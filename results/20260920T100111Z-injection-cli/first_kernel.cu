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

// Each GPU thread writes its index to one valid array element.
__global__ void write_indices(std::uint32_t* data, std::size_t count) {
    const std::size_t idx = static_cast<std::size_t>(blockIdx.x) * blockDim.x
                            + threadIdx.x;
    if (idx < count) {
        data[idx] = static_cast<std::uint32_t>(idx);
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

int main(int argc, char* argv[]) {
    const bool injection_enabled =
        argc == 2 && std::string_view(argv[1]) == "--inject";

    if (argc > 1 && !injection_enabled) {
        std::fprintf(stderr, "Usage: %s [--inject]\n", argv[0]);
        return 2;
    }

    constexpr std::size_t count = 1025;
    constexpr unsigned threads_per_block = 256;
    constexpr unsigned blocks = (count + threads_per_block - 1) / threads_per_block;
    constexpr std::size_t bytes = count * sizeof(std::uint32_t);

    cudaDeviceProp properties{};
    CUDA_CHECK(cudaGetDeviceProperties(&properties, 0));
    std::printf("gpu=%s count=%zu bytes=%zu blocks=%u threads_per_block=%u\n",
                properties.name, count, bytes, blocks, threads_per_block);

    std::uint32_t* device_data = nullptr;
    CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&device_data), bytes));
    write_indices<<<blocks, threads_per_block>>>(device_data, count);
    CUDA_CHECK(cudaGetLastError());

    if (injection_enabled) {
        inject_error<<<1, 1>>>(device_data, count, 512, 3u);
        CUDA_CHECK(cudaGetLastError());
    }

    CUDA_CHECK(cudaDeviceSynchronize());

    std::vector<std::uint32_t> host_data(count);
    CUDA_CHECK(cudaMemcpy(host_data.data(), device_data, bytes, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaFree(device_data));

    std::size_t mismatches = 0;
    for (std::size_t i = 0; i < count; ++i) {
    const auto expected = static_cast<std::uint32_t>(i);
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
    std::printf("first=%u last=%u mismatches=%zu status=%s\n", host_data.front(),
                host_data.back(), mismatches, mismatches == 0 ? "PASS" : "FAIL");
    return mismatches == 0 ? 0 : 1;
}
