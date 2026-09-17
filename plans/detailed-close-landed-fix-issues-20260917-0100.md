# Detailed plan: verify and close the open issues that already have a landed fix

## Task

This is item 1 of the backlog-convergence sequence. The open-issue count has risen every week for nine
weeks and has never fallen. Part of that count is bookkeeping: issues whose fix already landed on
`main` were never closed.

This plan verifies each landed-fix candidate against its own acceptance conditions. It closes only the
ones that are really fixed and hands every other verdict on, as specified below. It is item 1 of 2
planned together. Item 2 (the deferred-findings register,
`plans/detailed-deferred-findings-register-20260917-0100.md`) runs **after** this plan and consumes
its verdict artifact.

### Pinned input

`/mnt/workspace/board-tools/backlog-triage/triage-snapshot.json`:
- sha256 `230a8a9c66cde38c375020af5921bf1233292b4b31357af15de2b6fa414e8ef3`;
- taken 2026-09-17T00:55:58Z against origin/main `11283f80`, with 223 open issues.

Its `landed_commit_candidates` key holds **30 issues**. For each, at least one commit on `main` has a
subject that names the issue with a `fix(`, `feat(`, `test(`, `docs(`, `chore(` or `plan(` prefix.
This plan does not re-derive the set. A commit subject is only how an issue entered the set; it is
never evidence of a fix.

### Scope, per the contract with item 2

| Set | Issues | Treatment |
|---|---|---|
| Out of scope: A buckets (HARDEN critical path) | #241 (A2), #825 (A3) | Record only, never close |
| Out of scope: codex in-flight | #525, #789, #825, #870 | Record only, never close |
| **In scope, bucket B** | #428, #451, #454, #456, #463, #464, #470, #481, #488, #490, #493, #498, #688 | Close if FIXED; otherwise hand to item 2 |
| **In scope, bucket D** | #733 | Close if FIXED; otherwise hand to item 2 |
| **In scope, bucket C** | #442, #660, #678, #685, #720 | Close if FIXED; otherwise stay open with the verdict recorded |
| **In scope, bucket E** | #358, #398, #601, #607, #630, #633 | Close if FIXED; otherwise stay open with the verdict recorded |

That makes 25 in scope and 5 out of scope. #825 sits in both out-of-scope rows; it stays with codex.

## Research summary

Ten candidates were spot-checked, across all six prefixes, to ground the verdict rule. These checks
compared each issue's acceptance text to the landed diff and to current `origin/main`. They are
**evidence for the rule, not final verdicts**; execution re-derives every verdict.

- **#488** — `fix(ci)` `97d223e7` changed two `timeout-minutes` values in `.github/workflows/test.yml`. On main the long jobs are now 120/100 min, the lint jobs stay at 5, and no CONFORM test was skipped. The acceptance holds on main. **FIXED-shaped.**
- **#470** — `test(CONFORM)` `e69a3132` rewrote the evidence fixture (+362 lines in `test_outside_agent_conform_evidence.py`). The defect was itself in a test fixture, so a `test(` commit can be the fix. **FIXED-shaped**, pending a check that the cross-mode `records_for` collision path is gone.
- **#464** — two `Revert` commits undo its `docs(CHANGELOG)` commit, and the surviving naming commit `b319b310` only adds `docs/releases/ci-archive-build-tooling.md`. Yet the acceptance effect — CI installs a pinned `build` — **holds on main** (`test.yml` installs `build==1.6.1`), through later `#428` commits that do not name #464. The lessons: a revert says nothing about the effect, and the effect commit need not name the issue. **FIXED-shaped via another commit.**
- **#733** — `docs(advisor-board)` `d96f85a4` says it will "sweep every surface for the stall wording". The wording "slow/stalled leg" is **still present** in `panel_invoker.py` on main, at lines 5441 and 6060. A subject promising a complete fix does not mean the fix is complete. **PARTIAL.**
- **#688** — `feat(roadmap)` `d1d6884b` landed the `--candidate-roadmap` instrument. The issue itself says "This is a roadmap decision, not a code change", and the GOVLEAN `Key files` narrowing was never applied to v10. **PARTIAL.**
- **#358** — the body is only "see consolidation", so its acceptance lives in a linked document. `fix(REVIEWTRUTH)` `1dd3a83a` enforces the ≥2-leg floor, which is one of the three P0 defects in the title. **PARTIAL.**
- **#442** — `fix(REVIEWTRUTH)` `d17419bb` touches only `plans/phase-plan-v10-REVIEWTRUTH.md` and `plans/manifest.json`. The issue asks the maintainer to ratify EC-REVIEWTRUTH-18, and that has not happened. **MENTION-ONLY.**
- **#498** — `docs(CONFORM)` `3c3878a3` "authorize clean-clone history repair" changes only `plans/phase-plan-v10-CONFORM.md`. **MENTION-ONLY**, unless an unnamed commit carries the effect.
- **#601 / #607** — both are named only by `chore(plan)` `4a3bd86e`, which adds a plan document. A later merge (PR #612, branch `claude/plan-evidence-existence-gate`) does not name either issue. **MENTION-ONLY**, pending an effect search.
- **#241** (out of scope) — `docs(triage)` `31473d88` *created* the pointer to #241 ("residuals -> #241"). This is the purest MENTION-ONLY case.

