#include "cuda_support.hpp"
#include "gmv/report.hpp"

#include <algorithm>
#include <array>
#include <cstdio>
#include <limits>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

// Faults are controlled return values, NOT hardware faults or a real OOM.
// Successful allocations, kernels, synchronization, and frees still use CUDA.
class ObservedRuntime : public gmv::detail::CudaRuntime {
public:
    unsigned int fail_allocation_at = 0;
    unsigned int fail_sync_at = 0;
    unsigned int fail_release_at = 0;
    unsigned int allocations = 0;
    unsigned int release_attempts = 0;
    unsigned int released = 0;
    unsigned int allocation_attempts = 0;
    unsigned int sync_attempts = 0;
    bool invalid_release = false;
    std::array<void*, 3> live{};

    cudaError_t allocate(void** pointer, std::size_t bytes) override {
        ++allocation_attempts;
        if (allocation_attempts == fail_allocation_at) return cudaErrorMemoryAllocation;
        const auto slot = std::find(live.begin(), live.end(), nullptr);
        if (slot == live.end()) return cudaErrorMemoryAllocation;
        const auto code = CudaRuntime::allocate(pointer, bytes);
        if (code == cudaSuccess) {
            *slot = *pointer;
            ++allocations;
        }
        return code;
    }

    cudaError_t release(void* pointer) noexcept override {
        ++release_attempts;
        const auto slot = std::find(live.begin(), live.end(), pointer);
        if (!pointer || slot == live.end()) {
            invalid_release = true;
            return cudaErrorInvalidValue;
        }
        const auto code = CudaRuntime::release(pointer);
        if (code != cudaSuccess) return code;
        *slot = nullptr;
        ++released;
        // Free for real before simulating a failure, so this test cannot leak VRAM.
        return release_attempts == fail_release_at ? cudaErrorUnknown : cudaSuccess;
    }

    cudaError_t synchronize() override {
        ++sync_attempts;
        const auto code = CudaRuntime::synchronize();
        if (code != cudaSuccess) return code;
        return sync_attempts == fail_sync_at ? cudaErrorUnknown : cudaSuccess;
    }

    void check_released(unsigned int expected) const {
        require(allocations == expected, "unexpected number of successful allocations");
        require(released == expected && release_attempts == expected,
                "an owned buffer was not released exactly once");
        require(!invalid_release, "unowned or duplicate release attempted");
        require(std::all_of(live.begin(), live.end(), [](void* p) { return p == nullptr; }),
                "an allocation is still tracked as live");
    }
};

void check_partial(const gmv::RunResult& result, gmv::Status first_status) {
    require(result.status == gmv::Status::error, "runtime failure did not take precedence");
    require(result.patterns.size() == 1 && result.patterns[0].pattern == 0
                && result.patterns[0].status == first_status, "completed evidence was lost");
    require(result.execution_error.has_value(), "execution error is missing");
    require(result.execution_error->operation == "cudaDeviceSynchronize"
                && result.execution_error->cuda_code == static_cast<int>(cudaErrorUnknown)
                && result.execution_error->pattern == 0xFFFFFFFFu, "failure context is wrong");
    std::ostringstream report;
    gmv::write_report(report, result);
    require(report.str().find("run_status=ERROR completed_patterns=1") != std::string::npos,
            "partial report did not identify incomplete execution");
    require(report.str().find("pattern=00000000\n") != std::string::npos,
            "completed pattern was not reported");
    require(report.str().find("\npattern=ffffffff\n") == std::string::npos,
            "unfinished pattern was reported as completed");
}

