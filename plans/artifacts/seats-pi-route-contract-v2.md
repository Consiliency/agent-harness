# SEATS PI: route, credential and attribution contract v2

Frozen detail for `plans/phase-plan-v1-seats-PI.md`, which cites this file by section. v2
replaces v1. It covers the subscription route (`pi`, `openai-codex`). The paid DeepSeek route is
the separate design in §13 and has no production registration. Exit criteria are cited by ID only.

**Labels.**

- **[source]**: read from the installed Pi 1.6.0 packages, `@earendil-works/pi-coding-agent` and
  `@earendil-works/pi-ai`.
- **[to measure]**: established in SL-3.1 or SL-3.6 and recorded in the route record.

A different projected Pi version is a new input.

## 1. Owner inputs

- **OD-5 (2026-11-21)**, verbatim: "1. But pi should be able to use subscription authed
  providers primarily". The rest of the roadmap default stands: the provider-scoped credential
  the Pi executor already uses for its routed provider, no aggregator, a spend cap if API-billed,
  and no plan or production slot change.
- **OQ-1: "OpenAI subscription".** The primary route is Pi's `openai-codex` sign-in, counted as
  codex. The credential is the operator's existing Pi sign-in.
- **OQ-2: "Yes, DeepSeek with a cap".** The paid route is wanted in v1. It is sequenced after
  the subscription route (§13). It waits on the owner's cap amount, cap period and key source,
  and on the other §13 gates. This is sequencing, not a change to the decision.

## 2. Pi facts

**Store [source].**

- `auth.json` is in `PI_CODING_AGENT_DIR`, else `~/.pi/agent`, with one entry per provider.
- OAuth entries hold `{type:"oauth", access, refresh, expires(epoch ms), …}`.
- Every store access takes a `proper-lockfile` lock directory next to `auth.json`.
- A refresh happens when `now + minValidity >= expires`. The default minimum validity is
  300000 ms, and a caller may ask for more. The refreshed token is written to the store.

**`openai-codex` [source].**

- Base URL `https://chatgpt.com/backend-api`; inference is `POST /codex/responses`.
- OAuth client `app_EMoamEEZ73f0CkXaXp7hrann`; requested scopes `openid profile email
  offline_access`; token endpoint `https://auth.openai.com/oauth/token`.
- `expires = now + expires_in·1000`.
- The adapter derives the `chatgpt-account-id` header from the bearer's claims, so whether the
  stored `accountId` is needed is to measure.
- The transport `auto` tries a WebSocket first. With `transport: "sse"` set, the WebSocket
  branch is skipped.
- On each HTTP response the adapter calls `onResponse({status, headers})`. The CLI exposes that
  call to extensions.
- On a non-success status the adapter throws an Error carrying the provider's text.
- It retries internally on 429 and 5xx, up to its `maxRetries` option.
- The assistant event's `provider` and `model` are copied from the request, so they attest
  nothing.

**CLI and events [source].**

- `--offline` disables startup networking only. `--api-key` exists.
- A bare `--` is a startup error.
- The JSON-mode event types are `session`, `agent_start`, `turn_start`, `turn_end`,
  `message_start`, `message_update`, `message_end`, `tool_execution_start`,
  `tool_execution_update`, `tool_execution_end`, `agent_end`, `agent_before_settle` and
  `agent_settled`.
- The built-in tools are `read`, `bash`, `edit`, `write`, `grep`, `find`, `ls` and `powershell`.

**To measure:**

- the request set and startup hosts;
- that private settings (`transport`, retry) reach the launch;
- the effective retry count;
- CA, redirect and proxy-dispatcher behavior in the jail;
- the issued claims (`iss`, `aud`, `client_id`, scopes, account claim, `exp − iat`);
- whether Pi needs `accountId`;
- read-only operation;
- the POST count per leg;
- whether tool processes inherit the witness descriptor (§7);
- the in-seat ptrace scope.

## 3. Route record, trust anchor and snapshot

**Route record.** `phase_loop_runtime/seat_egress/pi-route.json`, schema `pi_seat_route.v1`, is
package data. Its fields:

