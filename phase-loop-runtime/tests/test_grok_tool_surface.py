"""The frozen basis of the grok tool probe (lane L1 of the grok tool-surface plan).

Contract: ``plans/artifacts/grok-tool-surface-contract-v1.md``. No installed grok build has
``--list-tools``, so the probe gains a second basis: a measured surface per binary digest and
route argv digest, valid only inside ``grok_seat_context.v1``. This lane ships the catalog
empty and wires no launch to the final context check, so every grok route stays
``grok_tool_surface_unverified``; these tests show it fails closed and that each rule holds
alone. No test runs grok or contacts the vendor: the probe's runner is a stand-in that answers
with the real 1.0.89 outputs in ``fixtures/grok_1_0_89/``.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import ssl
import subprocess
import tomllib
import urllib.parse
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime import panel_invoker as pi

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "grok_1_0_89"
HELP = (FIXTURES / "help.out").read_bytes()
VERSION = (FIXTURES / "version.out").read_bytes()
LISTTOOLS_ERR = (FIXTURES / "listtools.err").read_bytes()
#: A stand-in for the ``grok-review`` allow-list digest; lane L2a ships the allow-list.
ALLOWLIST = "a" * 64
SEAT_ROUTES = ("review", "sealed", "staged")
#: The five digests in the contract header.
CONTRACT_DIGESTS = {
    "help.out": "67572647636f496ccfdd1899390efb1dc14bc7de8a4e77c109ef22787fb80c16",
    "version.out": "1e1b53a8ed47243cf0f71d5199d626d7c5a1a83c666b2c9d95cbb08c8deeb059",
    "listtools.err": "4f7e3e9993486c3ca348e6fded76e9000b34fc9d7cffde78f249e1833f990dad",
    "forms.json": "17e63cbb744e5645554f4a17f4ce933131f02f88375e8411a0f6c068d68c9081",
    "argv-parse-summary.json": "382a8d0690d07237d990774973b0ac236b4542d22e9499ab50e14b21f3f9df6b",
}
CONTRACT_BINARY = "a3dface51d9bdc71fd121e0481dd02d9b46a721f7a6b892f756480e9666eba1f"
REFUSED = "grok_tool_surface_unverified"
#: The real reader, before any fixture stands in for the allow-list lane L2a ships.
_SHIPPED_ALLOWLIST_DIGEST = gts.egress_allowlist_digest


class _Launched(Exception):
    """The launch primitive was reached."""


def _runner(calls=None, *, help_text=None, version_text=None, help_err="", version_rc=0,
            version_err="", help_bytes=None):
    """Answers like grok 1.0.89 offline: ``--help`` and ``--version`` from the fixtures, and
    clap's refusal for ``--list-tools``. A ``text=False`` call gets bytes, as subprocess
    gives them; ``help_bytes`` is what a bytes read of ``--help`` sees, where text mode
    would have normalised it."""
    calls = [] if calls is None else calls

    def runner(argv, **options):
        text = options.get("text", True)
        calls.append((*argv[1:], "text" if text else "bytes"))
        if argv[-1] == "--help":
            out, err, rc = HELP.decode() if help_text is None else help_text, help_err, 0
            if not text and help_bytes is not None:
                return subprocess.CompletedProcess(argv, 0, help_bytes, err.encode())
        elif argv[-1] == "--version":
            out, err, rc = VERSION.decode() if version_text is None else version_text, version_err, version_rc
        else:
            out, err, rc = "", LISTTOOLS_ERR.decode(), 2
        if not text:
            return subprocess.CompletedProcess(argv, rc, out.encode(), err.encode())
        return subprocess.CompletedProcess(argv, rc, out, err)
    return runner


@pytest.fixture
def seat(tmp_path, monkeypatch):
    """A grok binary on the provider search path, a private record root, a HOME holding the
    two files a grok seat projects, and a stand-in ``grok-review`` allow-list digest."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    binary = bin_dir / "grok"
    binary.write_bytes(b"\x7fELF grok 1.0.89 stand-in, never executed\n")
    binary.chmod(0o755)
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(bin_dir))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    home = tmp_path / "home"
    (home / ".grok").mkdir(parents=True)
    for name, body in ((".grok/auth.json", '{"access_token": "fixture-access-token-0001"}'),
                       (".grok/agent_id", "fixture-agent-0001")):
        (home / name).write_text(body)
        (home / name).chmod(0o600)
    monkeypatch.setattr(gts, "egress_allowlist_digest", lambda: ALLOWLIST)
    # The proxy-only namespace a launch holds: its holder is a stand-in here.
    monkeypatch.setattr(pi, "_filtered_holder_namespace", lambda: 1)
    out, tree = tmp_path / "out", tmp_path / "tree"
    out.mkdir()
    tree.mkdir()
    return SimpleNamespace(binary=binary, digest=sha256(binary.read_bytes()).hexdigest(),
                           env={"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin",
                                "LANG": "C.UTF-8"},
                           home=home, out=out, tree=tree, root=tmp_path)


def _form(route, directory="/definition-probe"):
    """A runtime form, with its masked ``--cwd`` slot naming ``directory``."""
    return [str(directory) if word == "/definition-probe" else word
            for word in pi.grok_runtime_forms()[route]]


def _route(label, argv, tools=None):
    tools = sorted(pi._grok_allowed_tools(argv)) if tools is None else tools
    return {"route": label, "argv_digest": pi._grok_argv_digest(argv), "tools": tools,
            "definitions_sha256": sha256(label.encode()).hexdigest()}


def _surface(binary_digest, routes, **overrides):
    surface = {
        "binary_sha256": binary_digest, "version": VERSION.decode().rstrip("\n"),
        "version_sha256": sha256(VERSION).hexdigest(), "help_sha256": sha256(HELP).hexdigest(),
        "model": "grok-4.7", "effort": "high", "context": gts.GROK_SEAT_CONTEXT,
        "context_digest": overrides.pop("context_digest", None) or gts.context_digest(),
        "measured_at": "2026-11-20T12:00:00Z", "routes": routes,
    }
    surface.update(overrides)
    return surface


def _seat_surface(seat, **overrides):
    return _surface(seat.digest, [_route(route, _form(route)) for route in SEAT_ROUTES], **overrides)


def _publish_host(surface, *, host_digest=None):
    from phase_loop_runtime import president_adapter as pa
    from phase_loop_runtime import seat_window
    name = gts.host_record_name(surface["binary_sha256"])
    (pa.private_record_root() / name).unlink(missing_ok=True)
    written = pa.write_private_record(name, {
        "schema": gts.HOST_RECORD_SCHEMA,
        "host_digest": seat_window._host_digest() if host_digest is None else host_digest,
        "surface": surface})
    # Lane L2b: a host-local route is consumable only while the attempts register names it
    # published from the latest attempt, as --aggregate leaves it.
    register = {"schema": gts.ATTEMPTS_SCHEMA, "binary_sha256": surface["binary_sha256"],
                "host_digest": seat_window._host_digest(), "attempts": {}, "published": {}}
    for route in surface["routes"]:
        register["attempts"][route["argv_digest"]] = {
            "route": route["route"], "grant": "fixture-grant", "reservation": "0001-" + "0" * 16,
            "at": "2026-11-20T12:00:00Z"}
        register["published"][route["argv_digest"]] = {
            "grant": "fixture-grant", "reservation": "0001-" + "0" * 16,
            "surface_digest": gts.surface_digest(surface, route)}
    attempts = gts.attempts_name(surface["binary_sha256"])
    (pa.private_record_root() / attempts).unlink(missing_ok=True)
    pa.write_private_record(attempts, register)
    return written


def _catalog(monkeypatch, surfaces=(), revoked=()):
    document = {"schema": gts.CATALOG_SCHEMA, "revoked": list(revoked), "surfaces": list(surfaces)}
    monkeypatch.setattr(gts, "_catalog_bytes", lambda: json.dumps(document).encode())


def _probe(command, **runner_options):
    return pi.probe_grok_tools(command, allowed_tools=pi._grok_allowed_tools(command),
                               runner=_runner(**runner_options))


def _receipt_path(seat, command):
    from phase_loop_runtime import president_adapter as pa
    return pa.private_record_root() / (
        "grok-probe-" + seat.digest + "-" + pi._grok_argv_digest(command) + ".json")


def _rewrite_receipt(seat, command, change):
    from phase_loop_runtime import president_adapter as pa
    path = _receipt_path(seat, command)
    record = json.loads(path.read_text())
    change(record)
    path.unlink()
    pa.write_private_record(path.name, record)


def _receipt(seat, command, kind):
    """A passing receipt for ``command``: ``legacy`` (written before the basis field),
    ``list_tools`` or ``frozen_measurement``."""
    # A form with no allow-list must be offered something its deny-list leaves.
    tools = sorted(pi._grok_allowed_tools(command)) if "--tools" in command else ["read_file"]
    if kind == "frozen_measurement":
        _publish_host(_surface(seat.digest, [_route("form", command, tools)]))
        receipt = _probe(command)
    else:
        receipt = pi.record_tool_probe(
            command, {"tools": tools, "diagnostics": []},
            allowed_tools=pi._grok_allowed_tools(command), version=VERSION.decode())
        if kind == "legacy":
            _rewrite_receipt(seat, command, lambda record: record.pop("basis"))
    assert receipt["passed"] and receipt["basis"] == ("list_tools" if kind == "legacy" else kind)
    return receipt


def _proxy(**overrides):
    from phase_loop_runtime.seat_egress_proxy import SeatEgressProxy
    values = dict(socket="/run/fixture/proxy.sock", proxy_url="http://fixture", ca_cert=Path("/fixture/ca.crt"),
                  ca_sha256="0" * 64, inner_sni_check=True, process=SimpleNamespace(poll=lambda: None),
                  allowlist_id=gts.EGRESS_ALLOWLIST_ID, allowlist_digest=ALLOWLIST)
    values.update(overrides)
    return SeatEgressProxy(**values)


PREFIX = ("nsenter", "-t", "4242", "--net", "--")


@contextlib.contextmanager
def _egress(prefix=PREFIX):
    token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
    try:
        yield
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(token)


@pytest.fixture
def launches(monkeypatch):
    """Everything below the launch-owner's own checks is a stand-in; reaching the launch
    primitive raises :class:`_Launched`."""
    from phase_loop_runtime import seat_seccomp
    seen = []

    def launch_provider(command, **kwargs):
        seen.append(command)
        raise _Launched()
    monkeypatch.setattr(pi, "launch_provider", launch_provider)
    monkeypatch.setattr(pi, "_filtered_holder_namespace", lambda: 1)
    # The holder and proxy are stand-ins, so is their bridge (lane L2c; the real binding is
    # exercised in tests/test_grok_board_leg_frozen_basis.py and lane L2b's tests).
    monkeypatch.setattr(gts, "bridged_to", lambda prefix, proxy: True)
    monkeypatch.setattr(pi, "_seat_filesystem_view", lambda *a, **k: [])
    monkeypatch.setattr(pi, "_seat_owner", lambda *a, **k: [])
    monkeypatch.setattr(seat_seccomp, "sealed_keyring_filter", lambda: os.open(os.devnull, os.O_RDONLY))
    return seen


