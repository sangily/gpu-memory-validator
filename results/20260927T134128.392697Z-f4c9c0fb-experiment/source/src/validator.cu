#include <cuda_runtime.h>

#include "cuda_support.hpp"

#include <cstdint>
#include <vector>
#include <utility>
#include <algorithm>
#include <array>
#include <chrono>

#define CUDA_CHECK(call) gmv::detail::check_cuda((call), #call)

namespace {

using gmv::ErrorRecord;

__device__ std::uint32_t device_word(std::size_t index, std::uint32_t value, gmv::PatternMode mode) {
    if (mode == gmv::PatternMode::constant) return value;
    std::uint32_t x = static_cast<std::uint32_t>(index) ^ value;
    if (mode == gmv::PatternMode::index) return x;
    x = (x ^ (x >> 16)) * 0x7feb352du;
    x = (x ^ (x >> 15)) * 0x846ca68bu;
    return x ^ (x >> 16);
}

__global__ void fill_pattern(
    std::uint32_t* data,
    std::size_t count,
    std::uint32_t pattern,
    gmv::PatternMode mode
) {
    const std::size_t idx =
        static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;

    if (idx < count) {
        data[idx] = device_word(idx, pattern, mode);
    }
}

__global__ void inject_error(
    std::uint32_t* data,
    std::size_t count,
    std::size_t target,
    std::uint32_t mask,
    const unsigned int* failed_pass
) {
    if (failed_pass && *failed_pass != 0) return;
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
    unsigned int max_records,
    gmv::PatternMode mode,
    const unsigned int* failed_pass
) {
    const std::size_t idx =
        static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;

    if (idx >= count) {
        return;
    }
    // Only the following latch kernel writes this flag, after ALL threads of
    // this verification have completed. Never gate on the live error counter.
    if (failed_pass && *failed_pass != 0) return;

    const auto actual = data[idx];
    const auto expected = device_word(idx, pattern, mode);
    if (actual != expected) {
        const unsigned int slot = atomicAdd(error_count, 1u);

        if (slot < max_records) {
            records[slot] = ErrorRecord{idx, expected, actual};
        }
    }
}

__global__ void latch_failure(const unsigned int* errors, unsigned int* failed_pass,
                              unsigned int pass) {
    if (*failed_pass == 0 && *errors != 0) *failed_pass = pass;
}

}  // namespace

