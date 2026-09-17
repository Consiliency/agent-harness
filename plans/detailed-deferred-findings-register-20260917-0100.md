# Detailed plan: deferred-findings register and per-finding disposition of buckets B and D

## Task

Convergence item 2. It does three things:
- builds one non-scheduling register for board findings ruled non-blocking;
- gives each open issue in triage buckets B (63 leftovers from phases the manifest records as `completed`) and D (12 deferred follow-ups that belong to no phase) its own disposition;
- makes the register the documented destination for deferred findings from now on.

Issues dispositioned PARKED or OBSOLETE get a register row and are closed as not planned. Issues
dispositioned ALREADY-FIXED are closed as completed. Every other issue stays open with a recorded
reason.

**Rules.** The execution rules shared with item 1 — R1 in-flight exclusion union, R2 phase-binding
guard, R3 acceptance extraction, R4 procedural conditions, R5 freshness, R6 mutation receipts, R7
verbatim fencing, and the `shared_rules.py` helper and its self-test — are defined **once**, in
`## Shared execution rules` of `plans/detailed-close-landed-fix-issues-20260917-0100.md`. This plan
cites them by name and restates none of them.

### Pinned input

`/mnt/workspace/board-tools/backlog-triage/triage-snapshot.json`, sha256 `230a8a9c…`, taken
2026-09-17T00:55:58Z against origin/main `11283f80`. Scope source: `buckets.B` ∪ `buckets.D` (75), less
agent-harness#361, which is handled as a migration (see "#361").

### Contract with item 1

Item 1's `## Dependencies & order` → "Contract with item 2" is binding and is not restated here. In
short, this plan starts only on an item-1 artifact whose `run_status` is `complete` or `verdicts_only`
and whose bytes match the published digest. Every B/D issue without a successful item-1 `issue_close`
receipt is in this plan's scope.

## Research summary

**Where the register lives.**
- `roadmap_ownership.owners_for` against v10 at `11283f80` returns `[]` for `docs/registers/deferred-findings.md`, and `['GOVLEAN']` for any `plans/` path.
- `git grep -nE 'docs/registers|deferred-findings'` over `phase-loop-runtime/src`, `phase-loop-runtime/scripts`, `.github`, `ci` and `scripts` is empty, so no runner, discovery path or gate reads it.
- `docs_surfaces.classify_surface` returns `None` for both new paths.
- `AGENTS.md` is in `entry_doc_check.PACKAGE_LONG_DESCRIPTION_DOCS`, so any path it names must exist.

**The ratchet has a ratified input, and this plan must comply with it.**
- The maintainer-ratified design on agent-harness#442 (2026-08-04) states: *"every `DEFERRED` finding must have a filed issue carrying its verbatim text before dispatch"*. It is falsified by *"a `DEFERRED` finding with no filed issue at dispatch"*. It is an anti-rubber-stamping safeguard, and the committed REVIEWTRUTH phase records it as hand-enforced at every gate.
- Frozen v10 Execution Notes gate 2 (`specs/phase-plans-v10.md:1357`) likewise files an unscheduled finding "as a repository-qualified issue".
- The register therefore cannot replace filing. It can only give a filed finding a disposition, and so an exit from the open queue. Round 1 of this PR's board caught the earlier draft's "no issue filed for non-phase-plan boards", which contradicted both texts and also left register rows with no source issue for promotion to reopen.

