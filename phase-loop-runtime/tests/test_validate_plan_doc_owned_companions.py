"""agent-harness#1304: check (R) warns on owned-file under-enumeration (Pattern A).

Commit 47c772b4 records what planners omitted in ~70% of phases of the 2026-05-25 drive:
test files, snapshots, generated migrations, env examples, lockfiles. The executor then
dirtied paths no lane owned and the closeout failed closed. Check (R) names each tracked
companion that no lane owns. It is a WARN until there is false-positive data to promote it.

The negative control is the Pattern A reconstruction below: the plan owns only the headline
files, and (R) must name every omitted category. The correctly enumerated plan must be silent.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from .phase_loop_test_utils import make_repo

BUNDLE = Path(__file__).resolve().parents[1] / "src" / "phase_loop_runtime" / "skills_bundle"
PLAN_VALIDATOR = BUNDLE / "claude-plan-phase" / "scripts" / "validate_plan_doc.py"


def _load():
    name = "validate_plan_doc_owned_companions_1304"
    spec = importlib.util.spec_from_file_location(name, PLAN_VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


V = _load()

# A Next.js + Supabase app shaped like the 2026-05-25 drive's targets.
TRACKED = [
    "package.json",
    "pnpm-lock.yaml",
    ".env.example",
    "src/lib/billing.ts",
    "src/lib/billing.test.ts",
    "src/components/Invoice.tsx",
    "src/components/Invoice.test.tsx",
    "src/components/__snapshots__/Invoice.test.tsx.snap",
    "supabase/migrations/20260501000000_init.sql",
    "supabase/tests/init.test.sql",
]

LANE_BODY = "- **Scope**: bill invoices; reads `process.env.STRIPE_KEY`.\n"

PATTERN_A_OWNED = [
    "src/lib/billing.ts",
    "src/components/Invoice.tsx",
    "package.json",
    "supabase/migrations/20260525120000_add_invoices.sql",
]

CORRECT_OWNED = [
    "src/lib/billing.ts",
    "src/lib/billing.test.ts",
    "src/components/Invoice.tsx",
    "src/components/Invoice.test.tsx",
    "src/components/__snapshots__/Invoice.test.tsx.snap",
    "package.json",
    "pnpm-lock.yaml",
    ".env.example",
    "supabase/migrations/*_add_invoices.sql",
    "supabase/tests/invoices.test.sql",
]


def _check(owned, tracked=TRACKED, body=LANE_BODY):
    return V._check_r_owned_companions({"SL-1": {"owned_globs": owned}}, {"SL-1": body}, tracked)


def test_pattern_a_plan_warns_on_every_omitted_category():
    findings = _check(PATTERN_A_OWNED)

    assert all(f.startswith("(R) WARN:") for f in findings), findings
    joined = "\n".join(findings)
    for named in (
        "test file `src/lib/billing.test.ts`",
        "test file `src/components/Invoice.test.tsx`",
        "snapshot `src/components/__snapshots__/Invoice.test.tsx.snap`",
        "lockfile `pnpm-lock.yaml`",
        "env example `.env.example`",
        "own the glob `supabase/migrations/*_add_invoices.sql`",
        "`*.test.sql`",
    ):
        assert named in joined, (named, findings)
    assert len(findings) == 7, findings


def test_correctly_enumerated_plan_is_silent():
    assert _check(CORRECT_OWNED) == []


def test_companions_owned_by_another_lane_count():
    # The closeout check is phase-level, so ownership by any lane satisfies it.
    lanes = {
        "SL-1": {"owned_globs": ["src/lib/billing.ts"]},
        "SL-2": {"owned_globs": ["src/lib/*.test.ts"]},
    }
    assert V._check_r_owned_companions(lanes, {}, TRACKED) == []


def test_glob_semantics_match_the_closeout():
    # fnmatchcase `*` crosses `/`, and a trailing `/` owns the subtree.
    assert _check(["src/lib/billing.ts", "src/*.test.ts"], body="") == []
    assert _check(["src/components/Invoice.tsx", "src/components/"], body="") == []


def test_silent_without_repo_evidence():
    # No tracked companions: nothing in this repo makes the categories relevant.
    assert _check(PATTERN_A_OWNED[:3], tracked=["src/lib/billing.ts", "package.json"]) == []


def test_env_example_needs_an_env_shape_signal():
    findings = _check(CORRECT_OWNED[:-3] + ["supabase/migrations/*_x.sql", "supabase/tests/x.test.sql"], body="")
    assert findings == []
    findings = _check([p for p in CORRECT_OWNED if p != ".env.example"])
    assert findings == [
        "(R) WARN: SL-1 changes env shape but no lane owns its env example `.env.example` "
        "— add it to `Owned files` (the closeout fails closed on unowned dirty paths)"
    ]


def test_python_layout_and_closest_test_wins():
    tracked = [
        "pkg-a/src/pkg_a/utils.py",
        "pkg-a/tests/test_utils.py",
        "pkg-b/tests/test_utils.py",
        "pkg-a/pyproject.toml",
        "uv.lock",
    ]
    findings = _check(["pkg-a/src/pkg_a/utils.py", "pkg-a/pyproject.toml"], tracked=tracked, body="")
    assert len(findings) == 2, findings
    assert "test file `pkg-a/tests/test_utils.py`" in findings[0]
    assert "lockfile `uv.lock`" in findings[1]  # nearest ancestor lockfile
    assert _check(
        ["pkg-a/src/pkg_a/utils.py", "pkg-a/tests/test_utils.py", "pkg-a/pyproject.toml", "uv.lock"],
        tracked=tracked,
        body="",
    ) == []


def test_new_module_with_no_owned_test_path_warns_once():
    tracked = ["src/old.py", "tests/test_old.py"]
    findings = _check(["src/new.py", "src/other.py"], tracked=tracked, body="")
    assert len(findings) == 1, findings
    assert "owns code (`src/new.py`) but no lane owns any test path" in findings[0]
    assert _check(["src/new.py", "tests/test_new.py"], tracked=tracked, body="") == []


def test_validator_cli_emits_r_as_warnings_only(tmp_path):
    repo = make_repo(tmp_path)
    for rel in TRACKED:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    owned = ", ".join(f"`{p}`" for p in PATTERN_A_OWNED)
    plan = repo / "plans" / "phase-plan-v1-PA.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "# PA: billing\n\n## Lane Index & Dependencies\n\nSL-1 — Billing\n  Depends on: (none)\n"
        "  Blocks: (none)\n  Parallel-safe: yes\n\n## Lanes\n\n### SL-1 — Billing\n\n"
        f"{LANE_BODY}- **Owned files**: {owned}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(PLAN_VALIDATOR), str(plan)], cwd=repo, capture_output=True, text=True
    )

    r_lines = [line for line in result.stderr.splitlines() if line.startswith("(R)")]
    assert len(r_lines) == 7, result.stderr
    assert all("WARN" in line for line in r_lines)


# --- board round 1 (agent-harness#1322) ---------------------------------------------


def test_board_f001_two_lanes_writing_migrations_get_one_consolidation_warning():
    # Per-lane globs in one migrations dir share a literal prefix, which the lane IR
    # refuses as overlapping_write_ownership. (R) must not advise that.
    from phase_loop_runtime.plan_ir import _patterns_overlap_any

    lanes = {
        "SL-1": {"owned_globs": ["supabase/migrations/20260601000000_add_a.sql"]},
        "SL-2": {"owned_globs": ["supabase/migrations/20260601000001_add_b.sql"]},
    }
    findings = V._check_r_owned_companions(lanes, {}, ["supabase/migrations/20260501000000_init.sql"])
    assert not any("own the glob" in f for f in findings), findings
    assert findings == [
        "(R) WARN: SL-1, SL-2 each write new migrations under `supabase/migrations/`; the generator "
        "picks the timestamps and per-lane globs there overlap under the lane IR — move migration "
        "authoring into one lane (or a preamble lane) that owns `supabase/migrations/*_*.sql`"
    ]
    assert not _patterns_overlap_any(("supabase/migrations/*_*.sql",), ())


def test_board_f002_closeout_sibling_expansion_counts_as_owned():
    tracked = [
        "src/lib/billing.ts",
        "src/lib/__tests__/billing.test.ts",
        "src/lib/__fixtures__/billing.json",
        "vendor/mod/src/mod/core.py",
        "vendor/mod/tests/test_core.py",
    ]
    assert _check(["src/lib/billing.ts", "vendor/mod/src/mod/core.py"], tracked=tracked, body="") == []


def test_board_f003_a_same_named_test_sharing_no_directory_is_ignored():
    tracked = ["scripts/index.ts", "packages/x/src/index.test.ts", "packages/x/src/x.test.ts"]
    assert _check(["scripts/index.ts", "packages/x/src/x.test.ts"], tracked=tracked, body="") == []
    # A repo-root module still finds its top-level tests dir.
    findings = _check(["setup.py", "tests/test_other.py"], tracked=["setup.py", "tests/test_setup.py"], body="")
    assert [f for f in findings if "tests/test_setup.py" in f], findings


def test_board_f004_editing_a_tracked_migration_is_not_a_generator_warning():
    tracked = ["supabase/migrations/20260501000000_init.sql"]
    assert _check(["supabase/migrations/20260501000000_init.sql"], tracked=tracked, body="") == []


def test_board_f005_a_bracketed_route_is_a_concrete_path():
    tracked = ["app/[id]/page.tsx", "app/[id]/page.test.tsx"]
    findings = _check(["app/[id]/page.tsx"], tracked=tracked, body="")
    assert len(findings) == 1 and "test file `app/[id]/page.test.tsx`" in findings[0], findings
    assert _check(["app/[id]/page.tsx", "app/[id]/page.test.tsx"], tracked=tracked, body="") == []
