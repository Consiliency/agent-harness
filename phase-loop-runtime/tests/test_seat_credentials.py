"""agent-harness#1132, plan amendment A1: the jailed Claude seat's credential source.

Every platform store, the precedence, the expiry margin and the CLI refresh trigger are
exercised with fakes; nothing here reads this host's real login.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import types
from pathlib import Path

import pytest

from phase_loop_runtime import seat_credentials as sc
from phase_loop_runtime import seat_jail

# Obviously fake values, built so no secret scanner mistakes them for real credentials.
ACCESS = "fake-login-access-" + "a" * 24
REFRESH = "fake-login-refresh-" + "r" * 24
OVERRIDE = b"fake-seat-override-" + b"o" * 24


def _store(access: str = ACCESS, expires_ms: object = 4_102_444_800_000) -> bytes:
    return json.dumps({
        "claudeAiOauth": {"accessToken": access, "refreshToken": REFRESH,
                          "expiresAt": expires_ms, "scopes": ["user:inference"],
                          "subscriptionType": "max"},
        "mcpOAuth": {"some-server": {"accessToken": "fake-mcp-" + "m" * 8}},
    }).encode()


def _write_store(directory: Path, raw: bytes, mode: int = 0o600) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".credentials.json"
    path.write_bytes(raw)
    os.chmod(path, mode)
    return path


@pytest.fixture
def no_override(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state-without-override"))


# --------------------------------------------------------------------------------------
# The platform stores.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("platform", ["linux", "win32", "cygwin"])
def test_the_file_store_yields_only_the_access_token_and_expiry(tmp_path, platform):
    _write_store(tmp_path / "cfg", _store(expires_ms=1_800_000_000_500))
    login = sc.read_login_token(platform=platform, env={"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")})
    assert login.token == ACCESS.encode() and login.expires_at == 1_800_000_000.5
    assert set(vars(login)) == {"token", "expires_at"}      # nothing else is taken
    assert REFRESH.encode() not in repr(login).encode()


def test_the_file_store_defaults_to_the_home_claude_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_store(tmp_path / ".claude", _store())
    assert sc.read_login_token(platform="linux", env={}).token == ACCESS.encode()


@pytest.mark.parametrize("shape", ["group-writable", "symlink", "directory", "absent"])
def test_an_unsuitable_file_store_is_no_login(tmp_path, shape):
    cfg = tmp_path / "cfg"
    if shape == "group-writable":
        _write_store(cfg, _store(), mode=0o620)
    elif shape == "symlink":
        real = _write_store(tmp_path / "real", _store())
        cfg.mkdir()
        (cfg / ".credentials.json").symlink_to(real)
    elif shape == "directory":
        (cfg / ".credentials.json").mkdir(parents=True)
    assert sc.read_login_token(platform="linux", env={"CLAUDE_CONFIG_DIR": str(cfg)}) is None


class _FakeSecurity:
    def __init__(self, stdout: bytes = b"", returncode: int = 0):
        self.stdout, self.returncode, self.argv = stdout, returncode, None

    def __call__(self, argv, **kwargs):
        self.argv = argv
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, b"")


def test_the_macos_keychain_is_read_by_service_and_account():
    fake = _FakeSecurity(_store())
    login = sc.read_login_token(platform="darwin", env={"USER": "alice"}, run=fake)
    assert login.token == ACCESS.encode()
    assert fake.argv[1:] == ["find-generic-password", "-a", "alice",
                             "-s", "Claude Code-credentials", "-w"]


def test_a_custom_config_dir_suffixes_the_keychain_service():
    fake = _FakeSecurity(_store())
    sc.read_login_token(platform="darwin", env={"USER": "alice", "CLAUDE_CONFIG_DIR": "/cfg/x"},
                        run=fake)
    suffix = hashlib.sha256(b"/cfg/x").hexdigest()[:8]
    assert fake.argv[fake.argv.index("-s") + 1] == f"Claude Code-credentials-{suffix}"


def test_a_missing_keychain_item_is_no_login():
    assert sc.read_login_token(platform="darwin", env={"USER": "alice"},
                               run=_FakeSecurity(b"", returncode=44)) is None


@pytest.mark.parametrize("raw", [
    b"", b"not json", b"[]", b'{"claudeAiOauth": {}}',
    json.dumps({"claudeAiOauth": {"accessToken": ""}}).encode(),
    json.dumps({"claudeAiOauth": {"accessToken": "has space"}}).encode(),
    json.dumps({"claudeAiOauth": {"accessToken": 7}}).encode(),
    json.dumps({"mcpOAuth": {"x": {"accessToken": "fake"}}}).encode(),
])
def test_a_malformed_store_is_no_login(raw):
    assert sc.parse_login_token(raw) is None


def test_a_non_numeric_expiry_is_unknown_not_an_error():
    assert sc.parse_login_token(_store(expires_ms=True)).expires_at is None
    assert sc.parse_login_token(_store(expires_ms="soon")).expires_at is None


# --------------------------------------------------------------------------------------
# Precedence, the margin and the refresh trigger.
# --------------------------------------------------------------------------------------

def _login(expires_at):
    return sc.LoginToken(ACCESS.encode(), expires_at)


def _session_account(monkeypatch, tmp_path, account: str | None, organization: str = "org-1"):
    """The launching session's login: the CLI's oauthAccount.accountUuid and
    organizationUuid (both from the one file)."""
    cfg = tmp_path / "claude-config"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    target = cfg / ".claude.json"
    if account is None:
        target.unlink(missing_ok=True)
        return
    target.write_text(json.dumps({"oauthAccount": {"accountUuid": account,
                                                   "organizationUuid": organization}}))
    os.chmod(target, 0o600)


def _store_override(monkeypatch, tmp_path, *, bound_to: str | None = "acct-A",
                    session: str | None = "acct-A", token: bytes = OVERRIDE):
    """A stored override: through the real store while the session is on ``bound_to``
    (``None``: an unbound, hand-placed raw token file), then the session moves to
    ``session``."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    if bound_to is None:
        path = seat_jail.claude_seat_token_path()
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(path.parent, 0o700)
        path.write_bytes(token + b"\n")
        os.chmod(path, 0o600)
    else:
        _session_account(monkeypatch, tmp_path, bound_to)
        sc.store_override(token)
    _session_account(monkeypatch, tmp_path, session)


