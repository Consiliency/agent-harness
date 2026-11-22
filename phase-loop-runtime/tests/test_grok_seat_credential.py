"""GROK SL-1: the jailed Grok seat's credential staging (IF-0-GROK-1 "Credential";
plans/artifacts/grok-jail-tool-surface-contract-v1.md section 2.3).

Every store here is a fabricated fixture under a temporary operator home; no test reads a
real login, runs ``grok`` or contacts a provider. Credential values are assembled at run
time so that no literal in this file looks like a secret.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import pickle
import stat
import time

import pytest

from phase_loop_runtime import grok_tool_surface, seat_grok_credential as cred
from phase_loop_runtime import seat_jail

#: The pinned input (plan IF-0-GROK-1; jail contract section 2.3).
PINNED_CONFIG_SHA256 = "2984e0c368943bb6c1627146e413995df12cca5820e782adffcb052a9b761780"
SIGN_IN = "https://" + "accounts.x.ai" + "/sign-in"
MARGIN_S = 2100
STAGED_ENTRIES = {"config.toml", "auth.json", "agent_id", "logs", "sessions",
                  ".config-init.lock", "managed_config.lock"}
CODES = {"grok_seat_credential_missing", "grok_seat_credential_refused",
         "grok_seat_token_expired", "seat_profile_unavailable"}


def _fabricated(label: str, length: int) -> str:
    """A fabricated credential value of ``length`` characters, built at run time."""
    filler = "".join(chr(ord("a") + (index * 7 + len(label)) % 26) for index in range(length))
    return ("fx" + "-" + label + "-" + filler)[:length]


SHORT = _fabricated("short", 10)      # 8..12 characters: the value is its own suffix
LONG = ".".join((_fabricated("head", 40), _fabricated("body", 480), _fabricated("sig", 86)))
REFRESH = _fabricated("refresh", 64)


def _iso(offset_s: float) -> str:
    moment = dt.datetime.fromtimestamp(time.time() + offset_s, tz=dt.timezone.utc)
    return moment.isoformat()


def _store(key: str = LONG, *, expires_at: object = None, extra: dict | None = None,
           entry_extra: dict | None = None) -> dict:
    entry = {"key": key, "expires_at": _iso(7 * 86400) if expires_at is None else expires_at,
             "user_id": "fx-user", "refresh_token": REFRESH}
    entry.update(entry_extra or {})
    document = {SIGN_IN: entry}
    document.update(extra or {})
    return document


@pytest.fixture
def operator(tmp_path, monkeypatch):
    """A fixture operator home with a valid subscription store, and an empty review dir."""
    home = tmp_path / "operator"
    grok = home / ".grok"
    grok.mkdir(parents=True, mode=0o700)
    review = tmp_path / "review"
    review.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))

    class Operator:
        def __init__(self) -> None:
            self.home = home
            self.grok = grok
            self.review = review
            self.config_dir = review / "grok-config"
            self.write(_store())
            self.agent_id(b"fx-agent-0001")

        def write(self, document, *, raw: bytes | None = None, mode: int = 0o600) -> Path:
            path = grok / "auth.json"
            if path.is_symlink() or path.exists():
                path.unlink()
            path.write_bytes(raw if raw is not None else json.dumps(document).encode())
            path.chmod(mode)
            return path

        def agent_id(self, data: bytes, *, mode: int = 0o600) -> Path:
            path = grok / "agent_id"
            if path.exists():
                path.unlink()
            path.write_bytes(data)
            path.chmod(mode)
            return path

        def stage(self, margin_s: float = MARGIN_S):
            return cred.stage_grok_seat_credential(self.config_dir, margin_s=margin_s)

    yield Operator()
    # The staged directory is 0555: give it back to its owner so tmp_path can be removed.
    if os.path.isdir(review / "grok-config") and not os.path.islink(review / "grok-config"):
        os.chmod(review / "grok-config", 0o700)


def _refusal(operator, margin_s: float = MARGIN_S) -> str:
    with pytest.raises(cred.GrokCredentialRefused) as caught:
        operator.stage(margin_s)
    assert isinstance(caught.value, seat_jail.SeatSandboxRefused)
    assert caught.value.code in CODES
    # Nothing is written to disk on a refusal.
    assert not os.path.lexists(operator.config_dir)
    assert list(operator.review.iterdir()) == []
    return caught.value.code


# --------------------------------------------------------------------------------------
# (a) Refusals: each store gives its code and nothing is written.
# --------------------------------------------------------------------------------------

def test_a_subscription_store_is_admitted(operator):
    staged = operator.stage()
    assert isinstance(staged, cred.GrokSeatCredential)
    assert staged.config_dir == operator.config_dir


@pytest.mark.parametrize("label,document", [
    ("api-key-field", {"api_key": "xai" + "-" + _fabricated("apikey", 40)}),
    ("api-key-beside-sign-in", _store(extra={"XAI_API_KEY": _fabricated("apikey", 40)})),
    ("api-key-in-entry", _store(entry_extra={"api_key": _fabricated("apikey", 40)})),
    ("api-key-shaped-bearer", _store(key="xai" + "-" + _fabricated("apikey", 40))),
    ("env-key", _store(entry_extra={"env_key": "XAI_API_KEY"})),
])
def test_an_api_key_store_is_refused(operator, label, document):
    operator.write(document)
    assert _refusal(operator) == "grok_seat_credential_refused", label


@pytest.mark.parametrize("label,document,raw", [
    ("second-scope", _store(extra={"https://idp.example.invalid": {"key": LONG}}), None),
    ("no-key", {SIGN_IN: {"expires_at": _iso(86400)}}, None),
    ("key-not-text", _store(key=12345678901234), None),
    ("empty-key", _store(key=""), None),
    ("too-short-key", _store(key="fx-1234"), None),
    ("entry-not-object", {SIGN_IN: LONG}, None),
    ("empty-store", {}, None),
    ("list", None, b"[1, 2]"),
    ("not-json", None, b"key=" + LONG.encode()),
    ("not-utf8", None, b"\xff\xfe{}"),
])
def test_an_ambiguous_marker_is_refused(operator, label, document, raw):
    operator.write(document, raw=raw)
    assert _refusal(operator) == "grok_seat_credential_refused", label


@pytest.mark.parametrize("label,expires_at", [
    ("words", "next week"),
    ("naive", (dt.datetime.now() + dt.timedelta(days=30)).replace(microsecond=0).isoformat()),
    ("missing", "<absent>"),
    ("bool", True),
    ("nan", float("nan")),
    ("out-of-range-number", 12345),
    ("object", {"seconds": 99999}),
])
def test_an_unparseable_expiry_is_refused(operator, label, expires_at):
    document = _store(expires_at="placeholder")
    if expires_at == "<absent>":
        del document[SIGN_IN]["expires_at"]
    else:
        document[SIGN_IN]["expires_at"] = expires_at
    operator.write(document)
    assert _refusal(operator) == "grok_seat_token_expired", label


def test_an_expired_store_is_refused(operator):
    operator.write(_store(expires_at=_iso(-60)))
    assert _refusal(operator) == "grok_seat_token_expired"


def test_a_store_inside_the_margin_is_refused(operator):
    operator.write(_store(expires_at=_iso(MARGIN_S - 120)))
    assert _refusal(operator) == "grok_seat_token_expired"


def test_the_remaining_lifetime_must_exceed_the_margin(operator):
    operator.write(_store(expires_at=_iso(MARGIN_S + 600)))
    assert operator.stage().expires_at > time.time() + MARGIN_S


@pytest.mark.parametrize("form", ["seconds", "milliseconds", "zulu"])
def test_epoch_and_zulu_expiries_parse(operator, form):
    moment = time.time() + 86400
    value = {"seconds": int(moment), "milliseconds": int(moment * 1000),
             "zulu": dt.datetime.fromtimestamp(moment, tz=dt.timezone.utc)
             .strftime("%Y-%m-%dT%H:%M:%SZ")}[form]
    operator.write(_store(expires_at=value))
    assert abs(operator.stage().expires_at - int(moment)) <= 1


@pytest.mark.parametrize("margin", [-1, float("nan"), float("inf"), True, "60", None])
def test_an_invalid_margin_is_a_caller_error(operator, margin):
    with pytest.raises((TypeError, ValueError)):
        operator.stage(margin)
    assert not os.path.lexists(operator.config_dir)


def test_a_missing_store_directory_is_missing(operator):
    for path in operator.grok.iterdir():
        path.unlink()
    operator.grok.rmdir()
    assert _refusal(operator) == "grok_seat_credential_missing"


def test_a_missing_auth_file_is_missing(operator):
    (operator.grok / "auth.json").unlink()
    assert _refusal(operator) == "grok_seat_credential_missing"


def test_a_missing_agent_id_is_missing(operator):
    (operator.grok / "agent_id").unlink()
    assert _refusal(operator) == "grok_seat_credential_missing"


def test_an_empty_agent_id_is_missing(operator):
    operator.agent_id(b"")
    assert _refusal(operator) == "grok_seat_credential_missing"


def test_a_linked_auth_file_is_unsafe(operator, tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps(_store()))
    target.chmod(0o600)
    (operator.grok / "auth.json").unlink()
    (operator.grok / "auth.json").symlink_to(target)
    assert _refusal(operator) == "seat_profile_unavailable"


def test_a_linked_agent_id_is_unsafe(operator, tmp_path):
    target = tmp_path / "agent"
    target.write_bytes(b"fx-agent")
    (operator.grok / "agent_id").unlink()
    (operator.grok / "agent_id").symlink_to(target)
    assert _refusal(operator) == "seat_profile_unavailable"


def test_a_linked_store_directory_is_unsafe(operator, tmp_path):
    real = tmp_path / "real-grok"
    operator.grok.rename(real)
    operator.grok.symlink_to(real)
    assert _refusal(operator) == "seat_profile_unavailable"


def test_a_foreign_owned_store_is_unsafe(operator, monkeypatch):
    monkeypatch.setattr(cred, "_owner_uid", lambda: os.geteuid() + 1)
    assert _refusal(operator) == "seat_profile_unavailable"


@pytest.mark.parametrize("name", ["auth.json", "agent_id"])
def test_a_foreign_owned_file_in_an_owned_store_is_unsafe(operator, monkeypatch, name):
    """Only the named file reports another owner (a non-root test cannot chown)."""
    target = os.stat(operator.grok / name)
    real_fstat = os.fstat

    def fstat(fd):
        result = real_fstat(fd)
        if (result.st_dev, result.st_ino) != (target.st_dev, target.st_ino):
            return result
        fields = list(result)
        fields[4] = os.geteuid() + 1
        return os.stat_result(fields)

    monkeypatch.setattr(os, "fstat", fstat)
    assert _refusal(operator) == "seat_profile_unavailable"


def test_a_group_readable_auth_file_is_unsafe(operator):
    operator.write(_store(), mode=0o640)
    assert _refusal(operator) == "seat_profile_unavailable"


def test_a_group_writable_store_directory_is_unsafe(operator):
    operator.grok.chmod(0o770)
    assert _refusal(operator) == "seat_profile_unavailable"


def test_a_writable_agent_id_is_unsafe(operator):
    operator.agent_id(b"fx-agent", mode=0o622)
    assert _refusal(operator) == "seat_profile_unavailable"


def test_an_oversize_auth_file_is_unsafe(operator):
    operator.write(None, raw=b" " * (cred.AUTH_CAP_BYTES + 1))
    assert _refusal(operator) == "seat_profile_unavailable"


def test_an_oversize_agent_id_is_unsafe(operator):
    operator.agent_id(b"a" * (cred.AGENT_ID_CAP_BYTES + 1))
    assert _refusal(operator) == "seat_profile_unavailable"


def test_a_non_regular_auth_file_is_unsafe(operator):
    (operator.grok / "auth.json").unlink()
    os.mkfifo(operator.grok / "auth.json", 0o600)
    assert _refusal(operator) == "seat_profile_unavailable"


def test_the_refusal_code_is_a_typed_seat_code(operator):
    operator.write(_store(expires_at=_iso(-1)))
    with pytest.raises(cred.GrokCredentialRefused) as caught:
        operator.stage()
    assert caught.value.code == "grok_seat_token_expired"
    with pytest.raises(ValueError):
        cred.GrokCredentialRefused("grok_tool_gate")


# --------------------------------------------------------------------------------------
# presence reads no secret.
# --------------------------------------------------------------------------------------

def test_presence_reads_no_secret(operator, monkeypatch):
    assert cred.grok_seat_credential_present() is True
    opened: list[object] = []
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda *a, **k: opened.append(a) or real_open(*a, **k))
    (operator.grok / "auth.json").chmod(0)
    assert cred.grok_seat_credential_present() is True
    assert opened == []


def test_presence_is_false_without_a_store(operator):
    (operator.grok / "auth.json").unlink()
    assert cred.grok_seat_credential_present() is False


def test_a_linked_store_is_present_and_refused_when_read(operator, tmp_path):
    (operator.grok / "auth.json").unlink()
    (operator.grok / "auth.json").symlink_to(tmp_path / "absent")
    assert cred.grok_seat_credential_present() is True
    assert _refusal(operator) == "seat_profile_unavailable"


# --------------------------------------------------------------------------------------
# (b) The staged read-only directory.
# --------------------------------------------------------------------------------------

def test_the_staged_directory_is_read_only_and_holds_exactly_the_table(operator):
    staged = operator.stage()
    root = operator.config_dir
    info = os.lstat(root)
    assert stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o555
    assert info.st_uid == os.geteuid()
    assert set(os.listdir(root)) == STAGED_ENTRIES
    for name in ("config.toml", "auth.json", "agent_id", ".config-init.lock",
                 "managed_config.lock"):
        entry = os.lstat(root / name)
        assert stat.S_ISREG(entry.st_mode), name
        assert stat.S_IMODE(entry.st_mode) == 0o444, name
        assert entry.st_uid == os.geteuid() and entry.st_nlink == 1, name
    for name in ("logs", "sessions"):
        entry = os.lstat(root / name)
        assert stat.S_ISDIR(entry.st_mode) and stat.S_IMODE(entry.st_mode) == 0o555, name
        assert os.listdir(root / name) == [], name
    for name in (".config-init.lock", "managed_config.lock"):
        assert (root / name).read_bytes() == b"", name
    assert staged.config_dir == root


def test_the_staged_config_is_the_pinned_seat_config(operator):
    operator.stage()
    data = (operator.config_dir / "config.toml").read_bytes()
    assert len(data) == 424
    assert hashlib.sha256(data).hexdigest() == PINNED_CONFIG_SHA256
    assert cred.SEAT_CONFIG_SHA256 == PINNED_CONFIG_SHA256
    assert cred.seat_config_bytes() == data


def test_the_staged_credential_is_the_access_only_copy(operator):
    staged = operator.stage()
    copied = (operator.config_dir / "auth.json").read_bytes()
    document = json.loads(copied)
    assert list(document) == [SIGN_IN]
    assert set(document[SIGN_IN]) == {"key", "expires_at", "user_id"}
    assert document[SIGN_IN]["key"] == LONG and document[SIGN_IN]["user_id"] == "fx-user"
    assert REFRESH.encode() not in copied and b"refresh" not in copied
    assert (operator.config_dir / "agent_id").read_bytes() == b"fx-agent-0001"
    assert staged.digest == cred.credential_digest(copied, b"fx-agent-0001")


def test_the_digest_binds_both_credential_files(operator):
    copied = b'{"a":1}'
    assert cred.credential_digest(copied, b"x") != cred.credential_digest(copied, b"y")
    assert cred.credential_digest(copied, b"x") != cred.credential_digest(b'{"a":2}', b"x")
    assert cred.credential_digest(b"ab", b"c") != cred.credential_digest(b"a", b"bc")


def test_the_staged_files_cannot_be_written_by_their_owner(operator):
    operator.stage()
    for name in ("auth.json", "config.toml", "agent_id"):
        with pytest.raises(PermissionError):
            os.open(operator.config_dir / name, os.O_WRONLY | os.O_APPEND)
    with pytest.raises(PermissionError):
        (operator.config_dir / "extra").write_bytes(b"x")


def test_an_existing_staged_directory_is_never_reused(operator):
    operator.config_dir.mkdir(mode=0o700)
    with pytest.raises(cred.GrokCredentialRefused) as caught:
        operator.stage()
    assert caught.value.code == "seat_profile_unavailable"
    assert os.listdir(operator.config_dir) == []


def test_a_linked_staged_directory_is_refused(operator, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    operator.config_dir.symlink_to(elsewhere)
    with pytest.raises(cred.GrokCredentialRefused) as caught:
        operator.stage()
    assert caught.value.code == "seat_profile_unavailable"
    assert os.listdir(elsewhere) == []


def test_a_shared_review_directory_is_refused(operator):
    operator.review.chmod(0o750)
    assert _refusal(operator) == "seat_profile_unavailable"


def test_the_staged_directory_has_the_fixed_name(operator):
    with pytest.raises(ValueError):
        cred.stage_grok_seat_credential(operator.review / "other", margin_s=MARGIN_S)
    assert list(operator.review.iterdir()) == []


def test_a_failure_while_staging_leaves_nothing(operator, monkeypatch):
    real = cred._write_read_only

    def fail_on_agent_id(dir_fd, name, data):
        if name == "agent_id":
            raise OSError(28, "No space left on device")
        return real(dir_fd, name, data)

    monkeypatch.setattr(cred, "_write_read_only", fail_on_agent_id)
    with pytest.raises(OSError):
        operator.stage()
    assert list(operator.review.iterdir()) == []


def test_the_config_source_switches_to_e8a_once_it_lands(operator, monkeypatch):
    literal = cred.seat_config_bytes()
    calls: list[int] = []

    def seat_config() -> bytes:
        calls.append(1)
        return literal

    monkeypatch.setattr(grok_tool_surface, "seat_config", seat_config, raising=False)
    operator.stage()
    assert calls, "the E8-A function is the byte source once it exists"
    assert (operator.config_dir / "config.toml").read_bytes() == literal


def test_a_seat_config_that_misses_the_pin_refuses_before_any_write(operator, monkeypatch):
    drifted = cred.seat_config_bytes() + b"\n"
    monkeypatch.setattr(grok_tool_surface, "seat_config", lambda: drifted, raising=False)
    assert _refusal(operator) == "seat_profile_unavailable"


# --------------------------------------------------------------------------------------
# (c) Scan values: each secret value and its last 12 characters, in memory only.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", [SHORT, LONG], ids=["short", "long"])
def test_scan_values_hold_each_secret_and_its_suffix(operator, key):
    operator.write(_store(key=key))
    staged = operator.stage()
    values = set(staged.scan_values)
    assert key.encode() in values
    assert key[-12:].encode() in values
    # Taken from the projected copy: the dropped refresh token is not there.
    assert REFRESH.encode() not in values and REFRESH[-12:].encode() not in values
    assert all(isinstance(value, bytes) and len(value) >= 8 for value in values)
    assert key.encode() in staged.scan_values and len(staged.scan_values) == len(values)


def test_scan_values_are_not_serialisable(operator):
    staged = operator.stage()
    for attempt in (lambda: pickle.dumps(staged.scan_values),
                    lambda: pickle.dumps(staged),
                    lambda: json.dumps(staged.scan_values),
                    lambda: copy.copy(staged.scan_values),
                    lambda: copy.deepcopy(staged.scan_values),
                    lambda: dataclasses.asdict(staged)):
        with pytest.raises(TypeError):
            attempt()
    for text in (repr(staged), str(staged), repr(staged.scan_values)):
        assert LONG not in text and LONG[-12:] not in text


def test_scan_values_cannot_be_built_from_text(operator):
    with pytest.raises(TypeError):
        cred.ScanValues(["fx-not-bytes-value"])


# --------------------------------------------------------------------------------------
# (d) The refresh after-check over the host-visible writable state (note B5).
# --------------------------------------------------------------------------------------

@pytest.fixture
def seat_home(tmp_path):
    home = tmp_path / "review" / "home"
    rw = home / ".grok-rw"
    (rw / "sessions").mkdir(parents=True)
    (rw / ".config-init.lock").write_bytes(b"")
    (rw / "managed_config.lock").write_bytes(b"")
    (home / ".mcp.json").write_bytes(b"")
    (home / ".config").mkdir()
    (rw / "sessions" / "tool_definitions.json").write_text(json.dumps(
        {"tools": [{"name": "read", "parameters": {"properties": {"key": {"type": "string"}}}}]}))
    return home


def test_a_clean_seat_home_passes_the_after_check(operator, seat_home):
    assert cred.grok_seat_credential_after(seat_home, operator.stage()) is None


def test_an_absent_seat_home_passes_the_after_check(operator, tmp_path):
    assert cred.grok_seat_credential_after(tmp_path / "gone", operator.stage()) is None


@pytest.mark.parametrize("relative,body", [
    (".grok-rw/auth.json", json.dumps({SIGN_IN: {"key": _fabricated("new", 40)}})),
    (".grok-rw/sessions/auth.json", "{}"),
    ("nested/deeper/cache.json", json.dumps({SIGN_IN: {"key": _fabricated("new", 40)}})),
    (".config/grok/state.json", json.dumps({"refresh_token": _fabricated("rt", 40)})),
    (".grok-rw/sessions/x.json", json.dumps({"https://idp.example.invalid": {
        "key": _fabricated("other", 40)}})),
])
def test_a_new_credential_shaped_file_fires_the_after_check(operator, seat_home, relative,
                                                            body):
    staged = operator.stage()
    path = seat_home / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    assert cred.grok_seat_credential_after(seat_home, staged) == \
        "grok_seat_token_refreshed_in_jail"


def test_a_linked_auth_file_fires_the_after_check(operator, seat_home, tmp_path):
    staged = operator.stage()
    (seat_home / ".grok-rw" / "auth.json").symlink_to(tmp_path / "absent")
    assert cred.grok_seat_credential_after(seat_home, staged) == \
        "grok_seat_token_refreshed_in_jail"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_an_unreadable_file_fails_the_after_check_closed(operator, seat_home):
    staged = operator.stage()
    path = seat_home / ".grok-rw" / "sessions" / "opaque"
    path.write_bytes(b"x")
    path.chmod(0)
    assert cred.grok_seat_credential_after(seat_home, staged) == \
        "grok_seat_token_refreshed_in_jail"


def test_the_after_check_takes_the_delivered_credential(seat_home):
    with pytest.raises(TypeError):
        cred.grok_seat_credential_after(seat_home, object())


# --------------------------------------------------------------------------------------
# Fix round 1 (review REQUIRED items 1-3 and the optional rollback).
# --------------------------------------------------------------------------------------

def test_a_short_sign_in_key_is_refused_even_beside_a_qualifying_secret(operator):
    """The sign-in bearer itself must be at least 8 characters; another secret that
    qualifies for scanning does not vouch for it."""
    document = _store(key=_fabricated("tiny", 5), entry_extra={"token": _fabricated("tok", 8)})
    operator.write(document)
    assert _refusal(operator) == "grok_seat_credential_refused"


def _member(name: str, value: object) -> str:
    return json.dumps(name) + ":" + json.dumps(value)


@pytest.mark.parametrize("label,raw", [
    # A first sign-in scope carrying an API-key field, overwritten by a valid one.
    ("duplicate-scope", lambda: "{" + _member(SIGN_IN, {"key": LONG, "api_key": _fabricated(
        "apikey", 40)}) + "," + _member(SIGN_IN, _store()[SIGN_IN]) + "}"),
    # A nested API-key-bearing object overwritten by an innocent duplicate.
    ("duplicate-nested", lambda: "{" + json.dumps(SIGN_IN) + ":{" + ",".join((
        _member("key", LONG), _member("expires_at", _iso(7 * 86400)),
        _member("meta", {"api_key": _fabricated("apikey", 40)}), _member("meta", {}))) + "}}"),
    # A duplicate whose values are both innocent still refuses.
    ("duplicate-innocent", lambda: "{" + json.dumps(SIGN_IN) + ":{" + ",".join((
        _member("key", LONG), _member("expires_at", _iso(7 * 86400)),
        _member("user_id", "a"), _member("user_id", "b"))) + "}}"),
])
def test_a_duplicate_json_member_is_refused(operator, label, raw):
    operator.write(None, raw=raw().encode())
    assert _refusal(operator) == "grok_seat_credential_refused", label


def test_traversal_depth_exhaustion_is_the_typed_marker_refusal(operator):
    """A store under the cap that the decoder accepts but no traversal can walk."""
    deep = "[" * 5_000 + "]" * 5_000
    raw = ("{" + json.dumps(SIGN_IN) + ":{" + _member("key", LONG) + ","
           + _member("expires_at", _iso(7 * 86400)) + ',"deep":' + deep + "}}")
    assert len(raw) < cred.AUTH_CAP_BYTES
    operator.write(None, raw=raw.encode())
    assert _refusal(operator) == "grok_seat_credential_refused"


def test_decoder_depth_exhaustion_is_the_typed_marker_refusal():
    """Beyond the store cap the size check refuses first, so the parser is driven
    directly: the decoder's own depth limit is a marker refusal, never a raw error."""
    raw = ("{" + json.dumps(SIGN_IN) + ':{"deep":' + "[" * 200_000 + "]" * 200_000
           + "}}").encode()
    assert cred._sign_in_entry(raw) is None


