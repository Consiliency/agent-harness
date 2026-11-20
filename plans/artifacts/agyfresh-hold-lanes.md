# AGYFRESH HOLD lanes r3: frozen detail for the HOLD phase plan

Detail for `plans/phase-plan-v1-agyroll-HOLD.md` (lanes SL-0 to SL-6) and
`plans/detailed-agyfresh-failexp-20261120-0114.md` (SL-5 FAILEXP). The design is
`plans/artifacts/agyfresh-contract.md` (AGYFRESH) **as amended by**
`plans/artifacts/agyfresh-hold-amendment.md` (the amendment); this file adds only what a
lane needs to build and test it. Where they disagree, the amended contract governs. Goal
IDs are defined in the roadmap (EC-HOLD-13 to -15 by the amendment) and are only
referenced.

r2 followed the review of r1 and the owner's decision that the jailed standalone seat runs
the admitted sealed image. r3 follows the review of r2 and the coordinator's four rulings:
the data-bind form is ruled out, the feasibility gate's checks are complete, release is
under a hold, and the jail lane's isolation and execution assertions are finished.

Paths are under `phase-loop-runtime/` unless they name another root; `src/` means
`src/phase_loop_runtime/`. `gh` is `gemini_heartbeat`, `q` is `agy_qualification`.

## A. Base and order

- Every code lane starts only after RESTORE's caps lane, with its contract repin, has
  merged. No lane branches from an unmerged lane.
- SL-0 (AMEND) and SL-1 (JAILPROBE) start at once, in parallel; they share no file.
- Then, one PR each, in order: SL-2 HOLD-CORE → SL-3 JAILBIND → SL-4 HOLD-CACHE → SL-5
  FAILEXP → SL-6 (reducer).
- SL-2 carries `tests/test_agy_hold_managed.py` from the F0 lane (branch
  `t3/agyfresh-f0-probe`), unmodified, as the EC-HOLD-6 guard.

## B. Options and rules

### B1. Selection promise (AGYFRESH §6.2): no memo

Amendment §2.3. The candidate list is rebuilt and walked in the total order on every hold;
nothing admitted or rejected earlier is remembered. At most five image reads per hold is
already the contract. r1's rejection memo is dropped: a metadata tuple is not a content
identity.

### B2. Replacement detection (AGYFRESH §6.3): option (b)

Amendment §2.4. After `from_fd`: the descriptor's `fstat` tuple is unchanged, and a
no-follow `stat` of the name relative to the opened directory names a regular file with the
descriptor's `(st_dev, st_ino)`. It detects an observed replacement and proves nothing
more; the sealed digest is the integrity control. Option (a) is not built or tested.

### B3. Managed-release skip (R-F0-1, R-F0-2)

Amendment §2.2 and §2.7. One predicate in `admit_seat`:
`seat_subject._names_managed_root(Path(resolved subject path))`, called read-only;
`MANAGED_RELEASES_ROOT` is read at call time. For a managed subject nothing is searched or
opened, `refusal` is raised unchanged and `retain` is not called. The agent-harness#1602
seam in `q.lookup` is untouched. The skip is by subject, so it covers every route in §C.

### B4. A held admission carries no path

Amendment §2.2. `admit_held` returns an `Admission` with `path=None`. Until SL-3 merges,
the jailed standalone route therefore refuses a held admission with today's code, and
`routes.jailed` is `"not_covered"`. SL-3 makes that route execute the sealed image.

### B5. Readers in SL-2, writers in SL-4

SL-2 implements the whole §2.4 candidate list, including reading `held/`. SL-4 implements
what writes: `retain`, pruning, corrupt-file removal, `clear --all`, the `retain` call site.

### B6. Status object (R2)

Amendment §2.5. `agy_hold.ROUTE_COVERAGE` is the one place that says which routes are
covered: SL-2 ships `{"seat_profile": True, "heartbeat": True, "jailed": False}`; SL-3 sets
`jailed` to `True` in the PR that makes it true. `q.hold_status(env, subject_path)` builds
the object. It never says "active" or "in use".

### B7. Retention gates (SL-4)

Amendment §2.6.

## C. Routes that admit a seat image

