#!/usr/bin/env python3
"""Extract pinned NVIDIA DCGM packages locally without changing drivers/services."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/dcgm-4.6.1'
BASE.mkdir(parents=True, exist_ok=True)
manifest = Path(__file__).with_name('packages.json')
for package in json.loads(manifest.read_text()):
    name = Path(package['Filename']).name
    target = BASE / name
    expected = package['SHA256']
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        url = 'https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/' + name
        partial = target.with_suffix('.part')
        print('Downloading ' + name, flush=True)
        with urllib.request.urlopen(url, timeout=120) as response, partial.open('wb') as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(partial.read_bytes()).hexdigest() != expected:
            raise RuntimeError('SHA256 mismatch: ' + name)
        partial.replace(target)
    subprocess.run(['dpkg-deb', '-x', str(target), str(BASE / 'root')], check=True)
shutil.copyfile(manifest, BASE / 'packages.json')
print('package_root=' + str(BASE / 'root'))
