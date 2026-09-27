#!/usr/bin/env python3
"""Reproduce tensor placement mistakes, then check a small GPU inference result."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path
import platform
import subprocess
import sys
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[2]
SEED = 20260927
RTOL = 1e-4
ATOL = 1e-5


def make_workload(torch):
    """Generate identical CPU float32 inputs/parameters for all three cases."""
    torch.manual_seed(SEED)
    model = torch.nn.Sequential(torch.nn.Linear(32, 16), torch.nn.ReLU()).eval()
    inputs = torch.randn(64, 32, dtype=torch.float32)
    return model, inputs


def compare_output(torch, actual, reference):
    """Compare on CPU in float64; explicitly reject shape errors and nonfinite data."""
    actual = actual.detach().cpu().to(torch.float64)
    reference = reference.detach().cpu().to(torch.float64)
    if actual.shape != reference.shape:
        raise AssertionError(f'shape mismatch: {tuple(actual.shape)} != {tuple(reference.shape)}')
    if not torch.isfinite(actual).all().item() or not torch.isfinite(reference).all().item():
        raise AssertionError('nonfinite output or reference')
    torch.testing.assert_close(actual, reference, rtol=RTOL, atol=ATOL, equal_nan=False)
    return {'elements': actual.numel(), 'shape': list(actual.shape), 'rtol': RTOL, 'atol': ATOL,
            'max_abs_error': (actual - reference).abs().max().item(), 'status': 'PASS',
            'reference': 'CPU float64 inference from the same float32 inputs and parameters'}


def run_case(torch, case, report):
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA device unavailable; this lab does not fall back to CPU')
    # Avoid TF32 in this accuracy exercise; this is not a performance measurement.
    torch.backends.fp32_precision = 'ieee'
    torch.backends.cuda.matmul.fp32_precision = 'ieee'
    torch.set_num_threads(1)
    cpu_model, cpu_inputs = make_workload(torch)
    with torch.inference_mode():
        reference = copy.deepcopy(cpu_model).to(torch.float64)(cpu_inputs.to(torch.float64))
        gpu_model = copy.deepcopy(cpu_model).to('cuda:0')
        report['devices'] = {'model': str(next(gpu_model.parameters()).device),
                             'original_input': str(cpu_inputs.device)}
        report['phase'] = 'prepare_input'
        if case == 'device-mismatch':
            inputs = cpu_inputs
        elif case == 'ignored-transfer':
            cpu_inputs.to('cuda:0')  # Intentional bug: Tensor.to returns a tensor.
            inputs = cpu_inputs
        else:
            inputs = cpu_inputs.to('cuda:0')
        report['devices']['operation_input'] = str(inputs.device)
        report['phase'] = 'forward'
        output = gpu_model(inputs)
        report['devices']['output'] = str(output.device)
        report['phase'] = 'synchronize'
        torch.cuda.synchronize()
        report['phase'] = 'reference_check'
        report['comparison'] = compare_output(torch, output, reference)
        report['phase'] = 'completed'


def capture(command):
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
        return {'command': command, 'exit_code': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'command': command, 'error': str(error)}


def snapshot(folder):
    hashes = {}
    paths = [*sorted((ROOT / 'experiments/pytorch').glob('*.py')),
             ROOT / 'experiments/pytorch/requirements.txt',
             *sorted((ROOT / 'tests/pytorch').glob('*.py'))]
    for path in paths:
        relative = path.relative_to(ROOT)
        raw = path.read_bytes()
        hashes[str(relative)] = hashlib.sha256(raw).hexdigest()
        target = folder / 'source' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['device-mismatch', 'ignored-transfer', 'fixed'], default='fixed')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'results')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    folder = args.output_root / f'{stamp}-{uuid.uuid4().hex[:8]}-pytorch-{args.case}'
    folder.mkdir(parents=True)
    report = {'schema_version': 'pytorch-device-lab-v1', 'case': args.case,
              'started_utc': datetime.now(timezone.utc).isoformat(), 'status': 'ERROR', 'phase': 'setup',
              'seed': SEED, 'input_shape': [64, 32], 'output_shape': [64, 16],
              'dtype': 'float32', 'tf32': False, 'command': [sys.executable, *sys.argv],
              'environment': {'python': sys.version, 'platform': platform.platform()},
              'source_sha256': snapshot(folder),
              'git_head': capture(['git', 'rev-parse', 'HEAD']),
              'git_status': capture(['git', 'status', '--short']),
              'packages': sorted(f'{d.metadata["Name"]}=={d.version}' for d in distributions())}
    try:
        import torch
        report['environment'].update(torch=str(torch.__version__), torch_cuda=torch.version.cuda,
                                     cuda_available=torch.cuda.is_available())
        smi = '/usr/lib/wsl/lib/nvidia-smi' if Path('/usr/lib/wsl/lib/nvidia-smi').exists() else 'nvidia-smi'
        report['environment']['nvidia_smi'] = capture([smi, '--query-gpu=name,uuid,driver_version', '--format=csv'])
        if torch.cuda.is_available():
            report['environment']['gpu'] = torch.cuda.get_device_name(0)
            report['environment']['capability'] = list(torch.cuda.get_device_capability(0))
        run_case(torch, args.case, report)
        report['status'] = 'PASS'
        code = 0
    except AssertionError as error:
        report.update(status='FAIL', error=str(error), error_type=type(error).__name__)
        code = 1
        (folder / 'traceback.txt').write_text(traceback.format_exc())
    except Exception as error:
        report.update(status='ERROR', error=str(error), error_type=type(error).__name__)
        code = 2
        (folder / 'traceback.txt').write_text(traceback.format_exc())
    report['exit_code'] = code
    (folder / 'run.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'case={args.case} status={report["status"]} phase={report["phase"]}')
    if 'devices' in report:
        print('devices=' + json.dumps(report['devices']))
    if 'comparison' in report:
        print('comparison=' + json.dumps(report['comparison']))
    if 'error' in report:
        print(report['error'], file=sys.stderr)
    print('run_dir=' + str(folder))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