- `leg`;
- `provider` (`openai-codex`) and `auth_type` (`oauth`);
- `admitted_models` (map: requested id → accepted upstream ids);
- `pi_version`;
- `allowlist_id` and `allowlist_sha256`;
- `kept_fields`;
- `expiry_unit` (`ms`), `min_validity_ms`, `skew_ms` and `lifetime_ceiling_s`;
- `claims` (§8);
- `request_budget`;
- `named_observations`;
- `settings`;
- `witness_sha256`.

**Trust anchor.**

- `pi_review_route.py`, installed runtime code, holds the record's sha256 as the constant
  `PI_ROUTE_SHA256`.
- The reader is `pi_review_route.load_route()`. It reads the record through the package
  data-path resolver the allowlists use, refuses a size above the cap or any digest mismatch,
  and never reads a checkout copy.
- The code itself is authenticated by the managed release (IF-0-TEAMHOST).
- A missing or tampered installed record is refused with `pi_seat_od5_evidence_missing`.
  Installed-package tests cover both cases.

**Snapshot.** The panel launch puts the selected model into the route request environment
(`PHASE_LOOP_PI_MODEL`) before resolution. The profile `variant(env)` returns the sha256 of the
record digest and that model. A model outside `admitted_models` is
`pi_seat_od5_evidence_missing`.

`key_for_launch` then folds in the projection and the allowlist digest. The resulting immutable
`PiRouteSnapshot` (variant, qualification key, projection digest, allowlist digest, model) is
carried by the launch.

Before spawn:

- the started proxy's `allowlist_digest` must equal the snapshot's;
- argv `--model` must equal the snapshot model;
- the settings and witness digests must match the record.

Any mismatch is `pi_seat_od5_evidence_missing`. The snapshot is computed before any cached
decision is used. A cached decision is reused only when its snapshot is equal.

## 4. Request set (`pi`)

Candidates are from source; the actual set is measured in SL-3.6.

- **Allowed:** `POST chatgpt.com /backend-api/codex/responses`.
- **Named refusals:**
  - `(CONNECT, auth.openai.com, None)`;
  - each startup host SL-3.6 observes without `--offline`;
  - one same-host account path and one token-like path, chosen in SL-3.6.

  The total stays within the 16-entry `named` limit.
- **Every other request is refused.**

**Lifetime.** The record's `lifetime_ceiling_s` is the largest measured lifetime plus 10
percent. A lifetime below the §5 margin is a STOP.

## 5. Expiry and typed ends

**Margin.**

- Admission needs `expires_ms − now_ms ≥ deadline_ms + max(min_validity_ms, requested_min_ms)
  + skew_ms`.
- The deadline is `panel_invoker._LEG_TIMEOUT_MAX_S`, `skew_ms` is 300000, and
  `requested_min_ms` is the largest minimum validity the launch configuration asks Pi for.
- That gives 2400 s at the current cap.
- The check runs on the exact projected bytes immediately before spawn.

**Credible expiry.**

- `expires` is a finite integer.
- `exp` and `iat` are present, and `iat ≤ now + skew`.
- `|expires − exp·1000| ≤ 60000`.
- `exp − iat ≤ lifetime_ceiling_s`.
- Otherwise the code is `pi_seat_credential_route_mismatch`.

**Short tokens.** The harness waits read-only for the owner to renew the login, as
`seat_credentials.await_login_margin` does. If the wait ends short, the code is
`pi_seat_token_expiring`. The harness never runs Pi or a token endpoint for credentials.

**Ends.** Each end is decided from the §7 witness and the proxy stream, applied in this order.
The first match wins:

1. An observed token-host request, or a refresh signal (§8): `pi_seat_token_refreshed_in_jail`
   (security).
2. An incomplete stream or witness, an unnamed denial, or a proxy-allowed inference count
   different from the witness count: `pi_seat_containment_unproven` (security).
3. A witnessed 401 or 403: `pi_seat_credential_expired`.
4. A witnessed 429, a 5xx or a transport failure: the existing generic availability codes, not
   counted.
5. A recorded budget refusal: `pi_seat_attribution_unavailable`. A clean review that used its
   last authorized POST is not a budget refusal.
6. Otherwise the §11 verdict rules apply.

Two responses with the same body but different status must produce different ends.

**Retries.** The harness-written settings set provider retries to 0 if Pi honors that, which is
to measure. Every Pi-internal retry is a witnessed and budgeted POST. No end leads the harness
to retry, renew or switch route.

