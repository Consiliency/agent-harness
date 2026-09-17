# Detailed plan: verify and close the open issues that already have a landed fix

## Task

Item 1 of the backlog-convergence sequence. The open-issue count has risen every week for nine weeks
and has never fallen. Part of that count is bookkeeping: issues whose fix already landed on `main` and
were never closed.

This plan verifies each landed-fix candidate against **its own acceptance conditions** and closes only
the ones that are really fixed. It is item 1 of 2 planned together; item 2
(`plans/detailed-deferred-findings-register-20260917-0100.md`) runs after it and consumes its artifact.

**This plan is also the single home of the execution rules both items share** (`## Shared execution
rules`). Item 2 cites those rules by name and restates none of them. Round 1 of this PR's board found
that two independently written copies of the same rules had already drifted apart.

### Pinned input

`/mnt/workspace/board-tools/backlog-triage/triage-snapshot.json`:
- sha256 `230a8a9c66cde38c375020af5921bf1233292b4b31357af15de2b6fa414e8ef3`;
- taken 2026-09-17T00:55:58Z against origin/main `11283f80`, with 223 open issues.

Its `landed_commit_candidates` key holds **30 issues**. For each, at least one commit subject on `main`
names the issue with a `fix(`, `feat(`, `test(`, `docs(`, `chore(` or `plan(` prefix. The set is not
re-derived. A commit subject is only how an issue entered the set; it is never evidence of a fix.

### Scope

| Set | Issues | Treatment |
|---|---|---|
| Out of scope: A buckets (HARDEN critical path) | #241 (A2), #825 (A3) | `recorded_only`, never mutated |
| Out of scope: codex in-flight at the snapshot | #525, #789, #825, #870 | `recorded_only`, never mutated |
| In scope, bucket B | #428, #451, #454, #456, #463, #464, #470, #481, #488, #490, #493, #498, #688 | close if FIXED and unbound; otherwise hand to item 2 |
| In scope, bucket D | #733 | close if FIXED and unbound; otherwise hand to item 2 |
| In scope, bucket C | #442, #660, #678, #685, #720 | close if FIXED and unbound; otherwise stay open |
| In scope, bucket E | #358, #398, #601, #607, #630, #633 | close if FIXED and unbound; otherwise stay open |

That is 25 in scope and 5 out. #825 sits in both out-of-scope rows and stays with codex. Rule R1 can
move further issues out of scope at execution; it can never move one in.

## Research summary

**Ten candidates were spot-checked** to ground the rules. These are evidence for the rules, not final
verdicts; execution re-derives every verdict.

- **#488** — `fix(ci)` `97d223e7` changed the two `timeout-minutes` values the issue names; they hold on main. FIXED-shaped.
- **#470** — `test(CONFORM)` `e69a3132` rewrote the defective fixture. The defect was in a test, so a `test(` commit can be the fix. FIXED-shaped, pending the cross-mode collision check.
- **#464** — two `Revert` commits undo the naming commit, yet the effect (CI installs a pinned `build`) holds on main (`test.yml:265`, `build==1.6.1`) through `fdd50704`, an agent-harness#428 commit that does not name #464. A revert says nothing about the effect, and the effect commit need not name the issue. FIXED-shaped.
- **#733** — `d96f85a4` says it will "sweep every surface for the stall wording", but the wording is still at `panel_invoker.py:5441` and `:6060`. PARTIAL.
- **#688** — the `--candidate-roadmap` instrument landed; the Key-files narrowing the issue asks for was never applied. PARTIAL.
- **#358** — the body says only "see consolidation"; one of its three P0 defects is fixed. PARTIAL.
- **#442, #498, #601, #607** — every naming commit touches only plans or records. MENTION-ONLY.

**Round 1 of this PR's board added five findings that change the rules:**

1. **Issues are bound to phases in ways a plan grep misses.**
   - SCHED is `executing`, and its `plans/manifest.json` entry carries `deferred_findings_issue: Consiliency/agent-harness#660`. #660 is in scope, and no phase plan cites it.
   - #678, #685 and #720 are cited by no plan or manifest at all, but their own bodies name SCHED, RUNTIME and INTEG as the owning gate.
   - A mechanical test of rule R2's checks (i)–(iii) at `11283f80` returns hits for #454 and #733 (plans), #660 (manifest), and #358, #398 and #442 (spec text outside completed phases). It returns no hits for #488, #470 and #464. #678, #685 and #720 are caught only by check (iv).
