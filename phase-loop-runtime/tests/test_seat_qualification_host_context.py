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
        record = {"schema": w.SCHEMA, "window": "W1", "context_id": f"c{index:031x}",
            "account_label": f"a{account:031x}", "host_class": host,
            "host_digest": ("a" if host == "team" else "b") * 64, "operator_id": account,
            "board_outcome": "terminated", "admission": "admitted", "canonical_gemini": True,
            "staged_read": True, "gemini_route": "jailed", "account_isolation": True,
            "co_seats": ["codex", "grok"], "containment": w.measurement(checks),
            "egress": w.measurement(egress), "rows": [r["id"] for r in w.candidates(w.readiness_rows(), host)],
            "observed_at": w._now().isoformat(),
            **{key: "c" * 64 for key in w.DIGEST_FIELDS}}
        record["qualification_keys"] = {key: record[key] for key in w.KEY_FIELDS}
        execution = pi.leg_exec_record("gemini", 0, [], model_turn=True, verdict=True)
        path = pa.write_private_record("leg-" + execution["attempt_id"] + ".json", execution)
        import hashlib
        record["exec_record_digest"] = hashlib.sha256(path.read_bytes()).hexdigest()
        observation = {"schema": "seat_window_observation.v1", "context_id": record["context_id"],
            "tree_digest": "d" * 64,
            "final_tree_digest": "d" * 64, "stopped": True, "watch_complete": True,
            "proxy_complete": True, "allowed_requests": 1, "refused_requests": 1,
            "before": {"direct_dns": "refused", "direct_ip": "refused", "unlisted_status": "refused"},
            "after": {"direct_dns": "refused", "direct_ip": "refused", "unlisted_status": "refused"},
            "contract_observation": {"binding": {"profile_digest": record["profile_digest"],
                "allowlist_digest": record["allowlist_digest"]},
                "outcomes": {**dict.fromkeys(w.CONTAINMENT_FIELDS[2:], "not_loaded"),
                    "credential_scope": "no wider than the recorded baseline", "refresh_detection": "passed"}}}
        identity = w.digest(observation)
        pa.write_private_record("window-observation-" + identity + ".json", observation)
        read = {"schema": "seat_window_read.v1", "tree_digest": "d" * 64,
            "observation_digest": identity, "access_observed": True, "tool_observed": True}
        record["tool_receipt_digest"] = w.digest(read)
        pa.write_private_record("window-read-" + w.digest(read) + ".json", read)
        record["source_attempt"] = execution["attempt_id"]
        leg = pi.PanelLegResult("gemini", "OK", "AGREE")
        object.__setattr__(leg, "_leg_exec_metadata", {"record_digest": record["exec_record_digest"]})
        record["row_observations"] = w.candidate_observations(w.candidates(w.readiness_rows(), host), [leg])
        record["containment"] = w.measurement(checks, observation_digest=identity)
        record["egress"] = w.measurement(egress, observation_digest=identity)
        record["record_digest"] = w.digest(record)
        records.append(record)
    return records


@pytest.mark.parametrize("change", ["missing", "malformed", "stale"])
def test_seats_firstseat_w1_receipt_observation_digest(change):
    from phase_loop_runtime import seat_window as w
    records = _window_records()
    assert w.verify_records(records)["passed"]
    value = records[0]["containment"]
    if change == "missing":
        del value["observation_digest"]
    else:
        value["observation_digest"] = "unavailable" if change == "malformed" else "f" * 64
    records[0].pop("record_digest")
    records[0]["record_digest"] = w.digest(records[0])
    assert not w.verify_records(records)["passed"]


@pytest.mark.parametrize("group,field", [(g, f) for g, fields in (
    ("containment", ("credential_scope", "refresh_detection", "project_settings", "hooks", "mcp_servers", "provider_overrides")),
    ("egress", ("allowed_proxy", "refused_proxy", "direct_dns", "direct_ip"))) for f in fields])
@pytest.mark.parametrize("negative", ["missing", "failed"])
def test_seats_firstseat_w1_receipt_measurements(group, field, negative):
    from phase_loop_runtime import seat_window as w
    records = _window_records()
    assert w.verify_records(records)["passed"]
    if negative == "missing":
        del records[0][group]["checks"][field]
    else:
        records[0][group]["checks"][field] = False
    records[0][group] = w.measurement(records[0][group]["checks"])
    records[0].pop("record_digest")
    records[0]["record_digest"] = w.digest(records[0])
    assert not w.verify_records(records)["passed"]


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
    assert not w.verify_records(records)["passed"]


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
    w.export_records(records, tmp_path / "out.json", reviewed=True)
    text = (tmp_path / "out.json").read_text()
    assert "host_digest" not in text and "operator_id" not in text


def test_seats_firstseat_w1_receipt_exception_expiry():
    from phase_loop_runtime import seat_window as w
    records = _window_records()
    assert not w.verify_records(records, now=dt.datetime(2026, 12, 4, tzinfo=dt.timezone.utc))["passed"]


@pytest.mark.parametrize("source", ["exec", "read", "observation"])
@pytest.mark.parametrize("change", ["missing", "digest", "content"])
def test_seats_firstseat_w1_receipt_retained_sources(tmp_path, monkeypatch, source, change):
    from phase_loop_runtime import seat_window as w
    from phase_loop_runtime import president_adapter as pa
    records = _window_records()
    assert w.verify_records(records)["passed"]
    record = records[0]
    names = {"exec": "leg-" + record["source_attempt"],
        "read": "window-read-" + record["tool_receipt_digest"],
        "observation": "window-observation-" + record["containment"]["observation_digest"]}
    path = pa.private_record_root() / (names[source] + ".json")
    import json
    value = json.loads(path.read_text())
    path.unlink()
    if change == "digest":
        value["schema"] = "unavailable"
    elif change == "content":
        if source == "exec": value["model_turn"] = False
        if source == "read": value["access_observed"] = False
        if source == "observation": value["contract_observation"]["outcomes"]["hooks"] = "loaded"
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
            for group in ("containment", "egress"):
                record[group] = w.measurement(record[group]["checks"], observation_digest=identity)
            path = pa.private_record_root() / ("window-observation-" + identity + ".json")
            read_path = pa.private_record_root() / ("window-read-" + record["tool_receipt_digest"] + ".json")
            read = json.loads(read_path.read_text())
            read_path.unlink()
            read["observation_digest"] = identity
            record["tool_receipt_digest"] = w.digest(read)
            pa.write_private_record("window-read-" + w.digest(read) + ".json", read)
        record.pop("record_digest")
        record["record_digest"] = w.digest(record)
    if change != "missing":
        pa.write_private_record(path.name, value)
    assert not w.verify_records(records)["passed"]


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
    assert '"passed": true' in capsys.readouterr().out
    target = tmp_path / "export.json"
    assert cli.main(["seat-window", "export", *args, "--output", str(target)]) == 1
    assert not target.exists()
    assert cli.main(["seat-window", "export", *args, "--output", str(target), "--reviewed"]) == 0
    assert target.exists()


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
