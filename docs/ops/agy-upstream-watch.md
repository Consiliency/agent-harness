# agy upstream watch: the rolling catalog job (agent-harness#1076, AGYROLL ROLLJOB)

The watch keeps the shipped agy catalog current. Each hour, a user timer on the
**qualification host** runs `phase-loop agy-qualification watch`. A tick qualifies the newest
stable upstream release and submits a signed qualification record **as data**: one issue,
created through an organization-owned GitHub App that can write issues and nothing else. A
workflow on `main` verifies the record, authors the catalog pull request with a second App,
and arms its merge only behind a gate. The nightly check reports how far the catalog lags
upstream.

Qualification needs a real Gemini subscription, so the job runs on a host, never on a hosted
runner. Hosts still self-qualify a genuine release on first use; the job is how a release
becomes a shipped member.

**Status.** This phase ships the code inert. No signing key is enrolled, the attestation
file is unattested, and auto-merge and lag enforcement are both off. The owner setup at the
end of this page is a prerequisite **of live operation, not of this phase's merge**, and this
phase performs none of it.

## The two Apps, and what each key can do

| App | Permissions | Where its key is | What a stolen key can do |
|---|---|---|---|
| **INTAKE** | Issues read and write; Metadata read | the job account on the qualification host, `~/.config/phase-loop/agy-watch/intake_app_key.pem`, 0600 | create, edit, label and close issues and comments here, and submit a signed record. Nothing else: no code, ref, pull request, workflow, variable or setting |
| **PROMOTION** | Contents and Pull requests read and write; Metadata read | a secret of the Actions environment `agy-promotion`, limited to `main` | write branches and pull requests, from a workflow running `main`'s own code only |

The job's only GitHub credential is the INTAKE App's. It makes **no git write**: the checkout
on the qualification host is fetched, never pushed, and there is no branch, commit or pull
request from the job. There is no fork and no `pull_request_target`.

## One tick

1. **Platform.** Only the release route, Linux x64 glibc, is proposed; any other platform
   prints `platform_not_proposed`.
2. **Local preflight, before any live operation.** The INTAKE key must be a regular file
   owned by the job account and readable by it alone, `intake.env` must supply the App id
   and installation id, and the `agy-watch` extra (`cryptography`) must be installed.
   Otherwise the tick ends with `agy_intake_unavailable` or `agy_intake_dependency_missing`.
   The signing key must be a private regular file, or the tick ends with
   `agy_watch_signing_unavailable`. No inference is spent on a record that cannot be
   submitted.
3. **Login.** A fresh Gemini login costs one file read. A login that is not fresh is renewed
   with the image that seat admission admits on this host: the host's own agy, or a held
   image when the hold applies. The unqualified candidate is never used. If admission
   admits no image, or the login is still not fresh after renewal, the tick ends with
   `gemini_login_expired` before any listing or download. Renew the login on the host.
4. **Newest release.** The first stable entry of the release listing, one request.
   `already_pinned` when it is already a member on `origin/main`. `up_to_date` when a
   submission for it, at the prepared tree's QCI, is pending (see Submission). A signed
   record kept from a failed submission is submitted again without re-qualifying.
5. **Work set.** The newest non-member release, plus every member whose catalog `qci` is
   not the prepared tree's seat QCI. Members whose `qci` matches are not fetched or run.
6. **One member at a time.** The archive member streams into a sealed image (no member is
   held in memory, and only one image is open at a time). Help is measured with the
   prepared tree's profile, and the series runs: the three operations, then `--validate`.
   - A failed operation is classified by the prepared tree's own classifier. `failed` is a
     violation and ends the tick with `series_violation`. `transient` retries the whole
     series in a fresh directory, three attempts in all, then ends it with
     `series_unavailable`. A validator refusal is a violation.
   - The record is signed with the job key (`ssh-keygen -Y sign`, namespace
     `agy-qualification`, principal `agy-watch`) over its canonical bytes.
7. `--contract` runs on the prepared tree. Its local catalog edit lets the worker gate pass
   and is never pushed. Aging is not done here: the workflow on `main` builds the catalog.
8. **Submission.** Each signed record becomes one issue.

