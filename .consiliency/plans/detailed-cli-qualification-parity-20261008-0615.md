# Detailed plan: per-host CLI qualification parity for every seat harness

## Task
Implement the three maintainer decisions of 2026-10-08:

1. **Parity.** Every harness that can fill a seat gets the same per-host CLI qualification model that only agy has today. That covers claude, codex, grok, gemini/agy and opencode, plus pi and cursor-agent once they can fill a seat.
2. **Relax agy.** A new upstream agy release becomes an advisory warning, not a blocker. First-use self-qualification on each host covers new versions. The full source pin of runtime files stays, and so does the release-time requalification of listed members.
3. **Feedback loop.** A version that a host qualifies for itself becomes a reviewable candidate. A maintainer can promote it into the shipped list, but only through a re-verifiable step. A record from another host is never trusted as-is.

Out of scope:
- The seat sandbox/jail design itself.
- The sealed-fallback policy for codex/grok, which stays as it is.
- The president ladder.

**Size.** This plan exceeds the skill's bounded-plan threshold of about 8 files and about 3 concepts. It is written as one umbrella document with **seven independently landable PRs**, each with its own acceptance criteria and falsifier, because the PRs share one contract and one trust model. Splitting it into seven plans would restate both seven times. The implementer of each PR should treat its section as that PR's bounded plan.

## Research summary
**What agy qualification does today.** A qualified agy image is identified by its binary sha256 plus the sha256 of its `--help` output. The version string is only a label.
- `gemini_heartbeat.QUALIFIED_IMAGES` (`gemini_heartbeat.py:21`) maps image sha256 to help sha256. `verify_qualified_agy_image.py` (VS) requires it to match `plans/evidence/qualified-provider-images.json` exactly. `catalog_route()` (VS:57) requires exactly one route, `gemini_heartbeat_linux_x64`.
- First use runs `agy_qualification.ensure_admitted` (AQ:1130) → `qualify_image` (AQ:1247) → `run_operation` (AQ:523) for each of `OPERATIONS` (AQ:50): completion, cancel and owner-loss. Each runs through the heartbeat broker with an external observer.
- **Admission classes** are `release_qualified`, `locally_qualified` and `qualification_candidate`.
- **The local store** is an HMAC'd per-host store, `Store.host_dir` (AQ:791) under `$XDG_STATE_HOME/phase-loop/agy-qualification/hosts/<machine>/`. Its entries bind image, platform, runtime identity, profile id and help digest (AQ:970-984).
- **Runtime identity** is `__version__` plus the digests of the `ROUTE_CORE` files (AQ:44, AQ:74).
- **Counting.** `counts_toward_landing` / `president_input_items` (AQ:1290-1330) decide whether a leg's vote counts.
- **Where the rules are written down.** `advisor_board/CONTRACTS.md` "First-use self-qualification (agent-harness#1076)" specifies all of the above and is the template for the generic contract.

**Claude.** Claude has only *jail* qualification. Its pass store `seat-jail-passes/<digest>.json` is keyed by the **jail profile digest** (`seat_jail.py:1061-1079`), the host and the falsifier layout, **not** by the CLI binary. A new claude CLI version therefore does not invalidate a pass.
- First use goes through `seat_jail_autoqualify.ensure_qualified` (around l.225).
- `qualify()` accepts only `leg="claude"`.

**Codex, grok and opencode** have the agent-harness#1282 owner and typed refusals only.

**The seam.** Every seat goes through `panel_invoker._seat_route_for_spawn` (PI:11049).
- It already takes injectable `decide`, `pass_recorded` and `qualify_on_first_use`, and returns `(route, notices, refusal)`.
- It returns `(None, [], None)` for legs that `seat_jail.decide_seat_route` does not handle (`seat_jail.py:675`: claude and gemini only).
- The preflight `_seat_launch_modes` (PI:1923) already carries a `qualified_now` field on `SeatMode` (`seat_preflight.py:190-226`).
- **Where launcher identity is resolved:**
  - `_seat_provider_source` (PI:4555) maps basenames such as `codex.js`, `claude.exe`, `grok-native` and `opencode.exe` to a harness and resolves symlinks.
  - `_provider_entry` / `_recorded_provider_hashes` (PI:5003-5028) hash the codex, claude, grok, agy and opencode binaries. They do not cover pi or cursor-agent.
