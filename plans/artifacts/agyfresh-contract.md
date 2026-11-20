# AGYFRESH contract r2: bounds, the hold, and the AGYROLL amendment

Frozen planning input for the AGYFRESH amendment to `specs/phase-plans-agyroll-v1.md`. It
adds two phases (RESTORE, HOLD) and clauses to existing phases. This file is the single
normative source; the roadmap and the phase plans cite it as `AGYFRESH §n` and do not restate
it. Changing this file is a reviewed repin: amend the roadmap's External Inputs row in the
same PR.

**Owner decisions applied (2026-11-20).** D3a, D3b, D3c, D4, D5, D7, D9, D10 and D11 as
recommended, so the values written below are the selected ones (no alternative is in force).
**D8 = B**: the §5.1 D8-B row and text are in force; the D8-A row stays as the record of the
alternative. The roadmap's "Owner Decisions (2026-11-20, AGYFRESH)" section lists them.

Source lines are `origin/main` at `2c8e0ec0c2b81d3b63acda02f67e98c9fc816f51`; paths are under
`phase-loop-runtime/src/phase_loop_runtime/` unless they start with a repository directory.
`gh` is `gemini_heartbeat`. r2 answers an independent planning review (findings F1–F9,
cited inline); §6 records the binding findings of its re-review.

## 1. Bounds (RESTORE)

### 1.1 Constants, defined once in `agy_provenance.py`

