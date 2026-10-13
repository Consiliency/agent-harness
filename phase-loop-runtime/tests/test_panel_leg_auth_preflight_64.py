"""#64 — advisor-panel leg auth preflight + soft-empty-turn retry.

A logged-out CLI (verified root cause) makes codex fail obliquely — an empty-turn
(`rc=0`, empty `--output-last-message`) then rate-limit errors — so the panel
silently degrades and the failure is misdiagnosed. The preflight catches a
de-authed leg at launch (DEGRADED, not a silent empty leg); the retry recovers
the genuinely-transient soft empty-turn without hammering a hard failure.
"""

from __future__ import annotations

import types
import json

import pytest

import phase_loop_runtime.panel_invoker as pi


def _stage(tmp_path):
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    (review_dir / "review-bundle.md").write_text("bundle", encoding="utf-8")
    (review_dir / "review-instructions.md").write_text("instructions", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    return review_dir, out_dir


# --- _leg_auth_ok --------------------------------------------------------------

def test_auth_ok_when_logged_in(monkeypatch):
    monkeypatch.setattr(
        pi, "run_provider",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="Logged in as x", stderr=""),
    )
    ok, detail = pi._leg_auth_ok("codex", {})
    assert ok and detail == ""


def test_auth_fails_and_classifies_degraded_when_logged_out(monkeypatch):
    monkeypatch.setattr(
        pi, "run_provider",
        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="not logged in"),
    )
    ok, detail = pi._leg_auth_ok("codex", {})
    assert not ok
    assert pi._AUTH_SIGNATURE.search(detail), "detail must carry an auth signature"
    assert pi._classify_leg(1, "", detail) == "DEGRADED"  # not EMPTY, not a silent pass


def test_auth_no_probe_fails_open_without_subprocess(monkeypatch):
    called = []
    monkeypatch.setattr(pi, "run_provider", lambda *a, **k: called.append(1))
    ok, detail = pi._leg_auth_ok("gemini", {})  # no probe registered
    assert ok and detail == "" and not called


def test_auth_probe_missing_cli_fails_open(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(pi, "run_provider", boom)
    ok, _ = pi._leg_auth_ok("codex", {})
    assert ok  # a flaky/absent probe must never block the leg


@pytest.mark.parametrize("returncode,output", [(126, ""), (127, "not logged in"),
    (1, "sh: codex: command not found"), (1, "sh: /missing/codex: No such file or directory"),
    (1, "bash: line 1: codex: command not found"),
    (1, "/bin/sh: 1: /missing/codex: No such file or directory"),
    (1, "command not found"), (1, "No such file"), (1, "No such file or directory")])
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_auth_probe_unavailable_executable_is_inconclusive(monkeypatch, returncode, output, stream):
    result = types.SimpleNamespace(returncode=returncode, stdout="", stderr="")
    setattr(result, stream, output)
    monkeypatch.setattr(pi, "run_provider", lambda *a, **k: result)
    assert pi._leg_auth_ok("codex", {}) == (True, "")


@pytest.mark.parametrize("output", [
    "not logged in: cannot read credentials: No such file or directory: /home/operator/.codex/auth.json",
    "cannot read /home/operator/.codex/auth.json: No such file or directory",
    "codex: No such file or directory: /home/operator/.codex/auth.json",
    "codex: No such file while reading /home/operator/.codex/auth.json",
    "cannot read /home/operator/.codex/auth.json: codex: No such file or directory",
    "codex: No such file or directory\ncannot read /home/operator/.codex/auth.json",
])
def test_auth_probe_missing_credentials_remains_a_failure(monkeypatch, output):
    result = types.SimpleNamespace(returncode=1, stdout="", stderr=output)
    monkeypatch.setattr(pi, "run_provider", lambda *a, **k: result)
    ok, detail = pi._leg_auth_ok("codex", {})
    assert not ok
    assert pi._AUTH_SIGNATURE.search(detail)


# --- strict Claude.ai subscription preflight -----------------------------------
# agent-harness#1444: the seat holds the login's access token alone, so the subscription is
# proven from the login store the credential is drawn from and the seat reports only
# logged-in / first-party / the descriptor-delivered token. Both real shapes, in depth:
# ``test_claude_seat_subscription_proof_1444.py``.

def _claude_auth_payload(**overrides):
    payload = {
        "loggedIn": True,
        "authMethod": "oauth_token",
        "apiProvider": "firstParty",
        "email": "private@example.invalid",
        "orgId": "org-secret",
        "orgName": "private org",
    }
    payload.update(overrides)
    return json.dumps(payload)


def _login_env(tmp_path, **oauth_overrides):
    """A leg env whose login store is a subscription login (or, overridden, is not)."""
    oauth = {"accessToken": "fake-login-access-" + "a" * 24, "expiresAt": 4_102_444_800_000,
             "scopes": ["user:inference"], "subscriptionType": "max"}
    oauth.update(oauth_overrides)
    config = tmp_path / "login-config"
    config.mkdir(exist_ok=True)
    store = config / ".credentials.json"
    store.write_text(json.dumps({"claudeAiOauth": oauth}), encoding="utf-8")
    store.chmod(0o600)
    return {"CLAUDE_CONFIG_DIR": str(config), "PATH": "/usr/bin"}


def test_claude_subscription_auth_accepts_only_proven_first_party(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pi,
        "run_provider",
        lambda *a, **k: types.SimpleNamespace(
            returncode=0, stdout=_claude_auth_payload(), stderr=""
        ),
    )
    ok, detail = pi._claude_subscription_auth_ok(_login_env(tmp_path))
    assert ok and detail == ""


def test_claude_subscription_auth_rejects_every_unproven_shape(monkeypatch, tmp_path):
    proven = _login_env(tmp_path)
    rejected = (
        (proven, _claude_auth_payload(loggedIn=False)),
        (proven, _claude_auth_payload(authMethod="apiKey")),
        (proven, _claude_auth_payload(apiProvider="bedrock")),
        (proven, "not-json"),
        # The login shows no subscription; a seat that claims one is not believed.
        (lambda: _login_env(tmp_path, subscriptionType=""), _claude_auth_payload()),
        (lambda: _login_env(tmp_path, subscriptionType=None),
         _claude_auth_payload(authMethod="claude.ai", subscriptionType="max")),
    )
    for env, raw in rejected:
        monkeypatch.setattr(
            pi,
            "run_provider",
            lambda *a, _raw=raw, **k: types.SimpleNamespace(
                returncode=0, stdout=_raw, stderr="private@example.invalid"
            ),
        )
        assert pi._claude_subscription_auth_ok(env() if callable(env) else env) == (
            False,
            "subscription_auth_unproven",
        )


def test_claude_subscription_auth_does_not_return_or_persist_identity(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(
        pi,
        "run_provider",
        lambda *a, **k: types.SimpleNamespace(
            returncode=0, stdout=_claude_auth_payload(), stderr=""
        ),
    )
    result = pi._claude_subscription_auth_ok(_login_env(tmp_path))
    assert result == (True, "")
    evidence = repr(result) + caplog.text
    assert "private@example.invalid" not in evidence
    assert "org-secret" not in evidence
    assert "private org" not in evidence


@pytest.mark.parametrize("route", ["tui", "print"])
def test_claude_unproven_auth_never_launches_tui(tmp_path, monkeypatch, route):
    review_dir, out_dir = _stage(tmp_path)
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", route)
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda **k: (True, "supported"))
    monkeypatch.setattr(
        pi,
        "_claude_subscription_auth_ok",
        lambda env: (False, "subscription_auth_unproven"),
    )
    launched = []
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **kwargs: launched.append(kwargs))
    monkeypatch.setattr(pi, "_run_claude_print_session", lambda *a, **k: launched.append(k))
    monkeypatch.setattr(pi, "_run_leg_with_liveness", lambda *a, **k: launched.append(k))
    status, detail = pi._exec_claude_tui_leg(
        review_dir, out_dir, 60, "bundle", env={}
    )
    assert (status, detail) == ("UNAVAILABLE", "subscription_auth_unproven")
    assert launched == []


