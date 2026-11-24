# IF-0-FIRSTSEAT-7 — Standing Gemini W1 policy

This contract applies to the standing Gemini W1 path and its versioned evidence
under the [FIRSTSEAT amendment](../amendments/seats-FIRSTSEAT-w1-standing-policy.md).
The bridge and ordinary row grants keep their existing contracts.

## Signed policy

The policy is one closed JSON object, at most 8192 bytes. Decode strict UTF-8
without a BOM. Reject duplicate keys at every level, unknown or missing keys,
non-JSON values, and trailing data other than JSON whitespace. All keys below
are required. Integer fields use JSON integer tokens and exclude booleans.

| Key | Value |
| --- | --- |
| `schema` | `seat_window_w1_policy.v1` |
| `policy_id` | 32 lowercase hexadecimal characters, fresh for each issuance |
| `signer` | SSH allowed-signers principal, 1–64 ASCII characters matching `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}` |
| `host_digest` | SHA-256 of the 32 lowercase ASCII hex characters in the local `/etc/machine-id`, after removing at most one terminal LF. Missing, malformed or unreadable identity refuses. |
| `operator_uid`, `operator_euid` | Integers in 1–4294967294. Both equal the enrolled owner UID and the corresponding process UID at admission. |
| `vendor`, `window`, `host_class` | `gemini`, `W1`, `standard`, respectively |
| `max_attempts` | Integer `1` per eligible debit tuple |
| `not_before`, `not_after` | UTC seconds, exactly `YYYY-MM-DDTHH:MM:SSZ`, valid calendar values. End equals start plus 90 × 86400 seconds. Validity is half-open. |
| `attendance` | `standing` |
| `schedule` | Array of 1–32 closed objects with exactly `weekday` (ISO integer 1–7), `start_utc` and `end_utc` (integer seconds from UTC midnight, 0–86400, start less than end). Slots are half-open, within one day, sorted by weekday and start, with no overlap. |

Use SHA-256 over the exact policy file bytes as its digest. Sign those same
bytes, including any final newline, with a passphrase-protected software Ed25519
key on the owner's own machine. Use OpenSSH SSHSIG and ASCII-armored detached
signature bytes (at most 8192 bytes), with namespace `seat-window-w1-policy`.
Use the `agy_catalog_policy.py` OpenSSH invocation pattern. Send the exact
policy bytes on stdin to `ssh-keygen -Y sign -f KEY -n seat-window-w1-policy`
and to `ssh-keygen -Y verify -f ALLOWED_SIGNERS -I PRINCIPAL -n seat-window-w1-policy -s SIGNATURE`.
Require verification success against the enrolled key and principal with the
namespace restriction. Reformatting the JSON changes both the signed bytes and
digest. The private key and SSH agent stay on the signing machine.

## Root trust and owner admission state

Use the root-owned trust directory `/etc/consiliency/agent-harness/` and these
fixed paths relative to it.

| Path | Contents |
| --- | --- |
| `w1-allowed-signers` | Enrolled Ed25519 keys restricted to the policy namespace. Use a distinct principal for each key, retain historical entries and never rebind a principal. |
| `w1-enrollment.json` | Closed `seat_window_w1_enrollment.v1` object with `schema`, `host_digest`, `operator_uid`, absolute `admission_path`, `enrolled_at`, and `genesis_sha256`. |
| `w1-policies/<policy_sha256>.json` and `w1-policies/<policy_sha256>.sig` | Immutable exact policy and detached signature bytes. |
| `w1-activation.jsonl` | Append-only history. Each closed `seat_window_w1_activation.v1` line has `schema`, `event`, `at`, `policy_sha256`, `signer`, and `revoked_after`. |