- `advisor_board/registries.py:202-210` lists all seven harnesses. The panel leg tables (`_LEG_CLI`, PI:1564) cover four.

**The upstream-agy "release gate" is not a release blocker in code.**
- `publish-pypi.yml:51-57` runs only `--source-only`.
- The newest-upstream check (`require(len(latest) == 1, …)`, VS:165) runs only in the `upstream` job of `.github/workflows/qualified-agy-image.yml:74-85`, on schedule or dispatch. It reddens the nightly.
- It is treated as a release blocker only by the release recipe text: `docs/releases/outside-agent-release-handoff.md` (around l.66, l.187-191, l.260-262) and the `CHANGELOG.md` 0.7.22 caveat (around l.523-528).
- No test pins the `upstream` job.

**A gap for decision 2.** `agy_integrity.check` (`agy_integrity.py:19`) accepts **only** `QUALIFIED_IMAGES` members. The owned Gemini seat path that runs without a heartbeat profile uses it (PI:4773-4774), as does the credential-refresh path (PI:4678-4679). A locally qualified newer agy is therefore refused there, even though the heartbeat route admits it.

agent-harness#1308 (merged) shows why the full pin stays: a non-agy file (credential-expiry parsing) broke agy qualification on Python 3.10.

## Design

### (a) The harness-agnostic qualification contract
A **qualified CLI version** is a key that passed every operation that applies to its route on this host, under this runtime.

**The key is `(harness, platform, launcher_identity, help_digest, runtime_identity)`.**
- `launcher_identity` is the sha256 of the resolved real-path content of the entry the seat actually executes. Resolution reuses `_seat_provider_source`.
  - For a script launcher (an npm-shipped `codex.js` or claude entry), the key also includes the sha256 of the interpreter's real path. Ruled (Q2, 2026-10-08): yes, the interpreter hash is part of the key.
- `help_digest` is the sha256 of a per-adapter **option-surface probe**. That is the declared help argv(s) covering every flag the seat's launch builder uses, with stdout and stderr captured together, the way AQ:1071 does it.
- `runtime_identity` is `__version__` plus the digests of the harness adapter's own route-core files. agy's tuple is unchanged.
- The version string is a display label only and never part of the key.

**Operations.** Each operation runs through the seat's **own production launch path**, never a test-only path:

| op | meaning | applies to |
|---|---|---|
| `identity` | resolve the launcher, hash it, and measure the help digest | every harness |
| `completion` | one short prompt; a parseable answer within the deadline | every harness |
| `cancel` | SIGTERM after progress is observed; a clean terminal and no surviving process | every harness |
| `owner_loss` | SIGKILL the owner; the provider process tree is gone and no terminal record is written | every route launched under an owner. Since agent-harness#1282 that is all routes: the agy broker, the claude jail and the codex/grok/opencode owner. |

**Classes.** The agy classes generalize unchanged: `release_qualified`, `locally_qualified` and `qualification_candidate`. A candidate is never counted and never persisted.

**Lifecycle.**
- First use happens per user, per host, per key.
- A new version gives a new launcher or help digest. The key is then absent, so first use runs again.
- A runtime upgrade gives a new `runtime_identity`, which also triggers first use. This is the same as agy today.
- **Failures.**
  - An identity or isolation violation writes `failed`. It is sticky until `phase-loop cli-qualification clear --harness <h>`.
  - Transients follow agy's rule: the third consecutive transient writes `failed` (`MAX_TRANSIENT_ATTEMPTS`, AQ:752).
  - Cancellation writes nothing.
- **Concurrency.** One `flock` per host namespace and harness. Waiters heartbeat and re-check the store, as `agy-qualification.json` progress does today.
- **Opt-out.** Opting out goes in the user config only: `[qualification.<harness>] self_qualification = false`. The existing `[agy] self_qualification` keeps working. A repository config cannot opt out.

**Notices.** The new codes are additive and generic:
- `seat_cli_unqualified`
- `seat_cli_qualification_failed`
- `seat_cli_qualification_unavailable`
- `seat_cli_qualification_store_unsafe`
- `seat_cli_adapter_missing`

