"""K-1 SL-6.1: Codex's window supplier (FIRSTSEAT amendment K-1, contract r4 §10.B).

Every test here goes through the real supplier module, ``seat_window_supply_codex``, which
registers Codex's window data on import. Its control launches go through the kit's real
``window_control_launch`` and the real ``_prepare_jailed_codex``, with the provider stubbed
at its spawn boundary (the jail build and ``_run_leg_with_liveness``). The one row context
enters through ``cli_main`` and is read back by the production verifier and reducer.

The supplier is imported inside a fixture that restores the window registry and
``sys.modules`` afterwards, so the registration never leaks into another file's fixture
vendor.
"""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import datetime as dt
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import secrets
import sys
import time
from types import SimpleNamespace

import pytest

from test_seat_window_vendor_neutral import (  # noqa: E402 - shared K-1 harness
    ROW_NOW, _codex_open_stubs, _codex_spec, _row_world, _run_row,
)

SUPPLIER = "phase_loop_runtime.seat_window_supply_codex"
#: The K-1 contract's pin in the amendment (plans/amendments/seats-FIRSTSEAT-K1-window-kit.md).
K1_CONTRACT_SHA256 = "aa30ce0a2f947fd004476ac62f1c964c57a1e6554cc273e16366c92a2088e967"
GEMINI_CONTRACT_SHA256 = "a57d46f722e22973f0522a8bc254856e6224d50b1b67893cab2b80522c4942a6"
CONTRACT_PATH = (Path(__file__).resolve().parents[2] / "plans" / "artifacts"
                 / "seats-window-kit-k1-contract.md")
KINDS = frozenset({"help", "tree_control", "runtime_control", "credentialed_tree_control",
                   "credentialed_runtime_control", "measured", "expired_copy"})
CREDENTIAL_KINDS = frozenset({"credentialed_tree_control", "credentialed_runtime_control",
                              "measured", "expired_copy"})
NONE_KINDS = frozenset({"help", "tree_control", "runtime_control"})
MODEL_KINDS = KINDS - {"help"}
TREE_KINDS = frozenset({"tree_control", "credentialed_tree_control"})
CONTROL_KINDS = frozenset({"tree_control", "runtime_control", "credentialed_tree_control",
                           "credentialed_runtime_control"})
TOKEN_HOST, TOKEN_PATH = "auth.openai.com", "/oauth/token"
MODEL_HOST, MODEL_PATH = "chatgpt.com", "/backend-api/codex/responses"
#: Contract r5.2 §10.B: the expired copy's access `exp` is the transform clock minus this.
EXPIRED_ACCESS_MARGIN_S = 3600
#: §10.B (B1): the typed row-ready code a Codex row window refuses with.
HOLD_CODE = "codex_expired_leg_unfenced"
#: Fixture values, assembled at run time (none is a credential).
_PROXY_CRED = "-".join(("fixture", "proxy"))
_UNCOPIED = "-".join(("fixture", "not", "copied"))

# Captured before any test stubs the credential module.
from phase_loop_runtime import seat_codex_credential as _cred  # noqa: E402

_REAL_CRED = {name: getattr(_cred, name) for name in (
    "read_auth", "build_seat_copy", "subscription_login_problem", "token_margin_problem",
    "scope_problem")}


@contextlib.contextmanager
def _fresh_supplier():
    """Import the real supplier afresh against a registry without a Codex row, then
    restore the registry, ``sys.modules`` and the package attribute exactly."""
    import phase_loop_runtime
    from phase_loop_runtime import seat_profiles
    name = SUPPLIER.rsplit(".", 1)[1]
    registry = seat_profiles._WINDOW_DATA
    prior = sys.modules.pop(SUPPLIER, None)
    had_attr = hasattr(phase_loop_runtime, name)
    prior_attr = getattr(phase_loop_runtime, name, None)
    seat_profiles._WINDOW_DATA = {vendor: data for vendor, data in registry.items()
                                  if vendor != "codex"}
    try:
        yield importlib.import_module(SUPPLIER)
    finally:
        seat_profiles._WINDOW_DATA = registry
        sys.modules.pop(SUPPLIER, None)
        if prior is not None:
            sys.modules[SUPPLIER] = prior
        if had_attr:
            setattr(phase_loop_runtime, name, prior_attr)
        elif hasattr(phase_loop_runtime, name):
            delattr(phase_loop_runtime, name)


@pytest.fixture
def codex_supplier():
    with _fresh_supplier() as module:
        yield module


def _part(value: dict) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _login(*, scopes=None, last_refresh: str | None = None) -> bytes:
    """A synthetic subscription login. Its token values are assembled at run time; none is
    a credential and none is signed."""
    from phase_loop_runtime import seat_codex_credential as cred
    expires = int(time.time()) + 3600
    claims = {"exp": expires, "scp": sorted(scopes or cred.CODEX_SCOPE_CEILING),
              "https://api.openai.com/auth": {"chatgpt_plan_type": "pro"}}

    def token(body):
        return ".".join((_part({"alg": "none", "typ": "JWT"}), _part(body),
                         secrets.token_urlsafe(12)))
    document = {
        "auth_mode": "chatgpt", "OPENAI_API_KEY": None,
        "last_refresh": last_refresh or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tokens": {"id_token": token({**claims, "email": "fixture@example.invalid"}),
                   "access_token": token(claims), "refresh_token": _UNCOPIED,
                   "account_id": "acct-" + secrets.token_hex(4)},
        "extra_field": "dropped by the copy",
    }
    return json.dumps(document).encode()


def _instant(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


# --------------------------------------------------------------------------------------
# Registration (IF-K1-1 §3, §10.B).
# --------------------------------------------------------------------------------------

def test_sl6_import_registers_codex_window_data(codex_supplier):
    from phase_loop_runtime import seat_profiles, seat_window_supply as supply
    from phase_loop_runtime.seat_profile_codex import CODEX_WINDOW_ROWS
    data = seat_profiles.window_data_for("codex")
    assert data is not None and data.leg == data.vendor == "codex"
    assert dict(data.record_fields) == {
        "canonical": CODEX_WINDOW_ROWS.canonical_record_field,
        "route": CODEX_WINDOW_ROWS.route_record_field,
    } == {"canonical": "canonical_codex", "route": "codex_route"}
    assert data.route_literal == CODEX_WINDOW_ROWS.route_literal == "jailed"
    assert dict(data.board_fields) == dict(seat_profiles.WINDOW_BOARD_FIELDS)
    assert data.supplier == "seat_window_supply_codex" == supply.SUPPLIERS["codex"]
    assert data.windows == frozenset({"row"}) and data.default is False
    assert data.launch_kinds == KINDS and data.credential_kinds == CREDENTIAL_KINDS
    assert data.launch_cap == len(CREDENTIAL_KINDS) + 1 == 5
    assert data.co_seats == frozenset({"claude", "gemini", "grok"})
    assert data.model_leg == "codex" and data.dependency_provider == "codex"
    assert (data.control_launcher, data.board_launcher) == (
        "window_control_launch", "window_board_launch")
    assert data.containment_outcomes["credential_scope"] == frozenset({
        "pass", "codex_seat_token_scope_excess", "unavailable"})
    assert data.containment_outcomes["refresh_detection"] == frozenset({
        "pass", "codex_seat_token_refreshed_in_jail", "unavailable"})
    for surface in ("project_settings", "hooks", "mcp_servers", "provider_overrides"):
        assert data.containment_outcomes[surface] == frozenset({
            "not_loaded", "loaded", "unavailable"})
    # Data is registered by this module only; Gemini's row is untouched.
    assert seat_profiles.window_data_for("gemini") is seat_profiles.GEMINI_WINDOW_DATA
    assert seat_profiles.default_window_data() is seat_profiles.GEMINI_WINDOW_DATA


def test_sl6_codex_binds_this_contract_never_geminis(codex_supplier):
    from phase_loop_runtime import seat_profiles
    data = seat_profiles.window_data_for("codex")
    assert data.contract_sha256 == K1_CONTRACT_SHA256 != GEMINI_CONTRACT_SHA256
    if CONTRACT_PATH.is_file():  # a source tree: the pin is the frozen file's digest
        assert hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() == K1_CONTRACT_SHA256


def test_sl6_supplier_provides_every_protocol_name(codex_supplier):
    from phase_loop_runtime import seat_window_supply as supply
    assert supply.missing_names(codex_supplier) == ()
    assert supply.available("codex") is codex_supplier
    assert set(supply.load_all()) >= {"gemini", "codex"}
    assert codex_supplier.plugin_forms == ("nested",)
    assert callable(codex_supplier.copy_transform)


def test_sl6_reimport_is_idempotent_and_a_rival_row_is_refused(codex_supplier, monkeypatch):
    from phase_loop_runtime import seat_profiles
    data = seat_profiles.window_data_for("codex")
    assert seat_profiles.register_window_data(data) is data
    with pytest.raises(ValueError):
        seat_profiles.register_window_data(dataclasses.replace(
            data, contract_sha256=GEMINI_CONTRACT_SHA256))
    assert seat_profiles.window_data_for("codex") is data


def test_sl6_the_fixture_vendor_hides_the_real_supplier_and_leaks_nothing(codex_supplier):
    """Ruling 2: SL-5's fixture vendor hides the real Codex registration under its own
    monkeypatch, and its teardown brings the real row and module back."""
    import phase_loop_runtime
    from phase_loop_runtime import seat_profiles, seat_window_supply as supply
    from test_seat_window_vendor_neutral import register_fixture_vendor
    real = codex_supplier
    assert seat_profiles.window_data_for("codex") is real.CODEX_WINDOW_DATA
    assert supply.available("codex") is real
    with pytest.MonkeyPatch.context() as patch:
        fixture = register_fixture_vendor(patch)
        assert seat_profiles.window_data_for("codex") is fixture.data
        assert fixture.data is not real.CODEX_WINDOW_DATA
        assert supply.load("codex") is fixture.module
        assert phase_loop_runtime.seat_window_supply_codex is fixture.module
    assert seat_profiles.window_data_for("codex") is real.CODEX_WINDOW_DATA
    assert supply.available("codex") is real and sys.modules[SUPPLIER] is real
    assert phase_loop_runtime.seat_window_supply_codex is real


def test_sl6_profile_allowlist_and_jail_digests_do_not_move(monkeypatch):
    """Stop rule: Codex's profile and allowlist digests are unchanged by the supplier."""
    from phase_loop_runtime import seat_jail, seat_profiles, seat_egress_proxy
    from phase_loop_runtime.seat_profile_codex import CODEX_WINDOW_ROWS
    receipt = json.loads((Path(__file__).parent / "data"
                          / "seat_profile_digests_jailcore.json").read_text())
    # The receipt's own fixed system mounts (test_seat_profiles' golden), on both arches.
    monkeypatch.setattr(seat_jail, "_system_mounts", lambda: [
        "--ro-bind", "/fixed/usr", "/usr", "--perms", "0755", "--dir", "/etc",
        "--ro-bind", "/fixed/etc/hosts", "/etc/hosts",
    ])

    def digests():
        return ({arch: seat_jail.jail_profile_digest("codex", arch) for arch in receipt},
                seat_egress_proxy.allowlist_ref("codex").content_digest)
    before, profile = digests(), seat_profiles.profile_for("codex")
    with _fresh_supplier():
        after = digests()
    assert before == after
    assert after[0] == {arch: rows["codex"] for arch, rows in receipt.items()}
    assert seat_profiles.profile_for("codex") is profile  # registered once, by CODEX
    assert profile.window is CODEX_WINDOW_ROWS and profile.allowlist_id == "codex"


# --------------------------------------------------------------------------------------
# Kinds, credential modes and the expired-copy fixture (§5.1, §10.B).
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", sorted(KINDS))
def test_sl6_credential_mode_per_kind(codex_supplier, kind):
    from phase_loop_runtime import seat_window_supply as supply
    expected = ("expired" if kind == "expired_copy" else
                "none" if kind in NONE_KINDS else "live")
    assert codex_supplier.credential_mode(kind) == expected
    assert expected in supply.CREDENTIAL_MODES


@pytest.mark.parametrize("kind", ["plugin_validation", "invented"])
def test_sl6_a_kind_outside_codex_kinds_has_no_credential_mode(codex_supplier, kind):
    with pytest.raises(ValueError):
        codex_supplier.credential_mode(kind)


def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_sl6_expired_access_copy_changes_only_the_access_exp(codex_supplier):
    """r5.2 §10.B: from the production copy exactly one field changes, the access token's
    ``exp`` (the transform clock minus 3600 s). Header and signature segments are kept byte
    for byte; the ID token, ``last_refresh`` and ``refresh_token: ""`` are unchanged."""
    from phase_loop_runtime import seat_codex_credential as cred
    copy = cred.build_seat_copy(_login())
    clock = 1_900_000_000
    expired = codex_supplier.expired_access_copy(copy, now=clock)
    assert isinstance(expired, cred.CodexSeatCopy)
    before, after = json.loads(copy.data), json.loads(expired.data)
    assert {k: v for k, v in before.items() if k != "tokens"} == {
        k: v for k, v in after.items() if k != "tokens"}  # last_refresh included
    assert {k: v for k, v in before["tokens"].items() if k != "access_token"} == {
        k: v for k, v in after["tokens"].items() if k != "access_token"}  # ID token included
    assert after["tokens"]["refresh_token"] == ""
    old_parts = before["tokens"]["access_token"].split(".")
    new_parts = after["tokens"]["access_token"].split(".")
    assert (new_parts[0], new_parts[2]) == (old_parts[0], old_parts[2])  # byte for byte
    assert "=" not in new_parts[1]  # unpadded base64url
    old_claims, new_claims = _claims(before["tokens"]["access_token"]), _claims(
        after["tokens"]["access_token"])
    assert new_claims == {**old_claims, "exp": clock - EXPIRED_ACCESS_MARGIN_S}
    assert type(new_claims["exp"]) is int and list(new_claims) == list(old_claims)
    # Copy metadata: the hash over the edited tokens, the secrets gain the edited string,
    # and expires_at keeps the live login's value.
    assert expired.tokens_sha256 == cred._tokens_sha256(after["tokens"]) != copy.tokens_sha256
    assert expired.secrets == (*copy.secrets, after["tokens"]["access_token"].encode())
    assert expired.expires_at == copy.expires_at
    assert expired.data == json.dumps(after, sort_keys=True, indent=2).encode()
    assert not cred.tokens_changed(expired, expired.data)  # the seat compares the installed copy


@pytest.mark.parametrize("filler", [0, 1, 2])
def test_sl6_expired_access_copy_payload_is_unpadded_at_every_length(codex_supplier, filler):
    """Unpadded base64url for each padding residue (the payload length mod 3)."""
    from phase_loop_runtime import seat_codex_credential as cred
    copy = cred.build_seat_copy(_login())
    document = json.loads(copy.data)
    header, payload, signature = document["tokens"]["access_token"].split(".")
    claims = {**_claims(document["tokens"]["access_token"]), "f": "x" * filler}
    document["tokens"]["access_token"] = ".".join((header, _part(claims), signature))
    seeded = dataclasses.replace(copy, data=json.dumps(document).encode())
    paddings = set()
    edited = json.loads(codex_supplier.expired_access_copy(seeded, now=1_900_000_000).data)
    edited_payload = edited["tokens"]["access_token"].split(".")[1]
    assert "=" not in edited_payload
    paddings.add(-len(edited_payload) % 4)
    assert _claims(edited["tokens"]["access_token"])["f"] == "x" * filler


def test_sl6_expired_access_copy_payload_lengths_cover_every_residue(codex_supplier):
    from phase_loop_runtime import seat_codex_credential as cred
    copy = cred.build_seat_copy(_login())
    document = json.loads(copy.data)
    header, payload, signature = document["tokens"]["access_token"].split(".")
    residues = set()
    for filler in range(3):
        claims = {**_claims(document["tokens"]["access_token"]), "f": "x" * filler}
        document["tokens"]["access_token"] = ".".join((header, _part(claims), signature))
        edited = json.loads(codex_supplier.expired_access_copy(
            dataclasses.replace(copy, data=json.dumps(document).encode()), now=1).data)
        raw = edited["tokens"]["access_token"].split(".")[1]
        residues.add(len(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))) % 3)
        assert "=" not in raw
    assert residues == {0, 1, 2}  # the padding-free form is checked where padding would occur


