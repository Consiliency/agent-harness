"""agent-harness#1433: a seat's declared output survives the provider's atomic write.

Claude Code's native ``Write`` creates a sibling temp file (``<name>.tmp.<pid>.<hex>``,
``O_CREAT|O_EXCL``) and renames it over the destination. The owned seat used to bind the
precreated output FILE writable inside a read-only parent, so, measured in the real sandbox:

* output directory == the seat's cwd (a private tmpfs): the temp file is created, and the
  rename fails ``EBUSY`` -- a bound file is a mount point, which no rename replaces;
* output directory anywhere else: the temp file itself fails ``EROFS`` (the issue's error).

Now an output its provider replaces atomically is declared ``replaceable_outputs``, and its
directory is, in the seat's view, a PRIVATE PER-LAUNCH directory mounted at that path. The
seat creates and renames freely there. The host's own directory is never mounted writable and
none of its other entries is visible. When the seat has ended, the owner copies only the
declared output names to the precreated host files, redacted, and removes the private
directory. ``outputs`` keeps its meaning: a file bound in place, shared live with the host.

On the host the private directory is a child of a 0700 holder under the owner's staging
root: never in the process temp root, never inside a path this seat can see, and not the
seat's to open to other accounts. A layout that cannot have one is refused before anything
is created.

Every cell that launches a seat runs it in the REAL owned sandbox (``launch_owned``).

Named mutations, each run against this file (all red):

* M-HOSTDIR: mount the host's own output directory writable instead of a private one ->
  the neighbour, scratch and two-seat cells fail.
* M-TMPROOT: create the holder in the process temp root -> the staging-root cell fails.
* M-EXPOSED: skip the "not inside a path this seat can see" check -> the view cell fails.
* M-NOMASK: do not mask the holders directory -> the three masking cells fail (another
  seat lists and reads a live launch's holder).
* M-MASK-LATE: mask only a holders directory that already exists -> the ``before any
  holder exists`` cell fails.
* M-HOLDERS-INPUT: accept an input that is a holders directory -> that cell fails.
* M-GROUP-HELD: accept any directory this account's primary group can write -> the
  shared-group cell fails.
* M-STAGE-EARLY: resolve the staging root before the layout is accepted -> the ``does not
  touch the staging root`` cell fails.
* M-STAGE-LATE: verify the staging root after the files are precreated -> the unusable
  staging cell fails.
* M-EMPTY-EARLY: empty an earlier file before the profile exists -> the ``refused after
  its layout was accepted`` cell fails.
* M-ENTRY: no holder removal for a failure on the way in -> the same cell fails.
* M-REMOVE-UNWRAPPED: let a raising removal leave at once -> the exit-sweep cell fails.
* M-HOLDER: bind the holder itself -> the seat can open it to others; that cell fails.
* M-NODELIVER: skip the copy to the host file -> the atomic-write cells fail.
* M-NOREDACT: deliver without redaction -> the redaction cell fails (the exit sweep would
  still redact the host file afterwards; the cell records every write to it).
* M-FOLLOW: read the seat's copy with a plain ``open`` -> the link cells deliver a host file
  (and the FIFO cell blocks).
* M-ORDER: mount the private directory after the read-only inputs -> the inputs cell fails.
* M-ANCHOR: mount a private directory wherever asked -> the read-only-input and
  system-mount cells fail.
* M-LIVE: read the host file while the seat runs -> the session cells never see the review.
* M-LIVE-FALLBACK: fall back to the host file when the private copy is absent or unsafe ->
  the live-read cell fails.
* M-STALE: keep an earlier launch's content in the host file -> the two stale cells fail.
* M-BOTH: let a replaceable declaration override an in-place one -> that cell fails.
* M-EARLY: skip the pre-launch placement check -> the read-only-input refusal cells fail.
* M-LATE: precreate before the placement check -> the ``creates nothing`` cell fails.
* M-EQUAL: do not refuse an output that is itself an input -> that cell fails.
* M-LINK: judge placement on the paths as written only -> the link cell fails.
* M-RMTREE: remove the holder with ``shutil.rmtree`` -> the deep-tree cell fails on
  Python 3.10 and 3.11.
* M-SWEEP: let a failed removal or delivery skip the exit sweep -> the notice and
  exit-step cells fail.
* M-UID / M-HOLDERUID / M-HOLDERMODE / M-HELD: drop one of the checks made where the
  directory is used -> its view cell fails.
* M-OWNMOUNT: allow an output under the seat's own mounts -> those cells fail.
* M-RESIDUE: leave holders out of the crash-residue sweep -> the dead-owner cell fails.
* M-SINK: do not hand the leg its notice list -> the board-leg cell fails.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import review_stage, sandbox_egress, sandbox_policy, seat_jail
from test_review_seat_stall_1176 import REQUEST, _JOURNAL, _ProviderTimer, _answer, _fast_tui

ADMIN = pi.SeatLaunchRole.PROVIDER_ADMIN
REVIEW = "Review body.\nAGREE\n"

#: What every fake seat below starts with. ``atomic_write`` is the provider's write, step for
#: step: a sibling temp file created exclusively, then renamed over the target.
SEAT = r'''
import errno, json, os, sys

def attempt(action, *args):
    try:
        action(*args)
        return "ok"
    except OSError as exc:
        return errno.errorcode.get(exc.errno, str(exc.errno))

def atomic_write(target, data):
    temp = "%s.tmp.%d.%s" % (target, os.getpid(), os.urandom(6).hex())
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data.encode())
    finally:
        os.close(fd)
    os.rename(temp, target)

def write(target, data):
    with open(target, "w") as handle:
        handle.write(data)

def read(target):
    with open(target) as handle:
        return handle.read()

def listing(directory):
    return sorted(os.listdir(directory))

facts = {}
'''
REPORT = "\nprint(json.dumps(facts))\n"


@pytest.fixture
def elsewhere(tmp_path):
    """A host directory outside the seat's private ``/tmp``: in the seat's view its path is
    only what the owner mounts there. (``tmp_path`` itself lies under ``/tmp``.)"""
    if os.path.isdir("/var/tmp") and os.access("/var/tmp", os.W_OK | os.X_OK):
        with tempfile.TemporaryDirectory(prefix="seat-output-test-", dir="/var/tmp") as directory:
            yield Path(directory)
        return
    directory = tmp_path / "elsewhere"
    directory.mkdir()
    yield directory


def _layout(name: str, tmp_path: Path, elsewhere: Path) -> tuple[Path, Path]:
    """``(cwd, output directory)``: the product layout (the output beside the seat's cwd
    inputs) and the issue's (an evidence directory of its own)."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    return cwd, (cwd if name == "output-in-cwd" else elsewhere)


LAYOUTS = ["output-in-cwd", "output-elsewhere"]


@contextmanager
def _profile(script: str, *, cwd: Path, outputs, readonly=(), env=None, argv=(), in_place=()):
    command = ["/usr/bin/python3", "-I", "-S", "-c", SEAT + script + REPORT, *map(str, argv)]
    with pi._seat_command_profile(command, env=env or {"PATH": "/usr/bin:/bin"}, cwd=cwd,
                                  replaceable_outputs=tuple(outputs), outputs=tuple(in_place),
                                  readonly_paths=tuple(readonly), role=ADMIN) as (owned, profile):
        yield owned, profile


