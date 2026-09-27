#pragma once

#include "gmv/reference.hpp"

#include <string>
#include <optional>
#include <functional>

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
    unsigned int iteration = 1;
    unsigned int gpu_passes_completed = 1;
    unsigned int first_failed_pass = 0;
    double gpu_phase_host_ms = 0;
    double cpu_phase_host_ms = 0;
};

struct ExecutionError {
    std::string operation;
    std::optional<int> cuda_code;
    std::string message;
    std::optional<std::uint32_t> pattern;
    std::optional<unsigned int> iteration;
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
    unsigned int iterations = 1;
    unsigned int max_records = 3;
    bool injection_enabled = false;
    std::vector<std::uint32_t> pattern_values;
    PatternMode pattern_mode = PatternMode::constant;
    unsigned int gpu_passes = 1;
    unsigned int inject_pass = 1;
};

using ProgressCallback = std::function<void(unsigned int, std::size_t, Status)>;
// Owns CUDA execution. Returns host-side values, never device pointers.
RunResult run_validation(const ValidationConfig& config, ProgressCallback progress = {});

}  // namespace gmv