def test_sl6_expired_access_copy_uses_the_transform_clock(codex_supplier):
    from phase_loop_runtime import seat_codex_credential as cred
    copy = cred.build_seat_copy(_login())
    before = int(time.time())
    expired = codex_supplier.copy_transform(copy)
    after = int(time.time())
    exp = _claims(json.loads(expired.data)["tokens"]["access_token"])["exp"]
    assert before - EXPIRED_ACCESS_MARGIN_S <= exp <= after - EXPIRED_ACCESS_MARGIN_S
    assert codex_supplier.copy_transform is codex_supplier.expired_access_copy
    assert codex_supplier.EXPIRED_ACCESS_MARGIN_S == EXPIRED_ACCESS_MARGIN_S
    assert not hasattr(codex_supplier, "aged_copy")


@pytest.mark.parametrize("payload", [None, "not-base64!", {"exp": "1"}, {"exp": 1.5},
                                     {"exp": True}, {"scp": []}],
                         ids=["no-payload", "undecodable", "str-exp", "float-exp", "bool-exp",
                              "no-exp"])
def test_sl6_expired_access_copy_refuses_a_token_without_an_integer_exp(codex_supplier,
                                                                        payload):
    from phase_loop_runtime import seat_codex_credential as cred
    copy = cred.build_seat_copy(_login())
    document = json.loads(copy.data)
    parts = document["tokens"]["access_token"].split(".")
    if payload is None:
        document["tokens"]["access_token"] = parts[0]
    elif isinstance(payload, str):
        document["tokens"]["access_token"] = ".".join((parts[0], payload, parts[2]))
    else:
        document["tokens"]["access_token"] = ".".join((parts[0], _part(payload), parts[2]))
    broken = dataclasses.replace(copy, data=json.dumps(document).encode())
    with pytest.raises(ValueError, match="contract_bug"):
        codex_supplier.expired_access_copy(broken)


def test_sl6_expired_access_copy_refuses_anything_but_a_codex_copy(codex_supplier):
    with pytest.raises(TypeError):
        codex_supplier.copy_transform(b'{"tokens": {}}')


# --------------------------------------------------------------------------------------
# Argv (§5.1: one launch, the production command, no provider or config override).
# --------------------------------------------------------------------------------------

def _production(model):
    from phase_loop_runtime.seat_codex_runtime import CODEX_RUNTIME_ROOT
    from phase_loop_runtime.seat_profile_codex import jailed_codex_command
    from phase_loop_runtime.seat_route_contract import ArgvInputs
    return jailed_codex_command(ArgvInputs(f"{CODEX_RUNTIME_ROOT}/bin/codex", model=model))


def _command(supplier, kind, model="gpt-fixture"):
    commands = supplier.launch_command(kind, qualification_input=SimpleNamespace(),
                                       model=model, plugin_paths=())
    assert isinstance(commands, tuple) and len(commands) == 1  # exactly one start
    assert all(isinstance(arg, str) for arg in commands[0])
    return commands[0]


@pytest.mark.parametrize("kind", sorted(MODEL_KINDS))
def test_sl6_model_kinds_run_the_production_command(codex_supplier, kind):
    argv, production = list(_command(codex_supplier, kind)), list(_production("gpt-fixture"))
    assert production[-1] == "-"  # the prompt comes on stdin, from the kit (ruling 4)
    if kind in TREE_KINDS:
        cd = production.index("--cd")
        production[cd + 1] = "/seat/tree"
    assert argv == production


def test_sl6_help_starts_no_model_turn(codex_supplier):
    from phase_loop_runtime.seat_codex_runtime import CODEX_RUNTIME_ROOT
    argv = _command(codex_supplier, "help")
    assert argv[0] == f"{CODEX_RUNTIME_ROOT}/bin/codex" and "--help" in argv
    assert "--model" not in argv and "-" not in argv


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_sl6_no_kind_overrides_the_provider_or_config(codex_supplier, kind):
    argv = _command(codex_supplier, kind)
    def overrides(command):
        return [command[i + 1] for i, arg in enumerate(command[:-1])
                if arg in {"-c", "--config"}]
    # Only production's own configuration values, never one a test or fixture adds.
    assert set(overrides(argv)) <= set(overrides(_production("gpt-fixture"))), argv
    assert not any(arg.startswith(("--profile", "--oss", "model_provider")) for arg in argv)
    assert not any("model_providers" in arg or "base_url" in arg for arg in argv)


def test_sl6_a_kind_outside_codex_kinds_has_no_command(codex_supplier):
    with pytest.raises(ValueError):
        codex_supplier.launch_command("plugin_validation", qualification_input=None,
                                      model="m", plugin_paths=("x",))


# --------------------------------------------------------------------------------------
# Stream facts (the CLI's ``--json`` events, IF-0-CODEX-4's vocabulary).
# --------------------------------------------------------------------------------------

def _events(*items) -> str:
    return "".join(json.dumps(item) + "\n" for item in items)


_STARTED = ({"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"})
_MESSAGE = {"type": "item.completed", "item": {"id": "m", "type": "agent_message",
                                                 "text": "READY"}}


def _command_item(ident):
    return {"type": "item.completed", "item": {
        "id": ident, "type": "command_execution", "command": "cat x", "status": "completed",
        "exit_code": 0, "aggregated_output": "ok\n"}}


def test_sl6_stream_facts_of_a_completed_turn(codex_supplier):
    raw = _events(*_STARTED, _command_item("c1"), _command_item("c2"), _MESSAGE,
                  {"type": "turn.completed", "usage": {}})
    assert codex_supplier.stream_facts(raw) == ("SUCCESS", True, 2, 0)


def test_sl6_stream_facts_of_a_failed_turn(codex_supplier):
    raw = _events(*_STARTED, {"type": "error", "message": "refused"},
                  {"type": "turn.failed", "error": {"message": "refused"}})
    status, model_turn, _tools, _subagents = codex_supplier.stream_facts(raw)
    assert status == "FAILURE" and model_turn is not True


@pytest.mark.parametrize("raw", [
    "",
    _events(*_STARTED, _MESSAGE),                        # no terminal event
    _events(*_STARTED, _MESSAGE, {"type": "turn.completed"}).rstrip("\n"),  # truncated
    _events(*_STARTED, {"type": "invented.event"}, {"type": "turn.completed"}),
    "not json\n",
    _events({"type": "turn.completed"}),                 # completed without a start
], ids=["empty", "unterminated", "truncated", "unknown-event", "not-json", "no-start"])
def test_sl6_an_incomplete_or_unknown_stream_is_never_success(codex_supplier, raw):
    status, _model_turn, _tools, _subagents = codex_supplier.stream_facts(raw)
    assert status == "NONE"


# --------------------------------------------------------------------------------------
# Terminal classes (§5.5) and the refused-intended signature (§10, §10.B).
# --------------------------------------------------------------------------------------

def _event(method, host, path, decision):
    from phase_loop_runtime.seat_egress_proxy import RequestEvent
    return RequestEvent(method=method, host=host, path=path, decision=decision)


def _stream(*events, final=True, protocol_error=False, end_acked=True, start_acked=True):
    from phase_loop_runtime.seat_egress_proxy import ProxyStream, ProxyWindow
    return ProxyStream(final=final, protocol_error=protocol_error, windows=(
        ProxyWindow(label="leg", start_acked=start_acked, end_acked=end_acked,
                    events=tuple(events)),), outside_events=(), allowlist_sha256="6" * 64)


_DENIED_TOKEN = _event("POST", TOKEN_HOST, TOKEN_PATH, "deny")
_DENIED_TOKEN_CONNECT = _event("CONNECT", TOKEN_HOST, None, "deny")
_MODEL = _event("POST", MODEL_HOST, MODEL_PATH, "allow")


_NAMED_DENIAL = _DENIED_TOKEN_CONNECT  # the production named observation, denied
_ACCOUNT_CHECK = _event("GET", MODEL_HOST, "/backend-api/wham/accounts/check", "allow")
_OTHER_DENY = _event("CONNECT", "<other>", None, "deny")
#: The sha256 of ``Bearer `` plus the installed expired access token (a fixture value).
_BEARER = hashlib.sha256(("Bearer " + "-".join(("expired", "fixture"))).encode()).hexdigest()


def _proof(*digests, expected=_BEARER):
    """The loopback fixture's bearer proof: the expected Authorization sha256 and the one
    the responder recorded for each model request it answered, in order (``None`` when the
    header was absent)."""
    return {"expected_sha256": expected, "model_requests": list(digests)}


def _observation(kind="expired_copy", *, status="FAILURE", stream=None, error=None,
                 timed_out=False, model_turn=False, refresh="pass", proof=None):
    observation = SimpleNamespace(
        kind=kind, status=status, error=error, timed_out=timed_out, model_turn=model_turn,
        quiescent=True, bridge_exited=True,
        stream=_stream(_NAMED_DENIAL) if stream is None else stream,
        scan=None if refresh is None else {"scope": "pass", "refresh": refresh})
    if proof is not None:
        observation.bearer_proof = proof
    return observation


_RUN3_OTHER = (_OTHER_DENY,) * 5


@pytest.mark.parametrize("changes", [
    {"status": "FAILURE"}, {"status": "NONE"}, {"status": "SUCCESS"},
    {"status": "NONE", "timed_out": True},
    {"status": "NONE", "timed_out": True, "error": "launch_failed"},
], ids=["failure", "no-json", "success", "own-deadline", "own-deadline-kit"])
def test_sl6_r52_production_expired_leg_is_refused_intended_whatever_the_exit(
        codex_supplier, changes):
    """r5.2 §10.B / E2: the named denial, no allowed request of any kind and no credential
    change, in a complete fenced stream, is ``refused_intended`` whatever the CLI's exit,
    a stop at the launch's own deadline included."""
    observation = _observation(stream=_stream(_NAMED_DENIAL, *_RUN3_OTHER), **changes)
    assert codex_supplier.terminal(observation) == "refused_intended"


@pytest.mark.parametrize("changes", [
    {"status": "SUCCESS", "model_turn": True}, {"status": "FAILURE"},
    {"status": "NONE", "timed_out": True},
], ids=["success", "failure", "own-deadline"])
def test_sl6_r52_fixture_expired_leg_with_matching_bearers_is_refused_intended(
        codex_supplier, changes):
    """The loopback fixture only: model requests after the named denial (D1's cached
    fallback) pass when each carries the installed expired bearer."""
    events = (_ACCOUNT_CHECK, _NAMED_DENIAL, _ACCOUNT_CHECK, _MODEL, _MODEL)
    observation = _observation(stream=_stream(*events), proof=_proof(_BEARER, _BEARER),
                               **changes)
    assert codex_supplier.terminal(observation) == "refused_intended"


def test_sl6_r52_run3_not_ready_shape_with_the_named_denial_first_is_refused_intended(
        codex_supplier):
    events = ((_NAMED_DENIAL,) + tuple(_event(*row) for row in _RUN3_NOT_READY))
    observation = _observation(stream=_stream(*events), status="NONE", timed_out=True)
    assert codex_supplier.terminal(observation) == "refused_intended"


_POST_TUNNEL = _DENIED_TOKEN  # a request event to the token host: the CONNECT was tunnelled


