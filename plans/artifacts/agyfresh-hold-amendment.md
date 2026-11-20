# AGYFRESH HOLD amendment: text for the roadmap and the contract

Text that lane SL-0 (AMEND) of `plans/phase-plan-v1-agyroll-HOLD.md` lands in
`specs/phase-plans-agyroll-v1.md` (the roadmap) and `plans/artifacts/agyfresh-contract.md`
(AGYFRESH), in one PR. It applies the owner decision of 2026-11-20 on the jailed standalone
route ("Do it: sandbox runs verified copy"), coordinator rulings R-F0-1 and R-F0-2, the
options AGYFRESH §6.2 and §6.3 delegate to the phase plan, and the two reviews of the HOLD
plan with the coordinator's rulings on them. One amendment, not several: every later lane implements this text and
edits neither file.

Baseline: both files as they stand after RESTORE's caps lane and its contract repin have
merged. SL-0 recomputes the roadmap's External Inputs digest from the committed contract,
re-stamps the HOLD plan's frontmatter digest, and runs `roadmap_lint`.

"Replace" quotes enough of the current text to find it; everything not named is unchanged.

## 1. Roadmap

### 1.1 Owner Decisions (2026-11-20, AGYFRESH): add

- **D12** — on the jailed standalone route a **held** admission runs as the admitted sealed
  image, not a path (AGYFRESH §2.11; EC-HOLD-13, EC-HOLD-14). Ordinary launches keep the
  existing path bind. The managed projection and its digest gate are unchanged. The bind
  must leave every canonical jail digest and qualification key as it is; a form that
  changes one is not admitted by this amendment. The jail integration lane merges only on
  the release owner's clearance (G-REL).

### 1.2 Non-Goals

Replace "- Seat-jail, egress or `SEALED_FALLBACK_CODES` changes." with:

- Egress or `SEALED_FALLBACK_CODES` changes.
- Seat-jail changes, **except** the one AGYFRESH §2.11 defines: for a held admission the
  standalone Gemini jail binds the admitted sealed image at `/seat/bin/gemini`. No other mount, capability, filter,
  uid, environment or egress property of any jail changes, and no jail of another leg
  changes.