Every return path prints `{"agy_watch": <status>, ...}` and writes the same status and exit
code to `~/.local/state/phase-loop/agy-watch/last-tick.json` (or under `$XDG_STATE_HOME`), a
0600 file in a 0700 directory. `--dry-run` qualifies and verifies, writes an unsigned record
into its prepared tree, keeps that tree, submits nothing and writes no status.
`--version <tag>` re-runs any listed stable release and ignores the wait after a refusal.

Budget about a minute of real inference per member qualified.

## Submission through the INTAKE App

The job mints a short-lived installation token (an RS256 App JWT signed with
`cryptography`) and asks only for this repository and `issues: write`. A wider grant is
refused. The token and the key never reach a log, an argv or a status line. The transport is
`api.github.com` only, with no proxy and no redirect.

The issue is titled `agy intake: <version>`, labelled `agy-intake`. Its body is one header
line, `agy-intake.v1 <version> <qci> <sha256 of the record text>`, a blank line, and one
fenced `json` block holding the signed record. A receipt is written to the qualification
store (`watch_push` entry, context `intake_receipt.v1`). A historical push receipt can never
read as one.

| State of the submission | Tick |
|---|---|
| issue open and younger than 6 h | `up_to_date` |
| issue open and older than 6 h | `intake_stalled`, exit 2; the hosted reconcile owns the retry |
| issue closed, version not a member (refused or exhausted) | waits 24 h from the receipt, then qualifies and submits again |
| no receipt and no open issue from this App | qualifies |
| an API failure after qualification | `agy_intake_submit_failed`, exit 2; the signed record is kept and the next tick submits it |

A lost POST response is recovered without a duplicate: before creating an issue the job
lists the open issues this App created and adopts one with the same header line.

## Installing and checking the timer

`phase-loop agy-qualification watch --install-units --repo ~/code/agent-harness` copies
`docs/ops/agy-upstream-watch/agy-upstream-watch.{service,timer}` to `~/.config/systemd/user/`
(0644), reloads the user manager and enables the timer. It is idempotent. With `--dry-run` it
prints its actions and changes nothing. It never creates a key, a login or a credential.

The timer fires hourly (`OnCalendar=hourly`, `RandomizedDelaySec=10m`, `Persistent=true`).
The service names the signing key and the INTAKE key by path and reads
`~/.config/phase-loop/agy-watch/intake.env` (`AGY_INTAKE_APP_ID`,
`AGY_INTAKE_INSTALLATION_ID`). No secret is in a unit file.

`phase-loop agy-qualification watch --check --repo ~/code/agent-harness` prints
`{"agy_watch_check": <state>, "last_tick": <status or null>}` and exits 0 only for
`installed`. The first state that applies wins:

1. `absent`: a unit file is not installed;
2. `failed: <status>`: the last tick exited non-zero (for example
   `failed: gemini_login_expired`);
3. `stale`: an installed unit differs from the checkout's, the timer is not enabled, or no
   valid last-tick status is newer than three hours;
4. `installed`.

To roll back: `systemctl --user disable --now agy-upstream-watch.timer`. No store migration
is needed.

## The workflow on `main`: intake, promotion and reconcile

`.github/workflows/agy-catalog-intake.yml` runs on an opened issue, on a dispatch naming an
issue number, and every 30 minutes for reconcile. Every job runs only on `refs/heads/main`.
Issue fields and the dispatch input reach steps only as environment variables.

- **`authenticate`** reads the issue and accepts it only when its author's numeric id is the
  attested INTAKE bot user, its type is `Bot`, and GitHub's attached App object carries the
  attested App id. A look-alike issue ends here, with no comment, no label and no further job.
- **`intake`** (no secret, no write permission) runs
  `verify_qualified_agy_image.py --intake`, the only step that parses a submission. It
  decides one class:

  | Class | When | What follows |
  |---|---|---|
  | `ignored` | not created by the INTAKE App | nothing |
  | `refused` | malformed body, a header that disagrees, an invalid record, a stale QCI, no job signature from `main`'s signer list, or an upstream mismatch (the release by tag, stable, its asset digest and URL, and the re-derived member digest) | `report` comments the reason and closes the issue |
  | `manual` | genuine and signed, but not one new newest member (an existing or older version, or a change aging does not allow) | `report` labels it `agy-intake-manual` and closes it; a writer takes it into an ordinary pull request |
  | `auto` | one new non-pinned member newer than every member, plus removals aging allows | `promote` |

  The upstream is fixed (`google-antigravity/antigravity-cli`), and `published_at` comes
  from its API; neither is ever taken from a submission. Aging keeps a member that is
  pinned, among the newest three, or published less than 14 days ago.