2. **A heading list is the wrong way to read acceptance.** Only 9 of the 25 in-scope bodies use an *Acceptance*-style heading, so the old rule's fallback ("no longer reproduces") would have ruled #720 FIXED even though its own CHANGELOG says only items 1–3 landed. It would also have ruled #633 FIXED, although #633 asked for a *required* check and an *advisory* one landed.
3. **"Phase completed" does not prove a review happened.** CONFORM's manifest `status` is `completed`, but its lifecycle ends at a `committed` event dated 2026-08-06, while #464's effect commit is dated 2026-09-14.
4. **The old validator trusted the artifact.** A synthetic artifact that dropped #870 from its own exclusion list and closed it, or closed #454 with an empty citation list, printed `artifact OK`.
5. **Contract holes.** The item-1/item-2 handoff had contradictory fallbacks, the publication format differed between the plans, and approval did not cover every mutation.

## Changes

**No repository source, test, configuration or documentation file is changed by executing this plan.**
Execution produces off-repo artifacts and GitHub issue state. The only repository change is this plan
file.

### Shared execution rules (normative for items 1 and 2)

Execution implements R1–R3 once, as
`/mnt/workspace/board-tools/backlog-triage/shared_rules.py`. Both items and both validators import it.
It is an off-repo execution tool, not repository code. Before any verdict is written, it must pass the
positive and negative controls under "Helper self-test".

- **R1 — In-flight exclusion union.** `exclusion_union()` returns the union of:
  - `codex_inflight_exclusions` from the pinned snapshot;
  - issue numbers in open PR titles, bodies and head-branch names;
  - issue numbers in every `origin/codex/*` branch name;
  - issue numbers in `git diff origin/main...origin/codex/<b>` for **every** `codex/*` branch not merged to main (no age cutoff). Diffs are included because codex's numberless closeout branches carry scope only in their diff;
  - issues under an explicit operator hold recorded in an issue body or comment. Example: #843 is held pending #789 and #842.

  An issue in the union is never mutated.
