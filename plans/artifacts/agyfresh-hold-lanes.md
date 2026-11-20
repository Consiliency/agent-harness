# AGYFRESH HOLD lanes r2: frozen detail for the HOLD phase plan

Detail for `plans/phase-plan-v1-agyroll-HOLD.md` (lanes SL-0 to SL-6) and
`plans/detailed-agyfresh-failexp-20261120-0114.md` (SL-5 FAILEXP). The design is
`plans/artifacts/agyfresh-contract.md` (AGYFRESH) **as amended by**
`plans/artifacts/agyfresh-hold-amendment.md` (the amendment); this file adds only what a
lane needs to build and test it. Where they disagree, the amended contract governs. Goal
IDs are defined in the roadmap (EC-HOLD-13 to -15 by the amendment) and are only
referenced.

r2 follows the review of r1 (findings R1–R3) and the owner's decision that the jailed
standalone seat runs the admitted sealed image.

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

**What it is.** A scratch lane with no production change. It decides the mount form of
amendment §2.8 and whether the canonical Gemini jail digest changes. It runs bwrap locally
with a stand-in executable (the conformance stand-in, `tests/fixtures/agy_conformance/`);
no agy, no network, no credential, no provider call, no host other than the one it runs on.

**Files.** `tests/test_agy_hold_jail.py` (new; probe cases that skip, with a reason, where
the host cannot run the jail) and `plans/evidence/agyfresh-jailbind-feasibility.md` (the
result).

**Questions, each answered by an observed run, not by reading code:**

| # | Question | How |
|---|---|---|
| P1 | Does bwrap mount `--ro-bind /proc/self/fd/<fd> /seat/bin/gemini` when `<fd>` is a sealed memfd from `VerifiedImage.from_fd`, in the production owner invocation? | build the real owner argv through `seat_jail._owner_argv`, with the fd in `pass_fds`; launch |
| P2 | Can the seat uid execute it? The memfd is mode 0500 and owned by the operator. If not, does it with the mode set to 0555 on that memfd, and what else observes that mode? | run the stand-in after the uid drop; record `stat` inside the jail |
| P3 | With P1 and P2: is `actual_profile_digest(jail) == jail_profile_digest("gemini")` with `provider_path = "/proc/self/fd/<fd>"` and no change to `actual_profile_digest`? Does `expected_mount_points` still hold? | call both; compare mountinfo with the expectation |
| P4 | Form B: does `--perms 0555 --ro-bind-data <fd> /seat/bin/gemini` execute as the seat uid? How many times is one `SeatJail` launched, and does a second launch need the descriptor rewound? What does one jail's copy cost in memory? | launch twice; measure the jail's tmpfs use |
| P5 | In either form, inside the jail: is the mount read-only and not writable by the seat uid; is any image descriptor open in the provider process; is any host provider, store or vendor path visible? | list `/proc/self/fd` and mountinfo from the stand-in |
| P6 | Do the probe jail and the production jail, each with its own `reopen()` descriptor, see the same inode and bytes? | hash `/seat/bin/gemini` inside both |

**Decision rule.** Form A if P1, P2 and P3 hold, without weakening anything P5 checks.
Otherwise form B if P4 and P5 hold; the report then states the new canonical digest's
cause and that roadmap step O4 applies. Otherwise stop: the route stays not covered and the
coordinator is told. The report records the kernel and bwrap versions and says plainly
that one host was probed.

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

**Needs.** SL-0 merged (the roadmap permits the change), SL-1's result, SL-2 merged.

### F1. Files

| File | Change |
|---|---|
| `src/panel_invoker.py` | `_prepare_jailed_gemini`, standalone branch only: no `realpath(admission.path)`; one `admission.image.reopen()` descriptor per jail, passed as `provider_fd`; the admission is closed after both jails are built and on every earlier exit; `_JailedSeat` gains `admission_source`, `hold_reason`, `subject_image_sha256`; the jailed seat's evidence writes the three keys beside `provider_image_sha256`. The managed branch, including its digest gate, is byte-identical. Form B only: rewind the descriptor before each launch. |
| `src/seat_jail.py` | `build_seat_jail(..., provider_fd=None)`: the checks of amendment §2.8; `provider_path` and the owner argv per the selected form; the descriptor joins `pass_fds`, is closed on a failed build and by `close_jail_fds`. Form B only: the Gemini owner argv and `expected_mount_points`; no change to `actual_profile_digest`'s normalization. |
| `src/agy_hold.py` | `ROUTE_COVERAGE["jailed"] = True`. |
| `tests/test_agy_hold_jail.py` | SL-1's probe cases kept as regression guards; §F2 added. |
| `tests/test_agy_hold_managed.py` | the "before SL-3" refusal case becomes the covered case; the eight F0 tests byte-identical. |
| `tests/test_agy_hold.py` | status: `routes.jailed == "covered"`. |
| `tests/test_seat_jail.py`, `tests/test_panel_invoker.py`, `tests/test_gemini_seat_egress_1170.py`, `tests/test_seats_teamhost_integration.py`, `tests/test_seat_qualification_key.py` | only where a stub or expectation must follow; form B: the Gemini canonical digest expectations. A test file outside this list that must change is named in the PR; if another lane owns it, stop. |
| `tests/test_agy_qci.py` | the source-hash supplement for `panel_invoker.py`, if it alone flags. |
| `tests/data/seat_launch_references.json`, `CONTRACTS.md`, the card, `CHANGELOG.md` | rows; the jailed route in the HOLD section; one entry. |

