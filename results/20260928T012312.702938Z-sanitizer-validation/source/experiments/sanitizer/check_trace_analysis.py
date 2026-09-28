"""Negative controls on a COPY of a real exported trace; never alter evidence."""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from profile import analyze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    source = args.evidence / 'read.sqlite'
    cases = [
        ('complete', None, False),
        ('no_gpu_trace', 'DROP TABLE CUPTI_ACTIVITY_KIND_KERNEL', True),
        ('lost_kernel', 'DELETE FROM CUPTI_ACTIVITY_KIND_KERNEL WHERE rowid=(SELECT MIN(rowid) FROM CUPTI_ACTIVITY_KIND_KERNEL)', True),
        ('lost_snapshot', 'DELETE FROM CUPTI_ACTIVITY_KIND_MEMCPY WHERE bytes=16777216', True),
        ('no_runtime_trace', 'DELETE FROM CUPTI_ACTIVITY_KIND_RUNTIME', True),
    ]
    results = []
    with tempfile.TemporaryDirectory() as temp:
        for name, mutation, should_reject in cases:
            dest = Path(temp) / (name + '.sqlite')
            shutil.copy2(source, dest)
            if mutation:
                with sqlite3.connect(dest) as db: db.execute(mutation)
            try:
                summary, _ = analyze(dest, 'read')
                rejected = summary['status'] != 'PASS'
                reason = summary['errors']
            except ValueError as error:
                rejected, reason = True, [str(error)]
            results.append({'name': name, 'mutation_on_copy': mutation,
                            'status': 'PASS' if rejected == should_reject else 'FAIL',
                            'analysis_rejected': rejected, 'reason': reason})
    report = {'status': 'PASS' if all(r['status'] == 'PASS' for r in results) else 'FAIL', 'checks': results}
    (args.evidence / 'analysis-controls.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return int(report['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
