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
import json
import os
import subprocess
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


def _projected(profile, proxy):
    """The ``grok-review`` proxy projection lane L2a's ``seat_profile(egress_proxy=...)`` adds
    (the read-only CA file and the two variables), on a profile composed without it."""
    ca = gts.PRIVATE_HOME + "/" + gts.PROXY_PROJECTED_PATHS[0]
    if ca in profile.mount_args:
        return profile
    url = getattr(proxy, "proxy_url", "http://fixture")
    return replace(profile, mount_args=(*profile.mount_args, "--perms", "0444", "--ro-bind-data", "9", ca),
                   env={**profile.env, "HTTPS_PROXY": url, "SSL_CERT_FILE": ca})


def _verify(seat, profile, **overrides):
    options = dict(env=seat.env, cwd=seat.out, role=pi.SeatLaunchRole.PROVIDER_REVIEW, proxy=_proxy())
    options.update(overrides)
    return gts.verify_launch_context(_projected(profile, options["proxy"]), **options)


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
            "home_file": lambda: replace(profile, mount_args=(*mounts, "--file", "9", home + "/.grok/config.toml")),
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
                        ("PROXY_PROJECTED_PATHS", (".config/seat-egress/ca.crt",))):
        with monkeypatch.context() as patch:
            patch.setattr(gts, name, value)
            assert gts.context_digest() != before, name
    monkeypatch.setattr(gts, "egress_allowlist_digest", lambda: "b" * 64)
    assert gts.context_digest() != before


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
