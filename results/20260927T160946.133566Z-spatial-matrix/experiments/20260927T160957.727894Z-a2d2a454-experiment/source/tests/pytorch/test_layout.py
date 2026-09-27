#!/usr/bin/env python3
"""Real CUDA layout, stream, inference integration and input-contract checks."""
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments/pytorch'))
import torch
from layout_lab import create_evidence, prepare, finish, run_case, compare, describe
from layout_ops import relu


def main():
    folder, report = create_evidence('layout-regression')
    report['checks'] = []
    try:
        prepare(report, folder)
        for layout in ('contiguous', 'transpose', 'slice', 'offset', 'expand'):
            for rows, cols in ((1, 1), (1, 257), (17, 19), (257, 33), (0, 19), (3, 0)):
                for strategy in ('strided', 'contiguous-copy'):
                    result = run_case(layout, strategy, rows, cols)
                    assert result['status'] == 'PASS', result
                    report['checks'].append(result)

        for layout in ('contiguous', 'transpose', 'slice', 'offset'):
            result = run_case(layout, 'flat-bug')
            expected = 'PASS' if layout == 'contiguous' else 'FAIL'
            assert result['status'] == expected, result
            report['checks'].append(dict(case='intentional_flat_bug', expected=expected, observed=result, status='PASS'))

        # The custom op replaces ReLU in a small inference pipeline. A transpose
        # before activation makes the Linear output noncontiguous; no training.
        torch.manual_seed(20260927)
        cpu = torch.nn.Linear(32, 16).eval()
        x = torch.randn(64, 32)
        gpu = torch.nn.Linear(32, 16).cuda().eval()
        gpu.load_state_dict(cpu.state_dict())
        torch.backends.cuda.matmul.fp32_precision = 'ieee'
        with torch.inference_mode():
            cpu_logits = cpu(x).t()
            gpu_logits = gpu(x.cuda()).t()
            for strategy in ('strided', 'contiguous-copy'):
                output = relu(gpu_logits, strategy)
                # Exact activation check isolates layout from GEMM rounding.
                assert compare(output, gpu_logits.cpu().clamp_min(0))['status'] == 'PASS'
                reference = cpu_logits.clamp_min(0)
                torch.testing.assert_close(output.cpu(), reference, rtol=1e-4, atol=1e-5)
                report['checks'].append(dict(case='linear_transpose_relu', strategy=strategy,
                    input=describe(gpu_logits), status='PASS', atol=1e-5, rtol=1e-4,
                    max_abs_error=float((output.cpu() - reference).abs().max())))

        # Delayed producer and downstream consumer use different non-default
        # streams with explicit dependencies. _sleep is test-only CUDA work.
        for strategy in ('strided', 'contiguous-copy'):
            data = torch.full((19, 17), -1., device='cuda')
            torch.cuda.synchronize()
            producer, consumer = torch.cuda.Stream(), torch.cuda.Stream()
            with torch.cuda.stream(producer):
                torch.cuda._sleep(20_000_000)
                data.fill_(7.)
                output = relu(data.t(), strategy)
                ready = torch.cuda.Event()
                ready.record()
            with torch.cuda.stream(consumer):
                consumer.wait_event(ready)
                checked = output + 1
            consumer.synchronize()
            assert torch.equal(checked.cpu(), torch.full((17, 19), 8.))
            report['checks'].append(dict(case='non_default_producer_consumer', strategy=strategy, status='PASS'))

        invalid = [
            ('dtype', torch.ones(2, 3, device='cuda', dtype=torch.float64), 0, 'float32'),
            ('rank', torch.ones(3, device='cuda'), 0, '2D'),
            ('autograd', torch.ones(2, 3, device='cuda', requires_grad=True), 0, 'inference-only'),
            ('mode', torch.ones(2, 3, device='cuda'), 9, 'strategy'),
            ('unsafe_demo', torch.ones(1, 3, device='cuda').expand(7, 3), 2, 'outside storage'),
            ('cpu_dispatch', torch.ones(2, 3), 0, 'CPU'),
        ]
        for name, data, mode, fragment in invalid:
            try:
                torch.ops.gmv_layout.relu(data, mode)
            except (RuntimeError, NotImplementedError) as error:
                assert fragment in str(error), str(error)
                report['checks'].append(dict(case=name, status='PASS', expected_error=str(error)))
            else:
                raise AssertionError('input unexpectedly accepted: ' + name)
        report['status'] = 'PASS'
        print('checks=' + str(len(report['checks'])))
        code = 0
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        (folder / 'traceback.txt').write_text(traceback.format_exc())
        print(traceback.format_exc())
        code = 1
    finish(folder, report)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
