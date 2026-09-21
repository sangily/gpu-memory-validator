#include <cuda_runtime.h>

#include "gmv/validator.hpp"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <utility>

#define CUDA_CHECK(call)                                                      \
    do {                                                                      \
        const cudaError_t error = (call);                                      \
        if (error != cudaSuccess) {                                           \
            std::fprintf(stderr, "ERROR %s:%d %s: %s\n", __FILE__, __LINE__,    \
                         #call, cudaGetErrorString(error));                   \
            std::exit(2);                                                     \
        }                                                                     \
    } while (false)

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

namespace gmv {

RunResult run_validation(const ValidationConfig& config) {
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

    cudaDeviceProp properties{};
    CUDA_CHECK(cudaGetDeviceProperties(&properties, 0));
    RunResult result{properties.name, count, bytes, blocks, threads_per_block, {}};

    std::uint32_t* device_data = nullptr;
    CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&device_data), bytes));

    unsigned int* device_error_count = nullptr;
    CUDA_CHECK(cudaMalloc(
        reinterpret_cast<void**>(&device_error_count),
        sizeof(unsigned int)
    ));

    constexpr unsigned int max_records = 3;

    ErrorRecord* device_records = nullptr;
    CUDA_CHECK(cudaMalloc(
        reinterpret_cast<void**>(&device_records),
        max_records * sizeof(ErrorRecord)
    ));

    for (const auto pattern : patterns) {
        CUDA_CHECK(cudaMemset(device_error_count, 0, sizeof(unsigned int)));

        fill_pattern<<<blocks, threads_per_block>>>(device_data, count, pattern);
        CUDA_CHECK(cudaGetLastError());

        if (config.injection_enabled && pattern == patterns[0]) {
            inject_error<<<1, 1>>>(device_data, count, 0, 1u);
            CUDA_CHECK(cudaGetLastError());

            inject_error<<<1, 1>>>(device_data, count, 512, 3u);
            CUDA_CHECK(cudaGetLastError());

            inject_error<<<1, 1>>>(device_data, count, count - 1, 1u);
            CUDA_CHECK(cudaGetLastError());
        }

        verify_pattern<<<blocks, threads_per_block>>>(
            device_data, count, pattern, device_error_count,
            device_records, max_records
        );
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaDeviceSynchronize());

        unsigned int gpu_mismatches = 0;
        CUDA_CHECK(cudaMemcpy(
            &gpu_mismatches,
            device_error_count,
            sizeof(unsigned int),
            cudaMemcpyDeviceToHost
        ));

        const unsigned int recorded_count =
            gpu_mismatches < max_records ? gpu_mismatches : max_records;

        std::vector<ErrorRecord> host_records(recorded_count);

        if (recorded_count > 0) {
            CUDA_CHECK(cudaMemcpy(
                host_records.data(),
                device_records,
                recorded_count * sizeof(ErrorRecord),
                cudaMemcpyDeviceToHost
            ));
        }

        std::vector<std::uint32_t> host_data(count);
        CUDA_CHECK(cudaMemcpy(host_data.data(), device_data, bytes, cudaMemcpyDeviceToHost));

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
    }

    CUDA_CHECK(cudaFree(device_error_count));
    CUDA_CHECK(cudaFree(device_data));
    CUDA_CHECK(cudaFree(device_records));

    return result;
}

}  // namespace gmv
