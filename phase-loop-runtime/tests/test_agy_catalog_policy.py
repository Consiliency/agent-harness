"""The catalog policy primitives the job and the verifier share (ROLLJOB-detail §1, §6.1).

Nothing here reaches the network. Signing uses an ed25519 key generated in a temporary
directory with ``ssh-keygen`` (skipped with a reason when it is absent; hosted CI has it).
"""
from __future__ import annotations

import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest

from phase_loop_runtime import agy_catalog_policy as policy

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "agy_catalog_policy"
DAY = 86_400
NOW = 1_800_000_000.0  # 2027-01-15

needs_ssh_keygen = pytest.mark.skipif(shutil.which("ssh-keygen") is None,
                                      reason="ssh-keygen is not installed (hosted CI has it)")


def _iso(timestamp):
    return policy.rfc3339(timestamp)


def _member(version, *, age_days=100, pinned=False, image=None):
    digest = image or sha256(version.encode()).hexdigest()
    return {"release_version": version, "image_sha256": digest, "help_sha256": "e" * 64, "asset_sha256": "b" * 64,
            "qci": "9" * 64, "published_at": _iso(NOW - age_days * DAY), "pinned": pinned,
            "record": f"agy-{version}-linux-x64-qualification.json"}


def _shipped_record():
    return json.loads((REPO / "plans/evidence/agy-1.5.3-linux-x64-qualification.json").read_text())


def _record(version="9.9.9", **changes):
    record = _shipped_record()
    url = f"https://github.com/{policy.UPSTREAM_REPO}/releases/tag/{version}"
    record.update(release_version=version, upstream_release_url=url)
    record["upstream"] = dict(record["upstream"], release_url=url)
    record.update(changes)
    return record


# ------------------------------------------------------------------------ canonical bytes

def test_canonical_bytes_ignore_key_order_and_signatures():
    record = _record()
    shuffled = dict(reversed(list(record.items())))
    signed = dict(record, signatures=[{"principal": "agy-watch", "namespace": "x", "signature": "y"}])
    assert policy.canonical_record(record) == policy.canonical_record(shuffled) == policy.canonical_record(signed)
    assert b"signatures" not in policy.canonical_record(signed)
    assert policy.canonical_record(record) == json.dumps(
        {k: v for k, v in record.items() if k != "signatures"}, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode()


# ------------------------------------------------------------------------------- signing

@pytest.fixture
def signer(tmp_path):
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is not installed (hosted CI has it)")
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)

    def make(name):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(keys / name)],
                       check=True, capture_output=True)
        return keys / name

    key, other = make("job"), make("other")
    allowed = tmp_path / "agy-allowed-signers"
    public = (keys / "job.pub").read_text().split()
    allowed.write_text(f"# test signer list\nagy-watch namespaces=\"agy-qualification\" {public[0]} {public[1]}\n")
    return key, other, allowed


def test_sign_then_verify_with_a_fixture_key(signer):
    key, _other, allowed = signer
    signed = policy.sign_record(_record(), key)
    (entry,) = signed["signatures"]
    assert entry["principal"] == "agy-watch" and entry["namespace"] == "agy-qualification"
    assert entry["signature"].startswith("-----BEGIN SSH SIGNATURE-----")
    assert policy.verified_signers(signed, allowed) == ["agy-watch"]
    # re-serialized in another key order, the signature still verifies
    assert policy.verified_signers(json.loads(json.dumps(signed, sort_keys=True)), allowed) == ["agy-watch"]


@pytest.mark.parametrize("field,value", [("image_sha256", "0" * 64), ("upstream_asset_sha256", "0" * 64),
                                         ("qci", "0" * 64), ("release_version", "9.9.10")])
def test_a_signature_over_an_altered_record_does_not_verify(signer, field, value):
    key, _other, allowed = signer
    signed = policy.sign_record(_record(), key)
    assert policy.verified_signers(dict(signed, **{field: value}), allowed) == []


def test_a_key_outside_the_allowed_signers_does_not_verify(signer):
    _key, other, allowed = signer
    assert policy.verified_signers(policy.sign_record(_record(), other), allowed) == []


