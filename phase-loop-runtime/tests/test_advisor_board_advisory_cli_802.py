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
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from pathlib import Path

import pytest

from phase_loop_runtime import cli
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.advisor_board import backing as backing_mod
from phase_loop_runtime.advisor_board import composition as comp_mod
from phase_loop_runtime.advisor_board.advisory_contract import (
    ADVISORY_CONTRACT,
    ADVISORY_CONTRACT_DIGESTS,
    ADVISORY_CONTRACT_ID,
    AdvisoryLandingRefused,
)
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult

_REAL_COMPOSE = comp_mod.compose_review_board
_REAL_PANEL_COMPOSE = comp_mod.compose_panel_board
_REAL_PREPARE_COMPOSITION = backing_mod.prepare_review_composition_authorization
_REAL_INVOKE_BOARD = pi.invoke_board
_REAL_PREPARE_ISOLATION = backing_mod.prepare_review_isolation_authorization
_REAL_RESOLVE_ARTIFACT = pi._resolve_artifact
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
_XDG_ROOTS: list = []


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
        self.git_env_seen: list[tuple[str, frozenset]] = []
        self.panel_compose_calls: list[dict] = []
        self.board = _hermetic_board()

        def seen(seam: str) -> None:
            self.git_env_seen.append((seam, frozenset(k for k in os.environ if k.startswith("GIT_"))))

        def compose(*args, **kwargs):
            seen("compose")
            self.compose_calls.append((args, kwargs))
            return self.board

        def compose_panel(table, **probes):
            # PANEL SL-1 (agent-harness#1078, amendment #3 grant): a default (code-review)
            # run composes its lanes through build_panel_context -> compose_panel_board. The
            # forced composer seats every vendor, as the node's own full board did.
            seen("compose")
            self.panel_compose_calls.append(probes)
            return _REAL_PANEL_COMPOSE(table, is_available=lambda vendor: vendor in _VENDORS,
                                       auth_ok=lambda vendor: True, preflight=lambda vendor: True)

        def prepare_composition():
            seen("prepare_composition")
            self.composition_authorizations += 1

        real_prepare = backing_mod.prepare_review_isolation_authorization

        def prepare(board, artifact, **kwargs):
            seen("prepare")
            self.prepare_calls.append({"artifact": artifact, **kwargs})
            if real_authorization:
                return real_prepare(board, artifact, **kwargs)
            return object()

        def invoke(board, artifact, **kwargs):
            seen("invoke")
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
        monkeypatch.setattr(comp_mod, "compose_panel_board", compose_panel)
        # A private user-table path, so the host's own advisor-boards.toml cannot change it.
        xdg = tempfile.TemporaryDirectory(prefix="advisory-802-xdg-")
        _XDG_ROOTS.append(xdg)
        monkeypatch.setenv("XDG_CONFIG_HOME", xdg.name)
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
def no_git_env(monkeypatch) -> None:
    """Scrub inherited GIT_* (a pre-commit hook exports GIT_INDEX_FILE, for example)."""
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)


@pytest.fixture
def outside_git(tmp_path, monkeypatch, no_git_env) -> Path:
    """A cwd with no ``.git`` at it or any ancestor (``/tmp`` is not inside a repository)."""
    cwd = tmp_path / "no-repo"
    cwd.mkdir()
    probe = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True)
    if probe.returncode == 0:
        pytest.skip(f"tmp_path is inside a git repository: {probe.stdout.strip()}")
    monkeypatch.chdir(cwd)
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
    # PANEL SL-1 (granted): the no-kwargs pin carries over to the lane composer. The CLI
    # passes no predicate of its own; the builder hands compose_panel_board its default
    # production probes (auth_ok reaches default_board_auth_ok).
    [probes] = run.panel_compose_calls
    assert {name: getattr(probes.get(name), "__qualname__", None)
            for name in ("is_available", "auth_ok", "preflight")} == {
        name: f"_default_probes.<locals>.{name}" for name in ("is_available", "auth_ok", "preflight")}
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
    [prepared] = run.prepare_calls
    assert prepared["stage_review_tree"] is False and prepared["mode"] == "review"
    [invoked] = run.invoke_calls
    # Nothing on the advisory call can put it on a landing path.
    assert not {"landing_tier", "review_policy", "president_invoke", "native_president_fill",
                "stream_dir"} & set(invoked)
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


