---
phase_loop_plan_version: 1
phase: HARDEN
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0
automation:
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      env PHASE_LOOP_TDD_EXPECT_HARDEN=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
      python3 -m pytest -q
      phase-loop-runtime/tests/test_advisor_board_advisory_mode.py
      phase-loop-runtime/tests/test_advisor_board_backcompat.py
      phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py
      phase-loop-runtime/tests/test_advisor_board_backing_omnigent.py
      phase-loop-runtime/tests/test_advisor_board_cli_legacy.py
      phase-loop-runtime/tests/test_advisor_board_composition.py
      phase-loop-runtime/tests/test_advisor_board_config.py
      phase-loop-runtime/tests/test_advisor_board_golden.py
      phase-loop-runtime/tests/test_advisor_board_integration.py
      phase-loop-runtime/tests/test_advisor_board_live_research.py
      phase-loop-runtime/tests/test_advisor_board_observability.py
      phase-loop-runtime/tests/test_advisor_board_presets.py
      phase-loop-runtime/tests/test_advisor_board_research.py
      phase-loop-runtime/tests/test_advisor_board_resolver.py
      phase-loop-runtime/tests/test_goal_coverage.py
      phase-loop-runtime/tests/test_harden_evidence_verifier.py
      phase-loop-runtime/tests/test_panel_invoker.py
      phase-loop-runtime/tests/test_panel_leg_failure_diagnostic.py
      phase-loop-runtime/tests/test_panel_native_fill_183.py
      phase-loop-runtime/tests/test_panel_streaming_verdicts.py
      phase-loop-runtime/tests/test_phase_loop_injection.py
      phase-loop-runtime/tests/test_ratification_policy.py
      phase-loop-runtime/tests/test_reconcile_portability_85c.py
      phase-loop-runtime/tests/test_review_leg_sandbox.py
      phase-loop-runtime/tests/test_verification_interpreter_guard_221.py;
      PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration";
      uv run --project phase-loop-runtime ruff check phase-loop-runtime/src/phase_loop_runtime phase-loop-runtime/scripts
---

# HARDEN: Security and Verification Hardening

## Context

HARDEN closes the five security and verification gaps named by EC-HARDEN-1 through
EC-HARDEN-5 while preserving the strict tests-first gate in EC-HARDEN-0. It starts only
from dependency-complete canonical main after FABPUB and the actual reviewed SCHED SL-2
handoff. REVIEWTRUTH remains downstream. No HARDEN lane implements SCHED, REVIEWTRUTH,
release, publication, or roadmap behavior.

The manifest's historical HARDEN contract and authority records remain immutable
provenance. Current authority is the last `plan_current_authority.v1` entry plus the
latest lifecycle authority metadata matching this plan and roadmap digest. They do not
prescribe future commit identities, counts, or topology.

## Interface Freeze Gates

- [ ] IF-0-HARDEN-1 — `HARDEN_TDD_CONTRACT`: SL-0 owns the exact 26-path test set below.
  With `PHASE_LOOP_TDD_EXPECT_HARDEN` absent, the repository is GREEN and only new
  capability assertions may skip. With it set to `1` before production, each collected
  case reaches exactly one deterministic marker:
  `HARDEN-RED-ANCHOR::staged-tree-containment`,
  `HARDEN-RED-ANCHOR::cwd-independent-reconcile`,
  `HARDEN-RED-ANCHOR::non-vacuous-goal-coverage`,
  `HARDEN-RED-ANCHOR::login-shell-interpreter`, or
  `HARDEN-RED-ANCHOR::review-leg-isolation`. Production exposes
  `HARDEN_CAPABILITY_VERSION = 1` only after every anchor is GREEN. No production lane
  edits SL-0.
