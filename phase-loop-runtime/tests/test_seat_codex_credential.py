"""SEATS CODEX SL-1.3 (agent-harness#1820): the Codex seat credential copy (IF-0-CODEX-2).

Every login here is synthetic: no test reads the developer's own Codex login. The one
measurement at the end (SL-1.5) runs only when a developer opts in on their own host.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import time
import urllib.request
from pathlib import Path

import pytest

from phase_loop_runtime import seat_codex_credential as cred
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_route_contract as contract


NOW = 1_800_000_000.0
ACCESS = "access-token-fixture"
ID = "id-token-fixture"
REFRESH = "refresh-token-fixture-must-not-reach-the-seat"
ACCOUNT = "account-fixture-0001"

# The IF-0-CODEX-5 classes of the codes this lane raises.
LANE_CODES = {
    "codex_seat_credential_missing": "ordinary",
    "codex_seat_api_key_refused": "ordinary",
    "codex_seat_token_expiring": "ordinary",
    "codex_seat_token_scope_excess": "security",
}
UNSAFE = "seat_sandbox_refused:token_file_unsafe"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _jwt(claims: object, *, marker: str = ACCESS) -> str:
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    return f"{header}.{_b64(json.dumps(claims).encode())}.{_b64(marker.encode())}"


def _claims(**overrides) -> dict:
    claims = {
        "exp": int(NOW) + cred.CODEX_LOGIN_MIN_S + 3600,
        "iat": int(NOW) - 60,
        "scp": sorted(cred.CODEX_SCOPE_CEILING),
    }
    claims.update(overrides)
    return {key: value for key, value in claims.items() if value is not _DROP}


_DROP = object()


def _login(*, claims: dict | None = None, access: str | None = None, **top) -> dict:
    document = {
        "OPENAI_API_KEY": None,
        "auth_mode": "chatgpt",
        "last_refresh": "2026-11-07T12:00:00Z",
        "tokens": {
            "access_token": access if access is not None else _jwt(claims or _claims()),
            "id_token": ID,
            "account_id": ACCOUNT,
            "refresh_token": REFRESH,
        },
        "agent_identity": None,
        "personal_access_token": None,
    }
    for key, value in top.items():
        if value is _DROP:
            document.pop(key, None)
        else:
            document[key] = value
    return document


def _raw(document: object) -> bytes:
    return json.dumps(document).encode("utf-8")


def _secrets_of(document: dict) -> tuple[str, ...]:
    tokens = document["tokens"]
    return (tokens["access_token"], tokens["id_token"], tokens["refresh_token"])


# --- subscription login ----------------------------------------------------------------

@pytest.mark.parametrize("document", (
    _login(OPENAI_API_KEY="sk-fixture-key"),
    _login(auth_mode="apikey"),
    _login(auth_mode="chatgptAuthTokens"),
    _login(auth_mode=_DROP),
    _login(tokens=_DROP),
    _login(tokens=None),
    _login(tokens="not-an-object"),
    _login(tokens={"access_token": ACCESS}),
    _login(last_refresh=_DROP),
    ["not", "an", "object"],
), ids=lambda document: "document")
def test_a_login_that_is_not_a_subscription_sign_in_is_api_key_refused(document):
    raw = _raw(document)
    assert cred.subscription_login_problem(raw) == "codex_seat_api_key_refused"
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        cred.build_seat_copy(raw)
    assert caught.value.code == "codex_seat_api_key_refused"


@pytest.mark.parametrize("raw", (b"", b"{not json", "é".encode("latin-1"),
                                 b" " * (cred.AUTH_CAP_BYTES + 1)))
def test_an_unreadable_login_is_api_key_refused(raw):
    assert cred.subscription_login_problem(raw) == "codex_seat_api_key_refused"


@pytest.mark.parametrize("empty", (None, "", _DROP))
def test_an_empty_api_key_is_a_subscription_sign_in(empty):
    assert cred.subscription_login_problem(_raw(_login(OPENAI_API_KEY=empty))) is None


@pytest.mark.parametrize("field", ("access_token", "id_token", "account_id"))
@pytest.mark.parametrize("value", (_DROP, "", None, 7))
def test_a_login_missing_a_kept_token_is_api_key_refused(field, value):
    document = _login()
    if value is _DROP:
        del document["tokens"][field]
    else:
        document["tokens"][field] = value
    assert cred.subscription_login_problem(_raw(document)) == "codex_seat_api_key_refused"


# --- the copy --------------------------------------------------------------------------

def test_the_copy_keeps_exactly_the_planned_fields_with_an_empty_refresh_token():
    document = _login()
    document["tokens"]["extra_token_field"] = "dropped"
    document["bedrock_api_key"] = None
    copy = cred.build_seat_copy(_raw(document))
    written = json.loads(copy.data)
    assert written == {
        "OPENAI_API_KEY": None,
        "auth_mode": "chatgpt",
        "last_refresh": document["last_refresh"],
        "tokens": {
            "access_token": document["tokens"]["access_token"],
            "id_token": ID,
            "account_id": ACCOUNT,
            "refresh_token": "",
        },
    }
    assert REFRESH.encode() not in copy.data
    assert copy.expires_at == _claims()["exp"]
    assert copy.secrets == (document["tokens"]["access_token"].encode(), ID.encode())
    assert len(copy.tokens_sha256) == 64


def test_no_secret_appears_in_the_copy_repr():
    document = _login()
    copy = cred.build_seat_copy(_raw(document))
    for text in (repr(copy), str(copy)):
        for secret in _secrets_of(document):
            assert secret not in text
        assert "data=" not in text and "secrets=" not in text
    assert copy.tokens_sha256 in repr(copy)


def test_the_copy_refuses_claims_it_cannot_decode_and_a_missing_expiry():
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        cred.build_seat_copy(_raw(_login(access="not-a-jwt")))
    assert caught.value.code == "codex_seat_token_scope_excess"
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        cred.build_seat_copy(_raw(_login(claims=_claims(exp=_DROP))))
    assert caught.value.code == "codex_seat_token_expiring"


# --- margin --------------------------------------------------------------------------

def test_margin_passes_at_the_threshold_and_refuses_below_it():
    at = _raw(_login(claims=_claims(exp=int(NOW) + cred.CODEX_LOGIN_MIN_S)))
    below = _raw(_login(claims=_claims(exp=int(NOW) + cred.CODEX_LOGIN_MIN_S - 1)))
    expired = _raw(_login(claims=_claims(exp=int(NOW) - 1)))
    assert cred.token_margin_problem(at, now=NOW) is None
    assert cred.token_margin_problem(below, now=NOW) == "codex_seat_token_expiring"
    assert cred.token_margin_problem(expired, now=NOW) == "codex_seat_token_expiring"


@pytest.mark.parametrize("exp", (_DROP, None, "1900000000", True, float("inf"), float("nan")))
def test_margin_refuses_a_token_without_a_readable_expiry(exp):
    raw = _raw(_login(claims=_claims(exp=exp)))
    assert cred.token_margin_problem(raw, now=NOW) == "codex_seat_token_expiring"


def test_margin_leaves_undecodable_claims_to_the_scope_check():
    raw = _raw(_login(access="not-a-jwt"))
    assert cred.token_margin_problem(raw, now=NOW) is None
    assert cred.scope_problem(raw) == "codex_seat_token_scope_excess"


def test_margin_and_scope_each_give_their_one_code():
    expiring = _raw(_login(claims=_claims(exp=int(NOW))))
    wide = _raw(_login(claims=_claims(scp=["openid", "api.model.admin"])))
    assert (cred.token_margin_problem(expiring, now=NOW), cred.scope_problem(expiring)) == (
        "codex_seat_token_expiring", None)
    assert (cred.token_margin_problem(wide, now=NOW), cred.scope_problem(wide)) == (
        None, "codex_seat_token_scope_excess")


# --- scope ---------------------------------------------------------------------------

@pytest.mark.parametrize("claims", (
    _claims(),
    _claims(scp=["openid", "email"]),
    _claims(scp=_DROP, scope="openid profile"),
    _claims(scp=[]),
))
def test_scopes_inside_the_ceiling_pass(claims):
    assert cred.scope_problem(_raw(_login(claims=claims))) is None


@pytest.mark.parametrize("claims", (
    _claims(scp=[*sorted(cred.CODEX_SCOPE_CEILING), "api.responses.write.all"]),
    _claims(scp=_DROP, scope="openid model.request"),
    _claims(scope="openid admin"),
    _claims(scp=_DROP),
    _claims(scp="openid"),
    _claims(scp=["openid", 7]),
    _claims(scp=_DROP, scope=["openid"]),
))
def test_scopes_beyond_or_without_a_stated_ceiling_are_scope_excess(claims):
    assert cred.scope_problem(_raw(_login(claims=claims))) == "codex_seat_token_scope_excess"


def _payload_access(payload: str) -> str:
    return f"{_b64(b'{}')}.{payload}.{_b64(b'sig')}"


@pytest.mark.parametrize("access", (
    "not-a-jwt",
    "a.b",
    "a.b.c.d",
    _payload_access(""),
    _payload_access("!!not-base64!!"),
    _payload_access(_b64(b"not json")),
    _payload_access(_b64(b"[1, 2]")),
    _payload_access(_b64(b"\xff\xfe")),
    "x" * (16 * 1024 + 1),
))
def test_an_access_token_whose_claims_cannot_be_decoded_is_scope_excess(access):
    assert cred.scope_problem(_raw(_login(access=access))) == "codex_seat_token_scope_excess"


def test_scope_excess_without_tokens_or_any_login():
    assert cred.scope_problem(_raw(_login(tokens=_DROP))) == "codex_seat_token_scope_excess"
    assert cred.scope_problem(b"{not json") == "codex_seat_token_scope_excess"


def test_the_checks_call_no_issuer(monkeypatch):
    def _no_network(*_args, **_kwargs):
        raise AssertionError("a credential check reached the network")

    monkeypatch.setattr(socket, "socket", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(socket, "getaddrinfo", _no_network)
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    for raw in (_raw(_login()), _raw(_login(access="not-a-jwt")),
                _raw(_login(claims=_claims(scp=["openid", "wide"])))):
        cred.subscription_login_problem(raw)
        cred.token_margin_problem(raw, now=NOW)
        cred.scope_problem(raw)
    cred.build_seat_copy(_raw(_login()))


# --- refresh detection ---------------------------------------------------------------

def test_tokens_changed_is_false_on_an_identical_read():
    copy = cred.build_seat_copy(_raw(_login()))
    assert cred.tokens_changed(copy, copy.data) is False
    reformatted = json.dumps(json.loads(copy.data), separators=(",", ":")).encode()
    assert cred.tokens_changed(copy, reformatted) is False


@pytest.mark.parametrize("field", ("access_token", "id_token", "account_id", "refresh_token"))
def test_tokens_changed_is_true_when_any_token_differs(field):
    copy = cred.build_seat_copy(_raw(_login()))
    observed = json.loads(copy.data)
    observed["tokens"][field] = "renewed-" + field
    assert cred.tokens_changed(copy, json.dumps(observed).encode()) is True


@pytest.mark.parametrize("observed", (
    b"", b"{not json", b"[]", b'{"tokens": null}', b"{}",
))
def test_tokens_changed_is_true_when_the_tokens_cannot_be_read(observed):
    copy = cred.build_seat_copy(_raw(_login()))
    assert cred.tokens_changed(copy, observed) is True


def test_tokens_changed_is_true_when_a_token_field_is_added_or_removed():
    copy = cred.build_seat_copy(_raw(_login()))
    added = json.loads(copy.data)
    added["tokens"]["expires_at"] = 1
    removed = json.loads(copy.data)
    del removed["tokens"]["refresh_token"]
    assert cred.tokens_changed(copy, json.dumps(added).encode()) is True
    assert cred.tokens_changed(copy, json.dumps(removed).encode()) is True


# --- the login file ------------------------------------------------------------------

def test_auth_path_follows_codex_home_then_home(tmp_path):
    assert cred.auth_path({"CODEX_HOME": str(tmp_path / "ch"), "HOME": "/nowhere"}) == (
        tmp_path / "ch" / "auth.json")
    assert cred.auth_path({"CODEX_HOME": "", "HOME": str(tmp_path)}) == (
        tmp_path / ".codex" / "auth.json")
    assert cred.auth_path({"HOME": str(tmp_path)}) == tmp_path / ".codex" / "auth.json"


def test_auth_path_and_present_read_the_process_environment(tmp_path, monkeypatch):
    home = tmp_path / "codex-home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("CODEX_HOME", str(home))
    assert cred.auth_path() == home / "auth.json"
    assert cred.present() is False
    (home / "auth.json").symlink_to(tmp_path / "missing")
    assert cred.present() is True


def _write_login(home: Path, data: bytes, mode: int = 0o600) -> Path:
    home.mkdir(mode=0o700, exist_ok=True)
    path = home / "auth.json"
    path.write_bytes(data)
    path.chmod(mode)
    return path


def _read_refusal(env) -> str:
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        cred.read_auth(env)
    return caught.value.code


def test_a_missing_login_is_credential_missing(tmp_path):
    assert _read_refusal({"CODEX_HOME": str(tmp_path / "none")}) == "codex_seat_credential_missing"


@pytest.mark.parametrize("mode", (0o640, 0o604, 0o660, 0o620, 0o602, 0o610))
def test_a_login_with_group_or_other_access_is_unsafe(tmp_path, mode):
    _write_login(tmp_path / "h", _raw(_login()), mode)
    assert _read_refusal({"CODEX_HOME": str(tmp_path / "h")}) == UNSAFE


def test_a_linked_login_is_unsafe(tmp_path):
    real = _write_login(tmp_path / "real", _raw(_login()))
    (tmp_path / "h").mkdir(mode=0o700)
    (tmp_path / "h" / "auth.json").symlink_to(real)
    assert _read_refusal({"CODEX_HOME": str(tmp_path / "h")}) == UNSAFE


def test_a_login_that_is_not_a_regular_file_is_unsafe(tmp_path):
    (tmp_path / "d" / "auth.json").mkdir(parents=True)
    assert _read_refusal({"CODEX_HOME": str(tmp_path / "d")}) == UNSAFE
    (tmp_path / "f").mkdir(mode=0o700)
    os.mkfifo(tmp_path / "f" / "auth.json", 0o600)
    assert _read_refusal({"CODEX_HOME": str(tmp_path / "f")}) == UNSAFE


def test_a_login_over_the_cap_is_unsafe(tmp_path):
    _write_login(tmp_path / "h", b" " * (cred.AUTH_CAP_BYTES + 1))
    assert _read_refusal({"CODEX_HOME": str(tmp_path / "h")}) == UNSAFE


def test_a_login_another_account_owns_is_unsafe(tmp_path, monkeypatch):
    _write_login(tmp_path / "h", _raw(_login()))
    monkeypatch.setattr(cred, "_owner_uid", lambda: os.geteuid() + 4242)
    assert _read_refusal({"CODEX_HOME": str(tmp_path / "h")}) == UNSAFE


def test_the_login_enters_through_auth_path_and_build_seat_copy(tmp_path, monkeypatch):
    """Path-entered: the file is found by ``auth_path``, read by ``read_auth``, copied by
    ``build_seat_copy`` and lands in the seat's home, mode 0600."""
    document = _login()
    _write_login(tmp_path / "codex-home", _raw(document))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    raw = cred.read_auth()
    assert cred.subscription_login_problem(raw) is None
    assert cred.token_margin_problem(raw, now=NOW) is None
    assert cred.scope_problem(raw) is None
    copy = cred.build_seat_copy(raw)
    seat_home = tmp_path / "seat-home"
    seat_home.mkdir(mode=0o700)
    home_fd = seat_jail.open_dir_nofollow(seat_home)
    try:
        cred.install_seat_copy(home_fd, copy)
        with pytest.raises(FileExistsError):
            cred.install_seat_copy(home_fd, copy)
    finally:
        os.close(home_fd)
    landed = seat_home / ".codex" / "auth.json"
    assert landed.read_bytes() == copy.data
    assert landed.stat().st_mode & 0o777 == 0o600
    assert cred.tokens_changed(copy, landed.read_bytes()) is False
    assert REFRESH.encode() not in landed.read_bytes()