def test_an_override_takes_precedence_over_the_login(monkeypatch, tmp_path):
    _store_override(monkeypatch, tmp_path)
    got = sc.resolve_claude_seat_credential(900, read_login=lambda: _login(None))
    assert (got.token, got.source, got.expires_at) == (OVERRIDE, sc.SOURCE_OVERRIDE, None)


def test_without_an_override_the_login_is_used(no_override):
    got = sc.resolve_claude_seat_credential(900, now=lambda: 1000.0,
                                            read_login=lambda: _login(5000.0))
    assert (got.token, got.source, got.expires_at) == (ACCESS.encode(), sc.SOURCE_LOGIN, 5000.0)


def test_neither_source_is_the_missing_notice(no_override):
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        sc.resolve_claude_seat_credential(900, read_login=lambda: None)
    assert caught.value.code == "claude_seat_token_missing"


def test_a_short_login_at_launch_is_refused_and_nothing_is_run(no_override, monkeypatch):
    # Plan amendment A3: the launch never renews a credential; the wait (before staging)
    # is where a short login is given time. At launch it is typed, and the seat is not run.
    monkeypatch.setattr(sc.subprocess, "run", pytest.fail)
    monkeypatch.setattr(sc.subprocess, "Popen", pytest.fail)
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        sc.resolve_claude_seat_credential(900, now=lambda: 1000.0,
                                          read_login=lambda: _login(1500.0))
    assert caught.value.code == "claude_seat_login_token_expiring"
    assert caught.value.code in seat_jail.JAIL_NOT_RUN_CODES
    assert caught.value.code not in seat_jail.SEALED_FALLBACK_CODES
    assert not hasattr(sc, "refresh_login_via_cli")


def test_a_login_replaced_between_launches_is_read_afresh(no_override):
    store = {"token": _login(9000.0)}
    first = sc.resolve_claude_seat_credential(900, now=lambda: 1000.0, read_login=lambda: store["token"])
    store["token"] = sc.LoginToken(b"fake-login-access-" + b"b" * 24, 9000.0)  # another subscription
    second = sc.resolve_claude_seat_credential(900, now=lambda: 1000.0, read_login=lambda: store["token"])
    assert first.token != second.token and second.token.endswith(b"b" * 24)


