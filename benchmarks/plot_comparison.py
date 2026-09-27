#!/usr/bin/env python3
"""Create a standalone figure from an existing comparison; never run the GPU."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    if report['status'] != 'PASS':
        parser.error('comparison must have completed successfully')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    sizes = report['config']['mib']
    fig, axes = plt.subplots(1, len(sizes), figsize=(10, 5.4), squeeze=False)
    colors = ['#8795a1', '#087f8c']
    maximum = max(row['elapsed_seconds'] for row in report['runs'] if not row['warmup'])
    for ax, mib in zip(axes[0], sizes):
        data = [[row['elapsed_seconds'] for row in report['runs']
                 if row['mib'] == mib and row['variant'] == variant and not row['warmup']]
                for variant in ['baseline', 'candidate']]
        boxes = ax.boxplot(data, positions=[0, 1], widths=0.42, patch_artist=True,
                           showfliers=False, medianprops={'color': '#17212b', 'linewidth': 2})
        for box, color in zip(boxes['boxes'], colors):
            box.set_facecolor(color)
            box.set_alpha(0.4)
        for i, (left, right) in enumerate(zip(*data)):
            jitter = ((i % 5) - 2) * 0.027
            ax.plot([jitter, 1+jitter], [left, right], color='#bbc6cf', alpha=0.6, linewidth=0.7, zorder=1)
            ax.scatter([jitter, 1+jitter], [left, right], c=colors, s=23, zorder=3)
        summary = report['summaries'][str(mib)]
        reduction = summary['median_time_reduction_percent']
        for i, variant in enumerate(['baseline', 'candidate']):
            value = summary[variant]['elapsed_seconds']['median']
            ax.text(i, max(data[i]) + maximum * .045, f'median {value:.3f} s', ha='center', fontsize=10)
        ax.set_title(f'{mib} MiB | median time reduced {reduction:.1f}%', fontsize=11, pad=12)
        ax.set_xticks([0, 1], ['Allocate each pattern', 'Reuse host buffer'])
        ax.set_ylim(0, maximum * 1.23)
        ax.set_ylabel('End-to-end process time (seconds)')
        ax.grid(axis='y', alpha=0.2)
        ax.spines[['top', 'right']].set_visible(False)
    fig.suptitle('CPU snapshot reuse: full validation retained', fontsize=16, y=.98)
    iterations = report['config']['iterations']
    samples = report['config']['samples_per_variant_size']
    fig.text(.5, .035, f'RTX 3060 / WSL2 | {iterations} iterations x 4 patterns | {samples} runs per variant and size\n'
             'All samples shown; paired AB/BA order. Includes initialization, copies, CPU reference, output and cleanup.',
             ha='center', fontsize=9, color='#465562')
    fig.tight_layout(rect=(0, .105, 1, .93))
    for extension in ['png', 'pdf']:
        destination = args.report.parent / f'comparison.{extension}'
        fig.savefig(destination, dpi=180, bbox_inches='tight')
        print(destination)


if __name__ == '__main__':
    main()