SL-2 re-checks this table by grep (`gemini_heartbeat.admit(`, `admit_for_seat(`,
`requalify_once(`, `ensure_admitted(`, `owned_profile(`, `require_capability(`) and stops if
a row is missing or its "executes" column is wrong.

| # | Route and call site | Subject | Executes | Hold |
|---|---|---|---|---|
| 1 | Seat profile launch and credential refresh: `agy_integrity.admit_for_seat` (two sites in `panel_invoker.seat_profile`) | caller's executable | admitted memfd | SL-2 |
| 2 | Non-jailed heartbeat: `gh.require_capability`, `gh.owned_profile` without an admission (`panel_invoker` brokered Gemini leg and its route check; `president_adapter`) | PATH `agy` | admitted memfd | SL-2 |
| 3 | Jailed review seat, managed dependency: `panel_invoker._prepare_jailed_gemini` | `dependency.subject_source` | the release projection | never (EC-HOLD-6); unchanged |
| 4 | Jailed review seat, standalone: same function | resolved subject | today the **path** `realpath(admission.path)`; after SL-3 the admitted sealed image | SL-3 |
| 5 | Board preflight and `agy-qualification run`: `q.requalify_once` | resolved subject | nothing | SL-2 |
| 6 | Help measurement: `q._run_help` → `gh.owned_profile(admission=...)` | given admission | given memfd | not an admission site |
| 7 | Executor and canary: `agy_integrity.check(path)` without env, `trusted_command`, `admitted_command`, `agy_canary_evidence` | PATH `agy` | memfd or path | never (AGYFRESH §2.2) |
| 8 | Reports: `q.admission_verdict` | resolved subject | — | `execute=False` unchanged (EC-HOLD-5) |

A managed subject is skipped on every row (B3).

## D. SL-1 JAILPROBE (feasibility gate)

**What it is.** A scratch lane with no production change. It decides whether the one
admitted mount form (amendment §2.8) works, and which launches may use it. It runs bwrap on
**one local host** with a stand-in executable (the conformance stand-in,
`tests/fixtures/agy_conformance/`): no agy, no network, no credential, no provider call.
For other configurations it uses static or already recorded evidence only. A run on a
second host is a separate request to the coordinator. `ai` is never used.

**Files.** `tests/test_agy_hold_jail.py` (new; probe cases that skip, with a reason, where
the host cannot run the jail) and `plans/evidence/agyfresh-jailbind-feasibility.md` (the
result).

**How every check is run.** Through the real owner launch chain: the argv from
`seat_jail._owner_argv`, the descriptor in `pass_fds`, then the production drop
(`setpriv_drop`, `seat_cwd`, `seat_fd_closer`) to the seat uid, exactly as a jailed seat is
launched. A hand-built bwrap call or a run without the uid drop is not evidence.

**Checks. All are required; each is an observed run, not a reading of code.**

| # | Check |
|---|---|
| P1 | bwrap mounts `--ro-bind /proc/self/fd/<fd> /seat/bin/gemini` when `<fd>` is a sealed memfd from `VerifiedImage.from_fd`. |
| P2 | After the uid drop the stand-in **executes** from that mount. The memfd is mode 0500 and operator-owned. If it executes only with the descriptor's mode set to 0555, record that 0555 is a production requirement, and what else observes the image's mode. |
| P3 | With `provider_path = "/proc/self/fd/<fd>"`: `actual_profile_digest(jail) == jail_profile_digest("gemini")`, with `actual_profile_digest` unmodified; the canonical digest of every registered leg equals its value on the base tree; `key_for_launch` returns the same key. |
| P4 | The mounts observed in the jail's mountinfo equal `expected_mount_points(jail)`, which is declared independently of the argv. |
| P5 | Inside the jail, as the seat uid: the mount is read-only and a write fails; the provider process's open descriptors are exactly the declared set; no host provider, store or vendor path is visible. |
| P6 | Two descriptors from `image.reopen()`, one for a production-shaped and one for a probe-shaped jail: before mounting they have the same `(st_dev, st_ino)` and digest; after mounting, the content hash of `/seat/bin/gemini` in each jail equals the admission's digest. |
| P7 | One jail launched twice executes the stand-in both times (the descriptor survives a launch). |

