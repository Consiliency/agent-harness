"""GROK SL-3: ``grok_jail_surface``, the jailed launch context and its gate.

Plan ``plans/phase-plan-v1-seats-GROK.md`` (SL-3.1 (c), (i), (j); IF-0-GROK-3); frozen
contract ``plans/artifacts/grok-jail-tool-surface-contract-v1.md`` §2.2, §2.4, §3, §4.2,
§4.4, BA-J2, BA-J2a, BA-J3, BA-J7 (the verifier's half). Nothing here runs grok, reads an
operator's real store or makes a provider call: the jail is built by the real
``build_seat_jail`` around a root-owned stand-in executable and never spawned, and every
record lives under a private ``XDG_STATE_HOME``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from phase_loop_runtime import grok_jail_surface as gjs
from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_grok_credential as cred
from phase_loop_runtime import seat_jail, seat_profile_grok as grok

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux seat jail")

REFUSED = "grok_tool_surface_unverified"
#: A root-owned regular file in a root-owned chain on every Linux CI image: the stand-in
#: subject. It is bound into a jail that is never spawned.
STAND_IN = os.path.realpath(sys.executable if sys.executable.startswith("/usr/") else
                            "/usr/bin/python3")


def _fabricated() -> str:
    return "-".join(("fixture", "grok", "bearer", secrets.token_hex(16)))


def _credential(config: Path, token: str | None = None):
    token = token or _fabricated()
    auth = json.dumps({"https://fixture.invalid::seat": {"key": token}}).encode()
    agent = b"fixture-agent-" + secrets.token_hex(4).encode()
    cred._stage(config, (
        (cred.CONFIG_FILE_NAME, cred.seat_config_bytes()), (cred.AUTH_FILE_NAME, auth),
        (cred.AGENT_ID_FILE_NAME, agent), *((lock, b"") for lock in cred.MOUNT_POINT_FILES)))
    return cred.GrokSeatCredential(
        config_dir=config, scan_values=cred.ScanValues([token.encode(), token[-12:].encode()]),
        digest=cred.credential_digest(auth, agent), expires_at=2**40), token


class _Proc:
    def poll(self):
        return None


def _build(base: Path, *, ca: bytes = b"fixture certificate\n", port: int = 3128,
           secret: str | None = None, stub: bool = True):
    """A production-shaped jailed Grok seat: the real builder over a staged ``.grok``, the
    mask sources, the CA and the stubs; nothing is spawned."""
    review = base / "seat"
    review.mkdir(parents=True, mode=0o700)
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(mode=0o700)
    (tree / "README").write_text("tree\n", encoding="utf-8")
    credential, token = _credential(review / grok.HOST_GROK_CONFIG_DIRNAME, secret)
    grok.write_mask_sources(review)
    certificate = review / "egress-ca.pem"
    certificate.write_bytes(ca)
    certificate.chmod(0o444)
    proxy_url = f"http://srt:{secrets.token_hex(8)}@127.0.0.1:{port}"
    jail = seat_jail.build_seat_jail(
        "grok", review, Path(STAND_IN), tree=tree,
        bundle_memfd=seat_jail.memfd_with("b", b"B"),
        instructions_memfd=seat_jail.memfd_with("i", b"I"), seat_ids=(7, 7),
        gemini_config=review / grok.HOST_GROK_CONFIG_DIRNAME, egress_ca=certificate,
        egress_proxy=proxy_url)
    if stub:
        grok.stub_mount_points(jail)
    proxy = SimpleNamespace(
        process=_Proc(), allowlist_id="grok-review",
        allowlist_digest=pi._seat_egress_proxy.allowlist_ref("grok-review").content_digest,
        request_budget=None, socket=str(base / "proxy.sock"), ca_cert=certificate,
        ca_sha256=hashlib.sha256(ca).hexdigest(), proxy_url=proxy_url)
    return SimpleNamespace(jail=jail, credential=credential, token=token, proxy=proxy,
                           review=review, tree=tree,
                           command=gjs.production_command(jail.provider_argv0))


def _host_surface(binary: str, launch: str, tools=None) -> dict:
    staged = list(gjs.production_command())
    tools = sorted(pi._grok_allowed_tools(staged)) if tools is None else tools
    from phase_loop_runtime.seat_jail import host_arch

    return {
        "binary_sha256": binary, "version": "grok 1.0.92 stand-in",
        "version_sha256": "1" * 64, "help_sha256": "2" * 64, "model": gjs.PRODUCTION_MODEL,
        "effort": gjs.PRODUCTION_EFFORT, "context": gjs.JAIL_CONTEXT,
        "context_digest": gjs.jail_context_digest(binary),
        "measured_at": "2026-11-22T00:00:00Z",
        "routes": [{"route": "staged", "argv_digest": gjs.staged_argv_digest(), "tools": tools,
                    "definitions_sha256": "3" * 64}],
        "jail_context_digest": gjs.jail_context_digest(binary),
        "launch_digest": {host_arch(): launch}, "image_sha256": binary,
    }


def _open_gate(binary: str, launch: str, *, skip=(), tools=None) -> None:
    """Write the records of eligibility conditions 3 to 5 and the jailed receipt."""
    from phase_loop_runtime.seat_jail import host_arch
    from phase_loop_runtime.seat_window import _host_digest

    if "confirmation" not in skip:
        gjs.write_private(gjs.confirmation_name(binary), {
            "schema": gjs.CONFIRMATION_SCHEMA, "image_sha256": binary,
            "launch_digest": {host_arch(): launch},
            "jail_context_digest": gjs.jail_context_digest(binary),
            "outcome": dict(gjs._CONFIRMATION_OUTCOME), "approval_id": "owner-fixture-1",
            "approved_on": "2026-11-22"})
    if "boundary" not in skip:
        gjs.write_private(gjs.boundary_name(launch), {
            "schema": gjs.BOUNDARY_SCHEMA, "hosted_run": "1", "head": "a" * 40,
            "launch_digest": launch, "jail_context_digest": gjs.jail_context_digest(binary),
            "ba_j5": "passed", "skipped": 0})
    if "record" not in skip:
        surface = _host_surface(binary, launch, tools)
        gjs.write_private(gjs.host_record_name(binary), {
            "schema": gjs.HOST_RECORD_SCHEMA, "host_digest": _host_digest(), "surface": surface})
        route = surface["routes"][0]
        digest = gts.surface_digest(surface, route)
        entry = {"grant": "g1", "reservation": "0001-00000000000000aa"}
        gjs.write_private(gjs.attempts_name(binary), {
            "schema": gjs.ATTEMPTS_SCHEMA, "binary_sha256": binary, "host_digest": _host_digest(),
            "attempts": {route["argv_digest"]: {**entry, "route": "staged", "at": "x"}},
            "published": {route["argv_digest"]: {**entry, "surface_digest": digest}}})
        if "receipt" not in skip and "confirmation" in skip:
            # No confirmed launch to issue from: the receipt the record would carry.
            record = gjs.resolve_record(binary, gjs.staged_argv_digest())
            gjs.write_private(gjs.receipt_name(binary, gjs.staged_argv_digest()),
                              gjs.jail_receipt(record, binary, launch))
        elif "receipt" not in skip:
            assert gjs.write_jail_receipt(binary)["passed"] is True


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    built = _build(tmp_path / "a")
    binary = gjs.root_owned_digest(built.jail.provider_path)
    table = dict(grok.JAIL_PROTECTION)
    table[binary] = table[grok.GROK_1_0_92_SHA256]
    monkeypatch.setattr(grok, "JAIL_PROTECTION", MappingProxyType(table))
    launch = gjs.launch_digest(built.jail, built.command)
    holder = os.getpid()  # a live pid with a network namespace; never entered
    prefix = ("/usr/bin/nsenter", "-t", str(holder), "-U")
    token = pi._EGRESS_LAUNCH_PREFIX.set(prefix)
    monkeypatch.setattr(gts, "bridged_to",
                        lambda p, proxy: tuple(p) == prefix and proxy is built.proxy)
    yield SimpleNamespace(**vars(built), binary=binary, launch=launch, holder=holder,
                          prefix=prefix, tmp=tmp_path)
    pi._EGRESS_LAUNCH_PREFIX.reset(token)
    seat_jail.close_jail_fds(built.jail)


def _verify(world, **override):
    arguments = dict(mode="board", proxy=world.proxy, holder=world.holder, cwd="/seat/tree",
                     command=world.command, credential=world.credential)
    arguments.update(override)
    jail = arguments.pop("jail", world.jail)
    return gjs.verify_jail_launch_context(jail, **arguments)


def _refuses(world, **override):
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        _verify(world, **override)
    assert caught.value.code == REFUSED


# --- Drift and the config (§2.3 "Code ownership", §2.4 "Drift", SL-1 N1) -------------------


def test_the_protection_table_equals_e8as_inputs_and_mains_discovery_paths():
    assert gjs.protection_drift(grok.GROK_1_0_92_SHA256) is None
    assert gjs.protection_drift("0" * 64) == "no protection table for the image"


@pytest.mark.parametrize("change", ["fixed_input", "exclusion", "discovery", "managed"])
def test_a_drifted_input_is_reported(monkeypatch, change):
    if change == "fixed_input":
        monkeypatch.setattr(gts, "SEAT_FIXED_INPUTS", (*gts.SEAT_FIXED_INPUTS, ".grok/new.toml"))
    elif change == "exclusion":
        monkeypatch.setattr(gts, "SEAT_FIXED_INPUT_EXCLUSIONS", (".grok/rules",))
    elif change == "discovery":
        monkeypatch.setattr(gts, "DISCOVERY_PATHS", (*gts.DISCOVERY_PATHS, ".windsurf"))
    else:
        monkeypatch.setattr(gts, "MANAGED_CONFIG_PATHS", ("/etc/grok/other.toml",))
    assert gjs.protection_drift(grok.GROK_1_0_92_SHA256) is not None


def test_the_jailed_config_bytes_equal_e8as_seat_config():
    assert gjs.staged_config_bytes() == gts.seat_config()
    assert hashlib.sha256(gjs.staged_config_bytes()).hexdigest() == gts.SEAT_CONFIG_SHA256


def test_a_raising_e8a_seat_config_is_seat_profile_unavailable(monkeypatch):
    """SL-1 N1: E8-A's own drift raises its ``_Refused`` (a ``ValueError``); the equality
    assertion maps it to the typed code instead of letting it propagate untyped."""
    def drifted():
        raise gts._Refused("record refused")
    monkeypatch.setattr(gts, "seat_config", drifted)
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        gjs.staged_config_bytes()
    assert caught.value.code == "seat_profile_unavailable"


def test_differing_jailed_bytes_refuse(monkeypatch):
    monkeypatch.setattr(cred, "seat_config_bytes", lambda: gts.seat_config() + b"#")
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        gjs.staged_config_bytes()
    assert caught.value.code == "seat_profile_unavailable"


# --- (j) the digests ------------------------------------------------------------------------

#: E8-A's unjailed ``context_digest()`` on this base, recorded before SL-3's change
#: (``origin/main`` at the E8-A baseline) and asserted unchanged after it.
UNJAILED_CONTEXT_DIGEST = "81292d4a8a5b24497f2eacd88ff49b0fe8e6700491db7783cbeb0a28fed08154"


def test_the_unjailed_context_digest_is_unchanged():
    assert gts.context_digest() == UNJAILED_CONTEXT_DIGEST


def test_the_jail_context_digest_is_canonical_json_of_the_document():
    image = grok.GROK_1_0_92_SHA256
    document = gjs.jail_context_document(image)
    assert set(document) == {"schema", "composition", "home", "seat_config", "mounts",
                             "protection", "environment", "managed_config",
                             "child_absent_policy", "egress"}
    assert document["schema"] == "grok_jail_context.v1"
    assert document["seat_config"] == {"path": ".grok/config.toml",
                                       "sha256": gts.SEAT_CONFIG_SHA256,
                                       "projection": "ro-staged-dotdir"}
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert gjs.jail_context_digest(image) == hashlib.sha256(raw.encode()).hexdigest()
    assert gjs.jail_context_digest(image) != gts.context_digest()


@pytest.mark.parametrize("change", [
    "image", "table", "mounts", "seat_config", "environment", "forbidden", "managed",
    "child_absent", "allowlist", "composition"])
def test_the_jail_context_digest_moves_with_each_input(monkeypatch, change):
    image = grok.GROK_1_0_92_SHA256
    before = gjs.jail_context_digest(image)
    if change == "image":
        image = "0" * 64
    elif change == "table":
        rows = grok.JAIL_PROTECTION[image][:-1]
        monkeypatch.setattr(grok, "JAIL_PROTECTION", MappingProxyType({image: rows}))
    elif change == "mounts":
        monkeypatch.setattr(grok, "WRITABLE_LOCKS", (".config-init.lock",))
    elif change == "seat_config":
        monkeypatch.setattr(gts, "SEAT_CONFIG_SHA256", "f" * 64)
    elif change == "environment":
        original = seat_jail.seat_env
        monkeypatch.setattr(seat_jail, "seat_env",
                            lambda *a, **k: {**original(*a, **k), "EXTRA": "1"})
    elif change == "forbidden":
        monkeypatch.setattr(gts, "FORBIDDEN_ENVIRONMENT_PREFIXES", ("GROK_",))
    elif change == "managed":
        monkeypatch.setattr(gts, "MANAGED_CONFIG_PATHS", ("/etc/grok/x.toml",))
    elif change == "child_absent":
        monkeypatch.setattr(gts, "CHILD_ABSENT_POLICY_PATHS", ())
    elif change == "allowlist":
        monkeypatch.setattr(gts, "egress_allowlist_digest", lambda: "e" * 64)
    else:
        monkeypatch.setattr(gjs, "COMPOSITION", "another")
    assert gjs.jail_context_digest(image) != before


def test_the_unjailed_context_digest_ignores_the_jailed_inputs(monkeypatch):
    before = gts.context_digest()
    monkeypatch.setattr(gjs, "COMPOSITION", "another")
    monkeypatch.setattr(grok, "JAIL_PROTECTION", MappingProxyType({}))
    assert gts.context_digest() == before == UNJAILED_CONTEXT_DIGEST


def test_ba_j2a_the_launch_digest_is_shared_across_launches(tmp_path, monkeypatch):
    """BA-J2a: different credentials, agent ids, CA bytes, descriptors, proxy ports and
    per-launch directories give the same ``launch_digest``."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    first = _build(tmp_path / "one", ca=b"first ca\n", port=3128)
    # Hold descriptors open so the second jail's memfd numbers differ.
    held = [os.dup(0) for _ in range(3)]
    try:
        second = _build(tmp_path / "two-other-path", ca=b"second ca, other bytes\n", port=40123)
    finally:
        for fd in held:
            os.close(fd)
    try:
        assert first.jail.bundle_fd != second.jail.bundle_fd
        assert first.credential.digest != second.credential.digest
        assert (gjs.launch_digest(first.jail, first.command)
                == gjs.launch_digest(second.jail, second.command)
                == gjs.production_launch_digest(seat_jail.host_arch()))
        assert gjs.launch_digest(first.jail, first.command, arch="aarch64") != \
            gjs.launch_digest(first.jail, first.command, arch="x86_64")
        # A different mount policy is a different launch.
        shuffled = dataclasses.replace(first.jail, process_owner=tuple(
            word if word != "/seat/home/.agents" else "/seat/home/.agentz"
            for word in first.jail.process_owner))
        assert gjs.launch_digest(shuffled, first.command) != gjs.launch_digest(
            first.jail, first.command)
    finally:
        seat_jail.close_jail_fds(first.jail)
        seat_jail.close_jail_fds(second.jail)