@pytest.mark.parametrize("env, deadline, expected", [
    ({}, None, sc.DEFAULT_MARGIN_S),
    ({}, 1800, 1800),
    ({sc.MARGIN_ENV: "60"}, 1800, 60),
    ({sc.MARGIN_ENV: "0"}, 1800, 0),
    ({sc.MARGIN_ENV: "nonsense"}, 1800, 1800),
    ({sc.MARGIN_ENV: "-5"}, 1800, 1800),
])
def test_the_margin_is_configurable_and_defaults_to_the_deadline(env, deadline, expected):
    assert sc.login_margin_s(deadline, env=env) == expected


def test_presence_is_an_override_or_a_login(no_override):
    assert sc.claude_seat_credential_present(read_login=lambda: _login(None)) is True
    assert sc.claude_seat_credential_present(read_login=lambda: None) is False



# --------------------------------------------------------------------------------------
# Maintainer ruling 2026-10-05: the seat's credential follows the subscription of the
# session that launched the leg. An override is used only when it is bound to that account.
# --------------------------------------------------------------------------------------

def test_an_override_bound_to_another_account_is_ignored_with_its_notice(monkeypatch, tmp_path):
    _store_override(monkeypatch, tmp_path, bound_to="acct-B", session="acct-A")
    got = sc.resolve_claude_seat_credential(900, now=lambda: 1000.0,
                                            read_login=lambda: _login(9000.0))
    assert (got.token, got.source) == (ACCESS.encode(), sc.SOURCE_LOGIN)
    assert got.notices == (sc.OVERRIDE_OTHER_SUBSCRIPTION,)


def test_an_override_bound_to_the_sessions_account_is_used(monkeypatch, tmp_path):
    _store_override(monkeypatch, tmp_path, bound_to="acct-A", session="acct-A")
    got = sc.resolve_claude_seat_credential(900, read_login=lambda: _login(9000.0))
    assert (got.token, got.source, got.notices) == (OVERRIDE, sc.SOURCE_OVERRIDE, ())


@pytest.mark.parametrize("bound_to, session", [
    (None, "acct-A"),        # the override has no binding
    ("acct-A", None),        # the session's account cannot be determined
    (None, None),
])
def test_an_undeterminable_binding_uses_the_login_with_the_notice(monkeypatch, tmp_path,
                                                                 bound_to, session):
    _store_override(monkeypatch, tmp_path, bound_to=bound_to, session=session)
    got = sc.resolve_claude_seat_credential(900, now=lambda: 1000.0,
                                            read_login=lambda: _login(9000.0))
    assert got.source == sc.SOURCE_LOGIN and got.notices == (sc.OVERRIDE_OTHER_SUBSCRIPTION,)


def test_a_subscription_swap_moves_the_seat_off_a_bound_override(monkeypatch, tmp_path):
    # The operator logs in to another subscription: the next launch follows the session.
    _store_override(monkeypatch, tmp_path, bound_to="acct-A", session="acct-A")
    assert sc.resolve_claude_seat_credential(900, read_login=lambda: _login(9e9)).source == (
        sc.SOURCE_OVERRIDE)
    _session_account(monkeypatch, tmp_path, "acct-B")
    assert sc.resolve_claude_seat_credential(900, read_login=lambda: _login(9e9)).source == (
        sc.SOURCE_LOGIN)


def test_no_override_raises_no_notice(no_override, monkeypatch, tmp_path):
    _session_account(monkeypatch, tmp_path, "acct-A")
    got = sc.resolve_claude_seat_credential(900, now=lambda: 1000.0,
                                            read_login=lambda: _login(9000.0))
    assert got.notices == ()


def test_the_session_identity_is_the_clis_own_oauth_account(monkeypatch, tmp_path):
    _session_account(monkeypatch, tmp_path, "acct-A", "org-7")
    assert sc.ClaudeCredentialAdapter().current_identity() == sc.Identity("acct-A", "org-7")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    for oauth in ({}, {"accountUuid": "acct-A"}, {"organizationUuid": "org-7"}):
        (tmp_path / "home" / ".claude.json").write_text(json.dumps({"oauthAccount": oauth}))
        assert sc.ClaudeCredentialAdapter().current_identity() is None   # both, or neither


# --------------------------------------------------------------------------------------
# `phase-loop seat-sandbox store-token` (maintainer decision 2026-10-05: "Store command
# binds it"): the override is stored together with the account it belongs to.
# --------------------------------------------------------------------------------------

def _store_env(monkeypatch, tmp_path, session="acct-A"):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    _session_account(monkeypatch, tmp_path, session)


