"""K-1 row-window grants (contract §8): K1-T1's module grammar and F8's falsifiers.

Each refusal goes through the production ``window_grant``, ``claim_window_attempt`` and
verification, against the real grant journal and witnesses in 0700 fixture directories.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

import pytest

from test_seat_window_vendor_neutral import (
    ROW_NOW, _row_world, _run_row, _write_grants, completed_row_world,
    register_fixture_vendor,
)


@pytest.fixture
def fixture_vendor(monkeypatch):
    return register_fixture_vendor(monkeypatch)


@pytest.fixture
def row_world(tmp_path, monkeypatch, fixture_vendor):
    return completed_row_world(tmp_path, monkeypatch)

PIN = ("a" * 64, "b" * 64, "2026-12-30T00:00:00+00:00")


# --- K1-T1: the grants module's grammar, from its checked bytes. ---

@pytest.mark.parametrize("source", [
    "ROW_GRANTS = {}\n",
    "ROW_GRANTS = {}\nRETIRED_ROW_GRANTS = {}\nROW_GRANTS = {}\n",
    '"""doc"""\nROW_GRANTS = {}\nRETIRED_ROW_GRANTS = {}\n',
    "ROW_GRANTS = {}\nRETIRED_ROW_GRANTS = {}\nEXTRA = 1\n",
    "ROW_GRANTS = RETIRED_ROW_GRANTS = {}\n",
    "ROW_GRANTS: dict = {}\nRETIRED_ROW_GRANTS = {}\n",
    "import os\nROW_GRANTS = {}\nRETIRED_ROW_GRANTS = {}\n",
    "ROW_GRANTS = dict()\nRETIRED_ROW_GRANTS = {}\n",
    "ROW_GRANTS = {**{}}\nRETIRED_ROW_GRANTS = {}\n",
    "ROW_GRANTS = {'gemini': %r, 'gemini': %r}\nRETIRED_ROW_GRANTS = {}\n" % (PIN, PIN),
    "ROW_GRANTS = {'pi': %r}\nRETIRED_ROW_GRANTS = {}\n" % (PIN,),
    "ROW_GRANTS = {'gemini': ('a' * 64, 'b' * 64, 'x')}\nRETIRED_ROW_GRANTS = {}\n",
    "ROW_GRANTS = {'gemini': ('A' * 64, 'b' * 64, '2026-12-30T00:00:00+00:00')}\n"
    "RETIRED_ROW_GRANTS = {}\n",
    "ROW_GRANTS = {'gemini': ['a' * 64, 'b' * 64, '2026-12-30T00:00:00+00:00']}\n"
    "RETIRED_ROW_GRANTS = {}\n",
    "ROW_GRANTS = {'gemini': ('a' * 64, 'b' * 64, '2026-12-30T00:00:00')}\n"
    "RETIRED_ROW_GRANTS = {}\n",
    "ROW_GRANTS = {'gemini': %r}\nRETIRED_ROW_GRANTS = {'gemini': (%r,)}\n" % (PIN, PIN),
    "ROW_GRANTS = {}\nRETIRED_ROW_GRANTS = {'gemini': %r}\n" % (PIN,),
    "ROW_GRANTS = {}\nRETIRED_ROW_GRANTS = {'gemini': (%r, %r)}\n" % (PIN, PIN),
])
def test_k1_t1_the_grant_grammar_refuses_everything_else(source):
    from phase_loop_runtime import seat_window as w
    with pytest.raises(w.WindowClaimRefused) as refused:
        w.row_grant_pins(source.encode())
    assert refused.value.code == "window_grants_invalid"


def test_k1_t1_the_shipped_module_parses_and_is_literal_only():
    from phase_loop_runtime import seat_window as w
    active, retired = w.row_grant_pins()
    assert active == {} and retired == {}
    good = ("ROW_GRANTS = {'codex': %r}\nRETIRED_ROW_GRANTS = {'codex': (%r,)}\n"
            % (PIN, ("c" * 64, "d" * 64, "2026-11-30T00:00:00+00:00"))).encode()
    active, retired = w.row_grant_pins(good)
    assert active == {"codex": PIN} and retired["codex"][0][0] == "c" * 64


@pytest.mark.parametrize("bad", ["ROW_GRANTS = {}\n", "ROW_GRANTS = {}\nRETIRED_ROW_GRANTS = {}\nX = 1\n"])
def test_k1_t1_eligibility_claim_and_verification_all_refuse_a_bad_module(
        tmp_path, monkeypatch, fixture_vendor, bad):
    from phase_loop_runtime import seat_window as w
    world = _row_world(tmp_path, monkeypatch)
    assert _run_row(world, monkeypatch)["code"] == "window_review_required"
    world.grants.write_text(bad)
    assert w.window_grant("codex", "row", ROW_NOW) is False
    with pytest.raises(w.WindowClaimRefused):
        w.claim_window_attempt("codex", "row", "c" + "9" * 31, ROW_NOW)
    assert world.verify()["code"] == "window_grants_invalid"


def test_k1_t1_values_come_from_the_checked_bytes_never_an_import(tmp_path, monkeypatch,
                                                                  fixture_vendor):
    import sys
    from phase_loop_runtime import seat_window as w
    world = _row_world(tmp_path, monkeypatch)
    sys.modules.pop("phase_loop_runtime.seat_window_grants", None)
    w.row_grant_pins()
    w.window_grant("codex", "row", ROW_NOW)
    assert "phase_loop_runtime.seat_window_grants" not in sys.modules


def test_k1_t1_a_retired_pin_admits_nothing(tmp_path, monkeypatch, fixture_vendor):
    from phase_loop_runtime import seat_window as w
    world = _row_world(tmp_path, monkeypatch)
    _write_grants(world.grants, {}, {"codex": (world.pin,)})
    assert w.window_grant("codex", "row", ROW_NOW) is False
    with pytest.raises(w.WindowClaimRefused):
        w.claim_window_attempt("codex", "row", "c" + "1" * 31, ROW_NOW)


# --- F8: grants. ---

def test_k1_f8_mint_publish_install_claim_in_order(tmp_path, monkeypatch, fixture_vendor):
    """The pin change touches only the grants module, so release identity does not move
    and the installed release's claim checks the identity the grant names."""
    from phase_loop_runtime import seat_window as w
    import shutil
    before = w.release_identity()
    world = _row_world(tmp_path, monkeypatch)
    package = Path(w.__file__).parent
    copy = tmp_path / "package"
    shutil.copytree(package, copy, ignore=shutil.ignore_patterns("__pycache__"))
    assert w.release_identity(copy) == before
    grants = copy / "seat_window_grants.py"
    grants.write_bytes(grants.read_bytes() + b"# pin publication edits this file only\n")
    assert w.release_identity(copy) == before  # a grants-only change keeps the identity
    other = copy / "seat_window.py"
    other.write_bytes(other.read_bytes() + b"\n")
    assert w.release_identity(copy) != before  # any other source change moves it
    assert json.loads(next((tmp_path / "admission").glob("row-grant-codex-*.jsonl"))
                      .read_bytes().splitlines()[0])["release_identity"] == before
    assert w.window_grant("codex", "row", ROW_NOW) is True
    monkeypatch.setattr(w, "release_identity", lambda: "0" * 64)
    with pytest.raises(w.WindowClaimRefused) as refused:
        w.claim_window_attempt("codex", "row", "c" + "1" * 31, ROW_NOW)
    assert refused.value.code == "window_grant_release_mismatch"


