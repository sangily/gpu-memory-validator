#include "gmv/cli.hpp"

namespace gmv {

std::optional<ValidationConfig> parse_cli(const std::vector<std::string_view>& args) {
    if (args.empty()) {
        return ValidationConfig{};
    }
    if (args.size() == 1 && args[0] == "--inject") {
        return ValidationConfig{true};
    }
    return std::nullopt;
}

}  // namespace gmv
