#!/usr/bin/env python3
"""Run real subprocess/GPU cases; expected application ERROR means test PASS."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments/pytorch'))
from device_lab import snapshot


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    folder = ROOT / 'results' / f'{stamp}-pytorch-validation'
    folder.mkdir()
    summary = {'status': 'RUNNING', 'cases': [], 'source_sha256': snapshot(folder)}
    try:
        unit = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/pytorch', '-v'],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
        (folder / 'unit.stdout.txt').write_text(unit.stdout)
        (folder / 'unit.stderr.txt').write_text(unit.stderr)
        summary['unit_exit_code'] = unit.returncode
        assert unit.returncode == 0, unit.stderr
        cases = [('device-mismatch', False), ('ignored-transfer', False), ('fixed', False), ('fixed', True)]
        for case, no_device in cases:
            name = 'no-device' if no_device else case
            output = folder / name
            env = os.environ.copy()
            if no_device:
                env['CUDA_VISIBLE_DEVICES'] = ''
            command = [sys.executable, 'experiments/pytorch/device_lab.py', '--case', case,
                       '--output-root', str(output)]
            completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
            output.mkdir(exist_ok=True)
            (output / 'stdout.txt').write_text(completed.stdout)
            (output / 'stderr.txt').write_text(completed.stderr)
            reports = list(output.glob('*/run.json'))
            assert len(reports) == 1, completed.stderr
            report = json.loads(reports[0].read_text())
            success = case == 'fixed' and not no_device
            assert completed.returncode == (0 if success else 2), completed.stderr
            assert report['status'] == ('PASS' if success else 'ERROR'), report
            if no_device:
                assert 'CUDA device unavailable' in report['error'], report
                assert 'comparison' not in report
            elif success:
                assert report['phase'] == 'completed'
                assert report['comparison']['elements'] == 1024
                assert report['comparison']['status'] == 'PASS'
                assert report['devices'] == {'model': 'cuda:0', 'original_input': 'cpu',
                                             'operation_input': 'cuda:0', 'output': 'cuda:0'}
            else:
                assert report['phase'] == 'forward', report
                assert report['error_type'] == 'RuntimeError'
                assert 'cpu' in report['error'].lower() and 'cuda' in report['error'].lower(), report
                assert report['devices']['model'] == 'cuda:0'
                assert report['devices']['operation_input'] == 'cpu'
                assert 'comparison' not in report
            summary['cases'].append({'name': name, 'test_status': 'PASS', 'program_status': report['status'],
                                     'exit_code': completed.returncode, 'command': command,
                                     'report': str(reports[0].relative_to(folder))})
            print(f'{name}: test=PASS program={report["status"]} exit_code={completed.returncode}')
        summary['status'] = 'PASS'
        return 0
    except Exception as error:
        summary.update(status='FAIL', error=str(error))
        print(str(error), file=sys.stderr)
        return 1
    finally:
        (folder / 'run.json').write_text(json.dumps(summary, indent=2) + '\n')
        print('evidence=' + str(folder))


if __name__ == '__main__':
    raise SystemExit(main())
