# Claude SDK boundary receipt — EC-CLAUDE-3

`receipt-v1.json` is pending. It is produced at GL-2 alone, from the `VB` and `VL` runs
on the final executable tree, and this directory carries no receipt until then. Without a
packaged receipt the `sdk` transport's preflight refuses
`claude_sdk_dependency_unavailable` before any credential is read; `sdk` also stays
unadmitted (`ADMITTED = False`) in `phase_loop_runtime/claude_seat_sdk.py`.

The receipt is closed schema `claude-sdk-boundary.v1`
(`claude_seat_sdk.RECEIPT_FIELDS`, checked by `claude_seat_sdk.validate_receipt`). It
holds only digests, counts, host and interpreter vocabulary and opaque evidence IDs:

- the SDK version, lock, contract and `proof_inputs_sha256` bindings;
- the installed bindings (launch fixture, export, closure manifest, worker payload and
  seat module), which runtime preflight recomputes from the installed package;
- the schema-defined source regions of shared modules;
- the runtime manifest digests of the qualified host class, the worker-install digest
  and the instrumentation-wrapper digest;
- the public `VB`/`VL` JUnit digests and per-file counts, and the private suite's digest,
  opaque selector IDs and counts. Every required selector collects tests, all pass,
  none is skipped.

The proof inputs are exactly `claude_seat_sdk.PROOF_FILES` and
`claude_seat_sdk.PROOF_REGIONS`. A change outside them cannot stale the receipt, a change
inside them always does, and an import outside `claude_seat_sdk.DEPENDENCY_INVENTORY`
fails closed.

## Worker install

The worker runs from its own sealed install, never from the harness environment:

```
uv venv --python <worker-python> <worker-venv>
uv pip sync --python <worker-venv>/bin/python --require-hashes --only-binary :all: \
  phase_loop_runtime/data/claude_sdk/requirements-v1.txt
python -m phase_loop_runtime.claude_seat_sdk seal <worker-venv>
python -m phase_loop_runtime.claude_seat_sdk verify
```

`seal` copies exactly the closure manifest's files, plus the interpreter, standard library,
ELF loader and runtime libraries, into a read-only snapshot under the operator's private
state, and writes a 0600 registration. `verify` hashes the snapshot in full the first time
a process sees it, then compares its signature inventory before every worker.
