# AGYFRESH HOLD amendment: text for the roadmap and the contract

Text that lane SL-0 (AMEND) of `plans/phase-plan-v1-agyroll-HOLD.md` lands in
`specs/phase-plans-agyroll-v1.md` (the roadmap) and `plans/artifacts/agyfresh-contract.md`
(AGYFRESH), in one PR. It applies the owner decision of 2026-11-20 on the jailed standalone
route ("Do it: sandbox runs verified copy"), coordinator rulings R-F0-1 and R-F0-2, the
options AGYFRESH §6.2 and §6.3 delegate to the phase plan, and the review of the HOLD plan
(findings R1–R3). One amendment, not several: every later lane implements this text and
edits neither file.

Baseline: both files as they stand after RESTORE's caps lane and its contract repin have
merged. SL-0 recomputes the roadmap's External Inputs digest from the committed contract,
re-stamps the HOLD plan's frontmatter digest, and runs `roadmap_lint`.

"Replace" quotes enough of the current text to find it; everything not named is unchanged.

## 1. Roadmap

### 1.1 Owner Decisions (2026-11-20, AGYFRESH): add

- **D12** — the jailed standalone Gemini seat runs the admitted sealed image, not a path
  (AGYFRESH §2.11; EC-HOLD-13, EC-HOLD-14). The managed projection and its digest gate are
  unchanged. If the jail profile digest changes, per-host jail requalification is an
  owner-gated operational step (O4); the owner is asked before any such run.

### 1.2 Non-Goals

Replace "- Seat-jail, egress or `SEALED_FALLBACK_CODES` changes." with:

- Egress or `SEALED_FALLBACK_CODES` changes.
- Seat-jail changes, **except** the one AGYFRESH §2.11 defines: the standalone Gemini jail
  binds the admitted sealed image at `/seat/bin/gemini`. No other mount, capability, filter,
  uid, environment or egress property of any jail changes, and no jail of another leg
  changes.