Three findings from these checks shape the rule:
- **Verdicts come from effects on current main, not from which commits exist** (#464, #733).
- **Commits that only touch plans, authorizations, or records never satisfy a code or behaviour condition on their own** (#442, #498, #601, #607).
- **Some acceptance conditions live outside the issue body** (#358).

Codex's in-flight state was checked for collisions. `origin/codex/merged-repairs-closeout-20260917`
(one commit, `2242e938`, 00:38Z) changes only `plans/manifest.json` (+229/−4) and records the #868
and #871 repairs. So codex runs its own closeout for #825 and #870, both of which are excluded. That
branch name carries no issue number, so the snapshot's branch-name exclusion rule would not have
caught it; execution has to inspect branch diffs, not just names.

## Changes

**No repository source, test, configuration or documentation file is changed by executing this plan.**
Execution produces an off-repo artifact and GitHub issue state. The only repository change is this
plan file itself, which the parent commits on `claude/backlog-convergence-plans`.

### Verdict artifact `/mnt/workspace/board-tools/backlog-triage/item1-landed-fix-verdicts.json` (create at execution)

- **Schema `landed_fix_verdicts.v1`** — add — this is the one artifact item 2 consumes. Top-level fields:
  - `schema`;
  - `snapshot_ref` `{path, sha256, snapshot_at, origin_main}`;
  - `executed_at`;
  - `origin_main_at_execution`;
  - `exclusions_at_execution` (sorted ints);
  - `approval` `{approved_at, batch_list_sha256}`;
  - `open_count_before`;
  - `open_count_after`;
  - `verdicts` — exactly one entry per snapshot candidate, all 30.
- **Verdict entry** — add — fields:
  - `issue` (int);
  - `bucket` (`A1`–`E`);
  - `verdict` (enum below);
  - `naming_commits` (sha list);
  - `effect_commits` (sha list; may differ from the naming commits);
  - `reverts` (sha list);
  - `acceptance_conditions` — a list of `{text, source, holds_on_main, evidence}`. `source` is `body` or a linked URL. `evidence` is a file path with a quoted line, or a command and its output digest;
  - `cited_by_open_phase` (list of `{file, line}`; empty when no non-completed phase plan cites the issue);
  - `action` (`closed` | `commented` | `handed_to_item2` | `recorded_only`);
  - `github_url` (the close or comment URL, or `null`).
- **Rendered companion `item1-landed-fix-verdicts.md`** — add — a human table (issue, bucket, verdict, action, cited effect commit). This is the text of the batch approval list and of the PR comment.

### The verdict rule (normative for execution)

The **acceptance conditions** of an issue are read from its body sections headed *Acceptance*,
*Required repair*, *Required correction*, *Required disposition*, or *Proposed*. If the body defers
elsewhere ("see consolidation"), follow the link and use the conditions found there. If the body
states only a problem, the condition is "the observed failure no longer reproduces on origin/main",
and it needs a concrete check. A condition that cannot be located or checked is recorded
`holds_on_main: false`, with evidence `unverifiable`.

A **procedural condition** (for example "receive Sol/Fable review before landing") is treated as
follows:
- For a **bucket B** issue, it is satisfied when the owning phase's `plans/manifest.json` lifecycle is `completed`, because that phase's closeout accepted its landings.
- For a **C or E** issue, it needs the landing PR's recorded review, otherwise it is `false`.

This convention is flagged for the board.

| Verdict | Evidence required | Action |
|---|---|---|
| **FIXED** | Every acceptance condition `holds_on_main: true` on `origin_main_at_execution`, each with at least one effect commit on main or a direct check. An effect commit need not name the issue. | Close as `completed`, with the close comment below. |
| **PARTIAL** | At least one condition holds via a landed change, and at least one does not or is `unverifiable`. | **C/E:** comment listing held and unheld conditions; leave open. **B/D:** no GitHub action; `handed_to_item2`, with the per-condition evidence. |
| **MENTION-ONLY** | No condition holds via a landed change. The naming commits only plan, authorize, document, record, or re-point the issue. | **C/E:** `recorded_only`. **B/D:** `handed_to_item2`. |
| **REVERTED** | A naming or effect commit was reverted, and after the revert no condition holds on main. If an effect still holds through another commit, use FIXED or PARTIAL on the effect and list the revert SHAs in `reverts`. | Same routing as MENTION-ONLY. |
| **OUT-OF-SCOPE** | In A1, A2 or A3, or in `exclusions_at_execution`. | `recorded_only`. Never closed, never commented. |
| **DRIFTED** | Closed by someone else since the snapshot, or newly referenced by an open PR or a codex branch diff. | `recorded_only`. No mutation. |

**Committed-phase citation guard.** Before any close, grep the issue's qualified number in
`specs/phase-plans-v10.md` and every `plans/phase-plan-v10-*.md` whose `plans/manifest.json`
lifecycle is not `completed`. If a non-completed phase plan cites the issue, the issue is **not
closed**, even when every condition holds. It keeps verdict FIXED and gains `cited_by_open_phase`,
listing each citing file and line. The action is `handed_to_item2` for B/D issues, where item 2's
SCHEDULED disposition applies, and `recorded_only` for C/E issues. The reason: a committed plan can
use an open issue as a live gate. `plans/phase-plan-v10-RELEASE.md` makes agent-harness#454 a
fail-closed admin-identity trigger, and `plans/phase-plan-v10-RESIDUAL.md` names the
agent-harness#733 disposition as a precondition. Closing either would silently change a committed
phase's behaviour. Both are in scope here, so this guard is expected to fire on at least those two.

A candidate is never FIXED on subject text. Commits that touch only `plans/`, `.consiliency/`, or
records under `docs/` can be effect commits only where the condition itself is a document condition.

### Close mechanics

- **FIXED:** run `gh issue close <N> -R Consiliency/agent-harness --reason completed --comment "<body>"`. The body cites each condition, the effect commit that satisfies it, and the evidence:

  ```
  Closing as completed. Each acceptance condition holds on origin/main `<sha7>`:
  - <condition text> — satisfied by `<effect sha7>` (<subject>); evidence: <file:line or check>.
  Verified by the landed-fix triage, plans/detailed-close-landed-fix-issues-20260917-0100.md.
  Reopen if a condition was missed.

  🤖 Generated with [Claude Code](https://claude.com/claude-code)
  ```
- **PARTIAL in C or E:** run `gh issue comment <N>`, listing held conditions (with effect commits) and unheld conditions (with the reason). Never close it.
- **Everything else:** no GitHub action.
- **Comment hygiene:** comments use qualified `Consiliency/agent-harness#N` references and never use a closing keyword against another issue.

### Drift detection at execution

1. **Re-snapshot first.** Regenerate the snapshot into `triage-snapshot-exec.json` with the same derivation, then diff it against the pinned snapshot:
   - a candidate that is now closed becomes **DRIFTED**;
   - new landed commits that name an in-scope candidate are appended to `naming_commits`;
   - newly appearing candidates are **reported, not processed** — the set stays fixed at 30.
2. **Build the exclusion union.** `exclusions_at_execution` = snapshot exclusions ∪ issue numbers referenced in open PR titles, bodies and branch names ∪ issue numbers referenced in the **diffs** of `origin/codex/*` branches updated in the last 7 days and not merged to main. Diffs are included because the numberless codex closeout branch shows branch names alone miss scope. A candidate that joins the union becomes **DRIFTED**.
3. **Re-check before every mutation.** Immediately before each close or comment, re-read that issue's `state` and re-test it against the union. If either changed, skip it, mark it DRIFTED, and continue. Stop the whole run on any `gh` error; never retry a mutation blindly.
4. **Re-check if main moves.** If origin/main advances between verdicting and approval, re-check every FIXED and PARTIAL condition against the new SHA before asking for approval.

### Operator approval gate

After all verdicts are written, render `item1-landed-fix-verdicts.md` and present the batch list in
chat. It lists every issue with its verdict, planned action, and the exact comment text. Record
`batch_list_sha256`.

No close or comment happens until the operator approves that list. The executed list must equal
the approved list. Any change after approval, including a DRIFTED skip, is reported, and any
addition requires re-approval.

### Publication (cross-host)

After execution, post `item1-landed-fix-verdicts.md` as a comment on the pull request carrying these
two plans. Include the sha256 of the JSON artifact, so a consumer on another host can verify its
copy. No new issue is opened for this (convergence rule 3).

## Documentation impact

None. The change is bookkeeping and has no documentation footprint: execution edits no file under
`docs/`, no `README.md`, `CHANGELOG.md`, `AGENTS.md`, `CLAUDE.md` or `llms*.txt`, and no public
surface. `docs-audit` has nothing to evaluate. The only committed file is this plan.

## Dependencies & order

- **Before execution:**
  1. this plan passes the board, within the round cap below;
  2. the pinned snapshot still exists and hashes to the value above;
  3. the operator approves the batch list.
- **Execution order:**
  1. re-snapshot and build the exclusion union;
  2. verdict all 25 in-scope candidates and record the 5 out-of-scope ones;
  3. write the JSON artifact and its rendering;
  4. operator approval;
  5. per-issue re-check, then close or comment;
  6. measure;
  7. publish to the PR.
- **Downstream contract (item 2):** item 2 starts only after the artifact is published. It consumes every `handed_to_item2` entry, and it must not re-disposition an issue this plan closed.
  - **Fallback:** if this plan is descoped or never publishes an artifact, item 2 treats all 15 in-scope B/D candidates as unverified and dispositions them itself.
- **Deconfliction:**
  - **Files:** no runtime file is touched, so there is no roadmap-ownership overlap. The plan file sits under `plans/`, which is GOVLEAN's directory token; that is an advisory annotation from a `completed` phase.
  - **Manifest:** `plans/manifest.json` is not written. Codex's `origin/codex/merged-repairs-closeout-20260917` is rewriting it (+229 lines), and every previous board endorsed skipping the row.
  - **GitHub:** GitHub collisions are handled by the exclusion union and per-issue re-checks.
- **Round cap (convergence rule 2):** at most **3** board rounds on this plan. If it is still unresolved after round 3, descope to verdicts only: write and publish the artifact and close nothing.

## Verification

Run on claw after execution, from any checkout with `gh` authenticated.

```bash
T=/mnt/workspace/board-tools/backlog-triage
# 1. the pinned input is intact
echo "230a8a9c66cde38c375020af5921bf1233292b4b31357af15de2b6fa414e8ef3  $T/triage-snapshot.json" | sha256sum -c

# 2. artifact structure: exactly the 30 candidates, once each, valid verdicts, safe actions
python3 - <<'PY'
import json,sys
T="/mnt/workspace/board-tools/backlog-triage"
s=json.load(open(f"{T}/triage-snapshot.json")); a=json.load(open(f"{T}/item1-landed-fix-verdicts.json"))
cand=sorted(int(n) for n in s["landed_commit_candidates"]); got=sorted(v["issue"] for v in a["verdicts"])
assert a["schema"]=="landed_fix_verdicts.v1", "schema"
assert got==cand, f"set mismatch: {set(cand)^set(got)}"
A=set(s["buckets"]["A1"]+s["buckets"]["A2"]+s["buckets"]["A3"]); X=set(a["exclusions_at_execution"])
ok={"FIXED","PARTIAL","MENTION-ONLY","REVERTED","OUT-OF-SCOPE","DRIFTED"}
for v in a["verdicts"]:
    n=v["issue"]; assert v["verdict"] in ok, n
    if v["action"]=="closed":
        assert v["verdict"]=="FIXED" and n not in A and n not in X, f"unsafe close #{n}"
        assert v["acceptance_conditions"] and all(c["holds_on_main"] is True for c in v["acceptance_conditions"]), f"#{n} closed without all conditions"
        assert v["effect_commits"], f"#{n} closed without an effect commit"
        assert not v.get("cited_by_open_phase"), f"#{n} closed while a committed phase plan cites it"
    if n in A or n in X: assert v["action"]=="recorded_only", f"#{n} out of scope but acted on"
    if v["verdict"]!="FIXED": assert v["action"]!="closed", f"#{n} non-FIXED closed"
    if v["bucket"] in ("B","D") and v["verdict"] in ("PARTIAL","MENTION-ONLY","REVERTED"): assert v["action"]=="handed_to_item2", n
print("artifact OK")
PY

# 3. effect commits are on main
python3 -c "
import json;a=json.load(open('$T/item1-landed-fix-verdicts.json'))
print('\n'.join(sorted({c for v in a['verdicts'] if v['action']=='closed' for c in v['effect_commits']})))" \
 | while read c; do git merge-base --is-ancestor "$c" origin/main || echo "NOT ON MAIN: $c"; done

# 4. GitHub state matches the artifact
python3 -c "
import json;a=json.load(open('$T/item1-landed-fix-verdicts.json'))
for v in a['verdicts']: print(v['issue'], v['action'])" | while read n act; do
  st=$(gh issue view "$n" -R Consiliency/agent-harness --json state,stateReason --jq '.state+"/"+(.stateReason//"")')
  case "$act" in closed) [ "$st" = "CLOSED/COMPLETED" ] || echo "MISMATCH #$n $act $st";;
                 *)      [ "${st%%/*}" = "OPEN" ] || echo "NOTE #$n $act now $st (expect DRIFTED)";; esac
done

# 5. measurement (convergence rule 4)
gh issue list -R Consiliency/agent-harness --state open --limit 1000 --json number --jq length
```

Behaviours and edge cases to observe:
- `#825`, `#870`, `#525`, `#789` and `#241` are never closed or commented by this run, even though four of them have landed fixes. Codex's own closeout may close #825 and #870; that shows up as DRIFTED or out-of-scope, not as a close by this run.
- A PARTIAL issue in bucket B or D receives **no** comment from this run, because item 2 owns its disposition.
- #454 and #733 are never closed by this run, whatever their verdict, because committed phase plans cite them (the citation guard).
- If `open_count_after` is lower than `open_count_before` by more than this run's closes, the difference belongs to others and is reported, not claimed.

**Expected result, derived from the spot-checks.** 3 of 10 were FIXED-shaped. The 15 unchecked
in-scope candidates include several fix-plus-test pairs (#451, #490, #493, #481, #720). The
expectation is to close **6–14 of the 25** in-scope candidates, for an attributable open-count
delta of **−6 to −14**.

Convergence rule 4 requires at least one attributable close. If execution finds zero FIXED, report
that as the item's result, and do not relax the rule to reach a number.

## Acceptance criteria

- [ ] The artifact validator (Verification step 2) exits 0. `item1-landed-fix-verdicts.json` lists exactly the 30 snapshot candidates once each, and no out-of-scope (A1/A2/A3) or `exclusions_at_execution` issue has any action other than `recorded_only`.
- [ ] Every issue this run closed is `CLOSED/COMPLETED` on GitHub (Verification step 4), has verdict FIXED with all acceptance conditions `holds_on_main: true`, and cites at least one effect commit that `git merge-base --is-ancestor` confirms is on origin/main (Verification step 3).
- [ ] No close or comment timestamp precedes `approval.approved_at`. The approved batch list re-hashes to `approval.batch_list_sha256`. Every executed action appears in that approved list, and every approved action that did not execute is recorded as a DRIFTED skip. No action is executed without being approved.
- [ ] `item1-landed-fix-verdicts.md` is posted on the plans PR, and the sha256 in the comment equals `sha256sum item1-landed-fix-verdicts.json`. The attributable open-count delta equals the number of FIXED closes and is at least 1.

## Execution Policy

- execute: effort=medium, reason=per-issue semantic verification of acceptance conditions against current main; mutations are mechanical but gated