def test_the_measurement_owner_substitutes_back_to_the_production_digest(world):
    measured = dataclasses.replace(world.jail, process_owner=gjs.measurement_owner(world.jail))
    assert measured.process_owner != world.jail.process_owner
    assert "--bind" in measured.process_owner
    assert gjs.launch_digest(measured, world.command, measurement=True) == world.launch
    assert gjs.launch_digest(measured, world.command) != world.launch


# --- (i) the five eligibility conditions -----------------------------------------------------


def test_all_five_conditions_open_the_gate(world):
    _open_gate(world.binary, world.launch)
    assert gjs.eligibility(world.binary) is None
    admission = gjs.staged_admission(world.binary)
    assert admission is not None and admission["context"] == gjs.JAIL_CONTEXT
    assert admission["launch_digest"] == world.launch
    context = _verify(world)
    assert gjs.admits(context, world.jail, world.command, "/seat/tree")


@pytest.mark.parametrize("condition", gjs.CONDITIONS)
def test_each_condition_removed_alone_keeps_staged_closed(world, monkeypatch, condition):
    """SL-3.1 (i): every other condition holds; removing this one keeps ``staged`` closed at
    eligibility, at the window kit's admission read and at the final spawn check."""
    _open_gate(world.binary, world.launch,
               skip=(condition,) if condition in {"confirmation", "boundary", "record"} else ())
    if condition == "enforcement":
        monkeypatch.setattr(gjs, "ENFORCEMENT", "grok_jail_enforcement.v0")
    elif condition == "protection":
        table = dict(grok.JAIL_PROTECTION)
        del table[world.binary]
        monkeypatch.setattr(grok, "JAIL_PROTECTION", MappingProxyType(table))
    assert gjs.eligibility(world.binary) == condition
    assert gjs.staged_admission(world.binary) is None
    _refuses(world)


