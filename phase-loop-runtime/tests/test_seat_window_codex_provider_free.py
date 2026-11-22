"""K-1 SL-6.2: assumption A-C1, provider-free, against the real pinned Codex binary.

K1-T6 (start gate K1-G5 for SL-6.3) and K1-T7 of contract r4 §15, for §10.B's A-C1:

* K1-T6. :data:`EXPECTED_CODEX_IMAGE` is the reviewed literal: the native image of the
  pinned CLI version, named by version and sha256, with its source. The digest compared is
  the one of the binary actually launched, read from the spawn evidence: the host file
  bound at the jail's runtime destination in the spawned argv, hashed at spawn time. The
  test's own on-disk pin is never what is compared.
* K1-T7. The real ``_prepare_jailed_codex`` and production auth path run with an isolated
  fixture ``HOME`` and ``CODEX_HOME`` and a synthetic login only. A decoy home with a
  planted credential is the process's own ``HOME`` and ``CODEX_HOME``; an audit hook fails
  the test on any lookup under it (or under the account's real ``.codex``), its directory
  is unreadable to children, and the bearer the loopback upstream receives must be the
  synthetic one. The proxy is the production ``codex`` allowlist, deny-by-default, with no
  upstream but the loopback responder; the CLI runs the production argv with no provider or
  config override.

Opt-in: the live cases need ``PHASE_LOOP_REQUIRE_LIVE_JAIL=1`` on a jail-capable host.
Under the opt-in every missing prerequisite and every skip fails. Without it the live cases
are skipped and A-C1 is NOT proven; that is the hosted-CI posture, never a gate's.
"""

from __future__ import annotations

import base64
import contextlib
import functools
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import stat
import sys
import time
from types import MappingProxyType, SimpleNamespace

import pytest

from test_seat_egress_allowlist_codex import (  # noqa: F401 - requested after the jail gate
    codex_front as _codex_front,
)

#: K1-T6's reviewed literal. The source is the CLI's own Linux x64 platform release of the
#: pinned version (the version every CODEX measurement names), read from an installed copy
#: of that release without running it. The npm tarball line is the registry's own digest
#: of the archive the member came from.
EXPECTED_CODEX_IMAGE = MappingProxyType({
    "cli_version": "0.167.0",
    "target": "x86_64-unknown-linux-musl",
    "member": "vendor/x86_64-unknown-linux-musl/bin/codex",
    "release": "npm @openai/codex@0.167.0-linux-x64",
    "release_tarball_sha512":
        "FNc7danfUng9Sp6w+Fh7kofNHHZpA6VMyNKWsWrS3OwHly69gywTWeiuwrUPXpJSho8Df4xqRsHfHRPzj7zYQg==",
    "sha256": "cdcb45aaa01d0f14e298985e09465aebccd47f64ecd298aea44814af7b62bbda",
})

OPT_IN = "PHASE_LOOP_REQUIRE_LIVE_JAIL"
TOKEN_HOST, TOKEN_PATH = "auth.openai.com", "/oauth/token"
MODEL_HOST, MODEL_PATH = "chatgpt.com", "/backend-api/codex/responses"
_BIND_FLAGS = frozenset({"--ro-bind", "--bind", "--ro-bind-try", "--bind-try"})
EVIDENCE = Path(__file__).resolve().parents[2] / "plans" / "evidence" / "seat-codex"


def _opted_in() -> bool:
    return os.environ.get(OPT_IN) == "1"


def _no_skip(function):
    """K1-T7: under the opt-in a skip is a failure (a gate run never passes by skipping)."""
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except pytest.skip.Exception as exc:
            if _opted_in():
                pytest.fail(f"A-C1 under {OPT_IN}=1 may not skip: {exc}")
            raise
    return wrapper


