# Grok jailed measurement procedure

The owner-gated procedure for the jailed Grok tool-surface measurement: the jailed `staged`
form measured inside the real Grok jail, in the context `grok_jail_context.v1`. It is the
TS contract §5.10 script with `--planned pilot,planted,confirm` and `--route staged` per
launch, as `plans/artifacts/grok-jail-tool-surface-contract-v1.md` §7.1 requires (GROK
SL-4, IF-0-GROK-4; Consiliency/agent-harness#1820).

It is run only under the owner's grant in jail contract §7, on the designated seat host, on
one installed release that carries TS contract erratum 8's lanes and GROK SL-0 to SL-4. The
confirmation and hosted boundary check are prerequisites for that grant.

## What the grant allows

- One binding **rehearsal** of `pilot` under a budget-0 proxy. Every request is refused and
  observed, nothing is forwarded, no model call is made, and nothing is charged.
- **3 planned launches**, by label: `pilot` on the `clean` tree, then `planted` (the `clean`
  tree with a marker at every discovery-inventory path) and `confirm` (`clean`) once the
  pilot is `measured`. Each `--route staged` stage takes the first label, in order, whose
  latest result is not `measured`.
- **At most 2 retries**, transport failures only, each manual and agreed with the
  coordinator; never for a credential or egress failure.
- **At most 5 counted requests**, budget 1 per launch, hard cap 5 for this grant.

A grant is jailed exactly when its `--planned` list is `pilot,planted,confirm`; `grant.json`
then records `"context": "grok_jail_context.v1"`. `--new-grant` and `--rehearse` refuse
(`jail_ineligible`) unless eligibility conditions 1 to 4 of jail contract §2.4 hold for the
image on the installed release.

## Stops that are not failures of the script

- **`unspawned`.** A launch refused before its spawn hook ran (the qualification check, the
  identity probe, the capped preflight, the sink probe or an earlier step) leaves no
  admission file. The reservation is settled `unspawned` and nothing is charged.
  Under r8-3 of the [jail contract revision r8](../../plans/artifacts/grok-jail-tool-surface-contract-v1-erratum-r8.md),
  a first `grok_sink_probe_timeout` on that label permits a later attended invocation
  of `--route staged` without spending a retry. The current invocation exits and leaves
  any following routes unattempted. A second `unspawned` on that label or any refusal
  outside the allowlist stops the grant with `grant_stopped_unspawned`.
- **Unresolved.** A reservation whose admission was consumed and that has no settlement (a
  crash, a kill, a spawn that failed after its hook, or a launch whose admission file the
  leg could not confirm after it ran) is charged in full, is never settled or resumed,
  and blocks every further reservation of the grant (`reservation_unresolved`).
- **Runtime drift.** A different install between the rehearsal and `--aggregate` makes
  `--aggregate` refuse `context_mismatch`. A refusal withdraws the current host-local record
  only when this grant owns the latest attempt. A new reservation of any grant still
  withdraws the image's jailed publication before it exists (BA-2).

## Record the projection confirmation and hosted boundary

The owner runs or attends the separately approved offline confirmation (§2.4) using the
installed Grok image, the exact §2.3 projection and a local inference fixture. Use a
credential-free fixture with egress disabled. Capture the launch digest from the composed
jail with `grok_jail_surface.launch_digest(jail, command)` and verify that the fixture saw
the inference request, saw no settings or models requests, and that the staged files and
masks are unchanged. A failed observation stops the procedure.

The owner prepares a metadata-only JSON observation in an operator-owned 0700 directory
with file mode 0600. Use the actual values for the image, architecture, digests and approval
of that offline launch.

```json
{
  "schema": "grok_jail_confirmation.v1",
  "image_sha256": "<observed image sha256>",
  "launch_digest": {"x86_64": "<observed launch digest on this architecture>"},
  "jail_context_digest": "<observed jail context digest>",
  "outcome": {
    "inference_request_reached": true,
    "settings_requested": false,
    "models_requested": false,
    "staged_unchanged": true
  },
  "approval_id": "<owner's offline approval id>",
  "approved_on": "<YYYY-MM-DD>",
  "credential_free": true,
  "no_egress": true,
  "masks_unchanged": true
}
```

Run the attended import with `GROK_CONFIRMATION` set to that file and `GROK_BIN` and
`GROK_SHA` set to the installed executable and approved sha256.

```sh
timeout 600 phase-loop seat-window measure-tools --vendor grok --binary "$GROK_BIN" \
  --expect-binary-sha256 "$GROK_SHA" --attended --reviewed --record "$GROK_CONFIRMATION"
```

For condition 4, the GitHub-hosted `test.yml` job on the merged head needs the real
jail prerequisites and both provider-free tests below. Run from the runtime project
directory and upload the XML as the sole member of an Actions artifact named
`grok-jail-boundary`. Use the same architecture and system mount layout as the target seat.
Both cases must pass, with zero skips. The tests record the runtime and run-attempt bindings
and BA-J5 records the actual launcher binding. The existing BA-3 workflow step needs a
separate CI change to publish this receipt.

```sh
PHASE_LOOP_REQUIRE_GROK_JAIL_NS=1 PHASE_LOOP_REQUIRE_LIVE_JAIL=1 PYTHONPATH=src:tests \
  timeout 600 python -m pytest -p no:xdist -p no:cacheprovider -o junit_family=xunit1 \
  --junitxml=grok-jail-boundary.xml tests/test_grok_seat_jail.py \
  -k 'jail_ns_ba_j1 or live_jail_b_ba_j4_ba_j5'
```

SL-4 runs the standalone boundary stage using the GitHub CLI and the full installed
release commit from the release manifest, exported as `GROK_INSTALLED_HEAD`. Set
`GROK_HOSTED_CHECK_RUN` to the upstream workflow run ID or URL. This step checks
GitHub Actions and writes the boundary record before the grant can open.

```sh
timeout 600 phase-loop seat-window measure-tools --vendor grok --binary "$GROK_BIN" \
  --expect-binary-sha256 "$GROK_SHA" --hosted-check "$GROK_HOSTED_CHECK_RUN"
```

## Before the slot (no request is spent; stop if any item fails)

Jail contract §7 lists these preconditions. Each is confirmed before the grant is opened, and
the script below stops before any reservation unless the credential check passes.
Items r8-4 and r8-5 of the [jail contract revision r8](../../plans/artifacts/grok-jail-tool-surface-contract-v1-erratum-r8.md)
both block the §7 grant run until `GROK-R8-FOLLOWUP` delivers them.

1. The owner signs in afresh through the attended managed Grok sign-in on the seat host
   immediately before the slot.
2. `VL` and `VL2` have passed on the seat host. The owner confirmation and the hosted
   boundary for `GROK_HOSTED_CHECK_RUN` have been recorded on the installed release.
3. Where a Gemini window refresh is required, it is separately authorised and completed
   first, on the same installed release.
4. The TS contract erratum 8 item 4 staging check passes: `--verify-probe initial` (step 1 below) checks
   the managed policy read-only, before anything is projected.
5. Shared compute: a quiet slot, both shared-compute locks held, the memory-PSI gate, and
   `MemorySwapMax=0` scopes, as for D4.
6. The credential-store writer publishes the credential metadata after successful attended
   managed sign-in (r8-5). It writes `credential-metadata.json` into the
   operator's `.grok` store, mode 0600, with exactly three keys: `subscription` (`true`),
   `expires_at` (integer Unix seconds) and `auth_state` (the signed-in `auth.json`'s
   `device`, `inode`, `size`, `mtime_ns` and `ctime_ns`). It holds no token material. The
   measurement reads only this record and stats `auth.json` without opening it; it never
   opens `auth.json` or `agent_id`. **If the record cannot be published, stop: no grant is
   opened.** A missing, malformed or stale record (the store changed after it was written)
   refuses `credential_metadata_unavailable`.
7. The slot's hard end is known and exported as `GROK_SLOT_END_EPOCH` (integer UTC epoch
   seconds). `--new-grant` refuses `grok_seat_token_expired`, writing no grant, unless the
   record's expiry exceeds both the slot end plus five minutes and the launch margin.
   `--rehearse` and every `--route staged` stage refuse the same way before reserving when
   the lifetime would not outlast the launch.