Replay activation events in file order with nondecreasing UTC timestamps.
`activate` makes the given digest the sole active policy at `at`, retiring the
previous one. `retire` ends the matching active interval. Both require a
policy digest and its signer, and `revoked_after: null`. `revoke` has a null
policy digest, names the compromised signer, and records a UTC
`revoked_after` no later than `at`. It immediately prevents new claims with
that signer and rejects historical claims at or after the boundary. Retired
policies keep their historical intervals. A claim binds the activation event
as well as the policy. Renew by signing and installing a fresh policy and
appending its activation. For compromise, revoke and enroll a replacement key
under a fresh principal before activation. Serialize trust changes and publish
policy material durably before activating it.

Use `<passwd home>/.local/state/agent-harness/w1-standing-admission/` for
admission. The literal enrolled path must equal the path derived from the
actual owner account. It is fixed across policy renewals, schedule slots,
checkouts and XDG overrides. The bridge store remains separate.

| Path relative to admission directory | Contents |
| --- | --- |
| `lock` | Stable regular lock file. Never replace it. |
| `journal.jsonl` | A pinned genesis followed by the chained debit journal. |
| `witnesses/<tuple_sha256>.json` | Exactly one exclusive witness per spent standing tuple. |
| `inputs.json` | Last verified installed tuple, disposition and any source tuple that justifies carrying the disposition forward. |

At enrollment, create these paths and pin the exact genesis-line digest,
absolute path and enrollment instant in root trust. Genesis is a closed
`seat_window_w1_genesis.v1` object with `schema`, `host_digest`,
`operator_uid` and `enrolled_at`. Write internal JSON in sorted-key, compact
UTF-8 form with one terminal LF. Hash exact line bytes including LF for
genesis, debit and activation lines. On reads enforce regular files, closed
schemas, complete lines and size bounds. Limits are 8192 bytes per JSON
object or JSONL line, 16 MiB per journal or activation history and 64 KiB
for allowed signers. Exhausted or missing state requires administrative
repair from retained evidence. Admission never initializes or resets state.

Walk components from the root directory by descriptor with no symlink
traversal, rejecting group/other write permissions. Trust paths and ancestors
are root-owned. Admission paths have root-owned system ancestors followed
by owner-owned components. The admission root and its subdirectories are
0700 and its files are 0600. Use bounded no-follow file opens and validate
the opened descriptors. Embedded digests and identifiers must match their
closed syntax before use as filenames. Reject a bad/missing anchor, partial
write, broken chain, duplicate or mismatched witness, orphan witness, or
missing expected entry. Trust the installed code, clock, owner account and
root administration. Simultaneous rollback of journal tail and witnesses is
outside this guard.

## Managed release, trigger and debit

The closed tuple has three keys, `release_identity` (K1 §8),
`qualification_key` (the K1 R8 Gemini key including architecture and excluding
`runtime_digest`), and `agy_image_sha256` (the production-admitted image bytes).
Use the closed K1 R8 key with `profile_digest`, `allowlist_digest`,
`falsifier_layout`, `projection_digest`, `variant`, `host_identity` and `arch`
from the actual Gemini launch. Use K1 types and nullability. Apply SHA-256 to the
compact, sorted-key UTF-8 tuple JSON without LF for its filename key. Verify the official
ref and release identity of the currently managed installed artifact, reject
checkout shadows and superseded candidates, and recheck that the admitted
image is the one the launcher will use. Missing tuple components refuse.
Keep `runtime_digest` as provenance. A catalog-only release can change
the admitted image without changing release identity.

`inputs.json` is a closed `seat_window_w1_inputs.v1` object with `schema`,
`installed_tuple` (nullable only before a baseline exists), `bridge_tuple`
(nullable, set once when reconciling a verified legacy debit), `disposition`
(`unseeded`, `baseline`, `pending`, `claimed` or `unchanged`) and
`source_tuple` (nullable). An unchanged disposition carries the tuple that
last established the input pair and is eligible for reuse only if that tuple
has independently valid evidence. A pending or failed change cannot be
relabelled as a previously passing change. Reconcile the disposition with
the journal on every read. Update it atomically under the stable lock with
file and directory fsync.

