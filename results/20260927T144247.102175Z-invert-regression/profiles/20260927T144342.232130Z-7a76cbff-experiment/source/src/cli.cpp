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
            : option == "--iterations" ? 8 : option == "--patterns" ? 16
            : option == "--pattern-mode" ? 32 : option == "--gpu-passes" ? 64
            : option == "--inject-pass" ? 128 : option == "--access-mode" ? 256 : 0;
        if (bit == 0 || (seen & bit)) return std::nullopt;
        seen |= bit;
        if (option == "--inject") {
            config.injection_enabled = true;
            continue;
        }
        if (++i == args.size()) return std::nullopt;
        const auto value = args[i];
        if (option == "--access-mode") {
            if (value == "read") config.access_mode = AccessMode::read;
            else if (value == "invert") config.access_mode = AccessMode::invert;
            else return std::nullopt;
            continue;
        }
        if (option == "--pattern-mode") {
            if (value == "constant") config.pattern_mode = PatternMode::constant;
            else if (value == "index") config.pattern_mode = PatternMode::index;
            else if (value == "seeded") config.pattern_mode = PatternMode::seeded;
            else return std::nullopt;
            continue;
        }
        if (option == "--patterns") {
            config.patterns.clear();
            std::size_t start = 0;
            do {
                const auto end = value.find(',', start);
                auto token = value.substr(start, end == std::string_view::npos ? end : end - start);
                if (token.substr(0, 2) == "0x" || token.substr(0, 2) == "0X") token.remove_prefix(2);
                if (token.empty() || token.size() > 8 || token.find_first_not_of("0123456789abcdefABCDEF") != std::string_view::npos)
                    return std::nullopt;
                std::uint32_t pattern = 0;
                const auto parsed = std::from_chars(token.data(), token.data() + token.size(), pattern, 16);
                if (parsed.ec != std::errc{} || parsed.ptr != token.data() + token.size()) return std::nullopt;
                config.patterns.push_back(pattern);
                if (config.patterns.size() > 64) return std::nullopt;
                if (end == std::string_view::npos) break;
                start = end + 1;
            } while (true);
            continue;
        }
        if (value.empty() || value.front() < '0' || value.front() > '9') return std::nullopt;
        std::size_t number = 0;
        const auto parsed = std::from_chars(value.data(), value.data() + value.size(), number);
        if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()) return std::nullopt;
        if (option == "--count") config.count = number;
        else {
            if (number > std::numeric_limits<unsigned int>::max()) return std::nullopt;
            if (option == "--max-records") config.max_records = static_cast<unsigned int>(number);
            else if (option == "--gpu-passes") config.gpu_passes = static_cast<unsigned int>(number);
            else if (option == "--inject-pass") config.inject_pass = static_cast<unsigned int>(number);
            else config.iterations = static_cast<unsigned int>(number);
        }
    }
    return valid_config(config) ? std::optional<ValidationConfig>{config} : std::nullopt;
}

}  // namespace gmv