Each code has what/why/fix text in `seat_jail.NOTICES`, and the fix lines name `phase-loop cli-qualification status|run|clear --harness <h>`. The existing `gemini_heartbeat_self_qualification_*` and `agy_image_unqualified` codes stay in place as agy's specific spellings. No code is renamed.

**Never toolless.** A qualification refusal maps to `MODE_DEGRADED` with its fix line, or to the next rung of the existing route ladder. It never maps to `sealed`. None of the new codes may join `SEALED_FALLBACK_CODES` (`seat_jail.py:349`), and a test pins that.

**Store.** The store lives at `$XDG_STATE_HOME/phase-loop/cli-qualification/hosts/<machine>/<harness>/`. It uses the same discipline as agy's `Store`:
- directories are 0700 and files 0600, owned by the euid and opened `O_NOFOLLOW`;
- every entry carries a per-host HMAC over the type, the euid, the machine-id and the live key.

It is a **new** store. It is orthogonal to `seat-jail-passes/`: a jailed claude seat needs both a jail pass and a CLI qualification.

### (b) Per-harness adapters
There is one table of adapters, one per harness. Each adapter declares:
- the launcher resolver, which reuses PI:4555 and PI:5003;
- the help-probe argv(s);
- the completion request, built by the seat's own launch builder;
- whether progress can be observed for `cancel`;
- an optional `upstream_provenance` hook, used only for promotion in (d). agy's is `agy_provenance`.

The adapters hold no fleet paths or markers.

**How they plug in.** `_seat_route_for_spawn` calls `cli_qualification.ensure_admitted(harness, …)` for **every** leg. It runs after the existing jail and route decision and before launch. The preflight records the admission class in `SeatMode.qualified_now`, and the board evidence records it per leg.

**Completeness test.** The set of harnesses that can fill a seat today is the union of the `_LEG_CLI` legs and any omnigent-backed seat route (opencode, pi, cursor-agent). Each of them must have an adapter, or the launch refuses with `seat_cli_adapter_missing`. pi and cursor-agent therefore get an adapter in the same PR that first lets them fill a seat, and not before.

### (c) agy relaxation (decision 2)
**What changes:**
- **The `upstream` job** (`qualified-agy-image.yml:84-85`) becomes advisory. The step stays on schedule and dispatch, but a failure emits `::warning::newest upstream agy <v> is not a shipped member; hosts self-qualify it on first use` and leaves the job green. It follows the existing nightly drift pattern (l.65-72).
- **The release recipe** stops listing "`--upstream-only` passes" as a cut criterion. That affects `docs/releases/outside-agent-release-handoff.md` (around l.66) and the 0.7.22-style caveats.
- **The gap.** `agy_integrity.check` admits by `agy_qualification.lookup` class (`release_qualified` or `locally_qualified`) instead of only by `QUALIFIED_IMAGES` membership. Then a self-qualified newer agy also runs on the owned non-heartbeat seat path. This touches no `ROUTE_CORE` file (`agy_integrity.py` is outside the tuple), so ordinary PR CI stays `--route-core`.

**What stays, unchanged:**
- `publish-pypi.yml` `--source-only` (blocking).
- `--route-core` on every PR.
- `agy_full_pin_scope.sh`.
- Live requalification of listed members on the release-cut tree.
- The `QUALIFIED_IMAGES` == catalog equality.
- `agy_watch` draft PRs.

### (d) Feedback and promotion, with its trust model
**Export.** `phase-loop cli-qualification export --harness <h>` writes a closed-schema `cli_qualification_candidate.v1` record:
- `harness`, `platform`, `version_label`
- `launcher_sha256`, `interpreter_sha256?`, `help_sha256`
- `runtime_identity`, `agent_harness_version`
- `ops: {op: "passed"}` and `utc`

The schema has `additionalProperties: false`, and every string is constrained to hex, semver, an enum or an ISO time. It carries **no** HMAC, machine-id, hostname, path, username, environment, credential or raw receipt. The exporter validates its own output against the schema and refuses to write a record that fails.

**Submission.** The operator attaches the record to a draft PR or an issue. v1 does not push automatically (ruled, Q4).