def _require_live_jail() -> None:
    if not _opted_in():
        pytest.skip(f"A-C1 not proven by this run: set {OPT_IN}=1 on a jail-capable host")
    from test_seat_egress_allowlist_codex import _live_jail_or_fail
    _live_jail_or_fail()  # missing prerequisites fail, they never skip


# --------------------------------------------------------------------------------------
# K1-T6: the launched image, from the spawn evidence.
# --------------------------------------------------------------------------------------

def _file_sha256(path: str) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("the launched image is not a regular file")
        digest = hashlib.sha256()
        while chunk := os.read(fd, 1 << 20):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(fd)


def launched_image(argv) -> tuple[str, str]:
    """``(host source, sha256)`` of the Codex image a spawned argv launches: the one host
    file bound at the runtime's ``bin/codex`` destination. Called at spawn time, before the
    child exists, so the digest is the launched bytes'."""
    from phase_loop_runtime.seat_codex_runtime import CODEX_RUNTIME_DESTINATIONS
    argv = [str(arg) for arg in argv]
    sources = [argv[i + 1] for i in range(len(argv) - 2)
               if argv[i] in _BIND_FLAGS and argv[i + 2] == CODEX_RUNTIME_DESTINATIONS[0]]
    if len(sources) != 1:
        raise ValueError("the spawn evidence binds no single Codex image")
    return sources[0], _file_sha256(sources[0])


def assert_pinned_image(evidence) -> None:
    """K1-T6: every launched image is the reviewed literal; anything else fails hard."""
    if not evidence:
        pytest.fail("K1-T6: no spawn evidence of a launched Codex image")
    for source, digest in evidence:
        if digest != EXPECTED_CODEX_IMAGE["sha256"]:
            pytest.fail(f"K1-T6: the launched image {source} is {digest}, not the reviewed "
                        f"{EXPECTED_CODEX_IMAGE['cli_version']} image "
                        f"{EXPECTED_CODEX_IMAGE['sha256']}")


class SpawnEvidence:
    """Wraps the seat spawn boundary (``seat_resource_caps.capped_popen``) and hashes the
    Codex image each provider start binds, before the start."""

    def __init__(self, monkeypatch):
        from phase_loop_runtime import seat_resource_caps
        self.images: list[tuple[str, str]] = []
        self.host_runs: list[tuple[str, str]] = []
        inner = seat_resource_caps.capped_popen

        def capped(command, **kwargs):
            if any(str(arg).endswith("/codex-runtime/bin/codex") for arg in command):
                self.images.append(launched_image(command))
            return inner(command, **kwargs)
        monkeypatch.setattr(seat_resource_caps, "capped_popen", capped)
        from phase_loop_runtime import panel_invoker as pi
        run_provider = pi.run_provider

        def host_run(argv, *args, **kwargs):  # the admission gate's host-side starts
            self.host_runs.append((str(argv[0]), _file_sha256(str(argv[0]))))
            return run_provider(argv, *args, **kwargs)
        monkeypatch.setattr(pi, "run_provider", host_run)


def test_k1_t6_the_literal_is_a_reviewed_version_and_digest():
    image = EXPECTED_CODEX_IMAGE
    assert len(image["sha256"]) == 64 and set(image["sha256"]) <= set("0123456789abcdef")
    assert image["member"].endswith(image["target"] + "/bin/codex")
    assert base64.b64decode(image["release_tarball_sha512"], validate=True)
    # The pinned version is the one every CODEX measurement names.
    scope = EVIDENCE / "credential-scope.json"
    if scope.is_file():
        assert json.loads(scope.read_text())["codex_cli_version"] == image["cli_version"]


