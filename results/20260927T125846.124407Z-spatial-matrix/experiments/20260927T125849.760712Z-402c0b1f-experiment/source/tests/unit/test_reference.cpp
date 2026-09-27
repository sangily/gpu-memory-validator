#include "gmv/reference.hpp"

#include <algorithm>
#include <cstdio>
#include <limits>
#include <stdexcept>
#include <string>

namespace {

using gmv::ErrorRecord;
using gmv::ReferenceError;
using gmv::ReferenceResult;

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void rejects(const ReferenceResult& result, ReferenceError reason) {
    require(!result.passed(), "invalid GPU evidence was accepted");
    require(std::find(result.errors.begin(), result.errors.end(), reason)
                != result.errors.end(), "expected rejection reason was missing");
}

// Fixed expected values: tests do not use the production scan to create their oracle.
const std::vector<std::uint32_t> damaged = {1, 0, 3, 0, 1};
const std::vector<ErrorRecord> records = {{0, 0, 1}, {2, 0, 3}, {4, 0, 1}};

void run_case(const std::string& name) {
    if (name == "clean_patterns") {
        for (const auto pattern : {0u, 0xFFFFFFFFu, 0xAAAAAAAAu, 0x55555555u}) {
            const auto result = gmv::check_reference({pattern, pattern}, pattern, 0, {}, 3);
            require(result.passed() && result.mismatch_count == 0
                    && result.cpu_records.empty(), "clean pattern was rejected");
        }
    } else if (name == "unordered_errors") {
        const auto result = gmv::check_reference(damaged, 0, 3,
                                                 {records[2], records[0], records[1]}, 3);
        require(result.passed() && result.mismatch_count == 3,
                "word count or order-independent matching failed");
        require(result.cpu_records.size() == 3, "CPU details missing");
        for (std::size_t i = 0; i < records.size(); ++i) {
            require(result.cpu_records[i].index == records[i].index
                    && result.cpu_records[i].expected == records[i].expected
                    && result.cpu_records[i].actual == records[i].actual,
                    "CPU detail contents differ from the fixed oracle");
        }
    } else if (name == "truncated_subset") {
        const auto result = gmv::check_reference(damaged, 0, 3, {records[2], records[1]}, 2);
        require(result.passed() && result.mismatch_count == 3
                && result.cpu_records.size() == 2, "valid truncated subset was rejected");
    } else if (name == "count_only") {
        const auto result = gmv::check_reference(damaged, 0, 3, {}, 0);
        require(result.passed() && result.mismatch_count == 3
                && result.cpu_records.empty(), "zero record budget lost the total count");
    } else if (name == "single_element") {
        const auto result = gmv::check_reference({0xABu}, 0xAAu, 1, {{0, 0xAAu, 0xABu}}, 4);
        require(result.passed() && result.mismatch_count == 1,
                "single-element evidence was rejected");
    } else if (name == "wrong_count") {
        rejects(gmv::check_reference(damaged, 0, 2, records, 3), ReferenceError::mismatch_count);
    } else if (name == "wrong_actual") {
        auto bad = records;
        bad[0].actual = 7;
        rejects(gmv::check_reference(damaged, 0, 3, bad, 3), ReferenceError::wrong_actual);
    } else if (name == "wrong_expected") {
        auto bad = records;
        bad[0].expected = 7;
        rejects(gmv::check_reference(damaged, 0, 3, bad, 3), ReferenceError::wrong_expected);
    } else if (name == "duplicate_index") {
        rejects(gmv::check_reference(damaged, 0, 3, {records[0], records[0], records[2]}, 3),
                ReferenceError::duplicate_index);
    } else if (name == "out_of_range") {
        for (const auto index : {damaged.size(), std::numeric_limits<std::size_t>::max()}) {
            auto bad = records;
            bad[0].index = index;
            rejects(gmv::check_reference(damaged, 0, 3, bad, 3), ReferenceError::index_out_of_range);
        }
    } else if (name == "not_an_error") {
        rejects(gmv::check_reference(damaged, 0, 3, {{1, 0, 0}, records[1], records[2]}, 3),
                ReferenceError::not_an_error);
    } else if (name == "missing_record") {
        rejects(gmv::check_reference(damaged, 0, 3, {records[0], records[1]}, 3),
                ReferenceError::record_count);
    } else if (name == "excess_records") {
        rejects(gmv::check_reference(damaged, 0, 3, records, 2), ReferenceError::record_count);
    } else if (name == "count_only_with_record") {
        rejects(gmv::check_reference(damaged, 0, 3, {records[0]}, 0), ReferenceError::record_count);
    } else if (name == "reset_between_calls") {
        rejects(gmv::check_reference(damaged, 0, 0, {}, 3), ReferenceError::mismatch_count);
        const auto clean = gmv::check_reference({0, 0, 0}, 0, 0, {}, 3);
        require(clean.passed() && clean.mismatch_count == 0 && clean.cpu_records.empty(),
                "previous result leaked into a subsequent call");
    } else if (name == "spatial_golden_values") {
        const std::size_t indices[] = {0, 1, 2, 256, 0xffffffffu};
        const std::uint32_t expected[] = {0xf5e71c96u, 0x3f779f73u, 0xeda6b628u, 0xc06aea9du, 0x1819718au};
        for (unsigned i = 0; i < 5; ++i) {
            require(gmv::reference_word(indices[i], 0x12345678u, gmv::PatternMode::seeded) == expected[i],
                    "seeded arithmetic differs from fixed oracle");
            require(gmv::reference_word(indices[i], 0xffffffffu, gmv::PatternMode::index)
                        == (static_cast<std::uint32_t>(indices[i]) ^ 0xffffffffu), "index pattern differs");
        }
    } else if (name == "spatial_wrong_fill") {
        // A shared GPU fill/verify defect could accept an all-constant buffer.
        // The independent CPU check must reject its zero-error claim.
        rejects(gmv::check_reference({0, 0, 0}, 0, 0, {}, 3, gmv::PatternMode::index),
                ReferenceError::mismatch_count);
        rejects(gmv::check_reference({0xf5e71c96u, 0xf5e71c96u}, 0x12345678u, 0, {}, 3,
                                    gmv::PatternMode::seeded), ReferenceError::mismatch_count);
    } else if (name == "spatial_swapped_words") {
        const auto result = gmv::check_reference({0, 2, 1}, 0, 2,
            {{2, 2, 1}, {1, 1, 2}}, 3, gmv::PatternMode::index);
        require(result.passed() && result.mismatch_count == 2, "swapped index words not detected");
        const auto constant = gmv::check_reference({7, 7, 7}, 7, 0, {}, 3);
        require(constant.passed() && constant.mismatch_count == 0, "constant control failed");
        rejects(gmv::check_reference({0, 2, 1}, 0, 2,
            {{2, 0, 1}, {1, 0, 2}}, 3, gmv::PatternMode::index), ReferenceError::wrong_expected);
    } else {
        throw std::runtime_error("unknown test case: " + name);
    }
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::fprintf(stderr, "Usage: %s CASE_NAME\n", argv[0]);
        return 2;
    }
    try {
        run_case(argv[1]);
        std::printf("%s: PASS\n", argv[1]);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "%s: FAIL: %s\n", argv[1], error.what());
        return 1;
    }
}
