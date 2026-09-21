"""Falsifiers for the opt-in CONFORM phase timing (Consiliency/agent-harness#945).

Board review of agent-harness#947 raised four properties that the instrumentation
asserts about itself but never checked. Each is checked here.

The module deliberately keeps ``outside_agent`` out of every node id so the
CONFORM ``-k outside_agent`` lifecycle corpus is unchanged.
"""
from __future__ import annotations

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


def _drive_hook(item) -> None:
    """Run the hookwrapper to completion exactly as pytest would."""
    generator = timing.pytest_runtest_call(item)
    next(generator)
    with pytest.raises(StopIteration):
        generator.send(None)


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
