---
phase_loop_plan_version: 1
phase: INVENTORY
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 82efbc23a19b62044e2e8252d90a0124a1c0b5d2cc6ae2180259f63dd2941ca3
automation:
  suite_command:
    - timeout
    - '300'
    - python3
    - -c
    - 'import pathlib, sys; lines=pathlib.Path(sys.argv[1]).read_text().splitlines(); start=lines.index("```python inventory-validator")+1; stop=lines.index("```", start); exec(chr(10).join(lines[start:stop]))'
    - plans/phase-plan-v1-seats-INVENTORY.md
---

# INVENTORY: Records, Dispositions and Issue Index

## Context

Root phase of Consiliency/agent-harness#1820 with two lanes and no upstream phase.
Only CLOSEOUT consumes its completion. Acceptance references EC-INVENTORY-2,
EC-INVENTORY-3, EC-INVENTORY-4 and EC-INVENTORY-6; retired IDs stay retired.
OD-2 supplies the disposition policy. No source, tests, runtime configuration,
roadmap or registry edits belong to this phase.

This plan authorizes no GitHub mutation during planning. Execution uses governed
PRs under roadmap principle 2; the non-active `superseded` registration is the
agent-harness#1824 workaround, not evidence of absorption or delivery. v11 stays
selected. Re-pin this plan when that registration repair changes roadmap bytes.

## External Inputs

- `specs/phase-plans-seats-v1.md`, pinned above, especially INVENTORY's disposition
  table, OD-1, OD-2 and principle 2.
- Existing `docs/proposals/review-seat-sandbox.md` and qualified GitHub issue/PR
  records. Re-read their current state before any execution-time write. V-I pins
  the existing proposal's 2026-10-14 paragraph (UTF-8, without paragraph separators)
  to SHA-256 `e4da4d5ff7c7fa7f37f58012015d60ec366fa8830e7c3c94b8ff75c4afeae3ae`;
  this is a frozen input, not a hash of the future banner.

## Interface Freeze Gates