def test_advisory_run_inside_a_repository_never_uses_it(monkeypatch, bundle, no_git_env):
    """Run from inside a git work tree, ``--advisory`` still mints its authority against the
    private scratch: the caller's repository is neither the authority nor its parent."""
    repo = _repo_root()
    monkeypatch.chdir(repo)
    run = _Run(monkeypatch)
    rc, _out, err = run(["advisor-board", str(bundle), "--advisory", "--json"])
    assert rc == 0, err
    [prepared] = run.prepare_calls
    [invoked] = run.invoke_calls
    authority = Path(invoked["canonical_repo_authority"])
    assert Path(prepared["canonical_repo_authority"]) == authority
    assert authority != repo and repo not in authority.parents
    assert invoked["_authority_tracked"] == ["ADVISORY-AUTHORITY"]


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


_REDIRECTING_GIT_ENV = [
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
    "GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_COUNT",
    "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_CONFIG_PARAMETERS", "GIT_EXEC_PATH",
    "GIT_SOME_FUTURE_VARIABLE",
]
# Inherited in ordinary shells and CI jobs; an advisory run must not refuse them.
_ORDINARY_GIT_ENV = {
    "GIT_OPTIONAL_LOCKS": "0", "GIT_PS1_SHOWDIRTYSTATE": "1", "GIT_EDITOR": "vi", "GIT_PAGER": "less",
    "GIT_COMMIT": "0" * 40, "GIT_BRANCH": "origin/main", "GIT_URL": "https://example.invalid/r.git",
    "GIT_DEPTH": "20", "GIT_STRATEGY": "fetch", "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TRACE": "0",
}


def _assert_git_free_run(run, err, names):
    """The run went ahead; the note names what was ignored; no probe seam saw any GIT_*."""
    assert f"--advisory ignores the inherited {', '.join(sorted(names))} for this run" in err
    assert run.invoke_calls, err
    assert {seam for seam, _env in run.git_env_seen} >= {"prepare_composition", "compose", "prepare", "invoke"}
    assert all(env == frozenset() for _seam, env in run.git_env_seen), run.git_env_seen


@pytest.mark.parametrize("name", _REDIRECTING_GIT_ENV)
def test_advisory_strips_an_inherited_git_redirect_before_any_probe(monkeypatch, bundle, outside_git, name):
    """The HARDEN probes run ``git -C <authority>`` with the process environment, so an
    advisory run removes every GIT_* before the authority is built and restores it after."""
    value = str(_REPO_ROOT / ".git") if name != "GIT_WORK_TREE" else str(_REPO_ROOT)
    monkeypatch.setenv(name, value)
    run = _Run(monkeypatch)
    rc, out, err = run(["advisor-board", str(bundle), "--advisory", "--json"])
    assert rc == 0, err
    _assert_git_free_run(run, err, [name])
    [invoked] = run.invoke_calls
    assert invoked["_authority_tracked"] == ["ADVISORY-AUTHORITY"]
    assert os.environ[name] == value  # restored for the caller
    assert json.loads(out)["gating"] is False


def test_advisory_runs_under_ordinary_shell_and_ci_git_variables(monkeypatch, bundle, outside_git):
    for name, value in _ORDINARY_GIT_ENV.items():
        monkeypatch.setenv(name, value)
    run = _Run(monkeypatch)
    rc, _out, err = run(["advisor-board", str(bundle), "--advisory", "--json"])
    assert rc == 0, err
    _assert_git_free_run(run, err, list(_ORDINARY_GIT_ENV))
    assert {k: os.environ[k] for k in _ORDINARY_GIT_ENV} == _ORDINARY_GIT_ENV


@pytest.mark.parametrize("error", [ValueError("I/O operation on closed file."), BrokenPipeError(32, "Broken pipe")],
                         ids=["closed-stderr", "broken-pipe"])
def test_git_variables_are_restored_when_the_note_cannot_be_written(monkeypatch, bundle, outside_git, error):
    """An in-process caller keeps its GIT_* even when writing the note raises; the error
    propagates exactly as before and nothing is composed."""
    monkeypatch.setenv("GIT_DIR", str(_REPO_ROOT / ".git"))
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "0")

    class _FailingStderr(io.StringIO):
        def write(self, _text):
            raise error

    run = _Run(monkeypatch)
    monkeypatch.setattr(sys, "stderr", _FailingStderr())
    with pytest.raises(type(error)):
        cli.main(["advisor-board", str(bundle), "--advisory", "--json"])
    assert os.environ["GIT_DIR"] == str(_REPO_ROOT / ".git")
    assert os.environ["GIT_OPTIONAL_LOCKS"] == "0"
    assert run.compose_calls == [] and run.invoke_calls == []


