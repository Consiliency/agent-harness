from __future__ import annotations

from pathlib import Path

from phase_loop_runtime.pipeline_adapter.markers import detect_pipeline_mode


def test_no_pipeline_markers_is_standalone(tmp_path, monkeypatch):
    monkeypatch.delenv("PHASE_LOOP_PIPELINE_MODE", raising=False)

    assert detect_pipeline_mode(tmp_path) is False


def test_pipeline_directory_marker_enables_pipeline_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("PHASE_LOOP_PIPELINE_MODE", raising=False)
    (tmp_path / ".pipeline").mkdir()

    assert detect_pipeline_mode(tmp_path) is True


def test_pipeline_bootstrap_workflow_marker_enables_pipeline_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("PHASE_LOOP_PIPELINE_MODE", raising=False)
    workflow = tmp_path / ".github" / "workflows" / "pipeline-bootstrap.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: pipeline bootstrap\n", encoding="utf-8")

    assert detect_pipeline_mode(tmp_path) is True


def test_pipeline_env_marker_exact_true_enables_pipeline_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("PHASE_LOOP_PIPELINE_MODE", "true")

    assert detect_pipeline_mode(tmp_path) is True


def test_combined_file_markers_enable_pipeline_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("PHASE_LOOP_PIPELINE_MODE", raising=False)
    (tmp_path / ".pipeline").mkdir()
    workflow = tmp_path / ".github" / "workflows" / "pipeline-bootstrap.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: pipeline bootstrap\n", encoding="utf-8")

    assert detect_pipeline_mode(tmp_path) is True


def test_non_true_pipeline_env_values_do_not_enable_pipeline_mode(tmp_path, monkeypatch):
    for value in ("True", "1", "yes", ""):
        monkeypatch.setenv("PHASE_LOOP_PIPELINE_MODE", value)

        assert detect_pipeline_mode(tmp_path) is False