def test_the_measurement_set_is_conditions_one_to_four(world):
    _open_gate(world.binary, world.launch, skip=("record",))
    assert gjs.eligibility(world.binary) == "record"
    assert gjs.eligibility(world.binary, through=4) is None


@pytest.mark.parametrize("change", [
    "other_image", "other_context", "outcome", "no_approval", "extra_key", "other_arch"])
def test_a_confirmation_off_its_bindings_is_absent(world, change):
    _open_gate(world.binary, world.launch)
    name = gjs.confirmation_name(world.binary)
    document = gjs.read_private(name)
    if change == "other_image":
        document["image_sha256"] = "0" * 64
    elif change == "other_context":
        document["jail_context_digest"] = "0" * 64
    elif change == "outcome":
        document["outcome"] = {**document["outcome"], "models_requested": True}
    elif change == "no_approval":
        document["approval_id"] = ""
    elif change == "extra_key":
        document["note"] = "x"
    else:
        document["launch_digest"] = {"riscv64": world.launch}
    gjs.write_private(name, document)
    assert gjs.eligibility(world.binary) == "confirmation"


@pytest.mark.parametrize("change", ["skipped", "failed", "other_launch", "context"])
def test_a_boundary_record_off_its_bindings_is_absent(world, change):
    _open_gate(world.binary, world.launch)
    name = gjs.boundary_name(world.launch)
    document = gjs.read_private(name)
    if change == "skipped":
        document["skipped"] = 1
    elif change == "failed":
        document["ba_j5"] = "failed"
    elif change == "other_launch":
        document["launch_digest"] = "0" * 64
    else:
        document["jail_context_digest"] = "0" * 64
    gjs.write_private(name, document)
    assert gjs.eligibility(world.binary) == "boundary"


