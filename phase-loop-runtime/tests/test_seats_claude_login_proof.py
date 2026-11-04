"""SEATS CLAUDE, IF-0-CLAUDE-4: the jailed Claude seat's login proof and the seat-mode
republish (EC-CLAUDE-7, agent-harness#1532, agent-harness#1255).

Every check runs the real proof against a real login store on disk; the auth-status probe
is the only stand-in, and each stand-in is a failing control except the one that answers as
a proven subscription login does.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path

import pytest

from phase_loop_runtime import seat_credentials as sc
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_preflight as sp

# Obviously fake values, built so no secret scanner mistakes them for real credentials.
ACCESS = "fake-login-access-" + "a" * 24
OTHER = "fake-other-access-" + "b" * 24
OVERRIDE = b"fake-seat-override-" + b"o" * 24
EMAIL = "seat-owner@example.invalid"
ACCOUNT = "11111111-2222-3333-4444-555555555555"
ORG = "66666666-7777-8888-9999-000000000000"


def _store(access: str = ACCESS, *, subscription: str | None = "max") -> bytes:
    oauth: dict[str, object] = {"accessToken": access, "refreshToken": "fake-refresh-" + "r" * 16,
                                "expiresAt": 4_102_444_800_000, "scopes": ["user:inference"]}
    if subscription is not None:
        oauth["subscriptionType"] = subscription
    return json.dumps({"claudeAiOauth": oauth}).encode()


def _write(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(raw)
    os.chmod(path, mode)


@pytest.fixture(autouse=True)
def _no_host_login(tmp_path, monkeypatch):
    """The host's own login and override can never satisfy a test."""
    home = tmp_path / "process-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.fixture
def caller_env(tmp_path):
    config = tmp_path / "login" / ".claude"
    _write(config / ".credentials.json", _store())
    return {"CLAUDE_CONFIG_DIR": str(config), "HOME": str(tmp_path / "login"),
            "PATH": "/usr/bin:/bin"}


def _login() -> sc.SeatCredential:
    return sc.SeatCredential(ACCESS.encode(), sc.SOURCE_LOGIN, 4_102_444_800.0)


def _status(**overrides: object) -> bytes:
    status: dict[str, object] = {"loggedIn": True, "authMethod": "oauth_token",
                                 "apiProvider": "firstParty", "email": EMAIL,
                                 "orgId": ORG, "subscriptionType": "max"}
    status.update(overrides)
    return json.dumps({k: v for k, v in status.items() if v is not None}).encode()


def _probe(stdout: bytes = b"", *, returncode: int = 0, token: bytes | None = None, calls=None):
    """A probe that reports the digest of the credential it was handed (or of ``token``)."""

    def probe(credential: bytes) -> sc.AuthProbeResult:
        if calls is not None:
            calls.append(credential)
        delivered = credential if token is None else token
        return sc.AuthProbeResult(hashlib.sha256(delivered).hexdigest(), returncode,
                                  stdout or _status())
    return probe


# --------------------------------------------------------------------------------------
# The three checks.
# --------------------------------------------------------------------------------------

def test_a_proven_login_yields_a_closed_proof(caller_env):
    calls: list[bytes] = []
    proof = sc.jailed_login_proof(_login(), _probe(calls=calls), caller_env)
    assert calls == [ACCESS.encode()]  # single use, on the exact credential
    assert proof == sc.LoginProof(sc.SOURCE_LOGIN, "oauth_token", "none")


def test_the_proof_type_has_no_identity_field():
    assert {f.name for f in dataclasses.fields(sc.LoginProof)} == {
        "source", "auth_method", "api_key_source"}
    with pytest.raises(ValueError):
        sc.LoginProof(sc.SOURCE_LOGIN, "claude.ai", "none")
    with pytest.raises(ValueError):
        sc.LoginProof(sc.SOURCE_LOGIN, "oauth_token", "present")


def test_a_store_pass_with_a_failed_probe_refuses(caller_env):
    with pytest.raises(sc.LoginUnproven) as caught:
        sc.jailed_login_proof(_login(), _probe(returncode=1), caller_env)
    assert caught.value.code == sc.LOGIN_UNPROVEN