- **R2 — Phase-binding guard.** `phase_bindings(n, ref, mechanical_only=False)` returns every place where
  a phase that is not `completed` binds issue `n` at git ref `ref`. With `mechanical_only=True` it runs
  only checks (i)–(iii), which are deterministic for a given ref; check (iv) is a recorded judgment and
  is validated through the entry's `binding_review` field instead. Numbers match as `Consiliency/agent-harness#N`,
  `agent-harness#N`, or a word-bounded `#N`. The checks:
  - **(i)** `specs/phase-plans-v10.md` hits outside the sections of completed phases. Execution Notes and other top-level sections count as binding.
  - **(ii)** Hits in any `plans/phase-plan-v10-<ALIAS>.md` whose phase is not `completed`.
  - **(iii)** Hits anywhere in the `plans/manifest.json` entry of a phase that is not `completed`, nested fields included (for example SCHED's `deferred_findings_issue`).
  - **(iv)** A **recorded judgment**, not a regex: the issue's title, body or comments name a non-completed phase as the owner, the gate, or the deferral target. Examples: "SCHED tests-only deferred board findings", "INTEG-owned binding", "DEFERRED under EC-REVIEWTRUTH-19". The executor quotes the binding sentence, or states "no binding" after reading. When unsure, it is binding.

  Any hit means the issue is bound and is never closed, whatever its verdict. Bindings are recorded as
  `phase_bindings` entries `{check, file_or_source, line_or_quote}`.
- **R3 — Acceptance extraction.** The acceptance conditions are **every ask the issue makes**, from the
  title, the full body (headed or not) and all comments. That includes requested remedies, "should",
  "must" and "required" statements, numbered fix lists, and proposals the issue asks to adopt.
  - A body that only defers elsewhere ("see consolidation") is followed to the linked text.
  - "The observed failure no longer reproduces on current main" is a valid condition only when the issue states a failure and asks for **no** specific remedy.
  - When an ask names a specific mechanism or strength ("a *required* check", "fail closed"), a weaker landed change does not satisfy it.
  - A condition that cannot be located or checked is `holds_on_main: false` with evidence `unverifiable`.
- **R4 — Procedural conditions.** A condition such as "receive Sol/Fable review before landing" holds
  only with recorded evidence:
  - the landing PR's recorded review for that condition; or
  - for a bucket B issue, a completion lifecycle event (a `transition: completed` entry, not merely `status: completed`) in the owning phase's `plans/manifest.json` record, with the effect commit an ancestor of that event's recorded landing.

  Otherwise the condition is `unverifiable`.
- **R5 — Freshness immediately before every mutation.** Before each close or comment:
  1. re-read the issue's `state`, `updatedAt`, and a sha256 of its title, body and comments. Any change since the verdict means **DRIFTED**, and the mutation is skipped;
  2. recompute `exclusion_union()`. If the issue is now in it, it is DRIFTED;
  3. re-run `phase_bindings(n, current origin/main)` checks (i)–(iii). Any new hit means DRIFTED;
  4. confirm every cited effect commit is an ancestor of current origin/main, and that every file:line evidence still holds there. Any failure means DRIFTED.

  Stop the whole run on any `gh` error, and never retry a mutation blindly.
- **R6 — Mutation receipts.** Every executed GitHub mutation appends one receipt:
  `{kind, issue_or_pr, command, started_at, finished_at, exit_code, url}`, where `kind` is one of
  `issue_close`, `issue_comment`, `pr_open`, `pr_comment`, or `pr_merge`. Measurement and validation
  count receipts, never a before/after open-issue count, because codex opens and closes issues
  concurrently.
- **R7 — Verbatim fencing.** Verbatim text copied into markdown, a PR comment, or the register goes in
  a code fence one backtick longer than the longest backtick run inside the text, with a minimum of four.

**Helper self-test** (`python3 shared_rules.py --self-test`, which must exit 0 before any verdict):
- at ref `11283f80`, checks (i)–(iii) of `phase_bindings` return at least one hit for each of #454, #733, #660, #358, #398 and #442, and zero hits for each of #488, #470 and #464;
- `exclusion_union()` is a superset of the snapshot's `codex_inflight_exclusions`;
- the R7 fence for a string containing a run of five backticks is at least six backticks long.

### Verdict artifact `/mnt/workspace/board-tools/backlog-triage/item1-landed-fix-verdicts.json` (create at execution)

- **Schema `landed_fix_verdicts.v1`.** Top-level fields:
  - `schema`;
  - `run_status` — `complete` (all approved mutations attempted), `verdicts_only` (the descope path; no mutations), or `aborted` (stopped on an error; its receipts are partial);
  - `snapshot_ref` `{path, sha256, snapshot_at, origin_main}`;
  - `executed_at`;
  - `origin_main_at_execution`;
  - `exclusions_at_execution` (sorted ints, the output of R1);
  - `approval` `{approved_at, batch_list_sha256}`, or `null` for `verdicts_only`;
  - `verdicts` — exactly one entry per snapshot candidate, all 30;
  - `receipts` — the R6 list.
- **Verdict entry.** Fields:
  - `issue`, `bucket`, `verdict`;
  - `naming_commits`, `effect_commits`, `reverts`;
  - `acceptance_conditions` — a list of `{text, source, holds_on_main, evidence}`, per R3 and R4;
  - `phase_bindings` — the R2 list;
  - `binding_review` — the quoted R2 check (iv) judgment;
  - `action` — `closed`, `commented`, `handed_to_item2`, `declined` (the operator removed it from the batch), or `recorded_only`.
- **Rendered companion `item1-landed-fix-verdicts.md`.** The human table, which is also the approval
  text.

### Verdict rule (normative)

| Verdict | Evidence required | Action, if the issue is unbound under R2 and not in R1 |
|---|---|---|
| **FIXED** | Every R3 condition `holds_on_main: true` on `origin_main_at_execution`, each with an effect commit on main or a direct check. The effect commit need not name the issue. | Close as `completed`. |
| **PARTIAL** | At least one condition holds via a landed change, and at least one does not or is `unverifiable`. | **C/E:** comment listing held and unheld conditions; leave open. **B/D:** `handed_to_item2`, no comment. |
| **MENTION-ONLY** | No condition holds via a landed change; the naming commits only plan, authorize, document, record or re-point the issue. | **C/E:** `recorded_only`. **B/D:** `handed_to_item2`. |
| **REVERTED** | A naming or effect commit was reverted, and no condition holds on main afterwards. If an effect still holds through another commit, use FIXED or PARTIAL instead. | Same routing as MENTION-ONLY. |
| **OUT-OF-SCOPE** | An A bucket, or in R1's union at execution. | `recorded_only`. |
| **DRIFTED** | R5 detected a change. | `recorded_only`, with the drift reason. |

**Binding overrides every verdict.** A FIXED issue with any R2 binding is not closed. It is
`handed_to_item2` for B/D issues, where item 2 dispositions it, or `recorded_only` for C/E issues. By
the self-test, #454, #733 and #660 are held; by check (iv), #678, #685 and #720 are expected to be held
too. Commits that touch only `plans/`, `.consiliency/` or `docs/` records count as effect commits only
for a condition that is itself about a document.

### Close mechanics

- **FIXED and unbound.** `gh issue close <N> -R Consiliency/agent-harness --reason completed --comment "<body>"`. The body lists each condition with the effect commit and evidence that satisfy it. When the effect commit differs from the naming commit, it says so explicitly. It ends with "Reopen if a condition was missed."
- **PARTIAL, C or E.** `gh issue comment <N>` listing held conditions (with effect commits) and unheld conditions (with reasons). Never close.
- **Hygiene.** Use qualified `Consiliency/agent-harness#N` references, and never a closing keyword against another issue.

### Operator approval gate

After all verdicts are written and R5 has passed once, present `item1-landed-fix-verdicts.md` in chat.
It enumerates **every GitHub mutation this item will make**:
- each issue close, with its full comment text;
- each issue comment, with its full text;
- the single publication comment on the plans PR.

Record `batch_list_sha256` over the exact list. No mutation happens before approval. Every executed
mutation must appear in the approved list. An approved mutation that does not execute is recorded as a
DRIFTED skip or `declined`. Anything not on the list requires re-approval.

### Publication (cross-host)

After execution, post one comment on the plans PR containing:
- the rendered table;
- the **JSON artifact's exact bytes**, serialized with `json.dumps(obj, indent=1, sort_keys=True)` followed by a trailing newline, and fenced per R7;
- the sha256 of those bytes.

If the fenced JSON would exceed 60,000 characters, split it across sequential comments marked
`part i/N`, each carrying the same full-artifact sha256. A consumer concatenates the parts in order and
verifies the digest. The local file is written from the same bytes.

## Documentation impact

None. Execution edits no file under `docs/`, no `README.md`, `CHANGELOG.md`, `AGENTS.md`, `CLAUDE.md`
or `llms*.txt`, and no public surface. The only committed file is this plan.

## Dependencies & order

- **Before execution:**
  1. this plan passes the board within the round cap;
  2. the pinned snapshot hashes to the value above;
  3. the helper self-test exits 0.
- **Execution order:**
  1. run R1 and write the verdicts for all 30 candidates, with R2 and R3/R4 evidence;
  2. run R5 once over the batch;
  3. write and render the artifact;
  4. operator approval;
  5. for each mutation: R5, then mutate, then record a receipt;
  6. set `run_status`;
  7. publish;
  8. validate.
- **Contract with item 2:**
  - Item 2 starts only when this artifact exists, carries `run_status` of `complete` or `verdicts_only`, and its local bytes hash to the published digest.
  - Every B/D issue **without a successful close receipt** enters item 2's scope, including FIXED issues held by R2, `declined` issues, DRIFTED issues, and every issue in a `verdicts_only` run.
  - An `aborted` or missing artifact means item 2 does not start, and the operator decides the next step.
- **Descope** (round cap reached, or the operator declines all closes): run steps 1–3, then set
  `run_status: verdicts_only` and publish, with no issue mutations. Item 2 then takes all 15 B/D overlap
  issues.
- **Deconfliction:**
  - no runtime file is touched;
  - `plans/manifest.json` is not written;
  - GitHub collisions are prevented by R1, R2 and R5 at the moment of each mutation.
- **Round cap (convergence rule 2):** at most 3 board rounds on this plan, then the descope above.

## Verification

Run on claw after execution, from a checkout with `gh` authenticated.

```bash
T=/mnt/workspace/board-tools/backlog-triage
echo "230a8a9c66cde38c375020af5921bf1233292b4b31357af15de2b6fa414e8ef3  $T/triage-snapshot.json" | sha256sum -c
python3 $T/shared_rules.py --self-test

# Independent validation: recompute the safety properties; never trust the artifact's own exclusion or binding fields
python3 - <<'PY'
import json, sys
T = "/mnt/workspace/board-tools/backlog-triage"
sys.path.insert(0, T)
import shared_rules as sr
s = json.load(open(f"{T}/triage-snapshot.json"))
a = json.load(open(f"{T}/item1-landed-fix-verdicts.json"))
assert a["schema"] == "landed_fix_verdicts.v1", "schema"
assert a["run_status"] in ("complete", "verdicts_only", "aborted"), "run_status"
cand = sorted(int(n) for n in s["landed_commit_candidates"])
assert sorted(v["issue"] for v in a["verdicts"]) == cand, "verdicts must be exactly the 30 candidates"
A = set(s["buckets"]["A1"] + s["buckets"]["A2"] + s["buckets"]["A3"])
snap_x = set(s["codex_inflight_exclusions"])
assert snap_x <= set(a["exclusions_at_execution"]), "artifact dropped a snapshot exclusion"
closes = {r["issue_or_pr"] for r in a["receipts"] if r["kind"] == "issue_close" and r["exit_code"] == 0}
legal = {"B": {"closed", "handed_to_item2", "declined", "recorded_only"},
         "D": {"closed", "handed_to_item2", "declined", "recorded_only"},
         "C": {"closed", "commented", "declined", "recorded_only"},
         "E": {"closed", "commented", "declined", "recorded_only"}}
live_x = sr.exclusion_union()
for v in a["verdicts"]:
    n, b, act = v["issue"], v["bucket"], v["action"]
    if n in A or n in snap_x or n in set(a["exclusions_at_execution"]):
        assert act == "recorded_only" and n not in closes, f"#{n} out of scope but acted on"
        continue
    assert act in legal[b], f"#{n} illegal action {act} for bucket {b}"
    if act == "closed":
        assert v["verdict"] == "FIXED", f"#{n} closed but not FIXED"
        assert n in closes, f"#{n} marked closed with no successful receipt"
        assert not sr.phase_bindings(n, a["origin_main_at_execution"], mechanical_only=True), f"#{n} closed while a non-completed phase binds it"
        assert v["binding_review"].strip(), f"#{n} closed without a recorded check-(iv) judgment"
        conds = v["acceptance_conditions"]
        assert conds and all(c["holds_on_main"] is True for c in conds), f"#{n} closed without every condition holding"
        assert v["effect_commits"], f"#{n} closed without an effect commit"
        if n in live_x:
            print(f"WARNING #{n}: now in the live exclusion union (post-close drift; report it)")
    else:
        assert n not in closes, f"#{n} has a close receipt but action {act}"
    if act == "commented":
        assert b in ("C", "E") and v["verdict"] == "PARTIAL", f"#{n} commented outside C/E PARTIAL"
    if act == "handed_to_item2":
        assert b in ("B", "D"), f"#{n} handed to item 2 from bucket {b}"
if a["run_status"] == "verdicts_only":
    assert not a["receipts"], "a verdicts_only run recorded mutations"
print("artifact OK; closes:", len(closes))
PY

# Every successful receipt matches GitHub
python3 - <<'PY'
import json, subprocess
T = "/mnt/workspace/board-tools/backlog-triage"
a = json.load(open(f"{T}/item1-landed-fix-verdicts.json"))
for r in a["receipts"]:
    if r["exit_code"] == 0 and r["kind"] == "issue_close":
        v = json.loads(subprocess.run(["gh", "issue", "view", str(r["issue_or_pr"]), "-R", "Consiliency/agent-harness",
                                       "--json", "state,stateReason"], capture_output=True, text=True, check=True).stdout)
        assert (v["state"], v["stateReason"]) == ("CLOSED", "COMPLETED"), r
print("receipts match GitHub")
PY
```

Behaviours to observe:
- #825, #870, #525, #789 and #241 are never mutated.
- #454, #733 and #660 are never closed, and neither are any issues held by R2 check (iv).
- No B/D issue receives a comment from this run.

**Expected result.**
- **Held back:** 6 of the 25 in-scope issues are expected to be held by R2 (#454, #733, #660, #678, #685, #720), leaving 19.
- **Spot-checked:** of the 9 spot-checked unheld issues, 3 are FIXED-shaped (#488, #470, #464).
- **Unchecked:** 10 are not yet checked.
- **Estimate:** **3–10 closes**. The lower bound is the three spot-checked FIXED-shaped issues surviving R3/R4. The upper bound assumes roughly the same FIXED rate on the 10 unchecked (3 of 9 gives about 3 of 10), plus up to 4 more.
- **Reporting:** below 3 is reported with reasons. Zero FIXED is a valid result, and the rules are not relaxed to reach a number.

## Acceptance criteria

- [ ] `shared_rules.py --self-test` exits 0, and the independent validator prints `artifact OK`. It recomputes the phase bindings and exclusions instead of trusting the artifact, and it checks the exactly-30 coverage and per-bucket action legality.
- [ ] Every issue with a successful `issue_close` receipt is `CLOSED/COMPLETED` on GitHub, had verdict FIXED with every R3/R4 condition holding, and had no mechanical R2 binding at `origin_main_at_execution`.
- [ ] No receipt's `started_at` precedes `approval.approved_at`; the approved list re-hashes to `approval.batch_list_sha256`; every receipt is in that list; every approved-but-unexecuted mutation is recorded as DRIFTED or `declined`.
- [ ] The published PR comment carries the artifact's exact JSON bytes and their sha256, and `sha256sum item1-landed-fix-verdicts.json` matches it. The attributable result is the count of successful close receipts, reported against the 3–10 estimate.

## Execution Policy

- execute: effort=medium, reason=per-issue semantic verification of every stated ask against current main, with mechanical guards and gated mutations
