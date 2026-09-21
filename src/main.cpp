#include "gmv/cli.hpp"
#include "gmv/report.hpp"
#include "gmv/validator.hpp"

#include <iostream>
#include <string_view>
#include <vector>

int main(int argc, char* argv[]) {
    const std::vector<std::string_view> args(argv + 1, argv + argc);
    const auto config = gmv::parse_cli(args);
    if (!config) {
        gmv::write_usage(std::cerr, argv[0]);
        return static_cast<int>(gmv::Status::error);
    }

    const auto result = gmv::run_validation(*config);
    gmv::write_report(std::cout, result);
    return static_cast<int>(result.status);
}