**Decision rule.** The form is selected only if P1 to P7 all hold. If any does not: stop.
SL-3 does not start, the route stays not covered, and the coordinator is told; the owner
decides between a new amendment and accepting the gap. There is no second form to fall
back to (amendment §2.8 says why).

**Supported deployment configurations.** The report lists the configurations the harness
supports for the jailed seat (from `docs/` and the recorded seat-jail evidence under
`plans/evidence/`: kernel and bwrap versions, setuid or user-namespace bwrap, the AppArmor
`unpriv_bwrap` restriction and its override) and marks each *observed here*, *recorded
evidence*, or *unverified*. The ordinary-launch default (amendment §2.8, "Which launches")
is recommended only if none is unverified; otherwise the report recommends held admissions
only and names the missing evidence.

**Not assumed.** Whether a memfd can be the source of a bind mount is a kernel fact this
plan does not know; P1 exists to find out.

## E. SL-2 HOLD-CORE

### E1. Files

| File | Change |
|---|---|
| `src/agy_hold.py` (new) | §2.4 constants and `HeldCandidate`; candidate list (cache reader, vendor authenticated, vendor hinted); anchored descriptor-relative opens (§2.5); the walk with split budgets and the B2 check; module lock; `hold_enabled()`, `hold_deny()`; `ROUTE_COVERAGE` (B6); `retain` no-op. Standard library plus `gh`; outside `ROUTE_CORE`. The §2.3 predicate is passed in as a callable. |
| `src/agy_qualification.py` | `_SubjectNotAdmitted`; `admit_seat`; `admit_held`; `ensure_admitted` delegating with its signature kept; `hold_status`; the `status` object. `lookup` keeps its signature, opt-out-first order, image ownership and the agent-harness#1602 seam. |
| `src/gemini_heartbeat.py` | `catalog_members(path=None) -> list[dict]` (never raises; `load_catalog` rebuilt on it); `admit` = candidate-token case, then `admit_seat(first_use=False)`, refusal mapped to `_CAPABILITY`; `owned_profile` evidence keys. |
| `src/agy_integrity.py` | `check` with env delegates to `admit_seat`; typed egress, quiescence and jail exceptions pass through; evidence keys. `check` without env unchanged. |
| `src/advisor_board/config.py`, `src/advisor_board/fixtures/advisor-boards.example.toml` | `[agy] hold`, `[agy] hold_deny`; `load_agy_hold`, `load_agy_hold_deny` (user file only; any error disables the hold). |
| `tests/conftest.py` | autouse: `agy_hold.VENDOR_STORES = ()`, so no test reads the host's real store. |
| `tests/test_agy_hold.py` (new) | §E3. |
| `tests/test_agy_hold_managed.py` (new here) | the eight F0 tests byte-identical; appended cases of §E3. |
| `tests/test_agy_catalog_data.py`, `tests/test_advisor_board_config.py` | `catalog_members`; the two keys. |
| `tests/test_agy_self_qualification.py`, `tests/test_agy_integrity_seat_admission.py`, `tests/test_agy_static_integrity.py`, `tests/test_seats_teamhost_gemini.py`, `tests/test_gemini_heartbeat_bootstrap.py`, `tests/test_agy_size_bounds.py` | only where a hook or stub must follow the moved read path; each keeps its intent; the agent-harness#1602 seam tests are not edited. |
| `tests/test_agy_qci.py` | only the source-hash supplement, if it alone flags (AGYFRESH §3). |
| `tests/data/seat_launch_references.json` | one row per new file read, `os.open` and `scandir` site. **H6:** the caps lane's `gemini_heartbeat` `io.open` row on `_open_image_fd` is kept as it is. |
| `src/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md` | section "HOLD — availability floor"; the hold, its config keys, the per-route coverage; one `[Unreleased]` entry. |

SL-2 edits neither the roadmap nor the contract; SL-0 did.

### E2. `admit_seat`, in order

1. Never-eligible, raised at their own sites with their own types, outside the hold
   handler: `_local_capabilities()` failure; unsupported platform; no provider;
   **an unavailable seal ABI when the image memfd is created** (`_linux_memfd_seal_abi`
   inside `_new_image_memfd`); **a memfd seal failure** (`AgyCanaryEvidenceError`). **H2:**
   the last two are classified here, before `check` maps them to `AgyImageUnqualified`,
   for example by a private exception subclass; the external refusal code is unchanged.
