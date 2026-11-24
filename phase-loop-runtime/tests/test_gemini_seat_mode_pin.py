"""The jailed Gemini seat pins agy's agent mode to Default.

agy 1.5.7 made Auto the default agent mode for sessions with no saved mode, headless ``-p``
runs included. Auto sends commands that would leave agy's terminal sandbox to a separate
reviewing agent, which is a second model session the seat forbids. The seat's argv is the
qualified profile and carries no ``--mode``, so the settings file the parent writes into
the seat's ``.gemini`` carries ``"agentMode": ""``, the value agy saves for Default.

The pin is not a requalification. It moves no validator closure, seat QCI, jail profile
digest or Claude-SDK proof input, and these tests hold each of those still. The heartbeat
route, which passes ``--mode plan`` and has its own owned settings, is unchanged.
"""
from __future__ import annotations

import importlib.util
import json
import os
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import agy_qualification as q
from phase_loop_runtime import claude_seat_transport as cst
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail, seat_jail_qualification, seat_subject

REPO = Path(__file__).resolve().parents[2]
CONVERTER = REPO / "phase-loop-runtime" / "scripts" / "convert_agy_record_v2.py"
#: The jail profile digests the registered seats were recorded against (x86_64).
DEFAULT_MODE = {"agentMode": ""}


def _settings(dotdir: Path) -> bytes:
    return (dotdir / "antigravity-cli" / "settings.json").read_bytes()


def _ro_bind_source(jail, target: str) -> str:
    owner = list(jail.process_owner)
    return next(owner[i + 1] for i, item in enumerate(owner)
                if item == "--ro-bind" and owner[i + 2] == target)


def _compose_seat(tmp_path: Path, monkeypatch) -> pi._JailedSeat:
    """The production composer, ``_prepare_jailed_gemini``, with only its host lookups
    replaced: the config directories and both jails are built for real."""
    tree = tmp_path / "review" / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    subject = seat_subject.SeatSubject("gemini", "standalone", Path("/usr/bin/true"), None, None)
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda _leg, _env: (subject, None))
    monkeypatch.setattr(pi, "_approved_stage_or_refuse", lambda *_args: tree)
    monkeypatch.setattr(pi.gemini_heartbeat, "admit", lambda _env, **_kwargs: SimpleNamespace(
        image=SimpleNamespace(sha256="0" * 64), admission_class="qualified",
        path="/usr/bin/true", close=lambda: None))
    ca = tmp_path / "egress-ca.pem"
    ca.write_text("certificate\n")
    egress = SimpleNamespace(ca_cert=ca, proxy_url="http://127.0.0.1:3128",
                            private_proxy_token=b"fixture-session")
    return pi._prepare_jailed_gemini(
        tmp_path / "review", tmp_path / "seat", SimpleNamespace(staged_tree_sha256="0" * 64),
        3, os.getpid(), ("artifact", "instructions"), egress,
        env={"HOME": str(tmp_path), "PATH": str(tmp_path)}, credential="none",
    )


