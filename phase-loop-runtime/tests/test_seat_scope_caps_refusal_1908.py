"""Tests mapping ``seat_resource_caps._seat_scope`` refusals to ``seat_resource_caps_unavailable`` (agent-harness#1908)."""

from __future__ import annotations

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_resource_caps as caps
from phase_loop_runtime.advisor_board.backing import CredentiallessAdapterFailure
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
from phase_loop_runtime.advisor_board.matrix import default_matrix
from phase_loop_runtime.advisor_board.schema import Board

from harden_tdd_guard import invoke_sanctioned_board_control
from test_jailed_gemini_refusals_1823 import _Route, _jailed_gemini_spawn, _raising


KEY = "gemini:gemini-4-argon:medium:alternative-approach"
UNKNOWN = "unknown failure; CLI output not retained"


def _board_detail(failure: object) -> str:
    leg = pi.PanelLegResult(
        leg="gemini",
        status="DEGRADED",
        text="",
        detail=pi._resolve_leg_detail(failure, None, KEY),
        seat_key=KEY,
    )
    return leg.detail


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


def _trigger_seat_scope_failure(path: str) -> caps.CapsUnavailable:
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
    raise AssertionError(f"unknown path: {path}")


@pytest.mark.parametrize(
    "path",
    [
        "empty_seat_key",
        "non_str_seat_key",
        "invalid_launch_class",
        "two_seat_keys",
        "two_launch_classes",
    ],
)
@pytest.mark.parametrize("through_broker", [False, True], ids=["direct", "broker-wrapped"])
def test_every_seat_scope_failure_path_maps_to_seat_resource_caps_unavailable(
    path: str, through_broker: bool
) -> None:
    exc = _trigger_seat_scope_failure(path)
    target = _wrapped(exc) if through_broker else exc
    failure = pi._exception_failure(target)
    assert failure == caps.CODE
    assert _board_detail(failure) == caps.CODE


def test_caps_unavailable_classification_requires_exact_type_and_respects_opaque_wrappers() -> None:
    class SlyCaps(caps.CapsUnavailable):
        pass

    assert pi._exception_failure(SlyCaps("spoofed")).unknown
    assert pi._exception_failure(_wrapped(SlyCaps("spoofed"))).unknown

    real = _trigger_seat_scope_failure("two_seat_keys")
    opaque = pi._exception_failure(_opaque(real))
    assert type(opaque) is pi._LegFailure and opaque.unknown
    assert _board_detail(opaque) == UNKNOWN


def test_default_spawn_via_provider_translates_seat_scope_refusal_into_detail_not_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert caps.CODE in getattr(spawned, "seat_notices", ())


def test_invoke_board_outer_seat_scope_refusal_surfaces_typed_detail_and_notice(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    exc = _trigger_seat_scope_failure("two_seat_keys")

    def _boom_scope(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(caps, "_seat_scope", _boom_scope)
    monkeypatch.setattr(
        pi,
        "_default_spawn_via_provider",
        lambda *a, **k: pytest.fail("provider must not run when outer _seat_scope refuses"),
    )
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
    assert any(notice.code == caps.CODE for notice in leg.seat_notices)
    assert any(notice.code == caps.CODE for notice in pi.refused_seat_notices(result.legs))


def test_default_spawn_outer_handler_surfaces_seat_scope_caps_unavailable_for_gemini(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When a nested _seat_scope refusal escapes from Gemini execution, _default_spawn
    classifies it as seat_resource_caps_unavailable rather than an unknown failure."""
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
    assert caps.CODE in getattr(spawned, "seat_notices", ())


@pytest.mark.parametrize("path", ["empty_seat_key", "two_seat_keys", "two_launch_classes"])
def test_jailed_gemini_broker_prepare_seat_scope_refusal_keeps_typed_detail_and_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path, path: str
) -> None:
    spawned, record = _jailed_gemini_spawn(
        monkeypatch,
        tmp_path,
        prepare=_raising(_trigger_seat_scope_failure(path)),
    )
    assert spawned[0] == "DEGRADED"
    assert spawned[1] == ""
    assert _board_detail(spawned[2]) == caps.CODE
    assert caps.CODE in getattr(spawned, "seat_notices", ())
    assert record["refusal"] == caps.CODE


def test_unjailed_gemini_broker_parent_infer_maps_seat_scope_refusal_instead_of_generic_provider_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Regression for agent-harness#1908: inside the brokered Gemini leg handler, a
    _seat_scope CapsUnavailable must surface ``seat_resource_caps_unavailable`` rather
    than falling through to ``Gemini broker local provider failure``."""
    exc = _trigger_seat_scope_failure("two_seat_keys")

    def _boom_exec(*_args, **_kwargs):
        raise exc

    def _prepare_unused(*_args, **_kwargs):
        pytest.fail("_prepare_jailed_gemini should not run on unjailed route")

    # Drive _jailed_gemini_spawn's brokered setup, but override the route to unjailed
    # so execution enters _parent_infer's _exec_leg catch block (panel_invoker.py:20967).
    orig_setattr = monkeypatch.setattr

    def _patched_setattr(target, name, value, raising=True):
        if target is pi and name == "_seat_route_for_spawn":
            value = lambda *a, **k: (_Route(False), [], None)
        orig_setattr(target, name, value, raising=raising)

    monkeypatch.setattr(pi, "_exec_leg", _boom_exec)
    monkeypatch.setattr = _patched_setattr  # type: ignore[method-assign]
    try:
        spawned, record = _jailed_gemini_spawn(
            monkeypatch,
            tmp_path,
            prepare=_prepare_unused,
        )
    finally:
        monkeypatch.setattr = orig_setattr  # type: ignore[method-assign]

    assert spawned[0] == "DEGRADED"
    assert spawned[1] == ""
    assert spawned[2] == caps.CODE
    assert caps.CODE in getattr(spawned, "seat_notices", ())
    assert record["refusal"] == caps.CODE
