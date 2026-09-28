// Small intentional defects for comparing memory-access checks with value checks.
// Run bounds-bug ONLY under Compute Sanitizer with --destroy-on-device-error kernel.
#include <cuda_runtime.h>
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
void check(cudaError_t result, const char* operation) {
    if (result != cudaSuccess)
        throw std::runtime_error(std::string(operation) + ": " + cudaGetErrorName(result));
}

struct Buffer {
    int* data = nullptr;
    explicit Buffer(std::size_t count) {
        check(cudaMalloc(reinterpret_cast<void**>(&data), count * sizeof(int)), "cudaMalloc");
    }
    ~Buffer() { if (data) cudaFree(data); }
    Buffer(const Buffer&) = delete;
    Buffer& operator=(const Buffer&) = delete;
};

__global__ void copy_view(const int* input, int* output, int count,
                          int columns, int row_stride, int column_stride) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= count) return;
    output[i] = input[(i / columns) * row_stride + (i % columns) * column_stride];
}

__global__ void write_one_past_end(int* output, int count) {
    // INTENTIONAL DEFECT: corrupt outside the inspected logical output.
    // A separate kernel preserves the correct output produced by copy_view.
    output[count] = 12345;
}
}

int main(int argc, char** argv) {
    if (argc < 2 || argc > 3) {
        std::cerr << "Usage: sanitizer_lab normal|bounds-bug|stride-bug|stride-fixed [--intentional-fault]\n";
        return 2;
    }
    const std::string mode = argv[1];
    const bool bounds = mode == "bounds-bug";
    if ((mode != "normal" && !bounds && mode != "stride-bug" && mode != "stride-fixed") ||
        (bounds && (argc != 3 || std::string(argv[2]) != "--intentional-fault")) ||
        (!bounds && argc != 2)) {
        std::cerr << "Invalid case or missing intentional-fault acknowledgement\n";
        return 2;
    }
    try {
        constexpr int count = 12;
        const std::array<int, count> source{1,2,3,4,5,6,7,8,9,10,11,12};
        // Fixed independent golden vector for transpose([3,4]); no device address formula.
        const std::array<int, count> transposed{1,5,9,2,6,10,3,7,11,4,8,12};
        const bool transpose = mode == "stride-bug" || mode == "stride-fixed";
        const auto& expected = transpose ? transposed : source;
        std::array<int, count> actual{};
        Buffer input(count), output(count);
        check(cudaMemcpy(input.data, source.data(), sizeof(source), cudaMemcpyHostToDevice), "input copy");
        check(cudaMemset(output.data, 0, sizeof(actual)), "output initialization");
        const int columns = transpose ? 3 : 4;
        const int row_stride = mode == "stride-fixed" ? 1 : columns;
        const int column_stride = mode == "stride-fixed" ? 4 : 1;
        copy_view<<<1, 32>>>(input.data, output.data, count, columns, row_stride, column_stride);
        check(cudaGetLastError(), "copy_view launch");
        check(cudaDeviceSynchronize(), "copy_view completion");
        if (bounds) {
            write_one_past_end<<<1, 1>>>(output.data, count);
            check(cudaGetLastError(), "bounds-bug launch");
            check(cudaDeviceSynchronize(), "bounds-bug completion");
        }
        check(cudaMemcpy(actual.data(), output.data, sizeof(actual), cudaMemcpyDeviceToHost), "output copy");
        int mismatches = 0;
        for (int i = 0; i < count; ++i) {
            if (actual[i] != expected[i]) {
                ++mismatches;
                std::cout << "index=" << i << " expected=" << expected[i] << " actual=" << actual[i] << '\n';
            }
        }
        std::cout << "case=" << mode << " cpu_mismatches=" << mismatches
                  << " value_check=" << (mismatches ? "FAIL" : "PASS") << '\n';
        return mismatches ? 1 : 0;
    } catch (const std::exception& error) {
        std::cerr << "execution_status=ERROR " << error.what() << '\n';
        return 2;
    }
}
