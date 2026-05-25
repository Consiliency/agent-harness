from __future__ import annotations

from phase_loop_runtime.pipeline_adapter.flag import branchgov_enabled


def test_branchgov_flag_unset_is_enabled(monkeypatch):
    monkeypatch.delenv("PHASE_LOOP_BRANCHGOV_ENABLE", raising=False)

    assert branchgov_enabled() is True


def test_branchgov_flag_exact_true_is_enabled(monkeypatch):
    monkeypatch.setenv("PHASE_LOOP_BRANCHGOV_ENABLE", "true")

    assert branchgov_enabled() is True


def test_branchgov_flag_exact_false_is_disabled(monkeypatch):
    monkeypatch.setenv("PHASE_LOOP_BRANCHGOV_ENABLE", "false")

    assert branchgov_enabled() is False


def test_branchgov_flag_non_canonical_values_are_enabled(monkeypatch):
    for value in ("True", "1", "yes", ""):
        monkeypatch.setenv("PHASE_LOOP_BRANCHGOV_ENABLE", value)

        assert branchgov_enabled() is True