def test_a_failure_opening_the_new_staged_directory_removes_it(operator, monkeypatch):
    real_open = os.open

    def failing_open(path, flags, *args, dir_fd=None, **kwargs):
        if path == "grok-config" and dir_fd is not None:
            raise OSError(24, "Too many open files")
        return real_open(path, flags, *args, dir_fd=dir_fd, **kwargs)

    monkeypatch.setattr(os, "open", failing_open)
    with pytest.raises((OSError, cred.GrokCredentialRefused)):
        operator.stage()
    monkeypatch.setattr(os, "open", real_open)
    assert list(operator.review.iterdir()) == []
    assert isinstance(operator.stage(), cred.GrokSeatCredential)


def test_an_oversize_credential_file_under_another_name_fails_the_after_check(operator,
                                                                             seat_home):
    staged = operator.stage()
    body = json.dumps({SIGN_IN: {"key": _fabricated("new", 40)}}).encode()
    path = seat_home / ".grok-rw" / "sessions" / "cache.json"
    path.write_bytes(body + b" " * (cred._AFTER_READ_CAP + 1))
    assert cred.grok_seat_credential_after(seat_home, staged) == \
        "grok_seat_token_refreshed_in_jail"


def test_an_oversize_file_of_any_content_fails_the_after_check_closed(operator, seat_home):
    staged = operator.stage()
    (seat_home / "big.bin").write_bytes(b"\0" * (cred._AFTER_READ_CAP + 1))
    assert cred.grok_seat_credential_after(seat_home, staged) == \
        "grok_seat_token_refreshed_in_jail"