The last non-goal ("A held image that meets no existing qualification predicate, or any
weakening of the managed-release authority check…") stays as written.

### 1.3 Assumption 5: append

The jailed **standalone** route executed the provider by path, so a held admission could
not run there either. D12 changes that route to execute the admitted sealed image
(AGYFRESH §2.11). Which mount form does it is decided by HOLD's jail feasibility lane, not
assumed.

### 1.4 Phase HOLD

**Exit criteria.** Replace EC-HOLD-9's last clause "and a file replaced during the read are
all rejected" with "and a file whose replacement is observed during the read (AGYFRESH
§2.5) are all rejected". Add:

- [ ] EC-HOLD-13 — Jailed standalone route (AGYFRESH §2.11): the production and the probe jail bind the same admitted sealed image at `/seat/bin/gemini`; the bytes the seat executes hash to the evidence's `provider_image_sha256` after the source file is renamed, unlinked or rewritten; a held admission runs there with source `lkg`; a descriptor that is not that sealed image is refused; a failed build and a cancellation leave no descriptor open.
- [ ] EC-HOLD-14 — Jail qualification (AGYFRESH §2.11, §3): for a sealed-image jail the actual profile digest equals the canonical Gemini digest, and no other leg's canonical digest changes; if the canonical Gemini digest differs from the one before this phase, that is recorded and operational step O4 is required before the change is installed on a host.
- [ ] EC-HOLD-15 — Status (AGYFRESH §2.6): `hold` reports the subject class, coverage per route, and a candidate with its state; it never reports a candidate as in use.

EC-HOLD-12 stays; its object is the amended §2.6.

**Scope notes.** Replace the lane list and the stop rule with:

Decompose into these lanes:
- **F0 feasibility** (managed authority): done; it failed (Assumption 5).
- **Amend** (docs): this amendment.
- **Jail feasibility** (scratch test, no production change): decides the mount form of
  AGYFRESH §2.11 and whether the canonical Gemini jail digest changes.
- **Core**: `agy_hold.py`, `admit_seat` in `agy_qualification.py`, config, status.
- **Jail integration**: `panel_invoker._prepare_jailed_gemini` and `seat_jail.build_seat_jail`
  for the standalone Gemini jail; evidence. After core and the jail feasibility lane.
- **Cache**: retain, prune and `clear --all`.
- **Dotfiles** (Consiliency/dotfiles, EXT-DOT): independent.

Stop rule: if the managed projection, its digest gate, the authority path, or any jail
property other than the AGYFRESH §2.11 bind would have to change for a test to pass, the
lane stops.

**Non-goals.** Replace "and any change to the authority or jail path" with "any change to
the authority path, and any jail change beyond AGYFRESH §2.11".

**Key files.** Add `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`,
`phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`,
`phase-loop-runtime/tests/test_agy_hold_jail.py`.

**Produces.** Add:

- IF-0-HOLD-5 — The standalone Gemini jail's sealed-image bind, its descriptor ownership and its evidence (AGYFRESH §2.11).

Add the same line to "Top Interface-Freeze Gates".

**Operational step, after the jail integration lane merges, only if EC-HOLD-14 records a
changed canonical digest:**

- **O4 — jail requalification (owner-gated).** Installing a runtime whose canonical Gemini
  jail digest changed makes each host run its first-use jail qualification on the next
  jailed Gemini launch (`seat_jail_autoqualify`). The owner is asked before that runtime is
  released or installed on any host, and per host named in the grant
  `phase-loop seat-sandbox qualify` is run and its outcome recorded in
  `plans/evidence/agyfresh-jail-requalification.json`, stamped by the runner. No code lane
  runs it.

### 1.5 Phase REQUAL

Replace EC-REQUAL-8 with:

- [ ] EC-REQUAL-8 — The doctor's Gemini row names a hold candidate, its state and the route coverage (AGYFRESH §2.6, early slice), and never reports it as in use.

### 1.6 Execution Notes, single-writer files

- `panel_invoker.py`: agent-harness#1916 → HOLD (jail integration) → REQUAL → EXECADMIT.
- Add `seat_jail.py`: HOLD (jail integration) only.

## 2. AGYFRESH contract

### 2.1 §1.2, memory rule: append

On the jailed standalone route the image is the same memfd (§2.11). If the feasibility lane
selects the data-bind form, each jail additionally holds one copy of the image in its own
tmpfs for the jail's lifetime: per leg, at most `MAX_MEMBER_BYTES` for the memfd plus
`MAX_MEMBER_BYTES` for each of the production and probe jails. That cost is recorded with
the lane's result; it is not hidden inside the one-image rule.

### 2.2 §2.2, the seat admission boundary

Add to "Never hold-eligible": "an unavailable memfd seal ABI when the image memfd is
created". Add after it:

`agy_integrity.check` maps a seal failure and an unavailable seal ABI to the same
`agy_image_unqualified` an unqualified subject raises. `admit_seat` classifies both
**before** that mapping; the mapped refusal is never a hold reason.

Replace the **Handler** paragraph with:

**Handler.** On `_SubjectNotAdmitted`: close the subject's image if one exists. If the
subject is a managed-release subject (§2.9) or `hold_enabled()` is false, raise `refusal`
unchanged, opening nothing. Otherwise call `admit_held(...)` and return its admission, or
raise `refusal` unchanged. A held admission is `gh.Admission(image, help_sha256, class,
None, source="lkg")`: it carries **no path**. Every route executes the admission's sealed
image (§2.11 for the jail); none may execute a path derived from a held admission.

In the candidate loop a candidate-local error skips that candidate. Cancellation and the
typed egress, quiescence and jail outcomes of a candidate's help measurement propagate.

### 2.3 §2.4, last paragraph

Replace "A process memo keeps the admitted candidate's `name` so later legs try it first
(it is still re-read and re-hashed)." with:

There is no process memo. Every hold rebuilds the candidate list and walks it in the total
order, so a newer eligible candidate that appears between two holds wins the second.
"Always examined" means `AUTH_READS` reads are reserved for authenticated candidates and
are spent as earlier candidates fail; the first candidate that passes §2.3 ends the walk.

### 2.4 §2.5, the Read bullet

Replace it with:

- **Read.** `VerifiedImage.from_fd` on that descriptor, and no other reader. Afterwards
  (i) `fstat` of the descriptor must equal the pre-read
  `(st_dev, st_ino, st_size, st_mtime_ns)`, and (ii) a no-follow `stat` of the file name
  relative to the opened candidate directory must be a regular file with the descriptor's
  `(st_dev, st_ino)`. A mismatch or a missing name rejects the candidate (§6.3 option (b)).
  This detects a replacement that is observable at that moment. It does not prove none
  happened: a swap reverted before (ii) is not seen. The integrity control is the digest of
  the sealed bytes under §2.3, not this check. A cache file pruned or cleared while it is
  being read is rejected, which can cost that one hold a candidate.

### 2.5 §2.6, evidence and status

Add `panel_invoker`'s jailed-seat evidence to the sites that write the three keys.

Replace the `agy-qualification status` sentence with:

`agy-qualification status` adds:

```
"hold": {"enabled": bool,
         "subject": "standalone" | "managed_release",
         "routes": {"seat_profile": C, "heartbeat": C, "jailed": C},
         "candidate": {"origin", "version", "image_sha256", "admission_class",
                       "state": "ready" | "pending_help_measurement"} | null}
```

`C` is `"covered"` or `"not_covered"`. For a managed-release subject every route is
`"not_covered"`, `candidate` is `null` and nothing is searched; it is rendered "not covered
(managed release)". `routes.jailed` is `"not_covered"` until the §2.11 bind is implemented.
`candidate` is the first candidate passing §2.3 without measuring help: `"ready"` for a
release member, `"pending_help_measurement"` for one that passed only the store half of
step 3. It is a lookup result. Neither status nor the doctor says an image is in use; use
is reported only by the evidence of a launch (`provider_admission_source == "lkg"`).
`clear --all` removes `held/`.

### 2.6 §2.8, harness cache: append

`retain` is called only when the hold is enabled and the subject is not a managed-release
subject.

### 2.7 §2.9, managed-release authority

Replace the "Outcome" paragraph with:

**Outcome (2026-11-20): F0 failed.** `admit_seat` skips the hold for a managed-release
subject: one whose resolved path lies below the managed releases root
(`seat_subject._names_managed_root`, called read-only). The skip is by subject, at the one
boundary, so it applies on every route, including the non-jailed heartbeat route. A PATH
`agy` outside the managed root is a standalone subject, on any host. Managed hosts recover
at build time (§2.10, EXT-DOT) and through the RESTORE restore runs. The projection, its
digest gate and the jail's dependency binding are unchanged by §2.11.

### 2.8 New §2.11, the jailed standalone route

For a standalone subject, `panel_invoker._prepare_jailed_gemini` no longer hands the jail a
path. For **every** standalone admission, subject or held:

- **Same bytes in both jails.** The production jail and the probe jail each receive their
  own descriptor from `admission.image.reopen()`. Before a jail takes it,
  `seat_jail.build_seat_jail(..., provider_fd=fd)` requires a regular file carrying the
  write, grow, shrink and seal seals whose content hashes to the admission's digest;
  anything else is `SeatSandboxRefused` (`identity`). `provider_fd` with a dependency is
  refused. The seat's recorded `image_sha256` is that digest.
- **Mount form**, chosen by the jail feasibility lane, in this order of preference:
  - **A.** `--ro-bind /proc/self/fd/<fd> /seat/bin/gemini`: the canonical owner argv shape
    is unchanged (the source stands where the provider path stood), so the canonical Gemini
    digest and every recorded pass stay valid. Selected only if the lane shows that bwrap
    mounts it, the seat uid executes it, and the actual digest equals the canonical digest
    with no new normalization.
  - **B.** `--perms 0555 --ro-bind-data <fd> /seat/bin/gemini`: the canonical Gemini owner
    argv changes, for the Gemini leg only. It is not normalized away. §3 and the roadmap's
    O4 apply. Each launch reads the descriptor from offset 0.
  - Neither works: the lane stops; the route stays `"not_covered"`.
- **Descriptor ownership.** A jail owns its descriptor from a successful build until
  `close_jail_fds`; it is in the jail's `pass_fds` for every launch of that jail. The
  admission is closed after both jails are built, and on any failure or cancellation before
  that, together with every descriptor already taken.
- **Inside the jail.** The seat uid can read and execute `/seat/bin/gemini` and cannot
  write it. No host path of the provider, the store, `held/` or a vendor store is bound.
  The provider process inherits no descriptor of the image (`seat_fd_closer`). Credentials,
  egress, filter, capabilities and uid drop are unchanged.
- **Managed dependency:** unchanged in every line.

### 2.9 §3, requalification triggers: add rows and a paragraph

| Event | Host store entries | Catalog records | Jail pass records |
|---|---|---|---|
| §2.11 form A | none | none | none |
| §2.11 form B | none | none | every Gemini jail key on every host and architecture requalifies at its next jailed launch (first use), or by `phase-loop seat-sandbox qualify`; other legs: none |

Jail qualification and agy qualification are separate. A `seat_jail.py` or
`panel_invoker.py` edit does not by itself change `seat_qci()`; `tests/test_agy_qci.py`
decides, as above (`panel_invoker.py` is in the validator's source-hash supplement, so that
table is updated as a reviewed change when only it flags). A changed canonical jail digest
is never normalized to reuse a pass record. No lane runs a jail qualification on a host
other than through its tests' stubs; the run is roadmap step O4.

### 2.10 §5, roadmap amendment text

Add EC-HOLD-13, EC-HOLD-14, EC-HOLD-15, the amended EC-HOLD-9 and EC-REQUAL-8, and
IF-0-HOLD-5, exactly as §1 above.

### 2.11 §6

Mark §6.2 as resolved by §2.4 (no memo) and §6.3 as resolved by §2.5 (option (b)).
