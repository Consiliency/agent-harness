"""Offline checks for staged review bundle delivery and admission."""

import json
import logging

import pytest

from harden_tdd_guard import invoke_sanctioned_review_transport
from phase_loop_runtime import cli, panel_invoker as pi
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from president_fakes import deferring_president


@pytest.mark.parametrize("gemini", [False, True])
def test_jailed_pointer_review_reads_the_index_first(gemini):
    prompt = pi._render_broker_pointer_prompt(
        "bundle contents", "review request",
        source_commit="a" * 40, staged_tree_sha256="b" * 64, model_only_network=gemini,
    )
    directives = [prompt]
    if gemini:
        transport = pi._broker_gemini_stream_protocol(prompt, tooled=True).transport
        body = json.loads(transport)["message"]["content"]
        directives.append(body.split("Analyze the input above", 1)[1])
    for text in directives:
        assert "standalone document" in text and "read it in full before judging" in text
        assert "scope/index section" in text
        assert "every changed path and acceptance criterion" in text
        assert "diff hunks, source files, and evidence" in text
        assert "bounded reads" in text
        assert "/seat/tree" in text and "/seat/review/review-bundle.md" in text
        assert "bundle contents" not in text


def test_jailed_review_without_an_index_builds_and_covers_the_path_inventory():
    prompt = pi._render_broker_pointer_prompt(
        "diff --git a/example.py b/example.py", "review request",
        source_commit="a" * 40, staged_tree_sha256="b" * 64,
    )
    fallback = prompt.split("If there is no index,", 1)[1].split("\n", 1)[0]
    assert "build the inventory yourself with bounded reads" in fallback
    assert "`diff --git` headers in the bundle" in fallback
    assert "account for every changed path in it" in fallback


@pytest.mark.parametrize("mode", ["review", "advisory"])
def test_no_tree_route_receives_the_complete_bundle(mode):
    bundle = "first line\nlast line"
    prompt = pi._render_broker_inline_prompt(bundle, pi._mode_instructions(mode), mode)
    assert bundle in prompt
    assert "scope/index section" not in prompt
    assert "Do not use or request tools, commands, files" in prompt
    if mode == "advisory":
        assert "read the staged material in full" in prompt


@pytest.mark.parametrize("characters", [1, 32_768, 32_769])
@pytest.mark.parametrize("board", [False, True])
def test_file_backed_bundle_warning_counts_utf8_bytes_before_launch(tmp_path, caplog, characters, board):
    bundle = tmp_path / "private-review.md"
    contents = "é" * characters
    bundle.write_text(contents, encoding="utf-8")
    expected_size = len(contents.encode("utf-8"))
    seen = []

    def spawn(_leg, artifact, **_kwargs):
        warnings = [r.getMessage() for r in caplog.records if "staged review bundle" in r.getMessage()]
        seen.append(warnings)
        assert artifact == contents
        return "OK", "AGREE"

    with caplog.at_level(logging.WARNING, logger=pi.__name__):
        if board:
            invoke_sanctioned_review_transport(
                DEFAULT_BOARD, "", artifact_ref=str(bundle), spawn=spawn, max_concurrency=1,
                landing_tier="production_code", president_invoke=deferring_president,
            )
        else:
            pi.invoke_panel("", ["codex"], artifact_ref=str(bundle), spawn=spawn)
    assert seen
    if expected_size > 65_536:
        (warning,) = seen[0]
        assert all(warnings == [warning] for warnings in seen)
        assert f"{expected_size} bytes" in warning and "65536" in warning
        assert "short index" in warning and "tree reads" in warning
        assert str(bundle) not in warning and "é" not in warning
    else:
        assert all(not warnings for warnings in seen)


def test_board_hard_limit_refuses_before_spawn(tmp_path):
    bundle = tmp_path / "review.md"
    bundle.write_text("éé", encoding="utf-8")
    seen = []
    result = pi.invoke_board(
        DEFAULT_BOARD, "", artifact_ref=str(bundle), max_staged_bundle_bytes=3,
        spawn=lambda *args: seen.append(args), repo_dir=tmp_path,
    )
    assert not seen
    assert len(result.legs) == len(DEFAULT_BOARD.seats)
    assert all(leg.status == "UNAVAILABLE" for leg in result.legs)
    assert {leg.detail for leg in result.legs} == {"seat_review_bundle_too_large"}
    notices = pi.refused_seat_notices(result.legs)
    assert len(notices) == len(result.legs)
    assert {notice.code for notice in notices} == {"seat_review_bundle_too_large"}


def test_board_cli_parses_the_optional_hard_limit():
    args = cli.build_parser().parse_args([
        "advisor-board", "bundle.md", "--max-staged-bundle-bytes", "16384",
    ])
    assert args.max_staged_bundle_bytes == 16_384