- [ ] IF-0-HARDEN-2 — `HARDEN_REVIEW_ISOLATION`: every executable public-board route
  authorizes an operation-bound, credentialless Linux isolation plus
  `parent_unix_broker_v1` intended-inference-only contract before capability, auth,
  session, provider, broker, callback, or child effects; `invoke_board()` independently
  revalidates it. A supported subscription-auth route is any seat model that resolves
  through the advisor-board model registry to a model runnable by one of the four
  broker lanes (claude, codex, gemini, grok), in that lane's invocation form; the
  route table is derived from the registry and the fleet-default seats, never a
  model-id literal (a literal pins a moving input and silently downgrades or refuses
  fleet seats). Every other executable route satisfies the same invariant
  or refuses before effects. Pure parsing, static configuration, and explicitly
  injected hermetic controls remain auth-free and effect-free; no global/autouse shim
  or residual register satisfies this gate.
- [ ] IF-0-HARDEN-3 — `HARDEN_COMPLETION_EVIDENCE`: metadata-only
  `verification_evidence.v3` binds each source-entered falsifier and restored positive
  control, immutable SL-0 bytes, actual ancestry and changed paths, exact candidate and
  canonical-main heads/trees, fresh-process suite/JUnit digests, CI, four isolated
  brokered seats, resolved model IDs and harness provenance, and coordinator/author/
  reviewer independence. Only a fresh clean exact-head audit may append the normal
  completion ledger event.

## Lane Index & Dependencies

SL-0 — Immutable tests-only RED contract
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no
SL-1 — Staging and review-route isolation
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes
SL-2 — Reconciliation and verification fail-closed repairs
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes
SL-3 — Evidence, documentation, and whole-phase reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Immutable tests-only RED contract

