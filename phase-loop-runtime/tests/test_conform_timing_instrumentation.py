"""Falsifiers for the opt-in CONFORM phase timing (Consiliency/agent-harness#945).

Board review of agent-harness#947 raised four properties that the instrumentation
asserts about itself but never checked. Each is checked here.

The module deliberately keeps ``outside_agent`` out of every node id so the
CONFORM ``-k outside_agent`` lifecycle corpus is unchanged.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tarfile
import types
from pathlib import Path

import pytest


@pytest.fixture
def timing(request):
    """The conftest module pytest actually loaded.

    `import conftest` from the tests directory builds a SECOND module object
    (pytest registers the plugin as `tests.conftest`), and that duplicate has
    its own recorder stack, so a test importing it directly would assert against
    state the live hook never touches.
    """
    plugin = request.config.pluginmanager.get_plugin(
        str(Path(__file__).with_name("conftest.py"))
    )
    assert plugin is not None and plugin.__name__ == "tests.conftest", plugin
    return plugin


WRAPPED_SYMBOLS = (
    "subprocess.Popen",
    "shutil.copytree",
    "shutil.rmtree",
    "tarfile.TarFile.extractall",
    "pathlib.Path.read_bytes",
    "pathlib.Path.read_text",
)


SYMBOL_SETTERS = {
    "subprocess.Popen": lambda v: setattr(subprocess, "Popen", v),
    "shutil.copytree": lambda v: setattr(shutil, "copytree", v),
    "shutil.rmtree": lambda v: setattr(shutil, "rmtree", v),
    "tarfile.TarFile.extractall": lambda v: setattr(tarfile.TarFile, "extractall", v),
    "pathlib.Path.read_bytes": lambda v: setattr(Path, "read_bytes", v),
    "pathlib.Path.read_text": lambda v: setattr(Path, "read_text", v),
}


def _current_identities() -> tuple[object, ...]:
    return (
        subprocess.Popen,
        shutil.copytree,
        shutil.rmtree,
        tarfile.TarFile.extractall,
        Path.read_bytes,
        Path.read_text,
    )


def test_timing_hook_rebinds_nothing_when_the_flag_is_unset(timing, monkeypatch, capsys):
    """An unset flag must leave every wrapped symbol's identity untouched."""
    monkeypatch.delenv(timing._CONFORM_TIMING_ENV, raising=False)
    item = types.SimpleNamespace(nodeid="probe::flag_unset")

    before = _current_identities()
    generator = timing.pytest_runtest_call(item)
    next(generator)
    during = _current_identities()
    with pytest.raises(StopIteration):
        generator.send(None)
    after = _current_identities()

    assert during == before, dict(zip(WRAPPED_SYMBOLS, during))
    assert after == before, dict(zip(WRAPPED_SYMBOLS, after))
    assert capsys.readouterr().out == ""


def test_timing_hook_restores_every_symbol_when_the_flag_is_set(timing, monkeypatch):
    """A set flag must leave no wrapper behind once the measured scope exits."""
    monkeypatch.setenv(timing._CONFORM_TIMING_ENV, "1")
    item = types.SimpleNamespace(nodeid="probe::flag_set")

    outermost = not timing._CONFORM_RECORDER_STACK
    before = _current_identities()
    generator = timing.pytest_runtest_call(item)
    next(generator)
    during = _current_identities()
    with pytest.raises(StopIteration):
        generator.send(None)
    after = _current_identities()

    if outermost:
        assert all(
            installed is not original for installed, original in zip(during, before)
        ), dict(zip(WRAPPED_SYMBOLS, during))
    else:
        # The suite itself is already running under the flag, so this scope
        # nests. Only the outermost install may rebind a symbol.
        assert during == before, dict(zip(WRAPPED_SYMBOLS, during))
    assert after == before, dict(zip(WRAPPED_SYMBOLS, after))


def test_install_and_restore_round_trip_is_identity_exact(timing):
    """`restore()` must put back the exact objects `install()` displaced."""
    outermost = not timing._CONFORM_RECORDER_STACK
    before = _current_identities()
    recorder = timing._ConformTimingRecorder("probe::round_trip")
    restore = timing._conform_timing_install(recorder)
    try:
        if outermost:
            assert _current_identities() != before
        else:
            assert _current_identities() == before
    finally:
        restore()
    assert _current_identities() == before
    assert not outermost or not timing._CONFORM_RECORDER_STACK


