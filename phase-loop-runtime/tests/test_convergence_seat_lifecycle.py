import json
import subprocess
import sys

import pytest

from phase_loop_runtime.panel_invoker import SeatOutcomeRecord, persist_seat_outcome


def test_seat_outcome_is_metadata_only_and_persisted():
    values = []
    record = SeatOutcomeRecord("codex:1", "codex", True, "OK", "a", 1, "artifact", "now", "evidence")
    persist_seat_outcome(record, values.append)
    assert json.loads(values[0])["seat_key"] == "codex:1"
    assert "text" not in values[0]


@pytest.mark.parametrize("first", ["panel_invoker", "fab_gate", "closeout_validators", "closeout", "cli"])
def test_fresh_import_order_registers_fab_once(first):
    code = f"""
import phase_loop_runtime.{first}
from phase_loop_runtime.closeout_validators import (
    registered_closeout_validators, unavailable_builtin_closeout_validators,
    load_builtin_closeout_validators,
)
from phase_loop_runtime import panel_invoker, seat_outcome
assert panel_invoker.SeatOutcomeRecord is seat_outcome.SeatOutcomeRecord
assert panel_invoker.serialize_seat_outcome is seat_outcome.serialize_seat_outcome
for _ in range(2):
    load_builtin_closeout_validators()
    assert sum(f.__name__ == 'fab_gate_validator' for f in registered_closeout_validators()) == 1
    assert not unavailable_builtin_closeout_validators()
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "partially initialized" not in result.stderr
    assert "gate NOT registered" not in result.stderr


def test_seat_outcome_serialization_keeps_legacy_bytes_and_optional_fields():
    from phase_loop_runtime.panel_invoker import serialize_seat_outcome

    legacy = SeatOutcomeRecord("codex:1", "codex", True, "OK", "a", 1, "artifact", "now", "evidence")
    expected = '{"artifact_digest":"artifact","attempt_id":"a","completed_at":"now","epoch":1,"evidence_digest":"evidence","reason":null,"required":true,"seat_key":"codex:1","status":"OK","vendor_leg":"codex"}'
    assert serialize_seat_outcome(legacy) == expected
    extended = SeatOutcomeRecord("codex:1", "codex", True, "OK", "a", 1, "artifact", "now", "evidence",
                                 verdict="AGREE", finding_ids=("finding-1",), seat_instance_id="instance-1")
    payload = json.loads(expected)
    payload.update(verdict="AGREE", finding_ids=["finding-1"], seat_instance_id="instance-1")
    assert serialize_seat_outcome(extended) == json.dumps(payload, sort_keys=True, separators=(",", ":"))
