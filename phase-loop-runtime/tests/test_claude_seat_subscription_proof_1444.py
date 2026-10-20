"""agent-harness#1444: a Claude seat's subscription is proven from the LOGIN its credential is
drawn from, and the seat itself must report logged-in and first-party.

Since agent-harness#1253 a seat receives the login's access token by descriptor, so the
seat-side ``claude auth status --json`` reports ``authMethod: "oauth_token"`` and no
``subscriptionType``. The check that demanded both from the seat refused every Claude TUI seat.

The invariant these tests hold: a seat launches only when BOTH (a) the login store the owner
draws the credential from carries a first-party Claude subscription with a non-empty
subscription type and (b) the seat reports logged-in, first-party, and the descriptor-delivered
credential. Anything missing, malformed, timed out, non-zero or disagreeing is
``subscription_auth_unproven``, and nothing identifying is returned or logged.

The two reports below are the REAL shapes (field names from Claude Code 2.1.295; every value
an obvious fake).
"""

from __future__ import annotations

import json
import os
import subprocess
import types
from pathlib import Path

import pytest

import phase_loop_runtime.panel_invoker as pi
from phase_loop_runtime import launcher
from phase_loop_runtime import seat_credentials as sc

UNPROVEN = (False, "subscription_auth_unproven")

# Obviously fake values, built so no secret scanner mistakes them for real credentials.
ACCESS = "fake-login-access-" + "a" * 24
OTHER_ACCESS = "fake-other-access-" + "b" * 24
REFRESH = "fake-login-refresh-" + "r" * 24
EMAIL = "private@example.invalid"
ORG_ID = "org-secret-1444"
ORG_NAME = "private org 1444"
PLAN = "plan-label-1444"


def login_store(**oauth_overrides) -> bytes:
    """The CLI's own credential store, as the login writes it."""
    oauth = {
        "accessToken": ACCESS,
        "refreshToken": REFRESH,
        "expiresAt": 4_102_444_800_000,
        "refreshTokenExpiresAt": 4_102_444_800_000,
        "scopes": ["user:file_upload", "user:inference", "user:profile", "user:sessions:claude_code"],
        "subscriptionType": PLAN,
        "rateLimitTier": "default_claude_max_20x",
    }
    for key, value in oauth_overrides.items():
        if value is _ABSENT:
            oauth.pop(key, None)
        else:
            oauth[key] = value
    return json.dumps({"claudeAiOauth": oauth,
                       "mcpOAuth": {"some-server": {"accessToken": "fake-mcp-" + "m" * 8}}}).encode()


_ABSENT = object()


def seat_report(**overrides) -> str:
    """``claude auth status --json`` INSIDE a seat holding the descriptor-delivered token."""
    payload = {
        "loggedIn": True,
        "authMethod": "oauth_token",
        "apiProvider": "firstParty",
        "analyticsDisabled": False,
        "projectsDirectory": "/home/phase-loop-seat/.claude/projects",
        "configDirectory": "/home/phase-loop-seat/.claude",
    }
    for key, value in overrides.items():
        if value is _ABSENT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return json.dumps(payload)


def login_report(**overrides) -> str:
    """The same command run BY THE LOGIN ITSELF (what the pre-#1253 check was written for)."""
    payload = {
        "loggedIn": True,
        "authMethod": "claude.ai",
        "apiProvider": "firstParty",
        "analyticsDisabled": False,
        "projectsDirectory": "/home/someone/.claude/projects",
        "configDirectory": "/home/someone/.claude",
        "email": EMAIL,
        "orgId": ORG_ID,
        "orgName": ORG_NAME,
        "subscriptionType": PLAN,
    }
    payload.update(overrides)
    return json.dumps(payload)


def write_store(config_dir: Path, raw: bytes, mode: int = 0o600) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / ".credentials.json"
    path.write_bytes(raw)
    os.chmod(path, mode)
    return path


