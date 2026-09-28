# Detailed plan: migrate BAML v0 (baml-py 0.222) to BAML v1 0.20.1 (baml-bridge)

Tracking issue: agent-harness#1135. The spike evidence (commands, outputs, hashes) is in the issue body. This plan cites it and does not repeat it.

## Task

Replace the `baml-py>=0.222,<0.223` dependency of `phase-loop-runtime` with BAML v1 0.20.1. The v1 Python package is `baml-bridge==0.20.1` (import name `baml_bridge`). The `.baml` sources and `baml_modular.py` move to the v1 language and runtime. Every public behavior of `phase_loop_runtime.baml_modular` stays the same.

## Research summary

- **The runtime surface is small.** Only `baml_modular._runtime()` imports `baml_py`. Only two live paths reach the runtime:
  1. `discovery.py` → `parse_baml_response("EmitPhaseCloseout")` → `runtime.parse_llm_response`. This is the closeout path and it is critical.
  2. `evidence_audit.py` → `build_baml_request("EvaluateSuspectedFakeEvidence")` → `runtime.build_request_sync`. This is the tier-3 HTTP request.
- Everything else is regex over the `.baml` text and never touches the runtime:
  - schema export: `export_function_schema`, `_class_fields`, `_enum_literal_map`
  - class-name parses (`DotfilesAdoptionManifest`, `DotfilesRuntimeProjection`, `EvidenceJudgment`)
  - `render_baml_prompt`
  - the live `EmitPhaseCloseout` prompt, which `_render_emit_phase_closeout_prompt` renders in Python
