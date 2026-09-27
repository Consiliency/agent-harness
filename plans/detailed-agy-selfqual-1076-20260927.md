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
Spec: the maintainer's proposal in agent-harness#1076 as refined by the maintainer
decisions D1–D4 below (2026-09-27). Where the issue and D1–D4 differ, D1–D4 govern;
any other disagreement between this plan and the issue is resolved by amending the
plan.

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
  separate checksum file or signature. Assets are per platform
  (`agy_cli_<os>_<arch>[_musl].<ext>`); release 1.2.12 added `*_musl` Linux assets.

## Invariants (each has a falsifier in "Tests")

- **I1 Only verified bytes execute.** A non-release image executes (help
  measurement, preflight, leg) only after provenance: archive SHA-256 equals the
  release asset's published digest, and the archive member equals the image. What
  executes is always a sealed memfd filled from the **same single read** whose
  digest was checked. `PATH` is never re-resolved after verification.
- **I2 The behavioural preflight is the existing three live operations**
  (completion, cancel after observed progress, owner loss) under the unchanged
  isolation contract and the same `validate_records` checks. Any failure refuses.
- **I3 Once per key per user per host, under a lock.** Key = image digest, help
  digest, isolation profile id, platform, and runtime identity (D2).
- **I4 The local record is integrity-checked.** A tampered, foreign (other host
  **or** other user), mis-keyed or loosely-permissioned record or store is absent.
- **I5 Every Gemini heartbeat leg carries exactly one admission class:**
  `release_qualified`, `locally_qualified`, or `qualification_candidate`.
- **I6 The release pin is not weakened.** A release-digest match is decided before
  any config, store or network access and is the same check as at `input_base_commit`.

Threat model: I4 defends against corruption, cross-host and cross-user copies,
loose or foreign storage, symlinks, and one key admitting another. A process
already running as the operator's uid can rewrite the runtime itself and is out
of scope, with one exception closed by construction: the qualification worker
entry (below) cannot be used to admit unverified bytes.

## Design

### One verified image object

A new `VerifiedImage` is produced by exactly one routine: open the source once
(`O_NOFOLLOW`, regular file), read it into memory, hash that buffer, fill a sealed
memfd from the **same buffer**, re-hash the memfd. The routine's input is either the
`PATH`-resolved agy (resolved once) or, for the watch, the archive member stream.
Everything downstream (help measurement, the three operations, board legs, the
president) takes the `VerifiedImage`'s memfd and never opens a path again.
`owned_profile` accepts a `VerifiedImage` instead of re-reading `agy`.

### Admission (lookup vs qualify)

`admit(env)` returns an `Admission(verified_image, help_sha256, class)`:
1. Build the `VerifiedImage`. If its digest is the release constant →
   `release_qualified`. No config, store or network is read (I6).
2. Else, if the user config opts out (D3) → refuse with today's
   `gemini_heartbeat_capability_unavailable`, reading nothing else.
3. Else, a valid local record for the full key → `locally_qualified`.
4. Else → miss.

`ensure_admitted(env, cancel_event)` = `admit`, and on a miss the first-use path.
Only the whole-board preflight (`_preflight_gemini_heartbeat` and its callers)
calls it; the resulting `Admission` is carried to the board's legs. Legs and the
president never qualify. A president run with no admission on the host is refused;
`phase-loop agy-qualification run` pre-qualifies explicitly.

### First-use path (coordinator process, never the seat)

1. Take the store lock (`flock`, CLOEXEC fd); waiters stay cancellable and emit
   heartbeats; re-run `admit` after acquiring.
2. **Provenance** over the network from the coordinator: host platform detected
   from the running host (D4); stable releases only; exact platform asset; URL
   under the release-download prefix; strict `sha256:<hex>` `asset.digest` equal
   to the archive digest; the archive member is streamed and hashed, never
   extracted; it must equal the `VerifiedImage` digest. No `Authorization` header
   is sent. Any fetch failure → `gemini_heartbeat_provenance_unavailable`,
   nothing executes, nothing is written.
3. Write a **provenance entry** (authenticated like a record) for the image digest.
4. Measure help by executing the `VerifiedImage` memfd through the admitted
   filename inside the owned profile.
5. Run the three operations through the packaged driver. On success write the
   **qualified record**; on a behavioural failure write a negative record (cleared
   by `agy-qualification clear`). Cancellation, a fetch failure or a mid-run image
   change writes nothing.

The recency window is a small constant: the member digest is only knowable by
downloading each archive, so a tampered image (which matches nothing) would
otherwise download every release on every first use. Verified member digests are
cached per `asset.digest` in the store so a repeat miss does not re-download.

### Qualification worker (no bypass by construction)

