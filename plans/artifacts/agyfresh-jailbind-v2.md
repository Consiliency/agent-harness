# AGYFRESH JAILBIND v2 (r3): a staged private copy for held admissions

Contract for the amendment `plans/amendments/agyroll-HOLD-jailbind-v2.md`. It replaces the
mount form of AGYFRESH §2.11 (`plans/artifacts/agyfresh-contract.md`), which the jail
feasibility lane showed cannot work, with a design that needs no descriptor bind. It is a
proposal for review: nothing here is in force until the amendment's docs lane lands §9.
r2 followed the review of r1 and the coordinator's four rulings on it; r3 completes the
custody-only variant, closes a cleanup race and fixes the feasibility and CI wording.

**Two outcomes.** Text marked **[observed]** applies when the runtime check can be made;
text marked **[custody only]** applies when it cannot. SL-8 lands exactly one of each
pair, as decided, and drops the marks.

Paths are under `phase-loop-runtime/` unless they name another root; `src/` means
`src/phase_loop_runtime/`.

## 1. What is established (inputs)

From `plans/evidence/agyfresh-jailbind-feasibility.md` (HOLD lane SL-1, dev0, kernel
7.0.0-43, bubblewrap 0.11.1) and the bubblewrap 0.13.1 addendum recorded with it:

- **A memfd cannot be a bind source.** bubblewrap resolves every bind source by name
  (`realpath`), and a memfd has none. Independently, the kernel refuses a memfd as a bind
  source through `mount(2)` and through `open_tree`/`move_mount`.
- **bubblewrap binds by name, at mount time,** in its own mount namespace. For a regular
  file it mounts whatever the name resolves to then.
- **A named regular file binds and runs.** The existing path bind, through the real owner
  chain, executes the stand-in as the seat uid. The mounted file is the source inode.
- **Mode.** The seat uid needs 0555. At 0500 both read and exec are refused.
- **Digest.** A path-bound jail's actual digest is the canonical Gemini digest
  (`09827a0e…97c2`), and the launch key is unchanged, whatever the path is.
- **Relaunch.** A second launch of one jail needs the seccomp, bundle and instructions
  descriptors rewound; existing behaviour.

## 2. Design

For a **held** admission on the jailed standalone route only. Ordinary admissions and the
managed dependency are unchanged in every line.

### 2.1 The guarantee and what carries it

**The admitted-image guarantee rests on custody of the staged file (§2.2–§2.4):** the
bytes admitted are written to a private file under one checked name, and that exact name
is what both jails bind.

- **[observed]** The runtime check (§4) is a fail-closed integrity backstop on top of it.
  It is not an attestation of which image executed first.
- **[custody only]** There is no runtime check of the executing image on this route: it
  relies on custody of the staged file (§4.5).

### 2.2 The staging name

- **One spelling.** The staging root is the absolute path
  `<state_home>/phase-loop/seat-images`, made absolute lexically (no `realpath`). That
  spelling, extended by `/<random>/gemini`, is the **only** string used: to stage, to
  re-check, and as the bind source of **both** the production and the probe jail. It is
  never canonicalized on the way to `build_seat_jail`.
- **No symlink in the spelling used.** The spelling is walked from `/`, one component at a
  time, each opened relative to the previous descriptor with
  `O_DIRECTORY|O_NOFOLLOW`. A symlink component fails the open and the route refuses. A
  resolved path is never substituted: a host whose state directory is reached through a
  symlink sets `XDG_STATE_HOME` to a symlink-free spelling, or this route stays not covered
  there. Mount points, including bind-mount aliases, are not symlinks and are walked
  through; §6 V1 records what backs them.
- **Every component is trusted.** Each directory in the spelling is owned by uid 0 or the
  euid, and is not other-writable. A **group-writable** component is rejected, unless it
  is established that no in-scope uid can write through the group: the group is the
  operator's user-private group (`seat_jail._operator_private_group`: no other member, no
  other user's primary group). A component carrying an extended POSIX ACL (any named-user
  or named-group entry, access or default) is rejected. Anything that cannot be
  established is rejected.
- **Pinned.** `seat-images/` (euid-owned, 0700) and the per-launch directory (created
  with an exclusive `mkdir`, 0700) are held open by descriptor for the launch: the
  **pinned directory**. The staged file is created relative to it.
- **The filesystem** must not be mounted `noexec` and must have room for the image.
- Any rule failing is `seat_sandbox_refused:jail_build`; nothing is staged elsewhere.

### 2.3 Write, verify, re-check

1. Stream the admission's sealed memfd in 1 MiB chunks through one reused buffer (peak
   traced memory within the caps lane's `OVERHEAD_CEILING`) to a file created
   `O_CREAT|O_EXCL|O_NOFOLLOW`, mode 0600 while written.
2. `fchmod` 0555, close the writing descriptor, reopen read-only relative to the pinned
   directory, re-read and hash. The digest must equal the admission's, else the file is
   removed and the route refuses (`identity`). The read-only descriptor's
   `(st_dev, st_ino)` is the **pinned inode**. The admission, and so the memfd, is closed
   after this.
