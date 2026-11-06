"""Owned review legs hold their own filtered namespace outside a board (agent-harness#1222).

Trusted host helpers (host Git above all) are resolved and run in the trusted parent,
never inside the seat's egress namespace: inside it, host files map to the overflow owner
and a trusted-helper check correctly refuses them. Only the provider launch goes through
the namespace.

The agy qualification's ``--help`` measurement runs an owned review leg outside any board
leg. Before this it found no namespace and refused, so the qualification was run inside a
hand-built namespace around the WHOLE command, which put the qualification worker -- and
its host Git -- inside it too. The leg now holds a namespace for its own launch only.
"""

from __future__ import annotations

import copy
import datetime as dt
import pytest


@pytest.fixture(autouse=True)
def _window_clock(request, monkeypatch):
    if "seats_firstseat_w1_receipt" in request.node.name:
        from phase_loop_runtime import seat_window as w
        monkeypatch.setattr(w, "_now", lambda: dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc))


@pytest.fixture(autouse=True)
def _window_sources(request, tmp_path, monkeypatch):
    if "seats_firstseat_w1_receipt" in request.node.name:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _window_records():
    from phase_loop_runtime import seat_window as w
    from phase_loop_runtime import president_adapter as pa, panel_invoker as pi
    records = []
    for index, (host, account) in enumerate((("team", 1), ("team", 2), ("standard", 1))):
        checks = {name: True for name in w.CONTAINMENT_FIELDS}
        egress = {name: True for name in w.EGRESS_FIELDS}
        context_id = f"c{index:031x}"
        account_label = f"a{account:031x}"
        record = {"schema": w.SCHEMA, "window": "W1", "context_id": f"c{index:031x}",
            "account_label": account_label, "host_class": host,
            "host_digest": ("a" if host == "team" else "b") * 64, "operator_id": account,
            "board_outcome": "terminated", "admission": "admitted", "canonical_gemini": True,
            "staged_read": True, "gemini_route": "jailed", "account_isolation": True,
            "co_seats": ["codex", "grok"],
            "rows": [r["id"] for r in w.candidates(w.readiness_rows(), host)],
            "observed_at": w._now().isoformat(),
            **{key: "c" * 64 for key in w.DIGEST_FIELDS}}
        execution = pi.leg_exec_record("gemini", 0, [], model_turn=True, verdict=True)
        path = pa.write_private_record("leg-" + execution["attempt_id"] + ".json", execution)
        import hashlib
        record["exec_record_digest"] = hashlib.sha256(path.read_bytes()).hexdigest()
        record["board_digest"] = (str(index + 1) * 64)
        record["tool_receipt_digest"] = "0" * 64
        record["board_input_digest"] = "d" * 64
        record["delivered_turn_digest"] = (str(index + 4) * 64)
        record["runtime_digest"] = "c" * 64
        record["profile_digest"] = "e" * 64
        record["allowlist_digest"] = "f" * 64
        outcomes = {name: "pass" if name in w.CONTAINMENT_FIELDS[:2] else "not_loaded"
                    for name in w.CONTAINMENT_FIELDS}
        observation = {"rows": {"context": index}, "canaries": [],
            "token_endpoint_events": {}, "credential_events": {}, "lookups": {},
            "home_row": {"baseline": "1" * 64, "measured": "1" * 64},
            "manifest_differences": False, "delivered_copy_sha256": "2" * 64,
            "bracket": {}, "issuer": {}, "unavailable_reasons": {}}
        identity = w.digest(observation)
        pa.write_private_record("window-observation-" + identity + ".json", observation)
        read = {"schema": "seat_window_read.v1", "tree_digest": ("def"[index] * 64),
            "access_observed": True, "tool_observed": True}
        record["tool_receipt_digest"] = w.digest(read)
        pa.write_private_record("window-read-" + w.digest(read) + ".json", read)
        egress_source = {"schema": "seat_window_egress.v1", "context_id": context_id,
            "measured_decisions": ["allow", "deny"], "board_decisions": ["allow"],
            "direct_without_proxy": "refused", "board_sha256": record["board_digest"],
            "board_input_sha256": record["board_input_digest"],
            "delivered_turn_sha256": record["delivered_turn_digest"],
            "exec_record_sha256": record["exec_record_digest"],
            "tool_receipt_sha256": record["tool_receipt_digest"]}
        egress_identity = w.digest(egress_source)
        pa.write_private_record("window-egress-" + egress_identity + ".json", egress_source)
        record["source_attempt"] = execution["attempt_id"]
        leg_records = {"claude": "6" * 64, "gemini": record["exec_record_digest"],
                       "codex": "7" * 64, "grok": "8" * 64}
        record["row_observations"] = w.candidate_observations(
            w.candidates(w.readiness_rows(), host), leg_records)
        record["containment"] = w.measurement(checks, observation_digest=identity)
        record["containment_outcomes"] = outcomes
        record["containment_binding"] = {
            key: ("release_qualified" if key == "admission_class"
                  else None if key in {"dependency_subject_sha256",
                                       "dependency_projection_sha256"}
                  else context_id if key == "context_id"
                  else account_label if key == "account_label"
                  else w.CONTAINMENT_CONTRACT_SHA256 if key == "contract_sha256"
                  else record["profile_digest"] if key == "jail_profile_sha256"
                  else record["allowlist_digest"] if key == "production_allowlist_sha256"
                  else record["board_input_digest"] if key == "board_input_sha256"
                  else "9" * 64)
            for key in w.BINDING_FIELDS}
        record["egress"] = w.measurement(egress, observation_digest=egress_identity)
        record["qualification_keys"] = {key: record[key] for key in w.KEY_FIELDS}
        record["record_digest"] = w.digest(record)
        records.append(record)
    return records


