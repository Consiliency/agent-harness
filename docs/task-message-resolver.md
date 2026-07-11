# Trusted task-message resolver

`phase-loop task-message-resolve` is the read-only cross-host source resolver for governed approvals. It reads one exact pair of Codex user-message items from an authenticated app-server; it does not read copied rollout JSONL, accept caller-supplied digests, search for a latest message, or mutate the source task.

## Source envelope

Codex app-server 0.144.1 identifies a caller-supplied `clientUserMessageId` as the persisted `userMessage.clientId`; the stored `userMessage.id` is separately assigned by app-server. Adjacent text inputs in one `turn/start` request are normalized into one persisted text item, so they cannot carry this contract.

Create two separate user messages in the same task, in this order:

1. one text input containing the exact human/source approval message, with `clientUserMessageId=<source-message-id>`;
2. one text input containing only the exact JSON approval record, with `clientUserMessageId=<source-message-id>-approval`.

The JSON record must be an authorized approval containing `contract_version`, `source_thread_id`, `source_message_id`, and `source_message_sha256`. The thread claim and source `clientId` claim must match the requested app-server identities, and `source_message_sha256` must be the SHA-256 of the first message's exact UTF-8 bytes. The resolver requires unique source and approval client identities, unique app-server-assigned item IDs, source-before-approval ordering, one text item in each message, and fresh timestamps for both turns. This fixed pair separates the source bytes from the canonical approval body without a self-referential hash or concatenated parsing.

The resolver returns the raw byte fields as base64 only after every identity, freshness, and digest check passes. It also returns SHA-256 of the source bytes, SHA-256 of the raw approval-body bytes, and SHA-256 of the RFC 8785-canonical approval object. The successful resolve payload is sensitive approval data and must be consumed directly, not copied into logs or ledger events.

## Authenticated source

Run the source Codex app-server on a tailnet-only listener with either capability-token or signed-bearer-token authentication. `--authority` must be exactly `codex-app-server://<endpoint-hostname>`; this binds the proof identity to the authenticated route instead of accepting a caller-selected label. Use the source host's tailnet DNS name or tailnet address in `--endpoint`; do not expose the listener to a public interface.

Keep the bearer value in a secret-backed environment variable. Pass only its variable name to the CLI:

```sh
phase-loop task-message-probe \
  --endpoint ws://claw.example.ts.net:8765 \
  --authority codex-app-server://claw.example.ts.net \
  --token-env CODEX_TASK_MESSAGE_TOKEN
```

The probe performs only the authenticated app-server initialization handshake and emits authority/status metadata. It does not read a task or message.

Codex app-server 0.144.1's owner-only Unix control socket is itself a WebSocket
transport. For a managed source task, run the resolver on the source host
against that socket and carry the JSON result back over a separately
authenticated channel such as tailnet SSH:

```sh
ssh claw.example.ts.net phase-loop task-message-resolve \
  --control-socket /home/operator/.codex/app-server-control/app-server-control.sock \
  --authority codex-app-server://claw.example.ts.net \
  --thread-id 019f4454-2012-7061-847d-1a9ab0e9ef00 \
  --message-id provdeploy-approval-001 \
  --max-source-age-seconds 900
```

`--control-socket` is local-side only. It performs the required WebSocket HTTP
Upgrade directly over the Unix socket with compression disabled, matching
Codex 0.144.1's supported transport. It does not expose the socket or add a
network listener. The caller is responsible for authenticating the outer
channel and pinning `--authority` to that source host. Network WebSocket mode
continues to require `--token-env`; control-socket mode never accepts or reads a
bearer. A missing socket, failed handshake, or unavailable task fails closed
with `source_task_unavailable`.

Resolve one exact source after the probe is ready:

```sh
phase-loop task-message-resolve \
  --endpoint ws://claw.example.ts.net:8765 \
  --authority codex-app-server://claw.example.ts.net \
  --token-env CODEX_TASK_MESSAGE_TOKEN \
  --thread-id 019f4454-2012-7061-847d-1a9ab0e9ef00 \
  --message-id provdeploy-approval-001 \
  --max-source-age-seconds 900
```

## Fail-closed results

Failures contain only authority and requested identities plus one code:

- `source_task_unavailable`
- `source_message_unavailable`
- `source_identity_mismatch`
- `source_bytes_unavailable`
- `approval_body_unavailable`
- `attestation_invalid`
- `source_stale`

Authentication failures, malformed app-server responses, wrong or duplicate client identities, missing app-server item identities, reversed pairs, concatenated single-item envelopes, non-text inputs, digest-only objects, and stale records never produce a successful proof.

## ai-stack boundary

When the source daemon supports proxying, ai-stack should invoke control-socket mode on the source host over its authenticated tailnet SSH boundary, decode the two successful base64 fields into its `TrustedSourceMessage(message_bytes, approval_body_bytes)` interface, and independently repeat schema, identity, source-message SHA-256, and RFC 8785 canonical approval checks before constructing an adapter or actuator. A ready resolver proves only the source boundary; it does not authorize a service restart or any other mutation.