### F2. Tests (`tests/test_agy_hold_jail.py`, names `test_ec_hold_13_…`, `test_ec_hold_14_…`)

Driven through the real `_prepare_jailed_gemini` with a standalone subject and the real
`build_seat_jail`; only the provider launch is a stand-in. Cases that launch bwrap skip,
with a reason, on a host that cannot jail; hosted CI must run them, and a lane whose CI
skips them all is not accepted.

- **Same bytes.** The production and probe jails' provider descriptors have one
  `(st_dev, st_ino)` and hash to `_JailedSeat.image_sha256`; inside each jail
  `/seat/bin/gemini` hashes to it.
- **Evidence digest.** For a subject admission and for a held one, the launch evidence's
  `provider_image_sha256` equals the hash of what the stand-in read at `/seat/bin/gemini`;
  for the held one `provider_admission_source == "lkg"`, the reason and the subject digest
  are present.
- **Source mutation after admission.** The subject or candidate file is renamed away,
  unlinked, and rewritten in place after admission and before launch: the jail still runs
  the admitted bytes.
- **Wrong or unsealed descriptor.** `provider_fd` that is a regular file on disk, an
  unsealed memfd, a memfd missing one seal, a sealed memfd with other bytes, a pipe, a
  closed number: each is `SeatSandboxRefused` (`identity`) and nothing launches.
  `provider_fd` with a dependency is refused.
- **Failed build.** The production build failing; the probe build failing after the
  production jail exists; `actual_profile_digest` raising: `/proc/self/fd` is as before the
  call and the admission is closed.
- **Cancellation.** During the login wait and between the two builds: the same.
- **Lifetime.** Each jail's descriptor is open through every launch of that jail and closed
  by `close_jail_fds`; closing the admission does not invalidate a jail.
- **Inside the jail.** As the seat uid: `/seat/bin/gemini` executes; a write to it fails;
  the provider process has no descriptor on the image; no host provider path, store, `held/`
  or vendor path is in mountinfo; `expected_mount_points` holds.
- **Managed unchanged.** The eight F0 tests; a managed dependency never receives
  `provider_fd`.
- **Held, end to end.** An unqualified standalone subject with a member in the vendor
  store: the jailed route launches the member.
- **EC-HOLD-14.** `actual_profile_digest(jail) == jail_profile_digest("gemini")` for a
  sealed-image jail; the canonical digests of every other registered leg equal their values
  before the lane (pinned in the test from the base tree, as inputs); form A: the Gemini
  canonical digest equals its base value too; form B: it differs, the test pins both, and
  no pass record for the old digest is accepted for the new jail.

### F3. Cost, requalification, stop rules

- **Memory.** Form A: none beyond the admission's memfd. Form B: one image copy per jail
  while it lives (amendment §2.1).
- **Jail requalification.** Form A: none. Form B: roadmap step O4, owner-gated, outside
  this lane. The lane's tests stub the qualifier (`conftest`'s
  `_no_real_first_use_jail_qualification`); the PR states in its first paragraph that
  installing it makes hosts requalify the Gemini jail on first use, and the lane does not
  release or install it.
- **agy requalification.** None intended; `tests/test_agy_qci.py` decides (AGYFRESH §3).
- **Run.** `tests/test_agy_hold_jail.py tests/test_agy_hold_managed.py tests/test_agy_hold.py tests/test_seat_jail.py tests/test_gemini_seat_egress_1170.py tests/test_seat_qualification_key.py tests/test_seats_teamhost_gemini.py tests/test_seats_teamhost_integration.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py`,
  serially under `timeout 600`; `tests/test_panel_invoker.py` as its own run; then
  `--contract`.
- **Stop.** The managed branch, the projection, the digest gate or any jail property other
  than the provider bind would have to change; another leg's canonical digest moves;
  `actual_profile_digest` would need a new normalization; the selected form does not behave
  as SL-1 recorded.
- **Rollback.** Revert; the route returns to refusing a held admission and status to
  `not_covered`. After form B and O4, a revert makes hosts requalify once more.

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

- **Q-A.** SL-3 binds the sealed image for every standalone Gemini jail, subject or held,
  because one mechanism is simpler to prove than two and the evidence digest then always
  describes the executed bytes. It changes the ordinary (non-hold) jailed launch too.
- **Q-B.** `requalify_once` still reads the subject once into memory to key its process
  memo. It is not evidence that everything streams; a streamed digest is a follow-up.
- **Q-C.** `hold_status` may read up to five images. The doctor computes it only when the
  Gemini verdict is not `admits`, and it mutates nothing.
- **Q-D.** If SL-1 selects form B, the release that carries SL-3 needs the owner's O4
  grant first.