2. Open and stream the subject. `OSError` → `subject_unreadable`; not regular →
   `subject_not_regular`; over the bound, at `fstat` or while streaming →
   `subject_over_bound`. `subject_sha256` is `None` for all three.
3. Release member → admit, source `subject`, before any config or store read.
4. Opt-out → `self_qualification_disabled`.
5. `lookup` (it owns the image, **H1**). `failed` entry → `subject_failed`; a miss →
   `subject_unqualified`; unsafe store → `store_unsafe`. Typed egress, quiescence, jail and
   cancellation outcomes propagate. A seam admission from `lookup` is returned unchanged.
6. `first_use=True` only: today's first-use body; its refusals map to
   `provenance_unverified`, `provenance_unavailable`, `first_use_failed`,
   `first_use_unavailable`. `CANCELLED` propagates.
7. Handler: amendment §2.2.

**H1, exactly-once.** The subject image and every candidate image is closed, or handed on
inside an `Admission`, exactly once on every branch. **H3, one reader.** A candidate is
loaded only by `VerifiedImage.from_fd` on a descriptor from the anchored traversal;
`agy_hold.py` never names `_open_image`, `_read_image`, `from_bytes` or `realpath`. The
subject's memfd is closed before the first candidate is opened, and each rejected candidate
before the next. **H4, bounds at call time.** `agy_provenance.MAX_MEMBER_BYTES` is read
when a candidate is opened and while it streams; a candidate over it is skipped.

### E3. Tests

Test functions are named `test_ec_hold_<n>_…`. "Both paths" is
`admit_seat(first_use=True)` and `agy_integrity.admit_for_seat` (spawn). Every goal has at
least one case that enters through those functions over files on disk; cases that call
`agy_hold` directly are additional.

- **EC-HOLD-1 (coverage).** Both paths, a held release member present, the subject is:
  over the bound; unreadable (mode 000); removed after resolution; replaced by a directory;
  unqualified with no record; provenance without `qualified`; carrying a `failed` entry;
  self-qualification off; first use returning `failed`; first use returning transient;
  provenance unverifiable. Each admits the member with `provider_admission_source ==
  "lkg"`, the §2.2 reason, and `provider_subject_image_sha256 is None` for the first four.
  Each again with no candidate: the original exception type and message. `gh.admit` and
  `gh.owned_profile` (route 2) once each. **Held execution, memfd routes:** the evidence of
  a seat-profile launch and of an owned profile carries the three keys and the held digest.
- **EC-HOLD-2 (propagation).** A member present, both paths, a spy on the candidate opener
  recording zero calls, one case each: `_local_capabilities` failing; **H2** the seal ABI
  unavailable at image creation (patch `_linux_memfd_seal_abi` as `_new_image_memfd` calls
  it, with `_local_capabilities` left passing); **H2** a seal failure (through `check` both
  are `AgyImageUnqualified`, and still no candidate was opened); `CANCELLED` in first use;
  `EgressUnavailable`; `GeminiQuiescenceError`; `ProviderProcessGroupQuiescenceError`;
  `SeatSandboxRefused`; unsupported platform; no `agy` on PATH; `seat_provider_unavailable`
  from the CLI. The same typed outcomes raised by a **candidate's** help measurement
  propagate and close the candidate.
- **EC-HOLD-3 (predicates).** A locally qualified candidate is admitted with provenance and
  `qualified`; refused with a `failed` entry, a different measured help, a foreign store
  key, or its digest in `hold_deny`; `_run_help` is never called for a candidate without a
  provenance entry; the subject's own bytes in a store are never the hold;
  self-qualification off admits a member but not a locally qualified image; an unsafe store
  admits a member only.
- **EC-HOLD-4 (first use).** A passing `qualify` stub returns the subject and was called;
  no candidate was opened.
- **EC-HOLD-5 (compatibility).** `admission_verdict(execute=False)` is not `admits` for a
  non-member with a held member present; `execute=True` is. `[agy] hold = false` and a
  malformed config refuse as today on every EC-HOLD-1 case. The agent-harness#1602 seam
  tests pass unmodified.
