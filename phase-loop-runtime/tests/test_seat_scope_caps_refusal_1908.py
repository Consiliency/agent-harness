"""Tests mapping ``seat_resource_caps._seat_scope`` refusals to ``seat_resource_caps_unavailable`` on review legs (agent-harness#1908)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_resource_caps as caps
from phase_loop_runtime.advisor_board.backing import CredentiallessAdapterFailure
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
from phase_loop_runtime.advisor_board.matrix import default_matrix
from phase_loop_runtime.advisor_board.schema import Board

from harden_tdd_guard import invoke_sanctioned_board_control
from test_jailed_gemini_refusals_1823 import _jailed_gemini_spawn, _raising


KEY = "gemini:gemini-4-argon:medium:alternative-approach"
UNKNOWN = "unknown failure; CLI output not retained"


def _board_leg(failure: object, notices: tuple[str, ...] = ()) -> pi.PanelLegResult:
    leg = pi.PanelLegResult(
        leg="gemini",
        status="DEGRADED",
        text="",
        detail=pi._resolve_leg_detail(failure, None, KEY),
        seat_key=KEY,
    )
    if notices:
        pi.attach_seat_notices(leg, notices)
    return leg


def _board_detail(failure: object) -> str:
    return _board_leg(failure).detail


def _wrapped(exc: BaseException) -> CredentiallessAdapterFailure:
    try:
        raise CredentiallessAdapterFailure(f"credentialless broker client failed: {exc}") from exc
    except CredentiallessAdapterFailure as wrapper:
        return wrapper


def _opaque(exc: BaseException) -> ValueError:
    try:
        raise ValueError("unrelated outer failure") from exc
    except ValueError as outer:
        return outer


def _trigger_seat_scope_failure(path: str, monkeypatch: pytest.MonkeyPatch | None = None) -> caps.CapsUnavailable:
    if path == "empty_seat_key":
        with pytest.raises(caps.CapsUnavailable) as caught:
            with caps._seat_scope(""):
                pass
        return caught.value
    if path == "non_str_seat_key":
        with pytest.raises(caps.CapsUnavailable) as caught:
            with caps._seat_scope(None):  # type: ignore[arg-type]
                pass
        return caught.value
    if path == "invalid_launch_class":
        with pytest.raises(caps.CapsUnavailable) as caught:
            with caps._seat_scope("seat-a", "not-a-class"):  # type: ignore[arg-type]
                pass
        return caught.value
    if path == "two_seat_keys":
        with pytest.raises(caps.CapsUnavailable) as caught:
            with caps._seat_scope("seat-a"):
                with caps._seat_scope("seat-b"):
                    pass
        return caught.value
    if path == "two_launch_classes":
        with pytest.raises(caps.CapsUnavailable) as caught:
            with caps._seat_scope("seat-a", caps._LaunchClass.BOARD):
                with caps._seat_scope("seat-a", caps._LaunchClass.QUALIFICATION):
                    pass
        return caught.value
    if path == "teardown_release_parent":
        assert monkeypatch is not None
        monkeypatch.setattr(
            caps,
            "_release_parent",
            lambda _parent: caps._refuse("parent cgroup teardown refused"),
        )
        with pytest.raises(caps.CapsUnavailable) as caught:
            with caps._seat_scope("seat-teardown"):
                scope = caps._CURRENT_SEAT_SCOPE.get()
                assert scope is not None
                scope.parent = object()  # type: ignore[assignment]
        return caught.value
    raise AssertionError(f"unknown path: {path}")


class _FakeImage:
    """Minimal image handle whose ``reopen()`` yields a real closeable fd."""

    def __init__(self, target: Path) -> None:
        self._target = target

    def reopen(self) -> int:
        return os.open(self._target, os.O_RDONLY)


def _write_expired_gemini_token(home: Path) -> Path:
    token_path = home / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    payload = {
        "auth_method": "oauth",
        "token": {
            "access_token": "synthetic-expired-access",
            "refresh_token": "synthetic-refresh",
            "token_type": "Bearer",
            "expiry": expired,
        },
    }
    token_path.write_text(json.dumps(payload), encoding="utf-8")
    return token_path


@pytest.mark.parametrize(
    "path",
    [
        "empty_seat_key",
        "non_str_seat_key",
        "invalid_launch_class",
        "two_seat_keys",
        "two_launch_classes",
        "teardown_release_parent",
    ],
)
@pytest.mark.parametrize("through_broker", [False, True], ids=["direct", "broker-wrapped"])
def test_every_seat_scope_failure_path_maps_to_seat_resource_caps_unavailable(
    monkeypatch: pytest.MonkeyPatch, path: str, through_broker: bool
) -> None:
    exc = _trigger_seat_scope_failure(path, monkeypatch)
    target = _wrapped(exc) if through_broker else exc
    failure = pi._exception_failure(target)
    assert failure == caps.CODE
    assert pi._caused_refusal_code(target) == caps.CODE
    assert _board_detail(failure) == caps.CODE


def test_caps_unavailable_exact_type_wrapper_and_literal_message_discipline() -> None:
    class SlyCaps(caps.CapsUnavailable):
        pass

    class SlyWrapper(CredentiallessAdapterFailure):
        pass

    # Exact-type check in _typed_refusal_code / _caused_refusal_code rejects subclasses
    # even when their message equals CODE, and rejects wrapper subclasses and opaque wrappers.
    assert pi._caused_refusal_code(SlyCaps("spoofed")) is None
    assert pi._caused_refusal_code(SlyCaps(caps.CODE)) is None
    assert pi._caused_refusal_code(_wrapped(SlyCaps("spoofed"))) is None
    assert pi._caused_refusal_code(_wrapped(SlyCaps(caps.CODE))) is None

    real = _trigger_seat_scope_failure("two_seat_keys")
    sly_wrapped = SlyWrapper("credentialless broker client failed: caps")
    sly_wrapped.__cause__ = real
    assert pi._caused_refusal_code(sly_wrapped) is None
    assert pi._exception_failure(sly_wrapped).unknown

    opaque = pi._exception_failure(_opaque(real))
    assert pi._caused_refusal_code(_opaque(real)) is None
    assert type(opaque) is pi._LegFailure and opaque.unknown
    assert _board_detail(opaque) == UNKNOWN

    # Direct literal-message case: ValueError(CODE) is an exact coded-message type;
    # _exception_failure's legacy exact-literal fallback also recognizes CODE directly.
    literal_value_error = ValueError(caps.CODE)
    assert pi._caused_refusal_code(literal_value_error) == caps.CODE
    assert pi._exception_failure(literal_value_error) == caps.CODE
    assert pi._exception_failure(SlyCaps("spoofed")).unknown
    assert pi._exception_failure(SlyCaps(caps.CODE)) == caps.CODE


def test_default_spawn_via_provider_translates_direct_and_broker_wrapped_caps_refusals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Direct _seat_scope refusal inside _default_spawn_via_provider.
    monkeypatch.setattr(
        pi,
        "_default_spawn",
        lambda *a, **k: pytest.fail("_default_spawn must not run when _seat_scope refuses"),
    )
    with caps._seat_scope("outer-seat-key"):
        spawned = pi._default_spawn_via_provider(
            "gemini",
            "artifact",
            seat_key="conflicting-seat-key",
        )
    assert spawned[0] == "DEGRADED"
    assert spawned[1] == ""
    assert spawned[2] == caps.CODE
    assert getattr(spawned, "seat_notices", ()) == (caps.CODE,)

    # 2. Exact CredentiallessAdapterFailure wrapping a real _seat_scope refusal.
    wrapped = _wrapped(_trigger_seat_scope_failure("two_seat_keys"))
    monkeypatch.setattr(pi, "_default_spawn", lambda *a, **k: (_ for _ in ()).throw(wrapped))
    spawned_wrapped = pi._default_spawn_via_provider("gemini", "artifact", seat_key="seat-a")
    assert spawned_wrapped[0] == "DEGRADED"
    assert spawned_wrapped[1] == ""
    assert spawned_wrapped[2] == caps.CODE
    assert getattr(spawned_wrapped, "seat_notices", ()) == (caps.CODE,)

    # 3. Direct literal-message ValueError(CODE) at the provider boundary.
    monkeypatch.setattr(
        pi, "_default_spawn", lambda *a, **k: (_ for _ in ()).throw(ValueError(caps.CODE))
    )
    spawned_literal = pi._default_spawn_via_provider("gemini", "artifact", seat_key="seat-a")
    assert spawned_literal[0] == "DEGRADED"
    assert spawned_literal[1] == ""
    assert spawned_literal[2] == caps.CODE
    assert getattr(spawned_literal, "seat_notices", ()) == (caps.CODE,)


def test_default_spawn_via_provider_does_not_misclassify_wrapper_subclasses_or_opaque_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlyWrapper(CredentiallessAdapterFailure):
        pass

    class SlyCaps(caps.CapsUnavailable):
        pass

    real = _trigger_seat_scope_failure("two_seat_keys")
    sly_wrapped = SlyWrapper("sly wrapper message")
    sly_wrapped.__cause__ = real

    for exc in (sly_wrapped, _opaque(real), SlyCaps(caps.CODE)):
        monkeypatch.setattr(pi, "_default_spawn", lambda *a, _e=exc, **k: (_ for _ in ()).throw(_e))
        spawned = pi._default_spawn_via_provider("gemini", "artifact", seat_key="seat-a")
        assert spawned[0] == "ERROR"
        assert len(spawned) == 2
        assert getattr(spawned, "seat_notices", ()) == ()


def test_default_spawn_via_provider_translates_real_seat_scope_teardown_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        caps,
        "_release_parent",
        lambda _parent: caps._refuse("parent cgroup teardown refused"),
    )

    def _spawn_attaching_parent(*_args, **_kwargs):
        scope = caps._CURRENT_SEAT_SCOPE.get()
        assert scope is not None
        scope.parent = object()  # type: ignore[assignment]
        return ("OK", "AGREE")

    monkeypatch.setattr(pi, "_default_spawn", _spawn_attaching_parent)
    spawned = pi._default_spawn_via_provider("gemini", "artifact", seat_key="seat-teardown")
    assert spawned[0] == "DEGRADED"
    assert spawned[1] == ""
    assert spawned[2] == caps.CODE
    assert getattr(spawned, "seat_notices", ()) == (caps.CODE,)
    leg = _board_leg(spawned[2], getattr(spawned, "seat_notices", ()))
    assert leg.detail == caps.CODE
    assert [notice.code for notice in leg.seat_notices] == [caps.CODE]


def test_invoke_board_outer_seat_scope_teardown_refusal_surfaces_typed_detail_and_one_notice(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        caps,
        "_release_parent",
        lambda _parent: caps._refuse("parent cgroup teardown refused"),
    )

    def _provider_attaching_parent(*_args, **_kwargs):
        scope = caps._CURRENT_SEAT_SCOPE.get()
        assert scope is not None
        scope.parent = object()  # type: ignore[assignment]
        return ("OK", "AGREE")

    monkeypatch.setattr(pi, "_default_spawn_via_provider", _provider_attaching_parent)
    monkeypatch.setattr(pi, "board_preflight_requalify", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_publish_seat_modes", lambda *a, **k: None)

    gemini = next(s for s in DEFAULT_SEATS if s.harness == "gemini")
    board = Board(name="gemini-only", purpose="premerge-review", seats=(gemini,))
    result = invoke_sanctioned_board_control(
        board,
        "artifact",
        matrix=default_matrix(env={}, probe=lambda *a: True),
        base_env={},
        repo_dir=tmp_path,
        stream_dir=tmp_path / "stream",
    )
    assert len(result.legs) == 1
    leg = result.legs[0]
    assert leg.status == "DEGRADED"
    assert leg.text == ""
    assert leg.detail == caps.CODE
    assert [notice.code for notice in leg.seat_notices] == [caps.CODE]
    assert [notice.code for notice in pi.refused_seat_notices(result.legs)] == [caps.CODE]


def test_default_spawn_outer_handler_surfaces_seat_scope_caps_unavailable_for_gemini(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        pi,
        "_exec_leg",
        lambda *a, **k: (_ for _ in ()).throw(
            _trigger_seat_scope_failure("two_seat_keys")
        ),
    )
    monkeypatch.setattr(
        pi,
        "_seat_route_for_spawn",
        lambda *a, **k: (None, [], None),
    )
    spawned = pi._default_spawn(
        "gemini",
        "artifact",
        repo_dir=tmp_path,
        mode="advisory",
        model="gemini-4-argon",
        env={},
    )
    assert spawned[0] == "DEGRADED"
    assert spawned[1] == ""
    assert spawned[2] == caps.CODE
    assert getattr(spawned, "seat_notices", ()) == (caps.CODE,)


@pytest.mark.parametrize(
    "path",
    ["empty_seat_key", "two_seat_keys", "two_launch_classes", "teardown_release_parent"],
)
def test_jailed_gemini_broker_prepare_seat_scope_refusal_keeps_typed_detail_and_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path, path: str
) -> None:
    spawned, record = _jailed_gemini_spawn(
        monkeypatch,
        tmp_path,
        prepare=_raising(_trigger_seat_scope_failure(path, monkeypatch)),
    )
    assert spawned[0] == "DEGRADED"
    assert spawned[1] == ""
    leg = _board_leg(spawned[2], getattr(spawned, "seat_notices", ()))
    assert leg.detail == caps.CODE
    assert [notice.code for notice in leg.seat_notices] == [caps.CODE]
    assert record["refusal"] == caps.CODE


@pytest.mark.real_seat_caps
@pytest.mark.parametrize(
    "failure_mode",
    ["real_capped_popen_unready", "capped_popen_caps_unavailable", "scope_teardown"],
)
def test_real_gemini_credential_renewal_caps_refusal_surfaces_typed_detail_notice_and_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure_mode: str
) -> None:
    """Regression for agent-harness#1908: drive the real ``_refresh_gemini_credential`` ->
    ``_seat_scope`` -> ``launch_provider`` -> ``capped_popen`` path inside the brokered
    Gemini leg handler and verify ``seat_resource_caps_unavailable`` (never
    ``Gemini broker local provider failure``), empty review text, one rendered notice,
    and retained ``leg_exec.v1`` refusal code."""
    home = tmp_path / "gemini-home"
    _write_expired_gemini_token(home)
    fake_bin = tmp_path / "fake-agy"
    fake_bin.write_bytes(b"#!/bin/sh\nexit 0\n")
    image = _FakeImage(fake_bin)

    if failure_mode == "real_capped_popen_unready":
        # Keep production caps.capped_popen in the path so its real _refuse -> _refused
        # conversion to SeatSandboxRefused(CODE) runs end-to-end.
        monkeypatch.setattr(caps, "load_caps", lambda: caps.DEFAULT_CAPS)
        monkeypatch.setattr(caps, "_device_plan", lambda _c: ((), ()))
        monkeypatch.setattr(caps, "readiness_code", lambda: caps.CODE)
    elif failure_mode == "capped_popen_caps_unavailable":
        def _failing_capped_popen(*_args, **_kwargs):
            raise caps.CapsUnavailable("no delegated cgroup v2 parent")

        monkeypatch.setattr(caps, "capped_popen", _failing_capped_popen)
    elif failure_mode == "scope_teardown":
        monkeypatch.setattr(
            caps,
            "_release_parent",
            lambda _parent: caps._refuse("renewal parent teardown refused"),
        )

        class _FakeProc:
            pid = 999999
            returncode = 0
            stdout = None
            stderr = None

            def communicate(self, timeout=None):
                return b"", b""

        def _popen_attaching_parent(*_args, **_kwargs):
            scope = caps._CURRENT_SEAT_SCOPE.get()
            assert scope is not None
            scope.parent = object()  # type: ignore[assignment]
            return _FakeProc()

        monkeypatch.setattr(caps, "capped_popen", _popen_attaching_parent)
        monkeypatch.setattr(pi, "_require_launch_proof", lambda _proc: None)
        monkeypatch.setattr(pi, "_count_provider_spawn", lambda: None)
        monkeypatch.setattr(pi, "_anchor_process_group", lambda _proc: None)
        monkeypatch.setattr(pi, "_terminate_process_group", lambda _proc: None)

    def _exec_driving_real_renewal(*_args, **_kwargs):
        pi._refresh_gemini_credential(home, image)
        pytest.fail("_refresh_gemini_credential must refuse on caps failure")

    def _prepare_unused(*_args, **_kwargs):
        pytest.fail("_prepare_jailed_gemini should not run on unjailed route")

    monkeypatch.setattr(pi, "_exec_leg", _exec_driving_real_renewal)
    spawned, record = _jailed_gemini_spawn(
        monkeypatch,
        tmp_path,
        prepare=_prepare_unused,
        jailed=False,
    )
    assert spawned[0] == "DEGRADED"
    assert spawned[1] == ""
    assert spawned[2] == caps.CODE
    leg = _board_leg(spawned[2], getattr(spawned, "seat_notices", ()))
    assert leg.detail == caps.CODE
    assert [notice.code for notice in leg.seat_notices] == [caps.CODE]
    assert record["refusal"] == caps.CODE