def test_store_refuses_without_a_login_and_writes_nothing(monkeypatch, tmp_path):
    _store_env(monkeypatch, tmp_path, session=None)
    with pytest.raises(sc.StoreRefused, match="no claude login"):
        sc.store_override(OVERRIDE)
    assert not seat_jail.claude_seat_token_path().exists()


@pytest.mark.parametrize("token", [b"", b"   \n", b"has space", b"x" * 20000])
def test_store_refuses_a_malformed_token(monkeypatch, tmp_path, token):
    _store_env(monkeypatch, tmp_path)
    with pytest.raises(sc.StoreRefused):
        sc.store_override(token)
    assert not seat_jail.claude_seat_token_path().exists()


def test_store_refuses_a_directory_that_is_not_private(monkeypatch, tmp_path):
    _store_env(monkeypatch, tmp_path)
    directory = seat_jail.claude_seat_token_path().parent
    directory.mkdir(parents=True, mode=0o755)
    os.chmod(directory, 0o755)
    with pytest.raises(sc.StoreRefused, match="chmod 700"):
        sc.store_override(OVERRIDE)
    assert not seat_jail.claude_seat_token_path().exists()


def test_the_cli_refuses_without_a_login(monkeypatch, tmp_path, capsys):
    import io
    import sys

    from phase_loop_runtime import cli

    _store_env(monkeypatch, tmp_path, session=None)
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(
        isatty=lambda: False, buffer=io.BytesIO(b"fake-token-" + b"z" * 20)))
    assert cli.main(["seat-sandbox", "store-token"]) == 1
    assert "refused" in capsys.readouterr().err
    assert not seat_jail.claude_seat_token_path().exists()


#: The record schema, spelled out so the module collects anywhere (checked below).
_SCHEMA = "seat_credential_override.v2"


def _record():
    return seat_jail.claude_seat_token_path().with_name("claude.override.json")


@pytest.mark.parametrize("shape", ["group-writable", "symlink", "dir-not-private", "fifo"])
def test_an_unsafe_override_record_refuses_the_launch(monkeypatch, tmp_path, shape):
    # A1's contract for an unsafe override: the launch refuses, typed, before any effect,
    # and the decision returns at once (no open of a FIFO blocks it).
    import signal

    _store_override(monkeypatch, tmp_path)
    record = _record()
    if shape == "group-writable":
        os.chmod(record, 0o620)
    elif shape == "symlink":
        real = tmp_path / "elsewhere.json"
        real.write_bytes(record.read_bytes())
        os.chmod(real, 0o600)
        record.unlink()
        record.symlink_to(real)
    elif shape == "dir-not-private":
        os.chmod(record.parent, 0o750)
    else:
        record.unlink()
        os.mkfifo(record, 0o600)

    def _blocked(signum, frame):
        raise AssertionError("the decision blocked on the override record")

    previous = signal.signal(signal.SIGALRM, _blocked)
    signal.setitimer(signal.ITIMER_REAL, 2)
    try:
        assert sc.override_decision() == sc.OverrideDecision(False, refusal=sc.OVERRIDE_UNSAFE)
        with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
            sc.resolve_claude_seat_credential(900, read_login=lambda: _login(9e9))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    assert refused.value.code == sc.OVERRIDE_UNSAFE


@pytest.mark.parametrize("content", [
    b"not json", b"[]", json.dumps({"schema": "other", "account": "acct-A", "token": "t"}).encode(),
    json.dumps({"schema": _SCHEMA, "token": "fake-token"}).encode(),
    json.dumps({"schema": _SCHEMA, "account": "acct-A"}).encode(),
    json.dumps({"schema": _SCHEMA, "account": "acct-A", "token": "has space"}).encode(),
    # an organization-less record, and a v1 (account-only) record, bind nothing
    json.dumps({"schema": _SCHEMA, "account": "acct-A", "token": "fake-token-x"}).encode(),
    json.dumps({"schema": "seat_credential_override.v1", "account": "acct-A",
                "token": "fake-token-x"}).encode(),
])
def test_a_malformed_override_record_binds_nothing(monkeypatch, tmp_path, content):
    assert sc.RECORD_SCHEMA == _SCHEMA
    _store_override(monkeypatch, tmp_path)
    _record().write_bytes(content)
    got = sc.resolve_claude_seat_credential(900, now=lambda: 1000.0,
                                            read_login=lambda: _login(9000.0))
    assert got.source == sc.SOURCE_LOGIN and got.notices == (sc.OVERRIDE_OTHER_SUBSCRIPTION,)