def _closure() -> dict[str, str]:
    spec = importlib.util.spec_from_file_location("convert_agy_record_v2", CONVERTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validator_closure(REPO / "phase-loop-runtime" / "src" / "phase_loop_runtime")


# ------------------------------------------------------------------ the seat home

def test_the_pin_is_agys_saved_default():
    assert pi._JAILED_GEMINI_SETTINGS == b'{"agentMode":""}\n'
    assert json.loads(pi._JAILED_GEMINI_SETTINGS) == DEFAULT_MODE


def test_the_composed_seat_and_probe_homes_pin_the_agent_mode(tmp_path, monkeypatch):
    from test_gemini_seat_egress_1170 import _assert_credential_free_gemini_jail

    seat = _compose_seat(tmp_path, monkeypatch)
    try:
        for jail in (seat.jail, seat.probe_jail):
            dotdir = Path(_ro_bind_source(jail, seat_jail.SEAT_GEMINI_DOTDIR))
            assert dotdir == Path(jail.gemini_config_dir)
            assert _settings(dotdir) == pi._JAILED_GEMINI_SETTINGS
            assert json.loads(_settings(dotdir)) == DEFAULT_MODE
            # The pinned settings leave the jail the qualified profile.
            assert jail.profile_digest == seat_jail.jail_profile_digest("gemini")
            pi._require_canonical_jail(jail)
            _assert_credential_free_gemini_jail(jail, seat.private_proxy_token)
        assert Path(seat.jail.gemini_config_dir) == (
            seat.seat_dir / seat_jail.HOST_GEMINI_CONFIG_DIRNAME)
    finally:
        seat_jail.close_jail_fds(seat.jail)
        seat_jail.close_jail_fds(seat.probe_jail)


def test_a_credentialed_seat_config_keeps_the_pin_beside_its_token(tmp_path):
    config = tmp_path / seat_jail.HOST_GEMINI_CONFIG_DIRNAME
    pi._write_gemini_config(config, b'{"token": {}}')
    assert _settings(config) == pi._JAILED_GEMINI_SETTINGS
    assert (config / "antigravity-cli" / "antigravity-oauth-token").read_bytes() == b'{"token": {}}'


def test_the_jail_qualification_shape_carries_the_production_settings(tmp_path):
    shape = seat_jail_qualification._gemini_shape(tmp_path)
    assert _settings(shape["gemini_config"]) == pi._JAILED_GEMINI_SETTINGS


# ------------------------------------------------------------- the heartbeat route

def test_the_heartbeat_route_keeps_plan_mode_and_its_own_settings():
    def has_plan_mode(argv) -> bool:
        argv = list(argv)
        return any(argv[i:i + 3] == ["--sandbox", "--mode", "plan"] for i in range(len(argv)))

    assert has_plan_mode(q._HEARTBEAT_ARGV)
    assert has_plan_mode(pi._brokered_gemini_command(
        model="gemini-model", deadline_s=60.0, monitoring_policy="heartbeat_only"))
    # Its owned profile's settings are the broker's, unpinned, and they alone are what the
    # agy profile digest binds.
    broker = pi._broker_agy_settings_bytes()
    assert "agentMode" not in json.loads(broker)
    assert broker != pi._JAILED_GEMINI_SETTINGS
    assert q.profile_description("<image>")["settings_sha256"] == sha256(broker).hexdigest()


def test_the_jailed_argv_still_carries_no_mode():
    argv = pi._jailed_gemini_command("gemini-model")
    assert "--mode" not in argv and "--sandbox" not in argv


# ------------------------------------------------------------------------- the pins

def test_the_seat_settings_feed_neither_the_qci_nor_the_jail_digest(tmp_path, monkeypatch):
    qci, jail_digest = q.seat_qci(), seat_jail.jail_profile_digest("gemini")
    digests = []
    for name, settings in (("pinned", pi._JAILED_GEMINI_SETTINGS), ("empty", b"{}\n")):
        monkeypatch.setattr(pi, "_JAILED_GEMINI_SETTINGS", settings)
        assert q.seat_qci() == qci
        seat = _compose_seat(tmp_path / name, monkeypatch)
        try:
            assert _settings(Path(seat.jail.gemini_config_dir)) == settings
            digests.append(seat_jail.actual_profile_digest(seat.jail))
        finally:
            seat_jail.close_jail_fds(seat.jail)
            seat_jail.close_jail_fds(seat.probe_jail)
    assert digests == [jail_digest, jail_digest]


@pytest.mark.skipif(not CONVERTER.is_file(), reason="the converter is repository source")
def test_the_pin_is_outside_the_validator_closure():
    closure = _closure()
    for name in ("_JAILED_GEMINI_SETTINGS", "_write_gemini_config", "_prepare_jailed_gemini"):
        assert f"panel_invoker:{name}" not in closure


def test_the_pin_is_outside_the_claude_sdk_proof_inputs():
    assert cst._PI not in cst.SDK_PROOF_FILES
    regions = cst.SDK_PROOF_REGIONS[cst._PI]
    unbound = cst.SDK_PROOF_UNBOUND[cst._PI]
    for name in ("_JAILED_GEMINI_SETTINGS", "_write_gemini_config", "_prepare_jailed_gemini"):
        assert name not in regions and name not in unbound
