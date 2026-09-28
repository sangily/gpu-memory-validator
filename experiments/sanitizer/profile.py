"""Capture CUDA timelines and reject incomplete traces, even if nsys exits zero.

Two seeded patterns x two iterations, 16 MiB, 32 GPU passes per checkpoint.
Read and invert traces describe execution; they are not a speedup benchmark.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess

from setup_nsight import NSYS, DEST

ROOT = Path(__file__).resolve().parents[2]


def analyze(database, access):
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'CUPTI_ACTIVITY_KIND_KERNEL', 'CUPTI_ACTIVITY_KIND_MEMCPY',
                    'CUPTI_ACTIVITY_KIND_RUNTIME', 'StringIds'}
        if not required <= tables:
            raise ValueError('Incomplete CUDA trace: missing ' + ', '.join(sorted(required - tables)))
        strings = dict(db.execute('SELECT id,value FROM StringIds'))
        kernels = [dict(r) for r in db.execute('SELECT * FROM CUPTI_ACTIVITY_KIND_KERNEL ORDER BY start')]
        copies = [dict(r) for r in db.execute('SELECT * FROM CUPTI_ACTIVITY_KIND_MEMCPY ORDER BY start')]
        apis = [dict(r) for r in db.execute('SELECT * FROM CUPTI_ACTIVITY_KIND_RUNTIME ORDER BY start')]
        diagnostics = [dict(r) for r in db.execute('SELECT * FROM DIAGNOSTIC_EVENT')] if 'DIAGNOSTIC_EVENT' in tables else []
    errors = []
    for item in kernels:
        name = strings[item['demangledName']]
        candidates = [n for n in ('fill_pattern', 'verify_pattern', 'latch_failure', 'invert_words') if n + '(' in name]
        if len(candidates) != 1:
            raise ValueError('Unexpected kernel: ' + name)
        item['name'] = candidates[0]
    for item in apis:
        item['name'] = strings[item['nameId']]
    expected = []
    for _ in range(4):
        expected.append('fill_pattern')
        for step in range(32):
            if access == 'invert' and step: expected.append('invert_words')
            expected.extend(('verify_pattern', 'latch_failure'))
    if [k['name'] for k in kernels] != expected: errors.append('kernel order/count differs from expected workload')
    streams = {(k['deviceId'], k['contextId'], k['streamId']) for k in kernels}
    if len(streams) != 1: errors.append('expected one device/context/stream')
    if any(a['end'] > b['start'] for a, b in zip(kernels, kernels[1:])):
        errors.append('same-stream kernels unexpectedly overlap')
    bulk = [c for c in copies if c['bytes'] == 16 * 1024 * 1024 and c['copyKind'] == 2]
    if len(bulk) != 4: errors.append('expected four complete 16 MiB device-to-host snapshots')
    fills = [i for i, k in enumerate(kernels) if k['name'] == 'fill_pattern']
    if len(fills) == 4 and len(bulk) == 4:
        for i in range(4):
            last = (fills[i + 1] if i < 3 else len(kernels)) - 1
            if bulk[i]['start'] < kernels[last]['end']:
                errors.append('snapshot started before final latch completed')
            if i < 3 and bulk[i]['end'] > kernels[fills[i + 1]]['start']:
                errors.append('next pattern started before snapshot finished')
    bad_diagnostics = [d for d in diagnostics if d['severity'] >= 3 or
                       'not supported by this build' in d['text']]
    if bad_diagnostics: errors.append('profiler reported an error or driver compatibility warning')
    if not apis: errors.append('CUDA Runtime API events missing')
    if any(a['returnValue'] != 0 for a in apis): errors.append('CUDA Runtime API returned an error')

    def aggregate(events):
        groups = defaultdict(list)
        for e in events: groups[e['name']].append(e['end'] - e['start'])
        return {name: {'count': len(times), 'total_ms': sum(times) / 1e6,
                       'mean_us': sum(times) / len(times) / 1e3}
                for name, times in sorted(groups.items())}

    summary = {'status': 'FAIL' if errors else 'PASS', 'errors': errors,
               'kernel_count': len(kernels), 'kernel_counts': dict(Counter(k['name'] for k in kernels)),
               'kernels': aggregate(kernels), 'runtime_apis': aggregate(apis),
               'full_snapshot_count': len(bulk), 'full_snapshot_bytes': sum(c['bytes'] for c in bulk),
               'full_snapshot_gpu_ms': sum(c['end'] - c['start'] for c in bulk) / 1e6,
               'diagnostics': diagnostics,
               'note': 'Instrumented execution. API and GPU durations overlap; do not add them or infer hardware health.'}
    events = {'kernels': [{k: e[k] for k in ('name', 'start', 'end', 'streamId')} for e in kernels],
              'copies': [{k: e[k] for k in ('start', 'end', 'bytes', 'copyKind', 'streamId')} for e in copies],
              'runtime_apis': [{k: e[k] for k in ('name', 'start', 'end')} for e in apis]}
    return summary, events


def main():
    binary = ROOT / 'build/cuda/gpu_memory_validator'
    if not NSYS.is_file() or not binary.is_file():
        raise SystemExit('Build the validator and run setup_nsight.py first')
    folder = ROOT / 'results' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-cuda-timeline')
    folder.mkdir()
    # Nsight saves process environments in its report; pass only the required values.
    env = {k: os.environ[k] for k in ('HOME', 'USER', 'LOGNAME', 'PATH', 'TMPDIR', 'XDG_RUNTIME_DIR') if k in os.environ}
    env.update(LANG='C.UTF-8', LD_LIBRARY_PATH=str(Path.home() / '.local/opt/cuda-12.8.1-minimal/lib') + ':/usr/lib/wsl/lib')
    report = {'status': 'RUNNING', 'platform': platform.platform(),
              'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'git_status': subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True),
              'tool_version': subprocess.check_output([str(NSYS), '--version'], text=True),
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'conditions': {'bytes': 16 * 1024 * 1024, 'patterns': ['12345678', 'deadbeef'],
                             'pattern_mode': 'seeded', 'iterations': 2, 'gpu_passes': 32},
              'runs': [], 'source_sha256': {}}
    shutil.copy2(DEST / 'package.json', folder / 'package.json')
    for p in [ROOT / 'CMakeLists.txt', *sorted((ROOT / 'src').glob('*')),
              *sorted((ROOT / 'include/gmv').glob('*')), *sorted(Path(__file__).parent.glob('*.py'))]:
        target = folder / 'source' / p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        report['source_sha256'][str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()

    def execute(name, command):
        with (folder / (name + '.stdout.txt')).open('w') as out, (folder / (name + '.stderr.txt')).open('w') as err:
            process = subprocess.run(command, cwd=ROOT, env=env, stdout=out, stderr=err, timeout=180)
        if process.returncode:
            raise RuntimeError(name + ' failed: ' + str(process.returncode))
        return (folder / (name + '.stdout.txt')).read_text()

    try:
        for access in ('read', 'invert'):
            prefix = folder / access
            app = [str(binary), '--count', '4194304', '--patterns', '12345678,deadbeef',
                   '--pattern-mode', 'seeded', '--iterations', '2', '--gpu-passes', '32',
                   '--access-mode', access, '--max-records', '2']
            command = [str(NSYS), 'profile', '--trace=cuda', '--sample=none', '--cpuctxsw=none',
                       '--cuda-event-trace=false', '--cuda-memory-usage=true', '--output=' + str(prefix), *app]
            row = {'access_mode': access, 'profile_command': command, 'status': 'RUNNING'}
            report['runs'].append(row)
            stdout = execute(access + '-profile', command)
            if 'run_status=PASS completed_patterns=4' not in stdout or stdout.count('reference_check=PASS') != 4:
                raise ValueError('application did not complete all independent CPU checks')
            export = [str(NSYS), 'export', '--type=sqlite', '--output=' + str(prefix) + '.sqlite', str(prefix) + '.nsys-rep']
            row['export_command'] = export
            execute(access + '-export', export)
            summary, events = analyze(str(prefix) + '.sqlite', access)
            (folder / (access + '-summary.json')).write_text(json.dumps(summary, indent=2) + '\n')
            (folder / (access + '-events.json')).write_text(json.dumps(events, indent=2) + '\n')
            row.update(status=summary['status'], kernel_counts=summary['kernel_counts'], errors=summary['errors'])
            print(access, row['status'], row['kernel_counts'], flush=True)
        report['status'] = 'PASS' if all(r['status'] == 'PASS' for r in report['runs']) else 'FAIL'
    except Exception as error:
        report.update(status='ERROR', error=str(error))
    finally:
        (folder / 'run.json').write_text(json.dumps(report, indent=2) + '\n')
        print('evidence=' + str(folder))
        print('status=' + report['status'])
    return int(report['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
