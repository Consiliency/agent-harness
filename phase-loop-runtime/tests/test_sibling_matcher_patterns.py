from __future__ import annotations

from phase_loop_runtime.pipeline_adapter.sibling_matcher import validate_phase_owned_evidence


def _accepted(declared, actual, evidence):
    return {item["path"]: item["kind"] for item in validate_phase_owned_evidence(declared, actual, evidence)}


def test_accepts_matching_tests_and_snapshots():
    declared = ("src/lib/feature.ts",)
    actual = (
        "src/lib/feature.ts",
        "src/lib/__tests__/feature.test.ts",
        "src/lib/__snapshots__/feature.snap",
    )

    accepted = _accepted(declared, actual, ["src/lib/__tests__/feature.test.ts", "src/lib/__snapshots__/feature.snap"])

    assert accepted == {
        "src/lib/__tests__/feature.test.ts": "test",
        "src/lib/__snapshots__/feature.snap": "snapshot",
    }


def test_accepts_migration_timestamp_peer_and_package_lock():
    declared = ("supabase/migrations/20260525010101_create_table.sql", "app/package.json")
    actual = (
        "supabase/migrations/20260525010101_create_table.sql",
        "supabase/migrations/20260525010101_test.sql",
        "app/package-lock.json",
    )

    accepted = _accepted(
        declared,
        actual,
        [
            {"path": "supabase/migrations/20260525010101_test.sql"},
            {"path": "app/package-lock.json"},
        ],
    )

    assert accepted == {
        "supabase/migrations/20260525010101_test.sql": "migration_timestamp",
        "app/package-lock.json": "package_lock",
    }


def test_accepts_env_example_for_env_source():
    declared = ("src/env.ts",)
    actual = ("src/env.ts", "src/.env.example")

    accepted = _accepted(declared, actual, ["src/.env.example"])

    assert accepted == {"src/.env.example": "env_example"}


def test_rejects_unrelated_or_non_actual_evidence():
    declared = ("src/lib/feature.ts",)
    actual = ("src/lib/feature.ts", "src/lib/__tests__/other.test.ts")

    accepted = validate_phase_owned_evidence(
        declared,
        actual,
        ["src/lib/__tests__/other.test.ts", "src/lib/__tests__/feature.test.ts"],
    )

    assert accepted == ()
