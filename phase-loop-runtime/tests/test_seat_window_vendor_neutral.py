"""K-1 vendor-neutral window kit (FIRSTSEAT amendment K-1, contract r4 §15).

Every test here enters through the production path named in the contract: ``qualify``,
``cli_main``, ``verify_records``, ``reduce_readiness``, ``export_records`` and the panel's
launch and board functions. A fixture vendor is registered only through
``register_window_data``.
"""

from __future__ import annotations

import contextlib
import dataclasses
from dataclasses import dataclass, field
import datetime as dt
import json
import os
from pathlib import Path
from typing import Mapping

import pytest

GOLDEN = Path(__file__).parent / "data" / "seat_window_gemini_k1_golden.json"
FIXED_NOW = dt.datetime(2026, 11, 4, 12, tzinfo=dt.timezone.utc)
FIXED_UID = 4242


# --------------------------------------------------------------------------------------
# The frozen-interface harness: stub launch and board results at the I-11 / I-12 seam.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class _PlantLayout:
    rows: tuple[object, ...]
    canary_hosts: Mapping[str, tuple[str, ...]] = field(repr=False)
    plugin_form: str
    layout_sha256: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _QualificationInput:
    repo: Path = field(repr=False)
    commit: str
    layout: _PlantLayout


@dataclass(frozen=True, slots=True, kw_only=True)
class _DefinitionResult:
    defined_rows: tuple[str, ...]
    defined_surfaces: tuple[str, ...]
    home_row_baseline: str
    credentialed_control_required: bool
    counted_lookups: Mapping[str, int]
    uncounted_home_lookups: Mapping[str, int]
    voided: tuple[object, ...]
    baseline_sha256: Mapping[str, str] = field(repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class _LaunchBinding:
    image_sha256: str
    admission_class: str
    stage_manifest_sha256: str
    argv_sha256: str
    input_sha256: str | None
    jail_profile_sha256: str
    allowlist_sha256: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _RequestEvent:
    method: str
    host: str = field(repr=False)
    path: str | None = field(repr=False)
    decision: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _ProxyWindow:
    label: str
    start_acked: bool
    end_acked: bool
    events: tuple[_RequestEvent, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class _ProxyStream:
    final: bool
    protocol_error: bool
    windows: tuple[_ProxyWindow, ...]
    outside_events: tuple[_RequestEvent, ...]
    allowlist_sha256: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _BracketRow:
    row: str
    outcome: str
    signature: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _BracketResult:
    start: object
    end: object
    post_refused: bool
    rows: tuple[_BracketRow, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class _WindowLaunchResult:
    kind: str
    status: str
    timed_out: bool
    error: str | None
    quiescent: bool
    model_turn: bool | None
    tool_steps: int | None
    subagent_steps: int | None
    stream: _ProxyStream | None
    bridge_exited: bool | None
    lookups: tuple[object, ...] | None
    created: tuple[object, ...] | None
    lookup_complete: bool | None
    watch: object | None
    scan: object | None
    first_jailed_launch_ns: int | None
    bracket: _BracketResult | None
    issuer: object | None
    delivered_copy_sha256: str | None = field(repr=False)
    help_sha256: str | None
    help_lists_plugin: bool | None
    plugin_validation: str | None
    binding: _LaunchBinding | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _BoardLegObservation:
    watch: object | None
    stream: _ProxyStream | None
    input_sha256: str
    binding: _LaunchBinding | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _BoardResult:
    """Carries both the base I-12 field names and the K-1 ones, so the same fixture drives
    the base tree (for the golden capture) and the K-1 tree."""

    composition: str
    board_outcome: str
    staged_read: bool
    board_sha256: str | None
    exec_record_sha256: str | None
    tool_receipt_sha256: str | None
    delivered_turn_sha256: str | None
    leg_exec_records: Mapping[str, str | None]
    co_seats: tuple[str, ...]
    canonical: bool
    leg_observation: _BoardLegObservation
    canonical_gemini: bool
    gemini: _BoardLegObservation
    window_leg: str = "gemini"
    board_stage_sha256: str | None = "d" * 64
    source_attempt: str | None = "f" * 32


@dataclass(frozen=True, slots=True, kw_only=True)
class _ContextBinding:
    context_id: str
    account_label: str
    dependency_subject_sha256: str | None
    dependency_projection_sha256: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _ContainmentInputs:
    context: _ContextBinding
    layout: _PlantLayout
    help: _WindowLaunchResult | None
    plugin_validation: _WindowLaunchResult | None
    controls: tuple[_WindowLaunchResult, ...]
    measured: _WindowLaunchResult | None
    expired_copy: _WindowLaunchResult | None
    board: _BoardLegObservation | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _OwnerSummary:
    schema: str
    context_id: str
    outcomes: Mapping[str, str]
    unavailable_reasons: Mapping[str, tuple[str, ...]]
    undefined_surfaces: tuple[str, ...]
    plugin_validation: str
    home_row_baseline: str
    counted_lookups: Mapping[str, int]
    uncounted_home_lookups: Mapping[str, int]
    voided_controls: tuple[object, ...]
    expired_copy_control: str
    private_route: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class _ContainmentReduction:
    containment: Mapping[str, str]
    checks: Mapping[str, bool]
    observation_sha256: str
    binding: Mapping[str, str | None]
    admitted: bool
    private: Mapping[str, object] = field(repr=False)
    owner_summary: _OwnerSummary


@dataclass(frozen=True, slots=True, kw_only=True)
class _Admitted:
    status: str = "admitted"
    code: str = "review_composition_admitted"


_CONTROL_KINDS = {"tree_control", "runtime_control", "credentialed_tree_control",
                  "credentialed_runtime_control"}


def _launch_result(kind, binding, stream):
    plain = kind in {"help", "plugin_validation"}
    control = kind in _CONTROL_KINDS
    return _WindowLaunchResult(
        kind=kind, status="SUCCESS", timed_out=False, error=None, quiescent=True,
        model_turn=None if plain else True, tool_steps=None if plain else 0,
        subagent_steps=None if plain else 0, stream=stream, bridge_exited=True,
        lookups=() if control else None, created=() if control else None,
        lookup_complete=True if control else None, watch=None, scan=None,
        first_jailed_launch_ns=1, bracket=_BracketResult(
            start=object(), end=object(), post_refused=True, rows=(
                _BracketRow(row="b_direct_without_proxy", outcome="refused",
                            signature="fixture"),)) if kind == "measured" else None,
        issuer=None, delivered_copy_sha256="2" * 64
        if kind in {"measured", "expired_copy"} else None,
        help_sha256="c" * 64 if kind == "help" else None,
        help_lists_plugin=True if kind == "help" else None,
        plugin_validation="valid" if kind == "plugin_validation" else None,
        binding=binding)


def _frozen_interface(tmp_path, monkeypatch, *, supplier_module=None, contract=None,
                      board_input=None):
    """Stub the I-11 launch, I-12 board and I-13 reducer seams; return the call log and the
    private writes. ``supplier_module`` is the module whose interface names are stubbed
    (``seat_jail_qualification`` on the base and through Gemini's re-exporting supplier)."""
    from phase_loop_runtime import panel_invoker as panel, president_adapter
    from phase_loop_runtime import seat_jail_qualification as jailq
    from phase_loop_runtime import seat_window as window

    calls: list[tuple[object, ...]] = []
    writes: dict[str, object] = {}
    target = supplier_module or jailq

    def plant_layout(*, plugin_form, window):
        assert window is not None
        calls.append(("layout", plugin_form))
        return _PlantLayout(rows=(), canary_hosts={}, plugin_form=plugin_form,
                            layout_sha256="1" * 64)

    def build_qualification_input(layout, base):
        calls.append(("build", layout.plugin_form))
        return _QualificationInput(repo=base, commit="2" * 40, layout=layout)

    empty = _ProxyStream(final=True, protocol_error=False, windows=(), outside_events=(),
                         allowlist_sha256="5" * 64)
    measured = _ProxyStream(final=True, protocol_error=False, windows=(
        _ProxyWindow(label="leg", start_acked=True, end_acked=True, events=(
            _RequestEvent(method="GET", host="fixture.invalid", path="<other>",
                          decision="allow"),
            _RequestEvent(method="GET", host="fixture.invalid", path="<other>",
                          decision="deny"))),), outside_events=(),
        allowlist_sha256="6" * 64)
    board_stream = _ProxyStream(final=True, protocol_error=False, windows=(
        _ProxyWindow(label="leg", start_acked=True, end_acked=True, events=(
            _RequestEvent(method="GET", host="fixture.invalid", path="<other>",
                          decision="allow"),)),), outside_events=(),
        allowlist_sha256="6" * 64)
    binding = _LaunchBinding(image_sha256="b" * 64, admission_class="release_qualified",
                             stage_manifest_sha256="d" * 64, argv_sha256="f" * 64,
                             input_sha256="9" * 64, jail_profile_sha256="7" * 64,
                             allowlist_sha256="6" * 64)

    def window_control_launch(spec):
        calls.append(("launch", spec.kind, spec.qualification_input.layout.plugin_form))
        return _launch_result(spec.kind, binding,
                              measured if spec.kind == "measured" else empty)

    def definition_probe(layout, controls):
        calls.append(("definition", tuple(item.kind for item in controls)))
        return _DefinitionResult(
            defined_rows=(), defined_surfaces=(), home_row_baseline="no_write_final",
            credentialed_control_required=True,
            counted_lookups={kind: 0 for kind in sorted(_CONTROL_KINDS)},
            uncounted_home_lookups={kind: index for index, kind in
                                    enumerate(sorted(_CONTROL_KINDS), start=1)},
            voided=(), baseline_sha256={})

    observation = _BoardLegObservation(watch=None, stream=board_stream,
                                       input_sha256=board_input or "a" * 64, binding=binding)
    board = _BoardResult(
        composition="admitted", board_outcome="terminated", staged_read=True,
        board_sha256="3" * 64, exec_record_sha256="4" * 64, tool_receipt_sha256="5" * 64,
        delivered_turn_sha256="6" * 64,
        leg_exec_records={"claude": "7" * 64, "gemini": "8" * 64, "codex": "9" * 64,
                          "grok": "a" * 64},
        co_seats=("claude", "codex", "grok"), canonical=True, leg_observation=observation,
        canonical_gemini=True, gemini=observation)

    def window_board_launch(spec):
        calls.append(("board", spec.qualification_input.layout.plugin_form,
                      spec.monitoring_policy))
        return board

    private = {"rows": {}, "canaries": [], "token_endpoint_events": {},
               "credential_events": {}, "lookups": {},
               "home_row": {"baseline": "1" * 64, "measured": "1" * 64},
               "manifest_differences": False, "delivered_copy_sha256": "2" * 64,
               "bracket": {}, "issuer": {}, "unavailable_reasons": {}}
    outcomes = {"credential_scope": "pass", "refresh_detection": "pass",
                "project_settings": "not_loaded", "hooks": "not_loaded",
                "mcp_servers": "not_loaded", "provider_overrides": "not_loaded"}

    def reduce_containment(inputs):
        calls.append(("reduce", tuple(item.kind for item in inputs.controls)))
        reduction_binding = {
            "image_sha256": "b" * 64, "admission_class": "release_qualified",
            "help_sha256": "c" * 64, "stage_manifest_sha256": "d" * 64,
            "plant_layout_sha256": "1" * 64,
            "contract_sha256": contract or window.CONTAINMENT_CONTRACT_SHA256,
            "control_argv_sha256": "f" * 64, "production_argv_sha256": "0" * 64,
            "control_input_sha256": "9" * 64, "measured_input_sha256": "8" * 64,
            "board_input_sha256": board_input or "a" * 64, "jail_profile_sha256": "7" * 64,
            "production_allowlist_sha256": "6" * 64,
            "refuse_all_allowlist_sha256": "5" * 64, "watch_sha256": "4" * 64,
            "proxy_sha256": "3" * 64, "validator_sha256": "2" * 64,
            "dependency_subject_sha256": None, "dependency_projection_sha256": None,
            "context_id": inputs.context.context_id,
            "account_label": inputs.context.account_label}
        owner = _OwnerSummary(
            schema="seat_window_owner_summary.v1", context_id=inputs.context.context_id,
            outcomes=outcomes,
            unavailable_reasons={name: () for name in window.CONTAINMENT_FIELDS},
            undefined_surfaces=(), plugin_validation="valid",
            home_row_baseline="no_write_final",
            counted_lookups={kind: 0 for kind in sorted(_CONTROL_KINDS)},
            uncounted_home_lookups={kind: 1 for kind in sorted(_CONTROL_KINDS)},
            voided_controls=(), expired_copy_control="pass", private_route=True)
        return _ContainmentReduction(
            containment=outcomes,
            checks={k: v in {"not_loaded", "pass"} for k, v in outcomes.items()},
            observation_sha256=window.digest(private), binding=reduction_binding,
            admitted=True, private=private, owner_summary=owner)

    for name, value in (("plant_layout", plant_layout),
                        ("build_qualification_input", build_qualification_input),
                        ("definition_probe", definition_probe),
                        ("ContextBinding", _ContextBinding),
                        ("ContainmentInputs", _ContainmentInputs),
                        ("reduce_containment", reduce_containment)):
        monkeypatch.setattr(target, name, value, raising=False)
    monkeypatch.setattr(panel, "window_control_launch", window_control_launch)
    monkeypatch.setattr(panel, "window_board_launch", window_board_launch)
    def preflight(**kwargs):
        # A row window binds its snapshot to the composed board (the plan-tier fixture).
        from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
        if kwargs.get("composed_out") is not None:
            kwargs["composed_out"].append(DEFAULT_BOARD)
        return _Admitted()

    monkeypatch.setattr(window, "preflight", preflight)
    monkeypatch.setattr(window, "_route_pass_current", lambda _: True)
    monkeypatch.setattr(window.seat_jail, "pass_record_verdict", lambda _: (True, "pass"))
    monkeypatch.setattr(window.seat_egress_proxy, "unavailable_reason", lambda: None)
    monkeypatch.setattr(window, "_find_exec_source_attempt", lambda d, root=None: "f" * 32)
    monkeypatch.setattr(window, "_host_digest", lambda: "0" * 64)
    monkeypatch.setattr(window, "_dependency_binding", lambda _provider: (None, None))
    monkeypatch.setattr(window.sandbox_policy, "staging_root", lambda: tmp_path)
    monkeypatch.setattr(window, "_now", lambda: FIXED_NOW)
    monkeypatch.setattr(window, "runtime_digest", lambda: "e" * 64)
    tokens = iter(f"{index:032x}" for index in range(1, 1000))
    monkeypatch.setattr(window.secrets, "token_hex", lambda _n=16: next(tokens))

    def write(name, value, **_kwargs):
        writes[name] = json.loads(json.dumps(value, sort_keys=True))
        return tmp_path / name

    monkeypatch.setattr(president_adapter, "write_private_record", write)
    return {"calls": calls, "writes": writes, "board": board}


@contextlib.contextmanager
def _fixed_uid(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(os, "getuid", lambda: FIXED_UID)
        yield


def _gemini_argv():
    from phase_loop_runtime import panel_invoker as panel
    from phase_loop_runtime import seat_jail
    model = "fixture-model"
    return {
        "help": [f"{seat_jail.SEAT_BIN}/gemini", "--help"],
        "production": list(panel._jailed_gemini_command(model)),
        **{kind: list(panel._window_control_command(kind, model))
           for kind in ("tree_control", "runtime_control", "credentialed_tree_control",
                        "credentialed_runtime_control", "measured", "expired_copy")},
    }


def _gemini_rows():
    from phase_loop_runtime import seat_window as window
    return [row for row in window.readiness_rows() if row.get("vendor") == "gemini"]


def _capture(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_window as window
    harness = _frozen_interface(tmp_path, monkeypatch)
    monkeypatch.setattr(window, "owner_w1_approved", lambda *a, **k: True)
    with _fixed_uid(monkeypatch):
        result = window.qualify(window="W1", monitoring_policy="bounded", repo=tmp_path,
                                attended=True)
    return {"schema": "seat_window_gemini_k1_golden.v1", "qualify": result,
            "calls": [list(call) for call in harness["calls"]],
            "writes": dict(sorted(harness["writes"].items())),
            "argv": _gemini_argv(), "rows": _gemini_rows()}


def test_seat_window_gemini_golden_is_byte_identical(tmp_path, monkeypatch):
    """F10 / EC-FIRSTSEAT-7: Gemini W1 at a fixed clock and registry. The golden was
    captured from the base tree (SL-5.1) before any K-1 source change."""
    captured = json.loads(json.dumps(_capture(tmp_path, monkeypatch), sort_keys=True))
    if os.environ.get("SEAT_WINDOW_K1_GOLDEN_CAPTURE") == "1" and not GOLDEN.exists():
        GOLDEN.write_text(json.dumps(captured, sort_keys=True, indent=1) + "\n")
    golden = json.loads(GOLDEN.read_text())
    assert captured == golden
    assert GOLDEN.read_bytes() == (json.dumps(golden, sort_keys=True, indent=1)
                                   + "\n").encode()


# ======================================================================================
# SL-5.2: the red-first acceptance tests (contract §13 F1–F17, §15 K1-T1–T5, T8, T9, G3).
# ======================================================================================

import hashlib
import sys
import threading
import types
from types import MappingProxyType, SimpleNamespace

ROW_NOW = dt.datetime(2026, 11, 25, 12, tzinfo=dt.timezone.utc)
FIXTURE_LAUNCH_KEY = {
    "profile_digest": "7" * 64, "allowlist_digest": "6" * 64, "falsifier_layout": "1" * 64,
    "projection_digest": None, "variant": None, "host_identity": "fixture-host",
    "arch": "x86_64", "runtime_digest": "e" * 64}


def _fixture_supplier(vendor="codex"):
    """A supplier module for a table vendor whose own adapter has not landed (SL-6 owns
    Codex's): every protocol name, delegating the interface names to the stubbed module."""
    from phase_loop_runtime import seat_window_supply, seat_jail_qualification as jailq
    module = types.ModuleType(f"phase_loop_runtime.{seat_window_supply.SUPPLIERS[vendor]}")
    for name in ("plant_layout", "build_qualification_input", "definition_probe",
                 "ContextBinding", "ContainmentInputs", "reduce_containment", "arm_watch",
                 "seed_runtime_plants"):
        setattr(module, name, getattr(jailq, name, None))
    module.plugin_forms = ("nested",)
    module.copy_transform = lambda copy: dataclasses.replace(copy, data=b"aged:" + copy.data) \
        if dataclasses.is_dataclass(copy) else b"aged:" + copy
    module.credential_mode = lambda kind: (
        "expired" if kind == "expired_copy" else
        "none" if kind in {"help", "tree_control", "runtime_control"} else "live")
    module.host_path_map = lambda seat, *, credential: SimpleNamespace(
        tree=Path("/fixture/tree"), seat_out=Path("/fixture/out"), credential=credential)
    module.launch_command = lambda kind, *, qualification_input=None, model, plugin_paths=(): (
        ("/seat/bin/codex", "exec", "--model", model, "--json", kind),)
    module.stream_facts = lambda raw: (("SUCCESS", True, 0, 0) if raw.strip() == "completed"
                                       else ("NONE", None, None, None))
    module.terminal = lambda observation: "completed"
    module.scan_secrets = lambda seat: (b"proxy-secret",)
    module.measure_credential_scope = lambda seat: "pass"
    module.refresh_detected = lambda seat: False
    module.token_endpoint = lambda event: False
    module.bracket_steps = lambda: (lambda proxy, run: "fixture-bracket")
    return module


def _fixture_window_data(vendor="codex", **changes):
    from phase_loop_runtime import seat_profiles
    data = dataclasses.replace(
        seat_profiles.GEMINI_WINDOW_DATA, leg=vendor, vendor=vendor,
        record_fields=MappingProxyType({"canonical": f"canonical_{vendor}",
                                        "route": f"{vendor}_route"}),
        model_leg="gemini", dependency_provider=vendor,
        co_seats=frozenset(seat_profiles.WINDOW_PLAN_TIER_LEGS - {vendor}),
        qualification_candidate_code=None, default=False,
        supplier=f"seat_window_supply_{vendor}", contract_sha256="1" * 64,
        windows=frozenset({"row"}),
        launch_kinds=frozenset({"help", "tree_control", "runtime_control",
                                "credentialed_tree_control", "credentialed_runtime_control",
                                "measured", "expired_copy"}),
        credential_kinds=frozenset({"credentialed_tree_control",
                                    "credentialed_runtime_control", "measured",
                                    "expired_copy"}),
        launch_cap=5)
    return dataclasses.replace(data, **changes)


@pytest.fixture
def fixture_vendor(monkeypatch):
    return register_fixture_vendor(monkeypatch)


def register_fixture_vendor(monkeypatch):
    """Register a Codex supplier and window data through ``register_window_data`` only.

    The real Codex supplier (K-1 SL-6) registers Codex's data on import. Under
    ``monkeypatch`` it is hidden first, in every place it can be found: its registry row,
    its ``sys.modules`` entry and the package attribute. Teardown restores all three."""
    import phase_loop_runtime
    from phase_loop_runtime import seat_profiles
    from phase_loop_runtime.seat_route_contract import WindowRows
    module = _fixture_supplier("codex")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(phase_loop_runtime, module.__name__.rsplit(".", 1)[1], module,
                        raising=False)
    profile = seat_profiles.profile_for("codex")
    rows = WindowRows(canonical_record_field="canonical_codex", route_record_field="codex_route",
                      route_literal="jailed",
                      plant_locations=(("tree", "/seat/tree", "reviewed-tree"),),
                      tree_rows=(("AGENTS.md", "provider_overrides"),))
    monkeypatch.setitem(seat_profiles._REGISTRY, "codex", dataclasses.replace(profile, window=rows))
    monkeypatch.setattr(seat_profiles, "_WINDOW_DATA", {
        vendor: data for vendor, data in seat_profiles._WINDOW_DATA.items()
        if vendor != "codex"})
    data = seat_profiles.register_window_data(_fixture_window_data("codex"))
    return SimpleNamespace(module=module, data=data, vendor="codex")


def _write_grants(path, active=None, retired=None):
    path.write_text("ROW_GRANTS = %r\nRETIRED_ROW_GRANTS = %r\n" % (active or {}, retired or {}))


class RowWorld(SimpleNamespace):
    def records(self):
        from phase_loop_runtime import seat_window as w
        return [w._read_record(path) for path in sorted(self.root.glob("window-*.json"))
                if w._partition_of_name(path.name) is not None]

    def verify(self, records=None, vendor=None, window="row"):
        from phase_loop_runtime import seat_window as w
        return w.verify_window(self.records() if records is None else records,
                               vendor or self.vendor, window, now=self.now,
                               source_root=self.root)

    def record(self):
        from phase_loop_runtime import seat_window as w
        return w._read_record(next(self.root.glob(f"window-row-{self.vendor}-*.json")))

    def rewrite(self, record, *, reseal=True):
        from phase_loop_runtime import seat_window as w
        if reseal:
            record["record_digest"] = w.digest({k: v for k, v in record.items()
                                                if k != "record_digest"})
        path = next(self.root.glob(f"window-row-{self.vendor}-*.json"))
        path.unlink()
        w_pa().write_private_record(path.name, record)

    def replace_file(self, name, data: bytes):
        path = self.root / name
        path.chmod(0o600)
        path.write_bytes(data)


def w_pa():
    from phase_loop_runtime import president_adapter
    return president_adapter


def _row_world(tmp_path, monkeypatch, vendor="codex", *, grok_degraded=False, dispatches=None,
               envelope=None, board_hook=None, max_attempts=1, board_input=None):
    """A complete row window for ``vendor`` through ``qualify``: real grant journal and
    witnesses, real run binding, snapshot, ledger and completion receipt, real retained
    source files in a 0700 directory; the I-11/I-12/I-13 seams stubbed."""
    from phase_loop_runtime import panel_invoker as panel, seat_window as w
    from phase_loop_runtime import seat_window_supply as supply
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(w, "_row_admission_dir", lambda: tmp_path / "admission")
    monkeypatch.setattr(w, "_w1_grant_dir", lambda: tmp_path / "w1-admission")
    grants = tmp_path / "grants.py"
    _write_grants(grants)
    monkeypatch.setattr(w, "_GRANTS_PATH", grants)
    supplier = sys.modules.get(f"phase_loop_runtime.seat_window_supply_{vendor}")
    harness = _frozen_interface(tmp_path, monkeypatch, supplier_module=supplier,
                                contract="1" * 64 if vendor != "gemini" else None,
                                board_input=board_input)
    monkeypatch.setattr(w_pa(), "write_private_record", _REAL_WRITE)
    monkeypatch.setattr(w, "_now", lambda: ROW_NOW)
    monkeypatch.setattr(w, "runtime_digest", lambda: "e" * 64)
    monkeypatch.setattr(w, "_launch_key", lambda data: dict(FIXTURE_LAUNCH_KEY))
    monkeypatch.setattr(panel, "window_reference_stage", lambda qi: "d" * 64)
    if board_input is None:
        monkeypatch.setattr(panel, "window_board_input_sha256", lambda: "a" * 64)
    monkeypatch.setattr(w, "_find_exec_source_attempt", _REAL_FIND)
    root = tmp_path / "state" / "agent-harness" / "seat-records"
    world = RowWorld(root=root, vendor=vendor, now=ROW_NOW, harness=harness, grants=grants,
                     tmp=tmp_path)
    env = dict(envelope or supply.required_envelope(vendor))
    with monkeypatch.context() as patch:
        patch.setattr(w, "_now", lambda: ROW_NOW - dt.timedelta(hours=2))
        world.grant_sha256 = w.mint_row_grant(
            vendor, not_before=(ROW_NOW - dt.timedelta(days=1)).isoformat(),
            not_after=(ROW_NOW + dt.timedelta(days=1)).isoformat(),
            packet_sha256="5" * 64, launch_envelope=env, max_attempts=max_attempts)
    world.pin = (world.grant_sha256, "5" * 64, (ROW_NOW + dt.timedelta(days=2)).isoformat())
    _write_grants(grants, {vendor: world.pin})
    # The board leg's retained exec record and staged-read receipt.
    execution = panel.leg_exec_record(vendor, 0, [], model_turn=True, verdict=True)
    path = _REAL_WRITE("leg-" + execution["attempt_id"] + ".json", execution)
    exec_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    read = {"schema": "seat_window_read.v1", "tree_digest": "d" * 64, "access_observed": True,
            "tool_observed": True, "input_sha256": "a" * 64}
    _REAL_WRITE("window-read-" + w.digest(read) + ".json", read)
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    board = dataclasses.replace(
        harness["board"], exec_record_sha256=exec_digest, tool_receipt_sha256=w.digest(read),
        source_attempt=execution["attempt_id"], window_leg=vendor,
        board_sha256=panel._window_board_composition_digest(DEFAULT_BOARD),
        leg_exec_records={leg: (exec_digest if leg == vendor else "7" * 64)
                          for leg in ("claude", "codex", "gemini", "grok")},
        co_seats=tuple(sorted({"claude", "codex", "gemini", "grok"} - {vendor})))
    # The board leg's launch attestation, as the runtime's ``start`` captures it.
    launch = {"leg": vendor, "qualification_key": dict(FIXTURE_LAUNCH_KEY), "binding": {
        "image_sha256": "b" * 64, "admission_class": "release_qualified",
        "stage_manifest_sha256": "d" * 64, "argv_sha256": "f" * 64, "input_sha256": "a" * 64,
        "jail_profile_sha256": "7" * 64, "allowlist_sha256": "6" * 64}}
    world.launch = launch
    world.exec_digest, world.attempt = exec_digest, execution["attempt_id"]
    plan = dispatches if dispatches is not None else [
        "subject", *(supply.seat_item(leg, vendor) for leg in ("claude", "codex", "gemini",
                                                              "grok")
                     if leg != vendor and not (grok_degraded and leg == "grok")),
        "fable_president"]

    stubbed_control = panel.window_control_launch

    def control(spec):
        with panel._window_subject_dispatch(spec.kind, "d" * 64):
            return stubbed_control(spec)

    def board_launch(spec):
        ledger = supply.active_ledger()
        for item in plan:
            ledger.dispatch(item, actual=_agreeing(ledger, item))
        if board_hook is not None:
            board_hook(ledger)
        panel._window_write_launch(SimpleNamespace(launch=world.launch), board.source_attempt,
                                   board.exec_record_sha256)
        return board

    monkeypatch.setattr(panel, "window_control_launch", control)
    monkeypatch.setattr(panel, "window_board_launch", board_launch)
    world.board = board
    return world


def _agreeing(ledger, item):
    """The route evidence a resolver reports when it agrees with the snapshot entry."""
    route = ledger.routes.get(item)
    entry = ledger.snapshot.get(route) if route else None
    if entry is None:
        return None
    mode = ("president" if route.startswith("president:") else
            "unconfined" if entry["exception"] == "unconfined" else "jailed")
    evidence = {"mode": mode, "exception": entry["exception"], "expiry": entry["expiry"]}
    if mode == "president":
        evidence["transport"] = route.split(":", 2)[-1]
    return evidence


def _run_row(world, monkeypatch, **kwargs):
    from phase_loop_runtime import seat_window as w
    return w.qualify(window="row", monitoring_policy="bounded", repo=world.tmp,
                     attended=True, vendor=world.vendor, **kwargs)


from phase_loop_runtime import president_adapter as _pa_module  # noqa: E402
from phase_loop_runtime import seat_window as _w_module  # noqa: E402

_REAL_WRITE = _pa_module.write_private_record
_REAL_FIND = _w_module._find_exec_source_attempt


@pytest.fixture
def row_world(tmp_path, monkeypatch, fixture_vendor):
    return completed_row_world(tmp_path, monkeypatch)


def completed_row_world(tmp_path, monkeypatch):
    world = _row_world(tmp_path, monkeypatch)
    assert _run_row(world, monkeypatch) == {"status": "candidate",
                                            "code": "window_review_required"}
    return world


def test_k1_row_world_verifies_through_the_production_reader(row_world):
    result = row_world.verify()
    assert result["passed"] is True, result
    assert result["code"] == "window_verified"




# --- F5: registration refuses bad data (IF-K1-1 §3). ---

@pytest.mark.parametrize("change", [
    {"record_fields": MappingProxyType({"canonical": "canonical_x", "route": "codex_route"})},
    {"record_fields": MappingProxyType({"canonical": "canonical_gemini",
                                        "route": "codex_route"})},
    {"co_seats": frozenset({"claude", "gemini"})},
    {"launch_kinds": frozenset({"help", "measured"})},
    {"launch_kinds": frozenset({"measured", "expired_copy", "invented"})},
    {"credential_kinds": frozenset({"measured", "expired_copy", "plugin_validation"})},
    {"launch_cap": 4},
    {"supplier": "seat_window_supply_gemini"},
    {"contract_sha256": "not-a-digest"},
    {"windows": frozenset({"W1", "row"})},
    {"board_fields": MappingProxyType({"canonical": "canonical_codex", "leg": "codex"})},
])
def test_k1_f5_registration_refuses_bad_window_data(monkeypatch, change):
    from phase_loop_runtime import seat_profiles
    # The real Codex supplier (K-1 SL-6) registers on import, and any earlier record
    # verification loads it (§4.3), so the isolated registry starts without its row.
    monkeypatch.setattr(seat_profiles, "_WINDOW_DATA", {
        vendor: data for vendor, data in seat_profiles._WINDOW_DATA.items()
        if vendor != "codex"})
    with pytest.raises(ValueError):
        seat_profiles.register_window_data(_fixture_window_data("codex", **change))
    assert seat_profiles.window_data_for("codex") is None


def test_k1_f5_gemini_window_data_is_version_two():
    from phase_loop_runtime import seat_profiles, seat_window as w
    data = seat_profiles.GEMINI_WINDOW_DATA
    assert data.supplier == "seat_window_supply_gemini"
    assert data.contract_sha256 == w.CONTAINMENT_CONTRACT_SHA256
    assert data.windows == frozenset({"W1", "row"}) and data.launch_cap == 5
    assert data.launch_kinds == seat_profiles.WINDOW_LAUNCH_KINDS
    assert dict(data.board_fields) == {"canonical": "canonical", "leg": "leg_observation"}
    assert set(data.co_seats) == {"claude", "codex", "grok"}


def test_k1_supplier_table_is_closed_and_loads_only_its_modules(monkeypatch):
    from phase_loop_runtime import seat_window_supply as supply
    assert dict(supply.SUPPLIERS) == {
        "gemini": "seat_window_supply_gemini", "codex": "seat_window_supply_codex",
        "claude": "seat_window_supply_claude", "grok": "seat_window_supply_grok"}
    assert supply.load("pi") is None and supply.load("../seat_jail") is None
    assert supply.available("gemini") is not None
    seen = []
    real = supply.importlib.import_module
    monkeypatch.setattr(supply.importlib, "import_module",
                        lambda name, package=None: seen.append(name) or real(name, package))
    supply.load_all()
    assert set(seen) <= {"." + name for name in supply.SUPPLIERS.values()}


def test_k1_missing_supplier_name_is_unavailable_before_any_claim(tmp_path, monkeypatch,
                                                                   fixture_vendor):
    from phase_loop_runtime import seat_window as w
    world = _row_world(tmp_path, monkeypatch)
    monkeypatch.delattr(fixture_vendor.module, "terminal")
    monkeypatch.setattr(w, "claim_window_attempt", lambda *a, **k: pytest.fail("claimed"))
    assert _run_row(world, monkeypatch)["code"] == "window_vendor_unavailable"


# --- F1, R4, R7, R10: only the vendor's own row changes. ---

def test_k1_f1_a_row_record_changes_only_its_vendor_row(row_world, tmp_path):
    from phase_loop_runtime import seat_window as w
    before = {row["id"]: row for row in w.readiness_rows()}
    after = w.reduce_readiness(row_world.records(), now=ROW_NOW, source_root=row_world.root)
    changed = {row["id"] for row in after if row != before[row["id"]]}
    assert changed == {"vendor:codex"}
    row = next(row for row in after if row["id"] == "vendor:codex")
    assert row["status"] == "done-local"
    assert row["live_evidence_digest"] == w.digest([row_world.exec_digest])
    record = row_world.record()
    assert record["rows"] == ["vendor:codex"] and len(record["row_observations"]) == 1
    exported = w.export_records(row_world.records(), tmp_path / "codex-row.json", reviewed=True,
                                source_root=row_world.root, vendor="codex", window="row")
    assert [row["id"] for row in exported["rows"]] == ["vendor:codex"]
    assert [context["context_id"] for context in exported["contexts"]] == [record["context_id"]]


def test_k1_f7_r4_assertion_is_mutation_checked(row_world, monkeypatch):
    from phase_loop_runtime import seat_window as w
    verdicts = w.verify_partitions(row_world.records(), now=ROW_NOW,
                                   source_root=row_world.root)["partitions"]
    real = w._apply_row

    def leaky(rows, row_id, record):  # a mutant writer that also touches another row
        real(rows, row_id, record)
        next(row for row in rows if row["id"] == "vendor:grok")["status"] = "done-local"

    monkeypatch.setattr(w, "_apply_row", leaky)
    with pytest.raises(AssertionError):
        w._reduce_partitions(verdicts)


def test_k1_f7_partition_cardinality_is_mutation_checked(row_world):
    from phase_loop_runtime import seat_window as w
    record = row_world.record()
    result = w.verify_partitions([record, record], now=ROW_NOW, source_root=row_world.root)
    assert result["partitions"][("codex", "row")]["code"] == "window_duplicate_records"


# --- F2, F3, F6: identity and isolation. ---

def test_k1_f2_mismatched_field_names_leave_the_record_unclassified(row_world):
    from phase_loop_runtime import seat_window as w
    record = row_world.record()
    record["canonical_gemini"] = record.pop("canonical_codex")
    result = w.verify_partitions([record], now=ROW_NOW, source_root=row_world.root)
    assert result["unclassified"] == 1 and result["partitions"] == {}


@pytest.mark.parametrize("field", ["profile_digest", "allowlist_digest"])
def test_k1_f3_a_borrowed_digest_fails(row_world, field):
    record = row_world.record()
    record[field] = "9" * 64  # another vendor's digest
    row_world.rewrite(record)
    assert row_world.verify()["passed"] is False


def test_k1_f3_a_borrowed_contract_digest_fails(row_world):
    record = row_world.record()
    record["containment_binding"]["contract_sha256"] = "a" * 64
    row_world.rewrite(record)
    assert row_world.verify()["passed"] is False


# --- F4, F14, K1-T9, R3: partitions. ---

def _w1_records(monkeypatch, tmp_path):
    import test_seat_qualification_host_context as host
    from phase_loop_runtime import seat_window as w
    monkeypatch.setattr(w, "_now", lambda: dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc))
    records = host._window_records()
    return records


def test_k1_f4_a_failing_partition_fails_only_itself(row_world, monkeypatch, tmp_path):
    from phase_loop_runtime import seat_window as w
    w1 = _w1_records(monkeypatch, tmp_path)
    broken = row_world.record()
    broken["staged_read"] = False
    now = dt.datetime(2026, 11, 5, tzinfo=dt.timezone.utc)
    root = w._private_root()
    result = w.verify_partitions([*w1, broken], now=now, source_root=root)["partitions"]
    assert result[("gemini", "W1")]["passed"] is True
    assert result[("codex", "row")]["passed"] is False
    rows = w.reduce_readiness([*w1, broken], now=now, source_root=root)
    assert next(r for r in rows if r["id"] == "vendor:gemini")["status"] == "done-local"
    assert next(r for r in rows if r["id"] == "vendor:codex")["status"] == "candidate"


def test_k1_f6_a_foreign_observation_is_ignored(monkeypatch, tmp_path):
    from phase_loop_runtime import seat_window as w
    w1 = _w1_records(monkeypatch, tmp_path)
    assert any(row["id"] == "vendor:codex" and row["outcome"] == "observed"
               for row in w1[0]["row_observations"])
    rows = w.reduce_readiness(w1)
    assert next(r for r in rows if r["id"] == "vendor:codex")["status"] == "candidate"
    assert next(r for r in rows if r["id"] == "vendor:gemini")["status"] == "done-local"


def test_k1_t9_mixed_validity_duplicates_fail_their_partition(row_world, monkeypatch,
                                                              tmp_path):
    """K1-T9: cardinality is counted before validity; a healthy partition still reduces."""
    from phase_loop_runtime import seat_window as w
    w1 = _w1_records(monkeypatch, tmp_path)
    valid = row_world.record()
    invalid = dict(valid, staged_read=False, context_id="c" + "1" * 31)
    now = dt.datetime(2026, 11, 5, tzinfo=dt.timezone.utc)
    root = w._private_root()
    result = w.verify_partitions([*w1, valid, invalid], now=now, source_root=root)
    assert result["partitions"][("codex", "row")]["code"] == "window_duplicate_records"
    assert result["partitions"][("gemini", "W1")]["passed"] is True
    rows = w.reduce_readiness([*w1, valid, invalid], now=now, source_root=root)
    assert next(r for r in rows if r["id"] == "vendor:gemini")["status"] == "done-local"


def test_k1_r3_read_errors_fail_only_the_named_partition(row_world, monkeypatch, tmp_path):
    from phase_loop_runtime import seat_window as w
    w1 = _w1_records(monkeypatch, tmp_path)
    now = dt.datetime(2026, 11, 5, tzinfo=dt.timezone.utc)
    root = w._private_root()
    result = w.verify_partitions(
        [*w1, row_world.record(), w.UnreadableRecord("window-row-codex-cX.json"),
         w.UnreadableRecord("context-7.json")], now=now, source_root=root)
    assert result["partitions"][("codex", "row")]["code"] == "window_record_unavailable"
    assert result["partitions"][("gemini", "W1")]["passed"] is True
    assert result["unclassified"] == 1
    result = w.verify_partitions([*w1, w.UnreadableRecord("window-W1-cY.json")], now=now,
                                 source_root=root)
    assert result["partitions"][("gemini", "W1")]["passed"] is False


def test_k1_r3_both_gemini_partitions_later_completion_sets_the_row(monkeypatch, tmp_path):
    from phase_loop_runtime import seat_window as w
    w1 = _w1_records(monkeypatch, tmp_path)[0]
    later = dict(w1, observed_at="2026-11-04T01:00:00+00:00", record_digest="e" * 64)
    verdicts = {("gemini", "W1"): {"passed": True, "record": w1},
                ("gemini", "row"): {"passed": True, "record": later}}
    rows = w._reduce_partitions(verdicts)
    row = next(r for r in rows if r["id"] == "vendor:gemini")
    assert row["qualification_record"] == w.digest(["e" * 64])
    tie = dict(w1, record_digest="f" * 64)
    verdicts[("gemini", "row")]["record"] = tie
    row = next(r for r in w._reduce_partitions(verdicts) if r["id"] == "vendor:gemini")
    assert row["qualification_record"] == w.digest(["f" * 64])


# --- F11 (R8): every stale key part fails, and the exec record's launch inputs bind. ---

@pytest.mark.parametrize("part", ["profile_digest", "allowlist_digest", "falsifier_layout",
                                  "projection_digest", "variant", "host_identity", "arch"])
def test_k1_f11_a_stale_key_part_fails(row_world, monkeypatch, part):
    from phase_loop_runtime import seat_window as w
    current = dict(FIXTURE_LAUNCH_KEY, **{part: "stale"})
    monkeypatch.setattr(w, "_launch_key", lambda data: current)
    result = row_world.verify()
    assert result["passed"] is False and result["code"] == "window_key_stale"


def test_k1_f11_no_recorded_execfind_pass_fails(row_world, monkeypatch):
    from phase_loop_runtime import seat_window as w
    monkeypatch.setattr(w.seat_jail, "pass_record_verdict", lambda _: (False, "no_record"))
    assert row_world.verify()["code"] == "window_key_stale"


def test_k1_f11_runtime_digest_is_provenance_only(row_world, monkeypatch):
    from phase_loop_runtime import seat_window as w
    monkeypatch.setattr(w, "_launch_key", lambda data: dict(FIXTURE_LAUNCH_KEY,
                                                            runtime_digest="0" * 64))
    assert row_world.verify()["passed"] is True


def test_k1_f11_key_differing_from_the_exec_launch_inputs_fails(row_world):
    record = row_world.record()
    record["containment_binding"]["jail_profile_sha256"] = "3" * 64
    row_world.rewrite(record)
    assert row_world.verify()["passed"] is False


# --- F13: integrity, through the production reader. ---

def test_k1_f13_a_restamp_inside_the_interval_fails(row_world):
    record = row_world.record()
    record["observed_at"] = (ROW_NOW - dt.timedelta(minutes=5)).isoformat()
    row_world.rewrite(record)
    assert row_world.verify()["code"] == "window_completion_mismatch"


@pytest.mark.parametrize("swap", ["source", "attempt", "counts"])
def test_k1_f13_swapped_same_vendor_evidence_fails(row_world, swap):
    import json as j
    record = row_world.record()
    ctx = record["context_id"]
    if swap == "source":
        name = f"owner-summary-row-codex-{ctx}.json"
        value = j.loads((row_world.root / name).read_text())
        value["home_row_baseline"] = "swapped"
        row_world.replace_file(name, j.dumps(value).encode())
    elif swap == "attempt":
        from phase_loop_runtime import panel_invoker as panel
        swapped = panel.leg_exec_record("codex", 0, [], model_turn=True, verdict=True)
        path = _REAL_WRITE("leg-" + swapped["attempt_id"] + ".json", swapped)
        record["source_attempt"] = swapped["attempt_id"]
        record["exec_record_digest"] = hashlib.sha256(path.read_bytes()).hexdigest()
        row_world.rewrite(record)
    else:
        name = f"window-ledger-codex-{ctx}.jsonl"
        raw = (row_world.root / name).read_bytes()
        row_world.replace_file(name, raw.replace(b'"units":1', b'"units":0', 1))
    assert row_world.verify()["passed"] is False


@pytest.mark.parametrize("missing", ["completion", "snapshot", "witness", "binding"])
def test_k1_f13_a_missing_receipt_snapshot_or_witness_fails(row_world, missing):
    ctx = row_world.record()["context_id"]
    name = {"completion": f"window-complete-codex-{ctx}.json",
            "snapshot": f"window-exceptions-codex-{ctx}.json",
            "binding": f"window-run-codex-{ctx}.json",
            "witness": next(p.name for p in row_world.root.glob("window-attempt-codex-*"))}[missing]
    (row_world.root / name).unlink()
    assert row_world.verify()["passed"] is False


@pytest.mark.parametrize("change", ["status", "run_binding", "snapshot_entry", "witness"])
def test_k1_f13_a_mismatched_receipt_snapshot_or_witness_fails(row_world, change):
    import json as j
    ctx = row_world.record()["context_id"]
    if change in {"status", "run_binding"}:
        name = f"window-complete-codex-{ctx}.json"
        value = j.loads((row_world.root / name).read_text())
        if change == "status":
            value["status"] = "aborted"
        else:
            value["run_binding_digest"] = "0" * 64
    elif change == "snapshot_entry":
        name = f"window-exceptions-codex-{ctx}.json"
        value = j.loads((row_world.root / name).read_text())
        value["entries"]["vendor:grok"]["expiry"] = None
    else:
        name = next(p.name for p in row_world.root.glob("window-attempt-codex-*"))
        value = j.loads((row_world.root / name).read_text())
        value["claimed_at"] = (ROW_NOW - dt.timedelta(minutes=1)).isoformat()
    row_world.replace_file(name, j.dumps(value, sort_keys=True).encode())
    assert row_world.verify()["passed"] is False


def test_k1_f13_corrupt_and_unavailable_journals_are_distinct(row_world, tmp_path):
    path = next((tmp_path / "admission").glob("row-grant-codex-*.jsonl"))
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"attempt":1', b'"attempt":2'))
    assert row_world.verify()["code"] == "window_journal_corrupt"
    path.write_bytes(raw)
    path.unlink()
    assert row_world.verify()["code"] == "window_journal_unavailable"


@pytest.mark.parametrize("change", ["relabel", "team", "foreign_stage"])
def test_k1_f13_relabel_team_and_foreign_stage_fail(row_world, change):
    record = row_world.record()
    if change == "relabel":
        record["account_label"] = "a" + "9" * 31
    elif change == "team":
        record["host_class"] = "team"
    else:
        record["containment_binding"]["stage_manifest_sha256"] = "8" * 64
    row_world.rewrite(record)
    result = row_world.verify()
    assert result["passed"] is False


def test_k1_f13_a_duplicate_record_fails(row_world):
    record = row_world.record()
    assert row_world.verify(records=[record, dict(record)])["code"] == "window_duplicate_records"


# --- F12 (R6): expiry with the launch snapshot. ---

def _expiring_rows(monkeypatch, *, expiry, vendors=("grok",)):
    from phase_loop_runtime import seat_window as w
    real = w.readiness_rows

    def rows():
        out = real()
        for row in out:
            if row["kind"] == "vendor" and row["vendor"] in vendors:
                row["exception"], row["expiry"] = "unconfined", expiry
        return out
    monkeypatch.setattr(w, "readiness_rows", rows)


def test_k1_f12_a_used_entry_expired_at_its_launch_fails(tmp_path, monkeypatch, fixture_vendor):
    world = _row_world(tmp_path, monkeypatch)
    _expiring_rows(monkeypatch, expiry=(ROW_NOW - dt.timedelta(hours=1)).isoformat())
    # The dispatch refuses at launch; a record that claims it ran anyway does not verify.
    assert _run_row(world, monkeypatch)["code"] == "window_exception_expired"


def test_k1_f12_valid_at_launch_expired_by_completion_passes(tmp_path, monkeypatch,
                                                             fixture_vendor):
    world = _row_world(tmp_path, monkeypatch)
    _expiring_rows(monkeypatch, expiry=(ROW_NOW + dt.timedelta(minutes=1)).isoformat())
    assert _run_row(world, monkeypatch)["code"] == "window_review_required"
    world.now = ROW_NOW + dt.timedelta(hours=1)
    assert world.verify()["passed"] is True


def test_k1_f12_an_expired_unused_rung_passes(tmp_path, monkeypatch, fixture_vendor):
    from phase_loop_runtime import seat_window as w
    world = _row_world(tmp_path, monkeypatch)
    real = w.readiness_rows

    def rows():
        out = real()
        for row in out:
            if row["id"].startswith("president:sol:"):
                row["exception"], row["expiry"] = "unconfined", (
                    ROW_NOW - dt.timedelta(days=1)).isoformat()
        return out
    monkeypatch.setattr(w, "readiness_rows", rows)
    assert _run_row(world, monkeypatch)["code"] == "window_review_required"
    assert world.verify()["passed"] is True


def test_k1_f12_a_delayed_used_leg_is_refused_at_dispatch(tmp_path, monkeypatch, fixture_vendor):
    from phase_loop_runtime import seat_window_supply as supply
    expiry = ROW_NOW + dt.timedelta(minutes=30)
    clock = [ROW_NOW]
    world = _row_world(tmp_path, monkeypatch, dispatches=["subject"],
                       board_hook=lambda ledger: (clock.__setitem__(0, expiry),
                                                  ledger.dispatch("grok_seat")))
    _expiring_rows(monkeypatch, expiry=expiry.isoformat())
    real = supply.WindowLedger.__init__

    def init(self, *a, **k):
        real(self, *a, **k)
        self._clock = lambda: clock[0]
    monkeypatch.setattr(supply.WindowLedger, "__init__", init)
    assert _run_row(world, monkeypatch)["code"] == "window_exception_expired"
    ledger = next(world.root.glob("window-ledger-codex-*.jsonl")).read_text()
    assert '"item":"grok_seat"' not in ledger


def test_k1_f12_a_later_matrix_change_does_not_change_the_verdict(tmp_path, monkeypatch,
                                                                  fixture_vendor):
    from phase_loop_runtime import seat_window as w
    world = _row_world(tmp_path, monkeypatch)
    assert _run_row(world, monkeypatch)["code"] == "window_review_required"
    # Another release (its own packaged matrix) verifies from the bound snapshot alone.
    monkeypatch.setattr(w, "release_identity", lambda: "f" * 64)
    _expiring_rows(monkeypatch, expiry=None, vendors=())
    real = w.readiness_rows
    monkeypatch.setattr(w, "readiness_rows",
                        lambda: [row for row in real() if row["id"] != "vendor:grok"])
    assert world.verify()["passed"] is True


def test_k1_f12_a_used_entry_missing_from_the_snapshot_fails(row_world):
    import json as j
    ctx = row_world.record()["context_id"]
    name = f"window-ledger-codex-{ctx}.jsonl"
    lines = (row_world.root / name).read_bytes().splitlines()
    entry = j.loads(lines[-1])
    entry["route"] = "vendor:unknown"
    lines[-1] = j.dumps(entry, sort_keys=True, separators=(",", ":")).encode()
    row_world.replace_file(name, b"\n".join(lines) + b"\n")
    assert row_world.verify()["passed"] is False


def test_k1_f12_the_subjects_current_expiry_fails(row_world, monkeypatch):
    _expiring_rows(monkeypatch, expiry=(ROW_NOW - dt.timedelta(minutes=1)).isoformat(),
                   vendors=("codex",))
    assert row_world.verify()["code"] in {"window_exception_expired", "window_snapshot_mismatch"}


# --- K1-T2, F12 legacy and F14: the legacy W1 check. ---

W1_RUN = dt.datetime(2026, 11, 20, 12, tzinfo=dt.timezone.utc)
AFTER_CUTOFF = dt.datetime(2026, 12, 5, 12, tzinfo=dt.timezone.utc)


def _legacy_w1(tmp_path, monkeypatch, *, link=True, claims=(W1_RUN,), not_after=None,
               newline_pin=True, witness_nonce=None, link_context=None):
    """A real legacy W1 record and its retained sources, plus a W1 grant journal and
    witnesses beside the grant. ``link`` adds the contemporaneous private record naming the
    context and the attempt, which the base W1 run does not write (K1-T2)."""
    import test_seat_qualification_host_context as host
    from phase_loop_runtime import seat_window as w
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    admission = tmp_path / "w1-admission"
    admission.mkdir(mode=0o700)
    monkeypatch.setattr(w, "_w1_grant_dir", lambda: admission)
    monkeypatch.setattr(w, "_now", lambda: W1_RUN + dt.timedelta(minutes=30))
    record = host._window_records()[0]
    nonce = "a" * 32
    grant = {"schema": w.W1_GRANT_SCHEMA, "host_digest": record["host_digest"],
             "not_before": (W1_RUN - dt.timedelta(days=1)).isoformat(),
             "not_after": (not_after or W1_RUN + dt.timedelta(days=2)).isoformat(),
             "vendor": "gemini", "host_class": "standard", "max_attempts": 1,
             "packet_sha256": "5" * 64, "nonce": nonce}
    raw = (json.dumps(grant, sort_keys=True, separators=(",", ":")) + "\n").encode()
    first = raw
    for number, claimed in enumerate(claims, start=1):
        entry = {"schema": w.W1_ATTEMPT_SCHEMA, "nonce": nonce, "attempt": number,
                 "claimed_at": claimed.isoformat(),
                 "previous_sha256": hashlib.sha256(raw).hexdigest()}
        raw += (json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n").encode()
        witness = dict(entry, nonce=witness_nonce or nonce)
        path = admission / f"w1-attempt-{nonce}-{number}.json"
        path.write_text(json.dumps(witness, sort_keys=True) + "\n")
        path.chmod(0o600)
    grant_path = admission / w.W1_GRANT_NAME
    grant_path.write_bytes(raw)
    grant_path.chmod(0o600)
    pin = hashlib.sha256(first if newline_pin else first[:-1]).hexdigest()
    monkeypatch.setattr(w, "OWNER_W1_GRANT_SHA256", pin)
    if link:
        _REAL_WRITE(f"window-W1-attempt-{record['context_id']}.json", {
            "schema": w.W1_LINK_SCHEMA, "context_id": link_context or record["context_id"],
            "nonce": nonce, "attempt": 1})
    return record


def test_k1_t2_legacy_literals_expire_at_the_w1_cutoff():
    from phase_loop_runtime import seat_window as w
    assert w._EXPIRES == w.OWNER_W1_APPROVED_UNTIL
    assert w.RUN_OUTER_BOUND_S == 7320 and w.W1_COMPLETION_MARGIN_S > w.RUN_OUTER_BOUND_S


def test_k1_t2_a_linked_w1_record_keeps_verifying_after_the_cutoff(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_window as w
    record = _legacy_w1(tmp_path, monkeypatch)
    assert w.verify_records([record], now=AFTER_CUTOFF)["passed"] is True


def test_k1_t2_an_unlinked_w1_record_gets_the_conservative_rule(tmp_path, monkeypatch):
    """Base W1 writes no context-to-attempt link, so a real W1 record falls back."""
    from phase_loop_runtime import seat_window as w
    record = _legacy_w1(tmp_path, monkeypatch, link=False)
    assert w.verify_records([record], now=W1_RUN + dt.timedelta(days=1))["passed"] is True
    assert w.verify_records([record], now=AFTER_CUTOFF)["passed"] is False


def test_k1_t2_a_second_context_in_the_same_interval_is_not_linked(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_window as w
    record = _legacy_w1(tmp_path, monkeypatch, link_context="c" + "f" * 31)
    assert w.verify_records([record], now=AFTER_CUTOFF)["passed"] is False


def test_k1_t2_the_first_line_is_compared_by_its_hash_with_newline(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_window as w
    record = _legacy_w1(tmp_path, monkeypatch, newline_pin=False)
    assert w.verify_records([record], now=AFTER_CUTOFF)["passed"] is False


def test_k1_f12_legacy_claim_just_inside_the_margin_passes(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_window as w
    claimed = W1_RUN
    not_after = claimed + dt.timedelta(seconds=w.W1_COMPLETION_MARGIN_S)
    record = _legacy_w1(tmp_path, monkeypatch, not_after=not_after)
    assert w.verify_records([record], now=AFTER_CUTOFF)["passed"] is True


def test_k1_f12_legacy_claim_outside_the_margin_falls_back(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_window as w
    not_after = W1_RUN + dt.timedelta(seconds=w.W1_COMPLETION_MARGIN_S - 1)
    record = _legacy_w1(tmp_path, monkeypatch, not_after=not_after)
    assert w.verify_records([record], now=AFTER_CUTOFF)["passed"] is False


@pytest.mark.parametrize("case", ["witness_nonce", "two_attempts", "journal_unavailable"])
def test_k1_f12_legacy_mismatches_fall_back_to_the_base_rule(tmp_path, monkeypatch, case):
    from phase_loop_runtime import seat_window as w
    kwargs = {"witness_nonce": {"witness_nonce": "b" * 32},
              "two_attempts": {"claims": (W1_RUN, W1_RUN + dt.timedelta(minutes=1))},
              "journal_unavailable": {}}[case]
    record = _legacy_w1(tmp_path, monkeypatch, **kwargs)
    if case == "journal_unavailable":
        (tmp_path / "w1-admission" / w.W1_GRANT_NAME).unlink()
    assert w.verify_records([record], now=W1_RUN + dt.timedelta(days=1))["passed"] is True
    assert w.verify_records([record], now=AFTER_CUTOFF)["passed"] is False


@pytest.mark.parametrize("journal", [True, False])
def test_k1_f14_w1_survives_a_registry_change(tmp_path, monkeypatch, fixture_vendor, journal):
    """Adding a candidate row's vendor never refuses W1; without the journal the base
    expiry rule applies."""
    from phase_loop_runtime import seat_window as w
    record = _legacy_w1(tmp_path, monkeypatch, link=journal)
    if not journal:
        (tmp_path / "w1-admission" / w.W1_GRANT_NAME).unlink()
    assert w.verify_records([record], now=W1_RUN + dt.timedelta(days=1))["passed"] is True
    assert w.verify_records([record], now=AFTER_CUTOFF)["passed"] is journal
    rows = w.reduce_readiness([record], now=W1_RUN + dt.timedelta(days=1))
    assert next(r for r in rows if r["id"] == "vendor:gemini")["status"] == "done-local"
    assert next(r for r in rows if r["id"] == "vendor:codex")["status"] == "candidate"


# --- F9, K1-T3, K1-T4, K1-T5: the launch envelope, enforced before dispatch. ---

def _ledger(tmp_path, vendor="gemini", **caps):
    from phase_loop_runtime import seat_window as w, seat_window_supply as supply
    envelope = dict(supply.required_envelope(vendor), **caps)
    ledger = supply.WindowLedger(tmp_path / "ledger.jsonl", envelope,
                                 clock=lambda: ROW_NOW)
    legs = [leg for leg in ("claude", "codex", "gemini", "grok") if leg != vendor]
    ledger.bind(w._snapshot_entries(vendor, legs), w.ledger_routes(vendor))
    return ledger


def _lines(ledger):
    return [json.loads(line) for line in ledger.path.read_text().splitlines()]


def test_k1_f9_a_refused_provider_start_never_spawns(tmp_path, monkeypatch):
    """The real provider boundary: the reservation refuses before any process exists."""
    from phase_loop_runtime import panel_invoker as panel, seat_window_supply as supply
    ledger = _ledger(tmp_path, subject=0)
    monkeypatch.setattr(panel.subprocess, "Popen", lambda *a, **k: pytest.fail("spawned"))
    token = panel._OWNED_LAUNCH.set(True)
    try:
        with supply.ledger_scope(ledger), supply.item_scope("subject"):
            with pytest.raises(supply.WindowRefused) as refused:
                panel.launch_provider(["/seat/bin/gemini", "--help"])
        assert refused.value.code == "window_envelope_exceeded"
        with supply.ledger_scope(ledger):
            with pytest.raises(supply.WindowRefused) as refused:
                panel.launch_provider(["/seat/bin/gemini", "--help"])
        assert refused.value.code == "window_unbudgeted_start"
    finally:
        panel._OWNED_LAUNCH.reset(token)
    assert _lines(ledger) == []


def test_k1_f9_run_provider_and_launch_provider_debit_once(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_window_supply as supply
    from phase_loop_runtime import seat_profiles
    ledger = _ledger(tmp_path)
    with supply.ledger_scope(ledger), supply.item_scope("grok_seat"):
        supply.note_route(_agreeing(ledger, "grok_seat"))
        with seat_profiles.window_provider_start(["grok", "-p", "x"], boundary="run"):
            seat_profiles.window_provider_start(["grok", "-p", "x"])
    assert ledger.counts()["grok_seat"] == 1


def test_k1_f9_a_cold_agy_start_beyond_its_reservation_is_refused(tmp_path):
    from phase_loop_runtime import panel_invoker as panel, seat_profiles
    from phase_loop_runtime import seat_window_supply as supply
    ledger = _ledger(tmp_path)
    authorization = SimpleNamespace(staged_tree_sha256="c" * 64)
    with panel._window_board_registration(authorization, SimpleNamespace(), ledger=ledger):
        with panel._window_agy_reservation(authorization):
            for _ in range(4):
                seat_profiles.window_provider_start(["agy", "--help"])
            with pytest.raises(supply.WindowRefused):
                seat_profiles.window_provider_start(["agy", "--help"])
    assert ledger.counts()["agy_first_use"] == 3 and ledger.counts()["agy_cold_help"] == 1


def test_k1_f9_grok_retry_beyond_two_and_subject_beyond_five(tmp_path):
    from phase_loop_runtime import seat_window_supply as supply
    ledger = _ledger(tmp_path)
    grok, subject = _agreeing(ledger, "grok_seat"), _agreeing(ledger, "subject")
    for _ in range(2):
        ledger.dispatch("grok_seat", actual=grok)
    with pytest.raises(supply.WindowRefused):
        ledger.dispatch("grok_seat", actual=grok)
    for _ in range(5):
        ledger.dispatch("subject", actual=subject)
    with pytest.raises(supply.WindowRefused):
        ledger.dispatch("subject", actual=subject)
    assert ledger.counts()["subject"] == 5 and ledger.counts()["grok_seat"] == 2
    assert len(_lines(ledger)) == 7  # a partial run keeps its counts, refusals write nothing


def test_k1_f9_fable_reask_beyond_two_and_any_fallback_rung_are_refused(tmp_path):
    from phase_loop_runtime import panel_invoker as panel
    ledger = _ledger(tmp_path)
    calls = []
    invoke = panel._WindowPresidentInvoke(
        lambda model, prompt: calls.append(model) or {"status": "ok", "text": "x"}, ledger)
    assert invoke("fable", "p")["status"] == "ok" and invoke("fable", "p")["status"] == "ok"
    assert invoke("fable", "p") == {"status": "refused", "code": "window_envelope_exceeded"}
    assert calls == ["fable", "fable"]
    # A descent to any other rung is refused even with Fable's budget untouched.
    (tmp_path / "fallback").mkdir()
    fresh = _ledger(tmp_path / "fallback")
    fallback = panel._WindowPresidentInvoke(
        lambda model, prompt: calls.append(model) or {"status": "ok", "text": "x"}, fresh)
    for rung in ("sol", "grok", "gemini"):
        assert fallback(rung, "p") == {"status": "refused", "code": "window_envelope_exceeded"}
    assert calls == ["fable", "fable"] and fresh.counts()["fable_president"] == 0


def test_k1_f9_an_envelope_smaller_than_the_context_needs_refuses_at_first_excess(tmp_path):
    from phase_loop_runtime import seat_window_supply as supply
    ledger = _ledger(tmp_path, subject=2)
    subject = _agreeing(ledger, "subject")
    ledger.dispatch("subject", actual=subject)
    ledger.dispatch("subject", actual=subject)
    with pytest.raises(supply.WindowRefused) as refused:
        ledger.dispatch("subject", actual=subject)
    assert refused.value.code == "window_envelope_exceeded"


def test_k1_f9_concurrent_legs_reserve_atomically(tmp_path):
    from phase_loop_runtime import seat_window_supply as supply
    ledger = _ledger(tmp_path)
    outcomes = []

    def leg():
        try:
            ledger.dispatch("grok_seat", actual=_agreeing(ledger, "grok_seat"))
            outcomes.append(True)
        except supply.WindowRefused:
            outcomes.append(False)
    threads = [threading.Thread(target=leg) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count(True) == 2 and len(_lines(ledger)) == 2


def test_k1_f9_envelope_totals():
    from phase_loop_runtime import seat_window_supply as supply
    assert {vendor: supply.model_capable_starts(supply.required_envelope(vendor))
            for vendor in ("gemini", "codex", "claude", "grok")} == {
        "gemini": 14, "codex": 14, "claude": 14, "grok": 13}


def _production_board(monkeypatch, *, ledger, leg_spawn, window_leg="codex", in_window=True,
                      president=None):
    """Run the real ``invoke_board`` (its pool, seat workers, retention and president)
    through the repo's sanctioned board-control protocol, with ``leg_spawn`` standing in at
    each seat's provider boundary. The window registers against the authorization the
    invoker actually receives, exactly as ``window_board_launch`` does."""
    from phase_loop_runtime import agy_qualification, panel_invoker as panel, seat_profiles
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    from harden_tdd_guard import invoke_sanctioned_board_control
    from president_fakes import deferring_president
    _guard_provider_spawns(monkeypatch)
    monkeypatch.setattr(panel, "integrated_seat_subject",
                        lambda *a, **k: SimpleNamespace(subject_path=None))
    monkeypatch.setattr(agy_qualification, "requalify_once", lambda *a, **k: (
        seat_profiles.window_provider_start(["agy", "--version"]), None)[1])
    real = panel.invoke_board
    seen = {}

    def registered(board, artifact, **kwargs):
        authorization = kwargs["review_authorization"]
        seen["authorization"] = authorization
        with panel._window_board_registration(authorization, SimpleNamespace(),
                                              leg=window_leg, ledger=ledger,
                                              in_window=in_window):
            return real(board, artifact, **kwargs)
    monkeypatch.setattr(panel, "invoke_board", registered)
    result = invoke_sanctioned_board_control(
        DEFAULT_BOARD, "fixture", spawn=lambda leg, artifact: leg_spawn(leg, seen), landing_tier="plan",
        president_invoke=president or deferring_president, max_concurrency=1)
    return result, seen


def _guard_provider_spawns(monkeypatch):
    import subprocess as sp
    real = sp.Popen

    class Guard(real):
        def __init__(self, args, *a, **k):
            words = [os.path.basename(str(w)) for w in (args if isinstance(args, (list, tuple))
                                                        else [args])]
            if any(w in {"codex", "claude", "grok", "agy", "gemini"} for w in words):
                raise AssertionError(f"live provider spawn {args!r}")
            super().__init__(args, *a, **k)
    monkeypatch.setattr(sp, "Popen", Guard)


def test_k1_t3_the_ledger_reaches_production_board_workers(tmp_path, monkeypatch):
    """K1-T3 through the production worker: the real board pool drops context variables,
    the seat worker takes the single shared ledger by explicit handoff, and the second
    Grok start is refused before it spawns."""
    from phase_loop_runtime import panel_invoker as panel, seat_profiles
    from phase_loop_runtime import seat_window_supply as supply
    # Grok is this test's unconfined vendor; hide its registered profile (GROK SL-2) so the
    # matrix keeps that exception for the fixture.
    monkeypatch.delitem(seat_profiles._REGISTRY, "grok")
    ledger = _ledger(tmp_path, grok_seat=1)
    started = []

    def leg_spawn(leg, seen):
        if leg != "grok":
            return ("OK", "review\nAGREE")
        panel._window_note_route(SimpleNamespace(**dict(_agreeing(ledger, "grok_seat"),
                                                        exception=SimpleNamespace(
            kind=_agreeing(ledger, "grok_seat")["exception"],
            expiry=dt.datetime.fromisoformat(_agreeing(ledger, "grok_seat")["expiry"]))),
            code=None))
        for _ in range(2):  # the soft-empty retry's second start
            seat_profiles.window_provider_start(["grok", "-p", "review"])
            started.append(leg)
        return ("OK", "review\nAGREE")

    result, _seen = _production_board(monkeypatch, ledger=ledger, leg_spawn=leg_spawn)
    assert started == ["grok"]
    assert ledger.counts()["grok_seat"] == 1
    grok = next(leg for leg in result.legs if leg.leg == "grok")
    assert grok.status != "OK"
    assert supply.active_ledger() is None


def test_k1_t3_a_production_worker_in_a_window_with_no_ledger_is_refused(tmp_path,
                                                                         monkeypatch):
    started = []
    result, _seen = _production_board(
        monkeypatch, ledger=None, in_window=True,
        leg_spawn=lambda leg, seen: started.append(leg) or ("OK", "review\nAGREE"))
    assert started == []
    assert {leg.leg: (leg.status, str(leg.detail)) for leg in result.legs} == {
        leg: ("DEGRADED", "window_unbudgeted_start")
        for leg in ("claude", "codex", "gemini", "grok")}


def _gemini_control_world(monkeypatch, tmp_path, *, issued):
    from phase_loop_runtime import panel_invoker as panel, seat_jail_qualification as jailq
    spawned = []
    session = SimpleNamespace(
        seat=SimpleNamespace(delivered_copy=b"copy", image_sha256="b" * 64,
                             admission_class="release_qualified", holder_pid=1,
                             seat_dir=tmp_path, token=b"tok", probe_jail=None,
                             jail=SimpleNamespace(profile_digest="7" * 64, env={})),
        proxy=SimpleNamespace(allowlist_sha256="6" * 64), prefix=(), paths=SimpleNamespace(),
        authorization=SimpleNamespace(staged_tree_sha256="d" * 64),
        quiescence_latch=SimpleNamespace(is_quiescent=lambda: True), trace_path=None,
        cleaned=False, cleanup=lambda: None)

    @contextlib.contextmanager
    def opened(spec):
        yield session
    watch = SimpleNamespace(prove_sentinel=lambda run: True,
                            drain_and_close=lambda quiescent: "watch")
    monkeypatch.setattr(panel, "_open_window_launch", opened)
    monkeypatch.setattr(jailq, "arm_watch", lambda *a, **k: watch)
    monkeypatch.setattr(jailq, "measure_issuer", lambda delivered: issued.append(1) or "issuer")
    monkeypatch.setattr(jailq, "scan_seat", lambda *a, **k: "scan")
    monkeypatch.setattr(panel._seat_egress_proxy, "fence",
                        lambda *a, **k: SimpleNamespace(acknowledged=True, acked_ns=None))
    monkeypatch.setattr(panel._seat_egress_proxy, "proxy_stream", lambda proxy: None)
    monkeypatch.setattr(panel._sandbox_egress, "wait_bridge_exit", lambda prefix: True)
    monkeypatch.setattr(panel, "_render_broker_pointer_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(panel, "_broker_gemini_stream_protocol",
                        lambda *a, **k: SimpleNamespace(transport="input"))
    monkeypatch.setattr(panel, "_run_window_process",
                        lambda session, command, **k: spawned.append(command)
                        or panel._WindowProcess(0, False, ""))
    return spawned


@pytest.mark.parametrize("allowance", [0, 1])
def test_k1_t4_the_gemini_issuer_request_is_reserved_immediately_before(tmp_path, monkeypatch,
                                                                        allowance):
    from phase_loop_runtime import panel_invoker as panel, seat_window_supply as supply
    issued = []
    spawned = _gemini_control_world(monkeypatch, tmp_path, issued=issued)
    ledger = _ledger(tmp_path, gemini_issuer=allowance)
    spec = panel.WindowLaunchSpec(kind="measured", qualification_input=SimpleNamespace(
        layout=SimpleNamespace(), commit="2" * 40), model="m", timeout_s=5)
    with supply.ledger_scope(ledger):
        if allowance == 0:
            with pytest.raises(supply.WindowRefused):
                panel.window_control_launch(spec)
            assert issued == [] and spawned == []
        else:
            panel.window_control_launch(spec)
            assert issued == [1]
    assert ledger.counts()["gemini_issuer"] == allowance
    issuer_lines = [line for line in _lines(ledger) if line["item"] == "gemini_issuer"]
    assert len(issuer_lines) == allowance


def test_k1_t5_reservations_are_not_dispatches_and_debit_once(tmp_path, monkeypatch):
    """K1-T5: a bulk reservation debits and records no route or launch time; each counted
    start is debited once across the call site and the provider boundary; an uncertain
    start still debits."""
    from phase_loop_runtime import panel_invoker as panel, seat_profiles
    from phase_loop_runtime import seat_window_supply as supply
    ledger = _ledger(tmp_path)
    ledger.reserve("agy_first_use", 3)
    reserve = _lines(ledger)[0]
    assert reserve["op"] == "reserve" and reserve["route"] is None
    assert reserve["launch_time"] is None
    with supply.ledger_scope(ledger), supply.item_scope("claude_seat"):
        supply.note_route(_agreeing(ledger, "claude_seat"))  # what the resolver reported
        with panel._window_call_site("claude_seat"):
            seat_profiles.window_provider_start(["claude", "-p"])  # consumes, no second debit
    assert ledger.counts()["claude_seat"] == 1
    dispatch = [line for line in _lines(ledger) if line["item"] == "claude_seat"]
    assert dispatch[0]["op"] == "dispatch" and dispatch[0]["route"] == "vendor:claude"
    assert dispatch[0]["launch_time"] == ROW_NOW.isoformat()
    # An uncertain start (the spawn raised after the reservation) still debits.
    with supply.ledger_scope(ledger), supply.item_scope("codex_seat"):
        supply.note_route(_agreeing(ledger, "codex_seat"))
        with pytest.raises(OSError):
            seat_profiles.window_provider_start(["codex", "exec"])
            raise OSError("spawn failed")
    assert ledger.counts()["codex_seat"] == 1


def test_k1_t5_a_used_seat_route_expired_at_launch_is_refused(tmp_path, monkeypatch,
                                                              fixture_vendor):
    world = _row_world(tmp_path, monkeypatch,
                       board_hook=lambda ledger: ledger.reserve("agy_first_use", 3))
    _expiring_rows(monkeypatch, expiry=(ROW_NOW - dt.timedelta(days=1)).isoformat(),
                   vendors=("gemini",))
    # Gemini's seat is a used entry here, so its expired exception refuses at dispatch.
    assert _run_row(world, monkeypatch)["code"] == "window_exception_expired"


def test_k1_t5_an_unused_reservation_of_an_expired_route_still_verifies(tmp_path, monkeypatch,
                                                                       fixture_vendor):
    world = _row_world(tmp_path, monkeypatch, dispatches=["subject", "claude_seat",
                                                          "fable_president"],
                       board_hook=lambda ledger: ledger.reserve("agy_first_use", 3))
    _expiring_rows(monkeypatch, expiry=(ROW_NOW - dt.timedelta(days=1)).isoformat(),
                   vendors=("gemini", "grok"))
    assert _run_row(world, monkeypatch)["code"] == "window_review_required"
    assert world.verify()["passed"] is True


# --- §5.1 credential seams and F16: through the real prepare functions. ---

def _codex_prepare_stubs(monkeypatch, tmp_path):
    from phase_loop_runtime import panel_invoker as panel, seat_codex_credential as cred
    from phase_loop_runtime import seat_codex_runtime, seat_profile_codex
    from phase_loop_runtime.seat_subject import SeatSubject
    seen = {"installed": [], "builds": []}
    copy = cred.CodexSeatCopy(data=b'{"tokens":"fixture"}', secrets=(b"fixture-token",),
                              tokens_sha256="0" * 64, expires_at=10 ** 10)
    root = tmp_path / "vendor/x86_64-unknown-linux-musl"
    for relative in seat_codex_runtime.CODEX_RUNTIME_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b"fixture codex image")
        path.chmod(0o755 if relative.startswith(("bin/", "codex-path/")) else 0o644)
    for directory in (tmp_path / "vendor", root, root / "bin", root / "codex-path"):
        directory.chmod(0o755)
    image = root / "bin/codex"
    seen["image_sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()

    monkeypatch.setattr(panel, "_approved_stage_or_refuse", lambda d, a: tmp_path / "tree")
    monkeypatch.setattr(panel, "_resolved_jail_subject", lambda leg, env: (
        SeatSubject("codex", "standalone", image, None, None), None))
    monkeypatch.setattr(panel, "_validate_jail_dependency", lambda leg, dependency: None)
    monkeypatch.setattr(seat_profile_codex, "validate_codex_projection", lambda d: None)
    monkeypatch.setattr(seat_profile_codex, "codex_admission_gate", lambda *a, **k: None)
    monkeypatch.setattr(cred, "read_auth", lambda env: {"fixture": "login"})
    for name in ("subscription_login_problem", "scope_problem"):
        monkeypatch.setattr(cred, name, lambda raw: None)
    monkeypatch.setattr(cred, "token_margin_problem", lambda raw, now: None)
    monkeypatch.setattr(cred, "build_seat_copy", lambda raw: copy)
    monkeypatch.setattr(cred, "install_seat_copy",
                        lambda fd, value: seen["installed"].append(value))
    monkeypatch.setattr(panel, "_write_egress_ca", lambda directory, ca: directory / "ca.pem")

    def build(leg, seat_dir, executable, **kwargs):
        runtime_handle = kwargs.get("standalone_runtime")
        normalized = {}
        for key, value in kwargs.items():
            if key == "egress_ca":
                continue
            if key == "standalone_runtime" and value is not None:
                normalized[key] = value.projection_digest
            else:
                normalized[key] = value
        seen["builds"].append((leg, normalized))
        return SimpleNamespace(provider_argv0="/seat/bin/codex", env={}, profile_digest="7" * 64,
                               filter_digest="8" * 64, pass_fds=(), profile_id="codex",
                               provider_path=str(image), standalone_runtime=runtime_handle)
    monkeypatch.setattr(panel, "_build_jail_with_owned_inputs", build)
    monkeypatch.setattr(panel._seat_jail, "open_dir_nofollow",
                        lambda path: os.open(str(tmp_path), os.O_RDONLY))
    monkeypatch.setattr(panel._seat_jail, "close_jail_fds", lambda jail: None)
    seen["copy"] = copy
    return seen


def _prepare_codex(tmp_path, name, **kwargs):
    from phase_loop_runtime import panel_invoker as panel
    return panel._prepare_jailed_codex(
        tmp_path / "review", tmp_path / name, SimpleNamespace(staged_tree_sha256="c" * 64), 1, 2,
        ("artifact", "instructions"), SimpleNamespace(ca_cert=b"ca", proxy_url="http://p"),
        **kwargs)


def test_k1_codex_seam_live_is_byte_for_byte_production(tmp_path, monkeypatch):
    seen = _codex_prepare_stubs(monkeypatch, tmp_path)
    default = _prepare_codex(tmp_path, "seat-a")
    live = _prepare_codex(tmp_path, "seat-b", credential_mode="live")
    assert seen["installed"] == [seen["copy"], seen["copy"]]
    assert seen["builds"][0] == seen["builds"][2] and seen["builds"][1] == seen["builds"][3]
    assert (default.codex_copy, default.delivered_copy, default.expires_at) == (
        live.codex_copy, live.delivered_copy, live.expires_at)


def test_k1_codex_seam_none_builds_no_credential(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_codex_credential as cred
    seen = _codex_prepare_stubs(monkeypatch, tmp_path)
    monkeypatch.setattr(cred, "build_seat_copy", lambda raw: pytest.fail("copy built"))
    reads = []
    monkeypatch.setattr(cred, "read_auth", lambda env: reads.append(1) or {"fixture": 1})
    seat = _prepare_codex(tmp_path, "seat", credential_mode="none")
    assert seen["installed"] == [] and seat.codex_copy is None and seat.delivered_copy == b""
    assert reads == [1]  # the read-only login checks still run


def test_k1_codex_seam_expired_applies_the_transform(tmp_path, monkeypatch):
    seen = _codex_prepare_stubs(monkeypatch, tmp_path)
    aged = dataclasses.replace(seen["copy"], data=b'{"last_refresh":"aged"}')
    seat = _prepare_codex(tmp_path, "seat", credential_mode="expired",
                          copy_transform=lambda copy: aged if copy == seen["copy"] else None)
    assert seen["installed"] == [aged] and seat.codex_copy == aged
    with pytest.raises(ValueError):
        _prepare_codex(tmp_path, "seat-2", credential_mode="expired")
    with pytest.raises(ValueError):
        _prepare_codex(tmp_path, "seat-3", credential_mode="other")


def _claude_prepare_stubs(monkeypatch, tmp_path):
    from phase_loop_runtime import panel_invoker as panel
    tokens = []
    monkeypatch.setattr(panel._claude_seat_transport, "is_admitted", lambda transport: True)
    monkeypatch.setattr(panel, "_resolved_jail_subject", lambda leg, env: (
        SimpleNamespace(subject_path=tmp_path / "claude"), None))
    monkeypatch.setattr(panel, "_validate_jail_dependency", lambda leg, dependency: None)
    monkeypatch.setattr(panel._seat_jail, "open_dir_nofollow",
                        lambda path: os.open(str(tmp_path), os.O_RDONLY))
    monkeypatch.setattr(panel._seat_jail, "tree_manifest_sha256_at", lambda fd: "c" * 64)
    monkeypatch.setattr(panel._seat_jail, "CLAUDE_PRESEED", None)
    reads = []
    monkeypatch.setattr(panel._seat_credentials, "resolve_claude_seat_credential",
                        lambda margin: reads.append(margin) or SimpleNamespace(
                            token=b"live-token", source="login", expires_at=1.0, notices=()))

    def build(leg, seat_dir, executable, *, token, **kwargs):
        tokens.append(token)
        return SimpleNamespace(dependency_projection_digest=None)
    monkeypatch.setattr(panel, "_build_jail_with_owned_inputs", build)
    return tokens, reads


def _prepare_claude(tmp_path, name, **kwargs):
    from phase_loop_runtime import panel_invoker as panel
    return panel._prepare_jailed_claude(
        tmp_path / "review", tmp_path / name, SimpleNamespace(staged_tree_sha256="c" * 64), 1, 2,
        ("artifact", "instructions"), transport="print", **kwargs)


def test_k1_claude_seam_live_none_and_expired(tmp_path, monkeypatch):
    """Through the real ``_prepare_jailed_claude``, the provider stubbed at its spawn
    boundary (the jail build): ``live`` is production, ``none`` delivers no credential and
    ``expired`` delivers the transform of the live token."""
    tokens, reads = _claude_prepare_stubs(monkeypatch, tmp_path)
    default = _prepare_claude(tmp_path, "a")
    live = _prepare_claude(tmp_path, "b", credential_mode="live")
    assert tokens[:4] == [b"live-token", b"probe", b"live-token", b"probe"]
    assert default.token == live.token == b"live-token"
    none = _prepare_claude(tmp_path, "c", credential_mode="none")
    assert tokens[4] is None and none.token == b"" and len(reads) == 3
    expired = _prepare_claude(tmp_path, "d", credential_mode="expired",
                              copy_transform=lambda token: b"refused:" + token)
    assert tokens[6] == b"refused:live-token" and expired.token == b"refused:live-token"
    with pytest.raises(ValueError):
        _prepare_claude(tmp_path, "e", credential_mode="expired")


def _codex_open_stubs(monkeypatch, tmp_path, *, proxy_error=None):
    from phase_loop_runtime import panel_invoker as panel
    seen = _codex_prepare_stubs(monkeypatch, tmp_path)
    seen.update(proxies=[], spawned=[])
    authorization = SimpleNamespace(staged_tree_sha256="d" * 64)
    monkeypatch.setattr(panel._review_stage, "host_git", lambda *a, **k: SimpleNamespace(
        stdout="2" * 40 + "\n"))
    monkeypatch.setattr(panel, "prepare_review_isolation_authorization",
                        lambda *a, **k: authorization)
    monkeypatch.setattr(panel, "activate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(panel, "close_review_isolation_authorization", lambda a: None)
    monkeypatch.setattr(panel._sandbox_policy, "staging_root", lambda: tmp_path)

    def stage(source, parent):
        path = parent / "staged"
        path.mkdir()
        return path
    monkeypatch.setattr(panel._review_stage, "stage_review_tree", stage)
    monkeypatch.setattr(panel._review_stage, "staged_source_commit", lambda tree: "2" * 40)
    monkeypatch.setattr(panel._review_stage, "remove_review_stage", lambda base: None)
    monkeypatch.setattr(panel._seat_uid, "subordinate_range", lambda path: (1, 2))
    monkeypatch.setattr(panel._seat_uid, "seat_id_count", lambda u, g: 1)
    monkeypatch.setattr(panel._seat_uid, "lease_seat_id", lambda n: contextlib.nullcontext(7))
    monkeypatch.setattr(panel._seat_uid, "holder_pid_from_prefix", lambda prefix: 99)

    @contextlib.contextmanager
    def start_proxy(*, allowlist_id, refuse_all, named=()):
        if proxy_error is not None:
            raise proxy_error
        seen["proxies"].append((allowlist_id, refuse_all))
        seen.setdefault("named", []).append(tuple(named))
        yield SimpleNamespace(socket="sock", allowlist_sha256="6" * 64, ca_cert=b"ca",
                              proxy_url="http://proxy")
    monkeypatch.setattr(panel._seat_egress_proxy, "start_proxy", start_proxy)
    monkeypatch.setattr(panel._sandbox_egress, "isolated_network",
                        lambda **k: contextlib.nullcontext(("nsenter", "-t", "99")))
    monkeypatch.setattr(panel._seat_egress_proxy, "fence",
                        lambda *a, **k: SimpleNamespace(acknowledged=True, acked_ns=None))
    monkeypatch.setattr(panel._seat_egress_proxy, "proxy_stream", lambda proxy: "stream")
    monkeypatch.setattr(panel._sandbox_egress, "wait_bridge_exit", lambda prefix: True)
    monkeypatch.setattr(panel, "_cleanup_jailed_seat", lambda seat, **k: None)
    monkeypatch.setattr(panel, "_exec_jailed_codex_leg",
                        lambda *a, **k: pytest.fail("a control launch used the board exec"))
    return seen


def _codex_spec(kind, tmp_path):
    from phase_loop_runtime import panel_invoker as panel
    repo = tmp_path / "input"
    repo.mkdir(exist_ok=True)
    return panel.WindowLaunchSpec(kind=kind, qualification_input=SimpleNamespace(
        repo=repo, commit="2" * 40, layout=SimpleNamespace()), model="m", timeout_s=5,
        leg="codex")


def _watch_stub(fixture_vendor, monkeypatch):
    watch = SimpleNamespace(prove_sentinel=lambda run: True,
                            drain_and_close=lambda quiescent: "watch")
    monkeypatch.setattr(fixture_vendor.module, "arm_watch", lambda *a, **k: watch)
    monkeypatch.setattr(fixture_vendor.module, "seed_runtime_plants", lambda *a: None)


@pytest.mark.parametrize("kind,installed,refuse_all", [
    ("tree_control", "none", True), ("measured", "live", False),
    ("expired_copy", "expired", False)])
def test_k1_f16_codex_control_launches_through_the_real_prepare(
        tmp_path, monkeypatch, fixture_vendor, kind, installed, refuse_all):
    from phase_loop_runtime import panel_invoker as panel, seat_resource_caps
    seen = _codex_open_stubs(monkeypatch, tmp_path)
    _watch_stub(fixture_vendor, monkeypatch)

    def run(command, **kwargs):
        scope = seat_resource_caps._CURRENT_SEAT_SCOPE.get()
        assert scope.launch_class is seat_resource_caps._LaunchClass.QUALIFICATION
        seen["spawned"].append(list(command))
        return SimpleNamespace(returncode=0, stdout="completed")

    monkeypatch.setattr(panel, "_run_leg_with_liveness", run)
    result = panel.window_control_launch(_codex_spec(kind, tmp_path))
    assert seen["proxies"] == [("codex", refuse_all)]
    expect = {"none": [], "live": [seen["copy"]],
              "expired": [dataclasses.replace(seen["copy"], data=b"aged:" + seen["copy"].data)]}
    assert seen["installed"] == expect[installed]
    # Exactly once, with the supplier's argv, and the binding names that argv.
    assert seen["spawned"] == [["/seat/bin/codex", "exec", "--model", "m", "--json", kind]]
    assert result.binding.argv_sha256 == panel._window_json_digest([seen["spawned"][0]])
    assert result.status == "SUCCESS" and result.error is None
    assert result.binding.stage_manifest_sha256 == "d" * 64


@pytest.mark.parametrize("failure,expected", [
    ("timeout", "timeout"), ("jail", "jail_failure"), ("not_ready", "not_ready"),
    ("proxy", "proxy_failure"), ("incomplete", "stream_incomplete")])
def test_k1_f16_codex_failure_modes_reach_a_closed_terminal_class(
        tmp_path, monkeypatch, fixture_vendor, failure, expected):
    from phase_loop_runtime import panel_invoker as panel, seat_window_supply as supply
    from phase_loop_runtime import seat_codex_credential as cred, seat_window_supply_gemini
    seen = _codex_open_stubs(monkeypatch, tmp_path, proxy_error=(
        panel._seat_egress_proxy.EgressLayerUnavailable("seat_egress_proxy_unavailable", "fixture")
        if failure == "proxy" else None))
    _watch_stub(fixture_vendor, monkeypatch)
    if failure == "jail":
        monkeypatch.setattr(panel, "_build_jail_with_owned_inputs", lambda *a, **k: (
            _ for _ in ()).throw(panel._seat_jail.SeatSandboxRefused("seat_sandbox_refused:jail_build")))
    if failure == "not_ready":
        monkeypatch.setattr(cred, "token_margin_problem",
                            lambda raw, now: "codex_seat_token_expiring")

    def spawn(command, **kwargs):
        seen["spawned"].append(command)
        if failure == "timeout":
            raise panel.subprocess.TimeoutExpired(command, 5)
        return SimpleNamespace(returncode=0, stdout="" if failure == "incomplete" else "completed")
    monkeypatch.setattr(panel, "_run_leg_with_liveness", spawn)
    result = panel.window_control_launch(_codex_spec("measured", tmp_path))
    terminal = seat_window_supply_gemini.terminal(result)
    assert terminal == expected and terminal in supply.TERMINAL_CLASSES
    assert len(seen["spawned"]) <= 1


def test_k1_f16_a_kind_outside_the_vendors_launch_kinds_is_a_contract_bug(
        tmp_path, monkeypatch, fixture_vendor):
    from phase_loop_runtime import panel_invoker as panel
    _codex_open_stubs(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="contract_bug"):
        panel.window_control_launch(_codex_spec("plugin_validation", tmp_path))


def test_k1_f16_a_codex_subject_launch_reserves_before_its_spawn(tmp_path, monkeypatch,
                                                                fixture_vendor):
    from phase_loop_runtime import panel_invoker as panel, seat_window_supply as supply
    seen = _codex_open_stubs(monkeypatch, tmp_path)
    _watch_stub(fixture_vendor, monkeypatch)
    ledger = _ledger(tmp_path, vendor="codex", subject=0)
    monkeypatch.setattr(panel, "_run_leg_with_liveness",
                        lambda command, **k: pytest.fail("spawned past the envelope"))
    with supply.ledger_scope(ledger), pytest.raises(supply.WindowRefused):
        panel.window_control_launch(_codex_spec("measured", tmp_path))


# --- F17 / K1-T8 (SL-5 part): hook ownership for the Gemini and Codex legs. ---

def _hook_calls(function):
    import ast, inspect, textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    counts = {"start": 0, "finish": 0}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "window_board"
                and node.func.attr in counts):
            counts[node.func.attr] += 1
    return counts


def test_k1_t8_each_existing_leg_has_exactly_one_hook_call_site():
    from phase_loop_runtime import panel_invoker as panel
    for leg in (panel._exec_jailed_gemini_leg, panel._exec_jailed_codex_leg):
        assert _hook_calls(leg) == {"start": 1, "finish": 1}, leg.__name__


def test_k1_t8_window_board_reaches_only_the_window_leg():
    import inspect
    from phase_loop_runtime import panel_invoker as panel
    authorization = SimpleNamespace(staged_tree_sha256="c" * 64)
    for leg in ("gemini", "codex"):
        with panel._window_board_registration(authorization, SimpleNamespace(), leg=leg) as run:
            for other in ("claude", "codex", "gemini", "grok"):
                hook = panel._window_leg_hook(authorization, other)
                assert hook is (run if other == leg else None)
    source = inspect.getsource(panel._default_spawn)
    assert source.count("_window_leg_hook(review_authorization, leg)") == 1
    assert '_registered_window_board(review_authorization) if leg == "gemini"' not in source


def _codex_leg_world(monkeypatch, tmp_path, events, *, provider="ok"):
    from phase_loop_runtime import panel_invoker as panel, seat_codex_credential as cred
    from phase_loop_runtime import seat_codex_evidence as evidence, seat_profile_codex
    copy = cred.CodexSeatCopy(data=b"{}", secrets=(b"tok",), tokens_sha256="0" * 64,
                              expires_at=10 ** 10)
    seat = SimpleNamespace(codex_copy=copy, holder_pid=1, seat_dir=tmp_path, notices=[],
                           probe_jail=None,
                           jail=SimpleNamespace(provider_argv0="/seat/bin/codex", env={},
                                                profile_digest="7" * 64, filter_digest="8" * 64,
                                                profile_id="codex"))
    monkeypatch.setattr(seat_profile_codex, "jailed_codex_command",
                        lambda inputs: ("/seat/bin/codex", "exec", "--json"))
    monkeypatch.setattr(panel, "_record_broker_provider_evidence", lambda *a, **k: None)
    monkeypatch.setattr(panel, "_record_executable_dependency_evidence", lambda *a, **k: None)
    monkeypatch.setattr(panel, "_note_exec_result", lambda *a, **k: None)
    monkeypatch.setattr(panel, "_cleanup_jailed_seat", lambda *a, **k: events.append("cleanup"))
    monkeypatch.setattr(panel._seat_uid, "read_in_h", lambda *a: b"")
    monkeypatch.setattr(cred, "tokens_changed", lambda copy, observed: False)
    monkeypatch.setattr(evidence, "read_tool_record", lambda raw: SimpleNamespace(
        commands_completed=1, turn_completed=True))
    monkeypatch.setattr(evidence, "tools_ran_code", lambda record: None)
    monkeypatch.setattr(panel, "_classify_leg", lambda *a: "OK")

    def spawn(command, **kwargs):
        events.append(("provider", tuple(command)))
        if provider == "raise":
            raise RuntimeError("provider failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(panel, "_run_leg_with_liveness", spawn)
    return seat


def _gemini_leg_world(monkeypatch, tmp_path, events, *, provider="ok"):
    from phase_loop_runtime import panel_invoker as panel
    seat = SimpleNamespace(token=b"tok", private_proxy_token=b"fixture",
                           expires_at=None, notices=[], probe_jail=None,
                           image_sha256="b" * 64, admission_class="release_qualified",
                           jail=SimpleNamespace(env={}, profile_digest="7" * 64,
                                                filter_digest="8" * 64, profile_id="gemini",
                                                redacted_owner=lambda: ()))
    monkeypatch.setattr(panel, "_record_broker_provider_evidence", lambda *a, **k: None)
    monkeypatch.setattr(panel, "_record_executable_dependency_evidence", lambda *a, **k: None)
    monkeypatch.setattr(panel, "_cleanup_jailed_seat", lambda *a, **k: events.append("cleanup"))
    monkeypatch.setattr(panel, "_note_exec_result", lambda *a, **k: None)
    monkeypatch.setattr(panel, "_broker_gemini_stream_protocol", lambda *a, **k: SimpleNamespace(
        transport="input", protocol="fixture", chunk_sha256=(), chunk_bytes=(),
        final_event_sha256="f" * 64))
    monkeypatch.setattr(panel, "_broker_gemini_stream_result",
                        lambda *a, **k: (0, "review\nAGREE", "", {"provider_stream_tool_steps": 1}))
    monkeypatch.setattr(panel, "_classify_leg", lambda *a: "OK")

    def spawn(command, **kwargs):
        events.append(("provider", tuple(command)))
        if provider == "raise":
            raise RuntimeError("provider failed")
        return SimpleNamespace(returncode=0, stdout="stream", stderr="")
    monkeypatch.setattr(panel, "_run_leg_with_liveness", spawn)
    return seat


@pytest.mark.parametrize("leg", ["gemini", "codex"])
@pytest.mark.parametrize("path", ["normal", "refused", "raised"])
def test_k1_t8_the_hook_finishes_before_teardown_and_binds_the_spawned_argv(
        tmp_path, monkeypatch, leg, path):
    from phase_loop_runtime import panel_invoker as panel
    events = []
    world = _gemini_leg_world if leg == "gemini" else _codex_leg_world
    seat = world(monkeypatch, tmp_path, events, provider="raise" if path == "raised" else "ok")
    bound = []
    observer = SimpleNamespace(proxy=object(), tool_steps=None)
    observer.start = lambda seat_, proxy, latch, command, prompt, auth: (
        events.append("start") or bound.append(tuple(command)) or path != "refused")
    observer.finish = lambda *a: events.append("finish")
    execute = panel._exec_jailed_gemini_leg if leg == "gemini" else panel._exec_jailed_codex_leg
    kwargs = dict(deadline_s=3, model="m", prompt="frame", broker_evidence=None,
                  quiescence_latch=panel._ProviderQuiescenceLatch(), window_board=observer,
                  review_authorization=SimpleNamespace(staged_tree_sha256="c" * 64))
    if path == "raised":
        with pytest.raises(RuntimeError):
            execute(seat, **kwargs)
    else:
        execute(seat, **kwargs)
    spawned = [event[1] for event in events if isinstance(event, tuple)]
    names = [event if isinstance(event, str) else "provider" for event in events]
    if path == "refused":
        assert names == ["start", "finish", "cleanup"] and spawned == []
    else:
        assert names == ["start", "provider", "finish", "cleanup"]
        assert bound == spawned  # the argv the hook bound is the argv spawned


def test_k1_t8_the_runtime_binding_digests_the_spawned_argv(tmp_path, monkeypatch,
                                                            fixture_vendor):
    """The real board runtime's ``start`` for a Codex window leg: its launch binding names
    exactly the argv the leg then spawns."""
    from phase_loop_runtime import panel_invoker as panel
    events = []
    seat = _codex_leg_world(monkeypatch, tmp_path, events)
    seat.image_sha256, seat.admission_class = "b" * 64, "release_qualified"
    _watch_stub(fixture_vendor, monkeypatch)
    monkeypatch.setattr(panel._seat_egress_proxy, "fence",
                        lambda *a, **k: SimpleNamespace(acknowledged=True))
    monkeypatch.setattr(panel._sandbox_egress, "wait_bridge_exit", lambda prefix: True)
    runtime = panel._WindowBoardLegRuntime(SimpleNamespace(layout=SimpleNamespace()),
                                           leg="codex")
    runtime.proxy = SimpleNamespace(allowlist_sha256="6" * 64)
    panel._exec_jailed_codex_leg(
        seat, deadline_s=3, model="m", prompt="frame", broker_evidence=None,
        quiescence_latch=panel._ProviderQuiescenceLatch(), window_board=runtime,
        review_authorization=SimpleNamespace(staged_tree_sha256="c" * 64))
    spawned = [event[1] for event in events if isinstance(event, tuple)]
    assert runtime.started_argv == spawned
    assert runtime.binding.argv_sha256 == panel._window_json_digest(spawned[0])
    assert runtime.watch == "watch" and runtime.tool_steps == 1


# --- F15: the CLI, in a fresh process where it matters. ---

_FRESH = r'''
import json, sys
from phase_loop_runtime import cli
from phase_loop_runtime.seat_window_supply import SUPPLIERS
argv = json.loads(sys.argv[1])
if argv[0] == "--parse":
    import argparse
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    from phase_loop_runtime.seat_window import register_parser
    register_parser(sub)
    args = parser.parse_args(argv[1:])
    loaded = sorted(name for name in sys.modules
                    if name.split(".")[-1] in set(SUPPLIERS.values()))
    print(json.dumps({"action": args.action, "vendor": args.vendor, "window": args.window,
                      "loaded": loaded}))
    raise SystemExit(0)
import os
from pathlib import Path
from phase_loop_runtime import seat_window
# Never reach the passwd-home W1 grant from a test (see conftest _isolate_w1_owner_grant).
seat_window._w1_grant_dir = lambda: Path(os.environ["TEST_W1_GRANT_DIR"])
raise SystemExit(cli.main(argv))
'''


def _fresh(tmp_path, argv):
    import subprocess
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home"),
           "XDG_STATE_HOME": str(tmp_path / "state"),
           "TEST_W1_GRANT_DIR": str(tmp_path / "w1-admission"),
           "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    done = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); "
                           % env["PYTHONPATH"] + _FRESH, json.dumps(argv)],
                          capture_output=True, text=True, env=env, timeout=120)
    return done.returncode, done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""


def test_k1_f15_parsing_imports_no_supplier(tmp_path):
    code, out = _fresh(tmp_path, ["--parse", "seat-window", "qualify", "--window", "row",
                                  "--vendor", "codex"])
    assert code == 0 and json.loads(out) == {"action": "qualify", "vendor": "codex",
                                             "window": "row", "loaded": []}
    code, out = _fresh(tmp_path, ["--parse", "seat-window", "status"])
    assert json.loads(out)["vendor"] is None  # Grok's actions keep grok as their default


def test_k1_f15_bare_qualify_is_gemini_w1(tmp_path):
    code, out = _fresh(tmp_path, ["seat-window", "qualify"])
    assert code == 1 and json.loads(out)["code"] == "window_owner_approval_required"


def _unlanded_table_vendor():
    """The first table vendor whose supplier module has not landed, computed now. When
    every supplier has landed the case must be rewritten to hide a module, so it fails."""
    import importlib.util
    from phase_loop_runtime.seat_window_supply import SUPPLIERS
    for vendor, name in SUPPLIERS.items():
        if importlib.util.find_spec("phase_loop_runtime." + name) is None:
            return vendor
    pytest.fail("every table vendor has a landed supplier: rewrite this case to hide one")


@pytest.mark.parametrize("argv", [["--window", "W1", "--vendor", "codex"],
                                  ["--window", "row", "--vendor", "<unlanded>"]])
def test_k1_f15_an_invalid_pair_is_unavailable_before_any_claim(tmp_path, argv):
    argv = [_unlanded_table_vendor() if arg == "<unlanded>" else arg for arg in argv]
    code, out = _fresh(tmp_path, ["seat-window", "qualify", "--attended", *argv])
    assert code == 1 and json.loads(out)["code"] == "window_vendor_unavailable"
    assert not (tmp_path / "state").exists()


def test_k1_f15_the_unscoped_matrix_is_the_base_matrix(tmp_path):
    from phase_loop_runtime import seat_window as w
    code, out = _fresh(tmp_path, ["seat-window", "matrix"])
    assert code == 0 and json.loads(out) == json.loads(json.dumps(w.readiness_rows()))


def test_k1_f15_a_mixed_record_set_with_read_errors_dup_and_tie(row_world, monkeypatch,
                                                                tmp_path, capsys):
    from phase_loop_runtime import cli, seat_window as w
    w1 = _w1_records(monkeypatch, tmp_path)
    monkeypatch.setattr(w, "_now", lambda: dt.datetime(2026, 11, 5, tzinfo=dt.timezone.utc))
    root = row_world.root
    paths = [_REAL_WRITE(f"window-W1-{w1[0]['context_id']}.json", w1[0])]
    paths.append(next(root.glob("window-row-codex-*.json")))
    broken = root / "window-row-codex-cbroken.json"
    broken.write_text("{")
    broken.chmod(0o600)
    args = [arg for path in [*paths, broken] for arg in ("--record", str(path))]
    capsys.readouterr()
    assert cli.main(["seat-window", "matrix", *args]) == 0
    rows = {row["id"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["vendor:gemini"]["status"] == "done-local"
    assert rows["vendor:codex"]["status"] == "candidate"  # its read error fails only it
    assert cli.main(["seat-window", "matrix", *args, "--vendor", "codex"]) == 0
    rows = {row["id"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["vendor:gemini"]["status"] == "candidate"
    dup = root / "window-row-codex-cdup.json"
    dup.write_bytes(paths[1].read_bytes())
    dup.chmod(0o600)
    args = [arg for path in [*paths, dup] for arg in ("--record", str(path))]
    assert cli.main(["seat-window", "verify", "--window", "row", "--vendor", "codex",
                     *args]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "window_duplicate_records"


def test_k1_f15_batch_exit_codes(tmp_path, monkeypatch, fixture_vendor, capsys):
    from phase_loop_runtime import cli, seat_window as w
    world = _row_world(tmp_path, monkeypatch)
    capsys.readouterr()
    assert cli.main(["--repo", str(tmp_path), "seat-window", "qualify", "--window", "row",
                     "--attended"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["vendors"] == {"codex": "window_review_required"}
    assert world.verify()["passed"] is True
    # The row is now done-local: nothing is eligible and the batch exits 1.
    assert cli.main(["--repo", str(tmp_path), "seat-window", "qualify", "--window", "row",
                     "--attended"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "window_no_eligible_vendor"
    monkeypatch.setattr(w, "batch_candidates", lambda: ["codex", "gemini"])
    monkeypatch.setattr(w, "_qualify_row", lambda vendor, **k: {
        "code": "window_review_required" if vendor == "codex" else "review_composition_refused"})
    assert cli.main(["--repo", str(tmp_path), "seat-window", "qualify", "--window", "row",
                     "--attended"]) == 1
    assert json.loads(capsys.readouterr().out)["vendors"] == {
        "codex": "window_review_required", "gemini": "review_composition_refused"}


def test_k1_f15_ready_only_reads(tmp_path, monkeypatch, fixture_vendor, capsys):
    from phase_loop_runtime import cli, seat_window as w
    world = _row_world(tmp_path, monkeypatch)
    monkeypatch.setattr(w, "claim_window_attempt", lambda *a, **k: pytest.fail("claimed"))
    monkeypatch.setattr(w, "preflight", lambda **k: pytest.fail("preflight"))
    cli.main(["seat-window", "ready", "--window", "row", "--vendor", "codex"])
    out = json.loads(capsys.readouterr().out)
    assert out["grant"] is True and out["available"] is True and set(out["logins"]) >= {
        "claude", "codex", "gemini"}
    assert not list(world.root.glob("window-attempt-*"))


# --- K1-G3: provider-free confirmation of §14 (a degraded Grok co-seat). ---

def _post_train_a_grok(monkeypatch):
    """Grok as the GROK contract's post-Train-A state registers it: an authenticated
    profile whose admission precondition refuses at L6 until GROK SL-6 admits it. (On this
    base Grok has no registered profile; see the lane report.)"""
    from phase_loop_runtime import seat_profiles
    from phase_loop_runtime.seat_route_contract import Precondition
    credential_reads = []
    grok = dataclasses.replace(
        seat_profiles.profile_for("codex"), leg="grok", vendor="grok", variant=None,
        credential_present=lambda: credential_reads.append(1) or True,
        preconditions=(Precondition("staged_admission", lambda: "grok_tool_surface_unverified"),),
        recorded_stop=None, window=None)
    monkeypatch.setitem(seat_profiles._REGISTRY, "grok", grok)
    return credential_reads


def test_k1_g3_degraded_grok_co_seat(tmp_path, monkeypatch, fixture_vendor):
    """K1-G3 end to end, provider-free: a Codex row window whose real four-seat board
    (``window_board_launch`` → ``invoke_board``: its pool, seat workers, retention and the
    president through the window wrapper) carries a Grok co-seat that refuses at L6 before
    any credential, through to a row that the production verifier passes."""
    from phase_loop_runtime import panel_invoker as panel, president_adapter, seat_profiles
    from phase_loop_runtime import seat_window as w, seat_window_supply as supply
    from phase_loop_runtime.seat_route_contract import QualificationKey
    from harden_tdd_guard import invoke_sanctioned_board_control
    from president_fakes import deferring_president
    credential_reads = _post_train_a_grok(monkeypatch)
    monkeypatch.setattr(panel._seat_jail, "seat_sandbox_capable", lambda: None)
    real_board_launch = panel.window_board_launch
    world = _row_world(tmp_path, monkeypatch, board_input=panel.window_board_input_sha256())
    boards = []
    monkeypatch.setattr(panel, "window_board_launch",
                        lambda spec: boards.append(real_board_launch(spec)) or boards[-1])
    # Grok's exception has expired by verification time; it is never a used entry.
    _expiring_rows(monkeypatch, expiry=(ROW_NOW + dt.timedelta(hours=2)).isoformat())
    _guard_provider_spawns(monkeypatch)
    outer = SimpleNamespace(staged_tree_sha256="d" * 64, monitoring_policy="bounded")
    # The board launch runs the composition the window bound at preflight; it never
    # recomposes (which would re-probe auth outside the envelope).
    monkeypatch.setattr("phase_loop_runtime.advisor_board.composition.compose_review_board_report",
                        lambda **kwargs: pytest.fail("the board launch recomposed"))
    monkeypatch.setattr(panel, "prepare_review_isolation_authorization", lambda *a, **k: outer)
    monkeypatch.setattr(panel, "close_review_isolation_authorization", lambda value: None)
    monkeypatch.setattr(panel, "set_review_instruction_digest", lambda value: object())
    monkeypatch.setattr(panel, "reset_review_instruction_digest", lambda token: None)
    monkeypatch.setattr(panel._sandbox_policy, "staging_root", lambda: tmp_path)

    def president(model, prompt):  # Fable, at its provider boundary
        seat_profiles.window_provider_start(["claude", "-p", "president"])
        return deferring_president(model, prompt)
    monkeypatch.setattr(president_adapter, "build_president_invoke", lambda *a, **k: president)
    monkeypatch.setattr(panel, "integrated_seat_subject",
                        lambda *a, **k: SimpleNamespace(subject_path=None))
    from phase_loop_runtime import agy_qualification
    monkeypatch.setattr(agy_qualification, "requalify_once", lambda *a, **k: None)
    monkeypatch.setattr(panel._seat_jail, "host_arch", lambda: "x86_64")
    watch = SimpleNamespace(prove_sentinel=lambda run: True,
                            drain_and_close=lambda quiescent: SimpleNamespace(
                                read_marker_opened=True))
    monkeypatch.setattr(fixture_vendor.module, "arm_watch", lambda *a, **k: watch)
    monkeypatch.setattr(panel._seat_egress_proxy, "fence",
                        lambda *a, **k: SimpleNamespace(acknowledged=True))
    monkeypatch.setattr(panel._sandbox_egress, "wait_bridge_exit", lambda prefix: True)
    key = QualificationKey(**{k: FIXTURE_LAUNCH_KEY[k] for k in (
        "profile_digest", "allowlist_digest", "falsifier_layout", "projection_digest",
        "variant", "host_identity")})
    inner = {}
    starts = []

    def resolved(leg):
        ledger = supply.active_ledger()
        evidence = _agreeing(ledger, supply.seat_item(leg, "codex"))
        exception = (SimpleNamespace(kind=evidence["exception"], expiry=dt.datetime.fromisoformat(
            evidence["expiry"])) if evidence["exception"] else None)
        panel._window_note_route(SimpleNamespace(mode=evidence["mode"], exception=exception,
                                                 code=None))

    @panel._retained_leg_exec
    def subject(leg, artifact):
        resolved(leg)
        runtime = panel._window_leg_hook(inner["authorization"], leg)
        seat = SimpleNamespace(image_sha256="b" * 64, admission_class="release_qualified",
                               jail=SimpleNamespace(profile_digest="7" * 64,
                                                    qualification_key=key),
                               probe_jail=None)
        runtime.proxy = SimpleNamespace(allowlist_sha256="6" * 64)
        command = ["/seat/bin/codex", "exec", "--json"]
        latch = panel._ProviderQuiescenceLatch()
        # The leg is handed the launcher's own authorization (``window_board_launch``
        # prepared it over the qualification input); the sanctioned protocol's minted one
        # only admits the injected provider boundary.
        assert runtime.start(seat, runtime.proxy, latch, command, "prompt", outer)
        seat_profiles.window_provider_start(command)
        starts.append(leg)
        panel._note_exec_result(0, command, {})
        panel._note_exec_signals(model_turn=True, verdict=True)
        runtime.tool_steps = 1
        runtime.finish(seat, (), latch)
        return ("OK", "review\nAGREE")

    def leg_spawn(leg, artifact):
        if leg == "codex":
            return subject(leg, artifact)
        if leg == "grok":  # the real resolver: L6 refuses before any credential
            route, notices, refusal = panel._seat_route_for_spawn(
                "grok", inner["authorization"], eligible=True)
            assert route.decision.steps[-1].step == "L6"
            return panel._BrokeredSpawnResult("DEGRADED", "", panel._HarnessCode(refusal),
                                              seat_notices=(refusal,))
        resolved(leg)
        seat_profiles.window_provider_start([leg, "-p", "review"])
        starts.append(leg)
        return ("OK", "review\nAGREE")

    real_invoke = panel.invoke_board

    def invoke(board, artifact, **kwargs):
        if kwargs.get("review_authorization") is outer:
            # The launcher's call: run it through the sanctioned protocol with the stubbed
            # provider boundary, carrying the launcher's window runtime and president.
            run = panel._registered_window_board(outer)
            def inner_invoke(board_, artifact_, **inner_kwargs):
                inner["authorization"] = inner_kwargs["review_authorization"]
                with panel._WINDOW_BOARD_RUNS_LOCK:
                    panel._WINDOW_BOARD_RUNS[id(inner["authorization"])] = run
                try:
                    return real_invoke(board_, artifact_, **inner_kwargs)
                finally:
                    with panel._WINDOW_BOARD_RUNS_LOCK:
                        panel._WINDOW_BOARD_RUNS.pop(id(inner["authorization"]), None)
            monkeypatch.setattr(panel, "invoke_board", inner_invoke)
            try:
                return invoke_sanctioned_board_control(
                    board, artifact, spawn=leg_spawn, landing_tier="plan",
                    president_invoke=kwargs["president_invoke"], max_concurrency=1)
            finally:
                monkeypatch.setattr(panel, "invoke_board", invoke)
        return real_invoke(board, artifact, **kwargs)
    monkeypatch.setattr(panel, "invoke_board", invoke)

    outcome = _run_row(world, monkeypatch)
    assert outcome["code"] == "window_review_required", outcome
    assert credential_reads and sorted(starts) == ["claude", "codex", "gemini"]
    ledger = [json.loads(line) for line in next(world.root.glob(
        "window-ledger-codex-*.jsonl")).read_text().splitlines()]
    items = [line["item"] for line in ledger if line["op"] == "dispatch"]
    assert "grok_seat" not in items and "fable_president" in items
    assert items.count("subject") == 5  # four credentialed controls and the board leg
    # The board carried the degraded Grok leg and its retained exec evidence.
    grok_runs = [path for path in world.root.glob("leg-*.json")
                 if json.loads(path.read_text())["vendor"] == "grok"]
    assert len(grok_runs) == 1
    assert boards[-1].leg_exec_records["grok"] == hashlib.sha256(
        grok_runs[0].read_bytes()).hexdigest()
    assert "grok" in boards[-1].co_seats and boards[-1].board_outcome == "terminated"
    world.now = ROW_NOW + dt.timedelta(days=1)  # Grok's exception has now expired
    assert world.verify()["passed"] is True, world.verify()
    before = {row["id"]: row for row in w.readiness_rows()}
    after = w.reduce_readiness(world.records(), now=world.now, source_root=world.root)
    assert {row["id"] for row in after if row != before[row["id"]]} == {"vendor:codex"}


def world_ledger_dispatch(item):
    from phase_loop_runtime import seat_window_supply as supply
    return supply.active_ledger().dispatch(item)


# ======================================================================================
# Fix round 1 (code review): new red-first guards.
# ======================================================================================

# --- Item 6: Claude ``none`` creates no credential channel, at the real build boundary. ---

def test_k1_claude_none_builds_no_token_pipe_at_the_real_jail_build(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as panel
    tokens, reads = _claude_prepare_stubs(monkeypatch, tmp_path)
    monkeypatch.setattr(panel, "_build_jail_with_owned_inputs", _REAL_BUILD)
    pipes, builds = [], []
    real_pipe = panel._seat_jail.token_pipe
    monkeypatch.setattr(panel._seat_jail, "token_pipe",
                        lambda token: pipes.append(token) or real_pipe(token))
    monkeypatch.setattr(panel._seat_jail, "build_seat_jail", lambda leg, directory, executable, **k:
                        builds.append(k.get("token_fd")) or SimpleNamespace(
                            dependency_projection_digest=None))
    _prepare_claude(tmp_path, "none", credential_mode="none")
    assert builds[0] is None and pipes == [b"probe"]  # only the probe jail's own marker
    pipes.clear()
    builds.clear()
    _prepare_claude(tmp_path, "live")
    assert isinstance(builds[0], int) and pipes == [b"live-token", b"probe"]


from phase_loop_runtime import panel_invoker as _pi_module  # noqa: E402

_REAL_BUILD = _pi_module._build_jail_with_owned_inputs


# --- Item 2: A4 Gemini renewals reserve under their own item. ---

def _renewal_world(monkeypatch, tmp_path, *, fresh):
    from phase_loop_runtime import panel_invoker as panel, seat_profiles
    spawned = []
    monkeypatch.setattr(panel, "_gemini_credential_fresh", lambda home: fresh[0])

    def launch(argv, **kwargs):
        seat_profiles.window_provider_start(argv)  # the real boundary launch_provider runs
        spawned.append(list(argv))
        fresh[0] = True
        return SimpleNamespace(communicate=lambda timeout: ("", ""), stdout=None, stderr=None,
                               returncode=0)
    monkeypatch.setattr(panel, "launch_provider", launch)
    monkeypatch.setattr(panel, "_anchor_process_group", lambda process: None)
    monkeypatch.setattr(panel, "_terminate_process_group", lambda process: None)
    monkeypatch.setattr(panel, "_names_provider", lambda argv: True)  # a recognized image
    image = SimpleNamespace(reopen=lambda: os.open("/dev/null", os.O_RDONLY))
    return spawned, image


@pytest.mark.parametrize("case", ["fresh", "blocked", "attempted"])
def test_k1_a4_renewals_reserve_under_their_own_item(tmp_path, monkeypatch, case):
    from phase_loop_runtime import panel_invoker as panel, seat_window_supply as supply
    spawned, image = _renewal_world(monkeypatch, tmp_path, fresh=[case == "fresh"])
    ledger = _ledger(tmp_path, agy_renewal=0 if case == "blocked" else 1, gemini_seat=1)
    with supply.ledger_scope(ledger), supply.item_scope("gemini_seat"):
        supply.note_route(_agreeing(ledger, "gemini_seat"))
        if case == "blocked":
            with pytest.raises(supply.WindowRefused):
                panel._refresh_gemini_credential(tmp_path, image)
        else:
            panel._refresh_gemini_credential(tmp_path, image)
    counts = ledger.counts()
    assert counts["gemini_seat"] == 0  # the review launch's budget is untouched
    assert counts["agy_renewal"] == (1 if case == "attempted" else 0)
    assert spawned == ([] if case != "attempted" else [spawned[0]])


# --- Item 1: R6 checks the route each start actually resolved. ---

@pytest.mark.parametrize("disagreement", ["mode", "exception", "expiry", "none"])
def test_k1_r6_a_resolved_route_disagreeing_with_the_snapshot_refuses_before_spawn(
        tmp_path, monkeypatch, disagreement):
    from phase_loop_runtime import panel_invoker as panel, seat_profiles
    from phase_loop_runtime import seat_window_supply as supply
    # Grok is this test's unconfined vendor; hide its registered profile (GROK SL-2) so the
    # matrix keeps that exception for the fixture.
    monkeypatch.delitem(seat_profiles._REGISTRY, "grok")
    ledger = _ledger(tmp_path)

    class Spawned(Exception):
        pass

    def popen(*a, **k):
        raise Spawned
    monkeypatch.setattr(panel.subprocess, "Popen", popen)
    monkeypatch.setattr(panel, "_compose_launch_prefix", lambda *a, **k: [])
    monkeypatch.setattr(panel, "_probes_seat", lambda *a, **k: False)
    monkeypatch.setattr(panel, "_owner_unshares_pid", lambda owner: False)
    entry = ledger.snapshot["vendor:grok"]
    exception = SimpleNamespace(kind=entry["exception"], expiry=dt.datetime.fromisoformat(
        entry["expiry"])) if entry["exception"] else None
    decision = SimpleNamespace(mode="unconfined", exception=exception, code=None)
    if disagreement == "mode":
        decision.mode = "jailed"
    elif disagreement == "exception":
        decision.exception = None
    elif disagreement == "expiry":
        decision.exception = SimpleNamespace(kind="unconfined", expiry=dt.datetime(
            2027, 1, 1, tzinfo=dt.timezone.utc))
    authorization = SimpleNamespace(staged_tree_sha256="c" * 64)
    token = panel._OWNED_LAUNCH.set(True)
    try:
        with panel._window_board_registration(authorization, SimpleNamespace(), ledger=ledger):
            with panel._window_worker_scope(authorization, "grok"):
                panel._window_note_route(decision)
                if disagreement == "none":
                    with pytest.raises(Spawned):  # agreement: it reaches the spawn
                        panel.launch_provider(["grok", "-p", "review"])
                else:
                    with pytest.raises(supply.WindowRefused) as refused:
                        panel.launch_provider(["grok", "-p", "review"])
                    assert refused.value.code == "window_exception_expired"
    finally:
        panel._OWNED_LAUNCH.reset(token)
    assert ledger.counts()["grok_seat"] == (1 if disagreement == "none" else 0)


def test_k1_r6_the_resolver_hands_its_decision_to_the_window_scope(tmp_path, monkeypatch):
    """Production wiring: ``_seat_route_for_spawn`` reports the decision it reached."""
    from phase_loop_runtime import panel_invoker as panel, seat_window_supply as supply
    _post_train_a_grok(monkeypatch)
    monkeypatch.setattr(panel._seat_jail, "seat_sandbox_capable", lambda: None)
    ledger = _ledger(tmp_path)
    authorization = SimpleNamespace(staged_tree_sha256="c" * 64, instructions_sha256=None)
    with supply.ledger_scope(ledger), supply.item_scope("grok_seat"):
        panel._seat_route_for_spawn("grok", authorization, eligible=True)
        assert supply.current_route()["mode"] == "degraded"
        assert supply.current_route()["code"] == "grok_tool_surface_unverified"


def test_k1_r6_a_start_with_no_resolved_route_is_refused(tmp_path):
    from phase_loop_runtime import seat_window_supply as supply
    ledger = _ledger(tmp_path)
    with pytest.raises(supply.WindowRefused):
        ledger.dispatch("codex_seat")
    assert ledger.counts()["codex_seat"] == 0


def test_k1_r6_the_board_must_be_the_composition_the_snapshot_was_written_for(
        tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as panel, seat_window_supply as supply
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    ledger = supply.WindowLedger(tmp_path / "l.jsonl", supply.required_envelope("gemini"))
    ledger.bind({}, {}, composition="0" * 64)
    monkeypatch.setattr("phase_loop_runtime.advisor_board.composition.compose_review_board_report",
                        lambda: SimpleNamespace(board=DEFAULT_BOARD, policy_outcome=lambda t:
                                                SimpleNamespace(status="admitted")))
    monkeypatch.setattr(panel, "invoke_board", lambda *a, **k: pytest.fail("board ran"))
    with supply.ledger_scope(ledger):
        result = panel.window_board_launch(panel.WindowBoardSpec(
            qualification_input=SimpleNamespace(repo=tmp_path, layout=SimpleNamespace()),
            monitoring_policy="bounded"))
    assert result.composition == "refused"


@pytest.mark.parametrize("change", ["board", "co_seats", "dispatch_mode"])
def test_k1_r6_the_snapshot_and_ledger_bind_composition_and_resolution(row_world, change):
    import json as j
    ctx = row_world.record()["context_id"]
    if change in {"board", "co_seats"}:
        name = f"window-exceptions-codex-{ctx}.json"
        value = j.loads((row_world.root / name).read_text())
        if change == "board":
            value["board_sha256"] = "0" * 64
        else:
            value["co_seats"] = value["co_seats"][:-1]
        raw = j.dumps(value, sort_keys=True).encode()
    else:
        name = f"window-ledger-codex-{ctx}.jsonl"
        raw = (row_world.root / name).read_bytes().replace(b'"resolved_mode":"jailed"',
                                                          b'"resolved_mode":"unconfined"', 1)
    row_world.replace_file(name, raw)
    assert row_world.verify()["passed"] is False


# --- Item 3: the exec source's launch attestation binds the key. ---

@pytest.mark.parametrize("change", ["missing", "exec", "key", "attempt", "binding"])
def test_k1_check4_the_exec_sources_launch_attestation_binds_the_key(row_world, change):
    import json as j
    record = row_world.record()
    name = f"window-launch-{record['source_attempt']}.json"
    if change == "missing":
        (row_world.root / name).unlink()
    else:
        value = j.loads((row_world.root / name).read_text())
        if change == "exec":
            value["exec_record_sha256"] = "0" * 64
        elif change == "key":
            value["launch"]["qualification_key"]["falsifier_layout"] = "2" * 64
        elif change == "attempt":
            value["attempt_id"] = "0" * 32
        else:
            value["launch"]["binding"]["jail_profile_sha256"] = "3" * 64
        row_world.replace_file(name, j.dumps(value).encode())
    assert row_world.verify()["passed"] is False


def test_k1_check4_a_swapped_same_vendor_exec_fails(row_world):
    """Another successful Codex exec, with every outer cross-reference rebuilt, still
    fails: its attempt has no launch attestation naming it."""
    import json as j
    from phase_loop_runtime import panel_invoker as panel, seat_window as w
    record = row_world.record()
    ctx = record["context_id"]
    other = panel.leg_exec_record("codex", 0, [], model_turn=True, verdict=True)
    path = _REAL_WRITE("leg-" + other["attempt_id"] + ".json", other)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    record.update(source_attempt=other["attempt_id"], exec_record_digest=digest)
    record["row_observations"][0]["exec_record_digest"] = digest
    egress_name = f"window-egress-{record['egress']['observation_digest']}.json"
    egress = j.loads((row_world.root / egress_name).read_text())
    egress["exec_record_sha256"] = digest
    _REAL_WRITE(f"window-egress-{w.digest(egress)}.json", egress)
    record["egress"] = w.measurement(record["egress"]["checks"],
                                     observation_digest=w.digest(egress))
    row_world.rewrite(record)
    assert row_world.verify()["passed"] is False


def test_k1_check4_the_runtime_attests_the_key_its_route_admitted(tmp_path, monkeypatch,
                                                                  fixture_vendor):
    from phase_loop_runtime import panel_invoker as panel
    from phase_loop_runtime.seat_route_contract import QualificationKey
    events = []
    seat = _codex_leg_world(monkeypatch, tmp_path, events)
    seat.image_sha256, seat.admission_class = "b" * 64, "release_qualified"
    seat.jail.qualification_key = QualificationKey(
        profile_digest="7" * 64, allowlist_digest="6" * 64, falsifier_layout="1" * 64,
        projection_digest=None, variant=None, host_identity="fixture-host")
    _watch_stub(fixture_vendor, monkeypatch)
    monkeypatch.setattr(panel._seat_egress_proxy, "fence",
                        lambda *a, **k: SimpleNamespace(acknowledged=True))
    monkeypatch.setattr(panel._sandbox_egress, "wait_bridge_exit", lambda prefix: True)
    runtime = panel._WindowBoardLegRuntime(SimpleNamespace(layout=SimpleNamespace()),
                                           leg="codex")
    runtime.proxy = SimpleNamespace(allowlist_sha256="6" * 64)
    panel._exec_jailed_codex_leg(
        seat, deadline_s=3, model="m", prompt="frame", broker_evidence=None,
        quiescence_latch=panel._ProviderQuiescenceLatch(), window_board=runtime,
        review_authorization=SimpleNamespace(staged_tree_sha256="d" * 64))
    key = runtime.launch["qualification_key"]
    assert {k: key[k] for k in ("profile_digest", "allowlist_digest", "falsifier_layout",
                                "host_identity")} == {
        "profile_digest": "7" * 64, "allowlist_digest": "6" * 64,
        "falsifier_layout": "1" * 64, "host_identity": "fixture-host"}
    assert runtime.launch["binding"]["stage_manifest_sha256"] == "d" * 64
    assert runtime.launch["binding"]["argv_sha256"] == runtime.binding.argv_sha256


# --- Item 7: readiness reflects W1's grant; matrix read errors stay in their partition. ---

def test_k1_ready_w1_reflects_the_owner_grant(tmp_path, monkeypatch, capsys):
    from phase_loop_runtime import cli, seat_window as w
    monkeypatch.setattr(w, "owner_w1_grant", lambda now=None: {"nonce": "a" * 32})
    cli.main(["seat-window", "ready", "--window", "W1", "--vendor", "gemini"])
    assert json.loads(capsys.readouterr().out)["grant"] is True
    monkeypatch.setattr(w, "owner_w1_grant", lambda now=None: None)
    cli.main(["seat-window", "ready", "--window", "W1", "--vendor", "gemini"])
    assert json.loads(capsys.readouterr().out)["grant"] is False


def test_k1_matrix_read_error_in_another_directory_stays_in_its_partition(
        row_world, monkeypatch, tmp_path, capsys):
    from phase_loop_runtime import cli
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    broken = elsewhere / "window-W1-cbroken.json"
    broken.write_text("{")
    broken.chmod(0o600)
    healthy = next(row_world.root.glob("window-row-codex-*.json"))
    capsys.readouterr()
    monkeypatch.setattr("phase_loop_runtime.seat_window._now", lambda: ROW_NOW)
    assert cli.main(["seat-window", "matrix", "--record", str(healthy),
                     "--record", str(broken)]) == 0
    rows = {row["id"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["vendor:codex"]["status"] == "done-local"
    assert rows["vendor:gemini"]["status"] == "candidate"


# --- Item 5, K1-T8 routing: through the production dispatch in ``_default_spawn``. ---

def _production_spawn_world(monkeypatch, tmp_path):
    """The real ``_default_spawn`` → broker → ``_parent_infer`` jailed branches, with the
    jail, proxy, namespace and staging boundaries doubled (as the existing window-board
    test drives the Gemini leg)."""
    from phase_loop_runtime import panel_invoker as pi, sandbox_policy
    received = {}
    allocations = iter(tmp_path / f"panel-{index}" for index in range(10))

    class Route:
        jailed = True

    class Broker:
        def __init__(self, *args, **kwargs):
            self.evidence = {}

        def run_credentialless_client(self, adapter, *, deadline_s, cancel_event=None):
            status, text = adapter.invoke()
            return {"schema": "parent_unix_broker_v1", "status": status, "text": text}, {}

        def close(self):
            return None

    backend = SimpleNamespace(name="local", commit=lambda prepared, request: None,
                              release=lambda prepared: None)

    def mkdtemp(*, prefix, dir):
        path = next(allocations)
        path.mkdir()
        return str(path)

    def prepare_local_stage(repo, review_dir, *, floor_bytes, mark):
        tree = Path(review_dir) / pi._review_stage.REVIEW_STAGE_TREE_DIRNAME
        (tree / ".git").mkdir(parents=True)
        (tree / ".git" / "phase-loop-source-commit").write_text("d" * 40, encoding="utf-8")
        return SimpleNamespace(review_dir=Path(review_dir), local_tree=tree,
                               snapshot_sha256="c" * 64, sandbox_ref="local:fixture")

    @contextlib.contextmanager
    def start_proxy(*, allowlist_id, refuse_all=False):
        yield SimpleNamespace(socket="proxy.sock", allowlist_sha256="b" * 64)

    @contextlib.contextmanager
    def isolated_network(**kwargs):
        yield ("namespace",)

    def seat(review_dir, seat_dir, *args, **kwargs):
        return SimpleNamespace(review_dir=Path(review_dir), seat_dir=Path(seat_dir),
                               notices=[])

    def exec_leg(leg):
        def run(seat_, **kwargs):
            received[leg] = kwargs.get("window_board")
            return "OK", "review\nAGREE"
        return run

    for name, value in {
        "_gc_stale_panel_scratch": lambda: None,
        "_canonical_review_repo_authority": lambda path: tmp_path,
        "_has_injected_review_execution_seam": lambda *, leg=None: False,
        "_seat_route_for_spawn": lambda *a, **k: (Route(), [], None),
        "_refuse_unless_executed_remotely": lambda *a, **k: None,
        "_placement_gate": lambda value: None,
        "_record_sandbox_facts": lambda *a, **k: None,
        "revalidate_review_isolation_authorization": lambda *a, **k: None,
        "harden_subscription_model": lambda leg, model, effort=None: model,
        "derive_review_leg_authorization": lambda *a, **k: SimpleNamespace(
            expires_monotonic_ns=10 ** 30),
        "ParentUnixBroker": Broker,
        "_render_broker_pointer_prompt": lambda *a, **k: "frame",
        "_prepare_jailed_gemini": seat, "_exec_jailed_gemini_leg": exec_leg("gemini"),
        "_prepare_jailed_codex": seat, "_exec_jailed_codex_leg": exec_leg("codex"),
        "_bind_route_qualification": lambda seat_, route: seat_,
    }.items():
        monkeypatch.setattr(pi, name, value)
    monkeypatch.setattr(pi.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(pi._sandbox_policy, "staging_root", lambda: tmp_path)
    monkeypatch.setattr(pi._sandbox_policy, "effective_floor_bytes", lambda path: 1)
    monkeypatch.setattr(pi._sandbox_policy, "select_sandbox_root",
                        lambda **kwargs: sandbox_policy.SandboxRootChoice(None, tmp_path, False))
    monkeypatch.setattr(pi._sandbox_retention, "reap_until_free", lambda *a, **k: None)
    monkeypatch.setattr(pi._sandbox_placement, "resolve_backend", lambda choice: backend)
    monkeypatch.setattr(pi._sandbox_placement, "prepare_local_stage", prepare_local_stage)
    monkeypatch.setattr(pi._sandbox_placement, "LegPlacement",
                        lambda value, prepared, *, scheme, authorization_sha256:
                        SimpleNamespace(backend=value, prepared=prepared,
                                        record_backend_receipt=lambda receipt: None))
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree",
                        lambda *a, **k: None)
    monkeypatch.setattr(pi._seat_uid, "subordinate_range", lambda path: (1, 2))
    monkeypatch.setattr(pi._seat_uid, "seat_id_count", lambda uids, gids: 1)
    monkeypatch.setattr(pi._seat_uid, "lease_seat_id", lambda count: contextlib.nullcontext(2))
    monkeypatch.setattr(pi._seat_uid, "holder_pid_from_prefix", lambda prefix: 71)
    monkeypatch.setattr(pi._seat_egress_proxy, "start_proxy", start_proxy)
    monkeypatch.setattr(pi._seat_egress_proxy, "start_private_gemini_proxy", start_proxy)
    monkeypatch.setattr(pi._seat_egress_proxy, "egress_evidence", lambda proxy: {})
    monkeypatch.setattr(pi._sandbox_egress, "isolated_network", isolated_network)
    monkeypatch.setattr(pi._sandbox_egress, "egress_required", lambda: False)
    monkeypatch.setattr(pi._sandbox_egress, "enforcement_report", lambda *, applied: {})
    monkeypatch.setattr(pi._review_stage, "remove_review_stage", lambda path: None)
    return received


@pytest.mark.parametrize("window_leg", ["gemini", "codex"])
def test_k1_t8_production_dispatch_routes_the_hook_to_the_window_leg_only(
        tmp_path, monkeypatch, window_leg):
    from phase_loop_runtime import panel_invoker as pi
    received = _production_spawn_world(monkeypatch, tmp_path)
    authorization = SimpleNamespace(staged_tree_sha256="c" * 64)
    with pi._window_board_registration(authorization, SimpleNamespace(),
                                       leg=window_leg) as run:
        for leg in ("gemini", "codex"):
            spawned = pi._default_spawn(
                leg, "artifact", repo_dir=tmp_path, mode="review", model="fixture",
                review_authorization=authorization, canonical_repo_authority=tmp_path)
            assert tuple(spawned)[:2] == ("OK", "review\nAGREE"), tuple(spawned)
    assert received == {leg: (run if leg == window_leg else None)
                        for leg in ("gemini", "codex")}


def _forge_consistently(world, name, mutate):
    """Rewrite one retained source and re-seal everything that names it (the completion
    receipt's source digest, the record's completion digest and record digest), so only
    the check that reads that source's contents can catch it."""
    import json as j
    from phase_loop_runtime import seat_window as w
    record = world.record()
    path = world.root / name
    raw = path.read_bytes()
    raw = mutate(raw)
    world.replace_file(name, raw)
    ctx = record["context_id"]
    receipt_name = f"window-complete-codex-{ctx}.json"
    receipt = j.loads((world.root / receipt_name).read_text())
    label = next(label for label, value in w._row_source_names("codex", ctx, record).items()
                 if value == name)
    receipt["sources"][label] = hashlib.sha256(raw).hexdigest()
    (world.root / receipt_name).unlink()
    _REAL_WRITE(receipt_name, receipt)
    record["completion_digest"] = hashlib.sha256(
        (world.root / receipt_name).read_bytes()).hexdigest()
    world.rewrite(record)


def test_k1_r6_a_forged_ledger_resolution_disagreeing_with_the_snapshot_fails(row_world):
    ctx = row_world.record()["context_id"]
    _forge_consistently(row_world, f"window-ledger-codex-{ctx}.jsonl", lambda raw: raw.replace(
        b'"resolved_mode":"jailed"', b'"resolved_mode":"unconfined"', 1))
    assert row_world.verify()["code"] == "window_exception_expired"


def test_k1_r6_a_board_other_than_the_composed_one_fails(tmp_path, monkeypatch, fixture_vendor):
    from phase_loop_runtime import panel_invoker as panel
    world = _row_world(tmp_path, monkeypatch)
    launched = panel.window_board_launch

    def other_board(spec):
        return dataclasses.replace(launched(spec), board_sha256="9" * 64)
    monkeypatch.setattr(panel, "window_board_launch", other_board)
    assert _run_row(world, monkeypatch)["code"] == "window_review_required"
    assert world.verify()["code"] == "window_snapshot_mismatch"


@pytest.mark.parametrize("change", ["exec", "key", "binding"])
def test_k1_check4_a_forged_attestation_fails_on_its_contents(row_world, change):
    import json as j
    record = row_world.record()

    def mutate(raw):
        value = j.loads(raw)
        if change == "exec":
            value["exec_record_sha256"] = "0" * 64
        elif change == "key":
            value["launch"]["qualification_key"]["host_identity"] = "another-host"
        else:
            value["launch"]["binding"]["allowlist_sha256"] = "3" * 64
        return j.dumps(value).encode()
    _forge_consistently(row_world, f"window-launch-{record['source_attempt']}.json", mutate)
    assert row_world.verify()["code"] == "window_key_stale"


def test_k1_check4_a_launch_key_differing_from_the_binding_is_refused_at_record_time(
        tmp_path, monkeypatch, fixture_vendor):
    world = _row_world(tmp_path, monkeypatch)
    world.launch["qualification_key"] = dict(FIXTURE_LAUNCH_KEY, variant="other")
    assert _run_row(world, monkeypatch)["code"] == "window_key_stale"
    assert not list(world.root.glob("window-row-codex-*.json"))


# ======================================================================================
# Fix round 2: the Fable president's transport and the board's full composition.
# ======================================================================================

PRINT = "president:fable:_launch_claude:print"


def _president_ledger(tmp_path, routes):
    from phase_loop_runtime import seat_window as w, seat_window_supply as supply
    ledger = supply.WindowLedger(tmp_path / "president.jsonl", supply.required_envelope("gemini"),
                                 clock=lambda: ROW_NOW)
    legs = ["claude", "codex", "grok"]
    ledger.bind(w._snapshot_entries("gemini", legs, routes), w.ledger_routes("gemini", routes))
    return ledger


@pytest.mark.parametrize("selected", ["print", "tui"])
def test_k1_r6_a_tui_president_under_a_print_snapshot_entry_refuses_before_spawn(
        tmp_path, monkeypatch, selected):
    from phase_loop_runtime import panel_invoker as panel
    monkeypatch.setattr(panel, "_under_claude_code", lambda env=None: False)
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", selected)
    ledger = _president_ledger(tmp_path, [PRINT])
    spawned = []
    invoke = panel._WindowPresidentInvoke(
        lambda model, prompt: spawned.append(model) or {"status": "ok", "text": "x"}, ledger)
    response = invoke("fable", "prompt")
    if selected == "tui":
        assert response == {"status": "refused", "code": "window_exception_expired"}
        assert spawned == [] and ledger.counts()["fable_president"] == 0
    else:
        assert response["status"] == "ok" and spawned == ["fable"]
        line = json.loads(ledger.path.read_text().splitlines()[-1])
        assert line["route"] == PRINT and line["resolved_transport"] == "_launch_claude:print"


def test_k1_r6_the_snapshot_holds_the_president_route_selected_at_composition(
        tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as panel, seat_window as w
    monkeypatch.setattr(panel, "_under_claude_code", lambda env=None: False)
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", "tui")
    assert w._reachable_president_routes() == ["president:fable:_launch_claude:tui"]
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", "print")
    assert w._reachable_president_routes() == [PRINT]
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", "sdk")  # refused: nothing reachable
    assert w._reachable_president_routes() == []


def test_k1_r6_a_forged_president_transport_fails_verification(row_world):
    ctx = row_world.record()["context_id"]
    _forge_consistently(row_world, f"window-ledger-codex-{ctx}.jsonl", lambda raw: raw.replace(
        b'"resolved_mode":"president","resolved_transport":"',
        b'"resolved_mode":"president","resolved_transport":"x', 1))
    assert row_world.verify()["code"] == "window_exception_expired"


@pytest.mark.parametrize("change", ["same", "host_leg", "backing", "allow_api_key_fallback",
                                    "research_policy"])
def test_k1_r6_a_same_label_board_substitution_refuses(tmp_path, monkeypatch, change):
    """The composed board and a board with the same labels but different execution inputs
    (a seat's ``host_leg`` or ``backing``, the board's API-key fallback or research
    policy)
    are different compositions: the launcher refuses the substitute before any seat runs."""
    from phase_loop_runtime import panel_invoker as panel, seat_window_supply as supply
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    composed = getattr(panel, "_window_board_composition_digest", panel._window_board_digest)
    seats = list(DEFAULT_BOARD.seats)
    if change in {"host_leg", "backing"}:
        seats[0] = dataclasses.replace(seats[0], **(
            {"host_leg": True} if change == "host_leg" else {"backing": "omnigent"}))
        substitute = dataclasses.replace(DEFAULT_BOARD, seats=tuple(seats))
    elif change == "same":  # the composed board itself proceeds to the board run
        substitute = DEFAULT_BOARD
    elif change == "allow_api_key_fallback":
        substitute = dataclasses.replace(DEFAULT_BOARD, allow_api_key_fallback=True)
    else:
        substitute = dataclasses.replace(DEFAULT_BOARD, research_policy=dataclasses.replace(
            DEFAULT_BOARD.research_policy, enabled=True))
    assert [s.seat_key for s in substitute.seats] == [s.seat_key for s in DEFAULT_BOARD.seats]
    assert panel._window_board_shape_ok(substitute)  # the shape check alone admits it
    ledger = supply.WindowLedger(tmp_path / "l.jsonl", supply.required_envelope("gemini"))
    ledger.bind({}, {}, composition=composed(DEFAULT_BOARD))
    monkeypatch.setattr("phase_loop_runtime.advisor_board.composition.compose_review_board_report",
                        lambda: SimpleNamespace(board=substitute, policy_outcome=lambda t:
                                                SimpleNamespace(status="admitted")))

    class BoardRan(Exception):
        pass

    def board_run(*a, **k):
        raise BoardRan
    monkeypatch.setattr(panel, "invoke_board", board_run)
    monkeypatch.setattr(panel, "prepare_review_isolation_authorization",
                        lambda *a, **k: SimpleNamespace(staged_tree_sha256="d" * 64))
    monkeypatch.setattr(panel, "close_review_isolation_authorization", lambda value: None)
    monkeypatch.setattr(panel, "set_review_instruction_digest", lambda value: object())
    monkeypatch.setattr(panel, "reset_review_instruction_digest", lambda token: None)
    monkeypatch.setattr(panel._sandbox_policy, "staging_root", lambda: tmp_path)
    ran = []
    monkeypatch.setattr("phase_loop_runtime.president_adapter.build_president_invoke",
                        lambda *a, **k: ran.append("president") or object())
    with supply.ledger_scope(ledger):
        result = panel.window_board_launch(panel.WindowBoardSpec(
            qualification_input=SimpleNamespace(repo=tmp_path, layout=SimpleNamespace()),
            monitoring_policy="bounded"))
    if change == "same":
        assert ran == ["president"] and result.composition == "admitted"
    else:
        assert ran == [] and result.composition == "refused"


# ======================================================================================
# Bot-review fix: the board past the auth-cache TTL, and route expiry at prepaid starts.
# ======================================================================================

def test_k1_bot_the_board_launch_past_the_auth_ttl_reuses_the_bound_composition(
        tmp_path, monkeypatch):
    """Preflight composes and caches auth under the window's ``auth_probe`` item. When
    the control launches outlast the cache's TTL, the board launch must not recompose:
    its probes would start outside any item and refuse, failing auth and the board."""
    import subprocess as sp
    from phase_loop_runtime import executor_availability as availability
    from phase_loop_runtime import panel_invoker as panel, seat_profiles
    from phase_loop_runtime import seat_window_supply as supply
    from phase_loop_runtime.advisor_board import composition
    clock = [1000.0]
    monkeypatch.setattr(availability.time, "monotonic", lambda: clock[0])
    availability.clear_auth_cache()
    probes = []

    def probe(command, *args, **kwargs):  # crosses the real provider boundary
        argv = command.split() if isinstance(command, str) else list(command)
        seat_profiles.window_provider_start(argv)
        probes.append(argv[0])
        stdout = '{"loggedIn": true}' if argv and argv[0] == "claude" else "Logged in using ChatGPT"
        return sp.CompletedProcess(argv, 0, stdout, "")
    monkeypatch.setattr(availability, "_run_probe", probe)
    real_compose = composition.compose_review_board_report
    monkeypatch.setattr(composition, "compose_review_board_report",
                        lambda **kwargs: real_compose(
                            is_available=lambda vendor: True,
                            # the production auth gate: cached by the real TTL cache
                            auth_ok=lambda vendor: composition.default_board_auth_ok(vendor),
                            **kwargs))
    ledger = supply.WindowLedger(tmp_path / "l.jsonl", dict(
        supply.required_envelope("gemini"), auth_probe=64))
    with supply.ledger_scope(ledger), supply.item_scope("auth_probe"):
        composed = composition.compose_review_board_report()  # preflight, inside its item
    assert composed.policy_outcome("plan").status == "admitted" and probes
    ledger.bind({}, {}, composition=panel._window_board_composition_digest(composed.board),
                board=composed.board)
    clock[0] += availability._AUTH_TTL_SECONDS + 1  # the control launches took longer
    probes.clear()

    class BoardRan(Exception):
        pass

    def board_run(*a, **k):
        raise BoardRan
    monkeypatch.setattr(panel, "invoke_board", board_run)
    monkeypatch.setattr(panel, "prepare_review_isolation_authorization",
                        lambda *a, **k: SimpleNamespace(staged_tree_sha256="d" * 64))
    monkeypatch.setattr(panel, "close_review_isolation_authorization", lambda value: None)
    monkeypatch.setattr(panel, "set_review_instruction_digest", lambda value: object())
    monkeypatch.setattr(panel, "reset_review_instruction_digest", lambda token: None)
    monkeypatch.setattr(panel._sandbox_policy, "staging_root", lambda: tmp_path)
    monkeypatch.setattr("phase_loop_runtime.president_adapter.build_president_invoke",
                        lambda *a, **k: object())
    with supply.ledger_scope(ledger):
        result = panel.window_board_launch(panel.WindowBoardSpec(
            qualification_input=SimpleNamespace(repo=tmp_path, layout=SimpleNamespace()),
            monitoring_policy="bounded", leg="gemini"))
    assert result.composition == "admitted"
    assert probes == []  # no auth recheck outside the window's envelope
    availability.clear_auth_cache()


def _expiring_claude_ledger(tmp_path, clock):
    from phase_loop_runtime import seat_window as w, seat_window_supply as supply
    ledger = supply.WindowLedger(tmp_path / "expiry.jsonl", supply.required_envelope("gemini"),
                                 clock=lambda: clock[0])
    legs = ["claude", "codex", "grok"]
    ledger.bind(w._snapshot_entries("gemini", legs), w.ledger_routes("gemini"))
    return ledger


@pytest.mark.parametrize("started", ["before_expiry", "after_expiry"])
def test_k1_bot_a_prepaid_start_rechecks_its_route_expiry(tmp_path, monkeypatch, started):
    """A reservation made just before the route's exception expires: the start that
    consumes it is checked again, and refuses (without a second debit) once expired."""
    from phase_loop_runtime import panel_invoker as panel, seat_profiles
    from phase_loop_runtime import seat_window_supply as supply
    expiry = dt.datetime.fromisoformat(
        next(row for row in __import__("phase_loop_runtime.seat_window", fromlist=["x"])
             .readiness_rows() if row["id"] == "vendor:claude")["expiry"])
    clock = [expiry - dt.timedelta(seconds=1)]
    ledger = _expiring_claude_ledger(tmp_path, clock)
    with supply.ledger_scope(ledger), supply.item_scope("claude_seat"):
        supply.note_route(_agreeing(ledger, "claude_seat"))  # the resolver's evidence
        with panel._window_call_site("claude_seat"):  # reserved just before expiry
            if started == "after_expiry":
                clock[0] = expiry + dt.timedelta(seconds=1)  # the login proof took a while
                with pytest.raises(supply.WindowRefused) as refused:
                    seat_profiles.window_provider_start(["claude", "-p", "review"])
                assert refused.value.code == "window_exception_expired"
            else:
                seat_profiles.window_provider_start(["claude", "-p", "review"])
    lines = [json.loads(line) for line in ledger.path.read_text().splitlines()]
    assert ledger.counts()["claude_seat"] == 1  # debited once, at the call site
    assert [line["op"] for line in lines] == (
        ["dispatch"] if started == "after_expiry" else ["dispatch", "start"])
    if started == "before_expiry":
        assert lines[1]["route"] == "vendor:claude" and lines[1]["expiry"] is not None


def test_k1_bot_the_verifier_checks_prepaid_starts(row_world):
    """A start line (no debit) that ran after its route's exception expired fails
    verification, as a dispatch would."""
    ctx = row_world.record()["context_id"]
    name = f"window-ledger-codex-{ctx}.jsonl"

    def append_expired_start(raw):
        lines = raw.decode().splitlines()
        claude = next(json.loads(line) for line in lines
                      if json.loads(line).get("route") == "vendor:claude")
        start = dict(claude, seq=len(lines) + 1, op="start", units=0,
                     launch_time=(dt.datetime.fromisoformat(claude["expiry"])
                                  + dt.timedelta(seconds=1)).isoformat())
        return (raw.decode() + json.dumps(start, sort_keys=True, separators=(",", ":"))
                + "\n").encode()
    _forge_consistently(row_world, name, append_expired_start)
    assert row_world.verify()["code"] == "window_exception_expired"


def test_gemini_missing_proxy_token_refuses_and_cleans_up(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as panel, seat_jail

    events = []
    seat = _gemini_leg_world(monkeypatch, tmp_path, events)
    del seat.private_proxy_token
    board = SimpleNamespace(
        start=lambda *a: pytest.fail("watch started without the proxy token"),
        finish=lambda *a: pytest.fail("an unstarted watch was finalized"),
    )

    def cleanup(refused_seat, *, primary):
        assert refused_seat is seat
        assert primary.code == "seat_sandbox_refused:gemini_proxy_token_missing"
        events.append("cleanup")

    monkeypatch.setattr(panel, "_cleanup_jailed_seat", cleanup)
    with pytest.raises(seat_jail.SeatSandboxRefused) as exc:
        panel._exec_jailed_gemini_leg(
            seat, deadline_s=1, model="fixture", prompt="fixture", broker_evidence=None,
            window_board=board, quiescence_latch=object(), review_authorization=object(),
        )
    assert exc.value.code == "seat_sandbox_refused:gemini_proxy_token_missing"
    assert events == ["cleanup"]