def test_a_probe_on_another_credential_refuses(caller_env):
    with pytest.raises(sc.LoginUnproven) as caught:
        sc.jailed_login_proof(_login(), _probe(token=OTHER.encode()), caller_env)
    assert (caught.value.code, caught.value.reason) == (sc.LOGIN_UNPROVEN, "probe_credential")


@pytest.mark.parametrize("variable", [
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
])
def test_a_caller_credential_variable_refuses_before_any_probe(caller_env, variable):
    calls: list[bytes] = []
    with pytest.raises(sc.LoginUnproven) as caught:
        sc.jailed_login_proof(_login(), _probe(calls=calls), {**caller_env, variable: "x"})
    assert (caught.value.code, caught.value.reason) == (sc.LOGIN_UNPROVEN, "caller_credential")
    assert calls == []


def test_a_login_without_a_subscription_refuses_before_any_probe(tmp_path):
    config = tmp_path / "nosub" / ".claude"
    _write(config / ".credentials.json", _store(subscription=None))
    calls: list[bytes] = []
    with pytest.raises(sc.LoginUnproven) as caught:
        sc.jailed_login_proof(_login(), _probe(calls=calls),
                              {"CLAUDE_CONFIG_DIR": str(config), "HOME": str(tmp_path)})
    assert caught.value.reason == "subscription"
    assert calls == []


@pytest.mark.parametrize("stdout", [
    _status(authMethod="claude.ai"),
    _status(authMethod="api_key"),
    _status(authMethod=None),
    _status(apiKeySource="ANTHROPIC_API_KEY"),
    _status(apiKeySource="none"),
    _status(apiKeySource="/login managed key"),
    _status(loggedIn=False),
    _status(apiProvider="bedrock"),
    b'{"loggedIn": true, "loggedIn": true, "authMethod": "oauth_token", "apiProvider": "firstParty"}',
    b"[" * 5000 + b"]" * 5000,
    b"not json",
    b"\xff\xfe",
    b"{" + b" " * (sc.PROBE_OUTPUT_CAP_BYTES + 1) + b"}",
])
def test_probe_output_that_is_not_a_subscription_oauth_login_refuses(caller_env, stdout):
    with pytest.raises(sc.LoginUnproven) as caught:
        sc.jailed_login_proof(_login(), _probe(stdout), caller_env)
    assert caught.value.code == sc.LOGIN_UNPROVEN


def test_a_token_in_probe_output_refuses_as_token_in_output(caller_env):
    with pytest.raises(sc.LoginUnproven) as caught:
        sc.jailed_login_proof(_login(), _probe(_status(email=ACCESS)), caller_env)
    assert caught.value.code == sc.TOKEN_IN_OUTPUT
    assert ACCESS not in str(caught.value)


def test_identity_in_probe_output_never_reaches_the_proof_or_its_evidence(caller_env):
    proof = sc.jailed_login_proof(_login(), _probe(), caller_env)
    kept = json.dumps(proof.as_evidence()) + repr(proof) + json.dumps(dataclasses.asdict(proof))
    for value in (EMAIL, ORG, ACCESS, "max"):
        assert value not in kept


def test_a_refusal_carries_a_slug_never_probe_text(caller_env):
    with pytest.raises(sc.LoginUnproven) as caught:
        sc.jailed_login_proof(_login(), _probe(_status(authMethod=EMAIL)), caller_env)
    assert EMAIL not in str(caught.value)


# --------------------------------------------------------------------------------------
# The override credential keeps its account binding.
# --------------------------------------------------------------------------------------

def _bind_override(tmp_path: Path, caller_env: dict, *, account: str = ACCOUNT) -> None:
    record = seat_jail.claude_seat_token_path()
    record = record.with_name(record.name + ".override.json")
    _write(record, json.dumps({"schema": sc.RECORD_SCHEMA, "account": account,
                               "organization": ORG, "token": OVERRIDE.decode()}).encode())
    os.chmod(record.parent, 0o700)
    _write(Path(caller_env["CLAUDE_CONFIG_DIR"]) / ".claude.json",
           json.dumps({"oauthAccount": {"accountUuid": ACCOUNT, "organizationUuid": ORG}}).encode())