## 6. Egress

- **Per launch.** Each launch has its own proxy-only namespace and its own
  `start_proxy(allowlist_id="pi", request_budget, named)`. The bridge is proven with grok's
  `bridged_to`, which checks holder, bridge and socket generically. A namespace held by another
  leg is never reused. A failed proof refuses the launch.
- **Windows.** The leg runs in a fenced `leg` window. Negative probes run only in a `bracket`
  window.
- **Probes.** From a real tool descendant: an unlisted host, each named host and path, a
  same-host method and path, a non-443 authority, an SNI mismatch, direct-IP, and DNS. Each must
  be refused or fail.
- **`--offline`.** Proven by a mutation run without the flag.
- **Environment and argv.** Checked in Pi and in a tool descendant. No pi-ai key or token
  variable, no `--api-key`, and planted ambient credentials never win.
- **Interfaces.** Only the existing `named` and `request_budget` proxy interfaces are used (S1).

## 7. Command, witness and terminal grammar

**Command.**

```
pi --offline --provider openai-codex --model M --thinking E --mode json --print --no-session --no-approve --no-context-files --no-mcp --no-skills --no-prompt-templates --no-themes --no-extensions --extension TOOLSET --extension WITNESS --tools read,grep,find,ls,bash
```

There is no trailing `--`. The prompt goes on stdin.

**Private directory.** The agent directory holds the credential (§8) and a harness-written
`settings.json` with only the record's `settings`. The CA is `.phase-loop-seat-egress-ca.pem`,
mounted read-only, with the trust variables SL-1.1 proves. `.config`, `.cache` and
`.local/share` are private and removed at teardown.

**Witness.** `phase_loop_runtime/data/pi_seat/witness.mjs` is pinned by `witness_sha256` and
projected read-only. It observes the adapter's `onResponse` and the terminal response, and
writes one validated metadata record per inference response to a descriptor that only the Pi
process holds. Each record holds:

- an ordinal;
- the HTTP status;
- whether the response completed;
- the response id;
- the upstream model;
- the sha256 of the final output text.

It holds no body and no header values beyond those fields. The witness can be trusted only on
two measured preconditions:

- tool processes do not inherit the descriptor;
- the seat's ptrace scope stops a tool from writing into its ancestor Pi.

If either fails, that is the S1 alternative: a proxy-side response witness, which changes the
shared proxy and so is a STOP.

**Cross-check.** The witness count must equal the proxy's allowed inference count. A
tool-originated allowed POST leaves the counts unequal and gives
`pi_seat_containment_unproven`.

**Tools.** Every `tool_execution_start` name must be in the listed set, or the code is
`pi_seat_unknown_event`.

**Terminal grammar.**

1. One `session` header first.
2. Then turns; an assistant `message_end` with `stopReason` `toolUse` is allowed.
3. The final assistant `message_end` has `stop`, carries no error, and holds the verdict
   payload.
4. Then `agent_end`, then `agent_settled{aborted:false}`.
5. Nothing follows.

**Fixtures.** They are recorded from the projected binary through a test-only loopback seam
that production cannot reach. They cover:

- a tooled success with several `message_end` events;
- an assistant error alongside `aborted:false`;
- malformed, duplicate and post-terminal streams;
- 401, 403 and 429 with identical bodies;
- a 5xx;
- a transport reset;
- a differing upstream model;
- a tool-originated POST.

## 8. Credential copy, mount and containment

**Copy.** One `openai-codex` entry, read from the owner-only, size-capped operator store at
`PI_CODING_AGENT_DIR` (else `~/.pi/agent`) only.

- Kept: `type`, `access`, `expires`, plus `accountId` only if SL-3.6 shows it is needed.
- `refresh` is set to `""`.
- A malformed entry, a duplicate key, or the wrong provider or type is
  `pi_seat_credential_route_mismatch`.

**Claims.** The bearer's claims are decoded on the host. This is inspection, not issuer
verification.

- `iss`, `aud` and `client_id` must equal the record's measured values. Pi's constant
  `app_EMoamEEZ73f0CkXaXp7hrann` is the expected client.
- The scope set must equal the record's measured set.
- The account claim must equal the expected account in the operator-private
  `pi_seat_login.v1` record. The owner writes that record at LA-2 sign-in with
  `phase-loop seat-sandbox pi-login-record`, which records the account id and the date, never a
  token.