def test_advisory_without_git_variables_prints_no_note(monkeypatch, bundle, outside_git):
    rc, _out, err = _Run(monkeypatch)(["advisor-board", str(bundle), "--advisory", "--json"])
    assert rc == 0 and "ignores the inherited" not in err


def test_default_run_keeps_its_git_environment(monkeypatch, bundle, no_git_env):
    """The default (code-review) run uses the caller's repository and is not changed."""
    monkeypatch.chdir(_repo_root())
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "0")
    run = _Run(monkeypatch)
    rc, _out, err = run(["advisor-board", str(bundle), "--json"])
    assert rc == 0 and "ignores the inherited" not in err
    assert all(env == frozenset({"GIT_OPTIONAL_LOCKS"}) for _seam, env in run.git_env_seen)


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
    # A redirect aimed at the caller's repository cannot reach the real authority probes.
    monkeypatch.setenv("GIT_DIR", str(_REPO_ROOT / ".git"))
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
    # The hint checks the platform first; pin Linux so this also holds on a macOS runner.
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    rc, _out, err = run(["advisor-board", str(bundle)])
    assert rc == 2 and run.compose_calls == []
    lines = err.splitlines()
    assert lines[0].startswith("advisor-board: review isolation unavailable: Command '['git', 'rev-parse'")
    assert lines[1].startswith("advisor-board: hint:") and "--advisory" in lines[1]


@pytest.mark.parametrize("advisory", [False, True])
def test_non_linux_refusal_names_the_linux_sandbox(monkeypatch, bundle, no_git_env, advisory):
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


# --- runtime: the advisory contract is never landing evidence, whoever calls ---------------

_TIERS = ("plan", "production_code", "tests_only", "docs_only")
_NOT_LANDING = "advisory_contract_not_landing_evidence"
_ADVISORY_REFUSED = AdvisoryLandingRefused


class _NoEffects:
    """Record the launch-side seams a refused landing must never reach."""

    def __init__(self, monkeypatch) -> None:
        self.effects: list[str] = []

        def resolve_artifact(*args, **kwargs):
            self.effects.append("resolve_artifact")
            return _REAL_RESOLVE_ARTIFACT(*args, **kwargs)

        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization",
                            lambda *a, **k: self.effects.append("authorize"))
        monkeypatch.setattr(pi, "_resolve_artifact", resolve_artifact)

    def spawn(self, *_args, **_kwargs):
        self.effects.append("spawn")
        return "OK", "AGREE"


def _brief(tmp_path, text: str) -> str:
    path = tmp_path / f"brief-{sha256(text.encode()).hexdigest()[:12]}.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _outcome(call):
    try:
        result = call()
    except (pi.PresidentPolicyError, AdvisoryLandingRefused) as exc:
        return ("raised", exc.code)
    return ("result", tuple((leg.status, leg.detail) for leg in result.legs))


_LANDINGS = [(f"tier-{tier}", {"landing_tier": tier}) for tier in _TIERS] + [
    ("review_policy", {"review_policy": pi.review_policy_for_tier("production_code")}),
    ("president_invoke", {"president_invoke": lambda _model, _prompt: {}}),
    ("native_president_fill", {"native_president_fill": {"rung": "fable", "text": "x"}}),
]


@pytest.mark.parametrize("landing", [kw for _id, kw in _LANDINGS], ids=[i for i, _kw in _LANDINGS])
def test_invoke_board_refuses_an_advisory_brief_on_every_landing_path(tmp_path, monkeypatch, landing):
    probe = _NoEffects(monkeypatch)
    with pytest.raises(AdvisoryLandingRefused) as refused:
        _REAL_INVOKE_BOARD(_hermetic_board(), _BUNDLE, brief_ref=_brief(tmp_path, ADVISORY_CONTRACT),
                           spawn=probe.spawn, base_env={}, **landing)
    assert refused.value.code == _NOT_LANDING
    assert probe.effects == []  # refused before the artifact, the authorization or any seat


