#!/usr/bin/env python3
"""Build and check the current 1,025-element learning example on a real GPU."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (0x00000000, 0xFFFFFFFF, 0xAAAAAAAA, 0x55555555)
INJECTIONS = {0: 1, 512: 3, 1024: 1}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def check_output(stdout, injected):
    """Check values independently of the executable's own PASS/FAIL labels."""
    require(
        re.search(r"^gpu=.+ count=1025 bytes=4100 blocks=5 threads_per_block=256$",
                  stdout, re.MULTILINE),
        "unexpected array or launch dimensions",
    )
    headers = list(re.finditer(r"^pattern=([0-9a-f]{8})$", stdout, re.MULTILINE))
    require([int(h[1], 16) for h in headers] == list(PATTERNS),
            "missing, duplicate, or unexpected patterns")

    for position, header in enumerate(headers):
        pattern = PATTERNS[position]
        end = headers[position + 1].start() if position + 1 < len(headers) else len(stdout)
        lines = stdout[header.end():end].strip().splitlines()
        masks = INJECTIONS if injected and position == 0 else {}
        expected_records = [
            f"index={idx} offset_bytes={idx * 4} expected={pattern:08x} "
            f"actual={pattern ^ mask:08x} xor_mask={mask:08x}"
            for idx, mask in masks.items()
        ]
        # GPU scheduling may change record order. Exact list comparison after
        # sorting also rejects duplicated or missing records.
        gpu_records = [line.removeprefix("gpu_record ")
                       for line in lines if line.startswith("gpu_record ")]
        cpu_records = [line for line in lines if line.startswith("index=")]
        label = f"pattern={pattern:08x}"
        require(sorted(gpu_records) == sorted(expected_records),
                f"{label}: GPU record contents differ")
        require(sorted(cpu_records) == sorted(expected_records),
                f"{label}: CPU record contents differ")
        errors = len(masks)
        summary = (f"gpu_summary error_count={errors} recorded_count={errors} "
                   "truncated=false")
        require([line for line in lines if line.startswith("gpu_summary ")] == [summary],
                f"{label}: wrong counts or truncation flag")
        require([line for line in lines if line.startswith("reference_check=")]
                == ["reference_check=PASS"], f"{label}: reference check failed")
        first = pattern ^ masks.get(0, 0)
        last = pattern ^ masks.get(1024, 0)
        status = "FAIL" if errors else "PASS"
        result = (f"first={first:08x} last={last:08x} cpu_mismatches={errors} "
                  f"gpu_mismatches={errors} status={status}")
        require([line for line in lines if line.startswith("first=")] == [result],
                f"{label}: wrong final values or status")
        allowed = {summary, "reference_check=PASS", result, *expected_records,
                   *("gpu_record " + record for record in expected_records)}
        require(all(not line.strip() or line in allowed for line in lines),
                f"{label}: unexpected output")


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    log_dir = ROOT / "results" / f"{stamp}-regression"
    log_dir.mkdir(parents=True)
    source = ROOT / "examples" / "first_kernel.cu"
    binary = ROOT / "build" / "first_kernel"
    binary.parent.mkdir(exist_ok=True)
    source_bytes = source.read_bytes()
    (log_dir / "first_kernel.cu").write_bytes(source_bytes)
    shutil.copyfile(__file__, log_dir / "test_first_kernel.py")
    report = {
        "started_utc": stamp,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "scope": "count=1025, max_records=3, four fixed patterns",
        "runs": [],
    }

    def run(name, command, expected_exit):
        entry = {"name": name, "command": command, "expected_exit": expected_exit}
        report["runs"].append(entry)
        try:
            completed = subprocess.run(command, cwd=ROOT, text=True,
                                       capture_output=True, timeout=60)
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
        require(completed.returncode == expected_exit,
                f"{name}: expected exit {expected_exit}, got {completed.returncode}")
        return completed

    try:
        nvcc = shutil.which("nvcc")
        require(nvcc is not None, "nvcc not found; run: source cuda-env.sh")
        run("build", [nvcc, "-std=c++17", "-lineinfo", str(source), "-o", str(binary)], 0)
        report["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        print("build: PASS", flush=True)
        for name, args, expected_exit in (
            ("normal", [], 0),
            ("injected", ["--inject"], 1),
            ("invalid_option", ["--invalid-option"], 2),
        ):
            completed = run(name, [str(binary), *args], expected_exit)
            if name == "invalid_option":
                require(not completed.stdout.strip(), "invalid option: unexpected stdout")
                require(completed.stderr.strip() == f"Usage: {binary} [--inject]",
                        "invalid option: missing or unexpected usage message")
            else:
                require(not completed.stderr.strip(), f"{name}: unexpected stderr")
                check_output(completed.stdout, injected=name == "injected")
            report["runs"][-1]["checks_passed"] = True
            print(f"{name}: PASS (program_exit={completed.returncode})", flush=True)
        report["status"] = "PASS"
        print("tests=3 passed=3 status=PASS")
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
