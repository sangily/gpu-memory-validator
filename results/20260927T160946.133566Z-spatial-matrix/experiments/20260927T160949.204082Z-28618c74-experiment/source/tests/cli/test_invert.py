#!/usr/bin/env python3
"""Verify read/write transitions, odd/even expectations and frozen failure snapshots."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import traceback

from test_validator import check_configured

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_experiment import snapshot, write_json


def check_invert(text, count, capacity, iterations, mode, injections, inject_pass, passes):
    expected_passes = [inject_pass if injections and i == 0 else passes for i in range(iterations * 2)]
    expected_phases = [number % 2 == 0 for number in expected_passes]
    observed = re.findall(r'^snapshot_inverted=(true|false)$', text, re.M)
    assert observed == [str(value).lower() for value in expected_phases]
    stripped = '\n'.join(line for line in text.splitlines()
                         if not line.startswith(('batch ', 'snapshot_inverted=')))
    check_configured(stripped, count, capacity, iterations, injections, (0x12345678, 0xdeadbeef), mode, expected_phases)
    assert 'access_mode=invert\n' in text
    assert f'load_config gpu_passes={passes} inject_pass={inject_pass} reference_mode=checkpoint_full' in text
    batches = re.findall(r'^batch gpu_passes_completed=(\d+) first_failed_pass=(\d+) ', text, re.M)
    assert batches == [(str(p), str(inject_pass if injections and i == 0 else 0)) for i, p in enumerate(expected_passes)]
    checkpoints = re.findall(r'^checkpoint iteration=(\d+) completed_patterns=(\d+) cumulative_status=(PASS|FAIL|ERROR)$', text, re.M)
    assert checkpoints == [(str(i // 2 + 1), str(i + 1), 'FAIL' if injections else 'PASS') for i in range(iterations * 2)]


def main():
    folder = ROOT / 'results' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-invert-regression')
    folder.mkdir()
    binary = ROOT / 'build/cuda/gpu_memory_validator'
    report = dict(status='RUNNING', checks=[], provenance=snapshot(folder, binary))
    try:
        for mode in ('constant', 'index', 'seeded'):
            for count, masks in ((1, {0: 1}), (2, {0: 1, 1: 3}), (257, {0: 1, 128: 3, 256: 1})):
                for capacity in (0, 2):
                    for passes in (5, 6):
                        for injection in (0, 1, 2, passes):
                            name = f'{mode}-{count}-k{capacity}-passes{passes}-inject{injection}'
                            command = [str(binary), '--access-mode', 'invert', '--pattern-mode', mode,
                                '--patterns', '12345678,deadbeef', '--count', str(count), '--iterations', '2',
                                '--max-records', str(capacity), '--gpu-passes', str(passes), '--inject-pass', str(injection or 1)]
                            if injection: command.append('--inject')
                            p = subprocess.run(command, capture_output=True, text=True, timeout=30)
                            (folder / (name + '.stdout.txt')).write_text(p.stdout)
                            (folder / (name + '.stderr.txt')).write_text(p.stderr)
                            assert p.returncode == int(bool(injection)), (name, p.stderr)
                            check_invert(p.stdout, count, capacity, 2, mode, masks if injection else {}, injection or 1, passes)
                            report['checks'].append(dict(case=name, status='PASS', command=command))
        for injection in (False, True):
            command = [sys.executable, str(ROOT / 'scripts/run_experiment.py'), '--profile',
                       str(ROOT / 'profiles/invert-smoke.json'), '--no-telemetry', '--output-root', str(folder / 'profiles')]
            if injection: command.append('--inject')
            p = subprocess.run(command, capture_output=True, text=True, timeout=30)
            assert p.returncode == int(injection), p.stderr + p.stdout
            run = Path(next(line[8:] for line in p.stdout.splitlines() if line.startswith('run_dir=')))
            data = json.loads((run / 'run.json').read_text())
            assert data['config']['access_mode'] == 'invert'
            check_invert((run / 'stdout.txt').read_text(), 257, 2, 2, 'seeded',
                         {0: 1, 128: 3, 256: 1} if injection else {}, 4, 6)
            report['checks'].append(dict(case='profile_injected' if injection else 'profile_normal',
                                        status='PASS', evidence=str(run.relative_to(folder))))
        report['status'] = 'PASS'
        print('checks=' + str(len(report['checks'])) + ' status=PASS')
        return 0
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        print(traceback.format_exc())
        return 1
    finally:
        write_json(folder / 'run.json', report)
        print('evidence=' + str(folder))


if __name__ == '__main__':
    raise SystemExit(main())