**Promotion is the only way the shipped list grows.** A promotion PR adds the member to the catalog (shape in PR6). CI and the release lane then **re-verify it independently**:
1. Obtain the artifact through the adapter's `upstream_provenance`, then match `launcher_sha256` (and `interpreter_sha256` where it applies) and re-measure `help_sha256`. For agy this is `agy_provenance`. For npm-shipped CLIs it is the registry tarball's published integrity. For a harness with no verifiable upstream digest (grok, opencode), promotion is refused and the harness stays first-use only (ruled, Q3).
2. Run the live operations on a release-lane host and commit a redacted record that the verifier checks against the binary hash, as agy members are recorded today.

The host's candidate is a lead and is never evidence: the verifier never reads its `ops`.

**Who benefits.** Other hosts skip the live operations only for **shipped** members. That is `release_qualified`: an identity and help-digest check, exactly as for agy now. They never skip them for a peer's candidate.

### (e) Phasing: seven PRs
Each PR is small, lands independently in the order shown, and quotes its own falsifier. "Tests-first" means the corpus *skips* contracts that are not yet implemented in ordinary runs instead of failing them.

**PR1: agy relaxation.** Files:
- `.github/workflows/qualified-agy-image.yml` (`upstream` job)
- `phase-loop-runtime/src/phase_loop_runtime/agy_integrity.py` (`check` admits by class)
- `phase-loop-runtime/tests/test_verify_qualified_agy_route_core.py` (new cells)
- a new `tests/test_agy_integrity_local_admission.py`
- `docs/releases/outside-agent-release-handoff.md`, `CHANGELOG.md`

Acceptance:
- [ ] A new test parses the workflow. It asserts that the `upstream` step cannot fail the job and emits `::warning::`, and that publish-pypi's `--source-only` step is still blocking: the existing `test_publication_is_gated_on_the_full_pin_set` stays green and unchanged.
- [ ] `agy_integrity.check` admits an image whose store lookup returns `locally_qualified`. It still refuses an image whose store is absent, failed or tampered.

Falsifiers:
- Restoring the bare `--upstream-only` run reddens the new workflow test.
- Making `check` accept any image reddens the tampered-store cell.

**PR2: the contract module, inert.** Files:
- a new `phase-loop-runtime/src/phase_loop_runtime/cli_qualification.py`: key, classes, ops runner, store, lock, candidate schema and export validator
- `seat_jail.NOTICES` (the 5 new codes)
- `panel_invoker._HARNESS_DETAIL_CODES` (around l.2824; the 5 new codes)
- a new `tests/test_cli_qualification_contract.py`
- `advisor_board/CONTRACTS.md` (a new "CLI qualification (all harnesses)" section that points at the agy section as the reference instance)

Nothing calls the module yet.

Acceptance:
- [ ] Unit tests cover store safety (permissions, symlink, foreign euid), HMAC tamper refusal, the transient → failed rule, a key change → absent, and the export schema refusing a path-shaped or host-shaped field.
- [ ] No new code is in `SEALED_FALLBACK_CODES`.

Falsifier: delete the HMAC check, and the tamper cell reddens.

**PR3: codex, grok and opencode adapters, wired.** Files:
- `cli_qualification.py` (the adapters)
- `panel_invoker._seat_route_for_spawn` and `_seat_launch_modes`
- `seat_preflight.py` (renders the class)
- a new `tests/test_cli_qualification_seat_route.py`

Acceptance:
- [ ] A codex or grok leg on a host with no record runs first use and launches with the recorded class `locally_qualified`.
- [ ] A seeded `failed` record refuses with `seat_cli_qualification_failed`, `MODE_DEGRADED` and a fix line, never `sealed`.
- [ ] A changed launcher digest re-runs first use.
- [ ] The completeness test binds the adapter table to the set of harnesses that can fill a seat.

Falsifier: drop the call in `_seat_route_for_spawn`, and the first-use cell reddens.

The PR body also records one real host run per harness, with the actual result of each operation.

**PR4: claude adapter.** Files:
- `cli_qualification.py` (the claude adapter)
- `_seat_route_for_spawn` (the jailed claude route now requires both checks)
- tests

The jail pass store is **untouched**.

Acceptance:
- [ ] A jail pass with an unqualified CLI refuses with `seat_cli_unqualified`.
- [ ] A qualified CLI with no jail pass keeps today's jail notice.
- [ ] Neither store's keys are read from the other's.