def test_the_rule_is_the_adapters_not_claudes():
    # Any harness adapter gets the same rule: a record whose account AND organization equal
    # the session's.
    class _Adapter:
        harness = "other"
        override_ignored_notice = "other_override_other_subscription"
        sources = ("seat_token", "login")

        def __init__(self, record, current, unsafe=False):
            self._r, self._c, self._u = record, current, unsafe

        def record_path(self):
            return Path("/nonexistent")

        def override_present(self):
            return self._r is not None or self._u

        def read_override(self):
            if self._u:
                raise sc.UnsafeOverride("x")
            return self._r

        def current_identity(self):
            return self._c

        def account_source(self):
            return Path("/nonexistent")

    here = sc.Identity("x", "org-1")
    good = sc.OverrideRecord(here, b"fake-token-x")
    assert sc.override_decision(_Adapter(None, here)) == sc.OverrideDecision(False)
    applied = sc.override_decision(_Adapter(good, here))
    assert applied.applies and applied.token == b"fake-token-x"
    for other in (sc.Identity("y", "org-1"), sc.Identity("x", "org-2"), None):
        assert sc.override_decision(_Adapter(good, other)) == sc.OverrideDecision(
            False, "other_override_other_subscription")
    assert sc.override_decision(_Adapter(None, here, unsafe=True)) == sc.OverrideDecision(
        False, refusal=sc.OVERRIDE_UNSAFE)


def test_store_binds_token_and_account_in_one_record(monkeypatch, tmp_path):
    _store_env(monkeypatch, tmp_path)
    sc.store_override(OVERRIDE + b"\n")
    record = _record()
    assert json.loads(record.read_text()) == {
        "schema": sc.RECORD_SCHEMA, "account": "acct-A", "organization": "org-1",
        "token": OVERRIDE.decode()}
    assert os.stat(record).st_mode & 0o777 == 0o600
    assert os.stat(record.parent).st_mode & 0o777 == 0o700
    assert [p.name for p in record.parent.iterdir()] == [record.name]   # no temp left behind
    decision = sc.override_decision()
    assert decision.applies and decision.token == OVERRIDE
    _session_account(monkeypatch, tmp_path, "acct-B")
    assert sc.override_decision() == sc.OverrideDecision(False, sc.OVERRIDE_OTHER_SUBSCRIPTION)


def test_an_interrupted_store_keeps_the_previous_record_whole(monkeypatch, tmp_path):
    # The record is replaced by one rename: interrupted before it, the old record (token
    # and account together) is still the one that applies, and no temp file is left.
    _store_env(monkeypatch, tmp_path)
    sc.store_override(b"fake-old-override-" + b"o" * 20)
    def _interrupt(*a, **k):
        raise KeyboardInterrupt   # after the new record is written, before its rename

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", _interrupt)
        with pytest.raises(KeyboardInterrupt):
            sc.store_override(b"fake-new-override-" + b"n" * 20)
    decision = sc.override_decision()
    assert decision.applies and decision.token == b"fake-old-override-" + b"o" * 20
    assert [p.name for p in _record().parent.iterdir()] == [_record().name]


@pytest.mark.parametrize("tty", [False, True])
def test_the_cli_stores_without_ever_printing_the_token(monkeypatch, tmp_path, capsys, tty):
    import io
    import sys

    from phase_loop_runtime import cli

    _store_env(monkeypatch, tmp_path)
    token = b"fake-cli-override-" + b"c" * 24
    if tty:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
        prompts = []
        monkeypatch.setattr("getpass.getpass",
                            lambda prompt="": prompts.append(prompt) or token.decode())
    else:
        monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(
            isatty=lambda: False, buffer=io.BytesIO(token + b"\n")))
    assert cli.main(["seat-sandbox", "store-token"]) == 0
    out = capsys.readouterr()
    assert token.decode() not in out.out + out.err
    decision = sc.override_decision()
    assert decision.applies and decision.token == token
    if tty:
        assert prompts and "hidden" in prompts[0]


# --------------------------------------------------------------------------------------
# agent-harness#1253 board round 1: the token the launch uses is the token whose binding was
# checked, whatever runs concurrently; the store writes only where it checked; nothing blocks.
# Each test hooks a seam that exists in every design (the session-account read, fsync, the
# files themselves), so it measures behaviour, not internals.
# --------------------------------------------------------------------------------------

