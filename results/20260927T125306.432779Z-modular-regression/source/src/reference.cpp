#include "gmv/reference.hpp"

#include <algorithm>

namespace gmv {

std::uint32_t reference_word(std::size_t index, std::uint32_t value, PatternMode mode) {
    if (mode == PatternMode::constant) return value;
    std::uint32_t word = static_cast<std::uint32_t>(index) ^ value;
    if (mode == PatternMode::index) return word;
    // All operations wrap modulo 2^32. A reproducible permutation, not a PRNG
    // quality claim or a cryptographic generator.
    word ^= word >> 16;
    word *= 0x7feb352du;
    word ^= word >> 15;
    word *= 0x846ca68bu;
    return word ^ (word >> 16);
}

ReferenceResult check_reference(
    const std::vector<std::uint32_t>& data,
    std::uint32_t pattern,
    std::size_t gpu_mismatch_count,
    const std::vector<ErrorRecord>& gpu_records,
    std::size_t max_records,
    PatternMode mode) {
    ReferenceResult result;

    for (std::size_t i = 0; i < data.size(); ++i) {
        const auto expected = reference_word(i, pattern, mode);
        if (data[i] != expected) {
            ++result.mismatch_count;
            if (result.cpu_records.size() < max_records) {
                result.cpu_records.push_back({i, expected, data[i]});
            }
        }
    }

    if (gpu_mismatch_count != result.mismatch_count) {
        result.errors.push_back(ReferenceError::mismatch_count);
    }
    if (gpu_records.size() != std::min(result.mismatch_count, max_records)) {
        result.errors.push_back(ReferenceError::record_count);
    }

    std::vector<bool> seen(data.size(), false);
    for (const auto& record : gpu_records) {
        if (record.index >= data.size()) {
            result.errors.push_back(ReferenceError::index_out_of_range);
            continue;  // Never index the host buffer before checking the boundary.
        }
        if (seen[record.index]) {
            result.errors.push_back(ReferenceError::duplicate_index);
        }
        seen[record.index] = true;

        const auto expected = reference_word(record.index, pattern, mode);
        if (record.expected != expected) {
            result.errors.push_back(ReferenceError::wrong_expected);
        }
        if (record.actual != data[record.index]) {
            result.errors.push_back(ReferenceError::wrong_actual);
        }
        if (data[record.index] == expected) {
            result.errors.push_back(ReferenceError::not_an_error);
        }
    }
    return result;
}

}  // namespace gmv
