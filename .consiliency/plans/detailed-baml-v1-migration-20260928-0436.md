# Detailed plan: migrate BAML v0 (baml-py 0.222) to BAML v1 0.20.1 (baml-bridge)

Tracking issue: agent-harness#1135. Evidence lives in the issue body and in three comments: the D1a addendum, the round-1 addendum and the **round-2 worker addendum**. Spike dir: `/mnt/workspace/spikes/baml-v1`, worker prototype in `worker_proto_r3/`. This plan cites that evidence and does not repeat it.

**Revision 3 changes the mechanism.** The v1 runtime is a process-global singleton, and in revision 2 it lived inside our process. That single fact is the root of four round-2 blockers:
- codex 1: fingerprint forgery;
- codex 2: foreign BAML runs before the ownership check, so `os._exit(1)` is reachable;
- grok 3: a poisoned pytest process;
- claude B1 / grok 4: the runtime sees the whole environment.

In revision 3, **the v1 runtime runs only in a dedicated worker subprocess that only we start.** This still honours D2: the runtime is built in memory from our sources, with no codegen. Revision 3 also closes the other round-2 blockers: the full closeout envelope, `injection.py` under failure, parse narrowing, the fmt/Jinja question, and the plan-text contradictions.

## Task

Replace the `baml-py>=0.222,<0.223` dependency of `phase-loop-runtime` with BAML v1 0.20.1, which is `baml-bridge==0.20.1` (import name `baml_bridge`). Move the `.baml` sources and `baml_modular.py` to the v1 language and runtime. Every public behavior of `phase_loop_runtime.baml_modular` is either preserved or listed in the **divergence register** with a disposition and a pin.

## Research summary

- **Paths that touch the runtime:**
  - `discovery.py` calls `parse_baml_response("EmitPhaseCloseout")`. This is the closeout parse.
  - `evidence_audit.py` calls `build_baml_request("EvaluateSuspectedFakeEvidence")`. This is tier 3.
  - Under D1, `injection.py` calls `build_baml_request("EmitPhaseCloseout")` to build the launch prompt.
  - Schema export, class-name parses and `render_baml_prompt` remain regex over the `.baml` text.
- **Pre-render is already wired.** `_read_baml_files()` returns `render_baml_prompt(text, taxonomy)` for every file. This refutes the r1 "placeholder wiring hole".
- **fmt and check on raw sources pass.** The raw sources still carry `{{ allowed_* | join(', ') }}` inside the backtick prompt, and both `baml fmt` and `baml check` pass on them. `fmt` is idempotent and leaves the placeholders alone (round-2 addendum §6). The E0001 cited against this in round 2 is the uncalled `${ctx.output_format}`, not `{{ }}`.
- **v1 API:**
  - `BamlRuntime.initialize_runtime(root, files)` is a virtual-root, process-global singleton.
  - `Fn@spec(k = v, …).parse()` and `.build_request()` replace `parse_llm_response` and `build_request_sync`.
  - `define_function("user.<fn>", "sync", params)` runs the bridge functions, which return only `map<string, string>`, so no typemap is needed.
- **Parity measured against real v0 on main, through the worker** (round-1 and round-2 addenda):
  - Evidence request: equal on every field.
  - Closeout request envelope (url, method, headers, body keys, `model`, message role and content type): **equal**. Only the prompt text differs, by D1.
  - Parse corpus (94 inputs): **93 identical**, 1 disclosed.
  - Schema dump: equal.