| Constant | Value | Meaning |
|---|---|---|
| `MAX_MEMBER_BYTES` | `512_000_000` (from agent-harness#2014) | largest agy image accepted anywhere |
| `MAX_ARCHIVE_BYTES` | `256_000_000` (was `128_000_000`) | largest compressed release asset |
| `MAX_EXPANDED_BYTES` | `1_024_000_000` (new) | largest decompressed tar stream of one archive, and largest sum of its declared member sizes |

- Every consumer reads the constant **at call time** as `agy_provenance.<NAME>`. No module
  keeps an alias: `gh._MAX_IMAGE_BYTES` (`gemini_heartbeat.py:116`) is deleted, and the three
  literals at `agy_integrity.py:65`, `:68`, `:75` go. This is what lets a test patch one
  attribute and see every reader follow (F8).
- `phase-loop-runtime/scripts/verify_qualified_agy_image.py` keeps script literals
  `MAX_MEMBER_BYTES` and a new `MAX_ARCHIVE_BYTES` (used at `:333`), tested equal to the
  module's.
- **Archive accounting in `read_member`** (F3; satisfies §6.1). The compressed bound alone
  does not bound decompression, and a sum of declared sizes does not bound what the tar
  parser consumes before a member is yielded. So `read_member`:
  - decompresses below the tar parser (`_ExpandedReader`: gzip inflated one bounded 1 MiB
    chunk per read, beneath `tarfile` in `r|` mode) and counts every decompressed byte
    handed to the parser against `MAX_EXPANDED_BYTES`: headers, extension records, padding,
    skipped members and the member;
  - also sums the declared sizes of **all** members as each is announced, and raises
    `UNVERIFIED` above `MAX_EXPANDED_BYTES`;
  - keeps the separate member-size check against `MAX_MEMBER_BYTES`;
  - bounds what the parser keeps, checked per header before the parser reads the record
    that header announces (`_bounded_tarinfo`):

    | Constant | Value | Bounds |
    |---|---|---|
    | `MAX_ARCHIVE_ENTRIES` | `4096` | header blocks of any kind, extension headers included |
    | `MAX_ARCHIVE_METADATA_BYTES` | `4_194_304` | bytes of extension records (PAX, GNU long name and link), summed over the archive |
    | `MAX_EXTENSION_CHAIN` | `8` | consecutive extension headers before one member (the parser recurses once per header) |

  - refuses sparse members: GNU type `S` and PAX-encoded sparse maps (GNU formats 0.0, 0.1
    and 1.0).

  Every refusal is `UNVERIFIED`. Integrity still rests on the archive digest, taken over
  every compressed byte. These limits fail closed. If upstream archives ever carry PAX
  records or sparse members beyond them, provenance reading refuses until the limits are
  reviewed. Upstream 1.2.10 and 1.5.13 archives are a single ustar member.
- **Maintenance dependency.** The parser bounds override private `tarfile.TarInfo` methods
  (`_proc_member`, `_proc_gnusparse_00`, `_01`, `_10`). The test
  `test_the_parser_hooks_exist_on_this_python` fails if any of them is renamed away, and it
  must stay.
- The verifier's `verify_archive` does not do this accounting. It checks the archive against
  the catalog record's upstream digest first, and bounds the member by `MAX_MEMBER_BYTES`.

### 1.2 Memory rule

The values above are size ceilings, not a demonstration that the host can afford them. The
nightly headroom alarm (§5, EC-ROLLJOB-8) is an operational warning, not a safety control.
The safety control is the reader:

- **One reader, streaming.** New `gh.VerifiedImage.from_fd(fd, *, path=None)`: copies from an
  already-opened, already-`fstat`-checked descriptor into a new memfd in 1 MiB chunks while
  hashing, refuses above `MAX_MEMBER_BYTES`, applies the same mode and seals as
  `_sealed_tree_fd(executable=True)` (a test compares `F_GET_SEALS` and mode with a
  `from_bytes` image), then re-hashes the memfd. Peak anonymous memory is one chunk; the
  image exists once, in the memfd.
- `gh._read_image` + `VerifiedImage.from_bytes` (chunk list, `join`, then memfd: about three
  copies) is replaced by `from_fd` in `gh.admit` and `agy_integrity.check`. `from_bytes`
  stays for callers that already hold bytes. `_read_image` stays for callers that need the
  bytes, and reads `MAX_MEMBER_BYTES` at call time.
- **Ownership.** A non-member image reaches `agy_qualification.lookup` as the sealed
  `VerifiedImage` of that single read. `lookup` takes ownership of a supplied image: it
  closes the image unless it hands it on inside an `Admission` or an `AdmissionMiss`,
  including on the opt-out. `lookup` still accepts bytes from other callers.
- **Seal failure on the seat path.** `agy_integrity.check` maps a memfd seal failure from
  `from_fd` to `AgyImageUnqualified("agy_image_unqualified")`, for a release member as well
  as a non-member.
- **Frozen peak per seat admission:** at most **one** sealed image alive at a time, so
  `MAX_MEMBER_BYTES` of shared memory plus 2 MiB. The tested form of the 2 MiB is a traced
  Python allocation (`tracemalloc`) below 2 MiB for `from_fd`, `gh.admit` and
  `agy_integrity.check`. The memfd is re-hashed through the same reused buffer, so the
  measured peak is about one chunk. §2 keeps this true during a hold: the
  subject's memfd is closed before the first candidate is opened, and a rejected candidate
  is closed before the next is opened.
- **Concurrency.** Candidate loading in one process is serialized by a module lock in
  `agy_hold`. Each concurrently running Gemini leg still holds its own memfd of the admitted
  image; that multiplier (legs × image size) exists today and is unchanged.
- **Out of scope here, stated:** the watch's `fetch_member(keep_bytes=True)` join
  (`agy_provenance.py:259`–`:268`) and its one-memfd-per-catalog-member loop. ROLLJOB (§5)
  must move it to `from_fd`-style streaming and one member at a time.

On the jailed standalone route the image is the same memfd (§2.11): the jails mount it and
hold no further copy.

## 2. The hold (HOLD)

### 2.1 What it is, precisely

When the seat's selected agy (the *subject*) cannot be used for a reason in the eligible
list below, seat admission admits a different image already on the host that satisfies an
**existing qualification predicate**, with `Admission.source = "lkg"`.

What does not change: which image digests can be admitted, and what each must prove.
What does change, deliberately (F6): which image is *selected*; that some subject refusals
no longer stop the seat; and that with `[agy] self_qualification = false` a release member
other than the subject can run.

The promise is **bounded best effort**: the newest qualified image among the candidates the
bounded search examines (§2.4), with a guarantee about which candidates are always examined.
It is not "the newest qualified image on the host".

### 2.2 The seat admission boundary (F2)

One function is the only place a seat image is admitted:

```python
# agy_qualification.py
def admit_seat(env, subject_path, *, first_use=False, cancel_event=None, heartbeat=None,
               store=None, transport=None, qualify=None) -> gh.Admission
```

- `gh.admit` (`gemini_heartbeat.py:229`) becomes: candidate-token case as today, then
  `admit_seat(..., first_use=False)`, mapping a refusal to `_CAPABILITY` as today.
- `agy_integrity.check(path, env)` **with** an env (`agy_integrity.py:55`; the two seat
  sites) becomes `admit_seat(dict(env), source, first_use=False)`, mapping a refusal to
  `AgyImageUnqualified` and passing the typed egress, quiescence and jail exceptions through
  exactly as `_locally_qualified` does today (`:42`–`:49`). `check(path)` **without** an env
  (executor, canary) is unchanged and never holds.
- `ensure_admitted` (`agy_qualification.py:1394`) becomes `admit_seat(..., first_use=True)`.
- `lookup` keeps its signature and stays the subject-only step; `admit_seat` calls it. The
  agent-harness#1602 seam (`:1154`–`:1214`) is unchanged.

Because spawn and preflight both go through `admit_seat`, a hold decided in the preflight is
reached again, independently, at each leg's spawn. Nothing is carried between them.

**Stages and typing.** `admit_seat` runs fixed stages. Each stage that can fail *because of
the subject* raises one internal type, `_SubjectNotAdmitted(reason, refusal, subject_sha256)`,
at an explicit site. `refusal` is the exception today's code would raise. The hold handler
catches **only** that type. No `except ValueError` decides a hold.

| Stage | Subject failure → `reason` (hold-eligible) |
|---|---|
| open and stream the subject (`from_fd`) | `subject_unreadable` (any `OSError`, including removed after resolution), `subject_not_regular`, `subject_over_bound` |
| release-member test | — (a member is admitted here, before any config or store read) |
| opt-out | `self_qualification_disabled` |
| store lookup | `subject_failed` (a `failed` entry), `subject_unqualified` (no record, or provenance without `qualified`), `store_unsafe` |
| first use (`first_use=True` only) | `provenance_unverified`, `provenance_unavailable`, `first_use_failed`, `first_use_unavailable` |

**Never hold-eligible; always propagate unchanged:** `_local_capabilities()` failure (memfd
or pidfd ABI); a memfd seal failure (`AgyCanaryEvidenceError`); an unavailable memfd seal
ABI when the image memfd is created; `CANCELLED`;
`EgressUnavailable` and subclasses; `GeminiQuiescenceError`;
`ProviderProcessGroupQuiescenceError`; `SeatSandboxRefused`; `dependency_route_unwired`;
an unsupported platform; and **no provider installed** (`resolve_seat_subject` raising
`seat_provider_unavailable`, or `shutil.which` returning `None`). A host with no agy
installed has no seat by configuration; the hold does not invent one.

`agy_integrity.check` maps a seal failure and an unavailable seal ABI to the same
`agy_image_unqualified` an unqualified subject raises. `admit_seat` classifies both
**before** that mapping; the mapped refusal is never a hold reason.

**Order in `first_use=True`.** The subject is always tried first, including first-use
qualification. Only when that raises `_SubjectNotAdmitted` does the hold run. `CANCELLED`
during first use propagates and uses no attempt, as today.

**Handler.** On `_SubjectNotAdmitted`: close the subject's image if one exists. If the
subject is a managed-release subject (§2.9) or `hold_enabled()` is false, raise `refusal`
unchanged, opening nothing. Otherwise call `admit_held(...)` and return its admission, or
raise `refusal` unchanged. A held admission is `gh.Admission(image, help_sha256, class,
None, source="lkg")`: it carries **no path**. Every route executes the admission's sealed
image (§2.11 for the jail); none may execute a path derived from a held admission.

In the candidate loop a candidate-local error skips that candidate. Cancellation and the
typed egress, quiescence and jail outcomes of a candidate's help measurement propagate.

### 2.3 Which held images qualify

Applied to one candidate, after its bytes are sealed and hashed (`digest`):

1. `digest == subject_sha256`, or `digest` in the deny list (§2.7) → reject.
2. **Release member:** `digest in gh.QUALIFIED_IMAGES` → admit as `release_qualified`.
   No store read, no execution. Allowed with self-qualification off and with any store state.
3. **Locally qualified:** only if the store is `ok` and self-qualification is on:
   `get_failed` is `None` **and** `get_provenance` is not `None`; only then is help measured
   from the sealed memfd, and `get_qualified` under that help must not be `None` → admit as
   `locally_qualified`.

Bytes from a candidate are **never executed, not even for `--help`**, before step 2 or the
provenance half of step 3 has passed (F5).

**Custody boundary, unchanged and stated (R2):** store entries are HMAC-bound with a key in
the same account's store. They resist accidents and cross-account files; they do not defend
against a process running as that account, which can forge an entry for a held image exactly
as it can for the subject today. Release members do not depend on the store at all.

### 2.4 Candidate discovery, order and budgets (F3, F4)

New module `agy_hold.py` (outside `ROUTE_CORE`; standard library plus `gh`).

```python
VENDOR_STORES: tuple[Path, ...] = (Path("/opt/consiliency/operational-clis/agy"),)
HELD_DIRNAME = "held"            # <Store.host_dir>/held/<image sha256>
HELD_KEEP = 2
MAX_DIR_ENTRIES = 1024           # names listed per directory; more → that source is skipped
MAX_DIRS_PER_VERSION = 2         # lexicographically first
MAX_HINT_FILES = 64              # qualified-*.json read for hints, lexicographic, each ≤ 256 KiB
AUTH_READS = 3                   # image reads for candidates with an authenticated version
HINT_READS = 2                   # image reads for candidates with a hinted version

class HeldCandidate(NamedTuple):
    version: tuple[int, int, int]
    authenticated: bool          # where the version came from; see below
    origin: Literal["cache", "vendor"]
    name: str                    # cache: the digest; vendor: "<x.y.z>-<16 hex>"
```

**Building the list (no image is read):**

- *Cache, authenticated.* Each 64-hex file name in `held/` is a digest. Its version is the
  catalog member's `release_version` if the digest is a member, else the `release_version`
  in its MAC-valid `provenance` entry. A name with neither, with a `failed` entry, or in the
  deny list is not a candidate.
- *Vendor, authenticated.* Directories named `<version>-<16 hex>` whose version equals a
  catalog member's `release_version` (new `gh.catalog_members(path=None) -> list[dict]`,
  never raises; `load_catalog` is rebuilt on it).
