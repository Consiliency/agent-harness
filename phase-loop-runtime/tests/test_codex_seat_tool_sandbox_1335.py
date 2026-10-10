"""agent-harness#1335: a codex seat whose command sandbox cannot start is DEGRADED.

codex runs each command inside its own bubblewrap sandbox. Where that sandbox cannot start in
the seat's view, every command the seat tries fails before it runs. codex still exits 0 and
writes a last message ending in a verdict, so the leg was ``OK`` and counted toward the
reviewer floor although it read nothing.

What these tests pin: before a codex seat that has a shell is run, the runtime probes the
capability itself -- ``codex sandbox ... -- true`` through the same seat-launch owner, with
the same working tree and sandbox mode, no model call. A failed probe that prints the
launcher's own diagnostic ends the leg ``DEGRADED`` with a typed notice, empty text, and it
is not a usable review anywhere. Every other probe outcome is inconclusive and the seat runs
exactly as before.

``fixtures/codex_seat_tools_1335/healthy.stderr`` is a real session transcript of codex-cli
0.162.1 (a two-command prompt, run directly, outside any seat) that the stand-in CLIs below
replay; its working directory (``{CWD}``), session id and file-owner names are placeholders.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import textwrap
import time
import types
import unittest.mock
from pathlib import Path

import pytest

from phase_loop_runtime import governed_review as gr
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail

FIXTURES = Path(__file__).parent / "fixtures" / "codex_seat_tools_1335"
CODE = "seat_tool_sandbox_unavailable"

#: bubblewrap 0.11.1 on an affected host, captured there from a nested bwrap. bubblewrap 0.6
#: words it "create new namespace"; the two differ, which is why nothing keys on the sentence.
TEAM_HOST_BWRAP_LINE = (
    "bwrap: No permissions to create a new namespace, likely because the kernel does not allow "
    "non-privileged user namespaces. See <https://deb.li/bubblewrap> or "
    "<file:///usr/share/doc/bubblewrap/README.Debian.gz>."
)


def _transcript(name: str, cwd: str) -> str:
    return (FIXTURES / f"{name}.stderr").read_text(encoding="utf-8").replace("{CWD}", cwd)


def _last(name: str) -> str:
    return (FIXTURES / f"{name}.last").read_text(encoding="utf-8")


def _evidence():
    from phase_loop_runtime import seat_tool_evidence

    return seat_tool_evidence


# --------------------------------------------------------------------------------------
# A replaced process runner: the seat is never probed, and its outcome is its own.
# --------------------------------------------------------------------------------------

class _Proc:
    def __init__(self, stderr: str, stdout: str = "", returncode: int = 0):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _exec_codex(monkeypatch, tmp_path, name: str, *, returncode: int = 0):
    """The unbrokered codex route of ``_exec_leg``: its real argv, its real output file, and a
    fake process that prints the transcript against the ``--cd`` it was actually given."""
    review_dir, out_dir = tmp_path / "review", tmp_path / "out"
    review_dir.mkdir()
    out_dir.mkdir()
    (review_dir / "review-bundle.md").write_text("x", encoding="utf-8")
    seen: list[list[str]] = []

    def fake(cmd, **kw):
        seen.append(list(cmd))
        assert "exec" in cmd, f"a replaced process runner was asked to answer a probe: {cmd!r}"
        cwd = cmd[cmd.index("--cd") + 1]
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(_last(name), encoding="utf-8")
        transcript = _transcript(name, cwd)
        head, _user, rest = transcript.partition("\nuser\n")
        return _Proc(head + "\nuser\n" + kw["input_text"] + "\n" + rest[rest.index("\ncodex\n"):],
                     stdout=_last(name), returncode=returncode)

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda leg, env: (True, ""))
    result = pi._exec_leg("codex", review_dir, out_dir, timeout_s=60, artifact="A", env={})
    assert seen and all(cmd[0] == "codex" and cmd[cmd.index("--cd") + 1] == str(review_dir)
                        for cmd in seen)
    return result


def test_exec_leg_leaves_a_working_seat_alone(monkeypatch, tmp_path):
    rc, text, log = _exec_codex(monkeypatch, tmp_path, "healthy")
    assert (rc, text) == (0, _last("healthy"))
    assert type(log) is not pi._HarnessCode
    assert pi._classify_leg(rc, text, log) == "OK"


def test_exec_leg_does_not_relabel_a_leg_that_already_failed(monkeypatch, tmp_path):
    """A non-zero exit keeps its own label (a usage limit, a crash)."""
    rc, _text, log = _exec_codex(monkeypatch, tmp_path, "healthy", returncode=1)
    assert rc == 1 and type(log) is not pi._HarnessCode


# --------------------------------------------------------------------------------------
# The production brokered route, with a real process inside the seat-launch owner.
# --------------------------------------------------------------------------------------

class _FakeBroker:
    """Only the transport is faked: the REAL ``_parent_infer`` closure runs in-process."""

    invoked = 0

    def __init__(self, *_a, **_k):
        self.evidence: dict[str, object] = {}

    def run_credentialless_client(self, adapter, *, deadline_s, cancel_event=None):
        type(self).invoked += 1
        status, text = adapter.invoke()
        return {"schema": "parent_unix_broker_v1", "status": status, "text": text}, {"fake": True}

    def close(self):
        return None


_STAND_IN_CODEX = """
    import sys
    prompt = sys.stdin.read()
    cwd = sys.argv[sys.argv.index("--cd") + 1]
    transcript = {transcript!r}.replace("{{CWD}}", cwd)
    head, _user, rest = transcript.partition("\\nuser\\n")
    sys.stderr.write(head + "\\nuser\\n" + prompt + "\\n" + rest[rest.index("\\ncodex\\n"):])
    last = {last!r}
    sys.stdout.write(last)
    open(sys.argv[sys.argv.index("--output-last-message") + 1], "w").write(last)
