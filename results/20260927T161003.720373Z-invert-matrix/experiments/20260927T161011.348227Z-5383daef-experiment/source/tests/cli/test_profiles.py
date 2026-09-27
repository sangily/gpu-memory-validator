#!/usr/bin/env python3
"""Exercise saved input files through the runner, real GPU and independent oracle."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('checks', ROOT / 'tests/cli/test_validator.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    output = ROOT / 'results' / (stamp + '-profile-regression')
    output.mkdir()
    report = {'status': 'RUNNING', 'runs': []}
    (output / 'test_profiles.py').write_bytes(Path(__file__).read_bytes())
    try:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            duplicate = temp / 'duplicate.json'
            single = temp / 'single.json'
            invalid = temp / 'invalid.json'
            for path, values in [(duplicate, ['deadbeef', 'deadbeef']), (single, ['ffffffff']), (invalid, ['100000000'])]:
                path.write_text(json.dumps({'schema_version': 1, 'name': path.stem, 'values': values}))
            custom = (0x12345678, 0x87654321, 0x00ff00ff, 0xff00ff00)
            profile = str(ROOT / 'profiles/custom-smoke.json')
            cases = [
                ('preset', ['--profile', profile, '--inject'], 1, (257, 2, 2, {0: 1, 128: 3, 256: 1}, custom)),
                ('overrides', ['--profile', profile, '--no-inject', '--iterations', '3', '--max-records', '0', '--no-telemetry'],
                 0, (257, 0, 3, {}, custom)),
                ('duplicate', ['--profile', profile, '--pattern-file', str(duplicate), '--inject', '--count', '2', '--no-telemetry'],
                 1, (2, 2, 2, {0: 1, 1: 3}, (0xdeadbeef, 0xdeadbeef))),
                ('single', ['--pattern-file', str(single), '--count', '1', '--max-records', '0', '--iterations', '2', '--inject', '--no-telemetry'],
                 1, (1, 0, 2, {0: 1}, (0xffffffff,))),
                ('invalid', ['--pattern-file', str(invalid)], 2, None),
            ]
            for mode, values in [('index', (0, 0xffffffff)), ('seeded', (0x12345678, 0xdeadbeef))]:
                for inject in (False, True):
                    cases.append((mode + ('_injected' if inject else '_normal'),
                                  ['--profile', str(ROOT / f'profiles/{mode}-128mib.json'), '--count', '257',
                                   '--iterations', '2', '--no-telemetry', '--inject' if inject else '--no-inject'],
                                  int(inject), (257, 3, 2, {0: 1, 128: 3, 256: 1} if inject else {}, values, mode)))
            for name, options, expected_exit, expected in cases:
                command = [sys.executable, str(ROOT / 'scripts/run_experiment.py'), '--output-root', str(output / 'experiments'), *options]
                # Unrelated cwd verifies profile-relative references and absolute runner invocation.
                completed = subprocess.run(command, cwd=temp, capture_output=True, text=True, timeout=60)
                (output / f'{name}.stdout.txt').write_text(completed.stdout)
                (output / f'{name}.stderr.txt').write_text(completed.stderr)
                entry = {'name': name, 'command': command, 'expected_exit': expected_exit, 'actual_exit': completed.returncode}
                report['runs'].append(entry)
                assert completed.returncode == expected_exit, (name, completed.stdout, completed.stderr)
                if expected is None:
                    assert 'run_dir=' not in completed.stdout, 'invalid input started an experiment'
                    assert 'hexadecimal' in completed.stderr, 'missing useful validation error'
                else:
                    assert not completed.stderr.strip(), completed.stderr
                    folder = Path(next(line[8:] for line in completed.stdout.splitlines() if line.startswith('run_dir=')))
                    entry['experiment'] = str(folder.relative_to(ROOT))
                    result = json.loads((folder / 'run.json').read_text())
                    assert result['status'] == ('FAIL' if expected_exit == 1 else 'PASS')
                    assert result['reason'] == 'COMPLETED'
                    assert result['reported_completed_patterns'] == expected[2] * len(expected[4])
                    checks.check_configured((folder / 'stdout.txt').read_text(), *expected)
                    settings = json.loads((folder / 'resolved_config.json').read_text())
                    assert settings['count'] == expected[0] and settings['max_records'] == expected[1]
                    assert settings['iterations'] == expected[2]
                    assert settings['injection_enabled'] == bool(expected[3])
                    assert settings['patterns'] == [f'{value:08x}' for value in expected[4]]
                    assert result['config']['patterns'] == settings['patterns']
                    assert result['config']['pattern_mode'] == (expected[5] if len(expected) > 5 else 'constant')
                    for source in result['input_files'].values():
                        data = (folder / source['snapshot']).read_bytes()
                        assert hashlib.sha256(data).hexdigest() == source['sha256']
                    if '--no-telemetry' in options:
                        assert result['telemetry']['status'] == 'DISABLED'
                entry['status'] = 'PASS'
                print(name + ': PASS', flush=True)
        report['status'] = 'PASS'
        print(f'tests={len(cases)} passed={len(cases)} status=PASS')
        return 0
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        print(f'profile regression failed: {error}', file=sys.stderr)
        return 1
    finally:
        (output / 'run.json').write_text(json.dumps(report, indent=2) + '\n')
        print('logs=' + str(output))


if __name__ == '__main__':
    raise SystemExit(main())