3. **Name re-check.** A fresh no-follow walk of the exact spelling from `/` must reach
   the pinned directory and the pinned inode (`fstat` identity at each of the two). This
   is done after staging, and again immediately before every start (§2.4).

### 2.4 Bind, lifetime, cleanup

- **Bind.** `build_seat_jail(leg, dir, <the spelling>, …)` with its existing signature.
  `seat_jail.py` is not edited: this is the path bind the profile already declares.
- **Lifetime.** The staged name exists, unchanged, from staging until every start and
  retry of both jails for that leg has finished. It is not removed early.
- **Cleanup.** The per-launch directory is removed, relative to the pinned `seat-images/`
  descriptor, when the leg is over: after a failed stage, a failed build of either jail, a
  refused check, a cancellation and a normal completion.
- **Publication and stale entries.** Two locks. The **root lock** is an exclusive `flock`
  on the pinned `seat-images/` descriptor; the **launch lock** is an exclusive `flock` on
  a per-launch directory, held for the launch's whole life. A launch takes the root lock,
  creates its directory, takes its launch lock, and only then releases the root lock: no
  entry is ever visible to a sweep without its launch lock held. A sweep runs only while
  holding the root lock, and removes an entry only if it is euid-owned, opened no-follow
  relative to the pinned root, and its launch lock can be taken without waiting: an
  inactive launch. An entry whose launch lock is held is never touched. An operator
  removing entries by hand does so only when no board is running; the docs say so.
- **Evidence.** The three keys of AGYFRESH §2.6, with `provider_admission_source: "lkg"`,
  plus `provider_image_check` (§4.4, §4.5).
- **Cost.** Per held leg: one write and two reads of the image (at most
  `MAX_MEMBER_BYTES` of disk while the leg runs), and one more read when a start is
  decided. Three held
  legs stage three copies.

A held admission still carries no path (AGYFRESH §2.2). The staged name is derived from
the sealed image, never from the candidate's path.

## 3. Threat model and the accepted window

- **Same uid: out of scope**, as ruled for the qualification-authority work.
- **Root: trusted.**
- **Any other uid: in scope**, including the seat uids and other subordinate uids. It
  cannot read or replace the staged file, or redirect its name: the per-launch directory
  is 0700 and euid-owned, and no component of the one spelling used is writable by it,
  directly, through a group or through an ACL. Inside the jail the seat uid has a
  read-only mount of a file it does not own and no bind of the host directory.

**Coordinator security decision (recorded).** The window between the last name re-check
and bubblewrap's mount, and the time the provider runs, are accepted. Checked staging
prevents replacement by in-scope actors before `exec`.

- **[observed]** The post-start check is a backstop that detects and refuses, and cannot
  undo.
- **[custody only]** Nothing observes the executing image. A start is refused only if the
  custody proofs fail (§4.5).

**Residual risk, stated.** A wrong image that reached `exec` (which under this model takes
a same-uid or root actor, or a defect in the custody rules) could read the inputs
delivered to the jail and the stripped bearer copy of the login, make the vendor-only
requests the egress proxy allows, and write the jail's writable state.

- **[observed]** It could do so before the check refuses it. Refusing the leg withholds
  its results; it does not reverse those effects.
- **[custody only]** It is not detected at runtime unless it also disturbed the staged
  file or its name, and its results would then be used.

**Not done.** No verifier or wrapper inside the jail. It would add trusted code to the
launch chain and change the canonical profile; that is an owner decision, not part of
this amendment.

## 4. The runtime check: a fail-closed integrity backstop

### 4.1 What it is and is not

A bounded observation, owned by the launch, of the provider process's executing image. A
matching observation shows that the provider slot was executing the staged inode, with the
admitted bytes, when it was sampled. It does **not** show which image executed first, or
what a process did between samples.

### 4.2 The observation

- **Which starts.** Every held production start and every retry, and every start of the
  probe jail that executes `/seat/bin/gemini` or whose result is trusted.
- **Which process.** The provider slot: the process the drop chain execs into, identified
  structurally from the launch's own process tree (SL-7 records the exact shape). The
  observer holds a `pidfd` on it and its start time from `/proc/<pid>/stat`.
- **A sample.** Open `/proc/<pid>/exe`; confirm through the `pidfd` and the start time,
  after the open, that the pid is still that process; then compare. The slot may show the
  chain's own fixed executables before the provider is exec'd; after that:
  - `(st_dev, st_ino)` equal to the pinned inode, and (on the first such sample) content
    hashing to the admitted digest → **match**;
  - anything else → **mismatch**, including a provider that has exec'd again into another
    file.
- **When.** From spawn, polled until the first match or mismatch, for at most the bound
  SL-7 measures and the lane fixes; and once more when the leg ends, if the process still
  exists.
- **The observer** is the unprivileged harness process, as in production. No privilege is
  added to make the check possible.

### 4.3 The decision, and what it gates

