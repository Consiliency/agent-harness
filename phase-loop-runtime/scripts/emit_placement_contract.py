#!/usr/bin/env python3
"""Emit the deliberately restricted, type-only cross-client placement contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/phase_loop_runtime/baml_src/placement_contract.baml'
OUTPUT = ROOT / 'src/phase_loop_runtime/contracts/placement'
VERSION = '0.23.0'  # Must match baml-bridge and the verified CI CLI pin.
JSON_OBJECT = 'map<string, baml.json.json>'
IDENT = r'[A-Za-z_][A-Za-z_0-9]*'
ALIAS = r'(?:\s+@alias\("([^"\\]*)"\))?'


def parse(source: str) -> dict:
    """Reject unconsumed syntax, duplicates and unresolved references; never eval."""
    text = re.sub(r'//[^\n]*', '', source)
    types = {}
    while text.strip():
        match = re.match(r'\s*(enum|class)\s+('+IDENT+r')\s*\{([^{}]*)\}', text)
        if not match:
            raise ValueError('unsupported BAML syntax: ' + text.strip()[:80])
        kind, name, body = match.groups()
        if name in types:
            raise ValueError('duplicate type: ' + name)
        entries = []
        # A field's map contains a comma, so consume whole lines, not comma splits.
        for line in body.splitlines():
            line = line.strip().removesuffix(',').strip()
            if not line:
                continue
            pattern = '('+IDENT+')'+ALIAS if kind == 'enum' else '('+IDENT+r')\s*:?\s+('+IDENT+r'(?:\[\])?\??|map<string, baml\.json\.json>)'+ALIAS
            item = re.fullmatch(pattern, line)
            if not item:
                raise ValueError(f'unsupported {name} member: {line}')
            parts = item.groups()
            if any(e[0] == parts[0] for e in entries):
                raise ValueError(f'duplicate member: {name}.{parts[0]}')
            entries.append(parts)
        types[name] = (kind, entries)
        text = text[match.end():]
    for name, (kind, entries) in types.items():
        if kind == 'enum':
            values = [alias or member for member, alias in entries]
            if not entries or len(set(values)) != len(values):
                raise ValueError('empty or duplicate enum values: ' + name)
            continue
        for field, typ, alias in entries:
            if typ == JSON_OBJECT:
                if (name, field) != ('CreateBody', 'policy'):
                    raise ValueError('opaque JSON is allowed only at CreateBody.policy')
            elif typ.removesuffix('?').removesuffix('[]') not in {'string', 'int', 'bool', *types}:
                raise ValueError(f'unsupported field type: {name}.{field}: {typ}')
    return types


def emit(source: bytes) -> dict[str, bytes]:
    types = parse(source.decode('utf-8'))
    header = (f'// Source: phase_loop_runtime/baml_src/placement_contract.baml\n'
              f'// baml-cli: {VERSION}; sha256: {hashlib.sha256(source).hexdigest()}\n'
              '// Generated; do not edit.\n\n')
    ts = header + 'export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };\n\n'
    defs = {}

    def field_schema(typ):
        # Mirrors baml_modular._schema_for_baml_field: primitive types, nullable
        # optionals and list items. References use $defs instead of inlining.
        if typ.endswith('?'):
            base = field_schema(typ[:-1])
            if 'type' in base:
                return {**base, 'type': [base['type'], 'null']}
            return {'anyOf': [base, {'type': 'null'}]}
        if typ == JSON_OBJECT:
            return {'type': 'object'}
        if typ.endswith('[]'):
            return {'type': 'array', 'items': field_schema(typ[:-2])}
        if typ in {'string', 'int', 'bool'}:
            return {'type': {'string': 'string', 'int': 'integer', 'bool': 'boolean'}[typ]}
        return {'$ref': '#/$defs/' + typ}

    for name, (kind, entries) in types.items():
        if kind == 'enum':
            values = [alias or member for member, alias in entries]
            ts += f'export const {name}Values = {json.dumps(values)} as const;\n'
            ts += f'export type {name} = ' + ' | '.join(json.dumps(v) for v in values) + ';\n\n'
            defs[name] = {'type': 'string', 'enum': values}
            continue
        ts += f'export interface {name} {{\n'
        properties = {}
        required = []
        for member, typ, alias in entries:
            wire = alias or member
            optional = typ.endswith('?')
            base = typ.removesuffix('?')
            ts_type = {'string': 'string', 'int': 'number', 'bool': 'boolean', JSON_OBJECT: '{ [key: string]: JsonValue }'}.get(base, base)
            # Wire response nullables are required keys (revision 6 examples).
            nullable_required = name in {'ErrorBody', 'LeaseStatus', 'InventoryPage'}
            ts += f'  {json.dumps(wire)}' + ('?' if optional and not nullable_required else '') + ': ' + ts_type + (' | null' if optional else '') + ';\n'
            properties[wire] = field_schema(typ)
            if not optional or nullable_required:
                required.append(wire)
        ts += '}\n\n'
        # Mirrors _schema_for_baml_class, except only requests reject extensions.
        defs[name] = {'type': 'object', 'additionalProperties': name not in {'CreateBody', 'ServiceExposure', 'InventoryQuery', 'DeadlineHeaders'}, 'required': required, 'properties': properties}

    def constrain(cls, field, **constraints):
        defs[cls]['properties'][field].update(constraints)

    constrain('CreateBody', 'image', pattern=r'^.+@sha256:[0-9a-f]{64}$')
    constrain('CreateBody', 'policy_digest', pattern=r'^sha256:[0-9a-f]{64}$')
    constrain('CreateBody', 'service_exposures', maxItems=4)
    constrain('CreateBody', 'providers', maxItems=0)
    constrain('CreateBody', 'restart_policy', const='never')
    constrain('ServiceExposure', 'name', pattern=r'^[a-z][a-z0-9-]{0,62}$')
    constrain('ServiceExposure', 'target_port', minimum=1, maximum=65535)
    constrain('ServiceExposure', 'protocol', const='http')
    constrain('InventoryQuery', 'page_size', minimum=1, maximum=200, default=100)
    constrain('DeadlineHeaders', 'X-Deadline-Ms', minimum=1, maximum=30000)
    constrain('Binding', 'label_matches', minimum=0)
    constrain('LeaseStatus', 'expires_at', format='date-time', pattern=r'(?:[Zz]|\+00:00)$')
    constrain('LeaseStatus', 'sandbox_id', format='uuid')
    defs['Binding']['properties']['duplicates']['items']['format'] = 'uuid'
    for cls, fields in {'CapacityReading': ['free', 'ceiling'], 'Limits': ['max_ttl_s', 'max_extend_s', 'max_lifetime_s']}.items():
        for field in fields:
            constrain(cls, field, minimum=0)
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$comment': header.replace('// ', '').strip(), '$defs': defs}
    return {'placement_contract.gen.ts': (ts.rstrip() + '\n').encode(), 'coordinator-v1.schema.json': (json.dumps(schema, indent=2, ensure_ascii=False) + '\n').encode()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=OUTPUT)
    args = parser.parse_args()
    try:
        outputs = emit(SOURCE.read_bytes())
    except ValueError as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (args.output_dir / name).write_bytes(content)


if __name__ == '__main__':
    main()