- **EC-HOLD-6 (managed).** The eight F0 tests, unmodified. Appended: an unqualified managed
  subject with a member in the vendor store and in `held/` — both paths raise today's
  refusal and the candidate and directory openers record zero calls; the same through a
  symlink alias of the managed root and of the subject; a managed subject removed after
  resolution is still classified managed (no hold); a PATH `agy` that is the guarded
  frontdoor is skipped on route 2; a PATH `agy` outside the managed root is standalone.
  Before SL-3: a held admission has `path is None`, and `_prepare_jailed_gemini` with a
  standalone subject and that admission raises `gemini_heartbeat_capability_unavailable`
  without calling `build_seat_jail`.
- **EC-HOLD-7 (order and budgets).** A newer vendor member beats an older cache member that
  has a newer mtime; 64 forged hint files naming newer versions with junk directories do
  not prevent admission of the catalog member; two directories for one version are taken in
  name order and a third is ignored; a directory with more than `MAX_DIR_ENTRIES` names is
  skipped; the result is identical with `os.scandir` reversed and shuffled; image reads
  never exceed `AUTH_READS + HINT_READS`; with three failing authenticated candidates above
  it, a fourth is not read. B1: after a hold admitted version X, a newer eligible candidate
  Y appears; the next hold in the same process admits Y; a candidate rejected by an earlier
  hold and since made eligible (its `failed` entry removed) is admitted.
- **EC-HOLD-8 (resources).** `VerifiedImage` creation and `close` are instrumented: never
  two images open; the subject's image is closed before the first candidate is opened.
  **H1:** on every refusal branch of §E2 (each never-eligible site, each subject reason with
  no candidate, a rejected candidate, a candidate raising mid-read, a cancellation, an
  `Admission` constructor failure) `/proc/self/fd` is as before the call. **H3:** the traced
  peak of a whole hold — subject refused, two candidates rejected, the third admitted, with
  24 MiB images — is under `OVERHEAD_CEILING` (2 MiB), on both paths; a static test that
  `agy_hold.py` names none of `_open_image`, `_read_image`, `from_bytes`, `realpath`.
  **H4:** with `agy_provenance.MAX_MEMBER_BYTES` patched on the module (never an alias) to
  N, a candidate of N bytes is read and one of N+1 is skipped, at `fstat` and when it grows
  while streaming, and the walk continues to the next candidate.
- **EC-HOLD-9 (filesystem).** Candidate `agy` is a symlink; version directory is a symlink;
  version directory swapped for a symlink between listing and open; a group-writable
  directory; a component not owned by uid 0 or the euid. B2, exactly: a different file
  renamed over the name after the first chunk is rejected and its bytes are not read in
  that walk; the name unlinked during the read is rejected; a rewrite in place is rejected;
  the untouched control is admitted.
- **EC-HOLD-12 and EC-HOLD-15 (status).** The B6 object for: hold disabled; managed subject
  (all routes `not_covered`, `candidate: null`, nothing opened); standalone with a release
  member (`state: "ready"`); standalone with a store-qualified candidate
  (`"pending_help_measurement"`, `_run_help` not called); standalone with none;
  `routes.jailed == "not_covered"` in this lane. No output contains "active" or "in use".
- **Config.** Defaults; `hold = false`; a non-boolean; `hold_deny` not a list of 64-hex
  strings; the keys in a repository config are rejected as `self_qualification` is.

### E4. Run list and stop rules

Run serially, without `-n`, under `timeout 600`, after a headroom check:

`tests/test_agy_hold.py tests/test_agy_hold_managed.py tests/test_seats_teamhost_gemini.py tests/test_agy_integrity_seat_admission.py tests/test_agy_static_integrity.py tests/test_agy_catalog_data.py tests/test_advisor_board_config.py tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_size_bounds.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py`,
then `tests/test_agy_self_qualification.py` as its own run, then
`timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract`.

Stop and report, without working around:

- any line of `panel_invoker.py`, `seat_jail.py` or `seat_subject.py` would have to change
  (SL-3 owns the first two; nothing owns the third);
