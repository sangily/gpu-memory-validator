#!/usr/bin/env python3
"""Capture a local, unprivileged DCGM discovery / Level 1 attempt.

Use an extracted NVIDIA package tree; this does not install a system service.
Raw diagnostic output must be reviewed: a zero exit alone is not a health verdict.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-root', type=Path, default=ROOT / 'build/dcgm-4.6.1/root')
    args = parser.parse_args()
    package = args.package_root.resolve()
    executable = package / 'usr/bin/dcgmi'
    engine = package / 'usr/bin/nv-hostengine'
    if not executable.is_file() or not engine.is_file():
        parser.error('Extract DCGM core and CUDA runtime packages first; see docs/DCGM.md')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    folder = ROOT / 'results' / (stamp + '-dcgm')
    folder.mkdir(parents=True)
    shutil.copyfile(__file__, folder / 'probe.py')
    if (package.parent / 'packages.json').is_file():
        shutil.copyfile(package.parent / 'packages.json', folder / 'packages.json')
    env = os.environ.copy()
    overrides = {
        'LD_LIBRARY_PATH': ':'.join([str(package / 'usr/lib/x86_64-linux-gnu'), '/usr/lib/wsl/lib',
                                    *([env['LD_LIBRARY_PATH']] if env.get('LD_LIBRARY_PATH') else [])]),
        'NVVS_BIN_PATH': str(package / 'usr/libexec/datacenter-gpu-manager-4'),
        'NVVS_PLUGIN_DIR': str(package / 'usr/libexec/datacenter-gpu-manager-4/plugins'),
    }
    env.update(overrides)
    report = {'started_utc': stamp, 'capture_status': 'RUNNING', 'commands': [],
              'installation': 'extracted NVIDIA packages, unprivileged foreground engine, private Unix socket',
              'environment_overrides': overrides, 'platform': os.uname().release,
              'device_nodes': {'dxg_exists': Path('/dev/dxg').exists(),
                               'nvidia_nodes': [str(p) for p in Path('/dev').glob('nvidia*')]},
              'diagnostic_verdict': 'REVIEW_RAW_OUTPUT',
              'note': 'Not a hardware health verdict. Unsupported/skipped/unexecuted tests are not PASS.',
              'executable_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in (executable, engine)}}

    def capture(name, command, timeout=15):
        started = time.monotonic()
        with (folder / f'{name}.stdout.txt').open('w') as stdout, (folder / f'{name}.stderr.txt').open('w') as stderr:
            child = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env, cwd=folder,
                                     start_new_session=True)
            timed_out = False
            try:
                child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        report['commands'].append({'name': name, 'command': command, 'exit_code': child.returncode,
                                   'timed_out': timed_out, 'elapsed_seconds': time.monotonic() - started})
        return child.returncode

    process = None
    try:
        smi = shutil.which('nvidia-smi') or '/usr/lib/wsl/lib/nvidia-smi'
        capture('nvidia-smi', [smi])
        capture('version', [str(executable), '--version'])
        with tempfile.TemporaryDirectory(prefix='gmv-dcgm-') as temp:
            socket = str(Path(temp) / 'engine.sock')
            command = [str(engine), '-n', '-d', socket, '--pid', str(Path(temp) / 'engine.pid'),
                       '-f', str(folder / 'hostengine.log'), '--log-level', 'DEBUG',
                       '--home-dir', str(folder)]
            report['engine_command'] = command
            with (folder / 'engine.stdout.txt').open('w') as stdout, (folder / 'engine.stderr.txt').open('w') as stderr:
                process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env,
                                           cwd=folder, start_new_session=True)
                try:
                    deadline = time.monotonic() + 10
                    while not Path(socket).exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.1)
                    report['socket_created'] = Path(socket).exists()
                    capture('discovery', [str(executable), 'discovery', '--host', 'unix://' + socket, '-l'])
                    capture('telemetry', [str(executable), 'dmon', '--host', 'unix://' + socket,
                                          '-i', '0', '-e', '150,155,203,204', '-c', '3', '-d', '1000'])
                    code = capture('diag-level1', [str(executable), 'diag', '--host', 'unix://' + socket,
                                                  '-r', '1', '-i', '0', '-j', '-t', '30'], timeout=40)
                    report['diagnostic_exit_code'] = code
                    report['capture_status'] = 'CAPTURED'
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                    report['engine_exit_code'] = process.returncode
        return 0 if code == 0 else 2
    except Exception as error:
        report.update(capture_status='ERROR', error=str(error))
        return 2
    finally:
        (folder / 'dcgm_lab.json').write_text(json.dumps(report, indent=2) + '\n')
        print('evidence=' + str(folder))
        print('capture_status=' + report['capture_status'] + ' diagnostic_verdict=REVIEW_RAW_OUTPUT')


if __name__ == '__main__':
    raise SystemExit(main())