def test_an_empty_signer_list_verifies_nothing(signer, tmp_path):
    key, _other, _allowed = signer
    empty = tmp_path / "empty-signers"
    empty.write_text("# no key is enrolled\n")
    assert policy.verified_signers(policy.sign_record(_record(), key), empty) == []


@pytest.mark.parametrize("entry", [None, "text", {"principal": "agy-watch"},
                                   {"principal": "agy watch", "namespace": "agy-qualification",
                                    "signature": "-----BEGIN SSH SIGNATURE-----"},
                                   {"principal": "agy-watch", "namespace": "other",
                                    "signature": "-----BEGIN SSH SIGNATURE-----"}])
def test_a_malformed_signature_entry_is_ignored_never_an_error(signer, entry):
    key, _other, allowed = signer
    signed = policy.sign_record(_record(), key)
    signed["signatures"].insert(0, entry)
    assert policy.verified_signers(signed, allowed) == ["agy-watch"]
    assert policy.verified_signers(dict(signed, signatures="nope"), allowed) == []


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_a_key_readable_by_group_or_others_refuses(signer, mode):
    key, _other, _allowed = signer
    key.chmod(mode)
    with pytest.raises(ValueError, match="agy_watch_signing_unavailable") as raised:
        policy.sign_record(_record(), key)
    assert str(key) not in str(raised.value)


def test_a_missing_or_symlinked_key_refuses(signer, tmp_path):
    key, _other, _allowed = signer
    for path in (None, "", tmp_path / "absent"):
        with pytest.raises(ValueError, match="agy_watch_signing_unavailable"):
            policy.sign_record(_record(), path)
    link = tmp_path / "link"
    link.symlink_to(key)
    with pytest.raises(ValueError, match="agy_watch_signing_unavailable"):
        policy.sign_record(_record(), link)


def test_a_failing_ssh_keygen_refuses(signer):
    key, _other, _allowed = signer

    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, b"", b"error")

    with pytest.raises(ValueError, match="agy_watch_signing_unavailable"):
        policy.sign_record(_record(), key, runner=runner)


# --------------------------------------------------------------------------------- aging

def test_the_newest_three_are_kept_regardless_of_age():
    members = [_member(f"1.{i}.0", age_days=400) for i in range(5)]
    kept, pruned = policy.aging(members, now=NOW)
    assert [m["release_version"] for m in kept] == ["1.2.0", "1.3.0", "1.4.0"]
    assert [m["release_version"] for m in pruned] == ["1.0.0", "1.1.0"]


def test_a_fourth_member_is_kept_under_fourteen_days_and_pruned_at_fourteen():
    newest = [_member(v, age_days=1) for v in ("2.0.0", "2.1.0", "2.2.0")]
    young = _member("1.0.0", age_days=13.99)
    due = dict(young, published_at=_iso(NOW - 14 * DAY))
    assert policy.aging(newest + [young], now=NOW)[1] == []
    assert policy.aging(newest + [due], now=NOW)[1] == [due]


def test_numeric_not_string_version_order():
    members = [_member(v) for v in ("1.9.0", "1.10.0", "1.2.0", "1.11.0")]
    _kept, pruned = policy.aging(members, now=NOW)
    assert [m["release_version"] for m in pruned] == ["1.2.0"]


def test_a_pinned_member_is_never_pruned_and_an_unparseable_date_is_kept():
    newest = [_member(v, age_days=500) for v in ("3.0.0", "3.1.0", "3.2.0")]
    pinned = _member("1.0.0", age_days=900, pinned=True)
    undated = dict(_member("1.1.0", age_days=900), published_at="not a date")
    old = _member("1.2.0", age_days=900)
    kept, pruned = policy.aging(newest + [pinned, undated, old], now=NOW)
    assert pinned in kept and undated in kept and pruned == [old]


# ------------------------------------------------------------------------ catalog_change

def _base():
    return [_member("1.0.0", age_days=30), _member("1.1.0", age_days=20), _member("1.2.0", age_days=10),
            _member("1.3.0", age_days=5)]


def test_auto_for_one_new_newest_member():
    base = _base()
    change = policy.catalog_change(base, base + [_member("1.4.0", age_days=0)], now=NOW)
    assert change.auto and change.reasons == () and [m["release_version"] for m in change.added] == ["1.4.0"]


