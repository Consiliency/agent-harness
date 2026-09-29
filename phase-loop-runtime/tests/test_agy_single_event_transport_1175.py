"""agent-harness#1175: a one-chunk brokered Gemini prompt is ONE agy user event.

Measured on claw (agy 1.2.13, gemini-3.8-flash-high, the brokered heartbeat route):
the ingestion v1 acknowledgement turn carries the whole review task, and the model
acted on it there. 6 of 8 single-chunk legs failed -- 4 on genuine tool calls that the
deny profile refused (``run_command ls``, ``view_file`` on the profile's settings and a
builtin skill), 2 on a full review in place of the ack line. The same bundles sent as
one event were accepted 6 of 6 with no tool step.

The stream classifier is unchanged: a tool step, denied or not, still rejects the leg.

Named mutations these tests are the falsifiers for:
- M1 ``_broker_gemini_stream_protocol``: send a one-chunk prompt through the ingestion
  branch (``if len(chunks) == 1`` -> ``if False``). Fails the one-event and verifier tests.
- M2 ``_broker_gemini_stream_result``: drop the tool clauses (``step_type == "tool"`` and
  ``"tool_info" in step``) from the rejection. Fails the replayed denied-tool stream.
- M3 ``verify_harden_evidence.broker_gemini_stream_protocol``: drop the one-chunk
  requirement. Fails the verifier's multi-chunk refusal.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from phase_loop_runtime import panel_invoker as panel
from phase_loop_runtime import president_adapter


def _sealed_prompt(bundle: str = "diff --git a/x b/x\n+one line\n") -> str:
    return panel._render_broker_inline_prompt(bundle, "Review the change. End with AGREE.", "review")


def _events(protocol) -> list[dict]:
    return [json.loads(line) for line in protocol.transport.rstrip("\n").split("\n")]


def _load_verifier():
    path = Path(__file__).resolve().parents[2] / "phase-loop-runtime/scripts/verify_harden_evidence.py"
    name = "harden_evidence_verifier_1175_subject"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_a_one_chunk_prompt_is_one_event_with_no_acknowledgement_turn():
    prompt = _sealed_prompt()
    protocol = panel._broker_gemini_stream_protocol(prompt)
    event, = _events(protocol)
    content = event["message"]["content"]
    assert protocol.protocol == "agy_ndjson_single_event_v1"
    assert protocol.acknowledgements == ()
    assert prompt in content
    # nothing asks the model to store, acknowledge, or hold back: the task is this turn
    for absent in ("Reply with exactly", "Store this", panel._BROKER_AGY_STREAM_ACK_PREFIX):
        assert absent not in content
    assert content.split("\n")[-1].startswith("Return the complete review")


def test_a_prompt_over_one_chunk_keeps_ingestion_v1():
    prompt = _sealed_prompt(("+" + "x" * 80 + "\n") * 1300)
    protocol = panel._broker_gemini_stream_protocol(prompt)
    assert protocol.protocol == panel._BROKER_AGY_STREAM_PROTOCOL
    assert len(protocol.acknowledgements) >= 2
    assert len(_events(protocol)) == len(protocol.acknowledgements) + 1


def _result(response: str) -> dict:
    return {"event": "result", "result": {"conversation_id": "c", "status": "SUCCESS", "response": response}}


def test_the_one_event_parser_accepts_exactly_one_result():
    protocol = panel._broker_gemini_stream_protocol(_sealed_prompt())
    rc, text, detail, metadata = panel._broker_gemini_stream_result(
        json.dumps(_result("No blocking findings.\nAGREE")), protocol,
    )
    assert (rc, detail) == (0, "") and text.endswith("AGREE")
    assert metadata["provider_stream_protocol"] == "agy_ndjson_single_event_v1"
    # an ingestion-style ack turn before the review is not this protocol
    raw = "\n".join(json.dumps(row) for row in (_result("ack"), _result("No blocking findings.\nAGREE")))
    rc, text, detail, _ = panel._broker_gemini_stream_result(raw, protocol)
    assert rc != 0 and text == "" and "incomplete ingestion" in detail


@pytest.mark.parametrize("mutation,reason", [
    ("final", "no successful terminal response"), ("truncation", "truncation"),
    ("json", "malformed JSON"), ("empty", "conversation"),
])
def test_the_one_event_parser_keeps_every_other_rejection(mutation, reason):
    protocol = panel._broker_gemini_stream_protocol(_sealed_prompt())
    row = _result("No blocking findings.\nAGREE")
    if mutation == "final":
        # the provider's own interruption shape, seen on claw 2026-09-29 with a complete-looking body
        row["result"].update(status="ERROR", error="The stream was interrupted.")
    if mutation == "truncation":
        row["result"]["response"] = "<truncated 123 bytes>"
    raw = {"json": '{"event":', "empty": ""}.get(mutation, json.dumps(row))
    rc, text, detail, _ = panel._broker_gemini_stream_result(raw, protocol)
    assert rc != 0 and text == "" and reason in detail


# A captured agy 1.2.13 stream (2026-09-29, claw), redacted: conversation id, review text
# and the per-run scratch path replaced; the tool list trimmed. Every tool call was refused
# by the deny profile, and the model still produced a verdict.
_DENIED_TOOL_STREAM = [
    {"event": "init", "conversation_id": "c", "init": {"model": "gemini-3.8-flash-high", "cwd": "/tmp/pl-panel-REDACTED/out", "tools": ["run_command", "view_file", "invoke_subagent"], "permission_mode": "request-review"}},
    {"event": "step_update", "step_update": {"conversation_id": "c", "step_index": 0, "state": "DONE", "step_type": "user_input"}},
    {"event": "step_update", "step_update": {"conversation_id": "c", "step_index": 1, "state": "DONE", "step_type": "agent_response"}},
    {"event": "step_update", "step_update": {"conversation_id": "c", "step_index": 2, "state": "ACTIVE", "step_type": "tool", "tool_name": "run_command", "tool_info": {"name": "run_command", "parameters": {"CommandLine": "ls -la .."}}}},
    {"event": "step_update", "step_update": {"conversation_id": "c", "step_index": 2, "state": "ERROR", "step_type": "tool", "tool_name": "run_command", "tool_info": {"name": "run_command", "parameters": {"CommandLine": "ls -la .."}, "error": {"type": "TOOL_ERROR", "message": "permission check failed for command \"ls -la ..\": Permission denied for command(ls -la ..). Matches user-configured deny rule."}}}},
    {"event": "step_update", "step_update": {"conversation_id": "c", "step_index": 3, "state": "ACTIVE", "step_type": "tool", "tool_name": "view_file", "tool_info": {"name": "view_file", "parameters": {"AbsolutePath": "/dev/phase-loop-agy/.gemini/antigravity-cli/builtin/skills/antigravity_guide/SKILL.md"}}}},
    {"event": "step_update", "step_update": {"conversation_id": "c", "step_index": 3, "state": "ERROR", "step_type": "tool", "tool_name": "view_file", "tool_info": {"name": "view_file", "parameters": {"AbsolutePath": "/dev/phase-loop-agy/.gemini/antigravity-cli/builtin/skills/antigravity_guide/SKILL.md"}, "error": {"type": "TOOL_ERROR", "message": "permission check failed for read_file \"/dev/phase-loop-agy/.gemini/antigravity-cli/builtin/skills/antigravity_guide/SKILL.md\": Permission denied for read_file(/dev/phase-loop-agy/.gemini/antigravity-cli/builtin/skills/antigravity_guide/SKILL.md). Matches user-configured deny rule."}}}},
    {"event": "step_update", "step_update": {"conversation_id": "c", "step_index": 4, "state": "DONE", "step_type": "agent_response"}},
    _result("No blocking findings.\nAGREE"),
]


@pytest.mark.parametrize("keep", ["active_only", "error_only", "both"])
def test_a_denied_tool_call_still_rejects_the_leg(keep):
    protocol = panel._broker_gemini_stream_protocol(_sealed_prompt())
    rows = [row for row in _DENIED_TOOL_STREAM if not (
        row["event"] == "step_update" and row["step_update"].get("step_type") == "tool"
        and {"active_only": "ERROR", "error_only": "ACTIVE", "both": None}[keep] == row["step_update"]["state"]
    )]
    rc, text, detail, metadata = panel._broker_gemini_stream_result(
        "\n".join(json.dumps(row) for row in rows), protocol,
    )
    assert rc != 0 and text == ""
    assert detail == "Gemini broker stream rejected: tool or subagent activity observed"
    assert metadata["provider_stream_outcome"] == "parse_error"


def test_the_gemini_president_rung_is_one_event_for_a_one_chunk_prompt():
    prompt = panel._president_prompt(("F001: [grok] a finding",))
    president = president_adapter._president_gemini_stream_protocol(prompt)
    event, = _events(president)
    content = event["message"]["content"]
    assert president.acknowledgements == () and "Reply with exactly" not in content
    assert "FORCING DECISION" in content.split("\n")[-1]


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(repo)}
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=repo, env=env,
                          check=True, capture_output=True, text=True).stdout.strip()


def _generated_prompt(verifier, repo: Path, patch_lines: int) -> str:
    """A sealed prompt over the verifier's own generated Git-bound review inputs."""
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "plans").mkdir()
    (repo / "plans/phase-plan-v10-HARDEN.md").write_text("# HARDEN\n")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "base")
    base, base_tree = _git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "change.txt").write_text(("x" * 80 + "\n") * patch_lines)
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "head")
    head, tree = _git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", "HEAD^{tree}")
    bundle, instructions = (verifier.git_bound_review_input(repo, base, base_tree, head, tree, kind)
                            for kind in ("bundle", "instructions"))
    return verifier.broker_sealed_prompt(bundle, instructions)


def test_the_independent_verifier_recomputes_the_one_event_transport(tmp_path):
    verifier = _load_verifier()
    prompt = _generated_prompt(verifier, tmp_path / "small", 1)
    runtime = panel._broker_gemini_stream_protocol(prompt)
    single = verifier.broker_gemini_stream_protocol(prompt, verifier.GEMINI_SINGLE_EVENT_PROTOCOL)
    assert single["transport"] == runtime.transport
    assert single["final_event_sha256"] == runtime.final_event_sha256
    assert list(single["chunk_bytes"]) == list(runtime.chunk_bytes)
    # a record made before agent-harness#1175 still recomputes as ingestion v1
    assert verifier.broker_gemini_stream_protocol(prompt)["acknowledgements"]
    big = _generated_prompt(verifier, tmp_path / "big", 1300)
    assert len(verifier.broker_gemini_stream_protocol(big)["acknowledgements"]) >= 2
    with pytest.raises(verifier.EvidenceError):
        verifier.broker_gemini_stream_protocol(big, verifier.GEMINI_SINGLE_EVENT_PROTOCOL)
    with pytest.raises(verifier.EvidenceError):
        verifier.broker_gemini_stream_protocol(prompt, "agy_ndjson_unknown")