- **Scope**: Land, review, and freeze the complete HARDEN falsifier set before production.
- **Owned files**: `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_advisor_board_advisory_mode.py`, `phase-loop-runtime/tests/test_advisor_board_backcompat.py`, `phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py`, `phase-loop-runtime/tests/test_advisor_board_backing_omnigent.py`, `phase-loop-runtime/tests/test_advisor_board_cli_legacy.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_advisor_board_config.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/test_advisor_board_integration.py`, `phase-loop-runtime/tests/test_advisor_board_live_research.py`, `phase-loop-runtime/tests/test_advisor_board_observability.py`, `phase-loop-runtime/tests/test_advisor_board_presets.py`, `phase-loop-runtime/tests/test_advisor_board_research.py`, `phase-loop-runtime/tests/test_advisor_board_resolver.py`, `phase-loop-runtime/tests/test_goal_coverage.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_panel_leg_failure_diagnostic.py`, `phase-loop-runtime/tests/test_panel_native_fill_183.py`, `phase-loop-runtime/tests/test_panel_streaming_verdicts.py`, `phase-loop-runtime/tests/test_phase_loop_injection.py`, `phase-loop-runtime/tests/test_ratification_policy.py`, `phase-loop-runtime/tests/test_reconcile_portability_85c.py`, `phase-loop-runtime/tests/test_review_leg_sandbox.py`, `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py`
- **Interfaces provided**: immutable HARDEN tests, named RED anchors, path-entered mutation controls.
- **Interfaces consumed**: actual reviewed `SCHED_HARDEN_HANDOFF` (pre-existing), pre-HARDEN behavior (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: Add the guard and exact EC-HARDEN-1..5 assertions. Default mode must be GREEN;
    activated pre-production runs must fail only at the named deterministic anchors,
    with no import, collection, skip, xfail, or unrelated failure accepted as RED.
  - test: Record raw output and JUnit for every activated anchor and a separate GREEN
    pure-control corpus. Bind the exact base, test landing, test blobs, plan, roadmap,
    manifest, and reviewer artifacts in metadata-only evidence.
  - impl: Land only these 26 paths. Obtain a fresh exact-head board verdict on that
    tests-only head before any production edit. A later test correction restarts SL-0.

### SL-1 — Staging and review-route isolation

- **Scope**: Turn staged-tree containment and every executable review route GREEN.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/__init__.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/resolver.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- **Interfaces provided**: hardened staging, public-route registry, operation-bound review authorization and independent invocation revalidation.
- **Interfaces consumed**: immutable HARDEN tests, `HARDEN_REVIEW_ISOLATION` (pre-existing).
- **Parallel-safe**: yes; write-disjoint from SL-2 after SL-0.
- **Tasks**:
  - test: Run the staged absolute-symlink escape and every public CLI/composition/
    config/preset/resolver/invoker positive, denial, forgery, crash, and cleanup arm.
  - impl: Reject staged roots, files, directories, and symlink chains that resolve
    outside the staged tree before launch. Authorize before composition side effects and
    revalidate at invocation. Give the untrusted leg only immutable snapshots,
    read-only tools, bounded argv/CWD/environment, and typed inference RPC; expose no
    live tree, ambient credential, direct egress, arbitrary provider method, host
    command, mutation credential, privileged side effect, or unjournaled cleanup.
  - impl: Preserve subscription authentication only. No API-key fallback, direct
    provider route, native bypass, or gateway/research bypass may satisfy a supported
    route. Preserve legacy and pure-control behavior under the no-global-shim rule.

### SL-2 — Reconciliation and verification fail-closed repairs

- **Scope**: Make path normalization, goal coverage, interpreter selection, and evidence serialization deterministic and fail closed.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`, `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`
- **Interfaces provided**: repo-anchored reconciliation, non-vacuous enforcement, fail-closed login-shell interpreter selection, evidence/ledger integration.
- **Interfaces consumed**: immutable HARDEN tests, SCHED ownership released by the actual handoff (pre-existing).
- **Parallel-safe**: yes; write-disjoint from SL-1 after SL-0.
- **Tasks**:
  - impl: Resolve automation artifact paths from repository authority, independent of
    ambient CWD, and preserve containment and normalization across fresh processes.
  - impl: In enforce mode, zero declared EC IDs is a non-human `contract_bug` at every
    completion gate; warn/default remains nonblocking and distinct.
  - impl: Parse and bind argument consumers `-o`, `+o`, `-O`, `+O`, `--rcfile`, and
    `--init-file` in split and joined forms. A profile-added interpreter version is
    rechecked and fails closed if it does not satisfy the requested constraint.
  - impl: Serialize source-entered falsifiers, exact heads/trees, model provenance,
    JUnit/CI/review digests, cleanup, and completion authority without raw secrets.

### SL-3 — Evidence, documentation, and whole-phase reducer

- **Scope**: Integrate producers, seal exact-head evidence, and reduce documentation without repairing producer files.
- **Owned files**: `phase-loop-runtime/scripts/verify_harden_evidence.py`, `CHANGELOG.md`
- **Interfaces provided**: HARDEN evidence verifier, completion ledger authority, user-facing security note.
- **Interfaces consumed**: immutable HARDEN tests, hardened staging, repo-anchored reconciliation, evidence/ledger integration.
- **Parallel-safe**: no.
- **Tasks**:
  - impl: Verify `verification_evidence.v3` independently from retained Git objects,
    canonical JSON, JUnit, CI, broker/probe, model/harness, and review artifacts. Reject
    stale heads, reused evidence, self-report, skipped cases, direct routes, synthetic
    votes, or non-biting mutations.
  - impl: In fresh clean worktrees, run focused activated, separate pure-control, broad,
    lint, CI, and four-seat candidate review; after landing repeat them on fetched
    canonical main. Back-fill the now-known canonical-main commit/tree and CI result
    into metadata-only evidence; never retain a placeholder. A material repair
    invalidates prior review and restarts the reducer.
  - impl: Append normal completion only after the final audit; keep
    `visual_render_declared=false`. Do not version, tag, release, publish, or dispatch
    REVIEWTRUTH.

## Execution Policy

- work-unit defaults: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- execute: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-3: effort=`high`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`

## Execution Notes

- One author vendor owns SL-0 through SL-3: Codex GPT-5.6 Terra at high effort. Both
  phase-loop schedulers stay off. The coordinator may use same-vendor workers only for
  the disjoint SL-1/SL-2 worktrees; author, coordinator, and exact-head reviewer roles
  remain independently attested.
- Before SL-0, run `SCHED_HARDEN_HANDOFF` verification below. Select the last
  handoff-bearing lifecycle event. Every earlier handoff-bearing event must retain
  `template_declared_actual_sl2_rebind_required` and null actual identities; do not
  require total cardinality one. The selected event must bind the actual reviewed SCHED
  atomic SL-2 plus SL-4 integration commit, reviewed head, tree, exact seven-path
  diff, current HARDEN/SCHED/roadmap digests, canonical receipt, and four usable
  `AGREE` reviews. `required_path_set` remains the exact six SL-2 overlap paths; the
  only admitted companion is SL-4's `phase_worktree_executor.py`, as required by
  `Consiliency/agent-harness#704`. An arbitrary 64-hex string, unreviewed object,
  stale plan, template, or other extra path cannot pass.
- SL-0 lands tests-only and receives exact-head board review. Production begins from
  that fetched landing; later production commits do not alter SL-0. SL-1 and SL-2 may
  proceed only after this boundary and must serialize with any external writer of their
  paths. SL-3 reduces after both.
- All external inference uses the subscription-authenticated harness and parent-owned
  narrow broker. Record resolved model IDs, harnesses, isolation attestations, and
  `api_fallback=false`. Never route directly to a provider API or expose credentials.
- Every material edit requires fresh exact-head review. Candidate and canonical-main
  evidence come from new processes and clean worktrees and bind Git, suite, JUnit, CI,
  model, broker, and reviewer facts. Planning state and transcripts are not authority.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: the 18 SL-1/SL-2 production paths, `phase-loop-runtime/scripts/verify_harden_evidence.py`, `CHANGELOG.md`
- evidence paths: `plans/phase-plan-v10-HARDEN.md`, `plans/manifest.json`, the 26 SL-0 paths, `.phase-loop/events.jsonl`, `.phase-loop/runs/**/verification.json`, `.phase-loop/runs/**/harden-*.json`, `.phase-loop/runs/**/harden-*.xml`
- redaction posture: `metadata_only`
- downstream handling: none; roadmap bytes remain unchanged and REVIEWTRUTH consumes canonical HARDEN completion

## Verification

Before SL-0, export exact full Git object IDs `SCHED_HARDEN_C` and `SCHED_HARDEN_R`, then run:

```bash
python3 - "$SCHED_HARDEN_C" "$SCHED_HARDEN_R" <<'PY'
import hashlib,json,subprocess,sys
from pathlib import Path
G=lambda *a:subprocess.check_output(["git","--no-replace-objects","-c","core.hooksPath=/dev/null",*a]).decode().strip()
B=lambda x,p:subprocess.check_output(["git","show",f"{x}:{p}"])
H=lambda b:hashlib.sha256(b).hexdigest()
C=lambda v:(json.dumps(v,sort_keys=True,separators=(",",":"))+"\n").encode()
D=lambda a,b:sorted(filter(None,G("diff-tree","--no-commit-id","--name-only","-r",a,b).splitlines()))
c=G("rev-parse",f"{sys.argv[1]}^{{commit}}"); r=G("rev-parse",f"{sys.argv[2]}^{{commit}}")
receipt=Path("plans","evidence","v10-SCHED-HARDEN-review.json").as_posix()
assert G("rev-list","--parents","-n","1",r).split()==[r,c] and D(c,r)==[receipt]
plan=Path("plans","phase-plan-v10-HARDEN.md").as_posix(); sched=Path("plans","phase-plan-v10-SCHED.md").as_posix(); roadmap=Path("specs","phase-plans-v10.md").as_posix(); manifest=Path("plans","manifest.json").as_posix()
m=json.loads(B(c,manifest)); row=[x for x in m["plans"] if x.get("phase_alias")=="HARDEN"]; assert len(row)==1
hs=[e["metadata"]["sched_harden_handoff"] for e in row[0]["lifecycle"] if isinstance(e.get("metadata"),dict) and "sched_harden_handoff" in e["metadata"]]
assert len(hs)>=2 and all(x["handoff_status"]=="template_declared_actual_sl2_rebind_required" and x["actual_sl2_commit"] is x["actual_sl2_reviewed_head"] is x["actual_sl2_tree"] is None for x in hs[:-1])
h=hs[-1]; paths=[Path("phase-loop-runtime","src","phase_loop_runtime",x).as_posix() for x in ("lane_scheduler.py","launcher.py","models.py","plan_ir.py","runner.py","worker_pool.py")]; companion=Path("phase-loop-runtime","src","phase_loop_runtime","phase_worktree_executor.py").as_posix(); integration_paths=sorted([*paths,companion]); seats=["native_codex","claude","gemini","grok"]
assert h["handoff_status"]=="candidate_awaiting_review" and h["required_path_set"]==paths and h["required_review_seats"]==seats
actual=G("rev-parse",f'{h["actual_sl2_commit"]}^{{commit}}'); reviewed=G("rev-parse",f'{h["actual_sl2_reviewed_head"]}^{{commit}}'); tree=G("rev-parse",f"{actual}^{{tree}}")
assert actual==h["actual_sl2_commit"] and reviewed==h["actual_sl2_reviewed_head"] and tree==h["actual_sl2_tree"]
p=G("rev-list","--parents","-n","1",actual).split(); assert len(p)==3 and p[2]==reviewed and D(p[1],actual)==integration_paths
G("merge-base","--is-ancestor",actual,c)
assert h["harden_plan_sha256"]==H(B(c,plan)) and h["sched_plan_sha256"]==H(B(c,sched)) and h["roadmap_sha256"]==H(B(c,roadmap))
payload={k:v for k,v in h.items() if k!="manifest_contract_sha256"}; assert h["manifest_contract_sha256"]==H(h["manifest_contract_digest_domain"].encode()+C(payload))
rb=B(r,receipt); q=json.loads(rb); assert rb==C(q); req=q["request"]
assert req["candidate_commit"]==c and req["candidate_tree"]==G("rev-parse",f"{c}^{{tree}}") and req["manifest_sha256"]==H(B(c,manifest)) and req["manifest_contract_sha256"]==h["manifest_contract_sha256"] and req["required_path_set"]==paths and req["required_review_seats"]==seats
assert req["harden_plan_sha256"]==h["harden_plan_sha256"] and req["sched_plan_sha256"]==h["sched_plan_sha256"] and req["roadmap_sha256"]==h["roadmap_sha256"]
assert q["request_sha256"]==H(h["review_request_digest_domain"].encode()+C(req))
assert [x["artifact"]["seat"] for x in q["reviews"]]==seats and all(x["artifact"]["status"]=="usable" and x["artifact"]["terminal_verdict"]=="AGREE" and x["artifact"]["candidate_commit"]==c and x["artifact"]["request_sha256"]==q["request_sha256"] for x in q["reviews"])
for x in q["reviews"]:
 a=x["artifact"]; assert x["artifact_sha256"]==H(b"v10.sched-harden-review-artifact.v1\n"+C(a)) and a["candidate_tree"]==req["candidate_tree"] and a["manifest_sha256"]==req["manifest_sha256"] and a["manifest_contract_sha256"]==req["manifest_contract_sha256"] and a["harden_plan_sha256"]==req["harden_plan_sha256"] and a["seat_instance_id"] and a["harness"] and a["report"].rstrip().splitlines()[-1]=="AGREE"
assert len({x["artifact"]["seat_instance_id"] for x in q["reviews"]})==len(seats)
PY
```

- `PYTHONPATH=phase-loop-runtime/src python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-HARDEN.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.plan_manifest import validate_manifest; v=validate_manifest(Path("plans").joinpath("manifest.json")); assert v.valid, "; ".join(v.errors)'`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'import hashlib,json; from pathlib import Path; p=Path("plans").joinpath("phase-plan-v10-HARDEN.md"); r=Path("specs").joinpath("phase-plans-v10.md"); m=json.loads(Path("plans").joinpath("manifest.json").read_text()); rows=[x for x in m["plans"] if x.get("phase_alias")=="HARDEN"]; assert len(rows)==1; x=rows[0]; assert x["plan_authority_history"][-1]["plan_sha256"]==hashlib.sha256(p.read_bytes()).hexdigest(); assert x["plan_authority_history"][-1]["roadmap_sha256"]==hashlib.sha256(r.read_bytes()).hexdigest(); assert any(e.get("metadata",{}).get("plan_current_authority",{}).get("plan_sha256")==hashlib.sha256(p.read_bytes()).hexdigest() for e in x["lifecycle"])'`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.planner_validation import validate_plan_dispatch_hints; f=validate_plan_dispatch_hints(Path("plans").joinpath("phase-plan-v10-HARDEN.md").read_text()); assert not f, f'`
- `env PHASE_LOOP_TDD_EXPECT_HARDEN=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_advisor_board_cli_legacy.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_goal_coverage.py phase-loop-runtime/tests/test_reconcile_portability_85c.py phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_verification_interpreter_guard_221.py`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `uv run --project phase-loop-runtime ruff check phase-loop-runtime/src/phase_loop_runtime phase-loop-runtime/scripts`
- `python3 -c 'from pathlib import Path; assert len(Path("plans").joinpath("phase-plan-v10-HARDEN.md").read_text().split()) <= 3000'`
- `git diff --exit-code -- specs/phase-plans-v10.md`
- `git diff --check`

## Acceptance Criteria

- [ ] EC-HARDEN-0 — proven by immutable tests-only Git/PR evidence, default GREEN,
  activated raw output/JUnit containing every unique named RED anchor before production,
  exact-head board approval of that landing, final `test_harden_evidence_verifier.py`,
  and one source-entered `verification_evidence.v3` record per frozen fact;
  falsified by a missing or non-biting `verification_evidence.v3` path-entered record,
  production preceding the landing, later test drift, a skip/import failure, or
  production/test co-landing.
- [ ] EC-HARDEN-1 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_review_leg_sandbox.py -q -k review_stage_rejects_every_escape_form_before_launch`; falsified by a path-entered containment mutation reaching the staging/launch sentinel before the restored positive control rejects it.
- [ ] EC-HARDEN-2 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_reconcile_portability_85c.py -q -k "cwd_independent or repo_anchored"`; falsified by a path-entered CWD-relative mutation resolving one logical input differently across two working directories.
- [ ] EC-HARDEN-3 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_goal_coverage.py -q -k "enforce_blocks_every_zero_declared or all_bare_legacy_is_distinct"`; falsified by a path-entered zero-declaration mutation letting enforce mode pass any completion gate instead of non-human `contract_bug`.
- [ ] EC-HARDEN-4 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_verification_interpreter_guard_221.py -q -k argument_consuming_bash_options_and_profile_patch_version_fail_closed`; falsified by a path-entered named-option or profile mutation selecting a non-satisfying interpreter.
- [ ] EC-HARDEN-5 — proven by `env PHASE_LOOP_TDD_EXPECT_HARDEN=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_advisor_board_cli_legacy.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_phase_loop_injection.py`, separate pure-control evidence, exact-head candidate/main four-seat reviews, registry/checklist equality, precomposition authorization, independent invocation revalidation, subscription-only broker attestations, and every route's isolation-or-refusal proof; falsified by a path-entered mutation firing any capability/auth/session/provider/broker/callback/spawn canary before authorization or exposing a direct provider/effect path.
