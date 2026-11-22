"""GROK SL-2: the Grok jail profile, registered with its tool-surface gate closed.

Plan: ``plans/phase-plan-v1-seats-GROK.md`` (SL-2, IF-0-GROK-2); frozen contract:
``plans/artifacts/grok-jail-tool-surface-contract-v1.md`` (§2.3 mounts, §2.4 protection,
§4.1 the closed gate, §6 Train A, BA-J4 and BA-J6). No test runs grok, reads an operator's
real store or makes a provider call; the ``live_jail`` test runs a Python stand-in as the
dropped seat UID inside the real composed jail.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import hashlib
import inspect
import json
import os
import posixpath
import secrets
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail, seat_profile_grok as grok, seat_profiles, seat_route
from phase_loop_runtime import seat_window as w
from phase_loop_runtime.seat_route_contract import (
    ArgvInputs, ContainmentEvidence, EnvInputs, OD10_CLASSES, OwnerPaths,
)

from test_grok_tool_surface import _form, _receipt, seat as _l1_seat

seat = _l1_seat  # lane L1's fixture: a stand-in grok binary, record root and HOME

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux seat jail")

REFUSED = "grok_tool_surface_unverified"
#: Jail contract §2.3's ordered list, written out here independently of the module's table.
ORDERED = (
    ("--ro-bind", "{config}", "/seat/home/.grok"),
    ("--perms", "1777", "--tmpfs", "/seat/home/.grok/logs"),
    ("--perms", "1777", "--tmpfs", "/seat/home/.grok/sessions"),
    ("--bind", "{home}/.grok-rw/.config-init.lock", "/seat/home/.grok/.config-init.lock"),
    ("--bind", "{home}/.grok-rw/managed_config.lock", "/seat/home/.grok/managed_config.lock"),
    ("--ro-bind", "{ca}", "/seat/egress-ca.pem"),
    ("--ro-bind", "{masks}/empty", "/seat/home/.claude.json"),
    ("--ro-bind", "{masks}/empty", "/seat/home/.mcp.json"),
    ("--ro-bind", "{masks}/empty.d", "/seat/home/.claude"),
    ("--ro-bind", "{masks}/empty.d", "/seat/home/.cursor"),
    ("--ro-bind", "{masks}/empty.d", "/seat/home/.agents"),
    ("--perms", "1777", "--tmpfs", "/seat/home/.config"),
    ("--perms", "0555", "--dir", "/seat/home/.config/grove"),
    ("--ro-bind", "{masks}/empty.d", "/seat/home/.config/grove"),
    ("--ro-bind", "{masks}/empty.d", "/seat/tree/.agents"),
    ("--ro-bind", "{masks}/empty.d", "/seat/tree/.claude"),
    ("--ro-bind", "{masks}/empty.d", "/seat/tree/.cursor"),
    ("--ro-bind", "{masks}/empty.d", "/seat/tree/.grok"),
    ("--ro-bind", "{masks}/empty", "/seat/tree/.mcp.json"),
)
MOUNT_POINTS = frozenset(entry[-1] for entry in ORDERED if "--dir" not in entry)


def _ordered(config, home, ca):
    masks = posixpath.join(posixpath.dirname(config), "grok-masks")
    return tuple(word.format(config=config, home=home, ca=ca, masks=masks)
                 for entry in ORDERED for word in entry)


def _paths(review: Path, *, ca: Path | None = None, proxy: str | None = None) -> OwnerPaths:
    return OwnerPaths(
        tree=str(review / "reviewed-tree"), home=str(review / "seat-home"),
        out=str(review / "seat-out"), provider="/usr/bin/true", bundle_fd="7",
        instructions_fd="8", token_fd=None, seccomp_fd="9",
        provider_config=str(review / "grok-config"),
        egress_ca=str(ca or review / "egress-ca.pem"),
        egress_proxy=proxy or "http://srt:fixture@127.0.0.1:3128")


# --- (a) JAILCORE invariants and the no-branch scan ---------------------------------------


def test_the_profile_is_registered_with_its_executable_and_admission_gate():
    from phase_loop_runtime import seat_admission, seat_subject

    profile = seat_profiles.profile_for("grok")
    assert profile is not None and profile.leg == profile.vendor == "grok"
    assert "grok" in seat_profiles.registered_legs()
    assert seat_subject._PROVIDER_EXECUTABLES["grok"] == "grok"
    assert grok.grok_admission_gate in seat_admission._GATES["grok"]
    # IF-0-GROK-2's field table.
    assert profile.home_dirs == (".grok",)
    assert profile.projection == "none"
    assert (profile.new_session, profile.token_fd) == (True, False)
    assert profile.credential.channel == "home_file"
    assert profile.credential.scope_evidence == "grok-credential-scope"
    assert profile.credential_missing_code == "grok_seat_credential_missing"
    assert profile.config_surface.closed is True
    assert profile.config_surface.planted_paths == gts.DISCOVERY_PATHS
    assert profile.output_secret_code == "grok_seat_token_in_output"
    assert OD10_CLASSES[profile.output_secret_code] == "security"
    assert profile.containment == ContainmentEvidence(
        "grok-credential-scope", "grok-refresh-detection", "grok-unlisted-refusal", None)
    assert profile.allowlist_id == "grok-review"
    assert profile.recorded_stop is None and profile.variant is None
    assert profile.notice_codes >= {
        "grok_seat_credential_missing", "grok_seat_credential_refused", "grok_seat_token_expired",
        "grok_seat_token_in_output", "grok_seat_token_refreshed_in_jail", REFUSED}
    assert all(code in OD10_CLASSES for code in profile.notice_codes)
    # The closed gate first, then the registry's own resource-caps check.
    assert [item.name for item in profile.preconditions] == ["tool_surface", "resource_caps"]
    window = profile.window
    assert (window.canonical_record_field, window.route_record_field, window.route_literal) == (
        "canonical_grok", "grok_route", "jailed")
    assert window.plant_locations == (
        ("tree", "/seat/tree", "reviewed-tree"), ("home", "/seat/home", "seat-home"),
        ("provider_config", "/seat/home/.grok", "grok-config"))
    assert window.tree_rows == ()


def test_the_environment_carries_the_proxy_and_ca_and_no_grok_or_xai_variable():
    profile = seat_profiles.profile_for("grok")
    assert dict(profile.env(EnvInputs(None, egress_proxy="http://srt:t@127.0.0.1:1"))) == {
        "HTTPS_PROXY": "http://srt:t@127.0.0.1:1", "SSL_CERT_FILE": "/seat/egress-ca.pem"}
    env = seat_jail.seat_env("grok", token_fd=None, egress_proxy="http://srt:t@127.0.0.1:1")
    assert not [name for name in env if name.startswith(gts.FORBIDDEN_ENVIRONMENT_PREFIXES)]
    assert not [name for name in env if "KEY" in name or "TOKEN" in name]


def test_owner_binds_are_exactly_the_ordered_mount_list(tmp_path):
    profile = seat_profiles.profile_for("grok")
    paths = _paths(tmp_path)
    assert tuple(profile.owner_binds(paths)) == _ordered(
        paths.provider_config, paths.home, paths.egress_ca)
    # Both the mount list and the canonical owner argv: nothing follows it but the builder's
    # own `--remount-ro /`.
    owner = seat_jail._owner_argv(
        "grok", tree="<tree>", home="<home>", out="<out>", provider="<provider>",
        bundle_fd="<b>", instructions_fd="<i>", token_fd=None, seccomp_fd="<s>",
        gemini_config="<gemini-config>", egress_ca="<egress-ca>", egress_proxy="<egress-proxy>")
    binds = _ordered("<gemini-config>", "<home>", "<egress-ca>")
    start = owner.index("<out>") + 2  # after the builder's `--bind <out> /seat/out`
    assert tuple(owner[start:start + len(binds)]) == binds
    assert owner[start + len(binds):start + len(binds) + 2] == ["--remount-ro", "/"]


@pytest.mark.parametrize("missing", ["provider_config", "egress_ca"])
def test_owner_binds_refuse_without_the_staged_config_or_ca(tmp_path, missing):
    paths = dataclasses.replace(_paths(tmp_path), **{missing: None})
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        seat_profiles.profile_for("grok").owner_binds(paths)
    assert refused.value.code == seat_jail.refused("jail_build")


def test_mount_points_name_every_destination_of_the_ordered_list(tmp_path):
    """President note B4: J1's declared set holds `.grok`, both tmpfs, both locks, the CA,
    every home and tree mask, and `.config`."""
    profile = seat_profiles.profile_for("grok")
    points = tuple(profile.mount_points(_paths(tmp_path)))
    assert len(points) == len(set(points))
    assert set(points) == MOUNT_POINTS
    for point in points:
        assert point.startswith("/seat/") and posixpath.normpath(point) == point


def test_no_destination_overlaps_another_except_the_declared_nesting():
    """§2.3: no mount at, below or above another entry, except the writable children of the
    read-only `.grok` and `grove` under the `.config` tmpfs (§2.4 "Coverage")."""
    nested = {("/seat/home/.grok", "/seat/home/.grok/" + name)
              for name in ("logs", "sessions", ".config-init.lock", "managed_config.lock")}
    nested.add(("/seat/home/.config", "/seat/home/.config/grove"))
    for left in MOUNT_POINTS:
        for right in MOUNT_POINTS:
            if left != right and right.startswith(left + "/"):
                assert (left, right) in nested, (left, right)
    # Nor with the builder's own namespace mounts.
    for point in MOUNT_POINTS:
        for builder in (seat_jail.SEAT_BUNDLE, seat_jail.SEAT_INSTRUCTIONS, "/seat/bin/grok",
                        seat_jail.SEAT_OUT):
            assert not seat_jail._paths_overlap(point, builder)


def test_the_protection_table_classifies_every_fixed_input_and_discovery_path_once():
    """§2.4's table for grok 1.0.92, against E8-A's inventory on this base and main's
    discovery set: each input exactly once, with its treatment."""
    rows = grok.JAIL_PROTECTION[grok.GROK_1_0_92_SHA256]
    assert set(grok.JAIL_PROTECTION) == {grok.GROK_1_0_92_SHA256}
    assert grok.GROK_1_0_92_SHA256 in gts.TOLERATED_REFUSALS_BY_IMAGE
    home = [path for scope, path, _ in rows if scope in {grok.HOME, grok.ABSOLUTE}]
    tree = [path for scope, path, _ in rows if scope == grok.TREE]
    assert len(home) == len(set(home)) and len(tree) == len(set(tree))
    assert set(home) == set(gts.SEAT_FIXED_INPUTS) | set(gts.SEAT_FIXED_INPUT_EXCLUSIONS)
    assert tuple(sorted(tree)) == tuple(sorted(gts.DISCOVERY_PATHS))
    treatment = {(scope, path): value for scope, path, value in rows}
    assert {path for (_, path), value in treatment.items() if value == grok.PROJECTED} == {
        ".grok/config.toml", ".grok/auth.json", ".grok/agent_id"}
    for path in gts.SEAT_FIXED_INPUTS:
        scope = grok.ABSOLUTE if path.startswith("/") else grok.HOME
        expected = (grok.ABSENT_OUTSIDE_WRITABLE_MOUNTS if path.startswith("/")
                    else grok.PROJECTED if path == ".grok/config.toml"
                    else grok.ABSENT_IN_READ_ONLY_DOTDIR if path.startswith(".grok/")
                    else grok.MASKED_FILE if path in {".claude.json", ".mcp.json"}
                    else grok.MASKED_DIRECTORY)
        assert treatment[(scope, path)] == expected, path
    assert treatment[(grok.HOME, ".grok/rules")] == grok.ABSENT_IN_READ_ONLY_DOTDIR
    for path in gts.DISCOVERY_PATHS:
        assert treatment[(grok.TREE, path)] == (
            grok.MASKED_FILE if path == ".mcp.json" else grok.MASKED_DIRECTORY)
    assert set(treatment.values()) <= grok.TREATMENTS
    # Every mask is mounted, in table order (§2.3 items 5 and 6).
    assert [path for path, _ in grok.HOME_MASKS] == [
        ".claude.json", ".mcp.json", ".claude", ".cursor", ".agents", ".config/grove"]
    assert [path for path, _ in grok.TREE_MASKS] == [
        ".agents", ".claude", ".cursor", ".grok", ".mcp.json"]


def _built(review: Path, *, ca: bytes = b"ca", proxy: str = "http://srt:a@127.0.0.1:3128",
           bundle: bytes = b"bundle"):
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    (review / "grok-config").mkdir()
    certificate = review / f"ca-{secrets.token_hex(4)}.pem"
    certificate.write_bytes(ca)
    return seat_jail.build_seat_jail(
        "grok", review, Path("/usr/bin/true"), tree=tree,
        bundle_memfd=seat_jail.memfd_with("fixture-bundle", bundle),
        instructions_memfd=seat_jail.memfd_with("fixture-instructions", b"instructions"),
        seat_ids=(1, 1), gemini_config=review / "grok-config", egress_ca=certificate,
        egress_proxy=proxy)


def test_the_built_jail_has_the_canonical_digest_through_the_gemini_config_placeholder(
        tmp_path):
    """President note B2: the real `grok-config` path normalises to main's literal, and
    two launches with different per-launch paths, CAs, proxies and descriptors agree."""
    first = _built(tmp_path / "a")
    try:
        # Burn descriptors so the second jail's numbers differ.
        spare = [os.open("/dev/null", os.O_RDONLY) for _ in range(3)]
        second = _built(tmp_path / "elsewhere" / "b", ca=b"other-ca",
                        proxy="http://srt:b@127.0.0.1:41234", bundle=b"other")
        try:
            canonical = seat_jail.jail_profile_digest("grok")
            assert first.profile_digest == second.profile_digest == canonical
            assert seat_jail.actual_profile_digest(first) == canonical
            assert first.seccomp_fd != second.seccomp_fd
            assert seat_jail.expected_mount_points(first) == seat_jail.expected_mount_points(second)
            assert MOUNT_POINTS <= set(seat_jail.expected_mount_points(first))
            pi._require_canonical_jail(first)
            # An added bind stays observable.
            mutated = dataclasses.replace(first, process_owner=(
                *first.process_owner, "--bind", first.tree_dir, "/seat/home/.grok/skills"))
            assert seat_jail.actual_profile_digest(mutated) != canonical
        finally:
            seat_jail.close_jail_fds(second)
            for fd in spare:
                os.close(fd)
    finally:
        seat_jail.close_jail_fds(first)


def test_a_placeholder_other_than_mains_literal_never_reaches_the_canonical_digest(
        tmp_path, monkeypatch):
    """The mutant president note B2 rules out: J's role name in place of the literal."""
    real = grok._placeholders

    def role_name(paths):
        return {key: value.replace("<gemini-config>", "<provider-config>")
                for key, value in real(paths).items()}

    profile = dataclasses.replace(seat_profiles.profile_for("grok"),
                                  digest_placeholders=role_name)
    monkeypatch.setitem(seat_profiles._REGISTRY, "grok", profile)
    jail = _built(tmp_path)
    try:
        assert seat_jail.actual_profile_digest(jail) != seat_jail.jail_profile_digest("grok")
    finally:
        seat_jail.close_jail_fds(jail)