Falsifier: seed only the jail pass, and the launch must refuse.

**PR5: agy onto the contract.** Files:
- `agy_qualification.py` delegates its store, lock, class and transient logic to `cli_qualification`, and keeps its broker-specific operations and provenance
- `gemini_heartbeat.py` only if needed

This touches `ROUTE_CORE`, so it **lands as part of a release cut**, which is where the full requalification already happens.

**Migration.** Existing v1 entries under `agy-qualification/` are read-only legacy. A v1 `qualified` entry that verifies against its original context mints a v2 entry, so there is no forced re-run. A v1 entry that fails verification is absent.

Acceptance:
- [ ] A host with a v1 `qualified` entry admits `locally_qualified` without running operations.
- [ ] A tampered v1 entry is absent.
- [ ] `verify_qualified_agy_image.py --source-only` passes on the cut tree with a fresh record.

Falsifier: flip one byte of the v1 entry, and the legacy cell must refuse.

**PR6: export, catalog v2 and a generic verifier.** Files:
- `cli_qualification.py` (`export`)
- the `phase-loop cli-qualification` CLI
- `plans/evidence/qualified-provider-images.json` → v2 (routes keyed by `(harness, platform)`; the agy route is carried byte-equivalently)
- `phase-loop-runtime/scripts/verify_qualified_agy_image.py` (generalized, or wrapped by a new `verify_qualified_cli.py` that keeps the agy flags)
- a new workflow step that re-verifies a promotion PR
- `docs/ops/cli-qualification-promotion.md` (new)

Acceptance:
- [ ] A promotion PR whose `launcher_sha256` does not match the upstream artifact fails.
- [ ] A PR whose catalog member has no committed release-lane record fails.
- [ ] An exported record passes the schema.
- [ ] The agy route verifies exactly as before.

Falsifier: point a candidate's hash at a different upstream asset, and the CI step must go red.

**PR7: counting enforcement for non-agy legs (ruled, Q1).** This PR lands in the release *after* the one that ships PR3 and PR4. It extends `counts_toward_landing` / `president_input_items` (AQ:1290-1330) to every harness's class. Until it lands, PR3 and PR4 record the class but do not change counting.

**Rollout and migration summary:**
- Self-qualification is on by default per harness, with a user-config opt-out.
- The claude jail pass store is unchanged.
- agy v1 entries migrate by verified legacy read (PR5).
- Shipped non-agy members start empty. Every host self-qualifies until PR6 promotions land.

### (f) Questions put to the maintainer
All five are ruled; see "Maintainer rulings" below. The question text is kept as history.
- **Q1. Counting.** Should a non-agy leg without a `release_qualified` or `locally_qualified` class stop counting toward landing, as agy's does? *Recommend:* yes, as PR7, after PR3 and PR4 have been live for one release.
- **Q2. Script launchers.** Does the interpreter (node) identity enter the key for npm-shipped CLIs? *Recommend:* yes. A node upgrade then triggers one cheap re-run per host.
- **Q3. Promotion without verifiable upstream provenance.** For harnesses such as grok or opencode with no published integrity digest, choose between two options:
  - *Recommended:* refuse promotion; those harnesses stay first-use only.
  - Accept a release-lane-built record keyed by a hash the release lane downloads itself. This is weaker, because there is no publisher attestation.
- **Q4. Submission channel.** Should export stay manual (attach to a PR or issue), or should a watcher in the style of `agy_watch` open draft promotion PRs from a subscribed host? *Recommend:* manual in v1.
- **Q5. Requalifying non-agy members at release.** Decision 2 keeps full requalification for agy members. Choose between two options:
  - *Recommended:* re-run every listed member of every harness at each cut. This costs about 1 min of inference per member and pushes towards a short list.
  - Re-run only the newest member per harness, and age out older ones.

### Maintainer rulings (2026-10-08)
These rulings are append-only. All five follow the recommendation, and no maintainer decision is left open.
- **Q1: yes.** A non-agy leg without a `release_qualified` or `locally_qualified` class stops counting toward landing. The first release that ships PR3 and PR4 only records the class. PR7 enforces it in the next release.
- **Q2: yes.** For npm-shipped CLIs, the node interpreter's real-path sha256 is part of the qualification key.
- **Q3: strict.** A harness with no verifiable upstream digest (today grok and opencode) is never promoted. It stays first-use only, and its shipped list stays empty.
- **Q4: manual submission in v1.** The operator attaches the exported record to a PR or an issue. There is no watcher-driven promotion PR.
- **Q5: requalify every listed member of every harness at each release cut.**