@pytest.mark.parametrize("change", ["missing", "malformed", "stale"])
def test_seats_firstseat_w1_receipt_observation_digest(change):
    from phase_loop_runtime import seat_window as w
    records = _window_records()
    assert w.verify_records(records)["records_valid"]
    value = records[0]["containment"]
    if change == "missing":
        del value["observation_digest"]
    else:
        value["observation_digest"] = "unavailable" if change == "malformed" else "f" * 64
    records[0].pop("record_digest")
    records[0]["record_digest"] = w.digest(records[0])
    assert not w.verify_records(records)["records_valid"]


@pytest.mark.parametrize("group,field", [(g, f) for g, fields in (
    ("containment", ("credential_scope", "refresh_detection", "project_settings", "hooks", "mcp_servers", "provider_overrides")),
    ("egress", ("allowed_proxy", "refused_proxy", "direct_dns", "direct_ip"))) for f in fields])
@pytest.mark.parametrize("negative", ["missing", "failed"])
def test_seats_firstseat_w1_receipt_measurements(group, field, negative):
    from phase_loop_runtime import seat_window as w
    records = _window_records()
    assert w.verify_records(records)["records_valid"]
    if negative == "missing":
        del records[0][group]["checks"][field]
    else:
        records[0][group]["checks"][field] = False
    records[0][group] = w.measurement(records[0][group]["checks"])
    records[0].pop("record_digest")
    records[0]["record_digest"] = w.digest(records[0])
    assert not w.verify_records(records)["records_valid"]


@pytest.mark.parametrize("change", ["account", "isolation", "disclosure", "stale", "coverage", "expiry", "canonical", "route", "admission", "row", "digest"])
def test_seats_firstseat_w1_receipt_boundaries(change):
    from phase_loop_runtime import seat_window as w
    records = _window_records()
    if change == "coverage":
        records.pop()
    else:
        r = records[0]
        if change == "account": records[1]["operator_id"] = 1
        if change == "isolation": r["account_isolation"] = False
        if change == "disclosure": r["co_seats"] = []
        if change == "stale": r["qualification_keys"]["profile_digest"] = "d" * 64
        if change == "expiry": r["observed_at"] = "2000-01-01T00:00:00+00:00"
        if change == "canonical": r["canonical_gemini"] = False
        if change == "route": r["gemini_route"] = "heartbeat"
        if change == "admission": r["admission"] = "policy_refused"
        if change == "row": r["rows"].pop()
        if change == "digest": r["runtime_digest"] = None
        for r in records:
            r.pop("record_digest")
            r["record_digest"] = w.digest(r)
    assert not w.verify_records(records)["records_valid"]


@pytest.mark.parametrize("value", ["/home/fixture/file", "operator@fixture.invalid", "fixture-host", "sk-fixture123456789"])
def test_seats_firstseat_w1_receipt_export(tmp_path, value):
    from phase_loop_runtime import seat_window as w
    records = _window_records()
    with pytest.raises(ValueError):
        w.export_records(records, tmp_path / "out.json", reviewed=False)
    bad = copy.deepcopy(records)
    bad[0]["account_label"] = value
    with pytest.raises(ValueError):
        w.export_records(bad, tmp_path / "out.json", reviewed=True)
    assert not (tmp_path / "out.json").exists()
    assert w.verify_records(records)["status"] == "done-local"
    exported = w.export_records(records, tmp_path / "out.json", reviewed=True)
    assert (tmp_path / "out.json").exists()
    assert any(row["status"] == "done-local" for row in exported["rows"])


