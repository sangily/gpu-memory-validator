#pragma once

#include <cstddef>
#include <cstdint>

namespace gmv {

struct ErrorRecord {
    std::size_t index;
    std::uint32_t expected;
    std::uint32_t actual;
};

}  // namespace gmv