@pytest.mark.parametrize("head,reason", [
    (lambda b: b, "added_count_not_one"),
    (lambda b: b + [_member("1.4.0"), _member("1.5.0")], "added_count_not_one"),
    (lambda b: b + [_member("1.4.0", pinned=True)], "added_member_pinned"),
    (lambda b: b[1:] + [_member("0.9.0")], "added_member_not_newest"),
])
def test_condition_one_exactly_one_new_unpinned_newest_member(head, reason):
    change = policy.catalog_change(_base(), head(_base()), now=NOW)
    assert not change.auto and reason in change.reasons


def test_condition_two_only_aged_out_members_may_be_removed():
    base = _base()
    # 1.0.0 is 30 days old and, with 1.4.0 added, outside the newest three: aged out.
    passing = policy.catalog_change(base, base[1:] + [_member("1.4.0", age_days=0)], now=NOW)
    assert passing.auto
    # 1.3.0 is among the newest three: removing it is not aging.
    failing = policy.catalog_change(base, base[:3] + [_member("1.4.0", age_days=0)], now=NOW)
    assert not failing.auto and failing.reasons == ("removed_member_not_aged_out",)


@pytest.mark.parametrize("field,value", [("pinned", True), ("help_sha256", "f" * 64), ("published_at", _iso(NOW))])
def test_condition_three_no_surviving_member_changes_any_field(field, value):
    base = _base()
    head = copy.deepcopy(base) + [_member("1.4.0", age_days=0)]
    head[2][field] = value
    change = policy.catalog_change(base, head, now=NOW)
    assert not change.auto and change.reasons == ("surviving_member_modified",)
    assert policy.catalog_change(base, copy.deepcopy(base) + [_member("1.4.0", age_days=0)], now=NOW).auto


# -------------------------------------------------------------------------- build_catalog

def test_build_catalog_adds_one_unpinned_member_and_prunes_by_aging():
    base = [_member("1.0.0", age_days=60, pinned=True), _member("1.1.0", age_days=50),
            _member("1.2.0", age_days=40), _member("1.3.0", age_days=30), _member("1.4.0", age_days=2)]
    built = policy.build_catalog(base, _record("1.5.0"), published_at=_iso(NOW), now=NOW)
    assert [m["release_version"] for m in built] == ["1.0.0", "1.3.0", "1.4.0", "1.5.0"]
    new = built[-1]
    assert new["pinned"] is False and new["published_at"] == _iso(NOW)
    assert new == {**policy.candidate_member(_record("1.5.0")), "published_at": _iso(NOW), "pinned": False}
    assert policy.parse_catalog(policy.render_catalog(built)) == built
    assert policy.catalog_change(base, built, now=NOW).auto


@pytest.mark.parametrize("version", ["1.4.0", "1.3.9", "0.1.0"])
def test_build_catalog_refuses_an_existing_or_older_version(version):
    base = [_member("1.3.0"), _member("1.4.0")]
    with pytest.raises(ValueError, match="already a member|not the newest"):
        policy.build_catalog(base, _record(version), published_at=_iso(NOW), now=NOW)


def test_candidate_member_accepts_a_valid_record_for_an_existing_version():
    shipped = json.loads((REPO / policy.CATALOG_PATH).read_text())["routes"]["linux-x64"][-1]
    record = json.loads((REPO / "plans/evidence" / shipped["record"]).read_text())
    member = policy.candidate_member(record)
    assert member == {key: shipped[key] for key in member}


@pytest.mark.parametrize("change", [
    lambda r: r.pop("qci"), lambda r: r.update(extra=1), lambda r: r.update(schema="v1"),
    lambda r: r.update(provider="claude"), lambda r: r.update(upstream_asset_name="other.tar.gz"),
    lambda r: r["upstream"].update(attestation="trusted"), lambda r: r["upstream"].update(asset_sha256="0" * 64),
    lambda r: r.update(signatures={}), lambda r: r.update(qci="Z" * 64),
    lambda r: r["records"].pop(), lambda r: r["records"][0].update(image_sha256="0" * 64),
    lambda r: r.update(upstream_release_url="https://example.invalid/9.9.9"),
])
def test_candidate_member_refuses_a_record_that_is_not_a_closed_v2_record(change):
    record = _record()
    change(record)
    with pytest.raises(ValueError):
        policy.candidate_member(record)