def test_a_duplicate_member_hiding_a_credential_fails_the_after_check(operator, seat_home):
    staged = operator.stage()
    scope = json.dumps("https://idp.example.invalid")
    body = "{" + scope + ":" + json.dumps({"key": _fabricated("hid", 40)}) + "," + scope + ":1}"
    (seat_home / ".grok-rw" / "state.json").write_text(body)
    assert cred.grok_seat_credential_after(seat_home, staged) == \
        "grok_seat_token_refreshed_in_jail"


@pytest.mark.parametrize("depth", [5_000, 200_000], ids=["traversal", "decoder"])
def test_depth_exhaustion_fails_the_after_check_closed(operator, seat_home, depth):
    staged = operator.stage()
    (seat_home / ".grok-rw" / "deep.json").write_text("[" * depth + "]" * depth)
    assert cred.grok_seat_credential_after(seat_home, staged) == \
        "grok_seat_token_refreshed_in_jail"


def test_a_file_that_grew_past_the_bound_after_its_stat_fails_the_after_check(operator,
                                                                            seat_home,
                                                                            monkeypatch):
    staged = operator.stage()
    path = seat_home / ".grok-rw" / "grown.json"
    path.write_bytes(b"[" + b" " * (cred._AFTER_READ_CAP + 1) + b"]")
    grown = os.stat(path)
    real_stat = os.stat

    def stat_before_growth(name, *args, **kwargs):
        result = real_stat(name, *args, **kwargs)
        if (result.st_dev, result.st_ino) != (grown.st_dev, grown.st_ino):
            return result
        fields = list(result)
        fields[6] = 2  # st_size as it was when listed
        return os.stat_result(fields)

    monkeypatch.setattr(os, "stat", stat_before_growth)
    assert cred.grok_seat_credential_after(seat_home, staged) == \
        "grok_seat_token_refreshed_in_jail"