TOKEN_A, TOKEN_B = b"fake-override-of-A-" + b"a" * 16, b"fake-override-of-B-" + b"b" * 16


def _two_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    configs = {}
    for account in ("acct-A", "acct-B"):
        cfg = tmp_path / f"cfg-{account}"
        cfg.mkdir()
        (cfg / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": account, "organizationUuid": "org-1"}}))
        os.chmod(cfg / ".claude.json", 0o600)
        configs[account] = cfg
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(configs["acct-A"]))      # this session: A
    return sc.ClaudeCredentialAdapter({"CLAUDE_CONFIG_DIR": str(configs["acct-B"])})


def test_a_store_during_the_launchs_decision_cannot_swap_the_token(monkeypatch, tmp_path):
    # Session B stores its token right after session A's launch has read the stored binding
    # (the hook fires when the stored override's JSON is parsed): A must still get A's token
    # (or the login), never B's.
    adapter_b = _two_sessions(monkeypatch, tmp_path)
    sc.store_override(TOKEN_A)
    real_loads = sc.json.loads
    fired = []

    def loads(raw, *a, **k):
        value = real_loads(raw, *a, **k)
        if not fired and isinstance(value, dict) and value.get("account") == "acct-A":
            fired.append(True)
            sc.store_override(TOKEN_B, adapter_b)
        return value

    monkeypatch.setattr(sc.json, "loads", loads)
    got = sc.resolve_claude_seat_credential(0, read_login=lambda: _login(None))
    assert fired
    assert got.token != TOKEN_B, "session A launched with account B's token"


def test_two_concurrent_stores_never_leave_a_mixed_token_and_binding(monkeypatch, tmp_path):
    # Store B runs to completion inside store A, while A is writing the file that binds its
    # account (identified by name through /proc; the test is skipped without it): whatever
    # the outcome, the token a session uses belongs to the account it was bound with.
    if not os.path.exists("/proc/self/fd"):
        pytest.skip("needs /proc to identify the file being written")
    adapter_b = _two_sessions(monkeypatch, tmp_path)
    real_fsync = os.fsync
    fired = []

    def fsync(fd):
        real_fsync(fd)
        name = os.readlink(f"/proc/self/fd/{fd}") if os.path.exists("/proc/self/fd") else ""
        if not fired and (".account." in name or ".override.json." in name):
            fired.append(True)
            sc.store_override(TOKEN_B, adapter_b)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fsync)
        sc.store_override(TOKEN_A)
    assert fired
    for session, own in (("acct-A", TOKEN_A), ("acct-B", TOKEN_B)):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / f"cfg-{session}"))
        got = sc.resolve_claude_seat_credential(0, read_login=lambda: _login(None))
        assert got.source == sc.SOURCE_LOGIN or got.token == own, (
            f"session {session} launched with the other account's token")


def test_a_token_file_replaced_by_hand_is_never_used(monkeypatch, tmp_path):
    # A stored, bound override; then the raw token file is replaced by hand with another
    # account's token (the A1-era rotation). The hand-placed token must not be used.
    _two_sessions(monkeypatch, tmp_path)
    sc.store_override(TOKEN_A)
    raw = seat_jail.claude_seat_token_path()
    staged = raw.with_name("claude.by-hand")
    staged.write_bytes(TOKEN_B + b"\n")
    os.chmod(staged, 0o600)
    os.replace(staged, raw)
    got = sc.resolve_claude_seat_credential(0, read_login=lambda: _login(None))
    assert got.token != TOKEN_B, "a hand-placed token was used under the stored binding"


def test_the_store_refuses_an_ancestor_link_and_writes_nothing_through_it(monkeypatch, tmp_path):
    # A directory component below the state root is a link -- even to a private directory
    # the user owns: the store refuses it rather than following it.
    _store_env(monkeypatch, tmp_path)
    path = seat_jail.claude_seat_token_path()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    os.chmod(elsewhere, 0o700)
    path.parent.parent.parent.mkdir(parents=True)
    path.parent.parent.symlink_to(elsewhere, target_is_directory=True)   # phase-loop -> elsewhere
    with pytest.raises((sc.StoreRefused, OSError)):
        sc.store_override(OVERRIDE)
    assert not any(elsewhere.rglob("*")), "the store wrote through a linked ancestor"