def test_the_builder_creates_only_the_declared_home_directory(tmp_path):
    jail = _built(tmp_path)
    try:
        home = tmp_path / seat_jail.HOST_HOME_DIRNAME
        assert sorted(entry.name for entry in home.iterdir()) == [".grok", ".tmp"]
    finally:
        seat_jail.close_jail_fds(jail)


def test_shared_builders_and_seat_uid_carry_no_grok_branch():
    """SL-2 edits no shared builder: no Grok literal in the generic jail path or seat_uid."""
    from phase_loop_runtime import seat_uid

    names = ("jail_profile_digest", "actual_profile_digest", "seat_env", "_owner_argv",
             "build_seat_jail", "expected_mount_points")
    sources = [inspect.getsource(getattr(seat_jail, name)) for name in names]
    sources += [Path(module.__file__).read_text(encoding="utf-8")
                for module in (seat_route, seat_uid)]
    for source in sources:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "grok" not in node.value.lower(), node.value


# --- (b) BA-J6: the gate is closed, through ordinary board routing ------------------------

AUTHORIZED = SimpleNamespace(staged_tree_sha256="0" * 64, instructions_sha256=None)


@pytest.fixture
def board(seat, monkeypatch):
    """The route's world for a Grok seat: a capable host, an operator login present, and
    every effect past L6 counted (none may happen)."""
    from phase_loop_runtime import seat_egress_proxy, seat_jail_autoqualify

    monkeypatch.setenv("HOME", str(seat.home))
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)
    effects: list[str] = []

    def counted(name):
        def effect(*_args, **_kwargs):
            effects.append(name)
            raise AssertionError(f"reached {name}")
        return effect

    monkeypatch.setattr(seat_egress_proxy, "start_proxy", counted("proxy"))
    monkeypatch.setattr(seat_egress_proxy, "unavailable_code", counted("egress"))
    monkeypatch.setattr(seat_jail_autoqualify, "ensure_qualified", counted("qualification"))
    monkeypatch.setattr(seat_jail_autoqualify, "_default_qualify", counted("qualification"))
    monkeypatch.setattr(pi, "launch_provider", counted("spawn"))
    monkeypatch.setattr(pi, "run_provider", counted("spawn"))
    monkeypatch.setattr(seat_jail, "build_seat_jail", counted("jail"))
    pi._JAILCORE_ROUTE_CACHE.clear()
    yield SimpleNamespace(seat=seat, effects=effects)
    pi._JAILCORE_ROUTE_CACHE.clear()