@pytest.fixture(autouse=True)
def _no_host_login(tmp_path, monkeypatch):
    """The host's own login can never satisfy a test: the process sees an empty home."""
    home = tmp_path / "process-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.fixture
def login_env(tmp_path):
    """A leg env naming a config directory whose store is a proven subscription login."""
    config = tmp_path / "login" / ".claude"
    write_store(config, login_store())
    return {"CLAUDE_CONFIG_DIR": str(config), "HOME": str(tmp_path / "login"),
            "PATH": "/usr/bin:/bin"}


def stub_seat(monkeypatch, stdout: str, *, returncode: int = 0, stderr: str = "") -> list:
    """Replace the owner's launch with a seat that answers ``stdout``; returns the calls."""
    calls: list = []

    def run_provider(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(pi, "run_provider", run_provider)
    return calls


# --------------------------------------------------------------------------------------
# (a) the login store: the real gathering path (a real file, the real reader and parser).
# --------------------------------------------------------------------------------------

def test_login_store_with_a_subscription_is_proven(login_env):
    assert sc.login_subscription_proven(login_env) is True


def test_proof_reads_the_process_login_when_no_env_is_given(tmp_path, monkeypatch):
    assert sc.login_subscription_proven() is False  # the fixture's empty home
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    write_store(tmp_path / "cfg", login_store())
    assert sc.login_subscription_proven() is True


@pytest.mark.parametrize("oauth", [
    {"subscriptionType": _ABSENT},
    {"subscriptionType": None},
    {"subscriptionType": ""},
    {"subscriptionType": "   "},
    {"subscriptionType": True},
    {"subscriptionType": 1},
    {"subscriptionType": ["max"]},
    {"subscriptionType": "ma\nx"},
    {"scopes": _ABSENT},
    {"scopes": []},
    {"scopes": ["user:profile"]},
    {"scopes": "user:inference"},
    {"accessToken": _ABSENT},
    {"accessToken": ""},
    {"accessToken": "has a space"},
], ids=lambda value: ",".join(f"{k}={'ABSENT' if v is _ABSENT else v!r}" for k, v in value.items()))
def test_login_store_without_the_subscription_facts_is_not_proven(tmp_path, oauth):
    config = tmp_path / "cfg"
    write_store(config, login_store(**oauth))
    assert sc.login_subscription_proven({"CLAUDE_CONFIG_DIR": str(config)}) is False


@pytest.mark.parametrize("raw", [
    b"", b"not-json", b"[]", b"null", b'{"claudeAiOauth": []}', b'{"claudeAiOauth": null}',
    b'{"mcpOAuth": {}}', b"[" * 100_000,
], ids=["empty", "not-json", "list", "null", "oauth-list", "oauth-null", "no-oauth", "deep"])
def test_malformed_login_store_is_not_proven(tmp_path, raw):
    config = tmp_path / "cfg"
    write_store(config, raw)
    assert sc.login_subscription_proven({"CLAUDE_CONFIG_DIR": str(config)}) is False


def test_absent_or_unsafe_login_store_is_not_proven(tmp_path):
    assert sc.login_subscription_proven({"CLAUDE_CONFIG_DIR": str(tmp_path / "none")}) is False
    writable = tmp_path / "writable"
    write_store(writable, login_store(), mode=0o666)
    assert sc.login_subscription_proven({"CLAUDE_CONFIG_DIR": str(writable)}) is False
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".credentials.json").symlink_to(write_store(tmp_path / "real", login_store()))
    assert sc.login_subscription_proven({"CLAUDE_CONFIG_DIR": str(linked)}) is False