"""


def _brokered_codex(monkeypatch, tmp_path, name: str):
    """``_default_spawn``'s brokered branch with a stand-in codex PROCESS: ``_parent_infer``,
    ``_exec_leg``, ``_run_leg_with_liveness`` and the seat-launch owner are production."""
    assert not pi._has_injected_review_execution_seam(leg="codex")
    monkeypatch.setattr(pi, "ParentUnixBroker", _FakeBroker)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(pi, "derive_review_leg_authorization",
                        lambda *a, **k: types.SimpleNamespace(expires_monotonic_ns=time.monotonic_ns() + 10**12))
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda _p: tmp_path)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda leg, env: (True, ""))
    monkeypatch.setattr(pi, "_record_broker_provider_evidence", lambda *a, **k: None)
    script = textwrap.dedent(_STAND_IN_CODEX.format(
        transcript=(FIXTURES / f"{name}.stderr").read_text(encoding="utf-8"), last=_last(name)))

    def fake_command(*, out_dir, out_file, **_kw):
        # As on the sandbox route, the seat's `--cd` is NOT the process cwd (`out_dir`).
        return ["/usr/bin/python3", "-c", script, "--cd", str(out_dir.parent / "review"),
                "--output-last-message", str(out_file)]

    monkeypatch.setattr(pi, "_brokered_codex_command", fake_command)
    monkeypatch.setattr(_FakeBroker, "invoked", 0)
    spawned = pi._default_spawn(
        "codex", "ARTIFACT", mode="review", model="gpt-test",
        review_authorization=types.SimpleNamespace(staged_tree_sha256=None),
        canonical_repo_authority=tmp_path,
    )
    assert _FakeBroker.invoked == 1, f"the brokered branch never ran: {spawned!r}"
    return spawned


def _leg_from(spawned, seat_key: str = "codex:red-team") -> pi.PanelLegResult:
    """What ``invoke_board`` stores for a spawned seat (its own normalization, in brief)."""
    status, text, *rest = spawned
    leg = pi.PanelLegResult(leg="codex", status=status, text=text, seat_key=seat_key,
                            detail=pi._resolve_leg_detail(rest[0] if rest else None, None, seat_key))
    return pi.attach_seat_notices(leg, getattr(spawned, "seat_notices", ()))


def test_brokered_codex_with_working_tools_stays_ok(monkeypatch, tmp_path, owned_review_network):
    spawned = _brokered_codex(monkeypatch, tmp_path, "healthy")
    assert tuple(spawned) == ("OK", _last("healthy"))


# --------------------------------------------------------------------------------------
# The joins: the floor, the president's input, the governed gate, the notice.
# --------------------------------------------------------------------------------------

def _degraded_leg() -> pi.PanelLegResult:
    """The leg a dead probe produces. The probe path returns ``(1, "", _HarnessCode(CODE))``
    from ``_exec_leg`` (the owner-gated tests below show it does); from there this follows
    the production classification and normalisation, so the joins are covered without an
    owner."""
    rc, text, log = 1, "", pi._HarnessCode(CODE)
    status = pi._classify_leg(rc, text, log)
    return _leg_from((status, text, pi._leg_failure_detail(status, rc, text, log)))


def test_the_degraded_seat_is_not_a_usable_review_anywhere(monkeypatch, tmp_path):
    leg = _degraded_leg()
    ok = pi.PanelLegResult(leg="grok", status="OK", text="Fine.\n\nAGREE", seat_key="grok:a")
    panel = pi.PanelResult(legs=(leg, ok))
    assert leg.status == "DEGRADED" and leg.detail == CODE and not leg.usable
    assert panel.usable_legs == (ok,) and panel.grounded_usable_legs == (ok,)
    seats = [types.SimpleNamespace(seat_key=item.seat_key) for item in panel.legs]
    assert pi.president_findings_from_legs(seats, panel.legs) == (
        "F001: [codex:red-team] unusable (DEGRADED)", "F002: [grok:a] Fine.")


def test_the_degraded_seat_is_an_operational_warning_not_a_nonconforming_review(monkeypatch,
                                                                                tmp_path):
    """Empty text: the governed gate reads a seat that could not run (WARN), not a review that
    broke the verdict contract (a promotion BLOCK)."""
    findings = gr._findings_from_panel(pi.PanelResult(legs=(_degraded_leg(),)))
    assert [(f.code, f.severity) for f in findings if f.code.startswith("panel_")] == [
        ("panel_leg_degraded", "warn")]


def test_the_notice_says_what_happened_and_how_to_fix_it(monkeypatch, tmp_path):
    leg = _degraded_leg()
    assert [n.code for n in leg.seat_notices] == [CODE]
    what, why, fix = seat_jail.NOTICES[CODE]
    assert "not counted" in what and "command sandbox" in why and fix
    assert "\n" not in fix, "a one-line fix"


def test_the_board_output_names_the_degraded_seat(monkeypatch, tmp_path):
    """Both CLI surfaces: the JSON payload and the text summary."""
    import phase_loop_runtime.advisor_board.composition as comp_mod
    from phase_loop_runtime.cli import main as cli_main

    leg = _degraded_leg()
    artifact = tmp_path / "artifact.md"
    artifact.write_text("x", encoding="utf-8")
    real_compose = comp_mod.compose_review_board
    outputs = {}
    for json_out in (True, False):
        out, err = io.StringIO(), io.StringIO()
        with (
            unittest.mock.patch.object(
                comp_mod, "compose_review_board",
                side_effect=lambda *a, **k: real_compose(
                    is_available=lambda v: v in {"codex", "gemini", "claude", "grok"})),
            unittest.mock.patch.object(pi, "invoke_board", return_value=pi.PanelResult(legs=(leg,))),
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err),
        ):
            cli_main(["advisor-board", *(["--json"] if json_out else []), str(artifact)])
        outputs[json_out] = out.getvalue()
    payload = json.loads(outputs[True])
    assert [(item["status"], item["detail"]) for item in payload["legs"]] == [("DEGRADED", CODE)]
    assert [n["code"] for n in payload["notices"]] == [CODE]
    assert outputs[False].count(f"notice {CODE}:") == 1, outputs[False]


def test_the_code_is_in_the_closed_vocabularies():
    assert CODE in seat_jail.NOTICE_CODES and CODE in pi._HARNESS_DETAIL_CODES
    assert _evidence().TOOL_SANDBOX_UNAVAILABLE == CODE
    assert CODE not in seat_jail.SEALED_FALLBACK_CODES, "a seat is never rerun toolless"


def test_cli_text_naming_the_code_never_degrades_a_leg():
    """Provenance by type: only the runtime's own code carries the label."""
    assert pi._leg_failure_kind(0, "", CODE) == "unknown"
    assert pi._classify_leg(0, f"{CODE}\n\nAGREE", f"codex\n{CODE}\n") == "OK"