def test_an_override_still_bound_to_the_session_is_proven(tmp_path, caller_env):
    _bind_override(tmp_path, caller_env)
    proof = sc.jailed_login_proof(sc.SeatCredential(OVERRIDE, sc.SOURCE_OVERRIDE),
                                  _probe(), caller_env)
    assert proof.source == sc.SOURCE_OVERRIDE


def test_an_override_no_longer_bound_to_the_session_refuses(tmp_path, caller_env):
    _bind_override(tmp_path, caller_env, account="99999999-2222-3333-4444-555555555555")
    calls: list[bytes] = []
    with pytest.raises(sc.LoginUnproven) as caught:
        sc.jailed_login_proof(sc.SeatCredential(OVERRIDE, sc.SOURCE_OVERRIDE),
                              _probe(calls=calls), caller_env)
    assert caught.value.reason == "override_binding" and calls == []


def test_an_override_whose_bytes_differ_from_the_bound_record_refuses(tmp_path, caller_env):
    _bind_override(tmp_path, caller_env)
    with pytest.raises(sc.LoginUnproven) as caught:
        sc.jailed_login_proof(sc.SeatCredential(b"fake-other-override-" + b"z" * 24,
                                                sc.SOURCE_OVERRIDE), _probe(), caller_env)
    assert caught.value.reason == "override_binding"


# --------------------------------------------------------------------------------------
# agent-harness#1255: a timed-out login wait republishes the seat's mode.
# --------------------------------------------------------------------------------------

def _published(stream: Path) -> list[sp.SeatMode]:
    rows = [
        sp.SeatMode("panel-claude", "claude", sp.MODE_JAILED,
                    "claude_seat_login_token_awaiting_refresh", "why", "fix", sc.SOURCE_LOGIN, 0),
        sp.SeatMode("panel-codex", "codex", sp.MODE_UNCONFINED, None, "why", "", None, 1),
    ]
    sp.write_modes_record(stream, rows)
    return rows


@pytest.mark.parametrize("code", ["claude_seat_login_token_expiring", "claude_seat_token_missing"])
def test_a_timed_out_wait_republishes_a_degraded_row_with_the_notice_text(tmp_path, code):
    stream = tmp_path / "stream"
    rows = _published(stream)
    before = json.loads((stream / sp.MODES_FILE).read_text())["modes"][1]
    _what, why, fix = seat_jail.NOTICES[code]
    sp.republish_seat_mode(stream, sp.SeatMode("panel-claude", "claude", sp.MODE_DEGRADED,
                                               code, why, fix, None, 0))
    record = json.loads((stream / sp.MODES_FILE).read_text())
    assert record["schema"] == sp.MODES_SCHEMA
    claude, codex = record["modes"]
    assert (claude["mode"], claude["code"], claude["why"], claude["fix"]) == (
        sp.MODE_DEGRADED, code, why, fix)
    assert codex == before == rows[1].as_json()


def test_republish_without_a_matching_row_refuses_and_leaves_the_record(tmp_path):
    stream = tmp_path / "stream"
    _published(stream)
    before = (stream / sp.MODES_FILE).read_bytes()
    for mode in (sp.SeatMode("panel-gemini", "gemini", sp.MODE_DEGRADED, None, "w", "f"),
                 sp.SeatMode("panel-codex", "claude", sp.MODE_DEGRADED, None, "w", "f", None, 1)):
        with pytest.raises(ValueError):
            sp.republish_seat_mode(stream, mode)
    assert (stream / sp.MODES_FILE).read_bytes() == before
    with pytest.raises(ValueError):
        sp.republish_seat_mode(tmp_path / "unpublished",
                               sp.SeatMode("panel-claude", "claude", sp.MODE_DEGRADED, None, "w", "f"))
