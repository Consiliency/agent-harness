# PI seat fixtures (frozen by SL-1.0)

Frozen inputs for `plans/phase-plan-v1-seats-PI.md`, contract
`plans/artifacts/seats-pi-route-contract-v3.md` §7. SL-1 owns this directory. SL-2 and SL-3 read it
and never write it. `manifest.json` lists every file with its sha256 and provenance;
`test_pi_panel_leg.py` checks that listing.

## Provenance

| Label | Meaning |
|---|---|
| `recorded` | Captured from the installed Pi 1.6.0 (`cli_bundle_sha256` in the manifest) under projected Node v24.22.3. Pi ran offline with no credential and no network: a network namespace with loopback only, a scratch home and a placeholder store. The answers came from a per-launch loopback recording proxy that forwards nothing. |
| `stub_witness` | Witness records written by the SL-1.0 stub extension from Pi's real `after_provider_response` and `provider_stream_event` calls. SL-1.2's `witness.mjs` re-records them. |
| `derived` | A recorded file with stated changes: `derived_from`, `case`, and `transformations` when there is more than one change. |
| `synthetic` | Hand-written in the documented format. Values the contract marks *to measure* are placeholders until SL-3.6. |

`manifest.owed` lists what offline recording could not supply.

**How the recordings were made.** Pi was started directly as the projected Node running the
recorded Pi bundle. The manifest's `command` is that argv normalized to `pi`, with `WITNESS`
standing for the stub witness path. Pi reached `chatgpt.com` through `HTTPS_PROXY`. The
per-launch proxy terminated TLS locally with a throwaway CA and answered every request itself.
That seam is test-only: it proves nothing about the jail's or the seat host's trust setup.

**Derived positive case.** `events/derived/tooled-verdict-eligible.jsonl`, with its witness and
proxy counterparts under `witness/derived/` and `proxy/derived/`, is the eligible counterpart of
the recorded tooled success. Its `transformations` list every change: a recognized terminal
verdict, the recomputed output digest, and the tool-originated POST removed. The recorded
tooled runs remain the refusal case, because their counts are unequal.

## Formats

- **`events/*.jsonl`**: Pi `--mode json` stdout, one event per line, unchanged except that the
  evidence and release path prefixes are replaced by `/seat` and `/opt/pi-release`.
- **`witness/*.jsonl`**: the channel is an `AF_UNIX` `SOCK_STREAM` socketpair end, passed to Pi as
  the descriptor named by `PHASE_LOOP_PI_WITNESS_FD`. Each line is one UTF-8 JSON object, the
  `pi_seat_witness.v1` record. It has exactly these fields:
  - `schema`: `"pi_seat_witness.v1"`;
  - `ordinal`: an integer, 1, 2, … with no gap or repeat;
  - `status`: the HTTP status, an integer from 100 to 599;
  - `completed`: a boolean;
  - `response_id` and `upstream_model`: a string or null;
  - `output_sha256`: lowercase hex sha256 of the response's final output text (the empty string
    when it has none), or null.

  A record with `completed: true` has a 2xx status and non-null `response_id`, `upstream_model`
  and `output_sha256`. `witness/synthetic/*` are the C1 refusal cases (`expected_refusal`).
  `after-settled` carries `settled_after_ordinal`, the last ordinal written before
  `agent_settled`.
- **`proxy/*.json`**: `pi_seat_fixture_proxy.v1`, the requests one launch's proxy saw.
  `origin` is `pi` or `tool_descendant`. `allowed_inference_count` counts the inference POSTs the
  proxy admitted. It is decided at admission, before any response, so it does not depend on
  `status_sent`. `response_body_sha256` is the sha256 of the response body the proxy sent, where
  that body was a fixed error body; it is null for event streams.
- **`stores/*.json`**: synthetic `auth.json` stores. `access` is a template,
  `{"$fixture_jwt": {"claims": {...}}}`. A consumer encodes it as
  `b64url({"alg":"none","typ":"JWT"}) + "." + b64url(claims) + ".FIXTURE-NOT-A-SIGNATURE"`, with
  no padding. `{"$fixture_opaque": "<label>"}` is any non-empty placeholder string. Times are
  relative to `manifest.fixture_now_ms`. `duplicate-key.json` repeats a JSON key on purpose.
- **`routes/route-record.synthetic.json`**: a `pi_seat_route.v1` record with contract §3 fields.
  The zero digests are placeholders.
- **`measurements/trust-preconditions.json`**: the three contract §7 preconditions, measured from
  a tool that Pi's own bash tool spawned (`pi -> bash -> python3`). It includes a positive
  control: the same calls against the probe's own child.
