# Sandboxed Review Seats — Phase Roadmap (seats v1)

> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v11.md` (2026-11-04)
>
> **ADVISORY ONLY. Line 3 is parser grammar, not a fact: nothing here is absorbed into v11,
> runner-selected or delivered.** The registry accepts only `active`, `delivered` and
> `superseded`, so line 3 encodes non-selection only (the interim pattern of
> agent-harness#1819). v11 remains the active, selected roadmap (OD-1, 2026-11-04).
> **Temporary workaround:** when the `advisory` registry status lands (agent-harness#1824),
> switch this registry entry and line 3 to it in one commit. Nothing here waits on it.
>
> How to use: plan a phase with `/claude-plan-phase specs/phase-plans-seats-v1.md <ALIAS>`;
> plans are `plans/phase-plan-seats-v1-<ALIAS>.md`. The runner refuses a non-active roadmap,
> so lanes land as governed PRs (principle 2), not by runner dispatch. Completion is recorded
> in the readiness matrix and the landed PRs, not by ticking boxes.

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
5. **No single roadmap.** A keyword search for seats, jails and sandboxes returns hundreds
   of open issues, with no shared definition of done.

On 2026-11-04 the native board on a team host returned no review from any vendor, and it
reviewed nothing at all when its composition was refused (agent-harness#1729), when its
president hung (agent-harness#1822), and when degraded legs left no evidence of why
(agent-harness#1821, agent-harness#1823). The governance board is part of the problem, so
this roadmap owns those failures.

**Thesis.** The first phase is one live, jailed, tool-using seat on a team host, together
with a native board that always terminates. Gemini is already jailed, so it goes first and
waits on nothing else. The Claude bake-off and the records work start the same day as
separate roots. The jail registry, the other vendors and the remote fallback follow. Live
qualification runs in batched owner windows, and each vendor qualifies in the first window
after its own phase is ready.

**Binding owner decisions (2026-11-04).**

- **Both routes, every vendor.** Claude, Gemini, Codex, Grok and Pi (Pi reaches models such
  as DeepSeek) each get a local per-seat jail with tools on our hosts, team hosts included.
  Any vendor the local jail cannot hold gets an OpenShell review-runner with provider egress
  and credential projection, behind its own security review and owner approval.
- **The Claude transport is chosen by bake-off.** The `ClaudeTransport` seam
  (`tui | print | sdk`) carries both `print` and `sdk`. A live bake-off compares them, with
  T3 Code's SDK route as the control, and the owner picks the default from its evidence.
  The TUI is the last fallback, and all TUI repair comes after the default is chosen.
- **Qualification runs in batched owner windows.**
- **No review seat ever runs toolless.**
- **OD-1:** this roadmap is registered as advisory (non-active). v11 stays active and
  selected. No runtime change.
- **OD-10:** reviews never stall. The T3 fallback applies even after a security or
  containment refusal, which is reported privately, never as a public issue (principle 2).
- **Capacity offload:** owner-controlled targets may take a review seat for capacity only
  after the local route passes every non-capacity check, an explicit private host policy
  matches vendor and host class, and one current generic egress-and-credential probe receipt
  binds the target. Packaged policy contains no grants. Per-vendor OD-7 activation is required
  only for third-party targets.

**Readiness snapshot (input, origin/main at the External Inputs baseline).** FIRSTSEAT
turns this into the maintained matrix (IF-0-FIRSTSEAT-1).

| Vendor | Local route today | Main blockers | Remote |
|---|---|---|---|
| Claude | Jailed, TUI only; auto-qualifies on first use | TUI returns no canonical output live (agent-harness#1461). Jailed print exists only as a conflicting draft (agent-harness#1740). `sdk` is refused for panel seats. Egress uses the shared public-internet policy; there is no Claude allowlist or proxy. Login-proof parity (agent-harness#1532). | No route |
| Gemini | Jailed with tools and an egress proxy (agent-harness#1555) | Not live-qualified on team hosts. On 2026-11-04 the team-host board ended it on `gemini_heartbeat_capability_unavailable`, stored as `unknown failure`. Board follow-ups (agent-harness#1706). Qualification lost on upgrade (agent-harness#1420). Partial-clone staging (agent-harness#1419). | No route |
| Codex | Unconfined, inside its own bwrap | Inner bwrap denied by AppArmor on team hosts (agent-harness#1335, agent-harness#1003); `seat_tool_sandbox_unavailable` on 2026-11-04. Jail route proposed (agent-harness#1480). | No route |
| Grok | Unconfined, allow-listed tools (agent-harness#1652) | "Not signed in" stored as `unknown failure` (agent-harness#1821). The tool surface on the installed CLI is unverified (EC-FIRSTSEAT-4). Read-only tree (agent-harness#1686). `--cwd` recurrence (agent-harness#1460). Unconfined egress (agent-harness#1653). | No route |
| Pi | None. The board registry lists `pi` on omnigent backing only; not a panel leg. | No leg, profile, credential lane or egress allowlist. Vendor family is `pi`, not the routed model's vendor. No issue filed. | `full-remote-pi-runner` has no egress. The agent-harness client refuses the `pi-runner` workload. |
| Native board | Four seats and a president ladder per tier | Backfilled composition refused by the landing policy, with empty output (agent-harness#1729). A president rung silent for over 10 minutes, with no start-of-attempt record (agent-harness#1822). Degraded legs keep no argv or exit code (agent-harness#1823). | — |

---

## Architecture North Star

```
 brokered review seat (vendor V, staged tree)
        │
        ▼
 seat route resolver (JAILCORE): one decision, one typed code per failed step
        │   any code off the descend list ──► 4. degraded; nothing launches
        │   only the closed descend list descends on a failed local step; the separately gated
        │   `seat_local_capacity_exhausted` path may enter remote only under the capacity ruling
  1. local seat jail: profile[V] = tools + projection + per-seat provider-only egress
        │              + closed config surface + EC-EXECFIND-2 pass on this host
        │   Claude only: ClaudeTransport = default (owner bake-off) → other admitted → tui last
        │ host capability missing, or the matrix routes this row remote
  2. remote sandbox: OpenShell review-runner + per-provider vector + bounded credential
        │              (generic probe activation on owner-controlled targets; per-vendor OD-7 activation on
        │              third-party targets). Capacity use is only through JAILCORE's disabled-by-default gate.
        │ unavailable (typed code)
  3. native fill: labelled stand-in for V; the president is told
        │ unavailable
  4. degraded: typed code + fix line in the pre-launch mode line.
               Never sealed, never toolless, never silently unconfined.