# --------------------------------------------------------------------------------------
# The pre-run capability probe: can codex's command sandbox start in THIS seat's view?
# --------------------------------------------------------------------------------------

def _staged_review(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A review dir holding a real staged tree (the marker `stage_review_tree` writes)."""
    from phase_loop_runtime import review_stage

    review_dir, out_dir = tmp_path / "review", tmp_path / "out"
    tree = review_dir / review_stage.REVIEW_STAGE_TREE_DIRNAME
    tree.mkdir(parents=True)
    out_dir.mkdir()
    (review_dir / "review-bundle.md").write_text("bundle", encoding="utf-8")
    (review_dir / "review-instructions.md").write_text("instructions", encoding="utf-8")
    (tree / "hello.txt").write_text("hello from the staged tree\n", encoding="utf-8")

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(tree), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "stage")
    (tree / ".git" / "phase-loop-source-commit").write_text(git("rev-parse", "HEAD") + "\n",
                                                            encoding="utf-8")
    return review_dir, out_dir, tree


def test_the_probe_argv_mirrors_the_launch(tmp_path):
    """Same tree, same sandbox mode, same workspace-write settings: codex's own subcommand for
    running one command in its sandbox, with `true` as the command."""
    _review_dir, out_dir, tree = _staged_review(tmp_path)
    launch = pi._brokered_codex_command(
        model="gpt-test", out_dir=out_dir, out_file=out_dir / "panel-codex.txt",
        codex_effort_args=("-c", "model_reasoning_effort=high"), staged_tree=tree)
    assert pi._codex_sandbox_probe_command(launch) == [
        "codex", "sandbox", "--permission-profile", ":workspace", "--cd", str(tree),
        "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
        "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true", "--", "true"]
    read_only = ["codex", "exec", "--cd", "/r", "--skip-git-repo-check", "--sandbox", "read-only",
                 "--model", "m", "-c", "model_reasoning_effort=high", "--output-last-message", "/o", "-"]
    assert pi._codex_sandbox_probe_command(read_only) == [
        "codex", "sandbox", "--permission-profile", ":read-only", "--cd", "/r", "--", "true"]


@pytest.mark.parametrize("argv", [
    ["codex", "exec", "--cd", "/r", "--sandbox", "danger-full-access", "-"],   # nothing to probe
    ["codex", "exec", "--sandbox", "read-only", "-"],                           # no tree named
    ["codex", "exec", "--cd", "/r", "-"],                                       # no sandbox named
    ["/usr/bin/python3", "-c", "pass", "--cd", "/r", "--sandbox", "read-only"],  # not codex
])
def test_no_probe_is_built_for_an_argv_it_would_not_mirror(argv):
    assert pi._codex_sandbox_probe_command(argv) is None


_STAND_IN_CODEX_CLI = """#!/usr/bin/python3
import os, sys, time
args = sys.argv[1:]
if "login" in args:
    sys.exit(0)
if args and args[0] == "sandbox":
    behaviour = {behaviour!r}
    tree = args[args.index("--cd") + 1]
    profile = args[args.index("--permission-profile") + 1]
    if behaviour == "real-mounts":
        # What codex's bwrap does first on the workspace-write route: make its protective
        # mount point in the workspace root. On a read-only tree it dies with this line.
        if profile == ":workspace":
            target = os.path.join(tree, ".agents")
            try:
                os.mkdir(target)
            except OSError as exc:
                sys.stderr.write("bwrap: Can't mkdir %s: %s\\n" % (target, exc.strerror))
                sys.exit(1)
            os.rmdir(target)
        sys.exit(0)
    if behaviour == "namespace-refused":
        sys.stderr.write({bwrap_line!r} + "\\n")
        sys.exit(1)
    if behaviour == "usage-error":   # a codex whose `sandbox` subcommand takes other options
        sys.stderr.write("error: unexpected argument '--permission-profile' found\\n")
        sys.exit(2)
    if behaviour == "other-failure":
        sys.stderr.write("thread 'main' panicked: no usable bwrap: something else\\n")
        sys.exit(1)
    if behaviour == "hangs":
        time.sleep(60)
    sys.exit(0)
prompt = sys.stdin.read()
tree = args[args.index("--cd") + 1]
transcript = {transcript!r}.replace("{{CWD}}", tree)
head, _user, rest = transcript.partition("\\nuser\\n")
sys.stderr.write(head + "\\nuser\\n" + prompt + "\\n" + rest[rest.index("\\ncodex\\n"):])
last = {last!r}
sys.stdout.write(last)
open(args[args.index("--output-last-message") + 1], "w").write(last)
"""


def _stand_in_codex_cli(tmp_path, monkeypatch, behaviour: str) -> dict[str, str]:
    """A `codex` on the provider search path: answers `login status`, the sandbox probe (as
    ``behaviour`` says) and `exec` (the real healthy transcript and a verdict)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cli = bin_dir / "codex"
    cli.write_text(_STAND_IN_CODEX_CLI.format(
        behaviour=behaviour, bwrap_line=TEAM_HOST_BWRAP_LINE,
        transcript=(FIXTURES / "healthy.stderr").read_text(encoding="utf-8"),
        last=_last("healthy")), encoding="utf-8")
    cli.chmod(0o755)
    home = tmp_path / "operator"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "auth.json").write_text('{"tokens": {"access_token": "synthetic-access"}}',
                                               encoding="utf-8")
    path = f"{bin_dir}{os.pathsep}/usr/bin:/bin"
    monkeypatch.setenv("PATH", path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", path)
    pi._recorded_provider_hashes.cache_clear()
    return {"HOME": str(home), "PATH": path}


def _run_codex_seat(tmp_path, monkeypatch, behaviour: str, *, route: str = "tree"):
    """Production `_exec_leg` -> `_run_leg_with_liveness` -> seat-launch owner -> a real
    process. ``route``: ``tree`` (brokered, staged tree, workspace-write), ``sealed`` (brokered,
    no tree, no tools) or ``direct`` (unbrokered, read-only sandbox)."""
    env = _stand_in_codex_cli(tmp_path, monkeypatch, behaviour)
    review_dir, out_dir, tree = _staged_review(tmp_path)
    if route == "sealed":
        import shutil

        shutil.rmtree(tree)
    kwargs = {} if route == "direct" else {"broker_prompt": "Review the staged change.",
                                           "broker_evidence": {}}
    return pi._exec_leg("codex", review_dir, out_dir, timeout_s=60, artifact="A", env=env,
                        **kwargs)


needs_owner = pytest.mark.skipif(not os.path.exists("/usr/bin/bwrap") or os.getuid() == 0,
                                 reason="needs an unprivileged /usr/bin/bwrap")


@needs_owner
def test_the_probe_sees_the_seats_own_view_of_the_tree(tmp_path, monkeypatch, owned_review_network):
    """Not a stubbed fact: the stand-in does what codex's launcher does first (make its mount
    point in the workspace root) INSIDE the seat-launch owner. Today the owner shows the staged
    tree read-only, so a workspace-write codex seat cannot start a command, and the leg is
    DEGRADED before the model is called -- the stand-in's `exec` would have returned AGREE."""
    rc, text, log = _run_codex_seat(tmp_path, monkeypatch, "real-mounts")
    assert (rc, text) == (1, "") and type(log) is pi._HarnessCode and log == CODE
    assert pi._classify_leg(rc, text, log) == "DEGRADED"


@needs_owner
def test_the_probe_passes_where_the_launcher_has_nothing_to_create(tmp_path, monkeypatch,
                                                                    owned_review_network):
    """The control for the test above: the read-only route needs no mount point in the tree,
    so the same stand-in, in the same kind of view, starts, and the seat runs."""
    rc, text, _log = _run_codex_seat(tmp_path, monkeypatch, "real-mounts", route="direct")
    assert (rc, text) == (0, _last("healthy"))


@needs_owner
def test_a_refused_namespace_degrades_the_seat_before_it_runs(tmp_path, monkeypatch,
                                                               owned_review_network):
    """The team-host fault, with that host's bubblewrap line, on the unbrokered route too."""
    for route in ("tree", "direct"):
        (tmp_path / route).mkdir()
        rc, text, log = _run_codex_seat(tmp_path / route, monkeypatch, "namespace-refused",
                                        route=route)
        assert (rc, text, log) == (1, "", CODE), route


@needs_owner
@pytest.mark.parametrize("behaviour", ["healthy", "usage-error", "other-failure"])
def test_a_probe_that_does_not_show_a_dead_launcher_lets_the_seat_run(tmp_path, monkeypatch,
                                                                      owned_review_network,
                                                                      behaviour):
    """Only the launcher's own diagnostic on a failed probe decides (a line that STARTS with
    its name). A codex that does not know the subcommand, or fails some other way -- even with
    a message that mentions the launcher -- is inconclusive: the seat runs."""
    rc, text, _log = _run_codex_seat(tmp_path, monkeypatch, behaviour)
    assert (rc, text) == (0, _last("healthy"))


@needs_owner
def test_a_probe_that_hangs_is_inconclusive(tmp_path, monkeypatch, owned_review_network):
    monkeypatch.setattr(pi, "_CODEX_SANDBOX_PROBE_TIMEOUT_S", 2)
    rc, text, _log = _run_codex_seat(tmp_path, monkeypatch, "hangs")
    assert (rc, text) == (0, _last("healthy"))


@needs_owner
def test_a_seat_with_no_tools_is_not_probed(tmp_path, monkeypatch, owned_review_network):
    """The sealed route disables codex's shell: there is no command sandbox to start, and a
    probe that would fail must not take the seat down."""
    rc, text, _log = _run_codex_seat(tmp_path, monkeypatch, "namespace-refused", route="sealed")
    assert (rc, text) == (0, _last("healthy"))


# --------------------------------------------------------------------------------------
# The whole brokered spawn: staging, placement record, probe, leg -- nothing replaced but
# the broker transport and the two authorization checks.
# --------------------------------------------------------------------------------------

def _full_brokered_spawn(tmp_path, monkeypatch, behaviour: str):
    """``_default_spawn`` on the staged-tree route with the REAL ``_brokered_codex_command``:
    the probe argv is derived from the argv a board actually launches."""
    from phase_loop_runtime import review_stage
    from phase_loop_runtime.advisor_board import backing

    _stand_in_codex_cli(tmp_path, monkeypatch, behaviour)
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(tmp_path / "staging"))
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_ROOT", raising=False)
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED", raising=False)
    repo = tmp_path / "reviewed-repo"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "SOURCE.py").write_text("value = 41\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"],
                   check=True)
    authorization = backing.ReviewIsolationAuthorization(
        operation="public_board_review.v1", purpose="t", input_sha256="0" * 64,
        instructions_sha256="1" * 64, broker_contract=backing.PARENT_UNIX_BROKER_V1,
        routes=(), readonly_tools=("Read",), child_credentialless=True,
        child_network_egress=False, live_tree_exposed=False, api_fallback=False,
        canonical_repo_sha256="2" * 64, issued_monotonic_ns=0,
        _seal=backing._AUTHORIZATION_SEAL,
        staged_tree_sha256=review_stage.review_tree_manifest_sha256(repo),
    )
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi, "derive_review_leg_authorization",
                        lambda *a, **k: types.SimpleNamespace(expires_monotonic_ns=1))
    monkeypatch.setattr(pi, "ParentUnixBroker", _FakeBroker)
    monkeypatch.setattr(_FakeBroker, "invoked", 0)
    assert not pi._has_injected_review_execution_seam(leg="codex")
    spawned = pi._default_spawn("codex", "REVIEW BUNDLE BODY", repo_dir=repo,
                                review_authorization=authorization,
                                canonical_repo_authority=repo)
    assert _FakeBroker.invoked == 1, f"the brokered branch never ran: {spawned!r}"
    return spawned


