# Sandboxed Review Seats — Phase Roadmap (seats v1)

> **Status (2026-11-04): PROPOSED — for board review. Not registered in `specs/roadmap-status.json` and not runner-selected (see OD-1).**
> How to use: after review and OD-1, run `/claude-plan-phase specs/seats-roadmap-v1.md <ALIAS>` per phase, then `/claude-execute-phase <alias>`. Completion is recorded in the ledger, not by ticking boxes.

---

## Context

The standing rule is agent-harness#1244: **a review seat never runs toolless.** A seat runs
with tools in a sandbox, or is filled natively and labelled, or reports a typed degraded
notice. Today only part of the board meets it. The Claude and Gemini seats have per-seat
jails (agent-harness#1132, agent-harness#1555). Codex and Grok run with tools but unconfined
(`seat_filesystem_unconfined`). Pi has no review-seat route at all.

The work has stalled for months, for five reasons:

1. **Per-vendor jail breakage.** Each vendor's CLI failed in its own way: Claude TUI
   output (agent-harness#1461), Codex's nested bubblewrap (agent-harness#1335), Grok's
   `--cwd` handling (agent-harness#1460) and agy version churn (agent-harness#1602).
2. **Team-host binds.** Bind walks, the managed tooling root, `pytest` in managed runtimes
   and resolver readability failed on shared hosts (agent-harness#1413,
   agent-harness#1357).
3. **Serial live qualification.** Every fix waited for its own owner window.
4. **Abandoned drafts.** Six or more draft PRs went stale and conflicting. The
   agent-harness#848 proposal (`docs/proposals/review-seat-sandbox.md`) went stale behind
   v10's digest freeze.
5. **No single roadmap.** About 60 open issues, with no shared definition of done.

**Thesis.** One roadmap, one per-vendor readiness matrix and one definition of done (DoD,
principle 1). Local jails proceed now. The remote fallback is built offline and activated
only after Stage 2 activates (agent-harness#1795). Live qualification is batched into owner
windows.

**Binding owner decisions (2026-11-04).**

- **Both routes, every vendor.** Claude, Gemini, Codex, Grok and Pi (Pi reaches models such
  as DeepSeek) each get a local per-seat jail with tools on our hosts, team hosts included.
  Any vendor the local jail cannot hold gets an OpenShell review-runner with provider egress
  and credential projection, behind its own security review and owner approval.
  Qualification is batched.
- **The Claude transport is chosen by bake-off.** The first Claude phase builds the
  `ClaudeTransport` seam (`tui | print | sdk`) with both `print` (reviving
  agent-harness#1740) and `sdk` (the Agent SDK projected into the jail through
  agent-harness#1782). A live bake-off compares them, and the owner picks the default from
  its evidence. The TUI is the last fallback. All TUI repair comes after.

**Readiness snapshot (input, origin/main at `c913e4121`).** INVENTORY turns this into the
maintained matrix (IF-0-INVENTORY-1).

| Vendor | Local route today | Main blockers | Remote |
|---|---|---|---|
| Claude | Jailed, TUI only; auto-qualifies on first use | TUI returns no canonical output live (agent-harness#1461). Jailed print is a conflicting draft (agent-harness#1740). `sdk` is refused for panel seats. Login-proof parity (agent-harness#1532). | No route |
| Gemini | Jailed with tools and an egress proxy (agent-harness#1555) | Board follow-ups (agent-harness#1706). Qualification lost on upgrade (agent-harness#1420). Partial-clone staging (agent-harness#1419). Not live-qualified on team hosts. | No route |
| Codex | Unconfined, inside its own bwrap | Inner bwrap denied by AppArmor on team hosts (agent-harness#1335, agent-harness#1003). Jail route proposed (agent-harness#1480). | No route |
| Grok | Unconfined, allow-listed tools (agent-harness#1652) | Read-only tree (agent-harness#1686). `--cwd` recurrence (agent-harness#1460). Unconfined egress (agent-harness#1653). | No route |
| Pi | None. The board registry lists `pi` on omnigent backing only; not a panel leg. | No leg, jail profile, credential lane or egress allowlist. Vendor family is `pi`, not the routed model's vendor. No issue filed. | The agent-toolkit `full-remote-pi-runner` vector has no egress. The agent-harness client refuses the `pi-runner` workload. |

---

## Architecture North Star

```
 brokered review seat (vendor V, staged tree)
        │
        ▼
 seat route resolver (JAILCORE): one decision, one typed code per failed step
        │
  1. local seat jail: profile[V] = tools + dependency projection + provider-only
        │              egress + EC-EXECFIND-2 pass on this host
        │   Claude only: ClaudeTransport = default (owner bake-off) → other admitted → tui last
        │ cannot hold (typed code)
  2. remote sandbox: OpenShell review-runner + provider-egress vector + projected
        │              expiring credential (owner-activated; REMOTE)
        │ unavailable (typed code)
  3. native fill: labelled stand-in for V; the president is told
        │ unavailable
  4. degraded: typed code + fix line in the pre-launch mode line. Never sealed, never toolless.
```

---

## Assumptions (fail-loud if wrong)

1. The per-seat jail (`seat_jail.py`, `seat_uid.py`, the J7 route decision and EC-EXECFIND-2
   passes) is the local boundary for every vendor. A vendor whose CLI cannot run in it gets
   a recorded can't-hold determination (principle 6), not a parallel boundary.
2. Executable-dependency projection (agent-harness#1782) can carry each vendor's launcher
   closure: the Node/Python runtime, packages and native images. That includes the Agent SDK
   and its Python dependencies.
3. Under a subscription login, `print` and `sdk` both draw on subscription limits. This is
   a dated external input (see External Inputs), not a guarantee. The bake-off checks it.
4. Stage 2 activation waits on the owner's live gateway qualification and ai-stack Unit 7.
   No local phase depends on it.
5. The v11 roadmap remains the runner's selected roadmap while this one is reviewed. Its
   PANELSPLIT phase may move `panel_invoker.py` into a package at any point in this
   roadmap.

---

## External Inputs

All pins are inputs. None is an output of this roadmap.

| Input | Pin |
|---|---|
| Input baseline | origin/main at `c913e4121`, fetched 2026-11-04 |
| Claude print-route decision record | `plans/decision-claude-print-subscription-route-20261008.md`, sha256 `14d424ad85fe97dcbaabc5df1f8d8beffc12a8eefdd2678694da19612fe59381`. §4a is the agent-harness#1775 record; its item 7 requires a further ratified amendment before any jailed default changes. |
| Claude SDK decision record (Stage 3) | `plans/decision-claude-sdk-subscription-route-20261015.md`, sha256 `544147229e0b2cc8ff44bfd761145dbe4cfe4f30e011d165fecd857bb8d0a2be` |
| Stage 2 plan (review-runner image, vectors) | `plans/detailed-openshell-coordinator-stage2-1795-20261102.md`, sha256 `ccd32c25047c2324ae2ab5c3a83b2daeb008c9b69b5b03fd19342a9b66653234` |
| Placement policy vectors (`pending_qualification`) | `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/policies.json`, sha256 `5b3bc7f515bd2a4cbc10a18d98465d511f65e8089213ceb8c21f9cce2409020f` |
| Remote placement contract (C5: empty `egress_needs` for non-local) | `plans/detailed-remote-seat-placement-896-20261010.md`, sha256 `28b15ad85e5ecbd6a600b6de7f3a0a5502da88122e8cdc314029ca0c37ffedac` |
| Dependency projection contract | `docs/executable-dependency-projection.md`, sha256 `c3e955fcdcae3d36dc59c60c293d84cb4df5df3fbcb6efdc3abe9e86ba1a8d9c` |
| Approved Gemini jail digest | `84d39a72` (agent-harness#1706) |
| Claude billing statement | Anthropic Help Center article 15036540, as read 2026-11-04. Under a subscription login, the Agent SDK and `claude -p` draw on subscription limits. A 2026-05 plan to bill them at API rates was paused on 2026-06-15 "for now" and reaffirmed on 2026-10-07. Dated; may change. |

---

## Non-Goals

- macOS Seatbelt and Windows AppContainer/WSL jails. Hosts without the Linux jail
  prerequisites use the remote rung. The per-OS jails stay tracked under agent-harness#1244.
- Extracting the sandbox code to its own package. Only the seat-side interface of
  agent-harness#1704 is in scope (JAILCORE).
- Stage 2 itself: transport, coordinator, image build and deployment. This roadmap
  consumes it.
- Solo-runner SDK rollout. Releasing the CHANGES REQUIRED hold on agent-harness#1781.
- Changing the advisor-board composition, seat floors or president ladder, except removing
  sealed paths (CLOSEOUT).
- Any automatic, silent fallback between Claude transports. Fallback is by selection or a
  typed, recorded step (decision record §2).

---

## Cross-Cutting Principles

1. **Definition of done, per vendor row.** "This vendor's seat runs with tools, sandboxed, on
   our hosts, live-qualified" means all four of these:
   - **Jailed with tools.** A brokered seat given a staged tree resolves to `jailed` with
     its full tool set.
   - **Sandboxed.** The profile has a recorded EC-EXECFIND-2 pass on each qualifying host.
     Egress is confined to its provider allowlist. It holds only the capability its profile
     declares (EC-HARDEN-6).
   - **On our hosts.** At least one standard host, and one team host under two operator
     accounts.
   - **Live-qualified.** An admitted canonical review from a real board in an owner window,
     on a released runtime, with a tool receipt proving a staged-tree read. Its evidence
     digest is in the matrix.

   A remote row means the same on the remote rung after owner activation. A row is
   `done-local`, `done-remote`, or not done.
2. **Governance, every phase.**
   - **Plan review before implementation.** The native agent-harness advisor board runs
     first. A T3 cross-vendor delegate replaces any failed native seat, and each native
     failure is filed or commented on as an issue (`agent-harness#NNN`).
   - **Before landing.** The six required CI checks, a dispatched Gate A on the branch, and
     a cross-vendor board on the exact head.
   - **Review rounds.** Bounded per `docs/agent-phase-convergence.md` §8.
3. **Never toolless.** No phase adds or widens a sealed route. Each failed step yields one
   typed notice code with a fix line (closed vocabulary in `seat_jail.NOTICES`).
4. **Qualification-pinned files.** Treat `gemini_heartbeat.py`, `agy_qualification.py`
   and every jail profile builder as qualification-pinned: never edit them casually. A
   change to a profile digest is batched with the next requalification (the
   agent-harness#1804 pattern) and names its window.
5. **Batch live work.** No phase runs its own live window except CLAUDE's bake-off (W0).
   The bake-off picks the default that QUALIFY1's Claude row qualifies. All other live
   evidence goes to QUALIFY1, QUALIFY2 or REMOTE's activation window.
6. **Stall rule.** A local vendor phase that needs a third plan amendment, or whose
   amendments outnumber its implementation PRs, stops. The owner then records either a
   diagnosis or a can't-hold determination (OD-9). A can't-hold determination moves that
   row to REMOTE; it does not wait.
7. **Plan discipline.** Pin inputs only. Downstream plans reference EC IDs and never
   restate them. Detail goes into the frozen artifacts below.
8. **Public repo.** No secrets, private hosts or private paths in code, docs or evidence.
   Security weaknesses are reported privately (CONTRIBUTING.md).

---

## Owner Decisions and Live Owner Actions

| ID | What the owner decides or does | Phase |
|---|---|---|
| OD-1 | How this roadmap becomes runner-selectable: stay advisory until v11 closes, extend the registry to allow a second active roadmap, or fold in as a v11 amendment | INVENTORY |
| OD-2 | Confirm the draft-PR dispositions | INVENTORY |
| OD-3a | Ratify the decision-record amendment: `print` and `sdk` both selectable for the jailed seat, the bake-off authorised, TUI last, and the jailed-default promotion taken from v11 PANEL (§4a item 8) | CLAUDE |
| OD-3b | Pick the jailed Claude default (`print` or `sdk`) from bake-off evidence | CLAUDE |
| OD-4 | The jail as Codex's boundary (inner sandbox off) supersedes the nested-AppArmor route | CODEX |
| OD-5 | Pi: credential lane (subscription vs opt-in API key), seated models, vendor-family identity | PI |
| OD-6 | TUI fallback: repaired, or retired to a typed degraded route | CLAUDETUI |
| OD-7 | Approve the provider-egress vector, credential projection, the security review and the C5 amendment; later, activation | REMOTE |
| OD-8 | Remove sealed routes and the president's sealed last resort (agent-harness#1250) | CLOSEOUT |
| OD-9 | Any can't-hold determination (principle 6) | any vendor phase |
| LA-1 | Host administration: subuid/subgid ranges, `legacy_tiocsti = 0`, the AppArmor `setpriv` override on Ubuntu 24.04+, a managed release carrying the seat dependencies | TEAMHOST |
| LA-2 | Vendor logins for each operator account on each window host | QUALIFY1, QUALIFY2 |
| LA-3 | Run windows W0, W1 and W2, and read the account usage meter for W0 | CLAUDE, QUALIFY1, QUALIFY2 |
| LA-4 | Stage 2 live gateway qualification, ai-stack Unit 7 and the remote activation window | REMOTE |

---

## Top Interface-Freeze Gates

1. **IF-0-INVENTORY-1** — The readiness-matrix row schema in
   `docs/review-seats-readiness.md`. Fields: vendor, route, profile digest, tool surface,
   credential lane, egress allowlist id, projection, hosts, qualification record, live
   evidence digest, status (principle 1).
2. **IF-0-CLAUDE-1** — The jailed `ClaudeTransport` selector. Values `tui | print | sdk`.
   The default comes from one declared setting. Refused values are typed and never fall
   back.
3. **IF-0-CLAUDE-2** — The bake-off evidence record, one per run. Fields: transport, run
   id, `CLAUDE_CODE_ENTRYPOINT` value, canonical-output outcome, admission predicates,
   billing landing (`subscription | extra_usage | api | unknown`), meter-observation
   reference.
4. **IF-0-JAILCORE-1** — The leg-profile contract. A vendor registers one jail profile:
   argv builder, binds, environment, projection requirement, credential delivery and
   notice codes. The route resolver evaluates registered profiles without leg-specific
   branches.
5. **IF-0-JAILCORE-2** — The per-provider egress allowlist contract: allowlist id, measured
   request set and probe rows, served by the host proxy. The Gemini allowlist is its first
   instance.
6. **IF-0-QUALIFY1-1** — The batched-window protocol and window evidence record
   (`plans/evidence/seat-qualification/`, metadata only).
7. **IF-0-REMOTE-1** — The provider-egress review-runner vector. It is a new entry in
   `policies.json`, never a change to `full-remote-pi-runner`.

---

## Phases

### Phase 0 — Inventory, Readiness Matrix and Dispositions (INVENTORY)

**Objective**
Replace scattered drafts and issues with one matrix, one DoD and one disposition per
stale artifact.

**Exit criteria**
- [ ] EC-INVENTORY-1 — `docs/review-seats-readiness.md` holds one row per vendor (Claude, Gemini, Codex, Grok, Pi) and per remote route, in the IF-0-INVENTORY-1 schema. Each row carries the principle 1 DoD and current evidence links. Falsified by a missing vendor, a row without a status, or a status that its evidence does not support.
- [ ] EC-INVENTORY-2 — Every open issue matched by `seat OR jail OR sandbox OR panel`, plus agent-harness#1244, agent-harness#1132 and agent-harness#1288, is assigned in that document to exactly one phase EC or recorded as out of scope. Falsified by an unassigned issue in a fresh search.
- [ ] EC-INVENTORY-3 — Each draft PR below carries its disposition as a PR comment, and closures are done after OD-2. Falsified by a draft still open without a disposition.
- [ ] EC-INVENTORY-4 — A Pi review-seat issue is filed, and the agent-harness#848 proposal is marked superseded by this roadmap. Falsified by either missing.
- [ ] EC-INVENTORY-5 — OD-1 is recorded. Then either the roadmap is registered coherently (`phase-loop validate-roadmap --repo . --roadmap <selected>` passes), or it stays advisory with that reason in its banner.

**Scope notes**
- Preamble phase (documentation and GitHub records); decompose into 2 lanes with disjoint
  outputs. Lane A owns the matrix document. Lane B owns PR comments, issue edits and the
  proposal banner.
- Draft dispositions, for OD-2:
  - agent-harness#1740: **revive** as CLAUDE lane B (`print`). It follows OD-3b instead of
    §4a's opt-in-only default.
  - agent-harness#1744: **salvage, then close.** The SDK adapter, the `claude-sdk` extra
    pin and the Gate A clean-room install fix move into CLAUDE lane C as a seat-neutral
    adapter. The solo-runner launcher route re-files on agent-harness#1391.
  - agent-harness#1641: **salvage, then close.** Its native-image resolver is already
    carried by agent-harness#1740. Its private startup evidence goes to CLAUDETUI.
  - agent-harness#1623: **split, then close.** The Grok allow-list part is superseded by
    agent-harness#1652. The PTY and screen-reader banner fixes go to CLAUDETUI. Resolver
    readability for the seat uid goes to TEAMHOST.
  - agent-harness#1644: **close.** Superseded by the jailed Codex route (OD-4).
  - agent-harness#1731: **hold** as a draft until the Codex row is `done-local` on a team
    host, then close. Its denial evidence is cited in the matrix. If OD-4 is rejected, it
    becomes CODEX's input.
  - agent-harness#1781: **out of scope.** It stays held at CHANGES REQUIRED; this roadmap
    neither releases the hold nor depends on the PR.
- Also record whether the SSH-first follow-on plans of agent-harness#896 are retired in
  favour of the OpenShell route.

**Governance**
- Principle 2. Lane B's closures wait for OD-2. OD-1 is required to exit.

**Non-goals**
- Any code change.

**Key files**
- `docs/review-seats-readiness.md`
- `docs/proposals/review-seat-sandbox.md`
- `specs/seats-roadmap-v1.md`
- `specs/roadmap-status.json`

**Depends on**
- (none)

**Produces**
- IF-0-INVENTORY-1

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: `docs/review-seats-readiness.md`, `docs/proposals/review-seat-sandbox.md`; evidence paths: the matrix and PR/issue links; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 1 — Claude Seat Transports and Bake-off (CLAUDE)

**Objective**
Give the jailed Claude seat the `ClaudeTransport` seam with both `print` and `sdk`, run the
bake-off and let the owner choose the default, with TUI as the last fallback.

**Exit criteria**
- [ ] EC-CLAUDE-1 — The jailed seat reads the IF-0-CLAUDE-1 selector. `print`, `sdk` and `tui` each launch inside the same jail, staged clone, tool set and teardown. A refused value launches nothing. Falsified by a transport that widens the tool surface or the binds, or by a silent fallback.
- [ ] EC-CLAUDE-2 — `print` runs `claude -p --output-format stream-json` in the jail under the decision record's admission rules: login-store subscription proof, `apiKeySource == "none"`, no `--bare`, no salvage. Falsified by an admitted result that breaks any rule.
- [ ] EC-CLAUDE-3 — `sdk` runs the Agent SDK inside the jail. The SDK and its Python dependencies are projected through agent-harness#1782, with the system `claude` pinned as its CLI and the same admission rules. Falsified by an ambient-host dependency or an unprojected import.
- [ ] EC-CLAUDE-4 — The amendment ratified as OD-3a is an ancestor of the activating landing, in the order EC-REVIEWTRUTH-15 requires. Falsified by a landing that activates `sdk` or changes the default without it.
- [ ] EC-CLAUDE-5 — Bake-off window W0 records one IF-0-CLAUDE-2 record per run, for a run count fixed in the phase plan before the window. It covers `print`, `sdk` and the control: T3 Code's SDK route, known to be billed to the subscription. Each record measures (a) canonical output actually returned (the agent-harness#1461 failure mode) and (b) billing landing against the owner's account usage meter, and records `CLAUDE_CODE_ENTRYPOINT`. Falsified by a run without its entrypoint tag or meter observation.
- [ ] EC-CLAUDE-6 — OD-3b: the owner's choice of default, citing W0's evidence digest, is recorded in the decision record, and the shipped default setting equals it. Switching default later changes the setting and the record only. Falsified by a default that disagrees with the record, or by a switch that needs code beyond the setting.
- [ ] EC-CLAUDE-7 — The jailed route holds the same login proof as the print and TUI routes (agent-harness#1532). `DISABLE_UPDATES=1` joins `seat_env` for the Claude leg (agent-harness#1804), and its digest change is batched into W0/W1. A timed-out login wait republishes the seat mode (agent-harness#1255).

**Scope notes**
- Decompose into 4 lanes:
  - **Lane A** owns the selector, the default setting and the decision-record amendment. It
    publishes IF-0-CLAUDE-1 on day one.
  - **Lane B** owns `print`, rebased from agent-harness#1740.
  - **Lane C** owns `sdk`: agent-harness#1744's adapter plus the projection declaration.
  - **Lane D** owns IF-0-CLAUDE-2, the bake-off recorder, and EC-CLAUDE-7.
  - Lanes B and C own disjoint transport modules and start against lane A's freeze.
- Until OD-3b the shipped default stays as §4a sets it (the TUI). Operators select `print`
  or `sdk` explicitly for the agent-harness#1461 workaround.
- A transport whose W0 runs land on extra usage or API billing ranks behind one that lands
  on subscription limits; OD-3b still decides. If both land off-subscription, OD-3b also
  chooses among the TUI, degraded, or REMOTE.
- Single writers: Lane A alone edits the decision record. The seat-launch module of
  `panel_invoker.py` (or its PANELSPLIT successor) is edited only at the selector call
  site, by Lane A.
- Absorbs agent-harness#1391 (jailed scope), agent-harness#1422, agent-harness#1494,
  agent-harness#1254, agent-harness#1531, agent-harness#1585 and agent-harness#1682.

**Governance**
- Principle 2.
- OD-3a must be ratified before lane B or C lands an activating change.
- OD-3b is required to exit. W0 is owner action LA-3.

**Non-goals**
- TUI repair (CLAUDETUI). Remote Claude (REMOTE). Capture and research seats stay as §4a
  item 1 sets them.

**Key files**
- `plans/decision-claude-print-subscription-route-20261008.md`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/claude_print_observations.py`
- `phase-loop-runtime/src/phase_loop_runtime/claude_sdk_adapter.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_credentials.py`
- `phase-loop-runtime/src/phase_loop_runtime/executable_dependency.py`
- `phase-loop-runtime/pyproject.toml`
- `docs/advisor-board-capabilities-card.md`

**Depends on**
- INVENTORY

**Produces**
- IF-0-CLAUDE-1
- IF-0-CLAUDE-2

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the Claude decision record, `advisor_board/CONTRACTS.md`, the capabilities card; evidence paths: W0 records under `plans/evidence/seat-qualification/` (operational evidence, owner-observed meter readings by reference); `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 2 — Gemini Seat to Done (GEMINI)

**Objective**
Take the landed Gemini jail to a qualification candidate on standard and team hosts.

**Exit criteria**
- [ ] EC-GEMINI-1 — Every agent-harness#1706 item is closed, or deferred with a recorded reason. Each new test turns red when its check is neutralised.
- [ ] EC-GEMINI-2 — A runtime upgrade that does not change the profile digest keeps the recorded agy qualification. A change re-qualifies once, without a manual `agy models` (agent-harness#1420, agent-harness#1520). Falsified by a lost pass after a digest-preserving upgrade.
- [ ] EC-GEMINI-3 — Staging works from a partial-clone checkout (agent-harness#1419), and a new agy version is admitted only through the last-known-good pointer (agent-harness#1602). Falsified by a board that qualifies mid-run.
- [ ] EC-GEMINI-4 — `phase-loop seat-sandbox qualify` and the Gemini egress install pass provider-free on one standard host and one team host. The matrix row reads `candidate`.

**Scope notes**
- Decompose into 2 lanes. **Lane A** owns the agent-harness#1706 egress-front, overlay and
  test items. **Lane B** owns qualification persistence, staging and the version-pointer
  integration.
- The route core is qualification-pinned (principle 4). Any digest change names its window.

**Governance**
- Principle 2.

**Non-goals**
- The Gemini heartbeat route with dependency projections (unsupported per
  agent-harness#1782; out of scope).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress/`
- `phase-loop-runtime/src/phase_loop_runtime/review_stage.py`

**Depends on**
- INVENTORY

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: `advisor_board/CONTRACTS.md`, the capabilities card; evidence paths: provider-free qualification records; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 3 — Jail Profile Registry and Route Resolver (JAILCORE)

**Objective**
Let a vendor join the jail by registering a profile, and run the fallback chain through
one resolver.

**Exit criteria**
- [ ] EC-JAILCORE-1 — The Claude and Gemini profiles are registered under IF-0-JAILCORE-1 with byte-identical profile digests. Falsified by any digest change, or by a profile needing a branch in the route decision.
- [ ] EC-JAILCORE-2 — The resolver walks local jail → remote → native fill → degraded and emits one typed code per failed step. The `SEALED_FALLBACK_CODES` routes resolve to that chain on review seats (agent-harness#1288). Falsified by the agent-harness#1282 falsifier: a sealed command selected for a review seat.
- [ ] EC-JAILCORE-3 — The host proxy serves per-provider allowlists under IF-0-JAILCORE-2, with Gemini as the first. A profile without its allowlist is degraded, never unconfined. Falsified by a jailed seat reaching an unlisted host.
- [ ] EC-JAILCORE-4 — Dependency projection works for any registered profile, and qualification passes are keyed by profile digest and falsifier layout (agent-harness#1287). Falsified by a pass carried across digests.

**Scope notes**
- Decompose into 3 lanes. **Lane A** owns the registry, the resolver and IF-0-JAILCORE-1.
  **Lane B** owns proxy generalisation and IF-0-JAILCORE-2. **Lane C** owns projection
  wiring and the qualification key.
- Lane A publishes IF-0-JAILCORE-1 first. `seat_jail.py` is single-writer to Lane A; lanes
  B and C edit their own modules.
- Deliver agent-harness#1704 acceptance item 3 (the fallback ladder expressed through the
  interface), for seats only.

**Governance**
- Principle 2. EC-JAILCORE-1 is checked by digest equality, so no requalification is needed.

**Non-goals**
- New vendor profiles (CODEX, GROK, PI). Package extraction.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`
- `phase-loop-runtime/src/phase_loop_runtime/sandbox_egress.py`
- `phase-loop-runtime/src/phase_loop_runtime/executable_dependency.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`

**Depends on**
- INVENTORY

**Produces**
- IF-0-JAILCORE-1
- IF-0-JAILCORE-2

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: `advisor_board/CONTRACTS.md`; evidence paths: digest-equality receipts; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 4 — Team-Host Binds and Tooling Paths (TEAMHOST)

**Objective**
Make jailed seats work on shared team hosts under several operator accounts.

**Exit criteria**
- [ ] EC-TEAMHOST-1 — Seats resolve the managed tooling release through declared projections, not ambient binds. Auth probes pass with the operator's scratch dir under a search-only workspace (the rest of agent-harness#1413). Falsified by a probe raising before the CLI runs.
- [ ] EC-TEAMHOST-2 — The namespace resolver is readable by the subordinate seat uid under a private umask (salvaged from agent-harness#1623). Two operator accounts run concurrent seats without shared-resource collisions (agent-harness#1108). Falsified by a DNS failure or a cross-account collision.
- [ ] EC-TEAMHOST-3 — The managed runtime carries the qualification dependencies, and fix text is one sentence with a managed-deployment branch (agent-harness#1357, agent-harness#1399). `phase-loop doctor` reports `seat_jail_prerequisites[]` truthfully, including on non-Linux hosts (agent-harness#1398, agent-harness#1479).
- [ ] EC-TEAMHOST-4 — A host-admin checklist (LA-1) lists every root action with print-only scripts that are never run by the runtime.

**Scope notes**
- Decompose into 3 lanes. **Lane A** owns bind and projection paths. **Lane B** owns
  resolver readability and multi-account isolation. **Lane C** owns doctor, prerequisites,
  fix text and the checklist.

**Governance**
- Principle 2. LA-1 is an owner/admin action and is not required to land code.

**Non-goals**
- Changing host policy automatically.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/sandbox_egress.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail_prerequisites.py`
- `phase-loop-runtime/src/phase_loop_runtime/doctor.py`
- `docs/TEAM-ONBOARDING.md`

**Depends on**
- INVENTORY

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: `docs/TEAM-ONBOARDING.md`, the capabilities card; evidence paths: team-host provider-free receipts; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 5 — Codex Seat in the Jail (CODEX)

**Objective**
Run the Codex seat inside its per-seat jail, with the jail as its only boundary
(agent-harness#1480).

**Exit criteria**
- [ ] EC-CODEX-1 — A registered Codex profile runs the codex CLI on the staged tree with its own sandbox off inside the jail (OD-4) and full tools. The mode line reads `jailed`. Falsified by a nested namespace attempt, or by `seat_filesystem_unconfined` on a capable host.
- [ ] EC-CODEX-2 — The codex launcher and its native image are projected (agent-harness#1774), and its credential is delivered the way the jail delivers Claude's. A "Not logged in" probe is not treated as logged in (agent-harness#1528).
- [ ] EC-CODEX-3 — Codex egress uses its measured allowlist under IF-0-JAILCORE-2 (agent-harness#1653).
- [ ] EC-CODEX-4 — A provider-free qualification passes on a team host where agent-harness#1335 reproduces, and the row reads `candidate`. Otherwise OD-9 records can't-hold and routes the row to REMOTE.

**Scope notes**
- Decompose into 3 lanes. **Lane A** owns profile and argv. **Lane B** owns projection and
  credential delivery. **Lane C** owns allowlist measurement and probes
  (agent-harness#1472).
- Expected to close agent-harness#1335, agent-harness#1003 and agent-harness#941.

**Governance**
- Principle 2. OD-4 is required before lane A lands.

**Non-goals**
- AppArmor nesting policy (agent-harness#1644, agent-harness#1731).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/executor_availability.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`

**Depends on**
- JAILCORE

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the capabilities card, `advisor_board/CONTRACTS.md`; evidence paths: provider-free receipts, allowlist probe rows; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 6 — Grok Seat in the Jail (GROK)

**Objective**
Run the Grok seat jailed, with a writable disposable tree and provider-only egress.

**Exit criteria**
- [ ] EC-GROK-1 — A registered Grok profile runs grok on a writable disposable clone. A probe write lands in the clone and nowhere else (agent-harness#1686). The `--cwd` path resolves inside the seat (agent-harness#1460).
- [ ] EC-GROK-2 — Headless tool approval does not cancel turns (agent-harness#1091). A tool-definition probe fails on any tool outside the allow-list (agent-harness#1653).
- [ ] EC-GROK-3 — Grok egress uses its measured allowlist under IF-0-JAILCORE-2.
- [ ] EC-GROK-4 — The row reads `candidate` after a provider-free team-host qualification, or OD-9 routes it to REMOTE.

**Scope notes**
- Decompose into 2 lanes. **Lane A** owns profile, tree and argv. **Lane B** owns allowlist
  measurement and the tool-definition probe.

**Governance**
- Principle 2.

**Non-goals**
- Grok API-key lanes.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`

**Depends on**
- JAILCORE

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the capabilities card; evidence paths: write-confinement probe, provider-free receipts; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 7 — Pi Seat (PI)

**Objective**
Add Pi as a jailed review-seat vendor that reaches its routed models (such as DeepSeek) only
through its declared provider.

**Exit criteria**
- [ ] EC-PI-1 — `pi` is a panel leg on the homebrew backing, with a headless structured-output invocation and the board's verdict contract. Falsified by a Pi seat that only resolves through the omnigent gateway.
- [ ] EC-PI-2 — A registered Pi profile projects the Pi runtime and packages (agent-harness#1782) and runs with full tools in the jail.
- [ ] EC-PI-3 — OD-5 is implemented: the credential lane, egress confined to the routed provider's allowlist, and vendor-family projection for distinct-vendor counting. Falsified by a Pi seat counted as the wrong vendor, or reaching another provider.
- [ ] EC-PI-4 — The row reads `candidate`, or OD-9 routes it to REMOTE.

**Scope notes**
- Decompose into 3 lanes. **Lane A** owns the leg and verdict parsing. **Lane B** owns the
  profile and projection. **Lane C** owns credential, egress and vendor identity
  (`advisor_board/schema.py`).

**Governance**
- Principle 2. OD-5 is required before lane C lands.

**Non-goals**
- Pi as an executor (existing runner route). Omnigent backing changes.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/registries.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/schema.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`

**Depends on**
- JAILCORE

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the capabilities card model × harness matrix, `advisor_board/CONTRACTS.md`; evidence paths: provider-free receipts; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 8 — Claude TUI as Last Fallback (CLAUDETUI)

**Objective**
Settle the jailed TUI as the last Claude fallback: repaired, or retired to a typed degraded
route.

**Exit criteria**
- [ ] EC-CLAUDETUI-1 — The agent-harness#1461 cause is diagnosed with retained private startup evidence (salvaged from agent-harness#1641), plus the PTY and banner fixes (salvaged from agent-harness#1623).
- [ ] EC-CLAUDETUI-2 — OD-6 is recorded. Either the jailed TUI returns admitted canonical output in W2, or `tui` on the jailed seat yields a typed degraded notice. Falsified by a TUI run reported OK with missing canonical output.

**Scope notes**
- Decompose into 2 lanes. **Lane A** owns diagnosis and repair. **Lane B** owns the degraded
  path and its notice.

**Governance**
- Principle 2. Starts only after CLAUDE, per the owner's order.

**Non-goals**
- Changing the default (CLAUDE owns it).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`

**Depends on**
- CLAUDE

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the capabilities card; evidence paths: startup evidence by digest; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 9 — Qualification Window 1 (QUALIFY1)

**Objective**
Build the batched qualification kit and live-qualify Claude and Gemini in one owner window.

**Exit criteria**
- [ ] EC-QUALIFY1-1 — One command qualifies every candidate row on a host and writes IF-0-QUALIFY1-1 records. Falsified by a vendor that needs its own procedure.
- [ ] EC-QUALIFY1-2 — In W1 the Claude row (on its OD-3b default) and the Gemini row meet the principle 1 DoD and read `done-local`, each with an evidence digest.

**Scope notes**
- Decompose into 2 lanes. **Lane A** owns the kit and record schema. **Lane B** owns window
  preparation, the matrix update and evidence.
- Operational evidence goes into the window record. The digest enters the matrix through a
  reviewed PR. Proxy evidence never stands in for a window.

**Governance**
- Principle 2 for the kit. W1 is owner action LA-2 and LA-3.

**Non-goals**
- Codex, Grok and Pi (QUALIFY2).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `docs/review-seats-readiness.md`

**Depends on**
- CLAUDE
- GEMINI
- TEAMHOST

**Produces**
- IF-0-QUALIFY1-1

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: `docs/review-seats-readiness.md`; evidence paths: `plans/evidence/seat-qualification/`; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 10 — Qualification Window 2 (QUALIFY2)

**Objective**
Live-qualify Codex, Grok, Pi and the settled TUI fallback in one owner window.

**Exit criteria**
- [ ] EC-QUALIFY2-1 — In W2 every row that is `candidate` reads `done-local`, with its evidence digest. Rows routed by OD-9 read `remote-pending`.
- [ ] EC-QUALIFY2-2 — The OD-6 outcome is checked live in W2.

**Scope notes**
- Single lane: one owner window, run with the QUALIFY1 kit.

**Governance**
- Principle 2 for the matrix PR. W2 is owner action LA-2 and LA-3.

**Non-goals**
- Remote rows (REMOTE).

**Key files**
- `docs/review-seats-readiness.md`

**Depends on**
- QUALIFY1
- CODEX
- GROK
- PI
- CLAUDETUI

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: `docs/review-seats-readiness.md`; evidence paths: `plans/evidence/seat-qualification/`; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 11 — Remote Review-Runner with Provider Egress (REMOTE)

**Objective**
Give any vendor the local jail cannot hold, and any host without jail prerequisites, a
remote sandbox seat with provider-only egress, behind security review and owner activation.

**Exit criteria**
- [ ] EC-REMOTE-1 — A new `policies.json` vector (IF-0-REMOTE-1) adds per-provider egress for the review-runner image, from IF-0-JAILCORE-2 allowlists. It stays `pending_qualification`, and `full-remote-pi-runner` is unchanged. Falsified by a changed existing vector digest.
- [ ] EC-REMOTE-2 — Credential projection carries only expiring subscription tokens, in the sealed worker envelope. The renewal token never leaves the launching host. Placement contract C5 is amended for provider egress under OD-7.
- [ ] EC-REMOTE-3 — A security review of credential and egress (threat model, falsifiers, method denials) is recorded and approved under OD-7. Weaknesses are reported privately.
- [ ] EC-REMOTE-4 — The remote rung is the resolver's step 2, disabled until activation, and refuses unwired dependency routes (agent-harness#1787).
- [ ] EC-REMOTE-5 — After Stage 2 activation (LA-4), the owner activates the rung, and every row the matrix routes remote reads `done-remote` from the activation window.

**Scope notes**
- Decompose into 4 lanes: **lane A** vector and contract amendment, **lane B** credential
  projection, **lane C** security-review packet, **lane D** resolver integration.
- Lanes A–D run offline now. EC-REMOTE-5 waits on Stage 2 activation (the owner's gateway
  qualification and ai-stack Unit 7). The remote window is batched with that
  qualification.

**Governance**
- Principle 2.
- OD-7 is needed twice: design approval before lanes A and B land, and activation before
  EC-REMOTE-5.
- Security review is required.

**Non-goals**
- Stage 2 transport and deployment. E2B. SSH backends.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/policies.json`
- `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/policy-digests.json`
- `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py`
- `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml`
- `phase-loop-runtime/images/review-runner/Containerfile`

**Depends on**
- JAILCORE

**Produces**
- IF-0-REMOTE-1

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: placement contract C5, `contracts/placement/README.md`; evidence paths: the security-review record and activation-window records; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 12 — Closeout (CLOSEOUT)

**Objective**
Remove the sealed paths, settle the matrix and close the umbrella issues.

**Exit criteria**
- [ ] EC-CLOSEOUT-1 — Under OD-8, review-seat defaults contain no sealed route, and the president's sealed last resort is removed (agent-harness#1250). Falsified by any reachable sealed review command.
- [ ] EC-CLOSEOUT-2 — Every matrix row reads `done-local` or `done-remote`, and the capabilities card matches the matrix.
- [ ] EC-CLOSEOUT-3 — agent-harness#1244, agent-harness#1132 and agent-harness#1288 close, citing the matrix. The roadmap status is recorded under OD-1's choice.

**Scope notes**
- Decompose into 2 lanes. **Lane A** owns sealed-route removal. **Lane B** owns docs, the
  matrix and issue closure.

**Governance**
- Principle 2. OD-8 is required.

**Non-goals**
- Per-OS jails.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `docs/advisor-board-capabilities-card.md`
- `docs/review-seats-readiness.md`

**Depends on**
- QUALIFY2
- REMOTE

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the capabilities card, `advisor_board/CONTRACTS.md`; evidence paths: the final matrix; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

## Phase Dependency DAG

```
  INVENTORY ─┬─► CLAUDE ──┬─► CLAUDETUI ─────────────────┐
             │            └──────────────┐               │
             ├─► GEMINI ─────────────────┼─► QUALIFY1 ─┐ │
             ├─► TEAMHOST ───────────────┘             ▼ ▼
             └─► JAILCORE ─┬─► CODEX ─┐              QUALIFY2 ─┐
                           ├─► GROK  ─┼──────────────►         ├─► CLOSEOUT
                           ├─► PI    ─┘                        │
                           └─► REMOTE ··· (Stage 2 activation) ┘

  Edges: INVENTORY → CLAUDE, GEMINI, TEAMHOST, JAILCORE
         CLAUDE → CLAUDETUI;  CLAUDE + GEMINI + TEAMHOST → QUALIFY1
         JAILCORE → CODEX, GROK, PI, REMOTE
         QUALIFY1 + CODEX + GROK + PI + CLAUDETUI → QUALIFY2
         QUALIFY2 + REMOTE → CLOSEOUT
  Parallel: CLAUDE ‖ GEMINI ‖ TEAMHOST ‖ JAILCORE;  CODEX ‖ GROK ‖ PI ‖ REMOTE (offline lanes)
```

---

## Execution Notes

- **Planning.** After OD-1, plan INVENTORY. Then CLAUDE, GEMINI, TEAMHOST and JAILCORE can be
  planned concurrently, and after JAILCORE, CODEX, GROK, PI and REMOTE. The downstream plan
  budget is 2000 + 500 per lane (`docs/phase-loop/plan-budget.md`).
- **Critical path.** INVENTORY → JAILCORE → CODEX/GROK/PI → QUALIFY2 → CLOSEOUT. REMOTE
  activation is an external gate on CLOSEOUT.
- **Owner windows.** W0 (CLAUDE bake-off), W1 (QUALIFY1), W2 (QUALIFY2), plus the remote
  activation window. That is four windows in total, not one per fix.
- **Single writers across phases.**
  - `seat_jail.py`: CLAUDE edits only the Claude environment; JAILCORE lane A owns the
    structure. Whichever lands second rebases.
  - `panel_invoker.py`: v11 PANELSPLIT may split it. Seat phases rebase onto the split
    rather than block it, and edit the seat-launch, broker or leg modules it names.
  - `docs/review-seats-readiness.md`: INVENTORY, then each QUALIFY phase, then CLOSEOUT.
- **Cross-roadmap ownership.** §4a item 8 gives the jailed-default promotion to v11 PANEL.
  OD-3a moves that promotion into CLAUDE; nothing else moves out of PANEL.

---

## Acceptance Criteria

- [ ] Every vendor (Claude, Gemini, Codex, Grok, Pi) meets principle 1 locally or remotely, with evidence digests in the matrix.
- [ ] No review seat can reach a sealed or toolless route.
- [ ] The jailed Claude default equals OD-3b, which cites W0 evidence; TUI is last.
- [ ] Remote provider egress was activated only after OD-7 and Stage 2 activation.

---

## Verification

```bash
# roadmap structure
phase-loop validate-roadmap specs/seats-roadmap-v1.md
# registry coherence, unchanged or as OD-1 sets it
phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-v11.md
# per host, each operator account
phase-loop seat-sandbox qualify
phase-loop seat-egress status
phase-loop doctor --json
# a production board: every seat_modes entry is `jailed` (or remote), none sealed
phase-loop advisor-board <bundle> --json
# matrix rows, window records and vectors reviewed on the closeout PR
```
