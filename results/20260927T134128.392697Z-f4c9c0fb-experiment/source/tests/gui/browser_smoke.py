#!/usr/bin/env python3
"""Exercise the real browser UI in an isolated workspace with genuine saved logs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from workbench import create_server
from playwright.sync_api import sync_playwright, expect


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    evidence = ROOT / 'results' / (stamp + '-workbench-browser')
    evidence.mkdir()
    report = {'status': 'RUNNING', 'checks': [], 'source_sha256': {},
              'fixture': 'isolated editable workspace; copied genuine 128 MiB baseline run'}
    for path in [ROOT / 'scripts/workbench.py', ROOT / 'scripts/experiment_config.py',
                 *sorted((ROOT / 'web').glob('*')), Path(__file__), ROOT / 'tests/gui/test_workbench.py']:
        relative = path.relative_to(ROOT)
        data = path.read_bytes()
        report['source_sha256'][str(relative)] = hashlib.sha256(data).hexdigest()
        target = evidence / 'source' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'patterns', root / 'patterns')
            shutil.copytree(ROOT / 'profiles', root / 'profiles')
            origin = ROOT / 'results/20260927T085019.212400Z-2db5cbad-experiment'
            target = root / 'results/real-baseline'
            target.mkdir(parents=True)
            for name in ['run.json', 'stdout.txt', 'stderr.txt', 'telemetry.jsonl']:
                shutil.copyfile(origin / name, target / name)
            server = create_server(root, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    context = browser.new_context(viewport={'width': 1440, 'height': 1080},
                                                  permissions=['clipboard-read', 'clipboard-write'])
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
                    pending = []
                    page.route('**/api/state', lambda route: pending.append(route))
                    page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='domcontentloaded')
                    expect(page.locator('#search')).to_be_disabled()
                    expect(page.locator('nav button[data-view="patterns"]')).to_be_disabled()
                    expect(page.locator('#new-document')).to_be_disabled()
                    # Hold the initial response so loading-state behavior is deterministic.
                    page.wait_for_timeout(100)
                    assert len(pending) == 1
                    pending[0].continue_()
                    page.unroute('**/api/state')
                    expect(page.locator('#search')).to_be_enabled()
                    report['checks'].append('initial_load_blocks_premature_editing')
                    expect(page.locator('#detail h2')).to_have_text('정상 메모리 검증')
                    expect(page.locator('#detail .badge')).to_have_text('PASS')
                    expect(page.locator('#detail .chart svg')).to_be_visible()
                    page.get_by_role('button', name='run.json', exact=True).click()
                    expect(page.locator('#detail pre')).to_contain_text('"reported_completed_patterns": 16')
                    report['checks'].append('real_result_status_chart_raw_log')
                    page.screenshot(path=str(evidence / 'results.png'), full_page=True)

                    page.locator('nav button[data-view="patterns"]').click()
                    page.locator('#new-document').click()
                    page.locator('[name="filename"]').fill('browser-pattern.json')
                    page.locator('[name="name"]').fill('Browser smoke pattern')
                    page.locator('[name="mode"]').select_option('seeded')
                    page.locator('[name="values"]').fill('deadbeef\ndeadbeef\n0')
                    page.get_by_role('button', name='저장', exact=True).click()
                    expect(page.locator('#save-message')).to_contain_text('저장했습니다')
                    saved = root / 'patterns/browser-pattern.json'
                    assert json.loads(saved.read_text())['values'] == ['deadbeef', 'deadbeef', '0']
                    assert json.loads(saved.read_text())['mode'] == 'seeded'
                    expect(page.locator('[name="mode"]')).to_have_value('seeded')
                    report['checks'].append('create_seeded_pattern_ordered_duplicates')

                    before = saved.read_bytes()
                    page.locator('[name="values"]').fill('100000000')
                    page.get_by_role('button', name='저장', exact=True).click()
                    expect(page.locator('#save-message')).to_contain_text('hexadecimal')
                    assert saved.read_bytes() == before
                    report['checks'].append('invalid_pattern_rejected_without_mutation')
                    # The expected HTTP 400 is a validation outcome, not a JS error.
                    errors[:] = [error for error in errors if '400 (Bad Request)' not in error]

                    page.locator('[name="values"]').fill('12345678\n87654321')
                    page.get_by_role('button', name='저장', exact=True).click()
                    expect(page.locator('#save-message')).to_contain_text('저장했습니다')
                    page.get_by_role('button', name='실행 명령 복사', exact=True).click()
                    expect(page.locator('#save-message')).to_contain_text('복사했습니다')
                    clipboard = page.evaluate('navigator.clipboard.readText()')
                    assert '--pattern-file patterns/browser-pattern.json' in clipboard
                    report['checks'].append('edit_pattern_and_copy_command')
                    page.screenshot(path=str(evidence / 'pattern-editor.png'), full_page=True)

                    page.locator('nav button[data-view="profiles"]').click()
                    page.locator('#new-document').click()
                    page.locator('[name="filename"]').fill('browser-profile.json')
                    page.locator('[name="name"]').fill('Browser smoke profile')
                    page.locator('[name="pattern_file"]').select_option('../patterns/browser-pattern.json')
                    page.locator('[name="count"]').fill('257')
                    page.locator('[name="iterations"]').fill('2')
                    page.locator('[name="gpu_passes"]').fill('7')
                    page.locator('[name="inject_pass"]').fill('4')
                    page.locator('[name="injection_enabled"]').check()
                    page.get_by_role('button', name='저장', exact=True).click()
                    expect(page.locator('#save-message')).to_contain_text('저장했습니다')
                    profile = root / 'profiles/browser-profile.json'
                    content = json.loads(profile.read_text())
                    assert content['count'] == 257 and content['injection_enabled'] is True
                    assert content['gpu_passes'] == 7 and content['inject_pass'] == 4
                    assert content['pattern_file'] == '../patterns/browser-pattern.json'
                    report['checks'].append('create_profile_with_selected_pattern')

                    # Simulate an external edit after opening the document.
                    profile.write_text(json.dumps({**content, 'name': 'External edit'}))
                    page.locator('[name="name"]').fill('Would overwrite')
                    page.get_by_role('button', name='저장', exact=True).click()
                    expect(page.locator('#save-message')).to_contain_text('파일이 변경')
                    assert json.loads(profile.read_text())['name'] == 'External edit'
                    report['checks'].append('concurrent_edit_conflict_visible')
                    errors[:] = [error for error in errors if '409 (Conflict)' not in error]
                    page.on('dialog', lambda dialog: dialog.accept())
                    page.locator('#refresh').click()
                    expect(page.locator('[name="name"]')).to_have_value('External edit')
                    page.screenshot(path=str(evidence / 'profile-editor.png'), full_page=True)

                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.locator('nav button[data-view="runs"]').click()
                    expect(page.locator('#detail .badge')).to_have_text('PASS')
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    report['checks'].append('mobile_layout_without_horizontal_overflow')
                    page.screenshot(path=str(evidence / 'mobile.png'), full_page=True)
                    assert not errors, errors
                    report['checks'].append('no_unexpected_browser_errors')
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)
        report['status'] = 'PASS'
        print(f'checks={len(report["checks"])} status=PASS')
        return 0
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        print(str(error), file=sys.stderr)
        return 1
    finally:
        (evidence / 'run.json').write_text(json.dumps(report, indent=2) + '\n')
        print('evidence=' + str(evidence))


if __name__ == '__main__':
    raise SystemExit(main())
