# Detailed plan: migrate BAML v0 (baml-py 0.222) to BAML v1 0.20.1 (baml-bridge)

Tracking issue: agent-harness#1135. Evidence lives in the issue body and in three comments: the D1a addendum, the round-1 addendum and the **round-2 worker addendum**. Spike dir: `/mnt/workspace/spikes/baml-v1`, worker prototype in `worker_proto_r3/`. This plan cites that evidence and does not repeat it.

**Revision 3 changes the mechanism.** The v1 runtime is a process-global singleton, and in revision 2 it lived inside our process. That single fact is the root of four round-2 blockers:
- codex 1: fingerprint forgery;
- codex 2: foreign BAML runs before the ownership check, so `os._exit(1)` is reachable;
- grok 3: a poisoned pytest process;
- claude B1 / grok 4: the runtime sees the whole environment.

In revision 3, **the v1 runtime runs only in a dedicated worker subprocess that only we start.** This still honours D2: the runtime is built in memory from our sources, with no codegen. Revision 3 also closes the other round-2 blockers: the full closeout envelope, `injection.py` under failure, parse narrowing, the fmt/Jinja question, and the plan-text contradictions.

**Revision 4 hardens the worker contract** (round 3: grok and gemini AGREE; codex and claude DISAGREE on hardening):
- fork safety (`register_at_fork`, lock re-init, fd close);
- bounded IPC (one send+receive deadline, frame caps, framing faults typed);
- owner liveness while hung (`PR_SET_PDEATHSIG` from a long-lived spawner thread, plus a `getppid` watchdog);
- env normalized **inside** the worker (C-locale coercion);
- `BamlWorkerError(BamlValidationError)`, with each live caller routed to "not evaluated", never to a verdict or a skip (per-site trace);
- any fault discards and kills the worker;
- claude's cheap hardening items: own session, framing rules, pipefail, platform-fail policy, sentinel-env Step 0, all wheel digests, memory disclosure.

All the new mechanisms were exercised in the round-3 spike (issue comment).

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

### Worker process (`phase_loop_runtime/_baml_worker.py`)
- **Scope.** It is a standalone script that imports only the stdlib plus `baml_bridge`, never `phase_loop_runtime`.
  - All side effects (fd dup/redirect, prctl, watchdog) run under `if __name__ == "__main__":`. Importing the module does nothing.
  - It serves a **fixed** op table: `init`, `parse_closeout`, `closeout_request`, `evidence_request`. There is no caller-named or arbitrary-invoke op.
  - A second `init` is answered with a `fault`, and so is any op before `init`.
- **Protocol.**
  - One JSON object per line, encoded as UTF-8 with `ensure_ascii=True`, over binary pipes. This makes it independent of locale and code page.
  - Requests come in on stdin. Responses go out on a dup of fd 1, taken before fd 1 is pointed at stderr, so native prints cannot corrupt the protocol.
  - Every request carries a monotonically increasing `id`, which continues across worker restarts. The response echoes it.
  - A response has exactly the keys `{id, fingerprint, <one of ok|error|request|fault>}`.
- **Faults.** Any exception inside an op, including `BamlPanic`, is caught and returned as `fault` (`"<module.Class>: <msg>"`). The **client** then discards and kills the worker (see Failure semantics).
- **Environment normalization.** The worker receives its allowlist key set in argv. Before it imports `baml_bridge`, it deletes every env key outside that set. That covers the `LC_CTYPE` CPython adds by C-locale coercion (spike: a PATH-only child starts with `['LC_CTYPE', 'PATH']`) and `__PYVENV_LAUNCHER__` on Windows/macOS venv launchers. Tests then assert the environment **inside the worker** (codex 4).
- **Owner liveness** (codex 3). The worker must die with its owner even while hung inside BAML.
  - **Linux:** at startup, `prctl(PR_SET_PDEATHSIG, SIGKILL)` via `ctypes`. It then re-checks `os.getppid() == <owner pid from argv>` and exits if the owner is already gone.
  - **PDEATHSIG fires when the parent *thread* that forked exits.** So the client always spawns the worker from **one dedicated, long-lived daemon thread** (`baml-worker-spawner`), never from the calling thread. A caller in a short-lived pool thread therefore cannot cause a spurious kill.
  - **All platforms:** a watchdog thread polls `os.getppid()` every 0.5 s and calls `os._exit(0)` when it changes.
  - Spike: a Python thread keeps running during a native BAML op, because the GIL is released (40/40 ticks over a 2 s `baml.sys.sleep`). Killing the owner with SIGKILL while the worker was blocked in a 30 s BAML op removed the worker within 1.5 s with PDEATHSIG alone, and within 1.5 s with the watchdog alone.
  - Stdin EOF remains a third, idle-time path.