@pytest.mark.parametrize("change", ["unadmitted_tool", "moved_context", "moved_launch",
                                    "withdrawn", "unsafe_mode"])
def test_the_record_condition_needs_an_admitted_current_record(world, change):
    tools = None
    if change == "unadmitted_tool":
        tools = sorted({*pi._grok_allowed_tools(list(gjs.production_command())), "use_tool"})
    _open_gate(world.binary, world.launch, tools=tools,
               skip=("receipt",) if tools is not None else ())
    root = Path(os.environ["XDG_STATE_HOME"]) / "agent-harness" / "seat-records"
    if change in {"moved_context", "moved_launch"}:
        document = gjs.read_private(gjs.host_record_name(world.binary))
        key = "jail_context_digest" if change == "moved_context" else "launch_digest"
        document["surface"][key] = ("0" * 64 if key == "jail_context_digest"
                                    else {k: "0" * 64 for k in document["surface"][key]})
        gjs.write_private(gjs.host_record_name(world.binary), document)
    elif change == "withdrawn":
        document = gjs.read_private(gjs.attempts_name(world.binary))
        for entry in document["attempts"].values():
            entry["reservation"] = "0002-00000000000000bb"
        gjs.write_private(gjs.attempts_name(world.binary), document)
    elif change == "unsafe_mode":
        (root / gjs.host_record_name(world.binary)).chmod(0o644)
    assert gjs.eligibility(world.binary) == "record"
    _refuses(world)


# --- BA-J3: receipts --------------------------------------------------------------------------


@pytest.mark.parametrize("receipt", ["absent", "frozen_unjailed", "legacy", "list_tools",
                                     "stale_surface"])
def test_ba_j3_only_the_matching_jailed_receipt_admits(world, receipt):
    _open_gate(world.binary, world.launch, skip=("receipt",))
    staged_argv = gjs.staged_argv_digest()
    name = gjs.receipt_name(world.binary, staged_argv)
    base = {"schema": "tool_probe.v1", "binary_digest": world.binary, "argv_digest": staged_argv,
            "passed": True, "public_code": None,
            "tools": sorted(pi._grok_allowed_tools(list(gjs.production_command()))),
            "version_digest": "1" * 64}
    if receipt == "frozen_unjailed":
        record = gjs.resolve_record(world.binary, staged_argv)
        document = {**gjs.jail_receipt(record, world.binary, world.launch),
                    "context": gts.GROK_SEAT_CONTEXT, "context_digest": gts.context_digest()}
    elif receipt == "legacy":
        document = base
    elif receipt == "list_tools":
        document = {**base, "basis": "list_tools"}
    elif receipt == "stale_surface":
        record = gjs.resolve_record(world.binary, staged_argv)
        document = {**gjs.jail_receipt(record, world.binary, world.launch),
                    "surface_digest": "0" * 64}
    if receipt != "absent":
        gjs.write_private(name, document)
    # An unjailed receipt at the unjailed name never counts here either.
    gjs.write_private("grok-probe-" + world.binary + "-" + staged_argv + ".json",
                      {**base, "basis": "list_tools"})
    assert gjs.jail_receipt_matches(world.binary, world.launch) is None
    _refuses(world)
    gjs.write_jail_receipt(world.binary)
    assert gjs.jail_receipt_matches(world.binary, world.launch) is not None
    assert _verify(world).surface_digest is not None


def test_ba_j3_a_jailed_probe_does_not_overwrite_an_unjailed_receipt(world):
    _open_gate(world.binary, world.launch, skip=("receipt",))
    unjailed = "grok-probe-" + world.binary + "-" + gjs.staged_argv_digest() + ".json"
    gjs.write_private(unjailed, {"schema": "tool_probe.v1", "basis": "list_tools"})
    gjs.write_jail_receipt(world.binary)
    assert gjs.read_private(unjailed) == {"schema": "tool_probe.v1", "basis": "list_tools"}
    assert gjs.receipt_name(world.binary, gjs.staged_argv_digest()) != unjailed


