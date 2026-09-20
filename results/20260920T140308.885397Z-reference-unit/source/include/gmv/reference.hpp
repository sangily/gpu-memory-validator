#pragma once

#include "gmv/types.hpp"

#include <vector>

namespace gmv {

enum class ReferenceError {
    mismatch_count,
    record_count,
    index_out_of_range,
    duplicate_index,
    wrong_expected,
    wrong_actual,
    not_an_error,
};

struct ReferenceResult {
    std::size_t mismatch_count = 0;
    // CPU details are bounded too; mismatch_count still covers the whole buffer.
    std::vector<ErrorRecord> cpu_records;
    std::vector<ReferenceError> errors;

    bool passed() const { return errors.empty(); }
};

// Checks a host snapshot independently of CUDA. Input data and records are not mutated.
// With truncation, GPU records may be any unique subset of the actual errors.
ReferenceResult check_reference(
    const std::vector<std::uint32_t>& data,
    std::uint32_t pattern,
    std::size_t gpu_mismatch_count,
    const std::vector<ErrorRecord>& gpu_records,
    std::size_t max_records);

}  // namespace gmv
