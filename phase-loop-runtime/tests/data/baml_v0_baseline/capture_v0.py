"""One-shot capture of the BAML v0 (baml-py 0.222) baselines (agent-harness#1135, Step 0).

Run ONCE, in a baml-py 0.222.0 environment, against a clean ``origin/main``
checkout, from ``phase-loop-runtime/``::

    PYTHONPATH=src python tests/data/baml_v0_baseline/capture_v0.py

It is not collected by pytest (no ``test_`` prefix) and is never re-run after
the v1 switch: the files it writes are the frozen v0 goldens.

The capture runs under the #15 sentinel environment with every real credential
variable unset.  If an environment sentinel shows up in any golden the script
aborts without writing anything.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
RUNTIME = HERE.parents[2]

ENV_SENTINELS = {
    "OPENAI_API_KEY": "ENVSENTINEL-openai-api-key",
    "OPENAI_BASE_URL": "https://envsentinel-openai-base-url.invalid/v1",
    "ANTHROPIC_API_KEY": "ENVSENTINEL-anthropic-api-key",
    "BAML_LOG": "ENVSENTINEL-baml-log",
    "BAML_TRACE": "ENVSENTINEL-baml-trace",
    "BAML_HOME": "/envsentinel-baml-home",
    "BOUNDARY_API_KEY": "ENVSENTINEL-boundary-api-key",
    "BOUNDARY_PROJECT_ID": "ENVSENTINEL-boundary-project-id",
    "HOME": "/envsentinel-home",
    "HTTPS_PROXY": "http://envsentinel-https-proxy.invalid:1",
}
_CREDENTIAL_RE = re.compile(r"(API_KEY|_TOKEN|SECRET|PASSWORD|^OPENAI_|^ANTHROPIC_|^BOUNDARY_|^BAML_|PROXY)", re.I)


def _prepare_env() -> None:
    for key in list(os.environ):
        if _CREDENTIAL_RE.search(key):
            del os.environ[key]
    os.environ.update(ENV_SENTINELS)


_prepare_env()

from phase_loop_runtime import baml_modular as m  # noqa: E402
from phase_loop_runtime.baml_modular import BamlValidationError  # noqa: E402

B = {"terminal_status": "complete", "verification_status": "passed", "dirty_paths": [], "produced_if_gates": ["G"], "required_human_inputs": []}
J = json.dumps

SYNTHETIC = {
    "valid_min": J(B),
    "not_json": "not json",
    "empty": "",
    "whitespace": "   \n",
    "missing_verification": J({"terminal_status": "complete"}),
    "int_status": J({**B, "terminal_status": 5}),
    "scalar_to_list": J({**B, "terminal_status": "executed", "dirty_paths": "x"}),
    "bad_bool": J({**B, "human_required": "yes"}),
    "fenced": "prose before ```json\n" + J({**B, "terminal_status": "blocked", "verification_status": "blocked", "blocker_class": "stuck_loop", "produced_if_gates": []}) + "\n``` after",
    "extra_key": J({**B, "extra_field": 1}),
    "null_required": J({**B, "verification_status": None}),
    "null_list": J({**B, "dirty_paths": None}),
    "nested_wrong": J({**B, "dirty_paths": [{"a": 1}]}),
    "list_of_int": J({**B, "dirty_paths": [1, 2]}),
    "two_objects": J({**B, "terminal_status": "blocked", "verification_status": "failed", "produced_if_gates": []}) + "\n" + J(B),
    "truncated_string": '{"terminal_status":"complete","verification_status":"passed","dirty_paths":["a.py',
    "truncated_obj": '{"terminal_status":"complete","verification_status":"passed","dirty_paths":[],"produced_if_gates":["G"],"required_human_inputs":[]',
    "trailing_comma": '{"terminal_status":"complete","verification_status":"passed","dirty_paths":[],"produced_if_gates":["G"],"required_human_inputs":[],}',
    "single_quotes": "{'terminal_status':'complete','verification_status':'passed','dirty_paths':[],'produced_if_gates':['G'],'required_human_inputs':[]}",
    "complete_no_gates": J({**B, "produced_if_gates": []}),
    "bad_blocker": J({**B, "blocker_class": "nope"}),
    "blocker_none": J({**B, "blocker_class": "none"}),
    "enum_case": J({**B, "terminal_status": "Complete"}),
    "dry_run": J({**B, "terminal_status": "dry_run"}),
    "pix_2p70": J({**B, "visual_evidence_non_black_pixels": 2**70}),
    "pix_float": J({**B, "visual_evidence_non_black_pixels": 5.7}),
    "array_root": J([B]),
    "wrapped": J({"closeout": B}),
    "comment_json": '{"terminal_status":"complete", // c\n"verification_status":"passed","dirty_paths":[],"produced_if_gates":["G"],"required_human_inputs":[]}',
    "unicode": J({**B, "next_action": "ünï ✓ `x` ${Y}"}),
    # Serialization row (claude r6): a raw lone surrogate character in the input.
    "lone_surrogate": '{"terminal_status":"complete","verification_status":"passed","dirty_paths":[],"produced_if_gates":["G"],"required_human_inputs":[],"next_action":"\ud83d"}',
}

EVIDENCE_PAYLOADS = {
    "sentinel_args": {
        "tier2_signal_summary": "ARGSENTINEL-tier2-signal-summary",
        "sample_artifact_content": "ARGSENTINEL-sample-artifact-content",
        "expected_artifact_characteristics": "ARGSENTINEL-expected-artifact-characteristics",
    },
    "template_syntax": {
        "tier2_signal_summary": "ARGSENTINEL-t2 sig ${PROJECT} {{ x }}",
        "sample_artifact_content": "ARGSENTINEL-sample line1\nline2 `tick` back\\slash",
        "expected_artifact_characteristics": "ARGSENTINEL-expected ünïcødé ✓",
    },
    "edge_values": {
        "tier2_signal_summary": "",
        "sample_artifact_content": "  lead/trail  ",
        "expected_artifact_characteristics": "{% for a in b %}x{% endfor %}",
    },
}

CLOSEOUT_PAYLOADS = {
    "empty": {"phase_alias": "P1", "plan_produces": [], "plan_owned_files": []},
    "two_gates_sha": {"phase_alias": "P1", "plan_produces": ["IF-0-P1-1", "IF-0-P1-2"], "plan_owned_files": ["a.py"], "closeout_commit_sha": "abc123"},
    "two_gates_nosha": {"phase_alias": "P1", "plan_produces": ["IF-0-P1-1", "IF-0-P1-2"], "plan_owned_files": ["a.py"]},
    "sentinels": {"phase_alias": "P${PROJECT}{{ x }}", "plan_produces": ["G `t` ü"], "plan_owned_files": ["docs/${PROJECT}/guide.md", "{% if %}"], "closeout_commit_sha": None},
    "sha_empty": {"phase_alias": "P1", "plan_produces": [], "plan_owned_files": [], "closeout_commit_sha": ""},
}
BACKSLASH_PAYLOAD = {"phase_alias": "P1", "plan_produces": ["C:\\new\\s"], "plan_owned_files": [], "closeout_commit_sha": None}


def _exc_name(exc: BaseException) -> str:
    if type(exc) is BamlValidationError:
        return "BamlValidationError"
    return f"{type(exc).__module__}.{type(exc).__qualname__}"


def _parse(function_name: str, text: str):
    try:
        return m.parse_baml_response(function_name, text).payload
    except BaseException as exc:  # noqa: BLE001 - the golden records the exact type
        return _exc_name(exc)


def _request(function_name: str, payload):
    try:
        r = m.build_baml_request(function_name, payload)
    except BaseException as exc:  # noqa: BLE001
        return _exc_name(exc)
    messages = r.body.get("messages") or []
    return {
        "url": r.url,
        "method": r.method,
        "headers": r.headers,
        "body": r.body,
        "message_roles": [msg.get("role") for msg in messages],
        "message_content_types": [type(msg.get("content")).__name__ for msg in messages],
        "prompt": r.prompt,
        "prompt_sha256": hashlib.sha256(r.prompt.encode("utf-8")).hexdigest(),
    }


def _all_names(baml_text: str) -> tuple[list[str], list[str]]:
    classes = sorted(set(re.findall(r"\bclass\s+([A-Za-z_]\w*)\s*\{", baml_text)))
    functions = sorted(set(re.findall(r"\bfunction\s+([A-Z]\w*)\s*\(", baml_text)))
    return classes, functions


def main() -> int:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=RUNTIME, check=True, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "src"], cwd=RUNTIME, check=True, capture_output=True, text=True).stdout.strip()
    if dirty:
        print(f"refusing to capture: src/ is dirty:\n{dirty}", file=sys.stderr)
        return 2
    provenance = {
        "main_sha": sha,
        "baml_py_version": importlib.metadata.version("baml-py"),
        "python": sys.version.split()[0],
        "captured_by": "tests/data/baml_v0_baseline/capture_v0.py",
        "env_sentinels": sorted(ENV_SENTINELS),
    }

    corpus = {key: {"input": text} for key, text in SYNTHETIC.items()}
    fixture_paths = sorted(set(RUNTIME.joinpath("tests/fixtures").rglob("*.json")) | set(RUNTIME.joinpath("tests/data").rglob("*closeout*")))
    for path in fixture_paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if '"terminal_status"' in text:
            corpus["fx:" + str(path.relative_to(RUNTIME))] = {"input": text}
    for entry in corpus.values():
        entry["v0"] = _parse("EmitPhaseCloseout", entry["input"])
    name_cases = {
        "EvaluateSuspectedFakeEvidence:evidence_payload": ("EvaluateSuspectedFakeEvidence", J({"verdict": "real", "confidence": 0.9, "reasoning": "r", "specific_concerns": []})),
        "EvaluateSuspectedFakeEvidence:closeout_payload": ("EvaluateSuspectedFakeEvidence", J(B)),
        "NoSuchFunction:closeout_payload": ("NoSuchFunction", J(B)),
    }
    names = {key: {"function": fn, "input": text, "v0": _parse(fn, text)} for key, (fn, text) in name_cases.items()}

    evidence = {key: {"payload": p, "v0": _request("EvaluateSuspectedFakeEvidence", p)} for key, p in EVIDENCE_PAYLOADS.items()}
    closeout = {key: {"payload": p, "v0": _request("EmitPhaseCloseout", p)} for key, p in CLOSEOUT_PAYLOADS.items()}
    closeout["backslash"] = {"payload": BACKSLASH_PAYLOAD, "v0": _request("EmitPhaseCloseout", BACKSLASH_PAYLOAD)}
    for fn in ("NoSuchFunction", "DotfilesAdoptionManifest"):
        closeout[f"name:{fn}"] = {"function": fn, "payload": {}, "v0": _request(fn, {})}

    baml_text = "\n".join(m._read_baml_files().values())
    classes, functions = _all_names(baml_text)
    schema = {
        "class_fields": {c: [list(f) for f in m._class_fields(baml_text, c)] for c in classes},
        "export_function_schema": {n: m.export_function_schema(n) for n in [*classes, *functions]},
        "enum_literal_map": {k: list(v) for k, v in sorted(m._enum_literal_map().items())},
    }

    outputs = {
        "parse_corpus.json": {"provenance": provenance, "corpus": corpus, "names": names},
        "evidence_requests.json": {"provenance": provenance, "requests": evidence},
        "closeout_requests_v0.json": {"provenance": provenance, "requests": closeout},
        "schema_dump.json": {"provenance": provenance, "schema": schema},
    }
    rendered = {name: json.dumps(data, indent=1, sort_keys=True, ensure_ascii=True) + "\n" for name, data in outputs.items()}
    for name, text in rendered.items():
        body = json.dumps({k: v for k, v in outputs[name].items() if k != "provenance"}, ensure_ascii=False)
        for key, value in ENV_SENTINELS.items():
            if value in body:
                print(f"ABORT: env sentinel {key} found in {name}; nothing written", file=sys.stderr)
                return 3
    for name, text in rendered.items():
        (HERE / name).write_text(text, encoding="utf-8")
        print(f"wrote {name} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