def test_an_api_key_file_never_reaches_a_copy(tmp_path, monkeypatch):
    _write_login(tmp_path / "codex-home", _raw({"OPENAI_API_KEY": "sk-fixture-key"}))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        cred.build_seat_copy(cred.read_auth())
    assert caught.value.code == "codex_seat_api_key_refused"


# --- vocabulary ----------------------------------------------------------------------

def _raised_codes() -> set[str]:
    codes: set[str] = set()
    corpus = [
        _raw(_login()), _raw(_login(OPENAI_API_KEY="sk-x")), _raw(_login(access="nope")),
        _raw(_login(claims=_claims(exp=int(NOW)))), _raw(_login(claims=_claims(scp=["x"]))),
        _raw(_login(claims=_claims(exp=_DROP))), b"{not json",
    ]
    for raw in corpus:
        codes.update(code for code in (
            cred.subscription_login_problem(raw), cred.token_margin_problem(raw, now=NOW),
            cred.scope_problem(raw)) if code is not None)
        try:
            cred.build_seat_copy(raw)
        except seat_jail.SeatSandboxRefused as exc:
            codes.add(exc.code)
    try:
        cred.read_auth({"CODEX_HOME": "/nonexistent/codex-home"})
    except seat_jail.SeatSandboxRefused as exc:
        codes.add(exc.code)
    return codes


