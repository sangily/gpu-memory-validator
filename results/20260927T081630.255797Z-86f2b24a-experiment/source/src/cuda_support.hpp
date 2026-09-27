#pragma once

// Internal CUDA implementation/test interface; not included by CPU-only modules.
#include "gmv/validator.hpp"

#include <cuda_runtime_api.h>
#include <limits>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>

namespace gmv::detail {

class CudaError : public std::runtime_error {
public:
    CudaError(cudaError_t code, std::string operation)
        : std::runtime_error(std::string(cudaGetErrorName(code)) + ": " + cudaGetErrorString(code)),
          code_(code), operation_(std::move(operation)) {}

    cudaError_t code() const noexcept { return code_; }
    const std::string& operation() const noexcept { return operation_; }

private:
    cudaError_t code_;
    std::string operation_;
};

inline void check_cuda(cudaError_t code, const char* operation) {
    if (code != cudaSuccess) throw CudaError(code, operation);
}

// Only resource operations and the completion boundary are replaceable in tests.
// Production uses these real CUDA calls; tests still run the actual GPU kernels.
class CudaRuntime {
public:
    virtual ~CudaRuntime() = default;
    virtual cudaError_t allocate(void** pointer, std::size_t bytes) {
        return cudaMalloc(pointer, bytes);
    }
    virtual cudaError_t release(void* pointer) noexcept { return cudaFree(pointer); }
    virtual cudaError_t synchronize() { return cudaDeviceSynchronize(); }
};

struct CleanupState {
    cudaError_t first_error = cudaSuccess;
    unsigned int failures = 0;

    void record(cudaError_t code) noexcept {
        if (code != cudaSuccess) {
            if (first_error == cudaSuccess) first_error = code;
            ++failures;
        }
    }
};

template <typename T>
class DeviceBuffer {
    static_assert(std::is_trivially_copyable_v<T>);
public:
    DeviceBuffer(CudaRuntime& runtime, CleanupState& cleanup, std::size_t count)
        : runtime_(runtime), cleanup_(cleanup) {
        if (count > std::numeric_limits<std::size_t>::max() / sizeof(T)) {
            throw std::length_error("DeviceBuffer byte size overflow");
        }
        if (count > 0) {
            void* pointer = nullptr;
            check_cuda(runtime_.allocate(&pointer, count * sizeof(T)), "cudaMalloc");
            pointer_ = static_cast<T*>(pointer);
        }
    }

    ~DeviceBuffer() noexcept {
        if (pointer_) cleanup_.record(runtime_.release(pointer_));
    }

    DeviceBuffer(const DeviceBuffer&) = delete;
    DeviceBuffer& operator=(const DeviceBuffer&) = delete;
    DeviceBuffer(DeviceBuffer&&) = delete;
    DeviceBuffer& operator=(DeviceBuffer&&) = delete;

    T* get() const noexcept { return pointer_; }

private:
    CudaRuntime& runtime_;
    CleanupState& cleanup_;
    T* pointer_ = nullptr;
};

RunResult run_validation_with_runtime(const ValidationConfig& config, CudaRuntime& runtime);

}  // namespace gmv::detail
