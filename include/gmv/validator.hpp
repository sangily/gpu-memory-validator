#pragma once

#include "gmv/reference.hpp"

#include <string>

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

struct RunResult {
    std::string gpu_name;
    std::size_t count;
    std::size_t bytes;
    unsigned int blocks;
    unsigned int threads_per_block;
    std::vector<PatternResult> patterns;
    Status status = Status::pass;
};

// Owns CUDA execution. Returns host-side values, never device pointers.
RunResult run_validation(const ValidationConfig& config);

}  // namespace gmv