- `tests/test_agy_qci.py`'s verdict-vector pin changes (AGYFRESH §3);
- a closed evidence schema rejects the three keys and its file is outside §E1;
- a §C row is missing or wrong.

Rollback: `[agy] hold = false` per host; revert globally. No state to clean.

## F. SL-3 JAILBIND

**Needs.** SL-0 merged (the roadmap permits the change), SL-1's report with every check
passing, SL-2 merged. If SL-1 stopped, this lane does not start.

### F1. Files

| File | Change |
|---|---|
| `src/panel_invoker.py` | `_prepare_jailed_gemini`, standalone branch only: for the launches SL-1's report allows (amendment §2.8), one `admission.image.reopen()` descriptor per jail, passed as `provider_fd`, in place of `realpath(admission.path)`; the admission is closed after both jails are built and on every earlier exit; `_JailedSeat` gains `admission_source`, `hold_reason`, `subject_image_sha256`; the jailed seat's evidence writes the three keys beside `provider_image_sha256`. The managed branch, including its digest gate, and `_require_canonical_jail` are byte-identical. |
| `src/seat_jail.py` | `build_seat_jail(..., provider_fd=None)`: the checks of amendment §2.8; `provider_path = "/proc/self/fd/<fd>"`; the 0555 mode if SL-1 recorded it as required; the descriptor joins `pass_fds`, is closed on a failed build and by `close_jail_fds`. `_owner_argv`, `jail_profile_digest`, `actual_profile_digest` and `expected_mount_points` are not edited. |
| `src/agy_hold.py` | `ROUTE_COVERAGE["jailed"] = True`. |
| `tests/test_agy_hold_jail.py` | SL-1's probe cases kept as regression guards; §F2 added. |
| `tests/test_agy_hold_managed.py` | the "before SL-3" refusal case becomes the covered case; the eight F0 tests byte-identical. |
| `tests/test_agy_hold.py` | status: `routes.jailed == "covered"`. |
| `tests/test_seat_jail.py`, `tests/test_panel_invoker.py`, `tests/test_gemini_seat_egress_1170.py`, `tests/test_seats_teamhost_integration.py`, `tests/test_seat_qualification_key.py` | only where a stub must follow. A test file outside this list that must change is named in the PR; if another lane owns it, stop. |
| `tests/test_agy_qci.py` | the source-hash supplement for `panel_invoker.py`, if it alone flags. |
| `tests/data/seat_launch_references.json`, `CONTRACTS.md`, the card, `CHANGELOG.md` | rows; the jailed route in the HOLD section; one entry. |

Not edited, by name: `seat_jail_qualification.py`, `seat_qualification_key.py`,
`seat_jail_autoqualify.py`, `seat_subject.py`, `seat_route.py`. The qualifier's
`_launch_probe` needs no work, because no canonical digest changes; §F2 proves that with
its real construction instead of assuming it.

### F2. Tests (`tests/test_agy_hold_jail.py`, names `test_ec_hold_13_…`, `test_ec_hold_14_…`)

Driven through the real `_prepare_jailed_gemini` with a standalone subject and the real
`build_seat_jail`, launched through the production owner chain and uid drop; the provider
is the stand-in. **The stand-in reports the SHA-256 of its own running image
(`/proc/self/exe`)**, so "what ran" is measured from the executing process, never from a
second process reading the pathname. Cases that launch bwrap skip, with a reason, on a host
that cannot jail; hosted CI must run them, and a run that skips them all is not a pass.

- **Same bytes.** Before mounting, the production and probe jails' descriptors have one
  `(st_dev, st_ino)` and hash to `_JailedSeat.image_sha256`; the stand-in executed in each
  jail reports that digest.
- **Evidence digest.** For a subject admission and for a held one, the launch evidence's
  `provider_image_sha256` equals the digest the executed stand-in reported; for the held
  one `provider_admission_source == "lkg"`, the reason and the subject digest are present.
- **Source mutation after admission.** The subject or candidate file is renamed away,
  unlinked, and rewritten in place after admission and before launch: the stand-in still
  executes, and the digest it reports is the admitted one.
- **Wrong or unsealed descriptor.** `provider_fd` that is a regular file on disk, an
  unsealed memfd, a memfd missing one seal, a sealed memfd with other bytes, a pipe, a
  closed number: each is `SeatSandboxRefused` (`identity`) and nothing launches.
  `provider_fd` with a dependency is refused.