def test_k1_t6_the_digest_comes_from_the_spawned_bind_not_the_pin(tmp_path):
    from phase_loop_runtime.seat_codex_runtime import CODEX_RUNTIME_DESTINATIONS
    image = tmp_path / "codex"
    image.write_bytes(b"not the pinned image")
    argv = ["bwrap", "--ro-bind", str(image), CODEX_RUNTIME_DESTINATIONS[0],
            "--", CODEX_RUNTIME_DESTINATIONS[0], "exec"]
    # Other binds in the same argv are not the image.
    argv[1:1] = ["--ro-bind", "/etc/hosts", "/etc/hosts", "--ro-bind", str(tmp_path),
                 "/seat/home"]
    source, digest = launched_image(argv)
    assert source == str(image) and digest == hashlib.sha256(image.read_bytes()).hexdigest()
    # A launched image whose actual digest differs fails hard, whatever the pin says.
    with pytest.raises(pytest.fail.Exception, match="K1-T6"):
        assert_pinned_image([(source, digest)])
    with pytest.raises(pytest.fail.Exception, match="no spawn evidence"):
        assert_pinned_image([])
    for bad in (argv[:1], [*argv, "--ro-bind", str(image), CODEX_RUNTIME_DESTINATIONS[0]]):
        with pytest.raises(ValueError):
            launched_image(bad)


# --------------------------------------------------------------------------------------
# K1-T7: the fixture is the only credential and config source.
# --------------------------------------------------------------------------------------

_GUARD: dict[str, object] = {"roots": (), "hits": []}
_HOOKED = False


def _audit(event, args):
    roots = _GUARD["roots"]
    if not roots or event not in {"open", "os.listdir", "os.scandir", "os.chdir"}:
        return
    if not args:
        return
    path = args[0]
    if isinstance(path, int) or path is None:
        return
    try:
        text = os.fsdecode(path)
    except (TypeError, ValueError):
        return
    # The audit event carries no ``dir_fd``: a relative name is read against the cwd.
    absolute = os.path.normpath(os.path.join(os.getcwd(), text)) if not text.startswith("/") \
        else os.path.normpath(text)
    if any(absolute == root or absolute.startswith(root + os.sep) for root in roots):
        _GUARD["hits"].append((event, absolute))


@contextlib.contextmanager
def decoy_guard(*roots: Path):
    """Record every open or listing under ``roots`` (audit hooks cannot be removed, so one
    process-wide hook is armed only inside this block)."""
    global _HOOKED
    if not _HOOKED:
        sys.addaudithook(_audit)
        _HOOKED = True
    _GUARD["roots"] = tuple(os.path.normpath(str(root)) for root in roots)
    _GUARD["hits"] = []
    try:
        yield _GUARD["hits"]
    finally:
        _GUARD["roots"] = ()


def _part(value: dict) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def synthetic_login(account: str) -> dict:
    """A subscription-shaped login whose token values are assembled at run time, unsigned,
    inside the scope baseline the host checks. None is a credential."""
    from phase_loop_runtime import seat_codex_credential as cred
    expires = int(time.time()) + 3600
    auth = {"chatgpt_plan_type": "pro", "chatgpt_account_id": account}
    claims = {"exp": expires, "scp": sorted(cred.CODEX_SCOPE_CEILING),
              "https://api.openai.com/auth": auth}

    def token(body):
        return ".".join((_part({"alg": "none", "typ": "JWT"}), _part(body),
                         secrets.token_urlsafe(12)))
    return {
        "auth_mode": "chatgpt", "OPENAI_API_KEY": None,
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tokens": {"id_token": token({**claims, "email": "fixture@example.invalid"}),
                   "access_token": token(claims), "refresh_token": "", "account_id": account},
    }


def plant_decoy(root: Path, monkeypatch) -> dict:
    """A decoy home with a planted credential and config, made the process's own ``HOME``
    and ``CODEX_HOME``; its ``.codex`` is unreadable to every child once planted."""
    codex = root / ".codex"
    codex.mkdir(parents=True, mode=0o700)
    login = synthetic_login("acct-decoy-" + secrets.token_hex(4))
    (codex / "auth.json").write_text(json.dumps(login))
    (codex / "config.toml").write_text('model_provider = "decoy"\n')
    for path in codex.iterdir():
        path.chmod(0o600)
    # The proxy's own install (srt, its CA) is found through the data home, which defaults to
    # ``$HOME``; it is not a Codex lookup, so it stays where it was before the decoy.
    from phase_loop_runtime import seat_egress_proxy
    monkeypatch.setenv("XDG_DATA_HOME", str(seat_egress_proxy._data_home()))
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    codex.chmod(0o000)
    return {"root": root, "codex": codex, "bearer": login["tokens"]["access_token"]}


