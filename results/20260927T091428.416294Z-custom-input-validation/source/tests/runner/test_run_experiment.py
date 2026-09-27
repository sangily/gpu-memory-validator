"""Runner failure contracts, using synthetic child processes rather than GPU faults."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/run_experiment.py'
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('runner', SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def test_metric_availability(self):
        device = runner.parse_telemetry('0, GPU-test, Test GPU, 1, N/A, 12.5, [Not Supported], 500, 1024, bad')[0]
        metrics = device['metrics']
        self.assertEqual(metrics['temperature_c']['status'], 'UNAVAILABLE')
        self.assertIsNone(metrics['temperature_c']['value'])
        self.assertEqual(metrics['power_w']['value'], 12.5)
        self.assertEqual(metrics['sm_clock_mhz']['status'], 'UNAVAILABLE')
        self.assertEqual(metrics['memory_used_mib']['status'], 'ERROR')
        with self.assertRaises(ValueError):
            runner.parse_telemetry('unexpected,columns')

    def test_exit_summary_contract(self):
        for status, code in [('PASS', 0), ('FAIL', 1), ('ERROR', 2)]:
            self.assertEqual(runner.classify(code, f'run_status={status} completed_patterns=4\n', 4)['status'], status)
        for code, text in [(0, ''), (0, 'run_status=FAIL completed_patterns=4\n'),
                           (0, 'run_status=PASS completed_patterns=3\n'),
                           (0, 'run_status=PASS completed_patterns=4\n' * 2), (-9, '')]:
            self.assertEqual(runner.classify(code, text, 4)['status'], 'ERROR')
        self.assertEqual(runner.classify(0, 'run_status=PASS completed_patterns=4\n', 4, 'TIMEOUT')['status'], 'ERROR')

    def test_telemetry_missing_command(self):
        with tempfile.TemporaryDirectory() as directory:
            telemetry = runner.Telemetry(Path(directory) / 'samples.jsonl', time.monotonic(), 1, None)
            telemetry.thread.start()
            telemetry.thread.join(2)
            self.assertFalse(telemetry.thread.is_alive())
            self.assertEqual(telemetry.summary['status'], 'UNAVAILABLE')
            sample = json.loads(telemetry.path.read_text())
            self.assertEqual(sample['status'], 'UNAVAILABLE')

    def test_telemetry_stopped_before_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            telemetry = runner.Telemetry(Path(directory) / 'samples.jsonl', time.monotonic(), 1, 'fake-smi')
            telemetry.stop.set()
            telemetry.collect()
            self.assertEqual(telemetry.summary['status'], 'NOT_SAMPLED')
            self.assertEqual(telemetry.summary['samples'], 0)

    def test_telemetry_query_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            telemetry = runner.Telemetry(Path(directory) / 'samples.jsonl', time.monotonic(), 1, 'fake-smi')
            def failed_probe(command):
                telemetry.stop.set()
                return {'status': 'ERROR', 'exit_code': 1, 'stdout': '', 'stderr': 'query failed'}
            with patch.object(runner, 'probe', side_effect=failed_probe):
                telemetry.collect()
            self.assertEqual(telemetry.summary['status'], 'ERROR')
            self.assertEqual(telemetry.summary['query_errors'], 1)
            self.assertEqual(json.loads(telemetry.path.read_text())['stderr'], 'query failed')

    def run_child(self, body, expected_exit, options=(), interrupt=False, missing=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'synthetic-validator'
            if not missing:
                binary.write_text(f'#!{sys.executable}\n' + body)
                binary.chmod(0o755)
            command = [sys.executable, str(SCRIPT), '--binary', str(binary), '--output-root', str(root / 'runs'),
                       '--no-telemetry', *options]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                if interrupt:
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        paths = list((root / 'runs').glob('*/stdout.txt'))
                        if paths and 'child-ready' in paths[0].read_text():
                            break
                        if process.poll() is not None:
                            self.fail('runner exited before interruption')
                        time.sleep(0.02)
                    else:
                        self.fail('child never started')
                    process.send_signal(signal.SIGINT)
                stdout, stderr = process.communicate(timeout=12)
                self.assertEqual(process.returncode, expected_exit, (stdout, stderr))
                folder, = (root / 'runs').iterdir()
                report = json.loads((folder / 'run.json').read_text())
                report['_stdout'] = (folder / 'stdout.txt').read_text()
                report['_stderr'] = (folder / 'stderr.txt').read_text()
                return report
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_success_and_fail_are_preserved(self):
        for state, code in [('PASS', 0), ('FAIL', 1)]:
            report = self.run_child(f'print("run_status={state} completed_patterns=4")\nraise SystemExit({code})\n', code)
            self.assertEqual(report['status'], state)
            self.assertEqual(report['child_exit_code'], code)
            self.assertEqual(report['reported_completed_patterns'], 4)
            self.assertIn('scripts/run_experiment.py', report['provenance']['source_sha256'])
            self.assertEqual(report['telemetry']['status'], 'DISABLED')

    def test_zero_exit_without_result_is_error(self):
        report = self.run_child('print("partial output")\n', 2)
        self.assertEqual(report['reason'], 'INVALID_RESULT')
        self.assertEqual(report['child_exit_code'], 0)
        self.assertIn('partial output', report['_stdout'])

    def test_timeout_preserves_partial_output(self):
        report = self.run_child('import time, signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint("child-ready", flush=True)\ntime.sleep(30)\n', 2,
                                ('--timeout-seconds', '0.3'))
        self.assertEqual(report['reason'], 'TIMEOUT')
        self.assertEqual(report['status'], 'ERROR')
        self.assertIn('child-ready', report['_stdout'])
        self.assertLess(report['process_elapsed_seconds'], 4)

    def test_interrupt_terminates_child_and_records_reason(self):
        report = self.run_child('import time\nprint("child-ready", flush=True)\ntime.sleep(30)\n', 2, interrupt=True)
        self.assertEqual(report['reason'], 'INTERRUPTED')
        self.assertEqual(report['status'], 'ERROR')
        self.assertEqual(report['signals'], [signal.SIGINT])
        self.assertIsNotNone(report['child_exit_code'])
        self.assertIn('child-ready', report['_stdout'])

    def test_missing_binary_is_recorded(self):
        report = self.run_child('', 2, missing=True)
        self.assertEqual(report['reason'], 'RUNNER_ERROR')
        self.assertIsNone(report['child_exit_code'])
        self.assertEqual(report['status'], 'ERROR')


if __name__ == '__main__':
    unittest.main()