def test_the_store_refuses_a_parent_directory_others_can_write(monkeypatch, tmp_path):
    _store_env(monkeypatch, tmp_path)
    parent = seat_jail.claude_seat_token_path().parent.parent      # phase-loop
    parent.mkdir(parents=True)
    os.chmod(parent, 0o777)
    with pytest.raises(sc.StoreRefused, match="writable by others"):
        sc.store_override(OVERRIDE)
    assert not sc.override_decision().applies


def test_the_store_writes_only_into_the_directory_it_checked(monkeypatch, tmp_path):
    # The credentials directory is swapped for a link to a public directory after the store
    # checked it, just before its first file is opened: nothing may land in the public
    # directory.
    _store_env(monkeypatch, tmp_path)
    directory = seat_jail.claude_seat_token_path().parent
    directory.mkdir(parents=True, mode=0o700)
    public = tmp_path / "public"
    public.mkdir()
    os.chmod(public, 0o777)
    real_open = os.open
    swapped = []

    def _open(path, *a, **k):
        if not swapped and str(path).endswith(".tmp"):
            swapped.append(True)
            directory.rename(directory.with_name("checked"))
            directory.symlink_to(public, target_is_directory=True)
        return real_open(path, *a, **k)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", _open)
        try:
            sc.store_override(OVERRIDE)
        except (sc.StoreRefused, OSError):
            pass
    assert swapped
    assert not any(public.iterdir()), "the store wrote into a directory it never checked"


def test_an_unreadable_session_account_file_never_blocks(monkeypatch, tmp_path):
    # A FIFO where the CLI's account file should be: the decision returns at once, and the
    # override is not used.
    import signal

    _store_override(monkeypatch, tmp_path)
    account_file = tmp_path / "claude-config" / ".claude.json"
    account_file.unlink()
    os.mkfifo(account_file, 0o600)

    def _blocked(signum, frame):
        raise AssertionError("the decision blocked on the session's account file")

    previous = signal.signal(signal.SIGALRM, _blocked)
    signal.setitimer(signal.ITIMER_REAL, 2)
    try:
        assert sc.override_decision() == sc.OverrideDecision(False, sc.OVERRIDE_OTHER_SUBSCRIPTION)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def test_the_store_names_an_unsafe_account_file_instead_of_saying_no_login(monkeypatch,
                                                                           tmp_path):
    _store_env(monkeypatch, tmp_path)
    account_file = tmp_path / "claude-config" / ".claude.json"
    real = tmp_path / "dotfiles-claude.json"
    real.write_bytes(account_file.read_bytes())
    os.chmod(real, 0o600)
    account_file.unlink()
    account_file.symlink_to(real)
    with pytest.raises(sc.StoreRefused) as refused:
        sc.store_override(OVERRIDE)
    assert ".claude.json" in str(refused.value) and "no claude login" not in str(refused.value)


def test_store_token_refuses_a_terminal_that_cannot_hide_input(monkeypatch, tmp_path, capsys):
    # getpass's fallback reads with echo ON (after a GetPassWarning): refuse instead.
    import io
    import sys

    from phase_loop_runtime import cli

    _store_env(monkeypatch, tmp_path)

    class _Terminal(io.StringIO):
        def isatty(self):
            return True

        def fileno(self):
            raise ValueError("no terminal descriptor")

    real_open = os.open

    def _no_tty(path, *a, **k):
        if path == "/dev/tty":
            raise OSError("no controlling terminal")
        return real_open(path, *a, **k)

    monkeypatch.setattr(os, "open", _no_tty)
    monkeypatch.setattr(sys, "stdin", _Terminal("fake-seat-token-echoed\n"))
    try:
        result = cli.main(["seat-sandbox", "store-token"])
    except Exception:          # an unhandled warning-as-error is still not a success
        result = 1
    monkeypatch.setattr(os, "open", real_open)
    assert result != 0
    assert not sc.override_decision().applies, "a token typed with echo on was stored"
    assert "fake-seat-token-echoed" not in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# agent-harness#1253 board round 1 (grok non-blocking): the store names the account; a
# status shows the binding; stale temps of a killed store are swept; sources gate the rule.
# --------------------------------------------------------------------------------------

