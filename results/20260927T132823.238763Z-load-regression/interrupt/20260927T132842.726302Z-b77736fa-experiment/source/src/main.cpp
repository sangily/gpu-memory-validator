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

    try {
        gmv::ProgressCallback progress;
        if (config->gpu_passes > 1) {
            progress = [](unsigned int iteration, std::size_t completed, gmv::Status status) {
                const char* name = status == gmv::Status::pass ? "PASS"
                    : status == gmv::Status::fail ? "FAIL" : "ERROR";
                std::cout << "checkpoint iteration=" << iteration << " completed_patterns=" << completed
                          << " cumulative_status=" << name << '\n' << std::flush;
            };
        }
        const auto result = gmv::run_validation(*config, progress);
        gmv::write_report(std::cout, result);
        return static_cast<int>(result.status);
    } catch (const std::exception& error) {
        std::cerr << "ERROR host: " << error.what() << '\n';
        return static_cast<int>(gmv::Status::error);
    }
}
