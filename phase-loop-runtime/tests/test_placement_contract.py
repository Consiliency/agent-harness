"""Cross-language contract drift, official-generator parity and wire vectors."""
from datetime import datetime
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import jsonschema
import pytest
import rfc8785

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('emit_placement_contract', ROOT / 'scripts/emit_placement_contract.py')
emitter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(emitter)
OUT = emitter.OUTPUT
VECTORS = json.loads((OUT / 'vectors/wire.json').read_text())


def assert_no_drift(directory):
    for name, expected in emitter.emit(emitter.SOURCE.read_bytes()).items():
        assert (directory / name).read_bytes() == expected, name


def test_drift():
    assert emitter.VERSION == importlib.metadata.version("baml-bridge")
    assert_no_drift(OUT)


def test_negative_control(tmp_path):
    for name in emitter.emit(emitter.SOURCE.read_bytes()):
        shutil.copy(OUT / name, tmp_path / name)
    target = tmp_path / 'placement_contract.gen.ts'
    target.write_text(target.read_text().replace('"at_capacity"', '"CORRUPTED"', 1))
    with pytest.raises(AssertionError, match='placement_contract.gen.ts'):
        assert_no_drift(tmp_path)


@pytest.mark.parametrize('vector', VECTORS['valid'], ids=lambda v: v['type']+'-'+v['name'])
def test_valid(vector):
    assert not list(validator(vector['type']).iter_errors(vector['value']))


@pytest.mark.parametrize('vector', VECTORS['invalid'], ids=lambda v: v['type']+'-'+v['name'])
def test_invalid(vector):
    errors = list(validator(vector['type']).iter_errors(vector['value']))
    # Some constraints sit alongside a $ref: collect nested anyOf errors too.
    def keywords(error):
        return {error.validator}.union(*(keywords(e) for e in error.context))
    assert errors
    assert vector['keyword'] in set().union(*(keywords(e) for e in errors))