Seed from verified managed state and reconcile a bridge claim by its private
input proof and retained ledger. An ambiguous match refuses. A mapped bridge debit counts as spent even if
its run failed, including on later rollback to the mapped tuple. With no managed
baseline, queue the first eligible install. Queue one eligible tuple when
the Gemini key or admitted image changes. On an identity-only update, record
`window_unchanged_inputs`. Coalesce unclaimed pending work for those inputs
onto the current installed tuple. Retain the link to a spent change across
identity-only updates, including a failed attempt. Reinstall, renewal,
superseded events and rollback to a spent tuple never authorize replay.

Generate the 32-lowercase-hex context ID before claim. Hold the stable exclusive lock
while rechecking policy, slot, installed tuple and both stores. Each closed
`seat_window_w1_debit.v1` line has `schema`, `tuple`, `context_id`,
`claimed_at`, `policy_sha256`, `activation_sha256`, `attempt` (integer 1),
and `previous_sha256`. The closed `seat_window_w1_witness.v1` object has
`schema`, `tuple`, `context_id`, `claimed_at`, `policy_sha256`,
`activation_sha256`, `attempt` (integer 1), and `debit_sha256`. Append and
fsync the debit, then exclusively create and fsync the witness and fsync its
directory. Both must agree before composition, auth or model work. Refusal
after claim, abort or timeout leaves it spent. Preserve the bridge journal,
witness and both bridge pin literals for historical verification. A standing
build offers no legacy start or fallback.

## Launch, evidence and reduction

At claim require at least 10800 seconds before the earlier of slot end and
policy expiry. Use a 7200-second run budget, 120-second kill grace and 3480
seconds reserved for cleanup and collection. Start by the effective end
minus 10800 seconds. Completion must be inside the signed validity and slot,
within the K1 receipt deadline. Require the LA-1 managed install and host
readiness, four current LA-2 logins, and LA-3 satisfied by the signed schedule
and automatic cleanup under bounded supervision. Run
`seat-window qualify --window W1 --monitoring-policy bounded` with the default
model, peer overrides and launch overrides disabled.

Preserve I-15 and the containment supplier interfaces. Apply K1 §§5 and 6
to the standing run, including the contemporaneous context link, binding,
snapshot, ledger and completion receipt. The closed standing envelope
inherits all IF-0-FIRSTSEAT-2 W1 evidence fields and adds the following
versioned, required bindings. Validate the standing schema before applying
the standing verifier. Legacy evidence cannot enter this partition by label
or timestamp.

| Object | Standing wire contract |
| --- | --- |
| Private record | `schema: "seat_window_record.v2"`, existing W1 evidence, `tuple`, `run_binding_digest`, `completion_digest`. |
| Run binding | `schema: "seat_window_w1_run_binding.v1"`, K1 §6.1 fields with `grant_sha256` replaced by `policy_sha256`. The attempt object has `number: 1`, `claimed_at`, `context_id`, `debit_sha256` and `witness_sha256` in place of the grant nonce. Add `tuple`, `activation_sha256`, `context_link_sha256` and `managed_install_sha256`. The last field binds the retained private verified-install receipt, including official ref, installed artifact digest and release identity. |
| Context link | Closed `seat_window_w1_context_link.v1` with `schema`, `context_id`, `tuple`, `policy_sha256`, `activation_sha256`, `claimed_at`, `debit_sha256`, and `witness_sha256`. Write once in retained private sources as `window-W1-standing-link-<context_id>.json` after the witness and before composition. |
| Completion receipt | `schema: "seat_window_w1_completion.v1"` and K1 §6.2 fields, with the contemporaneous context link and verified-install receipt in its source digests. |
| Public export | `seat_window_export.v2`. Same closed top-level and context fields as the W1 v1 export, with only the `vendor:gemini` row using the existing row fields. Owner review of the passing record is required before export and the records PR. |

