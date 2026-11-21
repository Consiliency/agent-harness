# ROLLJOB detail r9.1: the tick, promotion policy, lag and headroom

Frozen detail for `plans/phase-plan-v1-agyroll-ROLLJOB.md`. The design is AGYROLL §6
(`plans/artifacts/agyroll-v1-contract.md`) as amended by AGYFRESH §5 and §5.1
(`plans/artifacts/agyfresh-contract.md`): R6′ under owner decision D8 = B, the hourly tick
(D9), and `EC-ROLLJOB-7..9`. This file freezes symbols, per-file changes and test cases. It
restates no exit criterion. A lane that needs a different interface stops and reports.

r3 (2026-11-20) replaces r2's identity design. The owner ruled that no new GitHub user account
is created per use case, so the fork-and-machine-user design is withdrawn. Two organization-
owned GitHub Apps split the work by trust boundary (R9′):

- the **INTAKE App**, whose key is on the qualification host, can only write issues. The job uses it to submit
  a signed qualification record as data;
- the **PROMOTION App**, whose key exists only as an Actions environment secret, has contents
  and pull-requests write. A workflow on `main` uses it to author the catalog pull request
  itself, from a record it has verified.

There is no fork, no `pull_request_target`, and no pull-request head written by the job. The
contract text is `plans/artifacts/agyroll-ROLLJOB-amendment.md` (ROLLJOB-amendment), applied
by lane SL-5 once the owner's confirmation of R9′ is recorded. r3 also makes the lag alarm
report-only until ACTIVATE (§5).

r4 (2026-11-20) applies the r3 re-review's five required items and the coordinator's rulings:
an attestation file for what tokens cannot read (§4.5); an author-agnostic required check on
every pull request that touches the catalog (§4.4); authenticated dispatch, reporting and durable recovery (§4.3); an
optional dependency extra for RS256 (§2.5); and an executable off-to-on step for ACTIVATE (§7).

r5 (2026-11-20) applies one owner decision: **no extra review**. Every agent pushes as the
owner's account, which cannot approve its own pull requests, and enforcing code-owner review
would also bind the existing CODEOWNERS lines. So r4's CODEOWNERS enforcement and its
maintainer-review condition are removed. Organization members with write access stay trusted
for these files as for any other code (§4.4). Nothing else in r4 changes.

r6 (2026-11-20) applies the r5 re-review: the new check is made required only after it has
run against a base that contains its verifier (§7); locking is per job (§4.3); the link from
an issue to its pull request and the bound on failures before a pull request exists are
derived from facts an issues-only credential cannot edit (§4.3).

r9 (2026-11-20) follows PROVFWD's merge (agent-harness#2039). The interfaces this file relies
on were re-checked against the merged code: `stable_releases(transport, limit=)`,
`attestation_status`, `second_channel_status`, `summarize(…, attestation, second_channel)`,
`newest_stable` and `latest_published_at`, the two closed status vocabularies in
`validate_record`, `read_member(…, keep_bytes=)` with its callers, the store's entry types
(`watch_push` is still one, `fetch_ledger` is new), and the plain `ValueError` with `reason`
that a first-use provenance refusal is. One sentence changed, in §2.1 step 2. The
qualification host is named by role throughout.

r9.1 (2026-11-21) applies the r9 review's three items: this phase's pull request may merge
under the existing branch protection, and the live setup may finish after it (§7); the
runtime install is separated from preparing the job account (§7); and §2.1 step 2 states
which admission failures the tick can meet when it renews the login, with tests for both the
host subject and a held image (§6.3).

Paths are under `phase-loop-runtime/` unless they start with a repository directory. "Catalog"
is `phase-loop-runtime/src/phase_loop_runtime/data/agy_catalog.json` (R6′ writes it as
`data/agy_catalog.json`). "Record" is `plans/evidence/agy-<x.y.z>-linux-x64-qualification.json`.

## 1. Policy primitives (`src/phase_loop_runtime/agy_catalog_policy.py`, new; SL-0)

Standard library only, no import from `agy_qualification`, `gemini_heartbeat` or
`panel_invoker`, so the base-branch verifier can import it cheaply.

```python
SERIES_RETRIES = 3
CATALOG_KEEP = 3
CATALOG_MIN_AGE_S = 14 * 86_400
LAG_BOUND_S = 48 * 3_600
HEADROOM_WARN_PERCENT = 80
HEADROOM_FAIL_PERCENT = 90
CATALOG_LABEL = "agy-catalog-auto"
INTAKE_LABEL = "agy-intake"
INTAKE_SCHEMA = "agy-intake.v1"
MAX_RECORD_BYTES = 60_000
RESUBMIT_AFTER_S = 86_400
CATALOG_BRANCH_PREFIX = "agy-catalog/"
LAG_ENFORCE_ENV = "AGY_LAG_ENFORCE"
UPSTREAM_REPO = "google-antigravity/antigravity-cli"   # the only upstream; never taken from a submission
ATTESTATION_PATH = "config/agy-rollout-attestation.json"
ATTESTATION_SCHEMA = "agy_rollout_attestation.v1"
IN_FLIGHT_MAX_S = 86_400
INTAKE_STALE_AFTER_S = 6 * 3_600
MAX_PROMOTION_ATTEMPTS = 6
MAX_PREPR_FAILURES = 6
LAG_LABEL = "agy-lag"
SIGNATURE_NAMESPACE = "agy-qualification"
SIGNER_PRINCIPAL = "agy-watch"
ALLOWED_SIGNERS = "plans/evidence/agy-allowed-signers"
CATALOG_PATH = "phase-loop-runtime/src/phase_loop_runtime/data/agy_catalog.json"
RECORD_PATH = re.compile(r"plans/evidence/agy-(\d+\.\d+\.\d+)-linux-x64-qualification\.json")
SIGNING_KEY_ENV = "AGY_WATCH_SIGNING_KEY"
TICK_STATUS_SCHEMA = "agy_watch_tick.v1"

def canonical_record(record: dict) -> bytes
def sign_record(record: dict, key_path, *, runner=subprocess.run) -> dict
def verified_signers(record: dict, allowed_signers_path, *, runner=subprocess.run) -> list[str]
def aging(members: list[dict], *, now: float) -> tuple[list[dict], list[dict]]   # (kept, pruned)
def catalog_change(base: list[dict], head: list[dict], *, now: float) -> CatalogChange
def build_catalog(base: list[dict], record: dict, *, published_at: str, now: float) -> list[dict]
def render_intake(record: dict) -> str
def parse_intake(body: str) -> dict
def parse_catalog(text: str) -> list[dict]
def candidate_member(record: dict) -> dict
def load_attestation(text: str) -> Attestation
def authentic_author(user: dict, via_app: dict | None, expected: AppIdentity) -> bool
def headroom(size: int, bound: int) -> str                                       # "ok" | "warn" | "fail"
def tick_status_path(environ=None) -> Path
def write_tick_status(status: str, exit_code: int, *, version=None, environ=None, now=None) -> None
def read_tick_status(environ=None) -> dict | None
```

- **`canonical_record`.** `json.dumps` of the record without its `signatures` key, with
  `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=True`, UTF-8.
