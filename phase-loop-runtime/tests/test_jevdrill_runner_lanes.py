"""JEVHOST §4 S4: an adapter run never takes the lane-wave branch.

``main``'s lane workers build their own launch requests and would not pass through the
JEV Drill adapter. With an adapter, ``run_loop`` takes the whole-phase path through
``launch_jevdrill`` whatever ``lane_scheduler_mode`` is, and records the bypass as one
``lane_scheduler`` event with reason ``jevdrill_adapter``. With no adapter, the lane-wave
path is as on ``main``.
"""
import pytest

from phase_loop_runtime import lane_wave_executor as lanes
from phase_loop_runtime import runner
from phase_loop_runtime.events import read_events
from phase_loop_runtime.models import PromptBundle
from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan
from test_phase_loop_wave_runner import _concurrent_wave_body


@pytest.fixture(autouse=True)
def deterministic_runner_capacity(monkeypatch):
    from phase_loop_runtime.lane_capacity import LaneCapacity
    monkeypatch.setattr("phase_loop_runtime.lane_capacity.memory_capacity",
                        lambda ceiling, budget: LaneCapacity(ceiling, ceiling, "available", 2 * 1024**3))


class Witness:
    """A pass-through adapter that records each entry."""

    def __init__(self):
        self.prepared, self.launched = [], []

    def prepare(self, *, mode, dry_run, **kwargs):
        self.prepared.append(mode)
        return kwargs

    def launch(self, launch, spec, **kwargs):
        self.launched.append(spec)
        return launch(spec, **kwargs)


def planned_phase(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "RUNNER", roadmap, body=_concurrent_wave_body())
    commit_fixture_paths(repo, "fixture", plan)
    monkeypatch.setattr(runner, "build_prompt", lambda *a, **k: PromptBundle("fake", "fixture", "context_file"))
    waves = []

    def execute(**kwargs):
        waves.append(kwargs)
        return lanes.LaneExecutionResult("preview", "ready", {})

    monkeypatch.setattr(lanes, "execute_lane_waves", execute)
    return repo, roadmap, waves


def lane_scheduler_events(repo):
    return [event["metadata"]["lane_scheduler"] for event in read_events(repo)
            if isinstance(event.get("metadata"), dict) and "lane_scheduler" in event["metadata"]]


def test_adapter_run_bypasses_lane_waves_under_the_default_mode(tmp_path, monkeypatch):
    repo, roadmap, waves = planned_phase(tmp_path, monkeypatch)
    adapter = Witness()
    runner.run_loop(repo, roadmap, phase="RUNNER", dry_run=True, jevdrill_adapter=adapter)
    assert waves == []
    assert adapter.prepared == ["main"]
    assert len(adapter.launched) == 1
    bypass = [row for row in lane_scheduler_events(repo) if row.get("reason") == "jevdrill_adapter"]
    assert len(bypass) == 1
    assert bypass[0]["requested_mode"] == "concurrent" and bypass[0].get("lane_id") is None


@pytest.mark.parametrize("mode", ["serialized", "concurrent"])
def test_adapter_run_bypasses_lane_waves_for_each_lane_mode(tmp_path, monkeypatch, mode):
    repo, roadmap, waves = planned_phase(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "_launch_ready_lane_wave",
                        lambda **_k: pytest.fail("an adapter run must not take the serialized lane path"))
    adapter = Witness()
    runner.run_loop(repo, roadmap, phase="RUNNER", dry_run=True, lane_scheduler_mode=mode,
                    jevdrill_adapter=adapter)
    assert waves == []
    assert adapter.prepared == ["main"] and len(adapter.launched) == 1
    reasons = [row.get("reason") for row in lane_scheduler_events(repo)]
    assert reasons.count("jevdrill_adapter") == 1


def test_no_adapter_keeps_the_lane_wave_path(tmp_path, monkeypatch):
    repo, roadmap, waves = planned_phase(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "launch_with_spec", lambda *a, **k: pytest.fail("no whole-phase launch"))
    runner.run_loop(repo, roadmap, phase="RUNNER", dry_run=True)
    assert len(waves) == 1 and waves[0]["max_workers"] == 4
    assert all(row.get("reason") != "jevdrill_adapter" for row in lane_scheduler_events(repo))
