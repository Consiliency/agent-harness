from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from harden_tdd_guard import invoke_sanctioned_board_control
from president_fakes import deferring_president
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
from phase_loop_runtime.advisor_board.schema import Board, Seat
from phase_loop_runtime.panel_invoker import (
    PresidentPolicyError,
    ReviewLandingTier,
    invoke_board,
    invoke_president,
    review_policy_for_tier,
)
from phase_loop_runtime.plan_pin_lint import find_plan_pin_violations


def _post_switch_repo(repo: Path) -> None:
    path = repo / "plans" / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "plans": [
                    {
                        "slug": "v10-GOVLEAN",
                        "lifecycle": [
                            {
                                "transition": "authority_switch",
                                "by": "codex-execute-phase",
                                "at": "2026-08-15T00:00:00Z",
                                "metadata": {"verification_status": "passed"},
                            }
                        ],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _weak_board() -> Board:
    return Board(
        name="weak",
        purpose="premerge-review",
        seats=(Seat(model="gpt-5.6-sol", effort="max", harness="codex"),),
    )


def _full_board() -> Board:
    # One fleet-default seat per review vendor, taken from the shared canonical
    # fixture rather than restated as literals: this test is about the LANDING
    # POLICY reaching the real invocation path, not about which model each vendor
    # currently ships, and every default-seat model aliases to the same policy
    # seat name (``DEFAULT_REVIEW_SEAT_ALIASES``) a literal board would.
    return Board(
        name="full",
        purpose="premerge-review",
        seats=DEFAULT_SEATS,
    )


def _ok_spawn(leg: str, artifact: str) -> tuple[str, str]:
    return "OK", f"{leg} reviewed {artifact}\nAGREE"


def test_review_tier_rejects_unknown_values() -> None:
    with pytest.raises(PresidentPolicyError) as excinfo:
        review_policy_for_tier("operational")  # type: ignore[arg-type]
    assert excinfo.value.code == "review_landing_tier_unknown"


def test_post_switch_board_requires_a_tier_and_rejects_understrength_board(tmp_path: Path) -> None:
    _post_switch_repo(tmp_path)

    with pytest.raises(PresidentPolicyError) as excinfo:
        invoke_board(_weak_board(), "artifact", repo_dir=tmp_path, spawn=_ok_spawn)
    assert excinfo.value.code == "review_landing_tier_required"

    with pytest.raises(PresidentPolicyError) as excinfo:
        invoke_board(
            _weak_board(),
            "artifact",
            repo_dir=tmp_path,
            spawn=_ok_spawn,
            landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        )
    assert excinfo.value.code == "review_board_policy_mismatch"


def test_post_switch_full_production_board_reaches_the_real_invocation_path(tmp_path: Path) -> None:
    _post_switch_repo(tmp_path)
    # An execution-capable review path needs an explicit sanctioned authorization
    # control (EC-HARDEN-5); the assertion below is unchanged.
    result = invoke_sanctioned_board_control(
        _full_board(),
        "artifact",
        repo_dir=tmp_path,
        spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        president_invoke=deferring_president,
    )
    assert [leg.status for leg in result.legs] == ["OK", "OK", "OK", "OK"]
    assert result.president is not None


def test_president_format_reask_unavailability_descends_the_ladder() -> None:
    calls: list[str] = []

    def invoke(model: str, prompt: str) -> dict[str, str]:
        calls.append(model)
        if model == "fable" and len(calls) == 1:
            return {"status": "ok", "text": "missing terminal grammar"}
        if model == "fable":
            return {"status": "unavailable", "code": "president_unavailable"}
        return {
            "status": "ok",
            "text": "FINDING F1: BLOCKING - repair required\nFORCING DECISION: REJECT",
        }

    ruling = invoke_president(
        findings=("F1: concrete board finding",),
        invoke=invoke,
        max_substantive_rounds=3,
    )

    assert ruling.model == "sol"
    assert calls == ["fable", "fable", "sol"]


@pytest.mark.parametrize(
    "digest_text",
    (
        "sha256: " + "a" * 64,
        "`" + "b" * 64 + "`",
    ),
)
def test_tracked_blob_digest_formatting_cannot_bypass_pin_lint(
    tmp_path: Path, digest_text: str
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    tracked = tmp_path / "src" / "tracked.txt"
    tracked.parent.mkdir()
    tracked.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/tracked.txt"], cwd=tmp_path, check=True)

    findings = find_plan_pin_violations(
        f"Future output `src/tracked.txt` must retain {digest_text}.\n",
        tmp_path,
        tmp_path / "plan.md",
    )

    assert "mutable_tracked_blob_pin" in {finding.category for finding in findings}