def test_every_codex_code_this_lane_raises_is_an_if0_codex5_code():
    codes = {code for code in _raised_codes() if code.startswith("codex_seat_")}
    assert codes == set(LANE_CODES)
    assert codes <= seat_jail.CODEX_SEAT_CODES
    for code in codes:
        assert contract.OD10_CLASSES[code] == LANE_CODES[code]
        assert code in seat_jail.NOTICES


def test_the_measured_constants_are_pinned():
    # SL-1.5 (plans/evidence/seat-codex/credential-scope.json): the token sits inside the
    # sign-in's requested scopes, and the CLI renews nothing while the token is valid, so
    # the margin is the longest a leg can run, plus 300s for clock skew and
    # launch work before the leg timer starts.
    from phase_loop_runtime import panel_invoker

    assert cred.CODEX_SCOPE_CEILING == frozenset({
        "openid", "profile", "email", "offline_access",
        "api.connectors.read", "api.connectors.invoke",
    })
    assert cred.CODEX_LOGIN_MIN_S == panel_invoker._LEG_TIMEOUT_MAX_S + 300 == 2100


def test_the_unsafe_file_refusal_reuses_the_existing_code():
    assert UNSAFE in seat_jail.NOTICES
    assert cred.SEAT_AUTH_RELPATH == ".codex/auth.json"


