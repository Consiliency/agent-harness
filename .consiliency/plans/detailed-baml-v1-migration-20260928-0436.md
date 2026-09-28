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

**Revision 5 changes these by construction, not by patching** (round 4: codex and claude DISAGREE; grok and gemini AGREE):
- **Owner death:** one kernel- or OS-level mechanism per platform, and a table that states exactly what is tested where:
  - Linux: PDEATHSIG;
  - Windows: a Job Object with `KILL_ON_JOB_CLOSE`, launching the real interpreter rather than the venv redirector;
  - macOS: the `getppid` watchdog, with the GIL release now verified during all three real ops, and the residual disclosed.
- **Client state:** all of it lives in one `_Client` object. The at-fork handler only does `os.close(int)` and drops the reference. Spawning is inside the deadline.
- **Snapshots:** one source snapshot per process, and one request-bytes snapshot per call reused across retries, with recovery parity pinned for all three ops.
- **Tests:** split into idle death (recovers), in-flight with retries at 0, and budget.
- **Claude r4 notes folded in:**
  - exact-type corpus;
  - frame caps treated as content errors (#27);
  - loader env vars allowlisted;
  - worker cwd pinned;
  - `--init` / zombie-aware checks;
  - comment- and string-stripped spawn tripwire;
  - an AST handler tripwire;
  - the wave `finally` test with a preserved phase;
  - downstream outcome pinned through `_parsed_child_automation`;
  - "re-run" wording corrected;
  - **adoption-bundle raw digests (#26), newly found**.

**Revision 6 changes the fork and spawn mechanisms** (round 5: codex and claude DISAGREE). The fork class had failed in rounds 3, 4 and 5 in new shapes each time.
- **The at-fork child handler closes nothing.** It does exactly one thing: `_CLIENT = _Client(retain=_CLIENT)`.
  - `_Client.__init__` only allocates, and `_CLIENT = _Client()` is created at import, so there is **no module-level lock at all**.
  - A fork child leaks its inherited parent-worker pipe fds, a bounded handful, and the ownership section justifies this. Owner death is kernel- or OS-enforced, so EOF is not load-bearing, and a test proves it.
  - The recorded-fd-integer machinery is deleted.
- **Spawn ownership protocol:** generation tokens. On timeout, the caller abandons its token and replaces the spawner. A late spawn kills and reaps its own process and is never published.
- **Frame caps are consistent by derivation.** Request cap 4 MiB; response cap 17 MiB, from a measured worst-case expansion of 4.01×. An in-cap request can never produce an over-cap response, and a test pins it.
- **The delegated wrapper catches the whole `BamlValidationError` family**, with `BamlWorkerError` first, and #27 outcomes are listed for every caller site.
- **Claude's r5 notes folded in:** `-I -S`, absolute `sys.path` only, and the #26 bridge exclusion, among others.

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
  - A second `init`, or any op before `init`, is answered with a `fault`.
  - The test-only ops (`env`) and the prctl-off flag are honoured only when `init` carries `"test_mode": true`, which only `_reset_worker_for_tests(test_mode=True)` sets. A tripwire asserts that no `src/` caller sets it.
- **Protocol.**
  - One JSON object per line, encoded as UTF-8 with `ensure_ascii=True`, over binary pipes.
  - Requests come in on stdin. Responses go out on a dup of fd 1, taken before fd 1 is pointed at stderr.
  - Every request carries a monotonically increasing `id`, continuing across restarts, which the response echoes.
  - A response has exactly the keys `{id, fingerprint, <one of ok|error|request|fault>}`.
- **Faults.** Any exception in an op, including `BamlPanic`, is caught with `BaseException` and returned as `fault`. The client then discards and kills the worker.
- **Environment normalization.** The worker gets its allowlist key set in argv. Before importing `baml_bridge`, it deletes every env key outside that set. This covers C-locale coercion's `LC_CTYPE` (spike: `['LC_CTYPE', 'PATH']`) and `__PYVENV_LAUNCHER__`. Tests read the environment **inside** the worker.
- **Working directory.** The worker runs in the fixed directory of the installed `phase_loop_runtime` package (`cwd=` on `Popen`), never the caller's cwd. That directory is trusted, and it stays removable on Windows.

### Owner death: one kernel- or OS-level mechanism per platform, stated exactly as tested
| Platform | Primary mechanism (works while the worker is hung in a native op) | Secondary | Tested where |
|---|---|---|---|
| **Linux** (glibc, musl) | `prctl(PR_SET_PDEATHSIG, SIGKILL)` via `ctypes.CDLL(None, use_errno=True)`. That form works on musl, where `find_library("c")` / `libc.so.6` do not. After the prctl, the worker re-checks `getppid()` against the owner pid in argv. PDEATHSIG fires when the forking **thread** exits, so the worker is spawned only from the client's long-lived spawner thread | `getppid` watchdog thread (every 0.5 s). Stdin EOF is **not** relied on, because fork children may hold the write end | CI pytest (Linux) and verification step 6 (musl). The step-6 containers run with **`docker run --init`**, so an orphaned worker is reaped and the "gone within 3 s" check never sees a zombie. The check also treats a zombie state (`Z` in `/proc/<pid>/stat`) as gone |
| **Windows** | **Job Object** with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, created by the parent through `ctypes` (`CreateJobObjectW` → `SetInformationJobObject(JobObjectExtendedLimitInformation)` → `AssignProcessToJobObject`). The job handle is non-inheritable and held only by the `_Client`. When the owner dies, its last handle closes and the kernel kills every process in the job, even a worker hung inside a native op. **To avoid the venv redirector**, the worker is started with `sys._base_executable` (the real interpreter; `sys.executable` elsewhere), so the process in the job is the worker itself, not a launcher whose child could escape. The venv's `site-packages` still resolve, because `init` carries the parent's `sys.path`. **Ordering:** the parent assigns the job **before** it sends `init`. Until `init` arrives the worker only blocks on stdin, so if the owner dies before assignment, the worker exits on that idle EOF. There is no window in which a hung worker is outside the job | stdin EOF when idle. `getppid` is **not** used on Windows: it does not change when the parent exits | the pre-merge `windows-latest` dispatch run, required by the acceptance criteria. The owner is killed (`TerminateProcess`) while the worker is inside a 30 s hostile `baml.sys.sleep`, and the worker must be gone within 3 s. A second assertion checks that the worker process is in the job (`IsProcessInJob`) |
| **macOS** | `getppid` watchdog thread. On POSIX the worker is reparented when the owner dies, so `getppid` changes. This needs the GIL. **Verified that the GIL is released during all three real ops**, not only during `baml.sys.sleep`: watchdog ticks were 45/46 during a 232 ms `parse_closeout` of a 1.8 MiB input, 113/124 during a 619 ms `closeout_request` with 40 k owned files, and 6/6 during a 31 ms `evidence_request` with a 2 MiB sample. That was measured on Linux against the same PyO3 build source | none. Stdin EOF is not relied on | the pre-merge `macos-14` and `macos-15-intel` dispatch run (`macos-13` is being retired; if `macos-15-intel` is unavailable, macOS x86_64 is listed as unverified): owner SIGKILL while the worker is in the hostile sleep, worker gone within 3 s. **Residuals, disclosed:** (1) **`initialize_runtime` holds the GIL for about 0.8 s** (measured: 1 watchdog tick in 788 ms), so during init the watchdog cannot run. An init that hung forever *after the owner died* would orphan the worker on macOS. While the owner lives, the spawn/init deadline kills it. (2) A future native op that held the GIL would delay the watchdog in the same way. There is no macOS kernel equivalent of PDEATHSIG |

The worker also runs in its own session or process group (`start_new_session=True` on POSIX, `CREATE_NEW_PROCESS_GROUP` on Windows), so a terminal Ctrl-C or a `killpg` aimed at the runner does not kill it.

### Launch and environment
- **Command.** `Popen([<interpreter>, "-I", "-S", <path of _baml_worker.py>, <owner pid>, <allowlist keys>], stdin=PIPE, stdout=PIPE, stderr=<temp file>, env=_worker_env(), cwd=<package dir>, close_fds=True, start_new_session=True)`, where `<interpreter>` is `sys._base_executable` on Windows and `sys.executable` elsewhere.
  - `init` carries the parent's `sys.path` and the rendered file map. Only absolute `str` entries are kept; `""` and relative entries are dropped, so they cannot resolve against the worker's cwd.
  - `-S` stops the base installation's `site` from running its `.pth` hooks. Imports come only from the carried absolute path list (claude r5 N2).
  - Imports follow the parent's trust domain; `-I` isolates the environment, not imports.
- **`_worker_env()` allowlist:**
  - `PATH=<directory of the interpreter>`;
  - `SYSTEMROOT`, `WINDIR`, `TMPDIR`, `TMP` and `TEMP` when set;
  - **the dynamic-loader variables `LD_LIBRARY_PATH` (Linux) and `DYLD_LIBRARY_PATH` / `DYLD_FALLBACK_LIBRARY_PATH` (macOS), when set.** Shared-libpython installs need them to start the interpreter at all (claude r4 Q4). They affect only library resolution and carry no credentials;
  - **everything else is excluded**, including `HOME`, `BAML_*`, `BOUNDARY_*`, `OPENAI_*`, `ANTHROPIC_*`, `*_API_KEY`, `PYTHON*`, proxies and locale variables.

### Ownership
- Only our client holds the worker's stdin, and the worker loads exactly the map it is sent.
- The worker echoes `fingerprint = sha256(canonical JSON of the rendered map)`, computed from what it loaded.

### Sources and argument snapshots (codex B2, claude r4 Q8)
- **Per process:** the rendered file map and its fingerprint are computed **once per process**, on first use, and held in the `_Client` (below). Every worker, including every respawn, is initialized from that same snapshot. It is cleared only by `_reset_worker_for_tests()` (as v0's `lru_cache` on `_runtime` behaved). The regex readers behind D1a / `export_function_schema` read the same snapshot, so the worker and the Python-side schema cannot diverge mid-process.
- **Per call:** `_worker_call(op, args)` serializes the request body **once** (`json.dumps(args, ensure_ascii=True, sort_keys=True)`) and captures the expected fingerprint **once**. Every attempt in the retry budget sends a frame whose **body bytes are identical**, and that **differs only in the monotonic `id`** (claude r5 N6), to a worker initialized from exactly that snapshot. A retry therefore cannot answer from different sources or different arguments.
- **Pinned:** recovery-parity tests for all three production ops against the real runtime. The first worker is killed mid-call, and the retried answer must be byte-equal to a healthy single call's answer.

### Client state: one `_Client` object; the fork handler closes nothing (claude r5 B1, codex r5 B2)
- **All client state lives in one `_Client` instance**, referenced by the module-level `_CLIENT`. It holds:
  - the request lock;
  - the worker slot;
  - the spawner thread with its hand-off queue, events and generation counter;
  - the writer thread, the daemon reader thread and their queues;
  - the `Popen` and its file objects;
  - on Windows, the Job handle;
  - the source snapshot;
  - the fault log.
- **`_Client.__init__` only allocates.** It creates locks, queues and events. It starts no thread, does no I/O and takes no snapshot.
  - Spawner, worker and snapshot are created lazily, inside the `_Client`, under its own lock.
  - **`_CLIENT = _Client()` runs at import**, so first use needs no module-level lock and two threads cannot race to create two clients. **There is no module-level lock or primitive at all.**
- **The at-fork child handler does exactly one thing:** `_CLIENT = _Client(retain=_CLIENT)`.
  - It closes nothing and touches no fd.
  - `retain` only stores a reference to the predecessor, so the stale object is never finalized in the child. Finalizing it would close its `BufferedReader`, whose internal lock may have been held by the parent's reader thread at fork time.
  - The chain is one object per fork generation.
  - Because the handler only allocates, it is safe in `Popen(preexec_fn=…)` children, where `PyOS_AfterFork_Child` runs it before `_posixsubprocess` sets up the child's stdio. It cannot close a reused descriptor or a new child's pipes or errpipe.
- **The recorded-fd-integer machinery is deleted.**
- **Consequence: a fork child leaks the parent-worker pipe fds it inherited.** State and justification:
  - **How many:** a handful per fork. That is the parent worker's stdin write end and stdout read end, plus at most one in-flight spawn's 3 pipe pairs if the fork lands inside `Popen`.
  - **Exec'd children never hold them.** Python creates these pipes non-inheritable (PEP 446 `O_CLOEXEC`), and `close_fds=True` is the default. So a fork child that execs (`subprocess`, `multiprocessing` spawn/forkserver) drops them.
  - **Owner death does not depend on these fds.** It is kernel- or OS-enforced (PDEATHSIG / Job Object / watchdog, as in the table), so a fork child holding the parent worker's stdin write end cannot keep that worker alive after the parent dies. **Stdin EOF is no longer load-bearing anywhere on POSIX.** On Windows, `os.fork` does not exist, so the pre-assignment EOF path still holds there.
  - **Graceful parent exit:** if the parent exits while a fork child still holds the stdin write end, the parent's `atexit` close-stdin step does not produce EOF. The bounded wait (5 s) then ends in kill. That costs at most 5 s at exit.
- **Spawn ownership protocol** (codex r5 B3):
  - Every spawn request carries a **generation token** from the `_Client`'s counter. The caller waits on the hand-off under the per-call deadline.
  - **On timeout, the caller abandons its token and replaces the spawner:** a fresh spawner thread with a fresh queue. Later calls therefore never queue behind a hung `Popen`. The call raises `BamlWorkerError(kind="spawn")`.
  - **When an old spawner returns late**, it checks its token under the `_Client` lock before publishing. If the token was abandoned, it kills its process, reaps it, closes its pipes and drops the Job handle. It never publishes, and it records one fault-log entry (`kind="spawn_late"`).
  - On Windows, **a failed `AssignProcessToJobObject` kills the new worker and raises `kind="spawn"`.** A worker is never published outside a job.
  - A dead spawner thread is recreated on the next request.
- **Bounded IPC:** one deadline covers spawn, send and receive. Writes go through a writer thread. The daemon reader uses `readline(MAX_RESPONSE_BYTES + 1)`.
- **Serialization errors:** a `TypeError` from `json.dumps(args)`, or a lone surrogate in the arguments, raises a plain `BamlValidationError` in the parent before anything is sent. It is not retried (claude r5 N9).
- **Frame caps are consistent by derivation** (codex r5 B1, claude r5 B2). They are content errors, not transport faults.
  - `MAX_REQUEST_BYTES = 4 MiB` for every op. It is checked on the serialized request frame before sending, and exceeding it raises a plain `BamlValidationError` with the worker untouched and no retry.
  - `MAX_RESPONSE_BYTES = 4 × MAX_REQUEST_BYTES + 1 MiB = 17 MiB`.
  - **Derivation, measured** on the real runtime (round-5 addendum). The response/request frame ratio in the worst case, all-backslash or all-quote payloads, is **4.00 for `evidence_request`, 4.01 for `closeout_request` and 1.00 for `parse_closeout`**. The other shapes (astral, BMP, control characters, ASCII) are at most 1.5. The fixed template overhead is at most 5.4 KB.
  - So **an in-cap request cannot produce an over-cap response**: 4.01 × 4 MiB plus 5.4 KB is less than 17 MiB. This is pinned by a test that sends, for every op and every pathological shape, a request sized just under the cap and asserts the response fits under the response cap.
  - The response cap therefore fires only on a misbehaving worker. It is then treated as `BamlWorkerError(kind="framing")`: discard, kill, and retry per budget. It is not a content error.
  - **Realistic inputs are far below the request cap.** Tier-3 samples are capped at `max_sample_bytes` (8 KiB by default). The runner's closeout parse sends `json.dumps(<extracted closeout object>)`, not the executor log. A launch prompt's plan lists are KB-scale.
- **`atexit`** acts only when `os.getpid()` equals the owning pid. It closes stdin, waits 5 s, then kills; on Windows it also closes the job handle.

### Failure semantics
- **`BamlWorkerError(BamlValidationError)`**, with `.kind` in {`spawn`, `init_fault`, `died`, `timeout`, `desync`, `framing`, `fingerprint`, `fault`} and `.rc` set only when the worker is known dead. It is raised only for transport and liveness faults. Content verdicts, the frame caps and names outside the bridge table raise a plain `BamlValidationError`.
- **Any `BamlWorkerError` discards and kills the worker.**
- **Retry budget:** at most 2 retries of a `BamlWorkerError`, each on a fresh worker built from the **same** snapshot with the **same** request bytes. Content errors are never retried.
- **Idle death** (the worker died between calls): the pre-send liveness check records it once, restarts, and proceeds. This is not a retry and does not consume the budget. The call's answer is the healthy answer.
- **`worker_fault_log()`** records **one entry per actual worker death or kill**: kind, rc, stderr tail, timestamp. It also emits a `logging.warning`.
- A `KeyboardInterrupt` or any other `BaseException` in the parent during spawn, write or wait kills and discards the worker, then re-raises unmapped.
- The parent never imports `baml_bridge`.

### Cost
- **Latency:** cold start about 755–839 ms, once per process; about 3 ms per call after that. On the launch path the first launch pays about 0.8 s.
- **Memory:** about 281 MB resident after `initialize_runtime` (v0 in-process: about 21 MB). This is the v1 runtime's own cost, and it is disclosed (#25).

## Caller handling of `BamlWorkerError` (claude B1, B2; code-read on main `b687e311`)

| Call site | Enclosing function and path to the CLI | Durable state written before the call | Can a sibling executor be live? | Rev-4 handling |
|---|---|---|---|---|
| Closeout parse: `runner._parse_native_closeout_status` → `discovery.parse_closeout_payload_doc` → `parse_baml_response("EmitPhaseCloseout")` (runner.py around line 10466) | `_parsed_child_automation` (around 10389). It is called after `launch_with_spec` returns: from `run_loop` (around 3924, serial and wave finalize after `run_phase_worker_pool` has joined), `launch_delegated_child` (around 5404/5446) and the lane helpers (around 10616/10962) | The executor has **finished**. Its output is in the launch artifacts (log). The phase status is still the launch-time status | No. Serial: one executor, already exited. Wave: the pool has joined every job before finalization | **Today `except BamlValidationError` maps to `automation_status=blocked`, `blocker_class=contract_bug`, "BAML closeout validation failed"**, a durable invalid-closeout verdict. Rev 4 adds `except BamlWorkerError` **before** it, after the bounded retries, and maps to `automation_parse_error` with `blocker_class="unretryable_external_outage"` (existing frozen vocabulary; no new term). The summary reads `"closeout NOT evaluated: BAML worker <kind> (rc=<rc>) after 3 attempts; executor output preserved at <log>"`. **No claim is made that a re-run re-parses the preserved output.** A re-run applies the runner's existing handling for a blocked phase, which may relaunch the executor; the preserved log is there for inspection, `human_required=false`. It is **never** `contract_bug` and never a verdict on the closeout content. It goes through the same code path v0 used for a parse error, so wave teardown and branch preservation behave exactly as they did for v0 parse errors. It does not propagate, because propagating out of wave finalization would run the wave `finally` (around runner.py 5006), which reclaims worktrees not in `preserve_branches`, i.e. it could discard sibling phases' completed work. **#27:** only an extracted closeout object over 4 MiB can hit the cap. That is an absurd closeout, and it is genuinely a content problem, so the plain `BamlValidationError` takes the existing `contract_bug` mapping with the summary naming the cap. Nothing propagates |
| Tier 3: `evidence_audit.evaluate_suspected_fake_evidence` → `build_baml_request("EvaluateSuspectedFakeEvidence")` (around line 905) | `run_evidence_audit` loop (around 845) → the runner's closeout evidence gate | The executor has finished. The Tier-2 findings are in memory | No (post-launch) | **Today every exception becomes `_uncertain_fallback` → verdict `uncertain` → `tier3_judgment_blocker` returns `None`**, a warning only. That is fail-open. Rev 4: `evaluate_suspected_fake_evidence` re-raises `BamlWorkerError`, placed before its `except (…, ValueError, …)`. The loop at around line 845 catches `BamlWorkerError` **before** `except Exception` and sets `blocker = {"human_required": False, "blocker_class": "unretryable_external_outage", "blocker_summary": "Tier 3 evidence audit NOT run: BAML worker <kind> after 3 attempts"}`. The closeout is blocked, **never skipped**, and never judged fake. Other Tier-3 call errors (HTTP down, and so on) keep v0's `uncertain` policy; that is unchanged and out of scope. **#27:** the cap is unreachable with default inputs (sample at most `max_sample_bytes`, 8 KiB). If it were hit, the plain `BamlValidationError` would take v0's content-error path (`uncertain`), exactly as v0 treated a `BamlValidationError` from `build_request_sync` |
| Launch prompt, serial: `run_loop` → `build_prompt` (around runner.py 3312) | `run_loop` → `cli._main` (cli.py around 1852). No handler in between (dispatch-lock handler around 1488 only; the `ValueError`/`Exception` handlers around 1318–1381 run before dispatch) | The phase selection event may have been emitted; nothing is launched | No. Launch follows the prompt build | `BamlWorkerError` propagates after the bounded retries. `phase-loop run` exits non-zero with the typed error. The dispatch lock is released by its context manager with **no live executor**. No verdict is written (#22). **#27:** a plain `BamlValidationError` (prompt over the cap) propagates in the same way: typed, nothing launched |
| Launch prompt, concurrent wave: `_dispatch_concurrent_wave` → `_prepare_phase_launch` → `build_prompt` (around 4703 → 3312) | Inside the wave `try:` (around 4785). Its `finally` (around 5006) reclaims prepared worktrees | Worktrees were created for the phases prepared so far. **No job has started**: `run_phase_worker_pool` runs only after every phase is prepared | **No.** All prompts are built before the pool starts | Propagates. The `finally` reclaims only freshly created, unlaunched worktrees, so no work can be lost. The dispatch lock is released with no live executor. **#27:** the same, for a plain `BamlValidationError` |
| Delegated child: `launch_delegated_child` → `build_prompt` (around 5253) | Called from `run_loop` around 4059, in the `automation_status == "delegated"` branch, after the **parent executor has exited** | The parent's closeout has been parsed. **The parent's phase status is NOT yet persisted**: `set_phase_status(...)` runs after `launch_delegated_child` returns (around 4121) | No. The parent has exited, and the child has not launched | Propagating would abort the run before the parent's result is recorded. So the `launch_delegated_child(...)` call in that branch is wrapped to catch **the whole `BamlValidationError` family**, with `except BamlWorkerError` first and `except BamlValidationError` second. Both route into the **existing** blocked-outcome flow of the branch (`status_after_launch = "blocked"`, persisted by the same `set_phase_status` call), with distinct summaries: (a) a worker fault gives `blocker_class="unretryable_external_outage"` and "delegated child NOT launched: BAML worker <kind> after 3 attempts"; (b) a content limit (#27) gives `blocker_class="contract_bug"` and "delegated child NOT launched: closeout contract render refused (<reason>)". The child is never launched, and the parent's result is always recorded. The revision-5 claim that a plain `BamlValidationError` "cannot occur" on this path was false, and is withdrawn |
| Harness lane: `launch_harness_lane_work_unit` → `build_prompt(harness_lane_assignment=…)` → `build_lane_prompt_bundle` (around 5961) | A library entry point. `git grep` finds **no `src/` caller**; only tests and external callers use it | Pipeline diagnostic only | Callers may run lanes in parallel. This function launches **one** unit, and its prompt build precedes its own launch | Propagates as `BamlWorkerError`. It is not converted to a lane verdict; there is no broad handler in this function. **#27:** a plain `BamlValidationError` propagates in the same way. Test: the lane entry point, with a failing worker and separately with an over-cap prompt, raises the typed error and spawns nothing |

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
| 24 | **New causes for `BamlValidationError`** (all retries within one call use one source snapshot and identical request bytes): the worker can die, time out, desync or fault, independent of the input (claude B1) | **Typed and routed**: `BamlWorkerError` subclass; bounded retries (at most 2) on a fresh worker for pure ops; a death between calls is recorded, not charged; each caller maps it to **"not evaluated"**, never to a content verdict and never to a skip (caller table) | real-worker tests: kill between calls and mid-call while driving the discovery closeout parse, the runner native-closeout path and the Tier-3 build; assert the caller outcomes in the table and the `worker_fault_log()` counts |
| 25 | **Memory**: the v1 runtime is about 240 MB resident (worker ~281 MB after init), against ~21 MB added by v0 in-process | **Accepted**, disclosed (CHANGELOG, D6 risk list); inherent to v1 | test: the worker's VmRSS after init is recorded in the verification log (Linux); no threshold is asserted, because the number is informative |
| 26 | **Adoption-bundle digests.** `adoption_bundle._schema_refs` hashes the RAW bytes of every `baml_src/*.baml` (around `adoption_bundle.py:151`). `fmt` and the syntax edits change 8 digests. **`phase_loop_bridge.baml` is excluded from `_schema_refs`**: it is host glue with no classes, so glue edits never force downstream refreshes (claude r5 N11; a one-line filter in `adoption_bundle.py`). A vendoring repo's committed adoption bundle therefore reports `stale` until `adoption-bundle refresh` | **Accepted**, disclosed (CHANGELOG: "downstream repos run `phase-loop adoption-bundle refresh` after upgrading"). This was not found in revision 4; claude r4 asked to confirm nothing hashes raw `.baml` bytes | test: on this tree, `check_adoption_bundle` of a freshly refreshed bundle is `fresh`, its `schema_refs` equal the 8 schema files, and it has **no** bridge ref. Editing the bridge file leaves it `fresh` |
| 27 | **Request cap** (new observable limit): a serialized request over 4 MiB raises a plain `BamlValidationError` before sending. The 17 MiB response cap is derived from it so that it can never fire on an in-cap request, and it is treated as a worker framing fault. Per-site outcomes are in the caller table's #27 column | **Accepted**. v0 had no cap. Real inputs are KB-scale (Tier-3 samples at most 8 KiB; the runner parses the extracted closeout object, not the log) | derivation test (every op × pathological shapes); per-site #27 tests, including a **real** cap failure on the delegated path |

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

- **Script.** `phase-loop-runtime/tests/data/baml_v0_baseline/capture_v0.py` runs one time, in a baml-py 0.222.0 venv against a clean `origin/main` worktree. It runs **under the same sentinel environment as the #15 test, with every real credential variable unset** (claude N7). The goldens then also show that v0 was env-independent, and no developer key can ever land in a committed golden. **Disposition decided before capture** (claude r5 N5): the round-2 spike already ran v0 with these sentinels set and found its evidence request byte-equal to the sentinel-free v1 request. If the capture nevertheless finds a sentinel in any v0 golden, the script **aborts without writing**, and the finding goes to the lead as a new register row. No golden containing a sentinel is ever committed. It is not collected by pytest, and a provenance header records the main SHA and the baml-py version. It writes:
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
  - the owner-death mechanisms from the platform table: PDEATHSIG on Linux (`ctypes.CDLL(None)`); the `getppid` watchdog on POSIX (Linux, as a secondary, and macOS); none inside the worker on Windows, where the parent's Job Object enforces it;
  - `ensure_ascii` framing;
  - `__main__`-only side effects.

### `phase-loop-runtime/src/phase_loop_runtime/baml_modular.py` (modify)
- **Add:**
  - `class BamlWorkerError(BamlValidationError)` with `.kind` and `.rc`;
  - **one `_Client` class holding all client state:** lock, slot, spawner thread and hand-off, generation counter, writer and daemon reader threads, `Popen`, file objects, the Windows Job handle, the source snapshot and the fault log. It is referenced by `_CLIENT`. `__init__` is allocation-only, and a `retain` reference keeps predecessors alive after fork;
  - the spawn ownership protocol: generation tokens, spawner replacement on timeout, and late-spawn self-disposal;
  - the Windows Job Object helper (ctypes) and the `sys._base_executable` launch;
  - `_worker_env()` (`_filtered_env` given a real job);
  - the module slot plus lock;
  - `os.register_at_fork(after_in_child=lambda: <_CLIENT = _Client(retain=_CLIENT)>)`. It is allocation-only, closes nothing, and touches no fd;
  - `_CLIENT = _Client()` at import. There is no module-level lock;
  - the pid-guarded `atexit`;
  - `_worker_call(op, args)`: a per-call snapshot (request bytes plus expected fingerprint) reused across the bounded retry (at most 2, transport and liveness faults only);
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

### `phase-loop-runtime/src/phase_loop_runtime/adoption_bundle.py` (modify; #26)
- `_schema_refs` skips `phase_loop_bridge.baml`, because it is host glue and not a schema.

### `phase-loop-runtime/scripts/_gate_a_probe.py` (modify; release-notes (f))
- **Replace** the `baml_py` resolution block (around line 44) with: `importlib.metadata.version("baml-bridge") == "0.20.1"`, followed by a real `parse_baml_response("EmitPhaseCloseout", <valid>)` through the worker. It then asserts that `baml_bridge` is not in the probe's `sys.modules`.
- This probe runs in the PR wheel smoke and in Gate A. It is a script, so it is outside the agy pin set.

### `.github/workflows/publish-pypi.yml` (modify; release-notes (f))
- In the release-wheel smoke heredoc (around line 93), add the same version assertion and a real parse through the worker.

### `.github/workflows/test.yml` (modify; D3 and release-notes (e))
- New job `baml-sources`: `ubuntu-latest`, Python 3.12, `pip install ./phase-loop-runtime`. Steps:
  1. Download `baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz`.
  2. `sha256sum -c` it against the published `.sha256` **and** against the literal `6067729f14483eca4ab61bfcd3c1921818e9ecc66da035bc64fbbfeb850e2795`.
  3. Check that `baml-cli --version` is `baml-cli 0.20.1` **and** equals `python -c "import baml_bridge as b; print(b.get_toolchain_version())"` (release-notes item (e); claude r5 N4). The job installs the package, so the bridge is present.
  4. Run `(cd phase-loop-runtime/src/phase_loop_runtime && baml-cli --agent-skill-check off fmt baml_src/*.baml)`, then `git diff --exit-code`. This works on the raw sources (spike §6).
  5. Copy the raw sources into a temp project with a minimal `baml.toml` and run `baml-cli check`. Then write the rendered `_read_baml_files()` map to a second temp project and `check` that too. Both runs must print `Finished checked 9 file(s)`, asserted with `grep -q` (the elapsed-time suffix varies).
  - Every step runs with `shell: bash` and `set -euo pipefail`, so `baml-cli`'s own exit status is also asserted; the Actions default `bash -e` lacks pipefail (claude N6).
- The job has no `if:`. Add it to the `gate` job's `needs`, add `BAMLSRC: ${{ needs.baml-sources.result }}`, and make the gate `exit 1` unless that result is `success`. `gate` runs `if: always()`, and a skipped job satisfies a required check, so this explicit check is what makes the job blocking.

## Tests

New file: `tests/test_phase_loop_baml_v1_runtime.py`. It uses the real worker and real runtime with no stubs. Any test that swaps sources calls `_reset_worker_for_tests()` in teardown.

- **Parity against the Step 0 goldens:**
  - the parse corpus is identical except the flagged `pix_2p70`, which is asserted `null`. **Content errors assert `type(e) is BamlValidationError`, never the subclass.** The whole corpus must be served by **one** worker pid with `worker_fault_log()` unchanged, so an input that surfaces as a worker `fault` fails parity instead of passing as a subclass (claude r4 Q1);
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
- **Worker faults** (codex B3; each case runs in a subprocess that must exit 0; assertions use `.kind` and `.rc`, never message text). The tests are split so that none contradicts the recovery contract:
  - **IDLE death, the recovery contract.** Between two calls, kill the idle worker, three ways: SIGKILL; the spawn hook; and a native `os._exit` by the hostile bridge on a *previous* call. The next call returns the **correct** answer on a new pid. `worker_fault_log()` gains **exactly one** entry for that death. The retry budget is untouched.
  - **IN-FLIGHT fault with retries forced to 0.** A hostile bridge sleeps via `baml.sys.sleep`, and the worker is SIGKILLed after 0.5 s. The call raises `BamlWorkerError(kind="died", rc=-9)`. The log gains one entry.
  - **IN-FLIGHT fault within the retry budget.** The same kill happens on attempt 1 only; the test harness kills only the first worker pid. The call returns the correct answer, byte-equal to a healthy call. The log gains exactly one entry, one per actual death.
  - **Retry-budget exhaustion.** Every attempt's worker is killed mid-call (a hostile bridge that always sleeps, plus the harness kill). There are 3 attempts, then `BamlWorkerError`, and the log gains **exactly 3** entries.
  - **Spawn hook, retries forced to 0.** The hostile `phase_loop_parse_closeout` does a detached failing `spawn`. Call 1 returns the correct result or `BamlWorkerError(kind="died")`, never a wrong answer. The worker exits rc 1 within 5 s. The log has **exactly one** entry (`rc == 1`). A **separate** test runs the same hook with the default budget and asserts one log entry per worker death that actually happened (checked against the set of pids started).
  - **Recovery parity for all three production ops** (codex B2). For `parse_closeout`, `closeout_request` and `evidence_request`, kill attempt 1 mid-call. The retried answer must be byte-equal to a healthy call's answer. The snapshot fingerprint and the request bytes (captured through a pass-through spy on the writer) must be identical across attempts.
  - **Timeout** (retries 0): `BamlWorkerError(kind="timeout")`, and the worker is gone.
  - **Blocked write** (scripted peer that never reads stdin; request larger than the pipe buffer): `BamlWorkerError(kind="timeout")` within the deadline, and the lock is free again.
  - **Spawn under the deadline:** the spawner is patched to block, and the call raises `BamlWorkerError(kind="spawn")` within the deadline. With the spawner thread killed (a test hook), the next call recreates it and succeeds. A spawn exception, such as a missing interpreter path, gives `kind="spawn"`.
  - **Framing** (scripted peers in `tests/fixtures/baml_worker_peers.py`): unterminated line plus EOF, non-JSON, JSON array, wrong id, wrong fingerprint, extra key, non-JSON `ok`. Each gives `BamlWorkerError` with the matching kind, and the peer is killed. **Caps:** see the frame-cap derivation test below.
  - **Broken source at init:** `BamlWorkerError(kind="init_fault")` at both entry points.
  - **In-BAML panic:** `BamlWorkerError(kind="fault")`, the pid is dead, and the next call succeeds on a new pid.
  - **Protocol:** an op before `init` gives a fault, and so does a second `init`.
  - **Fingerprint:** a mismatched map gives `kind="fingerprint"`.
- **Owner death, per platform, exactly as in the contract table.** The worker is inside a 30 s hostile `baml.sys.sleep` when its owner is killed, and it must be gone within 3 s (zombie-aware):
  - **Linux:** PDEATHSIG enabled; and separately, PDEATHSIG off (test flag) with the watchdog only. A further case calls from a short-lived pool thread that exits, and the worker must **survive** that exit, which pins the spawner-thread design.
  - **Windows** (dispatch run):
    - Kill the owner via `TerminateProcess`. The `IsProcessInJob` check runs **inside the owner process**, against the owner's own job handle, and is printed to the test's log. The test process itself never duplicates the job handle, which would keep the job open and void the test.
    - Also assert that the worker's image is `sys._base_executable`.
    - Run twice, **inside a stdlib `venv` and inside a `uv venv`**, so the redirector case this design exists for is actually exercised (claude r5 N1).
  - **macOS** (dispatch run): watchdog path.
- **Signals:** a `killpg` SIGINT to the runner's group leaves the worker alive (own session), and the next call uses the same pid. A separate test sends SIGINT to the parent pid mid-wait: the parent ends with an unmapped `KeyboardInterrupt`, the worker is killed, and no `BamlValidationError` is printed.
- **Environment inside the worker** (#15): sentinels for `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `ANTHROPIC_API_KEY`, `BAML_LOG`, `BAML_TRACE`, `BAML_HOME`, `BOUNDARY_API_KEY`, `BOUNDARY_PROJECT_ID`, `HOME` and `HTTPS_PROXY` are set in the parent. Then:
  - the test-mode `env` op returns the worker's `sorted(os.environ)`, which must be a subset of the allowlist, with `LC_CTYPE` absent;
  - both `BamlRequest`s equal their goldens;
  - no sentinel appears anywhere in them;
  - stdout and stderr are empty;
  - the worker's cwd is the package directory.
- **Callers of `BamlWorkerError`** (#24, the caller table). These are **in-flight faults with retries forced to 0.** Idle deaths are covered above and recover.
  - `discovery.parse_closeout_payload_doc` raises `BamlWorkerError`.
  - `_parse_native_closeout_status` gives `automation_parse_error` with `unretryable_external_outage`, never `contract_bug`.
  - **Downstream** through `_parsed_child_automation`, in both serial and wave finalize:
    - the phase is persisted as `blocked` / `unretryable_external_outage`;
    - no fallback (owned-dirty handling, #785 executor-exited handling) upgrades it to evaluated or complete;
    - sibling worktrees are untouched.
  - `run_evidence_audit` gives an `unretryable_external_outage` blocker, never an `uncertain`-only warning.
  - The serial `run_loop` raises, and the launch spy is never entered.
  - **Wave prepare** raises before `run_phase_worker_pool`. The wave contains one phase **already carrying preserved work** (in `preserve_branches`), and that branch and worktree must survive the `finally`. Only the freshly created, unlaunched worktrees are reclaimed.
  - The delegated branch records the parent as `blocked`, with the child not launched.
  - `launch_harness_lane_work_unit` raises and spawns nothing.
- **Structural handler tripwire** (claude r4 Q8, widened per r5 N11). An AST scan of **all of `src/phase_loop_runtime/**/*.py`**:
  - It finds every `try` whose body **directly calls** one of the BAML-reaching functions (`parse_baml_response`, `build_baml_request`, `parse_closeout_payload_doc`, `parse_closeout_payload`, `evaluate_suspected_fake_evidence`, `build_prompt`, `build_prompt_bundle`, `build_lane_prompt_bundle`, `launch_delegated_child`, `_parsed_child_automation`) and has a handler catching `BamlValidationError`, `ValueError`, `Exception` or `BaseException`.
  - Each such handler must be preceded by an `except BamlWorkerError` or be listed in `tests/data/baml_worker_handler_allowlist.json`, which records file, function, handler and reason.
  - The scan covers direct calls only, and says so. Deeper call chains are covered by the caller table and its tests.
- **Concurrency:** 8 threads from a cold `_CLIENT`, exactly one worker pid, all results equal, 60 s timeout.
- **Fork** (POSIX). The handler closes nothing, so each test asserts survival and progress, not closure:
  - **Fork while another thread holds the request lock** inside a 3 s hostile op. In the child, `_CLIENT` is a new object, the old one is reachable through `retain`, and the first call succeeds within its deadline on a new pid with a new spawner thread. In the parent, A's request completes and the same worker pid keeps serving.
  - **Fork during first-use `_Client` work**, i.e. during the lazy snapshot and spawner creation inside the import-time `_Client`, driven by a slowed snapshot. The child's first call succeeds within its deadline. There is no module lock to inherit, because none exists.
  - **Fork during a spawn after the pipes are created but before publication.** A pass-through spy on `Popen` sleeps after `Popen.__init__` returns, while the spawner is still unpublished. The child's first call succeeds within its deadline. The parent's spawn completes and is published normally.
  - **Fork after a discard, with an unrelated fd reusing the old number.** Kill and discard the worker, open an unrelated file (the test asserts it reuses the discarded worker's former stdin fd number), then:
    - `os.fork()`: in the child, the unrelated fd is still open and readable (same inode), and the child's first call succeeds within its deadline;
    - **`Popen(preexec_fn=lambda: None, ...)`** of a small script that writes to its stdout: the child runs and exits 0 with its expected output, which shows the at-fork handler did not touch its stdio or errpipe. The parent's unrelated fd is also intact.
  - **Owner death does not depend on the inherited pipes.** The parent starts a worker (inside a 30 s hostile sleep), forks a child that sleeps holding the inherited pipe fds, then the parent is SIGKILLed. The worker must be gone within 3 s while the fork child is still alive. This proves EOF is not load-bearing. Linux (PDEATHSIG) and the watchdog-only variant are both run.
- **Spawn ownership** (codex r5 B3), without any spawner-kill hook:
  - A pass-through spy delays `Popen` return by 3 s against a 1 s deadline. The call raises `BamlWorkerError(kind="spawn")`, and the spawner is replaced.
  - An immediate next call succeeds on a fresh worker within its deadline. It does not queue behind the hung spawn.
  - When the late `Popen` returns, its process is killed and reaped **by the old spawner**: the pid no longer exists within 2 s, it never answers any request, and the slot never holds it.
  - `worker_fault_log()` gains exactly one `spawn_late` entry.
  - Windows: an injected `AssignProcessToJobObject` failure raises `kind="spawn"`, and the created process is gone.
- **Frame-cap derivation** (#27): for each of the three ops and each shape (all backslash, all quote, astral, control, BMP, ASCII), build a request whose serialized frame is just under 4 MiB, send it to the real worker, and assert the response frame is under 17 MiB. That shows an in-cap request can never produce an over-cap response. A request just over 4 MiB raises a plain `BamlValidationError` (`type(e) is BamlValidationError`), is not sent, and leaves the worker untouched with the same pid. A scripted peer that emits an over-cap response gives `BamlWorkerError(kind="framing")`, and the peer is killed.
- **#27 per caller site**, with **real** cap failures, not mocks:
  - **Delegated path:** a delegation request whose plan lists push the closeout-prompt request frame over 4 MiB. The parent phase is persisted `blocked` with the `contract_bug` "closeout contract render refused" summary, and **no child is launched** (launch spy not entered).
  - Serial `run_loop` and wave prepare raise the plain type before launch.
  - The lane entry point raises and spawns nothing.
  - The runner closeout parse of an over-cap extracted object gives the existing `contract_bug` mapping.
  - `run_evidence_audit` with an over-cap sample (`max_sample_bytes` raised in the test) takes v0's `uncertain` content path.
- **Latency (#16):** a second call reuses the same worker pid and completes in < 250 ms.
- **Tripwires:**
  - after a full public call, `'baml_bridge' not in sys.modules`;
  - no `spawn` **statement** in any packaged `.baml`. The scan strips `//` comments and string or backtick-template contents first, so prompt prose that says "spawn" does not trip it;
  - `_read_baml_files()` output contains no `{{` or `{%`;
  - the #18 grep;
  - the #19 grep;
  - `_worker_env()` keys are a subset of the allowlist;
  - `import phase_loop_runtime._baml_worker` has no side effects: fds 1 and 2 are unchanged and no thread is started.
- **Platform guards:**
  - The fork, SIGKILL, `killpg` and PDEATHSIG tests are POSIX- or Linux-only, and skip with an explicit reason elsewhere.
  - The Windows owner-death test (Job Object) runs only on Windows, and the macOS watchdog test only on macOS, exactly as in the owner-death table.
  - The env test asserts, inside the worker, that `__PYVENV_LAUNCHER__` is gone.
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
- **Tests that patch sources or taxonomy** (claude r5 N8), e.g. by patching `_baml_src_dir`, `_read_baml_files`, `models.PHASE_STATUSES` / `BLOCKER_CLASSES`, or calling `_runtime.cache_clear()`, must now call `_reset_worker_for_tests()`, because the snapshot is per process. The implementer finds them with `git grep -nE "_baml_src_dir|_read_baml_files|PHASE_STATUSES|BLOCKER_CLASSES|_runtime\.cache_clear" tests/`, and each edit is **listed under the coverage rule as an edited test, not as unchanged**.
- **D3 strictness** (claude r5 N7): `_class_fields` already raises `BamlValidationError("unsupported BAML class field syntax …")` on any non-comment line it cannot match, and the D3 regex keeps that. A future attribute or union field therefore fails loudly instead of silently disappearing from export. A test pins it with `status: "a" | "b",`.
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
- **Pre-merge, and part of the acceptance criteria:** run verification step 3 once on GitHub-hosted `ubuntu-24.04-arm`, `macos-14`, `macos-15-intel` (`macos-13` is being retired; if `macos-15-intel` is unavailable, macOS x86_64 is listed as unverified) and `windows-latest` (in a stdlib venv and in a uv venv), via a throwaway `workflow_dispatch` on an unmerged scratch branch, with the platform guards above. Record the results in the PR.
  - **Re-dispatch requirement** (claude r5 N3): the run must be repeated on the final head **whenever `_baml_worker.py` or the `_Client` code changes** after the recorded run. A result from an older head does not count.
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
  - **the new `BamlWorkerError(BamlValidationError)`**: faults are retried at most twice on a fresh worker. After that, the closeout parse and the Tier-3 audit record a `blocked` / `unretryable_external_outage` "NOT evaluated" outcome instead of a verdict or a skip, and a launch fails typed. An in-flight worker fault that persists through the retry budget, i.e. the restarted workers also fail, can therefore abort `phase-loop run` before launch (#22, #24). A death between calls is recovered transparently and logged;
  - v1 source syntax;
  - the public API is unchanged;
  - **the closeout prompt text changed (D1)**; the envelope and the evidence request are unchanged;
  - **`injection.py` no longer launches with a fallback instruction when the closeout contract cannot be rendered (#22)**;
  - the fixed backslash crash (#10);
  - the pixel `null` (#12);
  - `baml` / `baml-cli` scripts are gone (#18);
  - platform coverage;
  - **vendoring repos must run `phase-loop adoption-bundle refresh` after upgrading**, because the raw `.baml` digests change (#26);
  - a 4 MiB request cap (plain `BamlValidationError`), with the response cap derived from it (#27);
  - `worker_fault_log()` as a new public diagnostic function;
  - fork children inherit and leak a handful of parent-worker pipe fds, which is bounded and harmless (the ownership section explains why);
  - owner-death guarantees per platform (the table) and the macOS residual;
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
- 7 `.py` files: `baml_modular.py`, `injection.py`, `runner.py` (the native-closeout `except BamlWorkerError` site, plus the delegated wrapper for the whole family), `evidence_audit.py` (two sites), `adoption_bundle.py` (the one-line bridge exclusion), the new `_baml_worker.py`, and `_gate_a_probe.py`;
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
  docker run --rm --init --network none -v "$vol:/venv" -v "$PWD:/w:ro" -w /w "$img" \
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
  - owner death per the platform table: Linux in CI and musl, Windows and macOS in the dispatch run; the worker survives a spawning-thread exit and a `killpg` SIGINT;
  - recovery parity for all three ops under a mid-call kill, with identical snapshot and request bytes across attempts;
  - idle-death recovery, in-flight faults at retries 0, and exact per-death log counts;
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