def _route(board, authorization=AUTHORIZED):
    route, notices, refusal = pi._seat_route_for_spawn(
        "grok", authorization, eligible=True, env=board.seat.env)
    return route, notices, refusal


@pytest.mark.parametrize("receipt", ["absent", "frozen_measurement", "legacy", "list_tools"])
def test_ba_j6_every_receipt_stops_at_l6_with_nothing_started(board, receipt):
    command = _form("staged")
    if receipt != "absent":
        _receipt(board.seat, command, receipt)
    # The receipt is one the unjailed gate would admit (or there is none): only the fixed
    # refusal can stop it here.
    assert pi.grok_tool_gate(command, board.seat.env) is (receipt != "absent")
    route, notices, refusal = _route(board)
    assert refusal == REFUSED
    assert route is not None and not route.jailed
    decision = route.decision
    assert (decision.mode, decision.code) == ("degraded", REFUSED)
    assert [(step.step, step.outcome, step.code) for step in decision.steps] == [
        ("L6", "failed", REFUSED)]
    assert board.effects == []
    assert pi._seat_jailed_at_launch("grok", AUTHORIZED, brokered=True, env=board.seat.env) \
        is False
    assert board.effects == []


def test_the_closed_check_reads_no_receipt(board, monkeypatch):
    read = []
    monkeypatch.setattr(pi, "_read_grok_receipt", lambda *a, **k: read.append(a))
    monkeypatch.setattr(pi, "grok_tool_gate", lambda *a, **k: read.append(a) or True)
    assert grok.tool_surface_code() == REFUSED
    assert _route(board)[2] == REFUSED
    assert read == []