def forbidden_roots(decoy: dict) -> tuple[Path, ...]:
    real = Path(pwd.getpwuid(os.geteuid()).pw_dir) / ".codex"
    return (decoy["codex"], real)


def test_k1_t7_the_decoy_guard_sees_a_planted_read(tmp_path, monkeypatch):
    """The isolation assertion is not vacuous: a read of the decoy is recorded."""
    decoy = plant_decoy(tmp_path / "decoy", monkeypatch)
    decoy["codex"].chmod(0o700)
    from phase_loop_runtime import seat_codex_credential as cred
    with decoy_guard(*forbidden_roots(decoy)) as hits:
        cred.read_auth()  # the ambient lookup: HOME and CODEX_HOME are the decoy's
    assert any(path.startswith(str(decoy["codex"])) for _event, path in hits), hits
    with decoy_guard(*forbidden_roots(decoy)) as hits:
        fixture = tmp_path / "fixture" / ".codex"
        fixture.mkdir(parents=True)
        auth = fixture / "auth.json"
        auth.write_text(json.dumps(synthetic_login("acct-fixture")))
        auth.chmod(0o600)
        cred.read_auth({"HOME": str(fixture.parent), "CODEX_HOME": str(fixture)})
    assert hits == []


@pytest.mark.parametrize("opt_in", [None, "0"])
def test_k1_t7_opting_out_skips_before_any_host_probe(monkeypatch, opt_in):
    from phase_loop_runtime import sandbox_egress, seat_egress_proxy, seat_uid
    if opt_in is None:
        monkeypatch.delenv(OPT_IN, raising=False)
    else:
        monkeypatch.setenv(OPT_IN, opt_in)

    def unexpected(*args, **kwargs):
        pytest.fail("an opted-out A-C1 run reached host or proxy setup")
    for module, name in ((seat_uid, "seat_uid_available"),
                         (sandbox_egress, "egress_isolation_available"),
                         (seat_egress_proxy, "unavailable_reason")):
        monkeypatch.setattr(module, name, unexpected)
    with pytest.raises(pytest.skip.Exception, match="A-C1 not proven"):
        _require_live_jail()


def test_k1_t7_under_the_opt_in_missing_prerequisites_and_skips_fail(monkeypatch):
    from phase_loop_runtime import sandbox_egress, seat_egress_proxy, seat_uid
    monkeypatch.setenv(OPT_IN, "1")
    monkeypatch.setattr(seat_uid, "seat_uid_available", lambda: False)
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: False)
    monkeypatch.setattr(seat_egress_proxy, "unavailable_reason", lambda: "fixture missing srt")

    @_no_skip
    def skipping():
        pytest.skip("anything")
    for call, expected in ((_require_live_jail, "live jail unavailable"),
                           (skipping, "may not skip")):
        # A skip escaping here would itself pass a gate run, so it is caught and failed.
        try:
            call()
        except pytest.fail.Exception as exc:
            assert expected in str(exc)
        except pytest.skip.Exception:
            pytest.fail(f"under {OPT_IN}=1 {call.__name__} skipped instead of failing")
        else:
            pytest.fail(f"under {OPT_IN}=1 {call.__name__} neither failed nor skipped")


# --------------------------------------------------------------------------------------
# A-C1: the live cases.
# --------------------------------------------------------------------------------------