def _spy_auth(monkeypatch):
    """Every preflight and auth function the kit can reach before a login."""
    from phase_loop_runtime import seat_window as w
    from phase_loop_runtime.advisor_board import composition
    calls = []
    monkeypatch.setattr(w, "preflight", lambda **k: calls.append("preflight"))
    monkeypatch.setattr(composition, "default_board_auth_ok",
                        lambda vendor: calls.append("auth") or True)
    monkeypatch.setattr(w, "run_native_window", lambda **k: calls.append("launch"))
    return calls


@pytest.mark.parametrize("change", [
    "no_pin", "no_file", "unsafe_dir", "corrupt", "partial", "broken_chain",
    "witness_disagrees", "wrong_host", "wrong_class", "wrong_uid", "packet", "release",
    "exhausted", "before_window", "past_deadline"])
def test_k1_f8_each_refusal_happens_before_any_auth_call(tmp_path, monkeypatch,
                                                         fixture_vendor, change):
    from phase_loop_runtime import seat_window as w
    world = _row_world(tmp_path, monkeypatch,
                       max_attempts=2 if change == "witness_disagrees" else 1)
    admission = tmp_path / "admission"
    grant = next(admission.glob("row-grant-codex-*.jsonl"))
    raw = grant.read_bytes()
    first = json.loads(raw.splitlines()[0])
    now = ROW_NOW

    def reline(**values):
        line = (json.dumps(dict(first, **values), sort_keys=True, separators=(",", ":"))
                + "\n").encode()
        grant.write_bytes(line)
        import hashlib
        _write_grants(world.grants, {"codex": (hashlib.sha256(line).hexdigest(), *world.pin[1:])})

    if change == "no_pin":
        _write_grants(world.grants, {})
    elif change == "no_file":
        grant.unlink()
    elif change == "unsafe_dir":
        admission.chmod(0o755)
    elif change == "corrupt":
        grant.write_bytes(raw + b"not json\n")
    elif change == "partial":
        grant.write_bytes(raw + b'{"schema":')
    elif change == "broken_chain":
        assert _run_row(world, monkeypatch)["code"] == "window_review_required"
        import re
        grant.write_bytes(re.sub(rb'"previous_sha256":"[0-9a-f]{64}"',
                                 b'"previous_sha256":"' + b"0" * 64 + b'"', grant.read_bytes()))
    elif change == "witness_disagrees":
        assert _run_row(world, monkeypatch)["code"] == "window_review_required"
        next(world.root.glob("window-attempt-codex-*")).unlink()
    elif change == "wrong_host":
        monkeypatch.setattr(w, "_host_digest", lambda: "9" * 64)
    elif change == "wrong_class":
        reline(host_class="team")
    elif change == "wrong_uid":
        reline(operator_uid=first["operator_uid"] + 1)
    elif change == "packet":
        reline(packet_sha256="6" * 64)
    elif change == "release":
        reline(release_identity="0" * 64)
    elif change == "exhausted":
        assert _run_row(world, monkeypatch)["code"] == "window_review_required"
    elif change == "before_window":
        now = ROW_NOW - dt.timedelta(days=2)
    else:
        now = ROW_NOW + dt.timedelta(days=1) - dt.timedelta(seconds=w.ROW_COMPLETION_MARGIN_S - 1)
    calls = _spy_auth(monkeypatch)
    monkeypatch.setattr(w, "_now", lambda: now)
    assert w.window_grant("codex", "row", now) is False
    result = w.qualify(window="row", monitoring_policy="bounded", repo=tmp_path, attended=True,
                       vendor="codex")
    assert result["code"] != "window_review_required"
    assert calls == []
    if change == "unsafe_dir":
        admission.chmod(0o700)