- **`promote`** (environment `agy-promotion`, the job lock) re-checks the decision against
  this run and its commit. If `main` has moved it writes nothing (`stale_base`), and
  reconcile rebuilds. Otherwise it mints the PROMOTION token for this repository with
  contents and pull-requests write only. It creates `agy-catalog/<version>-<run>-<attempt>`
  with one commit writing exactly the catalog and the record. The commit carries two
  trailers, `Agy-Intake-Issue` and `Agy-Record-Sha256`, which link the pull request to its
  issue and cannot be edited like a label, title or body. It reads the commit back, opens
  the pull request labelled `agy-catalog-auto`, and arms squash auto-merge, with that commit
  as the expected head, only when the gate passes.
- **`report`** comments the class and reasons. Labels and comments are bookkeeping; nothing
  reads them as authority.

**How a writer takes a `manual` record into an ordinary pull request.** Copy the record from
the issue's `json` block into `plans/evidence/agy-<version>-linux-x64-qualification.json`
(the shape the job writes: sorted keys, two-space indent), edit
`phase-loop-runtime/src/phase_loop_runtime/data/agy_catalog.json` by hand, and open a pull
request. It needs the passing `agy catalog provenance` check and a writer's merge, nothing
more; no signature is asked for.

**Reconcile** acts on the oldest item that needs work, one per run, in this order:

1. an authenticated open intake issue whose version is now a member: closed;
2. an open App-authored promotion built on a commit that is no longer the tip of `main` (its
   head commit's sole parent, which never changes; the pull request's own `base.sha` follows
   `main` and is not read), or which is unarmed while auto-merge is switched on, is
   **superseded**: closed with the reason recorded, its branch deleted, and a fresh run
   dispatched from current `main`. A promotion whose version is no longer newer than every
   member is closed and not rebuilt. Before anything is closed or dispatched, the issue's
   closed, unmerged promotions are counted from GitHub, this one included; at six it is
   closed without a rebuild. "Update branch" is never used;
3. an issue whose promotions have ended unmerged six times: commented `stalled` and closed.
   The count is read from GitHub on every run, so it holds after a run that stopped part-way;
4. an authenticated open intake issue with no open promotion. Reconcile reads this
   workflow's run history back to the issue's creation time. If the history is unavailable
   or incomplete, it reports `history_unavailable` and dispatches nothing. A matching run that
   is queued or in progress means nothing is done this time. If the six latest completed runs
   named `agy-intake-<issue>` all ended without a pull request, the issue is closed `stalled`.
   Otherwise a run is dispatched.

When two promotions race on one tip, strict up-to-date checks let only one merge. If the
older one merges first, the newer one is superseded and rebuilt. If the newer one merges
first, the older one is closed and its issue ends as `manual`. On a busy `main`, promotions go
stale and are rebuilt; past six attempts they stall, and the lag rule reports it.

## The required check: `agy catalog provenance`

`.github/workflows/agy-catalog-provenance.yml` runs on every pull request to `main`, with no
path filter, whoever wrote it. It fetches the pull request's **base** commit and runs that
commit's verifier with `--catalog-pr`. The head's objects are fetched as data; no head code
is checked out, installed or run. Nothing is installed: the mode imports only the standard
library and `agy_catalog_policy`.

- Neither the catalog nor a record changed: it passes at once, with no network read.
- Otherwise, every member added or changed is re-derived from the fixed upstream: the
  release by tag and stable, the asset digest and URL equal to the member's and its record's,
  the archive downloaded and the member digest re-derived, and `published_at` equal to
  upstream's. A renamed or removed catalog, or a catalog or record that is not a regular file,
  fails.
- Removing members or flipping `pinned` changes no member's bytes and passes. No signature
  and no review is asked for. The job signature matters only for automatic promotion.

