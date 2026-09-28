"""Check independent value/access outcomes; preserve raw output and source hashes.

Intentional out-of-bounds case is run only under memcheck, in its own process.
The sanitizer's exit code alone is NOT a verdict: tool report and app output
must both match. In particular, app FAIL does not mean sanitizer found an error.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'build/cuda')
    parser.add_argument('--sanitizer', default='compute-sanitizer')
    args = parser.parse_args()
    suffix = '.exe' if __import__('os').name == 'nt' else ''
    lab = args.build_dir.resolve() / ('sanitizer_lab' + suffix)
    core = args.build_dir.resolve() / ('gpu_memory_validator' + suffix)
    sanitizer = shutil.which(args.sanitizer)
    if not sanitizer or not lab.is_file() or not core.is_file():
        parser.error('Build diagnostic labs and make compute-sanitizer available first')
    folder = ROOT / 'results' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-sanitizer-validation')
    folder.mkdir()
    report = {'status': 'RUNNING', 'checks': [], 'tool': sanitizer,
              'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'git_status': subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True),
              'binary_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (lab, core)},
              'scope': 'Memory access and independent output checks. Not hardware fault diagnosis.'}
    sources = [ROOT / 'CMakeLists.txt', *sorted((ROOT / 'src').glob('*')),
               *sorted((ROOT / 'include/gmv').glob('*')), *sorted(Path(__file__).parent.glob('*.py')),
               *sorted(Path(__file__).parent.glob('*.cu'))]
    report['source_sha256'] = {}
    for p in sources:
        dest = folder / 'source' / p.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        report['source_sha256'][str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    report['tool_version'] = subprocess.check_output([sanitizer, '--version'], text=True)

    def run(name, app_args, expected_exit, expect_memory_error, app_marker):
        tool_log = folder / (name + '.sanitizer.txt')
        command = [sanitizer, '--tool', 'memcheck', '--error-exitcode', '86',
                   '--check-exit-code', 'no', '--destroy-on-device-error', 'kernel',
                   '--log-file', str(tool_log), *map(str, app_args)]
        errors = []
        try:
            completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
            stdout, stderr, code = completed.stdout, completed.stderr, completed.returncode
        except subprocess.TimeoutExpired as error:
            stdout = (error.stdout or b'').decode(errors='replace') if isinstance(error.stdout, bytes) else (error.stdout or '')
            stderr = (error.stderr or b'').decode(errors='replace') if isinstance(error.stderr, bytes) else (error.stderr or '')
            code = None
            errors.append('TIMEOUT')
        (folder / (name + '.stdout.txt')).write_text(stdout)
        (folder / (name + '.stderr.txt')).write_text(stderr)
        log = tool_log.read_text() if tool_log.exists() else ''
        summaries = re.findall(r'ERROR SUMMARY: (\d+) errors?', log)
        count = int(summaries[-1]) if len(summaries) == 1 else None
        if code != expected_exit: errors.append(f'exit: expected {expected_exit}, got {code}')
        if app_marker not in stdout: errors.append('missing expected application result')
        if expect_memory_error:
            if count != 1 or 'Invalid __global__ write of size 4 bytes' not in log or 'write_one_past_end' not in log or 'memory_access.cu:' not in log:
                errors.append('missing precise source-attributed invalid-write report')
        elif count != 0:
            errors.append(f'expected zero sanitizer errors, got {count}')
        if 'Failed to initialize' in log or 'Internal Sanitizer Error' in log:
            errors.append('sanitizer execution failure')
        row = {'name': name, 'command': command, 'exit_code': code,
               'expected_exit_code': expected_exit, 'sanitizer_error_count': count,
               'expected_memory_error': expect_memory_error, 'expected_app_marker': app_marker,
               'status': 'FAIL' if errors else 'PASS', 'errors': errors}
        report['checks'].append(row)
        (folder / 'run.json').write_text(json.dumps(report, indent=2) + '\n')
        print(name, row['status'], 'sanitizer_errors=' + str(count), flush=True)

    for case, code, memory_error, mismatches in [
        ('normal', 0, False, 0), ('bounds-bug', 86, True, 0),
        ('stride-bug', 1, False, 10), ('stride-fixed', 0, False, 0)]:
        extra = ['--intentional-fault'] if memory_error else []
        run(case, [lab, case, *extra], code, memory_error,
            f'case={case} cpu_mismatches={mismatches} value_check={"FAIL" if mismatches else "PASS"}')
    # Normal production executable after the isolated negative control.
    for mode in ('constant', 'index', 'seeded'):
        for access in ('read', 'invert'):
            for inject in (False, True):
                command = [core, '--count', '257', '--patterns', '12345678,deadbeef',
                           '--pattern-mode', mode, '--access-mode', access, '--iterations', '2',
                           '--gpu-passes', '3', '--max-records', '2', '--inject-pass', '2']
                if inject: command.append('--inject')
                run(f'{mode}-{access}-inject-{int(inject)}', command, int(inject), False,
                    f'run_status={"FAIL" if inject else "PASS"} completed_patterns=4')
    report['status'] = 'PASS' if all(c['status'] == 'PASS' for c in report['checks']) else 'FAIL'
    (folder / 'run.json').write_text(json.dumps(report, indent=2) + '\n')
    print('evidence=' + str(folder))
    print('status=' + report['status'])
    return int(report['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