@needs_owner
def test_a_full_brokered_spawn_with_a_working_sandbox_runs_the_seat(tmp_path, monkeypatch,
                                                                     owned_review_network):
    """The probe passes, the leg runs, and the placement record counts every launch the
    runtime made: the login check, the sandbox probe and the seat."""
    spawned = _full_brokered_spawn(tmp_path, monkeypatch, "healthy")
    assert (spawned[0], spawned[1]) == ("OK", _last("healthy"))
    placement = spawned.sandbox_placement_evidence
    assert placement["sandbox_root_applied"] is True
    assert placement["sandbox_local_provider_spawns"] == 3
    assert [r["step"] for r in placement["sandbox_placement_receipts"]] == ["prepared", "launched"]
    assert "seat_filesystem_unconfined" in spawned.seat_notices


@needs_owner
def test_a_full_brokered_spawn_on_todays_read_only_tree_is_degraded(tmp_path, monkeypatch,
                                                                     owned_review_network):
    """The board route as it is today: the owner shows the staged tree read-only, the probe
    (derived from the real launch argv) finds codex's launcher cannot start, and the seat
    ends DEGRADED with the notice, beside the route's own notice, without being run."""
    spawned = _full_brokered_spawn(tmp_path, monkeypatch, "real-mounts")
    status, text, detail = spawned
    assert (status, text) == ("DEGRADED", "") and pi._finalize_leg_detail(detail) == CODE
    assert spawned.sandbox_placement_evidence["sandbox_local_provider_spawns"] == 2
    leg = _leg_from(spawned)
    assert sorted(n.code for n in leg.seat_notices) == ["seat_filesystem_unconfined", CODE]
    assert not leg.usable
