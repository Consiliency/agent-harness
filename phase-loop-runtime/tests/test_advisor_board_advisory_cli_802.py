"""`phase-loop advisor-board --advisory` (agent-harness#802; agent-harness#1098 items 1 and 3).

An advisory run reviews a standalone document through the SAME HARDEN review operation as the
default board. Only the authoritative instructions (the advisory contract, not the code-review
brief), the authority (a private scratch repository, no staged tree) and the result labels
(advisory, non-gating) differ. These tests pin:

- the flag parses, and the default command without it is unchanged;
- every seat's authoritative instructions are the advisory contract, inside the digest-bound
  frame, with the verdict protocol kept in the sealed preamble;
- an advisory run cannot reach a landing: ``--landing-tier`` / ``--native-president`` are
  refused before any probe, and an advisory native fill is refused by the default review;
- a run from a directory outside any git repository mints and revalidates a REAL authorization
  against the scratch authority, with no staged tree.

Hermetic: composition and ``invoke_board`` are patched, so no vendor CLI is spawned.
"""
from __future__ import annotations

import io
import json
import os
import platform
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from pathlib import Path

import pytest

from phase_loop_runtime import cli
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.advisor_board import backing as backing_mod
from phase_loop_runtime.advisor_board import composition as comp_mod
from phase_loop_runtime.advisor_board.advisory_contract import ADVISORY_CONTRACT, ADVISORY_CONTRACT_ID
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult

_REAL_COMPOSE = comp_mod.compose_review_board
_REAL_PREPARE_COMPOSITION = backing_mod.prepare_review_composition_authorization
_VENDORS = {"codex", "gemini", "claude", "grok"}
_REVIEW_BRIEF = pi._mode_instructions("review")
_DEFAULT_JSON_KEYS = {
    "board", "usable", "requested_seats", "delivered_seats", "shortfall", "independence", "legs",
}
_CANNED = PanelResult(legs=(
    PanelLegResult(leg="grok", status="OK", text="AGREE", seat_key="grok:adversarial"),
    PanelLegResult(leg="codex", status="OK", text="PARTIALLY AGREE", seat_key="codex:red-team"),
    PanelLegResult(leg="gemini", status="OK", text="AGREE", seat_key="gemini:alt"),
    PanelLegResult(leg="claude", status="UNAVAILABLE", text="", detail="deferred", seat_key="claude:corr"),
))
_BUNDLE = (
    "# Research bundle\n\n## Panel charter\nGive your recommendation, attack the provisional "
    "recommendation (option B), rank options A-C, end with AGREE/PARTIALLY AGREE/DISAGREE.\n"
)
_linux_only = pytest.mark.skipif(platform.system() != "Linux", reason="HARDEN review isolation is Linux-only")


_BOARD_CACHE: list = []


def _hermetic_board():
    # Composed once, before any test patches the composition authorization seam.
    if not _BOARD_CACHE:
        _BOARD_CACHE.append(_REAL_COMPOSE(is_available=lambda vendor: vendor in _VENDORS))
    return _BOARD_CACHE[0]


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _repo_root() -> Path:
    return Path(subprocess.check_output(
        ["git", "-C", str(_REPO_ROOT), "rev-parse", "--show-toplevel"], text=True,
    ).strip()).resolve()


