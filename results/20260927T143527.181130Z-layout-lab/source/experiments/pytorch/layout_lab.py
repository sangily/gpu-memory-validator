#!/usr/bin/env python3
"""Reproduce a layout bug, verify two fixes, and preserve CUDA experiment evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import traceback

import torch
from layout_ops import STRATEGIES, load_operator, relu

ROOT = Path(__file__).resolve().parents[2]
LAYOUTS = ('contiguous', 'transpose', 'slice', 'offset', 'expand')


def make_input(layout, rows, cols):
    """Create identical CPU/GPU base storage, then apply the same view operation."""
    dimensions = {'contiguous': (rows, cols), 'transpose': (cols, rows),
                  'slice': (2 * rows + 1, 3 * cols + 2),
                  'offset': (rows + 2, cols + 2), 'expand': (1, cols)}
    shape = dimensions[layout]
    base = torch.arange(shape[0] * shape[1], dtype=torch.float32).reshape(shape)
    base = base - base.numel() // 3
    gpu_base = base.to('cuda')

    def view(x):
        if layout == 'transpose': return x.t()
        if layout == 'slice': return x[1:1 + 2 * rows:2, 1:1 + 3 * cols:3]
        if layout == 'offset': return x[1:1 + rows, 1:1 + cols]
        if layout == 'expand': return x.expand(rows, cols)
        return x

    return view(base), view(gpu_base)


def describe(tensor):
    return dict(shape=list(tensor.shape), stride=list(tensor.stride()),
                storage_offset=tensor.storage_offset(), contiguous=tensor.is_contiguous(),
                dtype=str(tensor.dtype), device=str(tensor.device))


def compare(actual, expected):
    actual = actual.detach().cpu()
    if actual.shape != expected.shape or not torch.isfinite(actual).all() or not torch.isfinite(expected).all():
        raise ValueError('invalid shape or non-finite output/reference')
    mask = actual != expected
    count = int(mask.sum())
    records = []
    for row, col in mask.nonzero()[:5].tolist():
        records.append(dict(row=row, column=col, expected=float(expected[row, col]),
                            actual=float(actual[row, col])))
    return dict(status='FAIL' if count else 'PASS', mismatches=count,
                elements=actual.numel(), records=records,
                criterion='exact finite float32 ReLU values; no reduction/rounding tolerance')


def run_case(layout, strategy, rows=17, cols=19):
    cpu, gpu = make_input(layout, rows, cols)
    # CPU logical indexing follows the view. It does not reuse the CUDA address formula.
    expected = cpu.clamp_min(0)
    output = relu(gpu, strategy)
    torch.cuda.synchronize()
    result = compare(output, expected)
    torch.testing.assert_close(gpu.cpu(), cpu, rtol=0, atol=0)
    return dict(layout=layout, strategy=strategy, input=describe(gpu),
                output=describe(output), comparison=result, status=result['status'])


def benchmark(rows=1024, cols=1025, samples=20):
    """CUDA event intervals, including any contiguous copy, allocation/launch gaps."""
    results = []
    for layout in ('contiguous', 'transpose', 'slice'):
        cpu, gpu = make_input(layout, rows, cols)
        expected = cpu.clamp_min(0)
        variants = {'strided': lambda: relu(gpu, 'strided'),
                    'contiguous-copy': lambda: relu(gpu, 'contiguous-copy'),
                    'torch-relu': lambda: torch.relu(gpu)}
        observations = {name: [] for name in variants}
        for call in variants.values():
            for _ in range(5): call()
        torch.cuda.synchronize()
        for sample in range(samples):
            names = list(variants)
            if sample % 2: names.reverse()
            for name in names:
                start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
                start.record()
                output = variants[name]()
                end.record()
                end.synchronize()
                elapsed = start.elapsed_time(end)
                assert compare(output, expected)['status'] == 'PASS'
                observations[name].append(elapsed)
        results.append(dict(layout=layout, input=describe(gpu), samples_ms=observations,
                            median_ms={name: statistics.median(values) for name, values in observations.items()}))
    return dict(scope='CUDA events around each operation; copy included for contiguous-copy. '
                     'Includes stream idle gaps from host submission; not isolated kernel time. '
                     '5 warm-ups per variant; alternating order; all outputs checked outside timing.',
                rows=rows, columns=cols, samples_per_variant=samples, results=results)


def create_evidence(label):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    folder = ROOT / 'results' / (stamp + '-' + label)
    folder.mkdir()
    report = dict(status='RUNNING', started_utc=stamp, command=[sys.executable, *sys.argv],
                  environment=dict(python=sys.version, platform=platform.platform(), torch=str(torch.__version__),
                                   torch_cuda=torch.version.cuda), source_sha256={})
    for directory in ('experiments/pytorch', 'tests/pytorch'):
        for path in sorted((ROOT / directory).glob('*')):
            if path.suffix not in ('.py', '.cu', '.txt'): continue
            relative = path.relative_to(ROOT)
            raw = path.read_bytes()
            target = folder / 'source' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            report['source_sha256'][str(relative)] = hashlib.sha256(raw).hexdigest()
    for key, command in [('git_head', ['git', 'rev-parse', 'HEAD']),
                         ('git_status', ['git', 'status', '--short'])]:
        p = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
        report[key] = dict(exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr)
    return folder, report


def prepare(report, folder):
    binary = load_operator()
    report['environment'].update(gpu=torch.cuda.get_device_name(), capability=list(torch.cuda.get_device_capability()))
    report['extension_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
    build_file = binary.parent / 'build.ninja'
    (folder / 'build.ninja.txt').write_bytes(build_file.read_bytes())
    report['build_requirements'] = (Path(__file__).with_name('requirements-layout.txt')).read_text()


def finish(folder, report):
    (folder / 'run.json').write_text(json.dumps(report, indent=2) + '\n')
    print('status=' + report['status'])
    print('evidence=' + str(folder))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout', choices=LAYOUTS, default='transpose')
    parser.add_argument('--strategy', choices=STRATEGIES, default='strided')
    parser.add_argument('--benchmark', action='store_true')
    args = parser.parse_args()
    folder, report = create_evidence('layout-lab')
    try:
        prepare(report, folder)
        report['case'] = run_case(args.layout, args.strategy)
        report['status'] = report['case']['status']
        print(json.dumps(report['case'], indent=2))
        if args.benchmark:
            report['benchmark'] = benchmark()
        code = 0 if report['status'] == 'PASS' else 1
    except Exception as error:
        report.update(status='ERROR', error=str(error), error_type=type(error).__name__)
        (folder / 'traceback.txt').write_text(traceback.format_exc())
        code = 2
    finish(folder, report)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