# ----------------------------------------------------------------------- the intake body

def _signed_shape(record):
    return dict(record, signatures=[{"principal": "agy-watch", "namespace": "agy-qualification",
                                     "signature": "-----BEGIN SSH SIGNATURE-----\nAAAA\n-----END SSH SIGNATURE-----\n"}])


def test_intake_render_then_parse_round_trips():
    record = _signed_shape(_record())
    body = policy.render_intake(record)
    header = body.splitlines()[0].split()
    assert header[:3] == ["agy-intake.v1", "9.9.9", record["qci"]]
    assert policy.parse_intake(body) == record
    assert policy.parse_intake(body.rstrip("\n")) == record


def _body():
    return policy.render_intake(_signed_shape(_record()))


@pytest.mark.parametrize("mutate", [
    lambda b: b + "\n```json\n{}\n```\n",                       # a second fenced block
    lambda b: b + "trailing text\n",                            # trailing text
    lambda b: "preamble\n" + b,
    lambda b: b.replace(b.splitlines()[0].split()[3], "0" * 64),  # a wrong digest
    lambda b: b.replace("agy-intake.v1 9.9.9", "agy-intake.v1 9.9.8"),  # a header that disagrees
    lambda b: b.replace(b.splitlines()[0].split()[2], "1" * 64, 1),
    lambda b: b.replace("```json", "```"),
    lambda b: b.replace("\n\n", "\r\n\r\n"),
])
def test_a_malformed_intake_body_raises(mutate):
    with pytest.raises(ValueError):
        policy.parse_intake(mutate(_body()))


def test_a_record_not_in_sorted_form_raises_even_with_a_matching_digest():
    record = _signed_shape(_record())
    text = json.dumps(record, separators=(",", ":"))  # not sorted
    body = f"agy-intake.v1 9.9.9 {record['qci']} {sha256(text.encode()).hexdigest()}\n\n```json\n{text}\n```\n"
    with pytest.raises(ValueError, match="sorted"):
        policy.parse_intake(body)


def test_an_oversize_intake_body_raises():
    record = _signed_shape(_record())
    record["qualified_under"] = "x" * policy.MAX_RECORD_BYTES
    with pytest.raises(ValueError, match="too large"):
        policy.render_intake(record)
    text = json.dumps(record, sort_keys=True, separators=(",", ":"))
    body = f"agy-intake.v1 9.9.9 {record['qci']} {sha256(text.encode()).hexdigest()}\n\n```json\n{text}\n```\n"
    with pytest.raises(ValueError, match="too large"):
        policy.parse_intake(body)


# ------------------------------------------------------------------------- parse_catalog

def _outcome(parse, text):
    try:
        return ("ok", parse(text))
    except Exception as exc:  # noqa: BLE001 - the two parsers must fail alike
        return ("error", type(exc).__name__)


@pytest.mark.parametrize("case", json.loads((FIXTURES / "catalogs.json").read_text()), ids=lambda c: c["name"])
def test_parse_catalog_agrees_with_the_runtime_parser(case):
    from phase_loop_runtime import gemini_heartbeat
    ours, theirs = _outcome(policy.parse_catalog, case["text"]), _outcome(gemini_heartbeat.parse_catalog, case["text"])
    assert ours == theirs
    assert (ours[0] == "ok") is case["accept"]


def test_the_shipped_catalog_parses_alike_and_renders_to_its_own_bytes():
    from phase_loop_runtime import gemini_heartbeat
    text = (REPO / policy.CATALOG_PATH).read_text()
    assert policy.parse_catalog(text) == gemini_heartbeat.parse_catalog(text)
    assert policy.render_catalog(policy.parse_catalog(text)) == text