- *Vendor, hinted.* Directories whose version equals a `payload.release_version` read,
  **without MAC verification**, from at most `MAX_HINT_FILES` `qualified-*.json` files, and
  is not a catalog version.

**Order (total and deterministic):** version descending; then authenticated before hinted;
then cache before vendor; then `name` ascending. `scandir` order never matters.

**Walk.** Take candidates in order. Reading an authenticated candidate spends one of
`AUTH_READS`; a hinted one spends one of `HINT_READS`; a candidate whose class is exhausted
is skipped. A file already examined (same `st_dev`, `st_ino`) or a digest already rejected
is skipped without spending. The first candidate that passes §2.3 is admitted.

**Guarantee.** The three newest authenticated candidates are always examined, whatever the
hint files say. Forged or stale hints can waste at most `HINT_READS` reads and can never
displace an authenticated candidate. Integrity never depended on hints; with this split,
availability of the release-member floor does not either.

**Total work per hold:** at most 5 image reads, 64 small file reads and
`MAX_DIR_ENTRIES` names per directory.

There is no process memo. Every hold rebuilds the candidate list and walks it in the total
order, so a newer eligible candidate that appears between two holds wins the second.
"Always examined" means `AUTH_READS` reads are reserved for authenticated candidates and
are spent as earlier candidates fail; the first candidate that passes §2.3 ends the walk.