def test_proof_is_about_the_store_the_seat_credential_is_drawn_from(tmp_path):
    """Two logins on one host. The proof follows the SAME env rule as the credential: whichever
    store ``resolve_claude_seat_credential`` takes the token from is the store that is judged."""
    home = tmp_path / "home"
    subscribed = home / ".claude"            # $HOME/.claude: a subscription login
    unsubscribed = tmp_path / "other-config"  # $CLAUDE_CONFIG_DIR: a login with no plan
    write_store(subscribed, login_store())
    write_store(unsubscribed, login_store(accessToken=OTHER_ACCESS, subscriptionType=_ABSENT))

    by_config_dir = {"CLAUDE_CONFIG_DIR": str(unsubscribed), "HOME": str(home)}
    assert sc.resolve_claude_seat_credential(0, env=by_config_dir).token == OTHER_ACCESS.encode()
    assert sc.login_subscription_proven(by_config_dir) is False

    by_home = {"HOME": str(home)}
    assert sc.resolve_claude_seat_credential(0, env=by_home).token == ACCESS.encode()
    assert sc.login_subscription_proven(by_home) is True


def test_a_brokered_leg_env_is_judged_on_the_login_its_seat_uses(tmp_path):
    """The broker allowlist drops CLAUDE_CONFIG_DIR, so a brokered seat's credential comes
    from ``$HOME/.claude``; the proof must follow it there, not stay with the launcher's."""
    home = tmp_path / "home"
    write_store(home / ".claude", login_store(subscriptionType=_ABSENT))
    write_store(tmp_path / "cfg", login_store(accessToken=OTHER_ACCESS))
    base = {"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"), "HOME": str(home), "PATH": "/usr/bin:/bin"}
    brokered = pi._broker_subscription_env(base)
    assert "CLAUDE_CONFIG_DIR" not in brokered
    assert sc.resolve_claude_seat_credential(0, env=brokered).token == ACCESS.encode()
    assert sc.login_subscription_proven(brokered) is False
    # The unbrokered leg keeps the config directory, and is judged on that login.
    direct = pi._subscription_env(base)
    assert sc.resolve_claude_seat_credential(0, env=direct).token == OTHER_ACCESS.encode()
    assert sc.login_subscription_proven(direct) is True


def test_keychain_login_is_judged_by_the_same_parser(tmp_path):
    def security(argv, **kwargs):
        assert argv[1] == "find-generic-password"
        return subprocess.CompletedProcess(argv, 0, stdout=security.raw, stderr=b"")

    def proven():
        return sc.login_subscription_proven(
            {"HOME": str(tmp_path)},
            read_store=lambda: sc.read_login_store(platform="darwin", env={"USER": "someone", "HOME": str(tmp_path)},
                                                   run=security))

    security.raw = login_store()
    assert proven() is True
    security.raw = login_store(subscriptionType=_ABSENT)
    assert proven() is False


def test_a_login_without_a_plan_is_still_a_login_for_presence_and_expiry(tmp_path):
    """The parser stays permissive: presence, expiry and the credential itself do not depend
    on the subscription facts. Only the subscription proof does."""
    config = tmp_path / "cfg"
    write_store(config, login_store(subscriptionType=_ABSENT, scopes=_ABSENT))
    login = sc.read_login_token(env={"CLAUDE_CONFIG_DIR": str(config)})
    assert login is not None and login.token == ACCESS.encode()
    assert login.expires_at == 4_102_444_800.0
    assert sc.claude_seat_credential_present(read_login=lambda: login) is True
    assert sc.resolve_claude_seat_credential(
        900, env={"CLAUDE_CONFIG_DIR": str(config)}).source == sc.SOURCE_LOGIN
    assert sc.login_subscription_proven({"CLAUDE_CONFIG_DIR": str(config)}) is False


def test_the_proof_is_a_boolean_and_the_credential_carries_nothing_new(login_env):
    """The seat credential is still the access token and its expiry, nothing else; the
    subscription question is answered with a bare boolean, never the plan's label."""
    assert sc.login_subscription_proven(login_env) is True
    login = sc.read_login_token(env=login_env)
    assert set(vars(login)) == {"token", "expires_at"}
    credential = sc.resolve_claude_seat_credential(0, env=login_env)
    assert set(vars(credential)) == {"token", "source", "expires_at", "notices"}
    held = repr(login) + repr(credential)
    assert PLAN not in held and REFRESH not in held and ACCESS not in held


