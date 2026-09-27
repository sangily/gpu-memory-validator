#include "gmv/cli.hpp"
#include <charconv>

namespace gmv {

std::optional<ValidationConfig> parse_cli(const std::vector<std::string_view>& args) {
    ValidationConfig config;
    unsigned int seen = 0;
    for (std::size_t i = 0; i < args.size(); ++i) {
        const auto option = args[i];
        const unsigned int bit = option == "--inject" ? 1
            : option == "--count" ? 2 : option == "--max-records" ? 4
            : option == "--iterations" ? 8 : 0;
        if (bit == 0 || (seen & bit)) return std::nullopt;
        seen |= bit;
        if (option == "--inject") {
            config.injection_enabled = true;
            continue;
        }
        if (++i == args.size()) return std::nullopt;
        const auto value = args[i];
        if (value.empty() || value.front() < '0' || value.front() > '9') return std::nullopt;
        std::size_t number = 0;
        const auto parsed = std::from_chars(value.data(), value.data() + value.size(), number);
        if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()) return std::nullopt;
        if (option == "--count") config.count = number;
        else {
            if (number > std::numeric_limits<unsigned int>::max()) return std::nullopt;
            if (option == "--max-records") config.max_records = static_cast<unsigned int>(number);
            else config.iterations = static_cast<unsigned int>(number);
        }
    }
    return valid_config(config) ? std::optional<ValidationConfig>{config} : std::nullopt;
}

}  // namespace gmv