def test_a_nested_install_never_wraps_a_wrapper(timing):
    """A second install must not double-count or steal the inner attribution."""
    outer = timing._ConformTimingRecorder("probe::outer")
    restore_outer = timing._conform_timing_install(outer)
    try:
        installed = _current_identities()
        inner = timing._ConformTimingRecorder("probe::inner")
        restore_inner = timing._conform_timing_install(inner)
        try:
            assert _current_identities() == installed, "a wrapper wrapped a wrapper"
            subprocess.Popen(
                [sys.executable, "-c", "print('nested')"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).communicate()
        finally:
            restore_inner()
        # The innermost scope owns the child; the outer scope is not charged.
        assert inner.counters.get("child_processes") == 1
        assert outer.counters.get("child_processes") is None
        subprocess.Popen(
            [sys.executable, "-c", "print('outer')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).communicate()
        assert outer.counters.get("child_processes") == 1
        assert inner.counters.get("child_processes") == 1
    finally:
        restore_outer()


def test_a_child_is_charged_to_the_recorder_that_started_it(timing):
    """A process awaited under a later recorder stays charged to its own test."""
    first = timing._ConformTimingRecorder("probe::starter")
    restore = timing._conform_timing_install(first)
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", "print('charged')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    finally:
        restore()

    second = timing._ConformTimingRecorder("probe::awaiter")
    restore = timing._conform_timing_install(second)
    try:
        process.communicate()
    finally:
        restore()

    assert first.counters.get("child_processes") == 1
    assert second.counters.get("child_processes") is None
    assert [event["label"] for event in second.events] == []


def test_repeated_communicate_counts_one_child_and_one_byte_total(timing):
    """Calling `communicate()` twice must not add the same bytes twice."""
    recorder = timing._ConformTimingRecorder("probe::repeat_communicate")
    restore = timing._conform_timing_install(recorder)
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", "print('abcdef')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        first_stdout, _ = process.communicate()
        try:
            process.communicate()
        except ValueError:
            # CPython refuses a second communicate() on some paths; the accounting
            # must survive either outcome.
            pass
        process.wait()
    finally:
        restore()

    process_events = [event for event in recorder.events if event["kind"] == "process"]
    assert len(process_events) == 1, process_events
    assert recorder.counters["child_processes"] == 1
    # text mode, so the unit is characters and the counter says so
    assert recorder.counters["child_output_chars"] == len(first_stdout)
    assert "child_output_bytes" not in recorder.counters
    assert process_events[0]["out_size"] == len(first_stdout)
    assert process_events[0]["out_kind"] == "chars"


def test_nested_copytree_records_one_event_and_counts_each_file_once(timing, tmp_path):
    """`shutil._copytree` recurses through the module global, re-entering the wrapper."""
    source = tmp_path / "source"
    (source / "level1" / "level2").mkdir(parents=True)
    (source / "root.txt").write_text("r", encoding="utf-8")
    (source / "level1" / "one.txt").write_text("1", encoding="utf-8")
    (source / "level1" / "level2" / "two.txt").write_text("2", encoding="utf-8")
    (source / "level1" / "level2" / "three.txt").write_text("3", encoding="utf-8")
    expected_files = 4

    recorder = timing._ConformTimingRecorder("probe::nested_copytree")
    restore = timing._conform_timing_install(recorder)
    try:
        shutil.copytree(source, tmp_path / "destination")
    finally:
        restore()

    copy_events = [
        event for event in recorder.events if event["label"] == "shutil.copytree"
    ]
    assert len(copy_events) == 1, copy_events
    assert recorder.counters["copytree_calls"] == 1
    assert recorder.counters["copytree_files"] == expected_files
    assert copy_events[0]["files"] == expected_files


def test_probe_children_record_their_stdin_digest(timing):
    """Probe identity and stdin digest come from the payload, not the argv."""
    recorder = timing._ConformTimingRecorder("probe::stdin_digest")
    restore = timing._conform_timing_install(recorder)
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.read()"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        process.communicate('{"mutation_id": "M-PROBE-1"}')
    finally:
        restore()

    event = next(event for event in recorder.events if event["kind"] == "process")
    assert event["probe"] == "M-PROBE-1"
    assert isinstance(event["stdin_sha256"], str) and len(event["stdin_sha256"]) == 64


# ---------------------------------------------------------------------------
# Restoration ordering (board round 2, agent-harness#947)
#
# The call-phase hook restores at the end of the CALL phase, but `monkeypatch`
# undoes in TEARDOWN. A test that patches one of the six wrapped symbols saves
# whatever is current -- the wrapper -- and reinstalls it after the hook has
# already restored, resurrecting a wrapper with an empty recorder stack. On the
# superseded code that raised `IndexError: list index out of range` at the next
# test's setup.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _as_the_outermost_scope(timing):
    """Run with no recorder installed, whatever the session's own flag is.

    Under a flag-set session the hook has already pushed this test's recorder, so
    a nested install rebinds nothing and the stack is never empty. Setting the
    stack aside reproduces the orphan condition deterministically in both modes,
    and putting it back leaves the session's own accounting untouched.
    """
    saved = list(timing._CONFORM_RECORDER_STACK)
    timing._CONFORM_RECORDER_STACK.clear()
    try:
        yield
    finally:
        timing._CONFORM_RECORDER_STACK[:] = saved


def _spawn_and_wait():
    process = subprocess.Popen(
        [sys.executable, "-c", "print('probe')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process.communicate()


def test_every_wrapper_degrades_to_the_real_symbol_on_an_empty_stack(timing, tmp_path):
    """All six wrappers, invoked with no recorder: no raise, nothing counted."""
    with _as_the_outermost_scope(timing):
        recorder = timing._ConformTimingRecorder("probe::degrade")
        restore = timing._conform_timing_install(recorder)
        wrappers = _current_identities()
        restore()
        assert not timing._CONFORM_RECORDER_STACK
        timing._conform_timing_sweep()
        _assert_orphaned_wrappers_are_inert(timing, recorder, wrappers, tmp_path)


def _assert_orphaned_wrappers_are_inert(timing, recorder, wrappers, tmp_path):
    popen, copytree, rmtree, extractall, read_bytes, read_text = wrappers
    before_events = len(recorder.events)
    before_counters = dict(recorder.counters)

    process = popen(
        [sys.executable, "-c", "print('orphan')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, _ = process.communicate()
    assert stdout.strip() == "orphan"

    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "file.txt").write_text("payload", encoding="utf-8")
    copytree(source, tmp_path / "copy")
    assert (tmp_path / "copy" / "nested" / "file.txt").is_file()

    archive_path = tmp_path / "archive.tar"
    with tarfile.open(archive_path, "w") as archive:
        archive.add(source / "nested" / "file.txt", arcname="file.txt")
    with tarfile.open(archive_path) as archive:
        extractall(archive, tmp_path / "extracted")
    assert (tmp_path / "extracted" / "file.txt").is_file()

    assert read_bytes(source / "nested" / "file.txt") == b"payload"
    assert read_text(source / "nested" / "file.txt") == "payload"
    rmtree(tmp_path / "copy")
    assert not (tmp_path / "copy").exists()

    assert len(recorder.events) == before_events
    assert recorder.counters == before_counters

    # The superseded rule, shown raising on the same empty stack.
    with pytest.raises(IndexError):
        timing._CONFORM_RECORDER_STACK[-1]
    assert timing._conform_current_recorder() is None


def test_a_wrapper_resurrected_after_restore_is_swept_at_teardown(timing, monkeypatch):
    """Exactly what `monkeypatch` teardown does, and the sweep that undoes it."""
    monkeypatch.setenv(timing._CONFORM_TIMING_ENV, "1")
    item = types.SimpleNamespace(nodeid="probe::resurrect")
    with _as_the_outermost_scope(timing):
        _assert_resurrected_wrappers_are_swept(timing, item)


def _assert_resurrected_wrappers_are_swept(timing, item):
    before = _current_identities()
    generator = timing.pytest_runtest_call(item)
    next(generator)
    resurrected = _current_identities()
    with pytest.raises(StopIteration):
        generator.send(None)
    assert _current_identities() == before
    assert resurrected != before, "the hook must have rebound as the outermost scope"

    # Fixture teardown reinstalling what it saved during the call phase.
    subprocess.Popen = resurrected[0]
    shutil.copytree = resurrected[1]
    shutil.rmtree = resurrected[2]
    tarfile.TarFile.extractall = resurrected[3]
    Path.read_bytes = resurrected[4]
    Path.read_text = resurrected[5]
    assert _current_identities() == resurrected

    # Harmless while resurrected: no recorder, no raise, nothing recorded.
    assert _spawn_and_wait()[0].strip() == "probe"

    teardown = timing.pytest_runtest_teardown(item, None)
    next(teardown)
    with pytest.raises(StopIteration):
        teardown.send(None)
    # The sweep leaves the IMPORT-TIME value, which equals `before` outside a
    # flag-set session and is the correct answer inside one too.
    expected = tuple(
        timing._CONFORM_PRISTINE[name] for name in WRAPPED_SYMBOLS
    )
    assert _current_identities() == expected, dict(
        zip(WRAPPED_SYMBOLS, _current_identities())
    )
    for name, value in zip(WRAPPED_SYMBOLS, before):
        SYMBOL_SETTERS[name](value)  # leave the session's own state as found


def test_restore_leaves_a_fixture_patch_that_was_installed_first(timing):
    """Reverse ordering: install over a patch, restore under it."""
    sentinel = type("SentinelPopen", (subprocess.Popen,), {})
    original = subprocess.Popen
    with _as_the_outermost_scope(timing):
        subprocess.Popen = sentinel
        try:
            recorder = timing._ConformTimingRecorder("probe::reverse")
            restore = timing._conform_timing_install(recorder)
            assert subprocess.Popen is not sentinel, "the hook must have rebound"
            restore()
            # restore() hands back the FIXTURE's patch, not the true original.
            assert subprocess.Popen is sentinel
            timing._conform_timing_sweep()
            assert subprocess.Popen is sentinel
        finally:
            subprocess.Popen = original
    assert subprocess.Popen is original


def test_zz_leak_a_monkeypatches_a_wrapped_symbol(monkeypatch):
    """Saves the wrapper under a flag-set session and reinstalls it at teardown."""
    monkeypatch.setattr(subprocess, "Popen", subprocess.Popen)
    monkeypatch.setattr(shutil, "copytree", shutil.copytree)
    monkeypatch.setattr(Path, "read_bytes", Path.read_bytes)
    assert _spawn_and_wait()[0].strip() == "probe"


@pytest.fixture
def spawns_outside_the_call_phase(tmp_path):
    assert _spawn_and_wait()[0].strip() == "probe"
    (tmp_path / "setup.txt").write_text("setup", encoding="utf-8")
    assert (tmp_path / "setup.txt").read_bytes() == b"setup"
    yield
    assert _spawn_and_wait()[0].strip() == "probe"


def test_zz_leak_b_a_following_test_spawns_in_setup_and_body(
    spawns_outside_the_call_phase,
):
    """The consecutive-test regression: this is where the IndexError landed."""
    assert _spawn_and_wait()[0].strip() == "probe"


# ---------------------------------------------------------------------------
# Flag mutation during a measured test (board round 3, agent-harness#947)
#
# The teardown sweep used to re-read PHASE_LOOP_CONFORM_TIMING. A test that was
# measured and then DELETED the flag skipped the sweep entirely; fixture undo
# then restored both the flag and the wrapper, and the next measured test wrapped
# a wrapper so both layers counted the same operation. The symptom is a silent
# double count, not a crash, so these assert COUNTER VALUES -- a clean run does
# not disprove this one.
# ---------------------------------------------------------------------------


class _Seam:
    """One wrapped symbol, with a way to exercise it exactly once."""

    def __init__(self, name, get, set_value, exercise, counter):
        self.name = name
        self.get = get
        self.set_value = set_value
        self.exercise = exercise
        self.counter = counter

    def __repr__(self) -> str:  # pragma: no cover - test ids only
        return self.name


def _exercise_popen(tmp_path):
    _spawn_and_wait()


def _exercise_copytree(tmp_path):
    source = tmp_path / f"src-{len(list(tmp_path.iterdir()))}"
    (source / "inner").mkdir(parents=True)
    (source / "inner" / "f.txt").write_text("x", encoding="utf-8")
    shutil.copytree(source, tmp_path / f"dst-{source.name}")


def _exercise_rmtree(tmp_path):
    victim = tmp_path / f"victim-{len(list(tmp_path.iterdir()))}"
    victim.mkdir()
    (victim / "f.txt").write_text("x", encoding="utf-8")
    shutil.rmtree(victim)


def _exercise_extractall(tmp_path):
    index = len(list(tmp_path.iterdir()))
    payload = tmp_path / f"p{index}.txt"
    payload.write_text("x", encoding="utf-8")
    archive_path = tmp_path / f"a{index}.tar"
    with tarfile.open(archive_path, "w") as archive:
        archive.add(payload, arcname="f.txt")
    with tarfile.open(archive_path) as archive:
        archive.extractall(tmp_path / f"out{index}")


def _exercise_read_bytes(tmp_path):
    target = tmp_path / "read-bytes.txt"
    target.write_text("payload", encoding="utf-8")
    assert target.read_bytes() == b"payload"


def _exercise_read_text(tmp_path):
    target = tmp_path / "read-text.txt"
    target.write_text("payload", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "payload"


SEAMS = [
    _Seam("subprocess.Popen", lambda: subprocess.Popen,
          lambda v: setattr(subprocess, "Popen", v), _exercise_popen, "child_processes"),
    _Seam("shutil.copytree", lambda: shutil.copytree,
          lambda v: setattr(shutil, "copytree", v), _exercise_copytree, "copytree_calls"),
    _Seam("shutil.rmtree", lambda: shutil.rmtree,
          lambda v: setattr(shutil, "rmtree", v), _exercise_rmtree, "rmtree_calls"),
    _Seam("tarfile.TarFile.extractall", lambda: tarfile.TarFile.extractall,
          lambda v: setattr(tarfile.TarFile, "extractall", v), _exercise_extractall,
          "tar_extractall_calls"),
    _Seam("pathlib.Path.read_bytes", lambda: Path.read_bytes,
          lambda v: setattr(Path, "read_bytes", v), _exercise_read_bytes, "path_read_calls"),
    _Seam("pathlib.Path.read_text", lambda: Path.read_text,
          lambda v: setattr(Path, "read_text", v), _exercise_read_text, "path_read_calls"),
]


def _run_call_phase(timing, nodeid, during=None):
    """Drive the call hookwrapper exactly as pytest does."""
    item = types.SimpleNamespace(nodeid=nodeid)
    generator = timing.pytest_runtest_call(item)
    next(generator)
    captured = during() if during is not None else None
    with pytest.raises(StopIteration):
        generator.send(None)
    return item, captured


def _run_teardown_phase(timing, item, during=None):
    """Drive the teardown hookwrapper; `during` stands in for fixture undo."""
    generator = timing.pytest_runtest_teardown(item, None)
    next(generator)
    if during is not None:
        during()
    with pytest.raises(StopIteration):
        generator.send(None)


def _counter_delta_for_one_exercise(timing, seam, tmp_path):
    """Install a fresh measured scope, exercise the seam once, return the count."""
    recorder = timing._ConformTimingRecorder(f"probe::{seam.name}")
    restore = timing._conform_timing_install(recorder)
    try:
        seam.exercise(tmp_path)
    finally:
        restore()
    return recorder.counters.get(seam.counter, 0)


@pytest.mark.parametrize("seam", SEAMS, ids=lambda seam: seam.name)
def test_deleting_the_flag_mid_test_cannot_leave_a_double_counting_wrapper(
    timing, monkeypatch, tmp_path, seam
):
    """Codex's sequence, measured: the next test must count the operation ONCE."""
    with _as_the_outermost_scope(timing):
        monkeypatch.setenv(timing._CONFORM_TIMING_ENV, "1")
        # Under a flag-set session `entry` is the session's own wrapper; the
        # sweep is required to leave the IMPORT-TIME value, which is the only
        # predecessor that cannot have expired.
        entry = seam.get()
        expected = timing._CONFORM_PRISTINE[seam.name]
        try:
            def delete_the_flag_mid_test():
                saved_by_monkeypatch = seam.get()
                monkeypatch.delenv(timing._CONFORM_TIMING_ENV, raising=False)
                return saved_by_monkeypatch

            item, wrapper = _run_call_phase(
                timing, "probe::flag_deleted", delete_the_flag_mid_test
            )
            assert wrapper is not entry, "the call phase must have installed a wrapper"
            assert seam.get() is entry, "the call phase must restore before teardown"

            def fixture_undo():
                # monkeypatch restores BOTH what it saved and the environment.
                seam.set_value(wrapper)
                monkeypatch.setenv(timing._CONFORM_TIMING_ENV, "1")

            _run_teardown_phase(timing, item, fixture_undo)

            assert seam.get() is expected, (
                f"{seam.name} survived teardown; the sweep re-read the flag"
            )
            assert _counter_delta_for_one_exercise(timing, seam, tmp_path) == 1, (
                f"{seam.name} counted the operation more than once"
            )
        finally:
            seam.set_value(entry)


@pytest.mark.parametrize("seam", SEAMS, ids=lambda seam: seam.name)
def test_setting_the_flag_mid_test_cannot_leave_a_double_counting_wrapper(
    timing, monkeypatch, tmp_path, seam
):
    """The mirror: unset at call start, set mid-test, nothing installed to leak."""
    with _as_the_outermost_scope(timing):
        monkeypatch.delenv(timing._CONFORM_TIMING_ENV, raising=False)
        entry = seam.get()
        try:
            def set_the_flag_mid_test():
                monkeypatch.setenv(timing._CONFORM_TIMING_ENV, "1")
                return seam.get()

            item, during = _run_call_phase(
                timing, "probe::flag_set", set_the_flag_mid_test
            )
            assert during is entry, "an unset flag at call start must install nothing"
            _run_teardown_phase(timing, item)

            # Nothing was installed, so nothing was retired and nothing is swept.
            assert seam.get() is entry
            assert _counter_delta_for_one_exercise(timing, seam, tmp_path) == 1
        finally:
            seam.set_value(entry)


def test_a_surviving_layer_cannot_double_count_even_if_one_is_left_installed(
    timing, tmp_path
):
    """Second defence: the per-seam guard, with a layer deliberately left behind."""
    with _as_the_outermost_scope(timing):
        leaked = timing._ConformTimingRecorder("probe::leaked_layer")
        leak_restore = timing._conform_timing_install(leaked)
        stale = _current_identities()
        timing._CONFORM_RECORDER_STACK.clear()  # orphan the layer, leave it bound
        timing._CONFORM_RETIRED_BINDINGS.clear()
        assert _current_identities() == stale, "the stale layer must still be bound"

        recorder = timing._ConformTimingRecorder("probe::over_a_leak")
        restore = timing._conform_timing_install(recorder)
        try:
            for seam in SEAMS:
                seam.exercise(tmp_path)
        finally:
            restore()
            timing._CONFORM_RECORDER_STACK.append(leaked)
            leak_restore()

        for seam in SEAMS:
            assert recorder.counters.get(seam.counter, 0) >= 1, seam.name
        assert recorder.counters["copytree_calls"] == 1
        assert recorder.counters["rmtree_calls"] == 1
        assert recorder.counters["tar_extractall_calls"] == 1
        assert recorder.counters["child_processes"] == 1
        # read_bytes and read_text each counted once, and nothing counted twice.
        assert recorder.counters["path_read_calls"] == 2
        assert not leaked.counters, leaked.counters


# ---------------------------------------------------------------------------
# Composition of two patch arrangements (board round 4, agent-harness#947)
#
# The wrapper-resurrection case and the independent-fixture case were each
# covered, but never COMPOSED. When `monkeypatch` initialises before a fixture
# that installs its own replacement F, the sweep used to restore the value
# captured at install -- which is F -- after F's own fixture had already torn
# down, leaking an expired object into every later test. It is durable: the next
# install captures F as its own predecessor, so nothing ever puts the original
# back.
#
# These assert on the symbol observed in a LATER test's SETUP phase, because a
# leak is invisible inside the test that creates it.
# ---------------------------------------------------------------------------

PRISTINE_AT_IMPORT = {
    "subprocess.Popen": subprocess.Popen,
    "pathlib.Path.read_bytes": Path.read_bytes,
}
_SYMBOL_AT_SETUP: dict[str, object] = {}


def _compose_fixture_then_wrapper(timing, monkeypatch, name, get, set_value):
    """Run codex's six-step sequence and return the symbol the sweep left.

    `entry` is whatever is bound when this test starts, which under a flag-set
    session is the session's own wrapper; it is put back at the end so the
    session's accounting is undisturbed. The value the sweep OUGHT to leave is
    the import-time original, which is the only predecessor that cannot expire.
    """
    entry = get()
    expected = timing._CONFORM_PRISTINE[name]
    foreign = (
        type("ForeignPopen", (expected,), {})
        if name == "subprocess.Popen"
        else (lambda self, *a, **k: expected(self, *a, **k))
    )
    with _as_the_outermost_scope(timing):
        set_value(foreign)  # 1. an independent fixture installs F over the original
        try:
            monkeypatch.setenv(timing._CONFORM_TIMING_ENV, "1")
            # 2. the instrumentation installs W, capturing F as its predecessor.
            # 3. the test's monkeypatch saves W.
            item, wrapper = _run_call_phase(
                timing, f"probe::composed::{name}", during=get
            )
            assert wrapper is not foreign, "the call phase must have installed a wrapper"
            assert get() is foreign, "4. call cleanup restores F, which is still live"

            def teardown_order():
                set_value(expected)  # 5a. the independent fixture restores the original
                set_value(wrapper)   # 5b. monkeypatch.undo restores W

            _run_teardown_phase(timing, item, teardown_order)  # 6. the sweep
            left = get()
        finally:
            # Deliberately NOT restored here. If the sweep left an expired
            # object, the next test must be able to observe it in its own setup
            # phase, which is where a leak of this shape actually shows. The
            # follower below restores.
            pass
    return left, foreign, expected, entry


def test_zzc_composed_popen_does_not_leak_an_expired_fixture_patch(timing, monkeypatch):
    left, foreign, expected, _entry = _compose_fixture_then_wrapper(
        timing, monkeypatch, "subprocess.Popen",
        lambda: subprocess.Popen, lambda v: setattr(subprocess, "Popen", v),
    )
    assert left is not foreign, "the sweep restored an expired fixture replacement"
    assert left is expected


def test_zzc_composed_read_bytes_does_not_leak_an_expired_fixture_patch(
    timing, monkeypatch
):
    left, foreign, expected, _entry = _compose_fixture_then_wrapper(
        timing, monkeypatch, "pathlib.Path.read_bytes",
        lambda: Path.read_bytes, lambda v: setattr(Path, "read_bytes", v),
    )
    assert left is not foreign, "the sweep restored an expired fixture replacement"
    assert left is expected


@pytest.fixture
def _record_symbols_at_setup(request):
    """Observe the symbols BEFORE this test's own call phase can install over them."""
    _SYMBOL_AT_SETUP[request.node.name] = {
        "subprocess.Popen": subprocess.Popen,
        "pathlib.Path.read_bytes": Path.read_bytes,
    }
    yield


def test_zzd_a_later_test_sees_clean_symbols_in_its_setup_phase(
    _record_symbols_at_setup, request
):
    """Where the leak is actually visible: a subsequent test's setup phase."""
    observed = _SYMBOL_AT_SETUP[request.node.name]
    try:
        for name, value in observed.items():
            assert value is PRISTINE_AT_IMPORT[name], (
                f"{name} was left as {value!r} by an earlier test"
            )
    finally:
        # Put the session back however the check went, so one leak does not
        # cascade through the rest of the module.
        for name, value in PRISTINE_AT_IMPORT.items():
            SYMBOL_SETTERS[name](value)


def test_read_seams_do_not_conflate_characters_with_bytes(timing, tmp_path):
    """A ten-byte, five-character file, read once through each seam.

    `read_bytes` returns bytes and `read_text` returns str, so `len` means a
    different thing at each seam. Recording both under one `path_read_bytes`
    counter conflated them: this file would report 15 there, ten real bytes plus
    five mislabelled characters. The counters must separate, and this fails if
    the split is not actually installed -- which is the point, because an edit
    tool reporting success is not evidence that a file changed.
    """
    target = tmp_path / "multibyte.txt"
    target.write_text("é" * 5, encoding="utf-8")
    assert len(target.read_bytes()) == 10, "fixture must be 10 bytes"
    assert len(target.read_text(encoding="utf-8")) == 5, "fixture must be 5 characters"

    recorder = timing._ConformTimingRecorder("probe::read_units")
    restore = timing._conform_timing_install(recorder)
    try:
        target.read_bytes()
        target.read_text(encoding="utf-8")
    finally:
        restore()

    assert recorder.counters["path_read_calls"] == 2
    assert recorder.counters["path_read_bytes"] == 10, recorder.counters
    assert recorder.counters["path_read_chars"] == 5, recorder.counters
    assert recorder.counters["path_read_bytes"] != 15, "the seams are still conflated"
