"""Local editor persistence and result-view contracts, without a GPU."""
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from workbench import Conflict, Store, create_server

PATTERN = {'schema_version': 1, 'name': 'Test pattern', 'values': ['12345678', '87654321']}
PROFILE = {'schema_version': 1, 'name': 'Test profile', 'pattern_file': '../patterns/test.json'}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.saved = self.store.save('patterns', 'test.json', PATTERN, None)

    def tearDown(self):
        self.temp.cleanup()

    def test_create_edit_conflict_and_validation(self):
        self.assertEqual(self.saved['resolved']['patterns'], ['12345678', '87654321'])
        with self.assertRaises(Conflict):
            self.store.save('patterns', 'test.json', PATTERN, None)
        updated = self.store.save('patterns', 'test.json', {**PATTERN, 'values': ['ff']}, self.saved['sha256'])
        self.assertEqual(updated['resolved']['patterns'], ['000000ff'])
        with self.assertRaises(Conflict):
            self.store.save('patterns', 'test.json', PATTERN, self.saved['sha256'])
        with self.assertRaises(ValueError):
            self.store.save('patterns', 'invalid.json', {**PATTERN, 'values': []}, None)
        self.assertFalse((self.root / 'patterns/invalid.json').exists())

    def test_profile_reference_and_command(self):
        saved = self.store.save('profiles', 'test.json', PROFILE, None)
        self.assertEqual(saved['resolved']['patterns'], ['12345678', '87654321'])
        self.assertIn('--profile profiles/test.json', saved['command'])
        with self.assertRaises(OSError):
            self.store.save('profiles', 'missing.json', {**PROFILE, 'pattern_file': '../patterns/missing.json'}, None)
        with self.assertRaises(ValueError):
            self.store.save('profiles', 'outside.json', {**PROFILE, 'pattern_file': '../../outside.json'}, None)

    def test_paths_and_symlinks_cannot_escape(self):
        for name in ['../test.json', '/tmp/test.json', 'x;echo.json']:
            with self.assertRaises(ValueError):
                self.store.save('patterns', name, PATTERN, None)
        (self.root / 'patterns/link.json').symlink_to(self.root / 'outside.json')
        with self.assertRaises(ValueError):
            self.store.save('patterns', 'link.json', PATTERN, None)
        with self.assertRaises(ValueError):
            self.store.run('../../outside')

    def test_invalid_document_remains_editable(self):
        path = self.root / 'patterns/test.json'
        path.write_text(json.dumps({**PATTERN, 'values': []}))
        entry, = self.store.documents('patterns')
        self.assertIn('error', entry)
        self.assertEqual(entry['document']['values'], [])
        self.assertEqual(entry['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.store.save('patterns', 'test.json', PATTERN, entry['sha256'])

    def test_results_keep_error_missing_metrics_and_truncation(self):
        folder = self.root / 'results/experiment'
        folder.mkdir(parents=True)
        report = {'schema_version': 1, 'run_id': 'example', 'status': 'ERROR', 'reason': 'TIMEOUT',
                  'started_utc': '2026-09-27T00:00:00Z', 'config': {}, 'telemetry': {'status': 'AVAILABLE'}}
        (folder / 'run.json').write_text(json.dumps(report))
        (folder / 'stdout.txt').write_text('x' * (2*1024*1024+1))
        sample = {'elapsed_seconds': 0, 'devices': [{'uuid': 'test', 'metrics': {'power_w': {'status': 'UNAVAILABLE', 'value': None}}}]}
        (folder / 'telemetry.jsonl').write_text(json.dumps(sample) + '\ninvalid\n')
        result = self.store.run('experiment')
        self.assertEqual(result['report']['status'], 'ERROR')
        self.assertIsNone(result['samples'][0]['devices'][0]['metrics']['power_w']['value'])
        self.assertEqual(result['malformed_samples'], 1)
        self.assertTrue(result['logs']['stdout.txt']['truncated'])
        self.assertFalse(result['logs']['stderr.txt']['available'])
        self.assertEqual(len(self.store.runs()['entries']), 1)
        nested = folder / 'source'
        nested.mkdir()
        (nested / 'run.json').write_text('{"status":"PASS","runs":[]}')
        self.assertEqual(len(self.store.runs()['entries']), 1)


class HttpTests(unittest.TestCase):
    def test_same_origin_token_required_for_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(Path(directory), 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = f'http://127.0.0.1:{server.server_port}'
            def request(method, path, body=None, headers=None):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                connection.request(method, path, body=body, headers=headers or {})
                response = connection.getresponse()
                data = response.read()
                status = response.status
                connection.close()
                return status, data
            try:
                status, raw = request('GET', '/api/state')
                self.assertEqual(status, 200)
                token = json.loads(raw)['token']
                payload = json.dumps({'kind':'patterns','filename':'test.json','document':PATTERN})
                status, _ = request('POST', '/api/document', payload)
                self.assertEqual(status, 403)
                headers={'Content-Type':'application/json','Origin':origin,'X-Workbench-Token':token}
                status, _ = request('POST', '/api/document', payload, {**headers, 'Origin':'http://elsewhere.test'})
                self.assertEqual(status, 403)
                status, _ = request('POST', '/api/document', payload, headers)
                self.assertEqual(status, 200)
                status, _ = request('GET', '/api/state', headers={'Host':'elsewhere.test'})
                self.assertEqual(status, 403)
                status, _ = request('GET', '/api/run?id=../../outside')
                self.assertEqual(status, 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)


if __name__ == '__main__':
    unittest.main()