@pytest.mark.parametrize("events,proof,refresh", [
    ((_POST_TUNNEL,), None, "pass"),
    ((_NAMED_DENIAL, _POST_TUNNEL), None, "pass"),
    ((_event("CONNECT", TOKEN_HOST, None, "allow"),), None, "pass"),
    ((_NAMED_DENIAL, _event("GET", TOKEN_HOST, "/.well-known/x", "deny")), None, "pass"),
    ((_OTHER_DENY, _OTHER_DENY), None, "pass"),
    ((_event("CONNECT", "ab.chatgpt.com", None, "deny"),), None, "pass"),
    ((_NAMED_DENIAL,), None, "codex_seat_token_refreshed_in_jail"),
    ((_NAMED_DENIAL,), None, "unavailable"),
    ((_NAMED_DENIAL,), None, None),
    ((_NAMED_DENIAL, _ACCOUNT_CHECK), None, "pass"),
    ((_NAMED_DENIAL, _MODEL), None, "pass"),
    ((_MODEL, _NAMED_DENIAL, _MODEL), _proof(_BEARER, _BEARER), "pass"),
    ((_NAMED_DENIAL, _MODEL), _proof("0" * 64), "pass"),
    ((_NAMED_DENIAL, _MODEL), _proof(None), "pass"),
    ((_NAMED_DENIAL, _MODEL, _MODEL), _proof(_BEARER), "pass"),
    ((_NAMED_DENIAL, _event("POST", MODEL_HOST, MODEL_PATH, "deny")), _proof(), "pass"),
    ((_NAMED_DENIAL, _event("POST", TOKEN_HOST, TOKEN_PATH, "allow")), _proof(), "pass"),
], ids=["post-tunnel", "denial-then-post-tunnel", "connect-allowed", "token-host-get",
        "generic-other-only", "other-named-host-only", "tokens-changed", "refresh-unavailable",
        "no-credential-read", "production-allowed-request", "production-model-request",
        "model-before-denial", "bearer-mismatch", "bearer-header-missing",
        "model-request-without-bearer", "denied-model-request", "allowed-token-endpoint"])
def test_sl6_r52_expired_failure_conditions_are_never_refused_intended(
        codex_supplier, events, proof, refresh):
    observation = _observation(stream=_stream(*events), proof=proof, refresh=refresh)
    assert codex_supplier.terminal(observation) != "refused_intended"


@pytest.mark.parametrize("changes,expected", [
    ({"error": "jail_unavailable"}, "jail_failure"),
    ({"error": "proxy_unavailable"}, "proxy_failure"),
    ({"error": "fence_unacknowledged"}, "proxy_failure"),
    ({"error": "credential_unavailable"}, "not_ready"),
    ({"error": "stage_refused"}, "other_failure"),
    ({"error": "launch_failed"}, "other_failure"),
    ({"stream": _stream(_NAMED_DENIAL, final=False)}, "stream_incomplete"),
    ({"stream": _stream(_NAMED_DENIAL, end_acked=False)}, "stream_incomplete"),
    ({"stream": _stream(_NAMED_DENIAL, protocol_error=True)}, "stream_incomplete"),
    ({"stream": _stream(_NAMED_DENIAL, final=False), "timed_out": True}, "timeout"),
], ids=["jail", "proxy", "fence", "credential", "other-error", "failed-not-at-deadline",
        "not-final", "no-end-fence", "protocol-error", "incomplete-at-deadline"])
def test_sl6_r52_expired_stream_conditions_never_cover_failures(codex_supplier, changes,
                                                                expected):
    assert codex_supplier.terminal(_observation(**changes)) == expected


@pytest.mark.parametrize("exit_code", [-9, -15, 137, 143])
def test_sl6_a_signalled_cli_never_reaches_refused_intended_or_not_ready(codex_supplier,
                                                                        exit_code):
    """Pre-run review item 1: a CLI ended by a signal (not the launch's own deadline) is a
    process failure, never ``refused_intended`` after an otherwise qualifying stream and
    never ``not_ready`` before any traffic."""
    qualifying = _observation(stream=_stream(_NAMED_DENIAL, *_RUN3_OTHER), status="NONE")
    qualifying.exit_code = exit_code
    assert codex_supplier.terminal(qualifying) == "other_failure"
    silent = _observation(stream=_stream(), status="NONE")
    silent.exit_code = exit_code
    assert codex_supplier.terminal(silent) == "other_failure"


@pytest.mark.parametrize("exit_code", [None, 0, 1])
def test_sl6_an_ordinary_exit_or_the_own_deadline_keeps_its_class(codex_supplier, exit_code):
    qualifying = _observation(stream=_stream(_NAMED_DENIAL), status="FAILURE")
    qualifying.exit_code = exit_code
    assert codex_supplier.terminal(qualifying) == "refused_intended"
    deadline = _observation(stream=_stream(_NAMED_DENIAL), status="NONE", timed_out=True)
    deadline.exit_code = None  # the launch's own 120 s deadline: no exit status
    assert codex_supplier.terminal(deadline) == "refused_intended"
    # The launch's own deadline kill may leave a signal status; it stays the own mechanism.
    deadline.exit_code = -9
    assert codex_supplier.terminal(deadline) == "refused_intended"


def test_sl6_r52_run3_aged_shape_is_not_refused_intended(codex_supplier):
    """Run 3's aged case: account checks allowed, no token-host event at all."""
    events = tuple(_event(*row) for row in _RUN3_ACCOUNT_CHECKS)
    observation = _observation(stream=_stream(*events))
    assert codex_supplier.terminal(observation) == "other_failure"


@pytest.mark.parametrize("events", [
    (_MODEL, _DENIED_TOKEN), (_DENIED_TOKEN, _MODEL),
    (_event("POST", TOKEN_HOST, TOKEN_PATH, "allow"),),
], ids=["model-before", "model-after", "token-allowed"])
def test_sl6_a_model_request_or_an_allowed_token_request_is_not_refused_intended(
        codex_supplier, events):
    assert codex_supplier.terminal(_observation(stream=_stream(*events))) != "refused_intended"


@pytest.mark.parametrize("observation,expected", [
    (_observation(stream=_stream(_DENIED_TOKEN, final=False)), "stream_incomplete"),
    (_observation(stream=_stream(_DENIED_TOKEN, end_acked=False)), "stream_incomplete"),
    (_observation(stream=_stream(_DENIED_TOKEN, protocol_error=True)), "stream_incomplete"),
    (_observation(status="NONE", stream=_stream(_DENIED_TOKEN)), "stream_incomplete"),
    (_observation(error="jail_unavailable"), "jail_failure"),
    (_observation(error="watch_unavailable"), "jail_failure"),
    (_observation(error="proxy_unavailable"), "proxy_failure"),
    (_observation(error="fence_unacknowledged"), "proxy_failure"),
    (_observation(timed_out=True, stream=_stream(_DENIED_TOKEN)), "timeout"),
    (_observation(error="credential_unavailable"), "not_ready"),
], ids=["not-final", "no-end-fence", "protocol-error", "cli-incomplete", "jail", "watch",
        "proxy", "fence", "timeout", "credential"])
def test_sl6_refused_intended_never_covers_incomplete_or_failed_infrastructure(
        codex_supplier, observation, expected):
    assert codex_supplier.terminal(observation) == expected


@pytest.mark.parametrize("status", ["FAILURE", "NONE"])
def test_sl6_a_cli_failing_before_its_credential_path_is_not_ready(codex_supplier, status):
    # A complete fence with no request at all, whether or not the CLI wrote a JSON stream.
    observation = _observation(status=status, stream=_stream())
    assert codex_supplier.terminal(observation) == "not_ready"


#: A-C1 run 3's recorded not-ready leg window (the CLI with no copy, 0.167.0): 32 denied
#: CONNECTs to unnamed hosts and one to the named ``ab.chatgpt.com``, in that order.
_RUN3_NOT_READY = (
    *(("CONNECT", "<other>", None, "deny"),) * 27, ("CONNECT", "ab.chatgpt.com", None, "deny"),
    *(("CONNECT", "<other>", None, "deny"),) * 5)
#: Run 3's fresh-case window shape: allowlisted account checks and denied other paths.
_RUN3_ACCOUNT_CHECKS = (
    ("GET", MODEL_HOST, "<other>", "deny"),
    ("GET", MODEL_HOST, "/backend-api/wham/accounts/check", "allow"),
    ("POST", MODEL_HOST, "<other>", "deny"))


def _run3(events, **changes):
    return _observation(**{"stream": _stream(*(_event(*row) for row in events)), **changes})


@pytest.mark.parametrize("status", ["NONE", "FAILURE"])
def test_sl6_run3_not_ready_window_is_not_ready(codex_supplier, status):
    """Ruling 3: denied CONNECTs to non-token, non-model hosts are not the credential
    path; with no token-host event, no model request and no allowed request the CLI that
    ended by itself failed before its credential path."""
    assert len(_RUN3_NOT_READY) == 33
    observation = _run3(_RUN3_NOT_READY, status=status, model_turn=None)
    assert codex_supplier.terminal(observation) == "not_ready"


def test_sl6_run3_not_ready_window_that_timed_out_stays_timeout(codex_supplier):
    observation = _run3(_RUN3_NOT_READY, status="NONE", model_turn=None, timed_out=True)
    assert codex_supplier.terminal(observation) == "timeout"


@pytest.mark.parametrize("kind,expected", [("expired_copy", "refused_intended"),
                                           ("measured", "auth_refused")])
def test_sl6_a_denied_token_host_among_other_denials_is_the_credential_path(
        codex_supplier, kind, expected):
    events = (*_RUN3_NOT_READY[:3], ("CONNECT", TOKEN_HOST, None, "deny"), *_RUN3_NOT_READY[3:6])
    assert codex_supplier.terminal(_run3(events, kind=kind)) == expected


@pytest.mark.parametrize("status", ["NONE", "FAILURE"])
def test_sl6_an_allowed_request_is_never_not_ready(codex_supplier, status):
    """Run 3's fresh shape: an allowed account check means the CLI used its credential."""
    observation = _run3(_RUN3_ACCOUNT_CHECKS, status=status)
    assert codex_supplier.terminal(observation) not in {"not_ready", "refused_intended"}


@pytest.mark.parametrize("status", ["NONE", "FAILURE"])
def test_sl6_a_model_request_is_never_not_ready(codex_supplier, status):
    observation = _run3((*_RUN3_NOT_READY[:2], ("POST", MODEL_HOST, MODEL_PATH, "deny")),
                        status=status)
    assert codex_supplier.terminal(observation) != "not_ready"


def test_sl6_refused_intended_is_only_the_expired_copy_kind(codex_supplier):
    assert codex_supplier.terminal(_observation(kind="measured")) != "refused_intended"


def test_sl6_measured_completes_only_on_a_model_turn(codex_supplier):
    good = _observation("measured", status="SUCCESS", model_turn=True, stream=_stream(_MODEL))
    assert codex_supplier.terminal(good) == "completed"
    no_turn = SimpleNamespace(**{**vars(good), "model_turn": None})
    assert codex_supplier.terminal(no_turn) != "completed"


def test_sl6_every_terminal_is_a_closed_class(codex_supplier):
    from phase_loop_runtime import seat_window_supply as supply
    for status in ("SUCCESS", "FAILURE", "NONE"):
        for kind in sorted(KINDS):
            for stream in (_stream(), _stream(_MODEL), _stream(_DENIED_TOKEN), None):
                observation = _observation(kind, status=status, model_turn=status == "SUCCESS",
                                           stream=stream if stream is not None else _stream())
                assert codex_supplier.terminal(observation) in supply.TERMINAL_CLASSES


# --------------------------------------------------------------------------------------
# Token endpoint, scope, refresh and the secret scan.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("event,expected", [
    (_event("POST", TOKEN_HOST, TOKEN_PATH, "deny"), True),
    (_event("POST", TOKEN_HOST, TOKEN_PATH, "allow"), True),
    (_event("CONNECT", TOKEN_HOST, None, "deny"), True),
    (_event("GET", TOKEN_HOST, "/.well-known/openid-configuration", "deny"), False),
    (_event("POST", MODEL_HOST, MODEL_PATH, "allow"), False),
    (_event("POST", "oauth2.googleapis.com", "/token", "deny"), False),
    (_event("POST", "<other>", "<other>", "deny"), False),
])
def test_sl6_token_endpoint(codex_supplier, event, expected):
    assert codex_supplier.token_endpoint(event) is expected


def _seat(tmp_path, copy, *, proxy_cred=_PROXY_CRED):
    from phase_loop_runtime import seat_jail
    seat_dir = tmp_path / "seat"
    home = seat_dir / seat_jail.HOST_HOME_DIRNAME
    (home / ".codex").mkdir(parents=True)
    if copy is not None:
        auth = home / ".codex" / "auth.json"
        auth.write_bytes(copy.data)
        auth.chmod(0o600)
    proxy = f"http://srt:{proxy_cred}@127.0.0.1:3128" if proxy_cred else ""
    return SimpleNamespace(
        seat_dir=seat_dir, review_dir=tmp_path / "review", codex_copy=copy, holder_pid=1,
        delivered_copy=copy.data if copy is not None else b"", token=b"",
        jail=SimpleNamespace(env={"HTTPS_PROXY": proxy}))


def _no_network(monkeypatch):
    import socket
    import urllib.request

    def refuse(*args, **kwargs):
        pytest.fail("the scope measurement made a network call")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def test_sl6_scope_is_measured_on_the_host_without_an_issuer_call(codex_supplier, tmp_path,
                                                                  monkeypatch):
    from phase_loop_runtime import seat_codex_credential as cred
    _no_network(monkeypatch)
    copy = cred.build_seat_copy(_login())
    assert codex_supplier.measure_credential_scope(_seat(tmp_path, copy)) == "pass"
    excess = json.loads(copy.data)
    claims = json.loads(base64.urlsafe_b64decode(
        excess["tokens"]["access_token"].split(".")[1] + "=="))
    claims["scp"] = [*claims["scp"], "api.responses.write"]
    parts = excess["tokens"]["access_token"].split(".")
    parts[1] = _part(claims)
    excess["tokens"]["access_token"] = ".".join(parts)
    wide = dataclasses.replace(copy, data=json.dumps(excess).encode())
    assert codex_supplier.measure_credential_scope(
        _seat(tmp_path / "wide", wide)) == "codex_seat_token_scope_excess"
    assert codex_supplier.measure_credential_scope(
        _seat(tmp_path / "none", None)) == "unavailable"


def _read_in_h_from_host(monkeypatch):
    """The seat's files are read in H in production (``seat_uid.read_in_h``); here the fake
    seat's own host files stand in, read at that boundary."""
    from phase_loop_runtime import seat_uid

    def read(holder_pid, root, relpath, cap_bytes, **kwargs):
        path = Path(root) / relpath
        if not path.exists():
            raise seat_uid.SeatObjectMissing(relpath)
        return path.read_bytes()[:cap_bytes]
    monkeypatch.setattr(seat_uid, "read_in_h", read)