def test_the_copied_shapes_equal_the_runtime_and_verifier():
    import importlib.util
    from phase_loop_runtime import agy_attestation, gemini_heartbeat
    spec = importlib.util.spec_from_file_location("verify_policy_shapes",
                                                  REPO / "phase-loop-runtime/scripts/verify_qualified_agy_image.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    assert policy.PROFILE_ID == gemini_heartbeat.PROFILE_ID
    assert policy.CATALOG_SCHEMA == gemini_heartbeat.CATALOG_SCHEMA
    assert policy.ATTESTATION_STATUSES == agy_attestation.ATTESTATION_STATUSES
    assert policy.SECOND_CHANNEL_STATUSES == agy_attestation.SECOND_CHANNEL_STATUSES
    assert (policy.RECORD_KEYS, policy.UPSTREAM_KEYS, policy.ROUTE, policy.ASSET, policy.RECORD_SCHEMA) == (
        verifier.RECORD_KEYS, verifier.UPSTREAM_KEYS, verifier.ROUTE, verifier.ASSET, verifier.RECORD_SCHEMA)
    assert policy.UPSTREAM_REPO == verifier.UPSTREAM


def test_the_module_imports_only_the_standard_library():
    import ast
    import sys
    tree = ast.parse(Path(policy.__file__).read_text())
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module}
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level]
    assert imported - {"__future__"} <= set(sys.stdlib_module_names)


# -------------------------------------------------------------------------------- headroom