8. Suspend Dotfiles auto-sync and release promotion for the full slot. Use the Python
   interpreter from the same installed runtime that provides `phase-loop`. Before opening
   the grant, resolve the subject in the measurement environment and match its exact
   canonical path and SHA-256 to the grant inputs. Record the selector target, the release
   device and inode, and the exact entry in the host's Grok pin. Recheck that snapshot before
   rehearsal and aggregation. Stop on any drift. Keep the freeze in place through the final
   probe. The executable is bound read-only by path after verification, so the procedure
   relies on trusted root keeping the selected release immutable through the bind.

## The script

The script is safe to paste into `bash` as a whole. It stops at the first unexpected result.
Every input is exported by the operator from the owner's grant before pasting; the script
stops if one is unset.

```bash
set -euo pipefail

# The approved image and its grant (jail contract §7), exported before pasting.
: "${GROK_BIN:?export GROK_BIN=<the installed grok executable the jailed subject resolves>}"
: "${GROK_SHA:?export GROK_SHA=<the image sha256 the grant names>}"
: "${GRANT:?export GRANT=<the grant id>}"
: "${GROK_SLOT_END_EPOCH:?export GROK_SLOT_END_EPOCH=<the slot hard end, UTC epoch seconds>}"
# The verified hosted CI run of BA-J1 and BA-J5 on the installed head (condition 4).
: "${GROK_HOSTED_CHECK_RUN:?export GROK_HOSTED_CHECK_RUN=<hosted run id or URL>}"
: "${PHASE_LOOP_PYTHON:?export PHASE_LOOP_PYTHON=<Python from the installed phase-loop runtime>}"
OUT="$HOME/.local/state/phase-loop/grok-jail-surface/$GRANT"
MT=(timeout 600 phase-loop seat-window measure-tools --vendor grok --host-class team
    --grant "$GRANT"
    --binary "$GROK_BIN" --expect-binary-sha256 "$GROK_SHA" --output "$OUT")

managed_grok_identity() {
    timeout 30 "$PHASE_LOOP_PYTHON" -I - "$GROK_BIN" "$GROK_SHA" <<'PYTHON'
import json
from pathlib import Path
import sys

from phase_loop_runtime.grok_jail_surface import resolve_subject
from phase_loop_runtime.panel_invoker import _subscription_env
from phase_loop_runtime.seat_subject import GROK_SUBJECT_PIN, MANAGED_RELEASES_ROOT, _read_pin

subject = resolve_subject(_subscription_env())
if (subject.path, subject.sha256) != tuple(sys.argv[1:]):
    raise SystemExit("Installed Grok subject differs from the grant inputs")
selector = MANAGED_RELEASES_ROOT.parent / "current"
release = selector.resolve(strict=True)
if release.parent != MANAGED_RELEASES_ROOT or Path(subject.path) != release / "native/grok":
    raise SystemExit("The active Dotfiles selector differs from the resolved Grok release")
entry = _read_pin(GROK_SUBJECT_PIN, "grok_subject_pin.v1").get(release.name)
if entry is None or entry["binary_sha256"] != subject.sha256:
    raise SystemExit("The active Grok pin changed during the resolver check")
info = release.stat()
print(json.dumps({
    "selector_target": str(release),
    "release_device": info.st_dev,
    "release_inode": info.st_ino,
    "pin_entry": {release.name: entry},
}, sort_keys=True))
PYTHON
}

check_grok_slot_release() {
    local observed
    observed=$(managed_grok_identity)
    if [[ "$observed" != "$grok_slot_release" ]]; then
        echo "Dotfiles release or Grok pin changed during the slot" >&2
        return 1
    fi
}

# 0. 0 calls. The installed runtime shows the Grok row jailed, and the provider-free
#    qualification is current for the production key.
timeout 300 phase-loop seat-window matrix
timeout 300 phase-loop seat-sandbox qualify --leg grok
echo "$GROK_SHA  $GROK_BIN" | sha256sum --check --strict

# 1. 0 calls. Erratum 8 item 4's staging check and the BA-3 isolation check; every route
#    still refused with basis "none".
"${MT[@]}" --verify-probe initial

# 2. Open the jailed grant: 3 labels, 2 retries, cap 5. 0 calls. It reads only the
#    credential metadata record and refuses, writing no grant, unless the expiry outlasts
#    GROK_SLOT_END_EPOCH plus 5 minutes (prerequisites 6 and 7).
export GROK_SLOT_END_EPOCH
grok_slot_release=$(managed_grok_identity)
printf '%s\n' "$grok_slot_release"
"${MT[@]}" --new-grant --planned pilot,planted,confirm --retries 2 \
  --hosted-check "$GROK_HOSTED_CHECK_RUN"

# 3. The rehearsal of the pilot under a budget-0 proxy. 0 calls.
check_grok_slot_release
"${MT[@]}" --attended --rehearse --route staged

# 4. Gate on THIS grant's rehearsal record.
"${MT[@]}" --require-rehearsed staged

# 5. The pilot. At most 1 counted request.
"${MT[@]}" --attended --route staged

# 6. Gate on the pilot: exits non-zero unless the label just launched is "measured".
"${MT[@]}" --require-measured staged

# 7. planted, then confirm. At most 1 counted request each.
"${MT[@]}" --attended --route staged --route staged
"${MT[@]}" --require-measured staged

# 8. Aggregate: the agreement rule and the publication gate, then the jailed host-local
#    record. 0 calls.
check_grok_slot_release
"${MT[@]}" --aggregate

# 9. The grant-backed check. 0 calls. Passes only if this grant owns the live jailed
#    publication, the jailed staged row is frozen_measurement, admitted and sourced from the
#    host-local jailed record, and every other form is refused. Its probe writes the host's
#    first jailed receipt.
"${MT[@]}" --verify-probe final

"${MT[@]}" --status
```

## Notes

- A `--route staged` stage exits non-zero when its label was not `measured`, when the launch
  was `unspawned`, or when nothing could be reserved; later routes on the same command line
  are not attempted. `--status` reports `charged`, `retries_used`, `unspawned`, `unresolved`
  and `stopped`.
- A retry is permitted only for a confirmed transport failure, and only with the
  coordinator's agreement (jail contract §7); never for a credential or egress failure. It is
  step 5 or step 7 run again; the label is chosen by the ledger, never by the operator. A
  retry is refused while any reservation is unresolved.
- `--aggregate` publishes `staged` only if `pilot`, `planted` and `confirm` are each
  `measured` with identical `tools` and `definitions_sha256`, and the passed rehearsal and
  every label record the same production `launch_digest`; otherwise it refuses
  `surface_unstable` and publishes nothing. A measured surface that is not admitted is
  evidence only.
- `--aggregate` is the only writer of the jailed host-local record; the jailed receipt is
  written only by the probe of step 9 (or `phase-loop seat-window probe-tools --vendor grok`
  once the record exists). Jail contract §3, "Production writers".
- The installed-catalog check (jail contract §7.1) comes after GROK SL-6 and is not part of
  this script.
