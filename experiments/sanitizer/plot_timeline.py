"""Plot actual Nsight timestamps for the first CPU checkpoint of each mode."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    colors = {'fill_pattern': '#0f766e', 'verify_pattern': '#2563eb',
              'latch_failure': '#a855f7', 'invert_words': '#d97706',
              'D2H snapshot': '#dc2626', 'CUDA API': '#64748b'}
    fig, axes = plt.subplots(2, 1, figsize=(11, 5.5), layout='constrained')
    for access, ax in zip(('read', 'invert'), axes):
        events = json.loads((args.evidence / (access + '-events.json')).read_text())
        start = events['kernels'][0]['start']
        snapshot = next(e for e in events['copies'] if e['bytes'] == 16777216 and e['copyKind'] == 2)
        end = snapshot['end']
        groups = [(events['runtime_apis'], 2, 'CUDA API'),
                  (events['kernels'], 1, None), ([snapshot], 0, 'D2H snapshot')]
        for rows, y, fixed in groups:
            for row in rows:
                left, right = max(start, row['start']), min(end, row['end'])
                if right <= left: continue
                ax.broken_barh([((left - start) / 1e6, (right - left) / 1e6)],
                               (y - .3, .6), facecolors=colors[fixed or row['name']])
        ax.set_yticks([0, 1, 2], ['GPU copy', 'GPU kernels', 'Host CUDA API'])
        ax.set_xlim(0, (end - start) / 1e6)
        ax.set_ylim(-.6, 2.7)
        ax.set_title(f'{access}: first checkpoint, 16 MiB / 32 verify passes', loc='left')
        ax.set_xlabel('Time since first fill kernel (ms)')
        ax.grid(axis='x', alpha=.2)
        ax.spines[['top', 'right']].set_visible(False)
    fig.legend(handles=[Patch(color=v, label=k) for k,v in colors.items()],
               loc='outside upper center', ncol=3, frameon=False)
    fig.suptitle('Instrumented CUDA timeline: API waits overlap GPU work', y=1.07, fontsize=13)
    fig.savefig(args.evidence / 'timeline.png', dpi=160, bbox_inches='tight')
    print(args.evidence / 'timeline.png')


if __name__ == '__main__':
    main()