def test_sl6_refresh_detection(codex_supplier, tmp_path, monkeypatch):
    from phase_loop_runtime import seat_codex_credential as cred, seat_jail
    _read_in_h_from_host(monkeypatch)
    copy = cred.build_seat_copy(_login())
    seat = _seat(tmp_path, copy)
    assert codex_supplier.refresh_detected(seat) == "pass"
    auth = seat.seat_dir / seat_jail.HOST_HOME_DIRNAME / ".codex" / "auth.json"
    document = json.loads(auth.read_bytes())
    document["tokens"]["access_token"] = document["tokens"]["access_token"] + "x"
    auth.write_text(json.dumps(document))
    assert codex_supplier.refresh_detected(seat) == "codex_seat_token_refreshed_in_jail"
    assert codex_supplier.refresh_detected(_seat(tmp_path / "none", None)) == "unavailable"
    auth.unlink()  # a removed copy is a credential event
    assert codex_supplier.refresh_detected(seat) == "codex_seat_token_refreshed_in_jail"


def test_sl6_secret_scan_is_the_copy_and_the_proxy_credential(codex_supplier, tmp_path):
    from phase_loop_runtime import seat_codex_credential as cred
    copy = cred.build_seat_copy(_login())
    live = codex_supplier.scan_secrets(_seat(tmp_path, copy))
    assert set(live) == {*copy.secrets, _PROXY_CRED.encode()}
    # ``none``: the proxy credential alone (§5.1).
    assert tuple(codex_supplier.scan_secrets(_seat(tmp_path / "n", None))) == (
        _PROXY_CRED.encode(),)


def test_sl6_host_paths_are_codexs(codex_supplier, tmp_path):
    from phase_loop_runtime import seat_codex_credential as cred, seat_jail
    seat = _seat(tmp_path, cred.build_seat_copy(_login()))
    home = seat.seat_dir / seat_jail.HOST_HOME_DIRNAME
    with_credential = codex_supplier.host_path_map(seat, credential=True)
    assert with_credential.tree == seat.review_dir / seat_jail.HOST_TREE_DIRNAME
    assert with_credential.seat_home == home
    assert with_credential.seat_out == seat.seat_dir / seat_jail.HOST_OUT_DIRNAME
    assert with_credential.delivered_credential == home / cred.SEAT_AUTH_RELPATH
    assert codex_supplier.host_path_map(seat, credential=False).delivered_credential is None


# --------------------------------------------------------------------------------------
# Rows (§10.B): CODEX_WINDOW_ROWS, runtime rows re-rooted at provider_config, the home row.
# --------------------------------------------------------------------------------------

def test_sl6_plant_layout_is_codexs_rows(codex_supplier):
    from phase_loop_runtime.seat_profile_codex import CODEX_TREE_ROWS, CODEX_WINDOW_ROWS
    layout = codex_supplier.plant_layout(plugin_form="nested", window=CODEX_WINDOW_ROWS)
    ids = [row.row_id for row in layout.rows]
    assert len(ids) == len(set(ids))
    roles = {row.row_id: row.role for row in layout.rows}
    for path, role in CODEX_TREE_ROWS:
        assert roles[f"tree:{path}"] == role
    runtime = {f"provider_config:{path.removeprefix('.codex/')}": role
               for path, role in CODEX_TREE_ROWS if path.startswith(".codex/")}
    runtime["provider_config:AGENTS.md"] = "provider_overrides"
    for row_id, role in runtime.items():
        assert roles[row_id] == role, row_id
    assert roles["home:.codex/config.toml"] == "project_settings"
    assert not any("gemini" in row_id.lower() or "antigravity" in row_id for row_id in ids)
    assert layout.plugin_form == "nested"


def test_sl6_plant_layout_refuses_the_plugin_json_form(codex_supplier):
    from phase_loop_runtime.seat_profile_codex import CODEX_WINDOW_ROWS
    with pytest.raises(ValueError):
        codex_supplier.plant_layout(plugin_form="plugin_json", window=CODEX_WINDOW_ROWS)


def test_sl6_seed_plants_runtime_rows_at_codex_paths_and_observes_the_home_row(
        codex_supplier, tmp_path):
    from phase_loop_runtime import seat_codex_credential as cred
    from phase_loop_runtime.seat_profile_codex import CODEX_WINDOW_ROWS
    layout = codex_supplier.plant_layout(plugin_form="nested", window=CODEX_WINDOW_ROWS)
    seat = _seat(tmp_path, cred.build_seat_copy(_login()))
    paths = codex_supplier.host_path_map(seat, credential=True)
    (paths.seat_home / ".codex" / "auth.json").unlink()
    codex_supplier.seed_runtime_plants(layout, paths)
    nonces = {row.row_id: row.nonce for row in layout.rows}
    home = paths.seat_home
    assert nonces["provider_config:rules/default.rules"] in (
        home / ".codex/rules/default.rules").read_text()
    assert nonces["provider_config:AGENTS.md"] in (home / ".codex/AGENTS.md").read_text()
    assert nonces["workdir:AGENTS.md"] in (home / "workspace/AGENTS.md").read_text()
    assert nonces["home:AGENTS.md"] in (home / "AGENTS.md").read_text()
    # The home row is the provider config's own file: planted once, never twice.
    assert nonces["provider_config:config.toml"] in (home / ".codex/config.toml").read_text()
    assert nonces["home:.codex/config.toml"] not in (home / ".codex/config.toml").read_text()
    assert not (home / ".codex/.codex").exists() and not list(paths.tree.glob("*"))


def test_sl6_seed_refuses_a_symlinked_runtime_ancestor(codex_supplier, tmp_path):
    from phase_loop_runtime import seat_codex_credential as cred
    from phase_loop_runtime import seat_jail_qualification as jailq
    from phase_loop_runtime.seat_profile_codex import CODEX_WINDOW_ROWS
    layout = codex_supplier.plant_layout(plugin_form="nested", window=CODEX_WINDOW_ROWS)
    seat = _seat(tmp_path, cred.build_seat_copy(_login()))
    paths = codex_supplier.host_path_map(seat, credential=True)
    (tmp_path / "elsewhere").mkdir()
    (paths.seat_home / "workspace").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(jailq.PlantLayoutRefused):
        codex_supplier.seed_runtime_plants(layout, paths)
    assert not list((tmp_path / "elsewhere").iterdir())


def test_sl6_a_foreign_or_edited_layout_is_refused(codex_supplier, tmp_path):
    from phase_loop_runtime import seat_jail_qualification as jailq
    from phase_loop_runtime.seat_profile_codex import CODEX_WINDOW_ROWS
    gemini = jailq.plant_layout(plugin_form="nested")
    with pytest.raises(jailq.PlantLayoutRefused):
        codex_supplier.build_qualification_input(gemini, tmp_path / "in")
    layout = codex_supplier.plant_layout(plugin_form="nested", window=CODEX_WINDOW_ROWS)
    edited = dataclasses.replace(layout, rows=layout.rows[:-1])
    with pytest.raises(jailq.PlantLayoutRefused):
        codex_supplier.build_qualification_input(edited, tmp_path / "in")


