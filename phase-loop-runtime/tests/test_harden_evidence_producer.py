"""HARDEN SL-4 tests-only contract for the retained-evidence producer.

Raw JSON input annotations are non-authoritative free text, exercised in positive
fixtures so secret-only substitutions cannot be masked by unknown-field rejection.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable
from xml.etree import ElementTree

import pytest

from harden_tdd_guard import HARDEN_CASES


ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_HARDEN_PRODUCER"
INPUT_SCHEMA = "harden_evidence_inputs.v1"
PRODUCER_PATH = "phase-loop-runtime/scripts/build_harden_evidence.py"
SKIP_REASON = (
    "HARDEN aggregate producer is absent (SL-4 tests-only boundary): "
    f"set {ACTIVATION_ENV}=1 to record the deterministic RED anchors"
)
ANCHORS = {
    "derive": "HARDEN-PRODUCER-RED::derive-live-facts",
    "assemble": "HARDEN-PRODUCER-RED::assemble-retained-evidence",
    "seal": "HARDEN-PRODUCER-RED::two-stage-seal",
}
RAW_ARTIFACT_NAMES = (
    "plan_authority",
    "sl0_review",
    "source_mutations",
    "execution_runs",
    "preproduction_red_raw",
    "preproduction_red_junit",
    "preproduction_control_raw",
    "preproduction_control_junit",
    "candidate_focused_raw",
    "candidate_focused_junit",
    "candidate_pure_control_raw",
    "candidate_pure_control_junit",
    "candidate_broad_raw",
    "candidate_broad_junit",
    "candidate_lint_raw",
    "candidate_ci",
    "candidate_review_request",
    "candidate_broker_receipts",
    "canonical_main_focused_raw",
    "canonical_main_focused_junit",
    "canonical_main_pure_control_raw",
    "canonical_main_pure_control_junit",
    "canonical_main_broad_raw",
    "canonical_main_broad_junit",
    "canonical_main_lint_raw",
    "canonical_main_ci",
    "canonical_main_review_request",
    "canonical_main_broker_receipts",
)
RAW_JUNIT_PAIRS = (
    ("preproduction_red_raw", "preproduction_red_junit"),
    ("preproduction_control_raw", "preproduction_control_junit"),
    ("candidate_focused_raw", "candidate_focused_junit"),
    ("candidate_pure_control_raw", "candidate_pure_control_junit"),
    ("candidate_broad_raw", "candidate_broad_junit"),
    ("canonical_main_focused_raw", "canonical_main_focused_junit"),
    ("canonical_main_pure_control_raw", "canonical_main_pure_control_junit"),
    ("canonical_main_broad_raw", "canonical_main_broad_junit"),
)
ROLE_NAMES = ("coordinator", "author", "reviewer")


def _repo_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent,
    )
    return Path(completed.stdout.strip()).resolve()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8", errors="strict")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate key: {key}")
        value[key] = item
    return value


def _strict_json(path: Path) -> Any:
    data = path.read_bytes()
    value = json.loads(
        data,
        object_pairs_hook=_no_duplicate_keys,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
    )
    assert data == _canonical_bytes(value)
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _different_hex(value: str) -> str:
    replacement = os.urandom(len(value) // 2).hex()
    while replacement == value:
        replacement = os.urandom(len(value) // 2).hex()
    return replacement


def _different_count(value: int) -> int:
    return value + 1 + os.urandom(1)[0]


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _commit(repo: Path, message: str, paths: dict[str, str]) -> str:
    for relative, contents in paths.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _write_ref(root: Path, relative: str, data: bytes) -> dict[str, str]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": relative, "sha256": _sha256(data)}


def _junit_bytes(
    outcomes: tuple[str, ...],
    *,
    named_anchors: bool = False,
    nodeids: tuple[str, ...] | None = None,
    run_tag: str = "",
) -> bytes:
    suite = ElementTree.Element(
        "testsuite",
        tests=str(len(outcomes)),
        failures=str(outcomes.count("failed")),
        errors="0",
        skipped=str(outcomes.count("skipped")),
        name=run_tag,
    )
    for index, outcome in enumerate(outcomes):
        classname, name = "retained", f"case_{index}"
        anchor = None
        if nodeids is not None:
            classname, name = _load_shipped_verifier().pytest_junit_identity(
                nodeids[index], "fixture node"
            )
        if named_anchors and index < len(HARDEN_CASES):
            case_id, contract = list(HARDEN_CASES.items())[index]
            module, name = contract.nodeid.split("::")
            classname = (
                module.removeprefix("phase-loop-runtime/")
                .removesuffix(".py")
                .replace("/", ".")
            )
            anchor = f"HARDEN-RED-ANCHOR::{case_id}"
        case = ElementTree.SubElement(
            suite,
            "testcase",
            classname=classname,
            name=name,
        )
        if outcome == "failed":
            ElementTree.SubElement(
                case, "failure", message="falsifier bit"
            ).text = anchor
        elif outcome == "skipped":
            ElementTree.SubElement(case, "skipped", message="capability absent")
    return ElementTree.tostring(suite, encoding="utf-8", xml_declaration=True)


def _fixture_variants() -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    suffix = _sha256(os.urandom(16))[:12]
    runtime_red = ("passed",) * (3 + int(suffix[0], 16) % 3) + ("skipped",)
    runtime_final = ("passed",) * (4 + int(suffix[1], 16) % 4)
    return (
        (
            "codex-gpt-5.6-terra",
            ("passed", "skipped"),
            ("passed", "passed"),
        ),
        (
            "claude-fable-5",
            ("passed", "passed"),
            ("passed", "passed", "passed"),
        ),
        (
            f"runtime-vendor-{suffix}",
            runtime_red,
            runtime_final,
        ),
    )


def _runtime_variant(seed: Path) -> str:
    return "runtime-" + _sha256(os.fsencode(str(seed.resolve())))[:16]


def _producer_module(case: str) -> Any:
    path = _repo_root() / PRODUCER_PATH
    if not path.is_file():
        if os.environ.get(ACTIVATION_ENV) == "1":
            pytest.fail(ANCHORS[case], pytrace=False)
        pytest.skip(SKIP_REASON)
    spec = importlib.util.spec_from_file_location("harden_evidence_producer", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _producer_command(*args: str) -> subprocess.CompletedProcess[str]:
    # Keep CI substitution in the test process, not in a production CLI flag or
    # environment switch. Only the canonical provider query is replaced; the
    # producer, verifier and all of their validation execute unchanged.
    bootstrap = """
import os, pathlib, runpy, subprocess, sys
producer, *arguments = sys.argv[1:]
if '--evidence-root' in arguments:
    root = pathlib.Path(arguments[arguments.index('--evidence-root') + 1]).parent
    fake_gh = root / 'fake-gh'
    assert fake_gh.is_file()
    original_lstat = pathlib.Path.lstat
    original_access = os.access
    def fixture_lstat(path, *positional, **keywords):
        return original_lstat(fake_gh if str(path) == '/usr/bin/gh' else path, *positional, **keywords)
    def fixture_access(path, *positional, **keywords):
        return original_access(fake_gh if str(path) == '/usr/bin/gh' else path, *positional, **keywords)
    pathlib.Path.lstat = fixture_lstat
    os.access = fixture_access
    os.environ.pop('GITHUB_TOKEN', None)
    os.environ['GH_TOKEN'] = 'hermetic-test-only-not-a-credential'
    original = subprocess.Popen
    class HermeticCIProcess(original):
        def __init__(self, command, *positional, **keywords):
            if isinstance(command, (list, tuple)) and command and str(command[0]) == '/usr/bin/gh':
                assert list(command[1:3]) == ['run', 'view'], 'unexpected CI query'
                command = [str(fake_gh), *command[1:]]
            super().__init__(command, *positional, **keywords)
    subprocess.Popen = HermeticCIProcess