class _Run:
    """Drive ``advisor-board`` with composition and dispatch patched; record what they saw."""

    def __init__(self, monkeypatch, *, real_authorization: bool = False) -> None:
        self.compose_calls: list[tuple] = []
        self.composition_authorizations = 0
        self.prepare_calls: list[dict] = []
        self.invoke_calls: list[dict] = []
        self.board = _hermetic_board()

        def compose(*args, **kwargs):
            self.compose_calls.append((args, kwargs))
            return self.board

        def prepare_composition():
            self.composition_authorizations += 1

        real_prepare = backing_mod.prepare_review_isolation_authorization

        def prepare(board, artifact, **kwargs):
            self.prepare_calls.append({"artifact": artifact, **kwargs})
            if real_authorization:
                return real_prepare(board, artifact, **kwargs)
            return object()

        def invoke(board, artifact, **kwargs):
            kwargs = dict(kwargs)
            kwargs["_brief_text"] = (
                Path(kwargs["brief_ref"]).read_text(encoding="utf-8") if kwargs.get("brief_ref") else None
            )
            kwargs["_authority_tracked"] = subprocess.check_output(
                ["git", "-C", str(kwargs["canonical_repo_authority"]), "ls-files"], text=True,
            ).split() if kwargs.get("canonical_repo_authority") else None
            if real_authorization:
                # The bound authorization revalidates for this exact board, bundle, authority
                # and (via the live digest) instructions -- what the invoker checks first.
                backing_mod.revalidate_review_isolation_authorization(
                    kwargs["review_authorization"], board, artifact, mode="review",
                    canonical_repo_authority=kwargs["canonical_repo_authority"],
                )
                kwargs["_bound"] = kwargs["review_authorization"]
            self.invoke_calls.append(kwargs)
            return _CANNED

        monkeypatch.setattr(comp_mod, "compose_review_board", compose)
        monkeypatch.setattr(backing_mod, "prepare_review_composition_authorization", prepare_composition)
        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", prepare)
        monkeypatch.setattr(pi, "invoke_board", invoke)

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()


@pytest.fixture
def bundle(tmp_path) -> Path:
    path = tmp_path / "bundle.md"
    path.write_text(_BUNDLE, encoding="utf-8")
    return path


@pytest.fixture
def outside_git(tmp_path, monkeypatch) -> Path:
    """A cwd with no ``.git`` at it or any ancestor (``/tmp`` is not inside a repository)."""
    cwd = tmp_path / "no-repo"
    cwd.mkdir()
    probe = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True)
    if probe.returncode == 0:
        pytest.skip(f"tmp_path is inside a git repository: {probe.stdout.strip()}")
    monkeypatch.chdir(cwd)
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)
    return cwd


# --- flag parsing --------------------------------------------------------------------------


def test_advisory_flag_parses_and_defaults_off():
    parser = cli.build_parser()
    assert parser.parse_args(["advisor-board", "b.md"]).advisory is False
    assert parser.parse_args(["advisor-board", "b.md", "--advisory"]).advisory is True
    # It does not disturb the flags it composes with.
    args = parser.parse_args(["advisor-board", "b.md", "--advisory", "--json", "--monitoring-policy", "heartbeat_only"])
    assert (args.advisory, args.json, args.monitoring_policy) == (True, True, "heartbeat_only")


# --- default path unchanged ----------------------------------------------------------------


def test_default_run_is_unchanged_by_the_advisory_seam(monkeypatch, bundle):
    monkeypatch.chdir(_repo_root())
    run = _Run(monkeypatch)
    captured_digests: list[str] = []
    real_set = backing_mod.set_review_instruction_digest
    monkeypatch.setattr(backing_mod, "set_review_instruction_digest",
                        lambda text: (captured_digests.append(text), real_set(text))[1])

    rc, out, _err = run(["advisor-board", str(bundle), "--json"])

    assert rc == 0
    assert run.compose_calls == [((), {})]  # the no-kwargs auth-aware production composer
    [prepared] = run.prepare_calls
    assert set(prepared) == {"artifact", "mode", "canonical_repo_authority"}  # no stage_review_tree
    assert Path(prepared["canonical_repo_authority"]) == _repo_root()
    [invoked] = run.invoke_calls
    assert "brief_ref" not in invoked and invoked["_brief_text"] is None
    assert Path(invoked["canonical_repo_authority"]) == _repo_root()
    assert captured_digests == [_REVIEW_BRIEF]
    payload = json.loads(out)
    assert set(payload) == _DEFAULT_JSON_KEYS
    assert payload["board"] == run.board.name == "code-review"


def test_default_text_output_is_unchanged(monkeypatch, bundle):
    monkeypatch.chdir(_repo_root())
    rc, out, _err = _Run(monkeypatch)(["advisor-board", str(bundle)])
    assert rc == 0
    assert out.splitlines()[0].startswith("advisor-board: code-review — independence=")
    assert "advisory (non-gating" not in out


