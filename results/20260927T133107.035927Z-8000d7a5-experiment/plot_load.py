#!/usr/bin/env python3
"""Render the saved telemetry; no smoothing or per-process attribution."""
import json
from pathlib import Path
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

folder = Path(sys.argv[1])
rows = [json.loads(line) for line in (folder / 'telemetry.jsonl').read_text().splitlines()]
uuids = {device['uuid'] for row in rows for device in row.get('devices', [])}
assert len(uuids) == 1, 'Select a GPU explicitly for multi-device captures.'
fig, axes = plt.subplots(3, 1, figsize=(10, 7), sharex=True, layout='constrained')
for ax, key, label, color in zip(axes, ('gpu_util_percent', 'temperature_c', 'power_w'),
                                ('GPU utilization (%)', 'Temperature (C)', 'Power (W)'),
                                ('#2563eb', '#dc2626', '#059669')):
    x, y = [], []
    for row in rows:
        x.append(row['elapsed_seconds'])
        device = next(iter(row.get('devices', [])), {})
        metric = device.get('metrics', {}).get(key, {})
        y.append(metric['value'] if metric.get('status') == 'AVAILABLE' else float('nan'))
    ax.plot(x, y, color=color, linewidth=1)
    ax.set_ylabel(label)
    ax.grid(alpha=.2)
axes[0].set_ylim(-3, 103)
axes[-1].set_xlabel('Seconds since telemetry capture began')
fig.suptitle('RTX 3060 / WSL2: 256 MiB repeated-read validation\nDevice-wide observations; includes startup and CPU checkpoints', fontsize=12)
fig.savefig(folder / 'telemetry.png', dpi=150)
fig.savefig(folder / 'telemetry.svg')

# Matplotlib SVG paths contain insignificant trailing spaces.
svg = folder / 'telemetry.svg'
svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
