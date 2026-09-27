#!/usr/bin/env python3
"""Loopback-only editor and read-only result viewer; no GPU execution endpoint."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import shlex
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

from experiment_config import (DEFAULTS, load_document, reject_duplicate_keys,
                               validate_patterns, validate_profile)

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'web'


class Conflict(ValueError):
    pass


def contained(base, relative):
    base = base.resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        raise ValueError('workspace 밖의 경로는 사용할 수 없습니다.')
    return path


def read_text(path, limit=2 * 1024 * 1024):
    if not path.exists():
        return {'text': '', 'available': False, 'truncated': False}
    with path.open('rb') as source:
        data = source.read(limit + 1)
    return {'text': data[:limit].decode('utf-8', errors='replace'),
            'available': True, 'truncated': len(data) > limit}


class Store:
    def __init__(self, root):
        self.root = root.resolve()
        self.lock = threading.Lock()

    def path(self, kind, filename):
        if kind not in ('patterns', 'profiles'):
            raise ValueError('지원하지 않는 문서 종류입니다.')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\.json', filename):
            raise ValueError('파일명은 영문·숫자·점·밑줄·하이픈으로 작성하고 .json으로 끝내세요.')
        return contained(self.root / kind, filename)

    def validate(self, kind, document, filename):
        path = self.path(kind, filename)
        if kind == 'patterns':
            return {'patterns': validate_patterns(document)}
        settings = validate_profile(document)
        pattern = contained(self.root / 'patterns',
                            str((path.parent / document['pattern_file']).resolve()))
        if pattern.suffix != '.json':
            raise ValueError('JSON 패턴 파일을 선택하세요.')
        data, _ = load_document(pattern)
        return {**settings, 'patterns': validate_patterns(data)}

    def command(self, kind, filename):
        option = '--profile' if kind == 'profiles' else '--pattern-file'
        return 'cd ' + shlex.quote(str(self.root)) + '\nsource cuda-env.sh\n' + shlex.join(
            ['python3', 'scripts/run_experiment.py', option, f'{kind}/{filename}'])

    def documents(self, kind):
        result = []
        for path in sorted((self.root / kind).glob('*.json')):
            entry = {'filename': path.name}
            try:
                path = self.path(kind, path.name)
                document, source = load_document(path)
                entry.update(document=document, sha256=source['sha256'], command=self.command(kind, path.name))
                entry['resolved'] = self.validate(kind, document, path.name)
            except (OSError, ValueError) as error:
                entry['error'] = str(error)
            result.append(entry)
        return result

    def save(self, kind, filename, document, expected):
        resolved = self.validate(kind, document, filename)
        raw = (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode()
        if len(raw) > 65536:
            raise ValueError('설정 파일은 64 KiB 이하여야 합니다.')
        path = self.path(kind, filename)
        with self.lock:
            current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            if current != expected:
                raise Conflict('파일이 변경되었거나 같은 이름이 이미 있습니다. 새로고침 후 다시 저장하세요.')
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
                    temporary = Path(output.name)
                    output.write(raw)
                temporary.replace(path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return {'filename': filename, 'document': document, 'sha256': hashlib.sha256(raw).hexdigest(),
                'resolved': resolved, 'command': self.command(kind, filename)}

    def runs(self):
        results = self.root / 'results'
        entries = []
        unreadable = 0
        for path in sorted(results.rglob('run.json'), reverse=True):
            try:
                path = contained(results, str(path.relative_to(results)))
                content = read_text(path)
                if content['truncated']:
                    raise ValueError('oversized run.json')
                report = json.loads(content['text'])
                # Test-suite and performance manifests are different schemas.
                if not isinstance(report, dict):
                    raise ValueError('invalid report object')
                if report.get('schema_version') != 1 or not isinstance(report.get('run_id'), str):
                    continue
                if not isinstance(report.get('config'), dict):
                    raise ValueError('invalid config object')
                entries.append({'id': str(path.parent.relative_to(results)),
                                'run_id': report['run_id'], 'started_utc': report.get('started_utc'),
                                'status': report.get('status'), 'reason': report.get('reason'),
                                'config': report.get('config', {}),
                                'elapsed': report.get('process_elapsed_seconds')})
            except (OSError, ValueError, AttributeError):
                unreadable += 1
        return {'entries': sorted(entries, key=lambda x: x['started_utc'] or '', reverse=True),
                'unreadable': unreadable}

    def run(self, identifier):
        folder = contained(self.root / 'results', identifier)
        content = read_text(contained(folder, 'run.json'))
        if not content['available'] or content['truncated']:
            raise ValueError('실행 기록을 읽을 수 없습니다.')
        report = json.loads(content['text'])
        if not isinstance(report, dict) or report.get('schema_version') != 1 or not report.get('run_id') or not isinstance(report.get('config'), dict):
            raise ValueError('실험 실행기 기록을 선택하세요.')
        logs = {name: read_text(contained(folder, name)) for name in
                ('stdout.txt', 'stderr.txt', 'resolved_config.json', 'inputs/profile.json', 'inputs/patterns.json')}
        raw = read_text(contained(folder, 'telemetry.jsonl'))
        samples = []
        malformed = 0
        lines = raw['text'].splitlines()
        for line in lines:
            try:
                sample = json.loads(line)
                if not isinstance(sample, dict):
                    raise ValueError('invalid sample')
                devices = sample.get('devices', [])
                if not isinstance(devices, list) or any(not isinstance(device, dict) for device in devices):
                    raise ValueError('invalid devices')
                samples.append(sample)
            except ValueError:
                malformed += 1
        return {'report': report, 'logs': logs, 'samples': samples,
                'telemetry_truncated': raw['truncated'], 'malformed_samples': malformed}


def create_server(root, port=8765):
    store = Store(root)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send(self, status, body, content_type='application/json; charset=utf-8'):
            data = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, (dict, list)) else body
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def local_host(self):
            port = self.server.server_port
            return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

        def do_GET(self):
            if not self.local_host():
                return self.send(403, {'error': 'local host only'})
            url = urlsplit(self.path)
            try:
                if url.path == '/api/state':
                    return self.send(200, {'token': token, 'patterns': store.documents('patterns'),
                                           'profiles': store.documents('profiles'), 'runs': store.runs(),
                                           'defaults': DEFAULTS})
                if url.path == '/api/run':
                    return self.send(200, store.run(parse_qs(url.query).get('id', [''])[0]))
                assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                          '/style.css': ('style.css', 'text/css; charset=utf-8')}
                if url.path in assets:
                    name, mime = assets[url.path]
                    return self.send(200, (ASSETS / name).read_bytes(), mime)
                if url.path == '/favicon.ico':
                    return self.send(204, b'')
                return self.send(404, {'error': 'not found'})
            except (OSError, ValueError) as error:
                return self.send(400, {'error': str(error)})

        def do_POST(self):
            origin = f'http://{self.headers.get("Host", "")}'
            if (not self.local_host() or self.headers.get('Origin') != origin
                    or not secrets.compare_digest(self.headers.get('X-Workbench-Token', ''), token)):
                return self.send(403, {'error': '이 화면에서 요청을 다시 보내세요.'})
            if self.path != '/api/document':
                return self.send(404, {'error': 'not found'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 131072:
                    raise ValueError('잘못된 요청 크기입니다.')
                data = json.loads(self.rfile.read(length), object_pairs_hook=reject_duplicate_keys)
                if not isinstance(data, dict):
                    raise ValueError('JSON object required')
                result = store.save(data['kind'], data['filename'], data['document'], data.get('expected_sha256'))
                return self.send(200, result)
            except Conflict as error:
                return self.send(409, {'error': str(error)})
            except (OSError, ValueError, KeyError, TypeError) as error:
                return self.send(400, {'error': str(error)})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--root', type=Path, default=ROOT, help='workspace root (also used by isolated tests)')
    args = parser.parse_args()
    server = create_server(args.root, args.port)
    print(f'workbench=http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