- **v1 removed** `client<llm> {…}` blocks (E0010), `#"…"#` strings (E0098) and Jinja. Only `emit_phase_closeout.baml` and `evaluate_suspected_fake_evidence.baml` fail `baml check` as-is. The other six compile unchanged.
- **v1 replacements:**
  - `BamlRuntime.initialize_runtime(root, files)` replaces `from_files`. It is an in-memory, process-global singleton.
  - `Fn@spec(args).parse(raw)` replaces `parse_llm_response`.
  - `Fn@spec(args).build_request()` replaces `build_request_sync`.
  - Python reaches these through `baml_bridge.define_function("user.<fn>", "sync", params)`.
  - Returning v1 classes to Python needs a codegen typemap. Small BAML bridge functions that return only `string` / `map<string,string>` need neither a typemap nor codegen. Verified on py3.10 and py3.12, glibc and musl (agent-harness#1135 (a), (e)).
- **v1 parse coercion matches v0** on every probed input: single value to array, bad bool to null, missing field or non-JSON input is an error, markdown-fenced JSON is extracted.
- **Verified divergences the plan must neutralize:**
  1. The evidence request role is `system` in v1 and `user` in v0. Fixed with `${role("user")}`.
  2. v1 drops the `baml-original-url` request header.
  3. A compile failure raises `baml_bridge.errors.BamlPanic`, which is a `BaseException` and not an `Exception`.
  4. v1 renders `{% for %}` bodies without v0's blank lines.
- **CI installs with `pip install "./phase-loop-runtime[visual]"`** (`.github/workflows/test.yml:315`). The pyproject pin is what CI enforces; `uv.lock` hashes are advisory there.

## Public surface — frozen (no change in names, signatures or semantics)

`build_baml_request`, `parse_baml_response`, `export_function_schema`, `inject_schema_description`, `render_baml_prompt`, `BamlValidationError`, `PhaseLoopCloseoutV1`, `BamlRequest`, `ParsedResponse`.

`protocol.md` (both copies) names only these public symbols, so the protocol and contract docs need no change and **no new vocabulary is introduced**. The closeout field set and enum literals in `emit_phase_closeout.baml` are unchanged. Only the syntax around them moves.

## Decisions for the maintainer

- **D1 — who renders the `EmitPhaseCloseout` prompt.** **Recommend: keep the Python renderer.** Today the live prompt is rendered in Python, not by BAML, and it contains the custom `_closeout_output_format()` block with `schema_sha256`. v1 `@spec().prompt()` renders loops differently (no blank lines) and uses a different output-format block. Switching would change the prompt every executor sees and break the mirror and injection tests.
  - Acceptance: the Python-rendered prompt is **byte-identical** to v0 for the three golden payloads in agent-harness#1135 (b):
    - `578144449b…afa15`
    - `0097cdc81a…b6b5b4f`
    - `288057f433…277f6`
  - Alternative: render through the runtime and re-baseline every prompt test. Rejected here, because it is a prompt-behavior change that has nothing to do with the dependency bump.
- **D2 — codegen vs in-memory.** **Recommend: in-memory `initialize_runtime`, plus one packaged bridge file `phase_loop_bridge.baml` whose functions return only primitives.**
  - Codegen ships a 9.8 MB, 142-file `baml_sdk` (7.6 MB of bytecode) under the fixed top-level name `baml_sdk`. That name collides with any other v1 user in the environment. The bytecode also hard-fails on any bridge-version mismatch.
  - Trade-off: the bridge docstrings describe bytecode as the main SDK path, so in-memory is the less-travelled one. Mitigations:
    - the exact pin (D6)
    - a test that `_runtime()` compiles every packaged `.baml`
    - the real-runtime verification commands below
- **D3 — class-field syntax.** Legacy `name type` still compiles silently, but `baml fmt` rewrites it to `name: type,`, and that breaks `_class_fields`. **Recommend:**
  - make `_class_fields` accept both forms: one regex with an optional `:` and an optional trailing `,`;
  - migrate all eight files to the v1 form `name: type,` in the same change, so the sources are `baml fmt`-stable;
  - pin the `baml fmt` round trip with a test.

  Rejected: keeping legacy syntax, because it is one `fmt` away from a silent schema-export break.
- **D4 — coexistence.** v0 and v1 load together in one process (verified), so a dual-runtime shim is possible. **Recommend: hard switch, no coexistence.** The only runtime consumers are the two paths above, both inside this package. A shim would double the test matrix for no consumer benefit.
- **D5 — hash-enforced install in CI** (`pip install --require-hashes` or `uv sync --locked`). **Recommend: out of scope.** Track it as a separate issue. This plan updates `uv.lock`, but CI does not enforce it today.
- **D6 — canary risk.** Boundary calls 0.20.1 a canary. Dev builds ship almost daily. The toolchain's own bundled skill documents `Fn$parse`, which the 0.20.1 compiler rejects. **Recommend:**
  - pin exactly: `baml-bridge==0.20.1`;
  - record the PyPI wheel sha256s in `uv.lock`;
  - do not float.

  Alternative: wait for a non-canary v1 release. The maintainer asked for 0.20.1, so the plan proceeds, but the maintainer should confirm they accept a canary as the dependency under the closeout parser.

## Changes

### `phase-loop-runtime/pyproject.toml` (modify)
- `[project].dependencies` — modify — replace `"baml-py>=0.222,<0.223"` with `"baml-bridge==0.20.1"` (D6). The `baml_src/*.baml` package-data glob is unchanged; it also covers the new `phase_loop_bridge.baml`.

### `phase-loop-runtime/uv.lock` (modify)
- regenerate with `uv lock` — modify. The spike resolution was: **Removed** baml-py 0.222.0; **Added** baml-bridge 0.20.1 and protobuf 7.36.2 (new transitive dependency via `protobuf>=6.31.1`).
- Verify that the lock's baml-bridge wheel hashes equal the PyPI digests recorded in agent-harness#1135.

### `phase-loop-runtime/src/phase_loop_runtime/baml_src/emit_phase_closeout.baml` (modify)
- `PhaseLoopCloseoutClient` — modify — replace the `client<llm>` block with a value client:

  ```baml
  client PhaseLoopCloseoutClient = openai.GenericClient.new(model = "phase-loop-closeout", base_url = "https://example.invalid/v1");
  ```

  Neither v1 nor our Python sends to this endpoint. `default_role` has no v1 equivalent, and this function's request is never built by the runtime (D1).
- `EmitPhaseCloseout`:
  - `client X` → `client: X`
  - `prompt #"…"#` → ``prompt: `…` ``
  - `{{ phase_alias }}` → `${phase_alias}`
  - the two `{% for %}` loops → `${plan_produces.map((gate) -> { "- " + gate }).join("\n")}` and the same for `plan_owned_files`
  - `{{ closeout_commit_sha | default("none") }}` → `${closeout_commit_sha ?? "none"}`
  - `{{ ctx.output_format }}` → `${ctx.output_format()}`
  - Reason: E0010 and E0098.
  - Keep the three taxonomy placeholders (`{{ allowed_* | join(', ') }}`) as they are. `render_baml_prompt` substitutes them before compilation, so v1 never sees them.
- `PhaseLoopCloseoutV1` — modify — field syntax to `name: type,` (D3). The field names, types, optionality, comments and enum-literal comment blocks are unchanged.

### `phase-loop-runtime/src/phase_loop_runtime/baml_src/evaluate_suspected_fake_evidence.baml` (modify)
- `EvidenceAuditClient` — modify — `openai.GenericClient.new(model = "phase-loop-evidence-audit", base_url = "https://example.invalid/v1")`.
- `EvaluateSuspectedFakeEvidence` — modify:
  - same prompt syntax migration as above;
  - **the prompt begins with `${role("user")}`**, which restores v0's `messages[0].role == "user"` (verified). Without it, v1 sends a lone `system` message to a live OpenAI-compatible endpoint.
- `EvidenceJudgment` — modify — field syntax (D3).

### The other six `.baml` files (modify, syntax only — D3)
Files: `dotfiles_adoption_manifest`, `dotfiles_c4_document`, `dotfiles_plan_manifest`, `dotfiles_runtime_projection`, `dotfiles_task_catalog`, `verification_evidence`.

- Every class: field syntax `name type` → `name: type,`.
- Generate with `baml fmt`, then diff and confirm that only syntax changed.
- Keep the `// … enum literals:` comments byte-identical; `_enum_literal_map` parses them.

### `phase-loop-runtime/src/phase_loop_runtime/baml_src/phase_loop_bridge.baml` (create)
The bridge functions from agent-harness#1135 (a). They return only primitives, so Python needs no typemap or codegen:
- `phase_loop_parse_closeout(raw: string) -> map<string, string>` — `EmitPhaseCloseout@spec(...).parse(raw)`. It catches `baml.errors.ParseError` and returns `{"error": msg}`; on success it returns `{"ok": baml.json.to_string(v)}`.
- `phase_loop_evidence_request(tier2_signal_summary: string, sample_artifact_content: string, expected_artifact_characteristics: string) -> string` — `baml.json.to_string(EvaluateSuspectedFakeEvidence@spec(...).build_request())`.

This is a new file because the bridge functions are glue for the Python host and have no existing home. It ships through the existing `baml_src/*.baml` glob. `_class_exists` and `_function_return_type` regexes must not match it by accident, since it declares no classes.

### `phase-loop-runtime/src/phase_loop_runtime/baml_modular.py` (modify)
- `_runtime` — modify:
  - `from baml_bridge import BamlRuntime, define_function`
  - `BamlRuntime.initialize_runtime("baml_src", _read_baml_files())`
  - return the two `define_function("user.phase_loop_parse_closeout", "sync", ["raw"])` / `("user.phase_loop_evidence_request", "sync", [...])` callables
  - keep `lru_cache(maxsize=1)`
  - catch `BamlError` and `BamlPanic` (a `BaseException`) → `BamlValidationError`
- `build_baml_request` (runtime branch) — modify:
  - call the evidence-request bridge function with payload keys mapped positionally from the BAML signature;
  - `json.loads` the result into `BamlRequest(url, method, headers, body=json.loads(body), prompt=_extract_prompt(body))`;
  - the `EmitPhaseCloseout` short-circuit is unchanged (D1);
  - the arg-mapping source is the parameter list read by regex from the `.baml` function signature. It is not hardcoded, so a signature change fails loudly.
- `parse_baml_response` (runtime branch) — modify — the runtime branch is reached only for function names:
  - call `phase_loop_parse_closeout`;
  - `{"error"}` → `BamlValidationError`;
  - `{"ok"}` → `PhaseLoopCloseoutV1.model_validate(json.loads(...))`. The validators and `extra="forbid"` stay the final gate, exactly as today.
  - Any other function name that reaches the runtime branch raises `BamlValidationError("no v1 bridge for <fn>")`. Today only `EmitPhaseCloseout` reaches it, because the tail already coerces every result to `PhaseLoopCloseoutV1`.
- `_function_prompt_template` — modify — the regex matches ``prompt:\s*`(?P<prompt>.*?)`\n\}`` instead of `prompt #"…"#`.
- `_render_emit_phase_closeout_prompt` / `_render_baml_list_loop` — modify:
  - recognize the v1 loop expression `${<list>.map((<var>) -> { "- " + <var> }).join("\n")}`;
  - render it **with v0's exact whitespace** (per item `"\n- " + item + "\n"`, which reproduces v0's jinja body including the blank lines);
  - `${closeout_commit_sha ?? "none"}` → sha or `none`;
  - `${ctx.output_format()}` → `_closeout_output_format()`;
  - `${phase_alias}` → value;
  - after rendering, assert that no `${` remains, so fail-closed catches an unrendered construct;
  - acceptance: the D1 golden sha256s.
