#pragma once

#include "gmv/types.hpp"

#include <optional>
#include <string_view>
#include <vector>

namespace gmv {

// Arguments exclude argv[0]. Invalid input produces no config and no GPU work.
std::optional<ValidationConfig> parse_cli(const std::vector<std::string_view>& args);

}  // namespace gmv