The driver's worker process runs `invoke_board` on a Gemini-only board and would
otherwise deadlock on its parent's lock. It receives the `VerifiedImage` memfd
explicitly (not by environment), re-hashes it, and admits it as
`qualification_candidate` **only if the store holds a valid provenance entry for
that digest** (step 3). A caller that seals an arbitrary memfd and enters the
worker without provenance gets zero launches. Candidate legs are never counted and
never persisted as records.

### Store and record

Per user, at `$XDG_STATE_HOME/phase-loop/agy-qualification/`. The directory must be
0700 and every file 0600, owned by the euid, opened `O_NOFOLLOW`; otherwise the
whole store is treated as absent. Entries carry an HMAC-SHA256 over canonical JSON
whose authenticated context includes the full key, the euid and `/etc/machine-id`.
Without a readable machine-id, self-qualification refuses; the release path is
unaffected.

### Runtime identity (D2)

A packaged `ROUTE_CORE` tuple (in the package, not `scripts/`) lists the route
modules that exist in an installed wheel: at least `gemini_heartbeat.py`,
`agy_qualification.py`, `agy_provenance.py`. The runtime hashes those installed
files; the key is `__version__` plus those digests. `verify_qualified_agy_image.py`
imports the same tuple, so the CI `--route-core` gate and the local key cover the
same files, including the new provenance code.

### Counting (D1)