| Observed | Decision |
|---|---|
| a match, and no mismatch at any sample | pass |
| any mismatch | refuse |
| alive at the bound with neither | refuse |
| exited before any match (short-lived, or exec'd away and gone) | pass **only if** the custody proofs still hold: the pinned inode re-hashes to the admitted digest, the name re-check (§2.3) passes, and the pinned directory holds only the staged file; otherwise refuse |

**The decision is made only after the last applicable sample:** the end-of-leg sample,
or the exit. A mismatch at any sample, including the last, is authoritative, whatever was
seen before. Until then, and until the decision is "pass", nothing derived from the start
is used: not its stream, not its output files, not a success record or success evidence.
On refuse the jail's whole process tree is torn down, the outputs are discarded, and the
leg is refused with `seat_sandbox_refused:identity`.

### 4.4 Two outcomes of the feasibility lane

Whether the unprivileged observer can open `/proc/<pid>/exe` of the provider after the
seat-uid drop depends on the user namespace, the LSM and procfs settings. SL-7 (V4)
establishes it; this document does not assume it.

- **Observed.** The check runs as §4.2–§4.3. Evidence: `provider_image_check: "observed"`,
  or `"custody_only"` for a start that passed on the last row of §4.3.
- **Custody only.** If the observer cannot read what it needs, §4.5 applies in place of
  §4.1–§4.3.

SL-7 reports which outcome the evidence supports. The coordinator decides GO on custody
only, or STOP.

### 4.5 [custody only] The start gate without a runtime check

This subsection is self-contained; it is what lands as §4 when the decision is custody
only.

On a host class where the unprivileged harness cannot read the provider's executing image,
the route **relies on custody of the staged file and has no runtime check of the executing
image**. No observation is attempted. Every held production start and retry, and every
start of the probe jail that executes `/seat/bin/gemini` or whose result is trusted, is
gated by the custody proofs:

1. **Before the start:** the name re-check (§2.3) passes.
2. **When the start ends**, by exit or at the end of the leg: the pinned inode re-hashes
   to the admitted digest; the name re-check passes again; and the pinned directory holds
   only the staged file.

All of them holding is "pass". Any failing is "refuse". Until the decision is "pass",
nothing derived from the start is used: not its stream, not its output files, not a
success record or success evidence. On refuse, any process of the jail still alive is torn
down with its whole tree, the outputs are discarded, and the leg is refused with
`seat_sandbox_refused:identity`. Every held launch's evidence carries
`provider_image_check: "custody_only"`.

## 5. Alternatives considered

| Alternative | Canonical digest | Managed route | Verdict |
|---|---|---|---|
| **Staged private copy on the state filesystem (this design)** | unchanged: the declared path bind | untouched | chosen |
| Staged copy on a per-user tmpfs (`$XDG_RUNTIME_DIR`) | unchanged | untouched | same design with memory instead of disk; size-limited, absent outside a login session. Not the default; the probe records it as data. |
| A private tmpfs mounted per launch in the owner's namespace | unchanged if the bind stays a path | untouched | adds a mount step to the launch chain for no gain. Not pursued. |
| fs-verity on the staged file | unchanged | untouched | would make the file immutable and kernel-measured, closing the same-uid window too. Depends on the filesystem. A later hardening; the probe records availability. |
| `open_tree` on a named file | unchanged only if bubblewrap consumed it; it does not | untouched | not viable. |
| Bind the candidate's own file | unchanged | untouched | loses custody of the admitted bytes and executes a candidate-derived path, which AGYFRESH §2.2 and §2.5 forbid. Rejected. |
| A verifier or wrapper inside the jail | **changes** (launch chain) | canonical gate shared | would verify before `exec`; an owner decision (§3). |
| Data bind (`--ro-bind-data`) | **changes** | canonical gate and normalization shared | ruled out in the first amendment; unchanged here. |

## 6. Feasibility probe (amendment lane SL-7)

One local host (dev0), the conformance stand-in and small variants of it, no production
change, no agy, network, credential or provider call, never `ai`. Chain checks run through
the real owner launch chain and the seat-uid drop, with the unprivileged observer.

**Durable result.** The report is `plans/evidence/agyfresh-jailbind-v2-feasibility.md`. It
is committed alone and merged by its own evidence-only PR, as SL-1's was; that file on
`main` is the record SL-8 and the G-REL clearance cite. The probe cases are written in
`tests/test_agy_hold_jail.py` on SL-7's scratch branch; that file is not merged by SL-7 and
is taken over by SL-3.

| # | Check |
|---|---|
| V1 | **Name and mount.** For the exact spelling of §2.2 on this host: the no-follow walk passes; each component's owner, mode, group membership and ACL state are recorded. From **inside the real owner chain, at the point bubblewrap runs**, record what that spelling resolves to, the mountinfo entry that covers it (mount id, root, filesystem, flags, source), and the `(st_dev, st_ino)` of the per-launch directory and staged file seen there; they must equal the pinned ones. dev0's home is reached through a bind-mount alias: record the alias and its backing mount, and that the alias is not a symlink. Record filesystem type, `noexec` and free space. |
| V2 | A file staged per §2 binds by that spelling, and the stand-in executes as the seat uid, in a production-shaped and a probe-shaped jail built from the one string. |
| V3 | `actual_profile_digest(jail) == jail_profile_digest("gemini")` with every source file unmodified; every leg's canonical digest and the launch key equal their base values. |
| V4 | **Observer.** As the unprivileged harness process, after the seat-uid drop: the provider slot is identified; a `pidfd` is held; `/proc/<pid>/exe` opens; its identity equals the pinned inode and its hash the admitted digest. Record the userns, `ptrace_scope`, LSM profile and procfs `hidepid` in force, the time from spawn to first match, and the time to hash a full-size image. If it cannot be opened, record the error and stop V5; the outcome is "custody only" (§4.4). |
| V5 | **Decisions**, each through the chain: (a) a stand-in that exits at once → the last row of §4.3; (b) one that execs another file at once, and one that forks and exits → mismatch, or the last row with custody intact, as observed and recorded; (c) the staged file replaced after verification by a wrong image that writes output at once → refuse, its output unused, the jail tree gone; (d) alive past the bound with no match → refuse. |
| V6 | Inside the jail, as the seat uid: a write to `/seat/bin/gemini` fails; the host staging name is not visible; the open descriptor set is the declared one. On the host, a process under a subordinate uid cannot open the staged name or list its directory. |
| V7 | Lifetime and cleanup: the staged name is present and unchanged across two starts of one jail and a start of the other; after the leg ends nothing remains and no mountinfo names it; an entry whose lock is held is not removed by another staging, and one whose lock is free is. |
| V8 | Hosted CI: whether the hosted suite runner can launch a seat jail at all (prerequisites present or not), recorded as a fact for §7's test tiers. |
| V9 | Data only: `$XDG_RUNTIME_DIR` mount flags and size; whether fs-verity can be enabled on the state filesystem; whether `/proc/<pid>/root/seat/bin/gemini` can be stat-ed by the observer. |

**Decision rule.**

| V1, V2, V3, V6, V7 | V4 | V5 | Outcome |
|---|---|---|---|
| any fails | — | — | STOP |
| all hold | holds | holds | recommend GO, observed |
| all hold | holds | **fails** | **STOP** |
| all hold | fails | not run | the report recommends neither; the coordinator decides between GO on custody only and STOP |

On STOP the amendment's remaining lanes do not run and HOLD lanes artifact §K2 applies if
the owner accepts the gap. The report states V8's result in one line, because the jail
lane's CI obligations depend on it.

## 7. Jail lane (amendment lane SL-3, JAILBIND v2)

**Files.**

| File | Change |
|---|---|
| `src/agy_hold_stage.py` (new) | `stage_image(image) -> StagedImage` (§2.2–§2.4), `StagedImage.recheck()`, the publication and sweep locks, and the start gate for the outcome decided: `observe_provider(staged, launch) -> decision` (§4.2–§4.3) when observed, or the custody gate (§4.5) when custody only. Standard library plus `gemini_heartbeat`; outside `ROUTE_CORE`. |
| `src/panel_invoker.py` | `_prepare_jailed_gemini`, standalone branch, `source == "lkg"` only: stage, build both jails on the one spelling, close the admission; `_JailedSeat` gains `admission_source`, `hold_reason`, `subject_image_sha256` and the staged image; every held start does the name re-check, then applies the start gate for the outcome decided and uses the start's results only on its "pass"; teardown removes the staging. The evidence writes `provider_admission_source` always, and the other keys for a held admission. The `source == "subject"` lines, the managed branch and `_require_canonical_jail` are byte-identical. |
| `src/agy_hold.py` | `ROUTE_COVERAGE["jailed"] = True`. |
| `tests/test_agy_hold_jail.py` | taken over from SL-7's scratch branch; the cases below. |
| `tests/test_agy_hold_managed.py`, `tests/test_agy_hold.py`, `tests/test_agy_hold_cache.py` | the refusal case becomes the covered case; status `routes.jailed == "covered"`; the jailed end-to-end cache case. The eight F0 tests stay byte-identical. |
| `tests/test_panel_invoker.py`, `tests/test_gemini_seat_egress_1170.py`, `tests/test_seats_teamhost_integration.py` | only where a stub must follow. |
| `tests/test_agy_qci.py` | the source-hash supplement for `panel_invoker.py`, if it alone flags. |
| `tests/data/seat_launch_references.json`, `CONTRACTS.md`, the capabilities card, `CHANGELOG.md` | rows for the new opens; the jailed route, with the §3 residual risk and, for the outcome decided, either the §4.1 limit or the "no runtime check" sentence, in words; one entry. |

Not edited, by name: `seat_jail.py`, `seat_jail_qualification.py`,
`seat_qualification_key.py`, `seat_jail_autoqualify.py`, `seat_subject.py`.

**Two test tiers, and where each runs.**

- **Tier 1, no jail.** Selected with `-m 'not requires_seat_jail'`. **Required in hosted
  CI, executed with zero skips, unconditionally**: no tier-1 case may skip on a host
  capability. Staging, the name rules, the re-check, publication and sweeping, the start
  gate and its decisions, gating and teardown, against real processes launched directly
  (no bubblewrap). The construction-level cases (both jails' argv, the EC-HOLD-14 digests,
  the managed and qualifier jails against the real `_require_canonical_jail`) need no
  launch either.
- **Tier 2, the real owner chain and seat-uid drop.** Marked `requires_seat_jail`. Always
  run on dev0 in SL-3, with the run record attached to the G-REL clearance. **If SL-7's V8
  shows the hosted runner can launch a seat jail, tier 2 is also required in hosted CI,
  executed with zero skips.** If V8 shows it cannot, tier 2 skips there with that reason
  and the dev0 record is its proof. A tier-2 skip is never counted as a pass of the goal.

**What depends on the outcome decided.**

- **[observed]** `observe_provider` ships. Tier 1 runs every row of §4.3 and every V5
  variant against directly launched processes. Tier 2 replays V5 on the real chain and
  asserts the observer passes there.
- **[custody only]** `observe_provider` does not ship. Tier 1 asserts the §4.5 gate: no
  process is inspected (a spy on `/proc/<pid>/exe` opens records none), each custody
  condition failing refuses with outputs unused and the tree torn down, and the evidence
  says `custody_only`. Tier 2 asserts the same on the real chain. No V5 replay and no
  observer assertion is written.

**Tier 1 cases** (`test_ec_hold_13_…`, `test_ec_hold_14_…`).

- **Staging.** Exact bytes; file 0555, directory 0700; streamed within `OVERHEAD_CEILING`;
  each of these refuses and leaves nothing behind: a short write, a full filesystem, a
  `noexec` mount, an other-writable component, a group-writable component whose group has
  another member, a component with an extended ACL, a symlink component in the spelling,
  a pre-existing name, a re-read digest that differs. A group-writable component on the
  operator's private group is accepted.
- **Exact name.** Both jails' argv carry the identical string, equal to the staged
  spelling and to `jail.provider_path`; nothing passes it through `realpath`. The name
  re-check fails, and the start is refused, when the per-launch directory or the file is
  swapped for another inode between staging and a start.
- **[observed] Observer and decisions.** Each row of §4.3, with a stable identity across
  the open (a pid reused between find and open is not accepted); exec-again is a mismatch;
  a mismatch at the last sample overrides an earlier match, and no result or success
  evidence is used before that sample; a wrong image's early output is not used and its
  process tree is gone; every retry and every trusted probe start is observed.
- **[custody only] The start gate.** As "What depends on the outcome decided" above.
- **Publication and sweeping.** Deterministic, with the two lock acquisitions made
  steppable: a sweep that starts between a launch's `mkdir` and its launch lock waits on
  the root lock and then leaves the new entry alone; an entry whose launch lock is held is
  left; a stale entry is removed; two launches publishing at once both keep their entries.
- **Evidence.** The three keys and `provider_image_check`; for an ordinary launch, the
  base tree's evidence plus `provider_admission_source: "subject"` and nothing else.
- **Lifetime and cleanup.** The staged name is unchanged until the last start ends; after
  a failed stage, a failed production build, a failed probe build, a refused check, a
  cancellation at each of those points and a normal completion: no per-launch directory,
  no descriptor beyond those open before the call, the admission closed. A locked stale
  entry is left; an unlocked one is removed.
- **Ordinary launches.** Both jails bind `realpath(admission.path)`; nothing is staged; no
  observation runs.
- **Managed and qualifier.** The eight F0 tests; unstubbed, a managed-dependency jail and
  every jail `seat_jail_qualification._run_probe_in_jail` builds pass the real
  `_require_canonical_jail` against their own leg's digest; no qualification pass is
  written.
- **EC-HOLD-14.** Actual equals canonical for a staged-image jail; every leg's canonical
  digest and the launch key equal their base values.

**Tier 2 cases.** The stand-in also reports the SHA-256 of its own running image. In
**both** jails it executes from the staged name and reports the admitted digest; the
start gate for the outcome decided, on the real chain (**[observed]** the observer passes
and the V5 decisions replay; **[custody only]** no observation, the custody gate, the
evidence); the candidate's
source renamed, unlinked and rewritten after admission changes nothing that runs; the
surviving descriptor set is the declared one; credential, store, `held/` and staging
sentinels are unreadable as the seat uid and absent from mountinfo; a write to
`/seat/bin/gemini` fails; a real stable-source ordinary launch executes.

**Stop rules.** `seat_jail.py`, the managed branch, the qualifier or
`_require_canonical_jail` would need an edit; any canonical digest or key moves; an
ordinary launch's argv or evidence would change beyond the one additive key; the observer
needs a privilege the harness does not have; the check does not behave as SL-7 recorded.

**Rollback.** Revert: the route refuses a held admission again and status returns to
`not_covered`.

## 8. Requalification and release

- **Jail.** None. The bind is the declared path bind, so no canonical digest or
  qualification key can change, and `seat_jail.py` is not edited. EC-HOLD-14 still proves
  it rather than assuming it.
- **agy.** None intended; `tests/test_agy_qci.py` decides (AGYFRESH §3).
- **G-REL stays.** The jail lane merges only by the release owner's head-conditioned merge
  on a cleared head. The clearance names the cleared SHA and three records: (i) SL-7's
  report on `main`, with its digest comparison (V3) and its V8 result; (ii) that head's
  hosted CI run with both hosted groups executed and zero skips — the EC-HOLD-14 cases and
  the tier-1 EC-HOLD-13 cases — and tier 2 as well where V8 showed support; (iii) SL-3's
  dev0 run record of tier 2. All required checks pass on that head; no auto-merge, no
  queued merge.

## 9. Amendment text (landed by amendment lane SL-8, only after the coordinator's GO)

### 9.1 AGYFRESH contract

Replace §2.11 from "**Held admission (`source == "lkg"`): the sealed image.**" to the end
of the section with §2, §3 and §4 of this document, under the heading "**Held admission
(`source == "lkg"`): a staged private copy.**", keeping the section's first bullet
(ordinary admission unchanged) and adding: "The managed dependency and the qualifier are
unchanged in every line. `routes.jailed` (§2.6) is `"covered"` once this is implemented."

Exactly one outcome is landed, with its marks dropped:

- **Observed:** every **[observed]** item of §2.1 and §3; §4.1 to §4.4 (the "Custody
  only" bullet of §4.4 shortened to "On a host class where the observation cannot be
  made, this route is not offered."); not §4.5.
- **Custody only:** every **[custody only]** item of §2.1 and §3; §4.5 as the whole of §4;
  none of §4.1 to §4.4. No sentence that promises a runtime check or a refusal of a wrong
  executing image is landed.

In §2.6, add `provider_image_check` (`"observed"` | `"custody_only"`) to the keys written
for a held admission on the jailed route.

In §3's jail table, replace the first row with: "| §2.11 staged copy for a held admission
(the declared path bind) | none | none | none: no canonical digest or key can change;
EC-HOLD-14 proves it |".

In §1.2's appended paragraph, replace its text with: "On the jailed standalone route a
held image is staged to a private file for the launch (§2.11): the memfd is closed after
staging, and the copy costs disk, not memory."

In §5, replace EC-HOLD-13 and IF-0-HOLD-5 with the roadmap's text below.

### 9.2 Roadmap

- Owner decision D12: replace "runs as the admitted sealed image, not a path" with "runs
  from a private per-launch copy of the admitted image, held under a checked name".
- Non-Goals, the seat-jail exception: replace its sentence with "**except** what AGYFRESH
  §2.11 defines for a held admission on the standalone Gemini route: a private staged copy
  bound by the existing path bind and gated at each start as §2.11 states. No jail
  property changes: no mount, capability, filter, uid, environment or egress property of
  any jail, and no jail of another leg."
- Assumption 5: append "The first mount form (a sealed-memfd bind) failed its feasibility
  lane: neither bubblewrap nor the kernel binds a memfd. The route instead stages a
  private copy (AGYFRESH §2.11), subject to the second feasibility lane. Its guarantee
  rests on custody of that copy." Then one sentence for the outcome decided — observed:
  "A runtime check of the executing image is a backstop, and a wrong image that reached
  `exec` could act inside the jail before it is refused (AGYFRESH §2.11)."; custody only:
  "There is no runtime check of the executing image, and a wrong image that reached `exec`
  would not be detected unless it disturbed the staged file (AGYFRESH §2.11)."
- Replace EC-HOLD-13 with:
  `- [ ] EC-HOLD-13 — Jailed standalone route (AGYFRESH §2.11): for a held admission the production and the probe jail bind one private per-launch copy of the admitted image at `/seat/bin/gemini`, by one checked name that no other uid can redirect; a staged copy that fails verification or the name rules is refused; every held start is gated as AGYFRESH §2.11 states, by the custody proofs and by the runtime check where §2.11 provides one, and a refused start's stream, files and success evidence are not used and its jail tree is torn down; what runs is unchanged after the candidate's source file is renamed, unlinked or rewritten; the evidence carries source `lkg`; a failed build, a refused check, a cancellation and a completion leave no staged file or descriptor; an ordinary launch keeps the existing path bind, and its launch and evidence behaviour apart from the one additive `provider_admission_source` key.`
- EC-HOLD-14: replace "a sealed-image jail" with "a staged-image jail".
- IF-0-HOLD-5, in both places: "The standalone Gemini jail's staged private copy for a
  held admission, its checked name, its start gate, and its evidence (AGYFRESH §2.11)."
- G-REL paragraph: replace "The clearance needs both proofs: the feasibility lane's
  recorded digest comparison, and EC-HOLD-14 executed with zero skips in that head's
  hosted CI, linked in the clearance." with "The clearance names three records: the second
  feasibility lane's report on `main`, with its digest comparison; that head's hosted CI
  run with both hosted groups executed and zero skips, namely the EC-HOLD-14 cases and the
  EC-HOLD-13 cases that need no jail, and the cases that need a real jail as well where
  that report showed the runner can launch one; and the jail lane's recorded dev0 run of
  the cases that need a real jail." The sole merge actor, the head-conditioned merge, the
  required checks and the exclusion from auto-merge and queued merges stay as written.
- Phase HOLD scope notes: the jail feasibility line gains "A second feasibility lane
  decides whether the staged-copy design works."; the jail integration line names
  `agy_hold_stage.py` and `panel_invoker._prepare_jailed_gemini`, and drops
  `seat_jail.build_seat_jail`.
- Key files: add `phase-loop-runtime/src/phase_loop_runtime/agy_hold_stage.py`; remove
  `seat_jail.py`. Single-writer list: remove the `seat_jail.py` line.
- The External Inputs AGYFRESH row is repinned to the committed contract, and the HOLD
  plan's frontmatter digest is re-stamped.

### 9.3 HOLD plan

SL-8 edits `plans/phase-plan-v1-agyroll-HOLD.md` as follows. Blocks M1 to M9 are the
replacement texts, verbatim.

1. **Lane index.** Replace the "Branch recorded" line with: "Branch recorded at the SL-1
   checkpoint: STOP, new amendment; amended by
   `plans/amendments/agyroll-HOLD-jailbind-v2.md`." Before "External prerequisite for
   every lane", add the amendment's SL-7, SL-8, SL-3 and SL-6 stanzas, with SL-3
   `Depends on: SL-2, SL-5, SL-7, SL-8` and SL-6 `Depends on: SL-0, SL-1, SL-2, SL-3,
   SL-4, SL-5, SL-7, SL-8`. Add `SL-6` to the `Blocks:` lines of SL-0, SL-1, SL-2, SL-4
   and SL-5, and `SL-3` to those of SL-2 and SL-5.
2. **`## Lanes`.** Before `## Verification`, add the four `### SL-N` sections from the
   amendment, verbatim, with one change: in SL-8, `Owned files` becomes `none` and the
   line `- **Continues**: SL-0's `specs/phase-plans-agyroll-v1.md`,
   `plans/artifacts/agyfresh-contract.md`, `plans/phase-plan-v1-agyroll-HOLD.md`` is
   added, because the HOLD plan's SL-0 already owns those files.
3. **Superseded context.** Replace from "**Owner decision (2026-11-20), jailed standalone
   seat" up to, not including, "**Other binding inputs.**" with block M1. Replace the
   bullet "**A held admission carries no path.** Routes execute the sealed image only."
   with block M9.
4. **Superseded execution instructions.** Replace from "**Branches after SL-1**" up to,
   not including, "## Lanes" with block M2. This removes the SL-1 GO branch, the old
   SL-3-before-SL-4 order and the branch-checkpoint instruction, and moves G-REL's
   evidence reference to SL-7.
5. **SL-4 notes.** Replace "After SL-3 on the GO branch, after SL-2 on a STOP branch; the
   jailed end-to-end case is written only on GO." with block M3.
6. **Execution Notes.** Replace the "Single-writer files" bullet with block M4, the "Cost
   of the jail work" bullet with block M5, the "Not covered" bullet with block M6 and the
   "Effort" bullet with block M7.
7. **Whole-phase command and evidence.** Add `tests/test_agy_hold_jail.py` back to the
   frontmatter `suite_command` (after `tests/test_agy_hold_managed.py`) and to the Spec
   Closeout `evidence paths`.
8. **Acceptance Criteria.** Replace the two "pending a new amendment" lines with the
   amendment's EC-HOLD-13 and EC-HOLD-14 lines. Replace IF-0-HOLD-5's line with block M8.
9. Run `validate_plan_doc.py` on the plan; exit 0 is required. All of these edits,
   with blocks M1 to M9, were dry-run against the plan as the checkpoint left it and
   passed, with nine lanes and only the changelog-heuristic warning.

```text M1
**Owner decision (2026-11-20), jailed standalone seat: "Do it: sandbox runs verified
copy."** The jailed standalone route executes the provider by path, so a held admission
could not run there, and on a host that can jail, the Gemini review seat takes only that
route. The first design, binding the admitted sealed image, failed its feasibility lane
(SL-1): neither bubblewrap nor the kernel binds a memfd. The owner asked for a new design.
For a held admission the route now runs a private per-launch copy of the admitted image,
held under a checked name and bound by the existing path bind
(`plans/artifacts/agyfresh-jailbind-v2.md`). The managed projection and its digest gate
stay as they are; managed hosts recover at build time.

**Rulings that still apply:**

1. **Held only.** Ordinary jailed launches keep the existing path bind, with launch and
   evidence behaviour preserved apart from one additive evidence key.
2. **No jail property changes**, and `seat_jail.py` is not edited, so no canonical jail
   digest or qualification key can change. A data bind stays ruled out.
3. **The guarantee rests on custody of the staged copy.** Where AGYFRESH §2.11 provides
   a runtime check it is a fail-closed backstop; where it does not, the route has no
   runtime check of the executing image. Either way the execution window is an accepted,
   recorded risk.
4. **Release hold G-REL: the control is the merge** (Lane Index, below).
5. **Feasibility first.** SL-7 decides whether the staged-copy design works, on one local
   host, through the real owner launch chain and uid drop; never `ai`.

```

```text M2
**History.** SL-1 reported STOP on the first jail design, and the branch checkpoint
recorded "STOP, new amendment". The jail lane and the reducer were then restored by the
amendment `plans/amendments/agyroll-HOLD-jailbind-v2.md`. The branch table and checkpoint
procedure of lanes artifact §A and §K are spent and no longer direct execution.

**Order.** SL-2 → SL-4 → SL-5 as before. SL-7 (feasibility) may run beside them; SL-8
(docs) follows the coordinator's GO on SL-7's report; SL-3 follows SL-5 and SL-8; SL-6
closes the phase. If SL-7 ends in STOP, SL-8, SL-3 and SL-6 do not run, and lanes artifact
§K2's edits apply if the owner accepts the gap.

**Execution gate G-REL (release hold): the control is the merge.** Release owner and
**only merge actor** for SL-3: the Agent-Harness Exec.

- **Clearance.** Recorded by the release owner in the engagement plan and ledger. It names
  the cleared head SHA and links (i) SL-7's report on `main`, with its digest comparison;
  (ii) that head's hosted CI run showing both hosted groups **executed with zero skips**,
  the EC-HOLD-14 cases and the EC-HOLD-13 cases that need no jail, and the cases that need
  a real jail as well where SL-7's report showed the runner can launch one; and (iii)
  SL-3's recorded dev0 run of the cases that need a real jail.
- **Merge.** Only by a head-conditioned merge on the cleared SHA
  (`gh pr merge --match-head-commit <cleared-sha>`, or the train runner's equivalent
  head-conditioned merge), after every required check has passed on that same head. If the
  PR head differs at merge time the clearance is invalid, and the head condition makes the
  merge fail rather than race a push.
- **No unattended path.** SL-3 is excluded from auto-merge and from any queued or deferred
  merge. The standing approval to merge accepted PRs does not replace the clearance.
- `main` therefore stays releasable at every tag, and a deployment that consumes `main`
  directly is covered by the same gate; no pre-tag check is needed.

```

```text M3
The jailed end-to-end cache case is written by SL-3, which follows SL-5.
```

```text M4
- **Single-writer files.** `agy_qualification.py`: SL-2 → SL-4 → SL-5. `agy_hold.py`:
  SL-2 → SL-4 → SL-3 (one constant). `panel_invoker.py`: SL-3 only in this phase.
  `seat_jail.py`: not edited by any lane. Append-only shared files (`CONTRACTS.md`,
  `CHANGELOG.md`, `tests/data/seat_launch_references.json`): each lane adds its own section
  or rows and keeps the caps lane's `_open_image_fd` row (H6).
```

```text M5
- **Cost of the jail work.** Two feasibility lanes (SL-1, spent; SL-7), one docs lane
  (SL-8) and the jail lane (SL-3), which adds one module and edits `panel_invoker.py`.
  Disk: one image per held leg while it runs. No extra memory.
```

```text M6
- **Not covered, stated in the docs each lane writes.** Managed-release subjects, on every
  route (EC-HOLD-6, second branch). The jailed standalone route until SL-3 merges, and on
  hosts whose state directory fails the staging name rules. Ordinary jailed launches still
  execute a path.
```

```text M7
- **Effort.** SL-2, SL-3 and SL-5: high. SL-4 and SL-7: medium. SL-0, SL-6 and SL-8: low.
```

```text M8
- [ ] IF-0-HOLD-5 — The standalone Gemini jail's staged private copy for a held admission, its checked name, its start gate, and its evidence (AGYFRESH §2.11). Produced by SL-3.
```

```text M9
- **A held admission carries no path.** The memfd routes execute the sealed image; the
  jailed route executes a private copy staged from it.
```

## 10. Open questions

- **Q1.** Whether the unprivileged observer can read the provider's executing image after
  the seat-uid drop (V4). The answer selects "observed" or "custody only" (§4.4); the
  coordinator decides whether custody only is a GO.
- **Q2.** Disk cost: one image per held leg while it runs. Sharing one staged copy between
  legs is possible later; it is not in this design.
- **Q3.** Hosts whose state directory fails the name rules (a symlink in its spelling, a
  writable component, an ACL, `noexec`) get a clean refusal on this route. The fix on such
  a host is a symlink-free, private `XDG_STATE_HOME`.
- **Q4.** If hosted CI cannot launch a seat jail (V8), the tier-2 proof is the dev0 run
  record alone; if it can, tier 2 is required there too.