- `_class_fields` — modify — accept `name type` and `name: type,` (D3). The trailing `?` and `[]` handling is unchanged.
- `_type_modules` — delete — dead once `parse_llm_response` is gone.
- `_is_pyo3_panic` / `_raise_baml_validation_error` — modify — also map `baml_bridge.errors.BamlPanic` (checked by class module and name, so importing the module stays lazy).

### Tests (modify)
- `tests/test_phase_loop_baml_dependency.py`:
  - pin assertion → `"baml-bridge==0.20.1"`;
  - `test_baml_py_imports_after_install` → import `baml_bridge`, assert `BamlRuntime.initialize_runtime` exists and `baml_bridge.get_version() == "0.20.1"`;
  - add `baml_src/phase_loop_bridge.baml` to the packaged-file list.
- `tests/test_phase_loop_baml_modular.py` — the pyo3-panic test (it patches `_runtime` with a fake `build_request_sync`) → rewrite the fake to raise a `BamlPanic`-shaped `BaseException` from the bridge callable. Keep the assertion: a `BamlValidationError`, not an escaped `BaseException`.
- **add** (in `test_phase_loop_baml_modular.py`) real-runtime, unstubbed tests:
  - `_runtime()` compiles every packaged file;
  - `parse_baml_response("EmitPhaseCloseout", …)` on the spike's six inputs gives the v0-observed outcomes;
  - `build_baml_request("EvaluateSuspectedFakeEvidence", …).body["messages"][0]["role"] == "user"`;
  - the three D1 prompt goldens (sha256 of `build_baml_request("EmitPhaseCloseout", p).prompt`);
  - a `baml fmt`-shape `_class_fields` case (D3).
