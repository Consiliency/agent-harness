# Detailed plan: deferred-findings register and per-finding disposition of buckets B and D

## Task

Convergence item 2. Build one non-scheduling register for board findings that were ruled
non-blocking, then give each open issue in triage buckets B and D its own disposition.
- **Bucket B:** 63 issues left over from phases the manifest records as `completed`.
- **Bucket D:** 12 deferred follow-ups that belong to no phase.

Issues dispositioned PARKED or OBSOLETE move into the register and are closed as not planned. Every
other issue stays open with a recorded reason. The register also becomes the documented destination
for DEFERRED findings from now on.

**Input (pinned, not re-derived):**
- file: `/mnt/workspace/board-tools/backlog-triage/triage-snapshot.json`
- taken at `2026-09-17T00:55:58Z` against origin/main `11283f80`, with 223 open issues
- scope: `buckets.B` (63) ∪ `buckets.D` (12) = 75

**Contract with convergence item 1, which is binding:**
- Item 1 owns the 30 `landed_commit_candidates` and runs first. 15 of them also sit in B or D:
  - in B: 428, 451, 454, 456, 463, 464, 470, 481, 488, 490, 493, 498, 688, 789;
  - in D: 733.
- Item 1 records its verdicts in `/mnt/workspace/board-tools/backlog-triage/item1-landed-fix-verdicts.json`,
  schema `landed_fix_verdicts.v1`, and posts a sha256-pinned copy to the plans PR. Its verdicts are
  FIXED, PARTIAL, MENTION-ONLY, REVERTED, OUT-OF-SCOPE, and DRIFTED.
- For B/D issues, item 1 closes only those it rules FIXED; those leave this plan's scope.
- PARTIAL and MENTION-ONLY come back here without any item-1 comment. REVERTED also comes back here.
  OUT-OF-SCOPE stays EXCLUDED. DRIFTED is stale and is handled in Dependencies step 1.
- A-bucket issues and every issue in `codex_inflight_exclusions` are out of scope for both plans. They
  are reported, never parked.
- Neither plan opens a new issue.
- No GitHub mutation happens without an explicit operator approval of a batch list.

## Research summary

**Where the register lives.**
- `roadmap_ownership.owners_for` against `specs/phase-plans-v10.md` at `11283f80` returns `[]` for
  `docs/registers/deferred-findings.md`, and `['GOVLEAN']` for the `plans/` alternative.
- `git grep -nE 'docs/registers|deferred-findings'` over `phase-loop-runtime/src`,
  `phase-loop-runtime/scripts`, `.github`, `ci`, and `scripts` returns nothing.
- The runtime reads only specifically named `docs/` paths, such as the `adoption_bundle.py` contracts
  and the outside-agent conformance docs. No runner, discovery path, or gate reads a `docs/registers/`
  file.
- `docs_surfaces.classify_surface` returns `None` for the register path and for `AGENTS.md`, so
  docs-audit requires no surface decision.
- `AGENTS.md` is in `entry_doc_check.PACKAGE_LONG_DESCRIPTION_DOCS`
  (`phase-loop-runtime/src/phase_loop_runtime/entry_doc_check.py:68-75`), so any path it names must
  resolve.

**The frozen roadmap already dictates a destination, and it is an issue.**
- v10 Execution Notes gate 2 (`specs/phase-plans-v10.md`, the chair paragraph at `:1357`) says a
  downstream finding is "mapped to its existing criterion, or filed as a repository-qualified issue
  when unscheduled".
- `specs/` must not change. So for v10 phase-plan panels, the convention in this plan cannot remove
  the filing step; it can only change what happens after filing. See Changes.

**#361 is itself cited by the frozen roadmap.** HARDEN Non-goals (`specs/phase-plans-v10.md:658`)
read "Re-opening the accepted-residual register (agent-harness#361). Items there are promoted
individually only on new reachability evidence." Any change to #361 must leave that reference
resolvable.

