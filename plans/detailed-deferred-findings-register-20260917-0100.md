# Detailed plan: deferred-findings register and per-finding disposition of buckets B and D

## Task

Convergence item 2. It does three things:
- builds one non-scheduling register for board findings ruled non-blocking;
- gives each open issue in triage buckets B (63 leftovers from phases the manifest records as `completed`) and D (12 deferred follow-ups that belong to no phase) its own disposition;
- makes the register the documented destination for filed deferred findings from now on.

Issues dispositioned PARKED or OBSOLETE get a register row and are closed as not planned. Issues
dispositioned ALREADY-FIXED are closed as completed. Every other issue stays open with a recorded
reason.

**Rules.** The execution rules shared with item 1 — R1 in-flight exclusion union, R2 phase-binding
guard, R3 acceptance extraction, R4 procedural conditions, R5 freshness, R6 receipts, R7 verbatim
fencing, the validation threat model, the close checks (`close_failures`, `published`, `parse_register`
and their helpers), and the `shared_rules.py` self-test — are defined **once**, in `## Shared execution
rules` of `plans/detailed-close-landed-fix-issues-20260917-0100.md`. This plan cites them by name and
restates none of them.

### Pinned input

`/mnt/workspace/board-tools/backlog-triage/triage-snapshot.json`, sha256 `230a8a9c…`, taken
2026-09-17T00:55:58Z against origin/main `11283f80`. Scope source: `buckets.B` ∪ `buckets.D` (75), less
agent-harness#361, which is handled as a migration (see "#361").

### Contract with item 1

Item 1's `## Dependencies & order` → "Contract with item 2" is binding and is not restated here. In
short, this plan starts only on a published item-1 artifact whose `run_status` is `complete` or
`verdicts_only`. Every B/D issue without a successful item-1 `issue_close` receipt is in this plan's
scope.

## Research summary

**Where the register lives.**
- `roadmap_ownership.owners_for` against v10 at `11283f80` returns `[]` for `docs/registers/deferred-findings.md`, and `['GOVLEAN']` for any `plans/` path.
- `git grep -nE 'docs/registers|deferred-findings'` over `phase-loop-runtime/src`, `phase-loop-runtime/scripts`, `.github`, `ci` and `scripts` is empty, so no runner, discovery path or gate reads it.
- `docs_surfaces.classify_surface` returns `None` for both new paths.
- `AGENTS.md` is in `entry_doc_check.PACKAGE_LONG_DESCRIPTION_DOCS`, so any path it names must exist.

**Filing is already ruled, by two sources, and this plan must not widen or narrow them.**
- The maintainer-ratified design on agent-harness#442 (2026-08-04): *"every `DEFERRED` finding must have a filed issue carrying its verbatim text before dispatch"*, falsified by *"a `DEFERRED` finding with no filed issue at dispatch"*. It concerns president rulings.
- Frozen v10 Execution Notes gate 2 (`specs/phase-plans-v10.md:1357-1361`): of the five chair classes, only an unscheduled finding is filed — *"a downstream finding is mapped to its existing criterion, or filed as a repository-qualified issue when unscheduled"*. Scheduled findings are retained against or mapped to criteria, and `nit_no_action` is not filed.
- The register therefore cannot replace filing, and must not add filing either. Round 2 of this PR's board caught the earlier draft filing *every* non-blocking finding; since scheduled filings stay open, that would have added open issues at every gate.
- #442 also says a `DEFERRED` finding "becomes tracked work". Whether a register row with a promotion rule is tracked work is a maintainer ruling. This plan does not assume it: the operator decides it at the approval gate (step 4).

