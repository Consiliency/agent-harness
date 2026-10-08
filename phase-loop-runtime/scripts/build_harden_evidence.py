#!/usr/bin/env python3
"""Build retained HARDEN completion evidence from a closed input manifest.

This command deliberately accepts references and attestations, not claims about
their contents.  All derived facts are recomputed from the referenced bytes and
the supplied Git repository before a new contained evidence root is written.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import re
from pathlib import Path, PurePosixPath
from typing import Any


INPUT_SCHEMA = "harden_evidence_inputs.v1"
RAW_ARTIFACTS = (
    "plan_authority", "sl0_review", "source_mutations", "execution_runs",
    "preproduction_red_raw", "preproduction_red_junit",
    "preproduction_control_raw", "preproduction_control_junit",
    "candidate_focused_raw", "candidate_focused_junit",
    "candidate_pure_control_raw", "candidate_pure_control_junit",
    "candidate_broad_raw", "candidate_broad_junit", "candidate_lint_raw",
    "candidate_ci", "candidate_review_request", "candidate_broker_receipts",
    "canonical_main_focused_raw", "canonical_main_focused_junit",
    "canonical_main_pure_control_raw", "canonical_main_pure_control_junit",
    "canonical_main_broad_raw", "canonical_main_broad_junit",
    "canonical_main_lint_raw", "canonical_main_ci",
    "canonical_main_review_request", "canonical_main_broker_receipts",
)
ROLES = ("coordinator", "author", "reviewer")


class BuildError(ValueError):
    pass


class StagePreservationRequired(BuildError):
    pass


def _load_verifier() -> Any:
    path = Path(__file__).with_name("verify_harden_evidence.py")
    spec = importlib.util.spec_from_file_location("harden_evidence_verifier", path)
    if spec is None or spec.loader is None:
        raise BuildError("shipped verifier is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _load_verifier()


def _canonical(value: Any) -> bytes:
    return V.canonical_bytes(value)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes, label: str) -> Any:
    try:
        value = V.parse_canonical_json(data, label)
        V.reject_secret_payloads(value, label)
        return value
    except Exception as exc:
        raise BuildError(str(exc)) from exc


def _retained_json(data: bytes, label: str) -> Any:
    try:
        return V.parse_retained_json(data, label)
    except Exception as exc:
        raise BuildError(str(exc)) from exc


def _closed(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BuildError(f"{label} must be an object")
    actual = set(value)
    if actual != keys:
        raise BuildError(f"{label} fields mismatch")
    return value


def _ref(value: Any, label: str) -> dict[str, str]:
    item = _closed(value, {"path", "sha256"}, label + " reference")
    if not isinstance(item["path"], str) or not isinstance(item["sha256"], str):
        raise BuildError(f"{label} reference field type")
    if len(item["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in item["sha256"]):
        raise BuildError(f"{label} reference digest mismatch")
    raw = item["path"]
    path = PurePosixPath(raw)
    if path.is_absolute() or str(path) != raw or any(part in {"", ".", ".."} for part in path.parts):
        raise BuildError(f"{label} reference has normalized relative path or parent traversal")
    return {"path": raw, "sha256": item["sha256"]}


def _regular_bytes(root: Path, ref: dict[str, str], label: str) -> bytes:
    """Read one retained file by descriptor without following a path swap."""
    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise BuildError(f"{label} root is unavailable") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise BuildError(f"{label} root is a symlink")
    try:
        data = V.read_regular_file_nofollow(
            root,
            V.canonical_relative_parts(ref["path"], label),
            label,
            V.MAX_ARTIFACT_BYTES,
        )
    except Exception as exc:
        raise BuildError(str(exc)) from exc
    if _sha(data) != ref["sha256"]:
        raise BuildError(f"{label} digest mismatch")
    return data


def _regular(root: Path, ref: dict[str, str], label: str) -> Path:
    _regular_bytes(root, ref, label)
    return root / ref["path"]


def _read(root: Path, ref: Any, label: str) -> tuple[dict[str, str], bytes]:
    parsed = _ref(ref, label)
    data = _regular_bytes(root, parsed, label)
    try:
        V.reject_raw_secret_bytes(data, label)
    except Exception as exc:
        raise BuildError(str(exc)) from exc
    return parsed, data


def _git(repo: Path, *args: str) -> str:
    try:
        return V.git_bytes(repo, *args).decode("utf-8", "strict").strip()
    except Exception as exc:
        raise BuildError("Git object validation failed") from exc


def _git_lines(repo: Path, *args: str) -> list[str]:
    try:
        return V.git_bytes(repo, *args).decode("utf-8", "strict").splitlines()
    except Exception as exc:
        raise BuildError("Git object validation failed") from exc


def _blob(repo: Path, revision: str, path: str) -> tuple[str, bytes]:
    try:
        return V.blob(repo, revision, path)
    except Exception as exc:
        raise BuildError("Git authority path is unavailable") from exc


def _copy_source(source: Path, target: Path) -> dict[tuple[str, str], dict[str, str]]:
    try:
        source_stat = source.lstat()
    except OSError as exc:
        raise BuildError("source root is unavailable") from exc
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISDIR(source_stat.st_mode):
        raise BuildError("source root is unavailable")
    if target.exists():
        raise BuildError("evidence root already exists")
    # Inventory and read every source entry before publishing anything.  The
    # destination is a private staging directory, so rejected symlink/race
    # probes cannot alter a caller-visible evidence location or their target.
    entries: list[tuple[str, bytes]] = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source).as_posix()
        try:
            entry = path.lstat()
        except OSError as exc:
            raise BuildError("source root contains an unavailable entry") from exc
        if stat.S_ISLNK(entry.st_mode):
            raise BuildError("source root contains a symlink")
        if stat.S_ISDIR(entry.st_mode):
            continue
        if not stat.S_ISREG(entry.st_mode):
            raise BuildError("source root contains a non-regular file")
        try:
            data = V.read_regular_file_nofollow(
                source,
                V.canonical_relative_parts(relative, "source artifact"),
                "source artifact",
                V.MAX_ARTIFACT_BYTES,
            )
        except Exception as exc:
            raise BuildError(str(exc)) from exc
        entries.append((relative, data))
    target.mkdir(mode=0o700, parents=True)
    copied: dict[tuple[str, str], dict[str, str]] = {}
    for relative, data in entries:
        destination = target / relative
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.write_bytes(data)
        os.chmod(destination, 0o600)
        digest = _sha(data)
        copied[(relative, digest)] = {"path": relative, "sha256": digest}
    return copied


def _put(root: Path, relative: str, value: Any) -> dict[str, str]:
    path = root / relative
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = value if isinstance(value, bytes) else _canonical(value)
    path.write_bytes(data)
    os.chmod(path, 0o600)
    return {"path": relative, "sha256": _sha(data)}


def _retained(ref: Any, copies: dict[tuple[str, str], dict[str, str]], label: str) -> dict[str, str]:
    source = _ref(ref, label)
    result = copies.get((source["path"], source["sha256"]))
    if result is None:
        raise BuildError(f"{label} was not copied from retained input")
    return result


def _summary(junit: bytes) -> tuple[dict[str, int], str]:
    return _summary_from_raw(junit, b"")


def _summary_from_raw(junit: bytes, raw: bytes) -> tuple[dict[str, int], str]:
    cases = V.parse_junit(junit, "retained JUnit")
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for case in cases:
        status = case["status"]
        if status == "failure":
            counts["failed"] += 1
        elif status == "error":
            counts["errors"] += 1
        else:
            counts[status] += 1
    try:
        raw_text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise BuildError("retained pytest output is not UTF-8") from exc

    def raw_count(noun: str) -> int:
        matches = re.findall(rf"(?<!\d)(\d+)\s+{re.escape(noun)}\b", raw_text)
        if len(matches) > 1:
            raise BuildError("retained pytest output has ambiguous summary")
        return int(matches[0]) if matches else 0

    result = {
        **counts,
        "xfails": raw_count("xfailed"),
        "xpasses": raw_count("xpassed"),
        "subtests": raw_count("subtests passed"),
        "deselected": raw_count("deselected"),
    }, _sha(_canonical(sorted(case["node"] for case in cases)))
    for field, noun in (("passed", "passed"), ("failed", "failed"), ("errors", "errors"), ("skipped", "skipped")):
        observed = raw_count(noun)
        if observed and observed != result[0][field]:
            raise BuildError("raw/JUnit count mismatch")
    return result


def _input_manifest(path: Path, source: Path) -> dict[str, Any]:
    try:
        manifest_bytes = V.read_regular_file_nofollow(
            path.parent,
            (path.name,),
            "input manifest",
            V.MAX_ARTIFACT_BYTES,
        )
    except Exception as exc:
        raise BuildError(str(exc)) from exc
    manifest = _json(manifest_bytes, "input manifest")
    caller_claims = {
        "receipts": "caller-authored receipt",
        "counts": "caller-authored counts",
        "git": "caller-authored git",
        "frozen_inventory": "caller-authored frozen_inventory",
        "author_vendor": "caller-authored author_vendor",
        "resolved_routes": "caller-authored resolved_routes",
    }
    if isinstance(manifest, dict):
        for field, message in caller_claims.items():
            if field in manifest:
                raise BuildError(message)
    if isinstance(manifest, dict) and set(manifest) - {"schema", "artifacts", "role_attestations"}:
        raise BuildError("unknown input manifest field")
    data = _closed(manifest, {"schema", "artifacts", "role_attestations"}, "input manifest")
    if data["schema"] != INPUT_SCHEMA:
        raise BuildError("input manifest schema mismatch")
    artifacts = data["artifacts"]
    roles = data["role_attestations"]
    if not isinstance(artifacts, dict):
        raise BuildError("artifacts must be an object")
    if not isinstance(roles, dict):
        raise BuildError("role_attestations must be an object")
    if set(artifacts) - set(RAW_ARTIFACTS):
        raise BuildError("unknown artifact input")
    if set(roles) - set(ROLES):
        raise BuildError("unknown role attestation")
    for name in RAW_ARTIFACTS:
        if name not in artifacts:
            raise BuildError("missing required input")
        _read(source, artifacts[name], "artifact")
    for name in ROLES:
        if name not in roles:
            raise BuildError("missing required input")
        _read(source, roles[name], "role attestation")
    return data


def _annotation(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise BuildError(label + " annotation is malformed")
    return value


def _raw_json(source: Path, ref: Any, label: str) -> tuple[dict[str, str], Any]:
    parsed, data = _read(source, ref, label)
    try:
        return parsed, V.parse_retained_json(data, label)
    except Exception as exc:
        raise BuildError(str(exc)) from exc


def _raw_ref(source: Path, value: Any, label: str) -> dict[str, str]:
    return _read(source, value, label)[0]


def _validate_raw_closure(manifest: dict[str, Any], source: Path) -> dict[str, Any]:
    """Close every source-entered record before normalized output exists."""
    artifacts = manifest["artifacts"]
    values = {name: _raw_json(source, ref, name)[1] for name, ref in artifacts.items()
              if name in {"plan_authority", "sl0_review", "source_mutations", "execution_runs",
                          "candidate_ci", "canonical_main_ci", "candidate_review_request",
                          "canonical_main_review_request", "candidate_broker_receipts",
                          "canonical_main_broker_receipts"}}
    plan = _closed(values["plan_authority"], {"schema", "annotation", "evidence_id", "repository", "commits", "author_vendor"}, "plan authority")
    _annotation(plan["annotation"], "plan authority")
    if plan["schema"] != "harden_plan_authority.v1" or not isinstance(plan["evidence_id"], str) or not isinstance(plan["repository"], str) or not isinstance(plan["author_vendor"], str):
        raise BuildError("plan authority is malformed")
    commits = _closed(plan["commits"], {"sl0_base", "reviewed_sl0", "landing", "candidate", "canonical_main"}, "plan authority commits")
    if any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{40}", item) for item in commits.values()):
        raise BuildError("retained Git identity is malformed")

    sl0_value = values["sl0_review"]
    if isinstance(sl0_value, dict):
        if "approval" not in sl0_value:
            raise BuildError("SL-0 approval is missing")
        if "production_start" not in sl0_value:
            raise BuildError("production start is missing")
    sl0 = _closed(sl0_value, {"schema", "annotation", "base_commit", "reviewed_commit", "landing_commit", "frozen_test_paths", "approval", "production_start"}, "SL-0 review")
    _annotation(sl0["annotation"], "SL-0 review")
    if sl0["schema"] != "harden_sl0_review.v1" or any(not isinstance(sl0[key], str) or not re.fullmatch(r"[0-9a-f]{40}", sl0[key]) for key in ("base_commit", "reviewed_commit", "landing_commit")):
        raise BuildError("SL-0 review is malformed")
    frozen = sl0["frozen_test_paths"]
    if not isinstance(frozen, list) or not frozen or any(not isinstance(path, str) or not path for path in frozen) or len(frozen) != len(set(frozen)):
        raise BuildError("frozen inventory is malformed")
    _raw_ref(source, sl0["approval"], "SL-0 approval")
    _raw_ref(source, sl0["production_start"], "production start")

    mutations = _closed(values["source_mutations"], {"schema", "annotation", "mutations"}, "source mutations")
    _annotation(mutations["annotation"], "source mutations")
    if mutations["schema"] != "harden_source_mutations.v1" or not isinstance(mutations["mutations"], list) or not mutations["mutations"]:
        raise BuildError("source mutations are malformed")
    for entry in mutations["mutations"]:
        required_mutation = {
            "case_id", "source_path", "nodeid", "restored_source",
            "mutated_source", "mutation", "restored",
        }
        if isinstance(entry, dict) and required_mutation - set(entry):
            raise BuildError("missing mutation proof")
        entry = _closed(entry, required_mutation, "source mutation")
        if any(not isinstance(entry[key], str) or not entry[key] for key in ("case_id", "source_path", "nodeid")):
            raise BuildError("source mutation is malformed")
        _raw_ref(source, entry["restored_source"], "restored source")
        _raw_ref(source, entry["mutated_source"], "mutated source")
        for stage in ("mutation", "restored"):
            required_stage = {"raw", "junit", "receipt"}
            if isinstance(entry[stage], dict) and required_stage - set(entry[stage]):
                raise BuildError("missing mutation proof")
            record = _closed(entry[stage], required_stage, "source mutation " + stage)
            for key in ("raw", "junit", "receipt"):
                _raw_ref(source, record[key], "source mutation " + stage)

    execution = _closed(values["execution_runs"], {"schema", "annotation", "runs", "groups"}, "execution runs")
    _annotation(execution["annotation"], "execution runs")
    expected_runs = {"preproduction_red", "preproduction_control", "candidate_focused", "candidate_pure_control", "candidate_broad", "candidate_lint", "canonical_main_focused", "canonical_main_pure_control", "canonical_main_broad", "canonical_main_lint"}
    if execution["schema"] != "harden_execution_runs.v1" or not isinstance(execution["runs"], dict):
        raise BuildError("execution run inventory is malformed")
    if expected_runs - set(execution["runs"]):
        raise BuildError("missing run observation")
    if set(execution["runs"]) != expected_runs:
        raise BuildError("execution run inventory is malformed")
    for name, ref in execution["runs"].items():
        _raw_ref(source, ref, name + " observation")
        observation = _raw_json(source, ref, name + " observation")[1]
        if name.endswith("_lint"):
            observation = _closed(observation, {"schema", "head", "tree", "process_nonce", "exit_code", "tool_identity", "argv_class", "checks", "raw_sha256"}, name + " observation")
            if observation["schema"] != "harden_static_receipt.v1":
                raise BuildError("run observation schema mismatch")
        else:
            fields = {"schema", "kind", "head", "tree", "process_nonce", "exit_code", "argv_class", "argv", "cwd", "env_keys", "source_tree", "raw", "junit", "baseline"}
            if name.startswith("preproduction_"):
                fields |= {"clock_id", "started_monotonic_ns", "finished_monotonic_ns"}
            if isinstance(observation, dict) and fields - set(observation):
                raise BuildError("missing run observation field")
            observation = _closed(observation, fields, name + " observation")
            if observation["schema"] != "harden_run_observation.v1" or observation["kind"] != name or not isinstance(observation["head"], str) or not re.fullmatch(r"[0-9a-f]{40}", observation["head"]) or not isinstance(observation["tree"], str) or not re.fullmatch(r"[0-9a-f]{40}", observation["tree"]):
                raise BuildError("run observation schema mismatch")
            if observation["source_tree"] != observation["tree"]:
                raise BuildError("source tree mismatch")
            if (
                name.endswith("_focused")
                and observation["argv"][:2] == [
                    "env", "PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests",
                ]
                and "PHASE_LOOP_TDD_EXPECT_HARDEN=1" not in observation["argv"]
            ):
                raise BuildError("focused activation missing")
            for key in ("raw", "junit"):
                _raw_ref(source, observation[key], name + " observation " + key)
    if not isinstance(execution["groups"], dict):
        raise BuildError("execution group inventory is malformed")
    if {"candidate", "canonical_main"} - set(execution["groups"]):
        raise BuildError("missing run group")
    if set(execution["groups"]) != {"candidate", "canonical_main"}:
        raise BuildError("execution group inventory is malformed")
    for name, group in execution["groups"].items():
        group = _closed(group, {"run_nonce", "head", "tree"}, name + " execution group")
        if any(not isinstance(group[key], str) or not re.fullmatch(r"[0-9a-f]{64}" if key == "run_nonce" else r"[0-9a-f]{40}", group[key]) for key in group):
            raise BuildError("execution group is malformed")

    for round_name in ("candidate", "canonical_main"):
        ci_required = {"schema", "annotation", "provider", "repository", "head", "run_id", "workflow", "event", "run_attempt", "check", "status", "conclusion"}
        ci_value = values[round_name + "_ci"]
        if isinstance(ci_value, dict) and {"status", "conclusion"} - set(ci_value):
            raise BuildError("missing CI result")
        if not isinstance(ci_value, dict) or not ci_required <= set(ci_value):
            raise BuildError("missing CI required field")
        ci = _closed(ci_value, ci_required, round_name + " CI")
        _annotation(ci["annotation"], round_name + " CI")
        if ci["status"] != "completed" or ci["conclusion"] != "success":
            raise BuildError("CI result is not successful")
        if ci["schema"] != "harden_ci_result.v1" or ci["provider"] != "github_actions" or ci["repository"] != "Consiliency/agent-harness" or ci["workflow"] != "test" or ci["event"] != ("pull_request" if round_name == "candidate" else "push") or ci["check"] != "suite gate" or not isinstance(ci["run_id"], int) or isinstance(ci["run_id"], bool) or ci["run_id"] < 1 or not isinstance(ci["run_attempt"], int) or isinstance(ci["run_attempt"], bool) or ci["run_attempt"] < 1:
            raise BuildError("CI observation is malformed")

        request_required = {"schema", "annotation", "round", "head", "tree", "routes", "operation_nonce", "bundle", "instructions"}
        if isinstance(values[round_name + "_review_request"], dict) and "routes" not in values[round_name + "_review_request"]:
            raise BuildError("missing review route")
        if not isinstance(values[round_name + "_review_request"], dict) or not request_required <= set(values[round_name + "_review_request"]):
            raise BuildError("missing review required field")
        request = _closed(values[round_name + "_review_request"], request_required, round_name + " review request")
        _annotation(request["annotation"], round_name + " review request")
        if request["schema"] != "harden_review_request.v1" or request["round"] != round_name or not isinstance(request["head"], str) or not re.fullmatch(r"[0-9a-f]{40}", request["head"]) or not isinstance(request["tree"], str) or not re.fullmatch(r"[0-9a-f]{40}", request["tree"]) or not isinstance(request["operation_nonce"], str) or not re.fullmatch(r"[0-9a-f]{64}", request["operation_nonce"]):
            raise BuildError("review request is malformed")
        if not isinstance(request["routes"], list) or len(request["routes"]) != 4:
            raise BuildError("missing review route")
        route_keys = set()
        for route in request["routes"]:
            route_required = {"harness", "requested_model", "resolved_model"}
            if not isinstance(route, dict) or not route_required <= set(route):
                raise BuildError("missing review route field")
            route = _closed(route, route_required, "review route")
            if any(not isinstance(route[key], str) or not route[key] for key in route):
                raise BuildError("review route is malformed")
            route_keys.add(route["harness"])
        if len(route_keys) != len(request["routes"]):
            raise BuildError("duplicate review route harness")
        if route_keys != {"claude", "codex", "gemini", "grok"}:
            raise BuildError("review route inventory is malformed")
        _raw_ref(source, request["bundle"], round_name + " review bundle")
        _raw_ref(source, request["instructions"], round_name + " review instructions")
        for kind in ("bundle", "instructions"):
            review_input = _closed(
                _raw_json(source, request[kind], round_name + " review " + kind)[1],
                {"schema", "kind", "head", "tree", "content"},
                round_name + " review " + kind,
            )
            if review_input["head"] != request["head"]:
                raise BuildError("review head does not match live Git")
            if review_input["tree"] != request["tree"]:
                raise BuildError("review tree does not match live Git")
            if review_input["schema"] != "harden_review_input.v1" or review_input["kind"] != kind or not isinstance(review_input["content"], str):
                raise BuildError("review input is malformed")

        broker_value = values[round_name + "_broker_receipts"]
        if not isinstance(broker_value, dict) or "receipts" not in broker_value:
            raise BuildError("missing broker receipt")
        brokers = _closed(broker_value, {"schema", "annotation", "round", "receipts"}, round_name + " broker receipts")
        _annotation(brokers["annotation"], round_name + " broker receipts")
        if brokers["schema"] != "harden_broker_receipts.v1" or brokers["round"] != round_name:
            raise BuildError("broker receipts are malformed")
        if not isinstance(brokers["receipts"], list) or len(brokers["receipts"]) != 4:
            raise BuildError("missing broker receipt")
        harnesses = [record.get("harness") for record in brokers["receipts"] if isinstance(record, dict)]
        if len(harnesses) != len(set(harnesses)):
            raise BuildError("duplicate broker receipt harness")
        for record in brokers["receipts"]:
            broker_required = {"harness", "requested_model", "resolved_model", "result_kind", "terminal_verdict", "head", "tree", "seat_id", "session_sha256", "harness_provenance", "report", "operation_nonce", "report_sha256", "report_bytes", "broker", "runtime_receipt"}
            if isinstance(record, dict) and {"result_kind", "terminal_verdict"} - set(record):
                raise BuildError("missing broker result")
            if not isinstance(record, dict) or not broker_required <= set(record):
                raise BuildError("missing broker receipt field")
            record = _closed(record, broker_required, "broker receipt")
            if record["result_kind"] != "live":
                raise BuildError("self-test material")
            if record["terminal_verdict"] != "AGREE":
                raise BuildError("broker result is not successful")
            if record["report"] == "":
                raise BuildError("missing reviewer report")
            if record["report_sha256"] != _sha(record["report"].encode("utf-8")):
                raise BuildError("reviewer report digest mismatch")
            if record["session_sha256"] == "0" * 64:
                raise BuildError("placeholder reviewer session")
            if record["harness_provenance"] != "brokered_subscription_cli":
                raise BuildError("non-brokered review seat")
            if any(not isinstance(record[key], str) or not record[key] for key in ("harness", "requested_model", "resolved_model", "head", "tree", "seat_id", "session_sha256", "harness_provenance", "report", "operation_nonce", "report_sha256")) or record["report"].rstrip().splitlines()[-1:] != ["AGREE"] or not isinstance(record["report_bytes"], int) or isinstance(record["report_bytes"], bool) or record["report_bytes"] != len(record["report"].encode("utf-8")):
                raise BuildError("broker receipt is not a usable live observation")
            _raw_ref(source, record["runtime_receipt"], "runtime receipt")
            runtime = _closed(
                _raw_json(source, record["runtime_receipt"], "runtime receipt")[1],
                {"schema", "head", "tree", "harness", "model", "seat_key", "status", "report", "report_sha256", "report_bytes", "broker"},
                "runtime receipt",
            )
            if runtime["schema"] != "harden_broker_run_receipt.v1" or runtime["status"] != "OK" or any(runtime[key] != record[other] for key, other in (("head", "head"), ("tree", "tree"), ("harness", "harness"), ("model", "resolved_model"), ("seat_key", "seat_id"), ("report", "report"), ("report_sha256", "report_sha256"), ("report_bytes", "report_bytes"), ("broker", "broker"))):
                raise BuildError("runtime receipt is detached from broker observation")
    for name, ref in manifest["role_attestations"].items():
        role_value = _raw_json(source, ref, name + " role")[1]
        required_role = {"schema", "annotation", "role", "identity", "vendor", "session_sha256", "evidence_id", "issued_at", "operation_nonce"}
        if isinstance(role_value, dict) and required_role - set(role_value):
            raise BuildError("missing role attestation field")
        role = _closed(role_value, required_role, name + " role")
        _annotation(role["annotation"], name + " role")
        if role["schema"] != "harden_role_attestation.v1" or role["role"] != name:
            raise BuildError("role attestation is malformed")
    return values


def derive_live_facts(inputs: Path, *, evidence_root: Path, repo: Path) -> dict[str, Any]:
    manifest = _input_manifest(inputs, evidence_root)
    artifacts = manifest["artifacts"]
    raw = _validate_raw_closure(manifest, evidence_root)
    plan = raw["plan_authority"]
    sl0 = raw["sl0_review"]
    execution = raw["execution_runs"]
    plan = _closed(plan, {"schema", "annotation", "evidence_id", "repository", "commits", "author_vendor"}, "plan authority")
    required_sl0 = {"schema", "annotation", "base_commit", "reviewed_commit", "landing_commit", "frozen_test_paths", "approval", "production_start"}
    if not isinstance(sl0, dict):
        raise BuildError("SL-0 review must be an object")
    if "approval" not in sl0:
        raise BuildError("SL-0 approval is missing")
    if "production_start" not in sl0:
        raise BuildError("production start is missing")
    sl0 = _closed(sl0, required_sl0, "SL-0 review")
    if plan["schema"] != "harden_plan_authority.v1" or sl0["schema"] != "harden_sl0_review.v1":
        raise BuildError("retained authority schema mismatch")
    if plan["repository"] != "Consiliency/agent-harness":
        raise BuildError("retained authority repository mismatch")
    commits = plan.get("commits")
    if not isinstance(commits, dict) or set(commits) != {"sl0_base", "reviewed_sl0", "landing", "candidate", "canonical_main"}:
        raise BuildError("retained Git identities are malformed")
    git: dict[str, dict[str, str]] = {}
    for name, commit in commits.items():
        if not isinstance(commit, str) or len(commit) != 40:
            raise BuildError("retained Git identity is malformed")
        try:
            resolved = _git(repo, "rev-parse", f"{commit}^{{commit}}")
        except BuildError as exc:
            raise BuildError("plan authority does not match live Git") from exc
        git[name] = {"commit": resolved, "tree": _git(repo, "rev-parse", f"{resolved}^{{tree}}")}
    if (
        sl0["base_commit"] != git["sl0_base"]["commit"]
        or sl0["reviewed_commit"] != git["reviewed_sl0"]["commit"]
        or sl0["landing_commit"] != git["landing"]["commit"]
    ):
        raise BuildError("SL-0 authority does not match live Git")
    expected_rounds = {
        "candidate": git["candidate"],
        "canonical_main": git["canonical_main"],
    }
    for round_name, identity in expected_rounds.items():
        ci = raw[round_name + "_ci"]
        request = raw[round_name + "_review_request"]
        brokers = raw[round_name + "_broker_receipts"]
        if ci["head"] != identity["commit"]:
            raise BuildError("CI head does not match live Git")
        if request["head"] != identity["commit"]:
            raise BuildError("review head does not match live Git")
        if request["tree"] != identity["tree"]:
            raise BuildError("review tree does not match live Git")
        route_index = {route["harness"]: route for route in request["routes"]}
        seen_harnesses: set[str] = set()
        for record in brokers["receipts"]:
            if record["harness"] in seen_harnesses or record["harness"] not in route_index:
                raise BuildError("broker receipt inventory is malformed")
            seen_harnesses.add(record["harness"])
            if (record["requested_model"], record["resolved_model"], record["head"], record["tree"]) != (
                route_index[record["harness"]]["requested_model"], route_index[record["harness"]]["resolved_model"], identity["commit"], identity["tree"]
            ):
                raise BuildError("broker receipt identity does not match review request")
        if seen_harnesses != set(route_index):
            raise BuildError("broker receipt inventory is malformed")
        group = execution["groups"][round_name]
        if group["head"] != identity["commit"] or group["tree"] != identity["tree"]:
            raise BuildError("execution group identity does not match live Git")
    if not isinstance(sl0.get("frozen_test_paths"), list):
        raise BuildError("frozen inventory is malformed")
    frozen = sorted(sl0["frozen_test_paths"])
    if not frozen or any(not isinstance(path, str) for path in frozen) or len(frozen) != len(set(frozen)):
        raise BuildError("frozen inventory is malformed")
    try:
        reviewed_changes = sorted(_git_lines(
            repo,
            "diff-tree", "--no-commit-id", "--name-only", "-r",
            git["sl0_base"]["commit"], git["reviewed_sl0"]["commit"],
        ))
        frozen_authority = sorted(
            V.plan_owned_paths(repo, git["canonical_main"]["commit"], "SL-0")
        )
        allowed_production = V.lane_owned_paths_since(
            repo, git["landing"]["commit"], git["canonical_main"]["commit"], "SL-5"
        )
        if V.plan_has_lane(repo, git["canonical_main"]["commit"], "SL-4"):
            candidate_base, _canonical_tip = V.canonical_candidate_fork(
                repo,
                git["candidate"]["commit"],
                git["canonical_main"]["commit"],
            )
            candidate_changes = V.changed_paths(
                repo, candidate_base, git["candidate"]["commit"]
            )
        else:
            candidate_base, candidate_changes = V.candidate_contribution_paths(
                repo,
                git["landing"]["commit"],
                git["candidate"]["commit"],
                allowed_production,
            )
        V.validate_sl4_boundary(
            repo,
            git["landing"]["commit"],
            candidate_base,
            git["canonical_main"]["commit"],
            candidate=git["candidate"]["commit"],
        )
    except Exception as exc:
        raise BuildError(str(exc)) from exc
    if frozen != frozen_authority or not reviewed_changes or not set(reviewed_changes) <= set(frozen):
        raise BuildError("frozen inventory paths mismatch")
    runs = execution.get("runs") if isinstance(execution, dict) else None
    if not isinstance(runs, dict):
        raise BuildError("execution run inventory is malformed")
    counts: dict[str, dict[str, int]] = {}
    for name in (key.removesuffix("_raw") for key, _ in ((x, artifacts[x]) for x in artifacts if x.endswith("_raw") and x != "candidate_lint_raw" and x != "canonical_main_lint_raw")):
        junit_name = name + "_junit"
        if junit_name not in artifacts:
            continue
        raw_name = name + "_raw"
        summary, _ = _summary_from_raw(
            _read(evidence_root, artifacts[junit_name], junit_name)[1],
            _read(evidence_root, artifacts[raw_name], raw_name)[1],
        )
        counts[name] = {key: summary[key] for key in ("passed", "failed", "skipped")}
    routes: list[dict[str, str]] = []
    for round_name in ("candidate", "canonical_main"):
        request = _retained_json(
            _read(
                evidence_root,
                artifacts[round_name + "_review_request"],
                "review request",
            )[1],
            "review request",
        )
        value = request.get("routes")
        if not isinstance(value, list):
            raise BuildError("review routes are malformed")
        if not routes:
            routes = value
        elif routes != value:
            raise BuildError("review routes drift between rounds")
    changed = {
        "reviewed_sl0": sorted(_git_lines(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", git["sl0_base"]["commit"], git["reviewed_sl0"]["commit"])),
        "candidate": sorted(candidate_changes),
        "canonical_main": sorted(_git_lines(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", git["candidate"]["commit"], git["canonical_main"]["commit"])),
    }
    author = _retained_json(
        _read(
            evidence_root,
            manifest["role_attestations"]["author"],
            "author attestation",
        )[1],
        "author attestation",
    )
    if not isinstance(author.get("vendor"), str) or author["vendor"] != plan.get("author_vendor"):
        raise BuildError("author attestation is malformed")
    return {"schema": "harden_live_facts.v1", "git": git, "changed_paths": changed,
            "frozen_test_paths": frozen, "run_counts": counts,
            "author_vendor": author["vendor"], "routes": routes}


def _receipt(root: Path, name: str, observation: dict[str, Any], raw: dict[str, str], junit: dict[str, str], *, kind: str) -> dict[str, str]:
    expected = {"schema", "kind", "head", "tree", "process_nonce", "exit_code", "argv_class", "argv", "cwd", "env_keys", "source_tree", "raw", "junit", "baseline"}
    if isinstance(observation, dict) and {"clock_id", "started_monotonic_ns", "finished_monotonic_ns"} <= set(observation):
        expected.update({"clock_id", "started_monotonic_ns", "finished_monotonic_ns"})
    observed = _closed(observation, expected, name + " observation")
    if observed["schema"] != "harden_run_observation.v1" or observed["kind"] != name:
        raise BuildError("run observation schema mismatch")
    if observed["raw"] != raw or observed["junit"] != junit:
        raise BuildError("run observation retained artifact mismatch")
    summary, nodes = _summary_from_raw(
        _regular_bytes(root, junit, name + " JUnit"),
        _regular_bytes(root, raw, name + " raw"),
    )
    value = {
        "schema": "harden_pytest_receipt.v1", "kind": kind,
        "head": observed["head"], "tree": observed["tree"],
        "process_nonce": observed["process_nonce"], "exit_code": observed["exit_code"],
        "argv_class": observed["argv_class"], "raw_sha256": raw["sha256"],
        "junit_sha256": junit["sha256"], "argv": observed["argv"],
        "cwd": observed["cwd"], "env_keys": observed["env_keys"],
        "source_tree": observed["source_tree"], "summary": summary,
        "nodeids_sha256": nodes, "baseline": observed["baseline"],
    }
    if kind == "broad":
        value["declared_outcomes"] = summary
    return _put(root, "derived/" + name + ".receipt.json", value)


def _provider_receipt(run_id: int) -> dict[str, Any]:
    """Read one fixed, credential-scoped CI result and retain only its schema."""
    try:
        with _temporary_directory() as authority_root:
            completed = subprocess.run(
                V.ci_command(run_id), cwd=authority_root, capture_output=True,
                check=False, timeout=20,
                env=V.github_cli_environment(authority_root, canonical=True),
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BuildError("authoritative CI query failed") from exc
    if completed.returncode:
        raise BuildError("authoritative CI query failed")
    try:
        value = json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise BuildError("authoritative CI response is malformed") from exc
    if not isinstance(value, dict):
        raise BuildError("authoritative CI response is malformed")
    required = {"databaseId", "headSha", "status", "conclusion", "event", "workflowName", "attempt", "jobs"}
    if set(value) != required:
        raise BuildError("authoritative CI response is malformed")
    return {**{key: value[key] for key in required - {"jobs"}}, "jobs": V.normalize_ci_jobs(value["jobs"], canonical=True)}


class _temporary_directory:
    def __enter__(self) -> Path:
        import tempfile
        self._value = tempfile.TemporaryDirectory(prefix="harden-ci-authority-")
        return Path(self._value.__enter__())

    def __exit__(self, *args: Any) -> None:
        self._value.__exit__(*args)


def _prepare_stage(inputs: Path, source_root: Path, evidence_root: Path, repo: Path, output: Path,
            completion_request: Path, reuse_registry: Path,
            expected_coordinator_session: str, expected_author_session: str) -> None:
    manifest = _input_manifest(inputs, source_root)
    facts = derive_live_facts(inputs, evidence_root=source_root, repo=repo)
    copies = _copy_source(source_root, evidence_root)
    artifacts = manifest["artifacts"]
    retained = lambda ref, label: _retained(ref, copies, label)
    def item(name: str) -> Any:
        reference = retained(artifacts[name], name)
        return V.parse_retained_json(
            _regular_bytes(evidence_root, reference, name), name
        )
    plan, sl0, execution = item("plan_authority"), item("sl0_review"), item("execution_runs")
    git = facts["git"]
    landing_parent = _git(repo, "rev-parse", git["landing"]["commit"] + "^")
    git_data = {"sl0_base": git["sl0_base"], "landing_first_parent": {"commit": landing_parent, "tree": _git(repo, "rev-parse", landing_parent + "^{tree}")}, **{name: git[name] for name in ("reviewed_sl0", "landing", "candidate", "canonical_main")}}
    inventory = []
    for path in facts["frozen_test_paths"]:
        entry: dict[str, Any] = {"path": path}
        for name in ("reviewed_sl0", "landing", "candidate", "canonical_main"):
            blob, data = _blob(repo, git[name]["commit"], path)
            entry[{"reviewed_sl0": "reviewed", "landing": "landing", "candidate": "candidate", "canonical_main": "canonical_main"}[name]] = {"blob": blob, "sha256": _sha(data), "bytes": len(data)}
        inventory.append(entry)
    runs = execution["runs"]
    def run(name: str, kind: str) -> dict[str, Any]:
        observed_ref = retained(runs[name], name)
        observed_bytes = _regular_bytes(evidence_root, observed_ref, name)
        try:
            canonical = V.read_regular_file_nofollow(
                repo,
                V.canonical_relative_parts(observed_ref["path"], name),
                name + " canonical run",
                V.MAX_ARTIFACT_BYTES,
            )
        except Exception as exc:
            raise BuildError(str(exc)) from exc
        if observed_bytes != canonical:
            raise BuildError(name + " canonical run receipt differs from retained observation")
        observed = _retained_json(observed_bytes, name)
        raw = retained(artifacts[name + "_raw"], name + " raw")
        junit = retained(artifacts[name + "_junit"], name + " junit")
        return {"receipt": _receipt(evidence_root, name, observed, raw, junit, kind=kind), "raw": raw, "junit": junit}
    mutations = item("source_mutations")["mutations"]
    for entry in mutations:
        for stage in ("mutation", "restored"):
            receipt = retained(entry[stage]["receipt"], "mutation receipt")
            entry[stage] = {key: retained(entry[stage][key], "mutation " + key) for key in ("raw", "junit")} | {"receipt": receipt}
        entry["mutated_source"] = retained(entry["mutated_source"], "mutated source")
        entry["restored_source"] = retained(entry["restored_source"], "restored source")
    reviews: dict[str, Any] = {}
    for round_name in ("candidate", "canonical_main"):
        supplied_request = item(round_name + "_review_request")
        request = {
            "schema": "harden_review_request.v1",
            "round": round_name,
            "head": git[round_name]["commit"],
            "tree": git[round_name]["tree"],
            "bundle": retained(supplied_request["bundle"], "review bundle"),
            "instructions": retained(supplied_request["instructions"], "review instructions"),
            "request_nonce": supplied_request["operation_nonce"],
            "seats": [],
        }
        seats = []
        broker_records = _closed(
            item(round_name + "_broker_receipts"),
            {"schema", "annotation", "round", "receipts"},
            "broker receipts",
        )
        if broker_records["schema"] != "harden_broker_receipts.v1" or broker_records["round"] != round_name or not isinstance(broker_records["receipts"], list):
            raise BuildError("broker receipts are malformed")
        for record in broker_records["receipts"]:
            record = _closed(
                record,
                {"harness", "requested_model", "resolved_model", "result_kind", "terminal_verdict", "head", "tree", "seat_id", "session_sha256", "harness_provenance", "report", "operation_nonce", "report_sha256", "report_bytes", "broker", "runtime_receipt"},
                "broker receipt",
            )
            if record["result_kind"] != "live" or record["terminal_verdict"] != "AGREE":
                raise BuildError("broker receipt is not a usable live observation")
            request_seat = {"harness": record["harness"], "requested_model": record["requested_model"]}
            request["seats"].append(request_seat)
            seat = {"schema": "harden_review_seat.v1", "round": round_name,
                    "head": git[round_name]["commit"], "tree": git[round_name]["tree"],
                    "request_sha256": "", "harness": record["harness"],
                    "requested_model": record["requested_model"], "resolved_model": record["resolved_model"],
                    "seat_id": record["seat_id"], "session_sha256": record["session_sha256"],
                    "harness_provenance": record["harness_provenance"], "status": "usable",
                    "result_kind": "real_subscription_inference", "report": record["report"],
                    "report_sha256": record["report_sha256"], "report_bytes": record["report_bytes"],
                    "broker": record["broker"], "runtime_receipt": retained(record["runtime_receipt"], "runtime receipt")}
            seats.append((record["harness"], seat))
        request_ref = _put(evidence_root, "derived/" + round_name + ".request.json", request)
        output_seats = []
        for harness, seat in seats:
            seat["request_sha256"] = request_ref["sha256"]
            output_seats.append({"harness": harness, "artifact": _put(evidence_root, "derived/" + round_name + "." + harness + ".seat.json", seat)})
        reviews[round_name] = {"head": git[round_name]["commit"], "tree": git[round_name]["tree"], "request": request_ref, "seats": output_seats}
    verification = {}
    for round_name in ("candidate", "canonical_main"):
        verification[round_name] = {"commit": git[round_name]["commit"], "tree": git[round_name]["tree"],
                                    "run_nonce": execution["groups"][round_name]["run_nonce"],
                                    "focused": run(round_name + "_focused", "focused_activated"),
                                    "pure_control": run(round_name + "_pure_control", "pure_control"),
                                    "broad": run(round_name + "_broad", "broad"),
                                    "lint": {"raw": retained(artifacts[round_name + "_lint_raw"], "lint raw"), "receipt": retained(runs[round_name + "_lint"], "lint receipt")}}
    authority = {}
    for name, path in (("plan", "plans/phase-plan-v10-HARDEN.md"), ("manifest", "plans/manifest.json")):
        blob, data = _blob(repo, git["canonical_main"]["commit"], path)
        authority[name] = {"path": path, "blob": blob, "sha256": _sha(data), "bytes": len(data)}
    authority["retained_inputs"] = [
        ref for _source, ref in sorted(copies.items())
    ]
    def role_attestation(name: str) -> dict[str, str]:
        source = _retained_json(
            (evidence_root / retained(manifest["role_attestations"][name], name + " role")["path"]).read_bytes(),
            name + " role",
        )
        fields = {"schema", "annotation", "role", "identity", "vendor", "session_sha256", "evidence_id", "issued_at", "operation_nonce"}
        source = _closed(source, fields, name + " role")
        return _put(
            evidence_root,
            "derived/" + name + ".role.json",
            {key: source[key] for key in ("schema", "role", "identity", "vendor", "session_sha256", "evidence_id", "issued_at")},
        )
    evidence = {"schema": "verification_evidence.v3", "evidence_id": plan["evidence_id"],
                "repository": plan["repository"], "git": git_data, "authority": authority,
                "sl0": {"frozen_inventory": inventory, "activated_red": run("preproduction_red", "activated_red"),
                        "pure_control": run("preproduction_control", "pure_control"), "mutations": mutations,
                        "approval": retained(sl0["approval"], "SL-0 approval"),
                        "production_start": retained(sl0["production_start"], "production start")},
                "verification": verification,
                "ci": {round_name: {key: item(round_name + "_ci")[key] for key in ("provider", "repository", "run_id", "workflow", "event", "run_attempt", "head", "check")} | {"provider_receipt": _put(evidence_root, "derived/" + round_name + ".ci.json", V.normalize_ci_jobs([], canonical=False))} for round_name in ()},
                "reviews": reviews,
                "roles": {name: role_attestation(name) for name in ROLES},
                "completion": {"mode": "pre_completion"}}
    # Provider receipts are normalized from their retained source bytes; this keeps
    # the producer independent of provider log bodies and caller-supplied summaries.
    evidence["ci"] = {}
    for round_name in ("candidate", "canonical_main"):
        claim = item(round_name + "_ci")
        run_id = claim["run_id"]
        receipt = _provider_receipt(run_id)
        evidence["ci"][round_name] = {key: claim[key] for key in ("provider", "repository", "run_id", "workflow", "event", "run_attempt", "head", "check")} | {"provider_receipt": _put(evidence_root, "derived/" + round_name + ".provider.json", receipt)}
    output.write_bytes(_canonical(evidence))
    request = {"schema": "harden_completion_request.v1", "phase": "HARDEN", "evidence_sha256": V.normalized_precompletion_digest(evidence),
               "canonical_commit": git["canonical_main"]["commit"], "canonical_tree": git["canonical_main"]["tree"],
               "visual_render_declared": False,
               "input_manifest_sha256": _sha(V.read_regular_file_nofollow(inputs.parent, (inputs.name,), "input manifest", V.MAX_ARTIFACT_BYTES)),
               "copied_artifacts": [{"source": {"path": path, "sha256": digest}, "retained": ref} for (path, digest), ref in sorted(copies.items())]}
    completion_request.write_bytes(_canonical(request))


def _open_target_parent(path: Path, label: str) -> tuple[int, str, Path]:
    """Pin every ancestor of one publication target."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise BuildError(f"{label} nofollow support is unavailable")
    if ".." in path.parts:
        raise BuildError(f"{label} contains parent traversal")
    absolute = Path(os.path.abspath(path))
    if not absolute.name:
        raise BuildError(f"{label} has no output name")
    flags = os.O_RDONLY | directory | nofollow | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open("/", flags)
    try:
        for component in absolute.parts[1:-1]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, absolute.name, absolute
    except Exception:
        os.close(descriptor)
        raise