def test_invoke_board_refuses_an_advisory_native_fill_on_a_landing_path(tmp_path, monkeypatch, bundle, outside_git):
    """The fill binds the contract digest, so its matching brief is the advisory contract,
    which every landing path refuses before the fill is even preflighted."""
    monkeypatch.setenv("CLAUDECODE", "1")
    rc, out, _err = _Run(monkeypatch)(
        ["advisor-board", str(bundle), "--advisory", "--emit-native-request",
         "--native-fill-dir", str(tmp_path / "fills"), "--json"])
    assert rc == 0
    request_dir = Path(json.loads(out)["request_path"]).parent
    (request_dir / pi.NATIVE_FILL_REVIEW_FILE).write_text("advice\n\nAGREE\n", encoding="utf-8")
    fill = pi.load_native_leg_fills(f"claude={request_dir}")
    assert fill.brief_sha256 == sha256(ADVISORY_CONTRACT.encode()).hexdigest()
    probe = _NoEffects(monkeypatch)
    for tier in _TIERS:
        with pytest.raises(AdvisoryLandingRefused) as refused:
            _REAL_INVOKE_BOARD(_hermetic_board(), _BUNDLE, brief_ref=_brief(tmp_path, ADVISORY_CONTRACT),
                               native_leg_fills=(fill,), landing_tier=tier, spawn=probe.spawn,
                               base_env={"CLAUDECODE": "1"})
        assert refused.value.code == _NOT_LANDING
    assert probe.effects == []


@pytest.mark.parametrize("tier", _TIERS)
def test_other_briefs_on_a_landing_path_are_unaffected(tmp_path, monkeypatch, tier):
    """Positive control: with the code-review brief, or a brief one byte off the contract,
    the landing call has exactly the outcome it has with no brief at all."""
    probe = _NoEffects(monkeypatch)

    def run(brief_ref):
        return _outcome(lambda: _REAL_INVOKE_BOARD(
            _hermetic_board(), _BUNDLE, brief_ref=brief_ref, landing_tier=tier, spawn=probe.spawn, base_env={},
        ))

    baseline = run(None)
    assert baseline != ("raised", _NOT_LANDING)
    for text in (_REVIEW_BRIEF, ADVISORY_CONTRACT + " "):
        assert run(_brief(tmp_path, text)) == baseline
    assert run(_brief(tmp_path, ADVISORY_CONTRACT)) == ("raised", _NOT_LANDING)
    assert "spawn" not in probe.effects


def test_a_tierless_advisory_invocation_is_not_refused_as_landing(tmp_path, monkeypatch):
    """The advisory CLI's own call carries no landing kwarg: the runtime check leaves it to
    the existing gates, exactly as a tierless call with no brief."""
    probe = _NoEffects(monkeypatch)

    def run(brief_ref):
        return _outcome(lambda: _REAL_INVOKE_BOARD(
            _hermetic_board(), _BUNDLE, brief_ref=brief_ref, spawn=probe.spawn, base_env={},
        ))

    assert run(_brief(tmp_path, ADVISORY_CONTRACT)) == run(None)
    assert "resolve_artifact" in probe.effects


def test_governed_gate_refuses_an_advisory_brief_before_composition(tmp_path):
    from phase_loop_runtime import governed_review

    calls: list[str] = []

    def compose():
        calls.append("compose")
        raise ValueError("composition stopped by the test")

    def invoke(*_a, **_k):
        calls.append("invoke")
        raise AssertionError("unreachable")

    kwargs = dict(artifact=_BUNDLE, author_executor="claude", run_mode="governed",
                  canonical_repo_authority=_REPO_ROOT, compose=compose, invoke=invoke)
    held = governed_review.governed_board_gate(brief_ref=_brief(tmp_path, ADVISORY_CONTRACT), **kwargs)
    assert held.promoted is False and calls == []
    assert held.reason == "advisory_not_landing_evidence"
    assert [f.code for f in held.findings] == [_NOT_LANDING]
    # Positive control: another brief reaches composition.
    other = governed_review.governed_board_gate(brief_ref=_brief(tmp_path, _REVIEW_BRIEF), **kwargs)
    assert calls == ["compose"] and other.promoted is False
    assert _NOT_LANDING not in [f.code for f in other.findings]


# --- round 2: identity, error type, one read ------------------------------------------------

_ADVISORY_V1_SHA256 = "b74710e890632b1931967be6629cce10f70fc31094297f08c0e2507f7e0203ce"


def test_every_shipped_advisory_contract_digest_is_recognised():
    """Golden: editing ADVISORY_CONTRACT fails here until its new digest is ADDED to
    ADVISORY_CONTRACT_DIGESTS (and this pin moves) -- an older fill or brief stays advisory."""
    assert sha256(ADVISORY_CONTRACT.encode("utf-8")).hexdigest() == _ADVISORY_V1_SHA256
    assert _ADVISORY_V1_SHA256 in ADVISORY_CONTRACT_DIGESTS