@pytest.mark.parametrize("module", [
    "absent", "no_check", "raises", "blank", "not_text"])
def test_an_incomplete_opening_check_keeps_the_gate_closed(monkeypatch, module):
    """SL-3 supplies the opening check; until it is a callable answering `None` or a code,
    the precondition refuses."""
    import types

    if module != "absent":
        fake = types.ModuleType("phase_loop_runtime.grok_jail_surface")
        answers = {"raises": lambda: 1 / 0, "blank": lambda: "", "not_text": lambda: 7}
        if module in answers:
            fake.precondition_code = answers[module]
        monkeypatch.setitem(sys.modules, "phase_loop_runtime.grok_jail_surface", fake)
        import phase_loop_runtime
        monkeypatch.setattr(phase_loop_runtime, "grok_jail_surface", fake, raising=False)
    assert grok.tool_surface_code() == REFUSED


def test_an_installed_opening_check_decides(monkeypatch):
    import types

    import phase_loop_runtime

    fake = types.ModuleType("phase_loop_runtime.grok_jail_surface")
    for answer in (None, "grok_seat_token_expired"):
        fake.precondition_code = lambda answer=answer: answer
        monkeypatch.setitem(sys.modules, "phase_loop_runtime.grok_jail_surface", fake)
        monkeypatch.setattr(phase_loop_runtime, "grok_jail_surface", fake, raising=False)
        assert grok.tool_surface_code() == answer


