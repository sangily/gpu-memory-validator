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
