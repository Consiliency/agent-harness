# AGYFRESH HOLD lanes: frozen detail for the HOLD phase plan

Detail for `plans/phase-plan-v1-agyroll-HOLD.md` (lanes SL-1 HOLD-CORE, SL-2 HOLD-CACHE) and
`plans/detailed-agyfresh-failexp-20261120-0114.md` (SL-3 FAILEXP). The design is
`plans/artifacts/agyfresh-contract.md` (AGYFRESH); this file adds only what a lane needs to
build and test it, and records the options AGYFRESH §6 tells the phase plan to choose.
Where this file and AGYFRESH disagree, AGYFRESH governs, except §B below, which AGYFRESH §6
delegates here. Goal IDs are defined in `specs/phase-plans-agyroll-v1.md` and are only
referenced.

Paths are under `phase-loop-runtime/` unless they name another root; `src/` means
`src/phase_loop_runtime/`. `gh` is `gemini_heartbeat`, `q` is `agy_qualification`.

## A. Base

- SL-1 builds on the RESTORE caps lane (`VerifiedImage.from_fd`, `gh._open_image_fd`,
  `gh._open_image`, `q.lookup` accepting and owning a `gh.VerifiedImage`). If that lane has
  not merged when SL-1 starts, SL-1 branches from it and rebases after it merges.
- SL-1 also carries `tests/test_agy_hold_managed.py` from the feasibility lane (branch
  `t3/agyfresh-f0-probe`), unmodified, as the EC-HOLD-6 regression guard.
- SL-2 starts after SL-1 merges, SL-3 after SL-2. Each lane is one PR.

## B. Options chosen by this plan

### B1. Selection promise (AGYFRESH §6.2)

- The walk of §2.4 runs in full on **every** hold: the candidate list is rebuilt (listing
  and hint files only) and walked in the total order. Nothing admitted earlier is tried
  first. The "tries the memoized name first" sentence of §2.4 is not implemented.
- "Always examined" means reserved capacity: `AUTH_READS` image reads are reserved for
  authenticated candidates and are spent only as earlier candidates fail. The first
  candidate that passes §2.3 ends the walk.
- **The only memo is a rejection memo**, process-local, under the `agy_hold` module lock:
  `(st_dev, st_ino, st_size, st_mtime_ns) -> image sha256` for files this process has read
  and rejected. On a later walk a candidate whose opened descriptor has the same tuple is
  judged from the memoized digest on the non-executing predicates (§2.3 step 1, step 2, and
  the `failed`/`provenance` half of step 3). If they still reject, the image is not read
  again, and the candidate **still spends its read from its class budget**. If they no
  longer reject, the candidate is read and judged normally.
- Why this cannot change the order: the memo never admits, never reorders and never changes
  which candidates fall inside the budgets. It can only replace a read whose outcome is
  already known. A stale memo entry can cost availability for one candidate, never
  integrity.
- Frozen test (SL-1): after a hold admitted version X, a newer eligible candidate Y appears
  (new file); the next hold in the same process admits Y. Mirror test (SL-2) with Y arriving
  through `retain`.

### B2. Replacement detection (AGYFRESH §6.3): option (b)

After `VerifiedImage.from_fd` returns for a candidate, and before §2.3 is applied:

1. `os.fstat` of the opened descriptor must equal the pre-read
   `(st_dev, st_ino, st_size, st_mtime_ns)` (§2.5, unchanged; catches an in-place rewrite).
2. `os.stat(<file name>, dir_fd=<the opened candidate directory>, follow_symlinks=False)`
   must name a regular file with the opened descriptor's `(st_dev, st_ino)`. A different
   inode, a non-regular file or `ENOENT` rejects the candidate and closes its image.

Stated limit: a swap that is reverted before step 2 is not observed. That is harmless: the
only bytes that can run are the sealed memfd's, and they run only if their digest passes
§2.3. Option (a) is not implemented and not tested. Consequence for the cache: a file
pruned or cleared while it is being read is rejected and the walk continues; a pruned file
always sorts below the files that displaced it.

The anchored traversal, the no-follow opens and the ownership and mode checks of §2.5 stay.

### B3. Managed-release skip (rulings R-F0-1, R-F0-2)

- One predicate at the one boundary: in `admit_seat`, a subject is *managed* when
  `seat_subject._names_managed_root(Path(resolved subject path))` is true. It is a read-only
  call into the resolver; `seat_subject.py` is not edited. `MANAGED_RELEASES_ROOT` is read at
  call time, so the F0 fixtures' substitution works.
