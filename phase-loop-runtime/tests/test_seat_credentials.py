"""agent-harness#1132, plan amendment A1: the jailed Claude seat's credential source.

Every platform store, the precedence, the expiry margin and the CLI refresh trigger are
exercised with fakes; nothing here reads this host's real login.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
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


def _session_account(monkeypatch, tmp_path, account: str | None):
    """The launching session's login account: the CLI's oauthAccount.accountUuid."""
    cfg = tmp_path / "claude-config"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    target = cfg / ".claude.json"
    if account is None:
        target.unlink(missing_ok=True)
        return
    target.write_text(json.dumps({"oauthAccount": {"accountUuid": account}}))
    os.chmod(target, 0o600)


def _bind_override(account: str | None) -> None:
    binding = seat_jail.claude_seat_token_path().with_name("claude.account")
    if account is None:
        binding.unlink(missing_ok=True)
        return
    binding.write_text(json.dumps({"schema": sc.BINDING_SCHEMA, "account": account}))
    os.chmod(binding, 0o600)


def _store_override(monkeypatch, tmp_path, *, bound_to: str | None = "acct-A",
                    session: str | None = "acct-A"):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    path = seat_jail.claude_seat_token_path()
    path.parent.mkdir(parents=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    path.write_bytes(OVERRIDE + b"\n")
    os.chmod(path, 0o600)
    _bind_override(bound_to)
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


@pytest.mark.parametrize("shape", ["group-writable", "symlink", "wrong-schema", "not-json",
                                   "dir-not-private"])
def test_an_unsafe_or_malformed_binding_is_no_binding(monkeypatch, tmp_path, shape):
    _store_override(monkeypatch, tmp_path, bound_to="acct-A", session="acct-A")
    binding = seat_jail.claude_seat_token_path().with_name("claude.account")
    if shape == "group-writable":
        os.chmod(binding, 0o620)
    elif shape == "symlink":
        real = tmp_path / "elsewhere.json"
        real.write_text(binding.read_text())
        binding.unlink()
        binding.symlink_to(real)
    elif shape == "wrong-schema":
        binding.write_text(json.dumps({"schema": "other", "account": "acct-A"}))
    elif shape == "not-json":
        binding.write_text("acct-A")
    else:
        os.chmod(binding.parent, 0o750)
    assert sc.ClaudeCredentialAdapter().override_account() is None
    assert sc.override_decision() == sc.OverrideDecision(False, sc.OVERRIDE_OTHER_SUBSCRIPTION)


def test_the_session_account_is_the_clis_own_oauth_account(monkeypatch, tmp_path):
    _session_account(monkeypatch, tmp_path, "acct-A")
    assert sc.ClaudeCredentialAdapter().current_account() == "acct-A"
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / ".claude.json").write_text(json.dumps({"oauthAccount": {}}))
    assert sc.ClaudeCredentialAdapter().current_account() is None


def test_the_rule_is_the_adapters_not_claudes(monkeypatch):
    # Any harness adapter gets the same rule: present + both accounts known + equal.
    class _Adapter:
        harness = "other"
        override_ignored_notice = "other_override_other_subscription"

        def __init__(self, present, bound, current):
            self._p, self._b, self._c = present, bound, current

        def override_present(self):
            return self._p

        def override_account(self):
            return self._b

        def current_account(self):
            return self._c

    assert sc.override_decision(_Adapter(False, None, "x")) == sc.OverrideDecision(False)
    assert sc.override_decision(_Adapter(True, "x", "x")) == sc.OverrideDecision(True)
    assert sc.override_decision(_Adapter(True, "y", "x")) == sc.OverrideDecision(
        False, "other_override_other_subscription")


# --------------------------------------------------------------------------------------
# `phase-loop seat-sandbox store-token` (maintainer decision 2026-10-05: "Store command
# binds it"): the override is stored together with the account it belongs to.
# --------------------------------------------------------------------------------------

def _store_env(monkeypatch, tmp_path, session="acct-A"):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    _session_account(monkeypatch, tmp_path, session)


def test_store_binds_the_override_to_the_current_login(monkeypatch, tmp_path):
    _store_env(monkeypatch, tmp_path)
    sc.store_override(OVERRIDE + b"\n")
    path = seat_jail.claude_seat_token_path()
    binding = path.with_name("claude.account")
    assert path.read_bytes() == OVERRIDE + b"\n"
    assert json.loads(binding.read_text()) == {"schema": sc.BINDING_SCHEMA, "account": "acct-A"}
    for target in (path, binding):
        assert os.stat(target).st_mode & 0o777 == 0o600
    assert os.stat(path.parent).st_mode & 0o777 == 0o700
    # ... and the next launch uses it, until the session moves to another account.
    assert sc.override_decision().applies
    _session_account(monkeypatch, tmp_path, "acct-B")
    assert sc.override_decision() == sc.OverrideDecision(False, sc.OVERRIDE_OTHER_SUBSCRIPTION)


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


def test_an_interrupted_store_leaves_an_ignored_override(monkeypatch, tmp_path):
    # Replacing a bound override: the old binding goes first, so a store interrupted
    # before the new binding is written leaves an UNBOUND override, which is ignored.
    _store_env(monkeypatch, tmp_path)
    sc.store_override(b"fake-old-override-" + b"o" * 20)
    real = sc._write_private

    def _fail_on_binding(path, data):
        if path.name.endswith(".account"):
            raise OSError("interrupted")
        real(path, data)

    monkeypatch.setattr(sc, "_write_private", _fail_on_binding)
    with pytest.raises(OSError):
        sc.store_override(b"fake-new-override-" + b"n" * 20)
    assert sc.override_decision() == sc.OverrideDecision(False, sc.OVERRIDE_OTHER_SUBSCRIPTION)


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
    assert seat_jail.claude_seat_token_path().read_bytes() == token + b"\n"
    assert sc.override_decision().applies
    if tty:
        assert prompts and "hidden" in prompts[0]


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