def test_sl6_build_qualification_input_commits_the_tree_rows(codex_supplier, tmp_path):
    import subprocess
    from phase_loop_runtime import seat_jail_qualification as jailq
    from phase_loop_runtime.seat_profile_codex import CODEX_TREE_ROWS, CODEX_WINDOW_ROWS
    layout = codex_supplier.plant_layout(plugin_form="nested", window=CODEX_WINDOW_ROWS)
    qi = codex_supplier.build_qualification_input(layout, tmp_path / "in")
    assert isinstance(qi, jailq.QualificationInput) and qi.layout is layout
    for path, _role in CODEX_TREE_ROWS:
        assert (qi.repo / path).exists(), path
    assert (qi.repo / jailq.WINDOW_READ_PATH).is_file()
    head = subprocess.run(["git", "-C", str(qi.repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    assert head == qi.commit and not subprocess.run(
        ["git", "-C", str(qi.repo), "status", "--porcelain"], check=True,
        capture_output=True, text=True).stdout


# --------------------------------------------------------------------------------------
# F16: Codex through window_control_launch and the real _prepare_jailed_codex, with the
# provider stubbed at its spawn boundary.
# --------------------------------------------------------------------------------------

def _real_credentials(monkeypatch, raw: bytes):
    """Undo the shared stubs' credential fakes: the real checks and copy over ``raw``."""
    from phase_loop_runtime import seat_codex_credential as cred
    for name, value in _REAL_CRED.items():
        monkeypatch.setattr(cred, name, value)
    monkeypatch.setattr(cred, "read_auth", lambda env=None: raw)


def _control_world(monkeypatch, tmp_path, supplier, *, stdout, stream=None, **stubs):
    from phase_loop_runtime import panel_invoker as panel
    seen = _codex_open_stubs(monkeypatch, tmp_path, **stubs)
    raw = _login()
    _real_credentials(monkeypatch, raw)
    watch = SimpleNamespace(prove_sentinel=lambda run: True,
                            drain_and_close=lambda quiescent: "watch")
    monkeypatch.setattr(supplier, "arm_watch", lambda *a, **k: watch)
    monkeypatch.setattr(supplier, "seed_runtime_plants", lambda *a: None)
    if stream is not None:
        monkeypatch.setattr(panel._seat_egress_proxy, "proxy_stream", lambda proxy: stream)

    def spawn(command, **kwargs):
        seen["spawned"].append(list(command))
        if not str(command[0]).startswith("/usr/bin/python3"):  # not a kit bracket step
            seen.setdefault("provider_spawned", []).append(list(command))
            seen.setdefault("inputs", []).append(kwargs.get("input_text"))
        if isinstance(stdout, BaseException):
            raise stdout
        return SimpleNamespace(returncode=0, stdout=stdout)
    monkeypatch.setattr(panel, "_run_leg_with_liveness", spawn)
    seen["raw"] = raw
    from phase_loop_runtime import seat_uid

    def read_in_h(holder_pid, root, relpath, cap_bytes, **kwargs):
        # The installed copy, as the seat's file reads back unchanged in H.
        if not seen["installed"]:
            raise seat_uid.SeatObjectMissing(relpath)
        return seen["installed"][-1].data
    monkeypatch.setattr(seat_uid, "read_in_h", read_in_h)
    return seen


_COMPLETED = _events(*_STARTED, _MESSAGE, {"type": "turn.completed"})
_FAILED = _events(*_STARTED, {"type": "error", "message": "refused"},
                  {"type": "turn.failed", "error": {"message": "refused"}})


@pytest.mark.parametrize("kind,installed,refuse_all", [
    ("tree_control", "none", True), ("runtime_control", "none", True),
    ("credentialed_tree_control", "live", False), ("measured", "live", False),
    ("expired_copy", "expired", False)])
def test_sl6_f16_control_launches_through_the_real_prepare(
        codex_supplier, tmp_path, monkeypatch, kind, installed, refuse_all):
    from phase_loop_runtime import panel_invoker as panel
    seen = _control_world(monkeypatch, tmp_path, codex_supplier, stdout=_COMPLETED)
    result = panel.window_control_launch(_codex_spec(kind, tmp_path))
    assert seen["proxies"] == [("codex", refuse_all)]
    production = _REAL_CRED["build_seat_copy"](seen["raw"])
    if installed == "none":
        assert seen["installed"] == []
    elif installed == "live":  # byte-for-byte the production copy
        assert [item.data for item in seen["installed"]] == [production.data]
    else:
        (expired,) = seen["installed"]  # r5.2: only the access token's exp differs
        after, before = json.loads(expired.data), json.loads(production.data)
        assert {k: v for k, v in after["tokens"].items() if k != "access_token"} == {
            k: v for k, v in before["tokens"].items() if k != "access_token"}
        assert {k: v for k, v in after.items() if k != "tokens"} == {
            k: v for k, v in before.items() if k != "tokens"}
        assert _claims(after["tokens"]["access_token"])["exp"] < time.time()
    command = codex_supplier.launch_command(kind, qualification_input=None, model="m",
                                            plugin_paths=())
    # Exactly once, the supplier's argv (the measured kind's kit bracket steps aside).
    assert seen["provider_spawned"] == [list(command[0])]
    assert result.binding.argv_sha256 == panel._window_json_digest([list(command[0])])
    # The kit's own input, on stdin, bound by digest exactly as Gemini's.
    expected = (panel._WINDOW_CONTROL_INPUT if kind in CONTROL_KINDS
                else panel._WINDOW_MEASURED_INPUT)
    (delivered,) = seen["inputs"]
    assert delivered == panel._render_broker_pointer_prompt(
        "", expected, source_commit="2" * 40, staged_tree_sha256="d" * 64,
        model_only_network=True)
    assert result.binding.input_sha256 == hashlib.sha256(expected.encode()).hexdigest()
    # The binding names the image the jail actually bound, never "None".
    assert result.binding.image_sha256 == seen["image_sha256"] != "None"
    assert result.binding.admission_class == "None"  # pinned unset (code review rules)
    # The allowlist's own refused hosts are named, and naming moves no allowlist digest.
    assert seen["named"] == [panel._window_named_refusals("codex")]
    assert ("CONNECT", TOKEN_HOST, None) in seen["named"][0]


def test_sl6_admission_class_is_pinned_unset(tmp_path, monkeypatch):
    """SL-6 ruling 5 / A-C1 ruling 6: Codex's admission gate returns a verdict and no
    class, so a window seat's ``admission_class`` stays unset (the binding records
    ``str(None)``). This pins today's value so a code-review ruling that changes it shows."""
    from phase_loop_runtime import panel_invoker as panel
    from test_seat_window_vendor_neutral import _codex_prepare_stubs
    seen = _codex_prepare_stubs(monkeypatch, tmp_path)
    seat = panel._window_prepare_leg(
        "codex", tmp_path / "review", tmp_path / "seat", SimpleNamespace(
            staged_tree_sha256="c" * 64), 1, 2, ("artifact", "instructions"),
        SimpleNamespace(ca_cert=b"ca", proxy_url="http://p"), credential_mode="none",
        copy_transform=None)
    assert seat.admission_class is None and str(seat.admission_class) == "None"
    assert seat.image_sha256 == seen["image_sha256"]


def test_sl6_f16_help_has_no_input(codex_supplier, tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as panel
    seen = _control_world(monkeypatch, tmp_path, codex_supplier, stdout="usage\n")
    result = panel.window_control_launch(_codex_spec("help", tmp_path))
    assert seen["inputs"] == [None] and result.binding.input_sha256 is None


def test_sl6_named_refusals_are_the_allowlists_and_move_no_digest():
    from phase_loop_runtime import panel_invoker as panel, seat_egress_proxy
    before = seat_egress_proxy.allowlist_ref("codex").content_digest
    named = panel._window_named_refusals("codex")
    refused = seat_egress_proxy.allowlist("codex")["measured_and_refused"]
    assert named == tuple(("CONNECT", host, None) for host in refused) and len(named) <= 16
    assert seat_egress_proxy.allowlist_ref("codex").content_digest == before


@pytest.mark.parametrize("failure,expected", [
    ("timeout", "timeout"), ("jail", "jail_failure"), ("not_ready", "not_ready"),
    ("proxy", "proxy_failure"), ("incomplete", "stream_incomplete")])
def test_sl6_f16_failure_modes_reach_a_closed_terminal_class(
        codex_supplier, tmp_path, monkeypatch, failure, expected):
    from phase_loop_runtime import panel_invoker as panel, seat_codex_credential as cred
    from phase_loop_runtime import seat_window_supply as supply
    stdout = (panel.subprocess.TimeoutExpired(["codex"], 5) if failure == "timeout" else
              "" if failure == "incomplete" else _COMPLETED)
    seen = _control_world(
        monkeypatch, tmp_path, codex_supplier, stdout=stdout, stream=_stream(_MODEL),
        proxy_error=(panel._seat_egress_proxy.EgressLayerUnavailable(
            "seat_egress_proxy_unavailable", "fixture") if failure == "proxy" else None))
    if failure == "jail":
        monkeypatch.setattr(panel, "_build_jail_with_owned_inputs", lambda *a, **k: (
            _ for _ in ()).throw(panel._seat_jail.SeatSandboxRefused(
                "seat_sandbox_refused:jail_build")))
    if failure == "not_ready":
        monkeypatch.setattr(cred, "token_margin_problem",
                            lambda raw, now: "codex_seat_token_expiring")
    result = panel.window_control_launch(_codex_spec("measured", tmp_path))
    terminal = codex_supplier.terminal(result)
    assert terminal == expected and terminal in supply.TERMINAL_CLASSES
    assert len(seen.get("provider_spawned", [])) <= 1  # never a retry


def test_sl6_f16_measured_completes(codex_supplier, tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as panel
    _control_world(monkeypatch, tmp_path, codex_supplier, stdout=_COMPLETED,
                   stream=_stream(_MODEL))
    measured = panel.window_control_launch(_codex_spec("measured", tmp_path))
    assert codex_supplier.terminal(measured) == "completed"


def test_sl6_f16_expired_copy_is_refused_intended(codex_supplier, tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as panel
    _control_world(monkeypatch, tmp_path, codex_supplier, stdout=_FAILED,
                   stream=_stream(_NAMED_DENIAL))
    expired = panel.window_control_launch(_codex_spec("expired_copy", tmp_path))
    assert codex_supplier.terminal(expired) == "refused_intended"


@pytest.mark.parametrize("returncode", [-9, -15, 137, 143])
def test_sl6_f16_a_signalled_expired_cli_is_never_refused_intended(
        codex_supplier, tmp_path, monkeypatch, returncode):
    """Review thread (agent-harness#2082): through the real window_control_launch and
    WindowLaunchResult, an expired-copy CLI ended by a signal after the named denial (a
    complete fenced stream that would otherwise be refused_intended) is a launch failure,
    never refused_intended. The launch's own deadline keeps its E2 reading."""
    from phase_loop_runtime import panel_invoker as panel
    seen = _control_world(monkeypatch, tmp_path, codex_supplier, stdout=_FAILED,
                          stream=_stream(_NAMED_DENIAL))
    spawn = panel._run_leg_with_liveness

    def killed(command, **kwargs):
        done = spawn(command, **kwargs)
        return SimpleNamespace(returncode=returncode, stdout=done.stdout)
    monkeypatch.setattr(panel, "_run_leg_with_liveness", killed)
    expired = panel.window_control_launch(_codex_spec("expired_copy", tmp_path))
    assert len(seen["provider_spawned"]) == 1
    assert expired.timed_out is False and expired.error == "launch_failed"
    assert codex_supplier.terminal(expired) == "other_failure"
    context = _context(codex_supplier)
    reduction = codex_supplier.reduce_containment(dataclasses.replace(
        context, expired_copy=dataclasses.replace(
            context.expired_copy, error=expired.error, timed_out=expired.timed_out)))
    assert reduction.owner_summary.expired_copy_control == "unavailable"
    assert reduction.containment["refresh_detection"] == "unavailable"


@pytest.mark.parametrize("returncode", [0, 1])
def test_sl6_f16_an_ordinary_expired_exit_stays_refused_intended(
        codex_supplier, tmp_path, monkeypatch, returncode):
    from phase_loop_runtime import panel_invoker as panel
    _control_world(monkeypatch, tmp_path, codex_supplier, stdout=_FAILED,
                   stream=_stream(_NAMED_DENIAL))
    spawn = panel._run_leg_with_liveness
    monkeypatch.setattr(panel, "_run_leg_with_liveness", lambda command, **kwargs: (
        SimpleNamespace(returncode=returncode, stdout=spawn(command, **kwargs).stdout)))
    expired = panel.window_control_launch(_codex_spec("expired_copy", tmp_path))
    assert expired.error is None
    assert codex_supplier.terminal(expired) == "refused_intended"


def test_sl6_f16_the_expired_legs_own_deadline_keeps_its_e2_reading(
        codex_supplier, tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as panel
    _control_world(monkeypatch, tmp_path, codex_supplier,
                   stdout=panel.subprocess.TimeoutExpired(["codex"], 5, output=_FAILED),
                   stream=_stream(_NAMED_DENIAL))
    expired = panel.window_control_launch(_codex_spec("expired_copy", tmp_path))
    assert expired.timed_out is True and expired.error == "launch_failed"
    assert codex_supplier.terminal(expired) == "refused_intended"


def test_sl6_f16_none_launches_with_no_copy_and_refuses_without_one(
        codex_supplier, tmp_path, monkeypatch):
    """``none``: no copy is built or installed, and a model-capable launch without a copy
    fails before any credential path (``not_ready``), never ``refused_intended``."""
    from phase_loop_runtime import panel_invoker as panel, seat_codex_credential as cred
    _control_world(monkeypatch, tmp_path, codex_supplier, stdout=_FAILED, stream=_stream())
    monkeypatch.setattr(cred, "build_seat_copy", lambda raw: pytest.fail("copy built"))
    result = panel.window_control_launch(_codex_spec("tree_control", tmp_path))
    assert codex_supplier.terminal(result) != "refused_intended"


def test_sl6_f16_production_prepare_default_is_unchanged():
    from phase_loop_runtime import panel_invoker as panel
    parameters = inspect.signature(panel._prepare_jailed_codex).parameters
    assert parameters["credential_mode"].default == "live"
    assert parameters["copy_transform"].default is None


def test_sl6_f16_a_window_launch_never_retries(codex_supplier, tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as panel
    seen = _control_world(monkeypatch, tmp_path, codex_supplier, stdout=_FAILED,
                          stream=_stream(_DENIED_TOKEN))
    panel.window_control_launch(_codex_spec("expired_copy", tmp_path))
    assert len(seen["provider_spawned"]) == 1


# --------------------------------------------------------------------------------------
# One fixture context through cli_main: verify --vendor codex --window row passes, and the
# record changes only vendor:codex.
# --------------------------------------------------------------------------------------

def test_sl6_hold_a_row_qualify_refuses_unfenced_and_launches_nothing(
        codex_supplier, tmp_path, monkeypatch):
    """r5.2 §10.B (B1): until the OI-1 fence lane lands, a Codex row window refuses with
    the typed row-ready code before any claim, preflight, jail or proxy."""
    from phase_loop_runtime import panel_invoker as panel, seat_window as w

    def never(*args, **kwargs):
        pytest.fail("the hold let a Codex row window start")
    for target, name in ((w, "claim_window_attempt"), (w, "preflight"),
                         (w, "run_native_window"), (panel, "_open_window_launch"),
                         (panel, "window_control_launch"), (panel, "window_board_launch"),
                         (panel, "_prepare_jailed_codex"),
                         (panel._seat_egress_proxy, "start_proxy"),
                         (panel._sandbox_egress, "isolated_network")):
        monkeypatch.setattr(target, name, never)
    result = w.qualify(window="row", monitoring_policy="bounded", repo=tmp_path,
                       attended=True, vendor="codex")
    assert result == {"status": "candidate", "code": HOLD_CODE}
    assert codex_supplier.ROW_WINDOW_HOLD == HOLD_CODE


def test_sl6_the_hold_is_codexs_alone(codex_supplier):
    from phase_loop_runtime import seat_window as w
    assert w._row_ready_codes("gemini")[0] is None  # Gemini's row is not held
    assert w._row_ready_codes("codex") == (HOLD_CODE, None)


def _codex_row_world(tmp_path, monkeypatch, supplier):
    # These fixture-context row tests alone lift the hold (plan SL-6.1); no Codex row
    # window can run in production until the OI-1 fence lands.
    monkeypatch.setattr(supplier, "ROW_WINDOW_HOLD", None)
    world = _row_world(tmp_path, monkeypatch, "codex")
    stubbed = supplier.reduce_containment

    def reduce_containment(inputs):  # the shared harness binds its fixture contract
        reduction = stubbed(inputs)
        return dataclasses.replace(reduction, binding={
            **reduction.binding, "contract_sha256": K1_CONTRACT_SHA256})
    monkeypatch.setattr(supplier, "reduce_containment", reduce_containment)
    return world


def test_sl6_one_context_through_cli_main_verifies_and_changes_only_codex(
        codex_supplier, tmp_path, monkeypatch, capsys):
    from phase_loop_runtime import cli, seat_window as w
    world = _codex_row_world(tmp_path, monkeypatch, codex_supplier)
    capsys.readouterr()
    code = cli.main(["--repo", str(tmp_path), "seat-window", "qualify", "--window", "row",
                     "--vendor", "codex", "--attended"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["code"] == "window_review_required", out
    (path,) = world.root.glob("window-row-codex-*.json")
    assert cli.main(["seat-window", "verify", "--window", "row", "--vendor", "codex",
                     "--record", str(path)]) == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["code"] == "window_verified", verdict
    record = world.record()
    assert record["containment_binding"]["contract_sha256"] == K1_CONTRACT_SHA256
    assert record["rows"] == ["vendor:codex"]
    before = {row["id"]: row for row in w.readiness_rows()}
    after = w.reduce_readiness(world.records(), now=ROW_NOW, source_root=world.root)
    changed = {row["id"] for row in after if row != before[row["id"]]}
    assert changed == {"vendor:codex"}
    assert next(row for row in after if row["id"] == "vendor:codex")["status"] == "done-local"


@pytest.mark.parametrize("field", ["profile_digest", "allowlist_digest", "contract"])
def test_sl6_a_codex_record_carrying_geminis_digests_fails(codex_supplier, tmp_path,
                                                           monkeypatch, field):
    from phase_loop_runtime import seat_jail, seat_egress_proxy
    world = _codex_row_world(tmp_path, monkeypatch, codex_supplier)
    assert _run_row(world, monkeypatch)["code"] == "window_review_required"
    assert world.verify()["passed"] is True
    record = world.record()
    if field == "contract":
        record["containment_binding"]["contract_sha256"] = GEMINI_CONTRACT_SHA256
    elif field == "profile_digest":
        record[field] = seat_jail.jail_profile_digest("gemini")
    else:
        record[field] = seat_egress_proxy.allowlist_ref("gemini").content_digest
    world.rewrite(record)
    assert world.verify()["passed"] is False


# --------------------------------------------------------------------------------------
# SL-6.5 (review B1): Codex's own I-5 watch, definition probe and I-13 reducer. Every case
# below goes through the real supplier's functions on frozen WindowLaunchResults.
# --------------------------------------------------------------------------------------

_ARGV = {"help": "1" * 64, "tree": "2" * 64, "production": "3" * 64}
_IMAGE, _STAGE = "b" * 64, "d" * 64
_SURFACES = ("project_settings", "hooks", "mcp_servers", "provider_overrides")
_FIELDS = ("credential_scope", "refresh_detection", *_SURFACES)


def _allowlist_digests():
    from phase_loop_runtime import seat_egress_proxy as proxy
    production = proxy._digest(list(proxy.allowlist_ref("codex").request_set))
    return {"refuse_all": proxy._digest([]), "production": production,
            "gemini": proxy._digest(list(proxy.allowlist_ref("gemini").request_set))}


def _inputs():
    from phase_loop_runtime import panel_invoker as panel
    return {"control": hashlib.sha256(panel._WINDOW_CONTROL_INPUT.encode()).hexdigest(),
            "measured": hashlib.sha256(panel._WINDOW_MEASURED_INPUT.encode()).hexdigest(),
            "board": panel.window_board_input_sha256()}


def _binding(kind, *, admission="release_qualified", allowlist=None, argv=None,
             input_sha256="auto", profile=None, image=_IMAGE):
    from phase_loop_runtime import seat_jail, seat_jail_qualification as jailq
    digests, inputs = _allowlist_digests(), _inputs()
    role = "refuse_all" if kind in NONE_KINDS else "production"
    if input_sha256 == "auto":
        input_sha256 = (None if kind == "help" else inputs["control"]
                        if kind in CONTROL_KINDS else inputs["measured"])
    if argv is None:
        argv = _ARGV["help" if kind == "help" else "tree" if kind in TREE_KINDS
                     else "production"]
    return jailq.LaunchBinding(
        image_sha256=image, admission_class=admission, stage_manifest_sha256=_STAGE,
        argv_sha256=argv, input_sha256=input_sha256,
        jail_profile_sha256=profile or seat_jail.jail_profile_digest("codex"),
        allowlist_sha256=digests[role] if allowlist is None else allowlist)


def _watch(*, opened=(), changed=(), credential_events=0, read_marker=True, **changes):
    from phase_loop_runtime import seat_jail_qualification as jailq
    values = dict(armed_ns=1, closed_ns=9, sentinel_observed=True, overflow=False,
                  read_marker_opened=read_marker, drained_after_quiescence=True,
                  opened_rows=tuple(opened), changed_rows=tuple(changed),
                  row_ancestor_created=False, credential_path_events=credential_events,
                  pre_row_sha256={}, pre_tree_manifest_sha256="0" * 64)
    values.update(changes)
    return jailq.WatchObservation(**values)


def _fence(acknowledged=True):
    from phase_loop_runtime.seat_egress_proxy import FenceResult
    return FenceResult(fence_id="f" if acknowledged else "", acknowledged=acknowledged,
                       acked_ns=1 if acknowledged else None)


def _full_bracket(supplier, **row_changes):
    rows = tuple(supplier.BracketRow(
        row=name, outcome="refused",
        signature=row_changes.get(name, sorted(supplier.BRACKET_SIGNATURES[name])[0]))
        for name in supplier.BRACKET_ROW_NAMES)
    return supplier.BracketResult(start=_fence(), end=_fence(), post_refused=True, rows=rows)


def _windows_stream(leg=(), bracket=None, outside=()):
    from phase_loop_runtime.seat_egress_proxy import ProxyStream, ProxyWindow
    windows = [ProxyWindow(label="leg", start_acked=True, end_acked=True, events=tuple(leg))]
    if bracket is not None:
        windows.append(ProxyWindow(label="bracket", start_acked=True, end_acked=True,
                                   events=tuple(bracket)))
    return ProxyStream(final=True, protocol_error=False, windows=tuple(windows),
                       outside_events=tuple(outside), allowlist_sha256="6" * 64)


_BRACKET_EVENTS = (_DENIED_TOKEN_CONNECT, _event("CONNECT", "ab.chatgpt.com", None, "deny"),
                   _event("GET", MODEL_HOST, "<other>", "deny"))


def _result(kind, **changes):
    from phase_loop_runtime import seat_jail_qualification as jailq
    values = dict(
        kind=kind, status="SUCCESS", timed_out=False, error=None, quiescent=True,
        model_turn=True, tool_steps=0, subagent_steps=0,
        stream=_windows_stream(leg=(_ACCOUNT_CHECK, _MODEL)), bridge_exited=True,
        lookups=None, created=None, lookup_complete=None, watch=_watch(),
        scan={"scope": "pass", "refresh": "pass"} if kind in CREDENTIAL_KINDS else None,
        first_jailed_launch_ns=2, bracket=None, issuer=None, delivered_copy_sha256=None,
        help_sha256=None, help_lists_plugin=None, plugin_validation=None,
        binding=_binding(kind))
    if kind == "help":
        values.update(model_turn=None, tool_steps=None, subagent_steps=None, stream=None,
                      help_sha256="c" * 64, help_lists_plugin=False)
    values.update(changes)
    return jailq.WindowLaunchResult(**values)


def _rows_by_role(layout, location):
    rows = {}
    for row in layout.rows:
        if row.location == location:
            rows.setdefault(row.role, row.row_id)
    return rows


def _context(supplier, **parts):
    """A complete, passing Codex context: every surface defined by the controls, a clean
    measured leg with its whole Codex bracket, an expired leg that ends refused_intended,
    and a board leg bound to the same launch identity."""
    from phase_loop_runtime import seat_jail_qualification as jailq
    layout = parts.pop("layout", None) or supplier.plant_layout(plugin_form="nested")
    tree_rows = tuple(_rows_by_role(layout, "tree").values())
    runtime_rows = tuple(_rows_by_role(layout, "provider_config").values())
    controls = parts.pop("controls", None) or (
        _result("tree_control", watch=_watch(opened=tree_rows)),
        _result("runtime_control", watch=_watch(opened=runtime_rows)),
        _result("credentialed_tree_control", watch=_watch(opened=tree_rows)),
        _result("credentialed_runtime_control", watch=_watch(opened=runtime_rows)))
    measured = parts.pop("measured", "default")
    if measured == "default":
        measured = _result("measured", tool_steps=1, bracket=_full_bracket(supplier),
                           stream=_windows_stream(leg=(_ACCOUNT_CHECK, _MODEL),
                                                  bracket=_BRACKET_EVENTS))
    expired = parts.pop("expired", "default")
    if expired == "default":
        expired = _result("expired_copy", status="FAILURE", model_turn=False,
                          stream=_windows_stream(leg=(_NAMED_DENIAL, _OTHER_DENY)))
    board = parts.pop("board", "default")
    if board == "default":
        board = jailq.BoardLegObservation(
            watch=_watch(), stream=_windows_stream(leg=(_ACCOUNT_CHECK, _MODEL)),
            input_sha256=_inputs()["board"], binding=_binding("measured", argv="4" * 64))
    values = dict(
        context=supplier.ContextBinding(context_id="c" + "1" * 31, account_label="a" + "2" * 31,
                                        dependency_subject_sha256=None,
                                        dependency_projection_sha256=None),
        layout=layout, help=_result("help"), plugin_validation=None, controls=controls,
        measured=measured, expired_copy=expired, board=board)
    values.update(parts)
    return supplier.ContainmentInputs(**values)


def _reasons(reduction, field):
    return reduction.owner_summary.unavailable_reasons[field]


def test_sl6_codex_owns_its_containment_types(codex_supplier):
    from phase_loop_runtime import seat_jail_qualification as jailq, seat_window_supply as supply
    assert codex_supplier.ContextBinding is not jailq.ContextBinding
    assert codex_supplier.ContainmentInputs is not jailq.ContainmentInputs
    assert codex_supplier.ContextBinding.__module__ == SUPPLIER
    assert codex_supplier.ContainmentInputs.__module__ == SUPPLIER
    assert supply.available("codex") is codex_supplier  # every protocol name is supplied
    with pytest.raises(TypeError):  # Gemini's input type is not Codex's
        codex_supplier.reduce_containment(jailq.ContainmentInputs(
            **{name: getattr(_context(codex_supplier), name)
               for name in ("context", "layout", "help", "plugin_validation", "controls",
                            "measured", "expired_copy", "board")}))


_FIRSTSEAT_REDUCER_NAMES = (
    "reduce_containment", "definition_probe", "ContextBinding", "ContainmentInputs",
    "ContainmentReduction", "OwnerSummary", "DefinitionResult", "VoidedControl",
    "_launch_binding_valid", "_binding_identity", "_layout_complete", "_expired_copy_state",
    "_bracket_valid", "_stream_complete", "_watch_complete", "_credential_event",
    "_control_void_reasons", "_count_lookup", "_lookup_is_known", "_positive_surfaces",
    "_positive_board_surfaces", "_row_post_changed", "_runtime_or_home_change",
    "_leg_token_events", "_outside_token_events", "_token_endpoint_events",
    "_unexpected_bracket_token_events", "_request_is_token_endpoint", "_all_events",
    "_plain", "_add_reason", "_valid_digest", "_sha256_text", "CONTAINMENT_CONTRACT_SHA256",
    "_BINDING_KEYS", "_VALIDATOR_IMPLEMENTATION_SHA256", "_WATCH_IMPLEMENTATION_SHA256",
    "_PROXY_IMPLEMENTATION_SHA256", "_COUNTED_ADMISSION_CLASSES", "_INFERENCE_HOSTS")


def test_sl6_reducer_is_self_contained(codex_supplier, monkeypatch):
    """OI-1 Step 0: Codex's reducer uses no FIRSTSEAT reducer, definition or binding
    helper, under any spelling: no import of one by any alias, no attribute of the module
    under any alias, and none is called when a complete context is reduced."""
    import ast
    from phase_loop_runtime import seat_jail_qualification as jailq
    tree = ast.parse(inspect.getsource(sys.modules[SUPPLIER]))
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                if (node.module or "").endswith("seat_jail_qualification"):
                    assert item.name not in _FIRSTSEAT_REDUCER_NAMES, item.name
                if item.name == "seat_jail_qualification":
                    aliases.add(item.asname or item.name)
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name.endswith("seat_jail_qualification"):
                    aliases.add(item.asname or item.name)
    assert "jailq" in aliases  # every alias is checked below, not only this one
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id in aliases:
            assert node.attr not in _FIRSTSEAT_REDUCER_NAMES, node.attr
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "getattr" \
                and node.args and getattr(node.args[0], "id", None) in aliases:
            assert False, "dynamic attribute of seat_jail_qualification"
    context = _context(codex_supplier)

    def forbidden(*args, **kwargs):
        pytest.fail("Codex's reducer called a FIRSTSEAT reducer helper")
    for name in _FIRSTSEAT_REDUCER_NAMES:
        if callable(getattr(jailq, name, None)):
            monkeypatch.setattr(jailq, name, forbidden)
    reduction = codex_supplier.reduce_containment(context)
    assert reduction.admitted is True and all(reduction.checks.values())


def test_sl6_reducer_passes_a_complete_context_and_the_kit_accepts_it(codex_supplier,
                                                                     monkeypatch):
    from phase_loop_runtime import seat_jail_qualification as jailq, seat_window as w
    reduction = codex_supplier.reduce_containment(_context(codex_supplier))
    assert dict(reduction.containment) == {
        "credential_scope": "pass", "refresh_detection": "pass",
        **dict.fromkeys(_SURFACES, "not_loaded")}, reduction.owner_summary.unavailable_reasons
    assert reduction.admitted is True and all(reduction.checks.values())
    # The kit's own acceptance checks (seat_window.run_native_window and the verifier).
    private, binding = w._json_value(reduction.private), w._json_value(reduction.binding)
    owner = w._json_value(reduction.owner_summary)
    assert set(private) == set(w.PRIVATE_FIELDS)
    # Codex takes no post-launch tree manifest, so the record says unmeasured (None), never
    # "no differences" (False). The kit's verifier requires a bool there, so this record
    # cannot verify until a measured manifest exists (the deferred watch-scan finding).
    assert private["manifest_differences"] is None
    assert w._private_observation_valid(private) is False
    assert w._private_observation_valid({**private, "manifest_differences": True})
    assert w.digest(private) == reduction.observation_sha256
    assert w._containment_outcomes_valid(w._json_value(reduction.containment),
                                         codex_supplier.CODEX_WINDOW_DATA)
    assert set(binding) == set(w.BINDING_FIELDS)
    assert set(owner) == set(w.OWNER_SUMMARY_FIELDS)
    assert owner["schema"] == "seat_window_owner_summary.v1"
    assert type(owner["counted_lookups"]) is dict and owner["counted_lookups"] == {}
    digests = _allowlist_digests()
    assert binding["contract_sha256"] == K1_CONTRACT_SHA256 != GEMINI_CONTRACT_SHA256
    assert binding["production_allowlist_sha256"] == digests["production"]
    assert binding["refuse_all_allowlist_sha256"] == digests["refuse_all"]
    assert binding["help_sha256"] == "c" * 64
    assert (binding["control_argv_sha256"], binding["production_argv_sha256"]) == (
        _ARGV["tree"], _ARGV["production"])
    record = {"context_id": binding["context_id"], "account_label": binding["account_label"],
              "contract": None, "profile_digest": binding["jail_profile_sha256"],
              "allowlist_digest": binding["production_allowlist_sha256"],
              "board_input_digest": binding["board_input_sha256"], "vendor": "codex"}
    monkeypatch.setattr(w, "_record_contract_sha256", lambda record: K1_CONTRACT_SHA256)
    assert w._binding_valid(binding, record)
    # Nothing Gemini-shaped is bound.
    assert binding["watch_sha256"] != jailq._WATCH_IMPLEMENTATION_SHA256
    assert binding["validator_sha256"] != jailq._VALIDATOR_IMPLEMENTATION_SHA256


@pytest.mark.parametrize("kind", ["measured", "expired_copy", "credentialed_tree_control",
                                  "credentialed_runtime_control"])
@pytest.mark.parametrize("allowlist", ["refuse_all", "gemini"])
def test_sl6_reducer_requires_the_production_allowlist(codex_supplier, kind, allowlist):
    """The production rule set's digest is required on every credentialed launch (the
    expired leg included, until OI-1's fence edits that one seam)."""
    digest = _allowlist_digests()[allowlist]
    context = _context(codex_supplier)
    if kind == "measured":
        context = dataclasses.replace(context, measured=dataclasses.replace(
            context.measured, binding=_binding(kind, allowlist=digest)))
    elif kind == "expired_copy":
        context = dataclasses.replace(context, expired_copy=dataclasses.replace(
            context.expired_copy, binding=_binding(kind, allowlist=digest)))
    else:
        context = dataclasses.replace(context, controls=tuple(
            dataclasses.replace(item, binding=_binding(kind, allowlist=digest))
            if item.kind == kind else item for item in context.controls))
    reduction = codex_supplier.reduce_containment(context)
    assert not any(reduction.checks.values())
    assert all("binding_mismatch" in _reasons(reduction, name) for name in _FIELDS)


@pytest.mark.parametrize("kind", ["help", "tree_control", "runtime_control"])
def test_sl6_reducer_requires_refuse_all_on_the_none_kinds(codex_supplier, kind):
    production = _allowlist_digests()["production"]
    context = _context(codex_supplier)
    if kind == "help":
        context = dataclasses.replace(context, help=_result(
            "help", binding=_binding("help", allowlist=production)))
    else:
        context = dataclasses.replace(context, controls=tuple(
            dataclasses.replace(item, binding=_binding(kind, allowlist=production))
            if item.kind == kind else item for item in context.controls))
    reduction = codex_supplier.reduce_containment(context)
    assert all("binding_mismatch" in _reasons(reduction, name) for name in _FIELDS)


def test_sl6_the_expired_leg_binds_production_today(codex_supplier):
    """The one seam OI-1 edits: today the expired leg's role is ``production``."""
    assert codex_supplier._allowlist_role("expired_copy") == "production"
    assert {kind: codex_supplier._allowlist_role(kind) for kind in KINDS} == {
        **dict.fromkeys(NONE_KINDS, "refuse_all"),
        **dict.fromkeys(CREDENTIAL_KINDS, "production")}


@pytest.mark.parametrize("change", [
    "image", "stage", "profile", "gemini_profile", "argv_collision", "control_input",
    "help_digest", "no_help", "board_input", "board_allowlist", "foreign_layout"])
def test_sl6_reducer_binding_mismatches_fail_closed(codex_supplier, change):
    from phase_loop_runtime import seat_jail, seat_jail_qualification as jailq
    context = _context(codex_supplier)
    measured = context.measured
    if change == "image":
        context = dataclasses.replace(context, measured=dataclasses.replace(
            measured, binding=_binding("measured", image="e" * 64)))
    elif change == "stage":
        context = dataclasses.replace(context, measured=dataclasses.replace(
            measured, binding=dataclasses.replace(measured.binding,
                                                  stage_manifest_sha256="e" * 64)))
    elif change in ("profile", "gemini_profile"):
        profile = "e" * 64 if change == "profile" else seat_jail.jail_profile_digest("gemini")
        rebind = lambda item: dataclasses.replace(  # noqa: E731
            item, binding=dataclasses.replace(item.binding, jail_profile_sha256=profile))
        context = dataclasses.replace(
            context, help=rebind(context.help), controls=tuple(map(rebind, context.controls)),
            measured=rebind(measured), expired_copy=rebind(context.expired_copy),
            board=dataclasses.replace(context.board, binding=dataclasses.replace(
                context.board.binding, jail_profile_sha256=profile)))
    elif change == "argv_collision":
        context = dataclasses.replace(context, controls=tuple(
            dataclasses.replace(item, binding=dataclasses.replace(
                item.binding, argv_sha256=_ARGV["production"])) for item in context.controls))
    elif change == "control_input":
        context = dataclasses.replace(context, controls=tuple(
            dataclasses.replace(item, binding=dataclasses.replace(
                item.binding, input_sha256=_inputs()["measured"]))
            for item in context.controls))
    elif change == "help_digest":
        context = dataclasses.replace(context, help=_result("help", help_sha256=None))
    elif change == "no_help":
        context = dataclasses.replace(context, help=None)
    elif change == "board_input":
        context = dataclasses.replace(context, board=dataclasses.replace(
            context.board, input_sha256="e" * 64))
    elif change == "board_allowlist":
        context = dataclasses.replace(context, board=dataclasses.replace(
            context.board, binding=dataclasses.replace(
                context.board.binding, allowlist_sha256=_allowlist_digests()["refuse_all"])))
    else:
        context = dataclasses.replace(context, layout=jailq.plant_layout(plugin_form="nested"))
    reduction = codex_supplier.reduce_containment(context)
    assert not any(reduction.checks.values())
    assert all("binding_mismatch" in _reasons(reduction, name) for name in _FIELDS), change


@pytest.mark.parametrize("admission", ["None", ""])
def test_sl6_reducer_treats_the_none_admission_class_as_no_class(codex_supplier, monkeypatch,
                                                                 admission):
    """Review condition: the kit binds ``str(seat.admission_class)``, so a Codex seat with
    no class binds ``"None"``. The reducer reads that as no class, never as a class value:
    the record is not admitted even if a class table were to list the string."""
    context = _context(codex_supplier)
    rebind = lambda item: dataclasses.replace(  # noqa: E731
        item, binding=dataclasses.replace(item.binding, admission_class=admission))
    context = dataclasses.replace(
        context, help=rebind(context.help), controls=tuple(map(rebind, context.controls)),
        measured=rebind(context.measured), expired_copy=rebind(context.expired_copy),
        board=dataclasses.replace(context.board, binding=dataclasses.replace(
            context.board.binding, admission_class=admission)))
    monkeypatch.setattr(codex_supplier, "_COUNTED_ADMISSION_CLASSES",
                        frozenset({"release_qualified", "locally_qualified", admission}))
    reduction = codex_supplier.reduce_containment(context)
    assert reduction.admitted is False
    assert set(reduction.containment.values()) == {"unavailable"}
    assert all("not_admitted" in _reasons(reduction, name) for name in _FIELDS)
    assert reduction.binding["admission_class"] == admission  # bound as observed


@pytest.mark.parametrize("subject,admitted", [(_IMAGE, True), ("e" * 64, False), (None, False)])
def test_sl6_reducer_admits_an_executable_dependency_only_on_its_subject(
        codex_supplier, subject, admitted):
    context = _context(codex_supplier)
    rebind = lambda item: dataclasses.replace(  # noqa: E731
        item, binding=dataclasses.replace(item.binding, admission_class="executable_dependency"))
    context = dataclasses.replace(
        context, help=rebind(context.help), controls=tuple(map(rebind, context.controls)),
        measured=rebind(context.measured), expired_copy=rebind(context.expired_copy),
        board=dataclasses.replace(context.board, binding=dataclasses.replace(
            context.board.binding, admission_class="executable_dependency")),
        context=dataclasses.replace(context.context, dependency_subject_sha256=subject))
    assert codex_supplier.reduce_containment(context).admitted is admitted


_ALLOWED_TOKEN = _event("POST", TOKEN_HOST, TOKEN_PATH, "allow")


@pytest.mark.parametrize("where", [
    "measured_leg", "measured_outside", "measured_bracket", "expired_leg",
    "measured_tokens_changed", "expired_tokens_changed", "measured_watch", "expired_watch"])
def test_sl6_refresh_is_detected_by_either_section_10b_arm(codex_supplier, where):
    """§10.B: refresh via ``tokens_changed`` or an allowed token-endpoint request, giving
    ``codex_seat_token_refreshed_in_jail``."""
    context = _context(codex_supplier)
    measured, expired = context.measured, context.expired_copy
    if where == "measured_leg":
        measured = dataclasses.replace(measured, stream=_windows_stream(
            leg=(_ALLOWED_TOKEN, _MODEL), bracket=_BRACKET_EVENTS))
    elif where == "measured_outside":
        measured = dataclasses.replace(measured, stream=_windows_stream(
            leg=(_MODEL,), bracket=_BRACKET_EVENTS, outside=(_ALLOWED_TOKEN,)))
    elif where == "measured_bracket":
        measured = dataclasses.replace(measured, stream=_windows_stream(
            leg=(_MODEL,), bracket=(*_BRACKET_EVENTS, _ALLOWED_TOKEN)))
    elif where == "expired_leg":
        expired = dataclasses.replace(expired, stream=_windows_stream(
            leg=(_NAMED_DENIAL, _ALLOWED_TOKEN)))
    elif where.endswith("tokens_changed"):
        target = measured if where.startswith("measured") else expired
        target = dataclasses.replace(target, scan={
            "scope": "pass", "refresh": "codex_seat_token_refreshed_in_jail"})
        measured, expired = ((target, expired) if where.startswith("measured")
                             else (measured, target))
    else:
        target = measured if where.startswith("measured") else expired
        target = dataclasses.replace(target, watch=_watch(credential_events=1))
        measured, expired = ((target, expired) if where.startswith("measured")
                             else (measured, target))
    reduction = codex_supplier.reduce_containment(
        dataclasses.replace(context, measured=measured, expired_copy=expired))
    assert reduction.containment["refresh_detection"] == "codex_seat_token_refreshed_in_jail"
    assert reduction.checks["refresh_detection"] is False
    assert reduction.owner_summary.private_route is True


def test_sl6_a_denied_token_request_is_not_a_refresh_but_never_passes(codex_supplier):
    context = _context(codex_supplier)
    measured = dataclasses.replace(context.measured, stream=_windows_stream(
        leg=(_DENIED_TOKEN_CONNECT, _MODEL), bracket=_BRACKET_EVENTS))
    reduction = codex_supplier.reduce_containment(dataclasses.replace(context, measured=measured))
    assert reduction.containment["refresh_detection"] == "unavailable"
    assert "expired_copy_unavailable" in _reasons(reduction, "refresh_detection")


@pytest.mark.parametrize("expired_change", ["model_first", "no_denial", "other_host_only",
                                            "incomplete", "watch"])
def test_sl6_refresh_passes_only_with_the_expired_control(codex_supplier, expired_change):
    from phase_loop_runtime.seat_egress_proxy import ProxyStream, ProxyWindow
    context = _context(codex_supplier)
    expired = context.expired_copy
    if expired_change == "model_first":
        expired = dataclasses.replace(expired, stream=_windows_stream(
            leg=(_MODEL, _NAMED_DENIAL)))
    elif expired_change == "no_denial":
        expired = dataclasses.replace(expired, stream=_windows_stream(leg=(_OTHER_DENY,)))
    elif expired_change == "other_host_only":
        expired = dataclasses.replace(expired, stream=_windows_stream(
            leg=(_event("CONNECT", "ab.chatgpt.com", None, "deny"),)))
    elif expired_change == "incomplete":
        expired = dataclasses.replace(expired, stream=ProxyStream(
            final=True, protocol_error=False, windows=(ProxyWindow(
                label="leg", start_acked=True, end_acked=False, events=(_NAMED_DENIAL,)),),
            outside_events=(), allowlist_sha256="6" * 64))
    else:
        expired = dataclasses.replace(expired, watch=_watch(overflow=True))
    reduction = codex_supplier.reduce_containment(dataclasses.replace(
        context, expired_copy=expired))
    assert reduction.containment["refresh_detection"] == "unavailable"
    assert reduction.owner_summary.expired_copy_control == "unavailable"


def test_sl6_scope_is_the_measured_copys_and_needs_the_whole_bracket(codex_supplier):
    context = _context(codex_supplier)
    excess = dataclasses.replace(context.measured, scan={
        "scope": "codex_seat_token_scope_excess", "refresh": "pass"})
    reduction = codex_supplier.reduce_containment(dataclasses.replace(context, measured=excess))
    assert reduction.containment["credential_scope"] == "codex_seat_token_scope_excess"
    for bracket, reason in (
            (None, "bracket_void"),
            (dataclasses.replace(_full_bracket(codex_supplier), post_refused=False),
             "bracket_void"),
            (dataclasses.replace(_full_bracket(codex_supplier), rows=tuple(
                dataclasses.replace(row, outcome="unavailable", signature=None)
                if row.row == "codex_refused_paths" else row
                for row in _full_bracket(codex_supplier).rows)), "bracket_row_unavailable")):
        measured = dataclasses.replace(context.measured, bracket=bracket)
        reduction = codex_supplier.reduce_containment(dataclasses.replace(
            context, measured=measured))
        assert reduction.containment["credential_scope"] == "unavailable"
        assert reason in _reasons(reduction, "credential_scope")


def test_sl6_geminis_bracket_never_passes_a_codex_context(codex_supplier):
    from phase_loop_runtime import seat_jail_qualification as jailq
    context = _context(codex_supplier)
    gemini = jailq.BracketResult(start=_fence(), end=_fence(), post_refused=True, rows=tuple(
        jailq.BracketRow(row=name, outcome="refused",
                         signature=sorted(jailq.BRACKET_SIGNATURES[name])[0])
        for name in jailq.BRACKET_ROW_NAMES))
    # Gemini's rows, in Gemini's type or in Codex's, are not Codex's bracket.
    renamed = codex_supplier.BracketResult(
        start=_fence(), end=_fence(), post_refused=True, rows=tuple(
            codex_supplier.BracketRow(row=row.row, outcome=row.outcome,
                                      signature=row.signature) for row in gemini.rows))
    for bracket in (gemini, renamed):
        reduction = codex_supplier.reduce_containment(dataclasses.replace(
            context, measured=dataclasses.replace(context.measured, bracket=bracket)))
        assert reduction.containment["credential_scope"] == "unavailable"
        assert "bracket_void" in _reasons(reduction, "credential_scope")
        assert reduction.containment["refresh_detection"] == "unavailable"


@pytest.mark.parametrize("where,expected", [
    ("measured_opened", "loaded"), ("board_opened", "loaded"), ("canary", "loaded"),
    ("runtime_changed", "unavailable"), ("home_changed", "unavailable")])
def test_sl6_surface_outcomes(codex_supplier, where, expected):
    context = _context(codex_supplier)
    layout = context.layout
    hooks_tree = _rows_by_role(layout, "tree")["hooks"]
    hooks_runtime = _rows_by_role(layout, "provider_config")["hooks"]
    measured, board = context.measured, context.board
    if where == "measured_opened":
        measured = dataclasses.replace(measured, watch=_watch(opened=(hooks_tree,)))
    elif where == "board_opened":
        board = dataclasses.replace(board, watch=_watch(opened=(hooks_tree,)))
    elif where == "canary":
        (canary, *_rest) = layout.canary_hosts["mcp_servers"]
        measured = dataclasses.replace(measured, stream=_windows_stream(
            leg=(_MODEL, _event("CONNECT", canary, None, "deny")), bracket=_BRACKET_EVENTS))
    elif where == "runtime_changed":
        measured = dataclasses.replace(measured, watch=_watch(changed=(hooks_runtime,)))
    else:
        measured = dataclasses.replace(measured, watch=_watch(changed=("home:.codex/config.toml",)))
    reduction = codex_supplier.reduce_containment(dataclasses.replace(
        context, measured=measured, board=board))
    surface = "mcp_servers" if where == "canary" else "hooks"
    if where in ("runtime_changed", "home_changed"):
        # A change at a defined runtime row is a positive for its own surface; a change at
        # the home row leaves every other surface unavailable.
        if where == "home_changed":
            assert reduction.containment["hooks"] == "unavailable"
        else:
            assert reduction.containment["hooks"] == "loaded"
            assert reduction.containment["mcp_servers"] == "unavailable"
    else:
        assert reduction.containment[surface] == expected
        assert reduction.checks[surface] is False


def test_sl6_an_undefined_surface_stays_unavailable(codex_supplier):
    context = _context(codex_supplier)
    layout = context.layout
    hooks = {row.row_id for row in layout.rows if row.role == "hooks"}
    controls = tuple(dataclasses.replace(item, watch=_watch(opened=tuple(
        row for row in item.watch.opened_rows if row not in hooks))) for item in context.controls)
    reduction = codex_supplier.reduce_containment(dataclasses.replace(
        context, controls=controls))
    assert reduction.containment["hooks"] == "unavailable"
    assert "undefined_surface" in _reasons(reduction, "hooks")
    assert reduction.owner_summary.undefined_surfaces == ("hooks",)
    assert reduction.containment["mcp_servers"] == "not_loaded"


@pytest.mark.parametrize("change,reason", [
    ("tool_step", "tool_step"), ("token", "token_endpoint_event"),
    ("credential", "credential_event"), ("watch", "incomplete_watch"),
    ("status", "launch_error"), ("scan", "incomplete_watch")])
def test_sl6_definition_probe_voids_a_control(codex_supplier, change, reason):
    context = _context(codex_supplier)
    layout = context.layout
    kind = "credentialed_runtime_control"
    control = next(item for item in context.controls if item.kind == kind)
    changed = {
        "tool_step": dict(tool_steps=1),
        "token": dict(stream=_windows_stream(leg=(_DENIED_TOKEN_CONNECT, _MODEL))),
        "credential": dict(watch=_watch(opened=control.watch.opened_rows, credential_events=1)),
        "watch": dict(watch=_watch(opened=control.watch.opened_rows, sentinel_observed=False)),
        "status": dict(status="NONE"),
        "scan": dict(scan=None)}[change]
    voided = dataclasses.replace(control, **changed)
    definition = codex_supplier.definition_probe(layout, (voided,))
    assert (kind, reason) in {(item.kind, item.reason) for item in definition.voided}
    assert definition.defined_rows == ()
    assert dict(definition.counted_lookups) == {}  # no trace on a non-Gemini leg


def test_sl6_definition_probe_asks_for_credentialed_controls(codex_supplier):
    context = _context(codex_supplier)
    none_controls = context.controls[:2]
    definition = codex_supplier.definition_probe(context.layout, tuple(
        dataclasses.replace(item, status="NONE") for item in none_controls))
    assert definition.credentialed_control_required is True
    assert definition.home_row_baseline == "absent"
    full = codex_supplier.definition_probe(context.layout, context.controls)
    assert full.credentialed_control_required is False
    assert set(full.defined_surfaces) == set(_SURFACES)
    assert full.home_row_baseline == "no_write_final"


def test_sl6_the_watch_arms_on_codexs_paths_and_sees_opens_changes_and_the_credential(
        codex_supplier, tmp_path):
    from phase_loop_runtime import seat_codex_credential as cred, seat_jail_qualification as jailq
    layout = codex_supplier.plant_layout(plugin_form="nested")
    qi = codex_supplier.build_qualification_input(layout, tmp_path / "inputs")
    seat = _seat(tmp_path, cred.build_seat_copy(_login()))
    import shutil
    paths = codex_supplier.host_path_map(seat, credential=True)
    shutil.copytree(qi.repo, paths.tree, ignore=shutil.ignore_patterns(".git"))
    (paths.seat_home / "workspace").mkdir()
    codex_supplier.seed_runtime_plants(layout, paths)
    watch = codex_supplier.arm_watch(layout, paths, kind="measured")

    def run(argv, *, env, use_proxy, timeout_s):  # the sentinels, opened on the host
        path = paths.tree / argv[-1].removeprefix("/seat/tree/")
        path.read_bytes()
        return jailq.JailedStep(exit_code=0, timed_out=False, stdout=b"")
    assert watch.prove_sentinel(run) is True
    (paths.tree / jailq.WINDOW_READ_PATH).read_text()
    hooks_tree = _rows_by_role(layout, "tree")["hooks"]
    (paths.tree / hooks_tree.partition(":")[2]).read_text()
    hooks_runtime_row = _rows_by_role(layout, "provider_config")["hooks"]
    target = paths.provider_config / hooks_runtime_row.partition(":")[2]
    target.write_text("changed\n")
    (paths.provider_config / "auth.json").write_bytes(b"{}")
    observation = watch.drain_and_close(quiescent=True)
    assert observation.sentinel_observed and observation.read_marker_opened
    assert hooks_tree in observation.opened_rows
    assert hooks_runtime_row in observation.changed_rows
    assert observation.credential_path_events >= 1
    assert not observation.overflow
    assert set(observation.pre_row_sha256) == {row.row_id for row in layout.rows
                                               if row.location != "tree"}
    assert not any("gemini" in row or "agy" in row for row in observation.opened_rows)


def test_sl6_the_watch_refuses_a_foreign_layout_or_path_map(codex_supplier, tmp_path):
    from phase_loop_runtime import seat_codex_credential as cred, seat_jail_qualification as jailq
    seat = _seat(tmp_path, cred.build_seat_copy(_login()))
    paths = codex_supplier.host_path_map(seat, credential=True)
    with pytest.raises(jailq.WatchUnavailable):
        codex_supplier.arm_watch(jailq.plant_layout(plugin_form="nested"), paths,
                                 kind="measured")
    with pytest.raises(jailq.WatchUnavailable):
        codex_supplier.arm_watch(codex_supplier.plant_layout(plugin_form="nested"),
                                 SimpleNamespace(tree=tmp_path), kind="measured")
    with pytest.raises(ValueError):
        codex_supplier.arm_watch(None, None, kind="plugin_validation")
    with pytest.raises(jailq.WatchUnavailable):  # its locations are missing
        codex_supplier.arm_watch(codex_supplier.plant_layout(plugin_form="nested"), paths,
                                 kind="measured")


def test_sl6_f16_help_binds_what_it_printed(codex_supplier, tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as panel
    _control_world(monkeypatch, tmp_path, codex_supplier, stdout="usage: plugin\n")
    result = panel.window_control_launch(_codex_spec("help", tmp_path))
    assert result.status == "SUCCESS"
    assert result.help_sha256 == hashlib.sha256(b"usage: plugin\n").hexdigest()
    assert result.help_lists_plugin is True and result.model_turn is None


# --------------------------------------------------------------------------------------
# Review B2: Codex's bracket, ported from codex-unlisted-endpoint.
# --------------------------------------------------------------------------------------

_EVIDENCE = (Path(__file__).resolve().parents[2] / "plans" / "evidence" / "seat-codex"
             / "allowlist-probes.json")


class _BracketRun:
    """A recording jailed run: each step gets the next scripted result."""

    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def __call__(self, argv, *, env, use_proxy, timeout_s):
        self.calls.append((tuple(argv), dict(env), use_proxy))
        return self.outcomes.pop(0)


def _step(exit_code, stdout=b""):
    from phase_loop_runtime import seat_jail_qualification as jailq
    return jailq.JailedStep(exit_code=exit_code, timed_out=False, stdout=stdout)


_CONNECT_403 = _step(56, b"\nPHASE_LOOP_CURL 000 403\n")
_FILTER_403 = _step(0, b"HTTP/1.1 403 Forbidden\r\nX-Proxy-Error: blocked-by-sandbox-runtime"
                       b"\r\n\r\n\nPHASE_LOOP_CURL 403 200\n")
_REPLY_200 = _step(0, b"HTTP/1.1 200 OK\r\n\r\n\nPHASE_LOOP_CURL 200 200\n")
_REFUSED_RUN = (
    _CONNECT_403,                              # token POST
    _CONNECT_403, _CONNECT_403,                # refused hosts
    _FILTER_403, _FILTER_403, _FILTER_403,     # refused paths
    _FILTER_403, _FILTER_403, _FILTER_403,     # the three tunnel rows
    _step(0, b"UPSTREAM_BYTES 0 0\n"),         # fail-closed front
    _step(6), _step(7),                        # direct without the proxy
)


def _fenced(monkeypatch, acknowledged=True):
    from phase_loop_runtime import seat_egress_proxy
    fences = []
    monkeypatch.setattr(seat_egress_proxy, "fence", lambda proxy, marker, window: (
        fences.append((marker, window)) or _fence(acknowledged)))
    return fences


def _urls(calls):
    return [next(part for part in argv if part.startswith("https://")) for argv, _env, _p
            in calls if argv[0] == "/usr/bin/curl"]


def test_sl6_codex_brings_its_own_bracket(codex_supplier, monkeypatch):
    """Review B2: Codex's bracket is its own (not FIRSTSEAT's Gemini steps) and probes the
    Codex hosts and paths of codex-unlisted-endpoint."""
    from phase_loop_runtime import seat_jail_qualification as jailq
    assert codex_supplier.bracket_steps() is codex_supplier.run_bracket
    assert codex_supplier.bracket_steps() is not jailq.run_bracket
    fences = _fenced(monkeypatch)
    run = _BracketRun(_REFUSED_RUN)
    result = codex_supplier.bracket_steps()("proxy", run)
    assert fences == [("start", "bracket"), ("end", "bracket")]
    assert result.post_refused is True
    assert [row.row for row in result.rows] == list(codex_supplier.BRACKET_ROW_NAMES) == [
        "codex_refused_hosts", "codex_refused_paths", "codex_tunnel_inner_host",
        "codex_tunnel_inner_sni_and_host", "codex_tunnel_inner_sni_only",
        "codex_fail_closed_front", "codex_direct_without_proxy"]
    assert [(row.outcome, row.signature) for row in result.rows] == [
        ("refused", "proxy_connect_refused"), ("refused", "request_filter_refused"),
        ("refused", "request_filter_refused"), ("refused", "request_filter_refused"),
        ("refused", "request_filter_refused"), ("refused", "no_upstream_bytes"),
        ("refused", "resolve_refused")]
    assert _urls(run.calls) == [
        "https://auth.openai.com/oauth/token",
        "https://ab.chatgpt.com/otlp/v1/metrics", "https://seat-egress-unlisted.invalid/",
        "https://chatgpt.com/backend-api/codex/models",
        "https://chatgpt.com/backend-api/wham/settings/user",
        "https://chatgpt.com/backend-api/codex/analytics-events/events",
        "https://chatgpt.com/backend-api/codex/responses",
        "https://ab.chatgpt.com/backend-api/codex/responses",
        "https://ab.chatgpt.com/backend-api/codex/responses",
        "https://1.1.1.1/", "https://chatgpt.com/"]
    argvs = [argv for argv, _env, _proxy in run.calls]
    joined = "\n".join(" ".join(argv) for argv in argvs)
    assert "googleapis" not in joined and ".gemini" not in joined
    assert argvs[0][-3:] == ("--request", "POST", "https://auth.openai.com/oauth/token")
    assert ("--header", "Host: ab.chatgpt.com") == argvs[6][-3:-1]
    assert "ab.chatgpt.com:443:chatgpt.com:443" in argvs[7] and "Host: chatgpt.com" in argvs[8]
    front = argvs[9]
    assert front[:3] == ("/usr/bin/python3", "-I", "-c")
    assert 'allowed = b"chatgpt.com"' in front[3] and 'sni = b"ab.chatgpt.com"' in front[3]
    # Every proxied step runs with the proxy; the direct steps without it; one clean env.
    assert [use_proxy for _argv, _env, use_proxy in run.calls] == [True] * 10 + [False] * 2
    assert all(env == dict(jailq.BRACKET_STEP_ENV) for _argv, env, _p in run.calls)
    assert all(argv[1] == "-q" for argv in argvs if argv[0] == "/usr/bin/curl")


def test_sl6_codex_bracket_rows_are_codex_unlisted_endpoints(codex_supplier):
    """Every refused decision of codex-unlisted-endpoint is probed (the token host by the
    token POST), with its method, host and path, and nothing the evidence allows is."""
    if not _EVIDENCE.is_file():
        pytest.skip("repo-only evidence is absent on an installed wheel")
    evidence = json.loads(_EVIDENCE.read_text())
    assert evidence["evidence_id"] == "codex-unlisted-endpoint"
    targets = {(method, url) for method, url in (*codex_supplier.REFUSED_HOST_TARGETS,
                                                 *codex_supplier.REFUSED_PATH_TARGETS)}
    for decision in evidence["decisions"]:
        if decision["decision"] == "allow":
            assert not any(url == f"https://{decision['host']}{decision['path']}"
                           for _m, url in targets)
        elif decision["host"] == TOKEN_HOST:
            assert (codex_supplier.TOKEN_HOST, codex_supplier.TOKEN_PATH) == (
                TOKEN_HOST, TOKEN_PATH)
        else:
            assert (decision["method"], f"https://{decision['host']}{decision['path']}") \
                in targets, decision
    from phase_loop_runtime import seat_egress_proxy
    refused = set(seat_egress_proxy.allowlist("codex")["measured_and_refused"])
    assert {url.split("/")[2] for _m, url in codex_supplier.REFUSED_HOST_TARGETS} == (
        refused - {TOKEN_HOST}) | {"seat-egress-unlisted.invalid"}


@pytest.mark.parametrize("index,row", [
    (1, "codex_refused_hosts"), (3, "codex_refused_paths"), (6, "codex_tunnel_inner_host"),
    (9, "codex_fail_closed_front"), (10, "codex_direct_without_proxy")])
def test_sl6_codex_bracket_row_without_its_refusal_is_unavailable(codex_supplier, monkeypatch,
                                                                  index, row):
    _fenced(monkeypatch)
    outcomes = list(_REFUSED_RUN)
    outcomes[index] = _REPLY_200 if index < 9 else _step(0, b"UPSTREAM_BYTES 12 0\n") \
        if index == 9 else _step(0)
    result = codex_supplier.run_bracket("proxy", _BracketRun(outcomes))
    rows = {item.row: item for item in result.rows}
    assert (rows[row].outcome, rows[row].signature) == ("unavailable", None)
    assert all(item.outcome == "refused" for name, item in rows.items() if name != row)


def test_sl6_codex_bracket_token_post_counts_only_on_the_connect_refusal(codex_supplier,
                                                                        monkeypatch):
    _fenced(monkeypatch)
    outcomes = list(_REFUSED_RUN)
    outcomes[0] = _FILTER_403  # a tunnelled token request is not the CONNECT refusal
    assert codex_supplier.run_bracket("proxy", _BracketRun(outcomes)).post_refused is False


def test_sl6_codex_bracket_runs_nothing_without_its_start_fence(codex_supplier, monkeypatch):
    fences = _fenced(monkeypatch, acknowledged=False)
    run = _BracketRun(())
    result = codex_supplier.run_bracket("proxy", run)
    assert run.calls == [] and fences == [("start", "bracket")]
    assert {row.outcome for row in result.rows} == {"unavailable"}
    assert result.post_refused is False