- **v0's `_filtered_env()` filtered nothing.** It is `{k: v for k, v in os.environ.items() if v is not None}`, and `os.environ` values are never `None`. So v0 handed the entire environment to the runtime. On our paths, v1 0.20.1 reads none of the probed provider or BAML variables, even in-process.
- **v0 name acceptance, measured:**
  - `parse_baml_response`'s runtime branch rejected every function name except `EmitPhaseCloseout`. It coerced every result to `PhaseLoopCloseoutV1`, so `EvaluateSuspectedFakeEvidence` failed validation and `NoSuchFunction` reported "not found".
  - `build_baml_request` accepted exactly the two declared functions, `EmitPhaseCloseout` and `EvaluateSuspectedFakeEvidence` (the latter is the live tier-3 path, row #3). It rejected `NoSuchFunction` and the class name `DotfilesAdoptionManifest`.
  - The v1 bridge table of those same two functions is therefore parity, not narrowing.
- **CI installs with `pip install "./phase-loop-runtime[visual]"`** (`test.yml:315`). Pyproject bounds are enforced there; `uv.lock` is advisory.

## Frozen public surface

`build_baml_request`, `parse_baml_response`, `export_function_schema`, `inject_schema_description`, `render_baml_prompt`, `BamlValidationError`, `PhaseLoopCloseoutV1`, `BamlRequest`, `ParsedResponse` keep their signatures, return shapes and failure type (`BamlValidationError`). The only permitted changes are the rows of the register. `protocol.md` (both copies) names only these symbols, and its schema-hash promise (around line 1341 / 1418) is kept by D1a, so it needs **no edit and gains no new vocabulary**. Exception message text is not contractual; tests assert types.

## Worker contract (replaces revision 2's in-process ownership contract)

- **New module `phase_loop_runtime/_baml_worker.py`.** It is a standalone script that imports only the stdlib plus `baml_bridge`, never `phase_loop_runtime`.
  - It serves a **fixed** operation table: `init`, `parse_closeout`, `closeout_request`, `evidence_request`. It never runs a caller-named function; there is no arbitrary-invoke op in production.
  - Protocol: one JSON object per line. Requests go in on stdin. Responses go out on a dup of fd 1, taken before fd 1 is redirected to stderr, so native prints cannot corrupt the protocol.
  - Each request carries a sequence `id` that the response echoes. On a mismatch the client treats the stream as desynchronized and raises the typed error.
  - Every exception inside an op, including `BamlPanic`, is caught in the worker and returned as `{"id", "fingerprint", "fault": "<module.Class>: <msg>"}`. The worker stays up.
  - `KeyboardInterrupt` and `SystemExit` inside the worker end it.
  - An op before `init` returns a `fault`. "Call before init" cannot happen through the client, but a protocol test pins the fault anyway.
- **Launch.** `subprocess.Popen([sys.executable, "-I", <path of _baml_worker.py>], stdin=PIPE, stdout=PIPE, stderr=<temp file>, env=_worker_env(), close_fds=True)`, where `-I` makes Python ignore `PYTHON*` variables and the user site.
  - The `init` message carries the parent's `sys.path`, so `baml_bridge` resolves exactly as it would in the parent, together with the **rendered** file map.
- **`_filtered_env()` is restored to a real role, renamed `_worker_env()`.**
  - It is an **allowlist**: `PATH=os.defpath` (not the parent's `PATH`), plus `SYSTEMROOT`, `WINDIR`, `TMPDIR`, `TMP` and `TEMP` when they are set. The `SYSTEMROOT`/`WINDIR` pair is needed for Python to start on Windows; the `TMP*` variables are for temp files.
  - **It excludes everything else**, including `HOME`, `BAML_*`, `BOUNDARY_*`, `OPENAI_*`, `ANTHROPIC_*`, any `*_API_KEY`, `PYTHON*`, proxy variables and locale variables.
  - Spike: the worker runs and parses with `PATH` only.
- **Ownership comes from process isolation.** Only our client can write to the worker's stdin, and the worker loads exactly the map it is sent.
  - As a further check, `fingerprint = sha256(canonical JSON of the RENDERED file map)`. The worker computes it from the map it actually loaded, and it echoes it on every response. The client compares it with its own hash of the map it sent.
  - This fixes codex 1 and N5: the hash covers the rendered bytes, including the taxonomy context, and it cannot be embedded in the source.
  - The BAML-side fingerprint function from revision 2 is removed.
- **Client (`baml_modular._BamlWorkerClient`).**
  - It lives in one module-level slot guarded by `threading.Lock`. One request at a time; the lock is held for the whole round trip.
  - It is started lazily on the first BAML call, so a process pays the ~0.8 s cold start once. A pid check makes it fork-safe: if `os.getpid()` differs from the pid that started the worker, the slot is dropped **without** touching the inherited pipes, and a new worker starts (N4).
  - Responses are read by a reader thread into a queue, with a per-request timeout (60 s). There is no `select`, so it is portable to Windows.
  - At `atexit`, the client closes stdin and waits up to 5 s, then kills. The worker also exits on stdin EOF when the parent dies.
- **Failure semantics.** Any of the following raises `BamlValidationError` carrying the rc and a sanitized tail of stderr:
  - the worker exits before or during a request, or a write raises `BrokenPipeError`;
  - EOF, a timeout (the worker is killed), a wrong `id`, a wrong fingerprint, a response shape other than exactly `{id, fingerprint, ok|error|request|fault}`, or a `fault`.

  After any of these, the slot is **discarded**, and the next call lazily starts a fresh worker.
  - **No automatic retry of a request.** A pre-send liveness check that finds a dead worker raises for *this* call, so the death is always reported once, and the next call restarts.
  - Measured: the `os._exit(1)` hook fires after the top-level call returns, about 138 ms later. That call's already-computed result is returned, and the death surfaces as the typed error on the next call. SIGKILL mid-call and timeout surface on the current call.
  - A `KeyboardInterrupt` in the parent while waiting kills and discards the worker, so a late response can never be read by the next request, and is then re-raised unmapped.
- **The parent never imports `baml_bridge`.** No hooks, no `atexit(shutdown_runtime)` and no process-global runtime ever exist in our process. That closes codex 2, grok 3, N1 and N4 by construction.
  - After a full public call, `'baml_bridge' not in sys.modules` is a tripwire.
  - A worker killed by the `os._exit(1)` hook, or by anything else, cannot take the caller down.
- **Latency** (round-2 addendum §1):
  - cold start (spawn, import, init) about 755–839 ms, once per process;
  - `parse_closeout` median 2.75 ms, p95 4.3 ms;
  - `closeout_request` median 3.5 ms; the first request after start is 5.5–5.7 ms.
  - v0: closeout prompt build 60 ms first, 0.9 ms after; closeout parse 27 ms first, 0.86 ms after.
  - **Launch path:** the first launch in a runner process gains about 0.8 s. Later launches in that process gain about 3 ms each.

## Divergence register (every v0→v1 difference found; each has a disposition and a pin)

| # | Divergence | Disposition | Pinned by |
|---|---|---|---|
| 1 | Evidence request role `system` instead of `user` | **Neutralized**: `${role("user")}` | evidence golden (full request) |
| 2 | `baml-original-url` header dropped | **Neutralized**: `EvidenceAuditClient … headers = {"baml-original-url": "https://example.invalid/v1"}` | evidence golden |
| 3 | Tier-3 prompt/body drift (dedent, output format, options, message count, content shape) | **Neutralized, measured equal** for 3 sentinel payloads, with a distinct sentinel per argument (N10) | evidence golden (3 payloads) |
| 4 | Closeout loop layout (no blank lines between items) | **Accepted (D1)** | prompt-byte refresh |
| 5 | Closeout output-format block (`{ field: type }` replaces the per-field list with enums) | **Accepted (D1)**. Enums remain in the contract prose and in the D1a block | refresh; test: every taxonomy literal appears in the prompt |
| 6 | Schema-description block absent from v1 | **Neutralized (D1a)**: Python appends it; tail byte-identical | D1a test |
| 7 | Extra payload key raises in v1 | **Neutralized**: filter to signature params | test |
| 8 | Missing payload key raises `BamlError` in v1 | **Neutralized**: `BamlValidationError` before the worker is called | test |
| 9 | `closeout_commit_sha=""` renders empty | **Neutralized**: v0 normalization (`or None`, lists `or []`, items `str()`) | test |
| 10 | Backslash in a closeout list value: v0 raises `re.error` (bug); v1 renders it literally | **Accepted (fix)** | test |
| 11 | `${…}` / `{{…}}` / `{%…%}` in caller values | **Parity, measured** (literal in both) | test |
| 12 | Parse: int > i64 is clamped in v0, `null` in v1 | **Accepted** (optional field; the gate decodes the image) | parse-corpus golden (entry flagged) |
| 13 | `BamlPanic` (`BaseException`) and in-BAML panics (`BamlError`) | **Contained in the worker**: returned as `fault`, raised by the parent as `BamlValidationError`; the worker survives | real tests: broken source at init; in-BAML panic |
| 14 | Process-global runtime, `atexit(shutdown_runtime)`, and the irreplaceable `os._exit(1)` spawn hook | **Isolated**: all of it lives only in the worker; the parent never imports `baml_bridge`; worker death gives a typed error and a lazy restart | real subprocess-death tests; `sys.modules` tripwire |
| 15 | Environment visible to the runtime: v0 got the **whole** env (its filter dropped nothing) | **Tightened**: the worker gets `_worker_env()` (allowlist above). Measured: v1 reads none of the probed variables even with the full env, so no output changes | env-sentinel test (below) |
| 16 | First-call latency ~0.8 s per process (v0 27–60 ms); ~3 ms per call after | **Accepted**, disclosed | test: a second call in the same process reuses the worker (same pid) and takes < 250 ms; the cold-start measurement is printed in the verification log |
| 17 | New transitive `protobuf` | **Bounded**: `protobuf>=6.31.1,<8` | dependency test |
| 18 | baml-py's `baml` / `baml-cli` console scripts are no longer installed | **Accepted**, disclosed | tripwire test: `git grep -nE '\bbaml(-cli)?\b (generate\|init\|test\|fmt\|check)'` over `ci/`, `.github/`, `phase-loop-runtime/scripts` and `install-agent-harness.sh` finds nothing; `shutil.which` is not asserted, because an unrelated install may provide one |
| 19 | Exception message text | **Accepted**, not contractual | test assertions check the type only: a grep tripwire over the new test file forbids `assertRaisesRegex` / `match=` on `BamlValidationError` |
| 20 | `BamlRequest.id`: v0 random `breq_…`, v1 `None` | **Accepted**. `git grep` finds no consumer | evidence and closeout goldens exclude `id`; test `id is None` |
| 21 | Closeout request **envelope** (url, method, headers, body keys, `model`, message role and content type) now comes from `PhaseLoopCloseoutClient` instead of Python | **Parity, measured equal** (2 payloads) | Step 0 closeout-request golden (all 5 payloads, every field except `id` and the prompt text) |
| 22 | `injection.py` when the worker fails: **v0 swallowed `BamlValidationError`** and launched with a one-line fallback ("BAML prompt render failed: …"), i.e. without the closeout contract | **Changed on the lead's instruction**: remove the fallback, so `BamlValidationError` propagates out of `build_prompt_bundle` / `build_lane_prompt_bundle`. The runner's `build_prompt(...)` call sites (around `runner.py` lines 3312, 5253 and 5961) sit before any child is spawned, so no launch happens. **Observed outcome on main, by code reading:** nothing between `run_loop`'s `build_prompt` call (runner.py around line 3312) and the CLI catches it. `run_loop` has only narrow handlers (`DispatchLockContention` around line 1488, and `ValueError`/`Exception` around lines 1318–1381 that run before dispatch), and `cli._main` calls `run_loop` (cli.py around line 1852) with no handler. So `phase-loop run` exits non-zero with the `BamlValidationError` traceback, and the dispatch lock is released by its context manager. No blocked record is written; that is acceptable for "fail typed, no launch" and is disclosed. **Disclosed as a behavior change** in the CHANGELOG | test: with the worker failing (init fault, killed, timeout), `build_prompt_bundle` raises `BamlValidationError` and returns no `PromptBundle`. Runner-level test: `run_loop(...)` raises `BamlValidationError`, the executor launch entry point (patched with a pass-through spy) is never entered, and no executor process is spawned |
| 23 | Names outside the bridge table. `parse_baml_response`: every name except `EmitPhaseCloseout`. `build_baml_request`: every name except `EmitPhaseCloseout` and `EvaluateSuspectedFakeEvidence` | **Parity**: v0 raised `BamlValidationError` for exactly these names ("function … not found", or coercion failure for `parse_baml_response("EvaluateSuspectedFakeEvidence")`). v1 raises `BamlValidationError("no v1 bridge for <fn>")` for the same set | Step 0 captures v0 for `parse_baml_response("EvaluateSuspectedFakeEvidence", …)`, and for `NoSuchFunction` and `DotfilesAdoptionManifest` on both functions; test requires `BamlValidationError` |

## Decisions (all decided)

- **D1 (maintainer):** v1 renders the closeout prompt, and its bytes change. My recommendation was otherwise. The Python renderer set is deleted: `_build_emit_phase_closeout_request`, `_render_emit_phase_closeout_prompt`, `_render_baml_list_loop`, `_function_prompt_template`, `_closeout_output_format`, `_schema_type_label`.
- **D1a (lead, under D1):** Python appends `"\n\n" + _render_schema_description(export_function_schema("EmitPhaseCloseout"))` to `BamlRequest.prompt` and to `body["messages"][0]["content"]`. The role is set in BAML. The prompt text is taken from the built request via `_extract_prompt`. `schema_sha256` hashes the canonical schema JSON, not source text, so it stays `77e72437…`.
- **D2:** in-memory runtime from our sources, with no codegen, **run in the worker subprocess**. The worker is required, not optional: it is the mechanism that makes ownership, env isolation and hook containment hold by construction.
- **D3:** a dual-form `_class_fields` using the stricter regex `([A-Za-z_]\w*)(?:\s*:\s*|\s+)([A-Za-z_]\w*(?:\[\])?)(\?)?\s*,?` with fullmatch (N2). Sources are `baml fmt`'d, and a CI fmt round-trip runs on the RAW sources, which spike §6 shows can pass.
- **D4:** hard switch. Step 0 is mandatory.
- **D5:** hash-enforced install stays out of scope. Instead, `protobuf>=6.31.1,<8`. The floor is baml-bridge's gencode `ValidateProtobufRuntimeVersion(6, 31)`. The spike loads and parses cleanly under `-W error` on 6.31.1 and 7.36.2. The repo has no pytest `filterwarnings` config (`git grep` is empty). The other direct dependency, `typing-extensions>=4.14.0`, is already satisfied by pydantic 2 and is not pinned here.
- **D6 (maintainer accepted the canary):** exact `==0.20.1`. The CHANGELOG discloses:
  - the worker process and its latency;
  - the hooks confined to the worker;
  - the protobuf window;
  - the platforms that were not load-tested;
  - rollback: revert to `baml-py>=0.222,<0.223` and cut a patch release.

## Step 0: capture the v0 baselines on main BEFORE the switch

- **Script.** `phase-loop-runtime/tests/data/baml_v0_baseline/capture_v0.py` runs one time, in a baml-py 0.222.0 venv against a clean `origin/main` worktree. It is not collected by pytest, and a provenance header records the main SHA and the baml-py version. It writes:
  - `parse_corpus.json`: input → full `ParsedResponse.payload` or `"BamlValidationError"`.
    - Inputs: the 30 synthetic cases from the round-1 addendum, plus every `tests/fixtures/**.json` and `tests/data/*closeout*` file that contains `"terminal_status"`.
    - Plus the #23 names: parse for `EvaluateSuspectedFakeEvidence` with an evidence payload and with a closeout payload, and `NoSuchFunction`.
  - `evidence_requests.json`: 3 payloads, each with a **distinct sentinel per argument** (N10), plus edge values → the full v0 `BamlRequest`, minus `id`.
  - `closeout_requests_v0.json`: the payloads `empty`, `two_gates_sha`, `two_gates_nosha`, `sentinels` and `sha_empty` → the full v0 `BamlRequest`, minus `id`.
    - It records url, method, headers, the whole body (including `model`), and the message roles and content types, plus the prompt text and its sha256.
    - `backslash` is recorded as `re.error`.
    - `build_baml_request` for `NoSuchFunction` and `DotfilesAdoptionManifest` is recorded as `BamlValidationError`.
  - `schema_dump.json`: `_class_fields` for every class, `export_function_schema` for every class and PascalCase function, and `_enum_literal_map`.
- **First commit** of the implementation PR: `test(baml-v1): capture v0 baselines (agent-harness#1135)`. These files are never regenerated after the switch.

## Changes

### `phase-loop-runtime/pyproject.toml` (modify)
- `dependencies`: replace `"baml-py>=0.222,<0.223"` with `"baml-bridge==0.20.1"` and `"protobuf>=6.31.1,<8"`. The package-data glob `baml_src/*.baml` already ships the bridge file, and `_baml_worker.py` is a normal module.

### `phase-loop-runtime/uv.lock` (modify)
- Run `uv lock`. Check that the baml-bridge wheel hashes equal the PyPI digests in agent-harness#1135. The lock stays advisory (D5).

### `baml_src/emit_phase_closeout.baml` (modify)
- `client PhaseLoopCloseoutClient = openai.GenericClient.new(model = "phase-loop-closeout", base_url = "https://example.invalid/v1");`. The #21 envelope was measured equal with exactly this client.
- `EmitPhaseCloseout` becomes:
  - `client:`
  - ``prompt: `${role("user")}` …``
  - `${phase_alias}`
  - `${xs.map((g) -> { "- " + g }).join("\n")}` for each list
  - `${closeout_commit_sha ?? "none"}`
  - `${ctx.output_format()}`

  The taxonomy `{{ allowed_* | join(', ') }}` placeholders stay; they are pre-rendered.
- `PhaseLoopCloseoutV1` moves to `name: type,`. Comments and enum-literal blocks stay byte-identical.

### `baml_src/evaluate_suspected_fake_evidence.baml` (modify)
- `client EvidenceAuditClient = openai.GenericClient.new(model = "phase-loop-evidence-audit", base_url = "https://example.invalid/v1", headers = {"baml-original-url": "https://example.invalid/v1"});`
- `EvaluateSuspectedFakeEvidence`: `client:`, ``prompt: `${role("user")}` …``, `${arg}` and `${ctx.output_format()}`.
- `EvidenceJudgment`: D3 syntax.

### The other six `.baml` files (modify; D3 syntax only)
- Run `baml fmt` on them. The enum-literal comments stay byte-identical, and the schema dump must equal Step 0.

### `baml_src/phase_loop_bridge.baml` (create; new host-glue logic)
- `phase_loop_parse_closeout(raw: string) -> map<string, string>` calls `EmitPhaseCloseout@spec(phase_alias = "", plan_produces = [], plan_owned_files = [], closeout_commit_sha = null).parse(raw)`. It catches `baml.errors.ParseError` and returns `{"error": msg}`; otherwise it returns `{"ok": baml.json.to_string(v)}`.
- `phase_loop_closeout_request(...)` and `phase_loop_evidence_request(...)` return `{"request": baml.json.to_string(<Fn>@spec(<args by keyword>).build_request())}`.
- The file has no `class` and no `spawn`. It contains no fingerprint; the worker adds that.
- **Spike-verified as written** (`planned2/`): 93 of 94 in the corpus, evidence equality, closeout envelope equality.

### `phase-loop-runtime/src/phase_loop_runtime/_baml_worker.py` (create)
- The worker script from the worker contract. It is ported from `worker_proto_r3/_baml_worker.py` and adds sequence ids and the fixed op table.

### `phase-loop-runtime/src/phase_loop_runtime/baml_modular.py` (modify)
- **Add** `_BamlWorkerClient`, `_worker_env()` (the allowlist; this is `_filtered_env` renamed and given a real job), a module slot plus lock, `_worker_call(op, args)`, and `_reset_worker_for_tests()`.
  - `_reset_worker_for_tests()` terminates and discards the worker. Any test that uses non-packaged sources calls it in teardown, so the pytest process is never poisoned (grok 3).
- **Add** a single-sourced reader. `_read_baml_files()` renders with the taxonomy and fails closed if `{{` or `{%` remains; this is the template check that replaces any output check (codex 3, B6). The fingerprint is computed by the client over this rendered map.
  - The **raw-read seam** is `_read_raw_baml_files()`. Tests that inject a broken or hostile source patch that seam, which fixes the N6 naming.
- **`build_baml_request`:**
  - Look up the function in a bridge table (`EmitPhaseCloseout`, `EvaluateSuspectedFakeEvidence`). Anything else raises `BamlValidationError` (#23).
  - Filter and require the payload (#7, #8), then normalize the closeout payload (#9).
  - Call `closeout_request` or `evidence_request` with keyword args.
  - Build `BamlRequest(id=None, url, method, headers, body=json.loads(body), prompt=_extract_prompt(body))`.
  - For `EmitPhaseCloseout`, add D1a to both the prompt and `messages[0].content`.
  - Delete the D1 renderer set.
- **`parse_baml_response`**, runtime branch:
  - A name other than `EmitPhaseCloseout` raises `BamlValidationError` (#23).
  - Otherwise call `parse_closeout`. `error` maps to `BamlValidationError`; otherwise run `PhaseLoopCloseoutV1.model_validate(json.loads(ok))`, and a pydantic failure maps to `BamlValidationError`.
  - The class-name branch is unchanged.
- **`_class_fields`:** the D3 regex.
- **Delete** `_runtime`, `_type_modules`, `_is_pyo3_panic` and the D1 renderers. `_raise_baml_validation_error` / `_sanitize_error` stay, since they are used for worker faults.

### `phase-loop-runtime/src/phase_loop_runtime/injection.py` (modify; #22)
- `_render_baml_closeout_instruction`: delete the `except BamlValidationError` fallback, so the error propagates. The remaining `include_schema_description=False` marker cut is unchanged, and D1a keeps it meaningful.

### `phase-loop-runtime/scripts/_gate_a_probe.py` (modify; release-notes (f))
- **Replace** the `baml_py` resolution block (around line 44) with: `importlib.metadata.version("baml-bridge") == "0.20.1"`, followed by a real `parse_baml_response("EmitPhaseCloseout", <valid>)` through the worker. It then asserts that `baml_bridge` is not in the probe's `sys.modules`.
- This probe runs in the PR wheel smoke and in Gate A. It is a script, so it is outside the agy pin set.

### `.github/workflows/publish-pypi.yml` (modify; release-notes (f))
- In the release-wheel smoke heredoc (around line 93), add the same version assertion and a real parse through the worker.

### `.github/workflows/test.yml` (modify; D3 and release-notes (e))
- New job `baml-sources`: `ubuntu-latest`, Python 3.12, `pip install ./phase-loop-runtime`. Steps:
  1. Download `baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz`.
  2. `sha256sum -c` it against the published `.sha256` **and** against the literal `6067729f14483eca4ab61bfcd3c1921818e9ecc66da035bc64fbbfeb850e2795`.
  3. Check that `baml-cli --version` is `baml-cli 0.20.1`.
  4. Run `(cd phase-loop-runtime/src/phase_loop_runtime && baml-cli --agent-skill-check off fmt baml_src/*.baml)`, then `git diff --exit-code`. This works on the raw sources (spike §6).
  5. Copy the raw sources into a temp project with a minimal `baml.toml` and run `baml-cli check`. Then write the rendered `_read_baml_files()` map to a second temp project and `check` that too. Both runs must print `Finished checked 9 file(s)`, asserted with `grep -q` (the elapsed-time suffix varies).
- The job has no `if:`. Add it to the `gate` job's `needs`, add `BAMLSRC: ${{ needs.baml-sources.result }}`, and make the gate `exit 1` unless that result is `success`. `gate` runs `if: always()`, and a skipped job satisfies a required check, so this explicit check is what makes the job blocking.

## Tests

New file: `tests/test_phase_loop_baml_v1_runtime.py`. It uses the real worker and real runtime with no stubs. Any test that swaps sources calls `_reset_worker_for_tests()` in teardown.

- **Parity against the Step 0 goldens:**
  - the parse corpus is identical except the flagged `pix_2p70`, which is asserted `null`;
  - the evidence request (#1–#3) and the closeout request envelope (#21) equal their goldens on every field except `id` and the closeout prompt;
  - `id is None` (#20);
  - the #23 names raise `BamlValidationError`;
  - payload handling (#7–#9) and the edge values (#10, #11) behave as registered.
- **Closeout D1/D1a:**
  - the refreshed prompt goldens match;
  - the marker appears exactly once;
  - `schema_sha256` equals the export;
  - there is a single user message whose content equals the prompt, with no leading `[`;
  - every taxonomy literal appears in the prompt (#5).
- **Schema dump:** equals Step 0.
- **Environment** (#15): run in a subprocess whose parent env sets distinct sentinels for `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `ANTHROPIC_API_KEY`, `BAML_LOG`, `BAML_TRACE`, `BAML_HOME`, `BOUNDARY_API_KEY`, `BOUNDARY_PROJECT_ID`, `HOME` and `HTTPS_PROXY`. Then check:
  - both `BamlRequest`s equal their goldens;
  - no sentinel appears in url, headers, body or prompt;
  - the worker's own environment (read through a protocol-test `init`) has only allowlisted keys;
  - the worker's stderr and the child's stdout and stderr are empty.
- **Worker death is always a typed error, the parent survives, and a restart follows.** Each of these runs in a subprocess and must exit 0:
  - **The spawn hook:** the patched raw-read seam supplies a hostile `phase_loop_bridge.baml` whose `phase_loop_parse_closeout` runs `spawn with baml.spawn.options(detach = true) { throw baml.errors.Io { … } }`. Call 1 returns; its result was fully computed before the hook fired (measured about 138 ms after return). Wait up to 5 s for the worker to exit with rc 1. Call 2 raises `BamlValidationError` mentioning rc 1. The no-retry rule guarantees that a lazy restart cannot hide the death. Call 3 succeeds on a new worker pid.
  - **SIGKILL mid-call:** a hostile bridge sleeps via `baml.sys.sleep`, the worker is killed after 0.5 s, and the current call raises `BamlValidationError`.
  - **Timeout:** with a test-sized timeout, the call raises `BamlValidationError` and the worker is gone.
  - **Broken source at init:** a `fault` becomes `BamlValidationError` at both public entry points.
  - **An in-BAML panic** becomes `BamlValidationError`, and the worker stays usable.
  - **Protocol op before `init`:** a `fault`.
  - **A wrong fingerprint:** the client is handed a map different from the one the worker loaded, and the call raises `BamlValidationError`. This is codex 1's counterexample: changing only the evidence prompt changes the rendered-map hash.
- **`KeyboardInterrupt`:** a *separate* subprocess test (fixing the r2 contradiction) sends SIGINT to the parent while it waits. The test requires the process to exit through an unmapped `KeyboardInterrupt` traceback, the worker to be killed, and no `BamlValidationError` to be printed.
- **Concurrency:** 8 threads start from a cold slot. Exactly one worker pid is started. All 8 results equal a single-threaded parse of the same input. The test has a 60 s timeout (N3).
- **Fork:** after the first use, `os.fork()`. The child's call starts its own worker (a different pid), and the parent's worker is untouched and still answers.
- **Launch path (#22):** under each worker failure mode, `build_prompt_bundle` raises `BamlValidationError`. A runner-level test using the existing runner test utilities shows that a failing worker produces the typed error before any child launch, and that no executor process is spawned.
- **Latency (#16):** a second call reuses the same worker pid and completes in < 250 ms.
- **Tripwires:**
  - after a full public call, `'baml_bridge' not in sys.modules`;
  - no `\bspawn\b` in any packaged `.baml`;
  - `_read_baml_files()` output contains no `{{` or `{%`;
  - the #18 grep;
  - the #19 grep;
  - `_worker_env()` keys are a subset of the allowlist.
- **`tests/test_phase_loop_baml_dependency.py`:**
  - the pins become `"baml-bridge==0.20.1"` and `"protobuf>=6.31.1,<8"`;
  - `test_baml_py_imports_after_install` becomes `test_baml_bridge_loads_after_install`, unmarked, so it runs on every pytest lane. It checks the installed version and does a real parse through the worker;
  - the packaged list gains `phase_loop_bridge.baml` and `_baml_worker.py`.
- **`tests/test_phase_loop_baml_modular.py`:** the pyo3-panic fake test is **replaced**, and the replacement is disclosed, by the worker panic and death tests. The prompt-text assertions in this file are listed in the refresh commit.
- **Prompt-text tests that change under D1**, re-baselined only in the refresh commit, with each edited assertion listed there:
  - `test_phase_loop_baml_modular.py` (prompt assertions only);
  - `test_phase_loop_schema_flow.py`;
  - `test_phase_loop_closeout_owned_dirty_fallback.py`;
  - `tests/data/launchspec_golden/launchspec_golden.json`, via `test_launchspec_golden.py` and `test_executor_exited_without_closeout_785.py`.
- **Unchanged, and any red is a finding.** `test_phase_loop_baml_schema_export.py` belongs here, **not** in the D1 list (fixing the round-2 contradiction): schema export is D3 territory and must not move.
  - `test_phase_loop_baml_{end_to_end,injection,runner_closeout,schema_export,schema_source}.py`
  - `test_phase_loop_skill_baml_closeout.py`
  - `test_phase_loop_terminal_summary_mirrors_baml_closeout.py`
  - `test_phase_loop_{adoption_bundle,closeout_hardening,dotfiles_schemas,dotfiles_sources,evidence_audit,evidence_audit_tier3,plan_manifest,protocol_contract,runtime_projection,discovery,v22_e2e,v22_principles}.py`
  - `test_phase_loop_baml_prompt_taxonomy.py`
  - `test_gate_a_wheel_isolation.py`
  - If `test_phase_loop_baml_injection.py` asserts the removed #22 fallback text, that assertion moves to the #22 row and is disclosed.
- **Coverage rule:** diff `pytest --collect-only -q` between main and the branch.
  - No existing node may disappear without being listed as replaced, with the replacing node and a reason.
  - New nodes are listed.
  - Edited assertions are listed with the old and new text.

## Prompt-byte refresh (D1): one separate, reviewed commit

1. **Before.** Use the Step 0 `closeout_requests_v0.json` prompt hashes: empty `578144449b…afa15`, two-gates-sha `0097cdc81a…b6b5b4f`, two-gates-nosha `288057f433…277f6`, plus `sentinels` and `sha_empty`.
2. **After.** Compute the v1+D1a hashes and store them in `tests/data/baml_closeout_prompt_goldens.json`. The spike's two-gates-sha value was `b28df4b29c…127e33`, which is informative only.
3. **Diff for review.** The PR body carries `diff -u` for two-gates-sha. Every hunk must be #4 or #5, and the D1a tail must show no hunk. The envelope (#21) must show no difference.
4. **Launchspec golden.**
   - Regenerate with `PYTHONPATH=src:tests PHASE_LOOP_REGEN_LAUNCHSPEC_GOLDEN=1 python -m pytest -q tests/test_launchspec_golden.py`, then run it again without the variable.
   - The diff is confined to the embedded closeout-prompt strings, with `schema_sha256: 77e72437…` unchanged.
   - If the golden embeds envelope fields, they must not change (#21), so the "confined" rule is satisfiable and not blind.
5. **Other consumers of the prompt bytes:**
   - the `injection.py` marker cut is kept by D1a;
   - `PromptBundle.body_sha256` / `context_sha256` are recorded per launch and compared only within a launch, so the drift across the upgrade is expected;
   - the skills cite names only;
   - tier 3 is unchanged (#3).

## BAML 0.20.1 release notes, item by item (https://boundaryml.com/blog/baml-0.20.1)

- **(a) Collector API removed.** We do not use it (`git grep -i collector` is empty), and the plan uses only bridges and `@spec`. No impact.
- **(b) Bigint as JSON number.** We have no `bigint` and no `match` on `baml.json.json`. The integers that cross are the three optional pixel fields. Spike parity holds for 12, 2^53+1, 5.0, 5.7, "42" and -1; 2^70 is #12.
- **(c) Streaming removed.** There is no `@stream` or `stream_types` anywhere. No impact.
- **(d) Empty or whitespace `HOME`/`BAML_HOME` treated as unset.** The worker receives neither variable (#15). The spike shows init and parse work with `HOME` empty, whitespace or unset, and under `env -i` / `PATH`-only.
- **(e) Update toolchain and bridge together.** The `baml-sources` job and verification step 2 enforce this: a sha-verified CLI whose version equals the bridge's `get_toolchain_version()`, both `0.20.1`.
- **(f) The 0.20.0 fingerprint failure hit all Linux wheels.** A real parse through the worker runs on every CI lane: pytest, wheel smoke, Gate A, and publish-pypi. It is not an import-only check. The 0.20.0 failure did not reproduce on our host.
- **Not applicable:** reflection, memory/GC, TypeScript, `baml agent install`.
- **Pin-bump checklist.** This is recorded in the CHANGELOG and applies to any future `baml-bridge` change: re-run the `baml describe` builtin `spawn` audit, the release-notes review, and Step 0-style parity. The worker keeps the hook harmless either way.

## Platforms

- **Verified:** x86_64 glibc (host 3.10 and 3.12, `python:3.10-slim`) and musl (`python:3.10-alpine`, `python:3.12-alpine`).
- **Pre-merge, and part of the acceptance criteria:** run verification step 3 once on GitHub-hosted `ubuntu-24.04-arm`, `macos-14`, `macos-13` and `windows-latest`, via a throwaway `workflow_dispatch` on an unmerged scratch branch. Record the results in the PR. A platform that cannot run is listed as unverified in the CHANGELOG, and that listing is itself the acceptance evidence.

## Documentation impact
- `CHANGELOG.md` `[Unreleased]` gets "BAML v1 0.20.1 (agent-harness#1135)", covering:
  - `baml-py` → `baml-bridge==0.20.1`, plus `protobuf>=6.31.1,<8`, which breaks environments pinned to `protobuf<6`;
  - **a BAML worker subprocess**: about 0.8 s cold start per process, about 3 ms per call after, an allowlist environment, and typed errors with lazy restart when it dies;
  - v1 source syntax;
  - the public API is unchanged;
  - **the closeout prompt text changed (D1)**; the envelope and the evidence request are unchanged;
  - **`injection.py` no longer launches with a fallback instruction when the closeout contract cannot be rendered (#22)**;
  - the fixed backslash crash (#10);
  - the pixel `null` (#12);
  - `baml` / `baml-cli` scripts are gone (#18);
  - platform coverage;
  - the pin-bump checklist;
  - rollback.
- `docs/reviews/2026-09-01-codebase-review.md`: none (historical). The CHANGELOG notes that C-8 is now covered by the D3 regex, the schema-dump test and the CI fmt round-trip.
- `protocol.md` (both copies), skills, READMEs and `docs/TEAM-ONBOARDING.md`: none. See the frozen-surface section; there are no BAML references elsewhere.

## Release and agy-requalification consequences
- **This PR** touches `phase_loop_runtime/**/*.py` (`baml_modular.py`, `injection.py` and the new `_baml_worker.py`), so it runs `--route-core` only. No requalification is needed here.
- **The next release cut** requalifies both agy images, because `source_sha256` covers all `phase_loop_runtime/**/*.py`, including the new worker.
  - The recipe: `qualify_gemini_heartbeat.py` (completion, cancel and owner-loss), then `--validate`, then regenerate the record, then `verify_qualified_agy_image.py --source-only`.
  - Budget for observer repair (agent-harness#1067).
  - Record the `baml-bridge` and `protobuf` versions in the release notes.
- **Recommendation to the lead, not decided here (N9).** D1 moves prompt layout out of `.py` into `.baml`, which the pin set does not cover. Consider adding `phase_loop_runtime/baml_src/*.baml` to `source_sha256` at the release cut, so a `.baml`-only prompt change still forces requalification. That changes the qualification tooling, so it belongs to the release cut, not to this PR.
- **Pre-merge, and part of the acceptance criteria:** run the recipe's cancel and owner-loss ops once on this branch. The worker is a child of the runner process, and this check confirms it neither blocks cancellation nor outlives its owner.

## Dependencies & order
1. **Step 0 baselines** first, captured on main.
2. Pin, protobuf bound and lock.
3. `.baml` migration, `fmt` and the bridge file, together with the D3 regex.
4. `_baml_worker.py` and the `baml_modular.py` worker client, bridges and D1/D1a, then the `injection.py` #22 change.
5. The probe, `publish-pypi.yml` and `test.yml`.
6. The new tests, then the **separate** refresh commit.
7. CHANGELOG.

Scope: 4 `.py` files (`baml_modular.py`, `injection.py`, the new `_baml_worker.py`, `_gate_a_probe.py`), pyproject and lock, 9 `.baml` files, 2 workflows, 1 new test file, and the Step 0 data plus goldens. This sits at the edge of the bounded-plan threshold, and the commits are split so each can be reviewed on its own.

## Verification
Run from `phase-loop-runtime/` in fresh venvs built from this tree, on py3.10 **and** py3.12. Nothing is stubbed.

```bash
# 1. CI-equivalent install; v0 gone; bridge/protobuf pinned; parent does not load baml_bridge.
python -m pip install "./[visual]" pytest
python -c "import importlib.util as u, importlib.metadata as md, sys; assert u.find_spec('baml_py') is None; assert md.version('baml-bridge')=='0.20.1'; import google.protobuf as pb; assert 6<=int(pb.__version__.split('.')[0])<8; from phase_loop_runtime import baml_modular as m; m.parse_baml_response('EmitPhaseCloseout', '{\"terminal_status\":\"complete\",\"verification_status\":\"passed\",\"dirty_paths\":[],\"produced_if_gates\":[\"G\"],\"required_human_inputs\":[]}'); assert 'baml_bridge' not in sys.modules"

# 2. Pinned, sha-verified CLI; fmt round-trip and check on RAW sources; check on rendered sources.
gh release download baml-language-0.20.1 -R BoundaryML/baml -p 'baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz*' -D /tmp/bamlcli
(cd /tmp/bamlcli && sha256sum -c baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz.sha256 \
  && echo "6067729f14483eca4ab61bfcd3c1921818e9ecc66da035bc64fbbfeb850e2795  baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz" | sha256sum -c - \
  && tar -xzf baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz)
export PATH=/tmp/bamlcli/bin:$PATH
test "$(baml-cli --version 2>/dev/null)" = "baml-cli 0.20.1"
(cd src/phase_loop_runtime && baml-cli --agent-skill-check off fmt baml_src/*.baml) && git diff --exit-code -- src/phase_loop_runtime/baml_src
rm -rf /tmp/bamlraw && mkdir -p /tmp/bamlraw/baml_src && cp src/phase_loop_runtime/baml_src/*.baml /tmp/bamlraw/baml_src/ && printf '[package]\nname = "bamlraw"\n' > /tmp/bamlraw/baml.toml
baml-cli --agent-skill-check off check --project /tmp/bamlraw 2>&1 | grep -q 'Finished checked 9 file(s)'   # RAW sources, placeholders included
python -c "from phase_loop_runtime import baml_modular as m; import pathlib; d=pathlib.Path('/tmp/bamlchk/baml_src'); d.mkdir(parents=True, exist_ok=True); [ (d/n).write_text(t) for n,t in m._read_baml_files().items() ]"
printf '[package]\nname = "bamlchk"\n' > /tmp/bamlchk/baml.toml
baml-cli --agent-skill-check off check --project /tmp/bamlchk 2>&1 | grep -q 'Finished checked 9 file(s)'

# 3. Real-worker parity, contracts, death, env, concurrency, fork, launch path.
python -m pytest -q tests/test_phase_loop_baml_v1_runtime.py tests/test_phase_loop_baml_dependency.py

# 4. Affected suites and the coverage-rule diff.
python -m pytest -q tests/test_phase_loop_baml_*.py tests/test_phase_loop_skill_baml_closeout.py tests/test_phase_loop_terminal_summary_mirrors_baml_closeout.py \
  tests/test_phase_loop_adoption_bundle.py tests/test_phase_loop_closeout_hardening.py tests/test_phase_loop_dotfiles_schemas.py tests/test_phase_loop_dotfiles_sources.py \
  tests/test_phase_loop_evidence_audit.py tests/test_phase_loop_evidence_audit_tier3.py tests/test_phase_loop_plan_manifest.py tests/test_phase_loop_protocol_contract.py \
  tests/test_phase_loop_runtime_projection.py tests/test_phase_loop_discovery.py tests/test_phase_loop_v22_e2e.py tests/test_phase_loop_v22_principles.py \
  tests/test_phase_loop_schema_flow.py tests/test_phase_loop_closeout_owned_dirty_fallback.py tests/test_launchspec_golden.py tests/test_executor_exited_without_closeout_785.py \
  tests/test_phase_loop_injection.py tests/test_gate_a_wheel_isolation.py
python -m pytest --collect-only -q > /tmp/nodes.branch   # compare with main; apply the coverage rule

# 5. Wheel ships 9 .baml + the worker; clean-venv probe.
python -m build --wheel
test "$(unzip -l dist/*.whl | grep -c 'baml_src/.*\.baml$')" = 9
unzip -l dist/*.whl | grep -q 'phase_loop_runtime/_baml_worker.py$'
bash scripts/gate_a_cleanroom.sh

# 6. musl, py3.10 and py3.12, no network after install.
for img in python:3.10-alpine python:3.12-alpine; do
  vol="bamlv1-$(echo "$img" | tr ':.' '--')"
  docker run --rm -v "$vol:/venv" -v "$PWD/dist:/d:ro" "$img" sh -c 'python -m venv /venv/v && /venv/v/bin/pip install -q /d/*.whl pytest'
  docker run --rm --network none -v "$vol:/venv" -v "$PWD:/w:ro" -w /w "$img" \
    /venv/v/bin/python -m pytest -q -p no:cacheprovider tests/test_phase_loop_baml_v1_runtime.py tests/test_phase_loop_baml_dependency.py
  docker volume rm "$vol"
done
```

## Acceptance criteria
- [ ] Step 0 baselines are committed first: captured on main with baml-py 0.222.0, with provenance, and including the full closeout `BamlRequest` for all 5 payloads.
- [ ] Verification steps 1, 3 and 4 pass on py3.10 and py3.12, and step 6 passes on `python:3.10-alpine` and `python:3.12-alpine`. That covers:
  - the parent never imports `baml_bridge`;
  - parity with every golden;
  - every register row's pin;
  - worker death (spawn hook, SIGKILL, timeout, init fault, panic) always gives `BamlValidationError` and a restart;
  - the env sentinels are absent and output is empty;
  - concurrency, fork, and the launch path failing typed (#22).
- [ ] The CI job `baml-sources` passes and is blocking through `gate`: sha-verified CLI 0.20.1, a zero-diff fmt round-trip on raw sources, and a check of 9 files on raw and rendered sources. The bridge load test is green on the pytest lanes, in the wheel smoke / Gate A probe, and in the publish-pypi smoke.
- [ ] The refresh is a separate commit. Its PR body carries the attributed v0→v1 diff, an unchanged envelope, the launchspec diff confined to the prompt strings with `schema_sha256: 77e72437…` unchanged, and the coverage-rule node diff with every replacement disclosed.
- [ ] Both pre-merge runs are recorded in the PR: the arm/macOS/Windows `workflow_dispatch` run (unrunnable platforms are listed in the CHANGELOG), and the agy cancel/owner-loss ops on this branch.

## Execution Policy
- execute: effort=high, reason=a new worker subprocess under the closeout parser and the launch path; ownership, death, env and fork semantics plus a reviewed prompt change are subtle.