@pytest.mark.parametrize("percent,expected", [(79, "ok"), (80, "warn"), (89, "warn"), (90, "fail"), (100, "fail")])
def test_headroom_thresholds(percent, expected):
    for bound in (256_000_000, 512_000_000):
        assert policy.headroom(bound * percent // 100, bound) == expected


def test_headroom_one_byte_below_each_threshold():
    bound = 256_000_000
    assert policy.headroom(bound * 80 // 100 - 1, bound) == "ok"
    assert policy.headroom(bound * 90 // 100 - 1, bound) == "warn"


# ------------------------------------------------------------------------- the attestation

def _template():
    return {"schema": "agy_rollout_attestation.v1", "status": "unattested",
            "intake_app": {"app_id": 0, "bot_user_id": 0}, "promotion_app": {"app_id": 0, "bot_user_id": 0},
            "main_ruleset": {"id": 0, "target": "refs/heads/main", "enforcement": "active", "bypass_actors": [],
                             "strict_required_status_checks": True, "required_checks": []},
            "catalog_ruleset": {"id": 0, "target": "refs/heads/agy-catalog/**", "enforcement": "active",
                                "rules": ["creation", "update", "deletion"],
                                "bypass_actors": [{"actor_type": "Integration", "actor_id": 0,
                                                   "bypass_mode": "always"}]},
            "promotion_environment": {"name": "agy-promotion", "branches": ["main"], "required_reviewers": 0,
                                      "admin_bypass": False},
            "attested_by": "", "attested_at": ""}


def test_the_shipped_attestation_file_is_unattested():
    path = REPO / policy.ATTESTATION_PATH
    if not (REPO / ".git").exists() and not path.is_file():
        pytest.skip("repository layout absent")  # pragma: no cover - sdist layout only
    attestation = policy.load_attestation(path.read_text())
    assert not attestation.attested and attestation.status == "unattested"
    assert attestation.intake_app == attestation.promotion_app == policy.AppIdentity(0, 0)


def test_the_template_loads_and_an_attested_file_must_name_real_ids():
    assert not policy.load_attestation(json.dumps(_template())).attested
    attested = _template()
    attested["status"] = "attested"
    with pytest.raises(ValueError, match="attested file"):
        policy.load_attestation(json.dumps(attested))
    attested.update(intake_app={"app_id": 11, "bot_user_id": 111}, promotion_app={"app_id": 22, "bot_user_id": 222})
    attested["main_ruleset"]["id"], attested["catalog_ruleset"]["id"] = 5, 6
    loaded = policy.load_attestation(json.dumps(attested))
    assert loaded.attested and loaded.promotion_app == policy.AppIdentity(22, 222)
    other = dict(attested, status="pending")
    assert not policy.load_attestation(json.dumps(other)).attested


@pytest.mark.parametrize("mutate", [
    lambda d: d["main_ruleset"].pop("bypass_actors"),
    lambda d: d["catalog_ruleset"].pop("bypass_actors"),
    lambda d: d.update(extra=True),
    lambda d: d["intake_app"].update(extra=1),
    lambda d: d["intake_app"].update(app_id="11"),
    lambda d: d["promotion_app"].update(bot_user_id=True),
    lambda d: d["main_ruleset"].update(id=-1),
    lambda d: d["main_ruleset"].update(strict_required_status_checks="true"),
    lambda d: d["catalog_ruleset"]["bypass_actors"][0].update(actor_id=None),
    lambda d: d.pop("attested_at"),
    lambda d: d.update(schema="agy_rollout_attestation.v2"),
    lambda d: d.update(status=None),
])
def test_a_missing_extra_or_mistyped_attestation_field_raises(mutate):
    document = _template()
    mutate(document)
    with pytest.raises(ValueError):
        policy.load_attestation(json.dumps(document))


# -------------------------------------------------------------------------- author check

EXPECTED = policy.AppIdentity(app_id=1001, bot_user_id=5005)
BOT = {"login": "agy-intake[bot]", "id": 5005, "type": "Bot"}
APP = {"id": 1001, "slug": "agy-intake"}


def test_the_author_check_accepts_only_the_attested_bot_and_app():
    assert policy.authentic_author(BOT, APP, EXPECTED)


@pytest.mark.parametrize("user,via_app", [
    (dict(BOT, id=5006), APP),                    # wrong id (a matching login is not enough)
    (dict(BOT, id="5005"), APP),
    (dict(BOT, type="User"), APP),                # wrong type
    (BOT, None),                                  # no App object
    (BOT, dict(APP, id=1002)),                    # wrong App id
    ({k: v for k, v in BOT.items() if k != "id"}, APP),
    ({k: v for k, v in BOT.items() if k != "type"}, APP),
    (BOT, {"slug": "agy-intake"}),
    (None, APP),
])
def test_the_author_check_refuses_everything_else(user, via_app):
    assert policy.authentic_author(user, via_app, EXPECTED) is False


def test_an_unset_expected_identity_authenticates_nobody():
    assert policy.authentic_author(dict(BOT, id=0), dict(APP, id=0), policy.AppIdentity(0, 0)) is False


# ----------------------------------------------------------------------------- tick status

def test_the_tick_status_is_private_and_round_trips(tmp_path):
    environ = {"XDG_STATE_HOME": str(tmp_path / "state")}
    policy.write_tick_status("up_to_date", 0, version="9.9.9", environ=environ, now=NOW)
    path = policy.tick_status_path(environ)
    assert path == tmp_path / "state/phase-loop/agy-watch/last-tick.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert policy.read_tick_status(environ) == {"schema": policy.TICK_STATUS_SCHEMA, "at": _iso(NOW),
                                                "status": "up_to_date", "exit": 0, "version": "9.9.9"}
    assert [p.name for p in path.parent.iterdir()] == ["last-tick.json"]  # no temporary left


def test_the_state_home_defaults_to_the_users_local_state(tmp_path):
    assert policy.tick_status_path({"HOME": str(tmp_path)}) == tmp_path / ".local/state/phase-loop/agy-watch/last-tick.json"


def test_a_missing_symlinked_or_malformed_status_reads_as_none(tmp_path):
    environ = {"XDG_STATE_HOME": str(tmp_path / "state")}
    assert policy.read_tick_status(environ) is None
    policy.write_tick_status("up_to_date", 0, environ=environ, now=NOW)
    path = policy.tick_status_path(environ)
    real = tmp_path / "elsewhere.json"
    real.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(real)
    assert policy.read_tick_status(environ) is None
    path.unlink()
    for text in ("{", "[]", json.dumps({"schema": "x"}), json.dumps(
            {"schema": policy.TICK_STATUS_SCHEMA, "at": "yesterday", "status": "ok", "exit": 0, "version": None}),
            json.dumps({"schema": policy.TICK_STATUS_SCHEMA, "at": _iso(NOW), "status": "ok", "exit": True,
                        "version": None})):
        path.write_text(text)
        os.chmod(path, 0o600)
        assert policy.read_tick_status(environ) is None, text