- **Failed build.** The production build failing; the probe build failing after the
  production jail exists; `actual_profile_digest` raising: `/proc/self/fd` is as before the
  call and the admission is closed.
- **Cancellation.** During the login wait and between the two builds: the same.
- **Lifetime.** Each jail's descriptor is open through every launch of that jail (launched
  twice) and closed by `close_jail_fds`; closing the admission does not invalidate a jail.
- **Surviving descriptors.** The stand-in lists `/proc/self/fd`: the set equals exactly the
  profile's declared set (standard streams, and the token descriptor where the profile
  declares one). No image, bundle, seccomp or other descriptor survives.
- **Credential sentinel.** A sentinel is planted in the operator's Gemini credential file
  beside the fields the seat copy keeps, and another in the operator's environment. From
  inside the jail, as the seat uid, neither sentinel is readable at any path or present in
  the environment; the seat sees only the delivered access-only copy.
- **Owner-store sentinel.** A sentinel file is placed in `Store.host_dir` and one in
  `held/`. As the seat uid, opening either by its host path fails, and neither path is in
  mountinfo. The same for the vendor-store path the candidate came from.
- **Mount.** A write to `/seat/bin/gemini` fails; mountinfo equals `expected_mount_points`.
  If SL-1 recorded the 0555 requirement: the mode inside the jail is 0555, and an image
  that never entered a jail keeps the caps lane's 0500.
- **Launch scope.** With the ordinary default off (SL-1 recommended held only), a subject
  admission still binds its path and a held one binds the image; with it on, both bind the
  image. Whichever SL-1's report selected is the shipped default; the other is tested by
  patching the one switch.
- **Managed unchanged.** The eight F0 tests; a managed dependency never receives
  `provider_fd`; **unstubbed:** a managed-dependency jail built by the real
  `build_seat_jail` passes the real `_require_canonical_jail`.
- **Qualifier unchanged.** For each profile whose jail the qualifier builds, the real
  `seat_jail_qualification._launch_probe` construction, with a harmless stand-in, passes
  the real `_require_canonical_jail`, and its actual digest equals that of a sealed-image
  jail. No pass is recorded and no qualification runs.
- **Held, end to end.** An unqualified standalone subject with a member in the vendor
  store: the jailed route launches the member, and the stand-in reports the member's
  digest.
- **EC-HOLD-14.** `actual_profile_digest(jail) == jail_profile_digest("gemini")` for a
  sealed-image jail; the canonical digest of every registered leg, and the key from
  `key_for_launch`, equal their values on the base tree (pinned in the test as inputs).

### F3. Cost, release, stop rules

- **Memory.** None beyond the admission's memfd.
- **Jail requalification.** None, because no canonical digest or key changes. That is what
  EC-HOLD-14 proves; it is not assumed.
- **Release hold G-REL.** No tag, PyPI publication or deployment may contain this lane
  until SL-1's recorded P3 and this lane's EC-HOLD-14 cases, run in hosted CI on the final
  head, show every canonical digest and key unchanged (amendment §1.4). The release owner
  is the Agent-Harness Exec, who records the hold. The PR's first paragraph states the hold
  and links both proofs. If any deployment consumes `main` directly, the merge waits too.
- **agy requalification.** None intended; `tests/test_agy_qci.py` decides (AGYFRESH §3).
- **Run.** `tests/test_agy_hold_jail.py tests/test_agy_hold_managed.py tests/test_agy_hold.py tests/test_seat_jail.py tests/test_gemini_seat_egress_1170.py tests/test_seat_qualification_key.py tests/test_seats_teamhost_gemini.py tests/test_seats_teamhost_integration.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py`,
  serially under `timeout 600`; `tests/test_panel_invoker.py` as its own run; then
  `--contract`.
- **Stop.** Any canonical digest or qualification key moves; `actual_profile_digest`,
  `_require_canonical_jail`, the qualifier or the managed branch would need an edit; any
  jail property other than the provider bind's source would have to change; the form does
  not behave as SL-1 recorded.