- A missing or ambiguous claim, or any mismatch, is `pi_seat_token_scope_excess`. A missing
  login record is `pi_seat_credential_missing`.

**Mount.** Both paths keep the file read-only.

- **Preferred:** `--ro-bind-fd` of the sealed memfd at `.pi/agent/auth.json`, which preserves
  identity. Whether the qualified launcher supports it is to measure.
- **Otherwise:** `--ro-bind-data`. Before exec, the parent records the mounted file's own device
  and inode and verifies its bytes equal the sealed bytes.

**Ancestors.**

- `.pi/agent` is its own private writable tmpfs mount, so Pi's lock directory works there. A
  mount point cannot be renamed or unlinked.
- `PI_CODING_AGENT_DIR` names that mount point.
- At pre-exec and at teardown (after tools are quiescent), the parent checks through a retained
  anchor that the expected path still resolves to the recorded mount, by mount id and path.
  `auth.json` must have the recorded identity and the sealed bytes.

**Outcomes.**

- Failed inspection (no anchor, a read error, an unresolvable path) is
  `pi_seat_containment_unproven`.
- Observed modification (bytes or identity differ, or the mount moved) is
  `pi_seat_token_refreshed_in_jail`.
- **Refresh signals:**
  - a token-host request;
  - an observed modification;
  - a Pi diagnostic of an OAuth refresh.

  Normal reads and lock-directory create and remove are not signals.

**Secrets.**

- `access` and its `seat_jail.secret_encodings` are registered with the parent's scan before
  spawn.
- Every output, error, diagnostic, verdict, record and artifact is scanned before it is
  retained.
- A positive is `pi_seat_secret_in_output`, reported privately, and the review goes to the T3
  board.
- Planted sentinels are tested on success, tool-failure, timeout and teardown-failure paths.
- Incomplete proof is recorded privately.

## 9. Pi containment proof (VL0 supplier)

The generic first-use jail pass, `seat_jail_qualification.qualify`, only gates jail capability.
The Pi containment proof is a separate supplier, `seat_pi_qualification.py`.

- It runs the real projected Pi with the §8 mount, the §6 proxy and the §7 witness against the
  loopback fixture.
- It writes a host-local pass record bound to the qualification key.
- The `pi` profile carries `Precondition("pi_containment", …)`, which reads that record, as
  Gemini's `tooled_profile` precondition does.
- Negative control: without the record, or with a record for another key, the route resolves
  degraded.
- `seat_jail_qualification.py` is not edited (S6).

## 10. Codes

- **Ordinary:** `pi_seat_credential_missing`, `pi_seat_od5_evidence_missing`,
  `pi_seat_credential_route_mismatch`, `pi_seat_token_expiring`, `pi_seat_credential_expired`,
  `pi_seat_attribution_unavailable` and `pi_seat_cli_shape`.
- **Security:** `pi_seat_secret_in_output`, `pi_seat_token_refreshed_in_jail`,
  `pi_seat_token_scope_excess`, `pi_seat_containment_unproven` and `pi_seat_unknown_event`.

`pi_seat_spend_cap_missing` belongs to §13 and is not registered in the subscription lanes.

## 11. Attribution and policy

**Verdict eligibility.** A verdict counts only when all of these hold:

- the final assistant response id matches a witness record with status 2xx and completion;
- the record's output digest equals the digest of the final assistant text;
- the witness and proxy counts agree;
- the stream is complete.

A failed, rejected, unrelated or tool-originated POST cannot satisfy this. Otherwise the code is
`pi_seat_attribution_unavailable`.

**Model.**

- The requested model (argv) is policy.
- The witnessed upstream model is evidence. It must be an accepted id for that model in
  `admitted_models`.
- A missing or different upstream model is `pi_seat_attribution_unavailable`.

**Vendor.**

- `PI_PROVIDER_VENDOR = {"openai-codex": "codex"}`, closed.
- Pre-launch board selection uses the snapshot's route intent.
- Final counts need eligibility.
- `vendor_family` never uses the model for the `pi` harness.

**Consumers.**