### 2.5 Filesystem handling (F5)

No candidate or cache path is ever passed to `realpath`, `gh._read_image`, or any
path-following call. All access is descriptor-relative:

- **Anchor.** Vendor store: walk from `/` one component at a time with
  `os.open(name, O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC, dir_fd=parent)`; after each open,
  `fstat` must show a directory owned by uid 0 or the euid and not group- or other-writable.
  Cache: the anchor is `Store.host_dir`, opened and checked the same way after
  `Store.status() == "ok"`.
- **Candidate.** `os.open(<dir name>, ...O_DIRECTORY|O_NOFOLLOW, dir_fd=anchor)`, same
  `fstat` test; then `os.open("agy" or <digest>, O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC,
  dir_fd=...)`; `fstat` on the **opened file** must show a regular file, owner uid 0 or
  euid, not group- or other-writable, size ≤ `MAX_MEMBER_BYTES`. A symlink at any step fails
  the open and the candidate is skipped.
- **Read.** `VerifiedImage.from_fd` on that descriptor, and no other reader. Afterwards
  (i) `fstat` of the descriptor must equal the pre-read
  `(st_dev, st_ino, st_size, st_mtime_ns)`, and (ii) a no-follow `stat` of the file name
  relative to the opened candidate directory must be a regular file with the descriptor's
  `(st_dev, st_ino)`. A mismatch or a missing name rejects the candidate (§6.3 option (b)).
  This detects a replacement that is observable at that moment. It does not prove none
  happened: a swap reverted before (ii) is not seen. The integrity control is the digest of
  the sealed bytes under §2.3, not this check. A cache file pruned or cleared while it is
  being read is rejected, which can cost that one hold a candidate.