- For a managed subject, on `_SubjectNotAdmitted`: no candidate list is built, no cache or
  vendor directory is opened, and `refusal` is raised unchanged. `retain` is not called.
  The agent-harness#1602 seam inside `q.lookup` is untouched, so the F0 probe tests pass
  unmodified.
- `status` (and SL-3's doctor row) report `coverage: "not_covered_managed_release"`,
  rendered "not covered (managed release)", with `held: null` and no search.
- R-F0-2: because the skip sits in `admit_seat`, every route in §C gets it, including the
  non-jailed heartbeat route, whose subject is PATH's `agy`. There the guarded frontdoor and
  `native/agy` resolve below the managed root and are skipped. A PATH `agy` outside the
  managed root is a standalone subject under the resolver's own classification and is
  covered as any standalone subject; no managed projection or authority is consulted on that
  route, and none is claimed. Open question Q2 asks whether a host-level skip is wanted
  instead.

### B4. What a held admission carries

- `admit_held` returns `gh.Admission(image, help_sha256, admission_class, None,
  source="lkg")`: **`path` is `None`**, never the subject's path and never a candidate path.
- Reason: the jailed standalone route (`panel_invoker._prepare_jailed_gemini`) executes by
  path. It binds `os.path.realpath(admission.path)` at `/seat/bin/gemini`
  (`seat_jail._owner_argv`, `provider_bind`), after the admission is closed. With the
  subject's path there, the jail would run the unadmitted subject under the held image's
  evidence. With `None`, that route's existing `admission.path is None` check refuses with
  today's code. No jail, authority or `panel_invoker.py` line changes.
- Consequence, stated: the hold is effective on the routes that execute the admitted memfd
  (§C rows 1, 2, 5). The jailed standalone route is **not covered** by SL-1. Open question
  Q1.

### B5. Reader and writer split between SL-1 and SL-2

SL-1 implements the whole candidate list of §2.4, **including reading `held/`** (tests place
files by hand), so the order and budget goals are provable in SL-1. SL-2 implements only
what writes: `retain`, pruning, corrupt-file removal, `clear --all`, and the `retain` call
site. `retain` is a no-op in SL-1.

### B6. Status shape (amends AGYFRESH §2.6, in SL-1)

```
"hold": {"enabled": bool,
         "coverage": "standalone" | "not_covered_managed_release",
         "held": {"origin", "version", "image_sha256", "admission_class"
                  [, "pending": "help_measurement"]} | null}
```

`pending` is present only for a candidate that passed the store half of §2.3 step 3: status
never measures help, so it does not claim that admission. `held` is `null` when the hold is
disabled, when the subject is managed, and when no candidate passes.

### B7. Retention gates (SL-2)

`retain` is called only when the hold is enabled and the subject is not managed. A host
that cannot use a held image writes none.

## C. Routes that admit a seat image

Enumerated on the caps-lane tree. SL-1 re-checks this table by grep
(`gemini_heartbeat.admit(`, `admit_for_seat(`, `requalify_once(`, `ensure_admitted(`,
`owned_profile(`, `require_capability(`) and stops if a row is missing or a row's "executes"
column is wrong.

| # | Route and call site | Subject | Executes | Hold in SL-1 |
|---|---|---|---|---|
| 1 | Seat profile launch and credential refresh: `agy_integrity.admit_for_seat` (two sites in `panel_invoker.seat_profile`) | caller's executable | admitted memfd (`image.reopen()`) | covered; managed subject skipped |
| 2 | Non-jailed heartbeat: `gh.require_capability` and `gh.owned_profile` without an admission (`panel_invoker` brokered Gemini leg and its route check; `president_adapter`) | PATH `agy` | admitted memfd | covered for a non-managed subject; managed subject skipped (B3) |
| 3 | Jailed review seat, managed dependency: `panel_invoker._prepare_jailed_gemini` | `dependency.subject_source` | the release projection | skipped; the digest gate and jail binding are unchanged (EC-HOLD-6) |
| 4 | Jailed review seat, standalone: same function | resolved subject | **the path** `realpath(admission.path)` | not covered: `path=None` refuses as today (B4) |
| 5 | Board preflight and `agy-qualification run`: `q.requalify_once` → `ensure_admitted` / `gh.admit` | resolved subject | nothing (admission is closed) | covered; first use for the subject runs first |
| 6 | Help measurement: `q._run_help` → `gh.owned_profile(admission=...)` | given admission | given memfd | not an admission site |
| 7 | Executor and canary: `agy_integrity.check(path)` without env, `trusted_command`, `admitted_command`, `agy_canary_evidence` | PATH `agy` | admitted memfd or path | never holds (AGYFRESH §2.2) |
| 8 | Reports: `q.admission_verdict` (`seat_admission`, `status`) | resolved subject | — | `execute=False` unchanged (EC-HOLD-5); `execute=True` goes through row 1 |

## D. SL-1 HOLD-CORE

### D1. Files

| File | Change |
|---|---|
| `src/agy_hold.py` (new) | §2.4 constants and `HeldCandidate`; candidate list (cache reader, vendor authenticated, vendor hinted); anchored descriptor-relative opens (§2.5); the walk with split budgets, B1 memo, B2 check; module lock; `hold_enabled()`, `hold_deny()`; `retain` no-op. Standard library plus `gh`; outside `ROUTE_CORE`. The §2.3 predicate is passed in as a callable, so this module does not import `q`. |
| `src/agy_qualification.py` | `_SubjectNotAdmitted`; `admit_seat` (AGYFRESH §2.2 signature); `admit_held` (§2.3 over the walk); `ensure_admitted` delegating with its signature kept; `hold_status(env, subject_path)` for `status` and SL-3; `cli_main` status object. `lookup` keeps its signature, its opt-out-first order, its image ownership and the agent-harness#1602 seam. |
| `src/gemini_heartbeat.py` | `catalog_members(path=None) -> list[dict]` (never raises; `load_catalog` rebuilt on it); `admit` = candidate-token case, then `admit_seat(first_use=False)`, refusal mapped to `_CAPABILITY`; `owned_profile` evidence keys (§2.6). |
| `src/agy_integrity.py` | `check` with env delegates to `admit_seat`; typed egress, quiescence and jail exceptions pass through as today; evidence keys. `check` without env unchanged. |
| `src/advisor_board/config.py` | `[agy] hold`, `[agy] hold_deny` in the known keys; `load_agy_hold`, `load_agy_hold_deny` (user file only; any error disables the hold). |
| `src/advisor_board/fixtures/advisor-boards.example.toml` | the two keys, commented. |
| `tests/conftest.py` | autouse: `agy_hold.VENDOR_STORES = ()` and an empty rejection memo, so no test reads the host's real store. |
| `tests/test_agy_hold.py` (new) | §D3. |
| `tests/test_agy_hold_managed.py` (new here) | the eight feasibility tests byte-identical; appended: the managed-skip and jailed-standalone cases of §D3. |
| `tests/test_agy_catalog_data.py` | `catalog_members`. |
| `tests/test_advisor_board_config.py` | the two keys. |
| `tests/test_agy_self_qualification.py`, `tests/test_agy_integrity_seat_admission.py`, `tests/test_agy_static_integrity.py`, `tests/test_seats_teamhost_gemini.py`, `tests/test_gemini_heartbeat_bootstrap.py` | only where a hook or stub must follow the moved read path; each keeps its intent, and the agent-harness#1602 seam tests are not edited. |
| `tests/data/seat_launch_references.json` | one row per new file read, `os.open` and `scandir` site. |
| `src/advisor_board/CONTRACTS.md` | new section "HOLD — availability floor". |
| `docs/advisor-board-capabilities-card.md` | the hold, its two config keys, what is not covered. |
| `CHANGELOG.md` | one `[Unreleased]` entry. |
| `plans/artifacts/agyfresh-contract.md` | §2.6 (B6), §2.9 (outcome and skip), §2.4 last sentence (B1), §2.5 read bullet (B2), §2.2 handler (B3, B4). |
| `specs/phase-plans-agyroll-v1.md` | External Inputs row: the AGYFRESH sha256 as committed. Nothing else. |
| `plans/phase-plan-v1-agyroll-HOLD.md` | frontmatter `roadmap_sha256` re-stamped after the row above. |

### D2. `admit_seat`, in order

1. Never-eligible, raised at their own sites with their own types, before and outside the
   hold handler: `_local_capabilities()` failure; unsupported platform; no provider
   (`shutil.which` is `None`); a memfd seal failure (`AgyCanaryEvidenceError` from
   `from_fd`). The caps lane's `check` maps a seal failure to `AgyImageUnqualified` **after**
   `admit_seat` raised it; that mapped refusal is never a hold reason.
2. Open and stream the subject. `OSError` → `subject_unreadable`; not regular →
   `subject_not_regular`; over the bound, at `fstat` or while streaming →
   `subject_over_bound`. `subject_sha256` is `None` for all three.
3. Release member → admit, source `subject`, before any config or store read.
4. Opt-out → `self_qualification_disabled`.
5. `lookup` (it owns the image). `failed` entry → `subject_failed`; a miss →
   `subject_unqualified` (the miss's image is closed here unless first use takes it);
   unsafe store → `store_unsafe`. Typed egress, quiescence, jail and cancellation outcomes of
   the help measurement propagate. A seam admission from `lookup` is returned unchanged.
6. `first_use=True` only: today's first-use body. Its refusals map to
   `provenance_unverified`, `provenance_unavailable`, `first_use_failed`,
   `first_use_unavailable`. `CANCELLED` propagates.
7. Handler, on `_SubjectNotAdmitted` only: close the subject image; if the subject is
   managed (B3) or the hold is disabled, raise `refusal`; else `admit_held`; with no
   candidate, raise `refusal`. `refusal` is the exact exception today's code raises at that
   point.

In the candidate loop a candidate-local error (`OSError`, a bad digest, a predicate miss)
skips that candidate. Cancellation and the typed egress, quiescence and jail outcomes of a
candidate's help measurement propagate and close the candidate.

### D3. Tests

Test functions are named `test_ec_hold_<n>_…` so each goal has a `-k` selector. "Both
paths" is `admit_seat(first_use=True)` and `agy_integrity.admit_for_seat` (spawn).
Every goal has at least one case that enters through those production functions over files
on disk; cases that call `agy_hold` directly are additional, never the only proof.

- **EC-HOLD-1 (coverage).** Both paths, a held release member present, the subject is:
  over the bound; unreadable (mode 000); removed after resolution; replaced by a directory;
  unqualified with no record; provenance without `qualified`; carrying a `failed` entry;
  self-qualification off; first use returning `failed`; first use returning transient;
  provenance unverifiable. Each admits the member with `provider_admission_source ==
  "lkg"`, the §2.2 reason, and `provider_subject_image_sha256 is None` for the first four.
  Each again with no candidate: the original exception type and message. `gh.admit` and
  `gh.owned_profile` (route 2) once each.
- **EC-HOLD-2 (propagation).** A member present: `_local_capabilities` failing; a seal
  failure, on both paths (through `check` it is `AgyImageUnqualified` and no candidate was
  opened); `CANCELLED` in first use; `EgressUnavailable`; `GeminiQuiescenceError`;
  `ProviderProcessGroupQuiescenceError`; `SeatSandboxRefused`; unsupported platform; no
  `agy` on PATH; `seat_provider_unavailable` from the CLI. Each raises its own type; a spy
  on the candidate opener records zero calls. The same typed outcomes raised by a
  **candidate's** help measurement propagate.
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
- **EC-HOLD-6 (managed).** The eight feasibility tests, unmodified. Appended: a managed
  subject that is unqualified, with a member in the vendor store and in `held/` — both paths
  raise today's refusal and the candidate opener and directory opener record zero calls;
  `hold_status` reports `not_covered_managed_release` with `held: null`; a PATH `agy` that
  is the guarded frontdoor is skipped on route 2. Jailed standalone (B4): a held admission
  has `path is None`, and `_prepare_jailed_gemini` with a standalone subject and that
  admission raises `gemini_heartbeat_capability_unavailable` without calling
  `build_seat_jail`.
- **EC-HOLD-7 (order and budgets).** A newer vendor member beats an older cache member that
  has a newer mtime; 64 forged hint files naming newer versions with junk directories do
  not prevent admission of the catalog member; two directories for one version are taken in
  name order and a third is ignored; a directory with more than `MAX_DIR_ENTRIES` names is
  skipped; the result is identical with `os.scandir` reversed and shuffled; image reads
  never exceed `AUTH_READS + HINT_READS`; with three failing authenticated candidates above
  it, a fourth is not read. B1: the newer-candidate-after-memo case; a memo-judged candidate
  spends its budget and is not re-read; a memo entry whose predicates no longer reject is
  read again.
- **EC-HOLD-8 (resources).** `VerifiedImage` creation and `close` are instrumented: never
  two images open; the subject's image is closed before the first candidate is opened; after
  a rejected candidate, a candidate raising mid-read and a cancellation, `/proc/self/fd` is
  as before the call.
- **EC-HOLD-9 (filesystem).** Candidate `agy` is a symlink; version directory is a symlink;
  version directory swapped for a symlink between listing and open; a group-writable
  directory; a component not owned by uid 0 or the euid. B2, exactly: a different file
  renamed over the name after the first chunk is rejected and its bytes are not read in
  that walk; the name unlinked during the read is rejected; a rewrite in place is rejected;
  the untouched control is admitted.
- **EC-HOLD-12 (status).** The B6 object for: disabled; managed; standalone with a member;
  standalone with a store-qualified candidate (`pending`); standalone with none.
- **Config.** Defaults; `hold = false`; a non-boolean; `hold_deny` not a list of 64-hex
  strings; the keys in a repository config are rejected as `self_qualification` is.

### D4. Run list and stop rules

Run, serially, under `timeout 600` (the locked venv has no xdist; pass `-n 0` only where it
is installed):

`tests/test_agy_hold.py tests/test_agy_hold_managed.py tests/test_seats_teamhost_gemini.py tests/test_agy_integrity_seat_admission.py tests/test_agy_static_integrity.py tests/test_agy_catalog_data.py tests/test_advisor_board_config.py tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_size_bounds.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py`,
then `tests/test_agy_self_qualification.py` as its own run, then
`timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract`.

Stop and report, without working around:

- any authority, projection or jail check, or any line of `panel_invoker.py`, `seat_jail.py`
  or `seat_subject.py`, would have to change for a test to pass;
- `tests/test_agy_qci.py`'s verdict-vector pin changes (AGYFRESH §3; the source-hash
  supplement alone is updated as a reviewed change, with no validator bump);
- a closed evidence schema rejects the three keys: add them there and name the file in the
  PR; if that file is outside §D1, stop;
- a §C row is missing or wrong.

Rollback: `[agy] hold = false` per host; revert globally. No state to clean.

## E. SL-2 HOLD-CACHE

**Files.** `src/agy_hold.py` (`retain`, prune, corrupt-file unlink, `clear_held`),
`src/agy_qualification.py` (the `retain` call in `admit_seat(first_use=True)` after a
subject admission and after the first-use lock is released, gated by B7; `clear --all`),
`tests/test_agy_hold_cache.py` (new), `tests/data/seat_launch_references.json`,
`CONTRACTS.md` (subsection of SL-1's section), `CHANGELOG.md`.

**Tests** (`test_ec_hold_10_…`). Retain writes `held/<sha256>`, mode 0600, in a 0700
directory, with exact bytes; a second retain is a no-op; a third image prunes by
authenticated version, not mtime, and never the one just retained; a file with no
authenticated version is pruned first; a file whose content does not hash to its name is
unlinked and skipped; `retain` with the store lock held elsewhere skips and the admission
still returns; `retain` on a read-only directory swallows the error; a symlink named like a
digest is neither followed nor unlinked through; a name replaced between judgement and
unlink is not unlinked (§2.5 stat match); **concurrent** retain and `clear --all` in two
threads leave a complete file or none; a reader holding a file that is pruned rejects it
and continues (B2); `Store.status()` stays `ok` with `held/` present; `clear` without
`--all` leaves the cache; B7: no file for a managed subject or with the hold disabled; no
retain on a spawn admission or after a held admission; end to end, with no vendor store, a
retained image is the hold for a later unqualified subject; B1 mirror case.

**Run.** `tests/test_agy_hold_cache.py tests/test_agy_hold.py tests/test_agy_hold_managed.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py`,
then `tests/test_agy_self_qualification.py`, then `--contract`.

**Stop rules.** As §D4. Rollback: revert; `clear --all` or removing `held/` frees the disk.

## F. SL-3 FAILEXP

Changes, tests and commands: `plans/detailed-agyfresh-failexp-20261120-0114.md`.

## G. Open questions (for the coordinator; none blocks SL-1's start)

- **Q1. Jailed standalone route.** It runs the provider by path, so SL-1 leaves it not
  covered (B4). Covering it needs one of: (i) a `panel_invoker.py` change to carry the
  three evidence keys and accept a held file's path, plus cache files the seat uid can
  execute (AGYFRESH §2.5 says 0600); (ii) the jail binding the admitted memfd instead of a
  path, which is a jail change this roadmap excludes; (iii) accepting the gap. On a host
  that can jail, the Gemini review seat takes only the jailed route, so until this is ruled
  the hold serves the non-jailed heartbeat and seat-profile routes.
- **Q2. Managed skip scope.** B3 skips by subject. A host-level skip (any host with the
  managed authority pin) is stricter and would also exclude a standalone PATH `agy` on a
  managed host.
- **Q3. EC-HOLD-9 wording.** Under B2 the roadmap text holds as written, within the stated
  limit on transient swaps. No roadmap change is proposed.
- **Q4. `requalify_once`** still reads the subject once into memory to key its process
  memo (unchanged by the caps lane). It is outside AGYFRESH §1.2's seat-admission rule as
  written; SL-1 leaves it. A streamed digest would be a small follow-up.
- **Q5. Status cost.** `hold_status` may read up to five images. SL-3's doctor row computes
  it only when the Gemini verdict is not `admits`.