def _open_target(path: Path, label: str) -> tuple[int, str, Path]:
    target = _open_target_parent(path, label)
    descriptor, name, _absolute = target
    try:
        try:
            os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return target
        raise BuildError(f"{label} already exists")
    except Exception:
        os.close(descriptor)
        raise


def _target_key(target: tuple[int, str, Path]) -> tuple[int, int, str]:
    descriptor, name, _path = target
    parent = os.fstat(descriptor)
    return parent.st_dev, parent.st_ino, name


def _target_parent_is_current(target: tuple[int, str, Path], label: str) -> bool:
    descriptor, name, path = target
    try:
        current_descriptor, current_name, _current_path = _open_target_parent(path, label)
    except (BuildError, OSError):
        return False
    try:
        current = os.fstat(current_descriptor)
        expected = os.fstat(descriptor)
        return (
            current_name == name
            and (current.st_dev, current.st_ino) == (expected.st_dev, expected.st_ino)
        )
    finally:
        os.close(current_descriptor)


def _new_stage(parent_fd: int, prefix: str) -> tuple[str, int, Path]:
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    for _attempt in range(16):
        name = f".{prefix}-{os.getpid()}-{os.urandom(16).hex()}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        return name, descriptor, Path(f"/proc/self/fd/{descriptor}")
    raise BuildError("cannot allocate a private staging directory")


