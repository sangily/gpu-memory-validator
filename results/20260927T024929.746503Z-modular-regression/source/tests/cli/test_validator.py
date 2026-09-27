#!/usr/bin/env python3
"""Check the modular executable against the original example's CLI contract.

Build it first with CMake. The shared output checker preserves the established
expectations, including order-independent GPU records and exit codes 0/1/2.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "baseline_checks", ROOT / "scripts" / "test_first_kernel.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def check_configured(stdout, count, capacity, iterations, injections):
    """Independent expected values, including any valid subset when K truncates."""
    require = baseline.require
    require(re.search(rf"^gpu=.+ count={count} bytes={count * 4} blocks={(count + 255) // 256} threads_per_block=256$",
                      stdout, re.MULTILINE), "wrong launch dimensions")
    injection_mode = "first_iteration_first_pattern" if injections else "disabled"
    require(f"config max_records={capacity} iterations={iterations} injection={injection_mode}" in stdout,
            "wrong configuration report")
    headers = list(re.finditer(r"^iteration=(\d+)\npattern=([0-9a-f]{8})$", stdout, re.MULTILINE))
    expected_order = [(i, p) for i in range(1, iterations + 1) for p in baseline.PATTERNS]
    require([(int(h[1]), int(h[2], 16)) for h in headers] == expected_order,
            "missing, duplicate, or out-of-order iteration/pattern")
    for position, header in enumerate(headers):
        iteration, pattern = expected_order[position]
        end = headers[position + 1].start() if position + 1 < len(headers) else len(stdout)
        lines = stdout[header.end():end].strip().splitlines()
        masks = injections if iteration == 1 and pattern == 0 else {}
        records = [f"index={index} offset_bytes={index * 4} expected={pattern:08x} "
                   f"actual={pattern ^ mask:08x} xor_mask={mask:08x}"
                   for index, mask in sorted(masks.items())]
        gpu = [line.removeprefix("gpu_record ") for line in lines if line.startswith("gpu_record ")]
        cpu = [line for line in lines if line.startswith("index=")]
        saved = min(len(masks), capacity)
        require(len(gpu) == saved and len(set(gpu)) == saved and set(gpu) <= set(records),
                "GPU records missing, duplicated, or invalid")
        require(cpu == records[:capacity], "wrong bounded CPU records")
        summary = (f"gpu_summary error_count={len(masks)} recorded_count={saved} "
                   f"truncated={str(len(masks) > capacity).lower()}")
        require([line for line in lines if line.startswith("gpu_summary ")] == [summary],
                "wrong count or truncation")
        require([line for line in lines if line.startswith("reference_check=")] == ["reference_check=PASS"],
                "reference mismatch")
        state = "FAIL" if masks else "PASS"
        last = pattern ^ masks.get(count - 1, 0)
        first = pattern ^ masks.get(0, 0)
        result = (f"first={first:08x} last={last:08x} cpu_mismatches={len(masks)} "
                  f"gpu_mismatches={len(masks)} status={state}")
        require([line for line in lines if line.startswith("first=")] == [result],
                "wrong values or per-pattern state")
        allowed = {summary, result, "reference_check=PASS", *cpu, *("gpu_record " + record for record in gpu)}
        if position == len(headers) - 1:
            allowed.add(f"run_status={'FAIL' if injections else 'PASS'} completed_patterns={iterations * 4}")
        require(all(not line.strip() or line in allowed for line in lines), "unexpected output")
    require([line for line in stdout.splitlines() if line.startswith("run_status=")]
            == [f"run_status={'FAIL' if injections else 'PASS'} completed_patterns={iterations * 4}"],
            "final status lost earlier failure")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path,
                        default=ROOT / "build" / "cuda" / "gpu_memory_validator")
    binary = parser.parse_args().binary.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    log_dir = ROOT / "results" / f"{stamp}-modular-regression"
    log_dir.mkdir(parents=True)
    report = {"started_utc": stamp, "runs": [], "source_sha256": {},
              "binary_built_by_runner": False}

    try:
        paths = [ROOT / "CMakeLists.txt", Path(__file__),
                 ROOT / "scripts" / "test_first_kernel.py"]
        paths += sorted((ROOT / "src").glob("*"))
        paths += sorted((ROOT / "include" / "gmv").glob("*"))
        paths += sorted((ROOT / "tests").rglob("*.cpp"))
        for path in paths:
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            data = path.read_bytes()
            snapshot = log_dir / "source" / relative
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(data)
            report["source_sha256"][str(relative)] = hashlib.sha256(data).hexdigest()
        report["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()

        cases = [
            ("normal", [], 0, None), ("injected", ["--inject"], 1, None),
            ("invalid_option", ["--invalid-option"], 2, None),
            ("no_visible_device", [], 2, None),
        ]
        # Explicit expected masks avoid using the executable's injection builder.
        for count, masks in (
            (1, {0: 1}), (2, {0: 1, 1: 3}), (3, {0: 1, 1: 3, 2: 1}),
            (255, {0: 1, 127: 3, 254: 1}), (256, {0: 1, 128: 3, 255: 1}),
            (257, {0: 1, 128: 3, 256: 1}),
            (1024, {0: 1, 512: 3, 1023: 1}), (1025, {0: 1, 512: 3, 1024: 1}),
        ):
            for inject in (False, True):
                args = ["--count", str(count), "--iterations", "2"] + (["--inject"] if inject else [])
                cases.append((f"count_{count}_{'injected' if inject else 'normal'}", args,
                              int(inject), (count, 3, 2, masks if inject else {})))
        for capacity in (0, 1, 2, 4):
            args = ["--inject", "--max-records", str(capacity), "--iterations", "3"]
            cases.append((f"capacity_{capacity}", args, 1,
                          (1025, capacity, 3, {0: 1, 512: 3, 1024: 1})))
        cases.append(("zero_count", ["--count", "0"], 2, None))
        cases.append(("numeric_overflow", ["--count", "18446744073709551616"], 2, None))
        for name, args, expected_exit, configured in cases:
            command = [str(binary), *args]
            entry = {"name": name, "command": command, "expected_exit": expected_exit}
            report["runs"].append(entry)
            env = os.environ.copy()
            if name == "no_visible_device":
                env["CUDA_VISIBLE_DEVICES"] = ""
                entry["environment_overrides"] = {"CUDA_VISIBLE_DEVICES": ""}
            try:
                completed = subprocess.run(command, cwd=ROOT, capture_output=True,
                                           text=True, timeout=60, env=env)
            except subprocess.TimeoutExpired as error:
                entry["error"] = "timeout after 60 seconds"
                for stream in ("stdout", "stderr"):
                    value = getattr(error, stream) or b""
                    if isinstance(value, bytes):
                        value = value.decode(errors="replace")
                    (log_dir / f"{name}.{stream}.txt").write_text(value)
                raise RuntimeError(f"{name}: timeout") from error
            entry["actual_exit"] = completed.returncode
            (log_dir / f"{name}.stdout.txt").write_text(completed.stdout)
            (log_dir / f"{name}.stderr.txt").write_text(completed.stderr)
            baseline.require(completed.returncode == expected_exit,
                             f"{name}: expected exit {expected_exit}, got {completed.returncode}")
            if name in ("invalid_option", "zero_count", "numeric_overflow"):
                baseline.require(not completed.stdout.strip(), "unexpected stdout")
                baseline.require(completed.stderr.strip() == f"Usage: {binary} [--inject] [--count N] [--max-records K] [--iterations N]",
                                 "unexpected usage message")
            elif name == "no_visible_device":
                baseline.require(not completed.stderr.strip(), "unexpected stderr")
                baseline.require("run_status=ERROR completed_patterns=0" in completed.stdout,
                                 "device error was not reported as an incomplete run")
                baseline.require("execution_error operation=cudaGetDeviceProperties" in completed.stdout
                                 and "cuda_code=" in completed.stdout,
                                 "CUDA device failure cause was lost")
                baseline.require(not any(line.startswith("pattern=")
                                         for line in completed.stdout.splitlines()),
                                 "unexecuted patterns were reported")
            else:
                baseline.require(not completed.stderr.strip(), "unexpected stderr")
                if configured:
                    check_configured(completed.stdout, *configured)
                else:
                    check_configured(completed.stdout, 1025, 3, 1,
                                     baseline.INJECTIONS if name == "injected" else {})
                    # Preserve the frozen learning example's independent contract.
                    legacy = "\n".join(line for line in completed.stdout.splitlines()
                                       if not line.startswith(("iteration=", "config ", "run_status=")))
                    baseline.check_output(legacy, injected=name == "injected")
            entry["checks_passed"] = True
            print(f"{name}: PASS (program_exit={completed.returncode})", flush=True)
        report["status"] = "PASS"
        print(f"tests={len(cases)} passed={len(cases)} status=PASS")
        return 0
    except (AssertionError, OSError, RuntimeError) as error:
        report["status"] = "FAIL"
        report["error"] = str(error)
        print(f"test_suite: FAIL: {error}", file=sys.stderr)
        return 1
    finally:
        (log_dir / "run.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"logs={log_dir}")


if __name__ == "__main__":
    sys.exit(main())
