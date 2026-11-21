# SEATS PI: route, credential and attribution contract v1

Frozen detail for `plans/phase-plan-v1-seats-PI.md`, which cites this file by section.
Exit criteria are cited by ID only; `specs/phase-plans-seats-v1.md` holds their text.

**Source labels.** Each Pi fact below carries one of two labels:

- **[source]**: read from the installed Pi 1.6.0 packages, `@earendil-works/pi-coding-agent` and
  `@earendil-works/pi-ai`, in the current managed release.
- **[to measure]**: not established from source. The named task measures it, and the measured
  value goes into the route record.

A different projected Pi version is a new input, and SL-3.1 runs again for it.

## 1. Owner inputs

- **OD-5 (2026-11-21)**, verbatim: "1. But pi should be able to use subscription authed
  providers primarily". The roadmap default otherwise stands: the provider-scoped credential the
  Pi executor already uses for its routed provider, no aggregator, a spend cap if API-billed, and
  no plan or production slot change.
- **OQ-1 (answered 2026-11-21): "OpenAI subscription".** The primary route is Pi's
  `openai-codex` subscription provider, counted as the codex vendor. The credential is the
  operator's existing Pi `openai-codex` sign-in, so the executor-credential default applies to
  it.
- **OQ-2 (answered 2026-11-21): "Yes, DeepSeek with a cap".** A DeepSeek API-key route is wanted
  in v1. Three values are still the owner's to give: the cap amount, the cap period, and the key
  source (the executor's key or a seat-only key). Until a spend-cap record holding all three
  exists (§9), the route refuses with `pi_seat_spend_cap_missing`.

## 2. Pi facts

**Credential store [source].**

- The store is `auth.json` in the agent directory: `PI_CODING_AGENT_DIR`, else `~/.pi/agent`.
- It holds one entry per provider id.
- An OAuth entry is `{type:"oauth", access, refresh, expires}` plus provider fields. `expires` is
  in epoch milliseconds.
- An API-key entry is `{type:"api_key", key, env}`. A `key` beginning with `!` runs a command,
  and `$VAR` or `${VAR}` forms expand environment variables.
- Store reads and writes take a `proper-lockfile` lock directory next to `auth.json`.

**Refresh [source].** pi-ai refreshes an OAuth token when `now + 300000 ms >= expires`, the
default minimum validity. A caller may ask for a longer minimum. A refresh runs under the store
lock and persists the new token.

**`openai-codex` [source].**

- Base URL `https://chatgpt.com/backend-api`, inference at `/codex/responses`.
- The OAuth client id and the scopes `openid profile email offline_access` are the Codex CLI's.
- The token endpoint is `https://auth.openai.com/oauth/token`.
- `expires = now + expires_in·1000`.
- `accountId` is derived from the access token's claims and sent as `chatgpt-account-id`.
- The default transport `auto` tries a WebSocket upgrade, then falls back to SSE. The settings
  key `transport` can force `sse`.
- The assistant event's `provider` and `model` are copied from the request model before any
  response arrives, so they do not attest anything.

**`deepseek` [source].**

- Base URL `https://api.deepseek.com`, OpenAI-completions API.
- API key only.
- The environment variable `DEEPSEEK_API_KEY` is one ambient source the seat must never see.

**JSON mode [source].**

- Event types: `session`, `agent_start`, `turn_start`, `turn_end`, `message_start`,
  `message_update`, `message_end`, `tool_execution_start`, `tool_execution_update`,
  `tool_execution_end`, `agent_end`, `agent_before_settle` and `agent_settled`.
- An assistant `stopReason` is one of `stop`, `toolUse`, `length`, `error` or `aborted`.
- `agent_settled.aborted == false` can accompany an assistant error.

**CLI [source].**

- A bare `--` is parsed as an unknown extension flag with an empty name, which is a startup error.
- `--offline` disables startup network operations only.
- `--api-key` exists.
- The built-in tools are `read`, `bash`, `edit`, `write`, `grep`, `find`, `ls` and `powershell`.

**To measure, each in SL-3.1 unless another task is named:**

- the inference request set and every other request Pi makes on the route;
- whether `--print` reads the prompt from stdin (SL-1.1);
- the WebSocket attempt under forced SSE;
- the token lifetime (`exp − iat`);
- the minimum set of credential fields Pi needs;
- whether Pi completes a turn with a read-only `auth.json`;
- the per-leg POST count;
- DeepSeek's request paths and its provider-side cap mechanism.

## 3. Route record and snapshot

**Route record.** A route record (`pi_seat_route.v1`) is package data:

- `phase_loop_runtime/seat_egress/pi-route.json`, with leg `pi`;
- `phase_loop_runtime/seat_egress/pi-deepseek-route.json`, with leg `pi-deepseek`.

The managed install carries both, under `seat_egress/*`. The release's integrity manifest
authenticates them as it does the allowlists, and a copy outside the installed package is never
read. `plans/evidence/seats-pi/` keeps the metadata-only measurement evidence behind each record.

Fields:

- `schema`, `leg`, `provider`, `auth_type` (`oauth` or `api_key`), `admitted_models`, and
  `pi_version` with the projected package digest;
- `allowlist_id` and `allowlist_sha256`;
- `kept_fields`;
- `expiry_unit` (`ms`), `refresh_window_ms`, `skew_ms` and `lifetime_ceiling_s`;
- `scope_basis`, which is `claims_ceiling` or `unavailable`;
- `request_budget`;
- `named_observations`;
- `transport`;
- `spend_cap_required`.

**Snapshot.** At route resolution the runtime builds one immutable `PiRouteSnapshot`: the
sha256 of the record bytes, the allowlist digest, the projection digest, the selected model,
the named-observation set and the budget.

- The snapshot digest is the profile `variant`, so it enters the qualification key. A
  provider, model, record, allowlist or projection change therefore changes the key, even when
  the endpoint rows are identical.
- Credential copy, argv, proxy start, settings and attribution all read the one snapshot. Any
  re-read that differs is refused with `pi_seat_od5_evidence_missing`.
- A missing or unauthenticated record, or a model outside `admitted_models`, is refused with
  `pi_seat_od5_evidence_missing`.

## 4. Routes

**Two legs.** Each route is its own registered leg, with its own profile, allowlist,
qualification key and window evidence, because `JailProfile.allowlist_id` is fixed per profile.
The two legs are additive under IF-0-JAILCORE-1.

| Leg | Provider / auth | Board harness | Counted vendor | Selected |
|---|---|---|---|---|
| `pi` | `openai-codex` / `oauth` | `pi` | codex | When board config lists `pi` |
| `pi-deepseek` | `deepseek` / `api_key` | `pi-deepseek` | deepseek | Only when board config lists `pi-deepseek`, sets `allow_api_key_fallback`, and §9 holds |

**No automatic switch.** No outcome of the `pi` leg selects `pi-deepseek`. That covers an
expiring token, an expiry, an unavailable route and a refusal. A paid leg runs only when the
board config lists it.

**`pi` request set (to measure; candidate rows from source).**

- Allowed: `POST chatgpt.com /backend-api/codex/responses`.
- Refused, with a named observation for each:
  - `CONNECT auth.openai.com:443`, which carries sign-in and token refresh;
  - a WebSocket `GET` on the inference path, when Pi still tries it under forced SSE;
  - every startup host that SL-3.1 observes without `--offline`.

  Same-host paths other than the inference row are refused by the rules. Two of them are
  named: one account path and one token-like path, both chosen in SL-3.1.

**`pi` token lifetime.**

- The lifetime is to measure.
- The record's `lifetime_ceiling_s` is the largest lifetime measured, plus 10 percent.
- If the measured lifetime is shorter than the §5 margin, the route cannot admit at the current
  leg cap. SL-3.1 then reports a STOP instead of lowering the margin.

**`pi-deepseek` request set (to measure).** `POST api.deepseek.com` on the measured completions
path is the only allowed row. No token host exists. Startup hosts are named as for `pi`.

## 5. Expiry, margin and typed ends

**Margin.**

- Admission needs `expires_ms − now_ms ≥ (deadline_s + refresh_window_s + skew_s) · 1000`.
- The deadline is `panel_invoker._LEG_TIMEOUT_MAX_S`. `refresh_window_s` is 300 and `skew_s`
  is 300.
- At the current 1800 s cap the margin is 2400 s.

**Pre-spawn check.** The check runs on the exact projected copy, immediately before spawn,
after staging and projection. An earlier admission does not carry over.

**Credible expiry.** `expires` must be a finite integer. The access token's `exp` claim must
agree with it within 60 s, and `exp − iat ≤ lifetime_ceiling_s`. Otherwise the code is
`pi_seat_credential_route_mismatch`.

**Short token.** A short token gets a read-only wait for owner renewal outside the harness, the
same behaviour as `seat_credentials.await_login_margin`. It ends with `pi_seat_token_expiring`.
The harness never runs Pi or a token endpoint for credentials.

**Typed ends after launch.** Each is decided from the real response evidence, never from the
assistant text: Pi's assistant error diagnostics, its HTTP status, and the proxy stream.

| Evidence | Code |
|---|---|
| Upstream 401 or 403 on an allowed inference request | `pi_seat_credential_expired` (ordinary) |
| Proxy refusal of a token or sign-in host, or any credential-file activity | `pi_seat_token_refreshed_in_jail` (security) |
| Proxy refusal of an unlisted host, path or method during the leg | `pi_seat_containment_unproven` (security) |
| 429, 5xx, or transport reset or timeout | the existing generic leg availability codes, not counted |
| Budget spent | the leg is not counted (`pi_seat_attribution_unavailable`) |

No end retries, renews or switches routes. The review falls to the T3 board under OD-10.

## 6. Egress and observation

**One namespace and proxy per launch.** Each Pi launch holds its own proxy-only namespace and
starts its own proxy:

```
seat_egress_proxy.start_proxy(allowlist_id=<leg>, request_budget=<record>, named=<record>)
```

Pi and every tool descendant run in that namespace. A namespace held by another leg is never
reused. Before spawn, the namespace is proven bridged to this proxy's socket, as grok's
`bridged_to` check does. That check is reused if it is profile-generic, and otherwise an
equivalent runs in SL-1. A missing or incomplete bridge proof refuses the launch.

**Leg window.** The leg runs inside a fenced `leg` window. Intentional negative probes run only
in a separate `bracket` window, so the two sets of events never mix.

**Completion.** `seat_egress_proxy.completion` must be complete. A complete stream holds:

- at least one allowed request on the record's inference row;
- no allowed request on any other row;
- only named refusals.

**Probes, all from a real tool descendant, inside the bracket window:**

- an unlisted host;
- each refused named host;
- a disallowed path and a disallowed method on the allowed host;
- a non-443 authority and an SNI mismatch;
- direct-IP TCP;
- a DNS lookup.

Each probe must be refused or must fail.

**`--offline`.** It is proven by observing startup through the proxy. A mutation without the
flag must produce the named startup observations.

**Environment and argv.** They are checked in the launched Pi process and in a tool descendant:

- no pi-ai provider key or token variable is present;
- `--api-key` is absent;
- `PI_CODING_AGENT_DIR` names the private directory;
- ambient credential settings never win: a variable planted in the launcher's environment and an
  `auth.json` planted in the owner home both stay unseen.

**Interfaces.** The existing `named` (at most 16 entries) and `request_budget` interfaces are
the only proxy interfaces used.

## 7. Leg command and terminal state

**Command.**

```
pi --offline --provider P --model M --thinking E --mode json --print --no-session --no-approve --no-context-files --no-mcp --no-skills --no-prompt-templates --no-themes --no-extensions --extension TOOLSET --tools read,grep,find,ls,bash
```

There is no trailing `--`. The prompt goes on stdin. `P` and `M` come from the snapshot.

**Private agent directory.**

- It holds the credential copy (§8) and a harness-written `settings.json` containing only
  `{"transport": "sse"}`, or the measured equivalent.
- Its CA file is `.phase-loop-seat-egress-ca.pem`, mounted read-only, with the trust variables
  SL-1.1 proves.
- `.config`, `.cache` and `.local/share` are private and removed at teardown.

**Tools.** `edit`, `write` and `powershell` are never listed. A `TOOLSET` name joins the list
only if `TOOLSET` declares it. Every `tool_execution_start` name must be in the listed set, or
the code is `pi_seat_unknown_event`.

**Terminal grammar.**

1. One `session` header first.
2. Then turns. An assistant `message_end` with `stopReason` `toolUse` is allowed.
3. The final assistant `message_end` has `stopReason` `stop`, carries no error, and holds the
   board-verdict payload.
4. Then `agent_end`, then `agent_settled` with `aborted == false`.
5. Nothing follows.

Any assistant `error`, `aborted` or `length` stop is a typed failure, classified by §5. Any
other deviation is a typed leg failure.

**Fixtures.** Fixtures are recorded from the projected binary against a loopback provider
fixture, through a test-only seam that production launch cannot reach. They include a tooled
success with several assistant `message_end` events, and an assistant error paired with
`agent_settled.aborted == false`.

## 8. Credential copy and containment

**Copy.** One entry for the snapshot's provider, built on the host from the owner-only,
size-capped operator store.

| Route | Kept | Changed or dropped | Refused |
|---|---|---|---|
| `oauth` | `type`, `access`, `expires` and the record's `kept_fields` (`accountId` is the candidate; to measure) | `refresh` becomes `""` | A malformed entry, a duplicate key, or the wrong provider or auth type: `pi_seat_credential_route_mismatch` |
| `api_key` | `type` and a literal `key` | `env` is dropped | A `key` that starts with `!` or contains `$`: `pi_seat_credential_route_mismatch` |

**Install.**

- The copy is a sealed memfd, mounted `--perms 0444 --ro-bind-data` at `.pi/agent/auth.json`,
  inside a writable private `.pi/agent` that holds Pi's lock directory.
- A bind-mounted file cannot be replaced or unlinked from inside the seat.
- If SL-3.1 shows Pi cannot complete a turn read-only, that is a STOP. There is no writable
  fallback.

**Read-back.**

- At teardown the parent reads the mounted file through the seat's root.
- The read is bounded by the size cap and identity-checked: the same device and inode as the
  mount source, and a regular file.
- The bytes must equal the sealed memfd.
- A pre-spawn check proves the checked host copy is exactly the bytes installed.
- Any difference, a substituted object, or a failed read is `pi_seat_token_refreshed_in_jail`.

**Secret registration.**

- Every delivered secret value is registered with the parent's redaction scan before spawn:
  `access`, or `key`, and their `seat_jail.secret_encodings`.
- That happens before any output, error, diagnostic, verdict, record or artifact is retained.
- A positive is `pi_seat_secret_in_output`. It is reported privately and the review falls to
  the T3 board.
- Planted sentinels are exercised on success, early tool failure, timeout and teardown-failure
  paths, and no published artifact may contain one.

**Teardown.**

- The seat home is destroyed.
- A partial teardown, or any missing containment proof, is `pi_seat_containment_unproven`,
  reported privately.

**Scope.**

- **`pi`:** `scope_basis = claims_ceiling`. The decoded claims must match the Codex seat's
  recorded issuer, client id and scope baseline (`seat_codex_credential.CODEX_SCOPE_CEILING`).
  This is claim inspection, not signature proof. Otherwise the code is
  `pi_seat_token_scope_excess`.
- **`pi-deepseek`:** `scope_basis = unavailable`, because the key is opaque. `credential_scope`
  reads `unavailable`. The route can be admitted only with §9's provider-enforced cap.

## 9. Spend cap (`pi-deepseek` only)

**Record.** The record is operator-private, schema `pi_seat_spend_cap.v1`, mode 0600, under
`seat_host_namespace.operator_private_dir`. Its fields:

- `provider` (`deepseek`);
- `account_binding`, an owner-attested account or project label;
- `key_binding`, an HMAC-SHA256 of the delivered key under a host-local private salt (never the
  key itself);
- `amount` and `currency`;
- `period`;
- `enforced_by = "provider"`, with `enforcement_evidence`: an owner-attested description and a
  date;
- `key_source`, either `executor` or `seat_only`;
- `owner`;
- `valid_from` and `valid_until`;
- `recorded_at`.

**Admission.** The record must be present, current, positive, and for this provider. Its
`key_binding` must match the copied key. Otherwise the code is `pi_seat_spend_cap_missing`.
Pi's reported usage is recorded for information only. It does not count as enforcement.

**Remaining owner inputs.** The amount, the period and the key source. The provider-side
enforcement mechanism is to measure, then owner-attested.

## 10. Codes

- **Ordinary:** `pi_seat_credential_missing`, `pi_seat_od5_evidence_missing`,
  `pi_seat_spend_cap_missing`, `pi_seat_credential_route_mismatch`, `pi_seat_token_expiring`,
  `pi_seat_credential_expired`, `pi_seat_attribution_unavailable` and `pi_seat_cli_shape`.
- **Security:** `pi_seat_secret_in_output`, `pi_seat_token_refreshed_in_jail`,
  `pi_seat_token_scope_excess`, `pi_seat_containment_unproven` and `pi_seat_unknown_event`.

All are terminal. Fix lines recommend a subscription sign-in or an owner record, never an
API-key lane.

## 11. Attribution and policy

**Provider attestation.** A leg is counted only with a complete §6 stream that shows its
allowed inference requests on the snapshot's single inference row. That row is the only allowed
egress, so the response Pi reports can only have come from that provider. Pi's JSONL `provider`
and `model` fields are never evidence. Without that proof the code is
`pi_seat_attribution_unavailable` and the leg is not counted.

**Model.**

- The model is attested only by the snapshot argv.
- A response model that differs, seen through Pi's real adapter against the fixture, must not
  change the counted vendor.
- Whether Pi can surface an independent upstream model is to measure. If it can, a mismatch
  against `admitted_models` is `pi_seat_attribution_unavailable`.

**Vendor.** Counting uses the closed `PI_PROVIDER_VENDOR` map: `openai-codex`→codex,
`deepseek`→deepseek. Anything else is refused. `vendor_family` never uses the model string for
the `pi` or `pi-deepseek` harnesses.

**Consumers.** The routed identity is carried through:

- `composition.board_independence`;
- `governed_review.select_reviewer_pool`, and the author paths that consume
  `author_vendor_for_executor`;
- `panel_invoker._validate_review_board_policy`, with `(harness, model)` alias keys;
- `president_adapter.seat_for_rung`, used by `president_operation`.

**Author provenance.** An author executor `pi` has unknown provenance unless the run's author
record names its routed provider. Unknown provenance is a typed independence refusal
(`author_provenance_unknown`). It is a policy outcome, so the review goes to the T3 board.

## 12. Shared surfaces and owner stops

- **S1.** `seat_egress_proxy.py` and `seat_egress/proxy.mjs` are not edited, because they feed
  the Gemini proxy proof digest. A proof that needs a proxy change is a STOP for the
  JAILCORE/GEMINI owner.
- **S2.** `seat_profiles.py` and `seat_route_contract.py` are whole-file Claude SDK proof inputs
  (`claude_seat_transport.SDK_PROOF_FILES`). PI's additive edits to them stale that receipt, so
  the CLAUDE owner must accept and re-prove it under EC-CLAUDE-3. PI edits no function in
  `SDK_PROOF_REGIONS`, and the regions in `seat_jail.py` stay untouched.
- **S3.** `grok_tool_surface.py` and the grok contract are not edited.
- **S4.** The readiness matrix (IF-0-FIRSTSEAT-1) gets no `pi-deepseek` row. The paid leg's
  status is recorded in the capabilities card and in `plans/evidence/seats-pi/paid/`. A matrix
  row needs a FIRSTSEAT change.
- **S5.** No window-kit function and no frozen JAILCORE or TEAMHOST artifact changes.