**#361 is cited by frozen text.** HARDEN Non-goals (`specs/phase-plans-v10.md:658`) reads "Re-opening
the accepted-residual register (agent-harness#361). Items there are promoted individually only on new
reachability evidence." HARDEN is `committed`. Closing #361 would contradict item 1's binding principle
(R2), so #361 stays open as a redirect.

**B and D contain bound, held, and live issues that titles hide.**
- **Bound through RESIDUAL:** #341 is RESIDUAL's `IF-0-RESIDUAL-4` and lane SL-3; #360 is `EC-RESIDUAL-5`.
- **Bound to a committed criterion:** #445 and #444 are "DEFERRED under `EC-REVIEWTRUTH-19`".
- **Under an operator hold:** #843 is held pending #789 and #842.
- **Live despite a mitigation:** #595 records that a direct `run_train` call skips the generation lease. The defect is still at `train_runner.py:3620-3621` and contradicts frozen FABPUB text (`specs/phase-plans-v10.md:298`), even though the CLI path is fail-closed.

**Sample of 16 B/D bodies**, read at `11283f80`, provisionally classified under the revised rules below:

| Issue | Phase | What the body establishes | Provisional |
|---|---|---|---|
| #445 | CONFORM | DEFERRED "under `EC-REVIEWTRUTH-19`"; producer provenance not independently enforced | SCHEDULED (R2 check iv) |
| #519 | CONFORM | Seal digest depends on build-host umask; mitigated under `umask 022` | PARKED |
| #790 | CONFORM | `vectors_executed` hardcoded `false`; the corpus runner is never called outside tests | DECISION-REQUIRED |
| #474 | PROOFGATE | Fable president DEFERRED PGB-003 | OBSOLETE only if its mechanism is removed from main; otherwise PARKED |
| #761 | PROOFGATE | Receipt mechanism "owned by nothing" after re-plan; "abandon or re-home" | DECISION-REQUIRED |
| #590 | FABPUB | Verification command is lifecycle-position dependent; workaround recorded | PARKED |
| #817 | FABPUB | Receipt loader joins a receipt-supplied `cutover_id` raw; an absolute path or `..` escapes | STILL-LIVE (safety floor) |
| #842 | FABPUB | Import-time test seam rebinds the production latch | EXCLUDED (codex, by standing instruction) |
| #640 | FABREADMIT | Grok 4.6 president: "downstream tightening rather than blockers" | PARKED |
| #554 | GOVLEAN | President classified every item DEFERRED; `carried_with_owner` | PARKED, unless an item is floor-class |
| #748 | GOVLEAN | Proposal: CI attests the agent's EC-GOVLEAN-4 receipt | DECISION-REQUIRED |
| #539 | LEGIBLE | Canonical test arm never runs in CI; "filed so the asymmetry is on the record" | PARKED |
| #797 | LEGIBLE | Three contract probes red on main | STILL-LIVE |
| #399 | D | Four non-blocking follow-ups; "none are urgent" | PARKED |
| #754 | D | Bounded TOCTOU residual carried per a round cap | STILL-LIVE, unless a reachability negative is recorded (floor class) |
| #796 | D | Choose one `PHASE_LOOP_VERIFY_ENFORCE` default | DECISION-REQUIRED |

**Corrected arithmetic.** The sample has 16 rows; #842 is EXCLUDED, leaving 15 evaluable. Under the
revised rules, 5 to 7 are closable: PARKED #519, #590, #640, #539 and #399, plus #554 and #474 if
confirmed. That is 33–47%. The table also shows that bucket B is not homogeneous, so every issue must be
decided from its body, its comments and current code, never from its title.

**Round-1 validator findings.**
- Findings copied byte-for-byte contain `###` headings (7 of the 75 bodies, including #399) and triple-backtick fences (18, including #539 and #590). A register parser that splits on `### ` or fences with three backticks breaks on real data.
- A coverage check that reads the artifact's own `scope` field passes an empty artifact.
- A post-mutation check that filters on an undefined `approved` field passes vacuously.

## Changes

### `docs/registers/deferred-findings.md` (create)

- **Header, "Purpose and status": add.** It states:
  - this is a record, not a work queue;
  - nothing in the runtime reads it;
  - #361's rule, quoted verbatim: "Do not schedule from this register directly."
- **Header, "How findings enter": add.** This is the single written definition of the convention.
  1. **Filing.** Every finding a board president or chair rules `DEFERRED`, and every finding a board records as non-blocking, is filed as an issue carrying its verbatim text before dispatch. That is exactly what agent-harness#442's ratified design and v10 Execution Notes gate 2 require; the register does not change it.
  2. **Disposition.** The filed issue is then dispositioned under this register's categories and precedence **before the board's PR merges**.
     - PARKED or OBSOLETE: a register row lands in that PR or a register PR, and only after the row is on main is the issue closed as not planned, with a link to the row.
     - SCHEDULED, STILL-LIVE or DECISION-REQUIRED: the issue stays open, with its reason recorded as a comment.
  3. **Result.** A filed finding is never left open without a disposition.
  4. **Scope.** This is a documented convention only. Runtime enforcement of a destination for `DEFERRED` rulings is a later convergence item.
- **Header, "Categories and precedence": add.** The seven dispositions and the precedence below, stated once here and cited by the convention.
- **Header, "Promotion rule": add.**
  - **Trigger:** a row returns to scheduled work only on new reachability evidence — a new production caller, a changed trust boundary, or a demonstrated exploit or failure path — and the evidence is cited.
  - **Mechanism:** reopen the row's source issue with that evidence. The row is marked `PROMOTED <date> <evidence link>` and is never deleted.
- **Rows R-001..R-005: add.** The five residuals in #361's table (#276, #273, #272, #269, #266, all closed today), migrated verbatim. Each row's `original ruling` quotes #361's table row. The register header quotes #361's original promotion text verbatim: "split it back out as its own P-ranked issue WITH the reachability evidence". Reopening the source issue satisfies that text, because the source issue is that residual's own issue.
- **Rows R-006 onward: add.** One row per issue dispositioned PARKED or OBSOLETE and approved.

**Row format**, machine-parseable and safe for verbatim content:

````markdown
<!-- row:R-006 -->
### R-006 — <issue title>
- **source:** Consiliency/agent-harness#640 (closed as not planned)
- **origin:** <phase; board / PR / exact head SHA / artifact digests as the issue records them; the typed
  `issue_dispositions` record from the owning phase's plans/manifest.json lifecycle, quoted, when one exists>
- **original ruling:** <verbatim ruling text and who ruled>
- **bound criteria:** <verbatim EC/IF identifiers the issue binds itself to, or `none`>
- **current-main check:** <SHA; what was checked; result>
- **safety floor:** <`not floor-class`, or the floor class plus its reachability negative>
- **disposition:** <`PARKED` | `OBSOLETE`> — <one sentence; OBSOLETE cites the removal commit>
- **promotion:** none
- **finding:**
<the issue's finding text, byte-for-byte, fenced per R7>
````

`finding` is always the last field, so a verbatim `###` heading or code fence inside it cannot be
mistaken for row structure. Rows are delimited only by `<!-- row:R-NNN -->` lines.

### `AGENTS.md` (modify)

- **`## Plan discipline (why phases stall)`: add one pure pointer sentence.** "The destination for
  deferred and non-blocking board findings is defined in `docs/registers/deferred-findings.md`." It
  states no part of the rule, so it cannot drift from it.

### No other repository file changes

- no `specs/` change;
- no `plans/manifest.json` row;
- no runtime code;
- no RESIDUAL-owned path, including RESIDUAL's own `plans/evidence/v10-RESIDUAL-f841-triage.md`.

### Execution artifacts, off-repo

- **`/mnt/workspace/board-tools/backlog-triage/item2-dispositions.json`**, schema `item2_dispositions.v1`. Top level:
  - `schema`, `run_status` (as item 1 defines it), `started_at`, `origin_main_at_execution`;
  - `item1_artifact_sha256`;
  - `approval` `{approved_at, batch_list_sha256}`;
  - `entries`, one per scope issue;
  - `receipts`, per R6.

  Each entry records:
  - `issue`, `bucket`, `disposition`, `evidence`;
  - `precedence_trace` — each category tested in order, with the reason it did or did not apply;
  - `phase_bindings` and `binding_review`, per R2;
  - `safety_floor_class` — `none` or the class;
  - `reachability_negative` — a string, required for a floor-class close;
  - `removal_commit` — required for OBSOLETE;
  - `register_row` — `R-NNN` or `null`;
  - `approved` — bool;
  - `action` — `closed_not_planned`, `closed_completed`, `commented`, `declined`, or `none`.
- **`item2-approval-batch.md`** — the exact list shown to the operator.

### Disposition categories and precedence

Each scope issue is tested against the categories **in this order**; the first that applies is its
disposition:

**EXCLUDED > SCHEDULED > DECISION-REQUIRED > STILL-LIVE > ALREADY-FIXED > OBSOLETE > PARKED**

Every decision reads the full body, all comments, any linked PR or commit, and the current code at the
cited location.

| Disposition | Applies when | Action |
|---|---|---|
| **EXCLUDED** | The issue is in an A bucket, or in R1's exclusion union at execution. R1 already includes operator holds such as #843. | none |
| **SCHEDULED** | R2 returns any binding (checks i–iv). Examples: #341, #360, #445, #444, and item-1 guard-held issues such as #454 and #733. | none; stays open, with the binding recorded |
| **DECISION-REQUIRED** | The issue asks for a maintainer choice that changes production behaviour or policy (#790, #796, #748). This includes "abandon or re-home" cases (#761), and anything descoped but still present in the code. | none; stays open, listed for the operator |
| **STILL-LIVE** | The defect is reachable on current main. Also applies to **any finding in a safety-floor class that lacks a reachability negative**, and to any finding that **contradicts a frozen requirement** — spec text or a frozen test invariant, mirroring #442's non-deferrable class. | none; stays open, reason recorded |
| **ALREADY-FIXED** | Item 1's verdict rule (R3, R4) yields FIXED at the execution SHA. | close as `completed` with item 1's close-comment format, under this plan's approval gate |
| **OBSOLETE** | The mechanism, file or path the finding concerns has been **removed from current main**. This needs the removal commit plus a grep that proves the mechanism is absent. "Explicitly descoped" alone does not qualify. | register row, then close as not planned |
| **PARKED** | The original ruling classed the finding `DEFERRED`, non-blocking or nit; no earlier category applied; and the safety floor is satisfied. | register row, then close as not planned |

**Safety floor.** The floor is a precondition of **every** close path that leaves a defect unfixed (OBSOLETE and PARKED).

*Floor classes:* path containment, credentials, authorization or authority, fail-open verification,
and concurrency or TOCTOU on an authority or evidence path.

*Reachability negative.* A floor-class finding may be closed only with one of these, recorded with
file:line evidence at `origin_main_at_execution`:
- **(a)** the cited code or mechanism no longer exists on main, shown by the removal commit plus a grep that proves its absence; or
- **(b)** every production caller of the cited code is enumerated, and each is shown not to reach the defect.

These **never** count as a reachability negative:
- the original deferral's reasoning;
- a mitigation note or workaround;
- a fail-closed CLI when a direct API path remains (#595);
- "not urgent".

### Agent-harness#361

#361 is **not** dispositioned and **not** closed. Its five rows migrate as R-001..R-005, and it
receives one approval-listed comment. The comment:
- redirects to the register;
- quotes `specs/phase-plans-v10.md:658`;
- explains that the issue stays open because frozen HARDEN Non-goals cite it.

It contributes nothing to the measured delta.

## Documentation impact

- `docs/registers/deferred-findings.md` — add — the register, and the single definition of the convention.
- `AGENTS.md` — modify — one pure pointer sentence. The path it names exists in the same PR, as entry-doc-check requires.
- `CHANGELOG.md` — no change. `classify_surface` returns `None` for both paths.
- `specs/phase-plans-v10.md` — no change (frozen). The convention complies with gate 2 as written.

## Dependencies & order

1. **Start contract.** Check item 1's artifact against its "Contract with item 2": it exists, its `run_status` is `complete` or `verdicts_only`, its schema matches, and its local sha256 equals the published digest. On any failure, do not start and report to the operator. Run `shared_rules.py --self-test` too; it must exit 0.
2. **Scope.** The scope is:

   ((pinned B ∪ D) − {361}) − {issues with a successful item-1 `issue_close` receipt} − {issues already closed before `started_at`}

   Issues opened after the snapshot are never added (convergence rule 1). EXCLUDED issues remain in scope as a disposition, so coverage is exact.
3. **Disposition every scope issue** by the precedence above, writing `item2-dispositions.json`. For an overlap issue item 1 ruled PARTIAL, re-verify item 1's held conditions at this plan's execution SHA before relying on them, because a revert between runs must not let a reverted defect be parked unseen.
4. **Run R5 over every intended mutation.** Then present `item2-approval-batch.md`, which enumerates every GitHub mutation this item will make:
   - each close (disposition, reason, register row anchor, full comment text);
   - the #361 comment;
   - the publication comment;
   - the register PR's open and merge.

   The open and merge are listed for visibility; they are also governed by the standing public-repo CR gate. Record `batch_list_sha256`. Nothing is mutated before approval.
5. **Build the register branch** from the approved rows plus the `AGENTS.md` pointer. Verify locally, then open the register PR (receipt `pr_open`).
6. **Board review of the register PR**, at most 3 rounds. If review changes a row's content or a disposition, the changed items return to the operator for re-approval. If round 3 is not 4/4 AGREE, descope to: the register header, R-001..R-005, and PARKED rows for bucket B only. The descope drops the D-bucket dispositions and the `AGENTS.md` pointer.
7. **Merge** only after the board agrees and CI is green (receipt `pr_merge`).
8. **For each approved close:** run R5, then close with the row anchor at the merged main SHA, then record a receipt. After the closes, post the #361 comment (receipt).
9. **Set `run_status`, measure, publish.** Measurement is by receipts. Publish `item2-dispositions.json`'s exact bytes to the register PR as item 1's "Publication" section specifies (receipt `pr_comment`).

## Verification

Run from a checkout at the merged register commit, with `PYTHONPATH=$PWD/phase-loop-runtime/src`.

```bash
T=/mnt/workspace/board-tools/backlog-triage
python3 $T/shared_rules.py --self-test

# 1. ownership, non-readership, exact file set of the register PR
python3 - <<'PY'
from pathlib import Path
from phase_loop_runtime import roadmap_ownership as ro
m = ro.ownership_map(Path('specs/phase-plans-v10.md').read_text())
assert ro.owners_for('docs/registers/deferred-findings.md', m) == [], 'register path is owned'
print('owners OK')
PY
test -z "$(git grep -nE 'docs/registers|deferred-findings' -- phase-loop-runtime/src phase-loop-runtime/scripts .github ci scripts)" && echo 'unread OK'
# on the register PR: expect exactly AGENTS.md and docs/registers/deferred-findings.md
gh pr diff <REGISTER_PR> -R Consiliency/agent-harness --name-only | sort

# 2. coverage recomputed independently, dispositions legal, register rows parse, closes are safe
python3 - <<'PY'
import json, re, sys, subprocess, collections
T = '/mnt/workspace/board-tools/backlog-triage'
sys.path.insert(0, T)
import shared_rules as sr
s = json.load(open(f'{T}/triage-snapshot.json'))
i1 = json.load(open(f'{T}/item1-landed-fix-verdicts.json'))
d = json.load(open(f'{T}/item2-dispositions.json'))
assert i1['run_status'] in ('complete', 'verdicts_only'), 'item 1 not in a startable state'
assert d['schema'] == 'item2_dispositions.v1', 'schema'
i1_closed = {r['issue_or_pr'] for r in i1['receipts'] if r['kind'] == 'issue_close' and r['exit_code'] == 0}
pinned = (set(s['buckets']['B']) | set(s['buckets']['D'])) - {361}
allst = json.loads(subprocess.run(['gh', 'issue', 'list', '-R', 'Consiliency/agent-harness', '--state', 'all',
    '--limit', '1000', '--json', 'number,closedAt'], capture_output=True, text=True, check=True).stdout)
closed_before = {x['number'] for x in allst if x['closedAt'] and x['closedAt'] < d['started_at']}
expected = pinned - i1_closed - (closed_before - {r['issue_or_pr'] for r in d['receipts']})
got = [e['issue'] for e in d['entries']]
assert len(got) == len(set(got)), 'an issue appears twice'
assert set(got) == expected, f'coverage mismatch: missing {sorted(expected - set(got))}, extra {sorted(set(got) - expected)}'
allowed = ['EXCLUDED', 'SCHEDULED', 'DECISION-REQUIRED', 'STILL-LIVE', 'ALREADY-FIXED', 'OBSOLETE', 'PARKED']
snap_x = set(s['codex_inflight_exclusions'])
A = set(s['buckets']['A1'] + s['buckets']['A2'] + s['buckets']['A3'])
reg = open('docs/registers/deferred-findings.md').read()
rows = {}
for m in re.finditer(r'^<!-- row:(R-\d{3}) -->\n(.*?)(?=^<!-- row:R-\d{3} -->\n|\Z)', reg, re.S | re.M):
    head = m.group(2).split('- **finding:**', 1)
    assert len(head) == 2, f'{m.group(1)} has no finding field'
    for f in ('source', 'origin', 'original ruling', 'bound criteria', 'current-main check', 'safety floor', 'disposition', 'promotion'):
        assert f'- **{f}:**' in head[0], f'{m.group(1)} missing field {f}'
    src = re.search(r'- \*\*source:\*\*[^\n]*?#(\d+)', head[0])
    assert src, f'{m.group(1)} has no source issue'
    rows[m.group(1)] = int(src.group(1))
for r in ('R-001', 'R-002', 'R-003', 'R-004', 'R-005'):
    assert r in rows, f'{r} (#361 migration) missing'
row_issues = collections.Counter(rows.values())
receipts_closed = {r['issue_or_pr']: r for r in d['receipts'] if r['kind'] == 'issue_close' and r['exit_code'] == 0}
for e in d['entries']:
    n, disp = e['issue'], e['disposition']
    assert disp in allowed and e['evidence'].strip(), f'#{n} bad disposition or empty evidence'
    assert e['precedence_trace'], f'#{n} has no precedence trace'
    if n in receipts_closed:
        assert e['approved'] is True, f'#{n} closed without approval'
        assert disp in ('ALREADY-FIXED', 'OBSOLETE', 'PARKED'), f'#{n} closed with disposition {disp}'
        assert n not in snap_x and n not in A, f'#{n} closed but excluded'
        assert not sr.phase_bindings(n, d['origin_main_at_execution'], mechanical_only=True), f'#{n} closed while bound'
        assert e['binding_review'].strip(), f'#{n} closed without a check-(iv) judgment'
        if disp in ('OBSOLETE', 'PARKED'):
            assert row_issues[n] == 1, f'#{n} needs exactly one register row'
            if e['safety_floor_class'] != 'none':
                assert e['reachability_negative'].strip(), f'#{n} floor-class close without a reachability negative'
        if disp == 'OBSOLETE':
            assert e['removal_commit'], f'#{n} OBSOLETE without a removal commit'
    elif disp in ('ALREADY-FIXED', 'OBSOLETE', 'PARKED') and e['approved']:
        assert e['action'] == 'declined' or 'DRIFTED' in e['evidence'], f'#{n} approved but neither closed nor recorded as a skip'
print('dispositions OK:', collections.Counter(e['disposition'] for e in d['entries']), '| closes:', len(receipts_closed))
PY

# 3. receipts match GitHub; #361 stays open
python3 - <<'PY'
import json, subprocess
T = '/mnt/workspace/board-tools/backlog-triage'
d = json.load(open(f'{T}/item2-dispositions.json'))
disp = {e['issue']: e['disposition'] for e in d['entries']}
for r in d['receipts']:
    if r['exit_code'] != 0 or r['kind'] != 'issue_close':
        continue
    n = r['issue_or_pr']
    v = json.loads(subprocess.run(['gh', 'issue', 'view', str(n), '-R', 'Consiliency/agent-harness',
        '--json', 'state,stateReason,comments'], capture_output=True, text=True, check=True).stdout)
    want = 'COMPLETED' if disp[n] == 'ALREADY-FIXED' else 'NOT_PLANNED'
    assert (v['state'], v['stateReason']) == ('CLOSED', want), (n, v['state'], v['stateReason'])
    if want == 'NOT_PLANNED':
        assert 'docs/registers/deferred-findings.md' in v['comments'][-1]['body'], f'#{n} close comment lacks the register link'
v = json.loads(subprocess.run(['gh', 'issue', 'view', '361', '-R', 'Consiliency/agent-harness', '--json', 'state'],
    capture_output=True, text=True, check=True).stdout)
assert v['state'] == 'OPEN', '#361 must stay open'
print('receipts match GitHub; #361 open')
PY

# 4. docs gates
python3 -m phase_loop_runtime.cli docs-audit --repo . --json
python3 -m pytest -q phase-loop-runtime/tests/test_entry_doc_check.py
```

**Measurement (convergence rule 4).** The attributable delta is the number of successful `issue_close`
receipts. The raw open count before and after is recorded, but it is not asserted, because codex opens
and closes issues concurrently. #361 contributes nothing.

**Expected delta.** This is a judgmental band, not a statistical interval.
- **Base pool:** the 59 non-overlap scope issues. That is 74 (B ∪ D without #361) minus the 15 overlap issues. The pool still contains its EXCLUDED and SCHEDULED issues.
- **Rate:** applying the sample's closable rate of 33–47% gives about 19–28.
- **Overlap:** returned overlap issues may add 0–5 more.
- **Expectation: 18–33 closes.** Below 12 is reported as under-delivery, with reasons. Above 40 triggers an audit of every floor-class call before closing.

## Acceptance criteria

- [ ] `shared_rules.py --self-test` exits 0, and verification script 2 prints `dispositions OK`. It independently recomputes scope coverage from the snapshot, item 1's receipts and GitHub state, and it checks precedence traces, safety-floor evidence, row parsing and binding re-checks.
- [ ] `docs/registers/deferred-findings.md` is unowned and unread. It contains R-001..R-005 migrated from #361, and exactly one schema-complete row, parsed by its `<!-- row:R-NNN -->` marker, for every closed PARKED or OBSOLETE issue.
- [ ] The register PR's diff is exactly `AGENTS.md` and `docs/registers/deferred-findings.md`, with no `specs/` or `plans/manifest.json` change. docs-audit and `test_entry_doc_check.py` pass, and the PR merged only after a 4/4 board and green CI.
- [ ] Every successful `issue_close` receipt matches GitHub (`NOT_PLANNED` with a register link, or `COMPLETED` for ALREADY-FIXED), was approved, and its start postdates `approval.approved_at`. #361 is still open and carries its redirect comment.
- [ ] The attributable delta (successful close receipts) is reported against the 18–33 band, with reasons if it falls outside, and no issue was opened by this item.

## Execution Policy

- execute: effort=medium, reason=about 60 issue bodies each need an ordered precedence decision against current code, with a mandatory safety floor; docs-only repository change
