#include "gmv/cli.hpp"

#include <cstdio>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

void run_case(const std::string& name) {
    if (name == "defaults") {
        const auto config = gmv::parse_cli({});
        require(config && !config->injection_enabled, "default unexpectedly enables injection");
        require(config->count == 1025 && config->max_records == 3 && config->iterations == 1,
                "default settings changed");
    } else if (name == "inject") {
        const auto config = gmv::parse_cli({"--inject"});
        require(config && config->injection_enabled, "injection option was ignored");
    } else if (name == "unknown_option") {
        require(!gmv::parse_cli({"--invalid-option"}), "unknown option was accepted");
        require(!gmv::parse_cli({"--inject=1"}), "unsupported syntax was accepted");
    } else if (name == "extra_arguments") {
        require(!gmv::parse_cli({"--inject", "--inject"}), "duplicate option was accepted");
        require(!gmv::parse_cli({"--inject", "extra"}), "trailing argument was ignored");
        require(!gmv::parse_cli({"extra", "--inject"}), "leading argument was ignored");
    } else if (name == "configuration") {
        const auto config = gmv::parse_cli({"--iterations", "2", "--inject", "--max-records", "0", "--count", "1"});
        require(config && config->injection_enabled && config->count == 1
                && config->max_records == 0 && config->iterations == 2, "settings were not preserved");
        require(gmv::parse_cli({"--count", "1", "--max-records", "10"}).has_value(),
                "record capacity larger than count should be allowed");
    } else if (name == "invalid_numbers") {
        for (const auto option : {"--count", "--max-records", "--iterations"}) {
            for (const auto value : {"", "-1", "+1", " 1", "1 ", "1x", "1.5", "0x10", "18446744073709551616"}) {
                require(!gmv::parse_cli({option, value}), "malformed number was accepted");
            }
        }
    } else if (name == "limits") {
        require(!gmv::parse_cli({"--count", "0"}), "empty array accepted");
        require(!gmv::parse_cli({"--count", "4294967296"}), "atomic counter may overflow");
        require(!gmv::parse_cli({"--max-records", "4294967296"}), "record limit narrowed");
        require(!gmv::parse_cli({"--iterations", "0"}), "empty run accepted");
        require(!gmv::parse_cli({"--iterations", "10001"}), "iteration limit ignored");
        require(!gmv::parse_cli({"--iterations", "4294967297"}), "iteration value narrowed");
        require(gmv::parse_cli({"--iterations", "10000"}).has_value(), "upper iteration boundary rejected");
        if (sizeof(std::size_t) >= 8) {
            require(gmv::parse_cli({"--count", "4294967295", "--max-records", "4294967295"}).has_value(),
                    "representable counter boundary rejected");
        }
    } else if (name == "duplicate_options") {
        for (const auto option : {"--count", "--max-records", "--iterations"}) {
            require(!gmv::parse_cli({option, "1", option, "2"}), "duplicate setting accepted");
        }
    } else if (name == "missing_values") {
        for (const auto option : {"--count", "--max-records", "--iterations"}) {
            require(!gmv::parse_cli({option}), "missing value accepted");
            require(!gmv::parse_cli({option, "--inject"}), "next option used as a value");
        }
    } else if (name == "patterns_valid") {
        const auto config = gmv::parse_cli({"--patterns", "0x12345678,FFFFFFFF,12345678,0", "--inject"});
        require(config && config->patterns == std::vector<std::uint32_t>{0x12345678u, 0xffffffffu, 0x12345678u, 0u},
                "pattern values or ordered duplicates were lost");
        require(gmv::parse_cli({})->patterns == std::vector<std::uint32_t>{0u, 0xffffffffu, 0xaaaaaaaau, 0x55555555u},
                "default patterns changed");
    } else if (name == "patterns_invalid") {
        for (const auto value : {"", ",", "1,", ",1", "1,,2", "-1", "+1", " 1", "1 ", "0x", "100000000", "xyz"}) {
            require(!gmv::parse_cli({"--patterns", value}), "invalid pattern accepted");
        }
        require(!gmv::parse_cli({"--patterns"}), "missing patterns accepted");
        require(!gmv::parse_cli({"--patterns", "1", "--patterns", "2"}), "duplicate option accepted");
    } else if (name == "patterns_limit") {
        std::string values = "1";
        for (int i = 1; i < 64; ++i) values += ",1";
        require(gmv::parse_cli({"--patterns", values}).has_value(), "64 patterns rejected");
        values += ",1";
        require(!gmv::parse_cli({"--patterns", values}), "65 patterns accepted");
    } else if (name == "status_priority") {
        using S = gmv::Status;
        const S states[] = {S::pass, S::fail, S::error};
        const S expected[3][3] = {
            {S::pass, S::fail, S::error},
            {S::fail, S::fail, S::error},
            {S::error, S::error, S::error},
        };
        for (int previous = 0; previous < 3; ++previous) {
            for (int current = 0; current < 3; ++current) {
                require(gmv::combine_status(states[previous], states[current])
                            == expected[previous][current], "status precedence was violated");
            }
        }
    } else {
        throw std::runtime_error("unknown test case");
    }
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc != 2) return 2;
    try {
        run_case(argv[1]);
        std::printf("%s: PASS\n", argv[1]);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "%s: FAIL: %s\n", argv[1], error.what());
        return 1;
    }
}