# --- the advisory contract reaches every seat ----------------------------------------------


def test_advisory_run_stages_the_contract_as_the_board_brief(monkeypatch, bundle, outside_git):
    run = _Run(monkeypatch)
    rc, out, _err = run(["advisor-board", str(bundle), "--advisory", "--json"])

    assert rc == 0
    [invoked] = run.invoke_calls
    # One brief for the whole board: every seat's review-instructions.md is this file.
    assert invoked["_brief_text"] == ADVISORY_CONTRACT
    assert Path(invoked["artifact_ref"]) == bundle.resolve()
    # The bundle is material, never the brief.
    assert "Panel charter" not in ADVISORY_CONTRACT and invoked["_brief_text"] != _BUNDLE
    payload = json.loads(out)
    assert payload["board"] == "advisory" and payload["composed_board"] == run.board.name
    assert payload["mode"] == "advisory" and payload["gating"] is False
    assert payload["contract"] == {"id": ADVISORY_CONTRACT_ID,
                                   "sha256": sha256(ADVISORY_CONTRACT.encode()).hexdigest()}
    assert set(payload) == _DEFAULT_JSON_KEYS | {"composed_board", "mode", "gating", "contract"}


def test_advisory_text_output_is_labelled_non_gating(monkeypatch, bundle, outside_git):
    rc, out, _err = _Run(monkeypatch)(["advisor-board", str(bundle), "--advisory"])
    assert rc == 0
    assert out.splitlines()[0].startswith("advisor-board: advisory (non-gating; composed from code-review)")


def test_the_seat_prompt_frames_the_contract_as_its_authoritative_instructions(tmp_path):
    """The invoker stages ONE ``review-instructions.md`` per board, from
    ``_resolve_brief("review", brief_ref)``, and every brokered seat's prompt is rendered from
    it and the staged bundle by ``_render_broker_inline_prompt`` (the harness does not enter
    the rendering), so one rendering covers every seat. The contract must sit inside the
    digest-bound AUTHORITATIVE-INSTRUCTIONS frame and the bundle (with its charter) inside the
    UNTRUSTED frame; the code-review brief is absent and the sealed preamble keeps the
    verdict protocol."""
    brief = tmp_path / "advisory-contract.md"
    brief.write_text(ADVISORY_CONTRACT, encoding="utf-8")
    instructions = pi._resolve_brief("review", str(brief))
    assert instructions == ADVISORY_CONTRACT
    prompt = pi._render_broker_inline_prompt(_BUNDLE, instructions, "review")

    frame_begin = prompt.index("AUTHORITATIVE-INSTRUCTIONS sha256=")
    bundle_begin = prompt.index("UNTRUSTED-REVIEW-BUNDLE sha256=")
    authoritative, untrusted = prompt[frame_begin:bundle_begin], prompt[bundle_begin:]
    assert ADVISORY_CONTRACT in authoritative and "Panel charter" not in authoritative
    assert "Panel charter" in untrusted and ADVISORY_CONTRACT not in untrusted
    assert sha256(ADVISORY_CONTRACT.encode()).hexdigest() in authoritative
    # The code-review brief is gone; the verdict protocol stays in the preamble.
    assert _REVIEW_BRIEF not in prompt
    assert "End with exactly one terminal verdict: AGREE, PARTIALLY AGREE, or DISAGREE." in prompt[:frame_begin]


def test_native_fill_request_carries_the_contract(tmp_path, monkeypatch, bundle, outside_git):
    monkeypatch.setenv("CLAUDECODE", "1")
    fill_dir = tmp_path / "fills"
    rc, out, _err = _Run(monkeypatch)(
        ["advisor-board", str(bundle), "--advisory", "--emit-native-request",
         "--native-fill-dir", str(fill_dir), "--json"])
    assert rc == 0
    record = json.loads(out)
    assert record["mode"] == "advisory" and record["gating"] is False
    assert Path(record["instructions_path"]).read_text(encoding="utf-8") == ADVISORY_CONTRACT
    request = json.loads(Path(record["request_path"]).read_text(encoding="utf-8"))
    assert request["brief_sha256"] == sha256(ADVISORY_CONTRACT.encode()).hexdigest()