namespace gmv::detail {

RunResult run_validation_with_runtime(const ValidationConfig& config, CudaRuntime& runtime,
                                     ProgressCallback progress) {
    const auto count = config.count;
    constexpr unsigned threads_per_block = 256;
    RunResult result;
    result.iterations = config.iterations;
    result.max_records = config.max_records;
    result.injection_enabled = config.injection_enabled;
    result.pattern_mode = config.pattern_mode;
    result.gpu_passes = config.gpu_passes;
    result.inject_pass = config.inject_pass;
    // Protect callers that bypass the CLI, before arithmetic or any GPU access.
    if (!valid_config(config)) {
        result.status = Status::error;
        result.execution_error = ExecutionError{"config", std::nullopt, "invalid validation settings", std::nullopt, std::nullopt};
        return result;
    }
    const unsigned blocks = static_cast<unsigned>((count - 1) / threads_per_block + 1);
    result.pattern_values = config.patterns;
    const std::size_t bytes = count * sizeof(std::uint32_t);
    result.count = count;
    result.bytes = bytes;
    result.blocks = blocks;
    result.threads_per_block = threads_per_block;
    CleanupState cleanup;
    std::optional<std::uint32_t> active_pattern;
    std::optional<unsigned int> active_iteration;

    try {
        cudaDeviceProp properties{};
        CUDA_CHECK(cudaGetDeviceProperties(&properties, 0));
        result.gpu_name = properties.name;

        DeviceBuffer<std::uint32_t> device_data(runtime, cleanup, count);
        DeviceBuffer<unsigned int> device_error_count(runtime, cleanup, 1);
        // More records than words cannot be produced; avoid allocating unused slots.
        const auto max_records = static_cast<unsigned int>(std::min<std::size_t>(config.max_records, count));
        DeviceBuffer<ErrorRecord> device_records(runtime, cleanup, max_records);
        DeviceBuffer<unsigned int> failed_pass(runtime, cleanup, config.gpu_passes > 1 ? 1 : 0);
        // Every successful copy below overwrites the full snapshot before CPU
        // validation. Reuse storage instead of allocating/zeroing it per pattern.
        std::vector<std::uint32_t> host_data(count);

        for (unsigned int iteration = 1; iteration <= config.iterations; ++iteration) {
            active_iteration = iteration;
            for (std::size_t pattern_index = 0; pattern_index < config.patterns.size(); ++pattern_index) {
                const auto pattern = config.patterns[pattern_index];
                active_pattern = pattern;
                const auto gpu_start = std::chrono::steady_clock::now();
                CUDA_CHECK(cudaMemset(device_error_count.get(), 0, sizeof(unsigned int)));
                if (failed_pass.get()) CUDA_CHECK(cudaMemset(failed_pass.get(), 0, sizeof(unsigned int)));

                fill_pattern<<<blocks, threads_per_block>>>(device_data.get(), count, pattern, config.pattern_mode);
                CUDA_CHECK(cudaGetLastError());

                for (unsigned int pass = 1; pass <= config.gpu_passes; ++pass) {
                    if (config.injection_enabled && iteration == 1 && pattern_index == 0 && pass == config.inject_pass) {
                        const std::array<std::size_t, 3> targets{0, count / 2, count - 1};
                        const std::array<std::uint32_t, 3> masks{1u, 3u, 1u};
                        for (std::size_t i = 0; i < targets.size(); ++i) {
                            // First occurrence wins: count=1 -> {0:1}, count=2 -> {0:1, 1:3}.
                            if (std::find(targets.begin(), targets.begin() + i, targets[i]) != targets.begin() + i) continue;
                            inject_error<<<1, 1>>>(device_data.get(), count, targets[i], masks[i], failed_pass.get());
                            CUDA_CHECK(cudaGetLastError());
                        }
                    }

                    verify_pattern<<<blocks, threads_per_block>>>(
                        device_data.get(), count, pattern, device_error_count.get(),
                        device_records.get(), max_records, config.pattern_mode, failed_pass.get()
                    );
                    CUDA_CHECK(cudaGetLastError());
                    if (failed_pass.get()) {
                        latch_failure<<<1, 1>>>(device_error_count.get(), failed_pass.get(), pass);
                        CUDA_CHECK(cudaGetLastError());
                    }
                }
                check_cuda(runtime.synchronize(), "cudaDeviceSynchronize");
                const auto cpu_start = std::chrono::steady_clock::now();
                unsigned int first_failed_pass = 0;
                if (failed_pass.get()) CUDA_CHECK(cudaMemcpy(&first_failed_pass, failed_pass.get(),
                    sizeof(unsigned int), cudaMemcpyDeviceToHost));

                unsigned int gpu_mismatches = 0;
                CUDA_CHECK(cudaMemcpy(
                    &gpu_mismatches,
                    device_error_count.get(),
                    sizeof(unsigned int),
                    cudaMemcpyDeviceToHost
                ));
                if (!failed_pass.get() && gpu_mismatches != 0) first_failed_pass = 1;
                if (first_failed_pass > config.gpu_passes
                    || ((first_failed_pass != 0) != (gpu_mismatches != 0))) {
                    throw std::runtime_error("inconsistent GPU failure latch");
                }

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

                CUDA_CHECK(cudaMemcpy(host_data.data(), device_data.get(), bytes, cudaMemcpyDeviceToHost));

                auto reference = check_reference(
                    host_data, pattern, gpu_mismatches, host_records, max_records, config.pattern_mode
                );
                const auto status = !reference.passed() ? Status::error
                    : (reference.mismatch_count == 0 && gpu_mismatches == 0
                        ? Status::pass : Status::fail);
                result.status = combine_status(result.status, status);
                result.patterns.push_back(PatternResult{
                    pattern, host_data.front(), host_data.back(), gpu_mismatches,
                    gpu_mismatches > max_records, std::move(host_records),
                    std::move(reference), status, iteration,
                    first_failed_pass ? first_failed_pass : config.gpu_passes, first_failed_pass,
                    std::chrono::duration<double, std::milli>(cpu_start - gpu_start).count(),
                    std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - cpu_start).count()
                });
                active_pattern.reset();
                if (progress) progress(iteration, result.patterns.size(), result.status);
            }
            active_iteration.reset();
        }
    } catch (const CudaError& error) {
        result.status = Status::error;
        result.execution_error = ExecutionError{
            error.operation(), static_cast<int>(error.code()), error.what(), active_pattern, active_iteration
        };
    } catch (const std::exception& error) {
        result.status = Status::error;
        result.execution_error = ExecutionError{"host", std::nullopt, error.what(), active_pattern, active_iteration};
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

RunResult run_validation(const ValidationConfig& config, ProgressCallback progress) {
    detail::CudaRuntime runtime;
    return detail::run_validation_with_runtime(config, runtime, std::move(progress));
}

}  // namespace gmv
