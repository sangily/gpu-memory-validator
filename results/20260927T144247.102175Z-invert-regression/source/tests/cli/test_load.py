#!/usr/bin/env python3
"""GPU batch checks, first-failure preservation and interrupted-run evidence."""
from datetime import datetime, timezone
import json
import re
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from test_validator import check_configured

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_experiment import snapshot, write_json


def check_batch(text, count, capacity, iterations, mode, injections, inject_pass, passes):
    # Reuse the independent data/record oracle, removing ONLY timing/batch lines.
    stripped = '\n'.join(line for line in text.splitlines() if not line.startswith('batch '))
    check_configured(stripped, count, capacity, iterations, injections, (0x12345678, 0xdeadbeef), mode)
    assert f'load_config gpu_passes={passes} inject_pass={inject_pass} reference_mode=checkpoint_full' in text
    batch = re.findall(r'^batch gpu_passes_completed=(\d+) first_failed_pass=(\d+) gpu_phase_host_ms=(\S+) cpu_phase_host_ms=(\S+)$', text, re.M)
    assert len(batch) == iterations * 2
    for index, (completed, failed, gpu_ms, cpu_ms) in enumerate(batch):
        expected_failure = inject_pass if injections and index == 0 else 0
        assert int(failed) == expected_failure
        assert int(completed) == (expected_failure or passes)
        assert float(gpu_ms) >= 0 and float(cpu_ms) >= 0
    checkpoints = re.findall(r'^checkpoint iteration=(\d+) completed_patterns=(\d+) cumulative_status=(PASS|FAIL|ERROR)$', text, re.M)
    assert checkpoints == [(str(i // 2 + 1), str(i + 1), 'FAIL' if injections else 'PASS') for i in range(iterations * 2)]


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    folder = ROOT / 'results' / (stamp + '-load-regression')
    folder.mkdir()
    binary = ROOT / 'build/cuda/gpu_memory_validator'
    report = {'status': 'RUNNING', 'checks': [], 'provenance': snapshot(folder, binary)}
    try:
        for mode in ('constant', 'index', 'seeded'):
            for count in (1, 257):
                for capacity in (0, 2):
                    for injection in (0, 1, 4, 7):
                        name = f'{mode}-{count}-k{capacity}-inject{injection}'
                        options = ['--pattern-mode', mode, '--patterns', '12345678,deadbeef', '--count', str(count),
                                   '--max-records', str(capacity), '--iterations', '2', '--gpu-passes', '7',
                                   '--inject-pass', str(injection or 1)] + (['--inject'] if injection else [])
                        p = subprocess.run([str(binary), *options], capture_output=True, text=True, timeout=30)
                        (folder / (name + '.stdout.txt')).write_text(p.stdout)
                        (folder / (name + '.stderr.txt')).write_text(p.stderr)
                        assert p.returncode == int(bool(injection)), (name, p.stderr)
                        errors = ({0: 1} if count == 1 else {0: 1, 128: 3, 256: 1}) if injection else {}
                        check_batch(p.stdout, count, capacity, 2, mode, errors, injection or 1, 7)
                        report['checks'].append({'case': name, 'status': 'PASS', 'command': [str(binary), *options]})
        # Real runner/profile -> kernel path, including mid-batch injection.
        p = subprocess.run([sys.executable, str(ROOT / 'scripts/run_experiment.py'),
                            '--profile', str(ROOT / 'profiles/load-smoke.json'), '--inject', '--no-telemetry',
                            '--output-root', str(folder / 'experiments')], capture_output=True, text=True, timeout=30)
        assert p.returncode == 1, p.stdout + p.stderr
        run = Path(next(line[8:] for line in p.stdout.splitlines() if line.startswith('run_dir=')))
        result = json.loads((run / 'run.json').read_text())
        assert result['status'] == 'FAIL' and result['config']['reference_mode'] == 'checkpoint_full'
        check_batch((run / 'stdout.txt').read_text(), 257, 2, 2, 'seeded', {0: 1, 128: 3, 256: 1}, 4, 7)
        report['checks'].append({'case': 'profile_mid_batch_injection', 'status': 'PASS', 'evidence': str(run.relative_to(folder))})
        # Stop real GPU work after at least one CPU checkpoint; no completion claim.
        for stopping in ('timeout', 'interrupt'):
            target = folder / stopping
            command = [sys.executable, str(ROOT / 'scripts/run_experiment.py'), '--count', '262144',
                       '--iterations', '10000', '--gpu-passes', '64', '--no-telemetry',
                       '--timeout-seconds', '2' if stopping == 'timeout' else '30', '--output-root', str(target)]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                if stopping == 'interrupt':
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        logs = list(target.glob('*/stdout.txt'))
                        if logs and 'checkpoint ' in logs[0].read_text():
                            break
                        assert process.poll() is None, 'runner exited before checkpoint'
                        time.sleep(.02)
                    else:
                        raise AssertionError('no checkpoint before interruption')
                    process.send_signal(signal.SIGINT)
                stdout, stderr = process.communicate(timeout=15)
                assert process.returncode == 2, (stdout, stderr)
                run, = target.iterdir()
                result = json.loads((run / 'run.json').read_text())
                assert result['status'] == 'ERROR' and result['reason'] == ('TIMEOUT' if stopping == 'timeout' else 'INTERRUPTED')
                text = (run / 'stdout.txt').read_text()
                assert 'checkpoint ' in text and not re.search(r'^run_status=', text, re.M), text
                report['checks'].append({'case': stopping + '_keeps_checkpoint', 'status': 'PASS', 'evidence': str(run.relative_to(folder))})
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
                    process.wait(timeout=5)
        report['status'] = 'PASS'
        print(f'checks={len(report["checks"])} status=PASS')
        return 0
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        print(str(error), file=sys.stderr)
        return 1
    finally:
        write_json(folder / 'run.json', report)
        print('evidence=' + str(folder))


if __name__ == '__main__':
    raise SystemExit(main())