# --- SL-1.5 measurement (VM): opt-in, on a developer host with the developer's login ---

MEASURE_ENV = "PHASE_LOOP_CODEX_MEASURE"
MEASURE_OUT_ENV = "PHASE_LOOP_CODEX_MEASURE_OUT"
_MEASURE_PROMPT = "Reply with the single word OK and nothing else."
# last_refresh ages, in days, at which the CLI is run with the narrowed copy to see
# whether it attempts a renewal before its turn.
_REFRESH_AGES_D = (0, 7, 9, 29)


def _measure_codex(native: str, target: Path, codex_home: Path, workdir: Path) -> dict:
    """One turn of the developer's own CLI with only the private ``CODEX_HOME``: no user
    config, rules or session files, and no inherited environment. It starts through the
    runtime's owned executor launch, the route the operator's own CLI takes on the host."""
    from phase_loop_runtime.panel_invoker import run_provider

    env = {
        "PATH": f"{target}/codex-path:/usr/bin:/bin", "HOME": str(codex_home.parent),
        "CODEX_HOME": str(codex_home), "LANG": "C.UTF-8",
    }
    before = (codex_home / "auth.json").read_bytes()
    started = time.monotonic()
    done = run_provider(
        [native, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--json",
         "--skip-git-repo-check", "--cd", str(workdir), "--sandbox", "read-only",
         "-c", 'approval_policy="never"', "-c", 'cli_auth_credentials_store="file"', "-"],
        executor=True, env=env, input=_MEASURE_PROMPT, text=True, capture_output=True,
        check=False, timeout=300, cwd=str(workdir))
    events: dict[str, int] = {}
    for line in (done.stdout or "").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and isinstance(event.get("type"), str):
            events[event["type"]] = events.get(event["type"], 0) + 1
    after = (codex_home / "auth.json").read_bytes() if (codex_home / "auth.json").exists() else b""
    stderr = (done.stderr or "").lower()
    return {
        "returncode": done.returncode,
        "elapsed_s": round(time.monotonic() - started),
        "event_type_counts": dict(sorted(events.items())),
        "turn_completed": events.get("turn.completed", 0) >= 1,
        "auth_file_rewritten": after != before,
        "stderr_mentions_refresh": "refresh" in stderr,
    }


