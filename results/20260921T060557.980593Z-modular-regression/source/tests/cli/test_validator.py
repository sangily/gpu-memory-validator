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
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "baseline_checks", ROOT / "scripts" / "test_first_kernel.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


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

        for name, args, expected_exit in (
            ("normal", [], 0), ("injected", ["--inject"], 1),
            ("invalid_option", ["--invalid-option"], 2),
        ):
            command = [str(binary), *args]
            entry = {"name": name, "command": command, "expected_exit": expected_exit}
            report["runs"].append(entry)
            try:
                completed = subprocess.run(command, cwd=ROOT, capture_output=True,
                                           text=True, timeout=60)
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
            if name == "invalid_option":
                baseline.require(not completed.stdout.strip(), "unexpected stdout")
                baseline.require(completed.stderr.strip() == f"Usage: {binary} [--inject]",
                                 "unexpected usage message")
            else:
                baseline.require(not completed.stderr.strip(), "unexpected stderr")
                baseline.check_output(completed.stdout, injected=name == "injected")
            entry["checks_passed"] = True
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