sys.argv = [producer, *arguments]
runpy.run_path(producer, run_name='__main__')
"""
    return subprocess.run(
        [sys.executable, "-c", bootstrap, str(_repo_root() / PRODUCER_PATH), *args],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _load_shipped_verifier() -> Any:
    path = _repo_root() / "phase-loop-runtime/scripts/verify_harden_evidence.py"
    spec = importlib.util.spec_from_file_location("shipped_harden_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _broker_observation(
    verifier: Any,
    harness: str,
    model: str,
    identity: str,
    inputs: dict[str, str],
    report: str,
    repo: Path,
    session_sha256: str,
) -> dict[str, Any]:
    """Independent hermetic observation data, never a production inference result."""
    prompt = verifier.broker_sealed_prompt(inputs["bundle"], inputs["instructions"])
    prompt_bytes = len(prompt.encode())
    scratch = "/tmp/harden-producer-observation"
    argv = []
    for token in verifier.broker_argv_grammar(harness, model):
        if isinstance(token, str):
            argv.append(token)
        elif argv[-1:] == ["--output-last-message"]:
            argv.append(scratch + "/last-message.txt")
        else:
            candidates = (scratch, "model_reasoning_effort=xhigh", "max", "high", "30s")
            argv.append(next(value for value in candidates if token.fullmatch(value)))
    stream = (
        verifier.broker_gemini_stream_protocol(prompt) if harness == "gemini" else None
    )
    transport = stream["transport"] if stream else prompt
    data: dict[str, Any] = {
        "schema": "parent_unix_broker_v1",
        "canonical_repo_sha256": _sha256(os.fsencode(str(repo.resolve()))),
        "stage_bundle_sha256": _sha256(inputs["bundle"].encode()),
        "stage_instructions_sha256": _sha256(inputs["instructions"].encode()),
        "leg_authorization_instructions_sha256": _sha256(
            inputs["instructions"].encode()
        ),
        "leg_authorization_issued_monotonic_ns": 1,
        "leg_authorization_expires_monotonic_ns": 30_000_000_001,
        "peer_pid": 101,
        "peer_uid": 1000,
        "peer_gid": 1000,
        "outer_bwrap_pid": 100,
        "outer_bwrap_start": 12345,
        "bwrap": "/usr/bin/bwrap",
        "socket": "/run/phase-loop-broker/intended-inference.sock",
        "stage": "/run/phase-loop-review",
        "stage_bundle_mode": 0o400,
        "stage_instructions_mode": 0o400,
        "child_returncode": 0,
        "operation_deadline_s": 30.0,
        "client_probe_assertions": [
            "credentialless_env",
            "readonly_stage",
            "no_live_bundle",
            "no_live_instructions",
            "no_host_secret",
            "no_live_tree",
            "no_inherited_fd",
            "fixed_socket_only",
            "no_af_inet",
        ],
        "provider_harness": harness,
        "provider_model": model,
        "provider_argv_shape": argv,
        "provider_argv_sha256": _sha256("\0".join(argv).encode()),
        "provider_cwd_class": "owned_empty_scratch",
        "provider_cwd_sha256": _sha256(scratch.encode()),
        "provider_no_tool_controls": list(verifier.NO_TOOL_CONTROLS[harness]),
        "provider_env_keys": ["HOME", "LANG", "PATH", "XDG_CONFIG_HOME"]
        if stream
        else ["LANG", "PATH"],
        "provider_prompt_transport": verifier.PROMPT_TRANSPORT[harness],
        "provider_response_status": "OK",
        "provider_response_sha256": _sha256(report.encode()),
        "provider_response_bytes": len(report.encode()),
    }
    for field in (
        "canonical_repo_probe_file_sha256",
        "argv_sha256",
        "client_probe_program_sha256",
        "child_stderr_sha256",
    ):
        data[field] = _sha256(f"{identity}:{field}".encode())
    for field in (
        "cleanup_root_removed",
        "host_secret_probe_removed",
        "child_quiescent",
        "peer_ancestry_verified",
        "network_unshared",
        "close_fds_requested",
        "socket_present_before_launch",
        "canonical_repo_file_denied",
        "canonical_repo_directory_denied",
        "host_stage_path_denied",
        "no_inherited_fd_observed",
        "broker_thread_quiescent",
        "provider_adapter_quiescent",
        "provider_input_inline",
        "provider_env_api_keys_scrubbed",
        "provider_env_direct_routes_scrubbed",
    ):
        data[field] = True
    for field in (
        "child_timeout",
        "provider_live_tree_cwd",
        "provider_cancel_requested",
    ):
        data[field] = False
    for prefix, content in (
        ("input", prompt),
        ("prompt", prompt),
        ("transport", transport),
    ):
        data[f"provider_{prefix}_sha256"] = _sha256(content.encode())
        data[f"provider_{prefix}_bytes"] = len(content.encode())
    if harness == "claude":
        data.update(
            {
                "claude_session_id_sha256": session_sha256,
                "claude_session_resume_forbidden": True,
                "claude_transcript_exact_path_sha256": _sha256(
                    f"{identity}:transcript-path".encode()
                ),
                "claude_transcript_preexisting": False,
                "claude_transcript_existed": True,
                "claude_transcript_sha256": _sha256(f"{identity}:transcript".encode()),
                "claude_transcript_bytes": 64,
                "claude_transcript_cleanup_verified": True,
                "provider_liveness_profile": "broker_prompt_scaled_v1",
                "provider_liveness_prompt_bytes": prompt_bytes,
                "provider_liveness_stall_threshold_s": float(
                    max(
                        1,
                        min(
                            verifier.BROKER_CLAUDE_STALL_BASE_S
                            + (
                                prompt_bytes
                                + verifier.BROKER_CLAUDE_STALL_BYTES_PER_S
                                - 1
                            )
                            // verifier.BROKER_CLAUDE_STALL_BYTES_PER_S,
                            max(
                                1, 30 - verifier.BROKER_CLAUDE_STALL_TRANSPORT_RESERVE_S
                            ),
                        ),
                    )
                ),
            }
        )
    if stream:
        settings = {
            "permissions": {"deny": list(verifier.AGY_DENY_ACTIONS)},
            "toolPermission": "request-review",
            "allowNonWorkspaceAccess": False,
        }
        data.update(
            {
                "provider_isolation_profile": "agy_temp_home_deny_all_v1",
                "provider_agy_deny_actions": list(verifier.AGY_DENY_ACTIONS),
                "provider_agy_settings_sha256": _sha256(_canonical_bytes(settings)),
                "provider_agy_subscription_reference": "private_symlink",
                "provider_agy_home_cleanup_verified": True,
                "provider_stream_protocol": verifier.GEMINI_STREAM_PROTOCOL,
                "provider_stream_chunk_count": len(stream["chunk_sha256"]),
                "provider_stream_chunk_sha256": stream["chunk_sha256"],
                "provider_stream_chunk_bytes": stream["chunk_bytes"],
                "provider_stream_final_event_sha256": stream["final_event_sha256"],
                "provider_stream_acknowledgements": stream["acknowledgements"],
                "provider_stream_result_count": len(stream["acknowledgements"]) + 1,
                "provider_stream_output_sha256": _sha256(
                    f"{identity}:stream-output".encode()
                ),
                "provider_stream_output_bytes": len(stream["acknowledgements"]) + 1,
                "provider_stream_outcome": "accepted",
                "provider_stream_acknowledgements_verified": True,
                "provider_stream_final_no_truncation": True,
            }
        )
    return data


def _raw_fixture(
    root: Path,
    *,
    variant: str = "valid",
    author_vendor: str = "codex-gpt-5.6-terra",
    red_outcomes: tuple[str, ...] = ("passed", "skipped"),
    final_outcomes: tuple[str, ...] = ("passed", "passed"),
    non_biting_mutation: bool = False,
) -> dict[str, Any]:
    verifier = _load_shipped_verifier()
    named_nodes = tuple(verifier.ACTIVATED_RED_NODEIDS)
    red_extras, final_extras = red_outcomes, final_outcomes
    native_path = "phase-loop-runtime/tests/test_panel_native_fill_183.py"
    control_node = native_path + "::test_pure_control"
    extra_path = f"phase-loop-runtime/tests/test_{variant}_one.py"
    extra_nodes = lambda outcomes: tuple(
        f"{extra_path}::test_extra_{index}" for index in range(len(outcomes))
    )
    red_nodes = named_nodes + (control_node,) + extra_nodes(red_extras)
    final_nodes = named_nodes + (control_node,) + extra_nodes(final_extras)
    red_outcomes = ("failed",) * len(named_nodes) + ("passed",) + red_extras
    final_outcomes = ("passed",) * (len(named_nodes) + 1) + final_extras
    repo = root / "repo"
    source_root = root / "retained-source"
    repo.mkdir(parents=True)
    source_root.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "user.email", "producer-test@example.invalid")
    _git(repo, "config", "user.name", "HARDEN producer test")
    frozen_paths = tuple(
        sorted(
            {
                extra_path,
                native_path,
                *(node.split("::")[0] for node in named_nodes),
            }
        )
    )
    production_path = f"phase-loop-runtime/src/phase_loop_runtime/{variant}.py"
    marker_path = "phase-loop-runtime/src/phase_loop_runtime/capability_registry.py"
    run_specs = {
        key: {
            field: list(value) if isinstance(value, tuple) else value
            for field, value in verifier.FINAL_RUN_SPECS[key].items()
            if field in {"argv", "cwd", "env_keys"}
        }
        for key in ("focused", "pure_control", "broad")
    }
    # Bind selection to the Git-owned miniature plan, not a producer-supplied
    # command. Preserve the real command grammar while varying its frozen input.
    run_specs["focused"]["argv"] = list(
        verifier.FINAL_RUN_SPECS["focused"]["argv"][:7]
    ) + list(frozen_paths)
    broad_path = "phase-loop-runtime/tests/test_broad_control.py"
    broad_node = broad_path + "::test_broad_control"
    pure_nodes = (control_node,) + tuple(
        node for node in named_nodes if "/test_advisor_board_composition.py::" in node
    )
    base = _commit(
        repo,
        "base",
        {
            **{
                case.production_path: f"def {case.symbol}():\n    return True\n"
                for case in HARDEN_CASES.values()
            },
            "README.md": "base\n",
            "phase-loop-runtime/pytest.ini": "[pytest]\n",
            "plans/phase-plan-v10-HARDEN.md": (
                "# HARDEN retained-input test contract\n\n"
                "### SL-0 — tests-first\n\n- **Owned files**: "
                + ", ".join(f"`{path}`" for path in frozen_paths)
                + "\n\n### SL-1 — production\n\n- **Owned files**: "
                + f"`{production_path}`, `{marker_path}`\n"
                + "\n### Verification commands\n\n```json\n"
                + _canonical_bytes(
                    {
                        "schema": "harden_suite_contract.v1",
                        "runs": run_specs,
                        "activated_nodeids": list(named_nodes),
                    }
                ).decode()
                + "```\n"
            ),
            "plans/manifest.json": '{"plans":[]}\n',
            marker_path: "# Capability marker is absent before production.\n",
            ".gitignore": ".phase-loop/\n__pycache__/\n.pytest_cache/\n",
            broad_path: "def test_broad_control(): pass\n",
            ".github/workflows/test.yml": (
                "name: test\n\n"
                "on:\n"
                "  push:\n"
                "    branches: [main]\n"
                "  pull_request:\n\n"
                "jobs:\n"
                "  gate:\n"
                "    name: suite gate\n"
                "    runs-on: ubuntu-latest\n"
                "    steps: []\n"
            ),
        },
    )
    prelude = (
        "from pathlib import Path\nimport os\nimport pytest\nimport unittest\n"
        "ROOT = Path(__file__).resolve().parents[2]\n"
        f"CAPABLE = 'HARDEN_CAPABILITY_VERSION = 1' in (ROOT / {marker_path!r}).read_text()\n"
    )
    frozen_tests = {path: prelude for path in frozen_paths}
    classes: dict[str, dict[str, str]] = {}
    contracts = {case.nodeid: (case_id, case) for case_id, case in HARDEN_CASES.items()}
    for node in named_nodes:
        test_path, *identity = node.split("::")
        case_id, contract = contracts.get(node, ("review-leg-isolation", None))
        body = (
            "    if os.environ.get('PHASE_LOOP_TDD_EXPECT_HARDEN') == '1' and not CAPABLE:\n"
            f"        pytest.fail('HARDEN-RED-ANCHOR::{case_id}', pytrace=False)\n"
        )
        if contract is not None:
            body += (
                "    namespace = {}\n"
                f"    source = ROOT / {contract.production_path!r}\n"
                "    exec(compile(source.read_bytes(), str(source), 'exec'), namespace)\n"
                f"    assert namespace[{contract.symbol!r}]()\n"
            )
        function = (
            f"def {identity[-1]}({'self' if len(identity) == 2 else ''}):\n" + body
        )
        if len(identity) == 1:
            frozen_tests[test_path] += "\n" + function
        else:
            classes.setdefault(test_path, {}).setdefault(identity[0], "")
            classes[test_path][identity[0]] += (
                "\n" + "\n".join("    " + line for line in function.splitlines()) + "\n"
            )
    for test_path, definitions in classes.items():
        for name, body in definitions.items():
            frozen_tests[test_path] += f"\nclass {name}(unittest.TestCase):\n" + body
    frozen_tests[native_path] += "\ndef test_pure_control(): pass\n"
    for condition, outcomes in (("not CAPABLE", red_extras), ("CAPABLE", final_extras)):
        frozen_tests[extra_path] += f"\nif {condition}:\n"
        for index, outcome in enumerate(outcomes):
            action = (
                "pytest.skip('capability absent')" if outcome == "skipped" else "pass"
            )
            frozen_tests[extra_path] += f"    def test_extra_{index}(): {action}\n"
    _git(repo, "checkout", "-qb", "reviewed-sl0")
    reviewed = _commit(
        repo,
        "tests only",
        frozen_tests,
    )
    historical_sessions = [
        _sha256(f"{variant}:sl0:{harness}:session".encode())
        for harness in ("claude", "codex", "gemini", "grok")
    ]
    approval_nonce = _sha256(f"{variant}:sl0:approval".encode())
    approval = {
        "schema": "harden_sl0_approval.v1",
        "base_commit": base,
        "head": reviewed,
        "tree": _git(repo, "rev-parse", f"{reviewed}^{{tree}}"),
        "patch_sha256": _sha256(
            subprocess.check_output(
                ["git", "diff", "--no-ext-diff", base, reviewed], cwd=repo
            )
        ),
        "clock_id": variant,
        "observed_monotonic_ns": time.monotonic_ns(),
        "operation_nonce": approval_nonce,
        "seats": [],
    }
    for harness, session in zip(
        ("claude", "codex", "gemini", "grok"), historical_sessions, strict=True
    ):
        report = f"Reviewed tests-only head {reviewed}, tree {approval['tree']}, as {harness}.\nAGREE\n"
        approval["seats"].append(
            {
                "harness": harness,
                "session_sha256": session,
                "status": "usable",
                "report": report,
                "report_sha256": _sha256(report.encode()),
                "report_bytes": len(report.encode()),
            }
        )
    approval_relative = f".phase-loop/runs/{variant}-sl0-review/approval.json"
    _write_ref(repo, approval_relative, _canonical_bytes(approval))
    approval_ref = _write_ref(
        source_root, approval_relative, _canonical_bytes(approval)
    )
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-qm", "land reviewed tests", "reviewed-sl0")
    landing = _git(repo, "rev-parse", "HEAD")
    operation_nonces = [
        _sha256(f"{variant}:operation:{index}".encode()) for index in range(13)
    ]
    reviewed_tree = _git(repo, "rev-parse", f"{reviewed}^{{tree}}")
    mutation_entries = []
    mutation_env = dict(os.environ)
    mutation_env.pop("PHASE_LOOP_TDD_EXPECT_HARDEN", None)
    mutation_env.pop("PYTEST_ADDOPTS", None)
    mutation_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    _git(repo, "checkout", "-q", reviewed)
    for case_id, case in HARDEN_CASES.items():
        restored_bytes = subprocess.check_output(
            ["git", "show", f"{reviewed}:{case.production_path}"], cwd=repo
        )
        non_biting = non_biting_mutation and not mutation_entries
        mutated_bytes = restored_bytes.replace(
            b"return True", b"return 2" if non_biting else b"return False", 1
        )
        assert mutated_bytes != restored_bytes
        entry: dict[str, Any] = {
            "case_id": case_id,
            "source_path": case.production_path,
            "nodeid": case.nodeid,
            "restored_source": _write_ref(
                source_root, f"raw/mutations/{case_id}/restored.py", restored_bytes
            ),
            "mutated_source": _write_ref(
                source_root, f"raw/mutations/{case_id}/mutated.py", mutated_bytes
            ),
        }
        for stage, exit_code, kind, marker, source_ref in (
            (
                "mutation",
                0 if non_biting else 1,
                "source_mutation",
                "HARDEN-MUTATION-BITE",
                entry["mutated_source"],
            ),
            (
                "restored",
                0,
                "restored_control",
                "HARDEN-RESTORED-CONTROL",
                entry["restored_source"],
            ),
        ):
            run_nonce = _sha256(f"{variant}:{case_id}:{stage}:process".encode())
            operation_nonces.append(run_nonce)
            junit_relative = f"raw/mutations/{case_id}/{stage}.xml"
            junit_path = source_root / junit_relative
            installed_source = repo / case.production_path
            installed_source.write_bytes(
                (source_root / source_ref["path"]).read_bytes()
            )
            started = time.monotonic_ns()
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        case.nodeid,
                        "--junitxml",
                        str(junit_path),
                    ],
                    cwd=repo,
                    env=mutation_env,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                assert completed.returncode == exit_code, completed.stdout.decode(
                    errors="replace"
                )
            finally:
                installed_source.write_bytes(restored_bytes)
            raw = _write_ref(
                source_root,
                f"raw/mutations/{case_id}/{stage}.txt",
                f"{marker}::{case_id}\n".encode() + completed.stdout,
            )
            junit = _write_ref(
                source_root,
                junit_relative,
                junit_path.read_bytes(),
            )
            record = {
                "schema": "harden_pytest_receipt.v1",
                "kind": kind,
                "head": reviewed,
                "tree": reviewed_tree,
                "clock_id": variant,
                "started_monotonic_ns": started,
                "finished_monotonic_ns": time.monotonic_ns(),
                "process_nonce": run_nonce,
                "exit_code": exit_code,
                "argv_class": f"pytest_harden_{kind}_v1",
                "raw_sha256": raw["sha256"],
                "junit_sha256": junit["sha256"],
                "source_path": case.production_path,
                "source_sha256": source_ref["sha256"],
            }
            receipt_path = (
                f".phase-loop/runs/{variant}-{case_id}-{stage}/pytest-receipt.json"
            )
            receipt_bytes = _canonical_bytes(record)
            _write_ref(repo, receipt_path, receipt_bytes)
            receipt = _write_ref(source_root, receipt_path, receipt_bytes)
            entry[stage] = {"raw": raw, "junit": junit, "receipt": receipt}
        mutation_entries.append(entry)
    _git(repo, "checkout", "-q", "main")
    mutation_index_path = f".phase-loop/runs/{variant}-mutations/index.json"
    mutation_index_bytes = _canonical_bytes(
        {
            "schema": "harden_source_mutations.v1",
            "annotation": f"retained input {variant}",
            "mutations": mutation_entries,
        }
    )
    _write_ref(repo, mutation_index_path, mutation_index_bytes)
    mutation_index_ref = _write_ref(
        source_root, mutation_index_path, mutation_index_bytes
    )
    preproduction_runs = {}
    _git(repo, "checkout", "-q", reviewed)
    try:
        for name, spec_key, is_red in (
            ("preproduction_red", "focused", True),
            ("preproduction_control", "pure_control", False),
        ):
            spec = copy.deepcopy(run_specs[spec_key])
            junit_path = source_root / f"raw/{name}_junit.xml"
            started = time.monotonic_ns()
            completed = subprocess.run(
                [*spec["argv"], "--junitxml", str(junit_path)],
                cwd=repo / spec["cwd"],
                env=mutation_env,
                capture_output=True,
                check=False,
                timeout=30,
            )
            assert completed.returncode == int(is_red), completed.stdout.decode(
                errors="replace"
            )
            raw_ref = _write_ref(source_root, f"raw/{name}_raw.txt", completed.stdout)
            junit_ref = _write_ref(
                source_root, f"raw/{name}_junit.xml", junit_path.read_bytes()
            )
            nonce = _sha256(f"{variant}:{name}:fresh-process".encode())
            operation_nonces.append(nonce)
            record = {
                "schema": "harden_run_observation.v1",
                "kind": name,
                "head": reviewed,
                "tree": reviewed_tree,
                "clock_id": variant,
                "started_monotonic_ns": started,
                "finished_monotonic_ns": time.monotonic_ns(),
                "process_nonce": nonce,
                "exit_code": int(is_red),
                "argv_class": "pytest_harden_activated_v1"
                if is_red
                else "pytest_harden_pure_control_v1",
                **spec,
                "source_tree": reviewed_tree,
                "raw": raw_ref,
                "junit": junit_ref,
                "baseline": {
                    "schema": "harden_broad_baseline.v1",
                    "commit": base,
                    "tree": _git(repo, "rev-parse", f"{base}^{{tree}}"),
                    "inherited_failures": [],
                    "inherited_skips": [],
                    "inherited_deselected": [],
                },
            }
            relative = f".phase-loop/runs/{variant}-{name}/observation.json"
            data = _canonical_bytes(record)
            _write_ref(repo, relative, data)
            preproduction_runs[name] = _write_ref(source_root, relative, data)
    finally:
        _git(repo, "checkout", "-q", "main")
    production_nonce = _sha256(f"{variant}:production:start".encode())
    production_start = {
        "schema": "harden_production_start.v1",
        "head": landing,
        "tree": _git(repo, "rev-parse", "HEAD^{tree}"),
        "clock_id": variant,
        "observed_monotonic_ns": time.monotonic_ns(),
        "operation_nonce": production_nonce,
        "sl0_approval": approval_ref,
        "preproduction_runs": preproduction_runs,
        "source_mutations": mutation_index_ref,
    }
    production_relative = f".phase-loop/runs/{variant}-production/start.json"
    _write_ref(repo, production_relative, _canonical_bytes(production_start))
    production_ref = _write_ref(
        source_root, production_relative, _canonical_bytes(production_start)
    )
    candidate = _commit(
        repo,
        "production",
        {
            production_path: "CAPABILITY = 1\n",
            marker_path: "HARDEN_CAPABILITY_VERSION = 1\n",
        },
    )
    _git(repo, "commit", "--allow-empty", "-qm", "canonical landing")
    canonical_main = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", canonical_main)
    commits = {
        "sl0_base": base,
        "reviewed_sl0": reviewed,
        "landing": landing,
        "candidate": candidate,
        "canonical_main": canonical_main,
    }
    trees = {
        name: _git(repo, "rev-parse", f"{commit}^{{tree}}")
        for name, commit in commits.items()
    }
    evidence_id = _sha256(f"evidence:{variant}".encode())
    operation_nonces.extend([approval_nonce, production_nonce, *historical_sessions])
    ci_seed = int(_sha256(f"{variant}:ci".encode())[:12], 16)
    ci_run_ids = {
        "candidate": ci_seed * 2 + 1,
        "canonical_main": ci_seed * 2 + 2,
    }
    routes = [
        {
            "harness": harness,
            "requested_model": f"{harness}-{variant}-requested",
            "resolved_model": f"{harness}-{variant}-resolved",
        }
        for harness in ("claude", "codex", "gemini", "grok")
    ]
    verifier = _load_shipped_verifier()
    reviewer_sessions = {
        (round_name, route["harness"]): _sha256(
            f"{variant}:{round_name}:{route['harness']}:reviewer-session".encode()
        )
        for round_name in ("candidate", "canonical_main")
        for route in routes
    }
    plan_authority = {
        "schema": "harden_plan_authority.v1",
        "annotation": f"retained input {variant}",
        "evidence_id": evidence_id,
        "repository": "Consiliency/agent-harness",
        "commits": commits,
        "author_vendor": author_vendor,
    }
    sl0_review = {
        "schema": "harden_sl0_review.v1",
        "annotation": f"retained input {variant}",
        "base_commit": base,
        "reviewed_commit": reviewed,
        "landing_commit": landing,
        "frozen_test_paths": list(frozen_paths),
        "approval": approval_ref,
        "production_start": production_ref,
    }
    run_cases = {
        "preproduction_red": (red_nodes, red_outcomes),
        "preproduction_control": (pure_nodes, ("passed",) * len(pure_nodes)),
        "candidate_focused": (final_nodes, final_outcomes),
        "candidate_pure_control": (pure_nodes, ("passed",) * len(pure_nodes)),
        "candidate_broad": (final_nodes + (broad_node,), final_outcomes + ("passed",)),
        "canonical_main_focused": (final_nodes, final_outcomes),
        "canonical_main_pure_control": (pure_nodes, ("passed",) * len(pure_nodes)),
        "canonical_main_broad": (
            final_nodes + (broad_node,),
            final_outcomes + ("passed",),
        ),
    }
    raw_outputs, junits = {}, {}
    for name, (nodes, outcomes) in run_cases.items():
        if name in preproduction_runs:
            observed = _strict_json(source_root / preproduction_runs[name]["path"])
            raw_outputs[name + "_raw"] = (
                source_root / observed["raw"]["path"]
            ).read_bytes()
            junits[name + "_junit"] = (
                source_root / observed["junit"]["path"]
            ).read_bytes()
            continue
        tag = f"{variant}:{name}:fresh-process"
        summary = ", ".join(
            f"{outcomes.count(status)} {status}"
            for status in ("failed", "passed", "skipped")
            if status in outcomes
        )
        markers = ""
        if name == "preproduction_red":
            markers = (
                "\n".join(
                    "HARDEN-RED-ANCHOR::"
                    + contracts.get(node, ("review-leg-isolation", None))[0]
                    for node in named_nodes
                )
                + "\n"
            )
        raw_outputs[name + "_raw"] = f"{summary}\nrun={tag}\n{markers}".encode()
        junits[name + "_junit"] = _junit_bytes(outcomes, nodeids=nodes, run_tag=tag)
    for round_name in ("candidate", "canonical_main"):
        raw_outputs[f"{round_name}_lint_raw"] = (
            f"All checks passed!\nrun={variant}:{round_name}:lint\n".encode()
        )
    artifacts: dict[str, dict[str, str]] = {
        "plan_authority": _write_ref(
            source_root, "raw/plan-authority.json", _canonical_bytes(plan_authority)
        ),
        "sl0_review": _write_ref(
            source_root, "raw/sl0-review.json", _canonical_bytes(sl0_review)
        ),
    }
    artifacts["source_mutations"] = mutation_index_ref
    for name, data in {**raw_outputs, **junits}.items():
        extension = "xml" if name.endswith("junit") else "txt"
        artifacts[name] = _write_ref(source_root, f"raw/{name}.{extension}", data)
    run_observations = {}
    for raw_name, junit_name in RAW_JUNIT_PAIRS:
        name = raw_name.removesuffix("_raw")
        if name in preproduction_runs:
            run_observations[name] = preproduction_runs[name]
            continue
        revision = (
            "reviewed_sl0"
            if name.startswith("preproduction_")
            else "candidate"
            if name.startswith("candidate_")
            else "canonical_main"
        )
        is_red = name == "preproduction_red"
        spec_key = (
            "focused"
            if is_red or "focused" in name
            else "broad"
            if "broad" in name
            else "pure_control"
        )
        kind = (
            "activated_red"
            if is_red
            else "focused_activated"
            if spec_key == "focused"
            else spec_key
        )
        nonce = _sha256(f"{variant}:{name}:fresh-process".encode())
        operation_nonces.append(nonce)
        record = {
            "schema": "harden_run_observation.v1",
            "kind": name,
            "head": commits[revision],
            "tree": trees[revision],
            "process_nonce": nonce,
            "exit_code": int(is_red),
            "argv_class": "pytest_harden_activated_v1"
            if is_red
            else f"pytest_harden_{kind}_v1",
            **copy.deepcopy(run_specs[spec_key]),
            "source_tree": trees[revision],
            "raw": artifacts[raw_name],
            "junit": artifacts[junit_name],
            "baseline": {
                "schema": "harden_broad_baseline.v1",
                "commit": base if revision == "reviewed_sl0" else landing,
                "tree": trees["sl0_base"]
                if revision == "reviewed_sl0"
                else trees["landing"],
                "inherited_failures": [],
                "inherited_skips": [],
                "inherited_deselected": [],
            },
        }
        relative = f".phase-loop/runs/{variant}-{name}/observation.json"
        raw_record = _canonical_bytes(record)
        _write_ref(repo, relative, raw_record)
        run_observations[name] = _write_ref(source_root, relative, raw_record)
    for round_name in ("candidate", "canonical_main"):
        name = f"{round_name}_lint"
        nonce = _sha256(f"{variant}:{name}:fresh-process".encode())
        operation_nonces.append(nonce)
        record = {
            "schema": "harden_static_receipt.v1",
            "head": commits[round_name],
            "tree": trees[round_name],
            "process_nonce": nonce,
            "exit_code": 0,
            "tool_identity": "harden_static_gate.v1",
            "argv_class": "harden_static_metadata_only_v1",
            "checks": ["py_compile", "ruff", "git_diff_check"],
            "raw_sha256": artifacts[f"{name}_raw"]["sha256"],
        }
        relative = f".phase-loop/runs/{variant}-{name}/lint-receipt.json"
        raw_record = _canonical_bytes(record)
        _write_ref(repo, relative, raw_record)
        run_observations[name] = _write_ref(source_root, relative, raw_record)
    groups = {}
    for round_name in ("candidate", "canonical_main"):
        run_nonce = _sha256(f"{variant}:{round_name}:parent-process".encode())
        operation_nonces.append(run_nonce)
        groups[round_name] = {
            "run_nonce": run_nonce,
            "head": commits[round_name],
            "tree": trees[round_name],
        }
    artifacts["execution_runs"] = _write_ref(
        source_root,
        "raw/execution-runs.json",
        _canonical_bytes(
            {
                "schema": "harden_execution_runs.v1",
                "annotation": f"retained input {variant}",
                "runs": run_observations,
                "groups": groups,
            }
        ),
    )
    for round_name, head in (
        ("candidate", candidate),
        ("canonical_main", canonical_main),
    ):
        run_id = ci_run_ids[round_name]
        ci = {
            "schema": "harden_ci_result.v1",
            "annotation": f"retained input {variant}",
            "provider": "github_actions",
            "repository": "Consiliency/agent-harness",
            "head": head,
            "run_id": run_id,
            "workflow": "test",
            "event": "pull_request" if round_name == "candidate" else "push",
            "run_attempt": 1,
            "check": "suite gate",
            "status": "completed",
            "conclusion": "success",
        }
        artifacts[f"{round_name}_ci"] = _write_ref(
            source_root, f"raw/{round_name}-ci.json", _canonical_bytes(ci)
        )
        request = {
            "schema": "harden_review_request.v1",
            "annotation": f"retained input {variant}",
            "round": round_name,
            "head": head,
            "tree": trees[round_name],
            "routes": routes,
            "operation_nonce": operation_nonces[0 if round_name == "candidate" else 1],
        }
        inputs = {
            kind: verifier.git_bound_review_input(
                repo, landing, trees["landing"], head, trees[round_name], kind
            )
            for kind in ("bundle", "instructions")
        }
        for kind, content in inputs.items():
            request[kind] = _write_ref(
                source_root,
                f"raw/{round_name}-{kind}.json",
                _canonical_bytes(
                    {
                        "schema": "harden_review_input.v1",
                        "kind": kind,
                        "head": head,
                        "tree": trees[round_name],
                        "content": content,
                    }
                ),
            )
        artifacts[f"{round_name}_review_request"] = _write_ref(
            source_root,
            f"raw/{round_name}-review-request.json",
            _canonical_bytes(request),
        )
        receipts = {
            "schema": "harden_broker_receipts.v1",
            "annotation": f"retained input {variant}",
            "round": round_name,
            "receipts": [
                {
                    **route,
                    "result_kind": "live",
                    "terminal_verdict": "AGREE",
                    "head": head,
                    "tree": trees[round_name],
                    "seat_id": f"{variant}-{round_name}-{route['harness']}",
                    "session_sha256": reviewer_sessions[round_name, route["harness"]],
                    "harness_provenance": "brokered_subscription_cli",
                    "report": (
                        f"Reviewed {head} / {trees[round_name]} as "
                        f"{route['harness']} in {round_name}.\nAGREE\n"
                    ),
                    "operation_nonce": operation_nonces[
                        (2 if round_name == "candidate" else 6) + index
                    ],
                }
                for index, route in enumerate(routes)
            ],
        }
        for item in receipts["receipts"]:
            report_bytes = item["report"].encode("utf-8")
            item["report_sha256"] = _sha256(report_bytes)
            item["report_bytes"] = len(report_bytes)
            item["broker"] = _broker_observation(
                verifier,
                item["harness"],
                item["resolved_model"],
                f"{variant}:{round_name}:{item['harness']}",
                inputs,
                item["report"],
                repo,
                item["session_sha256"],
            )
            runtime_record = {
                "schema": "harden_broker_run_receipt.v1",
                "head": head,
                "tree": trees[round_name],
                "harness": item["harness"],
                "model": item["resolved_model"],
                "seat_key": item["seat_id"],
                "status": "OK",
                "report": item["report"],
                "report_sha256": item["report_sha256"],
                "report_bytes": item["report_bytes"],
                "broker": item["broker"],
            }
            relative = (
                f".phase-loop/runs/{variant}-{round_name}/"
                f"implementation-panel-{item['harness']}.harden-broker-run.json"
            )
            runtime_bytes = _canonical_bytes(runtime_record)
            if item["harness"] != "claude":
                # Stateless non-Claude seats bind identity to the complete
                # canonical one-shot observation, not a caller's fresh label.
                item["session_sha256"] = _sha256(runtime_bytes)
                reviewer_sessions[round_name, item["harness"]] = item["session_sha256"]
            _write_ref(repo, relative, runtime_bytes)
            item["runtime_receipt"] = _write_ref(source_root, relative, runtime_bytes)
        artifacts[f"{round_name}_broker_receipts"] = _write_ref(
            source_root,
            f"raw/{round_name}-broker-receipts.json",
            _canonical_bytes(receipts),
        )
    operation_nonces.extend(reviewer_sessions.values())
    sessions = {
        role: _sha256(f"{variant}:{role}-session".encode()) for role in ROLE_NAMES
    }
    sessions["reviewer"] = _sha256(
        "\0".join(sorted(reviewer_sessions.values())).encode()
    )
    role_attestations = {
        role: _write_ref(
            source_root,
            f"raw/{role}-attestation.json",
            _canonical_bytes(
                {
                    "schema": "harden_role_attestation.v1",
                    "annotation": f"retained input {variant}",
                    "role": role,
                    "identity": (
                        "reviewer-" + session[:32]
                        if role == "reviewer"
                        else f"{variant}-{role}"
                    ),
                    "vendor": author_vendor if role == "author" else role,
                    "session_sha256": session,
                    "evidence_id": evidence_id,
                    "issued_at": "2026-09-05T00:00:00Z",
                    "operation_nonce": operation_nonces[10 + index],
                }
            ),
        )
        for index, (role, session) in enumerate(sessions.items())
    }
    manifest = {
        "schema": INPUT_SCHEMA,
        "artifacts": artifacts,
        "role_attestations": role_attestations,
    }
    assert set(artifacts) == set(RAW_ARTIFACT_NAMES)
    manifest_path = root / "harden-evidence-inputs.json"
    manifest_path.write_bytes(_canonical_bytes(manifest))
    unrelated_registry_id = _sha256(f"{variant}:unrelated-evidence".encode())
    unrelated_registry_nonce = _sha256(f"{variant}:unrelated-nonce".encode())
    registry_path = root / "reuse-registry.json"
    registry_path.write_bytes(
        _canonical_bytes(
            {
                "schema": "harden_evidence_registry.v1",
                "evidence_ids": [unrelated_registry_id],
                "operation_nonces": [unrelated_registry_nonce],
            }
        )
    )
    ci_responses = {
        str(run_id): {
            "databaseId": run_id,
            "headSha": commits[round_name],
            "status": "completed",
            "conclusion": "success",
            "event": "pull_request" if round_name == "candidate" else "push",
            "workflowName": "test",
            "attempt": 1,
            "jobs": [
                {
                    "databaseId": run_id * 100 + 1,
                    "name": "suite gate",
                    "status": "completed",
                    "conclusion": "success",
                    "startedAt": "2026-09-05T00:00:00Z",
                    "completedAt": "2026-09-05T00:00:01Z",
                    "url": f"https://example.invalid/job/{run_id}",
                    "steps": [],
                }
            ],
        }
        for round_name, run_id in ci_run_ids.items()
    }
    (root / "ci-responses.json").write_bytes(_canonical_bytes(ci_responses))
    ci_query = root / "fake-gh"
    ci_query.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "root = pathlib.Path(__file__).resolve().parent\n"
        "responses = json.loads((root / 'ci-responses.json').read_bytes())\n"
        "assert len(sys.argv) == 8 and sys.argv[3] in responses, 'unexpected CI query'\n"
        "assert sys.argv[1:] == ['run', 'view', sys.argv[3], '--repo', "
        "'github.com/Consiliency/agent-harness', '--json', "
        "'databaseId,headSha,status,conclusion,event,workflowName,attempt,jobs'], 'unexpected CI query'\n"
        "with (root / 'ci-queries.jsonl').open('a') as log:\n"
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "print(json.dumps(responses[sys.argv[3]]))\n",
        encoding="utf-8",
    )
    ci_query.chmod(0o700)
    expected = {
        "evidence_id": evidence_id,
        "commits": commits,
        "trees": trees,
        "changed_paths": {
            "reviewed_sl0": sorted(frozen_paths),
            "candidate": sorted([production_path, marker_path]),
            "canonical_main": [],
        },
        "frozen_test_paths": sorted(frozen_paths),
        "run_counts": {
            name: {
                outcome: outcomes.count(outcome)
                for outcome in ("passed", "failed", "skipped")
            }
            for name, (_nodes, outcomes) in run_cases.items()
        },
        "author_vendor": author_vendor,
        "routes": routes,
        "reviewer_sessions": reviewer_sessions,
        "operation_nonces": operation_nonces,
        "registry": {
            "evidence_ids": [unrelated_registry_id],
            "operation_nonces": [unrelated_registry_nonce],
        },
        "ci_run_ids": ci_run_ids,
    }
    return {
        "root": root,
        "repo": repo,
        "source_root": source_root,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "registry": registry_path,
        "sessions": sessions,
        "expected": expected,
        "evidence_root": root / "prepared-evidence",
        "output": root / "verification-evidence.v3.json",
        "request": root / "completion-request.json",
        "ci_query": ci_query,
    }


def _ci_provider_attack(context: dict[str, Any], round_name: str, attack: str) -> None:
    path = context["root"] / "ci-responses.json"
    responses = _strict_json(path)
    response = responses[str(context["expected"]["ci_run_ids"][round_name])]
    if attack == "stale-head":
        response["headSha"] = context["expected"]["commits"]["landing"]
    elif attack == "failed":
        response["conclusion"] = "failure"
        response["jobs"][0]["conclusion"] = "failure"
    elif attack == "missing-gate":
        response["jobs"][0]["name"] = "not the suite gate"
    else:
        raise AssertionError(attack)
    path.write_bytes(_canonical_bytes(responses))


def _persist_manifest(context: dict[str, Any]) -> None:
    context["manifest_path"].write_bytes(_canonical_bytes(context["manifest"]))


def _prepare_command(context: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    ledger = context["repo"] / ".phase-loop/events.jsonl"
    protected = (
        context["manifest_path"],
        context["source_root"],
        context["repo"] / ".phase-loop/runs",
        ledger,
    )
    before = [_path_snapshot(path) for path in protected]
    context["prepare_manifest_sha256"] = _sha256(context["manifest_path"].read_bytes())
    context["prepare_source_inventory"] = {
        name: _sha256(record[1])
        for name, record in before[1].items()
        if record[0] == "file"
    }
    completed = _producer_command(
        "prepare",
        "--inputs",
        str(context["manifest_path"]),
        "--source-root",
        str(context["source_root"]),
        "--evidence-root",
        str(context["evidence_root"]),
        "--repo",
        str(context["repo"]),
        "--output",
        str(context["output"]),
        "--completion-request",
        str(context["request"]),
        "--reuse-registry",
        str(context["registry"]),
        "--expected-coordinator-session-sha256",
        context["sessions"]["coordinator"],
        "--expected-author-session-sha256",
        context["sessions"]["author"],
    )
    assert [_path_snapshot(path) for path in protected] == before, (
        "prepare modified retained input or canonical evidence"
    )
    return completed


def _path_snapshot(root: Path) -> dict[str, tuple[Any, ...]]:
    paths = (
        [root, *root.rglob("*")] if root.is_dir() and not root.is_symlink() else [root]
    )
    snapshot = {}
    for path in paths:
        name = str(path.relative_to(root))
        if path.is_symlink():
            snapshot[name] = ("symlink", os.readlink(path))
        elif path.is_file():
            snapshot[name] = ("file", path.read_bytes())
        elif path.is_dir():
            snapshot[name] = ("directory",)
        else:
            snapshot[name] = ("absent",)
    return snapshot


def _seal_command(
    context: dict[str, Any],
    ledger: Path,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    return _producer_command(
        "seal",
        "--pre-completion",
        str(context["output"]),
        "--evidence-root",
        str(context["evidence_root"]),
        "--repo",
        str(context["repo"]),
        "--ledger",
        str(ledger),
        "--output",
        str(output),
        "--reuse-registry",
        str(context["registry"]),
        "--expected-coordinator-session-sha256",
        context["sessions"]["coordinator"],
        "--expected-author-session-sha256",
        context["sessions"]["author"],
    )


def _assert_no_prepare_output(context: dict[str, Any]) -> None:
    assert not context["output"].exists()
    assert not context["request"].exists()
    assert not context["evidence_root"].exists() or not any(
        context["evidence_root"].iterdir()
    )


def _normalized_precompletion_digest(evidence: dict[str, Any]) -> str:
    normalized = copy.deepcopy(evidence)
    normalized["completion"] = {"mode": "pre_completion"}
    return _sha256(_canonical_bytes(normalized))


def _completion_event(
    request: dict[str, Any], *, timestamp: str = "2026-09-04T00:00:00Z"
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "phase": "HARDEN",
        "action": "phase_execute",
        "status": "complete",
        "metadata": {
            "harden_completion": {
                "schema": "harden_completion.v1",
                "evidence_sha256": request["evidence_sha256"],
                "canonical_commit": request["canonical_commit"],
                "canonical_tree": request["canonical_tree"],
                "visual_render_declared": False,
            }
        },
    }


def _history_event() -> dict[str, Any]:
    return {
        "timestamp": "2026-09-03T00:00:00Z",
        "phase": "SCHED",
        "action": "phase_execute",
        "status": "complete",
        "metadata": {"history": True},
    }


def _blocked_harden_event() -> dict[str, Any]:
    return {
        "timestamp": "2026-09-03T12:00:00Z",
        "phase": "HARDEN",
        "action": "phase_execute",
        "status": "blocked",
        "metadata": {"history": True},
    }


def _ledger_history_bytes() -> bytes:
    return _canonical_bytes(_history_event()) + _canonical_bytes(
        _blocked_harden_event()
    )


def _ledger_bytes(request: dict[str, Any]) -> bytes:
    return _ledger_history_bytes() + _canonical_bytes(_completion_event(request))


def _contained_ref_path(root: Path, ref: dict[str, str], label: str) -> Path:
    assert set(ref) == {"path", "sha256"}
    raw = ref["path"]
    relative = PurePosixPath(raw)
    assert not relative.is_absolute(), f"{label} path must be relative"
    assert str(relative) == raw and all(
        part not in {"", ".", ".."} for part in relative.parts
    ), f"{label} path must be normalized"
    assert not root.is_symlink(), f"{label} root is a symlink"
    unresolved = root
    for part in relative.parts:
        unresolved /= part
        assert not unresolved.is_symlink(), f"{label} path contains a symlink"
    root_resolved = root.resolve(strict=True)
    path = unresolved.resolve(strict=True)
    assert path.is_relative_to(root_resolved), f"{label} path escaped its root"
    assert path.is_file(), f"{label} is not a regular file"
    assert _sha256(path.read_bytes()) == ref["sha256"], f"{label} digest mismatch"
    return path


def _reachable_artifact_refs(value: Any, root: Path) -> set[tuple[str, str]]:
    reachable: set[tuple[str, str]] = set()
    queued = [value]
    while queued:
        item = queued.pop()
        if isinstance(item, list):
            queued.extend(item)
            continue
        if not isinstance(item, dict):
            continue
        if set(item) == {"path", "sha256"}:
            path = _contained_ref_path(root, item, "reachable retained artifact")
            key = (item["path"], item["sha256"])
            if key in reachable:
                continue
            reachable.add(key)
            if path.suffix == ".json":
                queued.append(_strict_json(path))
            continue
        queued.extend(item.values())
    return reachable


def _verify_with_shipped_verifier(
    context: dict[str, Any], evidence_path: Path, label: str
) -> None:
    verifier = _load_shipped_verifier()
    registry = context["root"] / f"shipped-verifier-{label}-registry.json"
    registry.write_bytes(
        _canonical_bytes(
            {
                "schema": "harden_evidence_registry.v1",
                "evidence_ids": [],
                "operation_nonces": [],
            }
        )
    )
    verifier.verify(
        evidence_path,
        context["evidence_root"],
        context["repo"],
        reuse_registry=registry,
        expected_coordinator_session=context["sessions"]["coordinator"],
        expected_author_session=context["sessions"]["author"],
        ci_query=context["ci_query"],
    )


def _assert_prepared(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = _strict_json(context["output"])
    request = _strict_json(context["request"])
    assert set(evidence) == {
        "schema",
        "evidence_id",
        "repository",
        "git",
        "authority",
        "sl0",
        "verification",
        "ci",
        "reviews",
        "roles",
        "completion",
    }
    assert evidence["schema"] == "verification_evidence.v3"
    assert evidence["completion"] == {"mode": "pre_completion"}
    assert evidence["evidence_id"] == context["expected"]["evidence_id"]
    for name, commit in context["expected"]["commits"].items():
        assert evidence["git"][name] == {
            "commit": commit,
            "tree": context["expected"]["trees"][name],
        }
    assert (
        sorted(item["path"] for item in evidence["sl0"]["frozen_inventory"])
        == (context["expected"]["frozen_test_paths"])
    )
    for round_name, run_id in context["expected"]["ci_run_ids"].items():
        assert (
            evidence["ci"][round_name]["head"]
            == context["expected"]["commits"][round_name]
        )
        assert evidence["ci"][round_name]["run_id"] == run_id
    assert set(evidence["reviews"]) == {"candidate", "canonical_main"}
    assert set(evidence["roles"]) == set(ROLE_NAMES)
    historical = _strict_json(
        context["source_root"] / context["manifest"]["artifacts"]["sl0_review"]["path"]
    )
    for field in ("approval", "production_start"):
        assert evidence["sl0"][field]["sha256"] == historical[field]["sha256"]

    def retained_json(ref: dict[str, str], label: str) -> dict[str, Any]:
        path = _contained_ref_path(context["evidence_root"], ref, label)
        value = _strict_json(path)
        assert isinstance(value, dict)
        return value

    receipt_refs = {
        "preproduction_red": evidence["sl0"]["activated_red"]["receipt"],
        "preproduction_control": evidence["sl0"]["pure_control"]["receipt"],
        "candidate_focused": evidence["verification"]["candidate"]["focused"][
            "receipt"
        ],
        "candidate_broad": evidence["verification"]["candidate"]["broad"]["receipt"],
        "candidate_pure_control": evidence["verification"]["candidate"]["pure_control"][
            "receipt"
        ],
        "canonical_main_focused": evidence["verification"]["canonical_main"]["focused"][
            "receipt"
        ],
        "canonical_main_broad": evidence["verification"]["canonical_main"]["broad"][
            "receipt"
        ],
        "canonical_main_pure_control": evidence["verification"]["canonical_main"][
            "pure_control"
        ]["receipt"],
    }
    for name, ref in receipt_refs.items():
        receipt_record = retained_json(ref, f"{name} receipt")
        summary = receipt_record["summary"]
        expected_counts = context["expected"]["run_counts"][name]
        assert {
            outcome: summary[outcome] for outcome in ("passed", "failed", "skipped")
        } == expected_counts
        observation_index = _strict_json(
            context["source_root"]
            / context["manifest"]["artifacts"]["execution_runs"]["path"]
        )
        observation_ref = observation_index["runs"][name]
        observed = _strict_json(context["source_root"] / observation_ref["path"])
        for field in (
            "head",
            "tree",
            "process_nonce",
            "exit_code",
            "argv_class",
            "argv",
            "cwd",
            "env_keys",
            "source_tree",
            "baseline",
        ):
            assert receipt_record[field] == observed[field], field
        result = (
            evidence["sl0"][
                "activated_red" if name == "preproduction_red" else "pure_control"
            ]
            if name.startswith("preproduction_")
            else evidence["verification"][
                "canonical_main" if name.startswith("canonical_main_") else "candidate"
            ][name.removeprefix("canonical_main_").removeprefix("candidate_")]
        )
        for field in ("raw", "junit"):
            assert result[field]["sha256"] == observed[field]["sha256"]
            assert receipt_record[field + "_sha256"] == observed[field]["sha256"]
    for round_name in ("candidate", "canonical_main"):
        group = evidence["verification"][round_name]
        supplied_group = observation_index["groups"][round_name]
        assert group["run_nonce"] == supplied_group["run_nonce"]
        assert group["commit"] == supplied_group["head"]
        assert group["tree"] == supplied_group["tree"]
        supplied_lint = _strict_json(
            context["source_root"]
            / observation_index["runs"][round_name + "_lint"]["path"]
        )
        assert retained_json(group["lint"]["receipt"], "lint receipt") == supplied_lint
        assert group["lint"]["raw"]["sha256"] == supplied_lint["raw_sha256"]

    source_mutations = _strict_json(
        context["source_root"]
        / context["manifest"]["artifacts"]["source_mutations"]["path"]
    )["mutations"]
    assert {entry["case_id"] for entry in evidence["sl0"]["mutations"]} == set(
        HARDEN_CASES
    )
    by_case = {entry["case_id"]: entry for entry in source_mutations}
    for entry in evidence["sl0"]["mutations"]:
        supplied = by_case[entry["case_id"]]
        for field in ("source_path", "nodeid"):
            assert entry[field] == supplied[field]
        for field in ("mutated_source", "restored_source"):
            assert entry[field]["sha256"] == supplied[field]["sha256"]
        for stage in ("mutation", "restored"):
            for field in ("raw", "junit", "receipt"):
                assert entry[stage][field]["sha256"] == supplied[stage][field]["sha256"]

    author = retained_json(evidence["roles"]["author"], "author attestation")
    assert author["vendor"] == context["expected"]["author_vendor"]
    expected_routes = {
        route["harness"]: route for route in context["expected"]["routes"]
    }
    for round_name in ("candidate", "canonical_main"):
        review = evidence["reviews"][round_name]
        review_request = retained_json(
            review["request"], f"{round_name} review request"
        )
        assert {
            seat["harness"]: seat["requested_model"] for seat in review_request["seats"]
        } == {
            harness: route["requested_model"]
            for harness, route in expected_routes.items()
        }
        retained_brokers = _strict_json(
            context["source_root"]
            / context["manifest"]["artifacts"][f"{round_name}_broker_receipts"]["path"]
        )
        by_harness = {item["harness"]: item for item in retained_brokers["receipts"]}
        for item in review["seats"]:
            seat = retained_json(item["artifact"], "prepared review seat")
            source = by_harness[item["harness"]]
            for field in (
                "seat_id",
                "session_sha256",
                "harness_provenance",
                "report",
                "report_sha256",
                "report_bytes",
                "broker",
                "runtime_receipt",
            ):
                assert seat[field] == source[field], field
        assert {
            item["harness"]: retained_json(
                item["artifact"], f"{round_name} {item['harness']} seat"
            )["resolved_model"]
            for item in review["seats"]
        } == {
            harness: route["resolved_model"]
            for harness, route in expected_routes.items()
        }
    assert set(request) == {
        "schema",
        "phase",
        "evidence_sha256",
        "canonical_commit",
        "canonical_tree",
        "visual_render_declared",
        "input_manifest_sha256",
        "copied_artifacts",
    }
    assert request["schema"] == "harden_completion_request.v1"
    assert request["phase"] == "HARDEN"
    assert request["evidence_sha256"] == _normalized_precompletion_digest(evidence)
    assert request["input_manifest_sha256"] == context["prepare_manifest_sha256"]
    assert (
        request["canonical_commit"] == context["expected"]["commits"]["canonical_main"]
    )
    assert request["canonical_tree"] == context["expected"]["trees"]["canonical_main"]
    assert request["visual_render_declared"] is False
    source_inventory = context["prepare_source_inventory"]
    copies = request["copied_artifacts"]
    assert isinstance(copies, list) and copies
    copied_sources = {
        item["source"]["path"]: item["source"]["sha256"] for item in copies
    }
    assert len(copies) == len(copied_sources) == len(source_inventory)
    assert copied_sources == source_inventory
    retained_paths = [item["retained"]["path"] for item in copies]
    retained_refs = [
        (item["retained"]["path"], item["retained"]["sha256"]) for item in copies
    ]
    assert len(retained_paths) == len(set(retained_paths))
    assert len(retained_refs) == len(set(retained_refs))
    copied_by_source = {
        (item["source"]["path"], item["source"]["sha256"]): item["retained"]
        for item in copies
    }
    for item in copies:
        assert set(item) == {"source", "retained"}
        assert set(item["source"]) == {"path", "sha256"}
        source = _contained_ref_path(
            context["source_root"], item["source"], "source artifact"
        )
        retained = _contained_ref_path(
            context["evidence_root"], item["retained"], "copied retained artifact"
        )
        assert source.read_bytes() == retained.read_bytes()
    assert not any(path.is_symlink() for path in context["evidence_root"].rglob("*"))
    required_reachable_refs = [
        context["manifest"]["artifacts"][name] for name in sorted(RAW_ARTIFACT_NAMES)
    ] + [context["manifest"]["role_attestations"][name] for name in ROLE_NAMES]
    required_retained_refs = {
        (
            copied_by_source[(ref["path"], ref["sha256"])]["path"],
            copied_by_source[(ref["path"], ref["sha256"])]["sha256"],
        )
        for ref in required_reachable_refs
    }
    assert len(required_retained_refs) == len(required_reachable_refs)
    reachable = _reachable_artifact_refs(evidence, context["evidence_root"])
    assert required_retained_refs <= reachable
    queries = [
        json.loads(line)
        for line in (context["root"] / "ci-queries.jsonl").read_text().splitlines()
    ]
    assert {query[2] for query in queries} == {
        str(run_id) for run_id in context["expected"]["ci_run_ids"].values()
    }
    _verify_with_shipped_verifier(context, context["output"], "prepared")
    return evidence, request


def _assert_fixture_proof_sources(context: dict[str, Any]) -> None:
    repo = context["repo"]
    verifier = _load_shipped_verifier()
    digests: dict[str, set[str]] = {}
    for path, digest in _reachable_artifact_refs(
        context["manifest"], context["source_root"]
    ):
        digests.setdefault(digest, set()).add(path)
    assert all(len(paths) == 1 for paths in digests.values()), (
        "distinct proof artifacts reused bytes"
    )
    verifier.verify_clean_canonical_main_context(
        repo, context["expected"]["commits"]["canonical_main"]
    )
    assert (
        context["expected"]["trees"]["candidate"]
        == context["expected"]["trees"]["canonical_main"]
    )
    assert not _git(
        repo,
        "diff",
        "--name-only",
        context["expected"]["commits"]["candidate"],
        context["expected"]["commits"]["canonical_main"],
    )
    for label, required in (
        ("reviewed_sl0", False),
        ("landing", False),
        ("candidate", True),
        ("canonical_main", True),
    ):
        verifier._marker_state(
            repo, context["expected"]["commits"][label], required=required
        )
    assert _git(
        repo,
        "rev-list",
        "--parents",
        "-n",
        "1",
        context["expected"]["commits"]["landing"],
    ).split()[1:] == [
        context["expected"]["commits"]["sl0_base"],
        context["expected"]["commits"]["reviewed_sl0"],
    ]
    store = verifier.ArtifactStore(context["source_root"])
    historical = store.json(
        context["manifest"]["artifacts"]["sl0_review"], "historical SL0 review"
    )
    approval = verifier.run_owned_receipt(
        store, repo, historical["approval"], "historical SL0 approval"
    )
    production_start = verifier.run_owned_receipt(
        store, repo, historical["production_start"], "production start"
    )
    assert approval["head"] == context["expected"]["commits"]["reviewed_sl0"]
    assert approval["tree"] == context["expected"]["trees"]["reviewed_sl0"]
    assert approval["clock_id"] == production_start["clock_id"]
    assert approval["observed_monotonic_ns"] < production_start["observed_monotonic_ns"]
    assert production_start["head"] == context["expected"]["commits"]["landing"]
    assert production_start["sl0_approval"] == historical["approval"]
    assert production_start["tree"] == context["expected"]["trees"]["landing"]
    assert (
        production_start["source_mutations"]
        == context["manifest"]["artifacts"]["source_mutations"]
    )
    execution_index = store.json(
        context["manifest"]["artifacts"]["execution_runs"], "execution index"
    )
    for name in ("preproduction_red", "preproduction_control"):
        ref = production_start["preproduction_runs"][name]
        assert ref == execution_index["runs"][name]
        observed = verifier.run_owned_receipt(
            store, repo, ref, "preproduction observation"
        )
        assert observed["clock_id"] == production_start["clock_id"]
        assert approval["observed_monotonic_ns"] < observed["started_monotonic_ns"]
        assert (
            observed["started_monotonic_ns"]
            <= observed["finished_monotonic_ns"]
            < production_start["observed_monotonic_ns"]
        )
    assert {seat["harness"] for seat in approval["seats"]} == {
        "claude",
        "codex",
        "gemini",
        "grok",
    }
    assert len({seat["session_sha256"] for seat in approval["seats"]}) == 4
    for seat in approval["seats"]:
        assert (
            seat["status"] == "usable"
            and seat["report"].rstrip().splitlines()[-1] == "AGREE"
        )
        assert seat["report_sha256"] == _sha256(seat["report"].encode())
        assert seat["report_bytes"] == len(seat["report"].encode())
        assert seat["session_sha256"] not in context["sessions"].values()
    mutations = store.json(
        context["manifest"]["artifacts"]["source_mutations"], "source mutations"
    )["mutations"]
    assert {entry["case_id"] for entry in mutations} == set(HARDEN_CASES)
    for entry in mutations:
        contract = HARDEN_CASES[entry["case_id"]]
        assert entry["source_path"] == contract.production_path
        assert entry["nodeid"] == contract.nodeid
        for stage, kind, outcome, expected_result in (
            ("mutation", "source_mutation", "failure", False),
            ("restored", "restored_control", "passed", True),
        ):
            source = entry[
                "mutated_source" if stage == "mutation" else "restored_source"
            ]
            namespace: dict[str, Any] = {}
            exec(
                compile(store.read(source, "source proof"), source["path"], "exec"),
                namespace,
            )
            assert namespace[contract.symbol]() is expected_result
            run = entry[stage]
            observed = verifier.run_owned_receipt(
                verifier.ArtifactStore(context["source_root"]),
                repo,
                run["receipt"],
                "source mutation process receipt",
            )
            assert observed["clock_id"] == production_start["clock_id"]
            assert approval["observed_monotonic_ns"] < observed["started_monotonic_ns"]
            assert (
                observed["started_monotonic_ns"]
                <= observed["finished_monotonic_ns"]
                < production_start["observed_monotonic_ns"]
            )
            verifier.exact_case(
                verifier.parse_junit(
                    store.read(run["junit"], "proof JUnit"), "proof JUnit"
                ),
                contract.nodeid,
                outcome,
                "proof JUnit",
            )
            assert observed == {
                "schema": "harden_pytest_receipt.v1",
                "kind": kind,
                "head": context["expected"]["commits"]["reviewed_sl0"],
                "tree": context["expected"]["trees"]["reviewed_sl0"],
                "process_nonce": observed["process_nonce"],
                "clock_id": production_start["clock_id"],
                "started_monotonic_ns": observed["started_monotonic_ns"],
                "finished_monotonic_ns": observed["finished_monotonic_ns"],
                "argv_class": f"pytest_harden_{kind}_v1",
                "exit_code": int(not expected_result),
                "raw_sha256": run["raw"]["sha256"],
                "junit_sha256": run["junit"]["sha256"],
                "source_path": contract.production_path,
                "source_sha256": source["sha256"],
            }
    sessions = set()
    for round_name in ("candidate", "canonical_main"):
        records = store.json(
            context["manifest"]["artifacts"][f"{round_name}_broker_receipts"],
            "review observations",
        )["receipts"]
        assert len(records) == 4
        request = store.json(
            context["manifest"]["artifacts"][f"{round_name}_review_request"],
            "review request",
        )
        inputs = {
            kind: store.json(request[kind], kind)["content"]
            for kind in ("bundle", "instructions")
        }
        for record in records:
            assert record["head"] == context["expected"]["commits"][round_name]
            assert record["tree"] == context["expected"]["trees"][round_name]
            assert record["session_sha256"] not in sessions
            sessions.add(record["session_sha256"])
            report = record["report"].encode()
            assert _sha256(report) == record["report_sha256"]
            assert len(report) == record["report_bytes"]
            assert record["report"].rstrip().splitlines()[-1] == "AGREE"
            verifier.verify_broker(
                record["broker"],
                record["harness"],
                record["requested_model"],
                record["resolved_model"],
                _sha256(inputs["bundle"].encode()),
                _sha256(inputs["instructions"].encode()),
                verifier.broker_sealed_prompt(inputs["bundle"], inputs["instructions"]),
                record["report"],
            )
            runtime = verifier.run_owned_receipt(
                store, repo, record["runtime_receipt"], "runtime receipt"
            )
            assert runtime["broker"] == record["broker"]
            assert runtime["report"] == record["report"]
            assert record["broker"]["canonical_repo_sha256"] == _sha256(
                os.fsencode(str(repo.resolve()))
            )
            observed_session = (
                runtime["broker"]["claude_session_id_sha256"]
                if record["harness"] == "claude"
                else _sha256(_canonical_bytes(runtime))
            )
            assert record["session_sha256"] == observed_session
    assert len(sessions) == 8
    assert not sessions & {seat["session_sha256"] for seat in approval["seats"]}
    assert context["sessions"]["reviewer"] == _sha256(
        "\0".join(sorted(sessions)).encode()
    )
    assert not sessions & set(context["sessions"].values())
    index = _strict_json(
        context["source_root"]
        / context["manifest"]["artifacts"]["execution_runs"]["path"]
    )
    environment = dict(os.environ)
    for key in ("PHASE_LOOP_TDD_EXPECT_HARDEN", "PYTEST_ADDOPTS"):
        environment.pop(key, None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    audit_root = context["root"] / "source-execution-audit"
    audit_root.mkdir()
    try:
        for name, ref in index["runs"].items():
            if name.endswith("_lint"):
                continue
            observed = _strict_json(context["source_root"] / ref["path"])
            assert (repo / ref["path"]).read_bytes() == (
                context["source_root"] / ref["path"]
            ).read_bytes()
            _git(repo, "checkout", "-q", observed["head"])
            junit = audit_root / f"{name}.xml"
            # The audit adds only the report destination to the retained command;
            # selection, activation and working directory are unchanged.
            completed = subprocess.run(
                [*observed["argv"], "--junitxml", str(junit)],
                cwd=repo / observed["cwd"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            assert completed.returncode == observed["exit_code"], (
                completed.stdout + completed.stderr
            )
            measured = verifier.parse_junit(junit.read_bytes(), name)
            supplied = verifier.parse_junit(
                (context["source_root"] / observed["junit"]["path"]).read_bytes(), name
            )
            assert sorted(
                (case["node"], case["status"]) for case in measured
            ) == sorted((case["node"], case["status"]) for case in supplied), name
    finally:
        _git(repo, "checkout", "-q", "main")
    verifier.verify_clean_canonical_main_context(
        repo, context["expected"]["commits"]["canonical_main"]
    )


def test_harden_producer_fixture_preserves_supplied_proof_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise every input variant while the production capability is absent."""
    for index, (author, red, final) in enumerate(_fixture_variants()):
        root = tmp_path / str(index)
        context = _raw_fixture(
            root,
            variant=_runtime_variant(root),
            author_vendor=author,
            red_outcomes=red,
            final_outcomes=final,
        )
        _assert_fixture_proof_sources(context)
    verifier_path = (
        _repo_root() / "phase-loop-runtime/scripts/verify_harden_evidence.py"
    )
    # Exercise the exact subprocess boundary even before the real producer exists.
    # This probe imports the unchanged validator, not a permissive replacement.
    cli_root = tmp_path / "cli-probe"
    probe = cli_root / PRODUCER_PATH
    probe.parent.mkdir(parents=True)
    probe.write_text(
        "import importlib.util, json, pathlib, subprocess\n"
        f"spec = importlib.util.spec_from_file_location('verifier', {str(verifier_path)!r})\n"
        "verifier = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(verifier)\n"
        f"root = pathlib.Path({str(context['root'])!r})\n"
        "assert verifier.CANONICAL_GH.lstat().st_ino == (root / 'fake-gh').lstat().st_ino\n"
        "assert verifier._ci_query_mode(verifier.ArtifactStore(root), verifier.CANONICAL_GH)\n"
        "environment = verifier.github_cli_environment(root, canonical=True)\n"
        f"runs = {context['expected']['ci_run_ids']!r}\n"
        f"heads = {context['expected']['commits']!r}\n"
        "for name, run_id in runs.items():\n"
        "    response = json.loads(subprocess.check_output(verifier.ci_command(run_id), env=environment))\n"
        "    assert verifier.normalize_ci_jobs(response['jobs'], canonical=True)\n"
        "    assert response['headSha'] == heads[name] and response['conclusion'] == 'success'\n"
        "print('hermetic canonical CI boundary passed')\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setitem(globals(), "_repo_root", lambda: cli_root)
    completed = _producer_command("--evidence-root", str(context["evidence_root"]))
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "hermetic canonical CI boundary passed"
    responses_path = context["root"] / "ci-responses.json"
    original_responses = responses_path.read_bytes()
    retained_claims = {
        name: (
            context["source_root"]
            / context["manifest"]["artifacts"][name + "_ci"]["path"]
        ).read_bytes()
        for name in ("candidate", "canonical_main")
    }
    try:
        for name in ("candidate", "canonical_main"):
            for attack in ("stale-head", "failed", "missing-gate"):
                responses_path.write_bytes(original_responses)
                _ci_provider_attack(context, name, attack)
                completed = _producer_command(
                    "--evidence-root", str(context["evidence_root"])
                )
                assert completed.returncode != 0, (name, attack)
                assert (
                    context["source_root"]
                    / context["manifest"]["artifacts"][name + "_ci"]["path"]
                ).read_bytes() == retained_claims[name]
    finally:
        responses_path.write_bytes(original_responses)
    command = [
        str(context["ci_query"]),
        "run",
        "view",
        str(context["expected"]["ci_run_ids"]["candidate"]),
        "--repo",
        "github.com/Consiliency/agent-harness",
        "--json",
        "databaseId,headSha,status,conclusion,event,workflowName,attempt,jobs",
    ]
    for index in range(1, len(command)):
        invalid = list(command)
        invalid[index] = "invalid-query-argument"
        rejected_query = subprocess.run(
            invalid, capture_output=True, text=True, timeout=10, check=False
        )
        assert (
            rejected_query.returncode != 0
            and "unexpected CI query" in rejected_query.stderr
        )


def test_harden_producer_derives_live_facts_without_historical_literals() -> None:
    producer = _producer_module("derive")
    source = (_repo_root() / PRODUCER_PATH).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=PRODUCER_PATH)
    forbidden = {
        "FINAL_RUN_SPECS",
        "FROZEN_SL0_PATHS",
        "PLAN_PRODUCTION_PATHS",
        "SELF_TEST_ROUTES",
        "_fixture",
        "self_test",
    }
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    def static_string(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = static_string(node.left)
            right = static_string(node.right)
            if left is not None and right is not None:
                return left + right
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "join"
            and len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], (ast.List, ast.Tuple))
        ):
            separator = static_string(node.func.value)
            parts = [static_string(item) for item in node.args[0].elts]
            if separator is not None and all(part is not None for part in parts):
                return separator.join(part for part in parts if part is not None)
        if isinstance(node, ast.Subscript) and isinstance(
            node.value, (ast.List, ast.Tuple)
        ):
            index_node = node.slice
            sign = 1
            while isinstance(index_node, ast.UnaryOp) and isinstance(
                index_node.op, (ast.UAdd, ast.USub)
            ):
                if isinstance(index_node.op, ast.USub):
                    sign *= -1
                index_node = index_node.operand
            if isinstance(index_node, ast.Constant) and isinstance(
                index_node.value, int
            ):
                index = sign * index_node.value
                if -len(node.value.elts) <= index < len(node.value.elts):
                    return static_string(node.value.elts[index])
        return None

    alias_names = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.alias)
        for name in (*node.name.split("."), node.asname)
        if name is not None
    }
    alias_names.update(
        segment
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
        for segment in node.module.split(".")
    )
    reconstructed_strings = {
        value for node in ast.walk(tree) if (value := static_string(node)) is not None
    }
    dynamic_accesses: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            value = static_string(node.slice)
            if value is not None:
                dynamic_accesses.add(value)
        if not isinstance(node, ast.Call):
            continue
        function_name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        argument_index = 0 if function_name == "attrgetter" else 1
        if (
            function_name
            in {
                "attrgetter",
                "delattr",
                "getattr",
                "hasattr",
                "setattr",
            }
            and len(node.args) > argument_index
        ):
            value = static_string(node.args[argument_index])
            if value is not None:
                dynamic_accesses.add(value)
    assert not forbidden & {
        segment
        for name in referenced | alias_names | reconstructed_strings | dynamic_accesses
        for segment in name.split(".")
    }
    for literal in (
        "16 failed, 439 passed, 3 skipped",
        "454 passed",
        "codex-gpt-5.6-terra",
    ):
        assert literal not in source
    assert INPUT_SCHEMA in source
    for name in ("derive_live_facts", "prepare", "seal"):
        assert callable(getattr(producer, name, None)), name

    facts_seen = []
    for author, red, final in _fixture_variants():
        with tempfile.TemporaryDirectory(prefix="pl-") as td:
            fixture_root = Path(td) / "fixture"
            context = _raw_fixture(
                fixture_root,
                variant=_runtime_variant(fixture_root),
                author_vendor=author,
                red_outcomes=red,
                final_outcomes=final,
            )
            facts = producer.derive_live_facts(
                context["manifest_path"],
                evidence_root=context["source_root"],
                repo=context["repo"],
            )
            assert set(facts) == {
                "schema",
                "git",
                "changed_paths",
                "frozen_test_paths",
                "run_counts",
                "author_vendor",
                "routes",
            }
            assert facts["schema"] == "harden_live_facts.v1"
            assert facts["git"] == {
                name: {
                    "commit": context["expected"]["commits"][name],
                    "tree": context["expected"]["trees"][name],
                }
                for name in context["expected"]["commits"]
            }
            for key in (
                "changed_paths",
                "frozen_test_paths",
                "run_counts",
                "author_vendor",
                "routes",
            ):
                assert facts[key] == context["expected"][key]
            facts_seen.append(facts)
    for key in (
        "git",
        "changed_paths",
        "frozen_test_paths",
        "run_counts",
        "author_vendor",
        "routes",
    ):
        assert len({_canonical_bytes(facts[key]) for facts in facts_seen}) == len(
            facts_seen
        )