def _launch(owned, profile, cwd: Path) -> dict:
    process = pi.launch_owned(owned, role=ADMIN, profile=profile, cwd=str(cwd),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = process.communicate(timeout=60)
    except BaseException:
        process.kill()
        process.wait()
        raise
    assert process.returncode == 0, stderr.decode(errors="replace")[-2000:]
    return json.loads(stdout)


def _seat(script: str, *, cwd: Path, outputs, readonly=(), env=None, argv=()) -> dict:
    with _profile(script, cwd=cwd, outputs=outputs, readonly=readonly, env=env,
                  argv=argv) as (owned, profile):
        return _launch(owned, profile, cwd)


def _names(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


# --- the contract: a sibling temp file renamed over the output ---------------------------------

@pytest.mark.parametrize("layout", LAYOUTS)
def test_a_sibling_temp_file_renamed_over_the_output_is_delivered(tmp_path, elsewhere, layout):
    cwd, directory = _layout(layout, tmp_path, elsewhere)
    output = directory / "opus.md"
    before = _names(directory)
    facts = _seat(
        "out = sys.argv[1]\n"
        "facts['first'] = attempt(atomic_write, out, 'A draft.\\n')\n"
        "facts['replaced'] = attempt(atomic_write, out, sys.argv[2])\n"  # over an existing file
        "facts['seen'] = listing(os.path.dirname(out))\n",
        cwd=cwd, outputs=(output,), argv=(output, REVIEW))
    assert facts == {"first": "ok", "replaced": "ok", "seen": ["opus.md"]}
    assert output.read_text() == REVIEW
    # The host directory gained the declared output and nothing else (no temp file).
    assert _names(directory) == sorted({*before, "opus.md"})


@pytest.mark.parametrize("layout", LAYOUTS)
def test_an_output_written_in_place_is_delivered_too(tmp_path, elsewhere, layout):
    """A provider that opens the destination directly (codex's last message) still works."""
    cwd, directory = _layout(layout, tmp_path, elsewhere)
    output = directory / "last-message.txt"
    facts = _seat("facts['write'] = attempt(write, sys.argv[1], sys.argv[2])\n",
                  cwd=cwd, outputs=(output,), argv=(output, REVIEW))
    assert facts == {"write": "ok"}
    assert output.read_text() == REVIEW


def test_two_outputs_of_one_seat_in_two_directories_are_both_delivered(tmp_path, elsewhere):
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    nested = elsewhere / "deeper" / "still"
    nested.mkdir(parents=True)
    first, second = elsewhere / "a.md", nested / "b.md"
    facts = _seat(
        "facts['a'] = attempt(atomic_write, sys.argv[1], 'first\\n')\n"
        "facts['b'] = attempt(atomic_write, sys.argv[2], 'second\\n')\n",
        cwd=cwd, outputs=(first, second), argv=(first, second))
    assert facts == {"a": "ok", "b": "ok"}
    assert (first.read_text(), second.read_text()) == ("first\n", "second\n")
    assert _names(elsewhere) == ["a.md", "deeper"] and _names(nested) == ["b.md"]


# --- negative cells: what the seat cannot reach ------------------------------------------------

@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_host_directory_is_never_writable_and_its_other_files_are_hidden(
        tmp_path, elsewhere, layout):
    """Whatever the seat creates, renames or removes beside its output stays in its private
    directory: on the host only the declared output changes, and the directory's other
    files are neither visible to the seat nor touched."""
    cwd, directory = _layout(layout, tmp_path, elsewhere)
    output = directory / "opus.md"
    neighbour = directory / "operator-notes.txt"
    neighbour.write_text("not an input of this seat\n")
    (directory / "kept").mkdir()
    (directory / "kept" / "file").write_text("kept\n")
    facts = _seat(
        "out = sys.argv[1]; here = os.path.dirname(out)\n"
        "facts['seen'] = listing(here)\n"
        "facts['read_neighbour'] = attempt(read, os.path.join(here, 'operator-notes.txt'))\n"
        "facts['read_kept'] = attempt(read, os.path.join(here, 'kept', 'file'))\n"
        # Not declared outputs: created, and renamed onto, in the seat's own view only.
        "facts['create'] = attempt(write, os.path.join(here, 'undeclared.md'), 'x')\n"
        "facts['rename_onto'] = attempt(atomic_write, os.path.join(here, 'other.md'), 'x')\n"
        "facts['overwrite_neighbour'] = attempt(\n"
        "    atomic_write, os.path.join(here, 'operator-notes.txt'), 'overwritten')\n"
        "facts['mkdir'] = attempt(os.makedirs, os.path.join(here, 'kept', 'new'))\n"
        "facts['output'] = attempt(atomic_write, out, sys.argv[2])\n",
        cwd=cwd, outputs=(output,), argv=(output, REVIEW))
    assert facts["seen"] == []
    assert facts["read_neighbour"] == "ENOENT" and facts["read_kept"] == "ENOENT"
    assert facts["output"] == "ok"
    # On the host: the declared output, and everything else exactly as it was.
    assert output.read_text() == REVIEW
    assert neighbour.read_text() == "not an input of this seat\n"
    assert _names(directory) == ["kept", "operator-notes.txt", "opus.md"]
    assert _names(directory / "kept") == ["file"]


def test_two_live_seats_sharing_a_host_directory_never_see_each_others_output(tmp_path, elsewhere):
    """Two seats with outputs in ONE host directory, both profiles live: the second cannot
    read, replace or remove what the first wrote, and each host file gets its own seat's
    bytes."""
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    first, second = elsewhere / "panel-first.txt", elsewhere / "panel-second.txt"
    with _profile("facts['write'] = attempt(atomic_write, sys.argv[1], 'first seat\\n')\n",
                  cwd=cwd, outputs=(first,), argv=(first,)) as (owned_first, profile_first):
        assert _launch(owned_first, profile_first, cwd) == {"write": "ok"}
        # The first seat has written; its profile is still open, as a parallel seat's is.
        facts = _seat(
            "mine, theirs = sys.argv[1], sys.argv[2]\n"
            "facts['seen'] = listing(os.path.dirname(mine))\n"
            "facts['read'] = attempt(read, theirs)\n"
            "facts['remove'] = attempt(os.unlink, theirs)\n"
            "facts['replace'] = attempt(atomic_write, theirs, 'second seat was here\\n')\n"
            "facts['write'] = attempt(atomic_write, mine, 'second seat\\n')\n",
            cwd=cwd, outputs=(second,), argv=(second, first))
        assert facts["seen"] == [] and facts["read"] == "ENOENT" and facts["remove"] == "ENOENT"
        assert facts["write"] == "ok"
    assert first.read_text() == "first seat\n"
    assert second.read_text() == "second seat\n"
    assert _names(elsewhere) == ["panel-first.txt", "panel-second.txt"]


def test_an_earlier_launchs_output_content_is_not_shown_to_the_next_seat(tmp_path, elsewhere):
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    output = elsewhere / "opus.md"
    output.write_text("an earlier launch's review\nAGREE\n")
    facts = _seat("facts['read'] = attempt(read, sys.argv[1])\n",
                  cwd=cwd, outputs=(output,), argv=(output,))
    assert facts == {"read": "ENOENT"}


def test_the_inputs_beside_the_output_stay_visible_and_read_only(tmp_path):
    """The product layout: the staged inputs live in the seat's cwd, next to its output.
    They are bound read-only INTO the private directory; the seat can replace its output
    there and nothing else."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    bundle = cwd / "review-bundle.md"
    bundle.write_text("the bundle\n")
    tree = cwd / review_stage.REVIEW_STAGE_TREE_DIRNAME
    tree.mkdir()
    (tree / "source.py").write_text("x = 1\n")
    declared = cwd / "context"
    declared.mkdir()
    (declared / "notes.md").write_text("declared input\n")
    output = cwd / "panel-claude.txt"
    facts = _seat(
        "out, bundle, tree, context = sys.argv[1:5]\n"
        "facts['read'] = [read(bundle), read(os.path.join(tree, 'source.py')),\n"
        "                 read(os.path.join(context, 'notes.md'))]\n"
        "facts['write_bundle'] = attempt(write, bundle, 'changed')\n"
        "facts['replace_bundle'] = attempt(atomic_write, bundle, 'changed')\n"
        "facts['remove_bundle'] = attempt(os.unlink, bundle)\n"
        "facts['write_tree'] = attempt(write, os.path.join(tree, 'new.py'), 'x')\n"
        "facts['write_source'] = attempt(write, os.path.join(tree, 'source.py'), 'x')\n"
        "facts['write_context'] = attempt(write, os.path.join(context, 'notes.md'), 'x')\n"
        "facts['replace_tree'] = attempt(os.rename, tree, tree + '.moved')\n"
        "facts['output'] = attempt(atomic_write, out, sys.argv[5])\n",
        cwd=cwd, outputs=(output,), readonly=(declared,),
        argv=(output, bundle, tree, declared, REVIEW))
    assert facts["read"] == ["the bundle\n", "x = 1\n", "declared input\n"]
    assert facts["output"] == "ok"
    refused = {key: value for key, value in facts.items() if key not in {"read", "output"}}
    assert set(refused.values()) <= {"EROFS", "EBUSY", "EXDEV"}, refused
    assert "ok" not in refused.values()
    assert bundle.read_text() == "the bundle\n"
    assert (tree / "source.py").read_text() == "x = 1\n" and _names(tree) == ["source.py"]
    assert (declared / "notes.md").read_text() == "declared input\n"
    assert output.read_text() == REVIEW
    assert _names(cwd) == sorted(["context", "panel-claude.txt", "review-bundle.md", tree.name])


@pytest.mark.parametrize("where", ["a declared input", "below a declared input",
                                   "the staged tree in the cwd"])
def test_an_output_inside_a_read_only_input_is_refused_before_launch(tmp_path, where, monkeypatch):
    """Where the output's directory is (inside) a read-only input, a private directory
    there would hide that input, and an output bound in place cannot be replaced by the
    provider's write: it would fail only at the end of the seat's turn. So the launch is
    refused before anything runs, with a typed notice, and no file is created."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    repo = tmp_path / "repo"
    (repo / "logs").mkdir(parents=True)
    (repo / "logs" / "earlier.log").write_text("an input\n")
    tree = cwd / review_stage.REVIEW_STAGE_TREE_DIRNAME
    tree.mkdir()
    output = {"a declared input": repo / "opus.md", "below a declared input": repo / "logs" / "opus.md",
              "the staged tree in the cwd": tree / "opus.md"}[where]
    monkeypatch.setattr(pi, "launch_owned", lambda *a, **k: pytest.fail("the seat launched"))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified) as refused:
        with _profile("", cwd=cwd, outputs=(output,), readonly=(repo,)):
            pytest.fail("a profile was built")
    assert str(refused.value) == "seat_output_inside_readonly_input"
    assert not os.path.lexists(output)
    assert pi._exception_failure(refused.value) == "seat_output_inside_readonly_input"
    notice = seat_jail.render_notice(str(refused.value), "claude:a")
    assert notice.what == "leg refused" and "outside its read-only inputs" in notice.fix


@pytest.mark.usefixtures("owned_review_network")
def test_a_claude_session_with_its_output_inside_an_input_is_refused_before_launch(
        tmp_path, monkeypatch):
    """The Claude route itself: the canonical output sits in a directory the argv grants
    read-only (``--add-dir``). The session refuses before the provider starts, never after a
    turn whose write cannot land (a late ``EROFS`` / ``EBUSY``)."""
    repo = tmp_path / "repo"
    (repo / "out").mkdir(parents=True)
    output = repo / "out" / "panel-claude.txt"
    launched = []
    monkeypatch.setattr(pi, "launch_owned", lambda *a, **k: launched.append(a) or pytest.fail("launched"))
    started = time.monotonic()
    with pytest.raises(sandbox_egress.SeatIdentityUnverified) as refused:
        pi._run_claude_tui_session(
            command=["/usr/bin/python3", "-c", "pass", "--add-dir", str(repo), "x"],
            cwd=tmp_path, prompt="input", output_file=output, timeout_s=600, backstop_s=600,
            env=os.environ,
            review_monitor=pi._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event()))
    assert str(refused.value) == "seat_output_inside_readonly_input"
    assert launched == [] and time.monotonic() - started < 10
    assert not os.path.lexists(output)