CONFIG_PATH = gts.PRIVATE_HOME + "/" + gts.SEAT_CONFIG_RELATIVE
#: Descriptors the helpers below opened; closed after each test.
_DESCRIPTORS: list[int] = []


@pytest.fixture(autouse=True)
def _close_descriptors():
    yield
    while _DESCRIPTORS:
        with contextlib.suppress(OSError):
            os.close(_DESCRIPTORS.pop())


def _held(descriptor: int) -> int:
    _DESCRIPTORS.append(descriptor)
    return descriptor


def _memfd(data: bytes, *, seals: int = gts._CONFIG_SEALS, offset: int = 0) -> int:
    """A memfd holding ``data`` at ``offset`` with ``seals``: a stand-in for the descriptor
    behind the seat config's mount."""
    descriptor = _held(os.memfd_create("fixture-config", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING))
    os.write(descriptor, data)
    os.lseek(descriptor, offset, os.SEEK_SET)
    if seals:
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
    return descriptor


def _with_config(profile, descriptor=None, *, passed=True):
    """``profile`` with the seat config mounted from ``descriptor`` (by default the real
    sealed one), in the mode ``seat_profile`` composes."""
    descriptor = _held(gts.seat_config_descriptor()) if descriptor is None else descriptor
    return replace(profile, mount_args=(*profile.mount_args, *gts.seat_config_projection(descriptor)),
                   pass_fds=(*profile.pass_fds, descriptor) if passed else profile.pass_fds)


def _projected(profile, proxy, *, seat_config=True):
    """What ``seat_profile(egress_proxy=...)`` adds, on a profile composed without it: lane
    L2a's ``grok-review`` proxy projection (the read-only CA file and the two variables) and
    the seat config of erratum 8, unless the profile already carries one or
    ``seat_config`` is false."""
    ca = gts.PRIVATE_HOME + "/" + gts.PROXY_PROJECTED_PATHS[0]
    if ca in profile.mount_args:
        return profile
    if seat_config and CONFIG_PATH not in profile.mount_args:
        profile = _with_config(profile)
    url = getattr(proxy, "proxy_url", "http://fixture")
    return replace(profile, mount_args=(*profile.mount_args, "--perms", "0444", "--ro-bind-data", "9", ca),
                   env={**profile.env, "HTTPS_PROXY": url, "SSL_CERT_FILE": ca})


def _verify(seat, profile, *, seat_config=True, **overrides):
    options = dict(env=seat.env, cwd=seat.out, role=pi.SeatLaunchRole.PROVIDER_REVIEW, proxy=_proxy())
    options.update(overrides)
    return gts.verify_launch_context(
        _projected(profile, options["proxy"], seat_config=seat_config), **options)


# --------------------------------------------------------------------------- fixtures


def test_the_fixtures_are_the_real_1_0_89_outputs():
    for name, digest in CONTRACT_DIGESTS.items():
        assert sha256((FIXTURES / name).read_bytes()).hexdigest() == digest, name
    summary = json.loads((FIXTURES / "argv-parse-summary.json").read_text())
    assert summary["binary_sha256"] == CONTRACT_BINARY
    assert {row["case"]: row["rc"] for row in summary["rows"]
            if row["case"] in pi.grok_runtime_forms()} == dict.fromkeys(pi.grok_runtime_forms(), 0)
    # The probe reads help and version as text; for these bytes that round-trips exactly, so
    # the digests a record binds are those of the exact outputs.
    for raw in (HELP, VERSION):
        assert b"\r" not in raw and raw.decode("utf-8").encode("utf-8") == raw
    forms = json.loads((FIXTURES / "forms.json").read_text())
    live = pi.grok_runtime_forms()
    assert set(forms) == set(live)
    for route, form in forms.items():
        assert pi._grok_argv_digest(form["argv"]) == form["argv_digest"] == pi._grok_argv_digest(live[route])


# --------------------------------------------------------------------------- the probe (§4.1)


def test_the_real_1_0_89_help_selects_the_frozen_basis(seat):
    calls = []
    command = pi.grok_runtime_forms()["review"]
    receipt = pi.probe_grok_tools(command, allowed_tools=pi._grok_allowed_tools(command),
                                  runner=_runner(calls))
    # Never --list-tools; the basis is chosen on text, the record bound to literal bytes.
    assert calls == [("--help", "text"), ("--help", "bytes"), ("--version", "bytes")]
    assert not receipt["passed"] and "basis" not in receipt  # no record yet


@pytest.mark.parametrize("stream", ["crlf", "lone_cr", "lf"])
def test_the_frozen_digests_are_of_the_literal_bytes(seat, stream):
    """Text mode turns CRLF and a lone CR into LF, so a build printing them would match a
    record of the LF bytes; the frozen basis hashes what was printed."""
    _publish_host(_seat_surface(seat))
    command = pi.grok_runtime_forms()["review"]
    assert HELP.endswith(b"t\n")
    printed = {"crlf": HELP.replace(b"\n", b"\r\n"), "lone_cr": HELP[:-1] + b"\r", "lf": HELP}[stream]
    assert printed.decode().replace("\r\n", "\n").replace("\r", "\n") == HELP.decode()
    receipt = _probe(command, help_bytes=printed)
    assert receipt["passed"] is (stream == "lf")
    assert pi.grok_tool_gate(command) is (stream == "lf")


def test_a_build_that_advertises_the_listing_in_its_bytes_takes_no_frozen_record(seat):
    _publish_host(_seat_surface(seat))
    command = pi.grok_runtime_forms()["review"]
    advertised = HELP + b"--list-tools Print tool definitions without running a model\n"
    assert not _probe(command, help_bytes=advertised)["passed"]


def test_a_build_that_advertises_the_listing_is_listed_and_never_falls_back(seat):
    _publish_host(_seat_surface(seat))
    command = pi.grok_runtime_forms()["review"]
    tools = sorted(pi._grok_allowed_tools(command))
    calls = []

    def runner(argv, **options):
        calls.append(argv[1:3])
        if argv[-1] == "--help":
            return subprocess.CompletedProcess(argv, 0, "--list-tools Print tool definitions without running a model", "")
        if argv[-1] == "--version":
            return subprocess.CompletedProcess(argv, 0, VERSION.decode(), "")
        return subprocess.CompletedProcess(argv, 0, "{", "")  # a broken listing
    receipt = pi.probe_grok_tools(command, allowed_tools=set(tools), runner=runner)
    assert [call[0] for call in calls] == ["--help", "--version", "--list-tools"]
    assert not receipt["passed"]  # the frozen record is not a fallback
    receipt = pi.probe_grok_tools(command, allowed_tools=set(tools), runner=lambda argv, **kw: (
        subprocess.CompletedProcess(argv, 0, json.dumps({"tools": tools, "diagnostics": []}), "")
        if "--list-tools" in argv else runner(argv, **kw)))
    assert receipt["passed"] and receipt["basis"] == "list_tools"
    assert not set(gts.RECEIPT_FIELDS) & set(receipt)


@pytest.mark.parametrize("allowlist", [False, True])
def test_with_the_empty_shipped_catalog_every_form_refuses(seat, monkeypatch, capsys, allowlist):
    """Acceptance criterion 1: the real fixtures and the empty catalog refuse every form,
    as this lane ships (no ``grok-review`` allow-list, so no context digest) and once one
    exists."""
    from phase_loop_runtime import seat_egress_proxy, seat_window
    assert gts.load_catalog() == gts.Catalog(revoked=frozenset(), surfaces={})
    if not allowlist:
        # Lane L2a now ships the allow-list; the case keeps its meaning by taking it away.
        monkeypatch.setattr(gts, "egress_allowlist_digest", _SHIPPED_ALLOWLIST_DIGEST)
        real_path = seat_egress_proxy._data_path
        monkeypatch.setattr(seat_egress_proxy, "_data_path", lambda name: (
            real_path(name).with_name("absent-" + name) if name.startswith("grok-review") else
            real_path(name)))
        with pytest.raises(seat_egress_proxy.EgressLayerUnavailable):
            gts.context_digest()
    for route, command in pi.grok_runtime_forms().items():
        receipt = _probe(command)
        assert (receipt["passed"], receipt["public_code"]) == (False, REFUSED), route
        assert "basis" not in receipt and "tools" not in receipt
        assert not pi.grok_tool_gate(command)
    runner = _runner()
    monkeypatch.setattr(pi, "run_provider", lambda argv, **kw: runner(argv, **kw))
    rc = seat_window.cli_main(SimpleNamespace(action="probe-tools", model=None, effort="high"))
    result = json.loads(capsys.readouterr().out)
    assert (rc, result["status"]) == (1, "candidate")
    assert result["routes"] == [{"route": route, "passed": False, "basis": "none"}
                                for route in pi.grok_runtime_forms()]


@pytest.mark.parametrize("change", ["version", "help", "help_stderr", "version_rc", "version_stderr",
                                    "context", "identity"])
def test_a_record_is_used_only_on_the_outputs_and_context_it_was_measured_on(seat, monkeypatch, change):
    _publish_host(_seat_surface(seat))
    command = pi.grok_runtime_forms()["review"]
    assert _probe(command)["passed"]
    options = {"version": {"version_text": "grok 1.0.90 (000000000000)\n"},
               "help": {"help_text": HELP.decode() + " "},
               "help_stderr": {"help_err": "warning"},
               "version_rc": {"version_rc": 1},
               "version_stderr": {"version_err": "warning"}}.get(change, {})
    if change == "context":
        monkeypatch.setattr(gts, "egress_allowlist_digest", lambda: "b" * 64)
    if change == "identity":  # the binary changed while it was probed
        identity, seen = pi._grok_probe_identity, []

        def probe_identity(*args):
            seen.append(args)
            return identity(*args) if len(seen) == 1 else ("/fixture/grok", seat.digest, ("changed",))
        monkeypatch.setattr(pi, "_grok_probe_identity", probe_identity)
    receipt = _probe(command, **options)
    assert (receipt["passed"], receipt["public_code"]) == (False, REFUSED)
    assert not pi.grok_tool_gate(command)


# ------------------------------------------------------------- receipts and the gate (§4.2-§4.3)