def test_the_installed_opening_check_stays_closed_without_its_records():
    """GROK SL-3 installs ``grok_jail_surface``: the precondition now decides through its
    opening check, which refuses while the eligibility records do not exist (jail
    contract §2.4). Before SL-3 this asserted the module was absent."""
    import importlib.util

    assert importlib.util.find_spec("phase_loop_runtime.grok_jail_surface") is not None
    assert grok.tool_surface_code() == REFUSED


# --- (c) earlier refusals keep their codes --------------------------------------------------


def _check_not_reached(monkeypatch):
    seen = []
    profile = seat_profiles.profile_for("grok")
    preconditions = tuple(
        dataclasses.replace(item, check=lambda: seen.append(1) or REFUSED)
        if item.name == "tool_surface" else item for item in profile.preconditions)
    monkeypatch.setitem(seat_profiles._REGISTRY, "grok",
                        dataclasses.replace(profile, preconditions=preconditions))
    return seen


def test_l0_without_a_staged_tree(board, monkeypatch):
    seen = _check_not_reached(monkeypatch)
    route, _notices, refusal = _route(board, SimpleNamespace(staged_tree_sha256=None,
                                                             instructions_sha256=None))
    assert refusal == "seat_sandbox_not_staged"
    assert [step.step for step in route.decision.steps] == ["L0"]
    assert seen == [] and board.effects == []


@pytest.mark.parametrize("code", ["seat_sandbox_unavailable_host", "seat_sandbox_unavailable_tiocsti"])
def test_l3_host_refusals(board, monkeypatch, code):
    seen = _check_not_reached(monkeypatch)
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: code)
    route, _notices, refusal = _route(board)
    assert refusal == code
    assert route.decision.steps[0].step == "L3"
    assert seen == [] and board.effects == []


def test_l5_without_an_operator_login(board, monkeypatch):
    seen = _check_not_reached(monkeypatch)
    (board.seat.home / ".grok" / "auth.json").unlink()
    route, _notices, refusal = _route(board)
    assert refusal == "grok_seat_credential_missing"
    assert [step.step for step in route.decision.steps] == ["L5"]
    assert seen == [] and board.effects == []


# --- (d) readiness rows (jail contract §6) -----------------------------------------------