The last non-goal ("A held image that meets no existing qualification predicate, or any
weakening of the managed-release authority check…") stays as written.

### 1.3 Assumption 5: append

The jailed **standalone** route executes the provider by path, so a held admission could
not run there either. D12 changes that route, for held admissions only, to execute the
admitted sealed image (AGYFRESH §2.11). Whether the one admitted mount form works is
decided by HOLD's jail feasibility lane, not assumed. If it does not, the route stays not
covered and the owner decides between a new amendment and accepting the gap; the rest of
HOLD is delivered either way.

### 1.4 Phase HOLD

**Exit criteria.** Replace EC-HOLD-9's last clause "and a file replaced during the read are
all rejected" with "and a file whose replacement is observed during the read (AGYFRESH
§2.5) are all rejected". Add:

- [ ] EC-HOLD-13 — Jailed standalone route (AGYFRESH §2.11): for a held admission the production and the probe jail bind the same admitted sealed image at `/seat/bin/gemini`, the bytes the seat executes hash to the evidence's `provider_image_sha256` after the candidate's source file is renamed, unlinked or rewritten, and the evidence carries source `lkg`; a descriptor that is not that sealed image is refused; a failed build and a cancellation leave no descriptor open; an ordinary launch keeps the existing path bind and its launch and evidence behaviour.
- [ ] EC-HOLD-14 — Jail qualification (AGYFRESH §2.11, §3): the canonical digest of every registered leg and every qualification key are the same before and after the jail integration lane; a sealed-image jail, the managed-dependency jail and every jail the qualifier builds each pass the unstubbed canonical comparison against their own leg's canonical digest.
- [ ] EC-HOLD-15 — Status (AGYFRESH §2.6): `hold` reports the subject class, coverage per route, and a candidate with its state; it never reports a candidate as in use.

EC-HOLD-12 stays; its object is the amended §2.6.

**Scope notes.** Replace the lane list and the stop rule with:

Decompose into these lanes:
- **F0 feasibility** (managed authority): done; it failed (Assumption 5).
- **Amend** (docs): this amendment.
- **Jail feasibility** (scratch test, no production change): decides whether the mount form
  of AGYFRESH §2.11 works. If it does not, the jail integration lane is not run and the
  other lanes complete without it.
- **Core**: `agy_hold.py`, `admit_seat` in `agy_qualification.py`, config, status.
- **Jail integration**: `panel_invoker._prepare_jailed_gemini` and `seat_jail.build_seat_jail`
  for a held admission on the standalone Gemini jail; evidence. After core and a passing
  jail feasibility lane; merged only under G-REL.
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

**Release hold G-REL (execution gate; release owner: the Agent-Harness Exec).** The control
is the merge, and the release owner is the only merge actor for the jail integration lane.
Its PR does not merge to `main` until the release owner has recorded an affirmative
clearance that names the cleared head SHA. The clearance needs both proofs: the feasibility
lane's recorded digest comparison, and EC-HOLD-14 executed with zero skips in that head's
hosted CI, linked in the clearance. The merge is head-conditioned on the cleared SHA
(`gh pr merge --match-head-commit <cleared-sha>`, or the train runner's equivalent), after
every required check has passed on that same head; the lane is excluded from auto-merge
and from any queued or deferred merge. A different PR head at merge time invalidates the
clearance, and the head condition enforces that. Because the lane is never on `main` without the clearance, `main` stays
releasable at every tag, every PyPI publication and every dotfiles nightly consumer is
covered, and a deployment that consumes `main` directly is covered by the same gate; no
pre-tag check is needed. The clearance is recorded in the engagement plan and ledger and
linked from the PR.

If a canonical key would change, the lane stops (it is outside this amendment). Should a
later amendment admit such a change, it would also need:

- **O4 — jail requalification (owner-gated)** covering every affected host, including the
  dotfiles nightly consumers, before the change merges. The harness requalifies a jail by
  itself at first use (`seat_jail_autoqualify`), so installation is the trigger; the owner
  is asked first. A rollback that changes a canonical key again is under the same rule. No
  code lane runs it.

**If the jail feasibility lane fails.** Once the coordinator has recorded the failed probe
and the owner has accepted the gap, the cache lane and the REQUAL early slice follow the
core lane, `routes.jailed` stays `"not_covered"`, and the phase closes on the delivered
scope with EC-HOLD-13 and EC-HOLD-14 recorded as **unmet** and G-REL not applicable. If the
owner instead calls for a new amendment, those lanes still proceed and the phase stays
open for the jailed route.

**Follow-up, not part of this phase.** Binding the sealed image for ordinary jailed
launches as well. Its precondition is evidence, per supported deployment configuration, of
this particular proc-descriptor bind through the owner chain and the seat-uid drop;
evidence that the existing jail works on a configuration is not enough.

### 1.5 Phase REQUAL

Replace EC-REQUAL-8 with:

- [ ] EC-REQUAL-8 — The doctor's Gemini row names a hold candidate, its state and the route coverage (AGYFRESH §2.6, early slice), and never reports it as in use.

### 1.6 Execution Notes, single-writer files

- `panel_invoker.py`: agent-harness#1916 → HOLD (jail integration) → REQUAL → EXECADMIT.
- Add `seat_jail.py`: HOLD (jail integration) only.

## 2. AGYFRESH contract

### 2.1 §1.2, memory rule: append

On the jailed standalone route the image is the same memfd (§2.11): the jails mount it and
hold no further copy.

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

On the jailed standalone route, `panel_invoker._prepare_jailed_gemini` treats the two
admission sources differently.

- **Ordinary admission (`source == "subject"`): unchanged.** The production and probe jails
  bind `realpath(admission.path)` as today. Launch behaviour is preserved, and the evidence
  is unchanged apart from the additive `provider_admission_source: "subject"`. The route's
  existing property stands: it executes the file at that path, so nothing in this section
  about admitted bytes or source mutation is claimed for an ordinary launch.
- **Held admission (`source == "lkg"`): the sealed image.** The remaining bullets apply to
  it only. They are what "sealed launch" means.
- **Same bytes in both jails.** The production jail and the probe jail each receive their
  own descriptor from `admission.image.reopen()`. Before a jail takes it,
  `seat_jail.build_seat_jail(..., provider_fd=fd)` requires a regular file carrying the
  write, grow, shrink and seal seals whose content hashes to the admission's digest;
  anything else is `SeatSandboxRefused` (`identity`). `provider_fd` with a dependency is
  refused. The seat's recorded `image_sha256` is that digest.
- **Mount form: one, and only one.** `--ro-bind /proc/self/fd/<fd> /seat/bin/gemini`, with
  that literal spelling both in the argv and in the jail's `provider_path`. The source
  stands where the provider path stands, so the owner argv shape, the canonical Gemini
  digest, every qualification key and every recorded pass are unchanged, and
  `actual_profile_digest` needs no new normalization. If the seat uid can execute the mount
  only with the image's mode set to 0555, that mode is a production requirement: it is set
  on the jail's descriptor before the build and asserted by a regression test.
- **No fallback form.** A data bind (`--ro-bind-data`) changes the one canonical Gemini
  digest. That digest is shared by `panel_invoker._require_canonical_jail`, by the
  dependency branch of `actual_profile_digest` (which restores the path-bind shape for the
  managed route), by `seat_qualification_key.key_for_launch` and by the jails the qualifier
  builds (`seat_jail_qualification._run_probe_in_jail`). Admitting it would need a
  route-aware canonical through all four, which cannot be done without touching the managed
  branch or its normalization. It is **not admitted** by this amendment. If the feasibility
  lane shows the proc-descriptor form does not satisfy every check, the jail integration
  lane does not run and the route stays `"not_covered"`.
- **Descriptor ownership.** A jail owns its descriptor from a successful build until
  `close_jail_fds`; it is in the jail's `pass_fds` for every launch of that jail. The
  admission is closed after both jails are built, and on any failure or cancellation before
  that, together with every descriptor already taken.
- **Inside the jail.** The seat uid can read and execute `/seat/bin/gemini` and cannot
  write it. No host path of the provider, the store, `held/` or a vendor store is bound.
  The provider process holds exactly the descriptors the profile declares and none on the
  image. Credentials, egress, filter, capabilities and uid drop are unchanged.
- **Managed dependency and the qualifier:** unchanged in every line. The managed jail and
  every jail the qualifier builds still pass the unstubbed canonical comparison against
  their own leg's canonical digest.
- `routes.jailed` (§2.6) is `"covered"` once this is implemented: it describes whether a
  hold can run on the route, which is all a held admission needs.

### 2.9 §3, requalification triggers: add rows and a paragraph

| Event | Host store entries | Catalog records | Jail pass records |
|---|---|---|---|
| §2.11 bind for a held admission (proc-descriptor form) | none | none | none: the canonical digests and qualification keys are unchanged, which EC-HOLD-14 proves rather than assumes |
| Any change to a canonical jail digest or qualification key | none | none | not admitted here; under a later amendment, every affected key requalifies at first use, behind owner step O4 |

Jail qualification and agy qualification are separate. A `seat_jail.py` or
`panel_invoker.py` edit does not by itself change `seat_qci()`; `tests/test_agy_qci.py`
decides, as above (`panel_invoker.py` is in the validator's source-hash supplement, so that
table is updated as a reviewed change when only it flags). A changed canonical jail digest
is never normalized to reuse a pass record. No lane runs a jail qualification on a host; the tests
that touch the qualifier construct its jail with a harmless stand-in and record no pass.

### 2.10 §5, roadmap amendment text

Add EC-HOLD-13, EC-HOLD-14, EC-HOLD-15, the amended EC-HOLD-9 and EC-REQUAL-8, and
IF-0-HOLD-5, exactly as §1 above.

### 2.11 §6

Mark §6.2 as resolved by §2.4 (no memo) and §6.3 as resolved by §2.5 (option (b)).