@pytest.mark.parametrize("route", SEAT_ROUTES)
def test_a_matching_record_passes_the_provisional_step_and_launches_only_on_a_marked_profile(
        seat, launches, route):
    _publish_host(_seat_surface(seat))
    command = _form(route, seat.tree)
    receipt = _probe(command)
    assert receipt["passed"] and receipt["basis"] == "frozen_measurement"
    assert receipt["surface_source"] == "host_local" and receipt["context"] == gts.GROK_SEAT_CONTEXT
    assert receipt["context_digest"] == gts.context_digest()
    assert pi.grok_tool_gate(command, seat.env)  # provisional: composition only
    with pytest.raises(pi._seat_jail.SeatSandboxRefused) as refusal:
        pi.require_grok_admission(command, seat.env)  # no launch context
    assert refusal.value.code == REFUSED
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (owned, profile):
        assert profile.grok_launch_context == gts.ProvisionalContext(tuple(command))
        with pytest.raises(pi._seat_jail.SeatSandboxRefused):
            pi.launch_owned(owned, role=pi.SeatLaunchRole.PROVIDER_REVIEW, profile=profile,
                            cwd=str(seat.out), env=seat.env)
        assert launches == []
        marked = _verify(seat, profile)
        assert gts.is_issued(marked.grok_launch_context)
        with pytest.raises(_Launched):
            pi.launch_owned(owned, role=pi.SeatLaunchRole.PROVIDER_REVIEW, profile=marked,
                            cwd=str(seat.out), env=seat.env)
        assert len(launches) == 1


@pytest.mark.parametrize("change", ["revoked", "withdrawn", "replaced", "shadowed_by_catalog",
                                    "context_drift", "other_host", "catalog_void"])
def test_each_invalidation_refuses_a_cached_receipt(seat, monkeypatch, change):
    surface = _seat_surface(seat)
    _publish_host(surface)
    command = pi.grok_runtime_forms()["review"]
    assert _probe(command)["passed"] and pi.grok_tool_gate(command)
    if change == "revoked":
        _catalog(monkeypatch, revoked=[seat.digest])
    elif change == "withdrawn":
        from phase_loop_runtime import president_adapter as pa
        (pa.private_record_root() / gts.host_record_name(seat.digest)).unlink()
    elif change == "replaced":
        _publish_host({**surface, "measured_at": "2026-11-21T12:00:00Z"})
    elif change == "shadowed_by_catalog":
        _catalog(monkeypatch, surfaces=[{**surface, "measured_at": "2026-11-21T12:00:00Z"}])
    elif change == "context_drift":
        monkeypatch.setattr(gts, "egress_allowlist_digest", lambda: "b" * 64)
    elif change == "other_host":
        _publish_host(surface, host_digest="d" * 64)
    elif change == "catalog_void":
        monkeypatch.setattr(gts, "_catalog_bytes", lambda: b"{")
    assert not pi.grok_tool_gate(command)
    # Re-running the probe rewrites the receipt to the current state.
    receipt = _probe(command)
    assert receipt["passed"] is (change in {"replaced", "shadowed_by_catalog"})
    if change == "replaced":
        assert receipt["surface_source"] == "host_local" and "shadowed" not in receipt
    if change == "shadowed_by_catalog":
        assert receipt["surface_source"] == "catalog" and receipt["shadowed"] == "host_local"


@pytest.mark.parametrize("change", ["unknown_basis", "basis_null", "frozen_field_on_listing",
                                    "frozen_field_on_legacy", "missing_field", "bad_source",
                                    "bad_context", "bad_digest"])
def test_the_receipt_fields_are_validated_in_combination(seat, change):
    _publish_host(_seat_surface(seat))
    command = pi.grok_runtime_forms()["review"]
    frozen = change in {"missing_field", "bad_source", "bad_context", "bad_digest", "unknown_basis",
                        "basis_null"}
    _receipt(seat, command, "frozen_measurement" if frozen else "list_tools")
    assert pi.grok_tool_gate(command)
    edits = {
        "unknown_basis": lambda record: record.update(basis="frozen"),
        "basis_null": lambda record: record.update(basis=None),
        "frozen_field_on_listing": lambda record: record.update(surface_digest="1" * 64),
        "frozen_field_on_legacy": lambda record: (record.pop("basis"), record.update(context=gts.GROK_SEAT_CONTEXT)),
        "missing_field": lambda record: record.pop("surface_source"),
        "bad_source": lambda record: record.update(surface_source="elsewhere"),
        "bad_context": lambda record: record.update(context="grok_seat_context.v2"),
        "bad_digest": lambda record: record.update(surface_digest=record["surface_digest"].upper()),
    }
    _rewrite_receipt(seat, command, edits[change])
    assert not pi.grok_tool_gate(command)


@pytest.mark.parametrize("kind", ["legacy", "list_tools"])
def test_listing_receipts_keep_their_meaning(seat, monkeypatch, kind):
    command = pi.grok_runtime_forms()["review"]
    _receipt(seat, command, kind)
    assert pi.grok_tool_gate(command) and pi.require_grok_admission(command)
    # A listing receipt never needs, or consults, a frozen record or the context digest.
    monkeypatch.setattr(gts, "load_catalog", lambda: pytest.fail("catalog consulted"))
    monkeypatch.setattr(gts, "egress_allowlist_digest", lambda: pytest.fail("context consulted"))
    assert pi.grok_tool_gate(command) and pi.require_grok_admission(command)


# ---------------------------------------------------------------- the launch context (§4.4)


def _composed(seat, route="staged"):
    _publish_host(_seat_surface(seat))
    command = _form(route, seat.tree)
    assert _probe(command)["passed"]
    return command


@pytest.mark.parametrize("name", gts.DISCOVERY_PATHS)
def test_a_tree_holding_a_discovery_path_is_ineligible(seat, name):
    command = _composed(seat)
    target = seat.tree / name
    target.write_text("{}") if "." in name[1:] else target.mkdir()
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        with pytest.raises(pi._seat_jail.SeatSandboxRefused) as refusal:
            _verify(seat, profile)
    assert refusal.value.code == REFUSED
    assert target.exists()  # the tree is judged, never rewritten


def test_the_discovery_guard_judges_what_the_seat_can_see(seat, tmp_path):
    command = _composed(seat)
    # Ancestors the seat cannot see do not count; the seat's tmpfs cwd hides the host's.
    (tmp_path / ".claude").mkdir()
    (seat.out / ".grok").mkdir()
    # Rules files are prompt text only on the pinned build; nested discovery is not bound.
    (seat.tree / "AGENTS.md").write_text("rules\n")
    (seat.tree / "CLAUDE.md").write_text("rules\n")
    (seat.tree / "sub" / ".grok").mkdir(parents=True)
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        assert gts.is_issued(_verify(seat, profile).grok_launch_context)
        # A visible ancestor does count: a bound input inside a discovery directory shows it.
        (tmp_path / ".claude" / "settings.json").write_text("{}")
        shown = replace(profile, readonly_paths=(*profile.readonly_paths, tmp_path / ".claude" / "settings.json"))
        with pytest.raises(pi._seat_jail.SeatSandboxRefused):
            _verify(seat, shown)


@pytest.mark.parametrize("change", ["grok_env", "xai_env", "extra_env", "home_file", "home_bind",
                                    "missing_projection", "second_tmpfs", "xdg"])
def test_the_home_and_environment_conditions_each_refuse_alone(seat, change):
    command = _composed(seat)
    home = gts.PRIVATE_HOME
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        assert gts.is_issued(_verify(seat, profile).grok_launch_context)
        mounts = list(profile.mount_args)
        changed = {
            "grok_env": lambda: replace(profile, env={**profile.env, "GROK_SANDBOX": "off"}),
            "xai_env": lambda: replace(profile, env={**profile.env, "XAI_API_KEY": "fixture"}),
            "extra_env": lambda: replace(profile, env={**profile.env, "NO_PROXY": "*"}),
            "home_file": lambda: replace(profile, mount_args=(*mounts, "--file", "9", home + "/.grok/settings.json")),
            "home_bind": lambda: replace(profile, mount_args=(*mounts, "--ro-bind", "/etc", home + "/.claude")),
            "missing_projection": lambda: replace(profile, mount_args=tuple(
                mounts[:mounts.index(home + "/.grok/agent_id") - 4]
                + mounts[mounts.index(home + "/.grok/agent_id") + 1:])),
            "second_tmpfs": lambda: replace(profile, mount_args=(*mounts, "--tmpfs", "/run/fixture")),
            "xdg": lambda: replace(profile, env={**profile.env, "XDG_CONFIG_HOME": "/tmp"}),
        }[change]()
        with pytest.raises(pi._seat_jail.SeatSandboxRefused):
            _verify(seat, changed)


def test_managed_configuration_refuses(seat, monkeypatch, tmp_path):
    managed = tmp_path / "etc-grok" / "managed_config.toml"
    monkeypatch.setattr(gts, "MANAGED_CONFIG_PATHS", (str(managed),))
    command = _composed(seat)
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        assert gts.is_issued(_verify(seat, profile).grok_launch_context)
        managed.parent.mkdir()
        managed.write_text("")
        with pytest.raises(pi._seat_jail.SeatSandboxRefused):
            _verify(seat, profile)


@pytest.mark.parametrize("change", ["bind_onto_cwd", "bind_onto_tree_ancestor", "data_file",
                                    "link_at_ancestor", "etc_bind_claude_settings", "etc_bind_grok_config"])
def test_the_guards_judge_the_effective_mount_view(seat, tmp_path, change):
    """A mount the launch composes later than the base view, at or above a discovery or
    managed-configuration path, is judged on its own source."""
    command = _composed(seat)
    alternate, empty = tmp_path / "alternate", tmp_path / "empty"
    alternate.mkdir()
    empty.mkdir()
    extra = {
        "bind_onto_cwd": lambda: ((alternate / ".grok").mkdir(), ("--ro-bind", str(alternate), str(seat.out))),
        "bind_onto_tree_ancestor": lambda: ((alternate / ".mcp.json").write_text("{}"),
                                            ("--ro-bind", str(alternate), str(seat.tree.parent))),
        "data_file": lambda: (None, ("--file", "9", str(seat.out / ".mcp.json"))),
        "link_at_ancestor": lambda: (None, ("--symlink", str(alternate), str(seat.tree))),
        "etc_bind_claude_settings": lambda: (
            (alternate / "claude-code").mkdir(),
            (alternate / "claude-code" / "managed-settings.json").write_text("{}"),
            ("--ro-bind", str(alternate), "/etc")),
        "etc_bind_grok_config": lambda: (
            (alternate / "grok").mkdir(), (alternate / "grok" / "requirements.toml").write_text(""),
            ("--ro-bind", str(alternate), "/etc")),
    }[change]()[-1]
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        assert gts.is_issued(_verify(seat, profile).grok_launch_context)
        with pytest.raises(pi._seat_jail.SeatSandboxRefused):
            _verify(seat, replace(profile, mount_args=(*profile.mount_args, *extra)))
        if extra[0] == "--ro-bind":  # the same mount from a source without the path passes
            control = (extra[0], str(empty), extra[2])
            assert gts.is_issued(_verify(seat, replace(
                profile, mount_args=(*profile.mount_args, *control))).grok_launch_context)


