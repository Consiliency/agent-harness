from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

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
    return Board(
        name="full",
        purpose="premerge-review",
        seats=(
            Seat(model="claude-fable-5", effort="max", harness="claude"),
            Seat(model="gpt-5.6-sol", effort="max", harness="codex"),
            Seat(model="gemini-3.6-flash", effort="high", harness="gemini"),
            Seat(model="grok-4.5", effort="max", harness="grok"),
        ),
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
    result = invoke_board(
        _full_board(),
        "artifact",
        repo_dir=tmp_path,
        spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE,
    )
    assert [leg.status for leg in result.legs] == ["OK", "OK", "OK", "OK"]


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