def _rows_without_grok(monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.delitem(seat_profiles._REGISTRY, "grok")
        return w.readiness_rows()


def test_readiness_rows_drop_the_unconfined_exception(monkeypatch):
    rows = {row["id"]: row for row in w.readiness_rows()}
    vendor = rows["vendor:grok"]
    assert (vendor["route"], vendor["exception"], vendor["expiry"], vendor["allowlist_id"],
            vendor["status"], vendor["interim_route"]) == (
        "jailed", None, None, "grok-review", "candidate", "degraded")
    remote = rows["remote:grok"]
    assert (remote["route"], remote["status"], remote["allowlist_id"]) == (
        "remote", "remote-pending", "grok-review")
    before = {row["id"]: row for row in _rows_without_grok(monkeypatch)}
    assert before["vendor:grok"]["exception"] == "unconfined"
    assert set(before) == set(rows)
    changed = {row_id for row_id in rows if rows[row_id] != before[row_id]}
    assert changed and all(row_id.split(":")[-1] == "grok" or row_id.startswith(
        "president:grok:") for row_id in changed)
    for row_id in changed:
        fields = {key for key in rows[row_id] if rows[row_id][key] != before[row_id][key]}
        assert fields <= {"route", "exception", "expiry", "allowlist_id"}, (row_id, fields)


def test_the_route_no_longer_offers_the_grok_exception():
    policy = seat_route.load_route_policy()
    assert "grok" not in policy.exceptions


# --- (e) a Gemini record across 2026-12-04 under the snapshot rule ------------------------


def test_a_gemini_record_observed_before_the_boundary_verifies_across_it(tmp_path, monkeypatch):
    import test_seat_window_vendor_neutral as kit

    record = kit._legacy_w1(tmp_path, monkeypatch)
    assert record["observed_at"] < "2026-12-04"
    assert w.verify_records([record], now=kit.W1_RUN + dt.timedelta(days=1))["passed"] is True
    assert w.verify_records([record], now=kit.AFTER_CUTOFF)["passed"] is True
    # Grok's row carries no expiry any more: only the rows still under an exception can
    # expire a record judged by the base rule.
    expiring = {row["id"] for row in w.readiness_rows() if row["expiry"]}
    assert not {row_id for row_id in expiring if "grok" in row_id}
    assert "vendor:claude" in expiring


# --- (f) the staged argv ------------------------------------------------------------------


@pytest.mark.parametrize("model, effort", [(None, None), (gts.MEASUREMENT_MODEL, "high")])
def test_the_jailed_argv_is_the_staged_form_with_argv0_and_cwd_replaced(model, effort):
    profile = seat_profiles.profile_for("grok")
    command = list(profile.argv(ArgvInputs("/seat/bin/grok", model=model, effort=effort)))
    staged = pi.grok_runtime_forms(model=model, effort=effort or "high")["staged"]
    assert pi._grok_argv_digest(command) == pi._grok_argv_digest(staged)
    assert command[command.index("--cwd") + 1] == "/seat/tree"
    differing = [index for index, (left, right) in enumerate(zip(command, staged))
                 if left != right]
    assert len(command) == len(staged) and differing == [0, command.index("--cwd") + 1]
    assert command[0] == "/seat/bin/grok"
    assert command[command.index("--prompt-file") + 1] == "/dev/stdin"
    assert pi._grok_tools_admitted(command, sorted(pi._grok_allowed_tools(staged)))


# --- The qualification shape (president notes B3 and SL-1 N2) ------------------------------


def test_the_shape_is_the_staged_directory_masks_and_ca(tmp_path):
    from phase_loop_runtime import seat_grok_credential as credential

    seat_dir = tmp_path / "seat"
    seat_dir.mkdir(mode=0o700)
    shape = grok.qualification_shape(seat_dir)
    config = shape["gemini_config"]
    assert config == seat_dir / "grok-config"
    assert sorted(os.listdir(config)) == sorted(credential.STAGED_ENTRIES)
    assert os.stat(config).st_mode & 0o7777 == 0o555
    assert hashlib.sha256((config / "config.toml").read_bytes()).hexdigest() == \
        gts.SEAT_CONFIG_SHA256
    masks = seat_dir / "grok-masks"
    assert sorted(os.listdir(masks)) == ["empty", "empty.d"]
    assert (os.stat(masks).st_mode & 0o7777, os.stat(masks / "empty").st_mode & 0o7777,
            os.stat(masks / "empty.d").st_mode & 0o7777) == (0o555, 0o444, 0o555)
    assert (masks / "empty").read_bytes() == b"" and os.listdir(masks / "empty.d") == []
    assert os.stat(shape["egress_ca"]).st_mode & 0o7777 == 0o444
    grok.remove_staged(seat_dir)
    assert sorted(os.listdir(seat_dir)) == ["egress-ca.pem"]


def test_a_failed_shape_leaves_nothing_behind(tmp_path, monkeypatch):
    seat_dir = tmp_path / "seat"
    seat_dir.mkdir(mode=0o700)
    monkeypatch.setattr(grok, "write_mask_sources", lambda _dir: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        grok.qualification_shape(seat_dir)
    assert os.listdir(seat_dir) == []


def test_stubs_are_created_after_the_build_and_refuse_a_wrong_type(tmp_path):
    jail = _built(tmp_path)
    try:
        home = tmp_path / seat_jail.HOST_HOME_DIRNAME
        tree = Path(jail.tree_dir)
        grok.stub_mount_points(jail)
        assert sorted(entry.name for entry in home.iterdir()) == sorted([
            ".grok", ".tmp", ".grok-rw", ".claude.json", ".mcp.json", ".claude", ".cursor",
            ".agents", ".config"])
        assert sorted(os.listdir(home / ".grok-rw")) == sorted(
            ["sessions", ".config-init.lock", "managed_config.lock"])
        assert (home / ".claude.json").is_file() and (home / ".config").is_dir()
        assert sorted(os.listdir(tree)) == sorted(gts.DISCOVERY_PATHS)
        assert (tree / ".mcp.json").is_file() and (tree / ".grok").is_dir()
        grok.stub_mount_points(jail)  # an entry of the right type is kept as it stands
        (tree / ".mcp.json").unlink()
        (tree / ".mcp.json").mkdir()
        with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
            grok.stub_mount_points(jail)
        assert refused.value.code == seat_jail.refused("jail_build")
        (tree / ".mcp.json").rmdir()
        (tree / ".mcp.json").symlink_to("/etc/hostname")
        with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
            grok.stub_mount_points(jail)
        assert refused.value.code == seat_jail.refused("jail_build")
    finally:
        seat_jail.close_jail_fds(jail)


# --- (g) live_jail BA-J4 (SL-2 part): the dropped child ----------------------------------

_BA_J4_PROBE = r'''
import errno, json, os, sys
config = json.loads(sys.argv[1])
results = {"uid": os.getuid(), "read": {}, "denied": {}, "allowed": {}}

def attempt(table, name, fn):
    try:
        fn()
        table[name] = "ok"
    except OSError as exc:
        table[name] = errno.errorcode.get(exc.errno, str(exc.errno))

def read(path):
    with open(path, "rb") as handle:
        return handle.read()

for name, path in config["staged"].items():
    results["read"][name] = __import__("hashlib").sha256(read(path)).hexdigest()
    attempt(results["denied"], "append:" + name, lambda path=path: open(path, "ab").close())
    attempt(results["denied"], "truncate:" + name, lambda path=path: os.truncate(path, 0))
    attempt(results["denied"], "unlink:" + name, lambda path=path: os.unlink(path))
    attempt(results["denied"], "chmod:" + name, lambda path=path: os.chmod(path, 0o666))
    def rename_over(path=path, name=name):
        source = "/seat/home/.grok/logs/over-" + name
        open(source, "wb").close()
        os.rename(source, path)
    attempt(results["denied"], "rename_over:" + name, rename_over)
for path in config["create_denied"]:
    def create(path=path):
        if path.endswith("/"):
            os.mkdir(path.rstrip("/"))
        else:
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    attempt(results["denied"], "create:" + path, create)
for path in config["write_denied"]:
    attempt(results["denied"], "write:" + path, lambda path=path: open(path, "ab").close())
attempt(results["denied"], "rename_within:agent_over_auth",
        lambda: os.rename("/seat/home/.grok/agent_id", "/seat/home/.grok/auth.json"))
for path in ("/seat/home/.grok", "/seat/home/.config"):
    attempt(results["denied"], "rename_away:" + path, lambda path=path: os.rename(path, path + "-moved"))
for path in config["writable"]:
    def write(path=path):
        with open(path, "ab") as handle:
            handle.write(b"seat")
    attempt(results["allowed"], path, write)
with open("/seat/home/.grok/logs/client.log", "w") as handle:
    handle.write("token suffix " + config["suffix"] + "\n")
print(json.dumps(results))
'''


def _fabricated_token() -> str:
    # Assembled at run time: no token-shaped literal in the source.
    return "-".join(("fixture", "grok", "access", secrets.token_hex(16)))


def _contains(root: Path, needles) -> list[str]:
    hits = []
    for directory, _dirs, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if any(needle in data for needle in needles):
                hits.append(str(path))
    return hits


def test_live_jail_ba_j4_the_dropped_child_reads_and_cannot_alter_the_staged_grok(
        tmp_path, monkeypatch):
    """BA-J4 (SL-2 part), through `build_seat_jail` and the production D8 prefix, as the
    actual seat UID: a Python stand-in, no provider. VL2 runs it with
    PHASE_LOOP_REQUIRE_LIVE_JAIL=1, where a missing prerequisite fails."""
    if os.environ.get("PHASE_LOOP_REQUIRE_LIVE_JAIL") != "1":
        pytest.skip("set PHASE_LOOP_REQUIRE_LIVE_JAIL=1 on a jail-capable host")
    from phase_loop_runtime import sandbox_egress, seat_grok_credential as credential, seat_uid

    missing = [reason for reason, ok in (
        (seat_uid.PREREQUISITE, seat_uid.seat_uid_available()),
        ("egress isolation unavailable", sandbox_egress.egress_isolation_available()),
        ("seat sandbox unavailable", seat_jail.seat_sandbox_capable() is None)) if not ok]
    if missing:
        pytest.fail("live jail unavailable: " + "; ".join(missing))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    token = _fabricated_token()
    suffix = token[-12:]
    auth = json.dumps({"https://fixture.invalid::seat": {"key": token}}).encode()
    agent = b"fixture-agent-" + secrets.token_hex(4).encode()
    base = tmp_path / "live"
    review = base / "review"
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    (tree / "README").write_text("stand-in tree\n", encoding="utf-8")
    seat_dir = base / "seat"
    seat_dir.mkdir(mode=0o700)
    config_dir = seat_dir / "grok-config"
    credential._stage(config_dir, (
        (credential.CONFIG_FILE_NAME, credential.seat_config_bytes()),
        (credential.AUTH_FILE_NAME, auth), (credential.AGENT_ID_FILE_NAME, agent),
        *((lock, b"") for lock in credential.MOUNT_POINT_FILES)))
    grok.write_mask_sources(seat_dir)
    certificate = seat_dir / "egress-ca.pem"
    certificate.write_bytes(b"stand-in certificate\n")
    certificate.chmod(0o444)
    staged = {"config": "/seat/home/.grok/config.toml", "auth": "/seat/home/.grok/auth.json",
              "agent": "/seat/home/.grok/agent_id", "ca": "/seat/egress-ca.pem"}
    expected = {"config": gts.SEAT_CONFIG_SHA256,
                "auth": hashlib.sha256(auth).hexdigest(),
                "agent": hashlib.sha256(agent).hexdigest(),
                "ca": hashlib.sha256(certificate.read_bytes()).hexdigest()}
    create_denied = [
        "/seat/home/.grok/requirements.toml", "/seat/home/.grok/managed_config.toml",
        "/seat/home/.grok/skills/", "/seat/home/.grok/staged/", "/seat/home/.grok/x",
        "/seat/home/.claude/x", "/seat/home/.cursor/x", "/seat/home/.agents/x",
        "/seat/home/.config/grove/x", "/seat/tree/.grok/x", "/seat/tree/.claude/x",
        "/seat/tree/.cursor/x", "/seat/tree/.agents/x"]
    write_denied = ["/seat/home/.claude.json", "/seat/home/.mcp.json", "/seat/tree/.mcp.json"]
    writable = ["/seat/home/.grok/logs/w", "/seat/home/.grok/sessions/w",
                "/seat/home/.grok/.config-init.lock", "/seat/home/.grok/managed_config.lock",
                "/seat/tree/README"]
    probe = {"staged": staged, "create_denied": create_denied, "write_denied": write_denied,
             "writable": writable, "suffix": suffix}
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    try:
        with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
                sandbox_egress.isolated_network(timeout_s=300, required=True,
                                                seat_uid_map=True) as egress:
            reset = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
            holder = seat_uid.holder_pid_from_prefix(egress)
            jail = seat_jail.build_seat_jail(
                "grok", seat_dir, Path("/usr/bin/python3"), tree=tree,
                bundle_memfd=seat_jail.memfd_with("b", b"B"),
                instructions_memfd=seat_jail.memfd_with("i", b"I"), seat_ids=(n, n),
                gemini_config=config_dir, egress_ca=certificate,
                egress_proxy="http://srt:fixture@127.0.0.1:3128")
            try:
                grok.stub_mount_points(jail)
                pi._require_canonical_jail(jail)
                prefix = pi._compose_seat_jail_prefix(jail)
                done = subprocess.run(
                    [*prefix, "/usr/bin/python3", "-I", "-c", _BA_J4_PROBE, json.dumps(probe)],
                    capture_output=True, text=True, timeout=120, pass_fds=jail.pass_fds,
                    env=pi._jail_launch_env(), stdin=subprocess.DEVNULL)
            finally:
                seat_jail.close_jail_fds(jail)
                retained = [*seat_uid.teardown_in_h(holder, str(review)),
                            *seat_uid.teardown_in_h(holder, str(seat_dir))]
                pi._EGRESS_LAUNCH_PREFIX.reset(reset)
    finally:
        grok.remove_staged(seat_dir)
    assert done.returncode == 0, done.stderr[-2000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["uid"] == n and n != 0
    assert result["read"] == expected
    assert {name: code for name, code in result["denied"].items() if code == "ok"} == {}
    assert set(result["denied"]) == {
        *(f"{verb}:{name}" for name in staged
          for verb in ("append", "truncate", "unlink", "chmod", "rename_over")),
        *(f"create:{path}" for path in create_denied),
        *(f"write:{path}" for path in write_denied),
        "rename_within:agent_over_auth",
        "rename_away:/seat/home/.grok", "rename_away:/seat/home/.config"}
    # Where the read-only mount is the barrier, the kernel says so: the staged files' modes
    # alone (0444 and 0555) would refuse with EACCES instead, so a writable bind cannot pass
    # here. Appends, truncation and the file masks are refused by mode first (EACCES).
    mount_refusals = {name: code for name, code in result["denied"].items()
                      if name.startswith(("create:", "unlink:", "chmod:", "rename_within:",
                                          "rename_away:"))}
    assert mount_refusals == {name: "EBUSY" if name.startswith("rename_away:") else "EROFS"
                              for name in mount_refusals}
    assert result["allowed"] == {path: "ok" for path in writable}
    assert retained == []
    # After teardown: neither the planted suffix nor the credential bytes are retained
    # anywhere under the review and seat directories or the record root.
    assert sorted(os.listdir(seat_dir)) == ["egress-ca.pem"]
    needles = (suffix.encode(), token.encode(), auth)
    assert _contains(base, needles) == []
    assert _contains(tmp_path / "state", needles) == []
