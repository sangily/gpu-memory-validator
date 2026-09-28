"""Extract a pinned official Nsight Systems package locally; no OS installation."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
VERSION = '2026.3.2'
URL = ('https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/'
       'nsight-systems-2026.3.2_2026.3.2.476-1_amd64.deb')
SHA256 = 'e9bf0ff9c613ff5545095a4177676a9579cb666e78c8621c3792f3559e2c1690'
DEST = ROOT / 'build' / ('nsight-systems-' + VERSION)
NSYS = DEST / 'root/opt/nvidia/nsight-systems' / VERSION / 'bin/nsys'


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    archive = DEST / 'package.deb'
    if not archive.exists():
        partial = archive.with_suffix('.part')
        print('Downloading official Nsight Systems package (~448 MB)', flush=True)
        with urllib.request.urlopen(URL, timeout=120) as response, partial.open('wb') as output:
            shutil.copyfileobj(response, output)
        partial.rename(archive)
    h = hashlib.sha256()
    with archive.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    if h.hexdigest() != SHA256:
        raise RuntimeError('Package SHA256 mismatch; remove the local archive before retrying')
    if not NSYS.exists():
        subprocess.run(['dpkg-deb', '-x', str(archive), str(DEST / 'root')], check=True)
    (DEST / 'package.json').write_text(json.dumps({'url': URL, 'sha256': SHA256,
        'version': VERSION, 'installation': 'local extraction; no system installation'}, indent=2) + '\n')
    subprocess.run([str(NSYS), '--version'], check=True)
    print('nsys=' + str(NSYS))


if __name__ == '__main__':
    main()