# --------------------------------------------------------------------------------------
# The precheck: (a) AND (b).
# --------------------------------------------------------------------------------------

def test_seat_with_the_descriptor_token_is_admitted_when_its_login_is_a_subscription(
        monkeypatch, login_env):
    """The agent-harness#1444 fault: this real pair was refused."""
    calls = stub_seat(monkeypatch, seat_report())
    assert pi._claude_subscription_auth_ok(login_env) == (True, "")
    assert [argv for argv, _ in calls] == [["claude", "auth", "status", "--json"]]


def test_seat_report_cannot_stand_in_for_the_login(monkeypatch, tmp_path):
    """The login carries no subscription type; the seat ADVERSARIALLY reports the whole
    login-side shape, plan and all. The seat's word is not the proof."""
    config = tmp_path / "cfg"
    write_store(config, login_store(subscriptionType=_ABSENT))
    for stdout in (login_report(), seat_report(subscriptionType=PLAN)):
        stub_seat(monkeypatch, stdout)
        assert pi._claude_subscription_auth_ok({"CLAUDE_CONFIG_DIR": str(config)}) == UNPROVEN


def test_an_unproven_login_refuses_without_starting_the_seat_probe(monkeypatch, tmp_path):
    calls = stub_seat(monkeypatch, seat_report())
    assert pi._claude_subscription_auth_ok({"CLAUDE_CONFIG_DIR": str(tmp_path / "none")}) == UNPROVEN
    assert pi._claude_subscription_auth_ok({}) == UNPROVEN  # the process's (empty) home
    assert calls == []


def test_the_precheck_judges_the_env_it_was_given_not_the_process_login(
        monkeypatch, tmp_path, login_env):
    """A proven login in the PROCESS environment does not vouch for a leg whose env names
    another store, and the reverse."""
    stub_seat(monkeypatch, seat_report())
    unsubscribed = tmp_path / "unsubscribed"
    write_store(unsubscribed, login_store(subscriptionType=_ABSENT))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", login_env["CLAUDE_CONFIG_DIR"])
    assert pi._claude_subscription_auth_ok({"CLAUDE_CONFIG_DIR": str(unsubscribed)}) == UNPROVEN
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(unsubscribed))
    assert pi._claude_subscription_auth_ok(login_env) == (True, "")


@pytest.mark.parametrize("stdout", [
    seat_report(loggedIn=False),
    seat_report(loggedIn="true"),
    seat_report(loggedIn=1),
    seat_report(loggedIn=_ABSENT),
    seat_report(authMethod="api_key"),
    seat_report(authMethod="api_key_helper"),
    seat_report(authMethod="third_party"),
    seat_report(authMethod="none"),
    seat_report(authMethod="claude.ai"),
    seat_report(authMethod=_ABSENT),
    seat_report(authMethod=None),
    seat_report(apiProvider="bedrock"),
    seat_report(apiProvider="vertex"),
    seat_report(apiProvider="gateway"),
    seat_report(apiProvider=_ABSENT),
    seat_report(apiKeySource="ANTHROPIC_API_KEY"),
    seat_report(apiKeySource="apiKeyHelper"),
    seat_report(apiKeySource=None),
    login_report(),
    login_report(authMethod="api_key"),
    "not-json", "", "[]", "null", '"oauth_token"',
], ids=lambda raw: raw[:60].replace(" ", ""))
def test_a_seat_that_reports_anything_else_is_refused(monkeypatch, login_env, stdout):
    """The login is proven throughout: each refusal here is the SEAT's report."""
    assert sc.login_subscription_proven(login_env) is True
    calls = stub_seat(monkeypatch, stdout, stderr=EMAIL)
    assert pi._claude_subscription_auth_ok(login_env) == UNPROVEN
    assert len(calls) == 1


