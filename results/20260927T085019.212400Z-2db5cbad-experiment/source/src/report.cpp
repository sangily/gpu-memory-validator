#include "gmv/report.hpp"

#include <iomanip>
#include <sstream>

namespace gmv {
namespace {

const char* status_name(Status status) {
    switch (status) {
        case Status::pass: return "PASS";
        case Status::fail: return "FAIL";
        case Status::error: return "ERROR";
    }
    return "ERROR";
}

void write_record(std::ostream& out, const ErrorRecord& record) {
    out << "index=" << std::dec << record.index
        << " offset_bytes=" << record.index * sizeof(std::uint32_t)
        << std::hex << std::setfill('0')
        << " expected=" << std::setw(8) << record.expected
        << " actual=" << std::setw(8) << record.actual
        << " xor_mask=" << std::setw(8) << (record.expected ^ record.actual)
        << std::dec << '\n';
}

void write_error(std::ostream& out, const char* label, const ExecutionError& error) {
    out << label << " operation=" << error.operation;
    if (error.cuda_code) out << " cuda_code=" << *error.cuda_code;
    if (error.iteration) out << " failed_iteration=" << *error.iteration;
    if (error.pattern) {
        out << " failed_pattern=" << std::hex << std::setfill('0')
            << std::setw(8) << *error.pattern << std::dec;
    }
    out << " message=" << error.message << '\n';
}

}  // namespace

void write_usage(std::ostream& out, std::string_view program) {
    out << "Usage: " << program << " [--inject] [--count N] [--max-records K] [--iterations N]\n";
}

void write_report(std::ostream& out, const RunResult& result) {
    // Format into a local stream so hex/width settings cannot leak to the caller.
    std::ostringstream text;
    text << "gpu=" << result.gpu_name << " count=" << result.count
         << " bytes=" << result.bytes << " blocks=" << result.blocks
         << " threads_per_block=" << result.threads_per_block << "\n\n";
    text << "config max_records=" << result.max_records << " iterations=" << result.iterations
         << " injection=" << (result.injection_enabled ? "first_iteration_first_pattern" : "disabled") << '\n';

    for (const auto& entry : result.patterns) {
        text << "iteration=" << entry.iteration << '\n';
        text << "pattern=" << std::hex << std::setfill('0') << std::setw(8)
             << entry.pattern << std::dec << '\n';
        for (const auto& record : entry.gpu_records) {
            text << "gpu_record ";
            write_record(text, record);
        }
        text << "gpu_summary error_count=" << entry.gpu_mismatches
             << " recorded_count=" << entry.gpu_records.size()
             << " truncated=" << (entry.truncated ? "true" : "false") << '\n';
        for (const auto& record : entry.reference.cpu_records) {
            write_record(text, record);
        }
        text << "reference_check=" << (entry.reference.passed() ? "PASS" : "ERROR") << '\n'
             << std::hex << std::setfill('0')
             << "first=" << std::setw(8) << entry.first
             << " last=" << std::setw(8) << entry.last << std::dec
             << " cpu_mismatches=" << entry.reference.mismatch_count
             << " gpu_mismatches=" << entry.gpu_mismatches
             << " status=" << status_name(entry.status) << "\n\n";
    }
    text << "run_status=" << status_name(result.status) << " completed_patterns=" << result.patterns.size() << '\n';
    if (result.execution_error || result.cleanup_error) {
        if (result.execution_error) write_error(text, "execution_error", *result.execution_error);
        if (result.cleanup_error) {
            write_error(text, "cleanup_error", *result.cleanup_error);
            text << "cleanup_failure_count=" << result.cleanup_failure_count << '\n';
        }
    }
    out << text.str();
}

}  // namespace gmv
