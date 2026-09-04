# Detailed Plan: FABPUB Zero-History Bootstrap

status: implemented-awaiting-exact-head-review
owner: codex-plan-detailed
issue: Consiliency/agent-harness#763
base: `6af811e98049f82bc82255c58c54caa6e618c8e6`
review: four-vendor board; Fable/Gemini agree, Grok safety findings reconciled,
  Sol implementation-only objection deferred to exact-head code review

## Objective

Make FABPUB usable on a host with no compatible legacy `run-train` broker
ledger. Add one explicit, irreversible, fail-closed bootstrap that creates a
persistent global `ACTIVE` authority without fabricating a legacy source and
onboards named repositories with authenticated zero-source receipts.

This repair unblocks the preserved `Consiliency/omniagent-plus` Omnigent v0.12
branch. It does not authorize direct push, manual npm publication, or a runtime
release ahead of Consiliency/agent-harness#710.

## Frozen Inputs

- `LegacyBrokerCutoverManifest.v2`, `LegacyBrokerCutoverTransaction.v2`, and
  `LegacyRepositoryPartitionReceipt.v2` stay byte-compatible.
- Empty legacy manifests remain illegal; bootstrap is a distinct transaction.
- The persistent default is
  `$XDG_STATE_HOME/phase-loop/fabpub/authority-v1`, falling back to
  `~/.local/state/phase-loop/fabpub/authority-v1`.
- Standalone publication receipts outside the hashed run-train layout are
  historical-evidence inputs. Hash and classify them in place; never silently
  import them as allocator authority.
- Omnigent upstream v0.12 is distinct from the Omniagent transport and GitHub
  release version `0.7.0`.

## Implementation

### 1. Freeze adversarial behavior

- Require a sealed probe inventory and independent CLI/Python confirmation.
- Cover the authority root, environment and explicit legacy roots, every named
  canonical namespace, historical-evidence roots, and discovered
  `.train-ledger/broker` roots below declared search roots.
- Re-probe under the authority lock before mutation and fail on changed bytes,
  root sets, repository identities, symlinks, unclassified state, held leases,
  prior incompatible receipts, or conflicting authority.
- Permit only an absent/empty namespace, a pristine initialized latch, or an
  idempotent receipt owned by the same bootstrap.
- Prove `DRAINING -> INVENTORY_SEALED -> ARMED -> ACTIVE`, byte-identical retry,
  fresh-process discovery, no retirement/archive artifacts, and authenticated
  active repositories.
- Prove direct onboarding before global `ACTIVE` fails and normal manifest
  barriers reach global `ACTIVE`.

### 2. Add the authority primitive

- Add `ZeroHistoryBootstrapInventory.v1`, a dedicated authority resolver, and
  read-only canonical source discovery in `convergence/broker/live.py`.
- Apply requires `confirmed_zero_history=True`, revalidates before latch
  mutation, drains and awaits each worktree, then records a dedicated monotonic
  journal. It must not call `_drive_cutover`, retire a source, write a root
  `RETIRED` tombstone, or create a legacy archive.
- Make onboarding require global `ACTIVE`, reject unattested canonical state,
  and enforce `DRAINING` before latch activation.
- Make the manifest barrier call its existing transaction's `activate()` before
  onboarding or leasing.
- Ensure fresh-process readers discover the dedicated persistent authority.

### 3. Add the operator command

Add `phase-loop fabpub-bootstrap` with mutually exclusive `--probe` and
`--apply` modes, required `--inventory`, repeatable worktree/root inputs, and
required `--confirm-zero-history` for apply. Output is metadata-only.

The inspected universe is bounded to canonical namespaces plus explicit,
environment-derived, historical, and searched roots. Confirmation attests no
compatible source exists outside that universe.

### 4. Verify and release

Run focused FABPUB and CLI tests, affected suites, Ruff, compilation,
`git diff --check`, and an exact-head four-vendor board. Do not bump or release
the runtime in this change; agent-harness#710 owns that release.

After merge, use the reviewed source to probe and apply one authority inventory
covering agent-harness, Omniagent, declared/search roots, and both known
standalone receipt roots. Publish the agent-harness repair through FABPUB, then
install merged main and publish Omniagent through the same authority.

## Acceptance Criteria

- [x] Bootstrap is explicit, inventory-bound, persistent, irreversible,
  retry-safe, and fail-closed.
- [x] Existing non-empty legacy cutover bytes and behavior are unchanged.
- [x] Direct onboarding before global `ACTIVE` is impossible.
- [x] Manifest-driven cutover reaches global `ACTIVE`.
- [x] Repositories receive authenticated zero-source receipts and active
  writer generations only after drain and quiescence.
- [x] Fresh-process discovery requires no transient shell state.
- [x] CLI output is metadata-only and confirmation-gated.
- [x] Focused and broad affected verification is green.
- [ ] Exact-head four-vendor review has no unresolved blocking finding.
- [ ] Publication uses FABPUB only; no direct push or manual npm publish.