# --- non-gating: an advisory run can never reach a landing ---------------------------------


@pytest.mark.parametrize("name", ["GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"])
def test_advisory_refuses_an_inherited_git_redirect_before_any_probe(monkeypatch, bundle, outside_git, name):
    """``GIT_DIR`` and friends override ``git -C``: the HARDEN probes would resolve the private
    authority to another repository, so the run is refused before it starts."""
    monkeypatch.setenv(name, str(_REPO_ROOT / ".git") if name != "GIT_WORK_TREE" else str(_REPO_ROOT))
    run = _Run(monkeypatch)
    rc, out, err = run(["advisor-board", str(bundle), "--advisory", "--json"])
    assert rc == 2 and out == ""
    assert f"--advisory cannot run with {name} set" in err
    assert run.compose_calls == [] and run.composition_authorizations == 0 and run.invoke_calls == []


def test_advisory_refuses_agy_canary_capture(monkeypatch, bundle, outside_git):
    """Capture is a governed exact-four run; an advisory run never produces capture evidence."""
    from phase_loop_runtime import agy_canary_evidence

    closed: list[bool] = []

    class _Capture:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(agy_canary_evidence, "consume_capture_environment", lambda: _Capture())
    run = _Run(monkeypatch)
    rc, out, err = run(["advisor-board", str(bundle), "--advisory", "--json",
                        "--agy-canary-private-board-name", "board.json"])
    assert rc == 2 and out == ""
    assert "cannot be --advisory" in err and closed == [True]
    assert run.compose_calls == [] and run.invoke_calls == []


@pytest.mark.parametrize("extra", [["--landing-tier", "plan"], ["--landing-tier", "production_code"],
                                   ["--landing-tier", "docs_only"], ["--native-president", "fill.json"]])
def test_advisory_refuses_landing_flags_before_any_probe(monkeypatch, bundle, extra):
    run = _Run(monkeypatch)
    rc, out, err = run(["advisor-board", str(bundle), "--advisory", *extra, "--json"])
    assert rc == 2 and out == ""
    assert "--advisory is non-gating" in err
    assert run.compose_calls == [] and run.composition_authorizations == 0
    assert run.prepare_calls == [] and run.invoke_calls == []


def test_advisory_native_fill_is_refused_by_the_default_review(tmp_path, monkeypatch, bundle, outside_git):
    """A fill written for an advisory request cannot be counted by a default (code-review)
    run: the fill binds the contract digest, the default preflight binds the review brief."""
    monkeypatch.setenv("CLAUDECODE", "1")
    fill_dir = tmp_path / "fills"
    rc, out, _err = _Run(monkeypatch)(
        ["advisor-board", str(bundle), "--advisory", "--emit-native-request",
         "--native-fill-dir", str(fill_dir), "--json"])
    assert rc == 0
    request_dir = Path(json.loads(out)["request_path"]).parent
    (request_dir / pi.NATIVE_FILL_REVIEW_FILE).write_text("advice\n\nAGREE\n", encoding="utf-8")

    monkeypatch.chdir(_repo_root())
    run = _Run(monkeypatch)
    rc, _out, err = run(["advisor-board", str(bundle), "--native-leg", f"claude={request_dir}", "--json"])
    assert rc == 2
    assert f"[{pi.NATIVE_FILL_DIGEST_MISMATCH}]" in err
    assert run.prepare_calls == [] and run.invoke_calls == []

    # Positive control: the same fill IS accepted by an advisory run.
    monkeypatch.chdir(outside_git)
    run = _Run(monkeypatch)
    rc, _out, err = run(["advisor-board", str(bundle), "--advisory", "--native-leg", f"claude={request_dir}", "--json"])
    assert rc == 0, err
    assert run.invoke_calls and run.invoke_calls[0].get("native_leg_fills")


# --- no repository needed; nothing of the caller's is exposed ------------------------------


