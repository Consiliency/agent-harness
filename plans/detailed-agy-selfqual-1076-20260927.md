---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 1fc5deae
related_issues: [agent-harness#1076, agent-harness#1008, agent-harness#905, agent-harness#1029, agent-harness#1075]
automation:
  suite_command: "PYTHONPATH=phase-loop-runtime/src python -m pytest -q phase-loop-runtime/tests/test_agy_self_qualification.py phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py phase-loop-runtime/tests/test_qualify_network_owner.py phase-loop-runtime/tests/test_verify_qualified_agy_route_core.py phase-loop-runtime/tests/test_agy_canary_evidence.py phase-loop-runtime/tests/test_panel_gemini_no_command_preamble.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: agy first-use self-qualification of genuine upstream releases (agent-harness#1076)

Status: draft for board + president review. Planning only; no source changed.
Spec: the maintainer's proposal in agent-harness#1076, which this plan implements
and does not restate. Where this plan and the issue disagree, the issue wins and
this plan is amended.

## Problem and inputs

Runtime admission of the brokered heartbeat-only Gemini seat is one hard digest
(`gemini_heartbeat.QUALIFIED_IMAGE_SHA256`, checked in `_read_image` and again on
the sealed memfd copy in `owned_profile`). Every upstream agy release therefore
removes the Gemini seat from every board on every host until a runtime release
ships the new digest. That happened for 1.2.11 (agent-harness#1075) and again for
1.2.12 on 2026-09-27. A separate PR is qualifying 1.2.12 by hand. This plan is the
durable fix and does not depend on that PR's content, only on its landing order
(see "Landing sequence").

Inputs observed at `input_base_commit` (inputs, not outputs):

- `gemini_heartbeat.py`: `require_capability` (capability probe + digest),
  `_read_image`, `owned_profile` (sealed memfd, `profile.evidence` hardcodes the
  constant as `provider_image_sha256`).
- `scripts/qualify_gemini_heartbeat.py`: the three live operations and
  `validate_records`/`validate_directory`. It reads the admitted image/help digest
  from `gh.QUALIFIED_*` in `run_operation`, `HelperObserver`, the `/proc/<pid>/exe`
  check and `main --validate`. **It is not shipped in the wheel** (`pyproject.toml`
  has no scripts/data-file entry for it), so an installed host such as dev0 cannot
  run it today.
- `scripts/verify_qualified_agy_image.py` + `.github/workflows/qualified-agy-image.yml`:
  route-core pins on PR/push, full pins at release (agent-harness#1029), nightly
  upstream check of `releases/latest` on a GitHub-hosted runner.
- `plans/evidence/qualified-provider-images.json` (`qualified_provider_images.v1`,
  exactly one route) and `agy-<version>-linux-x64-qualification.json` records.
- `advisor_board/CONTRACTS.md`, "Review monitoring policy v1" and "Qualified Gemini
  extension (agent-harness#905)".
- Upstream (observed with `gh api repos/google-antigravity/antigravity-cli/releases`):
  each release carries GitHub's per-asset `digest` (`sha256:<hex>`) and **no**
  separate checksum file or signature. Release 1.2.12 added `*_musl` Linux assets
  beside `agy_cli_linux_x64.tar.gz`.

## Invariants (each has a falsifier in "Tests")

- **I1 No unverified binary is executed.** An installed image whose digest is not
  release-qualified is executed (for help measurement or preflight) only after
  provenance: the archive's SHA-256 equals the release asset's published digest
  and the archive's `antigravity` member equals the installed bytes. Everything
  that executes is the sealed memfd copy of exactly those bytes.
- **I2 The behavioural preflight is the existing three live operations** —
  completion, cancel after observed progress, owner loss — under the unchanged
  isolation contract (`agy_memfd_home_deny_all_v1`, broker, egress isolation,
  heartbeat-only monitor, the same `validate_records` checks). Any failure refuses
  the seat, as today.
- **I3 Once per key per host.** The key is (image digest, help digest, isolation
  profile id, runtime identity — see D2). Qualification runs under an exclusive
  lock; concurrent first uses wait and then reuse the one result.
- **I4 The local record is operator-owned and integrity-checked.** Store 0700,
  files 0600, owned by the effective uid, no symlinks; a tampered, foreign,
  mis-keyed or wrongly-permissioned record is ignored (treated as absent), never
  trusted.
- **I5 Every Gemini leg result states its admission class**:
  `release_qualified` or `locally_qualified`.
- **I6 The release pin is not weakened.** The release-qualified digest path is
  byte-for-byte the current check; no local record can change what a
  release-qualified image needs, and no network or local state is consulted for it.

Threat model, stated plainly: I4 defends against corruption, copying a record from
another host or user, group/world-writable or foreign-owned storage, symlink
redirection, and a record for one key admitting another. It does **not** defend
against an adversary already executing as the operator's uid; that adversary can
rewrite the runtime itself, so no same-uid record scheme can stop it.

## Design

### Admission split (lookup vs qualify)

`require_capability(env)` keeps its signature and its capability probes but returns
an admission (`image path`, `image_sha256`, `help_sha256`, `class`) from a **pure
lookup**: the release constant (`release_qualified`) or a valid local record
(`locally_qualified`). It never runs provenance or inference. `_read_image` and the
memfd re-hash in `owned_profile` check against the admission's digest instead of the
constant; `profile.evidence["provider_image_sha256"]` reports the admitted digest.

A new `ensure_admitted(env, *, cancel_event)` runs lookup first and, only if lookup
misses, the first-use path below. It is called **only** from the whole-board
preflight `_preflight_gemini_heartbeat` (its callers: `invoke_board`, both `cli.py`
sites, `train_runner`, `governed_review`), which already precedes availability,
auth and dispatch. The per-leg re-check (`panel_invoker` review-monitor branch) and
`president_adapter` keep calling the pure lookup. A leg's own launch path therefore
never triggers provenance or inference.

### First-use path (coordinator process, never the seat)

1. Lookup misses → acquire the store lock (below). Re-run lookup after acquiring;
   another process may have finished.
2. **Provenance, in the coordinator process** (the host process running the board,
   which has network; the seat sandbox never does). Hash the installed image by fd.
   Enumerate releases of `google-antigravity/antigravity-cli` through the GitHub
   REST API, latest first, within a bounded recent window (D4). For each, take only
   the asset named `agy_cli_linux_x64.tar.gz` (musl and other assets are refused,
   D4), require its `browser_download_url` under
   `https://github.com/google-antigravity/antigravity-cli/releases/download/<tag>/`,
   download it to a 0700 scratch directory with a size cap, require
   `sha256(archive) == asset.digest`, then stream the `antigravity` member (regular
   file, size cap) and compare with the installed digest. The version is learned
   from the matching release; the binary is never executed to discover it. No
   match within the window → refuse `gemini_heartbeat_provenance_unmatched`.
3. **Authoritative digest source**: GitHub's `digest` field on the release asset.
   It is the only vendor-side digest upstream publishes; the trust anchor is GitHub
   (TLS + API) and the `google-antigravity` organisation's release. This is the
   same source `verify_qualified_agy_image.py` already trusts for release
   qualification, so the local path adds no weaker anchor. If upstream later
   publishes signed checksums, adopting them is a follow-up, not this plan.
4. **Offline**: any provenance fetch failure (DNS, TLS, HTTP, rate limit,
   timeout) refuses with `gemini_heartbeat_provenance_unavailable`, writes no
   record, and does not execute the image. Release-qualified images and images
   with a valid local record need no network and are unaffected.
5. **Help measurement** runs only after step 2, by executing the sealed memfd
   copy through the admitted filename (`/dev/phase-loop-agy/agy --help`) inside the
   owned profile, per the contract's "measure help through the admitted filename".
6. **Behavioural preflight**: the three operations run in sequence through the
   packaged driver (next section), each with the existing preregistration,
   observer and `validate_records`, followed by `validate_directory`. This is real
   subscription inference (roughly a minute in total, once per key per host). Any
   failure refuses the seat with the existing fixed diagnostics.
7. On success, write the local record atomically (temp file in the store, fsync,
   rename), release the lock, and admit as `locally_qualified`.

### Packaged driver and the recursion guard

Move the operation and validation logic of `scripts/qualify_gemini_heartbeat.py`
into the package (`phase_loop_runtime/agy_qualification.py`); the script becomes a
thin shim with the same CLI, so the manual release-qualification workflow is
unchanged. Parametrise it on an explicit candidate (image digest, help digest)
instead of reading `gh.QUALIFIED_*`; the release path passes the constants.

The driver's worker calls `invoke_board` with a Gemini-only board, which would hit
`ensure_admitted` and deadlock on its parent's lock. The worker is instead launched
with a **candidate admission** passed by an inherited sealed memfd (not an
environment variable), naming exactly one image/help digest. Lookup honours it
only inside a process started by the driver's `--worker` entry, it is never
persisted, and legs admitted by it carry class `qualification_candidate`, which is
neither `release_qualified` nor `locally_qualified` and is never a countable vote.

### Lock

`fcntl.flock(LOCK_EX)` on a lock file in the store. Waiters poll a non-blocking
acquire in short intervals and stay cancellable through the operation cancel event
(heartbeat-only: no wall-clock deadline on the wait). The kernel releases the lock
when the qualifier dies, and the next holder re-checks the record first.
A **behavioural** failure (an operation ran and failed validation) is persisted as
a negative record under the same key, so concurrent and later boards refuse
immediately instead of each spending inference; `phase-loop agy-qualification
clear` removes it. Infrastructure failures (provenance unavailable, credential
missing, capability missing) persist nothing.

### Local record store

`$XDG_STATE_HOME/phase-loop/agy-qualification/` (default `~/.local/state/...`),
created 0700; records and the host key 0600. Opened with `O_NOFOLLOW`; directory
and every file must be owned by the euid with no group/other bits, else ignored.
Record schema `agy_local_qualification.v1`: the key fields, release tag, asset
name, `asset.digest`, archive and member digests, the redacted three-operation
summary in the same shape as `plans/evidence/agy-*-qualification.json`, and an
HMAC-SHA256 over the canonical JSON with a per-store random key. The key file also
binds `/etc/machine-id`, so a copied store fails verification. Lookup recomputes
everything and treats any mismatch, parse error or unknown schema as absent.

### Leg result class

Add `provider_image_admission` (`release_qualified` | `locally_qualified` |
`qualification_candidate`) to `profile.evidence`, which flows into
`harden_isolation_evidence`, and to the leg's landing evidence. Existing
broker/observer envelopes and `provider_*` keys stay unchanged (the contract freezes
them); the executing lane confirms no closed key-set assertion in
`test_gemini_heartbeat_bootstrap.py` breaks and, if one exists, extends it
explicitly rather than loosening it.

### Upstream watch (scheduled, subscribed host)

A new operator command `phase-loop agy-qualification watch` runs on a subscribed
host from the host's own scheduler (a systemd user timer or cron entry documented
in `docs/`), **not** on a GitHub-hosted runner (no subscription) and **not** as a
registered self-hosted runner. When the latest upstream release's Linux x64 member
differs from the release-qualified digest, it runs provenance and the three
operations against that release's archive member (installed into a private path,
not replacing the operator's agy), and on success opens the evidence-record PR
(`agy-<version>-linux-x64-qualification.json`, catalog pointer, constants) with
`gh`. It never merges. Hosted CI keeps the provenance-only nightly
(`--upstream-only`) unchanged.

## Changes

| File | Action |
|---|---|
| `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py` | Admission split, `ensure_admitted`, class in evidence; release constants unchanged. |
| `phase-loop-runtime/src/phase_loop_runtime/agy_provenance.py` (new) | Release enumeration, digest and member verification; no execution. |
| `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py` (new) | Packaged driver, candidate admission, store, lock, record. |
| `phase-loop-runtime/scripts/qualify_gemini_heartbeat.py` | Shim over the packaged driver. |
| `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | `_preflight_gemini_heartbeat` → `ensure_admitted` with cancel event; per-leg re-check stays lookup-only; landing evidence carries the class. |
| `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py` | Lookup-only admission; class in evidence. |
| `phase-loop-runtime/src/phase_loop_runtime/cli.py` | `agy-qualification {status,clear,watch}`. |
| `phase-loop-runtime/scripts/verify_qualified_agy_image.py` | `ROUTE_CORE` and `actual_source_hashes` follow the moved driver files. |
| `.github/workflows/qualified-agy-image.yml` | `paths:` follow the moved files; upstream job unchanged. |
| `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` | Qualified Gemini extension: two admission classes, provenance, store, lock, class field. |
| `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, operator doc for the watch timer | Documentation. |
| `phase-loop-runtime/tests/test_agy_self_qualification.py` (new); moved-path updates in `test_qualify_network_owner.py`, `test_gemini_heartbeat_bootstrap.py`, `test_verify_qualified_agy_route_core.py` | Tests. |

## Lanes and order

- **L0 tests first.** Land `test_agy_self_qualification.py` with every falsifier
  below, skipping (not failing) unimplemented contracts in ordinary runs.
- **L1 driver move + parametrisation** (no behaviour change; release path passes
  the constants). Update verifier, workflow paths and moved-path tests.
- **L2 provenance module** (network code; fakes a GitHub API and archive server
  in tests).
- **L3 store, lock, record, candidate admission.**
- **L4 admission split + preflight wiring + class evidence + contract text.**
- **L5 CLI `status/clear/watch` + operator doc.**
- **L6 live verification** on a subscribed host (below).

L1 → L4 are ordered; L2 and L3 may run in parallel after L1.

### Landing sequence

Any PR touching `gemini_heartbeat.py` or the driver turns the `--route-core` check
red until it carries a fresh live qualification record for its own tree. The
implementation PR therefore lands **after** the in-flight manual 1.2.12
qualification PR and carries a new record produced on a subscribed host from its
own final tree. Tests alone cannot land it.

## Tests and falsifiers

Each is a named mutation that must turn its test red:

- **Tampered binary (I1).** Flip one byte of an image whose unmodified bytes match a
  fake release member: provenance refuses, help measurement and preflight are never
  launched (the fake launcher records zero executions), no record is written.
- **Digest mismatch (I1).** Archive bytes differ from `asset.digest`; wrong asset
  name (including `*_musl`); download URL outside the release prefix; member absent,
  non-regular or oversized: each refuses before execution.
- **Offline (I1, I6).** API unreachable: first use refuses with
  `gemini_heartbeat_provenance_unavailable`; the release-qualified image in the same
  run is still admitted with no network call made; an image with a valid local
  record is admitted with no network call made.
- **Tampered record (I4).** One flipped byte; valid HMAC but a different image
  digest; a store copied with a different machine-id; mode 0644; foreign owner;
  symlinked file or directory; unknown schema: each is ignored and first use runs
  again (never admits).
- **Concurrent first use (I3).** Two processes race `ensure_admitted` on one
  unqualified image with a fake driver: exactly one qualification runs, both are
  admitted `locally_qualified`; killing the holder mid-run releases the lock and the
  waiter qualifies; a waiter's cancel event ends its wait with
  `review_operation_cancelled`.
- **Behavioural failure (I2).** Each of the three operations failing validation
  refuses the seat and persists a negative record; a later board refuses without a
  driver launch; `clear` removes it.
- **Unchanged isolation (I2).** The driver's `validate_records` checks and argv are
  byte-identical to the release path; a mutation that drops any observer check in
  the local path turns the parity test red.
- **Recursion guard.** A candidate admission presented to an ordinary board entry
  point (not a driver worker) is ignored; a `qualification_candidate` leg is never
  counted by landing.
- **Class (I5).** Every Gemini leg result carries exactly one class; a
  release-qualified image reports `release_qualified` even when a local record for
  the same digest exists.
- **Release pin (I6).** With the store absent, unreadable or populated, admission of
  the release-qualified digest makes the same checks as `input_base_commit` and
  nothing else; a record claiming a different digest for the release key cannot
  alter it.
- **Lookup-only legs.** Per-leg and president admission never call provenance or the
  driver (spy asserts zero calls).

L6 live: on a subscribed host with an agy lacking a release record, run one board;
confirm exactly one qualification, a `locally_qualified` class on the Gemini leg, a
0600 record in a 0700 store, and reuse by a second board without inference. Then
flip a byte in a private copy of the image on `PATH` and confirm refusal with no
execution.

## Open maintainer decisions (recommendations only; not decided here)

- **D1 Do governed landings count a `locally_qualified` Gemini seat?**
  `review_policy_for_tier` requires `gemini` for PLAN and PRODUCTION_CODE.
  Recommendation: **count it for all tiers, with the class recorded in landing
  evidence.** The behavioural preflight and provenance are the same ones release
  qualification uses. The deciding fact: the evidence-record PR for a new agy
  version itself needs a board with a Gemini seat, which on an auto-updated host is
  only locally qualified. "Do not count" therefore blocks every new release's
  record PR (and every other governed landing) until a standing per-version
  exception is granted. Alternative: do not count, plus a documented per-version
  exception.
- **D2 What "runtime version" means in the key.** Recommendation: package
  `__version__` plus the route-core source digests, matching the
  agent-harness#1029 regime, so a development edit outside the route does not force
  another minute of inference. Alternative: the full source-pin set (safer, but
  requalifies on every source edit in a development tree).
- **D3 Default on or opt-in.** Recommendation: default on, with an operator opt-out
  (`agy_self_qualification: false` in the user config) that restores today's hard
  refusal. Alternative: opt-in, which keeps dev0's next auto-update outage by default.
- **D4 Release window and musl.** Recommendation: search the latest few releases
  (not all history) and admit only `agy_cli_linux_x64.tar.gz`; a musl install is
  refused until it has its own record and route. Alternative: accept musl members
  via the same provenance, which widens the admitted set.

## Security review

This touches `gemini_heartbeat.py`, the qualification driver and the route
contract, all security-sensitive. It requires a four-vendor board and a president
on this plan and again on the implementation. Reviewers should check at least:
the TOCTOU window between provenance hashing and the sealed memfd copy (the
admitted digest must be re-verified on the memfd, as today); that no code path
executes the image before provenance; archive extraction (tar member type, size,
path; stream-hash, never extract to disk); the store's permission, ownership and
symlink handling; that the candidate admission cannot be reached from an ordinary
board; and that the provenance fetch runs in the coordinator process with no
credential and never inside the seat namespace.

## Acceptance

- [ ] Every falsifier in "Tests and falsifiers" exists, fails under its named
  mutation and passes on the candidate; the `automation.suite_command` passes.
- [ ] The release-qualified admission path is unchanged in behaviour (I6 test green)
  and the manual qualification CLI still produces a record that
  `verify_qualified_agy_image.py` accepts.
- [ ] L6 live verification on a subscribed host is recorded, including the
  tampered-binary refusal.
- [ ] `CONTRACTS.md` states both admission classes, the provenance source, the
  store and the lock; the maintainer's D1 ruling is recorded in it.
- [ ] Plan and implementation each pass a four-vendor board and a president.

Non-goals: extending digest pinning to other harnesses (issue's last bullet);
revoking local records when upstream withdraws a release; signed-checksum adoption.