# --- _exec_leg codex path ------------------------------------------------------

def test_exec_leg_codex_blocks_when_preflight_fails(tmp_path, monkeypatch):
    review_dir, out_dir = _stage(tmp_path)

    def fake_run(cmd, **k):
        if list(cmd[:3]) == ["codex", "login", "status"]:
            return types.SimpleNamespace(returncode=1, stdout="", stderr="not logged in")
        raise AssertionError("codex exec must NOT run when the auth preflight fails")

    monkeypatch.setattr(pi, "run_provider", fake_run)
    rc, review, log = pi._exec_leg("codex", review_dir, out_dir, timeout_s=60)
    assert rc != 0 and not review
    assert "not logged in" in log
    assert pi._classify_leg(rc, review, log) == "DEGRADED"


def test_exec_leg_codex_retries_soft_empty_turn(tmp_path, monkeypatch):
    review_dir, out_dir = _stage(tmp_path)
    out_file = out_dir / "panel-codex.txt"
    calls = {"exec": 0}

    # Auth preflight uses the owned administrative seam; keep it logged-in.
    monkeypatch.setattr(
        pi, "run_provider",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="logged in", stderr=""),
    )

    # the leg exec now goes through _run_leg_with_liveness; the codex verdict is the
    # out_file (--output-last-message), so simulate an empty first turn then a real one.
    def fake_liveness(cmd, **k):
        calls["exec"] += 1
        out_file.write_text("" if calls["exec"] == 1 else "PARTIALLY AGREE\n", encoding="utf-8")
        return pi._LegRun(0, "transcript", "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
    rc, review, log = pi._exec_leg("codex", review_dir, out_dir, timeout_s=60)
    assert calls["exec"] == 2, "a soft empty-turn (rc=0 + empty) must be retried once"
    assert review.strip() == "PARTIALLY AGREE"


def test_exec_leg_codex_does_not_retry_hard_failure(tmp_path, monkeypatch):
    review_dir, out_dir = _stage(tmp_path)
    out_file = out_dir / "panel-codex.txt"
    calls = {"exec": 0}

    monkeypatch.setattr(
        pi, "run_provider",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="logged in", stderr=""),
    )

    def fake_liveness(cmd, **k):
        calls["exec"] += 1
        out_file.write_text("", encoding="utf-8")
        return pi._LegRun(1, "", "rate limit")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
    rc, review, log = pi._exec_leg("codex", review_dir, out_dir, timeout_s=60)
    assert calls["exec"] == 1, "a hard failure (rc!=0) must NOT be retried (never hammer)"
    assert rc == 1