void run_case(const std::string& name) {
    ObservedRuntime runtime;
    if (name == "success") {
        const auto result = gmv::detail::run_validation_with_runtime({}, runtime);
        require(result.status == gmv::Status::pass && result.patterns.size() == 4,
                "normal execution failed");
        require(!result.execution_error && !result.cleanup_error, "unexpected runtime errors");
        runtime.check_released(3);
    } else if (name == "allocation_failure") {
        // Exercise both partial-construction cases: one or two buffers already owned.
        for (unsigned int failure_at : {2u, 3u}) {
            ObservedRuntime failed;
            failed.fail_allocation_at = failure_at;
            const auto result = gmv::detail::run_validation_with_runtime({}, failed);
            require(result.status == gmv::Status::error && result.patterns.empty(),
                    "allocation failure was not handled before pattern execution");
            require(result.execution_error && result.execution_error->operation == "cudaMalloc"
                    && result.execution_error->cuda_code == static_cast<int>(cudaErrorMemoryAllocation),
                    "allocation failure cause was lost");
            failed.check_released(failure_at - 1);
        }
    } else if (name == "sync_failure" || name == "prior_fail_then_error") {
        runtime.fail_sync_at = 2;
        const bool inject = name == "prior_fail_then_error";
        const auto result = gmv::detail::run_validation_with_runtime({inject}, runtime);
        check_partial(result, inject ? gmv::Status::fail : gmv::Status::pass);
        runtime.check_released(3);
        gmv::write_report(std::cout, result);
    } else if (name == "cleanup_failure" || name == "primary_and_cleanup_failure") {
        runtime.fail_release_at = 1;
        const bool primary = name == "primary_and_cleanup_failure";
        runtime.fail_sync_at = primary ? 2 : 0;
        const auto result = gmv::detail::run_validation_with_runtime({}, runtime);
        require(result.status == gmv::Status::error && result.cleanup_error
                && result.cleanup_error->operation == "cudaFree"
                && result.cleanup_failure_count == 1, "cleanup failure was silently ignored");
        if (primary) check_partial(result, gmv::Status::pass);
        else require(!result.execution_error && result.patterns.size() == 4,
                     "cleanup failure incorrectly discarded completed results");
        runtime.check_released(3);
        std::ostringstream report;
        gmv::write_report(report, result);
        require(report.str().find("cleanup_error operation=cudaFree") != std::string::npos,
                "cleanup error missing from output");
    } else if (name == "recovery") {
        runtime.fail_sync_at = 1;
        const auto failed = gmv::detail::run_validation_with_runtime({}, runtime);
        require(failed.status == gmv::Status::error, "controlled error did not occur");
        runtime.check_released(3);
        runtime.fail_sync_at = 0;
        const auto recovered = gmv::detail::run_validation_with_runtime({}, runtime);
        require(recovered.status == gmv::Status::pass && recovered.patterns.size() == 4,
                "controlled error affected the next call");
        runtime.check_released(6);
    } else if (name == "invalid_config") {
        gmv::ValidationConfig config;
        config.count = 0;
        const auto result = gmv::detail::run_validation_with_runtime(config, runtime);
        require(result.status == gmv::Status::error && result.execution_error
                && result.execution_error->operation == "config" && result.patterns.empty(),
                "direct invalid config reached execution");
        require(runtime.allocation_attempts == 0 && runtime.sync_attempts == 0, "invalid config touched GPU buffers");
        runtime.check_released(0);
    } else if (name == "repeat_failure") {
        gmv::ValidationConfig config{true};
        config.iterations = 3;
        runtime.fail_sync_at = 5;
        const auto result = gmv::detail::run_validation_with_runtime(config, runtime);
        require(result.status == gmv::Status::error && result.patterns.size() == 4,
                "prior iteration results were lost");
        require(result.patterns.front().status == gmv::Status::fail
                && result.patterns.back().status == gmv::Status::pass,
                "completed fail/pass evidence was lost");
        require(result.execution_error && result.execution_error->iteration == 2
                && result.execution_error->pattern == 0, "failing iteration was not identified");
        for (const auto& entry : result.patterns) require(entry.iteration == 1, "incomplete iteration was stored");
        std::ostringstream report;
        gmv::write_report(report, result);
        require(report.str().find("failed_iteration=2 failed_pattern=00000000") != std::string::npos,
                "report lost iteration context");
        runtime.check_released(3);
    } else if (name == "buffer_boundaries") {
        gmv::detail::CleanupState cleanup;
        {
            gmv::detail::DeviceBuffer<std::uint32_t> empty(runtime, cleanup, 0);
            require(empty.get() == nullptr, "empty buffer unexpectedly allocated");
        }
        bool rejected = false;
        try {
            gmv::detail::DeviceBuffer<std::uint32_t> oversized(
                runtime, cleanup, std::numeric_limits<std::size_t>::max());
        } catch (const std::length_error&) {
            rejected = true;
        }
        require(rejected && runtime.allocation_attempts == 0, "size overflow reached CUDA");
        runtime.check_released(0);
    } else {
        throw std::runtime_error("unknown test case");
    }
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc != 2) return 2;
    try {
        std::printf("test_case=%s fault_model=controlled_return_codes\n", argv[1]);
        run_case(argv[1]);
        std::printf("%s: PASS\n", argv[1]);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "%s: FAIL: %s\n", argv[1], error.what());
        return 1;
    }
}
