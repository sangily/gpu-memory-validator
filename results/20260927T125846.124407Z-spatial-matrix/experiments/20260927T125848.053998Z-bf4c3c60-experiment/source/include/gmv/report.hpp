#pragma once

#include "gmv/validator.hpp"

#include <iosfwd>
#include <string_view>

namespace gmv {

void write_usage(std::ostream& out, std::string_view program);
void write_report(std::ostream& out, const RunResult& result);

}  // namespace gmv