The governed-landing seat check (`governed_review.py`'s per-leg usable check, and
the president's input legs) accepts a brokered heartbeat Gemini leg only when its
class is `release_qualified` or `locally_qualified`; `qualification_candidate` or a
missing class is not a vote. Landing evidence records each leg's class and flags a
Gemini leg whose admitted digest is the one the PR under review pins. Boards run
with the installed base runtime's admission, never the reviewed tree's.

### Upstream watch (scoped to what can pass the gate)

`phase-loop agy-qualification watch` runs from a timer on a subscribed host (no
GitHub-hosted runner, no self-hosted runner registration). It only proposes the
release route (Linux x64 glibc; `qualified_provider_images.v1` has only that route);
on other platforms it reports and opens nothing. For the newest stable release not
yet pinned on `main`:
1. It is idempotent per version: an existing branch or PR for that version whose
   base route-core matches current `main` → no-op.
2. It builds a `VerifiedImage` from the provenance-checked archive member stream
   (no disk install).
3. In a fresh checkout of current `main` with the constants and catalog edited, it
   runs the manual qualification (the shim) **from that tree**. The record
   therefore matches that tree, which is what `--route-core` requires.
4. It opens a draft PR and never merges.

The hosted nightly provenance check is unchanged.

## Changes

| File | Action |
|---|---|
| `phase_loop_runtime/gemini_heartbeat.py` | `VerifiedImage`, `admit`/`ensure_admitted`, `owned_profile` takes a `VerifiedImage`, class in evidence; release constants unchanged. |
| `phase_loop_runtime/agy_provenance.py` (new) | Platform detection, stable-release selection, asset, digest and member checks; no execution. |
| `phase_loop_runtime/agy_qualification.py` (new) | Packaged driver and worker, store, lock, entries, `ROUTE_CORE`, watch. |
| `scripts/qualify_gemini_heartbeat.py` | Shim over the packaged driver. |
| `phase_loop_runtime/panel_invoker.py`, `president_adapter.py`, `cli.py`, `train_runner.py` | Preflight carries the `Admission`; legs and president are lookup-only; CLI `agy-qualification {status,run,clear,watch}`. |
| `phase_loop_runtime/governed_review.py` | D1 counting rule. |
| `phase_loop_runtime/advisor_board/config.py`, `schema.py`, example fixture | D3: user-file-only `[agy] self_qualification = false` (the repo file keeps rejecting unknown tables). |
| `scripts/verify_qualified_agy_image.py`, `.github/workflows/qualified-agy-image.yml` | Import the packaged `ROUTE_CORE`; `paths:` cover the new modules. |
| `advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, watch-timer operator doc | Contract and docs. |
| `tests/test_agy_self_qualification.py` (new) + moved-path updates in the existing agy tests | Tests. |

## Lanes and landing

L0–L5 are commits in **one** implementation PR, because any change to route-core
needs one live record for the final tree:
- L0 tests first (skip-guarded)
- L1 driver move and `ROUTE_CORE`
- L2 provenance ‖ L3 store/lock/worker (both after L1)
- L4 admission and counting (after L2 and L3)
- L5 CLI, watch and docs

The PR lands after the in-flight manual 1.2.12 qualification, with a live record
produced on a subscribed host from its final tree. L6's live check needs an
in-window stable build that is not the pinned one.

## Tests and falsifiers

Each falsifier names the mutation that must turn it red:
- **I1 before provenance.** Byte-flipped image, digest mismatch, wrong/other-platform
  asset, prerelease/draft, bad URL, malformed `digest`, bad member: refuse, zero executions.
- **I1 after verification (TOCTOU).** The fake filesystem replaces the `PATH` image
  (or re-points `PATH`) after each of: provenance, help measurement, qualification,
  and a cached `locally_qualified` admission before a leg launches. The executed
  bytes are always the original sealed memfd, and the path is opened exactly once
  per admission. Mutations: a second open of the path, or taking the expected
  digest from the bytes being checked, turn it red.
- **Worker bypass.** Worker started with a sealed memfd of unverified bytes and no
  provenance entry → zero launches.
- **Offline.** First use refuses; release-qualified and already-recorded images are
  admitted with zero network calls.
- **Record/store (I4).** Flipped byte; foreign owner; 0644 file; 0755 store dir;
  symlink; unknown schema; store copied from another host; the whole store (key
  included) copied to another user on the same host with valid ownership and
  modes: each → absent.
- **D2 key.** A valid-HMAC record differing only in `__version__`, in one
  `ROUTE_CORE` digest, in profile id, in platform, or in help digest → absent. A
  test asserts that the verifier's and the runtime's `ROUTE_CORE` are the same
  object and that it includes the provenance and qualification modules.
- **I3 concurrency.** Two real processes race → one qualification, both admitted;
  killing the holder hands off; a waiter's cancel returns `review_operation_cancelled`.
- **I2.** Each operation failing → refuse and a negative record; cancel or a
  mid-run image change → no record; validation parity with the release path.
- **D3 opt-out is exactly today.** Golden parity against `input_base_commit`'s
  `require_capability`, with a valid local record **seeded**, across preflight,
  per-leg and president paths, for the release image, a non-release image and a
  missing agy. The result, diagnostic string, store reads, network calls and
  executions must all be identical to today (no store reads, no network, no
  launches for non-release images). A repo-level `[agy]` table is still rejected.
- **D4.** Host detection ignores config and environment; a record whose platform is
  not the host's is absent; an unsupported platform refuses before any network call.
- **D1.** At every tier, a `locally_qualified` Gemini leg counts; a
  `qualification_candidate` leg or one with no class does not.
- **I5/I6.** Exactly one class per leg. A release image reports `release_qualified`
  even when a record exists, and its admission reads no config, store or network.
- **Watch.** A second tick for the same version is a no-op; on a non-glibc-x64
  platform no PR is opened; `merge` is never invoked; the produced record passes
  `verify_qualified_agy_image.py --route-core` against the prepared tree.

## Maintainer decisions (recorded 2026-09-27)

- **D1** A `locally_qualified` Gemini seat counts toward governed landings at every
  tier, and the class is recorded on every leg. Enforced in "Counting (D1)".
- **D2** The runtime identity in the key is `__version__` plus the route-core
  digests. Enforced in "Runtime identity (D2)".
- **D3** On by default, with a user-config opt-out that restores exactly today's
  hard refusal. Enforced by admission step 2 and the parity test.
- **D4** The stable (not prerelease, not draft) asset for the host-detected platform
  is eligible, musl included on a musl host; platform-mismatched assets are
  refused; the checks apply per platform. The isolation contract and the three
  operations are unchanged, and a platform that cannot meet them refuses as today.
  The recency window is kept (justified above).

## Security review

Plan and implementation each need a four-vendor board and a president. The focus
areas are:
- the single-read `VerifiedImage` construction and the absence of any later path open;
- the worker's provenance-entry gate;
- archive handling (stream-hash only);
- store binding (euid, machine-id, key);
- that provenance runs only in the coordinator, with no credential.

## Acceptance

- [ ] Every falsifier above exists and is red under its named mutation. After L4,
  `test_agy_self_qualification.py` runs with **zero skips**, and the
  `automation.suite_command` passes.
- [ ] The release-qualified admission is unchanged (I6 and D3 parity green), and the
  manual qualification shim still produces a record that
  `verify_qualified_agy_image.py` accepts.
- [ ] L6 live on a subscribed host:
  - one first-use qualification of a non-pinned stable build, reused by a second
    board without inference;
  - a post-verification image swap still executes only the verified bytes;
  - one watch dry run, whose record passes `--route-core` on its prepared tree.
- [ ] `CONTRACTS.md` states the three classes, `VerifiedImage`, provenance, store,
  lock, platform selection and the D1 counting rule.
- [ ] Plan and implementation each pass a four-vendor board and a president.

Non-goals: pinning other harnesses; revoking local records when upstream withdraws
a release; adopting signed checksums.
