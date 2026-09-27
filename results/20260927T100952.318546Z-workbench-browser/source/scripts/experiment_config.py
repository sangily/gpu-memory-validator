"""Shared validation and resolution for experiment CLI and the future local GUI."""
import hashlib
import json
import math
from pathlib import Path
import re

DEFAULT_PATTERNS = ['00000000', 'ffffffff', 'aaaaaaaa', '55555555']
DEFAULTS = dict(count=1025, max_records=3, iterations=1, injection_enabled=False,
                timeout_seconds=60.0, sample_interval=1.0, telemetry_enabled=True)


def validate_header(document, allowed):
    if not isinstance(document, dict):
        raise ValueError('document must be a JSON object')
    if set(document) - allowed:
        raise ValueError('unknown fields: ' + ', '.join(sorted(set(document) - allowed)))
    if type(document.get('schema_version')) is not int or document['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    if not isinstance(document.get('name'), str) or not document['name'].strip() or len(document['name']) > 120:
        raise ValueError('name must be a non-empty string of at most 120 characters')
    if 'description' in document and (not isinstance(document['description'], str) or len(document['description']) > 4096):
        raise ValueError('description must be a string of at most 4096 characters')


def validate_patterns(document):
    validate_header(document, {'schema_version', 'name', 'description', 'values'})
    values = document.get('values')
    if not isinstance(values, list) or not 1 <= len(values) <= 64:
        raise ValueError('values must contain 1..64 hexadecimal strings')
    normalized = []
    for value in values:
        if not isinstance(value, str) or not re.fullmatch(r'(?:0[xX])?[0-9a-fA-F]{1,8}', value):
            raise ValueError('each pattern must be a 1..8 digit hexadecimal string, optionally prefixed with 0x')
        normalized.append(f'{int(value, 16):08x}')
    # Ordered duplicates are valid: testing the same constant again is a new pass.
    return normalized


def validate_settings(settings):
    for name, low, high in [('count', 1, 2**32-1), ('max_records', 0, 2**32-1), ('iterations', 1, 10000)]:
        value = settings[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{name} must be an integer in {low}..{high}')
    for name in ['injection_enabled', 'telemetry_enabled']:
        if type(settings[name]) is not bool:
            raise ValueError(f'{name} must be boolean')
    for name in ['timeout_seconds', 'sample_interval']:
        value = settings[name]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be finite and positive')
    return settings


def validate_profile(document):
    validate_header(document, {'schema_version', 'name', 'description', 'pattern_file', *DEFAULTS})
    pattern_file = document.get('pattern_file')
    if not isinstance(pattern_file, str) or not pattern_file.strip():
        raise ValueError('pattern_file must be a non-empty path string')
    return validate_settings({**DEFAULTS, **{k: document[k] for k in DEFAULTS if k in document}})


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def load_document(path):
    path = Path(path).resolve()
    with path.open('rb') as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError('configuration document exceeds 64 KiB')
    document = json.loads(raw.decode('utf-8'), object_pairs_hook=reject_duplicate_keys)
    return document, {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'text': raw.decode('utf-8')}


def resolve_config(profile=None, pattern_file=None, overrides=None):
    settings = dict(DEFAULTS)
    inputs = {}
    if profile is not None:
        document, inputs['profile'] = load_document(profile)
        settings = validate_profile(document)
        if pattern_file is None:
            pattern_file = Path(inputs['profile']['path']).parent / document['pattern_file']
    settings.update({key: value for key, value in (overrides or {}).items() if value is not None})
    if set(settings) != set(DEFAULTS):
        raise ValueError('unknown setting override')
    validate_settings(settings)
    patterns = list(DEFAULT_PATTERNS)
    if pattern_file is not None:
        document, inputs['patterns'] = load_document(pattern_file)
        patterns = validate_patterns(document)
    return {**settings, 'patterns': patterns}, inputs


def persist_inputs(folder, settings, inputs):
    (folder / 'resolved_config.json').write_text(json.dumps(settings, indent=2) + '\n')
    metadata = {}
    for name, source in inputs.items():
        target = folder / 'inputs' / f'{name}.json'
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(source['text'].encode('utf-8'))
        metadata[name] = {'source_path': source['path'], 'sha256': source['sha256'],
                          'snapshot': str(target.relative_to(folder))}
    return metadata
