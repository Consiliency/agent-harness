"""ah#291: the Claude CLI rejects a draft-2020-12 `$schema` at ARG-PARSE time.

`--json-schema` is validated with Ajv against a DEFAULT draft-07 registry, so a schema
declaring `https://json-schema.org/draft/2020-12/schema` fails BEFORE any model turn:

    Error: --json-schema is not a valid JSON Schema: no schema with key or ref
    "https://json-schema.org/draft/2020-12/schema"

`CLOSEOUT_SCHEMA` declares exactly that, so every claude execute/repair/review launch
failed instantly. Codex's `--output-schema` accepts 2020-12, which is why resume worked
and masked the failure.

Deliberately in an UNMARKED module: `dotfiles_integration`-marked tests are deselected in
CI, and this must actually run there.
"""
from __future__ import annotations

import json

from phase_loop_runtime import launcher
from phase_loop_runtime.models import CLOSEOUT_SCHEMA


def test_closeout_schema_still_declares_2020_12_at_the_source():
    """Pins the PREMISE. If the source schema is ever changed to draft-07, the adapter
    down-convert becomes a no-op and this test says so loudly rather than leaving dead
    code that looks load-bearing."""
    assert CLOSEOUT_SCHEMA.get("$schema") == "https://json-schema.org/draft/2020-12/schema"


def test_claude_schema_drops_the_unsupported_metaschema():
    out = launcher._claude_json_schema(CLOSEOUT_SCHEMA)
    assert "$schema" not in out, "the 2020-12 declaration reaches the Claude CLI"


def test_down_convert_is_constraint_preserving():
    """Only the declaration is removed — every constraint survives byte-for-byte."""
    out = launcher._claude_json_schema(CLOSEOUT_SCHEMA)
    expected = {k: v for k, v in CLOSEOUT_SCHEMA.items() if k != "$schema"}
    assert out == expected
    # and the body uses no 2020-12-only constructs, which is WHY dropping it is safe
    body = json.dumps(CLOSEOUT_SCHEMA)
    for only_2020 in ("prefixItems", "$dynamicRef", "$dynamicAnchor", "unevaluatedProperties",
                      "unevaluatedItems"):
        assert only_2020 not in body, f"{only_2020} needs 2020-12; stripping would change meaning"


def test_built_claude_command_carries_no_2020_12_schema():
    """Drives the PRODUCTION argv builder — not the helper — so deleting the call site at
    the emission point is caught, not just a change to the helper itself."""
    from pathlib import Path

    from phase_loop_runtime.models import ModelSelection

    cmd = launcher.build_claude_command(
        Path("/tmp/repo"),
        ModelSelection(profile="execute", model="claude-sonnet-5", effort="medium"),
        "do the thing",
        permission_mode="default",
        closeout_schema=CLOSEOUT_SCHEMA,
    )
    i = cmd.index("--json-schema")
    emitted = json.loads(cmd[i + 1])
    assert "$schema" not in emitted, (
        "build_claude_command emitted a schema the CLI rejects at arg-parse time"
    )
    assert emitted == {k: v for k, v in CLOSEOUT_SCHEMA.items() if k != "$schema"}


def test_down_converter_annotations_resolve():
    """`from __future__ import annotations` defers annotation evaluation, so an undefined
    name in a signature survives import and every call — it only surfaces via
    get_type_hints() or a linter. This repo runs NO linter in CI, so this test is the
    only guard. Mutation: drop `Mapping` from launcher.py's typing import -> NameError."""
    from typing import get_type_hints

    hints = get_type_hints(launcher._claude_json_schema)
    assert hints["schema"] is not None
