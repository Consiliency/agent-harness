# Update to phase-loop 0.7.9 and run a roadmap — outside-worker instructions

Use **0.7.9** (not 0.7.8) — it contains the plan-checker fix that lets multi-lane
roadmaps run without being rejected at plan time.

## What this is (and isn't)

phase-loop is an **orchestration runner**: you give it a **roadmap** (a plan document)
and it plans + executes each phase in turn, handing the actual work to an AI executor.

It does **NOT** scan or "digest" your repository into a spec. There is **no big
first-time ingestion grind** — it only runs the roadmap you give it. (Repo→spec
transformation is a separate capability that is not shipped yet.) So the first run is
just "plan the first phase, execute it" — fast, not a corpus-wide crawl.

## 1. Update

If you install the runtime directly:

```bash
pip install --upgrade "phase-loop-runtime==0.7.9"
# or via the friendly-name shim (pulls the latest runtime automatically):
pip install --upgrade consiliency-harness
```

If you use the fleet install script, re-run it — it now pins to `v0.7.9`:

```bash
scripts/install-agent-harness.sh      # (or your fleet manager's equivalent)
```

Verify:

```bash
python -c "import phase_loop_runtime as p; print(p.__version__)"   # -> 0.7.9
phase-loop --version                                               # -> 0.7.9
```

## 2. Two settings you MUST set before running a governed roadmap

The runner will falsely flag a phase as "dirty" if pytest leaves cache files behind
(a known issue being fixed properly later). Prevent the caches at the source — set
these in the phase's execution environment:

```bash
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS="-p no:cacheprovider"
```

(If a roadmap already bakes these into its phase env — e.g. the SPECCONFORM roadmap —
you don't need to set them by hand.)

## 3. Run the phases ONE AT A TIME

Do **not** pass `--lane-scheduler concurrent` — parallel multi-lane dispatch is
separately broken (it starts with an empty file-ownership contract and fails closed).
Run lanes serially. Plan and execute each phase in turn:

```bash
/claude-plan-phase   <PHASE-ALIAS>     # produce the phase plan
/claude-execute-phase <phase-alias>    # execute it
```

Phases with no shared dependency in the roadmap's DAG can be done in either order, but
run each one's lanes serially.

## What's fixed in 0.7.9 vs 0.7.8

- **0.7.8** added the cross-repo run-train broker (the convergence live path).
- **0.7.9** adds the plan-validator fix (#182): a plan that consumes an interface from
  another lane must now name that lane in `Depends on` — the checker catches it at plan
  time instead of the run failing partway through.

## Known limitations (handle if you hit them — not first-run blockers)

- Don't run with an explicit `--phase X` while a *different* phase is blocked (it may
  repair the blocked one instead — #84).
- Avoid editing a roadmap mid-run; amendments that change phase wording can confuse
  status (#85). Amend at a clean stopping point.
- Resuming after an interrupted session may need a manual `reconcile` (#90).