SETTINGS = "/etc/claude-code/managed-settings.json"


def _alternate_etc(root):
    """An alternate ``/etc`` holding Claude Code's managed settings."""
    etc = root / "alternate-etc"
    (etc / "claude-code").mkdir(parents=True)
    (etc / "claude-code" / "managed-settings.json").write_text("{}")
    return etc


def _linked_etc(root, target):
    """An alternate ``/etc`` whose ``claude-code`` is a link to ``target``."""
    etc = root / "linked-etc"
    etc.mkdir(parents=True)
    (etc / "claude-code").symlink_to(target)
    return etc


def _overlap(case, seat, root):
    """``(checked path, extra profile mounts)`` for one overlap case."""
    alternate, empty = _alternate_etc(root), root / "empty"
    empty.mkdir()
    linked_dir = root / "elsewhere"
    linked_dir.mkdir()
    (linked_dir / "managed-settings.json").write_text("{}")
    bound = ("--ro-bind", str(alternate), "/etc")
    tree_parent = root / "tree-parent"
    (tree_parent / "elsewhere-tree").mkdir(parents=True)
    (tree_parent / "elsewhere-tree" / ".grok").mkdir()
    (tree_parent / seat.tree.name).symlink_to(tree_parent / "elsewhere-tree")
    return {
        # Refused: absence cannot be proved.
        "dir_over_bound_view": (SETTINGS, (*bound, "--dir", "/etc/claude-code")),
        "tmpfs_over_bound_view": (SETTINGS, (*bound, "--tmpfs", "/etc/claude-code")),
        "data_over_bound_view": (SETTINGS, (*bound, "--ro-bind-data", "9", "/etc/claude-code")),
        "skipped_optional_bind": (SETTINGS, (*bound, "--ro-bind-try", str(root / "missing"),
                                             "/etc/claude-code")),
        "optional_bind_over_ancestor": (SETTINGS, ("--ro-bind-try", str(empty), "/etc")),
        "intermediate_link": (SETTINGS, ("--ro-bind", str(_linked_etc(root, linked_dir)), "/etc")),
        "intermediate_link_to_missing": (SETTINGS, ("--ro-bind", str(_linked_etc(
            root / "second", Path("/nonexistent-host-path/claude-code"))), "/etc")),
        "intermediate_link_to_discovery": (str(seat.tree / ".grok"),
                                           ("--ro-bind", str(tree_parent), str(seat.tree.parent))),
        "dir_at_path": (SETTINGS, ("--dir", SETTINGS)),
        "tmpfs_at_discovery_path": (str(seat.out / ".grok"), ("--tmpfs", str(seat.out / ".grok"))),
        # Proved absent: admitted.
        "dir_alone": (SETTINGS, ("--dir", "/etc/claude-code")),
        "bind_replacing_bound_view": (SETTINGS, (*bound, "--ro-bind", str(empty), "/etc/claude-code")),
        "tmpfs_over_unshown_view": (SETTINGS, ("--ro-bind", str(empty), "/etc", "--tmpfs", "/etc/claude-code")),
    }[case]


REFUSED_OVERLAPS = ("dir_over_bound_view", "tmpfs_over_bound_view", "data_over_bound_view",
                    "skipped_optional_bind", "optional_bind_over_ancestor", "intermediate_link",
                    "intermediate_link_to_missing", "intermediate_link_to_discovery", "dir_at_path",
                    "tmpfs_at_discovery_path")
PROVED_ABSENT = ("dir_alone", "bind_replacing_bound_view", "tmpfs_over_unshown_view")


@pytest.mark.parametrize("case", REFUSED_OVERLAPS + PROVED_ABSENT)
def test_the_mount_evaluator_admits_only_proved_absence(seat, tmp_path, case):
    """Bubblewrap applies the view in order: a ``--dir`` creates a directory only where none
    exists and hides nothing; a ``-try`` bind is skipped when its source is missing; a bound
    source is followed in the host namespace. What the evaluator cannot prove absent counts
    as visible."""
    command = _composed(seat)
    path, extra = _overlap(case, seat, tmp_path)
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        stock = gts._effective_mounts(pi, profile, str(seat.out))
        assert not gts._visible(path, stock)
        changed = replace(profile, mount_args=(*profile.mount_args, *extra))
        visible = gts._visible(path, gts._effective_mounts(pi, changed, str(seat.out)))
        assert visible is (case in REFUSED_OVERLAPS)


@pytest.mark.parametrize("case", ["dir_over_bound_view", "skipped_optional_bind", "intermediate_link",
                                  "intermediate_link_to_discovery", "dir_alone",
                                  "bind_replacing_bound_view"])
def test_the_final_check_refuses_what_the_evaluator_cannot_prove(seat, tmp_path, case):
    command = _composed(seat)
    _path, extra = _overlap(case, seat, tmp_path)
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        assert gts.is_issued(_verify(seat, profile).grok_launch_context)
        changed = replace(profile, mount_args=(*profile.mount_args, *extra))
        if case in REFUSED_OVERLAPS:
            with pytest.raises(pi._seat_jail.SeatSandboxRefused):
                _verify(seat, changed)
        else:
            assert gts.is_issued(_verify(seat, changed).grok_launch_context)


@pytest.mark.parametrize("route", SEAT_ROUTES)
def test_the_stock_composition_is_proved_clean(seat, route):
    """Control: each seat form's own composition admits, with every path the guards check
    proved absent from its view."""
    _publish_host(_seat_surface(seat))
    command = _form(route, seat.tree)
    assert _probe(command)["passed"]
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        mounts = gts._effective_mounts(pi, profile, str(seat.out))
        checked = [*gts.MANAGED_CONFIG_PATHS, *gts.CHILD_ABSENT_POLICY_PATHS]
        for directory in gts._discovery_directories(command, str(seat.out)):
            while True:
                checked += [os.path.join(directory, name) for name in gts.DISCOVERY_PATHS]
                if directory == "/":
                    break
                directory = os.path.dirname(directory)
        assert [path for path in checked if gts._visible(path, mounts)] == []
        assert gts.is_issued(_verify(seat, profile).grok_launch_context)


def test_claude_managed_settings_are_judged_in_the_child_view(seat, monkeypatch, tmp_path):
    """Present on the host is not a refusal; visible to the child is."""
    command = _composed(seat)
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        # The stock view binds nothing under /etc/claude-code, whatever this host holds.
        mounts = gts._effective_mounts(pi, profile, str(seat.out))
        assert not gts._visible("/etc/claude-code/managed-settings.json", mounts)
    settings = tmp_path / "host-etc" / "claude-code" / "managed-settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"remoteControlAtStartup": true}')
    monkeypatch.setattr(gts, "CHILD_ABSENT_POLICY_PATHS", (str(settings),))
    command = _composed(seat)  # a record under the patched context
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        assert gts.is_issued(_verify(seat, profile).grok_launch_context)
        shown = replace(profile, readonly_paths=(*profile.readonly_paths, settings.parent))
        with pytest.raises(pi._seat_jail.SeatSandboxRefused):
            _verify(seat, shown)


@pytest.mark.parametrize("via", ["launch_owned", "require_grok_admission"])
def test_the_mark_binds_the_discovery_operands_it_judged(seat, launches, via):
    """Verified for a staged root with no discovery path at its root and a nested directory
    holding ``.grok``. Reusing the mark with ``--cwd`` pointed into the nested directory keeps
    the form digest, which masks ``--cwd``, and is refused; so is an added ``--add-dir``."""
    _publish_host(_seat_surface(seat))
    command = _form("review", seat.tree)
    assert _probe(command)["passed"]
    nested = seat.tree / "nested"
    (nested / ".grok").mkdir(parents=True)
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (owned, profile):
        marked = _verify(seat, profile)
        if via == "launch_owned":
            launch = dict(role=pi.SeatLaunchRole.PROVIDER_REVIEW, profile=marked, cwd=str(seat.out),
                          env=seat.env)
            moved = [str(nested) if word == str(seat.tree) else word for word in owned]
            assert moved != owned and pi._grok_argv_digest(moved) == pi._grok_argv_digest(owned)
            for argv in (moved, [*owned, "--add-dir", str(nested)]):
                with pytest.raises(pi._seat_jail.SeatSandboxRefused):
                    pi.launch_owned(argv, **launch)
            assert launches == []
            with pytest.raises(_Launched):
                pi.launch_owned(owned, **launch)  # the argv it judged
        else:  # a grok-named argv, as under a dependency lease
            mark = marked.grok_launch_context
            moved = [str(nested) if word == str(seat.tree) else word for word in command]
            with pytest.raises(pi._seat_jail.SeatSandboxRefused):
                pi.require_grok_admission(moved, seat.env, context=mark)
            assert pi.require_grok_admission(command, seat.env, context=mark)


@pytest.mark.parametrize("change", ["no_egress", "no_proxy", "other_allowlist", "stale_allowlist",
                                    "dead_proxy", "admin_role", "jailed", "unstamped",
                                    "host_namespace"])
def test_the_egress_and_composition_conditions_each_refuse_alone(seat, monkeypatch, change):
    command = _composed(seat)
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        monkeypatch.setattr(pi, "_filtered_holder_namespace", lambda: 1)
        assert gts.is_issued(_verify(seat, profile).grok_launch_context)
        options = {
            "no_proxy": {"proxy": None},
            "other_allowlist": {"proxy": _proxy(allowlist_id="gemini")},
            "stale_allowlist": {"proxy": _proxy(allowlist_digest="b" * 64)},
            "dead_proxy": {"proxy": _proxy(process=SimpleNamespace(poll=lambda: 1))},
            "admin_role": {"role": pi.SeatLaunchRole.PROVIDER_ADMIN},
            "jailed": {"jailed": True},
        }.get(change, {})
        if change == "unstamped":
            profile = replace(profile, grok_launch_context=None)
        if change == "host_namespace":
            def unavailable():
                raise pi._sandbox_egress.EgressUnavailable("seat_filtered_egress_unavailable")
            monkeypatch.setattr(pi, "_filtered_holder_namespace", unavailable)
        with (_egress(()) if change == "no_egress" else contextlib.nullcontext()):
            with pytest.raises(pi._seat_jail.SeatSandboxRefused):
                _verify(seat, profile, **options)


@pytest.mark.parametrize("change", ["profile", "cwd", "egress_prefix", "proxy_exited", "role",
                                    "record_withdrawn", "context_drift", "forged"])