- `tests/test_phase_loop_baml_prompt_taxonomy.py` — keep. It tests `render_baml_prompt` on synthetic Jinja strings, which is our own pre-render syntax and still valid. Review each case; change none unless it reads a real `.baml` file.
- Run the named suites unchanged and treat any red as a finding, not a re-baseline:
  - `test_phase_loop_baml_{end_to_end,injection,runner_closeout,schema_export,schema_source}.py`
  - `test_phase_loop_skill_baml_closeout.py`
  - `test_phase_loop_terminal_summary_mirrors_baml_closeout.py`
  - `test_phase_loop_{adoption_bundle,closeout_hardening,dotfiles_schemas,dotfiles_sources,evidence_audit_tier3,plan_manifest,protocol_contract,runtime_projection,v22_e2e,v22_principles}.py`
- The implementer must diff the collected node list before and after. No test may disappear; disclose any that are rewritten.
- `tests/test_gate_a_wheel_isolation.py` names BAML only as a resolution-path probe, not the dependency, so it needs no change. Confirm it stays green.

## Documentation impact
- `CHANGELOG.md` — `[Unreleased]` — add. Entry "BAML v1 0.20.1 (agent-harness#1135)" covering:
  - `baml-py` replaced by `baml-bridge==0.20.1`;
  - new transitive dependency `protobuf`;
  - `.baml` sources moved to v1 syntax;
  - public API and live closeout prompt unchanged;
  - downstream code that imported `baml_py` through our dependency must declare it itself.