- **Cache mutations** (retain, prune, corrupt-file unlink, `clear --all`) all take
  `Store.lock()` and all use `dir_fd`: temp file with `O_CREAT|O_EXCL|O_NOFOLLOW` 0600,
  `os.rename(..., src_dir_fd=, dst_dir_fd=)`, `os.unlink(name, dir_fd=)` only after
  `os.stat(name, dir_fd=, follow_symlinks=False)` matches the descriptor being judged.
  Readers take no lock: an unlink under an open descriptor is harmless.
- `retain` tries the lock without waiting; if it is busy, retention is skipped this time.

### 2.6 Evidence and status

Additive keys where `provider_admission_class` is written (`agy_integrity.py:36`, `:83`;
`gemini_heartbeat.py:496`), and in `panel_invoker`'s jailed-seat evidence:

- `provider_admission_source`: `"subject"` or `"lkg"`;
- when `"lkg"`: `provider_hold_reason` (a §2.2 `reason`), and
  `provider_subject_image_sha256`, which is **`null` when the subject could not be read**.
  No digest is invented.

`provider_image_sha256` remains the digest of the image that runs. Counting is unchanged
(`COUNTED_ADMISSION_CLASSES`, `agy_qualification.py:1557`).

`admission_verdict(execute=False)` (`:1217`) is unchanged: a non-member subject never
reports `admits` because a held image exists (the dotfiles build reads that as "release
member").

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

### 2.7 Config

User board config only, never a repository config (as `self_qualification`):

- `[agy] hold` — boolean, default `true`. `false`, or any config error, disables the hold.
- `[agy] hold_deny` — list of image SHA-256 strings never admitted as a hold. This is the
  per-host security response for a held image later found unsafe (F9). The fleet-wide
  response is removing the member from the shipped catalog in a release.

### 2.8 Harness cache (lane L2)

`agy_hold.retain(image, store)`, called by `admit_seat(first_use=True)` after a **subject**
admission and after the first-use lock is released. Best effort, never raising. If
`held/<sha256>` exists it returns. Otherwise it streams the sealed memfd to a temp file,
`fsync`s, re-hashes, renames. Pruning keeps the `HELD_KEEP` highest authenticated versions
(§2.4), always including the one just retained; a file with no authenticated version is
pruned first. A cache file whose content does not hash to its name is unlinked.
Disk: at most `HELD_KEEP` × `MAX_MEMBER_BYTES` steady state, plus one temp file while
retaining. `Store.status()` must stay `ok` with `held/` present.

`retain` is called only when the hold is enabled and the subject is not a managed-release
subject.

### 2.9 Managed-release authority (F6)

Qualification and managed dependency authority are independent. A qualified digest does not
by itself authorize running something other than the release's pinned executable: the route
acquires projection authority (`seat_route.py:357`, `seat_admission.py:99`–`:137`) and the
jail binds projection anchors (`seat_jail.py:1561`–`:1587`). TEAMHOST §5 says a
last-known-good admission "admits that image, not the subject", but whether the real
projection and jail admission accept that is **not established**.

Lane F0 establishes it before L1 is frozen for managed hosts (HOLD phase plan). The authority
check is never weakened. If F0 fails, the hold ships for standalone subjects only, managed
hosts are reported as **not covered**, and D6 option B is an operational recovery route, not
delivery of the hold.

**Outcome (2026-11-20): F0 failed.** `admit_seat` skips the hold for a managed-release
subject: one whose resolved path lies below the managed releases root
(`seat_subject._names_managed_root`, called read-only). The skip is by subject, at the one
boundary, so it applies on every route, including the non-jailed heartbeat route. A PATH
`agy` outside the managed root is a standalone subject, on any host. Managed hosts recover
at build time (§2.10, EXT-DOT) and through the RESTORE restore runs. The projection, its
digest gate and the jail's dependency binding are unchanged by §2.11.

### 2.10 Dotfiles (lane L3, Consiliency/dotfiles)

`lib/seat_authority.py` `stage_agy`: candidates passed to `agy_verdicts` are the selected
image first, then up to five retained store images, newest version first.
`lib/seat_authority_agy.py` already stops at the first whose integrity verifies. That image
is staged; if it is not the selected one the build log says so and the sidecar's existing
`source` field names it. None verifies → `Refused` as today. The selection-changed check
stays. No sidecar field, pin or authority schema changes.

### 2.11 The jailed standalone route

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

## 3. Requalification triggers

| Event | Host store entries | Catalog records |
|---|---|---|
| New upstream image | first use for that image (help + three live operations) | one new live record (ROLLJOB) |
| `agy_profile_digest()` changes (`PROFILE_ID`, owned-profile description, `OPERATIONS_CONTRACT`) | all dropped; requalify at next preflight | every member re-recorded, or `--contract` fails the PR |
| `QUALIFICATION_VALIDATOR` bump | same | same |
| Measured help differs for the same image | that image requalifies | — |
| New machine-id, euid or state directory | all requalify | — |
| Harness upgrade with the same QCI | none | none |

| Event | Host store entries | Catalog records | Jail pass records |
|---|---|---|---|
| §2.11 bind for a held admission (proc-descriptor form) | none | none | none: the canonical digests and qualification keys are unchanged, which EC-HOLD-14 proves rather than assumes |
| Any change to a canonical jail digest or qualification key | none | none | not admitted here; under a later amendment, every affected key requalifies at first use, behind owner step O4 |

**This plan's lanes: none intended, conditionally.** `seat_qci()` depends on the profile and
the validator literal (`agy_qualification.py:816`–`:825`), which no lane edits. That is true
only if the validator's transitive closure and verdict vector are in fact unchanged, which
`tests/test_agy_qci.py` decides, not this document. If its verdict-vector pin changes, the
lane stops and reports. If only its source-hash supplement flags an edited file, the lane
updates the table as a reviewed change and does **not** bump the validator. An unchanged-QCI
source edit never justifies a live re-record.

No lane may edit `PROFILE_ID`, `profile_description`, `OPERATIONS_CONTRACT`,
`validate_records`, `validate_directory`, `_classify_failure` or anything they reach.

Jail qualification and agy qualification are separate. A `seat_jail.py` or
`panel_invoker.py` edit does not by itself change `seat_qci()`; `tests/test_agy_qci.py`
decides, as above (`panel_invoker.py` is in the validator's source-hash supplement, so that
table is updated as a reviewed change when only it flags). A changed canonical jail digest
is never normalized to reuse a pass record. No lane runs a jail qualification on a host; the tests
that touch the qualifier construct its jail with a harmless stand-in and record no pass.

## 4. Codes

No new refusal code. A hold is an admission; with no qualifying candidate the subject's
original refusal is raised unchanged. §2.2's `reason` values are evidence values only.

## 5. Roadmap amendment text

**External Inputs** adds this file with its sha256 as committed, and repins the AGYROLL
contract for §1.2 (archive bound; expanded-bytes rule) and, per D8/D9, §6.1/§6.2.

**New phase RESTORE:**

- EC-RESTORE-1 — A released `phase-loop-runtime` contains the 512 MB member bound, and
  `phase-loop agy-qualification status` on each host named in the O2 grant reports
  `verdict.status == "admits"` for the staged seat subject; operational evidence in
  `plans/evidence/agyfresh-restore.json`, stamped by the runner.
- EC-RESTORE-2 — AGYFRESH §1: at a patched bound N, an image of N−1 and of exactly N bytes
  is accepted and N+1 refused by `read_member`, `gh.admit`, `agy_integrity.check` and the
  verifier; an archive whose declared member sizes exceed `MAX_EXPANDED_BYTES` is refused;
  the seat reader's peak traced allocation stays under 4 MiB for any image size.

**New phase HOLD:**

- EC-HOLD-1 — For each hold-eligible reason in AGYFRESH §2.2, at preflight and at spawn, a
  held release member is admitted with source `lkg` and the reason in evidence; with no
  candidate the original refusal is raised unchanged.
- EC-HOLD-2 — Each never-eligible condition in §2.2 propagates unchanged with a candidate
  present, including no provider installed.
- EC-HOLD-3 — A held non-member needs a MAC-valid `provenance` and `qualified` entry and no
  `failed` entry, and is never executed before the provenance check; `hold_deny` excludes it.
- EC-HOLD-4 — First use runs for the subject before any hold; a passing subject is returned.
- EC-HOLD-5 — `admission_verdict(execute=False)` never reports `admits` for a non-member
  because of a held image; `[agy] hold = false` restores today's refusals.
- EC-HOLD-6 — Managed release: with a fallback image whose digest differs from the pinned
  subject, the real projection and jail admission pass (lane F0); otherwise managed hosts
  are recorded as not covered and the authority check is unchanged.
- EC-HOLD-7 — Order and budgets (§2.4): a newer vendor member beats an older cache member
  whatever their mtimes; 64 forged hints cannot prevent admission of an authenticated
  candidate; result is identical under shuffled directory order.
- EC-HOLD-8 — Resource rule (§1.2, §2.2): at most one sealed image is open at any point of a
  hold; every rejected, cancelled or failing candidate is closed.
- EC-HOLD-9 — Filesystem rule (§2.5): a symlinked candidate, a directory swapped for a
  symlink between listing and open, and a file whose replacement is observed during the read
  (AGYFRESH §2.5) are all rejected.
- EC-HOLD-10 — Cache (§2.8): retain, prune, corrupt-file removal and `clear --all` are
  correct under concurrent retain and clear.
- EC-HOLD-11 — (Consiliency/dotfiles) a selected agy the release runtime refuses no longer
  fails the release build when a retained image verifies.
- EC-HOLD-12 — `agy-qualification status` reports the hold state (§2.6).
- EC-HOLD-13 — Jailed standalone route (AGYFRESH §2.11): for a held admission the production
  and the probe jail bind the same admitted sealed image at `/seat/bin/gemini`, the bytes
  the seat executes hash to the evidence's `provider_image_sha256` after the candidate's
  source file is renamed, unlinked or rewritten, and the evidence carries source `lkg`; a
  descriptor that is not that sealed image is refused; a failed build and a cancellation
  leave no descriptor open; an ordinary launch keeps the existing path bind and its launch
  and evidence behaviour.
- EC-HOLD-14 — Jail qualification (AGYFRESH §2.11, §3): the canonical digest of every
  registered leg and every qualification key are the same before and after the jail
  integration lane; a sealed-image jail, the managed-dependency jail and every jail the
  qualifier builds each pass the unstubbed canonical comparison against their own leg's
  canonical digest.
- EC-HOLD-15 — Status (AGYFRESH §2.6): `hold` reports the subject class, coverage per route,
  and a candidate with its state; it never reports a candidate as in use.

**HOLD also produces:**

- IF-0-HOLD-5 — The standalone Gemini jail's sealed-image bind, its descriptor ownership and
  its evidence (AGYFRESH §2.11).

**ROLLJOB adds:**

- EC-ROLLJOB-7 — When the lag rule fails, the nightly workflow creates or updates exactly
  one open issue labelled `agy-lag`, and closes it on the next pass.
- EC-ROLLJOB-8 — Nightly `--upstream-only` measures the newest upstream archive and member
  and warns at 80%, fails at 90%, of `MAX_ARCHIVE_BYTES` or `MAX_MEMBER_BYTES`.
- EC-ROLLJOB-9 — The watch streams each member to a sealed descriptor and holds one member
  image at a time.

**REQUAL early slice adds:**

- EC-REQUAL-8 — The doctor's Gemini row names a hold candidate, its state and the route
  coverage (AGYFRESH §2.6, early slice), and never reports it as in use.

### 5.1 D8: frozen mapping (F1)

| Owner choice | Roadmap and contract | Lane A0 | Lane L6 |
|---|---|---|---|
| **D8-A: keep R6 as ruled** (also the default if no choice is made) | unchanged | edits nothing in §6.1, R6, EC-ROLLJOB-4, EC-ACTIVATE-2 | implements AGYROLL §6.1 exactly as written: job key **and** enrolled owner key on every catalog PR |
| **D8-B: amend R6** | replaced by the text below | lands the text below | implements the text below |

Text landed **only under D8-B**:

- *R6′.* R6 stands except that no catalog PR needs an owner signature. The second Q10 signer
  is the base branch's hosted provenance check, which re-fetches the asset by tag and
  re-derives the member digest. Only a PR whose diff is only `data/agy_catalog.json` and
  `plans/evidence/agy-*-linux-x64-qualification.json`, and that adds or ages non-`pinned`
  members, auto-merges. A `pinned` change, any other path, and any change to the signer list,
  verifier or merge-rule workflow never auto-merges: a maintainer merges it through the
  ordinary reviewed pull request under the non-bypassable `main` ruleset.
- *EC-ROLLJOB-4′.* As EC-ROLLJOB-4, with "valid job and enrolled-owner signatures" replaced by
  "a valid job signature and a passing base-branch provenance check that re-fetches the asset
  by tag and re-derives the member digest", for every catalog PR. Auto-merge stays limited to
  the diff class in R6′; any other diff never auto-merges and is merged by a maintainer under
  the non-bypassable `main` ruleset. No owner key is enrolled: `agy-allowed-signers` lists the
  job key only.
- *EC-ACTIVATE-2′.* The newest stable upstream release at activation reaches `main` through
  an `agy-catalog-auto` PR with no hand step.

Under either option: signatures are over the canonical record minus `signatures`, namespace
`agy-qualification`; the record binds `release_version`, `image_sha256`, `asset_sha256` and
`qci`, so a signature cannot be replayed onto another image or another contract identity,
and a stale-QCI record fails `--contract`. The verifier, signer list and merge rule are read
from the **base** branch; the PR head supplies data only.

What a compromised job identity can promote: under D8-A, nothing by itself. Under D8-B, a
**genuine** upstream stable release recorded as having passed live qualification when it did
not. It cannot promote non-upstream bytes, and it cannot promote a `pinned` flag or a policy
change without a maintainer merge. Hosted provenance re-verification proves the bytes are
upstream's; it does not prove the live operations passed. The seat jail contains a misbehaving
binary; it is not a substitute for that attestation.

**DAG after amendment:**

```
RECBIND ─┬─> RESTORE ──> HOLD ──> REQUAL(early slice) ─┐
         └─> PROVFWD ─┬─> REQUAL(rest) ──> EXECADMIT ──┼──> ACTIVATE
                      └─> ROLLJOB ─────────────────────┘
```

Single-writer order: `agy_qualification.py` RECBIND → HOLD → REQUAL;
`verify_qualified_agy_image.py` and `agy_provenance.py` RECBIND → RESTORE → PROVFWD → ROLLJOB.
ACTIVATE still depends on EXECADMIT and ROLLJOB as roadmapped. EXT-1916 is met
(agent-harness#1916 merged).

## 6. Binding review requirements (coordinator ruling, 2026-11-20)

The independent re-review of r2 accepted the design with three REQUIRED findings. The
coordinator ruled them **binding implementation requirements** for the lanes they touch; each
lane's code review verifies them. Where the text above conflicts, the requirement governs and
the lane's phase plan records the option it chose.

1. **Archive expansion (RESTORE caps lane; §1.1, EC-RESTORE-2).** *Satisfied by §1.1
   ("Archive accounting in `read_member`").* Summing declared
   `member.size` does not bound tar headers, padding or extension records parsed before a
   member is yielded. Count actual decompressed bytes below the tar parser against
   `MAX_EXPANDED_BYTES`, keep the separate member-size check, bound member count and parser
   metadata as needed, and add small-budget fixtures for large extension records and many
   empty members.
2. **One selection promise (HOLD core and cache lanes; §2.4, EC-HOLD-7).** *Resolved by
   §2.4 (no memo).* "The three newest
   authenticated candidates are always examined" means reserved authenticated read capacity
   *if earlier candidates fail*. Every admission preserves the §2.4 total order; the process
   memo may only skip discovery work where it cannot change that order. A test freezes the
   case of a newer eligible candidate appearing after the memo was populated.
3. **Replacement detection (HOLD core lane; §2.5, EC-HOLD-9).** *Resolved by §2.5
   (option (b)).* A before/after `fstat` of an
   open descriptor cannot see a rename over the pathname. The lane either (a) accepts the
   opened inode, states that rename or unlink is harmless, and tests that only its admitted
   sealed bytes run; or (b) compares a final descriptor-relative no-follow stat of the name
   with the opened inode and rejects a mismatch, stating the limit on transient swaps. The
   anchored traversal and no-follow opens stay either way.