def test_the_store_says_which_account_it_bound_and_status_shows_it(monkeypatch, tmp_path,
                                                                   capsys):
    import io
    import sys

    from phase_loop_runtime import cli

    _store_env(monkeypatch, tmp_path)
    token = b"fake-status-override-" + b"s" * 20
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(
        isatty=lambda: False, buffer=io.BytesIO(token + b"\n")))
    assert cli.main(["seat-sandbox", "store-token"]) == 0
    out = capsys.readouterr().out
    assert "account acct-A" in out and "organization org-1" in out
    assert cli.main(["seat-sandbox", "token-status"]) == 0        # 0 only when it applies
    out = capsys.readouterr().out
    assert "bound: account acct-A, organization org-1" in out
    assert "this session: account acct-A, organization org-1" in out
    assert "applies to this session: yes" in out
    _session_account(monkeypatch, tmp_path, "acct-B")
    assert cli.main(["seat-sandbox", "token-status"]) != 0
    out = capsys.readouterr().out
    assert "applies to this session: no" in out and sc.OVERRIDE_OTHER_SUBSCRIPTION in out
    assert token.decode() not in out


def test_a_store_sweeps_stale_temps_a_killed_store_left(monkeypatch, tmp_path):
    _store_env(monkeypatch, tmp_path)
    sc.store_override(OVERRIDE)
    directory = _record().parent
    stale = directory / ".claude.override.json.dead.tmp"
    young = directory / ".claude.override.json.live.tmp"
    for leftover in (stale, young):
        leftover.write_bytes(b"fake-leftover")
        os.chmod(leftover, 0o600)
    old = time.time() - 3600
    os.utime(stale, (old, old))
    sc.store_override(OVERRIDE)
    assert not stale.exists() and young.exists()


def test_an_adapter_without_the_override_source_never_uses_one():
    class _LoginOnly:
        harness = "other"
        override_ignored_notice = "other_override_other_subscription"
        sources = ("login",)

        def record_path(self):
            return Path("/nonexistent")

        def override_present(self):
            return True

        def read_override(self):
            return sc.OverrideRecord(sc.Identity("x", "o"), b"fake-token-x")

        def current_identity(self):
            return sc.Identity("x", "o")

        def account_source(self):
            return Path("/nonexistent")

    assert sc.override_decision(_LoginOnly()) == sc.OverrideDecision(False)



# --------------------------------------------------------------------------------------
# agent-harness#1253 president, maintainer ruling 2026-10-05: the override binds the account
# AND the organization of the login it was stored under.
# --------------------------------------------------------------------------------------

def test_same_account_in_another_organization_uses_the_login(monkeypatch, tmp_path):
    _store_env(monkeypatch, tmp_path)
    _session_account(monkeypatch, tmp_path, "acct-A", "org-1")
    sc.store_override(OVERRIDE)
    _session_account(monkeypatch, tmp_path, "acct-A", "org-2")     # same account, other org
    got = sc.resolve_claude_seat_credential(900, now=lambda: 1000.0,
                                            read_login=lambda: _login(9000.0))
    assert got.source == sc.SOURCE_LOGIN and got.notices == (sc.OVERRIDE_OTHER_SUBSCRIPTION,)
    _session_account(monkeypatch, tmp_path, "acct-A", "org-1")     # back: it applies again
    assert sc.override_decision().applies


def test_store_refuses_when_the_organization_is_unknown(monkeypatch, tmp_path):
    _store_env(monkeypatch, tmp_path)
    cfg = tmp_path / "claude-config"
    (cfg / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": "acct-A"}}))
    with pytest.raises(sc.StoreRefused):
        sc.store_override(OVERRIDE)
    assert not _record().exists()


# codex round-2 falsifiers (F001, F002), adopted as written apart from their filenames.

@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_override_record_refuses_group_or_world_read_access(monkeypatch, tmp_path, mode):
    _store_override(monkeypatch, tmp_path)
    sc.ClaudeCredentialAdapter().record_path().chmod(mode)
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        sc.resolve_claude_seat_credential(
            0, read_login=lambda: sc.LoginToken(b"fake-login-A", None))
    assert refused.value.code == sc.OVERRIDE_UNSAFE


def test_store_refuses_a_linked_state_root(monkeypatch, tmp_path):
    _store_env(monkeypatch, tmp_path)
    root = seat_jail.state_home()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    root.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises((sc.StoreRefused, OSError)):
        sc.store_override(b"fake-seat-token")
    assert not (elsewhere / "phase-loop" / "seat-credentials" / "claude.override.json").exists()