def test_a_seat_probe_that_fails_is_refused(monkeypatch, login_env):
    stub_seat(monkeypatch, seat_report(), returncode=1)
    assert pi._claude_subscription_auth_ok(login_env) == UNPROVEN
    for error in (FileNotFoundError("claude"), subprocess.TimeoutExpired("claude", 20)):
        def boom(*_args, _error=error, **_kwargs):
            raise _error
        monkeypatch.setattr(pi, "run_provider", boom)
        assert pi._claude_subscription_auth_ok(login_env) == UNPROVEN


def test_nothing_identifying_is_returned_logged_or_written(monkeypatch, tmp_path, login_env, caplog):
    caplog.set_level("DEBUG")
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    results = []
    for stdout in (seat_report(), login_report(), seat_report(authMethod="api_key"), "not-json"):
        stub_seat(monkeypatch, stdout, stderr=EMAIL)
        results.append(pi._claude_subscription_auth_ok(login_env))
    results.append(pi._claude_subscription_auth_ok({"CLAUDE_CONFIG_DIR": str(tmp_path / "none")}))
    evidence = repr(results) + caplog.text
    for secret in (EMAIL, ORG_ID, ORG_NAME, PLAN, ACCESS, REFRESH, "oauth_token", "loggedIn"):
        assert secret not in evidence
    assert set(results) == {(True, ""), UNPROVEN}
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


def test_the_seat_probe_runs_through_the_owner_with_the_leg_env(monkeypatch, login_env):
    calls = stub_seat(monkeypatch, seat_report())
    pi._claude_subscription_auth_ok(login_env, timeout_s=7)
    (argv, kwargs), = calls
    assert kwargs["timeout"] == 7 and kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["env"]["CLAUDE_CONFIG_DIR"] == login_env["CLAUDE_CONFIG_DIR"]
    assert "executor" not in kwargs  # a seat, never the operator's own CLI


# --------------------------------------------------------------------------------------
# _exec_claude_tui_leg: the seat launches, or it does not.
# --------------------------------------------------------------------------------------

class _Launched(Exception):
    pass


def _stage(tmp_path):
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    (review_dir / "review-bundle.md").write_text("bundle", encoding="utf-8")
    (review_dir / "review-instructions.md").write_text("instructions", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    return review_dir, out_dir


ROUTES = ("print", "tui")


def _leg(monkeypatch, tmp_path, env, route):
    """The real ``_exec_claude_tui_leg`` with the real precheck, on ``route``; the session
    itself is replaced. Returns the outcome and the launches."""
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", route)
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a, **k: (True, "supported"))
    launched = []

    def tui_session(**kwargs):
        launched.append(("tui", list(kwargs["command"])))
        raise _Launched

    def print_session(command, prompt, **kwargs):
        launched.append(("print", list(command)))
        raise _Launched

    monkeypatch.setattr(pi, "_run_claude_tui_session", tui_session)
    monkeypatch.setattr(pi, "_run_claude_print_session", print_session)
    review_dir, out_dir = _stage(tmp_path)
    try:
        outcome = pi._exec_claude_tui_leg(review_dir, out_dir, 60, "bundle", env=env)
    except _Launched:
        outcome = "launched"
    return outcome, launched


@pytest.mark.parametrize("route", ROUTES)
def test_the_real_precheck_lets_the_seat_launch_on_either_route(
        monkeypatch, tmp_path, login_env, route):
    """The fault agent-harness#1444 reported: the seat-side shape with a proven login."""
    assert pi._claude_subscription_auth_ok is pi._PRODUCTION_CLAUDE_SUBSCRIPTION_AUTH_OK
    stub_seat(monkeypatch, seat_report())
    outcome, launched = _leg(monkeypatch, tmp_path, login_env, route)
    assert outcome == "launched" and [kind for kind, _ in launched] == [route]
    assert launched[0][1][0] == "claude" and ("-p" in launched[0][1]) is (route == "print")


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("oauth, stdout", [
    ({"subscriptionType": _ABSENT}, seat_report()),
    ({"scopes": ["user:profile"]}, seat_report()),
    ({"subscriptionType": _ABSENT}, login_report()),
    ({}, seat_report(authMethod="api_key")),
    ({}, seat_report(loggedIn=False)),
    ({}, seat_report(apiProvider="bedrock")),
    ({}, seat_report(apiKeySource="ANTHROPIC_API_KEY")),
    ({}, login_report()),
], ids=["login-no-plan", "login-no-inference-scope", "login-no-plan-seat-claims-one",
        "seat-api-key", "seat-logged-out", "seat-third-party", "seat-sees-api-key",
        "seat-reports-a-login-of-its-own"])
