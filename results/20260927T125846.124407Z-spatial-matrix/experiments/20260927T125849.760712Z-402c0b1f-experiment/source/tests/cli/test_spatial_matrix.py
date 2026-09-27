#!/usr/bin/env python3
"""Run 128/256 MiB spatial patterns with normal and injected controls.

This checks correctness under repeated larger allocations, not saturated GPU
bandwidth or a long-duration hardware qualification.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from test_validator import check_configured

ROOT = Path(__file__).resolve().parents[2]


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    folder = ROOT / 'results' / (stamp + '-spatial-matrix')
    folder.mkdir()
    (folder / 'test_spatial_matrix.py').write_bytes(Path(__file__).read_bytes())
    report = {'status': 'RUNNING', 'runs': [], 'scope': 'full CPU reference; repeated correctness, not GPU saturation'}
    try:
        for mode, values in [('index', (0, 0xffffffff)), ('seeded', (0x12345678, 0xdeadbeef))]:
            for mib in (128, 256):
                count = mib * 1024 * 1024 // 4
                for inject in (False, True):
                    command = [sys.executable, str(ROOT / 'scripts/run_experiment.py'), '--output-root', str(folder / 'experiments'),
                               '--profile', str(ROOT / f'profiles/{mode}-128mib.json'), '--count', str(count),
                               '--iterations', '4', '--inject' if inject else '--no-inject']
                    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=150)
                    name = f'{mode}-{mib}mib-' + ('injected' if inject else 'normal')
                    (folder / f'{name}.stdout.txt').write_text(completed.stdout)
                    (folder / f'{name}.stderr.txt').write_text(completed.stderr)
                    assert completed.returncode == int(inject), (name, completed.stdout, completed.stderr)
                    run = Path(next(line[8:] for line in completed.stdout.splitlines() if line.startswith('run_dir=')))
                    result = json.loads((run / 'run.json').read_text())
                    check_configured((run / 'stdout.txt').read_text(), count, 3, 4,
                                     {0: 1, count // 2: 3, count - 1: 1} if inject else {}, values, mode)
                    assert result['reason'] == 'COMPLETED' and result['status'] == ('FAIL' if inject else 'PASS')
                    report['runs'].append({'case': name, 'experiment': str(run.relative_to(folder)),
                                           'checks': 'PASS', 'validator_status': result['status'],
                                           'seconds': result['process_elapsed_seconds'], 'config': result['config']})
                    print(name + ': PASS (validator=' + result['status'] + ')', flush=True)
        report['status'] = 'PASS'
        return 0
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        print(str(error), file=sys.stderr)
        return 1
    finally:
        (folder / 'matrix.json').write_text(json.dumps(report, indent=2) + '\n')
        print('evidence=' + str(folder))


if __name__ == '__main__':
    raise SystemExit(main())