def test_seats_firstseat_w1_receipt_exception_expiry():
    from phase_loop_runtime import seat_window as w
    records = _window_records()
    assert not w.verify_records(records, now=dt.datetime(2026, 12, 4, tzinfo=dt.timezone.utc))["records_valid"]


@pytest.mark.parametrize("field", ["context_id", "account_label", "profile_digest",
                                  "allowlist_digest", "board_digest", "board_input_digest",
                                  "delivered_turn_digest"])
def test_seats_firstseat_w1_receipt_source_identity(field):
    from phase_loop_runtime import seat_window as w
    records = _window_records()
    record = records[0]
    assert w._reconcile_sources(record)
    record[field] = ("c" + "f" * 31 if field == "context_id" else "a" + "f" * 31
                     if field == "account_label" else "0" * 64)
    record["qualification_keys"] = {k: record[k] for k in w.KEY_FIELDS}
    record.pop("record_digest")
    record["record_digest"] = w.digest(record)
    assert not w._reconcile_sources(record)
    assert not w.verify_records(records)["records_valid"]


def test_seats_firstseat_w1_receipt_source_contexts():
    from phase_loop_runtime import seat_window as w
    records = _window_records()
    assert w.verify_records(records)["records_valid"]
    for record in records[1:]:
        for key in ("source_attempt", "exec_record_digest", "tool_receipt_digest", "containment", "egress"):
            record[key] = copy.deepcopy(records[0][key])
        next(r for r in record["row_observations"] if r["id"] == "vendor:gemini")[
            "exec_record_digest"] = record["exec_record_digest"]
        record.pop("record_digest")
        record["record_digest"] = w.digest(record)
    assert not w.verify_records(records)["records_valid"]