@pytest.mark.parametrize("flag", ["--cd", "--cwd"])
@pytest.mark.parametrize("tree_at", ["beside the output directory", "inside the output directory"])
def test_a_tree_named_in_the_argv_composes_with_a_replaceable_output(tmp_path, flag, tree_at):
    """agent-harness#1438's join: a seat launches in its output directory and names the
    staged tree only in its argv (codex ``--cd``, grok ``--cwd``), and its output is
    replaceable. The tree is visible and read-only at its path, also when it lies inside the
    private output directory, and the atomically written output is delivered."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    tree = (tmp_path / "review" if tree_at.startswith("beside") else out_dir) / "reviewed-tree"
    tree.mkdir(parents=True)
    (tree / "source.txt").write_text("TREE-CONTENT\n")
    output = out_dir / "out.txt"
    facts = _seat(
        "tree, out = sys.argv[2], sys.argv[3]\n"
        "facts['read'] = read(os.path.join(tree, 'source.txt'))\n"
        "facts['write_tree'] = attempt(write, os.path.join(tree, 'source.txt'), 'x')\n"
        "facts['output'] = attempt(atomic_write, out, facts['read'])\n",
        cwd=out_dir, outputs=(output,), argv=(flag, tree, output))
    assert facts == {"read": "TREE-CONTENT\n", "write_tree": "EROFS", "output": "ok"}
    assert output.read_text() == "TREE-CONTENT\n"
    assert (tree / "source.txt").read_text() == "TREE-CONTENT\n"


# --- the other kind of output: bound in place, as before ---------------------------------------

def test_an_output_declared_in_place_is_still_one_live_file_shared_with_the_host(tmp_path, elsewhere):
    """``outputs`` keeps its meaning: one precreated host file, shared live. The seat reads
    what the host writes into it and the host reads what the seat writes, while the seat
    runs; the seat cannot replace it (it is a mount point). Only ``replaceable_outputs``
    are delivered when the seat ends."""
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    review, signal, answer = elsewhere / "opus.md", elsewhere / "signal", elsewhere / "answer"
    script = (
        "import time\n"
        "review, signal, answer = sys.argv[1:4]\n"
        "deadline = time.monotonic() + 30\n"
        "while not read(signal) and time.monotonic() < deadline: time.sleep(.02)\n"
        "facts['heard'] = read(signal)\n"
        "facts['replace'] = attempt(atomic_write, answer, 'x')\n"
        "write(answer, 'live from the seat')\n"
        "while read(signal) != 'done' and time.monotonic() < deadline: time.sleep(.02)\n"
        "facts['review'] = attempt(atomic_write, review, sys.argv[4])\n")
    with _profile(script, cwd=cwd, outputs=(review,), in_place=(signal, answer),
                  argv=(review, signal, answer, REVIEW)) as (owned, profile):
        assert [Path(path) for path in profile.outputs] == [signal, answer]
        process = pi.launch_owned(owned, role=ADMIN, profile=profile, cwd=str(cwd),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            signal.write_text("go")  # the host writes; the running seat reads it
            deadline = time.monotonic() + 30
            while answer.read_text() != "live from the seat" and time.monotonic() < deadline:
                time.sleep(.02)
            assert answer.read_text() == "live from the seat"  # read while the seat runs
            assert pi._seat_output_text(profile, answer) == "live from the seat"
            signal.write_text("done")
            stdout, stderr = process.communicate(timeout=60)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        assert process.returncode == 0, stderr.decode(errors="replace")[-2000:]
        assert json.loads(stdout) == {"heard": "go", "replace": "EBUSY", "review": "ok"}
        assert review.read_text() == ""  # the replaceable output arrives when the seat has ended
    assert review.read_text() == REVIEW
    assert _names(elsewhere) == ["answer", "opus.md", "signal"]


def test_an_output_declared_both_ways_stays_in_place(tmp_path, elsewhere):
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    output = elsewhere / "opus.md"
    with _profile("facts['write'] = attempt(write, sys.argv[1], sys.argv[2])\n"
                  "facts['replace'] = attempt(atomic_write, sys.argv[1], 'x')\n",
                  cwd=cwd, outputs=(output,), in_place=(output,),
                  argv=(output, REVIEW)) as (owned, profile):
        assert profile.output_dirs == () and [Path(path) for path in profile.outputs] == [output]
        facts = _launch(owned, profile, cwd)
        # No sibling can be created (EROFS) or, under the seat's /tmp, renamed over it (EBUSY).
        assert facts["write"] == "ok" and facts["replace"] in {"EROFS", "EBUSY"}
        assert output.read_text() == REVIEW  # live, before the profile ends
    assert output.read_text() == REVIEW


# --- delivery: redacted, and only a private regular file ---------------------------------------

def _codex_shaped_profile(monkeypatch, tmp_path):
    """A seat whose private home holds a copied credential (``synthetic-access-token``)."""
    home = tmp_path / "operator"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex/auth.json").write_text('{"tokens":{"access_token":"synthetic-access-token"}}')
    python = str(Path("/usr/bin/python3").resolve())
    monkeypatch.setattr(pi, "_seat_provider_source", lambda *_: ("codex", python))
    return {"PATH": "/usr/bin:/bin", "HOME": str(home)}


@pytest.mark.parametrize("layout", LAYOUTS)
def test_delivery_redacts_before_the_secrets_are_released_and_keeps_nothing_else(
        tmp_path, elsewhere, layout, monkeypatch):
    env = _codex_shaped_profile(monkeypatch, tmp_path)
    cwd, directory = _layout(layout, tmp_path, elsewhere)
    output = directory / "opus.md"
    script = (
        "secret = json.loads(read(os.path.join(os.environ['CODEX_HOME'], 'auth.json')))\n"
        "secret = secret['tokens']['access_token']\n"
        "facts['copied'] = secret == 'synthetic-access-token'\n"
        "facts['write'] = attempt(atomic_write, sys.argv[1], 'leaked ' + secret + ' here\\nAGREE\\n')\n"
        "facts['scratch'] = attempt(write, sys.argv[1] + '.notes', 'also ' + secret)\n")
    written: list[str] = []
    real_write = pi._write_seat_text

    def recording_write(path, text):
        written.append(text)
        return real_write(path, text)

    monkeypatch.setattr(pi, "_write_seat_text", recording_write)
    with _profile(script, cwd=cwd, outputs=(output,), env=env, argv=(output,)) as (owned, profile):
        (private, seen_at), = profile.output_dirs
        assert seen_at == str(directory) and Path(private) != directory
        assert _launch(owned, profile, cwd) == {"copied": True, "write": "ok", "scratch": "ok"}
        # While the profile is open the unredacted bytes exist only in the private directory;
        # the host file has received nothing yet, and the live read is already redacted.
        assert "synthetic-access-token" in (Path(private) / "opus.md").read_text()
        assert output.read_text() == ""
        assert pi._seat_output_text(profile, output) == "leaked [credential redacted] here\nAGREE"
    assert output.read_text() == "leaked [credential redacted] here\nAGREE\n"
    # The host file never held the secret, not even between delivery and the exit sweep.
    assert written == ["leaked [credential redacted] here\nAGREE\n"]
    assert not os.path.lexists(private), "the unredacted private copy was retained"
    assert _names(directory) == ["opus.md"]


UNSAFE = {
    "a link to a host file": "os.symlink('/etc/hostname', out)\n",
    "a link to its own scratch": "write(out + '.real', sys.argv[2]); os.symlink(out + '.real', out)\n",
    "a dangling link": "os.symlink(out + '.absent', out)\n",
    "a second name for the file": "write(out, sys.argv[2]); os.link(out, out + '.alias')\n",
    "a directory": "os.mkdir(out)\n",
    "a fifo": "os.mkfifo(out)\n",
}


@pytest.mark.parametrize("shape", sorted(UNSAFE))
def test_a_name_that_is_not_a_private_regular_file_delivers_nothing(tmp_path, elsewhere, shape):
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    output = elsewhere / "opus.md"
    with _profile("out = sys.argv[1]\n" + UNSAFE[shape], cwd=cwd, outputs=(output,),
                  argv=(output, REVIEW)) as (owned, profile):
        _launch(owned, profile, cwd)
        (private, _seen_at), = profile.output_dirs
        assert os.path.lexists(Path(private) / "opus.md")
        assert pi._seat_output_text(profile, output) == ""  # never followed, never blocking
    assert output.read_text() == ""
    assert not os.path.lexists(private)
    assert _names(elsewhere) == ["opus.md"]


def test_the_private_directory_is_removed_whatever_the_seat_left_in_it(tmp_path, elsewhere):
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    output = elsewhere / "opus.md"
    with _profile(
            "here = os.path.dirname(sys.argv[1])\n"
            "os.makedirs(os.path.join(here, 'a', 'b'))\n"
            "write(os.path.join(here, 'a', 'b', 'c'), 'x')\n"
            "os.symlink('/etc', os.path.join(here, 'a', 'link'))\n"
            "os.mkfifo(os.path.join(here, 'pipe'))\n"
            "os.chmod(os.path.join(here, 'a', 'b'), 0)\n"
            "os.chmod(os.path.join(here, 'a'), 0)\n"
            "facts['write'] = attempt(atomic_write, sys.argv[1], sys.argv[2])\n",
            cwd=cwd, outputs=(output,), argv=(output, REVIEW)) as (owned, profile):
        (private, _seen_at), = profile.output_dirs
        assert _launch(owned, profile, cwd) == {"write": "ok"}
    assert not os.path.lexists(private)
    assert output.read_text() == REVIEW and os.path.isdir("/etc")


def test_a_profile_that_never_launches_leaves_no_private_directory(tmp_path, elsewhere):
    output = elsewhere / "opus.md"
    with _profile("", cwd=tmp_path, outputs=(output,)) as (_owned, profile):
        (private, _seen_at), = profile.output_dirs
        info = os.stat(private)
        assert info.st_uid == os.getuid() and (info.st_mode & 0o777) == 0o700
        assert os.listdir(private) == []
    assert not os.path.lexists(private) and output.read_text() == ""


# --- where the private directory lives on the host ---------------------------------------------

def _holders() -> list[str]:
    """This account's output holders under the staging root (none outside a live profile)."""
    root = Path(os.path.realpath(sandbox_policy.staging_root())) / "pl-seat-outputs"
    return sorted(entry.name for entry in root.iterdir()
                  if entry.name.startswith(pi._SEAT_OUTPUT_HOLDER_PREFIX)
                  and not entry.name.endswith(".owner")) if root.is_dir() else []