def test_launch_owned_holds_the_mark_to_the_launch(seat, launches, monkeypatch, change):
    command = _composed(seat)
    alive = {"proxy": None}
    proxy = _proxy(process=SimpleNamespace(poll=lambda: alive["proxy"]))
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (owned, profile):
        marked = _verify(seat, profile, proxy=proxy)
        launch = dict(role=pi.SeatLaunchRole.PROVIDER_REVIEW, profile=marked, cwd=str(seat.out), env=seat.env)
        if change == "profile":
            launch["profile"] = replace(marked, env={**marked.env, "TERM": "xterm"})
        elif change == "cwd":
            launch["cwd"] = str(seat.tree)
        elif change == "proxy_exited":
            alive["proxy"] = 0
        elif change == "role":
            launch["role"] = pi.SeatLaunchRole.PROVIDER_ADMIN
        elif change == "record_withdrawn":
            from phase_loop_runtime import president_adapter as pa
            (pa.private_record_root() / gts.host_record_name(seat.digest)).unlink()
        elif change == "context_drift":
            monkeypatch.setattr(gts, "egress_allowlist_digest", lambda: "b" * 64)
        elif change == "forged":
            with pytest.raises(TypeError):
                gts.LaunchContext(command=tuple(command), context_digest=gts.context_digest(),
                                  cwd=str(seat.out), egress_prefix=PREFIX, profile_fingerprint="0" * 64,
                                  proxy=proxy)
            launch["profile"] = replace(marked, grok_launch_context=SimpleNamespace(
                **{key: getattr(marked.grok_launch_context, key) for key in (
                    "command", "context_digest", "cwd", "egress_prefix", "profile_fingerprint", "proxy")}))
        with (_egress(("nsenter", "-t", "4343", "--net", "--")) if change == "egress_prefix"
              else contextlib.nullcontext()):
            with pytest.raises(pi._seat_jail.SeatSandboxRefused):
                pi.launch_owned(owned, **launch)
    assert launches == []


# ------------------------------------------------------------------- consumer audit (§4.4)

RECEIPTS = ("legacy", "list_tools", "frozen_measurement")


def _consumer_command(seat):
    return _form("review", seat.tree)


@pytest.mark.parametrize("kind", RECEIPTS)
def test_consumer_board_review_leg(seat, launches, kind):
    """``_exec_leg`` -> ``_run_leg_with_liveness`` -> ``launch_owned(PROVIDER_REVIEW)``.
    Eligible only once verified and marked, which lane L2c wires."""
    command = _consumer_command(seat)
    _receipt(seat, command, kind)
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (owned, profile):
        launch = dict(role=pi.SeatLaunchRole.PROVIDER_REVIEW, cwd=str(seat.out), env=seat.env)
        if kind == "frozen_measurement":
            with pytest.raises(pi._seat_jail.SeatSandboxRefused):
                pi.launch_owned(owned, profile=profile, **launch)
            assert launches == []
            profile = _verify(seat, profile)
        else:
            assert profile.grok_launch_context is None
        with pytest.raises(_Launched):
            pi.launch_owned(owned, profile=profile, **launch)


@pytest.mark.parametrize("kind", RECEIPTS)
def test_consumer_leg_on_the_fallback_namespace(seat, launches, monkeypatch, kind):
    """``_run_leg_with_liveness`` with no proxy-only prefix holds its own slirp namespace."""
    command = _consumer_command(seat)
    _receipt(seat, command, kind)

    @contextlib.contextmanager
    def isolated_network(**kwargs):
        yield list(PREFIX)
    monkeypatch.setattr(pi._sandbox_egress, "isolated_network", isolated_network)
    expected = pi._seat_jail.SeatSandboxRefused if kind == "frozen_measurement" else _Launched
    with pytest.raises(expected):
        pi._run_leg_with_liveness(command, cwd=seat.out, env=seat.env, deadline_s=30)
    assert len(launches) == (kind != "frozen_measurement")


@pytest.mark.parametrize("kind", RECEIPTS)
def test_consumer_jailed_route(seat, launches, kind):
    command = _consumer_command(seat)
    _receipt(seat, command, kind)
    expected = pi._seat_jail.SeatSandboxRefused if kind == "frozen_measurement" else _Launched
    with pytest.raises(expected):
        pi._run_leg_with_liveness(command, cwd=seat.out, env=seat.env, deadline_s=30,
                                  seat_jail=object(), probe_jail=None)
    assert len(launches) == (kind != "frozen_measurement")


@pytest.mark.parametrize("change", ["withdrawn", "unreadable", "replaced_by_frozen"])
def test_the_jailed_route_needs_a_positive_listing_decision(seat, launches, change):
    """The leg's early gate admits a frozen-basis receipt provisionally. If the receipt is
    then withdrawn (or mid unlink-then-write), unreadable, or turns out frozen, the jailed
    boundary refuses: only a positive legacy or listing decision launches there."""
    command = _consumer_command(seat)
    _receipt(seat, command, "frozen_measurement")
    assert pi.grok_tool_gate(command, seat.env)  # the early, provisional step
    path = _receipt_path(seat, command)
    if change == "withdrawn":
        path.unlink()
    elif change == "unreadable":
        path.chmod(0o644)
    with pytest.raises(pi._seat_jail.SeatSandboxRefused):
        pi._run_leg_with_liveness(command, cwd=seat.out, env=seat.env, deadline_s=30,
                                  seat_jail=object(), probe_jail=None)
    assert launches == []


def test_the_jailed_route_ignores_a_bare_admission(seat, launches, monkeypatch):
    """A gate result that names no basis is not a listing decision."""
    command = _consumer_command(seat)
    monkeypatch.setattr(pi, "grok_tool_gate", lambda *a: True)
    with pytest.raises(pi._seat_jail.SeatSandboxRefused):
        pi._run_leg_with_liveness(command, cwd=seat.out, env=seat.env, deadline_s=30,
                                  seat_jail=object(), probe_jail=None)
    assert launches == []


@pytest.mark.parametrize("kind", RECEIPTS)
def test_consumer_run_provider_admin(seat, launches, kind):
    command = _consumer_command(seat)
    _receipt(seat, command, kind)
    expected = pi._seat_jail.SeatSandboxRefused if kind == "frozen_measurement" else _Launched
    with pytest.raises(expected):
        pi.run_provider(command, cwd=str(seat.out), env=seat.env)
    assert len(launches) == (kind != "frozen_measurement")


@pytest.mark.parametrize("kind", RECEIPTS)
def test_consumer_executor_and_supervisor(seat, launches, kind):
    """``launch_owned(EXECUTOR_TRUSTED)``, and ``launcher.py``'s supervisor launch, which calls
    ``require_grok_admission`` itself before launching the supervisor."""
    command = _consumer_command(seat)
    _receipt(seat, command, kind)
    if kind == "frozen_measurement":
        for attempt in (
                lambda: pi.launch_owned(command, role=pi.SeatLaunchRole.EXECUTOR_TRUSTED,
                                        profile=pi.SeatProfile(env=seat.env), env=seat.env,
                                        cwd=str(seat.out)),
                lambda: pi.require_grok_admission(command, seat.env)):
            with pytest.raises(pi._seat_jail.SeatSandboxRefused):
                attempt()
        assert launches == []
    else:
        assert pi.require_grok_admission(command, seat.env)
        with pytest.raises(_Launched):
            pi.launch_owned(command, role=pi.SeatLaunchRole.EXECUTOR_TRUSTED,
                            profile=pi.SeatProfile(env=seat.env), env=seat.env, cwd=str(seat.out))


@pytest.mark.parametrize("kind", RECEIPTS)
def test_consumer_seat_admission_doctor(seat, kind):
    """The doctor verdict's own call, with its fixed argv. It is never a launch: a listing
    receipt admits as before, and a frozen-basis receipt, which carries no launch context
    there, refuses."""
    command = ["grok", "-p", "doctor"]
    _receipt(seat, command, kind)
    if kind == "frozen_measurement":
        assert pi.grok_tool_gate(command, seat.env)  # the provisional step holds
        with pytest.raises(pi._seat_jail.SeatSandboxRefused):
            pi.require_grok_admission(command, seat.env)
    else:
        assert pi.require_grok_admission(command, seat.env)


# ----------------------------------------------------------------- records (§3.1, §3.2)


def test_precedence_and_shadowed_reporting(seat, monkeypatch):
    command = pi.grok_runtime_forms()["review"]
    digest = pi._grok_argv_digest(command)
    surface = _seat_surface(seat)
    assert gts.frozen_surface(seat.digest, digest) is None
    _publish_host(surface)
    resolved = gts.frozen_surface(seat.digest, digest)
    assert (resolved.source, resolved.shadowed) == ("host_local", None)
    _catalog(monkeypatch, surfaces=[surface])  # the same route in both: nothing is shadowed
    resolved = gts.frozen_surface(seat.digest, digest)
    assert (resolved.source, resolved.shadowed) == ("catalog", None)
    _catalog(monkeypatch, surfaces=[{**surface, "measured_at": "2026-11-21T00:00:00Z"}])
    resolved = gts.frozen_surface(seat.digest, digest)
    assert (resolved.source, resolved.shadowed) == ("catalog", "host_local")
    # A catalog entry without this route leaves the host-local one in use.
    _catalog(monkeypatch, surfaces=[{**surface, "routes": surface["routes"][1:]}])
    assert gts.frozen_surface(seat.digest, digest).source == "host_local"
    _catalog(monkeypatch, surfaces=[], revoked=[seat.digest])
    assert gts.frozen_surface(seat.digest, digest) is None


def test_probe_tools_rows_name_the_basis_source_and_shadowing(seat, monkeypatch, capsys):
    from phase_loop_runtime import seat_window
    surface = _seat_surface(seat)
    _publish_host(surface)
    staged = [route for route in surface["routes"] if route["route"] == "staged"]
    _catalog(monkeypatch, surfaces=[{**surface, "routes": staged, "measured_at": "2026-11-21T00:00:00Z"}])
    runner = _runner()
    monkeypatch.setattr(pi, "run_provider", lambda argv, **kw: runner(argv, **kw))
    rc = seat_window.cli_main(SimpleNamespace(action="probe-tools", model=None, effort="high"))
    result = json.loads(capsys.readouterr().out)
    assert (rc, result["status"]) == (1, "candidate")  # the executor forms stay refused
    assert {row["route"]: row for row in result["routes"]} == {
        "execute": {"route": "execute", "passed": False, "basis": "none"},
        "workflow": {"route": "workflow", "passed": False, "basis": "none"},
        "review": {"route": "review", "passed": True, "basis": "frozen_measurement", "source": "host_local"},
        "sealed": {"route": "sealed", "passed": True, "basis": "frozen_measurement", "source": "host_local"},
        "staged": {"route": "staged", "passed": True, "basis": "frozen_measurement", "source": "catalog",
                   "shadowed": "host_local"},
    }


@pytest.mark.parametrize("route,passes", [("sealed", True), ("review", False), ("workflow", False)])
def test_an_observed_empty_surface(seat, route, passes):
    """§3.1 "Empty lists": valid evidence, which passes only for a form whose allow-list is
    itself empty; the nonempty rules are not edited."""
    command = pi.grok_runtime_forms()[route]
    _publish_host(_surface(seat.digest, [_route(route, command, tools=[])]))
    receipt = _probe(command)
    assert receipt["passed"] is passes
    assert pi.grok_tool_gate(command) is passes


