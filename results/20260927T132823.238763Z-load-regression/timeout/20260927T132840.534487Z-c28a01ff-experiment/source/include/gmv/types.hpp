#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace gmv {

enum class PatternMode { constant, index, seeded };

inline const char* pattern_mode_name(PatternMode mode) {
    switch (mode) {
        case PatternMode::constant: return "constant";
        case PatternMode::index: return "index";
        case PatternMode::seeded: return "seeded";
    }
    return "invalid";
}

struct ValidationConfig {
    bool injection_enabled = false;
    std::size_t count = 1025;
    unsigned int max_records = 3;
    unsigned int iterations = 1;
    std::vector<std::uint32_t> patterns{0u, 0xFFFFFFFFu, 0xAAAAAAAAu, 0x55555555u};
    PatternMode pattern_mode = PatternMode::constant;
    unsigned int gpu_passes = 1;
    unsigned int inject_pass = 1;
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
        && config.gpu_passes > 0 && config.gpu_passes <= 4096
        && config.inject_pass > 0 && config.inject_pass <= config.gpu_passes
        && !config.patterns.empty() && config.patterns.size() <= 64
        && (config.pattern_mode == PatternMode::constant || config.pattern_mode == PatternMode::index
            || config.pattern_mode == PatternMode::seeded);
}

}  // namespace gmv