def test_k1_f8_a_held_lock_refuses_and_two_concurrent_claims_leave_one_winner(
        tmp_path, monkeypatch, fixture_vendor):
    import fcntl
    from phase_loop_runtime import seat_window as w
    world = _row_world(tmp_path, monkeypatch)
    grant = next((tmp_path / "admission").glob("row-grant-codex-*.jsonl"))
    with open(grant, "rb") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(w.WindowClaimRefused) as refused:
            w.claim_window_attempt("codex", "row", "c" + "1" * 31, ROW_NOW)
        assert refused.value.code == "window_claim_locked"
    outcomes = []
    barrier = threading.Barrier(8)

    def claim(index):
        barrier.wait()
        try:
            w.claim_window_attempt("codex", "row", f"c{index:031x}", ROW_NOW)
            outcomes.append("won")
        except w.WindowClaimRefused as exc:
            outcomes.append(exc.code)
    threads = [threading.Thread(target=claim, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("won") == 1
    assert len(grant.read_bytes().splitlines()) == 2
    assert len(list(world.root.glob("window-attempt-codex-*"))) == 1


def test_k1_f8_every_claim_counts_and_none_is_released(tmp_path, monkeypatch, fixture_vendor):
    from phase_loop_runtime import seat_window as w
    from phase_loop_runtime.advisor_board.composition import CompositionOutcome
    world = _row_world(tmp_path, monkeypatch)
    monkeypatch.setattr(w, "preflight", lambda **k: CompositionOutcome(
        "policy_refused", "review_composition_refused", ("grok",), "restore"))
    assert _run_row(world, monkeypatch)["code"] == "review_composition_refused"
    assert _run_row(world, monkeypatch)["code"] == "window_attempts_exhausted"


def test_k1_f8_batch_enumeration_preflights_nothing_and_claims_nothing(
        tmp_path, monkeypatch, fixture_vendor):
    from phase_loop_runtime import seat_window as w
    world = _row_world(tmp_path, monkeypatch)
    calls = _spy_auth(monkeypatch)
    monkeypatch.setattr(w, "claim_window_attempt", lambda *a, **k: calls.append("claim"))
    assert w.batch_candidates() == ["codex"]
    assert calls == []
    assert w.window_grant("codex", "row", ROW_NOW) is True
    assert not list(world.root.glob("window-attempt-*"))


def test_k1_f8_grant_rollover_keeps_retired_pin_records_verifying(row_world):
    _write_grants(row_world.grants, {}, {"codex": (row_world.pin,)})
    assert row_world.verify()["passed"] is True
    _write_grants(row_world.grants, {}, {})
    assert row_world.verify()["code"] == "window_grant_unavailable"


def test_k1_f8_second_attempt_needs_the_owners_explicit_ok(tmp_path, monkeypatch,
                                                           fixture_vendor):
    from phase_loop_runtime import seat_window as w, seat_window_supply as supply
    with pytest.raises(w.WindowClaimRefused):
        w.mint_row_grant("codex", not_before="x", not_after="y", packet_sha256="5" * 64,
                         launch_envelope=supply.required_envelope("codex"), max_attempts=3)


def test_k1_f8_w1_is_unchanged():
    from phase_loop_runtime import seat_window as w
    assert w.OWNER_W1_APPROVED_UNTIL == "2026-12-04T00:00:00+00:00"
    assert w.W1_COMPLETION_MARGIN_S == 10800 and w.W1_GRANT_NAME == "w1-grant.jsonl"
    # The owner-approved W1 packet and its minted grant (agent-harness#2157).
    assert w.OWNER_W1_GRANT_SHA256 == "6145c5c47aa724133622ca8cd19f461fd21ae798a57521bd89f9c642ef9c0041"
    assert w.OWNER_W1_PACKET_SHA256 == "bfc7b22c3cf60cc41a9a400397ffdf23d46f2154001554046b23410fd097e361"
    assert w.W1_GRANT_FIELDS == ("schema", "host_digest", "not_before", "not_after", "vendor",
                                 "host_class", "max_attempts", "packet_sha256", "nonce")
