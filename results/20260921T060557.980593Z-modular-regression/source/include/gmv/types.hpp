#pragma once

#include <cstddef>
#include <cstdint>

namespace gmv {

struct ValidationConfig {
    bool injection_enabled = false;
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

}  // namespace gmv