def test_harden_producer_assembles_only_contained_retained_evidence() -> None:
    _producer_module("assemble")

    for index, (author, red, final) in enumerate(_fixture_variants()):
        with tempfile.TemporaryDirectory(prefix="pl-") as td:
            fixture_root = Path(td) / "fixture"
            context = _raw_fixture(
                fixture_root,
                variant=_runtime_variant(fixture_root),
                author_vendor=author,
                red_outcomes=red,
                final_outcomes=final,
            )
            if index:
                ledger = context["repo"] / ".phase-loop/events.jsonl"
                ledger.write_bytes(_ledger_history_bytes())
            registry_before = context["registry"].read_bytes()
            completed = _prepare_command(context)
            assert completed.returncode == 0, completed.stderr
            _assert_prepared(context)
            assert context["registry"].read_bytes() == registry_before

    def rejected(
        name: str,
        mutate: Callable[[dict[str, Any]], None],
        message: str,
        *,
        non_biting_mutation: bool = False,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="pl-") as td:
            fixture_root = Path(td) / "fixture"
            context = _raw_fixture(
                fixture_root,
                variant=_runtime_variant(fixture_root),
                non_biting_mutation=non_biting_mutation,
            )
            mutate(context)
            _persist_manifest(context)
            registry_before = context["registry"].read_bytes()
            completed = _prepare_command(context)
            assert completed.returncode != 0, name
            for secret in context.get("must_not_echo", ()):
                if (
                    secret.casefold()
                    in (completed.stderr + completed.stdout).casefold()
                ):
                    pytest.fail(
                        f"{name}: diagnostic exposed planted credential", pytrace=False
                    )
            diagnostic = (completed.stderr + completed.stdout).lower()
            assert message.lower() in diagnostic, f"{name}: {diagnostic}"
            _assert_no_prepare_output(context)
            assert context["registry"].read_bytes() == registry_before

    rejected(
        "wrong-manifest-schema",
        lambda context: context["manifest"].__setitem__(
            "schema", f"{os.urandom(16).hex()}.v1"
        ),
        "input manifest schema mismatch",
    )
    rejected(
        "unknown-manifest-key",
        lambda context: context["manifest"].__setitem__(os.urandom(16).hex(), True),
        "unknown input manifest field",
    )
    for artifact in RAW_ARTIFACT_NAMES:
        rejected(
            f"missing-artifact-{artifact}",
            lambda context, artifact=artifact: context["manifest"]["artifacts"].pop(
                artifact
            ),
            "missing required input",
        )
    for role in ROLE_NAMES:
        rejected(
            f"missing-role-{role}",
            lambda context, role=role: context["manifest"]["role_attestations"].pop(
                role
            ),
            "missing required input",
        )
    rejected(
        "extra-artifact-key",
        lambda context: context["manifest"]["artifacts"].__setitem__(
            os.urandom(16).hex(),
            copy.deepcopy(context["manifest"]["artifacts"]["plan_authority"]),
        ),
        "unknown artifact input",
    )
    rejected(
        "extra-role-key",
        lambda context: context["manifest"]["role_attestations"].__setitem__(
            os.urandom(16).hex(),
            copy.deepcopy(context["manifest"]["role_attestations"]["author"]),
        ),
        "unknown role attestation",
    )
    for group, names, label in (
        ("artifacts", RAW_ARTIFACT_NAMES, "artifact"),
        ("role_attestations", ROLE_NAMES, "role attestation"),
    ):
        for value in (
            None,
            [],
            os.urandom(16).hex(),
            True,
            _different_count(0),
            _different_count(0) + 0.5,
        ):
            rejected(
                f"{group}-wrong-container-{type(value).__name__}",
                lambda context, group=group, value=value: context[
                    "manifest"
                ].__setitem__(group, value),
                f"{group} must be an object",
            )
        for name in names:
            for value in (
                None,
                [],
                os.urandom(16).hex(),
                True,
                _different_count(0),
                _different_count(0) + 0.5,
            ):
                rejected(
                    f"{name}-ref-wrong-container-{type(value).__name__}",
                    lambda context, group=group, name=name, value=value: context[
                        "manifest"
                    ][group].__setitem__(name, value),
                    f"{label} reference must be an object",
                )
            rejected(
                f"{name}-ref-empty",
                lambda context, group=group, name=name: context["manifest"][
                    group
                ].__setitem__(name, {}),
                f"{label} reference fields mismatch",
            )
            for field in ("path", "sha256"):
                rejected(
                    f"{name}-ref-missing-{field}",
                    lambda context, group=group, name=name, field=field: context[
                        "manifest"
                    ][group][name].pop(field),
                    f"{label} reference fields mismatch",
                )
                for value in (
                    None,
                    [],
                    {},
                    True,
                    _different_count(0),
                    _different_count(0) + 0.5,
                ):
                    rejected(
                        f"{name}-ref-{field}-wrong-type-{type(value).__name__}",
                        lambda context, group=group, name=name, field=field, value=value: (
                            context["manifest"][group][name].__setitem__(field, value)
                        ),
                        f"{label} reference field type",
                    )
            rejected(
                f"{name}-ref-extra-field",
                lambda context, group=group, name=name: context["manifest"][group][
                    name
                ].__setitem__(os.urandom(16).hex(), True),
                f"{label} reference fields mismatch",
            )

    def secret_extra_ref(context: dict[str, Any]) -> None:
        secret = os.urandom(24).hex()
        context.setdefault("must_not_echo", []).append(secret)
        context["manifest"]["artifacts"][os.urandom(16).hex()] = _write_ref(
            context["source_root"],
            "raw/data.txt",
            f"api_key={secret}\n".encode(),
        )

    rejected("secret-bearing-extra-ref", secret_extra_ref, "unknown artifact input")

    rejected(
        "caller-receipts",
        lambda context: context["manifest"].__setitem__(
            "receipts", {"candidate": {"passed": True}}
        ),
        "caller-authored receipt",
    )
    rejected(
        "caller-counts",
        lambda context: context["manifest"].__setitem__(
            "counts",
            {
                "passed": _different_count(
                    context["expected"]["run_counts"]["candidate_focused"]["passed"]
                )
            },
        ),
        "caller-authored counts",
    )
    rejected(
        "caller-git",
        lambda context: context["manifest"].__setitem__(
            "git",
            {
                "candidate_tree": _different_hex(
                    context["expected"]["trees"]["candidate"]
                )
            },
        ),
        "caller-authored git",
    )
    rejected(
        "caller-inventory",
        lambda context: context["manifest"].__setitem__("frozen_inventory", []),
        "caller-authored frozen_inventory",
    )
    rejected(
        "caller-author-vendor",
        lambda context: context["manifest"].__setitem__(
            "author_vendor", f"runtime-vendor-{os.urandom(16).hex()}"
        ),
        "caller-authored author_vendor",
    )
    rejected(
        "caller-routes",
        lambda context: context["manifest"].__setitem__("resolved_routes", []),
        "caller-authored resolved_routes",
    )

    def input_ref(context: dict[str, Any], group: str, name: str) -> dict[str, str]:
        return context["manifest"][group][name]

    attack_inputs = (
        *((f"artifact-{name}", "artifacts", name) for name in RAW_ARTIFACT_NAMES),
        *((f"role-{name}", "role_attestations", name) for name in ROLE_NAMES),
    )
    for label, group, artifact in attack_inputs:

        def absolute_path(
            context: dict[str, Any], group: str = group, artifact: str = artifact
        ) -> None:
            ref = input_ref(context, group, artifact)
            ref["path"] = str((context["source_root"] / ref["path"]).resolve())

        rejected(f"{label}-absolute-path", absolute_path, "normalized relative path")

        def parent_traversal(
            context: dict[str, Any], group: str = group, artifact: str = artifact
        ) -> None:
            ref = input_ref(context, group, artifact)
            ref["path"] = "raw/../raw/" + Path(ref["path"]).name

        rejected(f"{label}-parent-traversal", parent_traversal, "parent traversal")

        def digest_mismatch(
            context: dict[str, Any], group: str = group, artifact: str = artifact
        ) -> None:
            ref = input_ref(context, group, artifact)
            ref["sha256"] = _different_hex(ref["sha256"])

        rejected(f"{label}-digest-mismatch", digest_mismatch, "digest mismatch")

        def direct_symlink(
            context: dict[str, Any], group: str = group, artifact: str = artifact
        ) -> None:
            ref = input_ref(context, group, artifact)
            original = context["source_root"] / ref["path"]
            target = context["root"] / "data"
            target.write_bytes(original.read_bytes())
            original.unlink()
            original.symlink_to(target)

        rejected(f"{label}-direct-symlink", direct_symlink, "symlink")

        def ancestor_symlink(
            context: dict[str, Any], group: str = group, artifact: str = artifact
        ) -> None:
            ref = input_ref(context, group, artifact)
            parent = (context["source_root"] / ref["path"]).parent
            target = context["root"] / "data"
            parent.replace(target)
            parent.symlink_to(target, target_is_directory=True)

        rejected(f"{label}-ancestor-symlink", ancestor_symlink, "symlink")

    def replace_input(
        context: dict[str, Any], group: str, name: str, value: Any
    ) -> None:
        ref = context["manifest"][group][name]
        data = value if isinstance(value, bytes) else _canonical_bytes(value)
        (context["source_root"] / ref["path"]).write_bytes(data)
        ref["sha256"] = _sha256(data)

    def replace_artifact(context: dict[str, Any], artifact: str, value: Any) -> None:
        replace_input(context, "artifacts", artifact, value)
        if artifact not in {"source_mutations", "execution_runs"}:
            return
        # Keep the production-boundary references synchronized for semantic attacks.
        # Dedicated custody attacks change the canonical receipt itself separately.
        artifacts = context["manifest"]["artifacts"]
        historical = _strict_json(
            context["source_root"] / artifacts["sl0_review"]["path"]
        )
        start_ref = historical["production_start"]
        start = _strict_json(context["source_root"] / start_ref["path"])
        if artifact == "source_mutations":
            ref = artifacts[artifact]
            _write_ref(
                context["repo"],
                ref["path"],
                (context["source_root"] / ref["path"]).read_bytes(),
            )
            start["source_mutations"] = ref
        else:
            start["preproduction_runs"].update(
                {
                    name: ref
                    for name, ref in value["runs"].items()
                    if name.startswith("preproduction_")
                }
            )
        data = _canonical_bytes(start)
        _write_ref(context["repo"], start_ref["path"], data)
        historical["production_start"] = _write_ref(
            context["source_root"], start_ref["path"], data
        )
        replace_input(context, "artifacts", "sl0_review", historical)

    def historical_approval_attack(context: dict[str, Any], attack: str) -> None:
        historical = _strict_json(
            context["source_root"]
            / context["manifest"]["artifacts"]["sl0_review"]["path"]
        )
        if attack in {"missing", "start-missing"}:
            historical.pop("approval" if attack == "missing" else "production_start")
        else:
            approval_ref, start_ref = (
                historical["approval"],
                historical["production_start"],
            )
            approval = _strict_json(context["source_root"] / approval_ref["path"])
            start = _strict_json(context["source_root"] / start_ref["path"])
            if attack == "stale":
                approval["head"] = context["expected"]["commits"]["sl0_base"]
                approval["tree"] = context["expected"]["trees"]["sl0_base"]
            elif attack == "unusable":
                approval["seats"][0]["status"] = "DEGRADED"
            elif attack == "late":
                approval["observed_monotonic_ns"] = start["observed_monotonic_ns"] + 1
            elif attack == "start-clock":
                start["clock_id"] += ":different-clock"
            elif attack == "start-identity":
                start["head"] = approval["head"]
                start["tree"] = approval["tree"]
            elif attack == "start-link":
                other = copy.deepcopy(approval)
                other["operation_nonce"] = _sha256(b"other retained approval")
                relative = str(
                    Path(approval_ref["path"]).with_name("other-approval.json")
                )
                data = _canonical_bytes(other)
                _write_ref(context["repo"], relative, data)
                start["sl0_approval"] = _write_ref(
                    context["source_root"], relative, data
                )
            elif attack == "duplicate-start-approval":
                start["operation_nonce"] = approval["operation_nonce"]
            elif attack == "duplicate-historical-sessions":
                approval["seats"][1]["session_sha256"] = approval["seats"][0][
                    "session_sha256"
                ]
            elif attack == "duplicate-approval-request":
                approval["operation_nonce"] = context["expected"]["operation_nonces"][0]
            elif attack == "duplicate-historical-final-session":
                approval["seats"][0]["session_sha256"] = context["expected"][
                    "reviewer_sessions"
                ]["candidate", "claude"]
            elif attack in {"reviewer-is-coordinator", "reviewer-is-author"}:
                approval["seats"][0]["session_sha256"] = context["sessions"][
                    attack.removeprefix("reviewer-is-")
                ]
            elif attack == "duplicate-start-mutation":
                mutations = _strict_json(
                    context["source_root"] / start["source_mutations"]["path"]
                )
                receipt = mutations["mutations"][0]["mutation"]["receipt"]
                start["operation_nonce"] = _strict_json(
                    context["source_root"] / receipt["path"]
                )["process_nonce"]
            else:
                raise AssertionError(attack)
            data = _canonical_bytes(approval)
            _write_ref(context["repo"], approval_ref["path"], data)
            historical["approval"] = _write_ref(
                context["source_root"], approval_ref["path"], data
            )
            if attack != "start-link":
                start["sl0_approval"] = historical["approval"]
            data = _canonical_bytes(start)
            _write_ref(context["repo"], start_ref["path"], data)
            historical["production_start"] = _write_ref(
                context["source_root"], start_ref["path"], data
            )
        replace_artifact(context, "sl0_review", historical)

    for attack in (
        "missing",
        "stale",
        "unusable",
        "late",
        "start-missing",
        "start-clock",
        "start-identity",
        "start-link",
        "duplicate-start-approval",
        "duplicate-historical-sessions",
        "duplicate-approval-request",
        "duplicate-historical-final-session",
        "duplicate-start-mutation",
        "reviewer-is-coordinator",
        "reviewer-is-author",
    ):
        rejected(
            f"historical-sl0-{attack}",
            lambda context, attack=attack: historical_approval_attack(context, attack),
            "duplicate input operation nonce"
            if attack.startswith("duplicate-")
            else "historical reviewer role independence"
            if attack.startswith("reviewer-is-")
            else "production start"
            if attack.startswith("start-")
            else "SL-0 approval",
        )

    def rebind_reviewer_role(context: dict[str, Any]) -> None:
        sessions = {
            seat["session_sha256"]
            for round_name in ("candidate", "canonical_main")
            for seat in _strict_json(
                context["source_root"]
                / context["manifest"]["artifacts"][round_name + "_broker_receipts"][
                    "path"
                ]
            )["receipts"]
        }
        ref = context["manifest"]["role_attestations"]["reviewer"]
        role = _strict_json(context["source_root"] / ref["path"])
        role["session_sha256"] = _sha256("\0".join(sorted(sessions)).encode())
        role["identity"] = "reviewer-" + role["session_sha256"][:32]
        replace_input(context, "role_attestations", "reviewer", role)

    def observed_identity_attack(context: dict[str, Any], attack: str) -> None:
        name = "canonical_main_broker_receipts"
        records = _strict_json(
            context["source_root"] / context["manifest"]["artifacts"][name]["path"]
        )
        seat = next(
            item
            for item in records["receipts"]
            if item["harness"]
            == (
                "codex" if attack in {"live-cwd", "fresh-stateless-label"} else "claude"
            )
        )
        broker = seat["broker"]
        if attack == "live-cwd":
            cwd = str(context["repo"].resolve() / "provider-scratch")
            argv = broker["provider_argv_shape"]
            argv[argv.index("--cd") + 1] = cwd
            argv[argv.index("--output-last-message") + 1] = cwd + "/last-message.txt"
            broker["provider_argv_sha256"] = _sha256("\0".join(argv).encode())
            broker["provider_cwd_sha256"] = _sha256(cwd.encode())
        elif attack != "fresh-stateless-label":
            candidate = _strict_json(
                context["source_root"]
                / context["manifest"]["artifacts"]["candidate_broker_receipts"]["path"]
            )
            prior = next(
                item for item in candidate["receipts"] if item["harness"] == "claude"
            )
            broker["claude_session_id_sha256"] = prior["broker"][
                "claude_session_id_sha256"
            ]
            assert seat["session_sha256"] != broker["claude_session_id_sha256"]
            if attack == "coherent-replay":
                seat["session_sha256"] = broker["claude_session_id_sha256"]
        ref = seat["runtime_receipt"]
        runtime = _strict_json(context["source_root"] / ref["path"])
        runtime["broker"] = broker
        data = _canonical_bytes(runtime)
        _write_ref(context["repo"], ref["path"], data)
        seat["runtime_receipt"] = _write_ref(context["source_root"], ref["path"], data)
        if attack == "live-cwd":
            seat["session_sha256"] = _sha256(data)
        elif attack == "fresh-stateless-label":
            seat["session_sha256"] = _different_hex(_sha256(data))
        replace_artifact(context, name, records)
        rebind_reviewer_role(context)

    rejected(
        "self-consistent-provider-cwd-in-live-repo",
        lambda context: observed_identity_attack(context, "live-cwd"),
        "canonical repository",
    )
    rejected(
        "observed-claude-session-replay-with-fresh-label",
        lambda context: observed_identity_attack(context, "session-replay"),
        "reviewer session",
    )
    rejected(
        "coherent-observed-and-claimed-claude-session-replay",
        lambda context: observed_identity_attack(context, "coherent-replay"),
        "reused review",
    )
    rejected(
        "fresh-stateless-session-label-with-rebound-aggregation",
        lambda context: observed_identity_attack(context, "fresh-stateless-label"),
        "reviewer session",
    )

    nested_targets = (
        [
            ("source_mutations", ("mutations", 0, field))
            for field in ("mutated_source", "restored_source")
        ]
        + [
            ("source_mutations", ("mutations", 0, stage, field))
            for stage in ("mutation", "restored")
            for field in ("raw", "junit", "receipt")
        ]
        + [
            ("sl0_review", ("approval",)),
            ("sl0_review", ("production_start",)),
            ("execution_runs", ("runs", "candidate_focused")),
            ("execution_runs", ("runs", "candidate_lint")),
            ("candidate_review_request", ("bundle",)),
            ("candidate_review_request", ("instructions",)),
            ("candidate_broker_receipts", ("receipts", 0, "runtime_receipt")),
        ]
    )
    for artifact, keys in nested_targets:
        for attack, message in (
            ("absolute", "normalized relative path"),
            ("parent", "parent traversal"),
            ("symlink", "symlink"),
            ("digest", "digest mismatch"),
        ):

            def corrupt_nested(
                context: dict[str, Any],
                artifact: str = artifact,
                keys: tuple = keys,
                attack: str = attack,
            ) -> None:
                record = _strict_json(
                    context["source_root"]
                    / context["manifest"]["artifacts"][artifact]["path"]
                )
                ref = record
                for key in keys:
                    ref = ref[key]
                original = context["source_root"] / ref["path"]
                if attack == "absolute":
                    ref["path"] = str(original.resolve())
                elif attack == "parent":
                    ref["path"] = "raw/../" + ref["path"]
                elif attack == "digest":
                    ref["sha256"] = _different_hex(ref["sha256"])
                else:
                    target = context["root"] / "nested-outside"
                    target.write_bytes(original.read_bytes())
                    original.unlink()
                    original.symlink_to(target)
                replace_artifact(context, artifact, record)

            rejected(f"nested-{artifact}-{keys}-{attack}", corrupt_nested, message)

    def alter_observed_run(
        context: dict[str, Any],
        name: str,
        mutate: Callable[[dict[str, Any]], None],
        *,
        sync: bool = True,
    ) -> None:
        index = _strict_json(
            context["source_root"]
            / context["manifest"]["artifacts"]["execution_runs"]["path"]
        )
        ref = index["runs"][name]
        record = _strict_json(context["source_root"] / ref["path"])
        mutate(record)
        data = _canonical_bytes(record)
        if sync:
            _write_ref(context["repo"], ref["path"], data)
        index["runs"][name] = _write_ref(context["source_root"], ref["path"], data)
        replace_artifact(context, "execution_runs", index)

    def secret_input(group: str, name: str) -> Callable[[dict[str, Any]], None]:
        def mutate(context: dict[str, Any]) -> None:
            secret_value = os.urandom(24).hex()
            context.setdefault("must_not_echo", []).append(secret_value)
            ref = context["manifest"][group][name]
            path = context["source_root"] / ref["path"]
            if name.endswith("_raw"):
                value: Any = path.read_bytes() + f"api_key={secret_value}\n".encode()
            elif name.endswith("_junit"):
                value = path.read_bytes().replace(
                    b"</testsuite>",
                    (
                        f"<system-out>api_key={secret_value}</system-out></testsuite>"
                    ).encode(),
                )
                assert value != path.read_bytes()
            else:
                value = _strict_json(path)
                assert isinstance(value["annotation"], str)
                value["annotation"] = f"api_key={secret_value}"
            if group == "artifacts":
                replace_artifact(context, name, value)
                if name.endswith(("_raw", "_junit")):
                    run_name = name.removesuffix("_raw").removesuffix("_junit")
                    field = "junit" if name.endswith("_junit") else "raw"
                    alter_observed_run(
                        context,
                        run_name,
                        lambda record: record.__setitem__(
                            "raw_sha256" if run_name.endswith("_lint") else field,
                            context["manifest"][group][name]["sha256"]
                            if run_name.endswith("_lint")
                            else context["manifest"][group][name],
                        ),
                    )
            else:
                replace_input(context, group, name, value)

        return mutate

    for artifact in RAW_ARTIFACT_NAMES:
        rejected(
            f"secret-artifact-{artifact}",
            secret_input("artifacts", artifact),
            "secret",
        )
    for role in ROLE_NAMES:
        rejected(
            f"secret-role-{role}",
            secret_input("role_attestations", role),
            "secret",
        )

    def lie_in_json(
        artifact: str, mutate: Callable[[dict[str, Any]], None]
    ) -> Callable[[dict[str, Any]], None]:
        def apply(context: dict[str, Any]) -> None:
            ref = context["manifest"]["artifacts"][artifact]
            record = _strict_json(context["source_root"] / ref["path"])
            mutate(record)
            replace_artifact(context, artifact, record)

        return apply

    for field in ("mutated_source", "restored_source", "mutation", "restored"):
        rejected(
            f"missing-source-proof-{field}",
            lie_in_json(
                "source_mutations",
                lambda record, field=field: record["mutations"][0].pop(field),
            ),
            "missing mutation proof",
        )
    for stage in ("mutation", "restored"):
        for field in ("raw", "junit", "receipt"):
            rejected(
                f"missing-{stage}-{field}",
                lie_in_json(
                    "source_mutations",
                    lambda record, stage=stage, field=field: record["mutations"][0][
                        stage
                    ].pop(field),
                ),
                "missing mutation proof",
            )
    rejected(
        "missing-named-mutation-case",
        lie_in_json("source_mutations", lambda record: record["mutations"].pop()),
        "mutation coverage",
    )

    def corrupt_mutation(context: dict[str, Any], attack: str) -> None:
        index = _strict_json(
            context["source_root"]
            / context["manifest"]["artifacts"]["source_mutations"]["path"]
        )
        entry = index["mutations"][0]
        if attack in {"comment-only", "wrong-restoration", "truthy-non-biting"}:
            field = (
                "restored_source" if attack == "wrong-restoration" else "mutated_source"
            )
            source = (
                context["source_root"] / entry["restored_source"]["path"]
            ).read_bytes()
            replacement = (
                source + b"# no executable change\n"
                if attack == "comment-only"
                else source.replace(b"return True", b"return 2")
            )
            entry[field] = _write_ref(
                context["source_root"], entry[field]["path"], replacement
            )
            stage = "mutation" if field == "mutated_source" else "restored"
            ref = entry[stage]["receipt"]
            receipt = _strict_json(context["source_root"] / ref["path"])
            receipt["source_sha256"] = entry[field]["sha256"]
            entry[stage]["receipt"] = _write_ref(
                context["source_root"], ref["path"], _canonical_bytes(receipt)
            )
        elif attack == "wrong-source-binding":
            entry["source_path"] = index["mutations"][1]["source_path"]
            for stage in ("mutation", "restored"):
                ref = entry[stage]["receipt"]
                receipt = _strict_json(context["source_root"] / ref["path"])
                receipt["source_path"] = entry["source_path"]
                entry[stage]["receipt"] = _write_ref(
                    context["source_root"], ref["path"], _canonical_bytes(receipt)
                )
        else:
            run = entry["mutation"]
            suite = ElementTree.fromstring(
                (context["source_root"] / run["junit"]["path"]).read_bytes()
            )
            suite = suite.find("testsuite") if suite.tag == "testsuites" else suite
            assert suite is not None
            case = suite.find("testcase")
            assert case is not None
            if attack == "extra-junit-case":
                suite.append(copy.deepcopy(case))
                suite.set("tests", "2")
                suite.set("failures", "2")
                raw = (context["source_root"] / run["raw"]["path"]).read_bytes()
                assert b"1 failed" in raw
                run["raw"] = _write_ref(
                    context["source_root"],
                    run["raw"]["path"],
                    raw.replace(b"1 failed", b"2 failed"),
                )
            elif attack == "wrong-nodeid":
                case.set("name", "test_wrong_named_property")
            elif attack == "not-biting":
                failure = case.find("failure")
                assert failure is not None
                case.remove(failure)
                suite.set("failures", "0")
                raw = (context["source_root"] / run["raw"]["path"]).read_bytes()
                run["raw"] = _write_ref(
                    context["source_root"],
                    run["raw"]["path"],
                    raw.replace(b"1 failed", b"1 passed"),
                )
            else:
                raise AssertionError(attack)
            run["junit"] = _write_ref(
                context["source_root"],
                run["junit"]["path"],
                ElementTree.tostring(suite),
            )
            receipt = _strict_json(context["source_root"] / run["receipt"]["path"])
            receipt["raw_sha256"] = run["raw"]["sha256"]
            receipt["junit_sha256"] = run["junit"]["sha256"]
            if attack == "not-biting":
                receipt["exit_code"] = 0
            run["receipt"] = _write_ref(
                context["source_root"],
                run["receipt"]["path"],
                _canonical_bytes(receipt),
            )
        # Semantic corruption must survive canonical-copy custody checks.
        for stage in ("mutation", "restored"):
            ref = entry[stage]["receipt"]
            _write_ref(
                context["repo"],
                ref["path"],
                (context["source_root"] / ref["path"]).read_bytes(),
            )
        replace_artifact(context, "source_mutations", index)

    rejected(
        "executed-truthy-non-biting-mutation",
        lambda context: None,
        "mutation did not fail",
        non_biting_mutation=True,
    )
    for attack, message in (
        ("comment-only", "mutation comment-only"),
        ("wrong-restoration", "restoration digest mismatch"),
        ("wrong-source-binding", "mutation source binding"),
        ("extra-junit-case", "mutation JUnit case count"),
        ("wrong-nodeid", "mutation node id"),
        ("not-biting", "mutation did not fail"),
    ):
        rejected(
            f"mutation-{attack}",
            lambda context, attack=attack: corrupt_mutation(context, attack),
            message,
        )

    def late_preproduction(
        context: dict[str, Any],
        name: str,
        *,
        wrong_clock: bool = False,
        ordering: str = "after-production",
    ) -> None:
        historical = _strict_json(
            context["source_root"]
            / context["manifest"]["artifacts"]["sl0_review"]["path"]
        )
        start = _strict_json(
            context["source_root"] / historical["production_start"]["path"]
        )

        def late(record: dict[str, Any]) -> None:
            if wrong_clock:
                record["clock_id"] += ":different-clock"
            elif ordering in {"at-approval", "before-approval"}:
                approval = _strict_json(
                    context["source_root"] / historical["approval"]["path"]
                )
                record["started_monotonic_ns"] = approval["observed_monotonic_ns"] - (
                    ordering == "before-approval"
                )
            elif ordering == "reversed-interval":
                record["finished_monotonic_ns"] = record["started_monotonic_ns"] - 1
            elif ordering in {"finish-at-production", "finish-after-production"}:
                record["finished_monotonic_ns"] = start["observed_monotonic_ns"] + (
                    ordering == "finish-after-production"
                )
            elif ordering == "after-production":
                record["started_monotonic_ns"] = start["observed_monotonic_ns"] + 1
                record["finished_monotonic_ns"] = start["observed_monotonic_ns"] + 2
            else:
                raise AssertionError(ordering)

        if name.startswith("preproduction_"):
            alter_observed_run(context, name, late)
        else:
            mutations = _strict_json(
                context["source_root"]
                / context["manifest"]["artifacts"]["source_mutations"]["path"]
            )
            ref = mutations["mutations"][0][name]["receipt"]
            record = _strict_json(context["source_root"] / ref["path"])
            late(record)
            data = _canonical_bytes(record)
            _write_ref(context["repo"], ref["path"], data)
            mutations["mutations"][0][name]["receipt"] = _write_ref(
                context["source_root"], ref["path"], data
            )
            replace_artifact(context, "source_mutations", mutations)

    for name in ("preproduction_red", "preproduction_control", "mutation", "restored"):
        rejected(
            f"different-clock-preproduction-{name}",
            lambda context, name=name: late_preproduction(
                context, name, wrong_clock=True
            ),
            "preproduction clock",
        )
        rejected(
            f"late-preproduction-{name}",
            lambda context, name=name: late_preproduction(context, name),
            "preproduction chronology",
        )
        for ordering in (
            "at-approval",
            "before-approval",
            "reversed-interval",
            "finish-at-production",
            "finish-after-production",
        ):
            rejected(
                f"{ordering}-preproduction-{name}",
                lambda context, name=name, ordering=ordering: late_preproduction(
                    context, name, ordering=ordering
                ),
                "preproduction interval chronology"
                if ordering == "reversed-interval"
                else "preproduction finish chronology"
                if ordering.startswith("finish-")
                else "preproduction approval chronology",
            )

    for raw_name, _junit_name in RAW_JUNIT_PAIRS:
        name = raw_name.removesuffix("_raw")
        rejected(
            f"missing-execution-{name}",
            lie_in_json(
                "execution_runs", lambda record, name=name: record["runs"].pop(name)
            ),
            "missing run observation",
        )
    for round_name in ("candidate", "canonical_main"):
        rejected(
            f"missing-lint-{round_name}",
            lie_in_json(
                "execution_runs",
                lambda record, name=round_name: record["runs"].pop(name + "_lint"),
            ),
            "missing run observation",
        )
        rejected(
            f"missing-parent-{round_name}",
            lie_in_json(
                "execution_runs",
                lambda record, name=round_name: record["groups"].pop(name),
            ),
            "missing run group",
        )
    for field, value, message in (
        ("argv", ["python3", "-m", "pytest", "-q", "tests"], "run argv mismatch"),
        ("argv_class", "pytest_harden_pure_control_v1", "run argv class mismatch"),
        ("env_keys", ["PYTHONPATH"], "run environment mismatch"),
        ("cwd", "phase-loop-runtime", "run cwd mismatch"),
        ("source_tree", "1" * 40, "source tree"),
    ):
        rejected(
            f"substituted-run-{field}",
            lambda context, field=field, value=value: alter_observed_run(
                context,
                "candidate_focused",
                lambda record: record.__setitem__(field, value),
            ),
            message,
        )
    rejected(
        "missing-focused-activation",
        lambda context: alter_observed_run(
            context,
            "candidate_focused",
            lambda record: record["argv"].remove("PHASE_LOOP_TDD_EXPECT_HARDEN=1"),
        ),
        "focused activation missing",
    )
    rejected(
        "wrong-run-baseline",
        lambda context: alter_observed_run(
            context,
            "candidate_focused",
            lambda record: record["baseline"].__setitem__(
                "commit", context["expected"]["commits"]["candidate"]
            ),
        ),
        "baseline",
    )
    rejected(
        "run-custody-divergence",
        lambda context: alter_observed_run(
            context,
            "candidate_focused",
            lambda record: record.__setitem__(
                "process_nonce", _different_hex(record["process_nonce"])
            ),
            sync=False,
        ),
        "canonical run",
    )

    def missing_observed_run_field(context: dict[str, Any], field: str) -> None:
        index = _strict_json(
            context["source_root"]
            / context["manifest"]["artifacts"]["execution_runs"]["path"]
        )
        ref = index["runs"]["candidate_focused"]
        record = _strict_json(context["source_root"] / ref["path"])
        record.pop(field)
        data = _canonical_bytes(record)
        _write_ref(context["repo"], ref["path"], data)
        _write_ref(context["source_root"], ref["path"], data)
        ref["sha256"] = _sha256(data)
        replace_artifact(context, "execution_runs", index)

    for field in (
        "process_nonce",
        "argv_class",
        "argv",
        "cwd",
        "env_keys",
        "source_tree",
        "baseline",
    ):
        rejected(
            f"missing-fresh-process-proof-{field}",
            lambda context, field=field: missing_observed_run_field(context, field),
            "missing run observation field",
        )

    def missing_red_anchor(context: dict[str, Any], field: str) -> None:
        name = "preproduction_red_" + field
        ref = context["manifest"]["artifacts"][name]
        raw = (context["source_root"] / ref["path"]).read_bytes()
        assert b"HARDEN-RED-ANCHOR::" in raw
        replace_artifact(
            context,
            name,
            raw.replace(b"HARDEN-RED-ANCHOR::", b"MISSING-RED-ANCHOR::"),
        )
        alter_observed_run(
            context,
            "preproduction_red",
            lambda record: record.__setitem__(
                field, context["manifest"]["artifacts"][name]
            ),
        )

    for field in ("raw", "junit"):
        rejected(
            f"missing-red-anchor-{field}",
            lambda context, field=field: missing_red_anchor(context, field),
            "RED anchor",
        )

    def wrong_red_node(context: dict[str, Any]) -> None:
        ref = context["manifest"]["artifacts"]["preproduction_red_junit"]
        suite = ElementTree.fromstring(
            (context["source_root"] / ref["path"]).read_bytes()
        )
        case = next(suite.iter("testcase"))
        assert case is not None
        case.set("name", "test_unrelated_failure")
        replace_artifact(
            context, "preproduction_red_junit", ElementTree.tostring(suite)
        )
        alter_observed_run(
            context,
            "preproduction_red",
            lambda record: record.__setitem__(
                "junit", context["manifest"]["artifacts"]["preproduction_red_junit"]
            ),
        )

    rejected("wrong-named-red-junit", wrong_red_node, "named RED test")

    def reused_reviewer_session(context: dict[str, Any]) -> None:
        observed_identity_attack(context, "coherent-replay")

    rejected("reused-reviewer-across-rounds", reused_reviewer_session, "reused review")

    def claimed_within_round(context: dict[str, Any]) -> None:
        name = "candidate_broker_receipts"
        records = _strict_json(
            context["source_root"] / context["manifest"]["artifacts"][name]["path"]
        )
        records["receipts"][1]["session_sha256"] = _different_hex(
            records["receipts"][1]["session_sha256"]
        )
        replace_artifact(context, name, records)
        rebind_reviewer_role(context)

    rejected(
        "claimed-reviewer-session-mismatch-within-round",
        claimed_within_round,
        "reviewer session",
    )

    def forged_git_review(context: dict[str, Any]) -> None:
        verifier = _load_shipped_verifier()
        request = _strict_json(
            context["source_root"]
            / context["manifest"]["artifacts"]["candidate_review_request"]["path"]
        )
        bundle_ref = request["bundle"]
        bundle = _strict_json(context["source_root"] / bundle_ref["path"])
        original = bundle["content"]
        patch, start, end = verifier.framed_payload(
            original, "fixture bundle", "COMPLETE-GIT-PATCH"
        )
        forged = patch.replace("+CAPABILITY = 1", "+CAPABILITY = 9")
        assert forged != patch and len(forged) == len(patch)
        begin_frame, end_frame = verifier.digest_bound_delimiters(
            "COMPLETE-GIT-PATCH", forged.encode()
        )
        prefix = original[:start].replace(
            _sha256(patch.encode()), _sha256(forged.encode())
        )
        bundle["content"] = (
            prefix
            + begin_frame
            + "\n"
            + forged
            + "\n"
            + end_frame
            + "\n"
            + original[end:]
        )
        verifier.validate_review_input_envelope(bundle["content"], "bundle")
        request["bundle"] = _write_ref(
            context["source_root"], bundle_ref["path"], _canonical_bytes(bundle)
        )
        replace_artifact(context, "candidate_review_request", request)
        inputs = {
            kind: _strict_json(context["source_root"] / request[kind]["path"])[
                "content"
            ]
            for kind in ("bundle", "instructions")
        }
        brokers = _strict_json(
            context["source_root"]
            / context["manifest"]["artifacts"]["candidate_broker_receipts"]["path"]
        )
        for seat in brokers["receipts"]:
            # Rebind every observation to the forged, self-consistent frame so
            # only comparison with the actual Git patch can reject the claim.
            seat["broker"] = _broker_observation(
                verifier,
                seat["harness"],
                seat["resolved_model"],
                "forged:" + seat["seat_id"],
                inputs,
                seat["report"],
                context["repo"],
                seat["session_sha256"],
            )
            runtime_ref = seat["runtime_receipt"]
            runtime = _strict_json(context["source_root"] / runtime_ref["path"])
            runtime["broker"] = seat["broker"]
            data = _canonical_bytes(runtime)
            _write_ref(context["repo"], runtime_ref["path"], data)
            seat["runtime_receipt"] = _write_ref(
                context["source_root"], runtime_ref["path"], data
            )
            if seat["harness"] != "claude":
                seat["session_sha256"] = _sha256(data)
        replace_artifact(context, "candidate_broker_receipts", brokers)
        rebind_reviewer_role(context)

    rejected("self-consistent-forged-git-review", forged_git_review, "Git-bound review")

    rejected(
        "plan-live-git-lie",
        lie_in_json(
            "plan_authority",
            lambda record: record["commits"].__setitem__(
                "candidate", _different_hex(record["commits"]["candidate"])
            ),
        ),
        "plan authority does not match live Git",
    )
    rejected(
        "sl0-live-git-lie",
        lie_in_json(
            "sl0_review",
            lambda record: record.__setitem__(
                "reviewed_commit", record["landing_commit"]
            ),
        ),
        "SL-0 authority does not match live Git",
    )
    for round_name in ("candidate", "canonical_main"):

        def detached_runtime_receipt(
            context: dict[str, Any], round_name: str = round_name
        ) -> None:
            record = _strict_json(
                context["source_root"]
                / context["manifest"]["artifacts"][f"{round_name}_broker_receipts"][
                    "path"
                ]
            )
            relative = record["receipts"][0]["runtime_receipt"]["path"]
            (context["repo"] / relative).unlink()

        rejected(
            f"{round_name}-detached-runtime-receipt",
            detached_runtime_receipt,
            "canonical run receipt",
        )

        def failed_isolation(
            context: dict[str, Any], round_name: str = round_name
        ) -> None:
            name = f"{round_name}_broker_receipts"
            record = _strict_json(
                context["source_root"] / context["manifest"]["artifacts"][name]["path"]
            )
            seat = record["receipts"][0]
            seat["broker"]["network_unshared"] = False
            ref = seat["runtime_receipt"]
            runtime = _strict_json(context["source_root"] / ref["path"])
            runtime["broker"] = seat["broker"]
            data = _canonical_bytes(runtime)
            _write_ref(context["repo"], ref["path"], data)
            _write_ref(context["source_root"], ref["path"], data)
            ref["sha256"] = _sha256(data)
            replace_artifact(context, name, record)

        rejected(f"{round_name}-failed-isolation", failed_isolation, "failed isolation")
        for suffix, collection, label, fields in (
            (
                "broker_receipts",
                "receipts",
                "broker receipt",
                (
                    "harness",
                    "requested_model",
                    "resolved_model",
                    "result_kind",
                    "terminal_verdict",
                    "operation_nonce",
                    "head",
                    "tree",
                    "seat_id",
                    "session_sha256",
                    "harness_provenance",
                    "report",
                    "report_sha256",
                    "report_bytes",
                    "broker",
                    "runtime_receipt",
                ),
            ),
            (
                "review_request",
                "routes",
                "review route",
                ("harness", "requested_model", "resolved_model"),
            ),
        ):
            artifact = f"{round_name}_{suffix}"
            rejected(
                f"{artifact}-missing-{collection}",
                lie_in_json(
                    artifact,
                    lambda record, collection=collection: record.pop(collection),
                ),
                f"missing {label}",
            )
            rejected(
                f"{artifact}-empty-{collection}",
                lie_in_json(
                    artifact,
                    lambda record, collection=collection: record.__setitem__(
                        collection, []
                    ),
                ),
                f"missing {label}",
            )
            for index in range(4):
                rejected(
                    f"{artifact}-missing-seat-{index}",
                    lie_in_json(
                        artifact,
                        lambda record, collection=collection, index=index: record[
                            collection
                        ].pop(index),
                    ),
                    f"missing {label}",
                )
                for field in fields:
                    rejected(
                        f"{artifact}-seat-{index}-missing-{field}",
                        lie_in_json(
                            artifact,
                            lambda record, collection=collection, index=index, field=field: (
                                record[collection][index].pop(field)
                            ),
                        ),
                        "missing broker result"
                        if field in {"result_kind", "terminal_verdict"}
                        else f"missing {label} field",
                    )
            rejected(
                f"{artifact}-duplicate-harness",
                lie_in_json(
                    artifact,
                    lambda record, collection=collection: record[collection][
                        1
                    ].__setitem__("harness", record[collection][0]["harness"]),
                ),
                f"duplicate {label} harness",
            )
        for field in (
            "schema",
            "provider",
            "repository",
            "head",
            "run_id",
            "workflow",
            "event",
            "run_attempt",
            "check",
            "status",
            "conclusion",
        ):
            rejected(
                f"{round_name}-ci-missing-{field}",
                lie_in_json(
                    f"{round_name}_ci", lambda record, field=field: record.pop(field)
                ),
                "missing CI result"
                if field in {"status", "conclusion"}
                else "missing CI required field",
            )
        for field in (
            "schema",
            "round",
            "head",
            "tree",
            "operation_nonce",
            "bundle",
            "instructions",
        ):
            rejected(
                f"{round_name}-review-missing-{field}",
                lie_in_json(
                    f"{round_name}_review_request",
                    lambda record, field=field: record.pop(field),
                ),
                "missing review required field",
            )
        for field, value in (("status", "queued"), ("conclusion", "failure")):
            rejected(
                f"{round_name}-ci-unsuccessful-{field}",
                lie_in_json(
                    f"{round_name}_ci",
                    lambda record, field=field, value=value: record.__setitem__(
                        field, value
                    ),
                ),
                "CI result is not successful",
            )
        for index in range(4):
            for field, value, message in (
                ("result_kind", "synthetic_self_test", "self-test material"),
                ("terminal_verdict", "DISAGREE", "broker result is not successful"),
            ):
                rejected(
                    f"{round_name}-broker-seat-{index}-invalid-{field}",
                    lie_in_json(
                        f"{round_name}_broker_receipts",
                        lambda record, index=index, field=field, value=value: record[
                            "receipts"
                        ][index].__setitem__(field, value),
                    ),
                    message,
                )

        for attack in ("stale-head", "failed", "missing-gate"):
            rejected(
                f"{round_name}-authoritative-ci-{attack}",
                lambda context, round_name=round_name, attack=attack: (
                    _ci_provider_attack(context, round_name, attack)
                ),
                "authoritative",
            )

        def ci_head_lie(context: dict[str, Any], round_name: str = round_name) -> None:
            artifact = f"{round_name}_ci"
            ref = context["manifest"]["artifacts"][artifact]
            record = _strict_json(context["source_root"] / ref["path"])
            record["head"] = context["expected"]["commits"]["landing"]
            replace_artifact(context, artifact, record)

        rejected(
            f"{round_name}-ci-head-live-git-lie",
            ci_head_lie,
            "CI head does not match live Git",
        )
        for field, fact in (("head", "commits"), ("tree", "trees")):

            def review_identity_lie(
                context: dict[str, Any],
                round_name: str = round_name,
                field: str = field,
                fact: str = fact,
            ) -> None:
                artifact = f"{round_name}_review_request"
                ref = context["manifest"]["artifacts"][artifact]
                record = _strict_json(context["source_root"] / ref["path"])
                stale = context["expected"][fact]["landing"]
                assert stale != record[field]
                record[field] = stale
                replace_artifact(context, artifact, record)

            rejected(
                f"{round_name}-review-stale-{field}",
                review_identity_lie,
                f"review {field} does not match live Git",
            )
        rejected(
            f"{round_name}-broker-within-class-duplicate-nonce",
            lie_in_json(
                f"{round_name}_broker_receipts",
                lambda record: record["receipts"][1].__setitem__(
                    "operation_nonce", record["receipts"][0]["operation_nonce"]
                ),
            ),
            "duplicate input operation nonce",
        )

    def role_session_mismatch(context: dict[str, Any]) -> None:
        ref = context["manifest"]["role_attestations"]["coordinator"]
        record = _strict_json(context["source_root"] / ref["path"])
        record["session_sha256"] = context["sessions"]["reviewer"]
        replace_input(context, "role_attestations", "coordinator", record)

    rejected("role-session-mismatch", role_session_mismatch, "role session mismatch")

    for role in ROLE_NAMES:
        for field in ("identity", "vendor", "issued_at"):

            def missing_role_proof(
                context: dict[str, Any], role: str = role, field: str = field
            ) -> None:
                ref = context["manifest"]["role_attestations"][role]
                record = _strict_json(context["source_root"] / ref["path"])
                record.pop(field)
                replace_input(context, "role_attestations", role, record)

            rejected(
                f"missing-{role}-{field}",
                missing_role_proof,
                "missing role attestation field",
            )

    for round_name in ("candidate", "canonical_main"):
        for field, value, diagnostic in (
            ("report", "", "missing reviewer report"),
            ("report_sha256", "0" * 64, "reviewer report digest mismatch"),
            ("session_sha256", "0" * 64, "placeholder reviewer session"),
            ("harness_provenance", "direct_provider", "non-brokered review seat"),
        ):
            rejected(
                f"{round_name}-invalid-proof-{field}",
                lie_in_json(
                    f"{round_name}_broker_receipts",
                    lambda record, field=field, value=value: record["receipts"][
                        0
                    ].__setitem__(field, value),
                ),
                diagnostic,
            )

    rejected(
        "unfetched-canonical-main",
        lambda context: _git(
            context["repo"], "update-ref", "-d", "refs/remotes/origin/main"
        ),
        "canonical-main",
    )
    rejected(
        "detached-canonical-main",
        lambda context: _git(context["repo"], "checkout", "--detach", "-q"),
        "canonical main branch",
    )

    def role_duplicate_nonce(context: dict[str, Any]) -> None:
        coordinator_ref = context["manifest"]["role_attestations"]["coordinator"]
        coordinator = _strict_json(context["source_root"] / coordinator_ref["path"])
        reviewer_ref = context["manifest"]["role_attestations"]["reviewer"]
        reviewer = _strict_json(context["source_root"] / reviewer_ref["path"])
        reviewer["operation_nonce"] = coordinator["operation_nonce"]
        replace_input(context, "role_attestations", "reviewer", reviewer)

    rejected(
        "role-within-class-duplicate-nonce",
        role_duplicate_nonce,
        "duplicate input operation nonce",
    )

    def inconsistent_count(context: dict[str, Any], name: str, field: str) -> None:
        artifact = name + "_" + field
        ref = context["manifest"]["artifacts"][artifact]
        data = (context["source_root"] / ref["path"]).read_bytes()
        if field == "raw":
            count = context["expected"]["run_counts"][name]["passed"]
            data = data.replace(
                f"{count} passed".encode(),
                f"{_different_count(count)} passed".encode(),
                1,
            )
        else:
            suite = ElementTree.fromstring(data)
            case = next(case for case in suite.iter("testcase") if not list(case))
            ElementTree.SubElement(case, "skipped", message="inconsistent count")
            suite.set("skipped", str(int(suite.get("skipped", "0")) + 1))
            data = ElementTree.tostring(suite)
        replace_artifact(context, artifact, data)
        alter_observed_run(
            context,
            name,
            lambda record: record.__setitem__(
                field, context["manifest"]["artifacts"][artifact]
            ),
        )

    for raw_name, junit_name in RAW_JUNIT_PAIRS:
        pair_name = raw_name.removesuffix("_raw")
        rejected(
            f"{pair_name}-raw-count-mismatch",
            lambda context, pair_name=pair_name: inconsistent_count(
                context, pair_name, "raw"
            ),
            "raw/JUnit count mismatch",
        )
        rejected(
            f"{pair_name}-junit-count-mismatch",
            lambda context, pair_name=pair_name: inconsistent_count(
                context, pair_name, "junit"
            ),
            "raw/JUnit count mismatch",
        )

    def reuse_id(context: dict[str, Any]) -> None:
        context["registry"].write_bytes(
            _canonical_bytes(
                {
                    "schema": "harden_evidence_registry.v1",
                    "evidence_ids": [
                        *context["expected"]["registry"]["evidence_ids"],
                        context["expected"]["evidence_id"],
                    ],
                    "operation_nonces": context["expected"]["registry"][
                        "operation_nonces"
                    ],
                }
            )
        )

    rejected("reused-evidence", reuse_id, "reused evidence_id")

    def reuse_nonce(index: int) -> Callable[[dict[str, Any]], None]:
        def mutate(context: dict[str, Any]) -> None:
            context["registry"].write_bytes(
                _canonical_bytes(
                    {
                        "schema": "harden_evidence_registry.v1",
                        "evidence_ids": context["expected"]["registry"]["evidence_ids"],
                        "operation_nonces": [
                            *context["expected"]["registry"]["operation_nonces"],
                            context["expected"]["operation_nonces"][index],
                        ],
                    }
                )
            )

        return mutate

    for index in range(len(context["expected"]["operation_nonces"])):
        if index < 2:
            kind = "review-request"
        elif index < 10:
            kind = "broker-receipt"
        elif index < 13:
            kind = "role-attestation"
        else:
            kind = "retained-proof"
        rejected(
            f"reused-{kind}-nonce-{index}",
            reuse_nonce(index),
            "reused operation nonce",
        )

    def duplicate_review_request_nonce(context: dict[str, Any]) -> None:
        ref = context["manifest"]["artifacts"]["canonical_main_review_request"]
        record = _strict_json(context["source_root"] / ref["path"])
        record["operation_nonce"] = context["expected"]["operation_nonces"][0]
        replace_artifact(context, "canonical_main_review_request", record)

    rejected(
        "duplicate-review-request-nonce",
        duplicate_review_request_nonce,
        "duplicate input operation nonce",
    )

    def duplicate_input_nonce(context: dict[str, Any], pair: str) -> None:
        broker_ref = context["manifest"]["artifacts"]["candidate_broker_receipts"]
        broker = _strict_json(context["source_root"] / broker_ref["path"])
        nonce = (
            broker["receipts"][0]["operation_nonce"]
            if pair == "receipt-role"
            else context["expected"]["operation_nonces"][0]
        )
        if pair == "request-receipt":
            broker["receipts"][0]["operation_nonce"] = nonce
            replace_artifact(context, "candidate_broker_receipts", broker)
        else:
            role_ref = context["manifest"]["role_attestations"]["coordinator"]
            role = _strict_json(context["source_root"] / role_ref["path"])
            role["operation_nonce"] = nonce
            replace_input(context, "role_attestations", "coordinator", role)

    for pair in ("request-receipt", "request-role", "receipt-role"):
        rejected(
            f"duplicate-input-nonce-{pair}",
            lambda context, pair=pair: duplicate_input_nonce(context, pair),
            "duplicate input operation nonce",
        )

    with tempfile.TemporaryDirectory(prefix="pl-") as td:
        fixture_root = Path(td) / "fixture"
        context = _raw_fixture(fixture_root, variant=_runtime_variant(fixture_root))
        body = _canonical_bytes(context["manifest"])
        duplicate = body.replace(
            b'"schema":"harden_evidence_inputs.v1"}',
            b'"schema":"harden_evidence_inputs.v1",'
            b'"schema":"harden_evidence_inputs.v1"}',
        )
        assert duplicate != body
        assert isinstance(json.loads(duplicate), dict)
        context["manifest_path"].write_bytes(duplicate)
        registry_before = context["registry"].read_bytes()
        completed = _prepare_command(context)
        assert completed.returncode != 0
        diagnostic = (completed.stderr + completed.stdout).lower()
        assert "duplicate json key" in diagnostic, diagnostic
        _assert_no_prepare_output(context)
        assert context["registry"].read_bytes() == registry_before

    top_help = _producer_command("--help")
    assert top_help.returncode == 0, top_help.stderr
    assert "prepare" in top_help.stdout and "seal" in top_help.stdout
    prepare_help = _producer_command("prepare", "--help")
    assert prepare_help.returncode == 0, prepare_help.stderr
    for option in (
        "--inputs",
        "--source-root",
        "--evidence-root",
        "--repo",
        "--output",
        "--completion-request",
        "--reuse-registry",
        "--expected-coordinator-session-sha256",
        "--expected-author-session-sha256",
    ):
        assert option in prepare_help.stdout