**B and D contain scheduled obligations that a title or number match cannot detect.** Grepping
`#N` against v10 and the v10 phase plans found:
- #361 (HARDEN Non-goals);
- #392 (LEGIBLE);
- #454 (`plans/phase-plan-v10-RELEASE.md`; RELEASE is `committed`);
- #733 (`plans/phase-plan-v10-RESIDUAL.md`);
- citations in the completed CONFORM and PROOFGATE plans, which are historical.

Reading the RESIDUAL plan found two more that carry no issue number:
- **#341** (the 28 F841 findings) is RESIDUAL's `IF-0-RESIDUAL-4` (`plan:83-91`) and its lane SL-3
  scope "retire all remaining F841 rows" (`plan:175`);
- **#360** (channel-route session-model provenance) is `EC-RESIDUAL-5`, also in RESIDUAL SL-3
  ("Bind or caveat session models", `plan:175`).

RESIDUAL is `committed`. Parking either issue would silently drop a roadmap obligation.

**Sample of 16 B/D bodies, read at `11283f80`,** spread across CONFORM, PROOFGATE, FABPUB,
FABREADMIT, GOVLEAN, LEGIBLE, and D:

| Issue | Phase | What the body establishes | Provisional class |
|---|---|---|---|
| #445 | CONFORM | Fable president: "non-blocking design/hardening note … tracked here as `DEFERRED` under `EC-REVIEWTRUTH-19`"; verbatim finding: producer provenance not independently enforced | authority-adjacent: STILL-LIVE unless a reachability negative is shown |
| #519 | CONFORM | Seal digest depends on build-host umask; mitigated by generating seals under `umask 022` | PARKED (mitigation recorded) |
| #790 | CONFORM | `vectors_executed` hardcoded `false`; the corpus runner is never called outside tests | DECISION-REQUIRED |
| #474 | PROOFGATE | Fable president DEFERRED PGB-003, filed "to satisfy the MAINTAINER-RATIFIED agent-harness#442 rule" | OBSOLETE candidate (PROOFGATE re-planned 2026-08-15) |
| #761 | PROOFGATE | Receipt/attestation mechanism "owned by nothing" after the re-plan; abandon or re-home | OBSOLETE or DECISION-REQUIRED |
| #590 | FABPUB | Documented verification command is lifecycle-position dependent; workaround recorded | PARKED |
| #817 | FABPUB | Receipt loader trusts receipt-supplied `global_journal_path`; `cutover_id` joined raw, so an absolute id or `..` escapes | STILL-LIVE (path containment) |
| #842 | FABPUB | Import-time "test seam" rebinds the production writer-generation latch | EXCLUDED (codex-owned by standing operator instruction) |
| #640 | FABREADMIT | Grok 4.6 president: "downstream tightening rather than blockers"; verbatim `FINDING … DEFERRED` lines | PARKED |
| #554 | GOVLEAN | President classified every item DEFERRED; disposition `carried_with_owner` | PARKED |
| #748 | GOVLEAN | A proposal: CI attests the agent's EC-GOVLEAN-4 receipt | DECISION-REQUIRED |
| #539 | LEGIBLE | Canonical test arm never runs in CI; "filed so the asymmetry is on the record" | PARKED |
| #797 | LEGIBLE | Three `test_legible_roadmap_contract` probes red on main; not fixable outside the LEGIBLE lane | STILL-LIVE |
| #399 | D | Four non-blocking follow-ups from a 4/4 AGREE round, "none are urgent" | PARKED |
| #754 | D | Bounded TOCTOU residual, carried per a round cap | PARKED |
| #796 | D | Choose one `PHASE_LOOP_VERIFY_ENFORCE` default; either choice changes production behaviour | DECISION-REQUIRED |