- **Signals.** The worker is started in its own session: `start_new_session=True` on POSIX, `CREATE_NEW_PROCESS_GROUP` on Windows. A terminal Ctrl-C or a supervisor `killpg` aimed at the runner does not kill it (claude N1). The three liveness paths above still end it when the owner actually dies.

### Launch and environment
- **Command.** `Popen([sys.executable, "-I", <path of _baml_worker.py>, <owner pid>, <allowlist keys>], stdin=PIPE, stdout=PIPE, stderr=<temp file>, env=_worker_env(), close_fds=True, start_new_session=True)`.
  - The `init` message carries the parent's `sys.path` (non-`str` entries dropped) and the **rendered** file map.
  - Import resolution therefore follows the parent's trust domain: `PYTHONPATH`, the user site, and a cwd entry if the parent has one. That is deliberate and stated. `-I` isolates the environment, not imports.
- **`_worker_env()` is `_filtered_env` given a real job.** It is an allowlist:
  - `PATH=<directory of sys.executable>`. This is neither `os.defpath`, which on Windows is `.;C:\bin` and puts the cwd on PATH, nor the parent's `PATH`.
  - `SYSTEMROOT`, `WINDIR`, `TMPDIR`, `TMP` and `TEMP`, when set.
  - It **excludes everything else**, including `HOME`, `BAML_*`, `BOUNDARY_*`, `OPENAI_*`, `ANTHROPIC_*`, any `*_API_KEY`, `PYTHON*`, proxies and locale variables.
  - No locale is set because the protocol does not depend on one (`ensure_ascii`, binary pipes). Coercion leftovers are removed inside the worker, as described above.

### Ownership
- **Process isolation.** Only our client holds the worker's stdin, and the worker loads exactly the map it is sent.
- **Fingerprint as a further check.** `fingerprint = sha256(canonical JSON of the RENDERED file map)`, computed by the worker from what it loaded and echoed on every response. The client compares it with its own hash of the map it sent.

### Client (`baml_modular._BamlWorkerClient`)
- **Slot and lock.** One module-level slot guarded by a `threading.Lock`. One request at a time; the lock is held for the whole round trip. The worker is started lazily, so a process pays the ~0.8 s cold start once.
- **Fork safety** (codex 1, claude N2). `os.register_at_fork(after_in_child=_baml_after_fork_in_child)` does three things in the child:
  1. replaces the lock with a fresh one, because an inherited held lock cannot be released;
  2. forgets the slot;
  3. `os.close`s the inherited pipe fds without flushing and neutralizes the `Popen` object, so the child never signals or waits on the parent's worker. The parent's worker still sees EOF when the parent dies.

  The `atexit` handler acts only when `os.getpid()` equals the pid that owns the slot.
  - Spike: with thread A holding the lock mid-request (a 3 s op), the main thread forked. The child's call succeeded in 0.82 s on its own worker pid. The parent's worker finished A's request and kept serving on the same pid.
- **Bounded IPC** (codex 2, claude N3). **One deadline covers send and receive.** The default is 60 s; tests can override it.
  - **Writes** are done by a per-worker writer thread. The caller waits on a completion event with the remaining deadline. If the deadline passes, the worker is killed, which unblocks the writer with `BrokenPipeError`, and the call fails typed. A worker that has stopped reading stdin therefore cannot hold the lock forever.
  - **Reads** are done by a per-worker **daemon** reader thread using `readline(MAX_RESPONSE_BYTES + 1)`, with `MAX_RESPONSE_BYTES = 4 MiB`, into a per-worker queue.
  - Request frames are capped at `MAX_REQUEST_BYTES = 16 MiB`. The `init` map today is about 30 KB.
  - Each of these becomes a typed error, followed by discard and kill:
    - an oversized request, which is refused before sending;
    - a response line longer than the cap;
    - a line without its trailing newline, i.e. EOF mid-frame (truncated);
    - non-JSON or a non-object;
    - a wrong `id`, a wrong fingerprint, or a wrong key set;
    - a `json.loads` failure of an `ok` payload.
- **`atexit`.** Close stdin, wait up to 5 s, then kill.