@pytest.mark.parametrize("source", ["exec", "read", "observation", "egress"])
@pytest.mark.parametrize("change", ["missing", "digest", "content"])
def test_seats_firstseat_w1_receipt_retained_sources(tmp_path, monkeypatch, source, change):
    from phase_loop_runtime import seat_window as w
    from phase_loop_runtime import president_adapter as pa
    records = _window_records()
    assert w.verify_records(records)["records_valid"]
    record = records[0]
    names = {"exec": "leg-" + record["source_attempt"],
        "read": "window-read-" + record["tool_receipt_digest"],
        "observation": "window-observation-" + record["containment"]["observation_digest"],
        "egress": "window-egress-" + record["egress"]["observation_digest"]}
    path = pa.private_record_root() / (names[source] + ".json")
    import json
    value = json.loads(path.read_text())
    path.unlink()
    if change == "digest":
        value["schema"] = "unavailable"
    elif change == "content":
        if source == "exec": value["model_turn"] = False
        if source == "read": value["access_observed"] = False
        if source == "observation": value["home_row"]["baseline"] = "loaded"
        if source == "egress": value["board_input_sha256"] = "f" * 64
        if source == "exec":
            import hashlib
            record["exec_record_digest"] = hashlib.sha256(
                (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
            next(r for r in record["row_observations"] if r["id"] == "vendor:gemini")[
                "exec_record_digest"] = record["exec_record_digest"]
        elif source == "read":
            record["tool_receipt_digest"] = w.digest(value)
            path = pa.private_record_root() / ("window-read-" + w.digest(value) + ".json")
        else:
            identity = w.digest(value)
            group = "egress" if source == "egress" else "containment"
            record[group] = w.measurement(record[group]["checks"], observation_digest=identity)
            path = pa.private_record_root() / (f"window-{source}-" + identity + ".json")
        record.pop("record_digest")
        record["record_digest"] = w.digest(record)
    if change != "missing":
        pa.write_private_record(path.name, value)
    assert not w.verify_records(records)["records_valid"]


def test_seats_firstseat_w1_receipt_cli(tmp_path, capsys):
    from phase_loop_runtime import cli, president_adapter as pa
    root = tmp_path / "records"
    paths = [pa.write_private_record(f"context-{i}.json", r, root=root)
             for i, r in enumerate(_window_records())]
    import shutil
    for source in pa.private_record_root().glob("*.json"):
        shutil.copyfile(source, root / source.name)
        (root / source.name).chmod(0o600)
    args = [arg for path in paths for arg in ("--record", str(path))]
    assert cli.main(["seat-window", "verify", *args]) == 0
    assert '"records_valid": true' in capsys.readouterr().out
    target = tmp_path / "export.json"
    assert cli.main(["seat-window", "export", *args, "--output", str(target)]) == 1
    assert not target.exists()
    assert cli.main(["seat-window", "export", *args, "--output", str(target), "--reviewed"]) == 0
    assert target.exists()


def test_seats_firstseat_w1_receipt_matrix_reducer_leaves_unobserved_rows_candidate():
    from phase_loop_runtime import seat_window as w
    rows = w.reduce_readiness(_window_records())
    assert {row["vendor"] for row in rows if row["kind"] == "vendor"
            and row["status"] == "done-local"} == {"claude", "gemini", "codex", "grok"}
    assert next(row for row in rows if row["id"] == "vendor:pi")["status"] == "candidate"
    assert all(row["status"] == "candidate" for row in rows if row["kind"] == "president")


def test_seats_firstseat_w1_receipt_failed_export(tmp_path):
    from phase_loop_runtime import seat_window as w
    records = _window_records()
    records[0]["containment"] = w.measurement({k: False for k in w.CONTAINMENT_FIELDS})
    records[0].pop("record_digest")
    records[0]["record_digest"] = w.digest(records[0])
    target = tmp_path / "public.json"
    with pytest.raises(ValueError):
        w.export_records(records, target, reviewed=True)
    assert not target.exists()


@pytest.mark.parametrize("outcome", ["readable", "denied", "missing"])
def test_seats_firstseat_w1_receipt_account_probe(tmp_path, monkeypatch, outcome):
    from phase_loop_runtime import seat_window as w
    path = tmp_path / "peer.json"
    if outcome == "readable":
        path.write_text("fixture")
    elif outcome == "denied":
        original = w.os.open
        def open_peer(p, flags, *a, **kw):
            if p == path:
                raise PermissionError()
            return original(p, flags, *a, **kw)
        monkeypatch.setattr(w.os, "open", open_peer)
    assert w.account_isolation(path) is ({"readable": False, "denied": True, "missing": None}[outcome])

import contextlib

import pytest

from phase_loop_runtime import sandbox_egress
from phase_loop_runtime import panel_invoker as pi

_HOLDER = ("nsenter", "--net", "--mount", "-t", "1", "-U", "--preserve-credentials",
           "setpriv", "--bounding-set=-all", "--inh-caps=-all", "--")


def test_an_owned_leg_outside_a_board_holds_its_own_namespace(tmp_path, monkeypatch):
    """The agy ``--help`` measurement runs a leg outside any board leg's namespace. The
    leg opens one for its own launch, so the unwrapped CLI never needs a hand-built holder
    around the whole qualification (which would also put the worker's host Git inside it)."""
    held, seen = [], []

    @contextlib.contextmanager
    def _holder(*, timeout_s, required, **_):
        held.append(required)
        yield _HOLDER

    def _launch(argv, **kwargs):
        seen.append(pi._EGRESS_LAUNCH_PREFIX.get())
        raise OSError("stop at the launch")

    monkeypatch.setattr(sandbox_egress, "isolated_network", _holder)
    monkeypatch.setattr(pi, "launch_owned", _launch)
    with pytest.raises(OSError):
        pi._run_leg_with_liveness(["true"], cwd=tmp_path, env={}, deadline_s=5)
    assert held == [True] and seen == [_HOLDER]
    assert pi._EGRESS_LAUNCH_PREFIX.get() == ()


def test_an_owned_leg_inside_a_board_reuses_its_namespace(tmp_path, monkeypatch):
    def _never(**_):
        raise AssertionError("a second namespace was opened")

    seen = []

    def _launch(argv, **kwargs):
        seen.append(pi._EGRESS_LAUNCH_PREFIX.get())
        raise OSError("stop at the launch")

    monkeypatch.setattr(sandbox_egress, "isolated_network", _never)
    monkeypatch.setattr(pi, "launch_owned", _launch)
    token = pi._EGRESS_LAUNCH_PREFIX.set(_HOLDER)
    try:
        with pytest.raises(OSError):
            pi._run_leg_with_liveness(["true"], cwd=tmp_path, env={}, deadline_s=5)
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(token)
    assert seen == [_HOLDER]