What the sample shows:
- B is not homogeneous. Titles hide live security-shaped defects (#817), red probes on main (#797),
  and maintainer decisions (#790, #796), next to genuinely parkable deferrals.
- Classification must therefore happen per issue, from the body, comments, and current code, as the
  codex seat warned.
- Several deferrals are bound by text to later criteria (#445 → `EC-REVIEWTRUTH-19`, which
  `plans/manifest.json` records as a `president_authority_criterion`). A register row must keep that
  binding verbatim.

## Changes

### `docs/registers/deferred-findings.md` (create)

- **Header, "Purpose and status": add.** It states that this register is a record, not a work queue.
  It carries #361's rule verbatim ("Do not schedule from this register directly") and states that
  nothing in the runtime reads the file.
- **Header, "How findings enter this register": add.** This is the single written definition of the
  DEFERRED-destination convention; nothing else restates it. It covers two cases:
  - **Board findings on anything other than a v10 phase-plan panel** (detailed-plan boards and PR
    code-review boards): a finding ruled DEFERRED, non-blocking, or nit gets a register row. No
    issue is filed.
  - **v10 phase-plan panels:** Execution Notes gate 2 is frozen and still requires a
    repository-qualified issue for an unscheduled finding. The issue is filed, its finding is copied
    into a register row in the same change, and the issue is then closed as not planned with a
    comment pointing at the row.

  It also states that this is a documented convention only; runtime enforcement of a destination
  for `DEFERRED` rulings is a later convergence item and is not part of this change.
- **Header, "Promotion rule": add.** It is adapted from #361 and covers two things:
  - **Trigger:** a parked row returns to scheduled work only on new reachability evidence — a new
    production caller, a changed trust boundary, or a demonstrated exploit or failure path — and the
    evidence must be cited.
  - **Mechanism:** promotion reopens the row's source issue with that evidence; it never opens a new
    issue. The row is marked `PROMOTED` with the date and a link to the evidence, and is never
    deleted.
- **Rows R-001..R-005: add.** The five residuals in #361's table (#276, #273, #272, #269, #266),
  migrated verbatim with #361 recorded as their source register.
- **Rows R-006 onward: add.** One row per issue dispositioned PARKED or OBSOLETE during execution,
  using the row schema below.

Row schema, one `### R-NNN` section per row. Findings run to several paragraphs, so a single table
would be unreadable.

| Field | Content |
|---|---|
| `source` | the repository-qualified issue, e.g. `Consiliency/agent-harness#640`, closed as not planned |
| `origin` | phase of origin, and the board / PR / exact head SHA / artifact digests exactly as the issue records them |
| `original ruling` | the original disposition text and who ruled, verbatim (e.g. "Grok 4.6 president … DEFERRED") |
| `bound criteria` | any EC or IF identifier the issue binds itself to, verbatim (e.g. `EC-REVIEWTRUTH-19`), or `none` |
| `finding` | the finding text copied byte-for-byte from the issue body into a fenced block, never paraphrased |
| `current-main check` | the SHA checked, what was checked, and the result |
| `disposition` | `PARKED` or `OBSOLETE`, with a one-sentence reason; for OBSOLETE, the superseding commit or plan line |
| `promotion` | `none`, or `PROMOTED <date> <evidence link>` |

### `AGENTS.md` (modify)

- **`## Plan discipline (why phases stall)`: add one pointer sentence.** It says board findings ruled
  DEFERRED or non-blocking are recorded in `docs/registers/deferred-findings.md`, and names that file
  as the rule's definition. It restates nothing, following the pointer-drift lesson. It is the pointer
  both agents actually read, because codex and Claude both load the repo's `AGENTS.md`.

### No other repository file changes

- No `specs/` change.
- No `plans/manifest.json` row: the prior decision stands, since another agent appends to that
  array.
- No runtime code.
- No change to any RESIDUAL-owned path. RESIDUAL's own triage artifact is
  `plans/evidence/v10-RESIDUAL-f841-triage.md` (`plans/phase-plan-v10-RESIDUAL.md:191`), and this plan
  does not touch it.

### Execution artifacts, off-repo (not committed)

- **`/mnt/workspace/board-tools/backlog-triage/item2-dispositions.json`:** the per-finding triage
  table covering every in-scope issue exactly once, in EC-RESIDUAL-7's form ("a triage table covering
  all N with a per-finding disposition, not a blanket deferral"). Each entry records: issue,
  disposition, evidence, and the GitHub action planned and taken.
- **`/mnt/workspace/board-tools/backlog-triage/item2-approval-batch.md`:** the exact list shown to the
  operator before any mutation.

### Disposition categories

Every in-scope issue gets exactly one. Each is decided by reading the full body, all comments, any
linked PR or commit, and the current code at the cited location — never from the title.

| Disposition | Evidence required | GitHub action |
|---|---|---|
| **EXCLUDED** | Membership in any of: an A bucket; `codex_inflight_exclusions` at the pinned snapshot; codex in-flight work recomputed at execution with the same rule item 1 uses (see "Common rules"); an item-1 OUT-OF-SCOPE verdict; an issue the operator has assigned to codex by standing instruction (#842). Already known in B∪D: #388, #789 (also an item-1 candidate), #842. | none; reported in the operator summary |
| **SCHEDULED** | The issue's subject is an obligation of a phase that is not `completed`, citing the exact EC, IF gate, or phase-plan lane text. Known now: #341 (`IF-0-RESIDUAL-4`, RESIDUAL SL-3), #360 (`EC-RESIDUAL-5`, RESIDUAL SL-3). #454 (RELEASE plan) and #733 (RESIDUAL plan) are item-1 candidates; if item 1 returns them, they land here. | none; stays open |
| **ALREADY-FIXED** | A landed commit on main whose diff, not its subject, resolves the issue's stated problem, and has not been reverted. | none from item 2. Recorded for item 1's rule. An issue item 1 already judged not-FIXED cannot be re-labelled ALREADY-FIXED here without new evidence that item 1 did not see. |
| **STILL-LIVE** | The defect is reachable on current main: a reproduction, or the cited code unchanged and reached from a production caller. **Mandatory safety floor:** any finding about path containment, credentials, authorization or authority, or fail-open verification is STILL-LIVE unless the row records a concrete reachability negative. | none; stays open, reason recorded |
| **DECISION-REQUIRED** | The issue asks for a maintainer choice that changes production behaviour or policy (e.g. #796, #790). | none; stays open, listed for the operator |
| **OBSOLETE** | The mechanism, file, or phase path the finding concerns was removed or explicitly descoped, citing the superseding commit or the plan line that states the descope. | register row, then close as not planned with a comment linking the row and the superseding evidence |
| **PARKED** | All four hold: the original ruling classed it DEFERRED, non-blocking, or nit; it is not SCHEDULED; it clears the safety floor; and the current-main check does not show a reachable failure. | register row, then close as not planned with a comment linking the row |

### Common rules, shared with item 1

- **Codex in-flight exclusion set.** Build it at execution time, not from the pinned snapshot alone,
  as the union of:
  - issue numbers in the titles, bodies, and head-branch names of open PRs;
  - issue numbers in `codex/*` branch names;
  - issue numbers appearing in the diff of any `codex/*` branch not yet merged to main
    (`git diff origin/main...origin/codex/<branch>`, including `plans/manifest.json` hunks).

  Branch names alone are not enough. `origin/codex/merged-repairs-closeout-20260917` carries no issue
  number in its name, yet its diff records the #868/#871 repairs in `plans/manifest.json`, so codex
  may be closing issues itself.
- **Procedural acceptance conditions.** Examples: "Sol/Fable review before landing", "exact-head board
  before dispatch". For a bucket B issue, such a condition is treated as met when its owning phase is
  `completed` in `plans/manifest.json`. That is the same convention item 1 uses. It is a **board
  judgement call**, and is flagged as such in the PR body.
- **Conditions outside the body.** When an issue body only points elsewhere — "see consolidation", a
  linked issue, a PR comment, a board artifact — follow the link. A condition that cannot be found is
  UNVERIFIABLE and is never silently treated as met. An issue whose disposition would depend on it is
  DECISION-REQUIRED, with the unverifiable condition named in its evidence.
- **PARTIAL from item 1.** A PARTIAL issue can be PARKED or OBSOLETE only for its *unlanded*
  remainder. The row's `current-main check` cites item 1's recorded landed part, and the finding field
  quotes only the unresolved text.

#361 itself is handled as a migration, not a disposition:
- its five rows become R-001..R-005;
- it is closed as completed, with a comment saying the register now lives at the docs path;
- v10 HARDEN Non-goals' reference to #361 still resolves to that closed issue and its redirect.

## Documentation impact

- **`docs/registers/deferred-findings.md`: add.** The register, and the single definition of the
  DEFERRED-destination convention.
- **`AGENTS.md`: modify.** A one-sentence pointer in `## Plan discipline`. It is an entry doc, so
  entry-doc-check must resolve the named path, which exists in the same PR.
- **`CHANGELOG.md`: no change.** `classify_surface` returns `None` for both files, so docs-audit
  requires no decision.
- **`specs/phase-plans-v10.md`: no change** (frozen). The gate-2 interaction is handled in the
  register's convention text instead.

## Dependencies & order

1. **Item 1 has finished, and its verdict artifact is consistent.** This is a hard precondition
   checked before step 2.
   - **Artifact:** `/mnt/workspace/board-tools/backlog-triage/item1-landed-fix-verdicts.json`, schema
     `landed_fix_verdicts.v1`, plus the sha256-pinned copy item 1 posted to the plans PR.
   - **Missing:** if either copy is missing, or the schema is not `landed_fix_verdicts.v1`, item 2 does
     not start at all. It must not partially proceed, because the 15 overlap issues could otherwise be
     actioned twice.
   - **Mismatched:** if the local file's sha256 differs from the pinned copy, stop and report.
   - **Incomplete:** every B/D issue item 1 marks FIXED must be closed on GitHub. Any FIXED-but-open
     issue means item 1 is unfinished; stop.
   - **Stale:** an overlap issue is stale if item 1 ruled it DRIFTED, or if its `updatedAt` is later
     than the artifact's recording time (reopened, edited, or newly commented). Re-run item 1's
     verification rule on it before it enters this scope.
   - **Routing:** PARTIAL, MENTION-ONLY, and REVERTED enter this scope. OUT-OF-SCOPE is EXCLUDED. A
     FIXED issue that item 1 held back under its committed-phase citation guard (`cited_by_open_phase`
     non-empty; #454 and #733 are expected) also enters this scope, and is dispositioned SCHEDULED.
2. **Re-snapshot open issues** and compute the execution scope:

   (pinned B ∪ D) ∩ (open now) − (item-1 FIXED) − EXCLUDED

   Issues opened after the pinned snapshot are **not** added: the list is fixed (convergence rule 1).
   Report the drift instead.
3. **Read and disposition every in-scope issue.** Write `item2-dispositions.json`, one entry per
   issue.
4. **On the branch, build the register.** Write R-001..R-005 from #361, then R-006 onward from the
   PARKED and OBSOLETE entries, plus the `AGENTS.md` pointer.
5. **Run local verification**, then open a PR. The PR body uses `Refs` and never a closing keyword:
   "Closes … stays open" qualifiers still auto-close.
6. **Board review of the PR**, at most 3 rounds. If round 3 is not 4/4 AGREE, descope to:
   - the register document;
   - the #361 migration;
   - PARKED closes for completed-phase (bucket B) deferrals only.

   The descope drops D-bucket dispositions and the `AGENTS.md` convention.
7. **Operator approval gate.** Present `item2-approval-batch.md`, which lists every intended mutation
   as issue, disposition, register row anchor, and action. Nothing is closed without an explicit yes
   to that exact list.
8. **Merge the register PR first,** so each close comment can link a row anchor at a merged commit on
   main.
9. **Apply the approved closes** (not planned, each with its row link), then close #361 with its
   redirect. Stop on the first failed mutation, and re-read the state before continuing.
10. **Measure** (see Verification).

## Verification

Run from the worktree root, with `PYTHONPATH=$PWD/phase-loop-runtime/src`.

```bash
# 1. ownership and non-readership of the new paths
python3 - <<'PY'
from pathlib import Path
from phase_loop_runtime import roadmap_ownership as ro
m = ro.ownership_map(Path('specs/phase-plans-v10.md').read_text())
assert ro.owners_for('docs/registers/deferred-findings.md', m) == [], 'register path is owned'
print('owners OK')
PY
test -z "$(git grep -nE 'docs/registers|deferred-findings' -- phase-loop-runtime/src phase-loop-runtime/scripts .github ci scripts)" && echo 'unread OK'

# 2. repo diff is exactly the register, the AGENTS.md pointer, and this plan
git diff --name-only origin/main...HEAD | sort
# expect exactly: AGENTS.md, docs/registers/deferred-findings.md, plans/detailed-deferred-findings-register-20260917-0100.md
test -z "$(git diff --name-only origin/main...HEAD -- specs/ plans/manifest.json)" && echo 'specs/manifest untouched OK'

# 3a. item 1's artifact is present, on the agreed schema, and matches its PR-pinned digest
python3 - <<'PY'
import json, hashlib, sys
p = '/mnt/workspace/board-tools/backlog-triage/item1-landed-fix-verdicts.json'
raw = open(p, 'rb').read(); a = json.loads(raw)
assert a.get('schema') == 'landed_fix_verdicts.v1', 'item 1 artifact schema mismatch'
print('item1 sha256', hashlib.sha256(raw).hexdigest(), '(must equal the digest pinned on the plans PR)')
PY

# 3b. triage table covers the whole scope exactly once, and rows match closable dispositions
python3 - <<'PY'
import json, re, collections
T = '/mnt/workspace/board-tools/backlog-triage'
disp = json.load(open(f'{T}/item2-dispositions.json'))
scope = {e['issue'] for e in disp['entries']}
assert len(scope) == len(disp['entries']), 'an issue appears twice'
assert set(disp['scope']) == scope, 'triage table does not cover the computed scope exactly'
allowed = {'EXCLUDED','SCHEDULED','ALREADY-FIXED','STILL-LIVE','DECISION-REQUIRED','OBSOLETE','PARKED'}
assert all(e['disposition'] in allowed and e['evidence'].strip() for e in disp['entries'])
reg = open('docs/registers/deferred-findings.md').read()
sections = {m.group(1): body for m, body in
            ((re.match(r'(R-\d{3})\b', s), s) for s in re.split(r'^### ', reg, flags=re.M)[1:]) if m}
fields = ('source','origin','original ruling','bound criteria','finding','current-main check','disposition','promotion')
row_issues = collections.Counter()
for rid, body in sections.items():
    for f in fields: assert f'`{f}`' in body, f'{rid} missing field {f}'
    src = re.search(r'`source`[^\n]*?#(\d+)', body); assert src, f'{rid} has no source issue'
    row_issues[int(src.group(1))] += 1
closable = {e['issue'] for e in disp['entries'] if e['disposition'] in {'PARKED','OBSOLETE'}}
for i in closable: assert row_issues[i] == 1, f'#{i} needs exactly one row'
for r in ('R-001','R-002','R-003','R-004','R-005'): assert r in sections, f'{r} (#361 migration) missing'
print('coverage OK:', collections.Counter(e['disposition'] for e in disp['entries']))
PY

# 4. the docs gates that cover AGENTS.md and the new file
python3 -m phase_loop_runtime.cli docs-audit --repo . --json
python3 -m pytest -q phase-loop-runtime/tests/test_entry_doc_check.py
```

After the approved mutations, confirm that exactly the approved batch changed and nothing else:

```bash
python3 - <<'PY'
import json, subprocess
T = '/mnt/workspace/board-tools/backlog-triage'
approved = {e['issue'] for e in json.load(open(f'{T}/item2-dispositions.json'))['entries']
            if e['disposition'] in {'PARKED','OBSOLETE'} and e.get('approved')}
for n in sorted(approved):
    v = json.loads(subprocess.run(['gh','issue','view',str(n),'-R','Consiliency/agent-harness',
        '--json','state,stateReason,comments'], capture_output=True, text=True, check=True).stdout)
    assert v['state'] == 'CLOSED' and v['stateReason'] == 'NOT_PLANNED', n
    assert 'docs/registers/deferred-findings.md' in v['comments'][-1]['body'], n
print('closes OK:', len(approved))
PY
gh issue view 361 -R Consiliency/agent-harness --json state,stateReason --jq '.state+" "+.stateReason'   # expect CLOSED COMPLETED
```

**Measurement (convergence rule 4).**
- The count is `gh issue list -R Consiliency/agent-harness --state open --limit 1000 --json number --jq length`,
  taken immediately before step 9 and immediately after it.
- Only closes on the approved list are credited to item 2, which separates them from concurrent codex
  activity.
- The weekly opened-minus-closed figure for the week of execution is also recorded.

**Expected delta.** Of the 13 non-excluded bodies in the sample, 9 look closable (6 PARKED + 3
OBSOLETE or OBSOLETE-candidates), or 60–70%. Allowing for that n=13 uncertainty, use 45–70%.
Applied to the non-overlap scope of about 56 issues (75, minus the 15 item-1 overlaps, minus #388
and #842, minus SCHEDULED #341 and #360), plus #361 itself, that gives an expected reduction of
**26–40 open issues**. Up to about 10 more are possible if item 1 returns non-FIXED overlap issues
that turn out closable here.
- **Below 20:** the item under-delivered, and the reason goes in the closeout.
- **Above 45:** it over-parked. Before closing, audit the safety-floor decisions.

## Acceptance criteria

- [ ] `item2-dispositions.json` covers the computed execution scope exactly once. Every entry has a disposition from the seven categories and non-empty evidence (verification script 3b passes).
- [ ] `docs/registers/deferred-findings.md` exists, is unowned (`owners_for` returns `[]`), and is unread by runtime and workflows. It contains R-001..R-005 migrated from #361, and exactly one schema-complete row for every PARKED or OBSOLETE issue (verification scripts 1, 3a and 3b pass).
- [ ] `git diff --name-only origin/main...HEAD` is exactly `AGENTS.md`, `docs/registers/deferred-findings.md`, and this plan. No `specs/` or `plans/manifest.json` change. docs-audit and `test_entry_doc_check.py` pass.
- [ ] After the operator-approved batch, every approved PARKED or OBSOLETE issue is `CLOSED`/`NOT_PLANNED` with a comment linking the register, #361 is `CLOSED`/`COMPLETED`, and no issue outside the approved batch changed state (post-mutation script passes).
- [ ] The **attributable** delta — the number of approved PARKED/OBSOLETE issues confirmed `CLOSED`/`NOT_PLANNED` by the post-mutation script, plus #361 — falls in the 26–40 range, or its shortfall or excess has a recorded reason. The raw open count before and after is recorded separately and is not asserted equal, because codex opens and closes issues concurrently. No new issue was opened by this item.

## Execution Policy

- execute: effort=medium, reason=about 60 issue bodies each need a judgment call against the code, with a mandatory safety floor; docs-only repository change