def test_the_private_directory_lives_in_a_holder_under_the_staging_root(tmp_path, monkeypatch):
    """Never in the process temp root. With the temp root inside a reviewed tree, another
    seat that reads that tree must not find this seat's private directory in it. The seat is
    bound a child of a 0700 holder under the owner's staging root, which records its owner."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(repo))  # a TMPDIR inside the reviewed tree
    staging = Path(os.path.realpath(sandbox_policy.staging_root()))
    assert not staging.is_relative_to(repo)
    before = _holders()
    with _profile("", cwd=cwd, outputs=(out / "review.txt",), readonly=(repo,)) as (_, first):
        private = Path(first.output_dirs[0][0])
        holder = private.parent
        assert holder.parent == staging / "pl-seat-outputs"
        assert holder.name.startswith("pl-seat-output-")
        assert not private.is_relative_to(repo)
        assert stat_mode(holder.parent) == 0o700
        assert stat_mode(holder) == 0o700 and stat_mode(private) == 0o700
        assert Path(str(holder) + ".owner").read_text().startswith(f"pid={os.getpid()} ")
        with _profile("", cwd=cwd, outputs=(out / "other.txt",), readonly=(repo,)) as (_, second):
            other = Path(second.output_dirs[0][0])
            assert other.parent != holder  # a holder per launch
            layers = pi._seat_view_layers(cwd, second.readonly_paths)
            assert not pi._seat_host_exposed(layers, private)
            assert not pi._seat_host_exposed(layers, other)
    assert _holders() == before and not os.path.lexists(str(holder) + ".owner")


def stat_mode(path) -> int:
    return os.lstat(path).st_mode & 0o7777


LOOK = (
    "holders, theirs, out = sys.argv[1:4]\n"
    "facts['holders'] = listing(holders) if os.path.isdir(holders) else 'absent'\n"
    "facts['read'] = attempt(read, theirs)\n"
    "facts['write_holders'] = attempt(write, os.path.join(holders, 'probe'), 'x')\n"
    "facts['output'] = attempt(write, out, sys.argv[4])\n"
)


def test_no_seat_sees_another_launchs_holder_through_its_own_inputs(tmp_path, monkeypatch):
    """A second seat whose read-only input IS the staging root, with an in-place output of
    its own and no replaceable one: it must not find a live launch's holder there. Both
    seats run as the same uid, so a 0700 holder would not stop it. The holders directory is
    masked in every seat's view: empty for this seat, in the real sandbox."""
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    with _profile("", cwd=first, outputs=(first / "review.txt",)) as (_owned, writer):
        private = Path(writer.output_dirs[0][0])
        (private / "review.txt").write_text("Private review\nAGREE\n")
        holders = private.parent.parent
        assert holders == staging / "pl-seat-outputs" and _names(holders) != []
        with _profile(LOOK, cwd=second, outputs=(), in_place=(second / "review.txt",),
                      readonly=(staging,),
                      argv=(holders, private / "review.txt", second / "review.txt", REVIEW)
                      ) as (owned, reader):
            layers = pi._seat_view_layers(second, reader.readonly_paths)
            assert not pi._seat_host_exposed(layers, private)
            assert not pi._seat_host_exposed(layers, holders / "anything-made-later")
            assert pi._seat_host_exposed(layers, staging / "other-scratch")  # the input itself
            facts = _launch(owned, reader, second)
        assert facts["holders"] == [] and facts["read"] == "ENOENT"
        assert facts["output"] == "ok" and (second / "review.txt").read_text() == REVIEW
        # Whatever it writes into the mask stays in its own view.
        assert _names(holders) == [private.parent.name, private.parent.name + ".owner"]
        assert (private / "review.txt").read_text() == "Private review\nAGREE\n"