def test_ba_j3_a_jailed_receipt_refuses_in_launch_owned(world, monkeypatch):
    """The unjailed gate reads only ``grok-probe-*``: a jailed receipt in the jailed store
    gives the unjailed spawn nothing to admit."""
    _open_gate(world.binary, world.launch)
    command = list(gjs.production_command(world.jail.provider_argv0))
    monkeypatch.setattr(pi, "_grok_binary_identity", lambda *_a, **_k: ("/x", world.binary))
    assert pi._grok_tool_gate(command) is False
    with pytest.raises(seat_jail.SeatSandboxRefused):
        pi.require_grok_admission(command)


# --- BA-J2: spawn-boundary substitutions (§4.4) ---------------------------------------------


@pytest.fixture
def opened(world):
    _open_gate(world.binary, world.launch)
    assert _verify(world) is not None
    return world


def test_ba_j2_the_mark_cannot_be_built_outside_the_verifier(opened):
    context = _verify(opened)
    with pytest.raises(TypeError):
        gjs.JailLaunchContext(**{**{f.name: getattr(context, f.name)
                                    for f in dataclasses.fields(context)}, "issuer": None})
    forged = SimpleNamespace(**vars(context)) if hasattr(context, "__dict__") else None
    assert not gjs.admits(forged, opened.jail, opened.command, "/seat/tree")
    assert not gjs.admits(context, opened.jail, [*opened.command, "--extra"], "/seat/tree")
    assert not gjs.admits(context, opened.jail, opened.command, "/seat/home")
    other = dataclasses.replace(opened.jail)
    assert not gjs.admits(context, other, opened.command, "/seat/tree")


def test_ba_j2_a_subject_failing_the_root_owned_walk_refuses(opened, tmp_path):
    fake = tmp_path / "grok"
    fake.write_bytes(Path(STAND_IN).read_bytes()[:64])
    fake.chmod(0o755)
    _refuses(opened, jail=dataclasses.replace(opened.jail, provider_path=str(fake)))


def test_ba_j2_a_binary_whose_digest_differs_refuses(opened, monkeypatch):
    monkeypatch.setattr(gjs, "root_owned_digest", lambda path: "9" * 64)
    _refuses(opened)


def test_ba_j2_a_dependency_projection_refuses(opened):
    _refuses(opened, jail=dataclasses.replace(opened.jail, dependency_destinations=("/x",)))
    _refuses(opened, jail=dataclasses.replace(opened.jail, dependency_mount_args=("--ro-bind",)))


@pytest.mark.parametrize("change", ["changed_config", "extra_file", "changed_auth",
                                    "changed_ca", "changed_mask_file", "mask_dir_entry"])
def test_ba_j2_a_changed_or_extra_projection_file_refuses(opened, change):
    config = opened.review / grok.HOST_GROK_CONFIG_DIRNAME
    masks = opened.review / grok.HOST_GROK_MASKS_DIRNAME
    target = {"changed_config": config, "extra_file": config, "changed_auth": config,
              "changed_ca": opened.review, "changed_mask_file": masks,
              "mask_dir_entry": masks / grok.MASK_DIRECTORY}[change]
    target.chmod(0o755)
    if change == "changed_config":
        (config / "config.toml").chmod(0o644)
        (config / "config.toml").write_bytes(gts.seat_config() + b"#")
        (config / "config.toml").chmod(0o444)
    elif change == "extra_file":
        (config / "requirements.toml").write_bytes(b"")
    elif change == "changed_auth":
        (config / "agent_id").chmod(0o644)
        (config / "agent_id").write_bytes(b"other")
        (config / "agent_id").chmod(0o444)
    elif change == "changed_ca":
        ca = opened.review / "egress-ca.pem"
        ca.chmod(0o644)
        ca.write_bytes(b"another certificate\n")
        ca.chmod(0o444)
    elif change == "changed_mask_file":
        (masks / grok.MASK_FILE).chmod(0o644)
        (masks / grok.MASK_FILE).write_bytes(b"x")
        (masks / grok.MASK_FILE).chmod(0o444)
    else:
        (target / "x").write_bytes(b"")
    target.chmod(0o555)
    _refuses(opened)


def test_ba_j2a_a_credential_other_than_the_staged_copy_refuses(opened):
    other = dataclasses.replace(opened.credential, digest="0" * 64)
    _refuses(opened, credential=other)
    _refuses(opened, credential=None)


@pytest.mark.parametrize("change", ["removed_mask", "retyped_mask", "shadow_mount",
                                    "mount_after", "reordered", "symlinked_destination",
                                    "symlinked_stub", "missing_stub"])
def test_ba_j2_a_removed_retyped_or_shadowed_mask_refuses(opened, change):
    owner = list(opened.jail.process_owner)
    jail = opened.jail
    if change == "removed_mask":
        index = owner.index("/seat/tree/.grok")
        del owner[index - 2:index + 1]
    elif change == "retyped_mask":
        index = owner.index("/seat/home/.claude.json")
        owner[index - 1] = owner[index - 1].replace("/empty", "/empty.d")
    elif change == "shadow_mount":
        index = owner.index("--remount-ro")
        owner[index:index] = ["--tmpfs", "/seat/home/.grok/skills"]
    elif change == "mount_after":
        index = owner.index("--remount-ro")
        owner[index + 2:index + 2] = ["--bind", "/tmp", "/seat/tree/.mcp.json"]
    elif change == "reordered":
        a, b = owner.index("/seat/home/.claude"), owner.index("/seat/home/.cursor")
        owner[a], owner[b] = owner[b], owner[a]
    elif change == "symlinked_destination":
        index = owner.index("/seat/tree/.agents")
        owner[index] = "/seat/tree/./.agents"
    elif change == "symlinked_stub":
        stub = opened.tree / ".cursor"
        stub.rmdir()
        stub.symlink_to("/tmp")
    else:
        (opened.tree / ".mcp.json").unlink()
    if change not in {"symlinked_stub", "missing_stub"}:
        jail = dataclasses.replace(jail, process_owner=tuple(owner))
    _refuses(opened, jail=jail)


