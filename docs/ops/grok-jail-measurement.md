# Grok jailed measurement procedure

The owner-gated procedure for the jailed Grok tool-surface measurement: the jailed `staged`
form measured inside the real Grok jail, in the context `grok_jail_context.v1`. It is the
TS contract §5.10 script with `--planned pilot,planted,confirm` and `--route staged` per
launch, as `plans/artifacts/grok-jail-tool-surface-contract-v1.md` §7.1 requires (GROK
SL-4, IF-0-GROK-4; Consiliency/agent-harness#1820).

It is run only under the owner's grant in jail contract §7, on the designated seat host, on
one installed release that carries erratum 8's lanes and GROK SL-0 to SL-4. Nothing in it is
run by an agent or in CI.

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
  admission file. The reservation is settled `unspawned` and nothing is charged. How a label
  resumes after that is OWNER-DECISION r7-1 (jail contract §20), which is not ruled: until
  it is, an `unspawned` settlement **stops the procedure** and later stages refuse
  `grant_stopped_unspawned`.
- **Unresolved.** A reservation whose admission was consumed and that has no settlement (a
  crash, a kill, a spawn that failed after its hook) is charged in full, is never resumed,
  and blocks every further reservation of the grant (`reservation_unresolved`).
- **Runtime drift.** A different install between the rehearsal and `--aggregate` makes
  `--aggregate` refuse `context_mismatch` and remove any jailed record for the image.

## The script

The script is safe to paste into `bash` as a whole. It stops at the first unexpected result.
Every value in angle brackets is the owner's grant, not a default.

```bash
set -euo pipefail

# The approved image and its grant (jail contract §7).
GROK_BIN=<the installed grok executable the jailed subject resolves>
GROK_SHA=<the image sha256 the grant names>
GRANT=<the grant id>
OUT="$HOME/.local/state/phase-loop/grok-jail-surface/$GRANT"
MT=(timeout 600 phase-loop seat-window measure-tools --vendor grok --host-class team
    --grant "$GRANT"
    --binary "$GROK_BIN" --expect-binary-sha256 "$GROK_SHA" --output "$OUT")

# The hosted CI run of the boundary check on the installed head (BA-J1, condition 4).
: "${GROK_HOSTED_CHECK_RUN:?export GROK_HOSTED_CHECK_RUN=<hosted run id or URL> first}"

# 0. 0 calls. The installed runtime shows the Grok row jailed, and the provider-free
#    qualification is current for the production key.
timeout 300 phase-loop seat-window matrix
timeout 300 phase-loop seat-sandbox qualify --leg grok
echo "$GROK_SHA  $GROK_BIN" | sha256sum --check --strict

# 1. Open the jailed grant: 3 labels, 2 retries, cap 5. 0 calls.
"${MT[@]}" --new-grant --planned pilot,planted,confirm --retries 2 \
  --hosted-check "$GROK_HOSTED_CHECK_RUN"

# 2. The rehearsal of the pilot under a budget-0 proxy. 0 calls.
"${MT[@]}" --attended --rehearse --route staged

# 3. Gate on THIS grant's rehearsal record.
"${MT[@]}" --require-rehearsed staged

# 4. The pilot. At most 1 counted request.
"${MT[@]}" --attended --route staged

# 5. Gate on the pilot: exits non-zero unless the label just launched is "measured".
"${MT[@]}" --require-measured staged

# 6. planted, then confirm. At most 1 counted request each.
"${MT[@]}" --attended --route staged --route staged
"${MT[@]}" --require-measured staged

# 7. Aggregate: the agreement rule and the publication gate, then the jailed host-local
#    record. 0 calls.
"${MT[@]}" --aggregate

# 8. The grant-backed check. 0 calls. Passes only if the jailed staged row is
#    frozen_measurement, admitted and sourced from the host-local jailed record, and every
#    other form is refused. Its probe writes the host's first jailed receipt.
"${MT[@]}" --verify-probe final

"${MT[@]}" --status
```

## Notes

- A `--route staged` stage exits non-zero when its label was not `measured`, when the launch
  was `unspawned`, or when nothing could be reserved; later routes on the same command line
  are not attempted. `--status` reports `charged`, `retries_used`, `unspawned`, `unresolved`
  and `stopped`.
- A transport retry is step 4 or step 6 run again; the label is chosen by the ledger, never
  by the operator. A retry is refused while any reservation is unresolved.
- `--aggregate` publishes `staged` only if `pilot`, `planted` and `confirm` are each
  `measured` with identical `tools` and `definitions_sha256`, and the passed rehearsal and
  every label record the same production `launch_digest`; otherwise it refuses
  `surface_unstable` and publishes nothing. A measured surface that is not admitted is
  evidence only.
- `--aggregate` is the only writer of the jailed host-local record; the jailed receipt is
  written only by the probe of step 8 (or `phase-loop seat-window probe-tools --vendor grok`
  once the record exists). Jail contract §3, "Production writers".
- The installed-catalog check (jail contract §7.1) comes after GROK SL-6 and is not part of
  this script.