def test_a_holders_directory_is_masked_before_any_holder_exists(tmp_path, monkeypatch):
    """A seat that starts BEFORE any launch has made a holder must not see one made later.
    So the holders directory is made, and masked, for every seat whose inputs would show
    it, here an input above a staging root that does not exist yet."""
    repo = tmp_path / "repo"
    repo.mkdir()
    staging = repo / "state" / "staging"
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    out = cwd / "out.txt"
    holders = staging / "pl-seat-outputs"
    with _profile(
            "holders, out = sys.argv[1:3]\n"
            "facts['before'] = listing(holders)\n"
            "import time\n"
            "deadline = time.monotonic() + 30\n"
            "while not os.path.exists(os.path.join(os.path.dirname(holders), 'go')) "
            "and time.monotonic() < deadline: time.sleep(.02)\n"
            "facts['after'] = listing(holders)\n"
            "facts['output'] = attempt(write, out, 'done')\n",
            cwd=cwd, outputs=(), in_place=(out,), readonly=(repo,), argv=(holders, out)
            ) as (owned, profile):
        process = pi.launch_owned(owned, role=ADMIN, profile=profile, cwd=str(cwd),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 30
            while not holders.is_dir() and time.monotonic() < deadline:
                time.sleep(.02)
            assert holders.is_dir()  # made for the mask
            # Another launch makes a holder while the first seat runs.
            with _profile("", cwd=tmp_path, outputs=(tmp_path / "review.txt",)) as (_o, writer):
                private = Path(writer.output_dirs[0][0])
                assert private.parent.parent == holders
                (private / "review.txt").write_text("unredacted")
                (staging / "go").write_text("")
                stdout, stderr = process.communicate(timeout=60)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert process.returncode == 0, stderr.decode(errors="replace")[-2000:]
    assert json.loads(stdout) == {"before": [], "after": [], "output": "ok"}


def test_a_seat_reading_its_own_staging_root_still_gets_its_replaceable_output(
        tmp_path, monkeypatch):
    """The staging root inside a read-only input is no reason to refuse: the seat's own
    holder is masked from it like any other, and its output is delivered."""
    repo = tmp_path / "repo"
    repo.mkdir()
    staging = repo / "new-directory" / "staging"
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    output = cwd / "review.txt"
    with _profile(
            "facts['holders'] = listing(sys.argv[2])\n"
            "facts['write'] = attempt(atomic_write, sys.argv[1], sys.argv[3])\n",
            cwd=cwd, outputs=(output,), readonly=(repo,),
            argv=(output, staging / "pl-seat-outputs", REVIEW)) as (owned, profile):
        private = Path(profile.output_dirs[0][0])
        assert private.is_relative_to(repo)  # on the host, inside the input ...
        layers = pi._seat_view_layers(cwd, profile.readonly_paths)
        assert not pi._seat_host_exposed(layers, private)  # ... and not in the seat's view
        assert _launch(owned, profile, cwd) == {"holders": [], "write": "ok"}
    assert output.read_text() == REVIEW and _holders() == []


def test_an_input_that_is_a_holders_directory_or_inside_one_is_refused(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
    with _profile("", cwd=tmp_path, outputs=(tmp_path / "review.txt",)) as (_owned, profile):
        private = Path(profile.output_dirs[0][0])
        for source in (private, private.parent, private.parent.parent):
            with pytest.raises(sandbox_egress.SeatIdentityUnverified,
                               match="seat_bind_source_unavailable"):
                pi._seat_filesystem_view(tmp_path / "other", readonly_paths=(source,))


@pytest.mark.parametrize("fault", ["above it a directory others can write", "not a directory"])
def test_an_unusable_staging_root_is_refused_before_any_file_exists(tmp_path, monkeypatch, fault):
    """A staging root that cannot give a private, un-replaceable holders directory is
    refused with its own code, whose fix names the setting, before the output file, the
    transcript or a holder exists, and with an earlier file left as it was."""
    shared = tmp_path / "shared"
    shared.mkdir()
    staging = shared / "staging"
    if fault == "not a directory":
        staging.write_text("")
    else:
        staging.mkdir(mode=0o700)
        shared.chmod(0o777)
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
    out = tmp_path / "out"
    out.mkdir()
    earlier = out / "earlier.md"
    earlier.write_text("Earlier launch\nDISAGREE\n")
    transcript = tmp_path / "journal.jsonl"
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_output_staging_unusable"):
        with pi._seat_command_profile(
                ["/usr/bin/python3", "-c", "pass"], env={"PATH": "/usr/bin:/bin"}, cwd=tmp_path,
                transcript_path=transcript,
                replaceable_outputs=(out / "review.txt", earlier), role=ADMIN):
            pytest.fail("a profile was built")
    assert _names(out) == ["earlier.md"] and not os.path.lexists(transcript)
    assert earlier.read_text() == "Earlier launch\nDISAGREE\n"
    notice = seat_jail.render_notice("seat_output_staging_unusable", "claude:a")
    assert notice.what == "leg refused" and "PHASE_LOOP_SANDBOX_STAGING_DIR" in notice.fix
    assert pi._exception_failure(sandbox_egress.SeatIdentityUnverified(
        "seat_output_staging_unusable")) == "seat_output_staging_unusable"


def test_a_launch_refused_after_its_layout_was_accepted_leaves_no_holder_and_no_emptied_file(
        tmp_path, elsewhere, monkeypatch):
    """The profile itself refuses (here: the seat's credential cannot be read). The launch
    never became this launch's: an earlier review in the host file is intact, and the
    holder made on the way in is gone."""
    python = str(Path("/usr/bin/python3").resolve())
    monkeypatch.setattr(pi, "_seat_provider_source", lambda *_: ("codex", python))
    home = tmp_path / "operator-without-a-login"
    home.mkdir()
    output = elsewhere / "opus.md"
    output.write_text("Earlier launch, a complete review\nDISAGREE\n")
    before = _holders()
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_profile_unavailable"):
        with pi._seat_command_profile(
                ["/usr/bin/python3", "-c", "pass"], env={"PATH": "/usr/bin:/bin", "HOME": str(home)},
                cwd=tmp_path, replaceable_outputs=(output,),
                role=pi.SeatLaunchRole.PROVIDER_REVIEW):  # a review seat needs its login
            pytest.fail("a profile was built")
    assert output.read_text() == "Earlier launch, a complete review\nDISAGREE\n"
    assert _holders() == before


def test_a_refused_layout_does_not_touch_the_staging_root(tmp_path, monkeypatch):
    """The staging root is resolved, and so made, only after the layout is accepted: a
    refused layout leaves a configured staging directory that does not exist yet absent,
    wherever it is."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for staging in (repo / "new-directory" / "staging", tmp_path / "not-yet" / "staging"):
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
        with pytest.raises(sandbox_egress.SeatIdentityUnverified,
                           match="seat_output_inside_readonly_input"):
            with pi._seat_command_profile(
                    ["/usr/bin/python3", "-c", "pass"], env={"PATH": "/usr/bin:/bin"},
                    cwd=tmp_path / "cwd", role=ADMIN,
                    replaceable_outputs=(repo / "review.txt",), readonly_paths=(repo,)):
                pytest.fail("the refused layout was admitted")
        assert not os.path.lexists(staging) and not os.path.lexists(staging.parent)
    assert _names(repo) == []


def test_the_seat_cannot_open_its_directory_to_other_accounts(tmp_path, elsewhere):
    """The seat owns the directory it is given and may give it any mode. The holder above
    it is not in the seat's view, stays 0700, and keeps every other account out."""
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    output = elsewhere / "opus.md"
    with _profile(
            "here = os.path.dirname(sys.argv[1])\n"
            "facts['write'] = attempt(atomic_write, sys.argv[1], sys.argv[2])\n"
            "facts['open_dir'] = attempt(os.chmod, here, 0o777)\n"
            "facts['open_file'] = attempt(os.chmod, sys.argv[1], 0o666)\n"
            "facts['open_holder'] = attempt(os.chmod, os.path.join(here, '..'), 0o777)\n"
            "facts['above'] = sorted(os.listdir(os.path.join(here, '..')))\n",
            cwd=cwd, outputs=(output,), argv=(output, REVIEW)) as (owned, profile):
        private = Path(profile.output_dirs[0][0])
        facts = _launch(owned, profile, cwd)
        assert facts["write"] == "ok" and facts["open_dir"] == "ok" and facts["open_file"] == "ok"
        # ``..`` of the seat's directory is the seat's own view, never the holder.
        assert facts["open_holder"] != "ok" and facts["above"] == [elsewhere.name]
        assert stat_mode(private) == 0o777  # the seat's to change
        assert stat_mode(private.parent) == 0o700  # not the seat's to change
    assert output.read_text() == REVIEW and not os.path.lexists(private.parent)


def test_a_refused_layout_creates_nothing(tmp_path):
    """Placement is settled before any side effect: a refused launch leaves no transcript,
    no in-place output, no replaceable output and no holder behind."""
    repo = tmp_path / "repo"
    repo.mkdir()
    transcript, in_place = tmp_path / "journal.jsonl", tmp_path / "capture.txt"
    before = _holders()
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_output_inside_readonly_input"):
        with pi._seat_command_profile(
                ["/usr/bin/python3", "-c", "pass"], env={"PATH": "/usr/bin:/bin"}, cwd=tmp_path,
                readonly_paths=(repo,), outputs=(in_place,), transcript_path=transcript,
                replaceable_outputs=(repo / "review.txt",), role=ADMIN):
            pytest.fail("the refused layout built a profile")
    assert [path.name for path in (transcript, in_place, repo / "review.txt")
            if os.path.lexists(path)] == []
    assert _holders() == before


def test_an_output_that_is_itself_a_read_only_input_is_refused(tmp_path):
    context = tmp_path / "context.txt"
    context.write_text("read-only input")
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_output_inside_readonly_input"):
        with pi._seat_command_profile(
                ["/usr/bin/python3", "-c", "pass"], env={"PATH": "/usr/bin:/bin"}, cwd=tmp_path / "x",
                readonly_paths=(context,), replaceable_outputs=(context,), role=ADMIN):
            pytest.fail("an output equal to a read-only input built a profile")
    assert context.read_text() == "read-only input"


def test_an_output_reached_through_a_link_into_an_input_is_refused(tmp_path):
    """The check reads the paths as the host holds them once parent links are resolved, as
    the binds do: an output named through a link whose target is inside a read-only input is
    inside that input."""
    repo = tmp_path / "repo"
    (repo / "logs").mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "link").symlink_to(repo, target_is_directory=True)
    output = tmp_path / "elsewhere" / "link" / "logs" / "opus.md"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_output_inside_readonly_input"):
        with _profile("", cwd=cwd, outputs=(output,), readonly=(repo,)):
            pytest.fail("a profile was built")
    assert _names(repo / "logs") == []


@pytest.mark.parametrize("directory", ["/home/phase-loop-seat/out", "/run/phase-loop-seat",
                                       "/usr/share/out", "/proc/self", "/dev/shm/out", "/"])
def test_an_output_under_a_system_mount_or_the_seats_own_mounts_is_refused(tmp_path, directory):
    """Also where the owner mounts the seat's own state after its outputs: a directory
    there would be covered by those mounts. Refused before anything is touched."""
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_output_inside_readonly_input"):
        with _profile("", cwd=tmp_path, outputs=(Path(directory) / "opus.md",)):
            pytest.fail("a profile was built")


def test_a_dead_owners_holder_is_swept_whatever_the_seat_left_in_it(tmp_path, monkeypatch):
    """An owner killed before its profile ends leaves its holder behind. The holder records
    its owner, so the crash-residue sweep removes it once that process is provably gone, at
    any depth, and leaves a live owner's holder alone."""
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(staging))
    dead = subprocess.Popen(["true"])
    dead.wait()
    holders = pi._seat_output_holders_root()
    assert holders == staging / "pl-seat-outputs"
    gone = pi._seat_output_holder(holders)
    (gone / "0").mkdir()
    subprocess.run(["/usr/bin/python3", "-c", "import os, sys\nos.chdir(sys.argv[1])\n"
                    "for _ in range(1200):\n    os.mkdir('d'); os.chdir('d')\n", str(gone / "0")],
                   check=True)
    (gone / "0" / "opus.md").write_text("unredacted")
    pi._sandbox_retention.claim_scratch_dir(gone, owner_pid=dead.pid)
    live = pi._seat_output_holder(holders)
    (live / "0").mkdir()
    pi._gc_stale_panel_scratch()
    assert not os.path.lexists(gone) and not os.path.lexists(str(gone) + ".owner")
    assert live.is_dir() and (live / "0").is_dir()
    assert pi._remove_seat_output_holder(live) and _names(holders) == []