The check is not required when this phase merges, because its own run has no verifier in its
base. The owner makes it required after a passing run on a later pull request.

## The files this trusts, and the residual risk for writers

The workflows (`agy-catalog-intake.yml`, `agy-catalog-provenance.yml`,
`qualified-agy-image.yml`), `ci/agy_catalog_promote.py`, `ci/agy-lag-issue.sh`,
`config/agy-rollout-attestation.json`, `plans/evidence/agy-allowed-signers`,
`phase-loop-runtime/scripts/verify_qualified_agy_image.py` and
`phase-loop-runtime/src/phase_loop_runtime/agy_catalog_policy.py` are read from `main` at run
time. One exception: GitHub takes a `pull_request` workflow's YAML from the pull request's
test merge commit, so the provenance workflow file is whatever the pull request makes it.

They change through ordinary pull requests by repository writers under the `main` ruleset;
no review rule is added and `.github/CODEOWNERS` is not edited. The automated path never
changes them: it writes only the catalog and one record. **A rogue or compromised writer can
change any of these files, as with any code**, and keeps GitHub's ordinary merge and
auto-merge authority. "Never auto-merges" limits this automation only. What it defends
against is a compromised qualification host or job identity: it holds only the INTAKE key and
the job signing key, and both the workflow and the required check re-derive every member from
the fixed upstream. It cannot promote bytes that are not upstream's, a `pinned` flag, or a
policy change.

**The signer list.** `plans/evidence/agy-allowed-signers` ships with no key; until the job's
public key is enrolled by an ordinary pull request, every submission is refused. Each line is
`agy-watch namespaces="agy-qualification" <key type> <key>`. Only the job's key is ever
listed.

## The attestation file and the merge gate

Tokens cannot read a ruleset's bypass list, and the promoter has no ruleset access. So
`config/agy-rollout-attestation.json` (`agy_rollout_attestation.v1`, closed schema) records
what cannot be read: both Apps' ids and bot user ids, each ruleset's id, target, enforcement
and exact bypass list, the strict-checks flag, the required checks and the `agy-promotion`
environment's settings. It ships `unattested` with zeros. An ordinary pull request fills it
after setup, from the settings pages, and refreshes it whenever one of those settings changes.
A missing, extra or mistyped field is an error; an absent bypass list is never read as empty.

Auto-merge is armed only when all four hold:

1. the file is `attested`, `main`'s bypass list is empty, and the catalog ruleset's is exactly
   the PROMOTION App;
2. `AGY_CATALOG_AUTOMERGE` in `agy-promotion` is exactly `true`;
3. live, `main`'s branch rules, paged to the end, show the pull-request and strict
   required-checks rules from the attested ruleset, with every attested check,
   `agy catalog provenance` and `agy catalog contract` among them;
4. live, the created branch has the creation, update and deletion rules of the attested
   catalog ruleset.

Anything else leaves the pull request open, unarmed, with the job green.

## Nightly: the lag rule, the `agy-lag` issue and headroom

`qualified-agy-image.yml`'s `upstream` job runs `--upstream-only --report`, on `main` only,
whatever ref a dispatch names. It names only the `agy-activation` environment, which is
limited to `main` and holds no secret, so the job that reads the switch never sits beside the
PROMOTION key.

- **Lag** for the newest stable release `L`: `ok` (a member); `warn_inside_bound` (not a
  member, published less than 48 h ago); `warn_pr_open` (older, and an App-authored promotion
  for `L` younger than 24 h is open; an intake issue never counts, nor does an older or
  superseded pull request, and with an unattested file nothing counts); `fail` (older, and
  nothing in flight). An unreadable pull-request listing counts as nothing in flight.
- **Report-only until ACTIVATE.** The status is always computed, printed and written to the
  report with `"enforced"`. It changes the exit, and the issue, only when `AGY_LAG_ENFORCE`
  in `agy-activation` is exactly `true`. Otherwise `fail` prints a `::warning::`.
