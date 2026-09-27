#!/usr/bin/env python3
"""128/256 MiB normal/injected read-write experiments with independent log checks."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import traceback

from test_invert import check_invert

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_experiment import write_json


def main():
    folder = ROOT / 'results' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-invert-matrix')
    folder.mkdir()
    report = dict(status='RUNNING', cases=[])
    try:
        for mib in (128, 256):
            count = mib * 1024 * 1024 // 4
            for inject in (False, True):
                command = [sys.executable, str(ROOT / 'scripts/run_experiment.py'),
                           '--profile', str(ROOT / 'profiles/invert-256mib.json'),
                           '--count', str(count), '--output-root', str(folder / 'experiments')]
                if inject: command.append('--inject')
                p = subprocess.run(command, capture_output=True, text=True, timeout=150)
                assert p.returncode == int(inject), p.stdout + p.stderr
                run = Path(next(line[8:] for line in p.stdout.splitlines() if line.startswith('run_dir=')))
                result = json.loads((run / 'run.json').read_text())
                assert result['status'] == ('FAIL' if inject else 'PASS') and result['reason'] == 'COMPLETED'
                check_invert((run / 'stdout.txt').read_text(), count, 3, 4, 'seeded',
                             {0: 1, count // 2: 3, count - 1: 1} if inject else {}, 16, 32)
                report['cases'].append(dict(mib=mib, inject=inject, evidence_check='PASS',
                    validator_status=result['status'], process_elapsed_seconds=result['process_elapsed_seconds'],
                    evidence=str(run.relative_to(folder))))
                print(f'mib={mib} inject={inject} evidence_check=PASS', flush=True)
        report['status'] = 'PASS'
        return 0
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        print(traceback.format_exc())
        return 1
    finally:
        write_json(folder / 'matrix.json', report)
        print('evidence=' + str(folder))


if __name__ == '__main__':
    raise SystemExit(main())