class _BearerRecorder:
    """Mixin for the loopback responder: keeps the bearer each request presented."""

    def _drain_body(self, tls, headers, rest):
        with self._lock:
            self.bearers.append(headers.get("authorization", ""))
        return super()._drain_body(tls, headers, rest)


@pytest.fixture
def codex_upstream(request):
    """The provider-free loopback harness of ``test_seat_codex_provider_free``: port-443
    dials go to a local responder that trusts only its own CA. Requested only after the
    jail gate, so an opted-out run probes nothing."""
    _require_live_jail()
    try:
        return request.getfixturevalue("_codex_front")
    except pytest.skip.Exception as exc:
        pytest.fail(f"A-C1 under {OPT_IN}=1 may not skip: {exc}")


def _native_subject():
    from phase_loop_runtime import seat_subject
    native = os.environ.get("PHASE_LOOP_CODEX_FIXTURE_NATIVE")
    if not native:
        pytest.fail("A-C1 needs PHASE_LOOP_CODEX_FIXTURE_NATIVE: the pinned native image")
    subject = seat_subject.SeatSubject("codex", "standalone", Path(native).resolve(), None, None)
    assert subject.subject_path is not None and subject.subject_path.is_file()
    return subject


def _stage(tmp_path):
    from phase_loop_runtime import seat_jail
    review = tmp_path / "review"
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    (tree / "window-read.txt").write_text("A-C1 fixture tree\n")
    fd = seat_jail.open_dir_nofollow(tree)
    try:
        digest = seat_jail.tree_manifest_sha256_at(fd)
    finally:
        os.close(fd)
    return review, type("Authorization", (), {"staged_tree_sha256": digest})()


def _redact(text: str, login: dict) -> str:
    """Synthetic values only, but none is kept verbatim in the evidence."""
    text = (text or "")[:8000]
    for value in (*login["tokens"].values(),):
        if isinstance(value, str) and len(value) > 8:
            text = text.replace(value, "<synthetic>")
    return text


def _write_evidence(case: str, document: dict) -> None:
    """When ``PHASE_LOOP_A_C1_EVIDENCE_DIR`` names a private (0700, own) directory, keep
    this case's evidence there as a 0600 file. Only an opt-in run writes it."""
    directory = os.environ.get("PHASE_LOOP_A_C1_EVIDENCE_DIR")
    if not directory:
        return
    info = os.stat(directory)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        pytest.fail("the A-C1 evidence directory must be private")
    document = {**document, "opt_in": os.environ.get(OPT_IN),
                "native": os.environ.get("PHASE_LOOP_CODEX_FIXTURE_NATIVE")}
    fd = os.open(os.path.join(directory, f"a-c1-{case}.json"),
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)