def test_the_real_precheck_never_launches_an_unproven_seat_on_either_route(
        monkeypatch, tmp_path, oauth, stdout, route):
    """The first two cells are what main admitted after agent-harness#1446: a seat reporting
    the runtime's own delivery on a host whose login shows no subscription."""
    config = tmp_path / "cfg"
    write_store(config, login_store(**oauth))
    stub_seat(monkeypatch, stdout)
    outcome, launched = _leg(monkeypatch, tmp_path, {"CLAUDE_CONFIG_DIR": str(config)}, route)
    assert outcome == ("UNAVAILABLE", "subscription_auth_unproven") and launched == []


# --------------------------------------------------------------------------------------
# The caller's own credential (agent-harness#1446's guard, kept as a refusal of its own).
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", [
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
])
def test_a_caller_env_carrying_its_own_credential_is_refused_unprobed(
        monkeypatch, login_env, key):
    """Everything else holds (a proven login, a seat reporting the delivered token): the
    caller's own credential is the one reason, and neither the login nor the seat is asked."""
    calls = stub_seat(monkeypatch, seat_report())
    assert pi._claude_subscription_auth_ok(login_env) == (True, "")
    del calls[:]
    read = []
    real = sc.login_subscription_proven
    monkeypatch.setattr(sc, "login_subscription_proven",
                        lambda *a, **k: read.append(1) or real(*a, **k))
    assert pi._claude_subscription_auth_ok({**login_env, key: "caller-value"}) == UNPROVEN
    assert calls == [] and read == []


@pytest.mark.parametrize("route", ROUTES)
def test_a_caller_credential_never_launches_a_seat_on_either_route(
        monkeypatch, tmp_path, login_env, route):
    # `_subscription_env` keeps CLAUDE_CODE_OAUTH_TOKEN, so the gate is what refuses it.
    stub_seat(monkeypatch, seat_report())
    outcome, launched = _leg(monkeypatch, tmp_path,
                             {**login_env, "CLAUDE_CODE_OAUTH_TOKEN": "caller"}, route)
    assert outcome == ("UNAVAILABLE", "subscription_auth_unproven") and launched == []


def test_the_reviewtruth_probe_env_is_judged_on_the_login_it_names(monkeypatch, login_env):
    """``legible_evidence`` calls the same precheck with ``_subscription_env()``; that env
    keeps the config directory, so its proof is about the process's own login."""
    stub_seat(monkeypatch, seat_report())
    assert pi._claude_subscription_auth_ok(pi._subscription_env()) == UNPROVEN
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", login_env["CLAUDE_CONFIG_DIR"])
    assert pi._claude_subscription_auth_ok(pi._subscription_env()) == (True, "")


# --------------------------------------------------------------------------------------
# The Claude executor preflight (launcher.run_auth_preflight): the same probe, same fault.
# --------------------------------------------------------------------------------------

_CLAUDE_PROBES = ("claude --version", "claude --help", "claude auth status")