@_linux_only
def test_advisory_run_outside_any_repository_mints_a_real_no_tree_authorization(monkeypatch, bundle, outside_git):
    run = _Run(monkeypatch, real_authorization=True)
    rc, out, err = run(["advisor-board", str(bundle), "--advisory", "--json"])
    assert rc == 0, err

    [prepared] = run.prepare_calls
    assert prepared["stage_review_tree"] is False
    [invoked] = run.invoke_calls
    authority = Path(invoked["canonical_repo_authority"])
    assert authority != outside_git and outside_git not in authority.parents
    assert invoked["_authority_tracked"] == ["ADVISORY-AUTHORITY"]
    bound = invoked["_bound"]
    assert bound.staged_tree_sha256 is None  # no tree: seats get only the two framed files
    assert bound.instructions_sha256 == sha256(ADVISORY_CONTRACT.encode()).hexdigest()
    assert bound.input_sha256 == sha256(_BUNDLE.encode()).hexdigest()
    # The scratch authority does not outlive the command.
    assert not authority.exists()
    assert json.loads(out)["gating"] is False


@_linux_only
def test_advisory_authorization_refuses_the_code_review_brief(tmp_path, monkeypatch):
    """The minted authorization is bound to the contract: a stage whose instructions are
    the code-review brief (or anything else) fails revalidation."""
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)
    root = tmp_path / "scratch"
    root.mkdir()
    authority = cli._advisory_review_authority(root)
    board = _hermetic_board()
    token = backing_mod.set_review_instruction_digest(ADVISORY_CONTRACT)
    try:
        authorization = backing_mod.prepare_review_isolation_authorization(
            board, _BUNDLE, mode="review", canonical_repo_authority=authority, stage_review_tree=False,
        )
        for brief, ok in ((ADVISORY_CONTRACT, True), (_REVIEW_BRIEF, False)):
            stage = tmp_path / f"stage-{ok}"
            stage.mkdir()
            (stage / "review-bundle.md").write_text(_BUNDLE, encoding="utf-8")
            (stage / "review-instructions.md").write_text(brief, encoding="utf-8")
            for name in ("review-bundle.md", "review-instructions.md"):
                (stage / name).chmod(0o400)
            check = lambda: backing_mod.revalidate_review_isolation_authorization(  # noqa: E731
                authorization, board, _BUNDLE, mode="review", staged_dir=stage,
                canonical_repo_authority=authority,
            )
            if ok:
                check()
            else:
                with pytest.raises(ValueError, match="staged input does not match"):
                    check()
    finally:
        backing_mod.reset_review_instruction_digest(token)


# --- actionable refusals (agent-harness#1098 item 1) ---------------------------------------


def test_default_run_outside_a_repository_keeps_its_refusal_and_adds_a_hint(monkeypatch, bundle, outside_git):
    run = _Run(monkeypatch)
    rc, _out, err = run(["advisor-board", str(bundle)])
    assert rc == 2 and run.compose_calls == []
    lines = err.splitlines()
    assert lines[0].startswith("advisor-board: review isolation unavailable: Command '['git', 'rev-parse'")
    assert lines[1].startswith("advisor-board: hint:") and "--advisory" in lines[1]


@pytest.mark.parametrize("advisory", [False, True])
def test_non_linux_refusal_names_the_linux_sandbox(monkeypatch, bundle, advisory):
    monkeypatch.chdir(_repo_root())
    run = _Run(monkeypatch)
    # The real pre-composition gate, not the recording stub, on a non-Linux host.
    monkeypatch.setattr(backing_mod, "prepare_review_composition_authorization", _REAL_PREPARE_COMPOSITION)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    rc, _out, err = run(["advisor-board", str(bundle), *(["--advisory"] if advisory else [])])
    assert rc == 2 and run.compose_calls == []
    lines = err.splitlines()
    assert lines[0] == "advisor-board: review isolation unavailable: HARDEN review composition requires Linux"
    assert lines[1].startswith("advisor-board: hint:") and "Linux review sandbox" in lines[1]