- [ ] IF-0-INVENTORY-1 — Freeze the index row as `number`, `part`, `kind`,
  `owner_ec`, `rationale`, `links` in `plans/evidence/seat-inventory/index.json`.
  The markdown table columns are qualified identifier, part, kind, owning EC,
  rationale and links. The top-level record carries `roadmap_sha256`, `rows` and
  a dated non-blocking `census` section (`query`, `rows`, each row's `repository`).
  One row owns a whole item unless the roadmap explicitly splits parts;
  mixed whole/part ownership is invalid.
- [ ] IF-0-INVENTORY-2 — Freeze the metadata-only disposition receipt in
  `plans/evidence/seat-inventory/dispositions.json`: `roadmap_sha256`, `comments`
  (number, comment_id, url, body_sha256, disposition_reviewed, pre_post_reviewed), `closures`
  (number, owner_ec, owner_receipt_url), `pi_issue_number`, `pi_issue_url`, and
  `retirement_reviewed`. Booleans record an actual review, not defaults. Pending
  actions are recorded separately and fail the completion verifier.
- [ ] IF-0-VC-2 — Validate the frontmatter argv using
  `phase_loop_runtime.verification_evidence.validate_verification_commands`.
  It is the effective `automation.suite_command`; no shell-generated selector or
  fabricated success receipt substitutes for live GitHub readback.

## Lane Index & Dependencies

SL-0 — A: Issue index and documentation reducer
  Depends on: SL-1
  Blocks: (none)
  Parallel-safe: no

SL-1 — B: GitHub dispositions and proposal banner
  Depends on: (none)
  Blocks: SL-0
  Parallel-safe: no

## Lanes

### SL-0 — A: Issue index and documentation reducer

- **Scope**: Produce EC-INVENTORY-2 using the roadmap and lane B's observed records.
- **Owned files**: `docs/review-seats-issue-index.md`, `plans/evidence/seat-inventory/index.json`
- **Interfaces provided**: `seats_issue_index`.
- **Interfaces consumed**: `seats_disposition_receipts`, IF-0-INVENTORY-1 (pre-existing plan contract), roadmap EC ownership (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: Before writing the index, run V-I and retain the expected missing-input
    failure. Once populated, run the same validation against scratch copies with
    an omitted named issue, duplicate owner, invalid EC, overlapping whole/part
    rows or mismatched markdown row; each must fail. An unmodified record is the
    path-entered positive control. These are document-validation commands, not
    new source or pytest tests.
  - impl: Inventory every issue and PR named anywhere in the roadmap. Use EC IDs
    without copying their text. Distinguish ownership from references and
    exclusions; partition agent-harness#1653 by vendor part. Incorporate lane B's
    Pi link, disposition comments, closure owners and outstanding owner actions.
    Retain one `out_of_scope` row for agent-harness#1781; do not omit it.
    Capture a fresh paginated GitHub search scoped to `repo:Consiliency/agent-harness`
    for `seat OR jail OR sandbox OR panel`, with timestamp, query and coverage
    limits in the non-blocking appendix; every result must belong to this repo.
    Search failures do not expand the exit; record them with an empty census.
  - impl: Review docs after all lane B outputs. The index can be drafted early,
    but its final synthesis depends on SL-1; it must not manufacture closure
    receipts while another phase's owner action remains pending.
  - verify: Run V-I and manually reconcile every ownership row with the pinned
    roadmap, including split-part exhaustiveness. Retain reviewed links and
    command results; machine checks supplement, rather than replace, this review.

### SL-1 — B: GitHub dispositions and proposal banner

- **Scope**: Produce the records for EC-INVENTORY-3, EC-INVENTORY-4 and EC-INVENTORY-6.
- **Owned files**: `docs/proposals/review-seat-sandbox.md`, `plans/evidence/seat-inventory/dispositions.json`
- **Interfaces provided**: `seats_disposition_receipts`.
- **Interfaces consumed**: IF-0-INVENTORY-2 (pre-existing plan contract), OD-2 disposition table (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: Capture read-only before-state and demonstrate V-I fails for absent
    receipts. Validate negative scratch controls for a stale comment digest,
    wrong issue association, open required closure, absent Pi record or removed
    proposal banner. Never mutate GitHub to create a negative control.
  - impl: Before any public write, review each exact body file against OD-2,
    allowing only table reasons and public-record links. This includes comments,
    closures, reopenings, Pi issue, banner and receipts. Record pre-post review
    against the body digest; edits require re-review. Apply the same review to reused
    bodies. Security-sensitive content follows OD-10 privately, never public text.
  - impl: At execution, post the table's dispositions on agent-harness#1740,
    agent-harness#1744, agent-harness#1641, agent-harness#1623, agent-harness#1644
    and agent-harness#1731. Preserve salvage destinations and the re-file to
    agent-harness#1391. Do nothing to agent-harness#1781. Reuse an already-correct
    disposition rather than duplicating it; use exact body files for comments.
  - impl: Close only agent-harness#1644 and agent-harness#1731 under this phase's
    authority, retaining the OD-4 reopening condition and public denial-evidence
    link (for example the public statement in agent-harness#1641). Reopening text
    cites the OD-4 decision by ID only; containment reasons remain private.
    The other four closures remain with the table's EC owners after salvage;
    collect their actual owner receipts rather than closing on their behalf.
    Record unresolved closures as pending, with EC-INVENTORY-3 still open.
  - impl: Find or file the Pi review-seat issue, reference EC-PI IDs and the
    roadmap, and record its returned number. Add a superseded banner to the
    proposal as a separate paragraph immediately after its title, exactly
    `> This proposal is superseded by specs/phase-plans-seats-v1.md.` Preserve the
    historical 2026-10-14 status paragraph byte-for-byte. Record EC-INVENTORY-6 on
    agent-harness#896 with the roadmap and REMOTE reference, preserving historical
    evidence. Re-read all changed records and store metadata-only receipts.
  - verify: Run V-I after the index reducer is ready. Confirm fetched bodies match
    their pre-post reviewed digests. Review owner closure receipts against landed
    salvage evidence; set their reviewed fields only then. Verify the retirement
    statement's meaning, not merely that a comment exists.

## Execution Notes

The roadmap prescribes `phase-plan-seats-v1-<ALIAS>.md`, which manifest `PLAN_RE`
rejects. Use the manifest-accepted `phase-plan-v1-seats-<ALIAS>.md` here;
`phase-plan-v1-<ALIAS>.md` collides with v1. A later roadmap erratum must reconcile
its banner/execution notes and re-pin plans; this repair preserves the pinned input.

No-doc-change decision for README, CHANGELOG and release notes: this phase
changes records only, with no runtime behavior, installation or release delta.
Lane A confirms that decision after reviewing lane B's outputs.

GitHub write ownership is limited to the six disposition threads, the two
INVENTORY-owned closures, the Pi issue, and agent-harness#896; all other closure
records are read-only inputs. Lanes have disjoint paths. No code companions,
lockfiles, generated files or skill changes are needed.

## Verification

V-I is the frontmatter `automation.suite_command`. Execute it from the repo root
with the installed runtime's Python and PyYAML:

```bash
timeout 300 python3 -c 'import pathlib, subprocess, yaml; p=pathlib.Path("plans/phase-plan-v1-seats-INVENTORY.md"); a=yaml.safe_load(p.read_text().split("---", 2)[1])["automation"]["suite_command"]; subprocess.run(a, check=True)'
```

The embedded validation command below is documentation, not a new runtime module.

```python inventory-validator
import hashlib, json, re, subprocess, sys
from pathlib import Path
if sys.flags.optimize:
    raise RuntimeError('INVENTORY validation requires assertions enabled')
roadmap = Path('specs/phase-plans-seats-v1.md').read_text()
index = json.loads(Path('plans/evidence/seat-inventory/index.json').read_text())
receipts = json.loads(Path('plans/evidence/seat-inventory/dispositions.json').read_text())
digest = hashlib.sha256(Path('specs/phase-plans-seats-v1.md').read_bytes()).hexdigest()
assert index['roadmap_sha256'] == receipts['roadmap_sha256'] == digest
named = set(re.findall(r'(?:Consiliency/)?agent-harness#([0-9]+)', roadmap))
goals = set(re.findall(r'^- \[ \] (EC-[A-Z0-9-]+) —', roadmap, re.M))
rows = index['rows']
assert 'repo:Consiliency/agent-harness' in index['census']['query'].split()
assert all(r['repository'] == 'Consiliency/agent-harness' for r in index['census']['rows'])
assert named <= {str(r['number']) for r in rows}
keys = [(r['number'], r['part']) for r in rows]
assert len(keys) == len(set(keys))
for number in {r['number'] for r in rows}:
    parts = [r['part'] for r in rows if r['number'] == number]
    assert 'whole' not in parts or len(parts) == 1
for r in rows:
    assert r['kind'] in ('owned', 'reference', 'out_of_scope')
    assert r['owner_ec'] in goals if r['kind'] == 'owned' else r['owner_ec'] is None
    assert r['rationale'].strip()
split = [r for r in rows if r['number'] == 1653 and r['kind'] == 'owned']
assert len(split) >= 2 and all(r['part'] != 'whole' for r in split)
rendered = Path('docs/review-seats-issue-index.md').read_text()
for r in rows:
    assert f"| agent-harness#{r['number']} | {r['part']} | {r['kind']} | {r['owner_ec'] or '—'} |" in rendered
excluded = [r for r in rows if r['number'] == 1781]
assert len(excluded) == 1 and excluded[0]['kind'] == 'out_of_scope'
# Supplemental screening, never a substitute for pre-post semantic review.
forbidden = re.compile(r'(?i)(?:/home/|/Users/|/mnt/|/tmp/|/var/|[A-Z]:\\|'
                       r'gh[pousr]_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|\bsk-[A-Za-z0-9]+|'
                       r'Bearer\s+\S+|[\w.+-]+@[\w.-]+\.[a-z]{2,}|'
                       r'\b(?:\d{1,3}\.){3}\d{1,3}\b|\b[\w-]+\.(?:local|internal)\b)')
def screened(body):
    assert not forbidden.search(body), 'public body requires private review'
def fetch(endpoint):
    return json.loads(subprocess.check_output(['gh', 'api', 'repos/Consiliency/agent-harness/' + endpoint], timeout=30))
expected = {1740, 1744, 1641, 1623, 1644, 1731, 896}
assert {r['number'] for r in receipts['comments']} == expected
for r in receipts['comments']:
    comment = fetch('issues/comments/' + str(r['comment_id']))
    assert comment['issue_url'].endswith('/' + str(r['number']))
    assert comment['html_url'] == r['url']
    assert hashlib.sha256(comment['body'].encode()).hexdigest() == r['body_sha256']
    assert r['disposition_reviewed'] is True and r['pre_post_reviewed'] is True
    screened(comment['body'])
owners = {1740: 'EC-CLAUDE-2', 1744: 'EC-CLAUDE-3', 1641: 'EC-CLAUDETUI-1', 1623: 'EC-CLAUDETUI-1', 1644: 'EC-INVENTORY-3', 1731: 'EC-INVENTORY-3'}
assert {r['number']: r['owner_ec'] for r in receipts['closures']} == owners
for r in receipts['closures']:
    pr = fetch('pulls/' + str(r['number']))
    assert pr['state'] == 'closed' and r['owner_receipt_url'].startswith('https://github.com/Consiliency/agent-harness/')
pi = fetch('issues/' + str(receipts['pi_issue_number']))
assert 'pull_request' not in pi and pi['html_url'] == receipts['pi_issue_url']
assert 'EC-PI-' in pi['body'] and 'specs/phase-plans-seats-v1.md' in pi['body']
screened(pi['body'])
proposal = Path('docs/proposals/review-seat-sandbox.md').read_text()
assert proposal.split('\n\n')[1] == '> This proposal is superseded by specs/phase-plans-seats-v1.md.'
# Frozen historical paragraph from the reviewed proposal input.
history = proposal.split('\n\n')[2]
assert hashlib.sha256(history.encode()).hexdigest() == 'e4da4d5ff7c7fa7f37f58012015d60ec366fa8830e7c3c94b8ff75c4afeae3ae'
screened(proposal.split('\n\n')[1])
assert receipts['retirement_reviewed'] is True
subprocess.run(['git', 'diff', '--check', '--',
                'docs/review-seats-issue-index.md',
                'plans/evidence/seat-inventory/index.json',
                'plans/evidence/seat-inventory/dispositions.json',
                'docs/proposals/review-seat-sandbox.md'], check=True, timeout=30)
print('INVENTORY evidence validation: PASS')
```

The verifier reads actual GitHub records, checks source-content binding and
reconciles the materialized index; each read has a 30-second timeout and the
whole check a 300-second timeout. Authentication/network errors fail visibly.
Run negative document controls by using scratch copies of the same input paths
and the same frontmatter argv, leaving the checkout and remote records intact.
The missing-input run must fail; an unmodified fixture with read-only GitHub
responses passes. Add negatives for optimized Python, unscoped/foreign census,
missing pre-post approval, a synthetic forbidden body, the old status paragraph
used as the banner, and altered historical text. Fixtures prove checks only;
completion still requires actual GitHub readback. Add an
explicit pairwise check during ownership review that no `whole` row coexists
with a vendor part, and that each split covers the roadmap's named parts.

There are **no new pytest selectors** in this documentation/GitHub phase, so
agent-harness#1825's collection rule has no selectors to test here. No full or
parallel local suite and no `-n auto`. Any later necessary scoped pytest command
on a shared host must specify `timeout 300`, `-n 0`, `-p no:cacheprovider` and explicit
files/selectors. Full-suite verification belongs to hosted CI or hosted Gate A.

Acceptance also requires semantic review of the table, owner receipts, Pi issue
and retirement comment; V-I cannot prove those meanings merely from hashes.
Retain the index and link receipts in the reviewed PR, with a runner-stamped
verification/closeout amendment if execution later becomes runner-selected.
Never use proxy evidence without a roadmap amendment. Plan and implementation
review follow principle 2, including native-first/T3 fallback, exact-head
cross-vendor review, the six required checks and hosted Gate A before landing.
None of those external actions is performed during this planning run.

## Acceptance Criteria

- [ ] EC-INVENTORY-2 — proven by `V-I` and ownership review of `docs/review-seats-issue-index.md`, falsified by the omitted/duplicate/overlapping-row controls at the actual index construction surface, with an unmodified path-entered control.
- [ ] EC-INVENTORY-3 — proven by `V-I` and the OD-2 disposition/owner-receipt review, falsified by stale-comment and unresolved-closure controls at the actual GitHub records, with a current path-entered readback control.
- [ ] EC-INVENTORY-4 — proven by `V-I` and the Pi issue/proposal review, falsified by missing-record/banner controls at the issue and proposal construction surfaces, with a valid path-entered readback control.
- [ ] EC-INVENTORY-6 — proven by `V-I` and the retirement review on `agent-harness#896`, falsified by a missing or semantically wrong retirement record, with the path-entered readback control.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/review-seats-issue-index.md`, `docs/proposals/review-seat-sandbox.md`
- evidence paths: `plans/evidence/seat-inventory/index.json`, `plans/evidence/seat-inventory/dispositions.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

Keep pending owner closures explicit. They hold this phase's final acceptance
and CLOSEOUT only; they create no start gate on another vendor phase. Missing or
malformed records route to non-human `contract_bug`. No security-sensitive detail,
private host identity, raw credentials or private review path enters the index,
comments, closures, reopenings, Pi issue, banner or receipts. Public-write review
precedes posting; automated screening supplements that review.