@pytest.mark.parametrize("change", ["other_proxy", "dead_proxy", "other_holder",
                                    "wrong_allowlist", "budget", "no_prefix"])
def test_ba_j2_another_proxy_holder_or_budget_refuses(opened, change):
    proxy = opened.proxy
    holder = opened.holder
    if change == "other_proxy":
        proxy = SimpleNamespace(**vars(opened.proxy))
    elif change == "dead_proxy":
        proxy = SimpleNamespace(**{**vars(opened.proxy),
                                   "process": SimpleNamespace(poll=lambda: 0)})
    elif change == "other_holder":
        holder = opened.holder + 1
    elif change == "wrong_allowlist":
        proxy = SimpleNamespace(**{**vars(opened.proxy), "allowlist_id": "gemini"})
    elif change == "budget":
        proxy = SimpleNamespace(**{**vars(opened.proxy), "request_budget": 1})
    else:
        token = pi._EGRESS_LAUNCH_PREFIX.set(())
        try:
            _refuses(opened)
        finally:
            pi._EGRESS_LAUNCH_PREFIX.reset(token)
        return
    _refuses(opened, proxy=proxy, holder=holder)


@pytest.mark.parametrize("change", ["cwd", "argv_extra", "model", "effort", "mode"])
def test_ba_j2_a_different_cwd_argv_or_mode_refuses(opened, change):
    command = list(opened.command)
    if change == "cwd":
        _refuses(opened, cwd="/seat/home")
        return
    if change == "argv_extra":
        command.append("--add-dir")
    elif change == "model":
        command[command.index("-m") + 1] = "grok-other"
    elif change == "effort":
        command[command.index("--reasoning-effort") + 1] = "low"
    else:
        _refuses(opened, mode="other")
        return
    _refuses(opened, command=command)


def test_ba_j2_a_withdrawn_record_after_the_gate_refuses(opened):
    root = Path(os.environ["XDG_STATE_HOME"]) / "agent-harness" / "seat-records"
    (root / gjs.host_record_name(opened.binary)).unlink()
    _refuses(opened)


# --- L6 (§4.2 provisional) and the closed-gate contract SL-2 left -------------------------


def test_precondition_code_refuses_a_subject_failing_the_walk(monkeypatch, tmp_path):
    from phase_loop_runtime import seat_subject

    fake = tmp_path / "grok"
    fake.write_bytes(b"\x7fELF stand-in\n")
    fake.chmod(0o755)
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda leg, env: (
        SimpleNamespace(subject_path=fake, source="standalone"), None))
    assert seat_subject is not None
    assert gjs.precondition_code() == REFUSED
    assert grok.tool_surface_code() == REFUSED


def test_precondition_code_refuses_a_dependency_projection(monkeypatch):
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda leg, env: (
        SimpleNamespace(subject_path=Path(STAND_IN), source="managed_release"), object()))
    assert gjs.precondition_code() == REFUSED


def test_precondition_code_opens_only_on_all_five_and_the_jailed_receipt(world, monkeypatch):
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda leg, env: (
        SimpleNamespace(subject_path=Path(STAND_IN), source="standalone"), None))
    assert gjs.precondition_code() == REFUSED
    _open_gate(world.binary, world.launch, skip=("receipt",))
    assert gjs.precondition_code() == REFUSED
    gjs.write_jail_receipt(world.binary)
    assert gjs.precondition_code() is None
    assert grok.tool_surface_code() is None


@pytest.mark.parametrize("raising, condition", [
    ("protection_drift", "protection"), ("staged_config_bytes", "protection"),
    ("_expected_launch", "confirmation"), ("_boundary_passed", "boundary"),
    ("_admitted_record", "record")])
def test_a_raising_eligibility_is_a_closed_gate_named_by_its_condition(
        world, monkeypatch, raising, condition):
    """Review N-6: an exception closes the gate and names the condition being checked."""
    _open_gate(world.binary, world.launch)
    assert gjs.eligibility(world.binary) is None

    def boom(*_a, **_k):
        raise ValueError("drift")
    monkeypatch.setattr(gjs, raising, boom)
    assert gjs.eligibility(world.binary) == condition
    assert gjs.staged_admission(world.binary) is None
    _refuses(world)


# --- BA-J7, the verifier's half: the measurement admission ------------------------------------


def _reservation(world, *, budget=1, rid="0001-00000000000000aa"):
    grant = world.tmp / "grant"
    grant.mkdir(mode=0o700, exist_ok=True)
    return gjs.MeasurementReservation("g1", rid, "pilot", world.binary, budget, str(grant))


def _measurement(world, *, budget=1):
    sink = Path(gjs.sink_source(str(world.review / "seat-home")))
    measured = dataclasses.replace(world.jail, process_owner=gjs.measurement_owner(world.jail))
    proxy = SimpleNamespace(**{**vars(world.proxy), "request_budget": budget})
    seat = SimpleNamespace(jail=measured, credential=world.credential)
    reservation = _reservation(world, budget=budget)
    launch = gjs.prepare_measurement(reservation, seat, proxy=proxy, holder=world.holder,
                                     command=world.command, check_route=False)
    return SimpleNamespace(jail=measured, proxy=proxy, launch=launch, sink=sink,
                           reservation=reservation)