def _valid_catalog():
    routes = [_route(route, pi.grok_runtime_forms()[route]) for route in SEAT_ROUTES]
    return {"schema": gts.CATALOG_SCHEMA, "revoked": ["e" * 64],
            "surfaces": [_surface("1" * 64, routes, context_digest="c" * 64)]}


def _first(document):
    return document["surfaces"][0]


@pytest.mark.parametrize("rule,mutate", [
    ("oversize", lambda d: _first(d).update(version="x" * (gts.CATALOG_MAX_BYTES + 1))),
    ("schema", lambda d: d.update(schema="grok_tool_surface_catalog.v2")),
    ("top_level_key", lambda d: d.update(extra=[])),
    ("surface_key", lambda d: _first(d).update(account="fixture")),
    ("route_key", lambda d: _first(d)["routes"][0].update(status="measured")),
    ("missing_key", lambda d: d.pop("revoked")),
    ("digest_case", lambda d: _first(d).update(help_sha256=_first(d)["help_sha256"].upper())),
    ("digest_length", lambda d: _first(d)["routes"][0].update(argv_digest="1" * 63)),
    ("revoked_digest", lambda d: d.update(revoked=["not-a-digest"])),
    ("tool_pattern", lambda d: _first(d)["routes"][0].update(tools=["read file"])),
    ("tool_unsorted", lambda d: _first(d)["routes"][0].update(tools=["read_file", "grep"])),
    ("tool_duplicate", lambda d: _first(d)["routes"][0].update(tools=["grep", "grep"])),
    ("context", lambda d: _first(d).update(context="grok_seat_context.v2")),
    ("duplicate_binary", lambda d: d["surfaces"].append(json.loads(json.dumps(_first(d))))),
    ("duplicate_route", lambda d: _first(d)["routes"].append(dict(_first(d)["routes"][0]))),
    ("revoked_and_surface", lambda d: d["revoked"].append(_first(d)["binary_sha256"])),
    ("measured_at", lambda d: _first(d).update(measured_at="2026-11-20 12:00:00")),
    ("type", lambda d: _first(d).update(routes={})),
])
def test_each_loader_rule_voids_the_catalog(seat, monkeypatch, rule, mutate):
    document = _valid_catalog()
    assert gts.parse_catalog(json.dumps(document).encode()).surfaces
    mutate(document)
    raw = json.dumps(document).encode()
    with pytest.raises(ValueError):
        gts.parse_catalog(raw)
    monkeypatch.setattr(gts, "_catalog_bytes", lambda: raw)
    assert gts.load_catalog() is None


@pytest.mark.parametrize("raw", [b"", b"{", b"[]", b'{"schema": "grok_tool_surface_catalog.v1", '
                                 b'"schema": "grok_tool_surface_catalog.v1", "revoked": [], "surfaces": []}'])
def test_unparseable_catalogs_are_void(monkeypatch, raw):
    monkeypatch.setattr(gts, "_catalog_bytes", lambda: raw)
    assert gts.load_catalog() is None


@pytest.mark.parametrize("change", ["mode", "symlink", "directory_mode", "schema", "binary", "key"])
def test_each_host_record_check_refuses(seat, change):
    from phase_loop_runtime import president_adapter as pa
    surface = _seat_surface(seat)
    path = _publish_host(surface)
    assert gts.load_host_record(seat.digest) == surface
    if change == "mode":
        path.chmod(0o644)
    elif change == "symlink":
        target = path.with_name("elsewhere.json")
        path.rename(target)
        path.symlink_to(target)
    elif change == "directory_mode":
        pa.private_record_root().chmod(0o755)
    elif change == "schema":
        record = json.loads(path.read_text())
        path.unlink()
        pa.write_private_record(path.name, {**record, "schema": "grok_tool_surface_measurement.v2"})
    elif change == "binary":
        _publish_host({**surface, "binary_sha256": "f" * 64})
        path.unlink()
        pa.private_record_root().joinpath(gts.host_record_name("f" * 64)).rename(path)
    elif change == "key":
        record = json.loads(path.read_text())
        path.unlink()
        pa.write_private_record(path.name, {**record, "grant": "fixture"})
    try:
        assert gts.load_host_record(seat.digest) is None
    finally:
        pa.private_record_root().chmod(0o700)


# ------------------------------------------------------------ the pinned context (§4.4)


def test_the_pinned_discovery_set():
    """The project paths grok 1.0.89 discovers that can add or reconfigure tools, derived
    offline from the documentation bundled in that binary (sha256 ``a3dface5…ba1f``, read
    with ``strings``; no execution beyond ``inspect``, below):

    - ``.grok/``: "The .grok/ Project Directory": ``config.toml`` (project MCP servers,
      plugins and permission rules), ``skills/``, ``plugins/``, ``agents/``, ``hooks/``,
      ``lsp.json``, ``rules/``, ``sandbox.toml``, ``workflows/``;
    - ``.agents/``: "Grok looks in four config directories, ``.grok/``, ``.agents/``,
      ``.claude/``, and ``.cursor/``" for skills and commands, from the cwd up to the repo root;
    - ``.claude/``: Claude Code compatibility, on by default: ``skills/``, ``commands/``,
      ``agents/``, ``plugins/``, ``rules/``, ``CLAUDE*.md``, and permissions and hooks from
      ``settings.json`` and ``settings.local.json``;
    - ``.cursor/``: Cursor compatibility, on by default: ``skills/``, ``commands/``,
      ``rules/``, ``mcp.json``, ``hooks.json``;
    - ``.mcp.json``: "MCP standard format, Project root (cwd to git root)".

    Not in the set: ``.grok-plugin/`` and ``.claude-plugin/`` are read only when a marketplace
    is added explicitly; ``.lsp.json`` only inside a trusted plugin.

    Rules files (contract §4.4). The bundled documentation describes ``AGENTS.md`` and
    ``CLAUDE.md`` only as project instructions ("Project rules are Markdown files that Grok
    reads and adds to its context"; ``.grok`` table: "AGENTS.md | Project instructions
    (system prompt)"). Checked offline on 1.0.89 with ``grok inspect --json`` under
    ``unshare -rn``, an empty HOME and no credential, folder trust ungated
    (``GROK_FOLDER_TRUST=0``) so the files load: an ``AGENTS.md``, a ``CLAUDE.md`` and a
    ``.claude/CLAUDE.md``, each carrying front matter that declares tools, MCP servers and
    hooks, an ``@./fixture-import.json`` line naming an MCP config, a JSON ``mcpServers``
    block and a TOML ``[mcp_servers.*]`` table, each appear only as one
    ``projectInstructions`` entry, with no MCP server, hook, skill, agent, plugin, permission
    or config layer. The controls, a ``.mcp.json`` and a ``.grok/config.toml`` holding the
    same server, each register it. So the rules files stay out of the set. The comparison of
    first-request tool definitions with and without each file needs the offline fixture
    upstream of §5.2, which lane L2a builds."""
    assert gts.DISCOVERY_PATHS == (".agents", ".claude", ".cursor", ".grok", ".mcp.json")
    assert {".grok", ".mcp.json", ".claude", ".cursor"} <= set(gts.DISCOVERY_PATHS)
    assert not {"AGENTS.md", "CLAUDE.md"} & set(gts.DISCOVERY_PATHS)


def test_the_context_digest_covers_every_condition(monkeypatch):
    monkeypatch.setattr(gts, "egress_allowlist_digest", lambda: ALLOWLIST)
    document = gts.context_document(ALLOWLIST)
    assert document == {
        "schema": "grok_seat_context.v1", "home": "/home/phase-loop-seat",
        "seat_config": {"path": ".grok/config.toml", "sha256": gts.SEAT_CONFIG_SHA256},
        "projected_paths": [".grok/agent_id", ".grok/auth.json", ".phase-loop-seat-egress-ca.pem"],
        "environment": {"allowed": sorted((*gts.ENVIRONMENT, "HTTPS_PROXY", "SSL_CERT_FILE")),
                        "forbidden_prefixes": ["GROK_", "XAI_"]},
        "managed_config": ["/etc/grok/managed_config.toml", "/etc/grok/requirements.toml"],
        "child_absent_policy": ["/etc/claude-code/managed-settings.json"],
        "discovery": list(gts.DISCOVERY_PATHS),
        "egress": {"allowlist_id": "grok-review", "content_digest": ALLOWLIST},
        "composition": gts.COMPOSITION,
    }
    before = gts.context_digest()
    for name, value in (("DISCOVERY_PATHS", (*gts.DISCOVERY_PATHS, ".vscode")),
                        ("MANAGED_CONFIG_PATHS", ()), ("CHILD_ABSENT_POLICY_PATHS", ()),
                        ("PROXY_ENVIRONMENT", ("HTTPS_PROXY",)),
                        ("PROXY_PROJECTED_PATHS", (".config/seat-egress/ca.crt",)),
                        ("SEAT_CONFIG_RELATIVE", ".config/grok/config.toml")):
        with monkeypatch.context() as patch:
            patch.setattr(gts, name, value)
            assert gts.context_digest() != before, name
    monkeypatch.setattr(gts, "egress_allowlist_digest", lambda: "b" * 64)
    assert gts.context_digest() != before


# ------------------------------------------------------- the seat config (erratum 8, item 1)

#: The config's bytes as the contract's erratum 8 prints them.
SEAT_CONFIG = b"""[model."grok-4.7"]
model = "grok-4.7"
name = "grok-4.7 (pinned local entry)"
base_url = "https://cli-chat-proxy.grok.com/v1"
api_backend = "chat_completions"

[[model."grok-4.7".reasoning_efforts]]
value = "low"
label = "Low Effort"

[[model."grok-4.7".reasoning_efforts]]
value = "medium"
label = "Medium Effort"

[[model."grok-4.7".reasoning_efforts]]
value = "high"
label = "High Effort"

[features]
remote_fetch = false
"""
SEAT_CONFIG_SHA256 = "2984e0c368943bb6c1627146e413995df12cca5820e782adffcb052a9b761780"
#: The parsed value of the fragment the offline observation of grok 1.0.92 ran with (the
#: engagement's review records, ``grok-offline-catalog-test/``). That file differs from the
#: pinned one by comments and table order only, so the two parse to this same value.
TESTED_VALUE = {
    "model": {"grok-4.7": {
        "model": "grok-4.7", "name": "grok-4.7 (pinned local entry)",
        "base_url": "https://cli-chat-proxy.grok.com/v1", "api_backend": "chat_completions",
        "reasoning_efforts": [{"value": "low", "label": "Low Effort"},
                              {"value": "medium", "label": "Medium Effort"},
                              {"value": "high", "label": "High Effort"}]}},
    "features": {"remote_fetch": False},
}
#: ``context_digest()`` on the shipped allow-list before erratum 8 added ``seat_config``.
CONTEXT_DIGEST_BEFORE_ERRATUM_8 = "3512f988bd7078d2339cc758a1e14ca9b15cb6160067bdd3fd5c33692739afd3"


