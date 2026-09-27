#include "gmv/reference.hpp"

#include <algorithm>

namespace gmv {

ReferenceResult check_reference(
    const std::vector<std::uint32_t>& data,
    std::uint32_t pattern,
    std::size_t gpu_mismatch_count,
    const std::vector<ErrorRecord>& gpu_records,
    std::size_t max_records) {
    ReferenceResult result;

    for (std::size_t i = 0; i < data.size(); ++i) {
        if (data[i] != pattern) {
            ++result.mismatch_count;
            if (result.cpu_records.size() < max_records) {
                result.cpu_records.push_back({i, pattern, data[i]});
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

        if (record.expected != pattern) {
            result.errors.push_back(ReferenceError::wrong_expected);
        }
        if (record.actual != data[record.index]) {
            result.errors.push_back(ReferenceError::wrong_actual);
        }
        if (data[record.index] == pattern) {
            result.errors.push_back(ReferenceError::not_an_error);
        }
    }
    return result;
}

}  // namespace gmv
