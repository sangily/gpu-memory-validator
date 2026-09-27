#!/usr/bin/env python3
"""Run a validator experiment and preserve its environment, logs and telemetry."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid

from experiment_config import resolve_config, persist_inputs

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("index", "uuid", "name", "driver_version", "temperature.gpu", "power.draw",
          "clocks.current.sm", "clocks.current.memory", "memory.total", "memory.used", "utilization.gpu", "utilization.memory")
METRICS = ("temperature_c", "power_w", "sm_clock_mhz", "memory_clock_mhz",
           "memory_total_mib", "memory_used_mib", "gpu_util_percent", "memory_util_percent")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def probe(command):
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=3)
        return {"status": "AVAILABLE" if completed.returncode == 0 else "ERROR",
                "command": command, "exit_code": completed.returncode,
                "stdout": completed.stdout, "stderr": completed.stderr}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"status": "UNAVAILABLE" if isinstance(error, FileNotFoundError) else "ERROR",
                "command": command, "error": str(error)}


def parse_telemetry(text):
    devices = []
    for row in csv.reader(text.splitlines()):
        if not row:
            continue
        if len(row) != len(FIELDS):
            raise ValueError("unexpected nvidia-smi column count")
        row = [value.strip() for value in row]
        device = dict(zip(FIELDS[:4], row[:4]))
        device["metrics"] = {}
        for name, raw in zip(METRICS, row[4:]):
            if raw.lower() in ("n/a", "[n/a]", "[not supported]", "not supported"):
                metric = {"status": "UNAVAILABLE", "value": None, "raw": raw}
            else:
                try:
                    value = float(raw)
                    if not math.isfinite(value):
                        raise ValueError("non-finite metric")
                    metric = {"status": "AVAILABLE", "value": value, "raw": raw}
                except ValueError:
                    metric = {"status": "ERROR", "value": None, "raw": raw}
            device["metrics"][name] = metric
        devices.append(device)
    if not devices:
        raise ValueError("nvidia-smi returned no devices")
    return devices


class Telemetry:
    """Polling lives outside the process deadline loop; failures stay in JSONL."""

    def __init__(self, path, origin, interval, executable):
        self.path, self.origin, self.interval = path, origin, interval
        self.executable = executable
        self.stop = threading.Event()
        self.summary = {"status": "RUNNING", "samples": 0, "query_errors": 0,
                        "metric_unavailable": 0, "metric_errors": 0,
                        "scope": "all GPUs reported by nvidia-smi; identify by UUID",
                        "interval_seconds": interval, "query_timeout_seconds": 3}
        self.thread = threading.Thread(target=self.collect, daemon=True)

    def collect(self):
        try:
            with self.path.open("w") as output:
                while not self.stop.is_set():
                    start = time.monotonic()
                    sample = {"timestamp_utc": utc_now(), "elapsed_seconds": start - self.origin}
                    if self.executable is None:
                        sample.update(status="UNAVAILABLE", reason="nvidia-smi not found")
                    else:
                        response = probe([self.executable, "--query-gpu=" + ",".join(FIELDS),
                                          "--format=csv,noheader,nounits"])
                        sample.update(response)
                        if response["status"] == "AVAILABLE":
                            try:
                                sample["devices"] = parse_telemetry(response["stdout"])
                                for device in sample["devices"]:
                                    for metric in device["metrics"].values():
                                        self.summary["metric_unavailable"] += metric["status"] == "UNAVAILABLE"
                                        self.summary["metric_errors"] += metric["status"] == "ERROR"
                            except ValueError as error:
                                sample.update(status="ERROR", error=str(error))
                    sample["query_duration_seconds"] = time.monotonic() - start
                    output.write(json.dumps(sample) + "\n")
                    output.flush()
                    self.summary["samples"] += 1
                    self.summary["query_errors"] += sample["status"] == "ERROR"
                    if sample["status"] == "UNAVAILABLE":
                        self.summary["status"] = "UNAVAILABLE"
                        break
                    self.stop.wait(max(0, self.interval - (time.monotonic() - start)))
            if self.summary["status"] == "RUNNING":
                if self.summary["samples"] == 0:
                    self.summary["status"] = "NOT_SAMPLED"
                elif self.summary["query_errors"] == self.summary["samples"]:
                    self.summary["status"] = "ERROR"
                else:
                    self.summary["status"] = "PARTIAL" if any(self.summary[k] for k in (
                        "query_errors", "metric_unavailable", "metric_errors")) else "AVAILABLE"
        except Exception as error:
            self.summary.update(status="ERROR", error=str(error))


def classify(exit_code, stdout, expected_patterns, stop_reason=None):
    summaries = re.findall(r"^run_status=(PASS|FAIL|ERROR) completed_patterns=(\d+)$", stdout, re.MULTILINE)
    result = {"status": "ERROR", "reason": stop_reason or "INVALID_RESULT",
              "reported_status": None, "reported_completed_patterns": None}
    if len(summaries) == 1:
        status, count = summaries[0]
        result.update(reported_status=status, reported_completed_patterns=int(count))
        if not stop_reason:
            if status == "ERROR" and exit_code == 2:
                result["reason"] = "VALIDATOR_ERROR"
            elif status in ("PASS", "FAIL") and exit_code == {"PASS": 0, "FAIL": 1}[status] and int(count) == expected_patterns:
                result.update(status=status, reason="COMPLETED")
    elif not stop_reason and exit_code is not None and exit_code < 0:
        result["reason"] = "SIGNAL"
    return result


def stop_child(child):
    if child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=2)


def snapshot(folder, binary):
    files = [ROOT / "CMakeLists.txt", ROOT / "cuda-env.sh"]
    for directory, suffixes in (("src", {".cpp", ".cu", ".hpp"}),
                                ("include", {".hpp"}), ("scripts", {".py"}),
                                ("tests", {".py", ".cpp"})):
        files += [p for p in (ROOT / directory).rglob("*") if p.suffix in suffixes]
    hashes = {}
    for path in sorted(files):
        relative = path.relative_to(ROOT)
        data = path.read_bytes()
        hashes[str(relative)] = hashlib.sha256(data).hexdigest()
        target = folder / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return {"git_head": probe(["git", "-C", str(ROOT), "rev-parse", "HEAD"]),
            "git_status": probe(["git", "-C", str(ROOT), "status", "--porcelain"]),
            "source_sha256": hashes,
            "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "binary_built_by_runner": False,
            "note": "Source snapshot and binary captured independently; rebuild before experiments."}


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def bounded_int(minimum, maximum):
    def parse(value):
        if not re.fullmatch(r"[0-9]+", value):
            raise argparse.ArgumentTypeError("expected decimal digits")
        number = int(value)
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"expected {minimum}..{maximum}")
        return number
    return parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "build/cuda/gpu_memory_validator")
    parser.add_argument("--output-root", type=Path, default=ROOT / "results")
    parser.add_argument("--count", type=bounded_int(1, 2**32 - 1), default=None)
    parser.add_argument("--max-records", type=bounded_int(0, 2**32 - 1), default=None)
    parser.add_argument("--iterations", type=bounded_int(1, 10000), default=None)
    parser.add_argument("--gpu-passes", type=bounded_int(1, 4096), default=None)
    parser.add_argument("--inject-pass", type=bounded_int(1, 4096), default=None)
    parser.add_argument("--inject", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--timeout-seconds", type=positive_float, default=None)
    parser.add_argument("--sample-interval", type=positive_float, default=None)
    parser.add_argument("--telemetry", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--pattern-file", type=Path)
    args = parser.parse_args()
    try:
        settings, inputs = resolve_config(args.profile, args.pattern_file, {
            "count": args.count, "max_records": args.max_records, "iterations": args.iterations,
            "gpu_passes": args.gpu_passes, "inject_pass": args.inject_pass,
            "injection_enabled": args.inject, "timeout_seconds": args.timeout_seconds,
            "sample_interval": args.sample_interval, "telemetry_enabled": args.telemetry})
    except (OSError, ValueError) as error:
        parser.error(str(error))
    for key in ("count", "max_records", "iterations", "gpu_passes", "inject_pass", "timeout_seconds", "sample_interval"):
        setattr(args, key, settings[key])
    args.inject = settings["injection_enabled"]
    args.no_telemetry = not settings["telemetry_enabled"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    folder = args.output_root.resolve() / (run_id + "-experiment")
    folder.mkdir(parents=True)
    for name in ("stdout.txt", "stderr.txt", "telemetry.jsonl"):
        (folder / name).touch()
    binary = args.binary.resolve()
    command = [str(binary), "--count", str(args.count), "--max-records", str(args.max_records),
               "--iterations", str(args.iterations), "--patterns", ",".join(settings["patterns"]), "--pattern-mode", settings["pattern_mode"],
               "--gpu-passes", str(args.gpu_passes), "--inject-pass", str(args.inject_pass)] + (["--inject"] if args.inject else [])
    report = {"schema_version": 1, "run_id": run_id, "started_utc": utc_now(), "status": "RUNNING",
              "command": command, "config": {"count": args.count, "allocation_bytes": args.count * 4,
              "max_records": args.max_records, "iterations": args.iterations,
              "injection_enabled": args.inject, "reference_mode": "full" if args.gpu_passes == 1 else "checkpoint_full",
              "gpu_passes": args.gpu_passes, "inject_pass": args.inject_pass,
              "timeout_seconds": args.timeout_seconds, "patterns": settings["patterns"],
              "pattern_mode": settings["pattern_mode"],
              "sample_interval": args.sample_interval, "telemetry_enabled": settings["telemetry_enabled"]},
              "environment": {"platform": platform.platform(), "python": platform.python_version(),
              "cuda_environment": {key: os.environ.get(key) for key in
                                   ("CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER", "CUDAToolkit_ROOT")}},
              "timing_scope": "child execution window including launch, polling, CUDA initialization, CPU checks and output; not GPU kernel timing",
              "raw_logs": {"stdout": "stdout.txt", "stderr": "stderr.txt", "telemetry": "telemetry.jsonl"}}
    report["input_files"] = persist_inputs(folder, settings, inputs)
    report["resolved_config"] = "resolved_config.json"
    write_json(folder / "run.json", report)
    print(f"run_dir={folder}", flush=True)
    interrupted = threading.Event()
    received = []

    def on_signal(signum, frame):
        received.append(signum)
        interrupted.set()

    previous = {sig: signal.signal(sig, on_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    child = None
    telemetry = None
    process_start = None
    process_end = None
    exit_code = None
    stop_reason = None
    try:
        report["provenance"] = snapshot(folder, binary)
        report["environment"]["nvcc"] = probe([shutil.which("nvcc") or "nvcc", "--version"])
        telemetry_origin = time.monotonic()
        report["telemetry_origin_utc"] = utc_now()
        if not args.no_telemetry:
            smi = shutil.which("nvidia-smi")
            if not smi and Path("/usr/lib/wsl/lib/nvidia-smi").exists():
                smi = "/usr/lib/wsl/lib/nvidia-smi"
            telemetry = Telemetry(folder / "telemetry.jsonl", telemetry_origin, args.sample_interval, smi)
            telemetry.thread.start()
        else:
            (folder / "telemetry.jsonl").touch()
        write_json(folder / "run.json", report)
        process_start = time.monotonic()
        report["process_started_utc"] = utc_now()
        with (folder / "stdout.txt").open("w") as stdout, (folder / "stderr.txt").open("w") as stderr:
            if interrupted.is_set():
                stop_reason = "INTERRUPTED"
            else:
                child = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr, start_new_session=True)
                while child.poll() is None:
                    if interrupted.is_set():
                        stop_reason = "INTERRUPTED"
                    elif time.monotonic() - process_start >= args.timeout_seconds:
                        stop_reason = "TIMEOUT"
                    if stop_reason:
                        stop_child(child)
                        break
                    interrupted.wait(0.02)
                exit_code = child.wait()
            process_end = time.monotonic()
        if interrupted.is_set():
            stop_reason = "INTERRUPTED"
        report.update(classify(exit_code, (folder / "stdout.txt").read_text(errors="replace"),
                               args.iterations * len(settings["patterns"]), stop_reason))
    except Exception as error:
        report.update(status="ERROR", reason="RUNNER_ERROR", error=str(error))
    finally:
        if child is not None:
            stop_child(child)
            exit_code = child.poll()
            process_end = process_end or time.monotonic()
        if telemetry:
            telemetry.stop.set()
            telemetry.thread.join(timeout=4)
            report["telemetry"] = dict(telemetry.summary)
            if telemetry.thread.is_alive():
                report["telemetry"].update(status="ERROR", error="sampler did not stop")
        else:
            report["telemetry"] = {"status": "DISABLED" if args.no_telemetry else "NOT_STARTED"}
        if interrupted.is_set():
            report.update(status="ERROR", reason="INTERRUPTED", signals=received)
        report.update(child_exit_code=exit_code, finished_utc=utc_now(),
                      process_elapsed_seconds=(process_end - process_start) if process_end and process_start else None)
        write_json(folder / "run.json", report)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    print(f"status={report['status']} reason={report.get('reason')} child_exit_code={exit_code}")
    return {"PASS": 0, "FAIL": 1}.get(report["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