def _a_c1(tmp_path, monkeypatch, codex_upstream, *, case):
    """One A-C1 launch through the real prepare path and the supplier's own command and
    classification. ``case``: ``fresh`` (measured), ``aged`` (expired_copy) or
    ``not_ready`` (expired_copy's command with no copy installed)."""
    from phase_loop_runtime import panel_invoker as pi, sandbox_egress, seat_egress_proxy
    from phase_loop_runtime import seat_jail, seat_uid
    from phase_loop_runtime import seat_window_supply_codex as supplier
    from fixtures.codex_fixture_provider import CodexFixtureProvider

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(seat_jail, "state_home", lambda: tmp_path / "state")
    subject = _native_subject()
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda *a: (subject, None))
    # As in the consumed CODEX harness: a provider-free run creates no EC-EXECFIND-2 host
    # pass, so the launch's recorded-pass check is satisfied here and nowhere else.
    monkeypatch.setattr(seat_jail, "pass_record_verdict", lambda _digest: (True, "pass"))
    fixture_home = tmp_path / "fixture-home"
    (fixture_home / ".codex").mkdir(parents=True, mode=0o700)
    login = synthetic_login("acct-fixture-" + secrets.token_hex(4))
    auth = fixture_home / ".codex" / "auth.json"
    auth.write_text(json.dumps(login))
    auth.chmod(0o600)
    fixture_env = {"HOME": str(fixture_home), "CODEX_HOME": str(fixture_home / ".codex"),
                   "PATH": "/usr/bin:/bin"}
    decoy = plant_decoy(tmp_path / "decoy-home", monkeypatch)
    review, authorization = _stage(tmp_path)
    evidence = SpawnEvidence(monkeypatch)
    upstream_class = type("Responder", (_BearerRecorder, CodexFixtureProvider), {})

    def responder(*args, **kwargs):
        provider = upstream_class(*args, command="cat /seat/tree/window-read.txt", **kwargs)
        provider.bearers = []
        return provider
    upstream = codex_upstream(hosts=[MODEL_HOST], upstream_class=responder)
    kind = "measured" if case == "fresh" else "expired_copy"
    mode = "none" if case == "not_ready" else supplier.credential_mode(kind)
    (argv,) = supplier.launch_command(kind, qualification_input=None, model="gpt-fixture",
                                      plugin_paths=())
    # The kit's own named set and stdin input (rulings 3b and 4), never re-declared here.
    named = pi._window_named_refusals("codex")
    input_value = pi._WINDOW_MEASURED_INPUT
    prompt = pi._render_broker_pointer_prompt(
        "", input_value, source_commit="0" * 40,
        staged_tree_sha256=str(authorization.staged_tree_sha256), model_only_network=True)
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    with decoy_guard(*forbidden_roots(decoy)) as hits:
        with seat_egress_proxy.start_proxy(allowlist_id="codex", named=named) as proxy:
            assert proxy.allowlist_digest == seat_egress_proxy.allowlist_ref("codex").content_digest
            with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
                    sandbox_egress.isolated_network(
                        timeout_s=120, required=True, seat_uid_map=True,
                        proxy_socket=proxy.socket,
                        proxy_port=seat_egress_proxy.SEAT_PROXY_PORT) as prefix:
                token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
                seat = None
                try:
                    seat = pi._prepare_jailed_codex(
                        review, tmp_path / "seat", authorization, n,
                        seat_uid.holder_pid_from_prefix(prefix), ("", ""), proxy,
                        env=fixture_env, credential_mode=mode,
                        copy_transform=supplier.copy_transform if mode == "expired" else None)
                    bound_image = pi._window_bound_image_sha256(seat)
                    start = seat_egress_proxy.fence(proxy, "start", "leg")
                    timed_out, exit_code, stderr = False, None, ""
                    try:
                        done = pi._run_leg_with_liveness(
                            list(argv), cwd="/seat/home/workspace", env=dict(seat.jail.env),
                            deadline_s=120, input_text=prompt, seat_jail=seat.jail,
                            probe_jail=seat.probe_jail)
                        stdout, exit_code = done.stdout, done.returncode
                        stderr = getattr(done, "stderr", "") or ""
                    except pi.subprocess.TimeoutExpired:
                        timed_out, stdout = True, ""
                    bridge = sandbox_egress.wait_bridge_exit(prefix)
                    end = seat_egress_proxy.fence(proxy, "end", "leg") if bridge else None
                finally:
                    if seat is not None:
                        pi._cleanup_jailed_seat(seat)
                    pi._EGRESS_LAUNCH_PREFIX.reset(token)
        stream = seat_egress_proxy.proxy_stream(proxy)
    status, model_turn, tools, subagents = supplier.stream_facts(stdout)
    observation = SimpleNamespace(
        kind=kind, status=status, model_turn=model_turn, tool_steps=tools,
        subagent_steps=subagents, timed_out=timed_out, error=None, quiescent=True,
        bridge_exited=bridge, stream=stream)
    events = [event for window in stream.windows if window.label == "leg"
              for event in window.events]
    terminal = supplier.terminal(observation)
    _write_evidence(case, {
        "case": case, "kind": kind, "credential_mode": mode, "terminal": terminal,
        "status": status, "model_turn": model_turn, "tool_steps": tools,
        "timed_out": timed_out, "exit_code": exit_code, "bridge_exited": bridge,
        "fenced": bool(start.acknowledged and end is not None and end.acknowledged),
        "stream_final": stream.final, "protocol_error": stream.protocol_error,
        "events": [[e.method, e.host, e.path, e.decision] for e in events],
        "outside_events": len(stream.outside_events),
        "named": [list(entry) for entry in named],
        "allowlist_digest": proxy.allowlist_digest,
        "upstream_connections": upstream.connections, "upstream_requests": [
            [method, target] for _sni, method, target, _host in upstream.requests],
        "bearer_is_synthetic": all(bearer == "Bearer " + login["tokens"]["access_token"]
                                   for bearer in upstream.bearers if bearer),
        "decoy_hits": len(hits), "images": [digest for _src, digest in evidence.images],
        "host_runs": [digest for _src, digest in evidence.host_runs],
        "bound_image": bound_image,
        "stdout": _redact(stdout, login), "stderr_tail": _redact(stderr[-2000:], login),
    })
    assert start.acknowledged and end is not None and end.acknowledged, "unfenced launch"
    assert_pinned_image(evidence.images)  # K1-T6, from the spawn evidence
    assert bound_image == EXPECTED_CODEX_IMAGE["sha256"]  # the binding names it (ruling 5)
    assert all(digest == EXPECTED_CODEX_IMAGE["sha256"] for _src, digest in evidence.host_runs)
    assert hits == [], f"K1-T7: a lookup reached the decoy or the real home: {hits}"
    assert decoy["bearer"] not in "".join(upstream.bearers)
    assert not upstream.problems
    return SimpleNamespace(observation=observation, events=events, upstream=upstream,
                           login=login, terminal=terminal,
                           token_events=[e for e in events if supplier.token_endpoint(e)],
                           model_events=[e for e in events if (e.method, e.host, e.path)
                                         == ("POST", MODEL_HOST, MODEL_PATH)])


