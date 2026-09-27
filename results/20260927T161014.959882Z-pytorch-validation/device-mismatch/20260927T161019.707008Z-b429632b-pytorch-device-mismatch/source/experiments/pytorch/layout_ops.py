"""Load the small CUDA inference operator into PyTorch's dispatcher."""
import os
from pathlib import Path
import sys

STRATEGIES = {'strided': 0, 'contiguous-copy': 1, 'flat-bug': 2}
_loaded = False


def load_operator():
    global _loaded
    import torch
    if 'CUDA_HOME' not in os.environ and os.environ.get('CUDAToolkit_ROOT'):
        os.environ['CUDA_HOME'] = os.environ['CUDAToolkit_ROOT']
    os.environ['PATH'] = str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']
    from torch.utils.cpp_extension import load
    root = Path(__file__).resolve().parents[2]
    target = root / 'build' / 'torch-layout'
    target.mkdir(parents=True, exist_ok=True)
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA device unavailable; no CPU fallback')
    if not _loaded:
        os.environ.setdefault('MAX_JOBS', '2')
        major, minor = torch.cuda.get_device_capability()
        os.environ.setdefault('TORCH_CUDA_ARCH_LIST', f'{major}.{minor}')
        load(name='gmv_layout_ops', sources=[str(Path(__file__).with_name('relu_layout.cu'))],
             build_directory=str(target), extra_cuda_cflags=['-O2', '-lineinfo'],
             is_python_module=False, verbose=False)
        _loaded = True
    return target / 'gmv_layout_ops.so'


def relu(inputs, strategy='strided'):
    import torch
    if not _loaded:
        load_operator()
    if strategy not in STRATEGIES:
        raise ValueError('unknown layout strategy: ' + strategy)
    return torch.ops.gmv_layout.relu(inputs, STRATEGIES[strategy])