@pytest.mark.host_seat_credentials
@pytest.mark.skipif(os.environ.get(MEASURE_ENV) != "1",
                    reason=f"SL-1.5 measurement runs only with {MEASURE_ENV}=1")
def test_measured_credential_scope(tmp_path):
    """Read the developer's own login once, then run the developer's codex CLI against the
    provider with the narrowed copy in a private ``CODEX_HOME``. The record keeps field
    names, counts and outcomes only; the test fails if any token value reaches it."""
    from datetime import datetime, timedelta, timezone

    from phase_loop_runtime import panel_invoker, seat_codex_runtime

    out = os.environ.get(MEASURE_OUT_ENV)
    assert out and os.path.isabs(out), f"{MEASURE_OUT_ENV} must name an absolute path"
    raw = cred.read_auth()
    document = json.loads(raw)
    tokens = document.get("tokens") if isinstance(document.get("tokens"), dict) else {}
    claims = cred._claims(raw) or {}
    scopes = cred._scopes(claims)
    exp, iat = cred._expiry(claims), claims.get("iat")
    now = time.time()
    _harness, native = panel_invoker._seat_provider_source("codex", dict(os.environ))
    runtime = seat_codex_runtime.resolve_runtime(Path(native))
    version = json.loads((runtime.target / "codex-package.json").read_bytes()).get("version")
    record: dict = {
        "schema": "seat_codex_credential_scope.v1",
        "evidence_id": "codex-credential-scope",
        "codex_cli_version": version,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "login_fields": {
            "top": sorted(document),
            "tokens": sorted(tokens),
            "access_token_claims": sorted(claims),
        },
        "checks": {
            "subscription_login": cred.subscription_login_problem(raw),
            "token_margin": cred.token_margin_problem(raw, now=now),
            "scope_ceiling": cred.scope_problem(raw),
        },
        "scope": {
            "stated_count": None if scopes is None else len(scopes),
            "ceiling_count": len(cred.CODEX_SCOPE_CEILING),
            "inside_ceiling_count": None if scopes is None else len(scopes & cred.CODEX_SCOPE_CEILING),
            "outside_ceiling_count": None if scopes is None else len(scopes - cred.CODEX_SCOPE_CEILING),
        },
        "token_lifetime_s": (exp - iat) if exp is not None and type(iat) is int else None,
        "token_left_at_measure_s": None if exp is None else round(exp - now),
        "copy_fields": None,
        "runs": [],
    }
    if record["checks"]["subscription_login"] is None and record["checks"]["scope_ceiling"] is None:
        copy = cred.build_seat_copy(raw)
        written = json.loads(copy.data)
        record["copy_fields"] = {"top": sorted(written), "tokens": sorted(written["tokens"])}
        runs = tmp_path / "runs"
        runs.mkdir(mode=0o700)
        try:
            for age_d in _REFRESH_AGES_D:
                run_home = runs / f"age-{age_d}" / ".codex"
                run_home.mkdir(parents=True, mode=0o700)
                workdir = runs / f"age-{age_d}" / "workspace"
                workdir.mkdir(mode=0o700)
                seeded = dict(written)
                if age_d:
                    seeded["last_refresh"] = (datetime.now(timezone.utc) - timedelta(days=age_d)
                                              ).isoformat().replace("+00:00", "Z")
                (run_home / "auth.json").write_bytes(json.dumps(seeded, indent=2).encode())
                (run_home / "auth.json").chmod(0o600)
                result = _measure_codex(native, runtime.target, run_home, workdir)
                result["last_refresh_age_d"] = age_d
                result["tokens_changed"] = cred.tokens_changed(
                    copy, (run_home / "auth.json").read_bytes())
                record["runs"].append(result)
        finally:
            # The private copies hold the developer's tokens; none outlives the test.
            shutil.rmtree(runs, ignore_errors=True)
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    # Names only, so a failure report cannot echo a token value.
    leaked = [name for name in ("access_token", "id_token", "refresh_token", "account_id")
              if isinstance(tokens.get(name), str) and tokens[name]
              and seat_jail.contains_secret(text.encode(), tokens[name].encode())]
    assert leaked == []
    descriptor = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(text)