Verify the policy signature, historical activation, revocation boundary,
freshness, deadline, tuple, managed release and image proof, journal and
witness, launch key, context link, bound sources, receipt and counts. At each
credential-bearing dispatch, including queued starts, reserve and fsync first
and check actual route expiry at spawn against the bound snapshot; an expired
or missing authorized route refuses. Apply the K1 §9.2 Gemini column
(14 model-capable starts with per-item caps and all ancillary caps), four
seats and the approved ladder. Verify the current subject inputs and exception,
and each used route's exception at its launch time.

Standing verification partitions by authenticated tuple, legacy W1 separately
and ordinary rows by K1. Attribute standing record read errors to a tuple
using its digest in the private filename
`window-W1-standing-<tuple_sha256>-<context_id>.json`; never grant positive
authority from the filename. Fail closed on a duplicate or unreadable record
within its attributed partition. On unscoped `matrix --record`, reduce the
installed tuple first. Only a recorded unchanged-input skip can reuse the
latest independently valid W1 with proven matching Gemini key and image.
Legacy equivalence also needs private bridge input proof. Failed, pending
or ambiguous changes disable reuse across identity-only updates. Among
eligible W1 and row results, latest completion wins with row winning ties.
Explicit verification and export use one record and its release-bound sources.
Only `vendor:gemini` advances on successful W1 verification, to `done-local`.
After 30 days an unchanged-input W1 can lapse to `candidate` without a rerun
or blocked routing. Runtime routing independently uses each launching
host/account's fresh provider-free EC-EXECFIND-2 pass. Retain raw records,
trust history, debits, and findings privately under OD-10.

## Typed outcomes and installer handoff

The installer queues one serialized asynchronous job using the managed
entrypoint after verified install, including already-current reconciliation.
Check headroom. `ready --window W1 --vendor gemini` is read-only and checks
everything knowable before claim, including egress and login presence,
without live auth, journal or witness writes. Defer on failed readiness.
The claim rechecks readiness inputs under the lock.

| Code | Meaning |
| --- | --- |
| `window_ready` | All pre-claim-checkable conditions pass. No debit. |
| `window_unchanged_inputs` | Identity-only change recorded. Skip without a new debit. |
| `window_policy_unavailable`, `window_policy_invalid`, `window_policy_signature_invalid` | Missing trust/policy material, invalid schema or signature verification failure, respectively. |
| `window_policy_inactive`, `window_policy_revoked`, `window_policy_context_mismatch` | No applicable activation, compromised signer or wrong host/account/context. |
| `window_policy_outside_slot`, `window_deadline_exceeded` | Outside the signed validity/schedule or insufficient claim margin. An overrun after claim also fails. |
| `window_release_mismatch`, `window_key_stale` | Stale or unverified installed release, or missing/stale qualification or image binding, respectively. |
| `window_journal_unavailable`, `window_journal_corrupt`, `window_claim_busy`, `window_attempt_spent` | Missing or unsafe state, disagreement or ambiguous prior state, lock contention, or an already spent tuple. |
| `window_host_readiness_required`, `window_exception_expired`, `window_envelope_invalid`, `window_envelope_mismatch`, `window_unbudgeted_start` | Existing readiness, route and dispatch refusals apply. |
| `window_vendor_unavailable` | W1 requested for another vendor or the supplier is unavailable. |
| `window_duplicate_records`, `window_record_unavailable` | Attributed duplicate or unreadable evidence. Existing K1 binding, snapshot, source, completion and count failures also apply. |
| `window_review_required` | A retained private record is available for verification. Use the code and retained record even on exit 1. |
| `window_verified` | Automatic verification passed. Keep the result private pending export review. |

A deferral before claim spends nothing. A refusal or timeout after claim
remains spent. Standing W1 outcomes do not roll back verified installation.