DEEP = (
    "here = os.path.dirname(sys.argv[1])\n"
    "facts['write'] = attempt(atomic_write, sys.argv[1], sys.argv[2])\n"
    "os.chdir(here)\n"
    "for _ in range(1200):\n"
    "    os.mkdir('d'); os.chdir('d')\n"
    "write('leaf', 'x')\n"
    "facts['depth'] = 1200\n"
)


def test_a_deep_tree_beside_the_output_cannot_stop_removal_or_the_sweep(
        tmp_path, elsewhere, monkeypatch):
    """A seat leaves a tree 1,200 levels deep beside its output. Removal does not depend on
    depth (a recursive removal raises ``RecursionError`` on Python 3.10 and 3.11): the holder
    is gone, the review is delivered, the exit sweep still redacts the in-place output, and
    nothing is raised."""
    env = _codex_shaped_profile(monkeypatch, tmp_path)
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    output, in_place = elsewhere / "opus.md", elsewhere / "notes.txt"
    script = (
        "secret = json.loads(read(os.path.join(os.environ['CODEX_HOME'], 'auth.json')))\n"
        "write(sys.argv[3], 'leaked ' + secret['tokens']['access_token'] + '\\n')\n" + DEEP)
    with _profile(script, cwd=cwd, outputs=(output,), in_place=(in_place,), env=env,
                  argv=(output, REVIEW, in_place)) as (owned, profile):
        private = Path(profile.output_dirs[0][0])
        assert _launch(owned, profile, cwd) == {"write": "ok", "depth": 1200}
    assert not os.path.lexists(private.parent), "the private directory survived"
    assert output.read_text() == REVIEW
    assert in_place.read_text() == "leaked [credential redacted]\n"


def test_a_holder_that_cannot_be_removed_is_a_notice_not_a_lost_review(
        tmp_path, elsewhere, monkeypatch, caplog):
    """If removal fails all the same, the delivered review stands, the exit sweep still
    runs, nothing is raised, and the leg gets a typed notice that names what is left."""
    env = _codex_shaped_profile(monkeypatch, tmp_path)
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    output, in_place = elsewhere / "opus.md", elsewhere / "notes.txt"
    real_remove = pi._remove_seat_output_holder
    script = (
        "secret = json.loads(read(os.path.join(os.environ['CODEX_HOME'], 'auth.json')))\n"
        "write(sys.argv[3], 'leaked ' + secret['tokens']['access_token'] + '\\n')\n"
        "facts['write'] = attempt(atomic_write, sys.argv[1], sys.argv[2])\n")
    notices: list[str] = []
    token = pi._SEAT_OWNER_NOTICES.set(notices)
    try:
        with caplog.at_level("WARNING", logger=pi.__name__):
            with _profile(script, cwd=cwd, outputs=(output,), in_place=(in_place,), env=env,
                          argv=(output, REVIEW, in_place)) as (owned, profile):
                holder = Path(profile.output_dirs[0][0]).parent
                assert _launch(owned, profile, cwd) == {"write": "ok"}
                monkeypatch.setattr(pi, "_remove_seat_output_holder", lambda path: False)
    finally:
        pi._SEAT_OWNER_NOTICES.reset(token)
        monkeypatch.setattr(pi, "_remove_seat_output_holder", real_remove)
    try:
        assert notices == ["seat_output_retained_after_teardown"]
        assert any("seat_output_retained_after_teardown" in record.getMessage()
                   and str(holder) in record.getMessage() for record in caplog.records)
        assert output.read_text() == REVIEW
        assert in_place.read_text() == "leaked [credential redacted]\n"
        notice = seat_jail.render_notice(notices[0], "claude:a")
        assert notice.what == "directory retained" and "pl-seat-output-" in notice.fix
        assert notices[0] in pi._HARNESS_DETAIL_CODES
    finally:
        assert real_remove(holder)


def test_each_exit_step_runs_whatever_the_others_did(tmp_path, elsewhere, monkeypatch):
    """Delivery fails: the holder is still removed and the sweep still redacts; the failure
    is raised afterwards."""
    env = _codex_shaped_profile(monkeypatch, tmp_path)
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    output, in_place = elsewhere / "opus.md", elsewhere / "notes.txt"
    script = (
        "secret = json.loads(read(os.path.join(os.environ['CODEX_HOME'], 'auth.json')))\n"
        "write(sys.argv[3], 'leaked ' + secret['tokens']['access_token'] + '\\n')\n"
        "facts['write'] = attempt(atomic_write, sys.argv[1], sys.argv[2])\n")

    def failing_delivery(source, destination):
        raise RuntimeError("synthetic delivery failure")

    with pytest.raises(RuntimeError, match="synthetic delivery failure"):
        with _profile(script, cwd=cwd, outputs=(output,), in_place=(in_place,), env=env,
                      argv=(output, REVIEW, in_place)) as (owned, profile):
            holder = Path(profile.output_dirs[0][0]).parent
            assert _launch(owned, profile, cwd) == {"write": "ok"}
            monkeypatch.setattr(pi, "_deliver_seat_output", failing_delivery)
    assert not os.path.lexists(holder)
    assert in_place.read_text() == "leaked [credential redacted]\n"


