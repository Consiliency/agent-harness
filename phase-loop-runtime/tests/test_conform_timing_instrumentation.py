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
    assert recorder.counters["child_output_bytes"] == len(first_stdout)
    assert process_events[0]["out_bytes"] == len(first_stdout)


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
    assert _current_identities() == before, dict(
        zip(WRAPPED_SYMBOLS, _current_identities())
    )


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