- `docs/reviews/2026-09-01-codebase-review.md` — no edit (historical record). Its C-8 note ("the `baml-py` pin is what keeps this safe") is superseded by the D3 dual-form regex and the `fmt` test; mention that in the CHANGELOG entry.
- `phase-loop-runtime/protocol/protocol.md` and `src/phase_loop_runtime/_contract_docs/phase-loop/protocol.md` — none. Only public, unchanged names are referenced (see the frozen-surface section).
- Skills bundle (`skills_bundle/*/SKILL.md`, `phase-loop-skills/**`) — none. They cite `EmitPhaseCloseout` in `emit_phase_closeout.baml` as the payload shape; that name, file and field set are unchanged.
- `README.md` / `phase-loop-runtime/README.md` / `docs/TEAM-ONBOARDING.md` — none; no BAML references.

## Release and agy-requalification consequences
- This PR changes `phase_loop_runtime/**/*.py` (`baml_modular.py`). Since agent-harness#1032, an ordinary runtime PR runs only `--route-core`, so the PR needs **no** agy requalification.
- **The next release cut does.** `publish-pypi.yml` blocks on the full pin set: `source_sha256` over every `phase_loop_runtime/**/*.py` in the agy qualification records. `baml_modular.py` is pinned there today (`plans/evidence/agy-1.2.*-linux-x64-qualification.json`, `"baml_modular.py": "3e9275e2…"`). The release that ships this must requalify both qualified agy images on the release-cut tree.
- Recipe: `scripts/qualify_gemini_heartbeat.py` with ops completion, cancel and owner-loss, then `--validate`, then regenerate the record in its existing shape and run `verify_qualified_agy_image.py --source-only`.
- Budget for observer repair: a launch-shape change can break the observer (the lesson from agent-harness#1067).
- A dependency change can alter behavior in downstream environments. The release notes must state the `baml_py` → `baml_bridge` swap. dev0 upgrades by reinstalling the release; there is no config change.

## Dependencies & order
1. Pin and lock (the `baml_bridge` import must resolve before anything else runs).
2. `.baml` syntax migration plus `phase_loop_bridge.baml`. Gate: `baml check` with CLI 0.20.1 is clean on the rendered set (Verification step 2).
3. `baml_modular.py` changes. `_class_fields` dual form lands **with or before** the class-syntax migration, or schema export breaks in between.
4. Tests.
5. CHANGELOG.

This is one PR and one bounded concern. There are 3 source files (`pyproject.toml`, `uv.lock`, `baml_modular.py`), 9 `.baml` files that are mechanical syntax, and 2 test files, so it is within the bounded-plan threshold.

## Verification
Run from `phase-loop-runtime/` in a fresh venv built from this tree, on py3.10 **and** py3.12. These exercise the real `baml_bridge` runtime and stub nothing:

```bash
# 1. Install exactly what CI installs; prove v0 is gone and v1 is the pinned build.
python -m pip install "./[visual]" pytest
python -c "import importlib.util as u, baml_bridge as b; assert u.find_spec('baml_py') is None; assert b.get_version()=='0.20.1'"

# 2. Compile the shipped sources as the runtime sees them (post render_baml_prompt), with the verified CLI.
#    CLI: gh release download baml-language-0.20.1 -R BoundaryML/baml -p 'baml-language-0.20.1-x86_64-unknown-linux-gnu.tar.gz*'
#         sha256sum -c *.sha256   # must print OK
python -c "from phase_loop_runtime import baml_modular as m; import pathlib; d=pathlib.Path('/tmp/bamlchk/baml_src'); d.mkdir(parents=True, exist_ok=True); [ (d/n).write_text(t) for n,t in m._read_baml_files().items() ]"
printf '[package]\nname = "bamlchk"\n' > /tmp/bamlchk/baml.toml
baml-cli --agent-skill-check off check --project /tmp/bamlchk          # "Finished checked 9 file(s)"
baml-cli --agent-skill-check off fmt --directory /tmp/bamlchk baml_src/*.baml && git diff --no-index --stat src/phase_loop_runtime/baml_src /tmp/bamlchk/baml_src  # fmt-stable modulo taxonomy render

# 3. Real-runtime behavior, no stubs.
python - <<'EOF'
import hashlib, json
from phase_loop_runtime import baml_modular as m
from phase_loop_runtime.baml_modular import BamlValidationError
ok='{"terminal_status":"complete","verification_status":"passed","dirty_paths":[],"produced_if_gates":["G"],"required_human_inputs":[]}'
assert m.parse_baml_response("EmitPhaseCloseout", ok).payload["terminal_status"]=="complete"
assert m.parse_baml_response("EmitPhaseCloseout", '{"terminal_status":"executed","verification_status":"passed","dirty_paths":"x","produced_if_gates":[],"required_human_inputs":[]}').payload["dirty_paths"]==["x"]
for bad in ["not json", '{"terminal_status":"complete"}', '{"terminal_status":5,"verification_status":"passed","dirty_paths":[],"produced_if_gates":[],"required_human_inputs":[]}']:
    try: m.parse_baml_response("EmitPhaseCloseout", bad); raise SystemExit(f"accepted {bad!r}")
    except BamlValidationError: pass
r = m.build_baml_request("EvaluateSuspectedFakeEvidence", {"tier2_signal_summary":"s","sample_artifact_content":"t","expected_artifact_characteristics":"u"})
assert r.url=="https://example.invalid/v1/chat/completions" and r.body["messages"][0]["role"]=="user", r.body
G={"578144449bebcc1ca7e237fe012b09d6b9f9226712d1aef65c5ce6ed030afa15":{"phase_alias":"P1","plan_produces":[],"plan_owned_files":[]},
   "0097cdc81a57d23d964c53b61e2cd7c4b5db65903c467c0be415e740ca6b5b4f":{"phase_alias":"P1","plan_produces":["IF-0-P1-1","IF-0-P1-2"],"plan_owned_files":["a.py"],"closeout_commit_sha":"abc123"},
   "288057f433fd2d598f59af9978bf1f97119984badfbad54940b81f0add4277f6":{"phase_alias":"P1","plan_produces":["IF-0-P1-1","IF-0-P1-2"],"plan_owned_files":["a.py"]}}
for h,p in G.items():
    got=hashlib.sha256(m.build_baml_request("EmitPhaseCloseout",p).prompt.encode()).hexdigest(); assert got==h,(h,got)
print("real-runtime OK")
EOF
```

The D1 goldens were captured on main `b687e311` with baml-py 0.222.0. They are only valid while the closeout taxonomy (`models.PHASE_STATUSES` / `BLOCKER_CLASSES`) is unchanged. If main changes the taxonomy before this lands, recapture them on the new main with v0 before switching.

4. Suites:
   - `python -m pytest -q tests/test_phase_loop_baml_*.py tests/test_phase_loop_skill_baml_closeout.py tests/test_phase_loop_terminal_summary_mirrors_baml_closeout.py tests/test_phase_loop_adoption_bundle.py tests/test_phase_loop_closeout_hardening.py tests/test_phase_loop_dotfiles_schemas.py tests/test_phase_loop_dotfiles_sources.py tests/test_phase_loop_evidence_audit_tier3.py tests/test_phase_loop_plan_manifest.py tests/test_phase_loop_protocol_contract.py tests/test_phase_loop_runtime_projection.py tests/test_phase_loop_v22_e2e.py tests/test_phase_loop_v22_principles.py tests/test_gate_a_wheel_isolation.py tests/test_phase_loop_discovery.py`
   - collect with `--collect-only -q` on main and on the branch and diff the node lists.
5. Wheel check: `python -m build --wheel` then `unzip -l dist/*.whl | grep baml_src/` lists all 9 `.baml` files, including `phase_loop_bridge.baml`.
6. musl smoke (the CI host has docker): run step 3 inside `python:3.12-alpine` against the built wheel.

## Acceptance criteria
- [ ] `pip install ./phase-loop-runtime` on py3.10 and py3.12 installs `baml-bridge==0.20.1` and not `baml-py`. Verification step 1 exits 0.
- [ ] Verification step 3 prints `real-runtime OK` on py3.10 and py3.12. This covers v0-parity parse outcomes, `messages[0].role == "user"` for the evidence request, and the three byte-identical closeout-prompt sha256 goldens.
- [ ] `baml-cli check` 0.20.1 reports 9 files clean on the rendered packaged sources, and `export_function_schema("EmitPhaseCloseout")` is equal (`==`) to its value on main `b687e311`.
- [ ] The suite set in step 4 passes with an identical collected node list, apart from disclosed rewrites of the two named tests.

## Execution Policy
- execute: effort=high, reason=replaces the runtime under the closeout parser; exact-byte prompt parity and fail-closed error mapping are subtle.