def test_harden_producer_prepare_then_seal_binds_one_canonical_event() -> None:
    _producer_module("seal")

    with tempfile.TemporaryDirectory(prefix="pl-") as td:
        fixture_root = Path(td) / "fixture"
        context = _raw_fixture(fixture_root, variant=_runtime_variant(fixture_root))
        registry_before_bytes = context["registry"].read_bytes()
        registry_before = _strict_json(context["registry"])
        prepared = _prepare_command(context)
        assert prepared.returncode == 0, prepared.stderr
        evidence, request = _assert_prepared(context)
        assert context["registry"].read_bytes() == registry_before_bytes
        canonical_ledger = context["repo"] / ".phase-loop/events.jsonl"
        canonical_ledger.parent.mkdir(parents=True, exist_ok=True)
        canonical_ledger.write_bytes(_ledger_bytes(request))
        ledger_before = _path_snapshot(canonical_ledger)
        sealed_path = context["root"] / "sealed-evidence.json"
        sealed_run = _seal_command(context, canonical_ledger, sealed_path)
        assert sealed_run.returncode == 0, sealed_run.stderr
        assert _path_snapshot(canonical_ledger) == ledger_before, (
            "seal modified canonical ledger"
        )
        sealed = _strict_json(sealed_path)
        assert sealed["completion"]["mode"] == "post_completion"
        assert _normalized_precompletion_digest(sealed) == request["evidence_sha256"]
        assert _normalized_precompletion_digest(evidence) == request["evidence_sha256"]
        ledger_ref = sealed["completion"]["ledger"]
        assert set(ledger_ref) == {"path", "sha256"}
        retained_ledger = _contained_ref_path(
            context["evidence_root"], ledger_ref, "sealed completion ledger"
        )
        assert retained_ledger.read_bytes() == canonical_ledger.read_bytes()
        assert not any(
            path.is_symlink() for path in context["evidence_root"].rglob("*")
        )
        registry = _strict_json(context["registry"])
        assert len(registry["evidence_ids"]) == len(registry_before["evidence_ids"]) + 1
        assert set(registry["evidence_ids"]) == {
            *registry_before["evidence_ids"],
            evidence["evidence_id"],
        }
        assert len(registry["operation_nonces"]) == (
            len(registry_before["operation_nonces"])
            + len(context["expected"]["operation_nonces"])
        )
        assert set(registry["operation_nonces"]) == {
            *registry_before["operation_nonces"],
            *context["expected"]["operation_nonces"],
        }
        _verify_with_shipped_verifier(context, sealed_path, "sealed")

    def seal_rejected(
        name: str,
        mutate: Callable[[dict[str, Any], Path, dict[str, Any]], Path],
        message: str,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="pl-") as td:
            fixture_root = Path(td) / "fixture"
            context = _raw_fixture(fixture_root, variant=_runtime_variant(fixture_root))
            prepared = _prepare_command(context)
            assert prepared.returncode == 0, prepared.stderr
            _evidence, request = _assert_prepared(context)
            canonical = context["repo"] / ".phase-loop/events.jsonl"
            canonical.parent.mkdir(parents=True, exist_ok=True)
            canonical.write_bytes(_ledger_bytes(request))
            ledger_argument = mutate(context, canonical, request)
            output = context["root"] / "sealed-evidence.json"
            registry_before = context["registry"].read_bytes()
            protected = (
                context["evidence_root"],
                canonical,
                canonical.resolve(),
                ledger_argument,
                ledger_argument.resolve(),
                context["output"],
                context["request"],
            )
            before = [_path_snapshot(path) for path in protected]
            completed = _seal_command(context, ledger_argument, output)
            assert completed.returncode != 0, name
            diagnostic = (completed.stderr + completed.stdout).lower()
            assert message.lower() in diagnostic, f"{name}: {diagnostic}"
            assert not output.exists()
            assert context["registry"].read_bytes() == registry_before
            assert [_path_snapshot(path) for path in protected] == before, name

    for round_name in ("candidate", "canonical_main"):
        for attack in ("stale-head", "failed", "missing-gate"):

            def ci_disagreement(
                context: dict[str, Any],
                canonical: Path,
                _request: dict[str, Any],
                round_name: str = round_name,
                attack: str = attack,
            ) -> Path:
                _ci_provider_attack(context, round_name, attack)
                return canonical

            seal_rejected(
                f"{round_name}-authoritative-ci-{attack}",
                ci_disagreement,
                "authoritative",
            )

    def detached(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        path = context["root"] / "events.jsonl"
        path.write_bytes(canonical.read_bytes())
        assert path.is_file() and not path.is_symlink()
        return path

    seal_rejected("regular-detached-ledger", detached, "canonical ledger path")

    for group, names in (
        ("artifacts", RAW_ARTIFACT_NAMES),
        ("role_attestations", ROLE_NAMES),
    ):
        for name in names:

            def retained_byte_drift(
                context: dict[str, Any],
                canonical: Path,
                request: dict[str, Any],
                group: str = group,
                name: str = name,
            ) -> Path:
                source = context["manifest"][group][name]
                retained = next(
                    item["retained"]
                    for item in request["copied_artifacts"]
                    if item["source"] == source
                )
                path = _contained_ref_path(
                    context["evidence_root"], retained, "retained drift target"
                )
                path.write_bytes(path.read_bytes() + b"\n")
                assert _sha256(path.read_bytes()) != retained["sha256"]
                return canonical

            seal_rejected(
                f"retained-byte-drift-{group}-{name}",
                retained_byte_drift,
                "digest mismatch",
            )

    def zero_event(
        _context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        canonical.write_bytes(_ledger_history_bytes())
        return canonical

    seal_rejected("zero-event", zero_event, "missing HARDEN completion")

    def duplicate(
        _context: dict[str, Any], canonical: Path, request: dict[str, Any]
    ) -> Path:
        canonical.write_bytes(
            _ledger_history_bytes()
            + _canonical_bytes(_completion_event(request))
            + _canonical_bytes(
                _completion_event(request, timestamp="2026-09-04T00:00:01Z")
            )
        )
        return canonical

    seal_rejected("duplicate-event", duplicate, "duplicate HARDEN completion")

    def registry_evidence_collision(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        registry = _strict_json(context["registry"])
        registry["evidence_ids"].append(context["expected"]["evidence_id"])
        context["registry"].write_bytes(_canonical_bytes(registry))
        return canonical

    seal_rejected(
        "seal-registry-evidence-collision",
        registry_evidence_collision,
        "reused evidence_id",
    )

    def registry_nonce_collision(
        index: int,
    ) -> Callable[[dict[str, Any], Path, dict[str, Any]], Path]:
        def mutate(
            context: dict[str, Any], canonical: Path, _request: dict[str, Any]
        ) -> Path:
            registry = _strict_json(context["registry"])
            registry["operation_nonces"].append(
                context["expected"]["operation_nonces"][index]
            )
            context["registry"].write_bytes(_canonical_bytes(registry))
            return canonical

        return mutate

    for index in range(len(context["expected"]["operation_nonces"])):
        seal_rejected(
            f"seal-registry-nonce-collision-{index}",
            registry_nonce_collision(index),
            "reused operation nonce",
        )

    def stale_precompletion(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        evidence = _strict_json(context["output"])
        evidence["evidence_id"] = _different_hex(evidence["evidence_id"])
        context["output"].write_bytes(_canonical_bytes(evidence))
        return canonical

    seal_rejected(
        "stale-precompletion",
        stale_precompletion,
        "pre-completion digest mismatch",
    )

    def mismatched_event_field(
        field: str,
    ) -> Callable[[dict[str, Any], Path, dict[str, Any]], Path]:
        def mutate(
            _context: dict[str, Any], canonical: Path, request: dict[str, Any]
        ) -> Path:
            event = _completion_event(request)
            proof = event["metadata"]["harden_completion"]
            proof[field] = _different_hex(proof[field])
            canonical.write_bytes(_ledger_history_bytes() + _canonical_bytes(event))
            return canonical

        return mutate

    seal_rejected(
        "mismatched-event-digest",
        mismatched_event_field("evidence_sha256"),
        "completion event evidence digest mismatch",
    )
    seal_rejected(
        "mismatched-event-commit",
        mismatched_event_field("canonical_commit"),
        "completion event commit mismatch",
    )
    seal_rejected(
        "mismatched-event-tree",
        mismatched_event_field("canonical_tree"),
        "completion event tree mismatch",
    )

    def invalid_completion(
        mutate: Callable[[dict[str, Any]], None],
        *,
        encode: Callable[[dict[str, Any]], bytes] = _canonical_bytes,
    ) -> Callable[[dict[str, Any], Path, dict[str, Any]], Path]:
        def apply(
            _context: dict[str, Any], canonical: Path, request: dict[str, Any]
        ) -> Path:
            event = _completion_event(request)
            mutate(event)
            canonical.write_bytes(_ledger_history_bytes() + encode(event))
            return canonical

        return apply

    seal_rejected(
        "missing-completion-action",
        invalid_completion(lambda event: event.pop("action")),
        "completion event action mismatch",
    )
    seal_rejected(
        "wrong-completion-action",
        invalid_completion(lambda event: event.__setitem__("action", "phase_plan")),
        "completion event action mismatch",
    )
    seal_rejected(
        "wrong-completion-schema",
        invalid_completion(
            lambda event: event["metadata"]["harden_completion"].__setitem__(
                "schema", f"{os.urandom(16).hex()}.v1"
            )
        ),
        "completion schema mismatch",
    )
    seal_rejected(
        "wrong-completion-visual-declaration",
        invalid_completion(
            lambda event: event["metadata"]["harden_completion"].__setitem__(
                "visual_render_declared", True
            )
        ),
        "completion visual_render_declared mismatch",
    )
    seal_rejected(
        "missing-completion-proof",
        invalid_completion(lambda event: event["metadata"].pop("harden_completion")),
        "missing HARDEN completion proof",
    )
    for value in (
        None,
        [],
        os.urandom(16).hex(),
        True,
        _different_count(0),
        _different_count(0) + 0.5,
    ):
        seal_rejected(
            f"invalid-completion-proof-{type(value).__name__}",
            invalid_completion(
                lambda event, value=value: event["metadata"].__setitem__(
                    "harden_completion", value
                )
            ),
            "invalid HARDEN completion proof",
        )
    seal_rejected(
        "empty-completion-proof",
        invalid_completion(
            lambda event: event["metadata"].__setitem__("harden_completion", {})
        ),
        "completion proof fields mismatch",
    )
    for field in (
        "schema",
        "evidence_sha256",
        "canonical_commit",
        "canonical_tree",
        "visual_render_declared",
    ):
        seal_rejected(
            f"completion-proof-missing-{field}",
            invalid_completion(
                lambda event, field=field: event["metadata"]["harden_completion"].pop(
                    field
                )
            ),
            "completion proof fields mismatch",
        )
        invalid_types = (
            (None, [], {}, "false", "", 0, 1, 0.0, 1.0)
            if field == "visual_render_declared"
            else (None, [], {}, False, _different_count(0), _different_count(0) + 0.5)
        )
        for index, value in enumerate(invalid_types):
            seal_rejected(
                f"completion-proof-{field}-wrong-type-{index}",
                invalid_completion(
                    lambda event, field=field, value=value: event["metadata"][
                        "harden_completion"
                    ].__setitem__(field, value)
                ),
                "completion proof field type",
            )
    seal_rejected(
        "completion-proof-extra-field",
        invalid_completion(
            lambda event: event["metadata"]["harden_completion"].__setitem__(
                os.urandom(16).hex(), True
            )
        ),
        "completion proof fields mismatch",
    )
    seal_rejected(
        "malformed-completion-json",
        invalid_completion(
            lambda event: None,
            encode=lambda event: _canonical_bytes(event)[:-2] + b"\n",
        ),
        "invalid completion ledger JSON",
    )
    seal_rejected(
        "duplicate-completion-proof-key",
        invalid_completion(
            lambda event: None,
            encode=lambda event: _canonical_bytes(event).replace(
                b'"visual_render_declared":false',
                b'"visual_render_declared":false,"visual_render_declared":false',
            ),
        ),
        "duplicate JSON key",
    )
    for token in (b"NaN", b"Infinity", b"-Infinity"):
        seal_rejected(
            f"nonfinite-completion-proof-{token.decode()}",
            invalid_completion(
                lambda event: None,
                encode=lambda event, token=token: _canonical_bytes(event).replace(
                    b'"visual_render_declared":false',
                    b'"visual_render_declared":' + token,
                ),
            ),
            "invalid completion ledger JSON",
        )

    def symlink_canonical_ledger(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        target = context["root"] / "events.jsonl"
        canonical.replace(target)
        canonical.symlink_to(target)
        return canonical

    seal_rejected(
        "symlink-canonical-ledger",
        symlink_canonical_ledger,
        "canonical ledger symlink",
    )

    def symlink_canonical_ledger_ancestor(
        context: dict[str, Any], canonical: Path, _request: dict[str, Any]
    ) -> Path:
        phase_loop = canonical.parent
        target = context["root"] / "data"
        phase_loop.replace(target)
        phase_loop.symlink_to(target, target_is_directory=True)
        return canonical

    seal_rejected(
        "symlink-canonical-ledger-ancestor",
        symlink_canonical_ledger_ancestor,
        "canonical ledger symlink",
    )

    seal_help = _producer_command("seal", "--help")
    assert seal_help.returncode == 0, seal_help.stderr
    for option in (
        "--pre-completion",
        "--evidence-root",
        "--repo",
        "--ledger",
        "--output",
        "--reuse-registry",
        "--expected-coordinator-session-sha256",
        "--expected-author-session-sha256",
    ):
        assert option in seal_help.stdout