def test_the_seat_config_is_the_pinned_bytes():
    data = gts.seat_config()
    assert data == SEAT_CONFIG and len(data) == 424
    assert sha256(data).hexdigest() == gts.SEAT_CONFIG_SHA256 == SEAT_CONFIG_SHA256
    assert tomllib.loads(data.decode("ascii")) == TESTED_VALUE
    assert gts.SEAT_CONFIG_RELATIVE == ".grok/config.toml"


def test_each_seat_config_field_comes_from_its_constant():
    """The table key and ``model`` are the measurement model, which is the board leg's;
    ``base_url`` is the inference host, and with the default backend names the one
    ``grok-review`` allow row; ``high`` is the measurement effort."""
    from phase_loop_runtime import seat_egress_proxy
    value = tomllib.loads(gts.seat_config().decode("ascii"))
    assert list(value) == ["model", "features"] and list(value["model"]) == [gts.MEASUREMENT_MODEL]
    entry = value["model"][gts.MEASUREMENT_MODEL]
    assert entry["model"] == gts.MEASUREMENT_MODEL == pi.DEFAULT_LEG_MODELS["grok"]
    base = urllib.parse.urlsplit(entry["base_url"])
    assert (base.scheme, base.netloc, base.path) == ("https", gts.INFERENCE_HOST, "/v1")
    assert entry["api_backend"] == gts.SEAT_CONFIG_API_BACKEND == "chat_completions"
    assert seat_egress_proxy.GROK_REVIEW_ALLOWLIST == gts.EGRESS_ALLOWLIST_ID
    rows = seat_egress_proxy.allowlist_ref(gts.EGRESS_ALLOWLIST_ID).request_set
    assert rows == ({"host": base.netloc, "port": 443, "method": "POST",
                     "path": base.path + "/chat/completions"},)
    efforts = [row["value"] for row in entry["reasoning_efforts"]]
    assert efforts == list(gts.SEAT_CONFIG_EFFORTS) == ["low", "medium", "high"]
    assert gts.MEASUREMENT_EFFORT == "high"
    assert value["features"] == {"remote_fetch": False}


@pytest.mark.parametrize("name,value", [
    ("MEASUREMENT_MODEL", "grok-4.6"), ("INFERENCE_HOST", "api.x.ai"),
    ("SEAT_CONFIG_API_BACKEND", "responses"), ("SEAT_CONFIG_EFFORTS", ("low", "high")),
    ("MEASUREMENT_EFFORT", "xhigh"), ("SEAT_CONFIG_SHA256", "0" * 64)])
def test_a_build_that_composes_other_bytes_has_no_seat_config(monkeypatch, name, value):
    """Each named constant feeds the bytes, and the digest pins them: a build whose constants
    moved without the pin composes no config and no descriptor."""
    monkeypatch.setattr(gts, name, value)
    with pytest.raises(gts._Refused):
        gts.seat_config()
    with pytest.raises(pi._seat_jail.SeatSandboxRefused) as refusal:
        gts.seat_config_descriptor()
    assert refusal.value.code == REFUSED


def test_the_config_descriptor_is_sealed_at_its_start():
    descriptor = _held(gts.seat_config_descriptor())
    assert os.pread(descriptor, 4096, 0) == SEAT_CONFIG
    assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0 and not os.get_inheritable(descriptor)
    assert fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) == gts._CONFIG_SEALS == (
        fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
    assert (gts._F_ADD_SEALS, gts._F_GET_SEALS) == (fcntl.F_ADD_SEALS, fcntl.F_GET_SEALS)
    for change in (lambda: os.pwrite(descriptor, b"#", 0), lambda: os.ftruncate(descriptor, 0),
                   lambda: os.ftruncate(descriptor, 4096)):
        with pytest.raises(OSError):
            change()
    assert os.pread(descriptor, 4096, 0) == SEAT_CONFIG


def test_the_context_digest_follows_the_config_bytes(monkeypatch):
    """``context_digest()`` moves when any config byte changes, and for erratum 8 by the
    ``seat_config`` field alone: without the field the document is the earlier one."""
    monkeypatch.setattr(gts, "egress_allowlist_digest", _SHIPPED_ALLOWLIST_DIGEST)
    before = gts.context_digest()
    document = gts.context_document(_SHIPPED_ALLOWLIST_DIGEST())
    assert document["seat_config"] == {"path": ".grok/config.toml", "sha256": SEAT_CONFIG_SHA256}
    del document["seat_config"]
    assert sha256(gts._canonical(document)).hexdigest() == CONTEXT_DIGEST_BEFORE_ERRATUM_8 != before
    seen = {before}
    for index in range(len(SEAT_CONFIG)):
        changed = bytearray(SEAT_CONFIG)
        changed[index] ^= 0x01
        with monkeypatch.context() as patch:
            patch.setattr(gts, "_seat_config_bytes", lambda changed=bytes(changed): changed)
            seen.add(gts.context_digest())
    assert len(seen) == len(SEAT_CONFIG) + 1  # every changed byte gives its own digest
    for other in (SEAT_CONFIG + b"\n", SEAT_CONFIG[:-1]):
        with monkeypatch.context() as patch:
            patch.setattr(gts, "_seat_config_bytes", lambda other=other: other)
            assert gts.context_digest() not in seen
    # The same bytes give the same digest, however they are composed, pinned or mounted.
    with monkeypatch.context() as patch:
        patch.setattr(gts, "_seat_config_bytes", lambda: bytes(SEAT_CONFIG))
        patch.setattr(gts, "SEAT_CONFIG_SHA256", "0" * 64)
        patch.setattr(gts, "SEAT_CONFIG_MODE", "0400")
        assert gts.context_digest() == before
    assert gts.context_digest() == before


# ----------------------------------------- the seat config in the home rule (erratum 8, item 1)

def _ca_proxy(root):
    """A stand-in ``grok-review`` proxy whose CA file ``seat_profile`` can project."""
    der = b"phase-loop fixture CA"
    certificate = root / "egress-ca.crt"
    certificate.write_text(ssl.DER_cert_to_PEM_cert(der), encoding="ascii")
    return _proxy(ca_cert=certificate, ca_sha256=sha256(der).hexdigest(),
                  proxy_url="http://srt:fixture-proxy-session-token@127.0.0.1:3128")


def _swap_config(profile, *replacement, pass_fds=()):
    """``profile`` with its composed seat config mount replaced by ``replacement``."""
    arguments = list(profile.mount_args)
    end = arguments.index(CONFIG_PATH) + 1
    start = end - len(gts.seat_config_projection(0))
    assert tuple(arguments[start:end]) == gts.seat_config_projection(int(arguments[end - 2]))
    return replace(profile, mount_args=(*arguments[:start], *replacement, *arguments[end:]),
                   pass_fds=(*profile.pass_fds, *pass_fds))


def _config_change(case, profile, root):
    """One change to a profile that carries the real seat config; each must refuse alone."""
    home = gts.PRIVATE_HOME
    host = root / "host-config.toml"
    host.write_bytes(SEAT_CONFIG)
    one_byte = bytearray(SEAT_CONFIG)
    one_byte[SEAT_CONFIG.index(b"false")] ^= 0x01

    def swapped(descriptor):
        return _swap_config(profile, *gts.seat_config_projection(descriptor),
                            pass_fds=(descriptor,))

    def added(*mount, pass_fds=()):
        return replace(profile, mount_args=(*profile.mount_args, *mount),
                       pass_fds=(*profile.pass_fds, *pass_fds))

    def data_file(relative, data=b""):
        descriptor = _memfd(data)
        return added("--perms", "0600", "--file", str(descriptor), home + "/" + relative,
                     pass_fds=(descriptor,))

    def second_file():
        descriptor = _memfd(SEAT_CONFIG)
        return added(*gts.seat_config_projection(descriptor), pass_fds=(descriptor,))

    def other_mode():
        descriptor = _memfd(SEAT_CONFIG)
        words = list(gts.seat_config_projection(descriptor))
        words[1] = "0644" if words[1] != "0644" else "0600"
        return _swap_config(profile, *words, pass_fds=(descriptor,))

    def closed():
        descriptor = os.memfd_create("fixture-closed", os.MFD_CLOEXEC)
        os.close(descriptor)
        return swapped(descriptor)

    return {
        "missing": lambda: _swap_config(profile),
        "one_byte_changed": lambda: swapped(_memfd(bytes(one_byte))),
        "one_byte_more": lambda: swapped(_memfd(SEAT_CONFIG + b"\n")),
        "one_byte_fewer": lambda: swapped(_memfd(SEAT_CONFIG[:-1])),
        "empty": lambda: swapped(_memfd(b"")),
        "second_file": second_file,
        "unsealed": lambda: swapped(_memfd(SEAT_CONFIG, seals=0)),
        "write_seal_absent": lambda: swapped(_memfd(
            SEAT_CONFIG, seals=gts._CONFIG_SEALS & ~fcntl.F_SEAL_WRITE)),
        "regular_file": lambda: swapped(_held(os.open(host, os.O_RDONLY | os.O_CLOEXEC))),
        "consumed": lambda: swapped(_memfd(SEAT_CONFIG, offset=len(SEAT_CONFIG))),
        "not_passed": lambda: _swap_config(
            profile, *gts.seat_config_projection(_memfd(SEAT_CONFIG))),
        "closed": closed,
        "other_mode": other_mode,
        "host_bind": lambda: _swap_config(profile, "--bind", str(host), CONFIG_PATH),
        "host_readonly_bind": lambda: _swap_config(profile, "--ro-bind", str(host), CONFIG_PATH),
        "link": lambda: _swap_config(profile, "--symlink", str(host), CONFIG_PATH),
        "bind_over_it": lambda: added("--ro-bind", str(host), CONFIG_PATH),
        "managed_config": lambda: data_file(".grok/managed_config.toml"),
        "requirements": lambda: data_file(".grok/requirements.toml"),
        "second_config_elsewhere": lambda: data_file(".config/grok/config.toml", SEAT_CONFIG),
    }[case]()


CONFIG_CHANGES = ("missing", "one_byte_changed", "one_byte_more", "one_byte_fewer", "empty",
                  "second_file", "unsealed", "write_seal_absent", "regular_file", "consumed",
                  "not_passed", "closed", "other_mode", "host_bind", "host_readonly_bind", "link",
                  "bind_over_it", "managed_config", "requirements", "second_config_elsewhere")


@pytest.mark.parametrize("case", CONFIG_CHANGES)
def test_each_seat_config_condition_refuses_alone_at_the_final_check(seat, launches, case):
    """A missing, second, differing, unsealed, consumed or host-backed config, and any other
    file added to the home, each refuse the launch with the one typed code; nothing launches."""
    command = _composed(seat)
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (owned, profile):
        stock = _projected(profile, _proxy())
        marked = _verify(seat, stock)
        assert gts.is_issued(marked.grok_launch_context)
        changed = _config_change(case, stock, seat.root)
        with pytest.raises(pi._seat_jail.SeatSandboxRefused) as refusal:
            _verify(seat, changed)
        assert refusal.value.code == REFUSED
        # The mark the unchanged profile earned does not carry over to the changed one.
        with pytest.raises(pi._seat_jail.SeatSandboxRefused):
            pi.launch_owned(owned, role=pi.SeatLaunchRole.PROVIDER_REVIEW, cwd=str(seat.out),
                            env=seat.env, profile=replace(
                                changed, grok_launch_context=marked.grok_launch_context))
    assert launches == []


def test_a_frozen_basis_profile_composed_without_the_proxy_refuses(seat):
    """Composition without the ``grok-review`` proxy carries neither the projection nor the
    config; the proxy projection without the config refuses too."""
    command = _composed(seat)
    with _egress(), pi._seat_command_profile(command, env=seat.env, cwd=seat.out) as (_owned, profile):
        assert CONFIG_PATH not in profile.mount_args
        for composed in (profile, _projected(profile, _proxy(), seat_config=False)):
            with pytest.raises(pi._seat_jail.SeatSandboxRefused) as refusal:
                gts.verify_launch_context(composed, env=seat.env, cwd=seat.out,
                                          role=pi.SeatLaunchRole.PROVIDER_REVIEW, proxy=_proxy())
            assert refusal.value.code == REFUSED
        assert gts.is_issued(_verify(seat, profile).grok_launch_context)


@contextlib.contextmanager
def _measurement(seat, monkeypatch):
    """A measurement's own composition (contract §5.1) and its context check:
    ``(profile, check)``."""
    monkeypatch.setattr(gts, "bridged_to", lambda prefix, proxy: True)
    sessions = seat.root / "sessions"
    sessions.mkdir(mode=0o700)
    proxy = _ca_proxy(seat.root)
    command = _form("review", seat.out)
    with _egress(), pi.seat_profile(
            harness="grok", executable=str(seat.binary), env=seat.env, cwd=seat.out,
            role=pi.SeatLaunchRole.PROVIDER_REVIEW, egress_proxy=proxy,
            grok_sessions=str(sessions)) as (_provider, profile):
        yield profile, lambda composed: gts.verify_measurement_context(
            composed, cwd=seat.out, command=command, proxy=proxy, sessions=str(sessions))


@pytest.mark.parametrize("case", CONFIG_CHANGES)
def test_each_seat_config_condition_refuses_alone_at_the_measurement_check(seat, monkeypatch,
                                                                           case):
    with _measurement(seat, monkeypatch) as (profile, check):
        assert check(profile) == gts.context_digest()
        with pytest.raises(pi._seat_jail.SeatSandboxRefused) as refusal:
            check(_config_change(case, profile, seat.root))
        assert refusal.value.code == REFUSED


def test_the_check_leaves_the_descriptor_at_its_start(seat, monkeypatch):
    """The bytes are read before the launch without consuming them: the launch that follows
    the check still copies the whole config."""
    with _measurement(seat, monkeypatch) as (profile, check):
        arguments = list(profile.mount_args)
        descriptor = int(arguments[arguments.index(CONFIG_PATH) - 1])
        for _ in range(2):
            check(profile)
            assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        assert os.read(descriptor, 4096) == SEAT_CONFIG


def test_a_config_whose_pin_moved_after_composition_refuses(seat, monkeypatch):
    with _measurement(seat, monkeypatch) as (profile, check):
        check(profile)
        monkeypatch.setattr(gts, "SEAT_CONFIG_SHA256", "0" * 64)
        with pytest.raises(pi._seat_jail.SeatSandboxRefused):
            check(profile)


# --------------------------------- where the seat config is composed (erratum 8, item 1)

def _mount_words(arguments):
    """Mount arguments with each descriptor masked."""
    words = [str(word) for word in arguments]
    for index, word in enumerate(words[:-1]):
        if word in {"--file", "--ro-bind-data"}:
            words[index + 1] = "<fd>"
    return words


def test_the_config_is_composed_only_with_the_grok_review_proxy(seat):
    """With the proxy the profile gains the config, from the sealed descriptor, beside the
    proxy projection; the same profile without the proxy is the one composed before."""
    home = gts.PRIVATE_HOME
    compose = dict(harness="grok", executable=str(seat.binary), env=seat.env, cwd=seat.out)
    with pi.seat_profile(**compose) as (provider, plain):
        assert _mount_words(plain.mount_args) == [
            "--tmpfs", home, "--perms", "0700", "--dir", home + "/.config",
            "--perms", "0700", "--dir", home + "/.cache",
            "--perms", "0700", "--dir", home + "/.local",
            "--perms", "0700", "--dir", home + "/.local/share",
            "--perms", "0700", "--dir", home + "/.grok",
            "--perms", "0600", "--file", "<fd>", home + "/.grok/auth.json",
            "--perms", "0600", "--file", "<fd>", home + "/.grok/agent_id",
            "--ro-bind", os.path.realpath(seat.binary), provider]
        assert len(plain.pass_fds) == 2
        with pi.seat_profile(**compose, egress_proxy=_ca_proxy(seat.root)) as (_provider, composed):
            arguments = list(composed.mount_args)
            descriptor = int(arguments[arguments.index(CONFIG_PATH) - 1])
            projection = gts.seat_config_projection(descriptor)
            start = arguments.index(CONFIG_PATH) + 1 - len(projection)
            assert tuple(arguments[start:start + len(projection)]) == projection
            assert descriptor in composed.pass_fds and len(composed.pass_fds) == 4
            assert os.pread(descriptor, 4096, 0) == SEAT_CONFIG
            assert fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) == gts._CONFIG_SEALS
            ca = ["--perms", "0444", "--ro-bind-data", "<fd>", home + "/" + gts.PROXY_PROJECTED_PATHS[0]]
            rest = _mount_words((*arguments[:start], *arguments[start + len(projection):]))
            index = next(i for i in range(len(rest)) if rest[i:i + len(ca)] == ca)
            assert rest[:index] + rest[index + len(ca):] == _mount_words(plain.mount_args)
            assert composed.evidence.keys() - plain.evidence.keys() == {
                "seat_egress_allowlist_id", "seat_egress_allowlist_digest", "seat_egress_ca_sha256"}
        with pytest.raises(OSError):
            os.fstat(descriptor)  # closed with its profile