- `composition.board_independence`;
- `governed_review.select_reviewer_pool`, `governed_planning_gate` and `governed_board_gate`;
- `author_vendor_for_executor` and `author_vendor_for_model`;
- `panel_invoker._validate_review_board_policy`, with `(harness, model)` keys;
- `president_adapter.seat_for_rung`.

**Author provenance.**

- `author_vendor_for_executor("pi")` returns `pi:unknown` unless a trusted `pi_author_route.v1`
  record binds the authoring run and review subject to a provider.
- `runner._phase_author_vendors` keeps non-empty values, so `pi:unknown` survives mixed-author
  aggregation.
- Both governed gates hold with `unknown_author` when any author is `pi:unknown`. That routes
  through the existing non-human hold and the T3 handoff.
- Tests: a mixed Claude and unknown-Pi author holds. A known Pi author (synthetic record)
  reviewed by a native codex seat is refused as same-vendor.
- The production producer of `pi_author_route.v1` belongs to the Pi LANE-executor plan, which
  owns `launcher.py` (S7).

## 12. Shared surfaces and stops

- **S1.** `seat_egress_proxy.py` and `seat_egress/proxy.mjs` are not edited, because they feed
  the Gemini proxy proof digest. A proxy-side response witness (§7 alternative) or new
  observation vocabulary is a STOP for the JAILCORE/GEMINI owner, with Gemini requalification.
- **S2.** `seat_profiles.py` and `seat_route_contract.py` are whole-file Claude SDK proof
  inputs. On `origin/main` the SDK is unadmitted (`claude_seat_sdk.ADMITTED = False`) and no
  receipt exists, so the SDK gate skips receipt validation and nothing goes stale. At the SL-2
  PR, recheck that on base and head and run `claude-sdk-audit` and `audit-order`. If the SDK is
  admitted or a receipt exists by then, STOP for the CLAUDE owner. Current-tree proof is
  required at SDK admission. No `SDK_PROOF_REGIONS` function is edited.
- **S3.** `grok_tool_surface.py` is not edited. `bridged_to` is called as is.
- **S4.** The paid route stays out of production registration, launch, qualification and
  readiness until §13's gates hold.
- **S5.** No window-kit function and no frozen JAILCORE or TEAMHOST artifact changes.
- **S6.** `seat_jail_qualification.py` is not edited. It feeds the Gemini watch and validator
  digests.
- **S7.** Treating Pi authorship as unknown changes governed gating for every Pi-executor phase.
  Today `pi` counts as its own vendor. The coordinator accepts the hold, or the Pi
  LANE-executor plan supplies `pi_author_route.v1` first.

## 13. Paid route (design only, not registered)

**Intent.** A DeepSeek API-key leg with a spend cap, wanted by the owner in v1, sequenced after
the subscription route.

**Gates.** It is built only under its own plan amendment (lane group SL-5) and its own plan
review, once all of these hold:

1. the owner's cap amount and currency, cap period and key source (`executor` or `seat_only`),
   recorded privately;
2. a FIRSTSEAT amendment to IF-0-FIRSTSEAT-1 that gives the leg its own readiness identity,
   because `seat_window.readiness_rows` keys rows by profile vendor;
3. a verified provider-side enforcement binding (below).

**Rules when built.**

- It is its own profile and allowlist (`pi-deepseek`).
- It runs only when board config explicitly lists it and sets `allow_api_key_fallback`.
- No `pi` outcome selects it.
- A literal key only: `env` is dropped, and `!` and `$` forms are refused.
- Its scope is `unavailable`.
- A missing or invalid cap record is `pi_seat_spend_cap_missing`.

**Enforcement binding.** The exact key must be shown, by provider-side evidence the amendment
names, to belong to the capped account or project. The expected account or project comes from
an independent owner record, not from the cap record. A positive hard stop (amount, currency
and period) must be in force.

A claimed budget, a notification threshold, or a request counter is not enforcement. An
unverifiable, partial or stale binding refuses the route. If the provider offers no verifiable
hard stop, the route stays withheld.

**Before the amendment.** No billable measurement is authorized. Until then:

- no `pi-deepseek` profile, allowlist, window, alias or harness exists in production;
- a board naming it is refused by the existing unknown-harness path;
- tests prove that a planted synthetic cap record or route file changes neither the registry,
  routing, qualification nor the Pi readiness row.