## Changes
The PR sections in (e) list every file. The new entities are:
- `cli_qualification.py`: `QualificationKey`, `Adapter`, `ADAPTERS`, `ensure_admitted`, `Store`, `export`
- the five `seat_cli_*` notice codes
- the `phase-loop cli-qualification` CLI
- catalog v2

No existing notice code is renamed or removed.

**Vocabulary.** `_HARNESS_DETAIL_CODES` (`panel_invoker.py:2824`) is a closed allowlist. Its agy block (around l.2858-2866) reads `"agy_image_unqualified", … "gemini_heartbeat_self_qualification_failed", … "gemini_heartbeat_platform_unsupported"`. This plan **adds** the five `seat_cli_*` codes to it, and they are pinned by `tests/test_cli_qualification_contract.py`. That is new vocabulary, introduced deliberately. No existing entry changes.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`: add the generic section (PR2), cross-link agy's (PR5) and add the promotion trust model (PR6).
- `docs/releases/outside-agent-release-handoff.md`: drop the upstream-pass criterion (PR1).
- `docs/ops/cli-qualification-promotion.md`: new, for the promotion runbook (PR6).
- `docs/ops/agy-upstream-watch.md`: note that upstream drift is advisory (PR1).
- `CHANGELOG.md`: one entry per PR.

## Dependencies & order
- PR1 is independent. Land it first.
- PR2 → PR3 → PR4.
- PR5 needs PR2 and a release cut.
- PR6 needs PR2 and PR5, because the agy route must be on the contract before catalog v2.
- PR7 needs PR3 and PR4 to have shipped in one release that only records the class (ruled, Q1).
- PR1's `agy_integrity` change and PR5 both touch agy admission. PR5 must keep PR1's local-admission cell green.

## Execution Policy
- execute: effort=high, reason=process ownership, store integrity and a trust boundary for promotion. PR1 alone: effort=medium.

## Verification
Run from `phase-loop-runtime/`:

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_verify_qualified_agy_route_core.py tests/test_qualified_agy_image_set.py  # 37 passed on origin/main 0840936d
PYTHONPATH=src python3 -m pytest -q tests/test_agy_self_qualification.py tests/test_seat_notices.py tests/test_agy_static_integrity.py
PYTHONPATH=src python3 -m pytest -q tests/test_cli_qualification_contract.py tests/test_cli_qualification_seat_route.py tests/test_agy_integrity_local_admission.py  # new per PR
python3 scripts/verify_qualified_agy_image.py --route-core
python3 scripts/verify_qualified_agy_image.py --source-only   # release-cut PRs (PR5) only
```

Live checks:
- **PR3, PR4 and PR5** each need one real first-use run per harness on a qualified host: `phase-loop cli-qualification run --harness <h>`, then `status`. The PR body records the actual result of each operation.
- **PR6:** run `export` and validate the record against the schema.

automation.suite_command: `cd phase-loop-runtime && PYTHONPATH=src python3 -m pytest -q tests/test_verify_qualified_agy_route_core.py tests/test_qualified_agy_image_set.py tests/test_agy_self_qualification.py tests/test_seat_notices.py`

## Acceptance criteria
- [ ] A newer upstream agy leaves the nightly `upstream` job green with a `::warning::`. `publish-pypi.yml`'s `--source-only` step is unchanged and blocking. (PR1)
- [ ] For every harness in the seat-fill set, a leg on a fresh host first-use qualifies and launches as `locally_qualified`. A failed or changed key refuses with a `seat_cli_*` code and `MODE_DEGRADED`, never `sealed`. (PR3, PR4)
- [ ] An existing agy v1 `qualified` entry admits after migration with no live run, and a tampered one does not. (PR5)
- [ ] A catalog member is added only if CI re-verifies its launcher hash against the upstream artifact and finds a committed release-lane record. An exported host record contains only schema-whitelisted fields. (PR6)
