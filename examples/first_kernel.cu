#include <cuda_runtime.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <string_view>

#define CUDA_CHECK(call)                                                      \
    do {                                                                      \
        const cudaError_t error = (call);                                      \
        if (error != cudaSuccess) {                                           \
            std::fprintf(stderr, "ERROR %s:%d %s: %s\n", __FILE__, __LINE__,    \
                         #call, cudaGetErrorString(error));                   \
            std::exit(2);                                                     \
        }                                                                     \
    } while (false)

struct ErrorRecord {
    std::size_t index;
    std::uint32_t expected;
    std::uint32_t actual;
};

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

int main(int argc, char* argv[]) {
    const bool injection_enabled =
        argc == 2 && std::string_view(argv[1]) == "--inject";

    if (argc > 1 && !injection_enabled) {
        std::fprintf(stderr, "Usage: %s [--inject]\n", argv[0]);
        return 2;
    }

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
    std::printf("gpu=%s count=%zu bytes=%zu blocks=%u threads_per_block=%u\n\n",
                properties.name, count, bytes, blocks, threads_per_block);

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

    bool all_passed = true;
    bool all_reference_ok = true;

    for (const auto pattern : patterns) {
        std::printf("pattern=%08x\n", pattern);

        CUDA_CHECK(cudaMemset(device_error_count, 0, sizeof(unsigned int)));

        fill_pattern<<<blocks, threads_per_block>>>(device_data, count, pattern);
        CUDA_CHECK(cudaGetLastError());

        if (injection_enabled && pattern == patterns[0]) {
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

        for (const auto& record : host_records) {
            std::printf(
                "gpu_record index=%zu offset_bytes=%zu "
                "expected=%08x actual=%08x xor_mask=%08x\n",
                record.index,
                record.index * sizeof(std::uint32_t),
                record.expected,
                record.actual,
                record.expected ^ record.actual
            );
        }

        std::printf(
            "gpu_summary error_count=%u recorded_count=%u truncated=%s\n",
            gpu_mismatches,
            recorded_count,
            gpu_mismatches > max_records ? "true" : "false"
        );
        
        std::vector<std::uint32_t> host_data(count);
        CUDA_CHECK(cudaMemcpy(host_data.data(), device_data, bytes, cudaMemcpyDeviceToHost));

        std::size_t mismatches = 0;
        for (std::size_t i = 0; i < count; ++i) {
            const auto expected = pattern;
            const auto actual = host_data[i];

            if (actual != expected) {
                ++mismatches;
                std::printf(
                    "index=%zu offset_bytes=%zu expected=%08x actual=%08x xor_mask=%08x\n",
                    i,
                    i * sizeof(std::uint32_t),
                    expected,
                    actual,
                    expected ^ actual
                );
            }
        }

        bool reference_ok = gpu_mismatches == mismatches;
        std::vector<bool> seen(count, false);

        for (const auto& record : host_records) {
            if (record.index >= count) {
                reference_ok = false;
                continue;
            }

            if (seen[record.index] ||
                record.expected != pattern ||
                record.actual != host_data[record.index] ||
                record.actual == record.expected) {
                reference_ok = false;
            }

            seen[record.index] = true;
        }

        std::printf(
            "reference_check=%s\n",
            reference_ok ? "PASS" : "ERROR"
        );

        all_reference_ok = all_reference_ok && reference_ok;

        const bool passed =
            reference_ok && mismatches == 0 && gpu_mismatches == 0;

        std::printf(
            "first=%08x last=%08x cpu_mismatches=%zu gpu_mismatches=%u status=%s\n\n",
            host_data.front(),
            host_data.back(),
            mismatches,
            gpu_mismatches,
            !reference_ok ? "ERROR" : (passed ? "PASS" : "FAIL")
        );
        
        all_passed = all_passed && passed;
    }

    CUDA_CHECK(cudaFree(device_error_count));
    CUDA_CHECK(cudaFree(device_data));
    CUDA_CHECK(cudaFree(device_records));

    if (!all_reference_ok) {
        return 2;
    }
    return all_passed ? 0 : 1;
}