def _cleanup_stage(parent_fd: int, name: str, descriptor: int) -> None:
    stage = Path(f"/proc/self/fd/{descriptor}")
    try:
        for child in os.listdir(descriptor):
            entry = os.stat(child, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(entry.st_mode):
                shutil.rmtree(stage / child, ignore_errors=True)
            else:
                try:
                    os.unlink(child, dir_fd=descriptor)
                except OSError:
                    pass
    finally:
        os.close(descriptor)
        try:
            os.rmdir(name, dir_fd=parent_fd)
        except OSError:
            pass


def _rename_noreplace(
    source_parent_fd: int,
    source_name: str,
    target_parent_fd: int,
    target_name: str,
) -> None:
    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is None:
        raise OSError("atomic no-clobber rename is unavailable")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(
        source_parent_fd,
        os.fsencode(source_name),
        target_parent_fd,
        os.fsencode(target_name),
        1,
    ) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _remove_if_owned(
    publication: tuple[int, str, tuple[int, int], int, str],
    *,
    expected_only: bool = True,
) -> bool:
    parent_fd, name, identity, source_parent_fd, source_name = publication
    try:
        _rename_noreplace(parent_fd, name, source_parent_fd, source_name)
    except OSError:
        return True
    try:
        moved = os.stat(source_name, dir_fd=source_parent_fd, follow_symlinks=False)
        if expected_only and (moved.st_dev, moved.st_ino) != identity:
            try:
                _rename_noreplace(source_parent_fd, source_name, parent_fd, name)
            except OSError:
                return False
        return True
    except OSError:
        return False


def _publish_noreplace(
    source_parent_fd: int,
    source_name: str,
    target: tuple[int, str, Path],
    label: str,
) -> tuple[int, str, tuple[int, int], int, str]:
    """Atomically publish to a pinned target only if its leaf is absent."""
    target_parent_fd, target_name, _target_path = target
    if not _target_parent_is_current(target, label):
        raise BuildError(f"{label} parent changed during publication")
    try:
        staged = os.stat(source_name, dir_fd=source_parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise BuildError(f"{label} staged source is unavailable") from exc
    expected_identity = (staged.st_dev, staged.st_ino)
    try:
        _rename_noreplace(
            source_parent_fd,
            source_name,
            target_parent_fd,
            target_name,
        )
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise BuildError(f"{label} appeared during publication") from exc
        raise BuildError(f"{label} cannot be published atomically: {exc}") from exc
    try:
        published = os.stat(
            target_name,
            dir_fd=target_parent_fd,
            follow_symlinks=False,
        )
        record = (
            target_parent_fd,
            target_name,
            expected_identity,
            source_parent_fd,
            source_name,
        )
        if (
            (published.st_dev, published.st_ino) != expected_identity
            or stat.S_IFMT(published.st_mode) != stat.S_IFMT(staged.st_mode)
        ):
            if not _remove_if_owned(record):
                raise StagePreservationRequired(
                    f"{label} changed during publication; staging preserved"
                )
            raise BuildError(f"{label} changed during publication")
        if not _target_parent_is_current(target, label):
            if not _remove_if_owned(record):
                raise StagePreservationRequired(
                    f"{label} parent changed during publication; staging preserved"
                )
            raise BuildError(f"{label} parent changed during publication")
        return record
    except OSError as exc:
        raise BuildError(f"{label} changed during publication") from exc


def prepare(inputs: Path, source_root: Path, evidence_root: Path, repo: Path, output: Path,
            completion_request: Path, reuse_registry: Path,
            expected_coordinator_session: str, expected_author_session: str) -> None:
    """Construct and independently accept a private aggregate before publication."""
    _input_manifest(inputs, source_root)
    targets: list[tuple[int, str, Path]] = []
    stage: tuple[str, int, Path] | None = None
    published: list[tuple[int, str, tuple[int, int], int, str]] = []
    preserve_stage = False
    try:
        for path, label in (
            (evidence_root, "evidence root"),
            (output, "output"),
            (completion_request, "completion request"),
        ):
            targets.append(_open_target(path, label))
        if len({_target_key(target) for target in targets}) != len(targets):
            raise BuildError("publication targets must be distinct")
        stage = _new_stage(targets[0][0], "harden-prepare")
        _stage_name, stage_fd, stage_path = stage
        stage_root = stage_path / "evidence"
        stage_output = stage_path / "evidence.json"
        stage_request = stage_path / "completion-request.json"
        _prepare_stage(
            inputs, source_root, stage_root, repo, stage_output, stage_request,
            reuse_registry, expected_coordinator_session, expected_author_session,
        )
        V.verify(
            stage_output, stage_root, repo, reuse_registry=reuse_registry,
            expected_coordinator_session=expected_coordinator_session,
            expected_author_session=expected_author_session,
            claim_reuse=False,
        )
        published.append(_publish_noreplace(stage_fd, "evidence", targets[0], "evidence root"))
        published.append(_publish_noreplace(stage_fd, "evidence.json", targets[1], "output"))
        published.append(_publish_noreplace(stage_fd, "completion-request.json", targets[2], "completion request"))
    except Exception as exc:
        preserve_stage = isinstance(exc, StagePreservationRequired)
        for publication in reversed(published):
            if not _remove_if_owned(publication):
                preserve_stage = True
        if isinstance(exc, BuildError):
            raise
        raise BuildError(str(exc)) from exc
    finally:
        if stage is not None:
            if preserve_stage:
                os.close(stage[1])
            else:
                _cleanup_stage(targets[0][0], stage[0], stage[1])
        for descriptor, _name, _path in targets:
            os.close(descriptor)


def _canonical_ledger_bytes(ledger: Path) -> bytes:
    """Read the canonical ledger without collapsing established symlinks into absence."""
    for path in (ledger.parent, ledger):
        try:
            entry = path.lstat()
        except OSError:
            continue
        if stat.S_ISLNK(entry.st_mode):
            raise BuildError("canonical ledger symlink")
    try:
        return V.read_regular_file_nofollow(
            ledger.parent, (ledger.name,), "canonical ledger", V.MAX_ARTIFACT_BYTES,
        )
    except Exception as exc:
        raise BuildError(str(exc)) from exc


def _completion_event_json(data: bytes) -> Any:
    """Keep duplicate-key diagnostics precise while classifying malformed JSON uniformly."""
    try:
        value = V.strict_json_loads(data, "completion ledger")
        V.reject_secret_payloads(value, "completion ledger")
        return value
    except Exception as exc:
        if str(exc) in {
            "completion ledger: invalid JSON",
            "JSON contains a non-finite numeric constant",
        }:
            raise BuildError("invalid completion ledger JSON") from exc
        raise BuildError(str(exc)) from exc


def _completion_event_digest_differs(ledger_bytes: bytes, digest: str) -> bool:
    for line in ledger_bytes.splitlines():
        event = _completion_event_json(line + b"\n")
        proof = event.get("metadata", {}).get("harden_completion") if isinstance(event, dict) else None
        if (
            event.get("phase") == "HARDEN"
            and event.get("status") == "complete"
            and isinstance(proof, dict)
            and proof.get("evidence_sha256") != digest
        ):
            return True
    return False


def _checked_completion_events(ledger_bytes: bytes, evidence: dict[str, Any], digest: str) -> int:
    matches = 0
    fields = {"schema", "evidence_sha256", "canonical_commit", "canonical_tree", "visual_render_declared"}
    for line in ledger_bytes.splitlines():
        event = _completion_event_json(line + b"\n")
        if event.get("phase") != "HARDEN" or event.get("status") != "complete":
            continue
        matches += 1
        if event.get("action") != "phase_execute":
            raise BuildError("completion event action mismatch")
        metadata = event.get("metadata")
        if not isinstance(metadata, dict) or "harden_completion" not in metadata:
            raise BuildError("missing HARDEN completion proof")
        proof = metadata["harden_completion"]
        if not isinstance(proof, dict):
            raise BuildError("invalid HARDEN completion proof")
        if set(proof) != fields:
            raise BuildError("completion proof fields mismatch")
        if (
            not all(isinstance(proof[field], str) for field in fields - {"visual_render_declared"})
            or type(proof["visual_render_declared"]) is not bool
        ):
            raise BuildError("completion proof field type")
        if proof["schema"] != "harden_completion.v1":
            raise BuildError("completion schema mismatch")
        if proof["visual_render_declared"] is not False:
            raise BuildError("completion visual_render_declared mismatch")
        if proof["evidence_sha256"] != digest:
            raise BuildError("completion event evidence digest mismatch")
        if proof["canonical_commit"] != evidence["git"]["canonical_main"]["commit"]:
            raise BuildError("completion event commit mismatch")
        if proof["canonical_tree"] != evidence["git"]["canonical_main"]["tree"]:
            raise BuildError("completion event tree mismatch")
    return matches


def _seal_stage(pre_completion_bytes: bytes, evidence_root: Path, repo: Path, ledger: Path, output: Path,
         reuse_registry: Path, expected_coordinator_session: str, expected_author_session: str) -> None:
    evidence = _json(
        pre_completion_bytes,
        "pre-completion evidence",
    )
    digest = V.normalized_precompletion_digest(evidence)
    canonical = repo / ".phase-loop/events.jsonl"
    if ledger != canonical:
        raise BuildError("canonical ledger path is required")
    ledger_bytes = _canonical_ledger_bytes(ledger)
    matches = _checked_completion_events(ledger_bytes, evidence, digest)
    if matches != 1:
        raise BuildError("missing HARDEN completion" if not matches else "duplicate HARDEN completion")
    ledger_ref = _put(evidence_root, "derived/completion-ledger.jsonl", ledger_bytes)
    sealed = dict(evidence)
    sealed["completion"] = {"mode": "post_completion", "ledger": ledger_ref}
    output.write_bytes(_canonical(sealed))


def seal(pre_completion: Path, evidence_root: Path, repo: Path, ledger: Path, output: Path,
         reuse_registry: Path, expected_coordinator_session: str, expected_author_session: str) -> None:
    """Verify the pre-completion aggregate and ledger before publishing a seal."""
    final_ledger = evidence_root / "derived/completion-ledger.jsonl"
    targets: list[tuple[int, str, Path]] = []
    stage: tuple[str, int, Path] | None = None
    published: list[tuple[int, str, tuple[int, int], int, str]] = []
    extra_source_descriptors: list[int] = []
    preserve_stage = False
    ledger_bytes: bytes | None = None
    expected_digest: str | None = None
    try:
        targets = [
            _open_target(final_ledger, "sealed completion ledger"),
            _open_target(output, "output"),
        ]
        if len({_target_key(target) for target in targets}) != len(targets):
            raise BuildError("publication targets must be distinct")
        evidence = _json(
            V.read_regular_file_nofollow(
                pre_completion.parent, (pre_completion.name,),
                "pre-completion evidence", V.MAX_ARTIFACT_BYTES,
            ),
            "pre-completion evidence",
        )
        if not isinstance(evidence, dict) or evidence.get("completion") != {"mode": "pre_completion"}:
            raise BuildError("pre-completion evidence is not pre-completion")
        ledger_bytes = _canonical_ledger_bytes(ledger)
        expected_digest = V.normalized_precompletion_digest(evidence)
        V.verify(
            pre_completion, evidence_root, repo, reuse_registry=reuse_registry,
            expected_coordinator_session=expected_coordinator_session,
            expected_author_session=expected_author_session,
            claim_reuse=False,
        )
        matches = _checked_completion_events(ledger_bytes, evidence, expected_digest)
        if matches != 1:
            raise BuildError("missing HARDEN completion" if not matches else "duplicate HARDEN completion")
        stage = _new_stage(targets[1][0], "harden-seal")
        _stage_name, stage_fd, stage_path = stage
        stage_root = stage_path / "evidence"
        stage_output = stage_path / "sealed.json"
        _copy_source(evidence_root, stage_root)
        pre_completion_bytes = V.read_regular_file_nofollow(
            pre_completion.parent, (pre_completion.name,), "pre-completion evidence", V.MAX_ARTIFACT_BYTES,
        )
        _seal_stage(
            pre_completion_bytes, stage_root, repo, ledger, stage_output, reuse_registry,
            expected_coordinator_session, expected_author_session,
        )
        V.verify(
            stage_output, stage_root, repo, reuse_registry=reuse_registry,
            expected_coordinator_session=expected_coordinator_session,
            expected_author_session=expected_author_session, claim_reuse=False,
        )
        staged_ledger = stage_root / "derived/completion-ledger.jsonl"
        ledger_parent_fd = os.open(
            staged_ledger.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        extra_source_descriptors.append(ledger_parent_fd)
        published.append(_publish_noreplace(
            ledger_parent_fd,
            staged_ledger.name,
            targets[0],
            "sealed completion ledger",
        ))
        published.append(_publish_noreplace(stage_fd, "sealed.json", targets[1], "output"))
        published_output = (
            Path(f"/proc/self/fd/{targets[1][0]}") / targets[1][1]
        )
        V.verify(
            published_output, evidence_root, repo, reuse_registry=reuse_registry,
            expected_coordinator_session=expected_coordinator_session,
            expected_author_session=expected_author_session,
        )
    except Exception as exc:
        # No source, canonical ledger, or caller output is published until both
        # independent verifier passes complete.  A registry collision therefore
        # leaves no seal output behind.
        preserve_stage = isinstance(exc, StagePreservationRequired)
        for publication in reversed(published):
            if not _remove_if_owned(publication):
                preserve_stage = True
        if (
            ledger_bytes is not None
            and expected_digest is not None
            and (
                "role artifact binding mismatch" in str(exc)
                or "retained plan authority is detached from derived evidence" in str(exc)
            )
            and _completion_event_digest_differs(ledger_bytes, expected_digest)
        ):
            raise BuildError("pre-completion digest mismatch") from exc
        if isinstance(exc, BuildError):
            raise
        raise BuildError(str(exc)) from exc
    finally:
        if stage is not None:
            if preserve_stage:
                os.close(stage[1])
            else:
                _cleanup_stage(targets[1][0], stage[0], stage[1])
        for descriptor in extra_source_descriptors:
            os.close(descriptor)
        for descriptor, _name, _path in targets:
            os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    for name in ("inputs", "source-root", "evidence-root", "repo", "output", "completion-request", "reuse-registry", "expected-coordinator-session-sha256", "expected-author-session-sha256"):
        prepare_parser.add_argument("--" + name, required=True)
    seal_parser = sub.add_parser("seal")
    for name in ("pre-completion", "evidence-root", "repo", "ledger", "output", "reuse-registry", "expected-coordinator-session-sha256", "expected-author-session-sha256"):
        seal_parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(Path(args.inputs), Path(args.source_root), Path(args.evidence_root), Path(args.repo), Path(args.output), Path(args.completion_request), Path(args.reuse_registry), args.expected_coordinator_session_sha256, args.expected_author_session_sha256)
        else:
            seal(Path(args.pre_completion), Path(args.evidence_root), Path(args.repo), Path(args.ledger), Path(args.output), Path(args.reuse_registry), args.expected_coordinator_session_sha256, args.expected_author_session_sha256)
    except (BuildError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print("HARDEN evidence rejected: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
