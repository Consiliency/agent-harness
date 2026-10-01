import pytest

from phase_loop_runtime import plan_manifest as pm


def test_append_entry_refuses_existing_null_manifest(tmp_path):
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "probe.md").write_text("# Probe\n", encoding="utf-8")
    manifest = plans / "manifest.json"
    before = b"null\n"
    manifest.write_bytes(before)
    assert not pm.validate_manifest(manifest).valid
    entry = pm.DotfilesPlanEntry(
        slug="probe",
        file="plans/probe.md",
        type="detailed",
        status="committed",
        created_at="2026-09-29T00:00:00Z",
        updated_at="2026-09-29T00:00:00Z",
        owner_skill="codex-plan-detailed",
        task_summary="Probe",
        acceptance_criteria_count=1,
    )

    with pytest.raises(ValueError, match="manifest must be an object"):
        pm.append_entry(tmp_path, entry)
    assert manifest.read_bytes() == before