**#361 is cited by frozen text.** HARDEN Non-goals (`specs/phase-plans-v10.md:658`) reads "Re-opening
the accepted-residual register (agent-harness#361). Items there are promoted individually only on new
reachability evidence." HARDEN is `committed`, and R2 binds #361 mechanically, so #361 stays open as a
redirect.

**B and D contain bound, held, and live issues that titles hide.**
- **Bound through RESIDUAL content (R2 check v):** #341 is EC-RESIDUAL-7 and IF-0-RESIDUAL-4; #360 is EC-RESIDUAL-5.
- **Bound by unfinished detailed plans (R2 check ii):** #748, #817, #842, #843.
- **Bound to a committed criterion (R2 check iv):** #445 and #444 are "DEFERRED under `EC-REVIEWTRUTH-19`".
- **Under an operator hold (R1):** #843.
- **Live despite a mitigation:** #595 records that a direct `run_train` call skips the generation lease. The defect is still at `train_runner.py:3620-3621` and contradicts frozen FABPUB plan text (`plans/phase-plan-v10-FABPUB.md:298`, which acquires the lease "at the public `run_train` boundary"), even though the CLI path is fail-closed.

**Sample of 16 B/D bodies**, read at `11283f80`, provisionally classified under the rules below:

| Issue | Phase | What the body establishes | Provisional |
|---|---|---|---|
| #445 | CONFORM | DEFERRED "under `EC-REVIEWTRUTH-19`"; producer provenance not independently enforced | SCHEDULED (R2 check iv) |
| #519 | CONFORM | Seal digest depends on build-host umask; mitigated under `umask 022` | PARKED |
| #790 | CONFORM | `vectors_executed` hardcoded `false`; the corpus runner is never called outside tests | DECISION-REQUIRED |
| #474 | PROOFGATE | Fable president DEFERRED PGB-003 | OBSOLETE only if its mechanism is removed from main; otherwise PARKED |
| #761 | PROOFGATE | Receipt mechanism "owned by nothing" after re-plan; "abandon or re-home" | DECISION-REQUIRED |
| #590 | FABPUB | Verification command is lifecycle-position dependent; workaround recorded | PARKED |
| #817 | FABPUB | Receipt loader joins a receipt-supplied `cutover_id` raw; an absolute path or `..` escapes | SCHEDULED (R2 check ii); STILL-LIVE if unbound |
| #842 | FABPUB | Import-time test seam rebinds the production latch | EXCLUDED (R1) |
| #640 | FABREADMIT | Grok 4.6 president: "downstream tightening rather than blockers" | PARKED |
| #554 | GOVLEAN | President classified every item DEFERRED; `carried_with_owner` | PARKED, unless an item is floor-class |
| #748 | GOVLEAN | Proposal: CI attests the agent's EC-GOVLEAN-4 receipt | SCHEDULED (R2 check ii) |
| #539 | LEGIBLE | Canonical test arm never runs in CI; "filed so the asymmetry is on the record" | PARKED |
| #797 | LEGIBLE | Three contract probes red on main | STILL-LIVE |
| #399 | D | Four non-blocking follow-ups; "none are urgent" | PARKED |
| #754 | D | Bounded TOCTOU residual carried per a round cap | STILL-LIVE, unless a reachability negative is recorded (floor class) |
| #796 | D | Choose one `PHASE_LOOP_VERIFY_ENFORCE` default | DECISION-REQUIRED |

**Arithmetic.** The sample has 16 rows; #842 is EXCLUDED, leaving 15 evaluable. 5 to 7 are closable:
PARKED #519, #590, #640, #539 and #399, plus #554 and #474 if confirmed. That is 33–47%. Bucket B is not
homogeneous, so every issue is decided from its body, its comments and current code, never its title.

## Changes

### `docs/registers/deferred-findings.md` (create)

- **Header, "Purpose and status": add.** It states:
  - this is a record, not a work queue;
  - nothing in the runtime reads it;
  - #361's rule, quoted verbatim: "Do not schedule from this register directly."
- **Header, "How findings enter": add.** The single written statement of the convention.
  1. **Filing is unchanged.** It is governed by agent-harness#442 and v10 Execution Notes gate 2, whose filing sentences the header quotes verbatim (the two quotations in the research summary above). The register neither adds nor removes a filing obligation: a finding those sources do not file is not filed because of this register.
  2. **Disposition.** Each issue filed under those sources receives a disposition comment naming its category (below) **before the board's PR merges**.
     - PARKED or OBSOLETE: its row lands in a later register PR, which may batch rows. The issue is closed as not planned only once its row is on main, with a permalink to the row. Until then it is open with its disposition recorded — a bounded, visible queue.
     - SCHEDULED, STILL-LIVE or DECISION-REQUIRED: the issue stays open.
  3. **Scope.** This is a documented convention only. Runtime enforcement of a destination for `DEFERRED` rulings is a later convergence item.
- **Header, "Categories and precedence": add.** The seven dispositions and the precedence below, stated once here and cited by the convention.
- **Header, "Promotion rule": add.**
  - **Trigger:** a row returns to scheduled work only on new reachability evidence — a new production caller, a changed trust boundary, or a demonstrated exploit or failure path — and the evidence is cited.
  - **Mechanism:** reopen the row's source issue with that evidence. The row is marked `PROMOTED <date> <evidence link>` and is never deleted.
- **Rows R-001..R-005: add.** The five residuals in #361's table (#276, #273, #272, #269, #266, all closed today), migrated verbatim. Each row's `original ruling` quotes #361's table row. The header quotes #361's original promotion text verbatim: "split it back out as its own P-ranked issue WITH the reachability evidence". Reopening the source issue satisfies that text, because the source issue is that residual's own issue.
- **Rows R-006 onward: add.** One row per issue dispositioned PARKED or OBSOLETE and approved.

**Row format**, parsed by `parse_register`:

````markdown
<!-- row:R-006 -->
### R-006 — <issue title>
- **source:** Consiliency/agent-harness#640
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

Row markers and field lines count only outside code fences, and `finding` is always the last field, so
verbatim `###` headings, fences, or a copied row marker inside a finding cannot be mistaken for row
structure. A row does not state the issue's GitHub state; GitHub does.

### `AGENTS.md` (modify)

- **`## Plan discipline (why phases stall)`: add one pure pointer sentence.** "The destination for
  filed deferred board findings is defined in `docs/registers/deferred-findings.md`." It states no part
  of the rule, so it cannot drift from it.

### No other repository file changes

- no `specs/` change;
- no `plans/manifest.json` row;
- no runtime code;
- no RESIDUAL-owned path, including RESIDUAL's own `plans/evidence/v10-RESIDUAL-f841-triage.md`.

### Execution artifacts, off-repo

- **`/mnt/workspace/board-tools/backlog-triage/item2-dispositions.json`**, schema `item2_dispositions.v1`. Top level:
  - `schema`, `run_status` (`complete`: every approved mutation executed or skipped; `verdicts_only`: no issue closed and no register PR merged; `aborted`), `started_at`, `origin_main_at_execution`;
  - `item1_artifact_sha256`;
  - `entries`, one per scope issue;
  - `receipts` — the R6 issue and PR mutation receipts.

  Each entry records:
  - `issue`, `bucket`, `disposition`, `evidence`;
  - `precedence_trace` — one `{category, applies, reason}` step per category, in precedence order, up to and including the disposition; the STILL-LIVE step also carries `floor_class` (`none` or the class);
  - `phase_bindings` and `binding_review`, per R2;
  - for ALREADY-FIXED: item 1's verdict-entry fields `naming_commits`, `effect_commits`, `acceptance_conditions` and `verdict_baseline`, with the same meaning;
  - `reachability_negative` — for a floor-class close: `{"kind": "removed", "removal_commit", "grep_pattern", "paths"}` or `{"kind": "callers", "callers": [{"site", "why_unreachable"}]}`;
  - `removal` — for OBSOLETE: `{commit, grep_pattern, paths}`;
  - `president_deferred` — whether the original ruling is a president `DEFERRED`;
  - `register_row` — `R-NNN` or `null`;
  - `action` — `closed_not_planned`, `closed_completed`, `declined`, `skipped` (with `skip_reason`), or `none`.
- **`item2-approval-batch.json`** — item 1's approval-batch format.
- **`item2-approval-batch.md`** — the rendered list the operator reads.
- **`item2-publication-receipts.json`** — per R6.

### Disposition categories and precedence

Each scope issue is tested against the categories **in this order**; the first that applies is its
disposition:

**EXCLUDED > SCHEDULED > DECISION-REQUIRED > STILL-LIVE > ALREADY-FIXED > OBSOLETE > PARKED**

Every decision reads the full body, all comments, any linked PR or commit, and the current code at the
cited location.

| Disposition | Applies when | Action |
|---|---|---|
| **EXCLUDED** | The issue is in an A bucket, or in R1's exclusion union at execution (which includes operator holds such as #843). | none |
| **SCHEDULED** | R2 returns any binding (checks i–v). Examples: #341, #360, #445, #748, and item-1 guard-held issues such as #454, #733 and #428. | none; stays open, with the binding recorded |
| **DECISION-REQUIRED** | The issue asks for a maintainer choice that changes production behaviour or policy (#790, #796). This includes "abandon or re-home" cases (#761), and anything descoped but still present in the code. | none; stays open, listed for the operator |
| **STILL-LIVE** | Any of: the defect is reachable on current main (a production caller reaches it, in the sense of the reachability negative's (b) below); the finding is in a safety-floor class and has no reachability negative; or it contradicts a frozen requirement — frozen spec or phase-plan text, or a class agent-harness#442 names non-deferrable, quoted: *"a finding contradicting staged prober evidence, an attestation claim, or a frozen-test invariant is NOT deferrable"*. | none; stays open, reason recorded |
| **ALREADY-FIXED** | Item 1's verdict rule yields FIXED at this plan's execution SHA, with item 1's evidence fields. | close as `completed` with item 1's close-comment format |
| **OBSOLETE** | The mechanism, file or path the finding concerns has been **removed from current main**, recorded as `removal`. "Explicitly descoped" alone does not qualify. | register row, then close as not planned |
| **PARKED** | The original ruling classed the finding `DEFERRED`, non-blocking or nit; no earlier category applied; and the safety floor is satisfied. | register row, then close as not planned |

**Safety floor.** The floor is a precondition of **every** close path that leaves a defect unfixed (OBSOLETE and PARKED).

*Floor classes:* path containment, credentials, authorization or authority, fail-open verification,
and concurrency or TOCTOU on an authority or evidence path. `ci/main-red.sh`'s issue state (#754) is
an evidence path.

*Reachability negative.* A floor-class finding may be closed only with one of these, recorded at
`origin_main_at_execution`:
- **(a)** `removed`: the cited code or mechanism no longer exists on main, shown by the removal commit plus a grep that finds nothing; or
- **(b)** `callers`: every production caller of the cited code is enumerated, and each is shown not to reach the defect.

These **never** count as a reachability negative:
- the original deferral's reasoning;
- a mitigation note or workaround;
- a fail-closed CLI when a direct API path remains (#595);
- "not urgent".

### Agent-harness#361

#361 is **not** dispositioned and **not** closed. Its five rows migrate as R-001..R-005, and it
receives one approved comment. The comment:
- redirects to the register;
- quotes `specs/phase-plans-v10.md:658`;
- explains that the issue stays open because frozen HARDEN Non-goals cite it.

It contributes nothing to the measured delta.

## Documentation impact

- `docs/registers/deferred-findings.md` — add — the register, and the single statement of the convention.
- `AGENTS.md` — modify — one pure pointer sentence. The path it names exists in the same PR, as entry-doc-check requires.
- `CHANGELOG.md` — no change. `classify_surface` returns `None` for both paths.
- `specs/phase-plans-v10.md` — no change (frozen). The convention quotes gate 2 and does not alter it.

## Dependencies & order

1. **Start contract.** Check item 1's artifact against its "Contract with item 2" with `published()`. On any failure, do not start and report to the operator. Run `shared_rules.py --self-test` too; it must exit 0.
2. **Scope.** The scope is:

   ((pinned B ∪ D) − {361}) − {issues with a successful item-1 `issue_close` receipt} − {issues GitHub shows closed before `started_at`}

   Issues opened after the snapshot are never added (convergence rule 1). EXCLUDED issues remain in scope as a disposition, so coverage is exact.
3. **Disposition every scope issue** by the precedence above, writing `item2-dispositions.json`. For an overlap issue item 1 ruled PARTIAL, re-verify item 1's held conditions at this plan's execution SHA before relying on them.
4. **Approval.** Run R5 over every intended mutation, then present `item2-approval-batch.md`. It enumerates:
   - each close: disposition, the precedence trace's floor-class call and reason, the register row anchor, and the full comment text. A not-planned close comment links its row as `https://github.com/Consiliency/agent-harness/blob/<merged main SHA>/docs/registers/deferred-findings.md#r-nnn`; the SHA is unknown until merge, so the approved text carries `{MERGED_MAIN}` there, and `body_sha256` abstracts exactly that SHA;
   - **as a separate group, every PARKED close whose `president_deferred` is true.** Approving this group is the operator's ruling that a register row with a promotion rule satisfies #442's "becomes tracked work"; declining it leaves those issues open, dispositioned PARKED, with action `declined`;
   - the #361 comment;
   - the register PR's open and merge (also governed by the standing public-repo CR gate);
   - the two publication comments (batch, artifact).

   On approval, write and publish `item2-approval-batch.json` per item 1's Operator approval gate and Publication. Nothing is mutated before it is published.
5. **Build the register branch** from the approved rows plus the `AGENTS.md` pointer. Verify locally, then open the register PR (receipt `pr_open`).
6. **Board review of the register PR**, at most 3 rounds. If review changes a row's content or a disposition, the changed items return to the operator for re-approval and a new published batch.
7. **Merge** only after a 4/4 board and green CI (receipt `pr_merge`).
8. **For each approved close:** run R5, then close with the permalink at the merged main SHA, then record a receipt. After the closes, post the #361 comment (receipt).
9. **Set `run_status`, measure, publish** the artifact per item 1's Publication.

**Descope, terminal.** If the register PR is not 4/4 AGREE by round 3, or this plan's own board does not
converge by its round 3, nothing merges and nothing is closed: the register PR stays unmerged, every
approved close is `skipped` with `skip_reason: "descoped: <reason>"`, `run_status` is `verdicts_only`,
and the artifact is published. The dispositions still stand as a record.

## Verification

Run from a checkout with `origin` fetched, `gh` authenticated, and `PYTHONPATH=$PWD/phase-loop-runtime/src`.

```bash
T=/mnt/workspace/board-tools/backlog-triage
python3 $T/shared_rules.py --self-test

# 1. ownership, non-readership, exact file set of the register PR (complete runs)
python3 - <<'PY'
from pathlib import Path
from phase_loop_runtime import roadmap_ownership as ro
m = ro.ownership_map(Path('specs/phase-plans-v10.md').read_text())
assert ro.owners_for('docs/registers/deferred-findings.md', m) == [], 'register path is owned'
print('owners OK')
PY
test -z "$(git grep -nE 'docs/registers|deferred-findings' origin/main -- phase-loop-runtime/src phase-loop-runtime/scripts .github ci scripts)" && echo 'unread OK'
test "$(gh pr diff <REGISTER_PR> -R Consiliency/agent-harness --name-only | sort | tr '\n' ' ')" = "AGENTS.md docs/registers/deferred-findings.md " && echo 'file set OK'

# 2. coverage, approval, precedence, close safety and register rows, against GitHub and git
python3 - <<'PY'
import json, os, re, sys, collections
T = os.environ.get("T", "/mnt/workspace/board-tools/backlog-triage")
sys.path.insert(0, T)
import shared_rules as sr
s = json.load(open(f"{T}/triage-snapshot.json"))
i1, _ = sr.published(f"{T}/item1-publication-receipts.json", "artifact")
assert i1["run_status"] in ("complete", "verdicts_only"), "item 1 not in a startable state"
d = json.load(open(f"{T}/item2-dispositions.json"))
batch, batch_at = sr.published(f"{T}/item2-publication-receipts.json", "batch")
art, _ = sr.published(f"{T}/item2-publication-receipts.json", "artifact")
assert art == d and d["schema"] == "item2_dispositions.v1" and d["run_status"] in ("complete", "verdicts_only", "aborted"), "schema/run_status"
assert batch["approved_at"] <= batch_at, "batch published before its approval"
ORDER = ["EXCLUDED", "SCHEDULED", "DECISION-REQUIRED", "STILL-LIVE", "ALREADY-FIXED", "OBSOLETE", "PARKED"]
A = set(s["buckets"]["A1"] + s["buckets"]["A2"] + s["buckets"]["A3"])
snap_x = set(s["codex_inflight_exclusions"])
# 1. coverage, from the snapshot, item 1's published receipts and live GitHub state
i1_closed = {r["issue_or_pr"] for r in i1["receipts"] if r["kind"] == "issue_close" and r["exit_code"] == 0}
pinned = (set(s["buckets"]["B"]) | set(s["buckets"]["D"])) - {361}
live = {n: sr.gh_issue(n) for n in pinned | {361}}
expected = {n for n in pinned - i1_closed if not (live[n]["state"] == "CLOSED" and live[n]["closedAt"] < d["started_at"])}
E = {e["issue"]: e for e in d["entries"]}
assert len(E) == len(d["entries"]), "an issue appears twice"
assert set(E) == expected, f"coverage: missing {sorted(expected - set(E))}, extra {sorted(set(E) - expected)}"
# 2. every mutation was approved, published first, and executed or skipped
M = {(m["kind"], m["target"]): m for m in batch["mutations"]}
assert len(M) == len(batch["mutations"]), "duplicate batch entry"
done = {}
for r in d["receipts"]:
    key = (r["kind"], r["issue_or_pr"])
    assert r["kind"] in ("issue_close", "issue_comment", "pr_open", "pr_merge") and type(r["issue_or_pr"]) is int, f"bad receipt {key}"
    assert key in M, f"{key} executed but not in the published approved batch"
    assert r["started_at"] >= batch_at, f"{key} started before the approved batch was published"
    if r["exit_code"] == 0:
        done[key] = r
for key in M:
    if key in done:
        continue
    if key[0] == "issue_close":
        assert key[1] in E and E[key[1]]["action"] == "skipped", f"approved {key} neither executed nor recorded as skipped"
    else:
        assert d["run_status"] != "complete", f"approved {key} not executed in a complete run"
if d["run_status"] == "verdicts_only":
    assert not any(k[0] in ("issue_close", "pr_merge") for k in done), "a verdicts_only run closed issues or merged"
# 3. per-entry precedence and close safety
closed_np = {}
for n, e in E.items():
    disp, act = e["disposition"], e["action"]
    assert disp in ORDER and e["evidence"].strip(), f"#{n} bad disposition or empty evidence"
    assert [t["category"] for t in e["precedence_trace"]] == ORDER[:ORDER.index(disp) + 1], f"#{n} precedence trace is not the ordered prefix up to {disp}"
    if n in A or n in snap_x:
        assert disp == "EXCLUDED", f"#{n} is excluded by the snapshot but dispositioned {disp}"
    k = ("issue_close", n)
    assert (act in ("closed_completed", "closed_not_planned")) == (k in done), f"#{n} action {act} disagrees with its close receipt"
    if k in M:
        assert disp in ("ALREADY-FIXED", "OBSOLETE", "PARKED"), f"#{n} close approved with disposition {disp}"
        assert M[k]["reason"] == ("completed" if disp == "ALREADY-FIXED" else "not_planned"), f"#{n} approved close reason"
    if act == "skipped":
        assert k in M and e.get("skip_reason", "").strip(), f"#{n} skipped without an approved close or a reason"
    if k not in done:
        continue
    fixed = disp == "ALREADY-FIXED"
    issue = live[n]
    fails = sr.close_failures(n, e, issue, M[k], done[k], fixed=fixed)
    assert not fails, f"#{n} unsafe close: {fails}"
    if fixed:
        continue
    ref = sr.close_ref(issue["closedAt"])
    floor = e["precedence_trace"][ORDER.index("STILL-LIVE")]
    assert floor.get("floor_class") and floor.get("reason", "").strip(), f"#{n} STILL-LIVE step records no floor-class call"
    neg = e.get("reachability_negative") or {}
    if floor["floor_class"] != "none":
        if neg.get("kind") == "removed":
            assert sr.is_ancestor(neg["removal_commit"], ref) and sr.grep_absent(neg["grep_pattern"], neg["paths"], ref), f"#{n} removal negative does not hold at {ref[:8]}"
        else:
            assert neg.get("kind") == "callers" and neg.get("callers"), f"#{n} floor-class close without a reachability negative"
    if disp == "OBSOLETE":
        rm = e.get("removal") or {}
        assert rm and sr.is_ancestor(rm["commit"], ref) and sr.grep_absent(rm["grep_pattern"], rm["paths"], ref), f"#{n} OBSOLETE but the mechanism is present at {ref[:8]}"
    link = next((mm for c in issue["comments"] if c["createdAt"] >= done[k]["started_at"] and sr.body_sha256(c["body"]) == M[k]["body_sha256"]
                 for mm in re.finditer(r"blob/([0-9a-f]{40})/docs/registers/deferred-findings\.md#(r-\d{3})", c["body"])), None)
    assert link and sr.is_ancestor(link.group(1), "origin/main"), f"#{n} close comment has no register permalink on main"
    rows = sr.register_at(link.group(1)) or {}
    row = rows.get(link.group(2).upper())
    assert row and re.search(r"#%d\b" % n, row["source"]) and row["disposition"].startswith(disp), f"#{n} permalink row does not record #{n} as {disp}"
    closed_np[n] = row
# 4. register on main: #361 migration present; no row for an issue that is neither closed nor a recorded skip
reg = sr.register_at("origin/main")
if d["run_status"] == "complete":
    assert reg is not None, "register missing from main"
    assert {"R-001", "R-002", "R-003", "R-004", "R-005"} <= set(reg), "#361 migration rows missing"
    for rid, row in reg.items():
        if rid in ("R-001", "R-002", "R-003", "R-004", "R-005"):
            continue
        src = int(re.search(r"#(\d+)", row["source"]).group(1))
        assert src in closed_np or E.get(src, {}).get("action") == "skipped", f"{rid} records #{src}, which was neither closed nor skipped"
    assert ("issue_comment", 361) in done and sr.posted(live[361], M[("issue_comment", 361)], done[("issue_comment", 361)]), "#361 redirect comment missing"
assert live[361]["state"] == "OPEN", "#361 must stay open"
print("dispositions OK:", dict(collections.Counter(e["disposition"] for e in d["entries"])), "| closes:", sum(k[0] == "issue_close" for k in done))
PY

# 3. docs gates (complete runs)
python3 -m phase_loop_runtime.cli docs-audit --repo . --json
python3 -m pytest -q phase-loop-runtime/tests/test_entry_doc_check.py
```

Script 2 was run before this revision against synthetic runs with a fake `gh`. It passes a correct
complete run, an unrelated later comment, a close skipped after its row merged, and a terminal descope.
It fails a close of an issue R1 named before the close, a PARKED close of content-bound #341, an
ALREADY-FIXED close of #595 without conditions, a precedence trace that skips STILL-LIVE, a floor-class
close without a negative, an approved close neither executed nor skipped, a register row for an issue
neither closed nor skipped, a permalink whose row names another issue, a mutation started before the
batch was published, a dropped entry, and a closed #361.

**Measurement (convergence rule 4).** The attributable delta is the number of successful `issue_close`
receipts. The raw open count before and after is recorded but not asserted, because codex opens and
closes issues concurrently. #361 contributes nothing.

**Expected delta.** A judgmental band, not a statistical interval.
- **Base pool:** the 59 non-overlap scope issues (74 B ∪ D without #361, minus the 15 overlap issues), EXCLUDED and SCHEDULED issues included.
- **Rate:** applying the sample's closable rate of 33–47% gives about 19–28.
- **Overlap:** returned overlap issues may add 0–5 more.
- **Expectation: 18–33 closes**, before any operator decision on the president-`DEFERRED` group. Below 12 is reported as under-delivery, with reasons. Above 40 triggers an audit of every floor-class call before closing.

## Acceptance criteria

- [ ] `shared_rules.py --self-test` exits 0, and verification script 2 prints `dispositions OK` for the run's `run_status`.
- [ ] If `run_status` is `complete`: `docs/registers/deferred-findings.md` on main is unowned and unread, contains R-001..R-005, and has a parseable row for every not-planned close and no row for an issue neither closed nor skipped; the register PR's diff is exactly `AGENTS.md` and the register; docs-audit and `test_entry_doc_check.py` pass; the PR merged after a 4/4 board and green CI; #361 is open with its redirect comment.
- [ ] If `run_status` is `verdicts_only`: no issue was closed, no register PR merged, and the dispositions artifact is published.
- [ ] The attributable delta (successful close receipts) is reported against the 18–33 band, with reasons if it falls outside, and no issue was opened by this item.

## Execution Policy

- execute: effort=medium, reason=about 60 issue bodies each need an ordered precedence decision against current code, with a mandatory safety floor; docs-only repository change