```

---

## Assumptions (fail-loud if wrong)

1. The per-seat jail (`seat_jail.py`, `seat_uid.py`, the J7 route decision and EC-EXECFIND-2
   passes) is the local boundary for every vendor. A vendor whose CLI cannot run in it gets
   a recorded can't-hold determination (principle 6), not a parallel boundary.
2. Executable-dependency projection (agent-harness#1782) carries only closures supported
   by its selected-subject contract; it does not authorize a non-subject interpreter.
   Owner decision 2026-11-05 selects a dedicated host worker for the Agent SDK in CLAUDE,
   refining the host-SDK choice; G1 must explicitly ratify that refinement. Only `claude`
   is the jailed subject, with no interpreter projected, under EC-CLAUDE-3 and OD-3a.
3. Under a subscription login, `print` and `sdk` both draw on subscription limits. This is
   a dated external input (see External Inputs), not a guarantee. The bake-off checks it.
4. Stage 2 activation waits on the owner's live gateway qualification and ai-stack Unit 7.
   No local phase depends on it.
5. v11 remains the runner's selected roadmap. Its PANELSPLIT phase may move
   `panel_invoker.py` into a package at any point in this roadmap.
6. The phase-loop runner refuses a non-active roadmap (`NonActiveSelectionError`), so this
   roadmap's lanes land as governed PRs. If the owner later makes it runner-selected, that
   is a registry change, not a re-plan.

---

## External Inputs

All pins are inputs. None is an output of this roadmap.

| Input | Pin |
|---|---|
| Input baseline | origin/main at `c913e412151e81867cea667c8ee545fb17cb47e1`, fetched 2026-11-04 |
| Claude print-route decision record | `plans/decision-claude-print-subscription-route-20261008.md`, sha256 `14d424ad85fe97dcbaabc5df1f8d8beffc12a8eefdd2678694da19612fe59381`. §4a is the agent-harness#1775 record. Its item 7 requires a further ratified amendment before any jailed default changes, and its item 9 sets the current ratification order. |
| Claude SDK decision record (Stage 3) | `plans/decision-claude-sdk-subscription-route-20261015.md`, sha256 `544147229e0b2cc8ff44bfd761145dbe4cfe4f30e011d165fecd857bb8d0a2be` |
| Stage 2 plan (review-runner image, vectors) | `plans/detailed-openshell-coordinator-stage2-1795-20261102.md`, sha256 `ccd32c25047c2324ae2ab5c3a83b2daeb008c9b69b5b03fd19342a9b66653234` |
| Placement policy vectors (`pending_qualification`) | `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/policies.json`, sha256 `5b3bc7f515bd2a4cbc10a18d98465d511f65e8089213ceb8c21f9cce2409020f` |
| Remote placement contract (C5: empty `egress_needs` for non-local) | `plans/detailed-remote-seat-placement-896-20261010.md`, sha256 `28b15ad85e5ecbd6a600b6de7f3a0a5502da88122e8cdc314029ca0c37ffedac` |
| Dependency projection contract | `docs/executable-dependency-projection.md`, sha256 `c3e955fcdcae3d36dc59c60c293d84cb4df5df3fbcb6efdc3abe9e86ba1a8d9c` |
| Approved Gemini jail digest | `84d39a72`, as quoted in agent-harness#1706 (a profile digest, not a git object) |
| Claude billing statement | Anthropic Help Center article 15036540, as read 2026-11-04. Under a subscription login, the Agent SDK and `claude -p` draw on subscription limits. A 2026-05 plan to bill them at API rates was paused on 2026-06-15 "for now" and reaffirmed on 2026-10-07. Dated; may change. |

---

## Non-Goals

- macOS Seatbelt and Windows AppContainer/WSL jails. Hosts without the Linux jail
  prerequisites use the remote rung. The per-OS jails stay tracked under agent-harness#1244.
- Extracting the sandbox code to its own package. Only the seat-side interface of
  agent-harness#1704 is in scope (JAILCORE).
- Stage 2 itself: transport, coordinator, image build and deployment. REMOTE amends Stage
  2's no-egress activation proof for provider egress; it does not build Stage 2.
- Solo-runner SDK rollout. It re-files on agent-harness#1391.
- **Weakening** advisor-board composition, seat floors or the president ladder. Making
  composition and president outcomes typed and bounded is in scope (agent-harness#1729,
  agent-harness#1822; FIRSTSEAT). Removing sealed paths is in scope (CLOSEOUT).
- Any automatic, silent fallback between Claude transports. Fallback is by selection or a
  typed, recorded step (decision record §2).
- The `opencode` and `cursor` board legs. Seats v1 covers the five named vendors. This is
  not an exemption: with no profile, those legs resolve degraded (EC-JAILCORE-5).
- API-key credential lanes for any seat, except what OD-5 sets for Pi and what OD-7 approves
  per vendor on the remote rung.
- agent-harness#1781 (verification retention and signed historical custody). It is
  unrelated to seats, and this roadmap claims no hold on it.
- The full agent-harness#1602 CLI-version lifecycle. It is owned outside this roadmap; the
  Gemini seat consumes its last-known-good pointer where one exists (EC-TEAMHOST-7).

---

## Cross-Cutting Principles

1. **Definition of done, per vendor row.** "This vendor's seat runs with tools, sandboxed, on
   our hosts, live-qualified" means all four of these:
   - **Jailed with tools.** A brokered seat given a staged tree resolves to `jailed` with
     its full tool set.
   - **Sandboxed.** The profile has a recorded EC-EXECFIND-2 pass on each qualifying host.
     Egress is confined to its own provider allowlist through a per-seat proxy. It holds only
     the capability its profile declares (EC-HARDEN-6), and its containment evidence is
     recorded (EC-JAILCORE-6).
   - **On our hosts.** At least one standard host, and one team host under two operator
     accounts. The matrix names host classes, never private hosts.
   - **Live-qualified.** An admitted canonical review in an owner window, on a released
     runtime, produced through the native board's seat-launch path. It carries a tool receipt
     proving a staged-tree read and the leg's exec record (IF-0-FIRSTSEAT-3). Other seats on
     that board may be degraded, but the board must terminate with a typed outcome. A direct
     seat harness, or a board run that bypasses the landing policy, is not a real board. The
     evidence digest goes into the matrix.

   A remote row means the same on the remote rung after target activation: a current generic
   egress-and-credential probe receipt on an owner-controlled target, or that vendor's OD-7
   record on a third-party target. A capacity-offload grant does not mark a local row
   `done-remote`. Row statuses are `not-started`, `candidate`, `done-local`,
   `remote-pending` and `done-remote`.
   `remote-pending` is an open deferral, not done.
2. **Governance, every phase.**
   - **Plan and implementation review.** The native agent-harness advisor board runs first.
     A T3 cross-vendor delegate replaces any failed native seat. If the native board fails as
     a whole, the T3 cross-vendor board is the landing board for that review. Whole-board
     failures include a composition that exits with empty output (agent-harness#1729), a
     hung president (agent-harness#1822) or no admitted seat. Under OD-10 this holds even
     when a seat ended on a security or containment code, so reviews never stall. A T3
     landing board records its vendors, author independence and the president's stand-in.
     No phase needs a working native board for its own reviews. Until EC-FIRSTSEAT-1 to
     EC-FIRSTSEAT-3 hold, expect the T3 board to be the landing board.
   - **Failure reporting (OD-10).** An ordinary failure (availability, auth, host capability,
     a hang) is filed, or commented on, as an issue in Consiliency/agent-harness. A security
     or containment failure, meaning any terminal code of EC-JAILCORE-2 that signals
     tampering, a token in output, excess token scope, unconfined egress, in-jail refresh or a failed
     install integrity check, or any failed containment probe, gets a private record and an owner summary and is never filed
     publicly. A correct, typed policy refusal (composition, independence or floor, as in
     EC-FIRSTSEAT-1 and EC-PI-5) also hands the review to the T3 board, but it is a policy
     outcome: board-failure metrics never count it as a failed board.
   - **Before landing.** The six required CI checks, a dispatched Gate A on the branch, and
     a cross-vendor board on the exact head.
   - **Review rounds.** Bounded per `docs/agent-phase-convergence.md` §8.
3. **Never toolless, never silently unconfined.** No phase adds or widens a sealed route.
   Each failed step yields one typed notice code with a fix line (closed vocabulary in
   `seat_jail.NOTICES`). No fix line recommends a removed route or an API-key lane. An
   unconfined seat, or a jailed seat without its allowlist, is allowed only as a named
   exception shown in the matrix with an expiry date. Only an owner record in the matrix
   renews it. An expired exception resolves degraded.
4. **Qualification-pinned files, one digest owner.** Treat `gemini_heartbeat.py`,
   `agy_qualification.py`, every jail profile builder and every egress allowlist as
   qualification-pinned. A change to any part of a row's qualification key (EC-JAILCORE-4)
   returns the row to `candidate`, and the change names the next batched window, where the
   row requalifies (the agent-harness#1804 pattern). Each digest has one owning phase at a
   time: Gemini in FIRSTSEAT, then TEAMHOST; Claude in CLAUDENET; Codex, Grok and Pi in their
   own phases. JAILCORE changes no digest.
5. **Batch live work.** The live windows are W1 (FIRSTSEAT), W0 (CLAUDE's bake-off), rolling
   row windows, and REMOTE's activation window. The owner runs a row window whenever any row
   is `candidate`. It qualifies every `candidate` row on its hosts with the IF-0-FIRSTSEAT-2
   kit, and it waits for no other row, phase or owner decision. A vendor phase exits
   through the first row window after its row is ready, so no window joins vendors. A
   window's records and matrix changes land through a reviewed PR, and proxy evidence never
   stands in for a window. Windows may share an owner session, but none waits for another.
   Measuring a request set on a developer host with the developer's own login is ordinary
   development work, not a window.
6. **Stall rule and can't-hold (OD-9).** A local vendor phase that needs a third plan
   amendment, or whose amendments outnumber its implementation PRs, stops. The owner then
   records a diagnosis or a can't-hold determination. A can't-hold determination:
   - cites a failed jail falsifier on a named host class, OD-3b's record that no transport was
     admitted, or an OD-4 rejection, never an amendment count alone;
   - is allowed only after the team-host work the row needs has landed (FIRSTSEAT lane A
     for Gemini, TEAMHOST for the others), with LA-1 done or recorded impossible on that host;
   - states the interim route: degraded by default, or an owner exception with an expiry
     (principle 3), never silently unconfined;
   - moves the row to `remote-pending`, an open deferral that REMOTE tracks. It does not
     hold up the local phases or local closeout.
7. **Plan discipline.** Pin inputs only. Downstream plans reference EC IDs and never
   restate them. No EC requires a SHA, a commit count or the ancestry of a commit this
   roadmap will create. Ordering is checked by content, for example the sha256 of a section
   on a landing's base tree. Detail goes into the frozen artifacts below.
8. **Public repo.** No secrets, private hosts or private paths in code, docs or evidence.
   Security weaknesses are reported privately (CONTRIBUTING.md).

---

## Owner Decisions and Live Owner Actions

**Decided.** The binding decisions above, including OD-1 and OD-10. Neither gates anything.

**Blocking, each for a narrow scope only.**

| ID | Decision | Blocks only | Recommended default |
|---|---|---|---|
| OD-3a | Ratify CLAUDE lane A's amendment to the print-route decision record. It makes `print` and `sdk` selectable for the jailed seat, authorises the bake-off and keeps TUI last. It moves the responsibilities in EC-CLAUDE-8 from v11 PANEL to this roadmap and sets the content-based order of EC-CLAUDE-4 in place of §4a item 9 for these landings, naming that departure from v11's EC-REVIEWTRUTH-15. It requires the token pipe for `sdk`. It lets a chosen default ship before its row window, provided the docs say so, including that it runs on open egress until CLAUDENET exits. | W0's `sdk` runs and any landing that activates `sdk` or changes the default | Ratify as drafted |
| OD-3b | Pick the jailed Claude default from W0 evidence, or record that no local transport was admitted | CLAUDE's exit | The transport that returned admitted canonical output on every W0 run and landed on subscription limits. If both did, `print`, which projects fewer dependencies. |
| OD-4 | Make the jail Codex's only boundary, with its inner sandbox off, superseding the nested-AppArmor route. This decision is informed by EC-CODEX-2, EC-CODEX-3 and EC-CODEX-5: the auth file is readable by tools, and tool commands inherit the seat's egress. If rejected, the Codex exception runs to its expiry and then resolves degraded, agent-harness#1644 and agent-harness#1731 reopen as CODEX input, and OD-9 may route the row remote. | CODEX lane A enabling the route | Accept, on the condition that EC-CODEX-2, EC-CODEX-3 and EC-CODEX-5 hold first |
| OD-5 | Pi's credential lane, provider narrowing, aggregator use, spend cap and board slot | PI lane C, and so the Pi leg's enablement | Use the provider-scoped credential the Pi executor already uses for its routed provider, with no aggregator and a spend cap if API-billed. Make no plan or production slot change in v1: Pi qualifies on a board that composes it explicitly, counted as its routed vendor. |
| OD-7 | Approve the remote design; on third-party targets, later activate each vendor and bind the digests EC-REMOTE-3 lists. Owner-controlled targets use the generic probe receipt. | REMOTE lanes A and B landing; each third-party vendor's activation | None. Security-gated by the binding decision. |
| OD-8 | Remove the sealed review routes and the president's sealed last resort (agent-harness#1250) | CLOSEOUT lanes A and B | Approve once the matrix's president rows meet EC-CLOSEOUT-4 and EC-FIRSTSEAT-2 holds |
| OD-11 | Whether `heartbeat_only` president rungs also get a no-output bound. That would reverse the operator's no-silence-kill policy (agent-harness#826, `advisor_board/CONTRACTS.md`, the capabilities card). | Any change to the `heartbeat_only` president path; not FIRSTSEAT's exit | DECIDED 2026-11-04: keep the policy. It is an explicit opt-in, agent-harness#1822 happened on `bounded`, and the start entry makes a wedged attempt visible. |

**Defaulted (these proceed unless the owner objects).**

| ID | Default |
|---|---|
| OD-2 | The corrected draft-PR disposition table in INVENTORY. Closures can be undone by reopening. |
| OD-6 | Repair the TUI if EC-CLAUDETUI-1's diagnosis finds a bounded fix; otherwise retire it to a typed degraded route. Only CLAUDETUI's exit waits on this. |

**Event-driven.** OD-9, any can't-hold determination, under the rules of principle 6.

**Live owner actions.**

| ID | Action | Phase |
|---|---|---|
| LA-1 | Host administration on each window host: subuid/subgid ranges, `legacy_tiocsti = 0`, the AppArmor `setpriv` override on Ubuntu 24.04+, and a managed release carrying the seat dependencies | FIRSTSEAT (its host), TEAMHOST (the checklist) |
| LA-2 | Vendor logins for each operator account on each window host | FIRSTSEAT, each vendor phase |
| LA-3 | Run W1, W0 and the row windows, and read the account usage meter for W0 | FIRSTSEAT, CLAUDE, each vendor phase |
| LA-4 | Stage 2 live gateway qualification, ai-stack Unit 7 and the remote activation window | REMOTE |

---

## Top Interface-Freeze Gates

1. **IF-0-FIRSTSEAT-1** — The readiness-matrix schema in `docs/review-seats-readiness.md`.
   Vendor rows carry: vendor, route, Claude transport, profile digest, allowlist id and
   allowlist content digest, tool surface, credential lane, projection, host classes,
   qualification record, live evidence digest, status (principle 1), any named exception
   with its expiry, renewal record and end condition, and the interim route. President-rung
   rows carry: rung, route as named in runtime source, tooled or sealed, bound, and host
   classes.
2. **IF-0-FIRSTSEAT-2** — The rolling-window protocol (principle 5) and window evidence
   record (`plans/evidence/seat-qualification/`, metadata only). One command qualifies every
   `candidate` row on a host.
3. **IF-0-FIRSTSEAT-3** — The per-leg exec record and post-launch auth classification:
   redacted argv, exit code, typed outcome code, auth classification and a size bound. It
   holds no secret in any encoding. On shared hosts it lives in per-operator private storage
   (mode 0600).
4. **IF-0-CLAUDE-1** — The jailed `ClaudeTransport` selector. Values `tui | print | sdk`.
   The default comes from one declared setting. Refused values are typed and never fall
   back.
5. **IF-0-CLAUDE-2** — The bake-off evidence record, one per run. Fields: transport, run
   id, `CLAUDE_CODE_ENTRYPOINT` value, canonical-output outcome, admission predicates,
   §4a item 7 check outcomes, billing landing
   (`subscription | extra_usage | api | unknown`), meter-observation reference, and the
   measured provider request set.
6. **IF-0-JAILCORE-1** — The leg-profile contract. A vendor registers one jail profile with
   these fields: argv builder, binds, environment, projection requirement, credential
   delivery (channel and measured scope), closed configuration surface, post-launch auth
   classifier, output secret refusal, containment evidence and notice codes. It also fixes
   the closed failure-descend list. The only failed local-step codes that may
   move to a later rung without the separate capacity gate are:
   `seat_sandbox_unavailable_host`, `seat_sandbox_unavailable_tiocsti`,
   `seat_sandbox_unavailable_seat_uid`, and the not-installed half of
   `gemini_seat_egress_unavailable` once EC-JAILCORE-2 splits it. Adding a code is a
   security change and needs a security review. The route resolver evaluates registered
   profiles without leg-specific branches.
7. **IF-0-JAILCORE-2** — The per-provider egress allowlist contract: allowlist id, content
   digest, measured request set and probe rows. One proxy process and token per seat, bound
   to one allowlist, with TLS terminated. The Gemini allowlist is its first instance.
8. **IF-0-REMOTE-1** — The per-provider review-runner vectors: one vector per provider, in
   their own vectors file with per-vector `pending_qualification`, plus a vector map keyed on
   leg and routed provider. Never a change to `full-remote-pi-runner`.
9. **IF-0-REMOTE-2** — The per-vendor remote credential table: shape, delivery channel,
   measured scope, maximum lifetime, in-sandbox refresh detection and revocation procedure.

---

## Phases

### Phase 0 — First Live Seat and a Terminating Board (FIRSTSEAT)

**Objective**
Get one jailed, tool-using seat (Gemini, already jailed) to `done-local` on a team host, and
make a plan-tier native board on that host terminate with a typed outcome. Nothing else in
this roadmap gates it.

**Exit criteria**
- [ ] EC-FIRSTSEAT-1 — Composition (agent-harness#1729). Availability backfill yields one of two outcomes: a board the production landing policy admits, or a typed pre-launch refusal naming the unmet slot, with a fix line. It never exits with empty output. The typed refusal is recorded as a policy outcome, not a board failure (principle 2). The fix weakens no independence, usable-seat, president or floor requirement. Falsified by an offline replay of the 2026-11-04 plan-tier composition that ends any other way, by a negative replay in which a board missing any one required seat is admitted, or by any change to the policy's required seats.
- [ ] EC-FIRSTSEAT-2 — President bound (agent-harness#1822). Each president rung writes a ledger entry when its attempt starts, on every path. On `bounded` monitoring, the route agent-harness#1822 hit, a no-output bound ends a silent rung in a typed timeout, and the board then advances the ladder or returns typed. `heartbeat_only` keeps its documented no-silence-kill contract unless OD-11 changes it. Falsified by a stub rung on `bounded` monitoring that emits nothing and is not ended typed within its bound, or by an attempt on any path with no start entry.
- [ ] EC-FIRSTSEAT-3 — Leg evidence (agent-harness#1823, agent-harness#1821). Under IF-0-FIRSTSEAT-3, every seat leg writes a bounded, redacted exec record, degraded or not. A post-launch auth classifier types each existing leg's not-signed-in or unavailable failure with a fix line, never `unknown failure`. It classifies only a non-zero exit with no model turn and no verdict, using host-side auth state where one exists. That covers Grok's "Not signed in" and Gemini's `gemini_heartbeat_capability_unavailable`. Grok's fix line does not recommend `XAI_API_KEY`. Falsified by an untyped leg failure, a degraded leg with no exec record, a planted token found in a record in any `contains_secret` encoding, or planted auth text in a reviewed tree that changes a seat's outcome.
- [ ] EC-FIRSTSEAT-4 — Grok tool surface. The tool-definition probe runs against each installed grok CLI version. A confirmed out-of-list tool is reported privately before any record lands, and the Grok leg resolves DEGRADED with a typed code until EC-GROK-2 passes. An inconclusive probe, or a CLI version not yet probed, also resolves DEGRADED until that version passes. The offered tool set is then recorded as metadata. Falsified by a leg that launches on a CLI version without a passing probe.
- [ ] EC-FIRSTSEAT-5 — Gemini on a team host. The jailed Gemini seat resolves `jailed`, not the heartbeat route, on the window team host. `phase-loop seat-sandbox qualify` and the Gemini egress install pass provider-free there. Staging works from a partial-clone checkout (agent-harness#1419). The namespace resolver is readable by the seat uid under a private umask (salvaged from agent-harness#1623). Falsified by a DNS failure or a heartbeat-route resolution on that host.
- [ ] EC-FIRSTSEAT-6 — Matrix and kit. `docs/review-seats-readiness.md` holds the IF-0-FIRSTSEAT-1 schema with rows for each vendor (Claude, Gemini, Codex, Grok, Pi), each remote route and each president rung, every status supported by its evidence. Codex and Grok carry their named unconfined exceptions, and Claude its open-egress exception, each with an expiry (principle 3). One command qualifies every `candidate` row on a host and writes IF-0-FIRSTSEAT-2 records. Falsified by a missing row, a status its evidence does not support, or a vendor needing its own procedure.
- [ ] EC-FIRSTSEAT-7 — Window W1. On the team host, under two operator accounts (sequential runs suffice), and on one standard host, a plan-tier native board terminates with a typed outcome. On that board, the jailed Gemini seat returns an admitted canonical review with tools, a tool receipt proving a staged-tree read, egress through its allowlist proxy, and its exec record retained. The W1 record names any co-seat that ran unconfined. Gemini's containment evidence for these hosts is recorded: the existing measurements plus a planted-config check (EC-JAILCORE-6). The Gemini row then reads `done-local` with its evidence digest, and a later EC-JAILCORE-6 failure returns it to `candidate`. If the stall rule fires instead, OD-9 may route the row to `remote-pending` once lane A's work has landed, citing the failed falsifier, EC-FIRSTSEAT-5's or W1's (principle 6). The phase then exits with EC-FIRSTSEAT-1 to EC-FIRSTSEAT-4 and EC-FIRSTSEAT-6 met. Only the Gemini `done-local` evidence is waived, plus EC-FIRSTSEAT-5 when its falsifier is the one cited.

**Scope notes**
- Plan against current origin/main. Decompose into 5 lanes:
  - **Lane A** owns EC-FIRSTSEAT-5, the Gemini team-host path. It is the single writer of
    `seat_jail.py` and the Gemini route files in this phase. It may land the part of a
    TEAMHOST issue that the window host reproduces; the issue stays owned by its TEAMHOST EC.
  - **Lane B** owns EC-FIRSTSEAT-1, in `advisor_board/composition.py`.
  - **Lane C** owns EC-FIRSTSEAT-2, in `president_adapter.py`, and gives lane E the
    president-rung rows, naming each route as runtime source names it. The 1800 s deadline
    on the `bounded` path already exists. The no-output bound and the start entry are what
    is missing.
  - **Lane D** owns EC-FIRSTSEAT-3 and EC-FIRSTSEAT-4, and publishes IF-0-FIRSTSEAT-3 on
    day one. It is the single writer of `panel_invoker.py` in this phase; lanes B and C hand
    it their call-site changes.
  - **Lane E** owns EC-FIRSTSEAT-6 and EC-FIRSTSEAT-7, publishes IF-0-FIRSTSEAT-1 and
    IF-0-FIRSTSEAT-2 on day one, and prepares W1.
- Any Gemini profile-digest change made here is qualified in W1 (principle 4).
- agent-harness#1729, agent-harness#1821, agent-harness#1822 and agent-harness#1823 close
  when their ECs hold, not at CLOSEOUT.

**Governance**
- Principle 2. This phase repairs the native board, so expect the T3 board to land its PRs.
- W1 is owner action LA-1 (window host), LA-2 and LA-3.

**Non-goals**
- New vendor profiles. Changing composition tiers, seat floors or the ladder; these fixes
  only make outcomes typed and bounded. The Gemini heartbeat route with dependency
  projections (unsupported per agent-harness#1782).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`
