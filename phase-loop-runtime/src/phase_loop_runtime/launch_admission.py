"""Read-only isolated pre-claim admission using the managed CLOSEOUT binding."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from . import supervised_launch_binding as binding
from .placement_process_contract import validate_message
from .supervised_capture_v2 import capture_launch_v2
from .supervised_envelope_v2 import parse_v2
from .supervised_launch import (
    AttemptBinding,
    PreparedLaunch,
    Refused,
    discard_admission,
    prepare_launch_v2,
)

BLOB_CAP = 1 << 20
FALLBACK = "codec_unavailable"
_DIGEST = re.compile("[a-f0-9]{64}")
_AUTHORITY = frozenset(
    (
        "expected_assignment_digest",
        "expected_snapshot_ref",
        "expected_crosswalk_ref",
        "timeout_max_seconds",
        "qualified_routes",
        "policy_epoch",
        "revoked_record_ids",
        "caller_context_suitability",
    )
)


def _check(ok):
    if not ok:
        raise ValueError("binding_invalid")


def controller_fields(raw, envelope):
    doc = parse_v2(raw).value
    _check(
        set(doc) == {"h", "attempt", "context", "slots"}
        and doc["h"] == hashlib.sha256(envelope).hexdigest()
    )
    context = doc["context"]
    _check(set(context) == _AUTHORITY)
    for key in ("expected_assignment_digest", "expected_snapshot_ref", "expected_crosswalk_ref"):
        _check(_DIGEST.fullmatch(context[key]))
    attempt = AttemptBinding(**doc["attempt"])
    _check(attempt.assignment_digest == context["expected_assignment_digest"])
    for identifier in (attempt.run_id, attempt.attempt_id):
        _check(
            isinstance(identifier, str)
            and 0 < len(identifier) <= 200
            and all(ord(c) >= 32 and c not in "/\\" for c in identifier)
        )
    limit = context["timeout_max_seconds"]
    _check(type(limit) in (int, float) and limit == int(limit) and 0 < limit <= 3600)
    _check(
        isinstance(context["qualified_routes"], tuple)
        and isinstance(context["revoked_record_ids"], tuple)
        and all(isinstance(name, str) and name for name in context["revoked_record_ids"])
        and isinstance(context["policy_epoch"], str)
        and context["policy_epoch"]
        and (
            context["caller_context_suitability"] is None
            or hasattr(context["caller_context_suitability"], "items")
        )
    )
    slots = doc["slots"]
    _check(isinstance(slots["reference_roots"], tuple))
    roots = []
    for val in (slots["workspace"], slots["target"], *slots["reference_roots"]):
        path = Path(val)
        _check(
            path.is_absolute()
            and ".." not in path.parts
            and str(path) == val
            and stat.S_ISDIR(path.lstat().st_mode)
        )
        roots.append(path)
    return doc, attempt, dict(workspace=roots[0], target=roots[1], reference_roots=tuple(roots[2:]))


def _diagnostic(value):
    return next(
        (
            code
            for code in (*value.diagnostics, value.reason)
            if isinstance(code, str) and validate_message("AdmissionDiagnostic", code)
        ),
        FALLBACK,
    )


def evaluate(envelope, controller, *, managed_binding):
    doc, attempt, roots = controller_fields(controller, envelope)
    locator = binding.read_binding_locator(managed_binding)
    if isinstance(locator, Refused):
        return _diagnostic(locator)
    passive = binding.load_v2_binding(managed_binding, **roots)
    if isinstance(passive, Refused):
        return _diagnostic(passive)
    agreed = binding.reconcile_v2_binding(locator, passive, controller=doc, attempt=attempt)
    if isinstance(agreed, Refused):
        return _diagnostic(agreed)
    active = binding.activate_v2_binding(agreed)
    if isinstance(active, Refused):
        return _diagnostic(active)
    try:
        decoded = active.codec.decode_v2(envelope, bundle=active.bundle)
    except ValueError:
        return "envelope_schema_invalid"
    diagnostics = active.codec.precheck_v2_admission(
        decoded, context=active.context, spec=active.spec, attempt=attempt
    )
    if diagnostics:
        return _diagnostic(Refused(FALLBACK, tuple(diagnostics)))
    capture = capture_launch_v2(spec=active.spec, context=active.context, attempt=attempt)
    if isinstance(capture, Refused):
        return _diagnostic(capture)
    prepared = None
    try:
        prepared = prepare_launch_v2(envelope, binding=active, capture=capture, attempt=attempt)
        if isinstance(prepared, Refused):
            return _diagnostic(prepared)
        _check(isinstance(prepared, PreparedLaunch))
        return None
    finally:
        if isinstance(prepared, PreparedLaunch):
            discard_admission(prepared)
        else:
            capture.close()


def _read_part(stream):
    header = stream.read(8)
    _check(len(header) == 8)
    length = int.from_bytes(header, "big")
    _check(0 < length <= BLOB_CAP)
    raw = stream.read(length)
    _check(len(raw) == length)
    return raw


def main():
    # Selected code may emit diagnostics. Only this module writes to the verdict pipe.
    with os.fdopen(os.dup(sys.stdout.fileno()), "wb") as reply:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        try:
            _check(sys.flags.isolated and len(sys.argv) == 1)
            envelope = _read_part(sys.stdin.buffer)
            controller = _read_part(sys.stdin.buffer)
            _check(not sys.stdin.buffer.read(1))
            code = evaluate(envelope, controller, managed_binding=binding.MANAGED_BINDING)
        except BaseException:
            code = FALLBACK
        result = {"admitted": True} if code is None else {"admitted": False, "diagnostic": code}
        reply.write(json.dumps(result, separators=(",", ":")).encode() + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