- **`sign_record`.** Runs `ssh-keygen -Y sign -n agy-qualification -f <key>` with the
  canonical bytes on stdin, and returns the record with one entry appended:
  `{"principal": "agy-watch", "namespace": "agy-qualification", "signature": "<armored>"}`.
  The key path is never printed. A missing key, a key readable by group or others, or a
  non-zero exit raises `ValueError("agy_watch_signing_unavailable")`.
- **`verified_signers`.** For each entry, `ssh-keygen -Y verify -f <allowed signers> -I
  <principal> -n agy-qualification -s <signature file>` over the canonical bytes, in a
  private temporary directory. It returns the distinct principals that verify. A malformed
  entry is ignored, never an error; an empty result is the caller's refusal.
- **`aging`.** A member is kept when it is `pinned`, or among the `CATALOG_KEEP` highest
  `release_version` tuples, or `published_at` is less than `CATALOG_MIN_AGE_S` before `now`.
  Everything else is pruned. An unparseable `published_at` keeps the member.
- **`catalog_change`.** Compares parsed member lists and returns
  `CatalogChange(added, removed, modified, auto: bool, reasons: tuple[str, ...])`. `auto` is
  true only when all of these hold:
  1. exactly one member is added, it is not `pinned`, and its version is greater than every
     base member's;
  2. every removed member is in `aging(base + added, now)`'s pruned list;
  3. no surviving base member differs in any field, `pinned` included.
- **`parse_catalog`.** A strict parser of `qualified_agy_catalog.v3`, standard library only,
  tested equal to `gemini_heartbeat.parse_catalog` on accepting and rejecting fixtures. It
  exists so the required check of §4.4 imports one small module and nothing else.
