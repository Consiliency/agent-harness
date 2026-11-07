"""TEAMHOST Gemini overlay and resolved-subject CLI follow-ups."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from phase_loop_runtime import agy_qualification
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_subject


REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "plans/evidence/seat-teamhost/gemini-config-writes.json"


def _writable_destinations(bind_args: list[str]) -> tuple[PurePosixPath, ...]:
    return tuple(
        PurePosixPath(bind_args[index + 2])
        for index, value in enumerate(bind_args)
        if value == "--bind"
    )


def _covered(path: PurePosixPath, destinations: tuple[PurePosixPath, ...]) -> bool:
    return any(path == destination or path.is_relative_to(destination) for destination in destinations)


def test_recorded_gemini_writes_fit_the_narrow_real_overlay_and_outside_is_refused(tmp_path):
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    binds = seat_jail._gemini_binds(
        str(tmp_path / "home"),
        str(tmp_path / "gemini-config"),
        str(tmp_path / "egress-ca.pem"),
    )
    destinations = _writable_destinations(binds)
    seat_home = PurePosixPath(seat_jail.SEAT_HOME)
    writes = tuple(seat_home / path for path in evidence["observed_writes"])
    outside = (
        seat_home / ".gemini/config.json",
        seat_home / ".gemini/extensions/provider.json",
        seat_home / ".gemini/antigravity-cli/settings.json",
    )

    assert evidence["closure"] == "closed"
    assert evidence["minimum_directory_overlay"] == ".gemini/config"
    assert all(_covered(path, destinations) for path in writes)
    assert all(not _covered(path, destinations) for path in outside)

    # Neutralising mutant: restoring a writable bind over the whole `.gemini` directory
    # admits the first two paths that production refuses.
    whole_directory = (PurePosixPath(seat_jail.SEAT_GEMINI_DOTDIR),)
    assert all(_covered(path, whole_directory) for path in outside[:2])


class _Store:
    host_dir = Path("/metadata-only/agy-qualification")

    @staticmethod
    def status():
        return {"safe": True}

    @staticmethod
    def entries():
        return []


def test_agy_qualification_status_uses_the_resolved_subject(tmp_path, monkeypatch, capsys):
    subject = tmp_path / "agy"
    seen: list[Path | None] = []
    monkeypatch.setattr(agy_qualification, "Store", _Store)
    monkeypatch.setattr(agy_qualification, "agy_profile_digest", lambda: "c" * 64)
    monkeypatch.setattr(
        agy_qualification,
        "_panel",
        lambda: SimpleNamespace(_broker_subscription_env=lambda: {"PATH": str(tmp_path)}),
    )
    monkeypatch.setattr(
        seat_subject,
        "resolve_seat_subject",
        lambda leg, env: SimpleNamespace(subject_path=subject),
    )
    monkeypatch.setattr(agy_qualification, "self_qualification_enabled", lambda: True)
    monkeypatch.setattr(
        agy_qualification,
        "admission_verdict",
        lambda env, subject_path, *, execute: (
            seen.append(subject_path)
            or agy_qualification.AgyVerdict("admits", None, None)
        ),
    )

    assert agy_qualification.cli_main(SimpleNamespace(action="status")) == 0
    assert seen == [subject]
    assert json.loads(capsys.readouterr().out)["verdict"]["status"] == "admits"


def test_agy_qualification_run_uses_the_resolved_subject(tmp_path, monkeypatch, capsys):
    subject = tmp_path / "agy"
    seen: list[Path | None] = []
    closed: list[bool] = []
    admission = SimpleNamespace(
        admission_class="locally_qualified",
        image=SimpleNamespace(sha256="a" * 64),
        help_sha256="b" * 64,
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(agy_qualification, "Store", _Store)
    monkeypatch.setattr(
        agy_qualification,
        "_panel",
        lambda: SimpleNamespace(_broker_subscription_env=lambda: {"PATH": str(tmp_path)}),
    )
    monkeypatch.setattr(
        seat_subject,
        "resolve_seat_subject",
        lambda leg, env: SimpleNamespace(subject_path=subject),
    )
    monkeypatch.setattr(
        agy_qualification,
        "requalify_once",
        lambda env, *, heartbeat, subject_path: seen.append(subject_path) or admission,
    )

    assert agy_qualification.cli_main(SimpleNamespace(action="run")) == 0
    assert seen == [subject]
    assert closed == [True]
    assert json.loads(capsys.readouterr().out)["image_sha256"] == "a" * 64