def validator(name):
    schema = json.loads((OUT / 'coordinator-v1.schema.json').read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    checker = jsonschema.FormatChecker()
    @checker.checks('date-time', raises=ValueError)
    def utc_timestamp(value):
        if not isinstance(value, str):
            return True
        datetime.fromisoformat(value.upper().replace('Z', '+00:00'))
        return value.upper().endswith(('Z', '+00:00')) and 'T' in value.upper()
    return jsonschema.Draft202012Validator({**schema, '$ref': '#/$defs/'+name}, format_checker=checker)


def test_digest_vectors():
    for vector in json.loads((OUT / 'vectors/policy-digests.json').read_text()):
        encoded = rfc8785.dumps(vector['policy'])
        assert encoded == vector['jcs_utf8'].encode()
        assert hashlib.sha256(encoded).hexdigest() == vector['sha256']


def test_type_only_ts():
    text = (OUT / 'placement_contract.gen.ts').read_text()
    assert not re.search(r'\b(enum|class|import)\b', text)
    assert not re.search(r'^export (?!type |interface |const \w+Values = )', text, re.M)
    node = shutil.which('node')
    if not node:
        pytest.skip('node absent')
    subprocess.run([node, '--experimental-strip-types', str(OUT / 'placement_contract.gen.ts')], check=True, capture_output=True, text=True)


@pytest.mark.parametrize('source', [
    'function X() -> string {}', 'class X {\n a float\n}',
    'class X {\n a string | int\n}', 'class X {\n a map<string, string>\n}',
    'class X {\n policy map<string, baml.json.json>\n}',
    'class CreateBody {\n other map<string, baml.json.json>\n}',
    'enum E {\n a @skip\n}', 'class X {\n a Missing\n}',
    'class X {\n a string\n a int\n}', 'class X {} class X {}',
    'class X {\n a string; evil\n}', 'enum E {\n a\n a\n}',
])
def test_restricted_parser(source):
    with pytest.raises(ValueError):
        emitter.parse(source)


def test_mapping():
    from phase_loop_runtime import placement_contract as p
    from phase_loop_runtime.sandbox_placement import PLACEMENT_CODES
    assert set(p.ADMISSION_OUTCOMES) == set(p.OUTCOME_CODES)
    assert set(p.ERROR_CODES) == set(p.COORDINATOR_CODES)
    assert set(p.OUTCOME_CODES.values()) - {None} <= PLACEMENT_CODES
    assert set(p.COORDINATOR_CODES.values()) - {None} <= PLACEMENT_CODES
    assert p.outcome_code('timeout') == 'sandbox_placement_operation_timeout'
    assert p.coordinator_code('deadline_exceeded') == p.outcome_code('timeout')
    assert p.coordinator_code('unknown_lease') is None
    assert p.coordinator_code('owner_mismatch') == 'sandbox_placement_identity_mismatch'


def test_parity(tmp_path):
    # CI (the baml-sources job) sets PLACEMENT_PARITY_REQUIRED=1 so this can never
    # pass by skipping there. Locally, another baml-cli on PATH (for example the
    # legacy npm one) is skipped, not run.
    required = os.environ.get('PLACEMENT_PARITY_REQUIRED') == '1'
    def unavailable(why):
        if required:
            pytest.fail(why)
        pytest.skip(why)
    cli = shutil.which('baml-cli')
    if not cli:
        unavailable('pinned baml-cli absent')
    env = {**os.environ, 'BAML_AGENT_SKILL_CHECK': 'off', 'BAML_TELEMETRY': 'off', 'BOUNDARY_API_KEY': 'local'}
    probe = subprocess.run([cli, '--version'], env=env, capture_output=True, text=True)
    if probe.returncode != 0 or probe.stdout.strip() != 'baml-cli ' + emitter.VERSION:
        unavailable(f'baml-cli on PATH is not the pinned {emitter.VERSION}: {(probe.stdout or probe.stderr).strip()[:80]!r}')
    def run(*args):
        return subprocess.run([cli, '--agent-skill-check', 'off', *args], env=env, check=True, capture_output=True, text=True).stdout
    (tmp_path / 'baml_src').mkdir()
    shutil.copy(emitter.SOURCE, tmp_path / 'baml_src/placement_contract.baml')
    (tmp_path / 'baml.toml').write_text('[package]\nname = "placement_parity"\n[generator.ts]\noutput_type = "typescript/node"\noutput_dir = "generated"\nnaming_convention = "preserve-case"\n')
    run('generate', '--project', str(tmp_path))
    official = (tmp_path / 'generated/baml_sdk/index.ts').read_text()
    ts = (OUT / 'placement_contract.gen.ts').read_text()
    for name, (kind, entries) in emitter.parse(emitter.SOURCE.read_text()).items():
        if kind == 'enum':
            body = re.search(r'export enum '+name+r' \{([^}]+)\}', official).group(1)
            declared = re.findall(r'(\w+) = "([^"]+)"', body)
            assert declared == [(member, member) for member, _ in entries]
            values = json.loads(re.search(r'export const '+name+r'Values = (\[.*?\]) as const', ts).group(1))
            assert values == [alias or member for member, alias in entries]
        else:
            body = re.search(r'export class '+name+r' \{(.*?)  constructor', official, re.S).group(1)
            assert re.findall(r'^  (\w+)[!?]:', body, re.M) == [member for member, _, _ in entries]
            wire_body = re.search(r'export interface '+name+r' \{(.*?)^\}', ts, re.S | re.M).group(1)
            assert re.findall(r'^  "([^"]+)"\??:', wire_body, re.M) == [alias or member for member, _, alias in entries]
        # Official TS uses declared names; describe independently confirms aliases.
        if kind == "enum" and any(e[-1] for e in entries):
            description = run('describe', 'root.'+name, '--project', str(tmp_path))
            for entry in entries:
                if entry[-1]:
                    assert f'@alias("{entry[-1]}")' in description
