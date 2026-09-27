#!/usr/bin/env python3
"""Check saved load logs against the independent oracle and summarize observations."""
import collections
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys

root = Path.cwd()
sys.path.insert(0, str(root / 'tests/cli'))
from test_load import check_batch

folder = Path(sys.argv[1])
run = json.loads((folder / 'run.json').read_text())
cfg = run['config']
count = cfg['count']
injections = {0: 1, count // 2: 3, count - 1: 1} if cfg['injection_enabled'] else {}
assert count > 2, 'This evidence summary expects three distinct injection targets.'
expected_status = 'FAIL' if injections else 'PASS'
assert run['status'] == expected_status and run['reason'] == 'COMPLETED'
assert run['child_exit_code'] == int(bool(injections))
assert run['provenance']['git_status']['stdout'] == '', 'Expect a clean source version at capture.'
text = (folder / 'stdout.txt').read_text()
check_batch(text, count, cfg['max_records'], cfg['iterations'], cfg['pattern_mode'],
            injections, cfg['inject_pass'], cfg['gpu_passes'])
batches = re.findall(r'^batch gpu_passes_completed=(\d+) first_failed_pass=(\d+) gpu_phase_host_ms=(\S+) cpu_phase_host_ms=(\S+)$', text, re.M)
samples = [json.loads(line) for line in (folder / 'telemetry.jsonl').read_text().splitlines()]
devices = {}
for sample in samples:
    for device in sample.get('devices', []):
        entry = devices.setdefault(device['uuid'], {'name': device['name'], 'metrics': {}})
        for key, metric in device['metrics'].items():
            stat = entry['metrics'].setdefault(key, {'values': [], 'status_counts': collections.Counter()})
            stat['status_counts'][metric['status']] += 1
            if metric['status'] == 'AVAILABLE':
                stat['values'].append(metric['value'])
for entry in devices.values():
    for stat in entry['metrics'].values():
        values = stat.pop('values')
        if values:
            stat.update(samples=len(values), minimum=min(values), median=statistics.median(values),
                        mean=statistics.mean(values), maximum=max(values))
summary = {
    'evidence_check': 'PASS', 'validator_status': run['status'],
    'git_head': run['provenance']['git_head']['stdout'].strip(),
    'process_elapsed_seconds': run['process_elapsed_seconds'],
    'cpu_checkpoints': len(batches),
    'gpu_passes_completed': sum(int(batch[0]) for batch in batches),
    'failed_batches': sum(int(batch[1]) != 0 for batch in batches),
    'gpu_phase_host_seconds': sum(float(batch[2]) for batch in batches) / 1000,
    'cpu_phase_host_seconds': sum(float(batch[3]) for batch in batches) / 1000,
    'telemetry_samples': len(samples),
    'telemetry_status_counts': collections.Counter(sample['status'] for sample in samples),
    'devices': devices,
    'scope': 'All collected samples, including startup/end; shared GPU metrics, not process attribution. Host phase times are not CUDA-event kernel timings.',
    'source_log_sha256': {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                          for name in ('run.json', 'stdout.txt', 'stderr.txt', 'telemetry.jsonl')},
}
print(json.dumps(summary, indent=2))
