"""Real object-store boundaries for agent-harness#906 and agent-harness#915."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import train_review_packet as packet
from phase_loop_runtime.train_ledger import LedgerRecord, append_record, read_ledger
from phase_loop_runtime.train_roadmap import TrainNode, TrainRoadmap


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
    return subprocess.run(["git", "-C", str(repo), *args], env=env,
                          capture_output=True, check=True).stdout.decode().strip()


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def dump(path, obj):
    path.write_text(json.dumps(obj, sort_keys=True))
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def candidate(tmp_path):
    repo = tmp_path / "node"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "code.py").write_text("old = 1\n")
    (repo / "gone.py").write_text("deleted = 1\n")
    (repo / "tool").write_text("echo test\n")
    (repo / "generated").mkdir()
    (repo / "generated" / "source.py").write_text("source-looking disposal\n")
    base = commit(repo, "base")
    git(repo, "checkout", "-qb", "candidate")
    (repo / "code.py").write_text("actual_changed_code = 2\n")
    (repo / "gone.py").rename(repo / "renamed.py")
    (repo / "tool").chmod(0o755)
    head = commit(repo, "candidate")
    node = TrainNode("repo-a", "CHANGELOG.md")
    roadmap = TrainRoadmap("packet boundary", [node])
    state = {node.node_id: LedgerRecord(node.node_id, "pr_open", branch="candidate",
                                      head_sha=head, pr_url="https://github.com/org/repo/pull/7")}
    acceptance = dump(tmp_path / "acceptance.txt", {"criterion": "actual acceptance sentinel"})
    evidence = dump(tmp_path / "evidence.txt", {"output": "actual evidence sentinel"})
    material = {"schema_version": 1, "nodes": {node.node_id: {
        "head_sha": head,
        "acceptance": [{"id": "AC1", "text": "Source and modes are correct", "provenance": acceptance}],
        "verification": [{"id": "pytest", "kind": "attested_command", "head_sha": head,
            "argv": ["python", "-m", "pytest"], "exit_code": 0, "result": "passed",
            "attested_by": "test operator", "observed_at": "2026-09-22T00:00:00Z", "evidence": evidence}],
        "context": [], "generated_removals": []}}}
    material_path = tmp_path / "material.json"
    dump(material_path, material)
    live = {"url": state[node.node_id].pr_url, "state": "OPEN", "headRefOid": head,
            "baseRefName": "main", "baseRefOid": base, "mergeCommit": None}
    def build(**kw):
        return packet.build_review_packet(roadmap, state, lambda n: repo, material_path,
                                         _pr_metadata_fn=lambda *_: dict(live), **kw)
    return dict(repo=repo, base=base, head=head, node=node, roadmap=roadmap, state=state,
                material=material, material_path=material_path, live=live, build=build, tmp=tmp_path)


def update_material(c):
    dump(c["material_path"], c["material"])


def test_git_reader_isolation_admitted_scope_not_label_or_workspace_head(candidate):
    c = candidate
    git(c["repo"], "checkout", "-q", "main")
    (c["repo"] / "code.py").write_text("dirty source must never appear\n")
    result = c["build"]()
    assert "actual_changed_code" in result.artifact
    assert "dirty source" not in result.artifact
    for name in ("gone.py", "renamed.py", "tool"):
        assert name in result.artifact
    assert "100755" in result.artifact
    assert "actual evidence sentinel" in result.artifact
    assert "operator-supplied attestation" in result.artifact


def test_git_reader_isolation_hostile_config_attributes_env(candidate, monkeypatch):
    c = candidate
    expected = c["build"]().artifact
    git(c["repo"], "config", "diff.external", "/must-not-execute")
    (c["repo"] / ".git" / "info" / "attributes").write_text("* -diff\n")
    (c["repo"] / ".gitattributes").write_text("* -diff\n")
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", "/must-not-execute")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "diff.external")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "/must-not-execute")
    assert c["build"]().artifact == expected


@pytest.mark.parametrize("field,value,reason", [
    ("headRefOid", "f" * 40, "stale_head"),
    ("baseRefName", "release", "retargeted_base"),
    ("state", "CLOSED", "pr_not_open"),
])
def test_observed_identity_drift_before_build(candidate, field, value, reason):
    candidate["live"][field] = value
    with pytest.raises(packet.PacketError, match=reason):
        candidate["build"]()


def test_git_reader_isolation_missing_object_never_fetches(candidate):
    candidate["live"]["baseRefOid"] = "f" * 40
    with pytest.raises(packet.PacketError, match="missing_git_object"):
        candidate["build"]()


def test_material_provenance_changed_acceptance_changes_identity(candidate):
    first = candidate["build"]()
    candidate["material"]["nodes"][candidate["node"].node_id]["acceptance"][0]["text"] += " amended"
    update_material(candidate)
    assert first.sha256 != candidate["build"]().sha256


@pytest.mark.parametrize("mutation", ["unbound", "result", "unknown", "digest", "intermediate_symlink"])
def test_material_provenance_refuses_invalid(candidate, mutation):
    c = candidate
    record = c["material"]["nodes"][c["node"].node_id]["verification"][0]
    if mutation == "unbound":
        record["head_sha"] = "f" * 40
    elif mutation == "result":
        record["exit_code"] = 1
    elif mutation == "unknown":
        record["extra"] = True
    elif mutation == "digest":
        record["evidence"]["sha256"] = "f" * 64
    else:
        (c["tmp"] / "link").symlink_to(c["tmp"], target_is_directory=True)
        record["evidence"]["path"] = "link/evidence.txt"
    update_material(c)
    with pytest.raises(packet.PacketError):
        c["build"]()


@pytest.mark.parametrize("text", ["a\r\nb\r", "literal\\r vs\r\n", "zero\u200bwidth\x01\t\n"])
def test_packet_text_encoding_reversible(text):
    encoded = packet.escape_text(text)
    assert "\r" not in encoded and "\u200b" not in encoded
    # JSON decoding shares the fixed-width escape grammar after protecting LF/TAB.
    decoded = json.loads('"' + encoded.replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t') + '"')
    assert decoded == text


def certify(c):
    (c["repo"] / "generated" / "source.py").unlink()
    head = commit(c["repo"], "remove generated subtree")
    c["head"] = head
    c["state"][c["node"].node_id].head_sha = head
    c["live"]["headRefOid"] = head
    material = c["material"]["nodes"][c["node"].node_id]
    material["head_sha"] = head
    material["verification"][0]["head_sha"] = head
    tree = git(c["repo"], "rev-parse", c["base"] + ":generated")
    att = dump(c["tmp"] / "disposal.json", {"attested_by": "operator", "observed_at": "2026-09-22T00:00:00Z",
        "base_tip_sha": c["base"], "merge_base_sha": c["base"], "head_sha": head,
        "path": "generated", "base_tree_oid": tree, "disposal_scope": "Discard this source-looking fixture tree"})
    material["generated_removals"] = [{"path": "generated", "base_tree_oid": tree,
        "rationale": "explicit disposal assertion", "attestation": att}]
    update_material(c)


def test_certificate_visibility_source_looking_is_attestation_not_generated_proof(candidate):
    certify(candidate)
    result = candidate["build"]()
    assert "source-looking fixture tree" in result.artifact
    assert "not proof of generatedness" in result.artifact
    assert "-source-looking disposal" not in result.artifact
    assert result.removals
    assert "generated/source.py" in json.dumps(result.removals)


def test_certificate_copy_out_new_identical_refuses(candidate):
    c = candidate
    (c["repo"] / "copy.py").write_text("source-looking disposal\n")
    certify(c)
    with pytest.raises(packet.PacketError, match="new_copy_out"):
        c["build"]()


def test_preview_output_deterministic_zero_ledger_effects(candidate):
    c = candidate
    ledger = c["tmp"] / "ledger" / "train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    before = ledger.read_bytes(), git(c["repo"], "rev-parse", "HEAD")
    for name in ("preview-a", "preview-b"):
        receipt = packet.preview_review_packet(c["roadmap"], ledger, lambda n: c["repo"],
            c["material_path"], c["tmp"] / name, _pr_metadata_fn=lambda *_: dict(c["live"]))
        assert receipt["ready"] is True
        assert receipt["rendered_prompt_bytes"] > receipt["packet_bytes"]
    assert (c["tmp"] / "preview-a/packet.md").read_bytes() == (c["tmp"] / "preview-b/packet.md").read_bytes()
    assert before == (ledger.read_bytes(), git(c["repo"], "rev-parse", "HEAD"))


def test_preview_output_nonempty_refuses(candidate):
    c = candidate
    receipt = packet.preview_review_packet(c["roadmap"], c["tmp"] / "ledger", lambda n: c["repo"],
        c["material_path"], c["repo"], _pr_metadata_fn=lambda *_: dict(c["live"]))
    assert receipt["ready"] is False
    assert not (c["repo"] / "receipt.json").exists()


def test_historical_packet_immutable_store_corruption_holds(candidate):
    result = candidate["build"]()
    root = candidate["tmp"] / "store"
    stored = packet.store_review_packet(result, root)
    assert packet.load_review_packet(root, result.sha256).artifact == result.artifact
    (stored / "packet.md").write_text("corrupt")
    with pytest.raises(packet.PacketError):
        packet.store_review_packet(result, root)
    with pytest.raises(packet.PacketError):
        packet.load_review_packet(root, result.sha256)


def test_approval_digest_round_trip(tmp_path):
    path = tmp_path / "ledger"
    rec = LedgerRecord("_train_review_", "approved", usable_reviewers=4, review_packet_sha256="a" * 64)
    append_record(path, rec)
    assert read_ledger(path)[rec.node_id].review_packet_sha256 == "a" * 64
    assert "review_packet_sha256" not in LedgerRecord("n", "pending").to_dict()


def never(*args, **kwargs):
    raise AssertionError("forbidden side effect reached")


def approved(artifact, mode):
    from phase_loop_runtime.governed_premerge import LoopResult
    from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult
    return LoopResult(mergeable=True, ran=True, rounds=1, panel=PanelResult(legs=[
        PanelLegResult(leg=vendor, status="OK", text="Source reviewed.\nAGREE")
        for vendor in ("codex", "claude", "gemini", "grok")]))


def run_candidate(c, monkeypatch, **kwargs):
    from phase_loop_runtime import train_runner as tr
    ledger = c["tmp"] / "ledger" / "train.ledger.jsonl"
    if not ledger.exists():
        append_record(ledger, c["state"][c["node"].node_id])
    monkeypatch.setattr(packet, "read_pr_metadata", lambda *_: dict(c["live"]))
    options = dict(run_mode="governed", review_only=True, review_material=c["material_path"],
        resolve_workspace=lambda _: c["repo"], _run_loop=never, _publish=never,
        _preflight_fn=lambda *_: [], _pr_is_open=lambda *_: True,
        _live_pr_head_sha_fn=lambda *_: c["live"]["headRefOid"], _merge_phase_enabled=True,
        _pr_merged_sha_fn=lambda *a, **k: None, _train_review_fn=approved,
        _merge_pr_fn=never, _post_merge_hook=lambda *_: None)
    options.update(kwargs)
    return tr.run_train(c["roadmap"], ledger, **options)


def test_real_runner_packet_cached_only_with_exact_material(candidate, monkeypatch):
    c = candidate
    first = run_candidate(c, monkeypatch)
    assert first["status"] == "review_approved", first
    artifact = Path(first["review_packet_path"]).read_text()
    assert "actual_changed_code" in artifact and "actual evidence sentinel" in artifact
    assert first["review_packet_sha256"] == hashlib.sha256(artifact.encode()).hexdigest()
    assert run_candidate(c, monkeypatch, review_material=None, _train_review_fn=never)["status"] == "review_approved"
    c["material"]["nodes"][c["node"].node_id]["acceptance"][0]["text"] += " changed"
    update_material(c)
    calls = []
    def review(artifact, mode):
        calls.append(artifact)
        return approved(artifact, mode)
    second = run_candidate(c, monkeypatch, _train_review_fn=review)
    assert second["status"] == "review_approved" and len(calls) == 1
    assert second["review_packet_sha256"] != first["review_packet_sha256"]


def test_real_runner_legacy_count_only_approval_requires_review(candidate, monkeypatch):
    c = candidate
    ledger = c["tmp"] / "ledger" / "train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    append_record(ledger, LedgerRecord("_train_review_", "approved", usable_reviewers=4))
    calls = []
    def review(artifact, mode):
        calls.append(artifact)
        return approved(artifact, mode)
    assert run_candidate(c, monkeypatch, _train_review_fn=review)["status"] == "review_approved"
    assert len(calls) == 1


def test_observed_identity_drift_before_approval_records_nothing(candidate, monkeypatch):
    c = candidate
    def review(artifact, mode):
        c["live"]["baseRefOid"] = "f" * 40
        return approved(artifact, mode)
    result = run_candidate(c, monkeypatch, _train_review_fn=review)
    assert result["status"] == "review_halted" and result["reason"] == "observed_identity_drift"
    assert "_train_review_" not in read_ledger(c["tmp"] / "ledger/train.ledger.jsonl")


def test_real_runner_native_stale_fill_precedes_cache(candidate, monkeypatch):
    from types import SimpleNamespace
    c = candidate
    assert run_candidate(c, monkeypatch)["status"] == "review_approved"
    result = run_candidate(c, monkeypatch, native_leg_fills=[SimpleNamespace(artifact_sha256="f" * 64)], _train_review_fn=never)
    assert result["reason"] == "native_fill_stale_request"


def test_real_runner_native_emission_uses_stored_packet(candidate, monkeypatch):
    c = candidate
    seen = []
    def emit(artifact, **kwargs):
        seen.append(artifact)
        return {"status": "native_fill_requested"}
    result = run_candidate(c, monkeypatch, emit_native_request=True, _emit_native_fill_request_fn=emit, _train_review_fn=never)
    assert result["status"] == "native_fill_requested"
    digest = hashlib.sha256(seen[0].encode()).hexdigest()
    assert (c["tmp"] / "ledger/review-packets" / digest / "packet.md").read_text() == seen[0]


def test_historical_packet_missing_on_partial_resume_holds(candidate, monkeypatch):
    c = candidate
    record = c["state"][c["node"].node_id]
    record.status = "merged"
    record.upstream_merge_sha = c["head"]
    result = run_candidate(c, monkeypatch, _train_review_fn=never)
    assert result["reason"] == "historical_packet_unavailable"


def test_historical_packet_valid_retains_original_base_after_merge(candidate):
    c = candidate
    historical = c["build"]()
    record = c["state"][c["node"].node_id]
    record.status = "merged"
    record.upstream_merge_sha = c["head"]
    c["live"].update(state="MERGED", mergeCommit={"oid": c["head"]}, baseRefOid=c["head"])
    result = c["build"](historical=historical)
    assert result.sha256 == historical.sha256
    assert result.metadata["nodes"][0]["identity"]["base_tip_sha"] == c["base"]


def test_preview_output_cli_never_constructs_broker_or_runs_train(candidate, monkeypatch, capsys):
    from phase_loop_runtime import cli, train_runner
    from phase_loop_runtime.convergence import broker
    c = candidate
    train = c["tmp"] / "train.md"
    train.write_text("# Release Train: packet boundary\n\n## Nodes\n\n### Node: repo-a / CHANGELOG.md\n\n**Depends on:** (none)\n**Channel:** (none)\n")
    ledger = c["tmp"] / "ledger/train-train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    before = ledger.read_bytes()
    monkeypatch.setattr(packet, "read_pr_metadata", lambda *_: dict(c["live"]))
    monkeypatch.setattr(broker, "build_routing_broker_client", never)
    monkeypatch.setattr(train_runner, "run_train", never)
    args = ["run-train", "--train", str(train), "--governed", "--review-only", "--review-material", str(c["material_path"]),
            "--preview-review", str(c["tmp"] / "preview"), "--workspace", "repo-a=" + str(c["repo"]), "--ledger-dir", str(ledger.parent), "--json"]
    assert cli.main(args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["ready"] and receipt["model_calls"] == 0
    assert ledger.read_bytes() == before
    assert not (ledger.parent / "broker").exists()


def test_preview_output_torn_ledger_is_not_repaired(candidate):
    c = candidate
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    ledger.write_bytes(ledger.read_bytes() + b'{"node_id":')
    before = ledger.read_bytes()
    receipt = packet.preview_review_packet(c["roadmap"], ledger, lambda n: c["repo"], c["material_path"], c["tmp"] / "preview")
    assert not receipt["ready"] and "torn_ledger" in receipt["errors"][0]
    assert ledger.read_bytes() == before
    assert not (c["tmp"] / "preview/packet.md").exists()


def test_render_preflight_wrapper_core_parity_and_fake_stage_refusal(tmp_path):
    from phase_loop_runtime import panel_invoker as pi
    from test_broker_staged_tree_delivery import _sandbox
    tree = _sandbox(tmp_path)
    artifact, instructions = "changed source\n", "review exactly\n"
    for stage in (None, tree):
        preamble = pi._BROKER_REVIEW_SEALED_PREAMBLE if stage is None else pi._broker_review_sandbox_preamble(stage)
        core = pi._assemble_broker_inline_prompt(artifact, instructions, preamble.rstrip("\n"),
            pi._digest_bound_broker_delimiters("AUTHORITATIVE-INSTRUCTIONS", instructions.encode()),
            pi._digest_bound_broker_delimiters("UNTRUSTED-REVIEW-BUNDLE", artifact.encode()))
        assert core == pi._render_broker_inline_prompt(artifact, instructions, "review", stage)
    with pytest.raises(ValueError):
        pi._render_broker_inline_prompt(artifact, instructions, "review", tmp_path)


def test_render_preflight_exact_bound_and_one_over(monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    rendered = packet.preflight_packet("source", instructions="review")
    monkeypatch.setattr(pi, "_BROKER_SEALED_PROMPT_MAX_BYTES", rendered["rendered_prompt_bytes"])
    assert packet.preflight_packet("source", instructions="review") == rendered
    with pytest.raises(ValueError, match="sealed transport bound"):
        packet.preflight_packet("source!", instructions="review")


def test_render_preflight_last_route_overflow_prevents_authorization_and_emission(candidate, monkeypatch):
    from phase_loop_runtime import governed_review as gr, panel_invoker as pi
    from phase_loop_runtime.advisor_board import backing
    from test_train_review_authorization import _board
    c = candidate
    artifact = c["build"]().artifact
    sealed = pi._render_broker_inline_prompt(artifact, pi._resolve_brief("review", None), "review")
    monkeypatch.setattr(pi, "_BROKER_SEALED_PROMPT_MAX_BYTES", len(sealed.encode()))
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization", never)
    result = gr.governed_board_gate(artifact=artifact, author_executor="train-coordinator", run_mode="governed",
        canonical_repo_authority=c["repo"], compose=lambda: _board("codex", "gemini", "grok"), invoke=never,
        emit_native_request=True, native_fill_dir=c["tmp"] / "emission")
    assert result.reason == "review_isolation_unavailable"
    assert not (c["tmp"] / "emission").exists()


@pytest.mark.parametrize("status,conclusion,result", [
    ("completed", "success", "passed"), ("completed", "failure", "failed"),
    ("completed", "timed_out", "failed"), ("completed", "cancelled", "failed"),
    ("completed", "action_required", "failed"), ("completed", "skipped", "skipped"),
    ("completed", "neutral", "skipped"), ("completed", "stale", "unknown"),
    ("completed", None, "unknown"), ("queued", "success", "unknown"),
    ("in_progress", "failure", "unknown"), ("completed", "new_value", "unknown"),
])
def test_material_provenance_check_status_mapping(candidate, status, conclusion, result):
    c = candidate
    c["material"]["nodes"][c["node"].node_id]["verification"] = [{"id": "ci", "kind": "github_check_run", "check_run_id": 9}]
    update_material(c)
    check = {"id": 9, "head_sha": c["head"], "name": "test", "status": status, "conclusion": conclusion,
        "url": "https://api.github.com/repos/org/repo/check-runs/9", "app": {"id": 1, "slug": "actions"},
        "check_suite": {"id": 2, "repository": {"full_name": "org/repo"}}, "output": {"summary": "check evidence sentinel"}}
    built = c["build"](_check_run_fn=lambda *_: check)
    record = built.metadata["nodes"][0]["material"]["verification"][0]
    assert record["result"] == result and record["status"] == status and record["conclusion"] == conclusion
    assert "reported by GitHub App actions" in built.artifact
    assert record["name_pinned"] is False and record["app_pinned"] is False


def test_certificate_comparison_tree_unrelated_main_change_requires_fresh_attestation(candidate):
    c = candidate
    certify(c)
    git(c["repo"], "checkout", "-q", "main")
    (c["repo"] / "unrelated").write_text("base-only change\n")
    new_base = commit(c["repo"], "advance main")
    c["live"]["baseRefOid"] = new_base
    with pytest.raises(packet.PacketError, match="disposal_attestation_mismatch"):
        c["build"]()
    declaration = c["material"]["nodes"][c["node"].node_id]["generated_removals"][0]
    attestation = json.loads((c["tmp"] / "disposal.json").read_text())
    attestation["base_tip_sha"] = new_base
    declaration["attestation"] = dump(c["tmp"] / "disposal.json", attestation)
    update_material(c)
    built = c["build"]()
    assert "base-only change" not in built.artifact
    assert built.metadata["nodes"][0]["identity"]["merge_base_sha"] == c["base"]


def test_certificate_comparison_tree_base_side_change_refuses(candidate):
    c = candidate
    certify(c)
    git(c["repo"], "checkout", "-q", "main")
    (c["repo"] / "generated/source.py").write_text("changed on main\n")
    c["live"]["baseRefOid"] = commit(c["repo"], "change disposal subtree")
    with pytest.raises(packet.PacketError, match="removal_base_subtree_changed"):
        c["build"]()


def test_certificate_copy_out_modified_visible(candidate):
    c = candidate
    (c["repo"] / "modified-copy.py").write_text("source-looking disposal but modified\n")
    certify(c)
    assert "+source-looking disposal but modified" in c["build"]().artifact


def test_packet_text_encoding_crlf_to_lf_is_visible(candidate):
    c = candidate
    (c["repo"] / "code.py").write_bytes(b"actual_changed_code = 2\r\n")
    head = commit(c["repo"], "CRLF change")
    c["state"][c["node"].node_id].head_sha = head
    c["live"]["headRefOid"] = head
    raw = c["material"]["nodes"][c["node"].node_id]
    raw["head_sha"] = raw["verification"][0]["head_sha"] = head
    update_material(c)
    built = c["build"]()
    assert "+actual_changed_code = 2\\r\n" in built.artifact
    assert "\r" not in built.artifact


def synthetic_packet_for_flow_tests(roadmap, state, *_args, **_kwargs):
    """Explicit control-flow fixture. This supplies NO Git-binding evidence.

    Historical train tests isolate publishing/reverification/merge behavior with
    fake repositories. Real object and cache authority are exercised above.
    """
    from dataclasses import asdict
    nodes = []
    for node in roadmap.topo_order():
        record = state[node.node_id]
        nodes.append({"identity": {"node_id": node.node_id, "head_sha": record.head_sha, "pr_url": record.pr_url},
            "material": {"declaration_sha256": "0" * 64, "acceptance": [], "verification": []},
            "inventory": [], "inventory_sha256": "0" * 64, "changed_paths": 0,
            "git_version": "SYNTHETIC FLOW FIXTURE - NOT GIT EVIDENCE", "diff_argv": [], "inventory_argv": [],
            "certificates": [], "context": [], "patch": packet._text(b"synthetic flow fixture\n", "fixture")})
    metadata = {"schema_version": 1, "train": {"title": roadmap.title, "nodes": [asdict(n) for n in roadmap.nodes]},
                "nodes": nodes, "material_manifest_sha256": "0" * 64, "removals_sha256": packet._sha(packet._json([]).encode())}
    return packet.ReviewPacket(packet._render(metadata), metadata, [])


@pytest.fixture
def synthetic_train_packet(monkeypatch):
    monkeypatch.setattr(packet, "build_review_packet", synthetic_packet_for_flow_tests)
    monkeypatch.setattr(packet, "recheck_packet_identities", lambda *a, **k: None)


def seed_synthetic_packet(ledger, roadmap):
    """Explicitly seed a historical packet for a synthetic resume test."""
    from dataclasses import replace
    state = read_ledger(ledger)
    built = synthetic_packet_for_flow_tests(roadmap, state)
    packet.store_review_packet(built, ledger.parent / "review-packets")
    approval = state.get("_train_review_")
    if approval is not None:
        append_record(ledger, replace(approval, review_packet_sha256=built.sha256))


def test_observed_identity_drift_same_repo_after_first_merge_holds_second(candidate, monkeypatch):
    from dataclasses import replace
    from phase_loop_runtime import train_runner as tr
    c = candidate
    first = c["node"]
    second = TrainNode("repo-a", "SECOND.md")
    c["roadmap"].nodes.append(second)
    second_record = replace(c["state"][first.node_id], node_id=second.node_id,
                            branch="candidate-second", pr_url="https://github.com/org/repo/pull/8")
    c["state"][second.node_id] = second_record
    c["material"]["nodes"][second.node_id] = json.loads(json.dumps(c["material"]["nodes"][first.node_id]))
    update_material(c)
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    for record in c["state"].values():
        append_record(ledger, record)
    live = {c["live"]["url"]: dict(c["live"]), second_record.pr_url: {**c["live"], "url": second_record.pr_url}}
    monkeypatch.setattr(packet, "read_pr_metadata", lambda _, url: dict(live[url]))
    merges = []
    def merge(workspace, branch, *, base, head_sha):
        assert base == "main" and head_sha == c["head"]
        merges.append(branch)
        live[second_record.pr_url]["baseRefOid"] = c["head"]
        live[c["live"]["url"]].update(state="MERGED", mergeCommit={"oid": c["head"]}, baseRefOid=c["head"])
        return c["head"]
    options = dict(run_mode="governed", review_material=c["material_path"], resolve_workspace=lambda _: c["repo"],
        _run_loop=never, _publish=never, _preflight_fn=lambda *_: [], _pr_is_open=lambda *_: True,
        _live_pr_head_sha_fn=lambda *_: c["head"], _merge_phase_enabled=True,
        _pr_merged_sha_fn=lambda *a, **k: None, _train_review_fn=approved, _merge_pr_fn=merge, _post_merge_hook=lambda *_: None)
    result = tr.run_train(c["roadmap"], ledger, **options)
    assert result["status"] == "review_halted" and result["reason"] == "observed_identity_drift"
    assert merges == ["candidate"]
    state = read_ledger(ledger)
    assert state[first.node_id].status == "merged" and state[second.node_id].status == "pr_open"
    historical = packet.load_review_packet(ledger.parent / "review-packets", state["_train_review_"].review_packet_sha256)
    rebuilt = packet.build_review_packet(c["roadmap"], state, lambda _: c["repo"], c["material_path"], historical=historical)
    assert rebuilt.metadata["nodes"][0] == historical.metadata["nodes"][0]
    assert rebuilt.metadata["nodes"][1]["identity"]["base_tip_sha"] == c["head"]
    assert rebuilt.sha256 != historical.sha256


def test_certificate_copy_out_empty_blob_remains_conservative(candidate):
    c = candidate
    git(c["repo"], "checkout", "-q", "main")
    (c["repo"] / "generated/source.py").write_bytes(b"")
    c["base"] = commit(c["repo"], "empty generated base")
    c["live"]["baseRefOid"] = c["base"]
    git(c["repo"], "checkout", "-qb", "empty-candidate")
    (c["repo"] / "outside-empty").write_bytes(b"")
    certify(c)
    with pytest.raises(packet.PacketError, match="new_copy_out"):
        c["build"]()


def test_certificate_copy_out_preexisting_duplicate_allowed(candidate):
    c = candidate
    git(c["repo"], "checkout", "-q", "main")
    (c["repo"] / "preexisting.py").write_text("source-looking disposal\n")
    c["base"] = commit(c["repo"], "preexisting outside duplicate")
    c["live"]["baseRefOid"] = c["base"]
    git(c["repo"], "checkout", "-qb", "duplicate-candidate")
    certify(c)
    assert c["build"]().removals


@pytest.mark.parametrize("mutation", ["overlap", "wrong_tree", "wrong_head", "CODEOWNERS", "survivor"])
def test_certificate_visibility_invalid_groups_refused(candidate, mutation):
    c = candidate
    if mutation in {"CODEOWNERS", "survivor"}:
        git(c["repo"], "checkout", "-q", "main")
        (c["repo"] / "generated/CODEOWNERS").write_text("* @owner\n")
        c["base"] = commit(c["repo"], "governance subtree")
        c["live"]["baseRefOid"] = c["base"]
        git(c["repo"], "checkout", "-qb", "governance-candidate")
        if mutation == "CODEOWNERS":
            (c["repo"] / "generated/CODEOWNERS").unlink()
    certify(c)
    groups = c["material"]["nodes"][c["node"].node_id]["generated_removals"]
    if mutation == "overlap":
        groups.append(dict(groups[0]))
    elif mutation == "wrong_tree":
        groups[0]["base_tree_oid"] = c["base"]
    elif mutation == "wrong_head":
        att = json.loads((c["tmp"] / "disposal.json").read_text())
        att["head_sha"] = c["base"]
        groups[0]["attestation"] = dump(c["tmp"] / "disposal.json", att)
    update_material(c)
    with pytest.raises(packet.PacketError):
        c["build"]()


def test_git_reader_isolation_symlink_blob_never_dereferenced(candidate):
    c = candidate
    (c["repo"] / "link").symlink_to("/private/never-open")
    head = commit(c["repo"], "symlink data")
    c["state"][c["node"].node_id].head_sha = head
    c["live"]["headRefOid"] = head
    raw = c["material"]["nodes"][c["node"].node_id]
    raw["head_sha"] = raw["verification"][0]["head_sha"] = head
    update_material(c)
    built = c["build"]()
    assert "+/private/never-open" in built.artifact and "120000" in built.artifact


def test_git_reader_isolation_binary_source_holds(candidate):
    c = candidate
    (c["repo"] / "code.py").write_bytes(b"binary\x00source")
    head = commit(c["repo"], "binary change")
    c["state"][c["node"].node_id].head_sha = head
    c["live"]["headRefOid"] = head
    raw = c["material"]["nodes"][c["node"].node_id]
    raw["head_sha"] = raw["verification"][0]["head_sha"] = head
    update_material(c)
    with pytest.raises(packet.PacketError, match="binary_source: code.py"):
        c["build"]()


def test_material_provenance_sidecar_mutation_cannot_rebind_approval(candidate):
    built = candidate["build"]()
    root = candidate["tmp"] / "packets"
    directory = packet.store_review_packet(built, root)
    metadata = json.loads((directory / "packet.json").read_text())
    metadata["nodes"][0]["material"]["head_sha"] = "f" * 40
    (directory / "packet.json").write_text(json.dumps(metadata))
    with pytest.raises(packet.PacketError, match="stored_packet_corrupt"):
        packet.load_review_packet(root, built.sha256)


def test_git_reader_isolation_patch_inventory_crosscheck_catches_wrong_path(candidate, monkeypatch):
    original = packet._GitReader.patch
    def substituted(self, base, head, paths):
        return original(self, base, head, ["gone.py"] if paths == ["code.py"] else paths)
    monkeypatch.setattr(packet._GitReader, "patch", substituted)
    with pytest.raises(packet.PacketError, match="patch_inventory_mismatch: code.py"):
        candidate["build"]()


def test_packet_delivery_real_gate_and_invoker_preserve_inline_material(candidate, monkeypatch):
    """Sanctioned hermetic delivery proof, not an actual provider approval."""
    from phase_loop_runtime import governed_premerge as gp, governed_review as gr, panel_invoker as pi
    from phase_loop_runtime.advisor_board import backing, composition
    from phase_loop_runtime.advisor_board.matrix import default_matrix
    from test_train_review_authorization import _board
    c = candidate
    certify(c)
    built = c["build"]()
    board = _board("codex", "gemini", "grok")
    monkeypatch.setattr(composition, "compose_review_board", lambda: board)
    factory = backing.prepare_review_isolation_authorization
    minted = {}
    def stable_factory(board, artifact, **kwargs):
        if "auth" not in minted:
            minted["auth"] = factory(board, artifact, **kwargs)
        return minted["auth"]
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization", stable_factory)
    seen = {}
    def spawn(leg, artifact):
        assert artifact == built.artifact
        prompt = pi._render_broker_inline_prompt(artifact, pi._resolve_brief("review", None), "review")
        assert "actual_changed_code" in prompt and "actual evidence sentinel" in prompt
        assert f"UNTRUSTED-REVIEW-BUNDLE sha256={built.sha256}" in prompt
        assert "generated/source.py" not in prompt
        seen[leg] = prompt
        return "OK", "Hermetic wiring control only.\nAGREE"
    real_invoke = pi.invoke_board
    def invoke(board, artifact, **kwargs):
        scratch = Path(kwargs["repo_dir"])
        assert not list(scratch.rglob("removals.json"))
        return real_invoke(board, artifact, matrix=default_matrix(env={}, probe=lambda _: True),
                           base_env={}, max_concurrency=1, **kwargs)
    result = gr.governed_board_gate(artifact=built.artifact, author_executor="train-coordinator", run_mode="governed",
        canonical_repo_authority=c["repo"], spawn=spawn, invoke=invoke)
    assert result.promoted, result
    assert set(seen) == {"codex", "gemini", "grok"}
    assert "Do not use or request tools" in seen["gemini"]


@pytest.mark.parametrize("component", ["base", "head", "evidence", "context", "train"])
def test_real_runner_changed_bound_component_rereviews(candidate, monkeypatch, component):
    c = candidate
    first = run_candidate(c, monkeypatch)
    raw = c["material"]["nodes"][c["node"].node_id]
    if component == "base":
        git(c["repo"], "checkout", "-q", "main")
        (c["repo"] / "main-only").write_text("unrelated base advancement\n")
        c["live"]["baseRefOid"] = commit(c["repo"], "advance base")
    elif component == "head":
        (c["repo"] / "code.py").write_text("candidate has advanced\n")
        head = commit(c["repo"], "new admission")
        c["live"]["headRefOid"] = head
        record = c["state"][c["node"].node_id]
        record.head_sha = head
        append_record(c["tmp"] / "ledger/train.ledger.jsonl", record)
        raw["head_sha"] = raw["verification"][0]["head_sha"] = head
    elif component == "evidence":
        raw["verification"][0]["evidence"] = dump(c["tmp"] / "evidence.txt", {"output": "new observed failure"})
        raw["verification"][0].update(result="failed", exit_code=1)
    elif component == "context":
        raw["context"] = ["tool"]
    else:
        c["roadmap"].title += " revised scope"
    update_material(c)
    seen = []
    def review(artifact, mode):
        seen.append(artifact)
        return approved(artifact, mode)
    result = run_candidate(c, monkeypatch, _train_review_fn=review)
    assert result["status"] == "review_approved", result
    assert len(seen) == 1 and result["review_packet_sha256"] != first["review_packet_sha256"]


def test_real_runner_current_reviewer_floor_invalidates_old_count(candidate, monkeypatch):
    from dataclasses import replace
    c = candidate
    assert run_candidate(c, monkeypatch)["status"] == "review_approved"
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    rec = read_ledger(ledger)["_train_review_"]
    append_record(ledger, replace(rec, usable_reviewers=1))
    seen = []
    def review(artifact, mode):
        seen.append(artifact)
        return approved(artifact, mode)
    assert run_candidate(c, monkeypatch, _train_review_fn=review)["status"] == "review_approved"
    assert len(seen) == 1


@pytest.mark.parametrize("target", ["head_sha", "expected_name", "expected_app_slug", "repository", "output"])
def test_material_provenance_check_identity_failures(candidate, target):
    c = candidate
    record = {"id": "ci", "kind": "github_check_run", "check_run_id": 9}
    check = {"id": 9, "head_sha": c["head"], "name": "test", "status": "completed", "conclusion": "success",
        "url": "https://api.github.com/repos/org/repo/check-runs/9", "app": {"id": 1, "slug": "actions"},
        "check_suite": {"id": 2, "repository": {"full_name": "org/repo"}}, "output": {"summary": "evidence"}}
    if target.startswith("expected_"):
        record[target] = "wrong"
    elif target == "repository":
        check["check_suite"]["repository"]["full_name"] = "other/repo"
    elif target == "output":
        check["output"]["summary"] = 12
    else:
        check[target] = "f" * 40
    c["material"]["nodes"][c["node"].node_id]["verification"] = [record]
    update_material(c)
    with pytest.raises(packet.PacketError):
        c["build"](_check_run_fn=lambda *_: check)


def test_preview_output_missing_workspace_does_not_create_it(candidate):
    c = candidate
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    missing = c["tmp"] / "missing-checkout"
    result = packet.preview_review_packet(c["roadmap"], ledger, lambda _: missing, c["material_path"], c["tmp"] / "preview",
        _pr_metadata_fn=lambda *_: dict(c["live"]))
    assert not result["ready"] and "missing_workspace" in result["errors"][0]
    assert not missing.exists()


def test_preview_output_symlink_component_refused(candidate):
    c = candidate
    link = c["tmp"] / "output-link"
    link.symlink_to(c["tmp"], target_is_directory=True)
    result = packet.preview_review_packet(c["roadmap"], c["tmp"] / "ledger/train.ledger.jsonl", lambda _: c["repo"],
        c["material_path"], link / "preview")
    assert not result["ready"] and "preview_output_symlink" in result["errors"][0]
    assert not (c["tmp"] / "preview").exists()


@pytest.mark.parametrize("mutation", [None, "brief", "composition"])
def test_real_runner_native_binding_before_unchanged_cache(candidate, monkeypatch, mutation):
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime.advisor_board import backing, composition
    from test_native_claude_seat_fill import _mixed_board, _fill
    c = candidate
    result = run_candidate(c, monkeypatch)
    board = _mixed_board()
    monkeypatch.setattr(composition, "compose_review_board", lambda: board)
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization", never)
    monkeypatch.setenv("CLAUDECODE", "1")
    fill = _fill(pi.NativeLegFill, board.seats[0], artifact_sha256=result["review_packet_sha256"],
        brief_sha256="f" * 64 if mutation == "brief" else pi.content_sha256(pi._resolve_brief("review", None)),
        composition_sha256="f" * 64 if mutation == "composition" else composition.composition_digest(board))
    cached = run_candidate(c, monkeypatch, native_leg_fills=[fill], _train_review_fn=never)
    assert cached["status"] == ("review_approved" if mutation is None else "review_halted"), cached