@pytest.mark.parametrize("group", ["shared with another account", "the operator's own"])
def test_a_holder_below_a_group_writable_directory_needs_a_private_group(
        tmp_path, monkeypatch, group):
    """A directory above the holder that this account's primary group can write is accepted
    only when that group is the operator's alone. A member of a shared group could rename
    the verified holder away and put its own in its place."""
    from types import SimpleNamespace

    uid, gid = os.getuid(), os.getgid()
    operator = SimpleNamespace(pw_uid=uid, pw_gid=gid, pw_name="operator")
    neighbor = SimpleNamespace(pw_uid=uid + 1, pw_gid=gid, pw_name="neighbor")
    shared_group = group == "shared with another account"
    members = ["operator", "neighbor"] if shared_group else ["operator"]
    accounts = [operator, neighbor] if shared_group else [operator]
    monkeypatch.setattr(seat_jail, "_account_db", lambda: (
        operator, lambda _gid: SimpleNamespace(gr_name="operator", gr_mem=members),
        lambda: accounts))
    assert seat_jail._operator_private_group(gid) is not shared_group
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o770)
    assert os.stat(shared).st_gid == gid
    holder = shared / "pl-seat-output-probe"
    holder.mkdir(mode=0o700)
    private = holder / "0"
    private.mkdir(mode=0o700)
    view = lambda: pi._seat_filesystem_view(  # noqa: E731
        tmp_path / "cwd", output_dirs=((str(private), str(tmp_path / "out")),))
    if shared_group:
        with pytest.raises(sandbox_egress.SeatIdentityUnverified,
                           match="seat_bind_source_unavailable"):
            view()
    else:
        assert str(private) in view()


def test_a_removal_that_raises_does_not_skip_the_exit_sweep(tmp_path, elsewhere, monkeypatch):
    """The removal step is wrapped like the other two: if it raises (an interrupt landing
    in it), the exit sweep still redacts, the holder is still removed on the way out, and
    the error is raised afterwards."""
    env = _codex_shaped_profile(monkeypatch, tmp_path)
    cwd, _ = _layout("output-elsewhere", tmp_path, elsewhere)
    output, in_place = elsewhere / "opus.md", elsewhere / "notes.txt"
    script = (
        "secret = json.loads(read(os.path.join(os.environ['CODEX_HOME'], 'auth.json')))\n"
        "write(sys.argv[3], 'leaked ' + secret['tokens']['access_token'] + '\\n')\n"
        "facts['write'] = attempt(atomic_write, sys.argv[1], sys.argv[2])\n")
    real_remove = pi._remove_seat_output_holder
    calls = []

    def interrupted_once(holder):
        calls.append(holder)
        if len(calls) == 1:
            raise KeyboardInterrupt("synthetic interrupt during removal")
        return real_remove(holder)

    with pytest.raises(KeyboardInterrupt, match="synthetic interrupt"):
        with _profile(script, cwd=cwd, outputs=(output,), in_place=(in_place,), env=env,
                      argv=(output, REVIEW, in_place)) as (owned, profile):
            holder = Path(profile.output_dirs[0][0]).parent
            assert _launch(owned, profile, cwd) == {"write": "ok"}
            monkeypatch.setattr(pi, "_remove_seat_output_holder", interrupted_once)
    assert in_place.read_text() == "leaked [credential redacted]\n"
    assert output.read_text() == REVIEW
    assert not os.path.lexists(holder)


def test_a_board_leg_carries_the_refusal_and_the_owners_notices(tmp_path, monkeypatch):
    """Through the board's own spawn: a refusal the owner raises reaches the leg as DEGRADED
    with empty text, its code as the detail and as a notice; and a notice the owner raises
    while the profile ends (a retained holder) lands in the same leg's notices."""
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", "tui")

    def refusing_leg(*args, **kwargs):
        pi._note_seat_output_retained(tmp_path / "pl-seat-output-left")
        raise sandbox_egress.SeatIdentityUnverified("seat_output_inside_readonly_input")

    monkeypatch.setattr(pi, "_exec_claude_tui_leg", refusing_leg)
    spawned = pi._default_spawn("claude", "an advisory question", repo_dir=tmp_path, mode="advisory")
    assert tuple(spawned) == ("DEGRADED", "", "seat_output_inside_readonly_input")
    assert spawned.seat_notices == ("seat_output_retained_after_teardown",
                                    "seat_output_inside_readonly_input")
    assert pi._SEAT_OWNER_NOTICES.get() is None  # the leg's list does not outlive the leg


# --- an earlier launch's content in the host file ----------------------------------------------

def test_the_live_read_never_falls_back_to_the_host_file(tmp_path, elsewhere):
    """While the seat runs, its output is what is in its private directory and nothing else:
    not a host file with content, whether the private copy is absent or not a regular file."""
    output = elsewhere / "opus.md"
    with _profile("", cwd=tmp_path, outputs=(output,)) as (_owned, profile):
        private = Path(profile.output_dirs[0][0])
        output.write_text("Not this seat's\nAGREE\n")
        assert pi._seat_output_text(profile, output) == ""
        (private / "opus.md").symlink_to(output)
        assert pi._seat_output_text(profile, output) == ""
        (private / "opus.md").unlink()
        (private / "opus.md").write_text(REVIEW)
        assert pi._seat_output_text(profile, output) == REVIEW.strip()


def test_a_host_file_left_by_an_earlier_launch_is_emptied_when_the_launch_is_accepted(
        tmp_path, elsewhere):
    """A replaceable output is this launch's file from the moment the launch is accepted: an
    earlier launch's review in it is emptied, so a launch that delivers nothing never leaves
    an earlier verdict behind. (A launch refused for its layout touches nothing.)"""
    output = elsewhere / "opus.md"
    output.write_text("Earlier launch\nAGREE\n")
    with _profile("", cwd=tmp_path, outputs=(output,)) as (_owned, profile):
        assert output.read_text() == ""
        assert pi._seat_output_text(profile, output) == ""
    assert output.read_text() == ""


@pytest.mark.usefixtures("owned_review_network")
def test_a_session_never_returns_an_earlier_launchs_verdict(tmp_path, elsewhere, monkeypatch):
    """The host file already holds "Earlier launch / AGREE"; this seat ends its turn and
    writes nothing. The session refuses (it used to return the stale AGREE with rc 0), and
    the stale verdict is gone from the file."""
    _fast_tui(monkeypatch)
    monkeypatch.setattr(pi, "_CLAUDE_TUI_SUBMIT_DELAY_S", .01)
    monkeypatch.setattr(pi, "_CLAUDE_TUI_READY_QUIESCENCE_S", .01)
    cwd, directory = _layout("output-elsewhere", tmp_path, elsewhere)
    output = directory / "opus.md"
    output.write_text("Earlier launch\nAGREE\n")
    body = json.dumps(REQUEST) + "\n" + json.dumps(_answer("a", "m", "AGREE")) + "\n"
    script = (
        "import sys, time\nfrom pathlib import Path\n" + _JOURNAL +
        "print('Claude Code fake provider ready for review', flush=True)\n"
        "time.sleep(.2)\n"
        f"_journal.write_text({body!r})\n"
        "while True:\n"
        "    sys.stdout.write('\\r* Idle...'); sys.stdout.flush(); time.sleep(.05)\n"
    )
    monitor = pi._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                stall_notice_s=3600)
    guard = _ProviderTimer(monkeypatch, 15, monitor.cancel.set)
    try:
        rc, text, log, _tail = pi._run_claude_tui_session(
            command=["/usr/bin/python3", "-c", script], cwd=cwd, prompt="input",
            output_file=output, timeout_s=600, backstop_s=600, stall_threshold_s=600,
            env=os.environ, review_monitor=monitor,
        )
    finally:
        guard.cancel()
    assert (rc, text, log) == (1, "", "claude_seat_delivery_refused")
    assert output.read_text() == ""


