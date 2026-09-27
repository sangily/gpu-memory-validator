#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace gmv {

struct ValidationConfig {
    bool injection_enabled = false;
    std::size_t count = 1025;
    unsigned int max_records = 3;
    unsigned int iterations = 1;
    std::vector<std::uint32_t> patterns{0u, 0xFFFFFFFFu, 0xAAAAAAAAu, 0x55555555u};
};

enum class Status { pass = 0, fail = 1, error = 2 };

// A later successful pattern must not erase an earlier failure.
constexpr Status combine_status(Status previous, Status current) {
    return static_cast<int>(previous) >= static_cast<int>(current) ? previous : current;
}

struct ErrorRecord {
    std::size_t index;
    std::uint32_t expected;
    std::uint32_t actual;
};

// The atomic counter must represent every possible mismatching word. Bound
// iterations because this version retains completed results until reporting.
constexpr unsigned int max_iterations = 10000;
inline bool valid_config(const ValidationConfig& config) {
    return config.count > 0
        && config.count <= std::numeric_limits<unsigned int>::max()
        && config.count <= std::numeric_limits<std::size_t>::max() / sizeof(std::uint32_t)
        && config.max_records <= std::numeric_limits<std::size_t>::max() / sizeof(ErrorRecord)
        && config.iterations > 0 && config.iterations <= max_iterations
        && !config.patterns.empty() && config.patterns.size() <= 64;
}

}  // namespace gmv
