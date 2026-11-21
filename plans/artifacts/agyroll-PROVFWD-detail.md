# PROVFWD detail r3: forward provenance, attestation, callers, store wiring

Frozen detail for `plans/phase-plan-v1-agyroll-PROVFWD.md`. The design is AGYROLL §1
(`plans/artifacts/agyroll-v1-contract.md`); this file freezes the symbols, the per-file
changes and the test cases. Exit criteria are the roadmap's `EC-PROVFWD-*`; none is restated
here. A lane that needs a different interface stops and reports.

r2 (2026-11-20) applies the independent review and the coordinator's rulings: the daily cap is
enforced in production from this phase onward (§1.3, replacing r1's interim), and the
second-channel measurement is authorized within the bounds in §2.2.

r3 (2026-11-20) applies the r2 re-review's finding P1: the fetch ledger is keyed on the store
and the image only, shared across profiles (§1.3), and the ordering exception for rejected
assets is stated with the candidate-order rule (§1.2).

**Erratum (2026-11-20), two items, wording only.** (1) §1.3 no longer prescribes a
`ValueError` subclass for a first-use provenance refusal: an exact, plain `ValueError` that
carries `reason` is the approved form, for the reason given there. (2) §2.2 describes the
installer manifest by its interface and field names only. No requirement, bound, test case or
measured value changes.

Paths are under `phase-loop-runtime/` unless they start with a repository directory.
"Today" means `origin/main` with RESTORE's caps lane merged.

## 1. Resolver (`src/phase_loop_runtime/agy_provenance.py`)

### 1.1 Symbols

```python
DOWNLOAD_BUDGET = 2
TOTAL_DOWNLOAD_CAP = 12
TOTAL_DOWNLOAD_WINDOW_S = 86_400
LISTING_PAGE = 100
MAX_LISTED = 300
BUDGET_EXHAUSTED = "budget_exhausted"
DOWNLOAD_CAP_REACHED = "download_cap_reached"

class ProvenanceError(ValueError):
    def __init__(self, code, reason=None): ...   # str(exc) stays the code; exc.reason is new

@dataclass(frozen=True)
class Provenance:
    image_sha256: str
    platform: str
    asset: ReleaseAsset
    attestation: str = "not_checked"
    second_channel: str = "not_checked"

def version_hint(subject_path) -> str | None
def stable_releases(transport, *, limit=None) -> list[dict]
def find_provenance(image_sha256, *, host, transport=None,
                    cached_member=lambda asset: None,
                    remember_member=lambda asset, member: None,
                    hint=None, budget=DOWNLOAD_BUDGET,
                    fetch_times=lambda: (), note_fetch=lambda at: None,
                    rejected=lambda: {}, note_rejected=lambda asset_sha256, at: None,
                    attest=None, now=time.time) -> Provenance
```

Removed: `RECENCY_WINDOW`, the `window` parameter of `stable_releases` and of
`find_provenance`, and `RELEASES_PATH`'s `per_page=30`.

### 1.2 Behaviour

- **`version_hint`.** The first component of `os.path.realpath(subject_path)` that matches
  `^(\d+\.\d+\.\d+)(?:[-+].*)?$`; group 1 is the hint. It opens nothing, executes nothing and
  never reads `--version`. No matching component gives `None`.
- **`stable_releases`.** Pages `…/releases?per_page=100&page=N` lazily, in API order (the
  order it uses today), applying today's stable filter. It stops at a short page, at
  `MAX_LISTED` scanned entries, or once `limit` stable releases are collected. `limit=1`
  costs one request. Each page keeps the `MAX_LISTING_BYTES` bound.
- **Candidate order.** If `hint` is given and is a listed stable release, it goes first. The
  rest follow in listing order. A hint that names no listed stable release is ignored.
- **Ordering exception for rejected assets.** `rejected()` maps an asset digest to the number
  of times its archive refused `UNVERIFIED` in the last 24 h. A candidate with a count of one
  or more goes after every candidate with none, in listing order, so an archive that keeps
  refusing cannot use up every call's budget ahead of untried releases. The hinted candidate
  is the one exception: it keeps first place after a single rejection, which covers a
  download damaged in transit, and moves to the back at two. This changes order only. Every
  uncached fetch still costs both budgets, and admission still needs a member-digest match.
- **Per candidate.** `release_asset` failures skip the candidate, as today. A `cached_member`
  hit costs nothing. Otherwise, before the fetch:
  1. count the `fetch_times()` values newer than `now() - TOTAL_DOWNLOAD_WINDOW_S`; at
     `TOTAL_DOWNLOAD_CAP` or more, raise `ProvenanceError(UNVERIFIED, DOWNLOAD_CAP_REACHED)`;
  2. if this call has already fetched `budget` archives, raise
     `ProvenanceError(UNVERIFIED, BUDGET_EXHAUSTED)`;
  3. call `note_fetch(now())`, then fetch.

  `remember_member` runs after each successful fetch, before the next candidate. A fetch that
  refuses `UNVERIFIED` (a malformed asset) is skipped, has spent one unit, and is reported
  through `note_rejected(asset.digest, now())`. `UNAVAILABLE` propagates at once, as today;
  its fetch was already counted by `note_fetch`.
- **Match.** On a member match, `attest` (default: `agy_attestation.attestation_status`,
  imported inside the function) is called once for the matched asset. Its value is
  `Provenance.attestation`; `second_channel` stays `not_checked`. A `ProvenanceError` from
  `attest` propagates.
- **No match after every candidate was examined:** `ProvenanceError(UNVERIFIED)` with
  `reason is None`. That is the definitive refusal; the two reasons are the retryable ones.

### 1.3 Store ledger and seat call-site wiring (`src/phase_loop_runtime/agy_qualification.py`; SL-5)

The resolver never ships with an empty ledger on the production route. The roadmap's split
("`agy_qualification.py` is not touched; REQUAL passes the hint") is amended (§6) so that this
phase owns one small, serialized edit to that file, after HOLD's core lane. The reason: R4's
total bound is a condition of removing the window, and a resolver without it lets an
unmatched image download without a daily limit.

This section is written against AGYFRESH §2.2 (`admit_seat`). The lane reconciles names with
the landed code. If the landed first-use stage cannot carry what follows without changing a
hold-eligibility rule, the lane stops and reports.

**Store: a new MAC-bound entry type `fetch_ledger`, keyed on the store and the image.**

```python
def fetch_times(self, image_sha256, host) -> tuple[float, ...]
def note_fetch(self, image_sha256, host, at) -> None
def rejected_assets(self, image_sha256, host, *, now) -> dict[str, int]
def note_rejected(self, image_sha256, host, asset_sha256, at) -> None
```

- **Key.** The entry's context is `{image_sha256, platform}`. It does **not** include the
  profile digest, the help digest or the runtime version, so every profile and every runtime
  that uses one store shares one allowance per image. This is R4's "(store, image)".
- **Why not the `transient` entry.** AGYROLL §1.2 said the fetch times ride in the
  `transient` entry. That entry is keyed with the profile digest and is deleted on a pass and
  by `agy-qualification clear`, so a profile change or a routine reset would start a fresh
  allowance. §6 amends that sentence.
- **Payload.** `fetches` (times, pruned to the last 24 h, at most `TOTAL_DOWNLOAD_CAP` kept)
  and `rejected` (asset digest → list of times, pruned to 24 h, at most `MAX_LISTED` digests).
- **Lifetime.** `reset_transients`, a qualification pass, and `agy-qualification clear`
  without `--all` leave the ledger alone. Only `agy-qualification clear --all` removes it;
  `fetch_ledger` joins `_ENTRY_TYPES` for that purpose. Entries older than 24 h are dropped
  on the next write.
- **Serialization.** Check and charge happen together under the store's one lock, which the
  first-use path already holds and which is per store, not per profile: the count is read,
  compared with the cap and incremented before the fetch starts, with no release in between.
  A download that fails or is interrupted is therefore still counted, and two processes on
  different profiles cannot both spend the last unit.
- **Tampering.** A ledger whose MAC does not verify is treated as **full** for 24 h from the
  moment it is seen, then rewritten. It is never read as empty.
- `put_provenance` also writes `attestation` and `second_channel` from the `Provenance`
  (AGYROLL §1.3).
- `Store.status()` must stay `ok` with the new entry present. If the store's own checks or
  HOLD's landed cache layout make that impossible without changing them, the lane stops.

**First-use provenance stage.** The one `find_provenance` call passes
`hint=agy_provenance.version_hint(subject_path)` and the four ledger callables bound to
`(image, host)`. A `ProvenanceError` becomes an exact, plain `ValueError` (not a
subclass) whose `str()` is the code, as today, and which carries the reason as a `reason`
attribute. *Erratum:* this replaces "a `ValueError` subclass". HOLD's core lane re-raises
the subject's original refusal unchanged, and its tests pin that exception's exact type, so a
subclass would change what callers and those tests observe. A plain `ValueError` with the
attribute preserves the type, the code and the object's identity through that re-raise, and
still gives `on_retryable` its reason.

**Retryable outcomes.** `ensure_admitted` (and `admit_seat`) gain a keyword
`on_retryable=None`. It is called when the subject's provenance stage refuses with
`budget_exhausted` or `download_cap_reached`, whether the caller then raises or a hold
admits another image. `requalify_once` passes a callback that discards its once-per-key
entry, exactly as it does for `CANCELLED`, so the next preflight in the same process
continues the walk. Neither reason calls `note_transient`. A hold stays eligible for these
refusals under the existing `provenance_unverified` reason; no hold rule changes.

**Not in this phase.** The `preflight` CLI, the runner and canary call sites, failed classes
and the TEAMHOST §5 repin stay with REQUAL, which inherits this wiring for EC-REQUAL-1.

## 2. Attestation and second channel (`src/phase_loop_runtime/agy_attestation.py`, new)

### 2.1 Symbols

```python
ATTESTATION_STATUSES = ("absent", "present_unverified", "not_checked")
SECOND_CHANNEL_STATUSES = ("match", "not_listed", "not_checked")
SECOND_CHANNEL_MISMATCH = "agy_provenance_second_channel_mismatch"
MANIFEST_HOST = "antigravity-cli-auto-updater-974169037036.us-central1.run.app"
MANIFEST_PATH = "/manifests/linux_amd64.json"
MANIFEST_DOWNLOAD_PREFIX = "https://storage.googleapis.com/antigravity-public/antigravity-cli/"
MAX_MANIFEST_BYTES = 262_144

def attestation_status(asset, transport=None) -> str      # "absent" | "present_unverified"
def second_channel_status(asset, member_sha256, *, host, transport=None) -> str   # "match" | "not_listed"
```

### 2.2 Behaviour

- **Transport.** The module has its own pinned opener. It reuses
  `agy_provenance._trust_context`, `USER_AGENT` and `ProvenanceError`, sends no credentials,
  uses no proxy, follows no redirect, and allows exactly three hosts: `api.github.com`,
  `MANIFEST_HOST` and `storage.googleapis.com`. It does not change `agy_provenance._Transport`.
- **`attestation_status`.** `GET /repos/google-antigravity/antigravity-cli/attestations/sha256:<asset.digest>`.
  HTTP 404 gives `absent`. HTTP 200 whose body is a JSON object with a non-empty
  `attestations` list gives `present_unverified`. Anything else (another status, an empty
  list, a non-object, an oversized or unparseable body, a network error) raises
  `ProvenanceError(UNAVAILABLE)`. It never verifies an attestation and never refuses for
  `absent`. Treating an empty list as malformed is the conservative reading; the lane checks
  GitHub's documented response shape and keeps a fixture of it. This query makes the GitHub
  API a dependency of first use: a rate-limited answer refuses `unavailable`.
- **`second_channel_status`.** Only `linux-x64` has a manifest; any other platform returns
  `not_listed` without a request. It reads the manifest, a JSON object with the fields
  `version`, `url` and `sha512`. An unreachable or malformed manifest raises
  `ProvenanceError(UNAVAILABLE)`. A manifest for another version returns `not_listed`. For
  the same version it compares on the measured basis below; equality returns `match`, a
  difference raises `ProvenanceError(SECOND_CHANNEL_MISMATCH)`.
- **Manifest validation.** Before any comparison the manifest must be a JSON object whose
  `version` matches `^\d+\.\d+\.\d+$`, whose `url` starts with `MANIFEST_DOWNLOAD_PREFIX`,
  and whose `sha512` is 128 hex characters. Anything else is `UNAVAILABLE`.
- **`not_listed` is not corroboration.** It records that the second channel could say nothing
  about this version, for example because the manifest has moved on. It never reports `match`
  for a version the manifest does not name, and a manifest that changes version between two
  reads of one check yields `not_listed`.
- **Comparison basis, measured before it is frozen (task SL-1.1).** The contract does not say
  whether Google's package is byte-identical to the GitHub asset. The coordinator authorized
  the measurement on 2026-11-20: public, unauthenticated reads only, through the pinned
  opener, with no credentials, proxy or redirect, under the existing archive, member and
  expanded-byte bounds, hashing while streaming, and executing nothing downloaded. It reads
  the manifest and the GitHub asset; the member basis also reads Google's package. The lane
  measures it once, for the newest release:
  - *archive basis:* the manifest `sha512` equals the SHA-512 of the GitHub asset; or
  - *member basis:* the manifest's package, fetched from `MANIFEST_DOWNLOAD_PREFIX`, checked
    against the manifest `sha512` and read with `agy_provenance.read_member`'s bounds, has an
    `antigravity` member whose SHA-256 equals `member_sha256`.

  The lane implements the first basis that holds, commits redacted fixture evidence of the
  measurement (version, sizes and digests only) with its tests, and records the basis in
  `advisor_board/CONTRACTS.md`. The basis is frozen before SL-2 starts. One release selects
  the method; it does not prove the two channels stay identical, which is why a later
  difference refuses the tick rather than being assumed away. **Stop rule:** if neither basis
  holds, the lane stops and reports; it does not ship a check that would refuse every tick.

## 3. Callers

### 3.1 `src/phase_loop_runtime/agy_watch.py`

- `main`: the listing call becomes `stable_releases(transport, limit=1)` for the newest
  release, and `stable_releases(transport)` filtered by tag for `--version`. Any listed
  stable release can be selected.
- After the new member is fetched, `main` calls `attestation_status(asset)` and
  `second_channel_status(asset, member_sha256, host=host)`. `summarize` gains keyword
  parameters `attestation` and `second_channel` and writes them into `upstream`.
  A requalified existing member records a fresh `attestation` and keeps its committed
  `second_channel`.
- A `SECOND_CHANNEL_MISMATCH` or `UNAVAILABLE` from either call ends the tick with exit 2 and
  that code as `agy_watch`; nothing is pushed.

### 3.2 `scripts/verify_qualified_agy_image.py`

- `validate_record`: `upstream.attestation` must be in `ATTESTATION_STATUSES` and
  `upstream.second_channel` in `SECOND_CHANNEL_STATUSES` (imported from the tree's package).
- `upstream_only`: the newest stable release comes from the first listing page
  (`…/releases?per_page=100`) through a new `newest_stable(fetch)`, with the resolver's
  stable filter, instead of `/releases/latest`. The result adds `latest_published_at`.
  Membership stays advisory in this phase; ROLLJOB adds the lag rule.

## 4. Tests

### 4.1 `tests/test_agy_provenance_forward.py` (new; SL-2)

1. Eighteen newer releases, subject nineteenth, cold cache: admitted after repeated calls,
   each call fetching at most `budget`; with the hint, admitted in one call and one fetch.
2. Fourteen releases, subject ninth newest: a provenance entry through `find_provenance`.
3. Tampered image, budget 2: exactly two fetches, `UNVERIFIED` with `reason ==
   "budget_exhausted"`; the second call fetches the next two (`member_cache` progress); with
   every member cached, zero fetches and `reason is None`.
4. Ledger: twelve fetch times inside 24 h give `download_cap_reached` with zero fetches;
   times older than 24 h do not count; `note_fetch` is called once per fetch, before it.
5. `version_hint`: the contract's example path; a symlinked path resolves first; no matching
   component gives `None`; `open`, `os.open` and `subprocess` patched to raise are never
   reached.
6. A wrong hint still admits the genuine image; no hint admits a non-matching image.
7. Listing: a second page is requested only when needed; `limit=1` makes one request; a
   listing longer than `MAX_LISTED` stops there; a 2-page fixture keeps API order.
8. Rejected ordering: two malformed archives at the head of the listing, reported through
   `note_rejected`, are tried last on the next call, which then reaches untried releases.
9. `Provenance.attestation` carries the `attest` value; an `UNAVAILABLE` from `attest`
   refuses; `second_channel == "not_checked"`.
10. `str(ProvenanceError(code, reason)) == code`.
11. Static: no `RECENCY_WINDOW` and no `window=` in `src/phase_loop_runtime/agy_*.py`.

### 4.2 `tests/test_agy_self_qualification.py` (existing; SL-2)

- The in-window first-use test stays as it is. The outside-the-window test is rewritten: the
  image is now found, within the calls its position needs.
- The fake transport serves the paged listing. Every §1.1 transport, asset and member test
  stays green unmodified.
- Watch tests: `--version` selects a release outside the old window; a mismatching second
  channel ends the tick with exit 2 and no push; the record carries the two statuses.

### 4.3 `tests/test_agy_attestation.py` (new; SL-1)

404 → `absent`; a non-empty list → `present_unverified`; an empty list, a non-object, HTTP
403/500, an oversized body and a network error → `UNAVAILABLE`; a redirect is refused; a host
outside the three is refused; no `Authorization` header is sent. Second channel: same version
and equal → `match`; same version and different → `SECOND_CHANNEL_MISMATCH`; another version
→ `not_listed`; unreachable or malformed → `UNAVAILABLE`; a non-`linux-x64` host → `not_listed`
with no request.

### 4.4 `tests/test_agy_upstream_advisory.py`, `tests/test_agy_record_v2.py` (existing; SL-3)

The fake upstream serves the listing; the newest stable release is chosen with the resolver's
filter on a shared fixture (a prerelease and a draft ahead of it are ignored); the result has
`latest_published_at`; a record with an out-of-vocabulary status fails `validate_record`; the
committed records still pass.

### 4.5 `tests/test_agy_provenance_wiring.py` (new; SL-5)

Every case goes through the real `requalify_once` and a real `Store` in a temporary state
home, with a fake transport and an injected clock.

1. Subject ninth of fourteen under a versioned path: one preflight, one fetch, a `provenance`
   entry (the hint reaches the resolver).
2. Same subject under an unversioned path: the first preflight refuses `unverified`; a
   **second preflight in the same process** continues and the image is admitted within the
   calls its position needs. The once-per-key entry was released each time.
3. Tampered image: twelve fetches inside 24 h across preflights, then
   `download_cap_reached` with no further fetch; after the clock passes 24 h, fetching
   resumes. The count survives a new `Store` object (it is on disk).
3a. **Multiple profiles, one store and image.** With `agy_profile_digest` patched to a
   second value halfway through, the two profiles together get twelve fetches, not twelve
   each; the thirteenth refuses `download_cap_reached` under either profile.
3b. A qualification pass (`reset_transients`) and `agy-qualification clear` leave the count
   in place; `agy-qualification clear --all` removes it.
3c. Two threads on different profiles racing for the last unit: exactly one fetch happens.
4. A fetch that raises mid-download is counted.
5. Neither retryable reason increments the transient count or writes a `failed` entry.
6. A tampered `fetch_ledger` entry (bad MAC) refuses `download_cap_reached` with no fetch,
   and is usable again 24 h later. It is never read as empty.
6a. The hinted candidate keeps first place after one rejection and goes last after two.
7. With a held release member present, a retryable refusal admits the hold and still
   releases the once-per-key entry.
8. The `provenance` entry carries `attestation` and `second_channel`.

## 5. Inventory

`tests/data/seat_launch_references.json` is exact in both directions. SL-5, the last code
lane, owns it: it adds the rows for every new `io.open` site in `agy_provenance.py`,
`agy_attestation.py`, `agy_watch.py` and `agy_qualification.py`, and removes none that still
exists. Earlier lanes do not run the inventory test.

## 6. Contract and roadmap amendment text (applied by SL-4)

Applied in this phase's pull request. It changes no exit criterion. It changes two sentences
of AGYROLL §1.2, so SL-4 also recomputes the AGYROLL digest in the roadmap's External Inputs
from the committed file.

**AGYROLL §1.2, "Candidate order".** Append:

> A candidate whose archive refused `unverified` in the last 24 h is tried after every
> candidate that has not, except that the hinted candidate keeps first place after a single
> refusal. This changes order only.

**AGYROLL §1.2, "Total bound".** Replace "The fetch times ride in the MAC-bound `transient`
entry." with:

> The fetch times ride in a MAC-bound `fetch_ledger` entry keyed on the image and platform
> only, shared by every profile and runtime that uses the store. Check and charge are done
> together under the store lock. A pass or `agy-qualification clear` does not reset it;
> `clear --all` does. An entry whose MAC does not verify counts as a reached cap.

**Roadmap (`specs/phase-plans-agyroll-v1.md`).**

- **PROVFWD scope notes.** Replace "`agy_qualification.py` is not touched; REQUAL passes the
  hint." with: "PROVFWD also owns one serialized edit to `agy_qualification.py`, after HOLD's
  core lane: the store's fetch ledger, the hint and ledger at the first-use call site, and
  release of the once-per-key entry on the two retryable reasons. R4's total bound is a
  condition of removing the window, so the resolver does not ship without it (coordinator
  ruling, 2026-11-20)."
- **PROVFWD key files.** Add `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`
  and `phase-loop-runtime/tests/test_agy_provenance_wiring.py`.
- **PROVFWD depends on.** Add `HOLD`.
- **Dependency DAG and its notes.** PROVFWD's resolver and attestation lanes run beside
  RESTORE and HOLD; its wiring lane and its merge follow HOLD's core lane.
- **Single-writer files.** `agy_qualification.py`: RECBIND → HOLD → PROVFWD (ledger and call
  site) → REQUAL.
- **REQUAL scope notes.** Add: "The hint, the fetch ledger and the retryable release landed
  with PROVFWD; REQUAL's preflight inherits them."