# --- the view: where the private directory is mounted ------------------------------------------

def _mounts(view: list[str]) -> list[tuple[str, str]]:
    """``(kind, destination)`` for each tmpfs and bind of a view, in mount order."""
    mounts, index = [], 0
    while index < len(view):
        if view[index] == "--tmpfs":
            mounts.append(("tmpfs", view[index + 1]))
            index += 2
        elif view[index] in {"--bind", "--ro-bind"}:
            mounts.append((view[index][2:], view[index + 2]))
            index += 3
        else:
            index += 1
    return mounts


def _private(tmp_path, name="private") -> str:
    directory = tmp_path / name
    directory.mkdir(mode=0o700)
    return str(directory)


def test_view_mounts_the_private_directory_over_the_cwd_and_under_its_inputs(tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "review-bundle.md").write_text("bundle")
    private = _private(tmp_path)
    view = pi._seat_filesystem_view(cwd, readonly_paths=(cwd / "review-bundle.md",),
                                    output_dirs=((private, str(cwd)),))
    mounts = _mounts(view)
    order = [mounts.index(("tmpfs", str(cwd))), mounts.index(("bind", str(cwd))),
             mounts.index(("ro-bind", str(cwd / "review-bundle.md")))]
    assert order == sorted(order)
    assert view[view.index("--bind"):view.index("--bind") + 3] == ["--bind", private, str(cwd)]
    # The host's own directory is never a writable bind source.
    assert [view[i + 1] for i, item in enumerate(view) if item == "--bind"] == [private]


def test_view_mounts_a_private_directory_above_the_cwd_before_the_cwd(tmp_path):
    above = tmp_path / "above"
    cwd = above / "work"
    cwd.mkdir(parents=True)
    mounts = _mounts(pi._seat_filesystem_view(cwd, output_dirs=((_private(tmp_path), str(above)),)))
    assert mounts.index(("bind", str(above))) < mounts.index(("tmpfs", str(cwd)))


def test_view_nests_a_deeper_private_directory_inside_a_shallower_one(tmp_path):
    outer, inner = tmp_path / "outer", tmp_path / "outer" / "inner"
    inner.mkdir(parents=True)
    dirs = ((_private(tmp_path, "p-inner"), str(inner)), (_private(tmp_path, "p-outer"), str(outer)))
    mounts = _mounts(pi._seat_filesystem_view(tmp_path / "outer" / "inner", output_dirs=dirs))
    assert mounts.index(("bind", str(outer))) < mounts.index(("bind", str(inner)))


@pytest.mark.parametrize("where", ["the input itself", "below the input"])
def test_view_refuses_a_private_directory_that_would_hide_a_read_only_input(tmp_path, where):
    repo = tmp_path / "repo"
    (repo / "logs").mkdir(parents=True)
    destination = repo if where == "the input itself" else repo / "logs"
    with pytest.raises(sandbox_egress.SeatIdentityUnverified):
        pi._seat_filesystem_view(tmp_path, readonly_paths=(repo,),
                                 output_dirs=((_private(tmp_path), str(destination)),))


@pytest.mark.parametrize("destination", ["/", "/usr", "/usr/lib/seat-output", "/etc/ssl/certs",
                                         "/proc/self", "/dev/shm/seat-output"])
def test_view_refuses_a_private_directory_over_the_root_or_a_system_mount(tmp_path, destination):
    with pytest.raises(sandbox_egress.SeatIdentityUnverified):
        pi._seat_filesystem_view(tmp_path, output_dirs=((_private(tmp_path), destination),))


@pytest.mark.parametrize("shape", ["a link", "a file", "open to others", "absent"])
def test_view_refuses_a_private_directory_source_that_is_not_private(tmp_path, shape):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    source = tmp_path / "source"
    if shape == "a link":
        source.symlink_to(target, target_is_directory=True)
    elif shape == "a file":
        source.write_text("")
    elif shape == "open to others":
        source.mkdir()
        source.chmod(0o755)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified):
        pi._seat_filesystem_view(tmp_path, output_dirs=((str(source), str(tmp_path / "out")),))


@pytest.mark.parametrize("fault", ["the directory is another account's",
                                   "the holder is another account's",
                                   "the holder is open to others",
                                   "the holder's parent is writable by others"])
def test_view_refuses_a_private_directory_whose_holder_is_not_ours_and_closed(
        tmp_path, monkeypatch, fault):
    """Verified where it is used: the directory and the holder above it are real directories
    of this account, the holder is 0700, and no other account can replace it."""
    shared = tmp_path / "shared"
    shared.mkdir()
    holder = shared / "holder"
    holder.mkdir(mode=0o700)
    source = holder / "0"
    source.mkdir(mode=0o700)
    view = lambda: pi._seat_filesystem_view(  # noqa: E731
        tmp_path / "cwd", output_dirs=((str(source), str(tmp_path / "out")),))
    built = view()  # accepted as it stands
    assert built[built.index("--bind"):built.index("--bind") + 3] == [
        "--bind", str(source), str(tmp_path / "out")]
    if fault == "the holder is open to others":
        holder.chmod(0o750)
    elif fault == "the holder's parent is writable by others":
        shared.chmod(0o777)
    else:
        foreign = str(source if fault.startswith("the directory") else holder)
        real_lstat = os.lstat

        def lstat(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if os.fspath(path) != foreign:
                return info
            fields = list(info)
            fields[4] = info.st_uid + 1  # st_uid
            return os.stat_result(fields)

        monkeypatch.setattr(pi.os, "lstat", lstat)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_bind_source_unavailable"):
        view()


def test_view_refuses_a_private_directory_the_seat_can_see_through_an_input(tmp_path):
    """The source of a private directory is never a host path one of this view's binds
    shows: here it lies inside a read-only input."""
    repo = tmp_path / "repo"
    holder = repo / "holder"
    (holder / "0").mkdir(parents=True, mode=0o700)
    holder.chmod(0o700)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_bind_source_unavailable"):
        pi._seat_filesystem_view(tmp_path / "cwd", readonly_paths=(repo,),
                                 output_dirs=((str(holder / "0"), str(tmp_path / "out")),))


# --- the live session: the review is read while the seat runs, and delivered when it ends ------

@pytest.mark.usefixtures("owned_review_network")
@pytest.mark.parametrize("layout", LAYOUTS)
def test_a_tui_session_accepts_and_delivers_an_atomically_written_review(
        tmp_path, elsewhere, layout, monkeypatch):
    _fast_tui(monkeypatch)
    monkeypatch.setattr(pi, "_CLAUDE_TUI_SUBMIT_DELAY_S", .01)
    monkeypatch.setattr(pi, "_CLAUDE_TUI_READY_QUIESCENCE_S", .01)
    cwd, directory = _layout(layout, tmp_path, elsewhere)
    output = directory / "opus.md"
    body = json.dumps(REQUEST) + "\n" + json.dumps(_answer("a", "m", "AGREE")) + "\n"
    script = (
        SEAT + "import time\nfrom pathlib import Path\n" + _JOURNAL +
        "print('Claude Code fake provider ready for review', flush=True)\n"
        "time.sleep(.2)\n"
        f"atomic_write({str(output)!r}, {REVIEW!r})\n"
        f"_journal.write_text({body!r})\n"
        "while True:\n"
        "    sys.stdout.write('\\r* Idle...'); sys.stdout.flush(); time.sleep(.05)\n"
    )
    profiles = []
    real_profile = pi._seat_command_profile

    @contextmanager
    def recording_profile(*args, **kwargs):
        with real_profile(*args, **kwargs) as (owned, profile):
            profiles.append(profile)
            yield owned, profile

    monkeypatch.setattr(pi, "_seat_command_profile", recording_profile)
    monitor = pi._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                stall_notice_s=3600)
    guard = _ProviderTimer(monkeypatch, 15, monitor.cancel.set)
    started = time.monotonic()
    try:
        rc, text, log, _tail = pi._run_claude_tui_session(
            command=["/usr/bin/python3", "-c", script], cwd=cwd, prompt="input",
            output_file=output, timeout_s=600, backstop_s=600, stall_threshold_s=600,
            env=os.environ, review_monitor=monitor,
        )
    finally:
        guard.cancel()
    assert (rc, text, log) == (0, REVIEW.strip(), "claude_tui_file_output")
    assert time.monotonic() - started < 12
    assert output.read_text() == REVIEW
    (private, seen_at), = profiles[0].output_dirs
    assert seen_at == str(directory) and not os.path.lexists(private)
    assert [name for name in _names(directory) if name.startswith("opus.md")] == ["opus.md"]