@pytest.mark.parametrize("route,kind", [
    *((route, "list_tools") for route in sorted(pi.grok_runtime_forms())),
    *((route, "frozen_measurement") for route in SEAT_ROUTES)])
@pytest.mark.parametrize("role", [pi.SeatLaunchRole.PROVIDER_REVIEW, pi.SeatLaunchRole.PROVIDER_ADMIN])
def test_no_route_without_the_proxy_carries_the_config(seat, route, kind, role):
    """Every grok form, on a listing receipt or a frozen-basis one, composed as a board or an
    admin launch composes it with no ``grok-review`` proxy, has no config in its home."""
    command = _form(route, seat.tree)
    _receipt(seat, command, kind)
    with pi._seat_command_profile(command, env=seat.env, cwd=seat.out, role=role) as (_owned, profile):
        assert not [word for word in profile.mount_args if "config.toml" in str(word)]
        assert len(profile.pass_fds) == 2  # the two credential files, and no third descriptor


@pytest.mark.parametrize("harness,files", [
    ("codex", {".codex/auth.json": '{"tokens": {"access_token": "fixture-access-token-0002", '
                                   '"id_token": "fixture-id-token-0002", "refresh_token": "r"}}'}),
    ("opencode", {".local/share/opencode/auth.json": '{"p": {"access": "fixture-access-token-0003"}}'}),
])
def test_another_harness_never_carries_the_grok_config(seat, harness, files):
    for relative, body in files.items():
        (seat.home / relative).parent.mkdir(parents=True, exist_ok=True)
        (seat.home / relative).write_text(body)
        (seat.home / relative).chmod(0o600)
    compose = dict(harness=harness, executable=str(seat.binary), env=seat.env, cwd=seat.out)
    with pi.seat_profile(**compose) as (_provider, profile):
        assert not [word for word in profile.mount_args
                    if str(word).startswith(gts.PRIVATE_HOME + "/.grok")]
    with pytest.raises(ValueError):
        with pi.seat_profile(**compose, egress_proxy=_ca_proxy(seat.root)):
            pytest.fail("a profile of another harness took the grok-review projection")


# ------------------------------------------------------------------ catalog parity (§3.3)

REPO = Path(__file__).resolve().parents[2]
_FULL_CONTEXT = ("binary_sha256", "version_sha256", "help_sha256", "model", "effort", "context",
                 "context_digest")


def _parity_failures(catalog, measurements):
    failures = []
    for binary, surface in catalog.surfaces.items():
        matches = [aggregate for aggregate in measurements
                   if all(aggregate.get(key) == surface[key] for key in _FULL_CONTEXT)]
        if len(matches) != 1:
            failures.append(binary)
            continue
        routes = {route.get("argv_digest"): route for route in matches[0].get("routes", ())}
        for route in surface["routes"]:
            evidence = routes.get(route["argv_digest"])
            if (evidence is None or evidence.get("status") != "measured" or evidence.get("eligible") is not True
                    or evidence.get("tools") != route["tools"]
                    or evidence.get("definitions_sha256") != route["definitions_sha256"]):
                failures.append(binary + ":" + route["route"])
    return failures


def test_the_shipped_catalog_has_evidence_on_the_full_context():
    catalog = gts.load_catalog()
    assert catalog is not None
    measurements = []
    if catalog.surfaces:
        evidence = json.loads((REPO / "plans/evidence/seat-grok/tool-surface.json").read_text())
        assert evidence["schema"] == "grok_tool_surface_evidence_set.v1"
        measurements = evidence["measurements"]
    assert _parity_failures(catalog, measurements) == []
    # A catalog entry with no such evidence fails.
    sample = gts.parse_catalog(json.dumps(_valid_catalog()).encode())
    surface = next(iter(sample.surfaces.values()))
    assert _parity_failures(sample, []) == [surface["binary_sha256"]]
    aggregate = {**{key: surface[key] for key in _FULL_CONTEXT}, "routes": [
        {**route, "status": "measured", "eligible": True} for route in surface["routes"]]}
    assert _parity_failures(sample, [aggregate]) == []
    aggregate["routes"][0]["eligible"] = False
    assert _parity_failures(sample, [aggregate]) == [surface["binary_sha256"] + ":review"]
