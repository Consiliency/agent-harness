# Detailed plan: verify and close the open issues that already have a landed fix

## Task

Item 1 of the backlog-convergence sequence. The open-issue count has risen every week for nine weeks
and has never fallen. Part of that count is bookkeeping: issues whose fix already landed on `main` and
were never closed.

This plan verifies each landed-fix candidate against **its own acceptance conditions** and closes only
the ones that are really fixed. It is item 1 of 2 planned together; item 2
(`plans/detailed-deferred-findings-register-20260917-0100.md`) runs after it and consumes its artifact.

**This plan is also the single home of the execution rules and close checks both items share**
(`## Shared execution rules`). Item 2 cites them by name and restates none of them.

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

**Round 1 of this PR's board** showed that issues bind to phases through manifest fields and issue
bodies (#660; #678, #685, #720), that acceptance must be read from every ask rather than a heading list
(#720, #633), that "phase completed" does not prove a review happened (CONFORM), and that the
validator trusted the artifact under test.

**Round 3 found** that the batch named a PR number before the PR existed, prescribed re-approval that
only one batch could validate, dated a PR reference by the PR's creation, let an out-of-scope close and a
contradictory precedence trace through item 2, and let R5 skip the required #361 comment. Each is fixed
by narrowing (one batch per run, PR mutations by branch, bindings gate closes only) or by checking a
value already recorded.

**Round 2 added:**
1. **Two more binding channels.** #341 and #360 are bound by *content*: #341 is EC-RESIDUAL-7 and IF-0-RESIDUAL-4, #360 is EC-RESIDUAL-5, and neither is cited by number in `specs/` or `plans/`. #428 is bound by two **executing detailed plans** (`plans/detailed-ci-nonroot-853-20260915.md`, `plans/detailed-proofgate-cleanup-858-20260915.md`), which the phase-only checks never read. Scanning every non-completed manifest entry's file at `11283f80` also binds #688, #748, #817, #842 and #843, and still binds none of #488, #470, #464.
2. **The remaining validator defects were one class:** a check reading, from the artifact under test, the property it claims to verify (the live exclusion union, the ref for the binding re-check, approval), plus a publication receipt that cannot exist inside the bytes it publishes. The fix is the threat model under `## Shared execution rules`, not more self-checking.

## Changes

**No repository source, test, configuration or documentation file is changed by executing this plan.**
Execution produces off-repo artifacts and GitHub issue state. The only repository change is this plan
file.

### Shared execution rules (normative for items 1 and 2)

**Validation threat model.** Validation guards against executor error and drift, not forgery by the
executor: the operator approves every mutation, and GitHub is the ground truth. So every safety
property is checked against an **authority outside the artifact under test** — GitHub state and
timestamps, git ancestry, a live recomputation of R1 and R2, and the approved batch as published on
GitHub — and never against a field of the artifact it validates. Semantic judgments (a verdict, a
floor class, a "no binding" reading) are recorded for the operator to review at approval; validation
checks their shape and consistency, not their truth.

Execution implements the rules once, as `/mnt/workspace/board-tools/backlog-triage/shared_rules.py`.
Both items and both validators import it. It is an off-repo execution tool, not repository code.
Before any verdict is written it must pass the "Helper self-test".

**Timestamps** everywhere are UTC `YYYY-MM-DDTHH:MM:SSZ`, the format GitHub returns, so string order is
time order. Issue numbers are JSON integers.

- **R1 — In-flight exclusion union.** `exclusion_union(with_sources=False)` returns the union below; with
  `with_sources=True` it returns `{n: [{source, at}]}`, where `at` is when that source first named `n`:
  - `codex_inflight_exclusions` from the pinned snapshot (`at` = the snapshot time);
  - issue numbers in open PR titles, bodies and head-branch names (`at` = `pr_reference_time(pr, n)`: the earliest title, body or rename revision GitHub records naming `n`, or the PR's `createdAt` when its head branch names it — so a body edited after a close to name the issue dates from the edit);
  - issue numbers in every `origin/codex/*` branch name, and in `git diff origin/main...origin/codex/<b>` for **every** `codex/*` branch not merged to main, with no age cutoff (`at` = the author date of the earliest unmerged commit on that branch that names `n`; author dates survive rebases);
  - operator holds recorded in an issue body or comment, kept in the helper's `OPERATOR_HOLDS` table with the quoted text (`at` = that body's or comment's `createdAt`). Seeded with #843 ("Under the operator hold, do not publish this follow-up before the post-push PR-confirmation fix lands"); the executor adds any hold found while reading bodies under R3.

  An issue in the union is never mutated.
- **R2 — Phase-binding guard.** `phase_bindings(n, ref, mechanical_only=False)` returns every place where
  unfinished work binds issue `n` at git ref `ref`. Numbers match as `Consiliency/agent-harness#N`,
  `agent-harness#N`, or a word-bounded `#N`. "Unfinished" means a `plans/manifest.json` entry of **any**
  `type` whose `status` is not `completed` or `orphaned`; entries are keyed by `file`, never by alias.
  - **(i)** `specs/phase-plans-v10.md` hits outside the sections of phases whose manifest entry is `completed`. Execution Notes and other top-level sections count as binding.
  - **(ii)** Hits in the `file` of any unfinished manifest entry — phase plans and detailed plans alike — except `specs/phase-plans-v10.md` itself (its manifest entry is `imported`), which only (i) reads, so (i)'s completed-phase carve-out holds.
  - **(iii)** Hits anywhere in an unfinished manifest entry's JSON, nested fields included (for example SCHED's `deferred_findings_issue`).
  - **(iv)** A **recorded judgment**: the issue's title, body or comments name an unfinished phase as the owner, the gate, or the deferral target. Examples: "SCHED tests-only deferred board findings", "INTEG-owned binding", "DEFERRED under EC-REVIEWTRUTH-19".
  - **(v)** A **recorded judgment**: an unfinished phase's exit criterion, interface-freeze gate or lane has this finding as its subject, whether or not it cites the number. The helper's `KNOWN_CONTENT_BINDINGS` table records each such binding found (seeded: #341 → EC-RESIDUAL-7 / IF-0-RESIDUAL-4; #360 → EC-RESIDUAL-5), and `mechanical_only=True` returns them together with (i)–(iii).

  For (iv) and (v) the executor records `binding_review` as `{"iv": ..., "v": ...}`, each either exactly
  `"no binding"` after reading, or the quoted binding sentence. When unsure, it is binding. Any hit
  means the issue is bound and is never closed, whatever its verdict.
- **R3 — Acceptance extraction.** The acceptance conditions are **every ask the issue makes**, from the
  title, the full body (headed or not) and all comments. That includes requested remedies, "should",
  "must" and "required" statements, numbered fix lists, and proposals the issue asks to adopt.
  - A body that only defers elsewhere ("see consolidation") is followed to the linked text.
  - "The observed failure no longer reproduces on current main" is a valid condition only when the issue states a failure and asks for **no** specific remedy.
  - When an ask names a specific mechanism or strength ("a *required* check", "fail closed"), a weaker landed change does not satisfy it.
  - Each condition's `evidence` is `{"kind": "effect_commit", "sha"}` or `{"kind": "direct_check", "command", "result"}`. A condition that cannot be located or checked is `holds_on_main: false` with `unverifiable` in its text.
- **R4 — Procedural conditions.** A condition such as "receive Sol/Fable review before landing" holds
  only with recorded evidence:
  - the landing PR's recorded review for that condition; or
  - for a bucket B issue, a `transition: completed` lifecycle event (not merely `status: completed`) in the owning phase's manifest entry, with the effect commit an ancestor of the landing SHA that event's `metadata` records (`merge_commit`, `merge_head`, `exact_main_head` or `exact_main_oid`).

  Otherwise the condition does not hold.
- **R5 — Freshness immediately before every mutation.** Each verdict entry records
  `verdict_baseline {updatedAt, content_sha256}` (sha256 of title, body and comments when the verdict was
  written). Before each close or comment:
  1. re-read the issue. Any change from the baseline means the mutation is skipped (`action: skipped`, `skip_reason: "drifted: <what changed>"`);
  2. recompute `exclusion_union()`. Membership means skipped;
  3. before a **close** only: re-run `phase_bindings(n, freshly fetched origin/main, mechanical_only=True)`. Any hit means skipped. A binding never blocks a comment: R2 protects against closing a bound issue, not commenting on it (item 2's #361 redirect comments on a bound issue);
  4. confirm every cited effect commit is an ancestor of that origin/main and every direct check still gives its recorded result. Any failure means skipped.

  Stop the whole run on any `gh` error, and never retry a mutation blindly.
- **R6 — Receipts.** Every executed **issue or PR mutation** (`issue_close`, `issue_comment`, `pr_open`,
  `pr_merge`) appends `{kind, issue_or_pr, command, started_at, finished_at, exit_code, url}` to the
  artifact's `receipts`. **Publication comments** are receipted separately, in
  `item{1,2}-publication-receipts.json` as `{publishes: "batch"|"artifact", part, path, command, started_at,
  exit_code, url}`, because a receipt cannot live inside the bytes it publishes. Measurement counts
  receipts, never a before/after open-issue count, because codex opens and closes issues concurrently.
- **R7 — Verbatim fencing.** Verbatim text copied into markdown, a PR comment, or the register goes in
  a code fence one backtick longer than the longest backtick run inside the text, with a minimum of four.

**Close checks (normative).** These functions are copied verbatim into `shared_rules.py`, next to
`exclusion_union`, `phase_bindings`, `OPERATOR_HOLDS` and `KNOWN_CONTENT_BINDINGS`. Both validators call
them, so the two items cannot check a close differently. `close_ref` assumes a first-parent commit's committer
date is when it reached `main`. That holds for PR merges; a rare direct push (the last was `fb0989fa`,
2026-09-04) is dated before its push. R5's live re-check at mutation time is the primary binding guard,
and validation is the backstop. `posted()` compares executor and GitHub timestamps, so the executing
host must be NTP-synchronized (claw is).

```python
import hashlib, json, re, subprocess

REPO = "Consiliency/agent-harness"

def _git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)

def gh_json(*a):
    return json.loads(subprocess.run(["gh", *a], capture_output=True, text=True, check=True).stdout)

def gh_issue(n):
    return gh_json("issue", "view", str(n), "-R", REPO, "--json", "state,stateReason,closedAt,comments")

def body_sha256(text):
    """Approval hash of a comment body: CRLF->LF, outer whitespace stripped, register permalink SHA abstracted."""
    t = re.sub(r"blob/[0-9a-f]{40}/docs/registers/", "blob/{MERGED_MAIN}/docs/registers/", text.replace("\r\n", "\n").strip())
    return hashlib.sha256(t.encode()).hexdigest()

def close_ref(closed_at):
    """The origin/main commit current when GitHub recorded the close (first-parent, committer date)."""
    r = _git("rev-list", "-1", "--first-parent", f"--before={closed_at}", "origin/main")
    assert r.returncode == 0 and r.stdout.strip(), f"no origin/main commit before {closed_at}"
    return r.stdout.strip()

def is_ancestor(sha, ref):
    return _git("merge-base", "--is-ancestor", sha, ref).returncode == 0

def posted(issue, mutation, receipt):
    """True if a comment created at or after the receipt's start carries the approved body."""
    return any(c["createdAt"] >= receipt["started_at"] and body_sha256(c["body"]) == mutation["body_sha256"]
               for c in issue["comments"])

def pr_reference_time(pr, n):
    """Earliest time GitHub shows PR `pr` naming issue `n`: in its head branch (from creation), its title
    (original title at creation, then each rename), or its body (each userContentEdits revision; the oldest
    revision is the original body). None if no revision names it. R1 uses this as a PR source's `at`."""
    q = ("query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n){"
         "createdAt headRefName title body userContentEdits(first:100){totalCount nodes{editedAt diff}} "
         "timelineItems(itemTypes:[RENAMED_TITLE_EVENT],first:100){nodes{... on RenamedTitleEvent{createdAt previousTitle currentTitle}}}}}}")
    owner, name = REPO.split("/")
    p = gh_json("api", "graphql", "-f", f"query={q}", "-f", f"o={owner}", "-f", f"r={name}", "-F", f"n={pr}")["data"]["repository"]["pullRequest"]
    ref = re.compile(r"(?:Consiliency/agent-harness#|agent-harness#|(?<![\w])#)%d\b" % n)
    if re.search(r"(?<!\d)%d(?!\d)" % n, p["headRefName"]):
        return p["createdAt"]
    renames = p["timelineItems"]["nodes"]
    texts = [(p["createdAt"], renames[0]["previousTitle"] if renames else p["title"])]
    texts += [(e["createdAt"], e["currentTitle"]) for e in renames]
    edits = p["userContentEdits"]
    if edits["totalCount"] > len(edits["nodes"]):
        return p["createdAt"]  # history truncated: the earliest possible time, so validation fails closed
    texts += [(e["editedAt"], e["diff"] or "") for e in edits["nodes"]] + [(p["createdAt"], p["body"] or "")] * (not edits["nodes"])
    hits = [t for t, text in texts if ref.search(text)]
    if hits:
        return min(hits)
    return p["createdAt"] if ref.search((p["title"] or "") + "\n" + (p["body"] or "")) else None

def close_failures(n, entry, issue, mutation, receipt, fixed):
    """Every reason one executed close is unsafe; [] means safe. Reads GitHub and git, never the artifact's
    exclusion, ref or approval fields. `fixed` selects COMPLETED (item-1 FIXED, item-2 ALREADY-FIXED)."""
    f = []
    want = "COMPLETED" if fixed else "NOT_PLANNED"
    if (issue["state"], issue["stateReason"]) != ("CLOSED", want):
        return [f"GitHub state {issue['state']}/{issue['stateReason']}, want CLOSED/{want}"]
    if mutation is None or mutation["kind"] != "issue_close":
        f.append("close is not in the published approved batch")
    elif not posted(issue, mutation, receipt):
        f.append("no posted comment matches the approved body")
    ref = close_ref(issue["closedAt"])
    for src in exclusion_union(with_sources=True).get(n, []):
        if src["at"] < issue["closedAt"]:
            f.append(f"in the R1 union before the close, via {src['source']}")
    for b in phase_bindings(n, ref, mechanical_only=True):
        f.append(f"bound at {ref[:8]}: {b}")
    review = entry.get("binding_review") or {}
    if review.get("iv") != "no binding" or review.get("v") != "no binding":
        f.append("R2 check (iv)/(v) judgment is not exactly 'no binding'")
    if fixed:
        conds = entry.get("acceptance_conditions") or []
        if not conds:
            f.append("no acceptance conditions")
        for c in conds:
            ev = c.get("evidence") or {}
            if c.get("holds_on_main") is not True:
                f.append(f"condition does not hold: {c.get('text')!r}")
            elif ev.get("kind") == "effect_commit":
                if not is_ancestor(ev.get("sha", ""), ref):
                    f.append(f"effect commit {ev.get('sha')} is not on main at the close")
            elif not (ev.get("kind") == "direct_check" and ev.get("command") and ev.get("result")):
                f.append(f"condition has neither an effect commit nor a direct check: {c.get('text')!r}")
    return f

def published(receipts_path, what):
    """(object, created_at) for the artifact published as `what`; asserts GitHub carries the local file's exact bytes."""
    rs = [r for r in json.load(open(receipts_path)) if r["publishes"] == what and r["exit_code"] == 0]
    assert rs, f"{what} was never published"
    parts, last = [], ""
    for r in sorted(rs, key=lambda r: r["part"]):
        cid = re.search(r"issuecomment-(\d+)", r["url"]).group(1)
        c = gh_json("api", f"repos/{REPO}/issues/comments/{cid}")
        m = re.search(r"^(`{4,})json\n(.*?)^\1$", c["body"], re.S | re.M)
        assert m, f"{r['url']} carries no fenced JSON"
        parts.append(m.group(2)); last = max(last, c["created_at"])
    data = "".join(parts).encode()
    local = open(rs[0]["path"], "rb").read()
    assert data == local, f"published {what} bytes differ from {rs[0]['path']}"
    return json.loads(data), last

ROW_FIELDS = ("source", "origin", "original ruling", "bound criteria", "current-main check", "safety floor", "disposition", "promotion")

def parse_register(text):
    """{row_id: {field: value, 'finding': text}}. Row markers and field lines count only outside code fences."""
    rows, cur, fence, in_finding = {}, None, None, False
    for line in text.splitlines():
        m = re.match(r"^(`{3,})", line)
        if fence:
            if m and line.strip() == fence:
                fence = None
            if cur and in_finding:
                rows[cur]["finding"] += line + "\n"
            continue
        if m:
            fence = m.group(1)
            if cur and in_finding:
                rows[cur]["finding"] += line + "\n"
            continue
        mk = re.fullmatch(r"<!-- row:(R-\d{3}) -->", line)
        if mk:
            cur, in_finding = mk.group(1), False
            assert cur not in rows, f"duplicate row {cur}"
            rows[cur] = {"finding": ""}
            continue
        if cur is None:
            continue
        fm = re.match(r"^- \*\*([a-z -]+):\*\*\s?(.*)$", line)
        if fm and fm.group(1) == "finding":
            in_finding = True
        elif fm and not in_finding and fm.group(1) in ROW_FIELDS:
            rows[cur][fm.group(1)] = fm.group(2)
    for rid, r in rows.items():
        missing = [f for f in ROW_FIELDS if f not in r]
        assert not missing and r["finding"].strip(), f"{rid} missing {missing or ['finding']}"
    return rows

def register_at(sha):
    r = _git("show", f"{sha}:docs/registers/deferred-findings.md")
    return parse_register(r.stdout) if r.returncode == 0 else None

def grep_absent(pattern, paths, ref):
    """True if `git grep -E pattern` finds nothing at ref (exit 1 = no match; anything else is an error)."""
    r = _git("grep", "-nE", pattern, ref, "--", *paths)
    assert r.returncode in (0, 1), r.stderr
    return r.returncode == 1
```

**Helper self-test** (`python3 shared_rules.py --self-test`, which must exit 0 before any verdict):
- at ref `11283f80`, `phase_bindings(n, ref, mechanical_only=True)` returns at least one hit for each of #454, #733, #660, #358, #398, #442, #428, #341 and #360, and zero hits for each of #488, #470, #464 and #392 (cited only inside completed LEGIBLE's spec section);
- `exclusion_union()` is a superset of the snapshot's `codex_inflight_exclusions` and contains #843;
- the R7 fence for a string containing a run of five backticks is at least six backticks long;
- `pr_reference_time` on fixture PRs returns the edit time for a body edited to name the issue, `createdAt` for a head branch naming it, the rename time for a renamed title, `None` when only a longer number (`#4880`) appears, and `createdAt` (the fail-closed earliest time) when the edit history is truncated (`totalCount` above the nodes returned) or no recorded revision explains a current mention;
- `close_failures` on synthetic inputs (no GitHub call beyond R1): a correct #488 close whose condition cites `97d223e7` returns `[]`; the same close returns a failure when `binding_review.iv` is a quote, when its effect commit is not on main, when its conditions are empty, when the posted comment differs from the approved body, and when R1 names #488 through a source dated before `closedAt`; a close of #454 returns a binding failure;
- `parse_register` on a register whose header shows the row format inside a fence, and whose rows carry the real bodies of #399, #463, #539 and #590, returns exactly the real rows; with one row's `origin` removed it raises.

### Verdict artifact `/mnt/workspace/board-tools/backlog-triage/item1-landed-fix-verdicts.json` (create at execution)

- **Schema `landed_fix_verdicts.v1`.** Top-level fields:
  - `schema`;
  - `run_status` — `complete` (every approved issue mutation executed or skipped), `verdicts_only` (the descope path; no issue mutations), or `aborted` (stopped on an error; receipts partial). The validators reject an `aborted` run; the operator decides the next step;
  - `snapshot_ref` `{path, sha256, snapshot_at, origin_main}`;
  - `executed_at`, `origin_main_at_execution` (the SHA verdicts were evaluated at; a record, not a validation input);
  - `verdicts` — exactly one entry per snapshot candidate, all 30;
  - `receipts` — the R6 issue-mutation receipts.
- **Verdict entry.** Fields:
  - `issue`, `bucket`, `verdict`, `verdict_baseline`;
  - `naming_commits`, `effect_commits`, `reverts`;
  - `acceptance_conditions` — a list of `{text, source, holds_on_main, evidence}`, per R3 and R4;
  - `phase_bindings` and `binding_review`, per R2;
  - `action` — `closed`, `commented`, `handed_to_item2`, `declined` (the operator removed it from the batch), `skipped` (with `skip_reason`), or `recorded_only`.
- **Approval batch `item1-approval-batch.json`.** `{approved_at, operator_message, publications, mutations}`, where `publications` names the comments to be posted (`batch`, `artifact`) and each mutation is `{kind, target, reason, body_sha256}` with `body_sha256 = body_sha256(<full comment text>)`. `target` is the issue number, or, for `pr_open` and `pr_merge`, the PR's head branch name, because GitHub assigns a PR number only at creation; the validator resolves a PR receipt's number to its head branch.
- **Rendered companion `item1-landed-fix-verdicts.md`.** The human table and every comment body; this is what the operator reads before approving.

### Verdict rule (normative)

| Verdict | Evidence required | Action, if the issue is unbound under R2 and not in R1 |
|---|---|---|
| **FIXED** | Every R3 condition `holds_on_main: true`, each evidenced by an effect commit on main or a direct check. The effect commit need not name the issue. | Close as `completed`. |
| **PARTIAL** | At least one condition holds via a landed change, and at least one does not. | **C/E:** comment listing held and unheld conditions; leave open. **B/D:** `handed_to_item2`, no comment. |
| **MENTION-ONLY** | No condition holds via a landed change; the naming commits only plan, authorize, document, record or re-point the issue. | **C/E:** `recorded_only`. **B/D:** `handed_to_item2`. |
| **REVERTED** | A naming or effect commit was reverted, and no condition holds on main afterwards. If an effect still holds through another commit, use FIXED or PARTIAL instead. | Same routing as MENTION-ONLY. |
| **OUT-OF-SCOPE** | An A bucket, or in R1's union at execution. | `recorded_only`. |

**Binding overrides every verdict.** A FIXED issue with any R2 binding is not closed. It is
`handed_to_item2` for B/D issues, where item 2 dispositions it, or `recorded_only` for C/E issues.
Commits that touch only `plans/`, `.consiliency/` or `docs/` records count as effect commits only for a
condition that is itself about a document. A mutation R5 skips keeps its verdict; its action becomes
`skipped`.

### Close mechanics

- **FIXED and unbound.** `gh issue close <N> -R Consiliency/agent-harness --reason completed --comment "<body>"`. The body lists each condition with the effect commit or direct check that satisfies it. When the effect commit differs from the naming commit, it says so explicitly. It ends with "Reopen if a condition was missed."
- **PARTIAL, C or E.** `gh issue comment <N>` listing held conditions (with evidence) and unheld conditions (with reasons). Never close.
- **Hygiene.** Use qualified `Consiliency/agent-harness#N` references, and never a closing keyword against another issue.

### Operator approval gate

After all verdicts are written and R5 has passed once, present `item1-landed-fix-verdicts.md` in chat.
It enumerates every issue mutation with its full text, and names the two publication comments on the
plans PR (the batch, then the artifact). Nothing is mutated before the operator approves in chat.

On approval, write `item1-approval-batch.json` with the operator's message quoted, and **publish it
before the first issue mutation**, as a comment on the plans PR carrying its exact bytes (see
Publication). Every executed issue mutation must be in the published batch with a matching body hash,
and must start after the batch comment's `created_at`. Every approved mutation that does not execute
is `skipped` with a reason. **A run has exactly one batch.** After publication nothing is added to or changed in it. An approved
mutation whose item would need a change is `skipped` with `skip_reason: "needs re-approval"`; an item
that would need to be *added* is not in the batch, so it is recorded as `declined` with the same
`skip_reason` (a B/D issue may instead be `handed_to_item2`). Either waits for a new run with its own
artifact and batch.

### Publication (cross-host)

Each publication is one PR comment containing a short heading, the file's **exact bytes** — written
with `json.dumps(obj, indent=1, sort_keys=True)` plus a trailing newline — fenced per R7 with the info
string `json`, and the bytes' sha256. Above 60,000 characters the bytes are split at line boundaries
across sequential comments marked `part i/N`; `published()` concatenates the parts and requires them to
equal the local file. Each comment's receipt goes to `item1-publication-receipts.json` (R6).

## Documentation impact

None. Execution edits no file under `docs/`, no `README.md`, `CHANGELOG.md`, `AGENTS.md`, `CLAUDE.md`
or `llms*.txt`, and no public surface. The only committed file is this plan.

## Dependencies & order

- **Before execution:**
  1. this plan passes the board and PR agent-harness#873 has **merged** (while it is open, its own description and comments name candidate issues, which would put them in R1's union);
  2. the pinned snapshot hashes to the value above;
  3. the helper self-test exits 0.
- **Execution order:**
  1. write the verdicts for all 30 candidates, with R1, R2 and R3/R4 evidence and baselines;
  2. run R5 once over the batch;
  3. write and render the artifact;
  4. operator approval, then publish the batch;
  5. for each approved mutation: R5, then mutate or skip, then record;
  6. set `run_status`;
  7. publish the artifact;
  8. validate.
- **Contract with item 2:**
  - Item 2 starts only when the artifact is published, its local bytes equal the published bytes, and `run_status` is `complete` or `verdicts_only`.
  - Every B/D issue **without a successful `issue_close` receipt** enters item 2's scope, including FIXED issues held by R2, `declined` and `skipped` issues, and every issue in a `verdicts_only` run.
  - An `aborted` or unpublished artifact means item 2 does not start, and the operator decides the next step.
- **Descope** (this plan's board is not 4/4 AGREE by round 3, or the operator declines all closes): run steps 1–3, get approval for a batch with no mutations, publish it, set `run_status: verdicts_only`, publish the artifact. No issue is mutated. A plan that did not converge is not merged, and only this descope may run, from the PR head. Item 2 then takes all 15 B/D overlap issues.
- **Deconfliction:**
  - no runtime file is touched;
  - `plans/manifest.json` is not written;
  - GitHub collisions are prevented by R1, R2 and R5 at the moment of each mutation.
- **Round cap (convergence rule 2):** at most 3 board rounds on this plan, then the descope above.

## Verification

Run on claw after execution, from a checkout with `gh` authenticated and `origin` fetched.

```bash
T=/mnt/workspace/board-tools/backlog-triage
echo "230a8a9c66cde38c375020af5921bf1233292b4b31357af15de2b6fa414e8ef3  $T/triage-snapshot.json" | sha256sum -c
python3 $T/shared_rules.py --self-test

# Validate against GitHub, git and a live R1/R2 recomputation; never against the artifact's own safety fields
python3 - <<'PY'
import json, os, sys
T = os.environ.get("T", "/mnt/workspace/board-tools/backlog-triage")
sys.path.insert(0, T)
import shared_rules as sr
s = json.load(open(f"{T}/triage-snapshot.json"))
a = json.load(open(f"{T}/item1-landed-fix-verdicts.json"))
batch, batch_at = sr.published(f"{T}/item1-publication-receipts.json", "batch")
art, _ = sr.published(f"{T}/item1-publication-receipts.json", "artifact")
assert art == a, "published artifact differs from the local artifact"
assert a["schema"] == "landed_fix_verdicts.v1" and a["run_status"] in ("complete", "verdicts_only"), "schema/run_status (an aborted run never validates)"
assert batch["approved_at"] <= batch_at, "batch published before its approval"
cand = sorted(int(n) for n in s["landed_commit_candidates"])
V = {v["issue"]: v for v in a["verdicts"]}
assert sorted(V) == cand and len(V) == len(a["verdicts"]), "verdicts must be exactly the 30 candidates, once each"
A = set(s["buckets"]["A1"] + s["buckets"]["A2"] + s["buckets"]["A3"])
snap_x = set(s["codex_inflight_exclusions"])
M = {(m["kind"], m["target"]): m for m in batch["mutations"]}
assert len(M) == len(batch["mutations"]), "duplicate batch entry"
done = {}
for r in a["receipts"]:
    key = (r["kind"], r["issue_or_pr"])
    assert r["kind"] in ("issue_close", "issue_comment") and type(r["issue_or_pr"]) is int, f"bad receipt {key}"
    assert key in M, f"{key} executed but not in the published approved batch"
    assert r["started_at"] >= batch_at, f"{key} started before the approved batch was published"
    if r["exit_code"] == 0:
        done[key] = r
for key in M:
    assert key[1] in V, f"batch mutates non-candidate #{key[1]}"
    assert key in done or V[key[1]]["action"] == "skipped", f"approved {key} neither executed nor recorded as skipped"
legal = {"B": {"closed", "handed_to_item2", "declined", "skipped", "recorded_only"},
         "C": {"closed", "commented", "declined", "skipped", "recorded_only"}}
legal["D"], legal["E"] = legal["B"], legal["C"]
for n, v in V.items():
    b, act = v["bucket"], v["action"]
    touched = [k for k in M if k[1] == n]
    if n in A or n in snap_x:
        assert act == "recorded_only" and not touched, f"#{n} out of scope but acted on"
        continue
    assert act in legal[b], f"#{n} illegal action {act} for bucket {b}"
    assert (act == "closed") == (("issue_close", n) in done), f"#{n} action {act} disagrees with its close receipt"
    assert (act == "commented") == (("issue_comment", n) in done), f"#{n} action {act} disagrees with its comment receipt"
    if act == "skipped":
        assert touched and v.get("skip_reason", "").strip(), f"#{n} skipped without an approved mutation or a reason"
    if ("issue_close", n) in M:
        assert v["verdict"] == "FIXED", f"#{n} close approved but verdict {v['verdict']}"
    if ("issue_comment", n) in M:
        assert b in ("C", "E") and v["verdict"] == "PARTIAL", f"#{n} comment approved outside C/E PARTIAL"
    if act == "closed":
        k = ("issue_close", n)
        fails = sr.close_failures(n, v, sr.gh_issue(n), M[k], done[k], fixed=True)
        assert not fails, f"#{n} unsafe close: {fails}"
    if act == "commented":
        k = ("issue_comment", n)
        assert sr.posted(sr.gh_issue(n), M[k], done[k]), f"#{n} posted comment differs from the approved body"
if a["run_status"] == "verdicts_only":
    assert not batch["mutations"] and not a["receipts"], "a verdicts_only run approved or made issue mutations"
print("artifact OK; closes:", sum(k[0] == "issue_close" for k in done))
PY
```

The validator was run before this revision against synthetic runs with a fake `gh`. It passes a correct
complete run, a `verdicts_only` run, a post-close exclusion, an unrelated later comment, a FIXED by
direct check with no effect commit, and an approved close skipped for drift. It fails a close whose
issue R1 named before the close, a bound close (#454), a quoted `binding_review`, an effect commit not
on main, a condition that does not hold, empty conditions, a close missing from the batch, an approved
close neither executed nor skipped, a mutation started before the batch was published, a posted comment
that differs from the approved text, a wrong close reason on GitHub, a comment approved on a B issue, a
published artifact that differs from the local file, a non-candidate close, a close of excluded #870, and
an `aborted` run. It also passes an item added after publication and recorded `declined`.
Its `close_failures` is shared with item 2's script, whose attack list covers the round-3 fixes.

Behaviours to observe:
- #825, #870, #525, #789 and #241 are never mutated.
- #454, #733, #660, #358, #398, #442, #428 and #688 are never closed, and neither are issues held by R2 checks (iv) and (v).
- No B/D issue receives a comment from this run.

**Expected result.**
- **Held back:** 11 of the 25 in-scope issues are expected to be held by R2: #454, #733, #660, #358, #398, #442, #428 and #688 mechanically, and #678, #685 and #720 by check (iv). That leaves 14.
- **Spot-checked:** of the 6 spot-checked unheld issues (#488, #470, #464, #498, #601, #607), 3 are FIXED-shaped.
- **Unchecked:** 8 (#451, #456, #463, #481, #490, #493, #630, #633).
- **Estimate:** **3–7 closes**: the three FIXED-shaped issues surviving R3/R4, plus up to half of the 8 unchecked at the spot-checked rate.
- **Reporting:** below 3 is reported with reasons. Zero FIXED is a valid result, and the rules are not relaxed to reach a number.

## Acceptance criteria

- [ ] `shared_rules.py --self-test` exits 0, including its `close_failures` and `parse_register` controls.
- [ ] The validator above prints `artifact OK` against live GitHub state (`complete` or `verdicts_only` runs).
- [ ] Every successful `issue_close` receipt's issue is `CLOSED/COMPLETED` on GitHub with `close_failures(...) == []`.
- [ ] The approval batch and the artifact are each published with bytes equal to their local files; the batch comment predates every issue mutation. The attributable result is the count of successful close receipts, reported against the 3–7 estimate.

## Execution Policy

- execute: effort=medium, reason=per-issue semantic verification of every stated ask against current main, with mechanical guards and gated mutations