def test_an_older_shipped_contract_is_still_refused_on_a_landing(tmp_path, monkeypatch):
    from phase_loop_runtime.advisor_board import advisory_contract

    older = "ADVISORY REVIEW CONTRACT (advisory.v0, a hypothetical earlier text)\n"
    monkeypatch.setattr(advisory_contract, "ADVISORY_CONTRACT_DIGESTS",
                        ADVISORY_CONTRACT_DIGESTS | {sha256(older.encode()).hexdigest()})
    with pytest.raises(AdvisoryLandingRefused):
        _REAL_INVOKE_BOARD(_hermetic_board(), _BUNDLE, brief_ref=_brief(tmp_path, older),
                           landing_tier="production_code", spawn=lambda *_a, **_k: ("OK", "AGREE"), base_env={})


def test_the_refusal_is_not_swallowed_by_a_caller_catching_the_existing_types(tmp_path):
    """A caller that falls back on PresidentPolicyError / ValueError / OSError / RuntimeError
    (a tierless retry, another board) must still see the advisory refusal."""
    assert not issubclass(AdvisoryLandingRefused, (pi.PresidentPolicyError, ValueError, OSError, RuntimeError))
    fell_back = False
    with pytest.raises(AdvisoryLandingRefused):
        try:
            _REAL_INVOKE_BOARD(_hermetic_board(), _BUNDLE, brief_ref=_brief(tmp_path, ADVISORY_CONTRACT),
                               landing_tier="plan", spawn=lambda *_a, **_k: ("OK", "AGREE"), base_env={})
        except (pi.PresidentPolicyError, ValueError, OSError, RuntimeError):
            fell_back = True
    assert fell_back is False


class _SwapAfterCheck:
    """Replace the brief file the moment the landing check has read it."""

    def __init__(self, monkeypatch, path: Path, replacement: str | None) -> None:
        from phase_loop_runtime.advisor_board import advisory_contract

        self.later_reads: list[object] = []
        real_is_advisory = advisory_contract.is_advisory_brief
        real_resolve = pi._resolve_brief
        checked: list[bool] = []

        def is_advisory(text):
            verdict = real_is_advisory(text)
            if not checked:
                checked.append(True)
                path.write_text(replacement, encoding="utf-8") if replacement is not None else None
            return verdict

        def resolve(mode, brief_ref):
            try:
                value = real_resolve(mode, brief_ref)
            except (OSError, ValueError) as exc:
                value = exc
            if checked and brief_ref == str(path):
                self.later_reads.append(value)
            if isinstance(value, BaseException):
                raise value
            return value

        monkeypatch.setattr(advisory_contract, "is_advisory_brief", is_advisory)
        monkeypatch.setattr(pi, "_resolve_brief", resolve)


def test_invoke_board_runs_on_the_brief_it_checked_not_a_replaced_file(tmp_path, monkeypatch):
    # PANEL SL-1 (agent-harness#1078, granted): a plan landing carries a context from
    # build_panel_context, its composed board and its landing policy.
    from test_panel_sl1_contracts import granted_landing_context_mp

    panel_context, panel_kwargs = granted_landing_context_mp(monkeypatch, "plan")
    brief = Path(_brief(tmp_path, _REVIEW_BRIEF))
    swap = _SwapAfterCheck(monkeypatch, brief, ADVISORY_CONTRACT)
    _outcome(lambda: _REAL_INVOKE_BOARD(
        panel_context.composed.board, _BUNDLE, brief_ref=str(brief), landing_tier="plan", **panel_kwargs,
        president_invoke=lambda _m, _p: {}, spawn=lambda *_a, **_k: ("OK", "AGREE"), base_env={},
    ))
    assert brief.read_text(encoding="utf-8") == ADVISORY_CONTRACT  # the file WAS replaced
    assert swap.later_reads, "nothing re-resolved the brief after the check"
    assert all(read == _REVIEW_BRIEF for read in swap.later_reads)