@pytest.mark.host_seat_credentials  # the installed-CLI opt-in; only synthetic auth is used
@_no_skip
def test_k1_t7_a_c1_fresh_copy_completes_its_local_model_request(
        tmp_path, monkeypatch, codex_upstream, live_seat_attempt):
    run = _a_c1(tmp_path, monkeypatch, codex_upstream, case="fresh")
    # The differential control (ruling 3a): no token-host event of any kind.
    assert not any(event.host == TOKEN_HOST for event in run.events), run.events
    posts = [event for event in run.events if event.method == "POST"]
    assert posts and posts[0] == run.model_events[0], run.events  # the first POST
    assert run.terminal == "completed", (run.observation, run.events)
    assert run.upstream.bearers and all(
        bearer == "Bearer " + run.login["tokens"]["access_token"]
        for bearer in run.upstream.bearers if bearer)


@pytest.mark.host_seat_credentials
@_no_skip
def test_k1_t7_a_c1_aged_copy_ends_refused_intended(
        tmp_path, monkeypatch, codex_upstream, live_seat_attempt):
    run = _a_c1(tmp_path, monkeypatch, codex_upstream, case="aged")
    assert run.token_events and all(e.decision == "deny" for e in run.token_events), run.events
    assert run.model_events == [], run.events  # none before the denial and none after
    assert run.upstream.bodies == []
    assert run.terminal == "refused_intended", (run.observation, run.events)


@pytest.mark.host_seat_credentials
@_no_skip
def test_k1_t7_a_c1_not_ready_variant_is_never_refused_intended(
        tmp_path, monkeypatch, codex_upstream, live_seat_attempt):
    run = _a_c1(tmp_path, monkeypatch, codex_upstream, case="not_ready")
    assert run.token_events == [] and run.model_events == [], run.events
    assert run.terminal == "not_ready", (run.observation, run.events)