- **The issue** (`ci/agy-lag-issue.sh`, the job's last step, which always runs). Report-only
  or no report: nothing is created, commented on or closed. Enforced `fail`: one open
  `agy-lag` issue is created, or commented on, and duplicates are closed. Enforced `ok` or
  `warn_*`: every open `agy-lag` issue is closed.
- **Headroom** for `L`'s archive against the 256,000,000-byte bound and its `antigravity`
  member against the 512,000,000-byte bound: a warning at 80 percent, a failure at 90, whatever
  the switch says. Headroom never opens or closes the issue.

## Owner setup: prerequisites of live operation, not performed by this phase

These are owner actions (ROLLJOB-detail §7 has the full text). They need organization or
repository administration, or access to the qualification host. None is a prerequisite of
this phase's merge, which happens under the existing branch protection and is inert.

1. Confirm R9′. The owner confirmed it on 2026-11-20; the contract amendment records it.
2. Create the **INTAKE App** (Issues read and write, Metadata read; Contents read only if the
   repository is private) and the **PROMOTION App** (Contents and Pull requests read and
   write, Metadata read; nothing else). Install each on this repository only. Record both App
   ids, both bot user ids and the INTAKE installation id.
3. Environment `agy-promotion`: one branch rule, exactly `main`; no reviewer; administrator
   bypass off; secret `AGY_PROMOTION_APP_PRIVATE_KEY`, stored nowhere else; variable
   `AGY_PROMOTION_APP_ID`. Environment `agy-activation`: the same branch rule, no secret.
4. Deliver the INTAKE key to the job account through the secret-handling path, 0600.
5. Labels `agy-intake`, `agy-catalog-auto`, `agy-lag` and `agy-intake-manual` (the last is
   bookkeeping for a writer; `report` creates it on first use if it is missing); allow
   auto-merge and squash merging.
6. The `main` ruleset, first form: no bypass actors, a pull request required with no review
   requirement, strict required checks (the existing ones plus `agy catalog contract`),
   force pushes and deletions blocked. Do not require `agy catalog provenance` yet. The
   catalog ruleset on `refs/heads/agy-catalog/**`: creations, updates and deletions
   restricted, the PROMOTION App the only bypass actor. CODEOWNERS is not changed.
7. On the qualification host, prepare the job account: a read-only clone at
   `~/code/agent-harness`, a Gemini login, `intake.env`, no `gh` login and no push
   credential; then the signing key,
   `ssh-keygen -t ed25519 -N '' -f ~/.config/phase-loop/agy-watch/signing_key` (0600).
8. After this phase merges, in order, with auto-merge off: confirm a passing
   `agy catalog provenance` run on a later pull request; add it to `main`'s required checks;
   fill and attest `config/agy-rollout-attestation.json` by an ordinary pull request; enrol
   the job's public key in `plans/evidence/agy-allowed-signers` by an ordinary pull request.
9. At ACTIVATE: install the released `phase-loop-runtime[agy-watch]` on the qualification
   host, `watch --install-units`, and `watch --check` reports `installed`. Confirm the first
   submission end to end with the switch off. Then set `AGY_CATALOG_AUTOMERGE=true` and let
   reconcile supersede that pull request. Set `AGY_LAG_ENFORCE=true` only after a fresh
   promotion has merged with the PROMOTION App as the merging identity.

If auto-merge stays off, a writer merges verified pull requests by hand. That is a supported
fallback; it does not complete ACTIVATE.

**GitHub behaviours not yet observed here** (each fails closed; ROLLJOB-detail §8 lists them
with their stop rules): the App object on an App-created issue and pull request, the
branch-rules read's ruleset ids and strict flag, the App's own checks and squash auto-merge on
its pull request, auto-merge merging as the App, a scheduled job dispatching this workflow
with the workflow token, an environment variable read by a scheduled job, the run history's
paging and exact run names (`display_title`), and the pinned action commits in the intake
workflow. Auto-merge and lag enforcement stay off until ACTIVATE confirms them.

## Related commands

- `phase-loop agy-qualification status` prints this host's store state, its entry types,
  whether self-qualification is enabled, and the runtime identity.
- `phase-loop agy-qualification run` pre-qualifies the `agy` on `PATH` (first use).
- `phase-loop agy-qualification clear [--all]` removes failed entries, or every entry;
  `--all` also removes intake receipts.
