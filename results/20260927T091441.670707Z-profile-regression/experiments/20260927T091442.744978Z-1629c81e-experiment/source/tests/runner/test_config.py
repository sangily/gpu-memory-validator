"""Configuration contracts shared by the CLI and local editor."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from experiment_config import (DEFAULTS, load_document, persist_inputs, resolve_config,
                               validate_patterns, validate_profile)

PATTERN = {'schema_version': 1, 'name': 'example', 'values': ['0X12345678', 'f', '12345678']}
PROFILE = {'schema_version': 1, 'name': 'smoke', 'pattern_file': '../patterns/example.json',
           'count': 257, 'iterations': 2, 'injection_enabled': True}


class ConfigTests(unittest.TestCase):
    def test_patterns_normalize_and_preserve_order(self):
        self.assertEqual(validate_patterns(PATTERN), ['12345678', '0000000f', '12345678'])
        self.assertEqual(len(validate_patterns({**PATTERN, 'values': ['f'] * 64})), 64)

    def test_reject_invalid_pattern_values(self):
        for values in ([], ['f'] * 65, [0], [True], ['100000000'], ['0x'], ['-1'], [' 1'], '1234'):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_patterns({**PATTERN, 'values': values})

    def test_profile_types_and_ranges(self):
        for field, value in [('count', True), ('count', 0), ('max_records', -1), ('iterations', 10001),
                             ('iterations', 2.0), ('injection_enabled', 1), ('telemetry_enabled', 'false'),
                             ('timeout_seconds', float('nan')), ('sample_interval', float('inf')),
                             ('pattern_file', '')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_profile({**PROFILE, field: value})
        self.assertEqual(validate_profile({**PROFILE, 'max_records': 0})['max_records'], 0)

    def test_schema_and_unknown_fields(self):
        for document in ([1], {**PATTERN, 'schema_version': True}, {**PATTERN, 'schema_version': 2},
                         {**PATTERN, 'name': ''}, {**PATTERN, 'value': ['1']}):
            with self.assertRaises(ValueError):
                validate_patterns(document)
        with self.assertRaises(ValueError):
            validate_profile({**PROFILE, 'interations': 2})

    def test_reject_duplicate_keys_and_oversize_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_text('{"count": 1, "count": 2}')
            with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                load_document(path)
            path.write_text(' ' * 65537)
            with self.assertRaisesRegex(ValueError, '64 KiB'):
                load_document(path)

    def test_resolution_precedence_relative_paths_and_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'patterns').mkdir()
            (root / 'profiles').mkdir()
            pattern = root / 'patterns/example.json'
            profile = root / 'profiles/smoke.json'
            original = json.dumps(PATTERN).encode()
            pattern.write_bytes(original)
            profile.write_text(json.dumps(PROFILE))
            settings, inputs = resolve_config(profile, overrides={'iterations': 3, 'injection_enabled': False})
            self.assertEqual(settings['patterns'], ['12345678', '0000000f', '12345678'])
            self.assertEqual(settings['count'], 257)
            self.assertEqual(settings['iterations'], 3)
            self.assertFalse(settings['injection_enabled'])
            self.assertEqual(settings['max_records'], DEFAULTS['max_records'])
            # Mutating the original after resolution must not change the run evidence.
            pattern.write_text(json.dumps({**PATTERN, 'values': ['0']}))
            output = root / 'result'
            output.mkdir()
            metadata = persist_inputs(output, settings, inputs)
            self.assertEqual((output / 'inputs/patterns.json').read_bytes(), original)
            self.assertEqual(metadata['patterns']['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(json.loads((output / 'resolved_config.json').read_text()), settings)
            other = root / 'other.json'
            other.write_text(json.dumps({**PATTERN, 'values': ['abc']}))
            resolved, _ = resolve_config(profile, other)
            self.assertEqual(resolved['patterns'], ['00000abc'])

    def test_default_configuration_without_files(self):
        settings, inputs = resolve_config()
        self.assertEqual(settings['patterns'], ['00000000', 'ffffffff', 'aaaaaaaa', '55555555'])
        self.assertEqual(settings['count'], 1025)
        self.assertEqual(inputs, {})


if __name__ == '__main__':
    unittest.main()
