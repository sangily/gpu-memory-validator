#include <cuda_runtime.h>

#include "cuda_support.hpp"

#include <cstdint>
#include <vector>
#include <utility>

#define CUDA_CHECK(call) gmv::detail::check_cuda((call), #call)

namespace {

using gmv::ErrorRecord;

__global__ void fill_pattern(
    std::uint32_t* data,
    std::size_t count,
    std::uint32_t pattern
) {
    const std::size_t idx =
        static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;

    if (idx < count) {
        data[idx] = pattern;
    }
}

__global__ void inject_error(
    std::uint32_t* data,
    std::size_t count,
    std::size_t target,
    std::uint32_t mask
) {
    if (target < count) {
        data[target] ^= mask;
    }
}

__global__ void verify_pattern(
    const std::uint32_t* data,
    std::size_t count,
    std::uint32_t pattern,
    unsigned int* error_count,
    ErrorRecord* records,
    unsigned int max_records
) {
    const std::size_t idx =
        static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;

    if (idx >= count) {
        return;
    }

    const auto actual = data[idx];
    if (actual != pattern) {
        const unsigned int slot = atomicAdd(error_count, 1u);

        if (slot < max_records) {
            records[slot] = ErrorRecord{idx, pattern, actual};
        }
    }
}

}  // namespace

namespace gmv::detail {

RunResult run_validation_with_runtime(const ValidationConfig& config, CudaRuntime& runtime) {
    constexpr std::size_t count = 1025;
    constexpr std::uint32_t patterns[] = {
        0x00000000u,
        0xFFFFFFFFu,
        0xAAAAAAAAu,
        0x55555555u
    };
    constexpr unsigned threads_per_block = 256;
    constexpr unsigned blocks = (count + threads_per_block - 1) / threads_per_block;
    constexpr std::size_t bytes = count * sizeof(std::uint32_t);

    RunResult result;
    result.count = count;
    result.bytes = bytes;
    result.blocks = blocks;
    result.threads_per_block = threads_per_block;
    CleanupState cleanup;
    std::optional<std::uint32_t> active_pattern;

    try {
        cudaDeviceProp properties{};
        CUDA_CHECK(cudaGetDeviceProperties(&properties, 0));
        result.gpu_name = properties.name;

        DeviceBuffer<std::uint32_t> device_data(runtime, cleanup, count);
        DeviceBuffer<unsigned int> device_error_count(runtime, cleanup, 1);
        constexpr unsigned int max_records = 3;
        DeviceBuffer<ErrorRecord> device_records(runtime, cleanup, max_records);

        for (const auto pattern : patterns) {
            active_pattern = pattern;
            CUDA_CHECK(cudaMemset(device_error_count.get(), 0, sizeof(unsigned int)));

            fill_pattern<<<blocks, threads_per_block>>>(device_data.get(), count, pattern);
            CUDA_CHECK(cudaGetLastError());

            if (config.injection_enabled && pattern == patterns[0]) {
                inject_error<<<1, 1>>>(device_data.get(), count, 0, 1u);
                CUDA_CHECK(cudaGetLastError());

                inject_error<<<1, 1>>>(device_data.get(), count, 512, 3u);
                CUDA_CHECK(cudaGetLastError());

                inject_error<<<1, 1>>>(device_data.get(), count, count - 1, 1u);
                CUDA_CHECK(cudaGetLastError());
            }

            verify_pattern<<<blocks, threads_per_block>>>(
                device_data.get(), count, pattern, device_error_count.get(),
                device_records.get(), max_records
            );
            CUDA_CHECK(cudaGetLastError());
            check_cuda(runtime.synchronize(), "cudaDeviceSynchronize");

            unsigned int gpu_mismatches = 0;
            CUDA_CHECK(cudaMemcpy(
                &gpu_mismatches,
                device_error_count.get(),
                sizeof(unsigned int),
                cudaMemcpyDeviceToHost
            ));

            const unsigned int recorded_count =
                gpu_mismatches < max_records ? gpu_mismatches : max_records;

            std::vector<ErrorRecord> host_records(recorded_count);

            if (recorded_count > 0) {
                CUDA_CHECK(cudaMemcpy(
                    host_records.data(),
                    device_records.get(),
                    recorded_count * sizeof(ErrorRecord),
                    cudaMemcpyDeviceToHost
                ));
            }

            std::vector<std::uint32_t> host_data(count);
            CUDA_CHECK(cudaMemcpy(host_data.data(), device_data.get(), bytes, cudaMemcpyDeviceToHost));

            auto reference = check_reference(
                host_data, pattern, gpu_mismatches, host_records, max_records
            );
            const auto status = !reference.passed() ? Status::error
                : (reference.mismatch_count == 0 && gpu_mismatches == 0
                    ? Status::pass : Status::fail);
            result.status = combine_status(result.status, status);
            result.patterns.push_back(PatternResult{
                pattern, host_data.front(), host_data.back(), gpu_mismatches,
                gpu_mismatches > max_records, std::move(host_records),
                std::move(reference), status
            });
            active_pattern.reset();
        }
    } catch (const CudaError& error) {
        result.status = Status::error;
        result.execution_error = ExecutionError{
            error.operation(), static_cast<int>(error.code()), error.what(), active_pattern
        };
    } catch (const std::exception& error) {
        result.status = Status::error;
        result.execution_error = ExecutionError{"host", std::nullopt, error.what(), active_pattern};
    }

    // Destructors have run before this point, including during stack unwinding.
    // Cleanup failure is separate evidence; it must not replace the original error.
    if (cleanup.failures != 0) {
        result.status = Status::error;
        result.cleanup_failure_count = cleanup.failures;
        result.cleanup_error = ExecutionError{
            "cudaFree", static_cast<int>(cleanup.first_error),
            cudaGetErrorString(cleanup.first_error), std::nullopt
        };
    }
    return result;
}

}  // namespace gmv::detail

namespace gmv {

RunResult run_validation(const ValidationConfig& config) {
    detail::CudaRuntime runtime;
    return detail::run_validation_with_runtime(config, runtime);
}

}  // namespace gmv