def test_a_brief_unreadable_at_the_check_stays_unreadable_for_the_call(tmp_path, monkeypatch):
    missing = tmp_path / "late-brief.md"
    from phase_loop_runtime.advisor_board import advisory_contract

    seen: list[object] = []
    real_resolve = pi._resolve_brief
    real_pin = pi._pin_landing_brief

    def pin(mode, brief_ref):
        token = real_pin(mode, brief_ref)
        missing.write_text(ADVISORY_CONTRACT, encoding="utf-8")  # appears after the check
        return token

    def resolve(mode, brief_ref):
        try:
            value = real_resolve(mode, brief_ref)
        except (OSError, ValueError) as exc:
            seen.append(exc)
            raise
        seen.append(value)
        return value

    monkeypatch.setattr(pi, "_pin_landing_brief", pin)
    monkeypatch.setattr(pi, "_resolve_brief", resolve)
    assert advisory_contract.is_advisory_brief(ADVISORY_CONTRACT)
    _outcome(lambda: _REAL_INVOKE_BOARD(
        _hermetic_board(), _BUNDLE, brief_ref=str(missing), landing_tier="plan",
        president_invoke=lambda _m, _p: {}, spawn=lambda *_a, **_k: ("OK", "AGREE"), base_env={},
    ))
    assert seen and all(isinstance(value, ValueError) for value in seen)


def test_governed_gate_binds_the_brief_it_checked_not_a_replaced_file(tmp_path, monkeypatch):
    from phase_loop_runtime import governed_review

    brief = Path(_brief(tmp_path, _REVIEW_BRIEF))
    swap = _SwapAfterCheck(monkeypatch, brief, ADVISORY_CONTRACT)
    bound: list[str] = []
    real_bind = backing_mod.set_review_instruction_digest
    monkeypatch.setattr(backing_mod, "set_review_instruction_digest",
                        lambda text: (bound.append(text), real_bind(text))[1])
    monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", lambda *a, **k: object())
    invoked: list[str] = []

    def invoke(board, artifact, **kwargs):
        invoked.append(pi._resolve_brief("review", kwargs["brief_ref"]))
        return _CANNED

    gate = governed_review.governed_board_gate(
        artifact=_BUNDLE, author_executor="claude", run_mode="governed",
        canonical_repo_authority=_REPO_ROOT, brief_ref=str(brief),
        compose=_hermetic_board, invoke=invoke,
    )
    assert brief.read_text(encoding="utf-8") == ADVISORY_CONTRACT
    assert bound == [_REVIEW_BRIEF] and invoked == [_REVIEW_BRIEF], gate
    assert all(read == _REVIEW_BRIEF for read in swap.later_reads)


@_linux_only
def test_an_advisory_fill_with_a_different_brief_is_refused_by_the_digest_preflight(tmp_path, monkeypatch, bundle, outside_git):
    """The other way an advisory fill could reach a landing: under a non-advisory brief. The
    landing check passes (the brief is not advisory) and the invoker's digest preflight refuses
    the fill before any seat."""
    monkeypatch.setenv("CLAUDECODE", "1")
    rc, out, _err = _Run(monkeypatch)(
        ["advisor-board", str(bundle), "--advisory", "--emit-native-request",
         "--native-fill-dir", str(tmp_path / "fills"), "--json"])
    assert rc == 0
    request_dir = Path(json.loads(out)["request_path"]).parent
    (request_dir / pi.NATIVE_FILL_REVIEW_FILE).write_text("advice\n\nAGREE\n", encoding="utf-8")
    fill = pi.load_native_leg_fills(f"claude={request_dir}")
    [claude_seat] = [seat for seat in _hermetic_board().seats if (seat.harness or "") == "claude"]
    from phase_loop_runtime.advisor_board.schema import Board

    grounded = Board(name="grounded", purpose="code-review", seats=(claude_seat,))
    monkeypatch.chdir(_REPO_ROOT)
    # The real HARDEN factory: the fill preflight runs after its lookup and revalidation.
    monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", _REAL_PREPARE_ISOLATION)
    result = _REAL_INVOKE_BOARD(
        grounded, _BUNDLE, brief_ref=_brief(tmp_path, _REVIEW_BRIEF), landing_tier="docs_only",
        native_leg_fills=(fill,), base_env={"CLAUDECODE": "1"},
    )
    details = [leg.detail for leg in result.legs]
    # agent-harness#1102 r9: the refusal code carries the reason only (a seat key is not a
    # closed detail field); the leg itself still carries its seat_key.
    assert details == [f"native_fill_refused:{pi.NATIVE_FILL_DIGEST_MISMATCH}"], details
    assert [leg.seat_key for leg in result.legs] == [claude_seat.seat_key]