- **Rollback.** Revert; the route returns to refusing a held admission and status to
  `not_covered`. No key changes in either direction.

## G. SL-4 HOLD-CACHE

**Files.** `src/agy_hold.py` (`retain`, prune, corrupt-file unlink, `clear_held`),
`src/agy_qualification.py` (the `retain` call in `admit_seat(first_use=True)` after a
subject admission and after the first-use lock is released, gated by B7; `clear --all`),
`tests/test_agy_hold_cache.py` (new), `tests/data/seat_launch_references.json`,
`CONTRACTS.md`, `CHANGELOG.md`.

**Tests** (`test_ec_hold_10_…`). Retain writes `held/<sha256>`, mode 0600, in a 0700
directory, with exact bytes, streamed (traced peak under `OVERHEAD_CEILING`); a second
retain is a no-op; a third image prunes by authenticated version, not mtime, and never the
one just retained, even when it is the oldest; a file with no authenticated version is
pruned first; a file whose content does not hash to its name is unlinked and skipped;
`retain` with the store lock held elsewhere skips and the admission still returns; `retain`
on a read-only directory swallows the error; a symlink named like a digest is neither
followed nor unlinked through; a name replaced between judgement and unlink is not
unlinked; **concurrent** retain and `clear --all` in two threads leave a complete file or
none; a reader holding a file that is pruned or cleared rejects it and continues, and with
no other candidate that hold raises the original refusal (the stated limit of B2);
`Store.status()` stays `ok` with `held/` present; `clear` without `--all` leaves the cache;
B7: no file for a managed subject or with the hold disabled; no retain on a spawn admission
or after a held admission; B1: a newer image arriving through `retain` wins the next hold.
End to end, with no vendor store: a retained image is the hold for a later unqualified
subject on route 1 and, through `_prepare_jailed_gemini`, on route 4 — the cache file stays
0600 and is never bound into the jail.

**Run.** `tests/test_agy_hold_cache.py tests/test_agy_hold.py tests/test_agy_hold_jail.py tests/test_agy_hold_managed.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py`,
then `tests/test_agy_self_qualification.py`, then `--contract`.

**Stop rules.** As §E4. Rollback: revert; `clear --all` or removing `held/` frees the disk.

## H. SL-5 FAILEXP

Changes, tests and commands: `plans/detailed-agyfresh-failexp-20261120-0114.md`.

## I. Handoffs from the RESTORE caps lane

| Handoff | Where it is carried |
|---|---|
| H1 image ownership, leak tests on every refusal branch | §E2, EC-HOLD-8 |
| H2 classify the seal failure and the unavailable seal ABI before normalization | §E2 step 1, EC-HOLD-2 (two separate cases, both paths, zero candidate opens) |
| H3 one reader for candidates; `OVERHEAD_CEILING` on the hold path | §E2, EC-HOLD-8 |
| H4 bounds at call time; oversized candidate is a local skip | §E2, EC-HOLD-8 |
| H5 replacement detection | B2, EC-HOLD-9 |
| H6 the `_open_image_fd` inventory row; append-only shared files; the contract baseline after the caps lane's repin | §E1; plan Execution Notes; amendment preamble |
| H7 PROVFWD and ROLLJOB keep `_ExpandedReader` and `_bounded_tarinfo`; ROLLJOB owes streaming for `fetch_member(keep_bytes=True)` | not this phase: recorded in the plan's Execution Notes as passed to those phases' plans |

## J. Open questions

Q1 of r1 (the jailed standalone route) is decided: SL-1 and SL-3. Remaining, none blocking:

- **Q-A.** Whether ordinary (non-hold) jailed launches also bind the sealed image is
  decided by SL-1's evidence on supported configurations (amendment §2.8). If the report
  recommends held only, a second-host run to close the gap is a separate request.
- **Q-B.** `requalify_once` still reads the subject once into memory to key its process
  memo. It is not evidence that everything streams; a streamed digest is a follow-up.
- **Q-C.** `hold_status` may read up to five images. The doctor computes it only when the
  Gemini verdict is not `admits`, and it mutates nothing.
- **Q-D.** If SL-1 stops, the jailed standalone route stays not covered and the owner
  chooses between a new amendment (a route-aware canonical for a data bind) and the gap.
