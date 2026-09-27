#!/usr/bin/env python3
"""Alternate two Release validators; compare end-to-end time with full CPU checks."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cli_oracle', ROOT / 'tests/cli/test_validator.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def capture(command):
    try:
        p = subprocess.run(command, capture_output=True, text=True, timeout=5)
        return {'command': command, 'exit_code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'command': command, 'error': str(error)}


def gpu_snapshot():
    return capture(['/usr/lib/wsl/lib/nvidia-smi',
                    '--query-gpu=uuid,name,driver_version,temperature.gpu,power.draw,clocks.current.sm,clocks.current.memory,memory.free',
                    '--format=csv,noheader,nounits'])


def save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def source_snapshot(folder, label, source, binary):
    paths = [source / 'CMakeLists.txt'] + sorted((source / 'src').glob('*')) + sorted((source / 'include/gmv').glob('*'))
    hashes = {}
    for path in paths:
        rel = path.relative_to(source)
        content = path.read_bytes()
        target = folder / 'source' / label / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        hashes[str(rel)] = hashlib.sha256(content).hexdigest()
    cache = binary.parent / 'CMakeCache.txt'
    if cache.exists():
        (folder / f'{label}.CMakeCache.txt').write_bytes(cache.read_bytes())
    return {'source_dir': str(source), 'binary': str(binary),
            'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(), 'source_sha256': hashes,
            'git_head': capture(['git', '-C', str(source), 'rev-parse', 'HEAD']),
            'git_status': capture(['git', '-C', str(source), 'status', '--porcelain'])}


def describe(values):
    quartiles = statistics.quantiles(values, n=4, method='inclusive')
    return {'median': statistics.median(values), 'min': min(values), 'max': max(values),
            'q1': quartiles[0], 'q3': quartiles[2]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'build/perf-baseline/gpu_memory_validator')
    parser.add_argument('--baseline-source', type=Path, default=ROOT / 'build/perf-baseline-source')
    parser.add_argument('--candidate', type=Path, default=ROOT / 'build/cuda/gpu_memory_validator')
    parser.add_argument('--mib', nargs='+', type=int, choices=(128, 256), default=[128, 256])
    parser.add_argument('--samples', type=int, default=10)
    parser.add_argument('--iterations', type=int, default=4)
    args = parser.parse_args()
    if not 2 <= args.samples <= 100 or not 1 <= args.iterations <= 10000:
        parser.error('samples must be 2..100 and iterations 1..10000')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    folder = ROOT / 'results' / (stamp + '-host-buffer-comparison')
    folder.mkdir()
    report = {'status': 'RUNNING', 'started_utc': stamp, 'environment': platform.platform(),
              'scope': 'fresh child process launch through exit; includes CUDA initialization, allocations, full CPU reference, output and cleanup; not kernel timing or bandwidth',
              'method': 'one excluded warm-up per variant/size; paired AB/BA order; telemetry outside measured regions; all samples retained',
              'config': {'mib': args.mib, 'iterations': args.iterations, 'patterns': ['00000000', 'ffffffff', 'aaaaaaaa', '55555555'],
                         'max_records': 3, 'reference': 'full', 'injection': False, 'samples_per_variant_size': args.samples},
              'runs': [], 'telemetry': [], 'summaries': {}}
    print(f'results={folder}', flush=True)
    binaries = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    try:
        report['variants'] = {
            'baseline': source_snapshot(folder, 'baseline', args.baseline_source.resolve(), binaries['baseline']),
            'candidate': source_snapshot(folder, 'candidate', ROOT, binaries['candidate'])}
        for path in [Path(__file__), ROOT / 'tests/cli/test_validator.py', ROOT / 'scripts/test_first_kernel.py']:
            destination = folder / 'source' / 'measurement' / path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
        report['toolchain'] = {'nvcc': capture(['nvcc', '--version']), 'cxx': capture(['c++', '--version'])}
        save(folder / 'run.json', report)

        def execute(label, mib, sample, warmup):
            count = mib * 1024 * 1024 // 4
            name = f'{mib}MiB-{label}-' + ('warmup' if warmup else f'{sample:02d}')
            command = [str(binaries[label]), '--count', str(count), '--iterations', str(args.iterations), '--max-records', '3']
            entry = {'name': name, 'variant': label, 'mib': mib, 'sample': sample, 'warmup': warmup, 'command': command}
            report['runs'].append(entry)
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            start = time.perf_counter()
            try:
                p = subprocess.run(command, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired as error:
                entry.update(status='ERROR', reason='TIMEOUT')
                for stream in ('stdout', 'stderr'):
                    value = getattr(error, stream) or b''
                    (folder / f'{name}.{stream}.txt').write_bytes(value if isinstance(value, bytes) else value.encode())
                raise RuntimeError(f'{name}: timeout') from error
            elapsed = time.perf_counter() - start
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            entry.update(elapsed_seconds=elapsed, exit_code=p.returncode,
                         user_seconds=after.ru_utime-before.ru_utime,
                         system_seconds=after.ru_stime-before.ru_stime,
                         minor_page_faults=after.ru_minflt-before.ru_minflt)
            (folder / f'{name}.stdout.txt').write_text(p.stdout)
            (folder / f'{name}.stderr.txt').write_text(p.stderr)
            if p.returncode != 0 or p.stderr.strip():
                raise RuntimeError(f'{name}: unexpected exit/stderr')
            # Archived constant-only binaries predate the explicit mode header.
            # Preserve raw output and normalize only the checker input. An
            # explicit non-constant header must still fail this benchmark.
            checked_output = p.stdout
            if not any(line.startswith('pattern_mode=') for line in p.stdout.splitlines()):
                checked_output = 'pattern_mode=constant\n' + p.stdout
            oracle.check_configured(checked_output, count, 3, args.iterations, {})
            entry['status'] = 'PASS'
            save(folder / 'run.json', report)
            print(f'{name}: {elapsed:.4f}s faults={entry["minor_page_faults"]} PASS', flush=True)

        for mib in args.mib:
            # Validate available VRAM before asking either binary to allocate.
            memory = capture(['/usr/lib/wsl/lib/nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'])
            report['telemetry'].append({'mib': mib, 'phase': 'memory_guard', 'reading': memory})
            if memory.get('exit_code') != 0 or mib * 2 > float(memory['stdout'].splitlines()[0]):
                raise RuntimeError('cannot confirm allocation is below half the currently free VRAM')
            for label in binaries:
                execute(label, mib, 0, True)
            for sample in range(args.samples):
                report['telemetry'].append({'mib': mib, 'sample': sample, 'phase': 'before_pair', 'reading': gpu_snapshot()})
                for label in (('baseline', 'candidate') if sample % 2 == 0 else ('candidate', 'baseline')):
                    execute(label, mib, sample, False)
                report['telemetry'].append({'mib': mib, 'sample': sample, 'phase': 'after_pair', 'reading': gpu_snapshot()})
            summary = {}
            for label in binaries:
                runs = [r for r in report['runs'] if r['mib'] == mib and r['variant'] == label and not r['warmup']]
                summary[label] = {metric: describe([r[metric] for r in runs]) for metric in
                                  ('elapsed_seconds', 'user_seconds', 'system_seconds', 'minor_page_faults')}
            baseline = summary['baseline']['elapsed_seconds']['median']
            candidate = summary['candidate']['elapsed_seconds']['median']
            summary['median_time_reduction_percent'] = (baseline-candidate)/baseline*100
            report['summaries'][str(mib)] = summary
        report['status'] = 'PASS'
        print(json.dumps(report['summaries'], indent=2), flush=True)
        return 0
    except Exception as error:
        report.update(status='ERROR', error=str(error))
        print(f'comparison failed: {error}', flush=True)
        return 2
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save(folder / 'run.json', report)


if __name__ == '__main__':
    raise SystemExit(main())