@pytest.fixture
def measuring(world, monkeypatch):
    _open_gate(world.binary, world.launch, skip=("record",))
    monkeypatch.setattr(gts, "bridged_to",
                        lambda p, proxy: tuple(p) == world.prefix
                        and getattr(proxy, "socket", None) == world.proxy.socket)
    return world


def test_ba_j7_the_verifier_verifies_and_only_the_spawn_hook_consumes(measuring):
    """r7 (§4.4, §4.5 M4/M5): the measurement mode verifies the recorded admission without
    consuming it; ``consume_admission`` (the M5 hook) consumes it once, mode 0600."""
    m = _measurement(measuring)
    assert list(m.launch.scan_values) == list(measuring.credential.scan_values)
    context = _verify(measuring, jail=m.jail, mode="measurement", proxy=m.proxy,
                      measurement=m.launch)
    assert context.reservation_id == m.reservation.reservation_id
    assert context.launch_digest == measuring.launch
    admitted = Path(m.reservation.grant_dir) / f"admission-{m.reservation.reservation_id}"
    assert not admitted.exists() and not gjs.admission_consumed(m.reservation)
    _verify(measuring, jail=m.jail, mode="measurement", proxy=m.proxy, measurement=m.launch)
    gjs.consume_admission(m.launch, m.jail, m.proxy, measuring.holder, measuring.command,
                          measuring.binary)
    assert admitted.stat().st_mode & 0o777 == 0o600 and gjs.admission_consumed(m.reservation)
    with pytest.raises(gjs.JailRefused):  # consumed twice
        gjs.consume_admission(m.launch, m.jail, m.proxy, measuring.holder, measuring.command,
                              measuring.binary)


@pytest.mark.parametrize("change", ["no_reservation", "swapped_proxy", "budget", "other_image",
                                    "forged", "production_jail"])
def test_ba_j7_the_measurement_refuses_with_nothing_spawned(measuring, change):
    m = _measurement(measuring)
    arguments = dict(jail=m.jail, mode="measurement", proxy=m.proxy, measurement=m.launch)
    if change == "no_reservation":
        arguments["measurement"] = None
    elif change == "swapped_proxy":
        arguments["proxy"] = SimpleNamespace(**{**vars(m.proxy), "socket": "/other.sock"})
    elif change == "budget":
        arguments["proxy"] = SimpleNamespace(**{**vars(m.proxy), "request_budget": 0})
    elif change == "other_image":
        arguments["measurement"] = dataclasses.replace(
            m.launch, reservation=dataclasses.replace(m.reservation, image_sha256="0" * 64))
    elif change == "forged":
        with pytest.raises(TypeError):
            gjs.JailedMeasurementLaunch(m.reservation, (), {})
        return
    else:
        arguments["jail"] = measuring.jail
    _refuses(measuring, **arguments)
    admitted = Path(m.reservation.grant_dir) / f"admission-{m.reservation.reservation_id}"
    assert not admitted.exists()


@pytest.mark.parametrize("change", ["non_empty_sink", "swapped_proxy", "other_holder",
                                    "replayed", "unprepared"])
def test_ba_j7_the_spawn_hook_refuses_and_writes_no_admission(measuring, change):
    """The M5 hook re-derives the binding from the actual objects and needs an empty sink;
    a replay against another launch, or a measurement not issued by ``prepare_measurement``,
    refuses with no admission file."""
    m = _measurement(measuring)
    proxy, holder, launch = m.proxy, measuring.holder, m.launch
    if change == "non_empty_sink":
        (m.sink / "planted").write_bytes(b"")
    elif change == "swapped_proxy":
        proxy = SimpleNamespace(**{**vars(m.proxy), "socket": "/other.sock"})
    elif change == "other_holder":
        holder = os.getppid()
    elif change == "replayed":
        other = _reservation(measuring, rid="0002-00000000000000bb")
        launch = dataclasses.replace(m.launch, reservation=other)
    else:
        launch = SimpleNamespace(reservation=m.reservation, admission=m.launch.admission)
    with pytest.raises(gjs.JailRefused):
        gjs.consume_admission(launch, m.jail, proxy, holder, measuring.command, measuring.binary)
    assert not any(Path(m.reservation.grant_dir).glob("admission-*"))


def test_ba_j7_prepare_refuses_a_pre_existing_sink_entry(measuring):
    sink = Path(gjs.sink_source(str(measuring.review / "seat-home")))
    (sink / "old").write_bytes(b"")
    with pytest.raises(seat_jail.SeatSandboxRefused):
        _measurement(measuring)


@pytest.mark.parametrize("change", ["removed_mask", "shadow_mount", "mount_after", "reordered",
                                    "unnormalised", "above"])
def test_the_mount_policy_check_alone_refuses_each_shape(world, change):
    """The §2.3 mount-policy check by itself (the launch digest also catches these)."""
    gjs._check_mount_policy(world.jail)
    owner = list(world.jail.process_owner)
    if change == "removed_mask":
        index = owner.index("/seat/tree/.grok")
        del owner[index - 2:index + 1]
    elif change == "shadow_mount":
        index = owner.index("--remount-ro")
        owner[index:index] = ["--tmpfs", "/seat/home/.grok/skills"]
    elif change == "mount_after":
        index = owner.index("--remount-ro")
        owner[index + 2:index + 2] = ["--bind", "/tmp", "/seat/elsewhere"]
    elif change == "reordered":
        a, b = owner.index("/seat/home/.claude"), owner.index("/seat/home/.cursor")
        owner[a], owner[b] = owner[b], owner[a]
    elif change == "unnormalised":
        owner[owner.index("/seat/tree/.agents")] = "/seat/tree/./.agents"
    else:
        index = owner.index("--bind")
        owner[index:index] = ["--tmpfs", "/seat/home/.grok-parent-of-nothing", "--tmpfs",
                              "/seat/home/.config/grove/.."]
    with pytest.raises(gjs.JailRefused):
        gjs._check_mount_policy(dataclasses.replace(world.jail, process_owner=tuple(owner)))