- `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`
- `phase-loop-runtime/src/phase_loop_runtime/review_stage.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `docs/review-seats-readiness.md`

**Depends on**
- (none)

**Produces**
- IF-0-FIRSTSEAT-1
- IF-0-FIRSTSEAT-2
- IF-0-FIRSTSEAT-3

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: `docs/review-seats-readiness.md`, `advisor_board/CONTRACTS.md`, the capabilities card; evidence paths: W1 records under `plans/evidence/seat-qualification/`, the composition replay and president stub receipts; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 1 — Claude Seat Transports and Bake-off (CLAUDE)

**Objective**
Give the jailed Claude seat the `ClaudeTransport` seam with both `print` and `sdk`, run the
bake-off and record the owner's default, with TUI as the last fallback. This phase changes
no jail profile digest; CLAUDENET owns the Claude digest.

**Exit criteria**
- [ ] EC-CLAUDE-1 — The jailed seat reads the IF-0-CLAUDE-1 selector. `print`, `sdk` and `tui` each launch the Claude CLI inside the same jail, staged clone, tool set and teardown. The `sdk` client/control code runs in a dedicated unprivileged host subprocess through an owned transport; its only CLI/protocol differences are the frozen EC-CLAUDE-3 delta. A refused value launches nothing. Falsified by a transport that widens the tools, binds, environment, descriptors or credential delivery, that changes the jail profile digest, or that falls back silently.
- [ ] EC-CLAUDE-2 — `print` runs `claude -p --output-format stream-json` in the jail under §4a items 4 and 5 of the print-route decision record, as amended by OD-3a. The jailed print diff of agent-harness#1740 is mined onto current main, and agent-harness#1740 is closed citing the PR that carries it. Falsified by an admitted result that breaks an item 4 or item 5 rule.
- [ ] EC-CLAUDE-3 — `sdk` runs Agent SDK 0.2.167 in a dedicated, credential-free, unprivileged host subprocess, separate from the trusted board parent. Only the selected system `claude` runs in the existing jail. No interpreter or SDK dependency is projected. Genuine Claude-subject projections still obey agent-harness#1782, including required dependency sessions. Salvage agent-harness#1744's seat-neutral adapter, package pins and Gate A fix; complete its disposition before closure. Before activation (GL-2), the offline proof below must pass under ratified OD-3a (G1).
  - **Frozen contract.** `plans/seats-claude-sdk-worker-contract.md`, sha256 `204d4ab83c7c1b9c0328a99e6934ee121d6e8269307d4547c1f6d5949481599d`, is normative for the worker sandbox, IPC/admission, install resources, proof bindings, continuous audit and OD-10 failure classes. Its generic falsifiers are required before GL-2; failed or absent proof leaves SDK unadmitted. G1 explicitly ratifies the dedicated host worker and this contract, not an in-parent SDK. Contract changes require renewed proof and authority under EC-CLAUDE-4.
- [ ] EC-CLAUDE-4 — Ratification order, by content. A landing is the merge into `main`, and its base tree is `main`'s tip just before that merge. A landing that activates `sdk` or changes the jailed default does not edit the decision record. Its base tree already holds the ratified amendment, and the landing cites the record path, the sha256 of that amendment section and the merged PR that landed the section, whose merge state an auditor reads. The OD-3b value lands in its own reviewed PR before the change that ships it, and every later switch does the same. This roadmap adds no SHA or ancestry requirement. Falsified by a landing that edits the record and the default together, a landing whose base lacks the cited section, or one PR that carries both the record and the switch, in any merge mode.
- [ ] EC-CLAUDE-5 — Bake-off window W0 records one IF-0-CLAUDE-2 record per run, for a run count fixed in the phase plan before the window. It covers `print`, `sdk` and the control: T3 Code's SDK route, known to be billed to the subscription. Each record measures (a) whether canonical output actually came back (the agent-harness#1461 failure mode), (b) where billing landed, against the owner's account usage meter, (c) the §4a item 7 qualification checks on the W0 head, and (d) the provider request set, which feeds CLAUDENET. Each also records observed `CLAUDE_CODE_ENTRYPOINT` (including `unset`), SDK execution location/version and package provenance where applicable, and measured launch-boundary differences. A native SDK capture twin uses the same dedicated worker, provenance preflight, parent forwarding/admission gate, outbound allowlist and frozen delta; a print twin relabeled SDK is invalid. The twin is the sole named exception to the jailed CLI launch path: a parent-owned developer-host capture launcher supplies only the declared path/home/proxy/CA delta and token pipe. Its output is admission-checked before discard, never used as a board result. Kit preflight checks `is_admitted("sdk")`, ratified G1 and a current GL-2 receipt before the first meter reading, credential resolution or twin launch, and the twin entry point repeats the check. Pre-GL-2 SDK twin execution is limited to the synthetic offline VB fixture; no live SDK twin can run. VB covers that path and proves unadmitted/stale inputs launch nothing. Record no projection when absent, or the real Claude-subject projection digest when used. Falsified by a run without its observed boundary metadata, meter observation or item 7 outcome; T3 parity is measured, never inferred from topology.
- [ ] EC-CLAUDE-6 — OD-3b is recorded in the decision record, citing W0's evidence digest. It is either a default among the admitted transports, or a record that none was admitted. In the second case the Claude row stays typed-degraded on the jailed seat until CLAUDENET records OD-9 (EC-CLAUDENET-4). When a default is chosen, the shipped setting equals it, and the capabilities card says the default is chosen, runs on open egress until CLAUDENET exits, and awaits its row window. A later switch changes the setting and the record only, in the EC-CLAUDE-4 order, and returns the row to `candidate`. Falsified by a default that disagrees with the record.
- [ ] EC-CLAUDE-7 — The jailed route holds the same login proof as the print and TUI routes (agent-harness#1532). A timed-out login wait republishes the seat mode (agent-harness#1255).
- [ ] EC-CLAUDE-8 — Ownership transfer. The OD-3a amendment names each responsibility it moves from v11 PANEL to this roadmap: the jailed transport seam (CLAUDE), jailed-seat live qualification (CLAUDENET) and jailed-default promotion (CLAUDE). PANELSPLIT's mechanical module extraction stays in v11. A v11 roadmap amendment marks the affected EC-PANEL-6 items as consumed from these EC IDs and notes OD-3a's departure from EC-REVIEWTRUTH-15. Falsified by a responsibility with two owners or none.

**Scope notes**
- Decompose into 4 lanes:
  - **Lane A** owns the selector, the default setting, the decision-record amendment and the
    v11 amendment. It publishes IF-0-CLAUDE-1 on day one.
  - **Lane B** owns `print`, mined from agent-harness#1740 onto current main. It does not
    start from that branch.
  - **Lane C** owns the host `sdk` adapter, owned transport and EC-CLAUDE-3 proof.
  - **Lane D** owns IF-0-CLAUDE-2, the bake-off recorder, and EC-CLAUDE-7.
  - Lane B owns the shared parsed-admission interface and preserves print behavior; lane C consumes it after lane B, with disjoint modules otherwise, against lane A's freeze.
- Until OD-3b, the shipped default stays as §4a sets it (the TUI). Operators may select
  `print` explicitly, or `sdk` once OD-3a is ratified and EC-CLAUDE-3's proof passes, as the agent-harness#1461 workaround.
- A transport whose W0 runs land on extra usage or API billing ranks behind one that lands
  on subscription limits; OD-3b still decides.
- Single writers: lane A alone edits the decision record. The seat-launch module of
  `panel_invoker.py` (or its PANELSPLIT successor) is edited only by lane A at the selector call site and
  the owned duplex I/O primitive and worker launcher (existing `seat_uid`/seat-owner primitives) needed by lane C. No lane edits a
  jail profile builder.
- W0 may share an owner session with W1. Neither waits for the other.
- Absorbs agent-harness#1391 (jailed scope), agent-harness#1422, agent-harness#1494,
  agent-harness#1254, agent-harness#1531, agent-harness#1585 and agent-harness#1682.

**Governance**
- Principle 2.
- OD-3a must be ratified before W0's `sdk` runs and before any landing that activates `sdk`
  or changes the default. G1 includes the dedicated host-process design and EC-CLAUDE-3 proof gate;
  GL-2 additionally requires its passing offline receipt before activation.
- OD-3b is required to exit. W0 is owner action LA-3.

**Non-goals**
- TUI repair (CLAUDETUI). Claude egress and `DISABLE_UPDATES` (CLAUDENET). Remote Claude
  (REMOTE). Capture and research seats stay as §4a item 1 sets them.

**Key files**
- `plans/decision-claude-print-subscription-route-20261008.md`
- `specs/phase-plans-v11.md`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/claude_print_observations.py` (new, mined from agent-harness#1740)
- `phase-loop-runtime/src/phase_loop_runtime/data/claude_sdk/worker/` (new; adapter salvaged from agent-harness#1744)
- `plans/seats-claude-sdk-worker-contract.md`
- `phase-loop-runtime/src/phase_loop_runtime/seat_credentials.py`
- `phase-loop-runtime/src/phase_loop_runtime/executable_dependency.py`
- `phase-loop-runtime/pyproject.toml`
- `docs/advisor-board-capabilities-card.md`

**Depends on**
- (none)

**Produces**
- IF-0-CLAUDE-1
- IF-0-CLAUDE-2

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the Claude decision record, `specs/phase-plans-v11.md` (EC-PANEL-6 consumption note), `advisor_board/CONTRACTS.md`, the capabilities card; evidence paths: W0 records under `plans/evidence/seat-qualification/` (operational evidence; owner-observed meter readings by reference); `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 2 — Records, Dispositions and Issue Index (INVENTORY)

**Objective**
Settle the record: draft dispositions, the Pi issue, the superseded proposal and an index of
the issues this roadmap owns. No phase waits on this one except CLOSEOUT.

**Exit criteria**
- [ ] EC-INVENTORY-2 — `docs/review-seats-issue-index.md` gives every issue and PR named in this roadmap exactly one owning EC, or records it as a reference or out of scope. Other ECs may cite an issue they do not own. An issue split across vendors (agent-harness#1653) has one owning EC per vendor part. A fresh `seat OR jail OR sandbox OR panel` search is appended as a non-blocking index; it is not an exit. Falsified by a named issue with no owner, or with two for the same part.
- [ ] EC-INVENTORY-3 — Each draft PR in the table below carries its disposition as a PR comment. Each is closed by the owner the table names. Falsified by a listed draft without a disposition comment.
- [ ] EC-INVENTORY-4 — A Pi review-seat issue is filed in Consiliency/agent-harness, and the agent-harness#848 proposal is marked superseded by this roadmap. Falsified by either missing.
- [ ] EC-INVENTORY-6 — agent-harness#896 records that its SSH-first follow-on plans are retired in favour of the OpenShell remote route (REMOTE), citing this roadmap.

**Scope notes**
- Preamble phase (documentation and GitHub records); decompose into 2 lanes with disjoint
  outputs. **Lane A** owns the issue index. **Lane B** owns PR comments, closures, issue
  edits and the proposal banner.
- EC-INVENTORY-1 (the matrix) moved to EC-FIRSTSEAT-6. EC-INVENTORY-5 (registration) was
  met by OD-1 when this roadmap was registered. Both IDs are retired, not reused.
- Draft dispositions (OD-2 default):

  | PR | Disposition | Closed by |
  |---|---|---|
  | agent-harness#1740 | Mine the jailed `print` diff onto current main; do not rebase the branch | EC-CLAUDE-2 |
  | agent-harness#1744 | Salvage the SDK adapter, the `claude-sdk` extra pin and the Gate A clean-room install fix into CLAUDE lane C. The solo-runner route re-files on agent-harness#1391. | EC-CLAUDE-3 |
  | agent-harness#1641 | Salvage. Its native-image resolver comes with the agent-harness#1740 mine; its private startup evidence goes to CLAUDETUI. | EC-CLAUDETUI-1 |
  | agent-harness#1623 | Split. The Grok allow-list part is superseded by agent-harness#1652. The PTY and banner fixes go to CLAUDETUI. Seat-uid resolver readability goes to FIRSTSEAT lane A. | EC-CLAUDETUI-1 |
  | agent-harness#1644 | Close; superseded by the jailed Codex route. Reopen as CODEX input if OD-4 is rejected. | This phase |
  | agent-harness#1731 | Close with agent-harness#1644, citing its denial evidence, which the matrix also cites. Reopen if OD-4 is rejected. | This phase |
  | agent-harness#1781 | No action. Unrelated (verification retention and signed historical custody); no hold claimed. | — |

**Governance**
- Principle 2. OD-2 is defaulted, and closures can be undone by reopening.

**Non-goals**
- Any code change. A census of every matching issue as an exit criterion.

**Key files**
- `docs/review-seats-issue-index.md`
- `docs/proposals/review-seat-sandbox.md`

**Depends on**
- (none)

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: `docs/review-seats-issue-index.md`, `docs/proposals/review-seat-sandbox.md`; evidence paths: the index and PR/issue links; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 3 — Jail Profile Registry and Route Resolver (JAILCORE)

**Objective**
Let a vendor join the jail by registering a profile, run the fallback chain through one
resolver, and make "no profile" mean degraded, never unconfined.

**Exit criteria**
- [ ] EC-JAILCORE-1 — The Claude and Gemini profiles are registered under IF-0-JAILCORE-1 by a digest-invariant refactor: on the same base, each profile digest is equal before and after the registry change. Vendor digest changes belong to vendor ECs (principle 4). Falsified by a refactor that changes a digest, or by a profile needing a branch in the route decision.
- [ ] EC-JAILCORE-2 — The resolver walks local jail → remote → native fill → degraded and emits one typed code per failed step. Only codes on IF-0-JAILCORE-1's descend list move after a failed local step, except that pre-launch `seat_local_capacity_exhausted` may enter remote through the capacity gate. Any other code goes straight to degraded, and nothing launches on a later rung. That includes `seat_sandbox_refused:identity`, `token_file_unsafe`, `stage_changed`, `output_unsafe`, every token-in-output code, and the `gemini_seat_*` containment codes (`token_scope_excess`, `egress_unconfined`, `token_refreshed_in_jail`, `credential_unusable`). `gemini_seat_egress_unavailable` splits into `seat_egress_not_installed` (ordinary, descend), `seat_egress_integrity_failed` (security, terminal), `seat_egress_tls_unterminated` (security, terminal) and `seat_egress_start_failed` (ordinary, terminal). The remote rung serves rows and host classes the matrix routes there, plus pre-launch capacity offload admitted by the disabled-by-default capacity gate. No review seat selects a sealed command for any `SEALED_FALLBACK_CODES` code (agent-harness#1288), and no fix line recommends a sealed or inline route. Falsified by the agent-harness#1282 falsifier (a sealed command selected for a review seat), or by any `seat_jail.NOTICES` code off the descend list that launches anything on a later rung.
- [ ] EC-JAILCORE-3 — The host proxy serves per-provider allowlists under IF-0-JAILCORE-2, with Gemini first. Each seat gets one proxy process and token, bound to one allowlist, with TLS terminated. A mode that cannot terminate TLS degrades the seat. A registered profile without its allowlist resolves degraded, never unconfined; jailed Claude's open egress is the one named exception (EC-JAILCORE-5). Falsified by a jailed seat, or a tool it runs, reaching an unlisted host or another provider's listed host, or by a profile without an allowlist launching outside that exception.
- [ ] EC-JAILCORE-4 — Dependency projection works for any registered profile. Qualification passes are keyed by profile digest, allowlist content digest, falsifier layout (agent-harness#1287), any projected profile's `dependency_projection_digest` and, for Claude, the transport. Falsified by a pass carried across any key part, for example a widened allowlist or a switched Claude transport that keeps its pass.
- [ ] EC-JAILCORE-5 — A leg with no registered profile resolves DEGRADED, never `MODE_UNCONFINED`. Codex and Grok keep their current unconfined route, and jailed Claude its open egress, only as named exceptions in the matrix with an expiry (principle 3). Each ends when its phase (CODEX, GROK, CLAUDENET) exits, as `jailed` or as degraded under OD-9, or earlier at expiry, when it resolves degraded. Falsified by a leg without a profile, Pi included, reaching an unconfined launch outside a named, unexpired exception.
- [ ] EC-JAILCORE-6 — Each profile declares four things. First, a closed configuration surface: planted tree config (project settings, hooks, MCP servers, provider overrides) is not loaded. Second, its post-launch auth classifier (IF-0-FIRSTSEAT-3). Third, its containment evidence: credential scope measured, in-jail refresh detected, an unlisted endpoint refused. Fourth, output secret refusal: credential material in seat output, in any `contains_secret` encoding, ends the leg with a typed terminal code. Gemini declares all four here. Claude declares all but its containment evidence here, and that in EC-CLAUDENET-3. Falsified, per profile, by a planted config that loads, or a planted credential in output that does not end the leg typed.

**Scope notes**
- Decompose into 3 lanes. **Lane A** owns the registry, the resolver, IF-0-JAILCORE-1,
  EC-JAILCORE-5 and EC-JAILCORE-6. **Lane B** owns proxy generalisation and
  IF-0-JAILCORE-2. **Lane C** owns projection wiring and the qualification key.
- Lane A publishes IF-0-JAILCORE-1 first. `seat_jail.py` is single-writer to lane A; lanes
  B and C edit their own modules.
- Plan this phase while FIRSTSEAT runs; execute it after FIRSTSEAT exits. It consumes
  IF-0-FIRSTSEAT-3 and the Gemini profile as W1 left it: qualified, or registered degraded
  if OD-9 routed the row.
- Making Codex and Grok degraded at once would leave plan and production boards refused,
  since their policies need those seats. Hence the named exceptions in EC-JAILCORE-5.
- Deliver agent-harness#1704 acceptance item 3 (the fallback ladder expressed through the
  interface), for seats only. Sweep fix lines that still name the sealed or inline route
  (`jail_unqualified` and others) under EC-JAILCORE-2.

**Governance**
- Principle 2. EC-JAILCORE-1 is checked by digest equality, so no requalification is needed.

**Non-goals**
- New vendor profiles (CODEX, GROK, PI). Changing any vendor's digest. Package extraction.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`
- `phase-loop-runtime/src/phase_loop_runtime/sandbox_egress.py`
- `phase-loop-runtime/src/phase_loop_runtime/executable_dependency.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`

**Depends on**
- FIRSTSEAT

**Produces**
- IF-0-JAILCORE-1
- IF-0-JAILCORE-2

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: `advisor_board/CONTRACTS.md`; evidence paths: digest-equality receipts, terminal-code falsifiers; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 4 — Team Hosts and Gemini Follow-ups (TEAMHOST)

**Objective**
Make jailed seats work on shared team hosts under several operator accounts, make the doctor
truthful, and finish the Gemini follow-ups.

**Exit criteria**
- [ ] EC-TEAMHOST-1 — Seats resolve the managed tooling release through declared projections, not ambient binds. Auth probes pass with the operator's scratch dir under a search-only workspace (agent-harness#1413). Falsified by a probe raising before the CLI runs.
- [ ] EC-TEAMHOST-2 — Two operator accounts run concurrent seats without shared-resource collisions (agent-harness#1108). Falsified by a cross-account collision, or by one account reading another's exec records or seat state.
- [ ] EC-TEAMHOST-3 — The managed runtime carries the qualification dependencies, and the fix text is one sentence with a managed-deployment branch (agent-harness#1357, agent-harness#1399). `phase-loop doctor` reports `seat_jail_prerequisites[]` truthfully, including on non-Linux hosts (agent-harness#1398).
- [ ] EC-TEAMHOST-4 — A host-admin checklist (LA-1) lists every root action, with print-only scripts that the runtime never runs.
- [ ] EC-TEAMHOST-5 — The doctor and admission agree. `seat_cli_qualification[]` reports whether the seat will admit, not whether a record exists (agent-harness#1479), and that includes agy qualification for this runtime (agent-harness#1520). Falsified by a doctor "qualified" that the seat then refuses.
- [ ] EC-TEAMHOST-6 — Every agent-harness#1706 item is closed, or deferred with a recorded reason. Each new test turns red when its check is neutralised.
- [ ] EC-TEAMHOST-7 — A runtime upgrade that does not change the profile digest keeps the recorded agy qualification. A digest change re-qualifies once, without a manual `agy models` (agent-harness#1420). A new agy version is admitted only by requalification, never mid-run; where agent-harness#1602's last-known-good pointer exists, the seat uses it. Falsified by a lost pass after a digest-preserving upgrade, or by a board that qualifies mid-run.

**Scope notes**
- Decompose into 4 lanes. **Lane A** owns bind and projection paths (EC-TEAMHOST-1).
  **Lane B** owns multi-account isolation (EC-TEAMHOST-2). **Lane C** owns the doctor,
  prerequisites, fix text and the checklist (EC-TEAMHOST-3 to EC-TEAMHOST-5). **Lane D** owns
  the Gemini follow-ups (EC-TEAMHOST-6, EC-TEAMHOST-7).
- `panel_invoker.py` is single-writer to lane A in this phase. JAILCORE runs at the same
  time; whichever lands second rebases.
- A Gemini digest change here returns the row to `candidate`, and it requalifies in the
  first row window after this phase exits (principle 4).
- This phase runs no window and needs no owner decision, so the vendor phases that depend
  on it never wait for either.

**Governance**
- Principle 2. LA-1 is an owner/admin action and is not required to land code.

**Non-goals**
- Changing host policy automatically. agent-harness#1602's wider lifecycle.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/sandbox_egress.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail_prerequisites.py`
- `phase-loop-runtime/src/phase_loop_runtime/doctor.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress/`
- `docs/TEAM-ONBOARDING.md`

**Depends on**
- FIRSTSEAT

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: `docs/TEAM-ONBOARDING.md`, the capabilities card; evidence paths: team-host provider-free receipts; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 5 — Claude Seat Egress and Row Qualification (CLAUDENET)

**Objective**
Hold the jailed Claude seat to the same egress and update policy as the other vendors, in
one batched profile-digest change, and live-qualify the Claude row.

**Exit criteria**
- [ ] EC-CLAUDENET-1 — Claude's allowlist under IF-0-JAILCORE-2 is built from the request sets W0 measured for each admitted transport (`print`, `sdk`, and `tui` only if CLAUDETUI repairs it). The jailed Claude seat launches only through its per-seat proxy. The dedicated SDK worker retains EC-CLAUDE-3's networkless sandbox, including for capture twins; it receives no proxy or open-egress exception. Falsified by a jailed Claude seat, or a tool it runs, reaching an unlisted host or another provider's listed host.
- [ ] EC-CLAUDENET-2 — One profile-digest change carries both the proxy wiring and `DISABLE_UPDATES=1` in the jailed seat environment (agent-harness#1804), and names the row window that requalifies it. Falsified by a Claude digest change landed in any other phase, or not named to a window.
- [ ] EC-CLAUDENET-3 — Claude's containment evidence under EC-JAILCORE-6: credential scope measured, in-jail refresh detected, an unlisted endpoint refused, and the planted-config falsifier run per admitted transport. Falsified by a refresh or an unlisted request that goes undetected, or a planted config that loads on any admitted transport, or an SDK worker reaching host-loopback or external network. Repeat the worker probes on the qualified installation.
- [ ] EC-CLAUDENET-4 — Claude row. In the first row window after EC-CLAUDENET-1 to EC-CLAUDENET-3 hold, Claude qualifies on its OD-3b default with this phase's egress in place (principle 1) and reads `done-local`. If OD-3b recorded no admitted transport, or the jail fails a falsifier on a named host class, OD-9 routes the row to `remote-pending` (principle 6). Falsified by a `done-local` Claude row with no window record on its current qualification key.

**Scope notes**
- Decompose into 2 lanes. **Lane A** owns the profile change (EC-CLAUDENET-2) and is the
  only writer of the Claude profile builder. **Lane B** owns the allowlist rows, probes,
  containment evidence and the row window.
- Until this phase exits, the matrix shows Claude's egress as open. The Claude row cannot
  read `done-local` before then.
- Known date: the matrix's jailed Claude open-egress exception expires 2026-12-04 UTC. If
  this phase has not exited by then, the jailed Claude seat resolves degraded
  (EC-JAILCORE-5) unless an owner record in the matrix renews it (principle 3).
- If OD-3b recorded no admitted transport, EC-CLAUDENET-1 to EC-CLAUDENET-3 do not apply,
  and the phase exits through EC-CLAUDENET-4's OD-9 branch.

**Governance**
- Principle 2. The row window is owner action LA-2 and LA-3.

**Non-goals**
- Transport selection or default (CLAUDE). TUI repair (CLAUDETUI).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress/`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `docs/review-seats-readiness.md`

**Depends on**
- CLAUDE
- JAILCORE
- TEAMHOST

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the capabilities card, `advisor_board/CONTRACTS.md`, `docs/review-seats-readiness.md`; evidence paths: allowlist probe rows, containment receipts, row-window records under `plans/evidence/seat-qualification/`; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 6 — Codex Seat in the Jail (CODEX)

**Objective**
Run the Codex seat inside its per-seat jail, with the jail as its only boundary
(agent-harness#1480), after its credential and egress are contained.

**Exit criteria**
- [ ] EC-CODEX-1 — A registered Codex profile runs the codex CLI on the staged tree, with its own sandbox off inside the jail (OD-4) and full tools. The mode line reads `jailed`. The route is enabled only after EC-CODEX-2, EC-CODEX-3 and EC-CODEX-5 hold. Falsified by a nested namespace attempt, by `seat_filesystem_unconfined` on a capable host, or by enabling the route before egress is confined.
- [ ] EC-CODEX-2 — The codex launcher and its native image are projected (agent-harness#1774). Credential delivery is stated as it really is: Codex's auth file in seat home. Its scope is measured and its containment evidence recorded under EC-JAILCORE-6. An auth file carrying an API key is refused for jailed seats. A "Not logged in" probe is not treated as logged in (agent-harness#1528). Falsified by an API-key auth file reaching a seat, or a not-logged-in probe read as logged in.
- [ ] EC-CODEX-3 — Codex egress uses its measured allowlist under IF-0-JAILCORE-2 (agent-harness#1653). Falsified by the jailed Codex seat, or a tool command it runs, reaching an unlisted host or another provider's listed host.
- [ ] EC-CODEX-4 — Codex row. A provider-free qualification passes on a team host where agent-harness#1335 reproduces, and the row reads `candidate`. It then qualifies in the next row window (principle 1) and reads `done-local`. If the jail fails a falsifier on a named host class, OD-9 applies (principle 6). Falsified by a `done-local` Codex row with no window record on its current qualification key.
- [ ] EC-CODEX-5 — On every run, a Codex seat whose tools could not run is typed and not counted as a review (agent-harness#1480). The agent-harness#1480 decision on the seat-launch-owner host fallback is recorded: removed, or kept with a written reason. Falsified by a seat that returns OK having read nothing (the agent-harness#1335 record).

**Scope notes**
- Decompose into 3 lanes. **Lane A** owns the profile, argv and EC-CODEX-5. **Lane B** owns
  projection and credential delivery. **Lane C** owns allowlist measurement and probes
  (agent-harness#1472). Lanes B and C land before lane A enables the route.
- The `setfcap` retention in `sandbox_egress.py` does not carry into the jailed route, and
  it retires when agent-harness#1335 closes.
- Expected to close agent-harness#1335, agent-harness#1003 and agent-harness#941.

**Governance**
- Principle 2. OD-4 is required before lane A enables the route; lanes B and C do not wait
  for it.

**Non-goals**
- AppArmor nesting policy (agent-harness#1644 and agent-harness#1731 are closed by
  INVENTORY). API-key lanes.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/executor_availability.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`
- `phase-loop-runtime/src/phase_loop_runtime/sandbox_egress.py`

**Depends on**
- JAILCORE
- TEAMHOST

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the capabilities card, `advisor_board/CONTRACTS.md`, `docs/review-seats-readiness.md`; evidence paths: provider-free receipts, allowlist probe rows, containment receipts, row-window records; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 7 — Grok Seat in the Jail (GROK)

**Objective**
Run the Grok seat jailed, with a writable disposable tree, a closed tool surface,
provider-only egress and a contained credential.

**Exit criteria**
- [ ] EC-GROK-1 — A registered Grok profile runs grok on a writable disposable clone. A probe write lands in the clone and nowhere else (agent-harness#1686). The `--cwd` path resolves inside the seat (agent-harness#1460).
- [ ] EC-GROK-2 — Headless tool approval does not cancel turns (agent-harness#1091). On the CLI version the profile pins, the tool-definition probe (first run in EC-FIRSTSEAT-4) fails on any tool outside the allow-list. Falsified by an offered tool outside the list.
- [ ] EC-GROK-3 — Grok egress uses its measured allowlist under IF-0-JAILCORE-2 (agent-harness#1653). Falsified by a jailed Grok seat, or a tool it runs, reaching an unlisted host or another provider's listed host.
- [ ] EC-GROK-4 — Grok row. The row reads `candidate` after a provider-free team-host qualification, then qualifies in the next row window (principle 1) and reads `done-local`. If the jail fails a falsifier on a named host class, OD-9 applies (principle 6). Falsified by a `done-local` Grok row with no window record on its current qualification key.
- [ ] EC-GROK-5 — The Grok credential's delivery, measured scope and actual expiry are recorded under EC-JAILCORE-6. The refresh path on seat-only hosts is typed, with a fix line (agent-harness#1289). Falsified by a credential readable outside its declared delivery, or an untyped expiry.

**Scope notes**
- Decompose into 2 lanes. **Lane A** owns the profile, tree and argv. **Lane B** owns
  allowlist measurement, the tool-definition probe and the credential, and lands before
  lane A enables the jailed route.

**Governance**
- Principle 2.

**Non-goals**
- Grok API-key lanes.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_egress_proxy.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_credentials.py`

**Depends on**
- JAILCORE
- TEAMHOST

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the capabilities card, `docs/review-seats-readiness.md`; evidence paths: write-confinement probe, tool-definition probe, provider-free receipts, row-window records; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 8 — Pi Seat (PI)

**Objective**
Add Pi as a jailed review-seat vendor that reaches its routed models (such as DeepSeek) only
through its declared provider, and that is counted as that provider.

**Exit criteria**
- [ ] EC-PI-1 — `pi` is a panel leg on the homebrew backing, with a headless structured-output invocation and the board's verdict contract. The leg is enabled only once the Pi profile is registered and EC-PI-3 and EC-PI-5 hold, so it never runs with open egress or unattested attribution. Falsified by a Pi seat that only resolves through the omnigent gateway, or a Pi leg reachable before its profile, credential narrowing, allowlist or attribution.
- [ ] EC-PI-2 — A registered Pi profile projects the Pi runtime and packages (agent-harness#1782) and runs with full tools in the jail, with its configuration surface closed (EC-JAILCORE-6).
- [ ] EC-PI-3 — OD-5 is implemented. The credential is narrowed to the routed provider, with no aggregator unless OD-5 allows one, and a spend cap on any API-billed lane. Egress is confined to the routed provider's allowlist. Falsified by a Pi seat, or a tool it runs, reaching another provider.
- [ ] EC-PI-4 — Pi row. The row reads `candidate` after a provider-free team-host qualification, then qualifies in the next row window (principle 1) and reads `done-local`. If the jail fails a falsifier on a named host class, OD-9 applies (principle 6). Falsified by a `done-local` Pi row with no window record on its current qualification key.
- [ ] EC-PI-5 — The routed provider is attested from the launch configuration and the provider's response, not from the declared model name. Landing-policy aliases are keyed on harness and model, so a Pi seat never fills another vendor's slot. Author/reviewer independence refuses a Pi seat routed to the author's vendor. Falsified by a Pi seat counted as the wrong vendor, a `gemini-*` model name filling the gemini slot through Pi, or a same-routed-vendor review counted as independent.

**Scope notes**
- Decompose into 3 lanes. **Lane A** owns the leg and verdict parsing. **Lane B** owns the
  profile and projection. **Lane C** owns the credential, egress and vendor identity
  (EC-PI-3, EC-PI-5). Lanes B and C land before lane A enables the leg.

**Governance**
- Principle 2. OD-5 is required before lane C lands, and so before the leg is enabled.
  Lanes A and B do not wait for it. Only CLOSEOUT depends on PI, so OD-5 never holds
  another vendor's row window.

**Non-goals**
- Pi as an executor (existing runner route). Omnigent backing changes. A Pi slot on plan or
  production tiers, unless OD-5 adds one.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/registries.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/schema.py`
- `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`
- `phase-loop-runtime/src/phase_loop_runtime/launcher.py`
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`

**Depends on**
- JAILCORE
- TEAMHOST

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the capabilities card model × harness matrix, `advisor_board/CONTRACTS.md`, `docs/review-seats-readiness.md`; evidence paths: provider-free receipts, attribution falsifiers, row-window records; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 9 — Claude TUI as Last Fallback (CLAUDETUI)

**Objective**
Settle the jailed TUI as the last Claude fallback: repaired, or retired to a typed degraded
route. This phase runs no live window of its own.

**Exit criteria**
- [ ] EC-CLAUDETUI-1 — The agent-harness#1461 cause is diagnosed with retained private startup evidence (salvaged from agent-harness#1641), and the PTY and banner fixes land (salvaged from agent-harness#1623). agent-harness#1641 and agent-harness#1623 are closed, citing the salvage.
- [ ] EC-CLAUDETUI-2 — OD-6 is recorded. If repaired: an offline-tested repair lands, and `tui` stays typed-degraded on the jailed seat until a batched window admits its canonical output, which the matrix records. If retired: `tui` on the jailed seat yields a typed degraded notice. Falsified by a TUI run reported OK with missing canonical output.

**Scope notes**
- Decompose into 2 lanes. **Lane A** owns diagnosis and repair. **Lane B** owns the degraded
  path and its notice.
- A repaired TUI's live check rides the next row window after this phase exits; no window
  waits for it. If a repaired TUI needs new allowlist rows, they are added by amendment to
  EC-CLAUDENET-1 and batched with that window.

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

### Phase 10 — Remote Review-Runner with Provider Egress (REMOTE)

**Objective**
Give each row the matrix routes remote, and each host class without jail prerequisites, a
remote sandbox seat with provider-only egress, behind security review and target activation
(a generic probe receipt on owner-controlled targets, per-vendor OD-7 on third-party targets).
The order is: amend Stage 2's activation proof for provider egress, then
activate these per-provider vectors. No runner activated under the no-egress proof gains
provider egress.

**Exit criteria**
- [ ] EC-REMOTE-1 — One vector per provider (IF-0-REMOTE-1), in its own vectors file with per-vector `pending_qualification`, so Stage 2's flip of its no-egress vectors cannot touch them. A vector map keyed on leg and routed provider replaces the single worker pin. `full-remote-pi-runner` and every existing vector digest stay unchanged. Each provider vector equals `full-remote-pi-runner` except in `network_policies` and the paths the security review lists. A local validator fails any other difference, and requires network enforcement `ENFORCE`, TLS `TERMINATE`, L7 rules equal to the measured request set, `allow_uninspected_credentials: false` and pinned binaries. The C5 amendment adds only public provider hosts, and keeps `inbound_closed`, `one_shot_secret_channel`, `private_ranges_unreachable` and the empty private allowlist. Falsified by a changed existing vector digest, a vector that passes the validator in AUDIT or PASSTHROUGH mode or with a difference outside its permitted fields, or one vector serving two providers.
- [ ] EC-REMOTE-2 — Credential projection follows the IF-0-REMOTE-2 table. A token whose remaining lifetime exceeds the seat deadline plus a margin is refused, unless OD-7 records a ceiling for that vendor. A token whose scope exceeds the table, or that refreshes inside the sandbox, ends the seat with a typed terminal code. `release_unconfirmed` and `lost_after_launch` trigger the revocation step. API keys are refused unless OD-7 approves them per vendor. The renewal token never leaves the launching host. Falsified by an over-lifetime or over-scope token delivered, an in-sandbox refresh not ended typed, a credential left unrevoked after `release_unconfirmed`, or an API key delivered without per-vendor approval.
- [ ] EC-REMOTE-3 — A security-review packet is recorded and approved under OD-7. It covers the threat model, falsifiers and method denials. It names everyone who can read the ExecSandbox stdin stream or the plaintext behind TLS termination, and states each vendor's actual token lifetime. It weighs a proxy-held credential against a guest-held one; proxy-held needs a coordinator revision, because `providers` is `maxItems: 0`. It declares the residual channels, including exfiltration through an allowed provider endpoint using a foreign credential, and source-code exposure to the remote host. Each third-party vendor's activation approval binds the digests of the vectors, the vector map, the validator, the image, EC-REMOTE-6's guest invocation and delivered runtime, and the credential module, plus the OpenShell and gateway versions. Any change voids that approval, and re-approval re-runs the EC-REMOTE-5 probes. An owner-controlled target is activated by one current generic egress-and-credential probe receipt, which binds the target and the probe-set digest and does not bind that digest list. Weaknesses are reported privately. Falsified by a third-party activation whose bound digests or versions differ from the approval, or by an owner-controlled activation whose probe receipt is missing, expired or bound to a different probe-set digest.
- [ ] EC-REMOTE-4 — The remote rung is the resolver's step 2, disabled until a current generic probe receipt activates an owner-controlled target or a per-vendor OD-7 record activates a third-party target, and refuses unwired dependency routes (agent-harness#1787). Each seat gets one sandbox, one lease and one credential copy. A tested deactivation path turns a vendor's rung off. The rung refuses a vector with neither a matching current owner-controlled probe receipt nor its vendor's third-party OD-7 activation record. Falsified by two seats sharing a sandbox or credential copy, a deactivated vendor launching remotely, or a vector launching without its activation record.
- [ ] EC-REMOTE-5 — Stage 2's activation proof is first amended to scope its no-egress claim to Stage 2's own vectors. Then, with Stage 2's infrastructure live (LA-4) and target activation under the capacity ruling (and per-vendor OD-7 on third-party targets), every row the matrix routes remote reads `done-remote` from the activation window. In that window, in-guest probes run as the pinned binary and from a tool command. They are refused for an unlisted host, another provider's host, a same-front-end host (the agent-harness#1170 `iam` case), a denied method or path on a listed host, a raw IP, DNS, private ranges and metadata. The runs exercise EC-REMOTE-6's invocation. Falsified by any probe request that reaches upstream.
- [ ] EC-REMOTE-6 — A trusted per-vendor review invocation runs in the guest. It delivers the runtime and dependencies, returns the admitted verdict and tool evidence under the board's contract, and uses only the credential lanes the IF-0-REMOTE-2 table supports. Unsupported lanes stay typed and pending. Falsified by a remote seat result admitted without tool evidence.

**Scope notes**
- Decompose into 5 lanes: **lane A** vectors, validator and C5 amendment; **lane B** the
  credential table, projection and revocation; **lane C** the security-review packet;
  **lane D** resolver integration, per-seat isolation and deactivation; **lane E** the remote
  review invocation.
- Lanes A to E run offline now. EC-REMOTE-5 waits on the proof amendment and Stage 2's
  infrastructure (the owner's gateway qualification and ai-stack Unit 7), not on Stage 2's
  no-egress flip. The remote window is batched with that qualification.
- Nothing else in this roadmap depends on REMOTE. Local closeout does not wait for it.

**Governance**
- Principle 2.
- OD-7 approves the EC-REMOTE-3 packet before lanes A and B land. On third-party targets,
  OD-7 is also the per-vendor activation that binds the EC-REMOTE-3 digests before
  EC-REMOTE-5; a later change to any bound digest voids it. Owner-controlled targets are
  not that second OD-7 act: one current generic egress-and-credential probe receipt
  activates the target and does not bind the EC-REMOTE-3 digest list.
- Security review is required.

**Non-goals**
- Stage 2 transport and deployment. E2B. SSH backends (EC-INVENTORY-6).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/policies.json` (unchanged; the comparison base)
- `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/policy-digests.json`
- `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/coordinator-v1.schema.json`
- `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py`
- `phase-loop-runtime/src/phase_loop_runtime/openshell_artifacts.py`
- `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml`
- `phase-loop-runtime/images/review-runner/Containerfile`

**Depends on**
- JAILCORE

**Produces**
- IF-0-REMOTE-1
- IF-0-REMOTE-2

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: placement contract C5, `contracts/placement/README.md`; evidence paths: the security-review record and activation-window records; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

### Phase 11 — Local Closeout (CLOSEOUT)

**Objective**
Remove the sealed and unconfined seat paths, bring every president rung to EC-CLOSEOUT-4, settle
the matrix and close the issues this roadmap owns. Local closeout does not wait for REMOTE.

**Exit criteria**
- [ ] EC-CLOSEOUT-1 — Seats. Under OD-8, review-seat defaults contain no sealed route and no reachable `MODE_UNCONFINED`; the Codex, Grok and Claude-egress exceptions have ended. Falsified by any reachable sealed or unconfined review-seat command.
- [ ] EC-CLOSEOUT-2 — Every matrix row reads `done-local`, `done-remote`, or `remote-pending` with a degraded interim route and an open REMOTE tracking issue. A row still `candidate` rides a row window first. The capabilities card matches the matrix. `remote-pending` is recorded as an open deferral, not as done.
- [ ] EC-CLOSEOUT-3 — agent-harness#1132 and agent-harness#1288 close, citing the matrix. agent-harness#1244 receives the matrix and stays open only for the per-OS jails (Non-Goals). Only once REMOTE has also exited, the registry entry and line 3 (`> # DELIVERED — CLOSED (assessed <date>)`) move to `delivered` in one commit.
- [ ] EC-CLOSEOUT-4 — President. For each rung on each supported host class, the matrix's president rows show a tooled route, or, where the rung's vendor row is `remote-pending`, a typed-degraded rung the ladder advances past. Under OD-8, the president's sealed last resort is removed (agent-harness#1250), and every rung keeps the EC-FIRSTSEAT-2 bound. Falsified by a rung that is neither tooled nor typed-degraded, or a reachable sealed president command.

**Scope notes**
- Decompose into 3 lanes. **Lane A** owns seat sealed and unconfined removal. **Lane B** owns
  president route removal. **Lane C** owns docs, the matrix and issue closure.
- Seats and the president are scoped separately, so the president's ordinary route is never
  mistaken for a sealed seat route, or excused as one.

**Governance**
- Principle 2. OD-8 is required for EC-CLOSEOUT-1 and EC-CLOSEOUT-4.

**Non-goals**
- Per-OS jails.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`
- `docs/advisor-board-capabilities-card.md`
- `docs/review-seats-readiness.md`
- `specs/roadmap-status.json`

**Depends on**
- CLAUDENET
- CODEX
- GROK
- PI
- CLAUDETUI
- INVENTORY

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces: the capabilities card, `advisor_board/CONTRACTS.md`; evidence paths: the final matrix; `redaction_posture: metadata_only`; missing or malformed evidence routes non-human `blocker_class=contract_bug`.

---

## Phase Dependency DAG

```
  roots (start now): FIRSTSEAT (W1)   CLAUDE (W0)   INVENTORY

  FIRSTSEAT ─┬─► JAILCORE ─┬─► REMOTE ··· (proof amendment, Stage 2 infra, OD-7)
             └─► TEAMHOST ─┤
                           │  JAILCORE + TEAMHOST
                           ├─► CODEX      (own row window) ─┐
                           ├─► GROK       (own row window) ─┤
                           ├─► PI         (own row window) ─┼─► CLOSEOUT
             CLAUDE ──────►└─► CLAUDENET  (own row window) ─┤
             CLAUDE ─► CLAUDETUI ───────────────────────────┤
             INVENTORY ─────────────────────────────────────┘

  Edges: FIRSTSEAT → JAILCORE, TEAMHOST;  JAILCORE → REMOTE
         JAILCORE + TEAMHOST → CODEX, GROK, PI;  CLAUDE + JAILCORE + TEAMHOST → CLAUDENET
         CLAUDE → CLAUDETUI
         CLAUDENET + CODEX + GROK + PI + CLAUDETUI + INVENTORY → CLOSEOUT
  Parallel: FIRSTSEAT ‖ CLAUDE ‖ INVENTORY (roots);  JAILCORE ‖ TEAMHOST;
            CODEX ‖ GROK ‖ PI ‖ CLAUDENET ‖ REMOTE;  CLAUDETUI any time after CLAUDE
  No window joins vendors: each vendor phase qualifies its own row (principle 5).
  REMOTE has no dependants. The roadmap is delivered when CLOSEOUT and REMOTE have both exited.
```

---

## Execution Notes

- **Start now.** FIRSTSEAT, CLAUDE and INVENTORY are roots. Plan and execute them
  concurrently against current origin/main. Plan JAILCORE and TEAMHOST while FIRSTSEAT runs,
  and execute them once it exits. The downstream plan budget is 2000 + 500 per lane
  (`docs/phase-loop/plan-budget.md`).
- **Execution route.** Plans come from `/claude-plan-phase specs/phase-plans-seats-v1.md
  <ALIAS>`, named `plans/phase-plan-seats-v1-<ALIAS>.md`. The runner refuses this non-active
  roadmap, so lanes land as governed PRs under principle 2.
- **Critical paths.** First live seat: FIRSTSEAT alone. Local closeout: FIRSTSEAT →
  JAILCORE ‖ TEAMHOST → {CODEX, GROK, PI, CLAUDENET}, each through its own row window →
  CLOSEOUT. A vendor's owner decision (OD-3b, OD-4, OD-5) holds only that vendor's phase and
  CLOSEOUT. REMOTE runs alongside, and its activation waits on Stage 2's infrastructure.
- **Owner windows.** W1 (FIRSTSEAT), W0 (CLAUDE), rolling row windows (principle 5) and the
  remote activation window. Windows are batched, not one per fix, and none joins vendors.
- **Single writers across phases.**
  - `seat_jail.py`: FIRSTSEAT lane A, then JAILCORE lane A for the structure, then each
    vendor phase for its own profile. Only CLAUDENET changes the Claude digest. CLAUDE edits
    no profile builder.
  - `panel_invoker.py`: v11 PANELSPLIT may split it. Seat phases rebase onto the split
    rather than block it, and edit the seat-launch, broker or leg modules it names. Between
    concurrent seat phases, whichever lands second rebases.
  - `docs/review-seats-readiness.md`: FIRSTSEAT creates it. Each vendor phase edits only its
    own row, including its window result. A row window's PR updates only the rows it
    qualified. CLOSEOUT settles the matrix.
  - `specs/roadmap-status.json`: switch this entry to `advisory` when agent-harness#1824
    lands, in any PR (a two-line change with line 3). CLOSEOUT later moves the entry and
    line 3 to `delivered` (EC-CLOSEOUT-3).
- **Cross-roadmap ownership.** As EC-CLAUDE-8 states. Nothing else moves out of v11.
- **Modules shared with v11.** v11 PANEL and ROUTE also write `advisor_board/composition.py`
  and `governed_review.py`, and ROUTE lists `president_adapter.py`. FIRSTSEAT lanes B and C
  and PI lane C state their narrow edit scope in their plans, name the v11 phase sharing each
  module, and never edit the same function concurrently with it; whichever lands second
  rebases. No seats phase waits for a v11 phase to complete.

---

## Acceptance Criteria

- [ ] Every vendor (Claude, Gemini, Codex, Grok, Pi) meets principle 1, locally or remotely, with evidence digests in the matrix.
- [ ] No review seat can reach a sealed, toolless or unconfined route, and every president rung meets EC-CLOSEOUT-4.
- [ ] A plan-tier native board on `bounded` monitoring on a team host always terminates with a typed outcome, and every leg leaves an exec record.
- [ ] The jailed Claude default equals OD-3b, which cites W0 evidence; TUI is last.
- [ ] Each row the matrix routes remote, and each host class with no local jail, has a remote route activated by a current generic probe receipt on owner-controlled targets or per vendor under OD-7 on third-party targets, after the Stage 2 proof amendment. A vendor that reached `done-local` needs no remote activation.

---

## Verification

```bash
# roadmap structure and registry coherence
phase-loop validate-roadmap specs/phase-plans-seats-v1.md
phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md
phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-v11.md
# per host, each operator account
phase-loop seat-sandbox qualify
phase-loop seat-egress status
phase-loop doctor --json
# a plan-tier board terminates typed; every seat_modes entry is `jailed` (or remote), none sealed or unconfined
phase-loop advisor-board <bundle> --json
# matrix rows, window records and vectors reviewed on the closeout PR
```