def _preflight(monkeypatch, status_stdout, *, status_rc: int = 0):
    spec = types.SimpleNamespace(auth_preflight_mode="metadata_only", executor="claude",
                                 auth_preflight_probes=_CLAUDE_PROBES)
    seen = []
    # The preflight judges the process env: keep the developer's own credentials out of it.
    for key in list(os.environ):
        if pi._claude_caller_supplied_credential({key: ""}):
            monkeypatch.delenv(key)

    def run_provider(argv, **kwargs):
        seen.append(list(argv))
        if list(argv) == ["claude", "auth", "status"]:
            return subprocess.CompletedProcess(argv, status_rc, status_stdout, "")
        return subprocess.CompletedProcess(argv, 0, "2.1.295 (Claude Code)\n", "")

    monkeypatch.setattr(pi, "run_provider", run_provider)
    return launcher.run_auth_preflight(spec), seen


def test_executor_preflight_passes_on_the_seat_report_when_the_login_is_a_subscription(
        monkeypatch, login_env):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", login_env["CLAUDE_CONFIG_DIR"])
    result, seen = _preflight(monkeypatch, seat_report())
    assert result.ok is True, result.blocker_summary
    assert result.metadata["auth_status"]["logged_in"] is True
    assert result.metadata["auth_status"]["subscription_present"] is True
    assert ["claude", "auth", "status"] in seen


def test_executor_preflight_blocks_a_login_without_a_subscription(monkeypatch, tmp_path):
    write_store(tmp_path / "cfg", login_store(subscriptionType=_ABSENT))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    # The second report ADVERSARIALLY carries a plan: the probe's word is not the proof.
    for stdout in (seat_report(), seat_report(subscriptionType=PLAN), login_report()):
        result, _ = _preflight(monkeypatch, stdout)
        assert result.ok is False
        assert result.blocker_class == "account_or_billing_setup"
        assert "subscription" in result.blocker_summary
        assert result.metadata["auth_status"]["subscription_present"] is False


def test_executor_preflight_blocks_a_logged_out_probe_before_reading_the_login(
        monkeypatch, login_env):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", login_env["CLAUDE_CONFIG_DIR"])
    read = []
    real = sc.login_subscription_proven
    monkeypatch.setattr(sc, "login_subscription_proven",
                        lambda *a, **k: read.append(1) or real(*a, **k))
    for stdout in (seat_report(loggedIn=False), "not-json", ""):
        result, _ = _preflight(monkeypatch, stdout)
        assert result.ok is False and "not logged in" in result.blocker_summary
        assert result.metadata["auth_status"]["subscription_present"] is False
    assert read == []
    result, _ = _preflight(monkeypatch, seat_report())
    assert result.ok is True and read == [1]


_SEAT = {"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"}


@pytest.mark.parametrize("status, caller_key", [
    ({"loggedIn": True}, None),
    ({**_SEAT, "loggedIn": "false"}, None),
    ({**_SEAT, "authMethod": "api_key", "apiKeySource": "ANTHROPIC_API_KEY"}, None),
    ({**_SEAT, "apiProvider": "bedrock"}, None),
    ({**_SEAT, "apiKeySource": None}, None),
    (_SEAT, "CLAUDE_CODE_OAUTH_TOKEN"),
    (_SEAT, "ANTHROPIC_API_KEY"),
    ({**_SEAT, "authMethod": "claude.ai"}, None),
], ids=["fields-missing", "loggedIn-string", "api-key", "third-party", "apiKeySource-present",
        "caller-oauth-token", "caller-anthropic-variable", "seat-reports-a-login-of-its-own"])
