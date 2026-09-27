#include <ATen/ATen.h>
#include <c10/cuda/CUDAStream.h>
#include <c10/cuda/CUDAGuard.h>
#include <c10/cuda/CUDAException.h>
#include <torch/library.h>

namespace {

__global__ void relu_kernel(const float* input, float* output, int64_t count,
                            int64_t columns, int64_t stride0, int64_t stride1) {
    const int64_t index = static_cast<int64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (index >= count) return;
    // data_ptr already points at the view's storage_offset. Do not add it again.
    const auto offset = (index / columns) * stride0 + (index % columns) * stride1;
    const float value = input[offset];
    output[index] = value < 0.0f ? 0.0f : value;
}

at::Tensor relu_layout(const at::Tensor& input, int64_t mode) {
    TORCH_CHECK(input.is_cuda(), "expected CUDA input");
    TORCH_CHECK(input.scalar_type() == at::kFloat, "expected float32 input");
    TORCH_CHECK(input.dim() == 2, "expected a 2D tensor");
    TORCH_CHECK(!input.requires_grad(), "inference-only operator; autograd is not implemented");
    TORCH_CHECK(mode >= 0 && mode <= 2, "unknown layout strategy");
    TORCH_CHECK(input.stride(0) >= 0 && input.stride(1) >= 0, "negative strides unsupported");
    TORCH_CHECK(input.numel() <= (int64_t{1} << 30), "input exceeds this lab's size limit");
    const c10::cuda::CUDAGuard guard(input.device());
    auto output = at::empty(input.sizes(), input.options());
    if (input.numel() == 0) return output;

    // mode 0: use logical strides; mode 1: materialize a contiguous copy first.
    // mode 2: INTENTIONAL BUG, ignore strides. Restricted to in-storage reads so
    // the demo produces a logical mismatch rather than an out-of-bounds access.
    auto source = mode == 1 ? input.contiguous() : input;
    if (mode == 2) {
        const auto available = input.storage().nbytes() / sizeof(float) - input.storage_offset();
        TORCH_CHECK(static_cast<uint64_t>(input.numel()) <= available,
                    "flat-bug demo would read outside storage");
    }
    const auto stride0 = mode == 2 ? input.size(1) : source.stride(0);
    const auto stride1 = mode == 2 ? 1 : source.stride(1);
    const auto blocks = static_cast<unsigned>((input.numel() + 255) / 256);
    // Respect the caller's CURRENT stream, including a non-default stream.
    relu_kernel<<<blocks, 256, 0, c10::cuda::getCurrentCUDAStream(input.get_device())>>>(
        source.const_data_ptr<float>(), output.mutable_data_ptr<float>(), input.numel(),
        input.size(1), stride0, stride1);
    C10_CUDA_KERNEL_LAUNCH_CHECK();
    return output;
}

}  // namespace

TORCH_LIBRARY(gmv_layout, m) {
    m.def("relu(Tensor input, int mode=0) -> Tensor");
}
TORCH_LIBRARY_IMPL(gmv_layout, CUDA, m) {
    m.impl("relu", &relu_layout);
}
