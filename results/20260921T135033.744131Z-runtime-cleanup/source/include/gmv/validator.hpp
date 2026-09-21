#pragma once

#include "gmv/reference.hpp"

#include <string>
#include <optional>

namespace gmv {

struct PatternResult {
    std::uint32_t pattern;
    std::uint32_t first;
    std::uint32_t last;
    unsigned int gpu_mismatches;
    bool truncated;
    std::vector<ErrorRecord> gpu_records;
    ReferenceResult reference;
    Status status;
};

struct ExecutionError {
    std::string operation;
    std::optional<int> cuda_code;
    std::string message;
    std::optional<std::uint32_t> pattern;
};

struct RunResult {
    std::string gpu_name = "unavailable";
    std::size_t count = 0;
    std::size_t bytes = 0;
    unsigned int blocks = 0;
    unsigned int threads_per_block = 0;
    std::vector<PatternResult> patterns;
    Status status = Status::pass;
    std::optional<ExecutionError> execution_error;
    std::optional<ExecutionError> cleanup_error;
    unsigned int cleanup_failure_count = 0;
};

// Owns CUDA execution. Returns host-side values, never device pointers.
RunResult run_validation(const ValidationConfig& config);

}  // namespace gmv
