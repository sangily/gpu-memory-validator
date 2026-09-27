#!/usr/bin/env python3
"""Submission audit of the existing test commands. Run from the repository root."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

ROOT = Path.cwd().resolve()
folder = ROOT / 'results' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-submission-verification')
folder.mkdir()
(folder / 'verify_commands.py').write_bytes(Path(__file__).read_bytes())
report = {'status': 'RUNNING', 'started_utc': datetime.now(timezone.utc).isoformat(), 'checks': []}
report['git_head'] = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
report['git_status_at_start'] = subprocess.check_output(['git','status','--porcelain'],text=True)
files = subprocess.check_output(['git','ls-files','-z'],text=True).split('\0')
report['tracked_file_sha256'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    for name in files if name and not name.startswith('results/') and (ROOT/name).is_file()}
(folder / 'run.json').write_text(json.dumps(report,indent=2)+'\n')
print('evidence='+str(folder),flush=True)
commands = [
 ('cpu_configure', ['cmake','-S','.','-B','build/submission-cpu','-DGMV_ENABLE_CUDA=OFF','-DCMAKE_BUILD_TYPE=Release']),
 ('cpu_build', ['cmake','--build','build/submission-cpu','-j','4']),
 ('cpu_only', ['ctest','--test-dir','build/submission-cpu','--output-on-failure']),
 ('cuda_configure', ['cmake','-S','.','-B','build/cuda','-DGMV_ENABLE_CUDA=ON','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CUDA_ARCHITECTURES=86']),
 ('cuda_clean_build', ['cmake','--build','build/cuda','--clean-first','-j','4']),
 ('cuda_ctest', ['ctest','--test-dir','build/cuda','--output-on-failure']),
 ('runner', [sys.executable,'-m','unittest','discover','-s','tests/runner','-v']),
 ('gui_server', [sys.executable,'-m','unittest','discover','-s','tests/gui','-v']),
 ('javascript', ['node','--check','web/app.js']),
 ('cli', [sys.executable,'tests/cli/test_validator.py']),
 ('profiles', [sys.executable,'tests/cli/test_profiles.py']),
 ('read_batch', [sys.executable,'tests/cli/test_load.py']),
 ('invert', [sys.executable,'tests/cli/test_invert.py']),
 ('spatial_large', [sys.executable,'tests/cli/test_spatial_matrix.py']),
 ('invert_large', [sys.executable,'tests/cli/test_invert_matrix.py']),
 ('pytorch_device', ['build/torch-env/bin/python','tests/pytorch/check_device_lab.py']),
 ('pytorch_layout', ['build/torch-env/bin/python','tests/pytorch/test_layout.py']),
 ('gui_browser', ['build/ui-env/bin/python','tests/gui/browser_smoke.py']),
]
try:
    assert not report['git_status_at_start'], 'Expected a clean source version.'
    for name, command in commands:
        entry={'name':name,'command':command,'status':'RUNNING'}
        report['checks'].append(entry)
        (folder/'run.json').write_text(json.dumps(report,indent=2)+'\n')
        start=time.monotonic()
        with (folder/(name+'.stdout.txt')).open('w') as out, (folder/(name+'.stderr.txt')).open('w') as err:
            p=subprocess.run(command,cwd=ROOT,stdout=out,stderr=err,timeout=1200)
        entry.update(exit_code=p.returncode,seconds=time.monotonic()-start,status='PASS' if p.returncode==0 else 'FAIL')
        stdout=(folder/(name+'.stdout.txt')).read_text()
        evidence=[]
        for match in re.finditer(r'^(?:evidence=|logs=)(.+)$',stdout,re.M):
            origin=Path(match[1])
            if origin.is_dir():
                evidence.append(str(origin.relative_to(ROOT)))
        entry['evidence']=evidence
        print(name+' '+entry['status']+f' {entry["seconds"]:.2f}s',flush=True)
        assert p.returncode==0, name+' failed; inspect its logs'
    report['status']='PASS'
except Exception as error:
    report.update(status='FAIL',error=str(error))
    (folder/'traceback.txt').write_text(traceback.format_exc())
finally:
    report['finished_utc']=datetime.now(timezone.utc).isoformat()
    report['binary_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path('build/cuda/gpu_memory_validator'),Path('build/torch-layout/gmv_layout_ops.so')) if p.is_file()}
    (folder/'run.json').write_text(json.dumps(report,indent=2)+'\n')
    print('status='+report['status'],flush=True)
raise SystemExit(0 if report['status']=='PASS' else 1)