def test_an_unjailed_config_differing_from_the_pinned_jailed_bytes_refuses(monkeypatch):
    """Only the equality assertion catches this: the jailed bytes keep the pin, the
    unjailed source returns other bytes without raising."""
    pinned = gts.seat_config()
    monkeypatch.setattr(cred, "seat_config_bytes", lambda: pinned)
    monkeypatch.setattr(gts, "seat_config", lambda: pinned + b"#")
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        gjs.staged_config_bytes()
    assert caught.value.code == "seat_profile_unavailable"


# --- §4.3 row 3 (jail contract r6, ruling (c)): probe_grok_tools keyed on staged_admission --

from test_grok_tool_surface import (  # noqa: E402 - lane L1's unjailed probe harness
    SEAT_ROUTES, _form, _probe, _publish_host, _receipt_path, _seat_surface, seat as _l1_seat,
)

seat = _l1_seat


def _unjailed_only(monkeypatch):
    """The probe with the jailed branch removed: today's unjailed behaviour."""
    monkeypatch.setattr(pi, "_grok_jailed_probe", lambda command: None)


@pytest.fixture
def probing(world, seat, monkeypatch):
    """The unjailed L1 seat (a stand-in grok on PATH with a published host-local frozen
    surface) beside a jailed subject whose admission the test opens or withholds."""
    _publish_host(_seat_surface(seat))
    monkeypatch.setattr(gjs, "resolve_subject",
                        lambda env=None: gjs.JailedSubject(STAND_IN, world.binary))
    return SimpleNamespace(world=world, seat=seat)


def _every_form(seat):
    results = {}
    for route in pi.grok_runtime_forms():
        command = _form(route)
        receipt = _probe(command)
        path = _receipt_path(seat, command)
        results[route] = (receipt, path.read_bytes() if path.exists() else None)
    return results


@pytest.mark.parametrize("withheld", [*gjs.CONDITIONS, "subject"])
def test_probe_is_byte_identical_to_the_unjailed_probe_without_admission(
        probing, monkeypatch, withheld):
    """Not held (each §2.4 condition removed alone, or no resolvable jailed subject): every
    form's receipt and receipt file equal the unjailed probe's."""
    world = probing.world
    _open_gate(world.binary, world.launch, skip=("receipt", *(
        (withheld,) if withheld in {"confirmation", "boundary", "record"} else ())))
    if withheld == "enforcement":
        monkeypatch.setattr(gjs, "ENFORCEMENT", "grok_jail_enforcement.v0")
    elif withheld == "protection":
        table = dict(grok.JAIL_PROTECTION)
        del table[world.binary]
        monkeypatch.setattr(grok, "JAIL_PROTECTION", MappingProxyType(table))
    elif withheld == "subject":
        def unresolved(env=None):
            raise seat_jail.SeatSandboxRefused(REFUSED)
        monkeypatch.setattr(gjs, "resolve_subject", unresolved)
    assert withheld == "subject" or gjs.staged_admission(world.binary) is None
    keyed = _every_form(probing.seat)
    with monkeypatch.context() as patch:
        _unjailed_only(patch)
        unjailed = _every_form(probing.seat)
    assert keyed == unjailed
    assert any(receipt.get("passed") for receipt, _raw in unjailed.values())
    assert gjs.read_private(gjs.receipt_name(world.binary, gjs.staged_argv_digest())) is None


def test_probe_reports_the_jailed_basis_when_admission_holds(probing, monkeypatch):
    """Held: the `staged` row reads and writes only the jailed receipt store and reports
    the jailed basis; every other form reports refused; no unjailed receipt is written and
    the runner is never asked."""
    from phase_loop_runtime import seat_window

    world = probing.world
    _open_gate(world.binary, world.launch, skip=("receipt",))
    assert gjs.staged_admission(world.binary) is not None
    asked = []
    monkeypatch.setattr(pi, "run_provider", lambda *a, **k: asked.append(a))
    results = {}
    for route in pi.grok_runtime_forms():
        command = _form(route)
        results[route] = pi.probe_grok_tools(
            command, allowed_tools=pi._grok_allowed_tools(command),
            runner=lambda argv, **kw: asked.append(argv))
        assert not _receipt_path(probing.seat, command).exists(), route
    staged = results.pop("staged")
    assert staged["passed"] is True and staged["basis"] == "frozen_measurement"
    assert staged["context"] == gjs.JAIL_CONTEXT and staged["surface_source"] == "host_local"
    assert staged["launch_digest"] == world.launch
    assert gjs.jail_receipt_matches(world.binary, world.launch) is not None
    assert all(receipt == {"passed": False, "public_code": REFUSED}
               for receipt in results.values()), results
    assert asked == []
    rows = {row["route"]: row for row in seat_window.probe_tool_rows()}
    assert rows["staged"] == {"route": "staged", "passed": True, "basis": "frozen_measurement",
                              "source": "host_local"}
    assert all(not row["passed"] for route, row in rows.items() if route != "staged")
    assert set(SEAT_ROUTES) <= set(rows)


def test_probe_admission_is_read_for_the_resolved_subject_only(probing, monkeypatch):
    """Admission held for another image does not switch the probe."""
    world = probing.world
    _open_gate(world.binary, world.launch)
    monkeypatch.setattr(gjs, "resolve_subject",
                        lambda env=None: gjs.JailedSubject(STAND_IN, "0" * 64))
    keyed = _every_form(probing.seat)
    with monkeypatch.context() as patch:
        _unjailed_only(patch)
        assert keyed == _every_form(probing.seat)