- **`candidate_member`.** Validates the record as a closed v2 record for this route and
  returns the member it describes (`release_version`, `image_sha256`, `help_sha256`,
  `asset_sha256`, `qci`, the record's file name). It decides validity only. It does not look
  at the existing catalog, so an existing or older version is still a valid candidate.
- **`build_catalog`.** The base members, plus `candidate_member(record)` as a non-pinned
  member with the given `published_at`, minus `aging()`'s pruned list. Eligibility is decided
  here and only here: it refuses a version that is already a member or is not greater than
  every member's.
- **`load_attestation`.** Parses §4.5's file with a closed schema. Any missing, extra or
  mistyped field raises; `status` other than `attested` is returned as unattested. Nothing is
  defaulted: an absent bypass list is an error, never an empty list.
- **`authentic_author`.** True only when the author's immutable numeric `id` equals the
  attested bot user id, its `type` is `Bot`, **and** the App object GitHub attaches to the
  issue or pull request is present with the attested App id. A missing field is `False`.
- **`render_intake` / `parse_intake`.** An intake body is exactly: one header line
  `agy-intake.v1 <release_version> <qci> <sha256 of the record text>`, a blank line, and one
  fenced `json` block holding the record text (the canonical bytes with `signatures`
  included, re-serialized sorted). `parse_intake` requires a full match of that shape, at
  most `MAX_RECORD_BYTES`, a header that agrees with the record, and a digest that agrees
  with the block. Anything else raises. It never evaluates or imports anything.
- **`headroom`.** `fail` when `size * 100 >= bound * HEADROOM_FAIL_PERCENT`, else `warn` when
  `size * 100 >= bound * HEADROOM_WARN_PERCENT`, else `ok`.
- **Tick status.** One JSON file, `<state home>/phase-loop/agy-watch/last-tick.json`, where
  the state home is `$XDG_STATE_HOME` or `~/.local/state`. The directory is 0700, the file
  0600, written to a temporary name and renamed. It lives outside the qualification store,
  whose entry types are closed. Content: `{"schema", "at" (RFC 3339 UTC), "status", "exit",
  "version"}`. `read_tick_status` returns `None` for a missing, foreign-owned, symlinked or
  malformed file.

## 2. The tick (`src/phase_loop_runtime/agy_watch.py`, `agy_provenance.py`; SL-2)

### 2.1 Order of one tick

1. Platform check, as today.
2. **Login (R7).** Read the login's remaining time with `panel_invoker._gemini_login_left_s`
   for the job's home. If it is not fresh, renew through `_await_gemini_login` then
   `_refresh_gemini_credential(home, image)`, where `image` is whatever the seat admission
   boundary (`admit_seat`, lookup only) admits on this host: the host's own subject, or a
   held image when HOLD applies. It is never the unqualified candidate.
   - **What a refusal looks like.** Lookup-only admission refuses with an ordinary
     `ValueError`, which usually has no `reason` attribute. Only a first-use provenance
     refusal is the plain `ValueError` that carries `reason`, and renewal never runs first
     use. So the tick never reads `reason`: any `ValueError` from this call means "no
     admitted image".
   - Typed failures that are not a refusal (for example an egress or sandbox failure)
     propagate unchanged, as they do for any caller. The tick does not turn them into a
     login status.

   If no admitted image exists to renew with, the tick writes status `gemini_login_expired`,
   prints it, and returns 2 without calling either renewal function and before any listing,
   fetch, candidate work or submission. The same status and exit apply if the login is still
   not fresh after renewal. A fresh login costs one local file read.
3. Newest stable release (`stable_releases(transport, limit=1)`). `already_pinned` when it is
   a member on `origin/main`. `up_to_date` when a submission for this version and QCI is
   pending (§2.5).
4. **Work set.** The newest non-member release, plus every existing member whose catalog
   `qci` differs from the prepared tree's `seat_qci()`. Members whose `qci` matches are not
   fetched, not run and not rewritten.
5. **Per member, one at a time (EC-ROLLJOB-9).** Stream the member to a sealed descriptor
   (§2.2); measure help; run the series (§2.3); write the signed record (§2.4); close the
   image before the next member starts.
6. `--contract` on the prepared tree, which exists only on the qualification host. The local catalog edit is
   what lets the worker gate pass; it is never pushed. Aging is not done here: the trusted
   workflow builds the catalog (§4).
7. Submit each signed record (§2.5).
8. Every return path writes the tick status with the same value it prints as `agy_watch`
   and the exit code it returns. `--dry-run` writes no status and submits nothing.

**The job makes no git write.** `publish_branch`, the push-destination checks, branch naming
and `gh pr create` are removed from the watch, with their tests. The checkout on the qualification host is
fetched, never pushed.

### 2.2 Streaming (`agy_provenance.py`)

```python
def read_member(stream, asset, *, sink=None) -> str          # the member's sha256
def fetch_member(transport, asset, *, sink=None) -> str
```

`keep_bytes` and the `bytes` half of the return value are removed. With `sink` (a writable
descriptor), each member chunk is written to it as it is hashed. The archive-digest equality
check still decides the result: on any refusal the caller discards the sink. The watch passes
an anonymous temporary file in its private work directory, then builds the image with
`gh.VerifiedImage.from_fd`, compares `image.sha256` with the returned digest, and closes the
temporary file. One sealed image exists at a time; no member is held as `bytes`.
`find_provenance` and every other caller use `fetch_member(transport, asset)` and take the
digest.

### 2.3 Series, retries, violation

A series is the three operations plus `--validate`, run by the prepared tree's shim as today.
On a failed series the watch asks the **prepared tree's** `_classify_failure` for the failed
operation's directory, in a subprocess like `_IDENTITY_PROGRAM`. `failed` is a violation: the
tick stops with status `series_violation`, exit 2, and no submission. `transient` retries the whole
series in a fresh directory, up to `SERIES_RETRIES` attempts in total; exhaustion ends the
tick with `series_unavailable`, exit 2. `agy_qualification.py` is not edited.

### 2.4 Signing

After `summarize`, the watch calls `sign_record(record, os.environ[SIGNING_KEY_ENV])`. A tick
that is not a dry run and cannot sign ends with `agy_watch_signing_unavailable`, exit 2,
before anything is submitted. A dry run writes an unsigned record.

### 2.5 Submission through the INTAKE App (`src/phase_loop_runtime/agy_intake.py`, new)

```python
def installation_token(app_id, installation_id, key_path, *, transport=None, now=None) -> str
def submit(record, token, *, transport=None) -> int            # the issue number
def pending(version, qci, token, *, transport=None, store=None, now=None) -> bool
```

- **Token.** A short-lived RS256 app JWT, exchanged for an installation token requested with
  `repositories: ["agent-harness"]` and `permissions: {"issues": "write"}` only. The key path
  comes from `AGY_INTAKE_APP_KEY`; the key must be a regular file, owned by the job account,
  mode 0600. The token and key never reach a log, an argv or a status line.
- **RS256 through an optional extra.** `pyproject.toml` gains the extra `agy-watch`, holding
  `cryptography` at the version already in `uv.lock`, and the lock is regenerated for it. The
  JWT is assembled in `agy_intake.py` and signed directly with `cryptography` (PKCS#1 v1.5,
  SHA-256); PyJWT is not used. The import is lazy. Without the extra the tick ends with
  `agy_intake_dependency_missing`, exit 2, before any live operation. The test dependency
  group includes the extra, so hosted CI runs the signing test rather than skipping it. The
  qualification host installs `phase-loop-runtime[agy-watch]` (§7).
- **Transport.** `http.client` to `api.github.com` only, no proxy, the compiled-in trust
  store, no redirect, as `agy_provenance._Transport` does. The watch no longer calls `gh`.
- **Receipt.** The store's closed entry types cannot grow here, so the receipt reuses the
  `watch_push` type under a context no push receipt ever had:
  `{"kind": "intake_receipt.v1", "version", "qci"}`, payload
  `{"issue", "record_sha256", "at"}`. A historical push receipt has another context and
  another payload shape; the reader requires both, so it can never count as an issue receipt.
- **`submit`.** First it lists open issues created by this App with the same header line.
  If one exists, it adopts that issue and writes the receipt, which is how a lost POST
  response is recovered without a duplicate. Otherwise it creates one issue titled
  `agy intake: <version>` with label `agy-intake` and body `render_intake(record)`, then
  writes the receipt.
- **`pending`.** Decided from the receipt and the issue's current state, read back:
  - issue open and younger than `INTAKE_STALE_AFTER_S` → pending, tick is `up_to_date`;
  - issue open and older → the tick ends with `intake_stalled`, exit 2, so `--check` shows
    it; the hosted reconcile of §4.3 owns the retry, and the job does not re-qualify;
  - issue closed and the version is not a member → refused or exhausted; the job waits
    `RESUBMIT_AFTER_S` from the receipt, then qualifies and submits again;
  - no receipt and no own open issue → not pending.

  An operator re-run with `--version` ignores the wait.
- **Refusals.** A missing or unsafe key gives `agy_intake_unavailable`, and a missing extra
  gives `agy_intake_dependency_missing`, each exit 2 before any live operation runs, so inference is never spent on a record that cannot be submitted. An
  API failure after qualification gives `agy_intake_submit_failed`, exit 2; the signed record
  stays in the work directory and the next tick submits it without re-qualifying.
- **What a compromised qualification host can do with this.** Create, edit, label and close issues and
  comments in this repository, and submit a signed record. It cannot write code, refs,
  pull requests, workflows, variables or settings.

## 3. Units, install and check (`agy_watch_units.py`, `cli.py`, unit files; SL-1)

- **Timer.** `OnCalendar=hourly`, `RandomizedDelaySec=10m`, `Persistent=true`.
- **Service.** Adds `Environment=` lines for `AGY_WATCH_SIGNING_KEY` and `AGY_INTAKE_APP_KEY`
  (both under `%h/.config/phase-loop/agy-watch/`), and an `EnvironmentFile=-%h/.config/phase-loop/agy-watch/intake.env`
  that supplies `AGY_INTAKE_APP_ID` and `AGY_INTAKE_INSTALLATION_ID`. No secret is in the unit.
- **CLI.** `agy-qualification watch` gains `--install-units` and `--check`, mutually
  exclusive. `cli.py` dispatches those two to `agy_watch_units.main(args)` before the existing
  `agy_qualification.cli_main`; every other `watch` invocation is unchanged.
- **`--install-units`.** Copies both unit files from `<--repo>/docs/ops/agy-upstream-watch/`
  to `~/.config/systemd/user/` (0644), then `systemctl --user daemon-reload` and
  `systemctl --user enable --now agy-upstream-watch.timer`. It is idempotent. With
  `--dry-run` it prints the actions and changes nothing. It never creates a key, a login or
  a credential.
- **`--check`.** Prints one JSON line `{"agy_watch_check": <state>, "last_tick": <status or
  null>}` and exits 0 only for `installed`. States, first match wins:
  1. `absent` — either unit file is not installed;
  2. `failed: <status>` — the last tick's `exit` is non-zero;
  3. `stale` — an installed unit differs from the checkout's, the timer is not enabled, or
     there is no valid last-tick status newer than three hours (a missing or malformed
     status file is `stale`, never `installed`);
  4. `installed`.

## 4. Intake, promotion and the catalog gate (SL-3, SL-6)

### 4.1 Two mechanisms, and what each is for

| Mechanism | Runs on | Purpose |
|---|---|---|
| Intake and promotion workflow (§4.3) | `main`, on an authenticated intake issue | Turns a signed record into a catalog pull request without a human |
| **Catalog provenance check** (§4.4), required | every pull request to `main` | A pull request that changes the catalog lands only upstream's bytes, whoever wrote it, unless it also changes the check itself (§4.4, residual risk) |

`EC-ROLLJOB-4`'s "a PR touching any other path or the policy fails and never auto-merges" is
met by the first: the workflow writes exactly two paths, so the automated path can never
carry a policy change. Such a change is an ordinary pull request merged by a repository
writer. The catalog check passes at once on a pull request that does not touch the catalog,
so it never blocks one.

### 4.2 Verifier modes (`scripts/verify_qualified_agy_image.py`; SL-3)

The verifier gains two modes, for five in all.

**`--intake <issue-number> --out <dir>`** runs from `main` at the workflow's own commit, with
a read-only token, and is the only step that parses a submission. It reads the issue once
through the API and works from that copy.

1. `authentic_author` against the attested INTAKE identity (§4.5). Otherwise class `ignored`.
2. `parse_intake(body)`.
3. `candidate_member(record)`, and the record's `qci` equals this checkout's `seat_qci()`.
4. `verified_signers(record, <this checkout's signer list>)` is not empty.
5. Provenance from `UPSTREAM_REPO` only: the release is fetched by tag and must be stable;
   its asset digest and URL must equal the record's; the archive is downloaded and
   `verify_archive` re-derives the member digest. The submission supplies a version and
   digests to compare, never a location. `published_at` comes from the API.
6. `build_catalog(base, record, published_at, now)` and `catalog_change(base, built).auto`.
7. The built tree passes `contract()`.

Output: the new catalog file, the record file and `decision.json` (`class`, `issue`,
`record_sha256`, `version`, `base_sha`, `catalog_sha256`, `run_id`, `reasons`). Classes:
`ignored` (check 1), `refused` (checks 2 to 5), `manual` (6 failed: genuine and signed but
not a new newest member; no pull request, a writer takes it into an ordinary one), `auto`.

**`--catalog-pr --base <sha> --head <sha> --pr <number>`** is §4.4's required check.

### 4.3 Workflow `.github/workflows/agy-catalog-intake.yml` and `ci/agy_catalog_promote.py` (SL-6)

- **Triggers.** `issues: [opened]`; `workflow_dispatch` with an issue number; `schedule`
  every 30 minutes for reconcile. Every job starts with
  `if: github.ref == 'refs/heads/main'`, because a dispatch can name another ref. The
  environment's branch rule (§4.5) is the boundary for the key; this `if` is the boundary
  for everything else.
- **No issue text in a shell.** Issue fields and the dispatch input reach steps only as
  environment variables or files. The dispatch input must match `^[0-9]{1,9}$`.
- **Third-party actions** are pinned by full commit SHA. Privileged jobs run on hosted
  runners, restore no cache and download no artifact except this run's own.
- **Job `authenticate`** (`contents: read`, `issues: read`; no concurrency group). For an
  issue event or a dispatch alike, it reads the issue through the API and applies
  `authentic_author`. Its output is the only thing that lets any later job run. A look-alike
  issue from anyone else ends here: no comment, no label, no further job.
- **Run name.** The workflow sets `run-name: agy-intake-<issue number>` from the validated
  number, so the run history can be counted per issue.
- **Jobs `intake` → `promote` → `report`** run only for an authenticated issue.
- **Locking is per job, not per workflow.** Only `promote` and `reconcile` carry
  `concurrency: agy-catalog-promotion` with `cancel-in-progress: false`. `authenticate`,
  `intake` and `report` carry none, so an unauthenticated event can never hold or displace
  the lock, and no lock is expected to span jobs. GitHub keeps one pending job per group; a
  `promote` displaced while pending is cancelled, and reconcile picks its issue up again.
  Two `intake` jobs may build on the same tip; `promote`'s current-base check under the lock
  is what serializes writes.
  - `intake` (`contents: read`, `issues: read`, no secret): §4.2 `--intake`; uploads its
    output as this run's artifact.
  - `promote` (environment `agy-promotion`; workflow token `contents: read`), class `auto`
    only. `ci/agy_catalog_promote.py promote`:
    1. requires the decision's `run_id` to be this run and `base_sha` to be `github.sha`;
       recomputes both files' digests; re-parses and re-runs `catalog_change(...).auto`;
    2. **current base:** requires the tip of `main` to equal `github.sha`. If `main` has
       moved, it writes nothing and exits `stale_base`; reconcile rebuilds from the new tip;
    3. mints the PROMOTION token, limited to this repository, `contents: write` and
       `pull-requests: write`;
    4. creates `agy-catalog/<version>-<run_id>-<attempt>` at `base_sha` with one commit whose
       message carries two trailer lines, `Agy-Intake-Issue: <number>` and
       `Agy-Record-Sha256: <digest>`. That commit is the link from pull request to issue: it
       is fixed with the head OID and cannot be edited like a label, a title or a body. Then
       reads it back and derives changed paths and file modes from its tree against the
       base tree. Anything but the catalog (modified) and one record (added), both regular
       files, stops with no pull request;
    5. opens the pull request, labelled `agy-catalog-auto`, naming the issue by its qualified
       number;
    6. arms the merge only if §4.5's gate passes; then enables auto-merge (squash) with the
       expected head OID set to the created commit. A rejection of that guard stops.
  - `report` (`issues: write` on the workflow token, no secret, `if: always()` **and**
    authenticated): comments class and reasons; closes `refused`; closes `manual` after
    labelling it for a writer to pick up. Labels and comments are bookkeeping. Nothing reads them
    as authority.
- **Job `reconcile`** (schedule only; environment `agy-promotion`; the same job-level lock;
  workflow token `contents: read`, `issues: write`, `actions: write`).
  `ci/agy_catalog_promote.py reconcile` derives state from facts it can verify, never from
  labels, and handles the oldest item that needs work, one per run. It parses no submission
  itself: where a record must be verified again, it starts a `workflow_dispatch` run of this
  workflow for that issue number, which goes through `authenticate`, `intake` and `promote`
  like any other. The cases are evaluated **in this order**, and the first that applies is
  the only one acted on:
  - an authenticated open intake issue whose version is now a member → close it, done;
  - an open pull request authored by the PROMOTION App on `agy-catalog/<version>-…` whose
    base is not the tip of `main`, or which has no armed auto-merge while the switch is on →
    **supersede**: close it with the reason recorded, delete its branch, and dispatch a
    rebuild from current `main`. It never uses "update branch";
  - an issue whose promotion has been superseded `MAX_PROMOTION_ATTEMPTS` times → comment
    `stalled`, close it. Nothing is in flight for that version after this;
  - an authenticated open intake issue with no open promotion pull request. **The stall
    threshold is evaluated first, and a dispatch happens only if it is verified not to be
    reached:**
    1. read the run history (below). If it is unavailable or incomplete → dispatch nothing,
       report `history_unavailable` in the job summary and exit non-zero. An unreadable
       history is never a verified count and never resets one;
    2. if a matching run is queued or in progress → do nothing this time;
    3. if the six latest completed matching runs all ended without a pull request → comment
       `stalled`, close the issue, and **do not dispatch**;
    4. otherwise (the event run never ran, was cancelled while pending, or failed fewer than
       six times in a row) → dispatch a run for it.

  **Reading the run history.** Reconcile uses its workflow token (`actions: write`, which
  includes read) to list this workflow's runs on `main`, newest first. It pages **back to the
  issue's creation time**: it stops only at the first run created before the issue, or at
  the end of the history. It does not stop early when it has six completed matches, because
  an older matching run may still be queued or in progress. From what it read it takes:
  - every run whose run name is exactly `agy-intake-<issue number>` and that is not older
    than the issue;
  - among those, any that is queued or in progress, however old (step 2 above);
  - among those, the `MAX_PREPR_FAILURES` latest that are `completed` (step 3 above).

  A run "ended without a pull request" when no pull request passing `authentic_author` for
  the PROMOTION identity exists, open or closed, on a branch
  `agy-catalog/<version>-<that run's id>-…`; the run's conclusion is recorded with it but a
  `success` with no such pull request still counts. The read is **verified** only if every
  page returned successfully and paging reached the issue-age boundary or the end of the
  history. Fewer than six completed matching runs with the history read to that boundary is
  a verified count below the threshold. An API error, a truncated page, or a listing that
  ends at the API's result limit before the boundary is `history_unavailable`.

  **Where those facts come from.** A pull request belongs to an issue when it passes
  `authentic_author` for the PROMOTION identity and its head commit carries that issue's
  trailer. Superseded attempts are the closed, unmerged pull requests that satisfy the same
  test. Failures before a pull request exists are counted from this workflow's own run
  history as described above. None of these can be
  changed with an issues-only credential, and none is a label.
- **Two racing promotions**, for versions A < B built on the same tip. Strict checks mean
  whichever merges second is no longer up to date and cannot merge (§4.5).
  - *A merges first.* B is still the newest non-member: reconcile supersedes B's pull request
    and rebuilds it from the new tip.
  - *B merges first.* A is now older than a member: reconcile closes A's pull request with
    the reason recorded and does not rebuild it; A's issue ends as `manual`.

### 4.4 Catalog provenance check, and the files it trusts (SL-3)

**The required check, `agy catalog provenance`** (`.github/workflows/agy-catalog-provenance.yml`).

- Trigger: `pull_request` to `main`, with no path filter, because a required check must
  report on every pull request.
- It checks out the pull request's **base** commit and runs that commit's verifier with
  `--catalog-pr`. It fetches the head's objects and reads files with `git show`; it never
  checks out, installs or runs head code. The workflow token is `contents: read`.
- The mode imports only `agy_catalog_policy` besides the standard library (a test asserts
  the import closure).
- **Logic.**
  1. Changed paths, with both sides of renames and file modes, come from the two trees. If
     neither the catalog nor any `RECORD_PATH` file changed: pass, "catalog untouched".
  2. Parse the base and head catalogs with `parse_catalog`. A head catalog that does not
     parse fails.
  3. **Provenance, for every member added or changed in the head**, whoever wrote the pull
     request: fetched by tag from `UPSTREAM_REPO`, stable, asset digest and URL equal the
     member's and its record's, archive downloaded, member digest re-derived, `published_at`
     equal to upstream's. Any mismatch fails. Success passes the check.
- That is the whole condition. A change that only removes members or flips `pinned` adds and
  changes no member's bytes, so it passes. No signature and no review is asked for here.
- **Where the job signature still matters.** Only automatic promotion requires it: `--intake`
  refuses a record without a valid job signature (§4.2 check 4), and only `--intake`'s `auto`
  class is ever armed for auto-merge. A writer's hand-made catalog change needs upstream
  bytes and a writer's merge, nothing more.

**The files this mechanism trusts.** With one exception, stated below the list, they are read
from the trusted base at run time:

```
.github/workflows/agy-catalog-intake.yml
.github/workflows/agy-catalog-provenance.yml
.github/workflows/qualified-agy-image.yml
ci/agy_catalog_promote.py
ci/agy-lag-issue.sh
config/agy-rollout-attestation.json
plans/evidence/agy-allowed-signers
phase-loop-runtime/scripts/verify_qualified_agy_image.py
phase-loop-runtime/src/phase_loop_runtime/agy_catalog_policy.py
```

- **The exception.** GitHub takes a `pull_request` workflow's YAML from the pull request's
  test merge commit, not from the base. So `agy-catalog-provenance.yml` itself is whatever
  the pull request makes it. The verifier it runs is the base's, because the workflow checks
  the base out; that holds only while the workflow file is unchanged. The intake workflow
  and the nightly workflow run from `main`.
- They change through ordinary pull requests by repository writers under the existing `main`
  ruleset. No review requirement is added, `.github/CODEOWNERS` is not edited, and its
  catch-all line stays advisory (owner decision, 2026-11-20).
- The automated path never changes them: it writes only the catalog and one record.
- **Residual risk, stated plainly.** A rogue or compromised writer can change any of these
  files, as with any code in the repository, and could then land a catalog change the
  mechanism would otherwise refuse. The required check runs from a workflow file that the
  pull request itself can edit (the exception above), and a writer can merge, or enable
  GitHub's own auto-merge on, any pull request that meets `main`'s ruleset. "Never
  auto-merges" in this design limits this automation only. It does not defend against a
  writer.
- **What it does defend against.** A compromised qualification host or job identity holds the INTAKE
  App key and the job signing key. Neither can write code or a pull request, and both the
  intake workflow and the required check re-derive every member from the fixed upstream. So
  it cannot promote bytes that are not upstream's, a `pinned` flag or a policy change.

### 4.5 The attestation file and the merge gate (SL-3, SL-6)

Tokens in this design cannot read a ruleset's bypass list, and the promoter is never given
ruleset access. So what cannot be read is **attested** in a file on `main`, and
what can be read is read live, failing closed.

**`config/agy-rollout-attestation.json`** (`agy_rollout_attestation.v1`, closed schema):

```json
{"schema": "agy_rollout_attestation.v1", "status": "unattested|attested",
 "intake_app":    {"app_id": 0, "bot_user_id": 0},
 "promotion_app": {"app_id": 0, "bot_user_id": 0},
 "main_ruleset": {"id": 0, "target": "refs/heads/main", "enforcement": "active",
                  "bypass_actors": [], "strict_required_status_checks": true,
                  "required_checks": [""]},
 "catalog_ruleset": {"id": 0, "target": "refs/heads/agy-catalog/**", "enforcement": "active",
                     "rules": ["creation", "update", "deletion"],
                     "bypass_actors": [{"actor_type": "Integration", "actor_id": 0,
                                        "bypass_mode": "always"}]},
 "promotion_environment": {"name": "agy-promotion", "branches": ["main"],
                           "required_reviewers": 0, "admin_bypass": false},
 "attested_by": "", "attested_at": ""}
```

- It ships as `"status": "unattested"` with zeros. An ordinary pull request fills it after
  setup (§7), from the owner's reading of the settings pages; it is trusted as any file on
  `main` is. It is read from the trusted checkout only.
- Identities live here, not in repository variables, which are not owner-only.
- **The gate, all of which must hold before auto-merge is armed:**
  1. the file is `attested`; `main_ruleset.bypass_actors` is present and empty;
     `catalog_ruleset.bypass_actors` is exactly the one PROMOTION App entry;
  2. the environment variable `AGY_CATALOG_AUTOMERGE` of `agy-promotion` is exactly `true`;
  3. **live, for `main`:** the branch-rules read, paged to the end, shows `pull_request` and
     `required_status_checks` rules whose ruleset id equals the attested one, with strict
     status checks and every attested required check, `agy catalog provenance` and
     `agy catalog contract` among them;
  4. **live, for the created branch:** `creation`, `update` and `deletion` rules are present
     from the attested catalog ruleset id.

  A missing field, an unexpected ruleset id, a short read or an API error leaves auto-merge
  off. Nothing is inferred from an omitted field.
- **What holds the verified head until merge.** Only the PROMOTION App can move a branch
  under `agy-catalog/**`. Strict required checks mean a pull request whose base is not the
  tip of `main` cannot merge, so a policy or catalog change that lands after verification
  makes the pending pull request unmergeable; reconcile then supersedes it and rebuilds under
  the new policy. The required provenance check runs on every such rebuild.

### 4.6 `plans/evidence/agy-allowed-signers`

Created with a comment header and **no key**. Until the job's public key is enrolled by an
ordinary pull request (§7), every submission is `refused` for lack of a verified signer.
Format per line: `agy-watch namespaces="agy-qualification" <key type> <key>`. No owner key is
ever listed (EC-ROLLJOB-4′).

## 5. Nightly: lag rule, issue and headroom (SL-3)

### 5.1 `--upstream-only`

Adds `--report <path>`; the JSON result gains `lag` and `headroom`, and the same object is
written to the report.

- **Mode.** The lag rule is **report-only until ACTIVATE**. The raw lag status is always
  computed, printed and written to the report. It changes the exit status only when the
  environment variable `AGY_LAG_ENFORCE` is exactly `true`, which the workflow sets from the
  variable of that name in the Actions environment `agy-activation`. That environment is
  limited to `main`, holds no secret, and is the only one the nightly `upstream` job names, so
  the job that reads the switch never sits beside the PROMOTION key. A repository variable
  is not used: it is not owner-only. Unset, or any other value, is report-only: a `fail`
  status prints `::warning::` and the step's exit is unaffected by lag. The report records
  the mode as `"enforced": true|false`. Headroom and the existing member checks fail
  independently of this switch.
- **Lag (AGYROLL §6.3).** `L` is PROVFWD's `newest_stable`. Statuses:
  - `ok` — `L` is a member;
  - `warn_inside_bound` — not a member, published less than `LAG_BOUND_S` ago;
  - `warn_pr_open` — not a member, older than the bound, and promotion for `L` is in
    flight. That means exactly: an open pull request on `agy-catalog/<L>-…` that passes
    `authentic_author` for the attested PROMOTION identity and was created less than
    `IN_FLIGHT_MAX_S` ago. An intake issue never counts, verified or not, and neither does an
    older or superseded pull request, so a stranded submission cannot hold the status at
    warn. With an unattested file nothing counts as in flight; the warning names the
    awaited check or merge, and says so when the pull request itself is older than the bound;
  - `fail` — not a member, older than the bound, and neither exists; exit 1 when enforced.

  The open-pull-request listing is paged to its end. A listing that cannot be read or proven
  complete counts as "neither exists".
- **Headroom (EC-ROLLJOB-8).** For `L`, member or not: the archive is downloaded once under
  the existing bound and its digest checked against the API's; `headroom` is computed for the
  archive size against `MAX_ARCHIVE_BYTES` and for the `antigravity` member's size against
  `MAX_MEMBER_BYTES`. `warn` prints `::warning::`; `fail` exits 1. When `L` is the newest
  shipped member the same download serves the existing archive check.

### 5.2 `ci/agy-lag-issue.sh` and the `upstream` job

The `upstream` job gains `issues: write` and `pull-requests: read`, on that job only, and a
final step with `if: always()` that runs the script when the report exists. The script
follows `ci/main-red.sh`:

- report-only (`"enforced": false`) → change nothing, whatever the status: no issue is
  created, commented on or closed;
- enforced and lag `fail` → no open `agy-lag` issue: create one; exactly one: comment on it;
  more than one: comment on the lowest-numbered and close the rest;
- enforced and lag `ok` or either `warn_*` → close every open `agy-lag` issue with a comment;
- no report → change nothing.

Headroom never opens or closes the issue. The `--upstream-only` step stays blocking.

**The flip.** ACTIVATE sets `AGY_LAG_ENFORCE=true` in the `agy-activation` environment after
EC-ACTIVATE-2 is proven as §7 defines it. Its evidence in
`plans/evidence/agyroll-activate.json` records the variable, the id of the last report-only
nightly run and the id of the first enforced one. This switch is separate from
`AGY_CATALOG_AUTOMERGE`, which governs merging.

## 6. Tests

### 6.1 `tests/test_agy_catalog_policy.py` (new; SL-0)

Canonical bytes ignore key order and `signatures`; sign then verify with a fixture ed25519
key (skipped with a reason when `ssh-keygen` is absent; hosted CI has it); a signature over a
record whose `image_sha256`, `asset_sha256`, `qci` or `release_version` was changed does not
verify; a key outside the allowed-signers file does not verify; a group-readable key refuses.
Aging: newest three kept regardless of age; a fourth kept under 14 days and pruned at 14;
`pinned` never pruned; unparseable date kept. `catalog_change`: each of the three `auto`
conditions has a passing and a failing case. `headroom` at 79, 80, 89, 90 and 100 percent.
Tick status: mode 0600 in a 0700 directory; a symlinked or malformed file reads as `None`.
`build_catalog`: adds one non-pinned member, prunes by aging, keeps `pinned`, and refuses an
existing or older version. Intake body: render then parse round-trips; a second fenced block,
trailing text, a wrong digest, a header that disagrees and an oversize body all raise.
`parse_catalog` agrees with the runtime parser on every fixture. `candidate_member` accepts a
valid record for an existing version (eligibility is `build_catalog`'s). `load_attestation`:
the shipped file is unattested; an absent `bypass_actors`, an extra key and a mistyped id each
raise. `authentic_author`: wrong id, wrong type, missing App object and wrong App id are all
`False`.

### 6.2 `tests/test_agy_watch_units.py` (new; SL-1)

The unit files carry the frozen timer and environment lines; `--install-units` copies both,
reloads and enables through a fake runner, twice without change; `--dry-run` runs nothing;
each `--check` state and its precedence; `failed: gemini_login_expired` from a status file;
the two flags are mutually exclusive and leave plain `watch` dispatch unchanged.

### 6.3 `tests/test_agy_watch_job.py` (new) and `tests/test_agy_self_qualification.py` (SL-2)

- Work set: with three members at the tree's QCI, only the new release is fetched and run;
  with one member at another QCI, that member is requalified too.
- Retries: two transient series then a pass gives one record and three attempts; three
  transients give `series_unavailable`; a `failed` classification stops at once with
  `series_violation` and no PR.
- Signing: the pushed record verifies against a fixture signer list; no key gives
  `agy_watch_signing_unavailable` and no push.
- Login: a fresh login makes no renewal call and no admission call. A stale one calls
  `_await_gemini_login` then `_refresh_gemini_credential`, in two cases: with **the admitted
  host subject**, and with **a held image returned by HOLD** when the subject itself is not
  admitted; in both the candidate is never passed. **Admission refuses** (a `ValueError`
  with no `reason` attribute, and again one that has it): `gemini_login_expired`, exit 2,
  **no renewal call**, no listing, no fetch, no candidate work and no submission. A typed
  non-refusal failure from admission propagates and is not reported as
  `gemini_login_expired`. A login still stale after renewal exits 2 with
  `gemini_login_expired`, submits nothing, and leaves a status that `--check` reports as
  `failed: gemini_login_expired`.
- Streaming: instrumented `VerifiedImage` creation and close show at most one image open
  across a two-member tick; peak traced allocation stays under 4 MiB for a multi-megabyte
  member; a sink is discarded when the archive digest refuses.
- Submission: the tick runs no `git push` and no `gh`; the token request names only this
  repository and `issues: write`; the issue body round-trips through `parse_intake`; the key
  and token appear in no output; a missing or group-readable key gives
  `agy_intake_unavailable` before any operation runs; an API failure after qualification
  gives `agy_intake_submit_failed` and the next tick submits the kept record without
  re-qualifying; a pending submission, by local record or by an open own issue, makes the
  tick `up_to_date`; after a refusal the tick does not re-qualify for 24 h.
- RS256: a JWT signed with a fixture RSA key verifies with its public key and has the
  required claims; the token exchange over a fake transport sends that JWT and requests only
  this repository and `issues: write`; with `cryptography` unimportable the tick ends
  `agy_intake_dependency_missing` before any operation.
- Recovery: a lost POST response (the issue exists, no receipt) is adopted with no duplicate;
  an own issue open past `INTAKE_STALE_AFTER_S` gives `intake_stalled`; a historical
  push-shaped `watch_push` entry is never read as a receipt.
- Kept coverage after the push and pull-request helpers are removed: dry run, `--version`
  selection, worktree cleanup, receipt persistence. `tests/test_publishing.py` is in this
  lane's ownership in case it exercises a removed helper; if it does not, it is untouched.
- Status: every return path writes a status equal to its printed value.
- Existing watch tests stay green; `tests/test_agy_size_bounds.py`'s `keep_bytes` case moves
  to `sink`.

### 6.4 `tests/test_agy_promotion.py` (SL-3) and `tests/test_agy_catalog_promote.py` (SL-6)

**`--intake`** (fake API, fixture keys): `ignored` for a person, another App, a matching
login with a different user id, and a matching user id with no App object; `auto` for one new
newest release, and with an aged member dropped and a `pinned` one kept; `refused`, one case
each, for a malformed body, a disagreeing header, an oversize body, no signature, an
unenrolled key, a record altered after signing, a stale `qci`, a withdrawn asset digest, a
different member digest, a prerelease; `manual` for an existing version and an older one, each
reached without `build_catalog` being asked to validate; `published_at` and the upstream
repository come from trusted values even when the submission carries others.

**`--catalog-pr`** (local git repository, fake API): a pull request that does not touch the
catalog passes without any network read; a writer's pull request adding a member with
non-upstream bytes fails; one adding a genuine member with no signature passes; a `pinned`
flip and a removal pass; a changed member whose new digest is not upstream's fails; a renamed
catalog and a catalog turned into a symlink fail; no review is read; the mode's import closure
is the standard library plus `agy_catalog_policy`.

**Promote and reconcile** (`ci/agy_catalog_promote.py`, fake `gh`, local git repository):
- a decision from another run or base is rejected; a file whose digest differs is rejected;
- `main` moved since the run's commit → `stale_base`, nothing written;
- the created commit changes exactly two regular files; a third path, a mode change or a
  symlink stops before the pull request;
- the gate: an unattested file, an absent or non-empty `main` bypass list, a second catalog
  bypass actor, the switch unset, a rules read cut short, a rule from an unexpected ruleset
  id, non-strict checks, or a missing required check each leave auto-merge off with the pull
  request open and the job green; all satisfied → auto-merge requested with the created
  commit as expected head OID;
- **two racing promotions, both orderings:** versions A < B built on one tip. A merges first
  → B's pull request is superseded and rebuilt from the new tip. B merges first → A's is
  closed with a recorded reason and not rebuilt;
- **link and bounds:** a pull request is matched to its issue by the head commit's trailer
  even when its labels, title and body are altered; a look-alike pull request by another
  author with the same trailer is ignored;
- **the six-run stop:** with six latest completed runs named for the issue and none having
  produced a pull request, reconcile closes the issue with `stalled` and the fake dispatch
  endpoint receives **zero** calls, in that run and in the next; five such runs → exactly one
  dispatch; six where one produced a pull request that was later superseded → not this case;
  a run named for another issue, a run older than the issue and a run still in progress are
  not counted, and an in-progress matching run means no dispatch; **an older queued match
  beyond the six completed ones** (seven matching runs, the oldest still queued, the six
  newer all completed without a pull request) means no dispatch and no `stalled` close, and
  the fake API shows the listing was paged past the sixth completed match to the issue-age
  boundary; a listing that cannot reach that boundary gives `history_unavailable`; a history read that
  errors, returns a truncated page or stops at the result limit gives `history_unavailable`,
  zero dispatches, a non-zero exit and an issue left open; labels and comments change none
  of these outcomes;
- **locking:** only `promote` and `reconcile` name the concurrency group;
- **a policy change between verification and merge:** the signer list changes on `main`
  while a promotion is pending; reconcile supersedes it, and the rebuild is verified against
  the new signer list;
- reconcile also: promotes an authenticated issue whose event run never happened; retries a
  failed promotion; supersedes a pull request with no armed auto-merge once the switch is on;
  closes an issue whose version became a member; stops after `MAX_PROMOTION_ATTEMPTS` with
  `stalled`; never acts on a label alone; never calls "update branch".

**Workflow shape** (YAML, both workflows): every job in the intake workflow is gated on
`refs/heads/main`; the dispatch input is pattern-checked and reaches no `run:` by
interpolation; `authenticate` precedes everything and has no concurrency group; `report` is
conditional on authentication; only `promote` and `reconcile` name `agy-promotion`; `intake`
has no secret and no write permission; the provenance workflow checks out the base commit
only, has no write permission and triggers on `pull_request` only;
neither uses `pull_request_target`; third-party actions are pinned by commit SHA.

### 6.5 `tests/test_agy_upstream_advisory.py`, `tests/test_ci_agy_lag_issue.py`, `tests/test_verify_qualified_agy_route_core.py` (SL-3)

Each lag status in **both modes**: report-only never changes the exit status and the script
mutates nothing, enforced fails on `fail`; an unreadable listing gives `fail`; the report
records the mode; an `AGY_LAG_ENFORCE` value other than `true` is report-only; headroom at the
four thresholds for archive and member; the report file equals the printed result; the
`upstream` job has `issues: write` and no other job does; the script creates, comments,
deduplicates and closes through a fake `gh`, and does nothing without a report; an intake
issue, an old pull request and a pull request by another author never count as in flight;
the `upstream` job names only the `agy-activation` environment; the verifier has exactly five
modes.

## 7. Owner actions (O3 and ACTIVATE), not lane work

No lane performs any of these. They need organization or repository administration, or access
to the qualification host. No new GitHub user account is created. Items marked *confirm* rest on GitHub
behaviour read from documentation, not observed on this repository.

**Confirmation**

1. The owner confirms R9′ as written in ROLLJOB-amendment, including its statement of the
   residual risk for writers (§4.4). SL-5 records the confirmation and does not start
   without it.

**Two organization-owned GitHub Apps**

2. **INTAKE App.** Repository permissions: Issues read and write; Metadata read; nothing
   else (Contents read only if the repository is private). No organization permissions, no
   webhook, no user authorization. Install it on `agent-harness` only.
3. **PROMOTION App.** Repository permissions: Contents read and write; Pull requests read
   and write; Metadata read; nothing else, in particular not Workflows, Administration,
   Actions, Secrets, Variables or Environments. Install it on `agent-harness` only.
4. Record each App's id, each App's bot **user id** (the immutable number, not the login),
   and the INTAKE installation id.

**Environments and keys**

5. Environment `agy-promotion`: Selected branches and tags, one branch rule exactly `main`,
   no tag rule, no required reviewer, administrator bypass off. Secret
   `AGY_PROMOTION_APP_PRIVATE_KEY`, stored nowhere else; delete the downloaded file.
   Variables `AGY_PROMOTION_APP_ID` and, at ACTIVATE only, `AGY_CATALOG_AUTOMERGE`.
6. Environment `agy-activation`: same branch rule, no secret. Variable `AGY_LAG_ENFORCE`, at
   ACTIVATE only.
7. INTAKE private key: delivered to the job account on the qualification host through the secret-handling
   path, never through chat, a ticket or a repository. Mode 0600 at
   `~/.config/phase-loop/agy-watch/intake_app_key.pem`.

**Repository**

8. Labels: `agy-intake`, `agy-catalog-auto`, `agy-lag`.
9. Settings: allow auto-merge; allow squash merging.
10. **`main` ruleset, first form.** No bypass actors, administrators included. Require a pull
    request, with no review requirement added. Require status checks, **strict** (branch up
    to date): the existing required checks plus `agy catalog contract`. Block force pushes
    and deletions. **Do not require `agy catalog provenance` yet:** until this phase has
    merged, the base has no `--catalog-pr` verifier, so requiring the check would block the
    very pull request that installs it (steps 16 to 19).
11. **Catalog ruleset.** Target `refs/heads/agy-catalog/**`. Restrict creations, updates and
    deletions. The PROMOTION App is the only bypass actor, mode Always.
12. CODEOWNERS is not changed.
13. Close agent-harness#1138 with that setup.

**On the qualification host**

14. **Prepare the job account** (can be done now): a read-only clone at
    `~/code/agent-harness`; a Gemini login; `intake.env` holding the INTAKE App id and
    installation id. No `gh` login and no push credential. The runtime itself is installed
    later, at step 21, because it must be a release that contains this phase.
15. The job's signing key: `ssh-keygen -t ed25519 -N '' -f ~/.config/phase-loop/agy-watch/signing_key`,
    mode 0600.

**After this phase merges, in this order, with auto-merge off throughout**

16. This phase's pull request merges. It may merge under the **existing** branch protection;
    step 10's ruleset is not a prerequisite for it, and neither is any other step from 2 to
    15. Its own `agy catalog provenance` run is not required and may fail, since its base
    has no verifier. What merges is inert.
17. Confirm a successful `agy catalog provenance` run on a later pull request whose base
    contains the verifier. GitHub also needs a recent successful run before a check can be
    selected as required.
18. **`main` ruleset, final form.** Add `agy catalog provenance` to the required checks.
19. By an ordinary pull request, fill `config/agy-rollout-attestation.json` from the settings
    pages as they now stand: both App ids and bot user ids, each ruleset's id, target,
    enforcement and exact bypass list, the strict-checks flag, the final required checks,
    and the environment's settings. Set `status` to `attested`. Refresh it whenever one of
    those settings changes; it records them as last observed.
20. By an ordinary pull request, add the job's public key line to
    `plans/evidence/agy-allowed-signers`. The owner creates and enrols no key of their own.

Steps 16 to 20 are complete before ACTIVATE begins. Until step 19, the gate of §4.5 cannot
pass, so nothing can be armed early.

**ACTIVATE only (needs EXECADMIT and ROLLJOB complete)**

21. On the qualification host, install the released `phase-loop-runtime[agy-watch]` that
    contains this phase (the extra is required). Then
    `phase-loop agy-qualification watch --install-units --repo ~/code/agent-harness`, and
    `watch --check` reports `installed`. The first ticks are live qualification runs.
22. **With the switch off, confirm** on the first submission: the intake workflow ran for the
    App-created issue, and the issue's payload and API reading both carry the bot user id
    and the App id; the pull request the PROMOTION App opened ran every required check,
    `agy catalog provenance` included, on the commit GitHub evaluates for it; a push to its branch by a write
    member is rejected. This pull request is not merged as evidence of anything.
23. **Flip and supersede.** Set `AGY_CATALOG_AUTOMERGE=true`. Reconcile then closes the pull
    request of step 22 with the recorded reason "created while auto-merge was off", deletes
    its branch, and opens a fresh verified proposal from current `main` with auto-merge armed
    while its checks are still pending. No direct merge is used: the contract authorizes
    none.
24. **EC-ACTIVATE-2 is proven only by** that fresh pull request merging with: the PROMOTION
    App as the merging identity, no review of any kind, and no human merge or "update
    branch" action in its timeline. A pull request merged by a person, or merged while the
    switch was off, never counts, however correct its contents.
25. Only then set `AGY_LAG_ENFORCE=true`.
26. Evidence in `plans/evidence/agyroll-activate.json`: the attestation file's commit; step
    22's observations; the superseded and the merged pull requests with the merged one's
    timeline facts; the ids of the last report-only and first enforced nightly runs.

**Order.** Step 1 gates only the amendment lane, SL-5. Steps 2 to 15 are live setup: they
may start once step 1 is done (D7), and they may also finish **after** this phase has
merged, because the merged phase is inert. Each must be complete before the post-merge step
that verifies or attests it: steps 10 and 11 before steps 17 to 19, and every step from 2 to
15 before ACTIVATE.

**If the switch stays off.** A writer merges verified pull requests by hand. That is a
supported fallback and it is not completion of ACTIVATE.

**The pattern generalizes.** One INTAKE-style App per class of untrusted host, holding only
the permission to submit data, and one PROMOTION-style App per class of trusted workflow,
whose key never leaves Actions. Future automation needs no new user account, and
the existing automation account's duties can move to such Apps later. That migration is out of scope here.

## 8. GitHub behaviours relied on and not yet verified

Each is from documentation or memory, not from this repository's observed behaviour. Each has
a stop rule. Auto-merge and lag enforcement stay off until ACTIVATE has confirmed the ones
that matter to them (§7).

| Behaviour relied on | If it does not hold |
|---|---|
| The issue's event payload and API reading both carry the bot user id and the attached App id | `authentic_author` fails closed, so no intake is accepted; the lane reports, and relying on the user id alone needs an amendment |
| The branch-rules read returns the ruleset id and the strict-checks flag for each rule | The gate cannot match the attestation, so auto-merge stays off; SL-6 reports |
| A PROMOTION-App pull request runs all required checks, `agy catalog provenance` included, and the App can enable and complete squash auto-merge here | Auto-merge stays off; proven at ACTIVATE steps 22 to 24 before anything depends on it |
| Auto-merge enabled by the App merges as the App, so the timeline shows it as merger | EC-ACTIVATE-2's evidence needs another field; ACTIVATE reports |
| A scheduled job can start a `workflow_dispatch` run of the same workflow with the workflow token and `actions: write` | Reconcile cannot rebuild; SL-6 stops and reports |
| `actions/create-github-app-token`, at its pinned commit, limits the token to one repository and named permissions | SL-6 stops and reports |
| An environment variable is readable by a scheduled job on `main` that names the environment, with no reviewer prompt | Lag enforcement cannot be switched; SL-3 reports |
| **Live history access.** Reconcile's workflow token (`actions: write`) can list this workflow's runs on `main` at run time, paged back to an issue's creation time, with each run's status, conclusion, creation time and id | Fail closed: reconcile reports `history_unavailable`, dispatches nothing, closes nothing and exits non-zero. SL-6 stops and reports if documentation contradicts it; ACTIVATE confirms it on the first reconcile run |
| **Exact run-name matching.** Each listed run carries the `run-name` the workflow set (`agy-intake-<issue>`), unchanged, so runs can be matched to one issue exactly | Fail closed: with no usable run name the history is `history_unavailable`, with the same outcome. A run name is never matched by prefix or pattern. SL-6 stops and reports; ACTIVATE confirms it |