### Failure semantics
- **New error type** (claude B1): `class BamlWorkerError(BamlValidationError)`.
  - It is raised only for transport and liveness faults: spawn or init failure, death, timeout, desync, framing error, fingerprint mismatch, or a worker-side `fault`.
  - It carries `.kind` (one of those names) and `.rc` (the exit code, set only when the worker is known to be dead, else `None`). Attributes are asserted instead of message text (#19).
  - A **content** verdict (`error` from the bridge, a pydantic failure, a missing payload key, a name outside the bridge table) stays a plain `BamlValidationError`.
  - Callers can therefore tell "we could not evaluate" apart from "the input is invalid", and the frozen surface is unchanged because `BamlWorkerError` is a `BamlValidationError`.
- **Any `BamlWorkerError` discards AND kills the worker** (claude B3). A `BamlPanic` is v1's unrecoverable class, so a runtime that raised one is never reused.
- **Bounded retry of transport and liveness faults only.**
  - Every op is a pure function of its input (parse, or render a request); none has side effects.
  - So `_worker_call` retries a `BamlWorkerError` on a **fresh** worker at most **2** times, 3 attempts in total, then raises the last `BamlWorkerError`.
  - Content verdicts are never retried.
- **A death between calls is not charged to the next call** (claude B1).
  - Before sending, a liveness check that finds the worker dead **records the death**, restarts, and proceeds; nothing was sent, so this is not a retry.
  - Recording means an entry in `baml_modular.worker_fault_log()` (kind, rc, stderr tail, timestamp) plus a `logging.warning`.
  - Deaths are never hidden. Every one is recorded exactly once, and tests assert that count.
- **`KeyboardInterrupt` and any other `BaseException`** raised in the parent during a write or wait kills and discards the worker, so a late response can never be read by the next request, and then re-raises unmapped.
- **The parent never imports `baml_bridge`.** No hooks, no `atexit(shutdown_runtime)` and no v1 singleton exist in our process. After a full public call, `'baml_bridge' not in sys.modules` is a tripwire.

### Cost (round-2 addendum §1, plus the round-3 measurement)
- **Latency:**
  - cold start about 755–839 ms, once per process;
  - `parse_closeout` median 2.75 ms (p95 4.3 ms);
  - `closeout_request` median 3.5 ms;
  - v0 took 27–60 ms on the first call and about 0.9 ms after.
  - On the launch path, the first launch in a runner process gains about 0.8 s, and later launches about 3 ms.
- **Memory:** the worker's VmRSS is about 41 MB before init, **about 281 MB after `initialize_runtime`**, and about 282 MB after a parse (peak about 286 MB). v0's in-process `from_files` added about 21 MB to the parent (28 MB → 49 MB maxrss).
  - The v1 cost comes from the runtime, not the worker; in-process would add the same to our own process.
  - It is paid once per runner process that touches BAML, and it is disclosed (#25).

## Caller handling of `BamlWorkerError` (claude B1, B2; code-read on main `b687e311`)

| Call site | Enclosing function and path to the CLI | Durable state written before the call | Can a sibling executor be live? | Rev-4 handling |
|---|---|---|---|---|
| Closeout parse: `runner._parse_native_closeout_status` → `discovery.parse_closeout_payload_doc` → `parse_baml_response("EmitPhaseCloseout")` (runner.py around line 10466) | `_parsed_child_automation` (around 10389). It is called after `launch_with_spec` returns: from `run_loop` (around 3924, serial and wave finalize after `run_phase_worker_pool` has joined), `launch_delegated_child` (around 5404/5446) and the lane helpers (around 10616/10962) | The executor has **finished**. Its output is in the launch artifacts (log). The phase status is still the launch-time status | No. Serial: one executor, already exited. Wave: the pool has joined every job before finalization | **Today `except BamlValidationError` maps to `automation_status=blocked`, `blocker_class=contract_bug`, "BAML closeout validation failed"**, a durable invalid-closeout verdict. Rev 4 adds `except BamlWorkerError` **before** it, after the bounded retries, and maps to `automation_parse_error` with `blocker_class="unretryable_external_outage"` (existing frozen vocabulary; no new term). The summary reads `"closeout NOT evaluated: BAML worker <kind> (rc=<rc>) after 3 attempts; executor output preserved at <log>; re-run to re-evaluate"`, `human_required=false`. It is **never** `contract_bug` and never a verdict on the closeout content. It goes through the same code path v0 used for a parse error, so wave teardown and branch preservation behave exactly as they did for v0 parse errors. It does not propagate, because propagating out of wave finalization would run the wave `finally` (around runner.py 5006), which reclaims worktrees not in `preserve_branches`, i.e. it could discard sibling phases' completed work |
| Tier 3: `evidence_audit.evaluate_suspected_fake_evidence` → `build_baml_request("EvaluateSuspectedFakeEvidence")` (around line 905) | `run_evidence_audit` loop (around 845) → the runner's closeout evidence gate | The executor has finished. The Tier-2 findings are in memory | No (post-launch) | **Today every exception becomes `_uncertain_fallback` → verdict `uncertain` → `tier3_judgment_blocker` returns `None`**, a warning only. That is fail-open. Rev 4: `evaluate_suspected_fake_evidence` re-raises `BamlWorkerError`, placed before its `except (…, ValueError, …)`. The loop at around line 845 catches `BamlWorkerError` **before** `except Exception` and sets `blocker = {"human_required": False, "blocker_class": "unretryable_external_outage", "blocker_summary": "Tier 3 evidence audit NOT run: BAML worker <kind> after 3 attempts; re-run to audit"}`. The closeout is blocked, **never skipped**, and never judged fake. Other Tier-3 call errors (HTTP down, and so on) keep v0's `uncertain` policy; that is unchanged and out of scope |
| Launch prompt, serial: `run_loop` → `build_prompt` (around runner.py 3312) | `run_loop` → `cli._main` (cli.py around 1852). No handler in between (dispatch-lock handler around 1488 only; the `ValueError`/`Exception` handlers around 1318–1381 run before dispatch) | The phase selection event may have been emitted; nothing is launched | No. Launch follows the prompt build | `BamlWorkerError` propagates after the bounded retries. `phase-loop run` exits non-zero with the typed error. The dispatch lock is released by its context manager with **no live executor**. No verdict is written (#22) |
| Launch prompt, concurrent wave: `_dispatch_concurrent_wave` → `_prepare_phase_launch` → `build_prompt` (around 4703 → 3312) | Inside the wave `try:` (around 4785). Its `finally` (around 5006) reclaims prepared worktrees | Worktrees were created for the phases prepared so far. **No job has started**: `run_phase_worker_pool` runs only after every phase is prepared | **No.** All prompts are built before the pool starts | Propagates. The `finally` reclaims only freshly created, unlaunched worktrees, so no work can be lost. The dispatch lock is released with no live executor |
| Delegated child: `launch_delegated_child` → `build_prompt` (around 5253) | Called from `run_loop` around 4059, in the `automation_status == "delegated"` branch, after the **parent executor has exited** | The parent's closeout has been parsed. **The parent's phase status is NOT yet persisted**: `set_phase_status(...)` runs after `launch_delegated_child` returns (around 4121) | No. The parent has exited, and the child has not launched | Propagating would abort the run before the parent's result is recorded. So rev 4 wraps the `launch_delegated_child(...)` call in that branch with `except BamlWorkerError` and routes it into the **existing** blocked-outcome flow of the branch: `status_after_launch = "blocked"`, and `event_blocker = {"human_required": False, "blocker_class": "unretryable_external_outage", "blocker_summary": "delegated child NOT launched: BAML worker <kind> after 3 attempts"}`, persisted by the same `set_phase_status` call. The child is not launched, and the parent's result is recorded. A plain content `BamlValidationError` cannot occur on this path, because the prompt build has no content verdict |
| Harness lane: `launch_harness_lane_work_unit` → `build_prompt(harness_lane_assignment=…)` → `build_lane_prompt_bundle` (around 5961) | A library entry point. `git grep` finds **no `src/` caller**; only tests and external callers use it | Pipeline diagnostic only | Callers may run lanes in parallel. This function launches **one** unit, and its prompt build precedes its own launch | Propagates as `BamlWorkerError`. It is not converted to a lane verdict; there is no broad handler in this function. Test: the lane entry point with a failing worker raises `BamlWorkerError` and spawns nothing |

## Divergence register (every v0→v1 difference found; each has a disposition and a pin)

| # | Divergence | Disposition | Pinned by |
|---|---|---|---|
| 1 | Evidence request role `system` instead of `user` | **Neutralized**: `${role("user")}` | evidence golden (full request) |
| 2 | `baml-original-url` header dropped | **Neutralized**: `EvidenceAuditClient … headers = {"baml-original-url": "https://example.invalid/v1"}` | evidence golden |
| 3 | Tier-3 prompt/body drift | **Neutralized, measured equal** (3 payloads, distinct sentinel per argument) | evidence golden |
| 4 | Closeout loop layout | **Accepted (D1)** | prompt-byte refresh |
| 5 | Closeout output-format block | **Accepted (D1)**. Enums remain in the contract prose and in D1a | refresh; taxonomy-literal test |
| 6 | Schema-description block absent in v1 | **Neutralized (D1a)** | D1a test |
| 7 | Extra payload key raises in v1 | **Neutralized**: filter to signature params | test |
| 8 | Missing payload key | **Neutralized**: plain `BamlValidationError` before the worker is called | test |
| 9 | `closeout_commit_sha=""` | **Neutralized**: v0 normalization | test |
| 10 | Backslash in a closeout list value: v0 raises `re.error` | **Accepted (fix)** | test |
| 11 | Template syntax inside caller values | **Parity, measured** | test |
| 12 | Parse: int > i64 is clamped in v0, `null` in v1 | **Accepted** | corpus golden (flagged) |
| 13 | `BamlPanic` and in-BAML panics | **Contained**: they happen in the worker, come back as a `fault`, and the parent raises `BamlWorkerError(kind="fault")`. The worker is **discarded and killed**. **The parent survives, and the next call succeeds on a fresh pid** | real tests: broken source at init; in-BAML panic, then the next call on a new pid |
| 14 | Process-global runtime, `atexit(shutdown_runtime)`, the `os._exit(1)` hook | **Isolated in the worker**; the parent never imports `baml_bridge` | subprocess-death tests; `sys.modules` tripwire |
| 15 | Runtime environment: v0 got the whole env | **Tightened**: allowlist, normalized inside the worker. v1 reads none of the probed variables | env-sentinel test asserting the env **inside the worker** |
| 16 | First-call latency ~0.8 s per process; ~3 ms per call after | **Accepted**, disclosed | reuse and latency test (same pid, < 250 ms) |
| 17 | New transitive `protobuf` | **Bounded** `>=6.31.1,<8` | dependency test |
| 18 | `baml` / `baml-cli` console scripts gone | **Accepted**, disclosed | grep tripwire |
| 19 | Exception message text | **Accepted**, not contractual | tripwire: no text assertions; the test uses `.kind` / `.rc` |
| 20 | `BamlRequest.id` becomes `None` | **Accepted** (no consumer) | goldens exclude `id`; `id is None` test |
| 21 | Closeout request envelope from `PhaseLoopCloseoutClient` | **Parity, measured equal** | Step 0 closeout-request golden (5 payloads) |
| 22 | `injection.py`: v0 swallowed `BamlValidationError` and launched with a fallback instruction | **Changed (lead)**: the fallback is removed. Per-site outcomes are in the caller table: the launch fails typed, and **no call site launches without the contract, releases a lock over a live executor, or converts the error into a verdict** | tests per site: serial `run_loop`, wave prepare, delegated child, lane entry point |
| 23 | Names outside the bridge table | **Parity** (v0 rejected the same set) | Step 0 plus test |
| 24 | **New causes for `BamlValidationError`**: the worker can die, time out, desync or fault, independent of the input (claude B1) | **Typed and routed**: `BamlWorkerError` subclass; bounded retries (at most 2) on a fresh worker for pure ops; a death between calls is recorded, not charged; each caller maps it to **"not evaluated"**, never to a content verdict and never to a skip (caller table) | real-worker tests: kill between calls and mid-call while driving the discovery closeout parse, the runner native-closeout path and the Tier-3 build; assert the caller outcomes in the table and the `worker_fault_log()` counts |
| 25 | **Memory**: the v1 runtime is about 240 MB resident (worker ~281 MB after init), against ~21 MB added by v0 in-process | **Accepted**, disclosed (CHANGELOG, D6 risk list); inherent to v1 | test: the worker's VmRSS after init is recorded in the verification log (Linux); no threshold is asserted, because the number is informative |

## Decisions (all decided)

- **D1 (maintainer):** v1 renders the closeout prompt, and its bytes change. My recommendation was otherwise. The Python renderer set is deleted: `_build_emit_phase_closeout_request`, `_render_emit_phase_closeout_prompt`, `_render_baml_list_loop`, `_function_prompt_template`, `_closeout_output_format`, `_schema_type_label`.
- **D1a (lead, under D1):** Python appends `"\n\n" + _render_schema_description(export_function_schema("EmitPhaseCloseout"))` to `BamlRequest.prompt` and to `body["messages"][0]["content"]`. The role is set in BAML. The prompt text is taken from the built request via `_extract_prompt`. `schema_sha256` hashes the canonical schema JSON, not source text, so it stays `77e72437…`.
- **D2:** in-memory runtime from our sources, with no codegen, **run in the worker subprocess**. The worker is required, not optional: it is the mechanism that makes ownership, env isolation and hook containment hold by construction.
- **D3:** a dual-form `_class_fields` using the stricter regex `([A-Za-z_]\w*)(?:\s*:\s*|\s+)([A-Za-z_]\w*(?:\[\])?)(\?)?\s*,?` with fullmatch (N2). Sources are `baml fmt`'d, and a CI fmt round-trip runs on the RAW sources, which spike §6 shows can pass.
- **D4:** hard switch. Step 0 is mandatory.
- **D5:** hash-enforced install stays out of scope. Instead, `protobuf>=6.31.1,<8`. The floor is baml-bridge's gencode `ValidateProtobufRuntimeVersion(6, 31)`. The spike loads and parses cleanly under `-W error` on 6.31.1 and 7.36.2. The repo has no pytest `filterwarnings` config (`git grep` is empty). The other direct dependency, `typing-extensions>=4.14.0`, is already satisfied by pydantic 2 and is not pinned here.
- **D6 (maintainer accepted the canary):** exact `==0.20.1`. The CHANGELOG discloses the following, plus the worker's ~280 MB resident memory (#25):
  - the worker process and its latency;
  - the hooks confined to the worker;
  - the protobuf window;
  - the platforms that were not load-tested;
  - rollback: revert to `baml-py>=0.222,<0.223` and cut a patch release.

## Step 0: capture the v0 baselines on main BEFORE the switch

- **Script.** `phase-loop-runtime/tests/data/baml_v0_baseline/capture_v0.py` runs one time, in a baml-py 0.222.0 venv against a clean `origin/main` worktree. It runs **under the same sentinel environment as the #15 test, with every real credential variable unset** (claude N7). The goldens then also show that v0 was env-independent, and no developer key can ever land in a committed golden. It is not collected by pytest, and a provenance header records the main SHA and the baml-py version. It writes:
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
- Run `uv lock`. Check that **all 8** baml-bridge 0.20.1 wheel hashes in the lock equal the PyPI digests listed in agent-harness#1135 (claude N8). The lock stays advisory (D5).

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
- The worker script from the worker contract, ported from `worker_proto_r3/_baml_worker.py`. It adds:
  - sequence ids and the fixed op table;
  - rejection of a second `init`;
  - env normalization against the argv allowlist before `baml_bridge` is imported;
  - `PR_SET_PDEATHSIG` on Linux, plus the `getppid` watchdog thread on every platform;
  - `ensure_ascii` framing;
  - `__main__`-only side effects.

### `phase-loop-runtime/src/phase_loop_runtime/baml_modular.py` (modify)
- **Add:**
  - `class BamlWorkerError(BamlValidationError)` with `.kind` and `.rc`;
  - `_BamlWorkerClient` with its writer and daemon reader threads, the frame caps, one deadline, and fault → discard + kill;
  - the long-lived `baml-worker-spawner` thread;
  - `_worker_env()` (`_filtered_env` given a real job);
  - the module slot plus lock;
  - `os.register_at_fork(after_in_child=…)`;
  - the pid-guarded `atexit`;
  - `_worker_call(op, args)` with the bounded retry (at most 2, transport and liveness faults only);
  - `worker_fault_log()`;
  - `_reset_worker_for_tests()`.
- `_reset_worker_for_tests()` terminates and discards the worker. Any test that uses non-packaged sources calls it in setup **and** teardown, so the pytest process is never poisoned and the first call never meets a stale fingerprint (grok 3; claude r3 Q3).
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

### `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify; #24 caller table)
- `_parse_native_closeout_status` (around line 10466): add `except BamlWorkerError` **before** the existing `except BamlValidationError`. It maps to the "not evaluated" `automation_parse_error` with `blocker_class="unretryable_external_outage"`, as in the caller table. The existing `contract_bug` mapping stays for content verdicts only.
- `run_loop`'s delegated branch (around line 4059): wrap `launch_delegated_child(...)` with `except BamlWorkerError` and route it into the branch's existing blocked flow, as in the caller table.
- The serial and wave prompt builds are **not** wrapped. They propagate, as the caller table shows.

### `phase-loop-runtime/src/phase_loop_runtime/evidence_audit.py` (modify; #24 caller table)
- `evaluate_suspected_fake_evidence` (around line 895): `except BamlWorkerError: raise`, placed before the existing `except (…, ValueError, …)`.
- The `run_evidence_audit` loop (around line 845): `except BamlWorkerError` before `except Exception`. It sets the "Tier 3 NOT run" blocker with `unretryable_external_outage` and never returns `uncertain`.

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
  - Every step runs with `shell: bash` and `set -euo pipefail`, so `baml-cli`'s own exit status is also asserted; the Actions default `bash -e` lacks pipefail (claude N6).
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
- **Worker death and faults: always a `BamlWorkerError`, the parent survives, and there is no wrong answer.** Each case runs in a subprocess that must exit 0. Assertions use `.kind` and `.rc`, never message text.
  - **The spawn hook:** the patched raw-read seam supplies a hostile `phase_loop_bridge.baml` whose `phase_loop_parse_closeout` runs `spawn with baml.spawn.options(detach = true) { throw baml.errors.Io { … } }`.
    - Call 1 must return **either** the correct result **or** `BamlWorkerError`, never a wrong answer. Its result is computed before the hook fires (measured about 138 ms after return).
    - Wait up to 5 s for the worker to exit with rc 1.
    - Call 2, with the **packaged** sources restored, succeeds on a fresh pid.
    - `worker_fault_log()` shows **exactly one** death with `rc == 1`. A death between calls is recorded, not charged to the next call.
  - **SIGKILL mid-call:** a hostile bridge sleeps via `baml.sys.sleep`, and the worker is killed after 0.5 s. With retries allowed, the call succeeds on a fresh pid, and the fault log shows the kill (`kind="died"`, `rc=-9`). With retries forced to 0, the call raises `BamlWorkerError(kind="died", rc=-9)`.
  - **Timeout:** with a test-sized deadline and retries at 0, the call raises `BamlWorkerError(kind="timeout")`, and the worker is gone.
  - **Blocked write** (codex 2): a scripted peer never reads stdin, and the request is larger than the pipe buffer. The call raises `BamlWorkerError(kind="timeout")` within the deadline, and the lock is free again.
  - **Framing** (codex 2): scripted peers emit, in turn:
    - an oversized line (over 4 MiB);
    - an unterminated line followed by EOF;
    - non-JSON;
    - a JSON array;
    - a wrong `id`;
    - a wrong fingerprint;
    - an extra key;
    - an `ok` that is not JSON.

    Each gives `BamlWorkerError` with the matching `kind`, and the peer is killed. An oversized request is refused before sending. The scripted peers live in `tests/fixtures/baml_worker_peers.py`; they are legitimate stand-ins for a misbehaving peer, which the real worker cannot be made to produce. Every other test uses the real worker.
  - **Broken source at init:** `BamlWorkerError(kind="init_fault")` at both public entry points. The next call with packaged sources succeeds.
  - **In-BAML panic** (claude B3): `BamlWorkerError(kind="fault")`. The worker pid is **dead**, and the next call succeeds on a **new** pid.
  - **Protocol checks:** an op before `init` gives a `fault`, and a second `init` gives a `fault`.
  - **Fingerprint:** a client that is handed a different map than the worker loaded raises `BamlWorkerError(kind="fingerprint")`. Changing only the evidence prompt changes the rendered-map hash.
- **Owner liveness** (codex 3), in a subprocess on Linux:
  - A parent starts the worker inside a 30 s hostile `baml.sys.sleep` op, then is SIGKILLed. The worker must be gone within 3 s. This is tested twice: once with PDEATHSIG enabled, and once with only the watchdog (a test flag in the `init` message disables prctl).
  - A second test runs the call from a short-lived pool thread that exits. The worker must **survive** that thread's exit, which pins the spawner-thread design.
  - Spike: both mechanisms remove a worker blocked in BAML within 1.5 s.
- **Signals** (claude N1): `os.killpg(parent_pgid, SIGINT)` interrupts the parent (the test catches `KeyboardInterrupt`), the worker survives it (it runs in its own session), and the parent's next call succeeds on the same pid.
- **`KeyboardInterrupt` in the parent** mid-wait, as a separate subprocess test: SIGINT to the parent's pid only. The process ends with an unmapped `KeyboardInterrupt` traceback, the worker is killed, and no `BamlValidationError` is printed.
- **Environment inside the worker** (codex 4; #15): the parent env holds distinct sentinels for `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `ANTHROPIC_API_KEY`, `BAML_LOG`, `BAML_TRACE`, `BAML_HOME`, `BOUNDARY_API_KEY`, `BOUNDARY_PROJECT_ID`, `HOME` and `HTTPS_PROXY`. Then:
  - a test-only `env` op (enabled by the same test flag) returns `sorted(os.environ)` **from inside the worker**, which must be a subset of the allowlist. `LC_CTYPE` from coercion must be absent;
  - both `BamlRequest`s equal their goldens;
  - no sentinel appears in url, headers, body or prompt;
  - the worker's stderr and the child's stdout and stderr are empty.
- **Callers of `BamlWorkerError`** (#24, the caller table), real worker, killing it between calls and mid-call with retries forced to 0:
  - `discovery.parse_closeout_payload_doc` raises `BamlWorkerError`, not a content verdict;
  - `runner._parse_native_closeout_status` returns `automation_parse_error` with `unretryable_external_outage`, and **never** `contract_bug`;
  - `run_evidence_audit` returns a blocker with `unretryable_external_outage`, and **never** an `uncertain`-only warning;
  - the serial `run_loop` raises `BamlWorkerError`, and the executor launch spy is never entered;
  - the concurrent-wave prepare raises before `run_phase_worker_pool` is called, and only unlaunched worktrees are reclaimed;
  - the delegated branch records the parent as `blocked` with the child not launched;
  - `launch_harness_lane_work_unit` raises `BamlWorkerError` and spawns nothing.
- **Test-only ops.** `env` and the prctl-off flag are accepted **only** when `init` carries `"test_mode": true`, which only `_reset_worker_for_tests(test_mode=True)` sets. A tripwire asserts that no `src/` caller sets it.
- **Concurrency:** 8 threads start from a cold slot. Exactly one worker pid is started. All 8 results equal the single-threaded parse. The test has a 60 s timeout.
- **Fork** (codex 1): thread A holds the lock inside a 3 s hostile op while the main thread forks.
  - The child's call succeeds within 5 s on its own new pid.
  - The parent's A-request completes, and the parent's worker keeps serving on the same pid.
  - In the child, the inherited worker fds are closed: `os.fstat` on them raises `EBADF`.
  - The test is POSIX-only; there is no `os.fork` on Windows.
- **Latency (#16):** a second call reuses the same worker pid and completes in < 250 ms.
- **Tripwires:**
  - after a full public call, `'baml_bridge' not in sys.modules`;
  - no `\bspawn\b` in any packaged `.baml`;
  - `_read_baml_files()` output contains no `{{` or `{%`;
  - the #18 grep;
  - the #19 grep;
  - `_worker_env()` keys are a subset of the allowlist;
  - `import phase_loop_runtime._baml_worker` has no side effects: fds 1 and 2 are unchanged and no thread is started.
- **Platform guards** (claude N5): the fork, SIGKILL, `killpg` and PDEATHSIG tests are skipped with an explicit reason on Windows, and the watchdog test runs everywhere. On Windows, the env test tolerates `__PYVENV_LAUNCHER__` only because the worker normalization removes it, and it asserts that it is gone inside the worker.
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
- **Pre-merge, and part of the acceptance criteria:** run verification step 3 once on GitHub-hosted `ubuntu-24.04-arm`, `macos-14`, `macos-13` and `windows-latest`, via a throwaway `workflow_dispatch` on an unmerged scratch branch, with the Windows guards above. Record the results in the PR.
  - **A platform that runs and FAILS blocks merge**, unless the maintainer explicitly accepts it as unsupported (claude N5). Under #22, `phase-loop run` cannot launch anything on such a platform.
  - A platform that cannot be run at all is listed as unverified in the CHANGELOG.

## Documentation impact
- `CHANGELOG.md` `[Unreleased]` gets "BAML v1 0.20.1 (agent-harness#1135)", covering:
  - `baml-py` → `baml-bridge==0.20.1`, plus `protobuf>=6.31.1,<8`, which breaks environments pinned to `protobuf<6`;
  - **a BAML worker subprocess**, covering:
    - about 0.8 s cold start per process and about 3 ms per call after;
    - **about 280 MB resident** (#25);
    - an allowlist environment;
    - its own session, so a terminal Ctrl-C does not kill it;
    - it dies with its owner;
  - **the new `BamlWorkerError(BamlValidationError)`**: faults are retried at most twice on a fresh worker. After that, the closeout parse and the Tier-3 audit record a `blocked` / `unretryable_external_outage` "NOT evaluated" outcome instead of a verdict or a skip, and a launch fails typed. Any worker fault, including a death since the previous call, can therefore abort `phase-loop run` before launch (#22, #24);
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
- **This PR** touches `phase_loop_runtime/**/*.py` (`baml_modular.py`, `injection.py`, `runner.py`, `evidence_audit.py` and the new `_baml_worker.py`), so it runs `--route-core` only. No requalification is needed here.
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

Scope:
- 6 `.py` files: `baml_modular.py`, `injection.py`, `runner.py` (two narrow `except BamlWorkerError` sites), `evidence_audit.py` (two sites), the new `_baml_worker.py`, and `_gate_a_probe.py`;
- pyproject and lock;
- 9 `.baml` files;
- 2 workflows;
- 1 new test file plus the scripted-peer fixture;
- the Step 0 data and the goldens.

This sits at the edge of the bounded-plan threshold, and the commits are split so each can be reviewed on its own. **Commits between step 4 and the refresh commit are expected to be red on the prompt-text tests** (claude N8). CI is judged on the PR head. The refresh commit is the one that turns them green.

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
  - worker faults of every kind give `BamlWorkerError` with the right `.kind`/`.rc`, discard and kill the worker, and never produce a wrong answer. The kinds are: spawn hook, SIGKILL, timeout, blocked write, each framing case, init fault, panic and fingerprint;
  - owner liveness (worker gone within 3 s of the parent's SIGKILL while hung; it survives a spawning-thread exit and a `killpg` SIGINT);
  - the environment **inside the worker** is a subset of the allowlist, with no sentinels, and output is empty;
  - concurrency and fork-while-locked;
  - every caller-table outcome (#22, #24).
- [ ] The CI job `baml-sources` passes and is blocking through `gate`: sha-verified CLI 0.20.1, a zero-diff fmt round-trip on raw sources, and a check of 9 files on raw and rendered sources. The bridge load test is green on the pytest lanes, in the wheel smoke / Gate A probe, and in the publish-pypi smoke.
- [ ] The refresh is a separate commit. Its PR body carries the attributed v0→v1 diff, an unchanged envelope, the launchspec diff confined to the prompt strings with `schema_sha256: 77e72437…` unchanged, and the coverage-rule node diff with every replacement disclosed.
- [ ] Both pre-merge runs are recorded in the PR:
  - the arm/macOS/Windows `workflow_dispatch` run. A platform that runs and fails blocks merge unless the maintainer accepts it as unsupported; a platform that cannot run is listed in the CHANGELOG;
  - the agy cancel/owner-loss ops on this branch, including a check that the worker exits when the runner is SIGKILLed.

## Execution Policy
- execute: effort=high, reason=a new worker subprocess under the closeout parser and the launch path; ownership, death, env and fork semantics plus a reviewed prompt change are subtle.