def test_executor_preflight_holds_the_seat_gate_on_a_proven_login(
        monkeypatch, login_env, status, caller_key):
    """The executor preflight applies the seat gate's caller guard and seat report on top of
    the login proof: with a proven subscription login, each of these is still refused, with
    one summary that is true whatever the cause and no variable name in the metadata."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", login_env["CLAUDE_CONFIG_DIR"])
    spec = types.SimpleNamespace(auth_preflight_mode="metadata_only", executor="claude",
                                 auth_preflight_probes=_CLAUDE_PROBES)

    def run_provider(argv, **kwargs):
        if list(argv) == ["claude", "auth", "status"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(status), "")
        return subprocess.CompletedProcess(argv, 0, "2.1.296 (Claude Code)\n", "")

    for key in list(os.environ):
        if pi._claude_caller_supplied_credential({key: ""}):
            monkeypatch.delenv(key)
    if caller_key:
        monkeypatch.setenv(caller_key, "fake-caller-value")
    monkeypatch.setattr(pi, "run_provider", run_provider)
    result = launcher.run_auth_preflight(spec)
    assert result.ok is False
    assert result.blocker_class == "account_or_billing_setup"
    assert result.metadata["auth_status"]["subscription_present"] is False
    if status.get("loggedIn") is True:
        assert result.blocker_summary == (
            "Claude CLI is logged in, but the Claude subscription is not proven.")
    rendered = json.dumps(result.metadata, sort_keys=True) + str(result.blocker_summary)
    for leaked in ("fake-caller-value", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", ACCESS):
        assert leaked not in rendered


def test_executor_preflight_admits_a_proven_login_with_a_clean_env_and_seat(
        monkeypatch, login_env):
    """Positive control for the states above: proven login, no caller credential, and the
    seat's ``oauth_token``/``firstParty`` report."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", login_env["CLAUDE_CONFIG_DIR"])
    result, _ = _preflight(monkeypatch, json.dumps(_SEAT))
    assert result.ok is True, result.blocker_summary
    assert result.metadata["auth_status"]["logged_in"] is True
    assert result.metadata["auth_status"]["subscription_present"] is True


def test_executor_preflight_metadata_carries_no_identity_or_plan(monkeypatch, login_env):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", login_env["CLAUDE_CONFIG_DIR"])
    for stdout in (seat_report(), login_report()):
        result, _ = _preflight(monkeypatch, stdout)
        rendered = json.dumps(result.metadata, sort_keys=True) + str(result.blocker_summary)
        for secret in (EMAIL, ORG_ID, ORG_NAME, PLAN, ACCESS, REFRESH):
            assert secret not in rendered


# --------------------------------------------------------------------------------------
# Both credential sources: a bound seat-token override is judged on the launching
# session's login, the one it must be bound to.
# --------------------------------------------------------------------------------------

OVERRIDE = b"fake-seat-override-" + b"o" * 24


def _session_with_override(tmp_path, monkeypatch, **oauth):
    """A session logged in to acct-A/org-A in its config dir, with an override stored while
    logged in to it (through the real store), and that session's login store."""
    config = tmp_path / "session-config"
    config.mkdir()
    account = config / ".claude.json"
    account.write_text(json.dumps({"oauthAccount": {"accountUuid": "acct-A",
                                                    "organizationUuid": "org-A"}}))
    os.chmod(account, 0o600)
    write_store(config, login_store(**oauth))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    sc.store_override(OVERRIDE)
    return {"CLAUDE_CONFIG_DIR": str(config), "PATH": "/usr/bin:/bin"}


def test_a_bound_override_seat_is_admitted_when_the_session_login_is_a_subscription(
        monkeypatch, tmp_path):
    env = _session_with_override(tmp_path, monkeypatch)
    credential = sc.resolve_claude_seat_credential(0, env=env)
    assert (credential.source, credential.token) == (sc.SOURCE_OVERRIDE, OVERRIDE)
    stub_seat(monkeypatch, seat_report())
    assert pi._claude_subscription_auth_ok(env) == (True, "")


def test_a_bound_override_seat_is_refused_when_the_session_login_shows_no_subscription(
        monkeypatch, tmp_path):
    env = _session_with_override(tmp_path, monkeypatch, subscriptionType=_ABSENT)
    assert sc.resolve_claude_seat_credential(0, env=env).source == sc.SOURCE_OVERRIDE
    calls = stub_seat(monkeypatch, seat_report())
    assert pi._claude_subscription_auth_ok(env) == UNPROVEN
    assert calls == []
