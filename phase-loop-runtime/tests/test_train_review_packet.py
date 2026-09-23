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


def test_git_reader_isolation_missing_object_refused(candidate):
    candidate["live"]["baseRefOid"] = "f" * 40
    with pytest.raises(packet.PacketError, match="missing_git_object"):
        candidate["build"]()


def test_real_partial_clone_missing_blob_never_fetches(candidate):
    import shlex
    c = candidate
    origin = c["tmp"] / "origin.git"
    git(c["tmp"], "clone", "--bare", "-q", str(c["repo"]), str(origin))
    git(origin, "config", "uploadpack.allowFilter", "true")
    partial = c["tmp"] / "partial"
    git(c["tmp"], "clone", "-q", "--filter=blob:none", "--no-checkout", origin.as_uri(), str(partial))
    blob = git(c["repo"], "rev-parse", c["head"] + ":code.py")
    assert "?" + blob in git(partial, "rev-list", "--objects", "--missing=print", c["head"])
    marker = c["tmp"] / "upload-pack-called"
    helper = c["tmp"] / "upload-pack-observer"
    helper.write_text("#!/bin/sh\nprintf 'called\\n' >> " + shlex.quote(str(marker)) + "\nexec git-upload-pack \"$@\"\n")
    helper.chmod(0o755)
    git(partial, "config", "remote.origin.uploadpack", str(helper))
    def objects():
        root = partial / ".git/objects"
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    before = objects()
    with pytest.raises(packet.PacketError, match="missing_git_object"):
        packet.build_review_packet(c["roadmap"], c["state"], lambda _: partial, c["material_path"],
            _pr_metadata_fn=lambda *_: dict(c["live"]))
    assert not marker.exists() and objects() == before
    # Same repository and observer really do fetch for an ordinary Git read.
    assert "actual_changed_code" in git(partial, "show", c["head"] + ":code.py")
    assert marker.exists() and objects() != before


def test_replacement_refs_cannot_change_bound_packet(candidate):
    c = candidate
    expected = c["build"]().artifact
    original = git(c["repo"], "rev-parse", c["head"] + ":code.py")
    replacement = c["tmp"] / "replacement.txt"
    replacement.write_text("hostile replacement sentinel\n")
    fake = git(c["repo"], "hash-object", "-w", str(replacement))
    git(c["repo"], "replace", original, fake)
    assert "hostile replacement" in git(c["repo"], "show", c["head"] + ":code.py")
    assert c["build"]().artifact == expected


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
    output = c["tmp"] / "external-preview"
    output.mkdir()
    (output / "retained").write_bytes(b"operator data")
    receipt = packet.preview_review_packet(c["roadmap"], c["tmp"] / "ledger/train.ledger.jsonl", lambda n: c["repo"],
        c["material_path"], output, _pr_metadata_fn=never)
    assert not receipt["ready"] and "preview_output_nonempty" in receipt["errors"][0]
    assert list(output.iterdir()) == [output / "retained"]
    assert (output / "retained").read_bytes() == b"operator data"


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
        for record in c["state"].values():
            append_record(ledger, record)
    monkeypatch.setattr(packet, "read_pr_metadata", lambda ws, url: dict(c.get("lives", {}).get(url, c["live"])))
    options = dict(run_mode="governed", review_only=True, review_material=c["material_path"],
        resolve_workspace=lambda n: c.get("workspaces", {}).get(n.node_id, c["repo"]), _run_loop=never, _publish=never,
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
    from phase_loop_runtime.convergence.broker import live
    c = candidate
    train = c["tmp"] / "train.md"
    train.write_text("# Release Train: packet boundary\n\n## Nodes\n\n### Node: repo-a / CHANGELOG.md\n\n**Depends on:** (none)\n**Channel:** (none)\n")
    ledger = c["tmp"] / "ledger/train-train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    before = ledger.read_bytes()
    monkeypatch.setattr(packet, "read_pr_metadata", lambda *_: dict(c["live"]))
    monkeypatch.setattr(live, "fabpub_capability_active", never)
    monkeypatch.setattr(live, "fabpub_activation_barrier", never)
    monkeypatch.setattr(broker, "build_routing_broker_client", never)
    monkeypatch.setattr(train_runner, "run_train", never)
    args = ["run-train", "--train", str(train), "--governed", "--review-only", "--review-material", str(c["material_path"]),
            "--preview-review", str(c["tmp"] / "preview"), "--workspace", "repo-a=" + str(c["repo"]), "--ledger-dir", str(ledger.parent), "--json"]
    assert cli.main(args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["ready"] and receipt["model_calls"] == 0
    assert ledger.read_bytes() == before
    assert not (ledger.parent / "broker").exists()


@pytest.mark.parametrize("governed_review", [False, True])
@pytest.mark.parametrize("fabpub_active", [False, True])
def test_preview_output_cli_empty_argument_refuses_before_effects(candidate, monkeypatch, capsys, governed_review, fabpub_active):
    from phase_loop_runtime import cli, train_runner
    from phase_loop_runtime.convergence import broker
    from phase_loop_runtime.convergence.broker import live
    c = candidate
    train = c["tmp"] / "train.md"
    train.write_text("# Release Train: packet boundary\n\n## Nodes\n\n### Node: repo-a / CHANGELOG.md\n\n**Depends on:** (none)\n**Channel:** (none)\n")
    ledger = c["tmp"] / "ledger/train-train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    before = ledger.read_bytes()
    paths_before = sorted(str(p.relative_to(c["tmp"])) for p in c["tmp"].rglob("*"))
    monkeypatch.setattr(live, "fabpub_capability_active", lambda: fabpub_active)
    monkeypatch.setattr(live, "fabpub_activation_barrier", never)
    monkeypatch.setattr(broker, "build_routing_broker_client", never)
    monkeypatch.setattr(train_runner, "run_train", never)
    args = ["run-train", "--train", str(train), "--preview-review", "",
            "--workspace", "repo-a=" + str(c["repo"]), "--ledger-dir", str(ledger.parent), "--json"]
    if governed_review:
        args += ["--governed", "--review-only"]
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2
    assert "--preview-review requires a non-empty directory" in capsys.readouterr().err
    assert ledger.read_bytes() == before
    assert sorted(str(p.relative_to(c["tmp"])) for p in c["tmp"].rglob("*")) == paths_before
    assert not (ledger.parent / "broker").exists()


def test_preview_output_torn_ledger_is_not_repaired(candidate):
    c = candidate
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    ledger.write_bytes(ledger.read_bytes() + b'{"node_id":')
    before = ledger.read_bytes()
    receipt = packet.preview_review_packet(c["roadmap"], ledger, lambda n: c["repo"], c["material_path"], c["tmp"] / "preview", _pr_metadata_fn=never)
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
        nodes.append({"identity": {"node_id": node.node_id, "head_sha": record.head_sha, "pr_url": record.pr_url,
                                  "admission": packet.admission_binding(record)},
            "material": {"declaration_sha256": "0" * 64, "acceptance": [], "verification": []},
            "inventory": [], "inventory_sha256": "0" * 64, "changed_paths": 0,
            "git_version": "SYNTHETIC FLOW FIXTURE - NOT GIT EVIDENCE", "diff_argv": [], "inventory_argv": [],
            "certificates": [], "context": [], "patch": packet._text(b"synthetic flow fixture\n", "fixture")})
    metadata = {"schema_version": 1, "train": {"title": roadmap.title, "nodes": [asdict(n) for n in roadmap.nodes]},
                "nodes": nodes, "material_manifest_sha256": "0" * 64, "removals_sha256": packet._sha(packet._json([]).encode())}
    return packet.ReviewPacket(packet._render(metadata), metadata, [])


@pytest.fixture
def synthetic_train_packet(monkeypatch):
    """Legacy fake-SHA plumbing only: substitute packet snapshots and identity rechecks.

    This makes no workspace/store and supplies no Git/admission-binding evidence.
    Real packet, cache, revocation and readmission boundaries use unpatched tests.
    """
    monkeypatch.setattr(packet, "build_review_packet", synthetic_packet_for_flow_tests)
    monkeypatch.setattr(packet, "recheck_packet_identities", lambda *a, **k: None)
    def prepare(roadmap, state, *args, proposed_heads, **kwargs):
        built = synthetic_packet_for_flow_tests(roadmap, state, *args, **kwargs)
        for node in built.metadata["nodes"]:
            ident = node["identity"]
            ident["head_sha"] = proposed_heads.get(ident["node_id"], ident["head_sha"])
            ident["admission"]["head_sha"] = ident["head_sha"]
        return packet.PreparedReviewPacket(packet._render(built.metadata), built.metadata, [],
            {nid: packet.admission_binding(rec) for nid, rec in state.items()})
    monkeypatch.setattr(packet, "prepare_review_packet", prepare)


def prepare_synthetic_fab_workspaces(workspaces):
    """Explicit environment setup for legacy FAB plumbing, before run_train."""
    from phase_loop_runtime.convergence.broker.live import repository_broker_namespace
    for workspace in workspaces:
        workspace = Path(workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        if not (workspace / ".git").exists():
            git(workspace, "init", "-q")
        repository_broker_namespace(workspace).mkdir(parents=True, exist_ok=True)


def seed_synthetic_packet(ledger, roadmap):
    """Explicitly seed a historical packet for a synthetic resume test."""
    from dataclasses import replace
    state = read_ledger(ledger)
    built = synthetic_packet_for_flow_tests(roadmap, state)
    packet.store_review_packet(built, ledger.parent / "review-packets")
    approval = state.get("_train_review_")
    if approval is not None:
        append_record(ledger, replace(approval, review_packet_sha256=built.sha256))
    else:
        append_record(ledger, LedgerRecord("_train_review_", "approved", review_packet_sha256=built.sha256))


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
    assert result["status"] == "merge_halted" and result["reason"] == "observed_identity_drift"
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
    from phase_loop_runtime import governed_review as gr, panel_invoker as pi
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
        c["material_path"], link / "preview", _pr_metadata_fn=never)
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


@pytest.mark.parametrize("field", ["check_suite", "app", "repository", "status", "conclusion"])
def test_malformed_check_run_is_typed_hold(candidate, field):
    c = candidate
    check = {"id": 9, "head_sha": c["head"], "name": "test", "status": "completed", "conclusion": "success",
        "url": "https://api.github.com/repos/org/repo/check-runs/9", "app": {"id": 1, "slug": "actions"},
        "check_suite": {"id": 2, "repository": {"full_name": "org/repo"}}, "output": {"summary": "evidence"}}
    if field == "repository":
        check["check_suite"][field] = ["malformed"]
    else:
        check[field] = ["malformed"]
    c["material"]["nodes"][c["node"].node_id]["verification"] = [{"id": "ci", "kind": "github_check_run", "check_run_id": 9}]
    update_material(c)
    with pytest.raises(packet.PacketError):
        c["build"](_check_run_fn=lambda *_: check)


def test_malformed_attested_result_is_typed_hold(candidate):
    c = candidate
    c["material"]["nodes"][c["node"].node_id]["verification"][0]["result"] = []
    update_material(c)
    with pytest.raises(packet.PacketError):
        c["build"]()


def test_missing_workspace_precedes_pr_subprocess(candidate):
    c = candidate
    with pytest.raises(packet.PacketError, match="missing_workspace"):
        packet.build_review_packet(c["roadmap"], c["state"], lambda _: c["tmp"] / "absent", c["material_path"], _pr_metadata_fn=never)


@pytest.mark.parametrize("count", ["4", 4.0, True])
def test_cached_count_requires_exact_integer(candidate, monkeypatch, count):
    from dataclasses import replace
    c = candidate
    run_candidate(c, monkeypatch)
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    append_record(ledger, replace(read_ledger(ledger)["_train_review_"], usable_reviewers=count))
    seen = []
    def review(*args):
        seen.append(args)
        return approved(*args)
    assert run_candidate(c, monkeypatch, _train_review_fn=review)["status"] == "review_approved"
    assert len(seen) == 1


def test_native_request_cache_hit_emits_and_returns(candidate, monkeypatch):
    c = candidate
    run_candidate(c, monkeypatch)
    seen = []
    def emit(artifact, **kwargs):
        seen.append(artifact)
        return {"status": "native_fill_required"}
    result = run_candidate(c, monkeypatch, review_only=False, emit_native_request=True,
                           _emit_native_fill_request_fn=emit, _train_review_fn=never, _merge_pr_fn=never)
    assert result["status"] == "native_fill_required" and len(seen) == 1


@pytest.mark.parametrize("field,value", [("head_sha", "f" * 40), ("fab_run_id", "other-run"), ("branch", "other-branch")])
def test_durable_only_drift_during_review_refuses_approval(candidate, monkeypatch, field, value):
    from dataclasses import replace
    c = candidate
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    def review(*args):
        append_record(ledger, replace(read_ledger(ledger)[c["node"].node_id], **{field: value}))
        return approved(*args)
    result = run_candidate(c, monkeypatch, _train_review_fn=review)
    assert result["status"] == "review_halted", result
    assert "_train_review_" not in read_ledger(ledger)


def enable_fab(c, monkeypatch):
    from phase_loop_runtime.governed_premerge import FAB_PROMOTION_ENV
    from phase_loop_runtime.convergence.broker.live import repository_broker_namespace
    monkeypatch.setenv(FAB_PROMOTION_ENV, "1")
    c["state"][c["node"].node_id].fab_run_id = "packet-fab"
    c["state"][c["node"].node_id].merge_order = 3
    namespace = repository_broker_namespace(c["repo"])
    namespace.mkdir(parents=True, exist_ok=True)
    return namespace


def revoke(namespace):
    # A real durable store row: gates use production namespace derivation/replay.
    from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
    path = namespace / "evidence.jsonl"
    path.write_text(json.dumps({"idempotency_key": "packet-test-revoke", "state": "outcome_ambiguous_blocked", "evidence_reference": "test"}) + "\n")
    assert BrokerEvidenceStore(namespace).epoch_blocked


@pytest.mark.parametrize("mode", ["review", "native", "merge"])
@pytest.mark.parametrize("store", ["revoked", "malformed", "unreadable", "absent", "empty"])
def test_real_revocation_store_before_sink(candidate, monkeypatch, mode, store):
    from phase_loop_runtime import train_runner as tr
    c = candidate
    namespace = enable_fab(c, monkeypatch)
    if store == "revoked":
        revoke(namespace)
    elif store == "malformed":
        (namespace / "evidence.jsonl").write_text('{"broken": true}\n')
    elif store == "unreadable":
        (namespace / "evidence.jsonl").mkdir()
    elif store == "absent":
        namespace.rmdir()
    before = sorted(str(p) for p in namespace.rglob("*"))
    namespace_existed = namespace.exists()
    sinks = []
    def sink(name, result):
        def call(*args, **kwargs):
            sinks.append(name)
            return result(*args, **kwargs)
        return call
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", lambda *a, **k: None)
    result = run_candidate(c, monkeypatch, review_only=mode == "review", emit_native_request=mode == "native",
        _emit_native_fill_request_fn=sink("native", lambda *a, **k: {"status": "native_fill_required"}),
        _train_review_fn=sink("review", approved),
        _merge_pr_fn=sink("merge", lambda *a, **k: c["head"]))
    if store == "empty":
        assert result["status"] == {"review": "review_approved", "native": "native_fill_required", "merge": "merged"}[mode], result
    else:
        assert result["status"] in {"review_halted", "merge_halted"}, result
        assert "_train_review_" not in read_ledger(c["tmp"] / "ledger/train.ledger.jsonl")
        assert sinks == []
    assert sorted(str(p) for p in namespace.rglob("*")) == before
    assert namespace.exists() == namespace_existed


def test_live_read_failure_preserves_fab_binding_then_resume(candidate, monkeypatch):
    c = candidate
    namespace = enable_fab(c, monkeypatch)
    def failed(*_):
        raise OSError("transient live read")
    result = run_candidate(c, monkeypatch, _live_pr_head_sha_fn=failed)
    assert result["status"] == "blocked"
    rec = read_ledger(c["tmp"] / "ledger/train.ledger.jsonl")[c["node"].node_id]
    assert (rec.fab_run_id, rec.merge_order, rec.head_sha, rec.pr_url) == ("packet-fab", 3, c["head"], c["live"]["url"])
    assert run_candidate(c, monkeypatch)["status"] == "review_approved"
    revoke(namespace)
    assert run_candidate(c, monkeypatch, _train_review_fn=never)["reason"] == "readmission_revoked"


def test_complete_blocked_admission_accepted_incomplete_refused(candidate):
    c = candidate
    c["state"][c["node"].node_id].status = "blocked"
    assert "actual_changed_code" in c["build"]().artifact
    c["state"][c["node"].node_id].branch = None
    with pytest.raises(packet.PacketError, match="unadmitted_node"):
        c["build"]()


def test_prepared_snapshot_has_no_authority_and_promotes_identical_bytes(candidate, monkeypatch):
    from dataclasses import replace
    c = candidate
    prior = replace(c["state"][c["node"].node_id], head_sha=c["base"], fab_run_id="packet-fab")
    prepared = packet.prepare_review_packet(c["roadmap"], {prior.node_id: prior}, lambda _: c["repo"], c["material_path"],
        proposed_heads={prior.node_id: c["head"]}, _pr_metadata_fn=lambda *_: dict(c["live"]))
    with pytest.raises(packet.PacketError, match="unfinalized_packet"):
        packet.store_review_packet(prepared, c["tmp"] / "packets")
    assert not (c["tmp"] / "packets").exists()
    with pytest.raises(packet.PacketError, match="admission_identity_drift"):
        packet.finalize_review_packet(prepared, c["roadmap"], {prior.node_id: prior}, lambda _: c["repo"], _pr_metadata_fn=lambda *_: dict(c["live"]))
    monkeypatch.setattr(packet, "_read_relative", never)
    monkeypatch.setattr(packet, "_GitReader", never)
    finalized = packet.finalize_review_packet(prepared, c["roadmap"], {prior.node_id: replace(prior, head_sha=c["head"])}, lambda _: c["repo"], _pr_metadata_fn=lambda *_: dict(c["live"]))
    assert finalized.artifact == prepared.artifact and finalized.sha256 == prepared.sha256


def proposed_candidate(c):
    (c["repo"] / "code.py").write_text("prospective_delta = 3\n")
    head = commit(c["repo"], "delta")
    c["live"]["headRefOid"] = head
    raw = c["material"]["nodes"][c["node"].node_id]
    raw["head_sha"] = raw["verification"][0]["head_sha"] = head
    update_material(c)
    return head


def add_sibling(c):
    from dataclasses import replace
    second = TrainNode("repo-b", "NEXT.md")
    repo = c["tmp"] / "sibling"
    git(c["tmp"], "clone", "-q", str(c["repo"]), str(repo))
    rec = replace(c["state"][c["node"].node_id], node_id=second.node_id, pr_url="https://github.com/org/repo-b/pull/8")
    c["state"][second.node_id] = rec
    c["roadmap"].nodes.append(second)
    c["material"]["nodes"][second.node_id] = json.loads(json.dumps(c["material"]["nodes"][c["node"].node_id]))
    c["workspaces"] = {c["node"].node_id: c["repo"], second.node_id: repo}
    c["lives"] = {c["live"]["url"]: c["live"], rec.pr_url: {**c["live"], "url": rec.pr_url}}
    update_material(c)
    return second, repo


@pytest.mark.parametrize("failure", ["old_evidence", "missing_object", "binary", "oversized", "mixed_stale", "native_fill"])
def test_whole_train_material_barrier_precedes_all_fab_effects(candidate, monkeypatch, failure):
    from phase_loop_runtime import train_runner as tr
    c = candidate
    enable_fab(c, monkeypatch)
    second, repo = add_sibling(c)
    proposed_candidate(c)
    raw = c["material"]["nodes"][second.node_id]
    if failure == "old_evidence":
        c["material"]["nodes"][c["node"].node_id]["verification"][0]["head_sha"] = c["head"]
    elif failure == "missing_object":
        c["lives"][c["state"][second.node_id].pr_url]["baseRefOid"] = "f" * 40
    elif failure == "binary":
        (repo / "code.py").write_bytes(b"binary\x00value")
        head = commit(repo, "binary")
        c["state"][second.node_id].head_sha = head
        raw["head_sha"] = raw["verification"][0]["head_sha"] = head
        c["lives"][c["state"][second.node_id].pr_url]["headRefOid"] = head
    elif failure == "oversized":
        raw["acceptance"][0]["text"] = "x" * (600 * 1024)
    elif failure == "mixed_stale":
        c["state"][second.node_id].fab_run_id = None
        c["lives"][c["state"][second.node_id].pr_url]["headRefOid"] = "f" * 40
    update_material(c)
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    for row in c["state"].values():
        append_record(ledger, row)
    before = ledger.read_bytes(), git(c["repo"], "rev-parse", "HEAD"), git(c["repo"], "status", "--porcelain"), (c["repo"] / "code.py").read_bytes()
    effects = []
    def effect(*args, **kwargs):
        effects.append("called")
        raise AssertionError("material barrier permitted an effect")
    for name in ("_train_revocation_store", "_fab_recover_torn_to_admitted", "_fab_delta_readmit"):
        monkeypatch.setattr(tr, name, effect)
    result = run_candidate(c, monkeypatch, review_only=False, fab_delta_shortcut=True, _train_review_fn=never,
        native_leg_fills=[object()] if failure == "native_fill" else None,
        _live_pr_head_sha_fn=lambda ws, br: c["live"]["headRefOid"] if ws == c["repo"] else c["lives"][c["state"][second.node_id].pr_url]["headRefOid"])
    assert result["status"] == "review_halted", result
    assert result["reason"] == {"old_evidence": "unbound_verification", "missing_object": "missing_git_object",
        "binary": "binary_source", "oversized": "brokered review input exceeds sealed transport bound",
        "mixed_stale": "stale_head", "native_fill": "native_fill_stale_request"}[failure], result
    assert effects == []
    assert before == (ledger.read_bytes(), git(c["repo"], "rev-parse", "HEAD"), git(c["repo"], "status", "--porcelain"), (c["repo"] / "code.py").read_bytes())


@pytest.mark.parametrize("failure", ["none", "fake", "before_append", "after_append"])
def test_readmission_result_never_substitutes_for_durable_authority(candidate, monkeypatch, failure):
    from dataclasses import replace
    from phase_loop_runtime import train_runner as tr
    c = candidate
    enable_fab(c, monkeypatch)
    head = proposed_candidate(c)
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", lambda *a, **k: None)
    def readmit(ws, ledger, **kwargs):
        # Explicit injected failure seam; real broker grant/routing has separate controls.
        assert kwargs["evidence_store"].root.is_dir()
        if failure == "after_append":
            append_record(ledger, replace(read_ledger(ledger)[c["node"].node_id], head_sha=head))
        if failure.endswith("append"):
            raise RuntimeError("crash seam")
        return head if failure == "fake" else None
    monkeypatch.setattr(tr, "_fab_delta_readmit", readmit)
    result = run_candidate(c, monkeypatch, review_only=False, fab_delta_shortcut=True, _train_review_fn=never)
    assert result["status"] == "merge_halted", result
    rec = read_ledger(c["tmp"] / "ledger/train.ledger.jsonl")[c["node"].node_id]
    assert rec.head_sha == (head if failure == "after_append" else c["head"])
    assert rec.fab_run_id == "packet-fab" and rec.merge_order == 3
    if failure == "after_append":
        monkeypatch.setattr(tr, "_fab_delta_readmit", never)
        assert run_candidate(c, monkeypatch)["status"] == "review_approved"


@pytest.mark.parametrize("boundary", ["finalize_identity", "post_finalize_revocation"])
def test_readmitted_head_finalization_refusal_reports_prior_effects(candidate, monkeypatch, boundary):
    from dataclasses import replace
    from phase_loop_runtime import train_runner as tr
    c = candidate
    namespace = enable_fab(c, monkeypatch)
    head = proposed_candidate(c)
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    appended = []
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", lambda *a, **k: None)
    def readmit(ws, path, **kwargs):
        # Inject only successful admission; finalization/store replay remain real.
        assert kwargs["evidence_store"].root == namespace
        append_record(path, replace(read_ledger(path)[c["node"].node_id], head_sha=head), durable=True)
        appended.append(path.read_bytes())
        if boundary == "finalize_identity":
            c["live"]["baseRefOid"] = head
        else:
            revoke(namespace)
        return head
    monkeypatch.setattr(tr, "_fab_delta_readmit", readmit)
    result = run_candidate(c, monkeypatch, review_only=False, fab_delta_shortcut=True,
        _train_review_fn=never, _merge_pr_fn=never)
    state = read_ledger(ledger)
    rec = state[c["node"].node_id]
    assert packet.admission_binding(rec) == packet.admission_binding(
        replace(c["state"][c["node"].node_id], head_sha=head))
    assert rec.status == "pr_open" and rec.merge_order == 3
    assert ledger.read_bytes() == appended[0] and "_train_review_" not in state
    assert result["reason"] == {"finalize_identity": "observed_identity_drift",
        "post_finalize_revocation": "readmission_revoked"}[boundary]
    assert result["status"] == "merge_halted", result


def test_whole_train_valid_material_reaches_every_effect(candidate, monkeypatch):
    """Positive barrier control; admission append is an explicit injected seam."""
    from dataclasses import replace
    from phase_loop_runtime import train_runner as tr
    from phase_loop_runtime.convergence.broker.live import repository_broker_namespace
    c = candidate
    enable_fab(c, monkeypatch)
    second, repo = add_sibling(c)
    repository_broker_namespace(repo).mkdir(parents=True, exist_ok=True)
    head = proposed_candidate(c)
    effects = []
    def recover(ws, *args, **kwargs):
        effects.append(("recover", ws))
    def readmit(ws, ledger, **kwargs):
        effects.append(("readmit", ws))
        append_record(ledger, replace(read_ledger(ledger)[c["node"].node_id], head_sha=head))
        return head
    def review(*args, **kwargs):
        effects.append(("review", None))
        return approved(*args, **kwargs)
    def merge(ws, *args, **kwargs):
        effects.append(("merge", ws))
        return kwargs["head_sha"]
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", recover)
    monkeypatch.setattr(tr, "_fab_delta_readmit", readmit)
    result = run_candidate(c, monkeypatch, review_only=False, fab_delta_shortcut=True,
        _train_review_fn=review, _merge_pr_fn=merge,
        _live_pr_head_sha_fn=lambda ws, br: head if ws == c["repo"] else c["head"])
    assert result["status"] == "merged", result
    assert ("readmit", c["repo"]) in effects and ("review", None) in effects
    assert {ws for effect, ws in effects if effect == "recover"} == {c["repo"], repo}
    assert [ws for effect, ws in effects if effect == "merge"] == [c["repo"], repo]


def test_revoke_after_recovery_reaches_real_helper_entry_before_delta(candidate, monkeypatch):
    from phase_loop_runtime import train_runner as tr
    c = candidate
    namespace = enable_fab(c, monkeypatch)
    proposed_candidate(c)
    git_effects = []
    real_run = tr.subprocess.run
    def checked_run(argv, *args, **kwargs):
        if argv[0] == "git" and any(command in argv for command in ("fetch", "rev-list")):
            git_effects.append(argv)
            raise AssertionError("Git effect reached after recovery revocation")
        return real_run(argv, *args, **kwargs)
    monkeypatch.setattr(tr.subprocess, "run", checked_run)
    after_recovery = []
    def recover(*a, **k):
        revoke(namespace)
        after_recovery.append((c["repo"] / "code.py").read_bytes())
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", recover)
    monkeypatch.setattr(tr, "_scope_run_to_admitted_prefix", never)
    monkeypatch.setattr(tr, "_commit_broker_readmitted_head", never)
    result = run_candidate(c, monkeypatch, review_only=False, fab_delta_shortcut=True, _delta_review_fn=never, _train_review_fn=never)
    assert result["status"] == "merge_halted", result
    assert after_recovery == [(c["repo"] / "code.py").read_bytes()]
    assert git_effects == []


def test_revoke_sibling_after_barrier_before_its_recovery(candidate, monkeypatch):
    from phase_loop_runtime import train_runner as tr
    from phase_loop_runtime.convergence.broker.live import repository_broker_namespace
    c = candidate
    enable_fab(c, monkeypatch)
    second, repo = add_sibling(c)
    namespace = repository_broker_namespace(repo)
    namespace.mkdir(parents=True, exist_ok=True)
    seen = []
    before = git(repo, "rev-parse", "HEAD")
    def recover(ws, *a, **k):
        seen.append(ws)
        revoke(namespace)
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", recover)
    result = run_candidate(c, monkeypatch, review_only=False, _train_review_fn=never)
    assert result["reason"] == "readmission_revoked", result
    assert seen == [c["repo"]] and git(repo, "rev-parse", "HEAD") == before


def test_approval_mapping_preserves_every_admission(candidate, monkeypatch):
    c = candidate
    enable_fab(c, monkeypatch)
    before = packet.admission_binding(c["state"][c["node"].node_id])
    assert run_candidate(c, monkeypatch)["status"] == "review_approved"
    state = read_ledger(c["tmp"] / "ledger/train.ledger.jsonl")
    assert packet.admission_binding(state[c["node"].node_id]) == before
    assert state["_train_review_"].fab_run_id is None


def real_fab_packet_inputs(fixture, seeded, roadmap, monkeypatch, ws_map=None):
    """Real Git/material fixture for broker controls; only GitHub reads injected."""
    from dataclasses import replace
    state = read_ledger(seeded["ledger_path"])
    ws_map = ws_map or {n.node_id: fixture.repo for n in roadmap.nodes}
    root = seeded["ledger_path"].parent
    evidence = dump(root / "packet-evidence.json", {"attribution": "test fixture execution only"})
    material = {"schema_version": 1, "nodes": {}}
    live = {}
    for node in roadmap.nodes:
        ws = ws_map[node.node_id]
        if ws != fixture.repo and not (ws / ".git").exists():
            git(root, "clone", "-q", str(fixture.repo), str(ws))
        rec = state.get(node.node_id)
        existed = rec is not None
        if rec is None:
            rec = LedgerRecord(node.node_id, "pr_open", branch="feat/repo-b", head_sha=seeded["candidate_head"])
        url = f"https://github.com/org/{node.repo}/pull/1"
        if rec.pr_url != url:
            rec = replace(rec, pr_url=url)
            if existed:
                append_record(seeded["ledger_path"], rec)
        head = seeded["delta_head"] if node.node_id == seeded["node_id"] else rec.head_sha
        live[url] = {"url": url, "state": "OPEN", "baseRefName": "main", "baseRefOid": seeded["base"], "headRefOid": head}
        material["nodes"][node.node_id] = {"head_sha": head,
            "acceptance": [{"id": "scope", "text": "Complete candidate and delta content", "provenance": evidence}],
            "verification": [{"id": "fixture", "kind": "attested_command", "head_sha": head,
                "argv": ["fixture"], "exit_code": 0, "result": "passed", "attested_by": "test fixture",
                "observed_at": "2026-09-22T00:00:00Z", "evidence": evidence}]}
    path = root / "packet-material.json"
    dump(path, material)
    monkeypatch.setattr(packet, "read_pr_metadata", lambda ws, url: dict(live[url]))
    return path


@pytest.mark.parametrize("crash", ["exception_after_append", "exit_after_append", "exit_before_append"])
def test_real_broker_crash_seams_resume_exact_durable_binding(tmp_path, monkeypatch, crash):
    from phase_loop_runtime import train_runner as tr
    from phase_loop_runtime.governed_premerge import FAB_PROMOTION_ENV
    from test_fab_delta_consumer import DeltaReadmitTransactionTest, _seed_fabreadmit_two_node_resume, _run_fabreadmit_two_node_resume
    fixture = DeltaReadmitTransactionTest()
    fixture.tmp_path = tmp_path
    fixture.setUp()
    try:
        seeded = fixture._setup_broker_readmit_candidate(node_id="repo-a/specs/plan-a.md", branch="feat/repo-a")
        _seed_fabreadmit_two_node_resume(seeded["ledger_path"], seeded["candidate_head"])
        monkeypatch.setenv(FAB_PROMOTION_ENV, "1")
        real_append = tr.append_record
        reviews = []
        real_review = fixture._review_fn
        def review(*a, **k):
            reviews.append(1)
            return real_review(*a, **k)
        fixture._review_fn = review
        def interrupt(path, record, **kwargs):
            if record.status == "pr_open" and record.head_sha == seeded["delta_head"]:
                if crash != "exit_before_append":
                    real_append(path, record, **kwargs)
                if crash == "exception_after_append":
                    raise OSError("after durable append")
                raise SystemExit("durable crash seam")
            return real_append(path, record, **kwargs)
        with monkeypatch.context() as seam:
            seam.setattr(tr, "append_record", interrupt)
            if crash == "exception_after_append":
                result = _run_fabreadmit_two_node_resume(tr, fixture, seeded, live_head_sha=seeded["delta_head"], captured={})
                assert result["reason"] == "fab_readmit_failed"
            else:
                with pytest.raises(SystemExit, match="durable crash seam"):
                    _run_fabreadmit_two_node_resume(tr, fixture, seeded, live_head_sha=seeded["delta_head"], captured={})
        durable = read_ledger(seeded["ledger_path"])[seeded["node_id"]]
        assert durable.fab_run_id == fixture.RUN and durable.merge_order == 0
        assert durable.head_sha == seeded["candidate_head" if crash == "exit_before_append" else "delta_head"]
        admissions = seeded["store"].replay()
        assert len(admissions) == 2 and admissions[-1].epoch == 2
        authority_digest = admissions[-1].binding.authority_digest
        captured = {}
        result = _run_fabreadmit_two_node_resume(tr, fixture, seeded, live_head_sha=seeded["delta_head"], captured=captured)
        assert result["status"] == "merged", result
        assert captured[seeded["node_id"]] == [{"branch": seeded["branch"],
            "head_sha": seeded["delta_head"], "run_id": fixture.RUN}]
        assert read_ledger(seeded["ledger_path"])[seeded["node_id"]].head_sha == seeded["delta_head"]
        assert len(reviews) == (2 if crash == "exit_before_append" else 1)
        assert len(seeded["store"].replay()) == 2
        assert seeded["store"].replay()[-1].binding.authority_digest == authority_digest
    finally:
        fixture.tearDown()


@pytest.mark.parametrize("sink", ["review", "cache", "native"])
def test_revocation_after_packet_storage_precedes_sink(candidate, monkeypatch, sink):
    c = candidate
    namespace = enable_fab(c, monkeypatch)
    if sink == "cache":
        assert run_candidate(c, monkeypatch)["status"] == "review_approved"
    store = packet.store_review_packet
    def mutate(*a, **k):
        result = store(*a, **k)
        revoke(namespace)
        return result
    monkeypatch.setattr(packet, "store_review_packet", mutate)
    result = run_candidate(c, monkeypatch, emit_native_request=sink == "native",
        _emit_native_fill_request_fn=never, _train_review_fn=never)
    assert result["status"] == "review_halted" and result["reason"] == "readmission_revoked", result


@pytest.mark.parametrize("checkpoint", ["post_storage", "post_review"])
@pytest.mark.parametrize("prior_effects", [False, True])
def test_later_packet_refusal_preserves_admission_effect_status(candidate, monkeypatch, checkpoint, prior_effects):
    from dataclasses import replace
    from phase_loop_runtime import train_runner as tr
    c = candidate
    namespace = enable_fab(c, monkeypatch)
    head = proposed_candidate(c) if prior_effects else c["head"]
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    for row in c["state"].values():
        append_record(ledger, row)
    before = ledger.read_bytes()
    effects, appended = [], []
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", lambda *a, **k: effects.append("recover"))
    def readmit(ws, path, **kwargs):
        # Inject admission success; append, packet checks and store replay stay real.
        assert kwargs["evidence_store"].root == namespace
        append_record(path, replace(read_ledger(path)[c["node"].node_id], head_sha=head), durable=True)
        appended.append(path.read_bytes())
        effects.append("durable_append")
        return head
    monkeypatch.setattr(tr, "_fab_delta_readmit", readmit)
    real_store = packet.store_review_packet
    def store(*args, **kwargs):
        result = real_store(*args, **kwargs)
        effects.append("storage")
        if checkpoint == "post_storage":
            revoke(namespace)
        return result
    monkeypatch.setattr(packet, "store_review_packet", store)
    def review(*args):
        assert checkpoint == "post_review"
        effects.append("injected_review")
        revoke(namespace)
        return approved(*args)
    result = run_candidate(c, monkeypatch, review_only=not prior_effects, fab_delta_shortcut=True,
        _train_review_fn=review if checkpoint == "post_review" else never,
        _merge_pr_fn=never, _emit_native_fill_request_fn=never)
    state = read_ledger(ledger)
    rec = state[c["node"].node_id]
    assert packet.admission_binding(rec) == packet.admission_binding(
        replace(c["state"][c["node"].node_id], head_sha=head))
    assert rec.status == "pr_open" and rec.merge_order == 3 and "_train_review_" not in state
    expected = (["recover", "durable_append"] if prior_effects else []) + ["storage"]
    if checkpoint == "post_review":
        expected.append("injected_review")
    assert effects == expected
    assert ledger.read_bytes() == (appended[0] if prior_effects else before)
    assert result["reason"] == "readmission_revoked", result
    assert result["status"] == ("merge_halted" if prior_effects else "review_halted"), result


def test_durable_only_drift_between_merges_holds_remaining_node(candidate, monkeypatch):
    from dataclasses import replace
    c = candidate
    second, _ = add_sibling(c)
    seen = []
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    def merge(ws, branch, **kwargs):
        seen.append(ws)
        append_record(ledger, replace(read_ledger(ledger)[second.node_id], branch="rebound"))
        return c["head"]
    result = run_candidate(c, monkeypatch, review_only=False, _merge_pr_fn=merge)
    assert result["status"] == "merge_halted" and result["reason"] == "admission_identity_drift", result
    assert seen == [c["repo"]], result
    assert read_ledger(ledger)[c["node"].node_id].status == "merged"


def test_later_readmission_failure_preserves_earlier_durable_binding(candidate, monkeypatch):
    from dataclasses import replace
    from phase_loop_runtime import train_runner as tr
    from phase_loop_runtime.convergence.broker.live import repository_broker_namespace
    c = candidate
    enable_fab(c, monkeypatch)
    second, repo = add_sibling(c)
    repository_broker_namespace(repo).mkdir(parents=True, exist_ok=True)
    first_head = proposed_candidate(c)
    (repo / "code.py").write_text("second delta\n")
    second_head = commit(repo, "second delta")
    raw = c["material"]["nodes"][second.node_id]
    raw["head_sha"] = raw["verification"][0]["head_sha"] = second_head
    c["lives"][c["state"][second.node_id].pr_url]["headRefOid"] = second_head
    update_material(c)
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", lambda *a, **k: None)
    seen = []
    def readmit(ws, ledger, **kwargs):
        # Inject only the admission outcome for this partial-failure boundary.
        # Real routing/grant authority is exercised by the controls above.
        seen.append(kwargs["node_id"])
        if kwargs["node_id"] == second.node_id:
            return None
        append_record(ledger, replace(read_ledger(ledger)[kwargs["node_id"]], head_sha=first_head))
        return first_head
    monkeypatch.setattr(tr, "_fab_delta_readmit", readmit)
    result = run_candidate(c, monkeypatch, review_only=False, fab_delta_shortcut=True, _train_review_fn=never,
        _live_pr_head_sha_fn=lambda ws, br: first_head if ws == c["repo"] else second_head)
    assert result["reason"] == "readmission_refused" and seen == [c["node"].node_id, second.node_id], result
    state = read_ledger(c["tmp"] / "ledger/train.ledger.jsonl")
    assert state[c["node"].node_id].head_sha == first_head
    assert state[second.node_id].head_sha == c["head"]
    assert "_train_review_" not in state


def test_external_merge_recovery_preserves_historical_fab_identity(candidate, monkeypatch):
    from phase_loop_runtime import train_runner as tr
    c = candidate
    enable_fab(c, monkeypatch)
    assert run_candidate(c, monkeypatch)["status"] == "review_approved"
    c["live"].update(state="MERGED", mergeCommit={"oid": c["head"]})
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", never)
    result = run_candidate(c, monkeypatch, review_only=False, _pr_is_open=lambda *_: False,
        _pr_merged_sha_fn=lambda *a, **k: c["head"], _train_review_fn=never)
    assert result["status"] == "merged", result
    assert read_ledger(c["tmp"] / "ledger/train.ledger.jsonl")[c["node"].node_id].fab_run_id == "packet-fab"


@pytest.mark.parametrize("target", ["node", "ledger"])
def test_preview_output_dotdot_cannot_enter_forbidden_directory(candidate, target):
    c = candidate
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    (c["tmp"] / "outside").mkdir()
    output = c["tmp"] / "outside" / ".." / target / "preview-output"
    before = ledger.read_bytes(), git(c["repo"], "status", "--porcelain")
    receipt = packet.preview_review_packet(c["roadmap"], ledger, lambda _: c["repo"],
        c["material_path"], output, _pr_metadata_fn=lambda *_: dict(c["live"]))
    assert not receipt["ready"] and "preview_output_forbidden" in receipt["errors"][0]
    assert not output.exists()
    assert before == (ledger.read_bytes(), git(c["repo"], "status", "--porcelain"))


def seed_partial_history(c):
    second, workspace = add_sibling(c)
    historical = packet.build_review_packet(c["roadmap"], c["state"], lambda n: c["workspaces"][n.node_id],
        c["material_path"], _pr_metadata_fn=lambda ws, url: dict(c["lives"][url]))
    record = c["state"][c["node"].node_id]
    record.status = "merged"
    record.upstream_merge_sha = c["head"]
    c["live"].update(state="MERGED", mergeCommit={"oid": c["head"]})
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    for row in c["state"].values():
        append_record(ledger, row)
    packet.store_review_packet(historical, ledger.parent / "review-packets")
    append_record(ledger, LedgerRecord("_train_review_", "approved", usable_reviewers=4,
                                      review_packet_sha256=historical.sha256))
    return second, workspace, ledger


@pytest.mark.parametrize("field", ["branch", "fab_run_id"])
def test_historical_full_binding_refused_before_pending_effects(candidate, monkeypatch, field):
    from dataclasses import replace
    from phase_loop_runtime import train_runner as tr
    from phase_loop_runtime.convergence.broker.live import repository_broker_namespace
    c = candidate
    enable_fab(c, monkeypatch)
    _, workspace, ledger = seed_partial_history(c)
    repository_broker_namespace(workspace).mkdir(parents=True, exist_ok=True)
    append_record(ledger, replace(read_ledger(ledger)[c["node"].node_id], **{field: "changed-binding"}))
    before = ledger.read_bytes()
    effects = []
    def effect(*args, **kwargs):
        effects.append("called")
        raise AssertionError("historical binding must fail before effects")
    monkeypatch.setattr(tr, "_train_revocation_store", effect)
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", effect)
    monkeypatch.setattr(tr, "_fab_delta_readmit", effect)
    result = run_candidate(c, monkeypatch, review_only=False, _train_review_fn=effect, _merge_pr_fn=effect)
    assert result["reason"] == "historical_packet_identity_mismatch", result
    assert effects == [] and ledger.read_bytes() == before


@pytest.mark.parametrize("flip_at", ["prepared", "recovery_store"])
def test_proposed_readiness_reversal_precedes_recovery(candidate, monkeypatch, flip_at):
    from phase_loop_runtime import train_runner as tr, governed_premerge as gp
    c = candidate
    enable_fab(c, monkeypatch)
    proposed_candidate(c)
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    before = ledger.read_bytes()
    prepare, store = packet.prepare_review_packet, tr._train_revocation_store
    calls, reads = [], []
    def prepared(*args, **kwargs):
        result = prepare(*args, **kwargs)
        if flip_at == "prepared":
            monkeypatch.setattr(gp, "_FAB_DELTA_BROKER_READMIT_READY", False)
        return result
    def resolved(*args, **kwargs):
        result = store(*args, **kwargs)
        reads.append(1)
        if flip_at == "recovery_store" and len(reads) == 2:
            monkeypatch.setattr(gp, "_FAB_DELTA_BROKER_READMIT_READY", False)
        return result
    monkeypatch.setattr(packet, "prepare_review_packet", prepared)
    monkeypatch.setattr(tr, "_train_revocation_store", resolved)
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", lambda *a, **k: calls.append("recovery"))
    monkeypatch.setattr(tr, "_fab_delta_readmit", lambda *a, **k: calls.append("readmission"))
    result = run_candidate(c, monkeypatch, review_only=False, fab_delta_shortcut=True,
        _train_review_fn=never, _merge_pr_fn=never)
    assert result["reason"] == "stale_head", result
    assert calls == [] and ledger.read_bytes() == before


@pytest.mark.parametrize("locus", ["check_suite", "root"])
@pytest.mark.parametrize("value", [[], "", False, None, 0])
def test_malformed_falsey_check_repository_is_refused(candidate, locus, value):
    c = candidate
    check = {"id": 1, "head_sha": c["head"], "name": "test", "status": "completed", "conclusion": "success",
        "url": "https://api.github.com/repos/org/repo/check-runs/1", "app": {"id": 1, "slug": "actions"},
        "check_suite": {"id": 2}, "output": {"summary": "evidence"}}
    (check["check_suite"] if locus == "check_suite" else check)["repository"] = value
    c["material"]["nodes"][c["node"].node_id]["verification"] = [{"id": "ci", "kind": "github_check_run", "check_run_id": 1}]
    update_material(c)
    with pytest.raises(packet.PacketError, match="malformed_check_run"):
        c["build"](_check_run_fn=lambda *_: check)


def test_check_response_bool_id_is_not_integer_identity(candidate):
    c = candidate
    check = {"id": True, "head_sha": c["head"], "name": "test", "status": "completed", "conclusion": "success",
        "url": "https://api.github.com/repos/org/repo/check-runs/1", "app": {"id": 1, "slug": "actions"},
        "check_suite": {"id": 2}, "output": {"summary": "evidence"}}
    c["material"]["nodes"][c["node"].node_id]["verification"] = [{"id": "ci", "kind": "github_check_run", "check_run_id": 1}]
    update_material(c)
    with pytest.raises(packet.PacketError, match="check_run_identity_mismatch"):
        c["build"](_check_run_fn=lambda *_: check)


def test_missing_historical_binding_during_review_is_typed_hold(candidate, monkeypatch):
    c = candidate
    second, _, ledger = seed_partial_history(c)
    c["material"]["nodes"][second.node_id]["acceptance"][0]["text"] += " amended pending scope"
    update_material(c)
    def review(*args):
        # Simulated corruption of the external durable ledger, not an append-only transition.
        lines = [line for line in ledger.read_text().splitlines()
                 if json.loads(line)["node_id"] != c["node"].node_id]
        ledger.write_text("\n".join(lines) + "\n")
        return approved(*args)
    result = run_candidate(c, monkeypatch, _train_review_fn=review)
    assert result["status"] == "review_halted" and result["reason"] == "admission_identity_drift", result


def test_admitted_pin_survives_live_change_after_final_recheck(candidate, monkeypatch):
    c = candidate
    recheck = packet.recheck_packet_identities
    def advance(*args, **kwargs):
        result = recheck(*args, **kwargs)
        if kwargs.get("node_ids") and "prior_bindings" not in kwargs:
            c["live"]["headRefOid"] = "f" * 40
        return result
    monkeypatch.setattr(packet, "recheck_packet_identities", advance)
    calls = []
    def merge(ws, branch, *, base, head_sha):
        calls.append(head_sha)
        assert head_sha == c["head"] != c["live"]["headRefOid"]
        return c["head"]
    assert run_candidate(c, monkeypatch, review_only=False, _merge_pr_fn=merge)["status"] == "merged"
    assert calls == [c["head"]]


@pytest.mark.parametrize("transition", ["file_to_directory", "directory_to_file", "file_to_symlink", "symlink_to_file"])
def test_complete_patch_type_transitions(candidate, transition):
    c = candidate
    path = c["repo"] / "code.py"
    if transition.startswith("directory_"):
        path.unlink()
        path.mkdir()
        (path / "nested.py").write_text("before_child = 3\n")
        c["base"] = c["live"]["baseRefOid"] = commit(c["repo"], "directory base")
        (path / "nested.py").unlink()
        path.rmdir()
        path.write_text("after_file = 4\n")
    elif transition.startswith("symlink_"):
        path.unlink()
        path.symlink_to("renamed.py")
        c["base"] = c["live"]["baseRefOid"] = commit(c["repo"], "symlink base")
        path.unlink()
        path.write_text("after_file = 4\n")
    elif transition.endswith("directory"):
        path.unlink()
        path.mkdir()
        (path / "nested.py").write_text("after_child = 3\n")
    else:
        path.unlink()
        path.symlink_to("renamed.py")
    head = commit(c["repo"], transition)
    c["state"][c["node"].node_id].head_sha = c["live"]["headRefOid"] = head
    raw = c["material"]["nodes"][c["node"].node_id]
    raw["head_sha"] = raw["verification"][0]["head_sha"] = head
    update_material(c)
    built = c["build"]()
    expected = subprocess.run(["git", "-C", str(c["repo"]), "diff-tree", "--no-commit-id", "-r", "-p",
        *packet._DIFF, c["base"], head], capture_output=True, check=True).stdout
    section = built.metadata["nodes"][0]["patch"]
    assert section["raw_sha256"] == hashlib.sha256(expected).hexdigest()
    assert section["raw_bytes"] == len(expected)
    assert section["text"] == packet.escape_text(expected.decode())
    if "symlink" in transition:
        assert "120000" in section["text"]


@pytest.mark.parametrize("supplementary", ["", "\U000e0001\U000e0020 literal\\U000e0001"])
def test_layered_material_context_certificate_roundtrip(candidate, supplementary):
    import re
    c = candidate
    raw = ('line one\n\t"quoted" literal\\r café\x01\r\u2028end' + supplementary).encode()
    (c["repo"] / "context.txt").write_bytes(raw)
    commit(c["repo"], "selected context")
    certify(c)
    material = c["material"]["nodes"][c["node"].node_id]
    material["context"] = ["context.txt"]
    for name, target in (("acceptance.txt", material["acceptance"][0]["provenance"]),
                         ("evidence.txt", material["verification"][0]["evidence"])):
        (c["tmp"] / name).write_bytes(raw)
        target["sha256"] = hashlib.sha256(raw).hexdigest()
    attestation_path = c["tmp"] / "disposal.json"
    attestation = json.loads(attestation_path.read_text())
    attestation["disposal_scope"] = raw.decode()
    attestation_raw = json.dumps(attestation, ensure_ascii=False, indent="\t").encode()
    attestation_path.write_bytes(attestation_raw)
    material["generated_removals"][0]["attestation"]["sha256"] = hashlib.sha256(attestation_raw).hexdigest()
    update_material(c)
    built = c["build"]()
    assert "JSON sections: decode outer escapes, parse JSON, then decode nested content.text escapes" in built.artifact
    assert "escaped_sha256 hashes intermediate escaped text" in built.artifact
    def unescape(text):
        # Independent lexer for the declared grammar, including non-JSON \U escapes.
        def token(match):
            value = match.group()
            return chr(int(value[2:], 16)) if value[1] in "uU" else {"\\\\": "\\", "\\r": "\r"}[value]
        return re.sub(r"\\(?:\\|r|u[0-9a-f]{4}|U[0-9a-f]{8})", token, text)
    def section(title):
        rendered = built.artifact.split("### " + title + "\n", 1)[1].split("\n### ", 1)[0].rstrip("\n")
        return json.loads(unescape(rendered))
    evidence = section("Acceptance and evidence")
    context = section("Selected head context")
    certificate = section("Explicit subtree disposal certificates")
    samples = [(evidence["acceptance"][0]["provenance"]["content"], raw),
               (evidence["verification"][0]["evidence"]["content"], raw),
               (context[0]["content"], raw),
               (certificate[0]["attestation"]["content"], attestation_raw)]
    for content, expected in samples:
        assert unescape(content["text"]).encode() == expected
        assert content["raw_sha256"] == hashlib.sha256(expected).hexdigest()
        assert content["escaped_sha256"] == hashlib.sha256(content["text"].encode()).hexdigest()
    assert certificate[0]["assertion"]["disposal_scope"] == raw.decode()
    if supplementary:
        assert "\\U000e0001" in context[0]["content"]["text"]
        assert "\\U000e0020" in built.metadata["nodes"][0]["patch"]["text"]


@pytest.mark.parametrize("mutation,reason", [("old_mode", "mode"), ("new_mode", "mode"), ("index", "object"), ("header", None)])
def test_type_transition_patch_must_match_inventory(candidate, monkeypatch, mutation, reason):
    c = candidate
    path = c["repo"] / "code.py"
    path.unlink()
    path.symlink_to("renamed.py")
    head = commit(c["repo"], "symlink transition")
    c["state"][c["node"].node_id].head_sha = c["live"]["headRefOid"] = head
    raw = c["material"]["nodes"][c["node"].node_id]
    raw["head_sha"] = raw["verification"][0]["head_sha"] = head
    update_material(c)
    original = packet._GitReader.patch
    def corrupt(self, base, head, paths):
        patch_bytes = original(self, base, head, paths)
        if paths == ["code.py"]:
            if mutation == "old_mode":
                patch_bytes = patch_bytes.replace(b"deleted file mode 100644", b"deleted file mode 100755")
            elif mutation == "new_mode":
                patch_bytes = patch_bytes.replace(b"new file mode 120000", b"new file mode 100644")
            elif mutation == "index":
                patch_bytes = patch_bytes.replace(b"index ", b"index f", 1)
            else:
                patch_bytes = patch_bytes.replace(b"diff --git a/code.py b/code.py", b"diff --git a/alien b/alien", 1)
        return patch_bytes
    monkeypatch.setattr(packet._GitReader, "patch", corrupt)
    with pytest.raises(packet.PacketError, match="patch_inventory_" + (reason + "_" if reason else "") + "mismatch"):
        c["build"]()


@pytest.mark.parametrize("mode", ["review", "native"])
def test_proposed_head_readonly_modes_have_zero_admission_effects(candidate, monkeypatch, mode):
    from phase_loop_runtime import train_runner as tr
    c = candidate
    enable_fab(c, monkeypatch)
    proposed_candidate(c)
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    for row in c["state"].values():
        append_record(ledger, row)
    before = ledger.read_bytes(), git(c["repo"], "rev-parse", "HEAD"), git(c["repo"], "status", "--porcelain")
    effects = []
    def effect(*args, **kwargs):
        effects.append("called")
        raise AssertionError("readonly proposed head permitted an effect")
    for name in ("_train_revocation_store", "_fab_recover_torn_to_admitted", "_fab_delta_readmit"):
        monkeypatch.setattr(tr, name, effect)
    result = run_candidate(c, monkeypatch, review_only=mode == "review", emit_native_request=mode == "native",
        fab_delta_shortcut=True, _train_review_fn=effect, _emit_native_fill_request_fn=effect, _merge_pr_fn=effect)
    assert result["status"] == "review_halted" and result["reason"] == "stale_head", result
    assert effects == []
    assert before == (ledger.read_bytes(), git(c["repo"], "rev-parse", "HEAD"), git(c["repo"], "status", "--porcelain"))


def test_material_duplicate_json_keys_are_refused(candidate):
    c = candidate
    c["material_path"].write_text(c["material_path"].read_text().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
    with pytest.raises(packet.PacketError, match="duplicate_material_field"):
        c["build"]()


def test_top_level_github_cannot_be_disposal_certificate(candidate):
    c = candidate
    (c["repo"] / "generated").rename(c["repo"] / ".github")
    c["base"] = c["live"]["baseRefOid"] = commit(c["repo"], "sensitive subtree base")
    tree = git(c["repo"], "rev-parse", c["base"] + ":.github")
    (c["repo"] / ".github/source.py").unlink()
    head = commit(c["repo"], "remove sensitive subtree")
    c["state"][c["node"].node_id].head_sha = c["live"]["headRefOid"] = head
    material = c["material"]["nodes"][c["node"].node_id]
    material["head_sha"] = material["verification"][0]["head_sha"] = head
    att = dump(c["tmp"] / "disposal.json", {"attested_by": "operator", "observed_at": "2026-09-22T00:00:00Z",
        "base_tip_sha": c["base"], "merge_base_sha": c["base"], "head_sha": head,
        "path": ".github", "base_tree_oid": tree, "disposal_scope": "explicit but forbidden"})
    material["generated_removals"] = [{"path": ".github", "base_tree_oid": tree,
        "rationale": "explicit disposal assertion", "attestation": att}]
    update_material(c)
    with pytest.raises(packet.PacketError, match="governance_removal_group"):
        c["build"]()


@pytest.mark.parametrize("drift,reason", [("base", "retargeted_base"), ("admission", "admission_identity_drift")])
@pytest.mark.parametrize("after_recovery", [False, True])
def test_readmission_identity_refusal_preserves_reason_and_effect_boundary(candidate, monkeypatch, drift, reason, after_recovery):
    from dataclasses import replace
    from phase_loop_runtime import train_runner as tr
    c = candidate
    enable_fab(c, monkeypatch)
    proposed_candidate(c)
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    prepare = packet.prepare_review_packet
    effects, snapshots = [], []
    def change_identity():
        if drift == "base":
            c["live"]["baseRefName"] = "retargeted"
        else:
            append_record(ledger, replace(read_ledger(ledger)[c["node"].node_id], fab_run_id="new-durable-binding"))
        snapshots.append(ledger.read_bytes())
    def prepared(*args, **kwargs):
        result = prepare(*args, **kwargs)
        if not after_recovery:
            change_identity()
        return result
    def recover(*args, **kwargs):
        effects.append("recovery")
        if after_recovery:
            change_identity()
    monkeypatch.setattr(packet, "prepare_review_packet", prepared)
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", recover)
    monkeypatch.setattr(tr, "_fab_delta_readmit", never)
    result = run_candidate(c, monkeypatch, review_only=False, fab_delta_shortcut=True,
        _train_review_fn=never, _merge_pr_fn=never)
    latest = read_ledger(ledger)[c["node"].node_id]
    observed = dict(result=result, effects=effects, ledger_changed=ledger.read_bytes() != snapshots[-1], latest=latest.to_dict())
    assert result["reason"] == reason, observed
    assert result["status"] == ("merge_halted" if after_recovery else "review_halted"), result
    assert effects == (["recovery"] if after_recovery else [])
    if after_recovery:
        assert ledger.read_bytes().startswith(snapshots[-1])
        assert latest.status == "blocked"
        assert latest.fab_run_id == ("new-durable-binding" if drift == "admission" else "packet-fab")
    else:
        assert ledger.read_bytes() == snapshots[-1]
        assert latest.status == "pr_open"


@pytest.mark.parametrize("live_head,metadata_matches", [(None, False), ("admitted", True), ("malformed", False), ("malformed", True), (True, True)])
def test_real_caller_missing_or_malformed_live_head_before_readmission(candidate, monkeypatch, live_head, metadata_matches):
    from phase_loop_runtime import train_runner as tr
    c = candidate
    enable_fab(c, monkeypatch)
    effects = []
    if live_head not in (None, "admitted") and metadata_matches:
        c["live"]["headRefOid"] = live_head
    monkeypatch.setattr(packet, "prepare_review_packet", never if live_head in (None, "admitted") else packet.prepare_review_packet)
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", lambda *a, **k: effects.append("recovery"))
    monkeypatch.setattr(tr, "_fab_delta_readmit", never)
    result = run_candidate(c, monkeypatch, review_only=False, fab_delta_shortcut=True,
        _live_pr_head_sha_fn=lambda *_: c["head"] if live_head == "admitted" else live_head,
        _merge_pr_fn=lambda *a, **kw: kw["head_sha"])
    if live_head in (None, "admitted"):
        assert result["status"] == "merged", result
        assert effects == ["recovery"]  # Existing admission recovery, never proposed readmission.
    else:
        assert result["status"] == "review_halted", result
        assert result["reason"] == ("invalid_git_oid" if metadata_matches else "stale_head"), result
        assert effects == []


@pytest.mark.parametrize("corruption", ["patch_null", "nodes_object", "deep_material", "deep_stored", "valid"])
def test_preview_external_json_boundary_always_returns_receipt(candidate, corruption):
    c = candidate
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    built = c["build"]()
    stored = packet.store_review_packet(built, ledger.parent / "review-packets")
    append_record(ledger, LedgerRecord("_train_review_", "approved", usable_reviewers=4, review_packet_sha256=built.sha256))
    metadata = json.loads((stored / "packet.json").read_text())
    if corruption == "patch_null":
        metadata["nodes"][0]["patch"] = None
        (stored / "packet.json").write_text(json.dumps(metadata))
    elif corruption == "nodes_object":
        metadata["nodes"] = {"unexpected": "object"}
        (stored / "packet.json").write_text(json.dumps(metadata))
    elif corruption.startswith("deep_"):
        path = c["material_path"] if corruption == "deep_material" else stored / "packet.json"
        path.write_text("[" * 2000 + "0" + "]" * 2000)
    before = ledger.read_bytes()
    assert hashlib.sha256((stored / "packet.md").read_bytes()).hexdigest() == built.sha256
    output = c["tmp"] / "preview"
    receipt = packet.preview_review_packet(c["roadmap"], ledger, lambda _: c["repo"], c["material_path"], output,
        _pr_metadata_fn=lambda *_: dict(c["live"]))
    assert receipt["ready"] is (corruption == "valid"), receipt
    assert receipt["model_calls"] == 0 and ledger.read_bytes() == before
    assert json.loads((output / "receipt.json").read_text()) == receipt
    if corruption != "valid":
        assert receipt["errors"] and not (output / "packet.md").exists()


@pytest.mark.parametrize("mode", ["emit", "fill"])
def test_claude_native_workflow_supplies_initial_material(candidate, monkeypatch, mode):
    """Exercise the documented arguments; native/provider outcomes remain injected seams."""
    from importlib.resources import files
    import re
    from types import SimpleNamespace
    c = candidate
    skill = files("phase_loop_runtime").joinpath("skills_bundle/claude-run-train/SKILL.md")
    text = skill.read_text().split("Under Claude Code", 1)[1].split("- The train-level review", 1)[0]
    flag = "--emit-native-request" if mode == "emit" else "--native-leg"
    command = next(s for s in re.findall(r"`([^`]+)`", text) if flag in s)
    built = c["build"]()
    result = run_candidate(c, monkeypatch,
        review_material=c["material_path"] if "--review-material material.json" in command else None,
        emit_native_request=mode == "emit",
        native_leg_fills=[SimpleNamespace(artifact_sha256=built.sha256)] if mode == "fill" else None,
        _emit_native_fill_request_fn=lambda *a, **kw: {"status": "native_fill_requested"})
    assert result["status"] == ("native_fill_requested" if mode == "emit" else "review_approved"), result
    if mode == "emit":
        assert "_train_review_" not in read_ledger(c["tmp"] / "ledger/train.ledger.jsonl")


@pytest.mark.parametrize("continuation_source", ["printed", "explicit_control"])
@pytest.mark.parametrize("quoted_ledger", [False, True])
def test_cli_native_fill_printed_continuation_retains_material_and_coordinates(candidate, monkeypatch, capsys,
                                                                              continuation_source, quoted_ledger):
    """Follow the printed hint through the real parser, packet and native-fill loader."""
    import shlex
    from types import SimpleNamespace
    from phase_loop_runtime import cli, train_runner as tr, governed_review as gr, panel_invoker as pi
    from phase_loop_runtime.advisor_board import backing, composition
    from phase_loop_runtime.convergence import broker
    from phase_loop_runtime.convergence.broker import live
    from phase_loop_runtime.train_ledger import default_ledger_path
    from test_native_claude_seat_fill import _mixed_board

    c = candidate
    train = c["tmp"] / "operator's train.md"
    train.write_text("# Release Train: packet boundary\n\n## Nodes\n\n### Node: repo-a / CHANGELOG.md\n\n"
                     "**Depends on:** (none)\n**Channel:** (none)\n")
    c["material_path"] = c["material_path"].rename(c["tmp"] / "operator's material.json")
    ledger_dir = c["tmp"] / ("operator's ledger" if quoted_ledger else "ledger")
    workspace_root = c["tmp"] / "unused workspace root"
    ledger = default_ledger_path(ledger_dir, train.stem)
    append_record(ledger, c["state"][c["node"].node_id])
    ledger_before = ledger.read_bytes()
    board = _mixed_board()
    monkeypatch.setattr(composition, "compose_review_board", lambda: board)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization", never)
    monkeypatch.setattr(live, "fabpub_capability_active", lambda: False)
    # No publication is reached: isolate the CLI's construction seam only.
    monkeypatch.setattr(broker, "build_routing_broker_client", lambda **kw: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(packet, "read_pr_metadata", lambda *a: dict(c["live"]))
    real_train = tr.run_train
    results, coordinates = [], []

    def train_with_remote_seams(roadmap, ledger_path, **kwargs):
        coordinates.append((ledger_path, kwargs["resolve_workspace"](roadmap.nodes[0]), kwargs["review_material"]))
        result = real_train(roadmap, ledger_path, **kwargs, _run_loop=never, _publish=never,
            _preflight_fn=lambda *_: [], _pr_is_open=lambda *_: True,
            _live_pr_head_sha_fn=lambda *_: c["head"], _pr_merged_sha_fn=lambda *a, **k: None,
            _merge_pr_fn=never)
        results.append(result)
        return result

    monkeypatch.setattr(tr, "run_train", train_with_remote_seams)
    original_coordinates = ["run-train", "--train", str(train), "--workspace-root", str(workspace_root),
        "--workspace", "repo-a=" + str(c["repo"]), "--workspace", "unused=" + str(c["tmp"] / "other's checkout"),
        "--ledger-dir", str(ledger_dir)]
    assert cli.main(original_coordinates + ["--governed", "--review-only", "--review-material",
        str(c["material_path"]), "--emit-native-request"]) == 0
    printed = capsys.readouterr().out
    emitted = results[-1]
    assert emitted["status"] == "native_fill_requested", emitted
    assert ledger.read_bytes() == ledger_before and "_train_review_" not in read_ledger(ledger)
    request_path = Path(emitted["request_path"])
    (request_path.parent / "review.md").write_text("Reviewed the exact emitted packet.\nAGREE\n")
    # Accept the existing flags-only form or a complete copyable command. Neither
    # receives a material argument from this test unless the CLI actually prints it.
    hint = printed.rsplit("and re-run with ", 1)[1].strip()
    if continuation_source == "explicit_control":
        hint = shlex.join(["--governed", "--review-only", "--native-leg", "claude=" + str(request_path.parent),
                           "--review-material", str(c["material_path"])])
    continuation = shlex.split(hint)
    if continuation[:1] == ["phase-loop"]:
        continuation = continuation[1:]
    if continuation[:1] != ["run-train"]:
        continuation = original_coordinates + continuation
    parsed = cli.build_parser().parse_args(continuation)
    assert parsed.train_file == str(train)
    assert parsed.workspace_root == str(workspace_root)
    assert parsed.workspace_overrides == ["repo-a=" + str(c["repo"]), "unused=" + str(c["tmp"] / "other's checkout")]
    assert parsed.ledger_dir == str(ledger_dir) and not parsed.emit_native_request
    gate_calls = []

    def injected_board_result(**kwargs):
        # Emission was real; only the reviewer outcome at fill is injected.
        gate_calls.append(kwargs)
        fills = kwargs["native_leg_fills"]
        assert len(fills) == 1 and fills[0].request_id == emitted["request_id"]
        assert fills[0].artifact_sha256 == pi.content_sha256(kwargs["artifact"])
        assert kwargs["artifact"] == Path(emitted["artifact_path"]).read_text()
        assert "actual evidence sentinel" in kwargs["artifact"]
        return gr.GateResult(ran=True, promoted=True, panel=approved(kwargs["artifact"], "governed").panel)

    monkeypatch.setattr(gr, "governed_board_gate", injected_board_result)
    assert cli.main(continuation) == 0, results[-1]
    assert results[-1]["status"] == "review_approved" and len(gate_calls) == 1
    assert coordinates == [(ledger, c["repo"], str(c["material_path"]))] * 2
    assert read_ledger(ledger)["_train_review_"].review_packet_sha256 == results[-1]["review_packet_sha256"]


def test_real_broker_retry_after_review_refusal_retains_original_publish_anchor(tmp_path, monkeypatch):
    """Two real admissions around a rejected packet review; only reviewer results are injected."""
    from phase_loop_runtime import train_runner as tr, fab_gate, fab_provenance
    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    from phase_loop_runtime.convergence.broker.live import build_routing_broker_client
    from phase_loop_runtime.governed_premerge import FAB_PROMOTION_ENV, LoopResult
    from test_fab_delta_consumer import DeltaReadmitTransactionTest

    fixture = DeltaReadmitTransactionTest()
    fixture.setUp()
    client = None
    try:
        node = TrainNode("repo-a", "specs/plan-a.md")
        roadmap = TrainRoadmap("readmission retry", [node])
        seeded = fixture._setup_broker_readmit_candidate(node_id=node.node_id)
        ledger = seeded["ledger_path"]
        transaction_bytes = seeded["transaction"].checkpoint_path.read_bytes()
        material = real_fab_packet_inputs(fixture, seeded, roadmap, monkeypatch)
        monkeypatch.setenv(FAB_PROMOTION_ENV, "1")
        client = build_routing_broker_client()
        coordinator = tr.CoordinatorRuntime(train_id="train1", coordinator_root=seeded["coordinator_root"],
            roadmap_path="train.md", roadmap_digest="d" * 64, workspace_id=str(fixture.repo), broker_client=client)
        reviews = []

        def reject_packet(artifact, mode):
            state = read_ledger(ledger)
            assert "_train_review_" not in state
            assert state[node.node_id].head_sha == seeded["delta_head"]
            digest = hashlib.sha256(artifact.encode()).hexdigest()
            assert packet.load_review_packet(ledger.parent / "review-packets", digest).artifact == artifact
            assert seeded["delta_head"] in artifact and "candidate content" in artifact
            reviews.append((seeded["delta_head"], digest))
            return LoopResult(mergeable=False, ran=True, rounds=1, reason="test_review_refused")

        def run(**kwargs):
            return tr.run_train(roadmap, ledger, run_mode="governed", review_material=material,
                resolve_workspace=lambda _: fixture.repo, coordinator_runtime=coordinator,
                _run_loop=never, _publish=never, _preflight_fn=lambda *_: [],
                _pr_is_open=lambda *_: True, _live_pr_head_sha_fn=lambda *_: seeded["delta_head"],
                _pr_merged_sha_fn=lambda *a, **k: None, _merge_phase_enabled=True, _merge_pr_fn=never,
                _delta_review_fn=fixture._review_fn, fab_fetch_origin="fetchsrc", fab_delta_shortcut=True, **kwargs)

        first = run(_train_review_fn=reject_packet)
        assert first["status"] == "review_halted" and first["reason"] == "test_review_refused", first
        first_head = seeded["delta_head"]
        first_grants = LinearizableAdmissionStore(seeded["store_root"], lambda _: True).replay()
        assert len(first_grants) == 2 and first_grants[-1].binding.prior_head_sha == seeded["candidate_head"]
        assert first_grants[-1].binding.proposed_head_sha == first_head
        assert read_ledger(ledger)[node.node_id].head_sha == first_head
        assert seeded["transaction"].checkpoint_path.read_bytes() == transaction_bytes

        fixture.write("pkg/d.py", "fix after rejected packet review\n")
        seeded["delta_head"] = fixture._vendor_commit("one supported fix after rejection", vendor="Codex")
        git(fixture.repo, "push", "-q", "fetchsrc", "HEAD:refs/heads/" + seeded["branch"])
        material = real_fab_packet_inputs(fixture, seeded, roadmap, monkeypatch)
        second = run(_train_review_fn=reject_packet)
        assert second["status"] == "review_halted" and second["reason"] == "test_review_refused", second
        grants = LinearizableAdmissionStore(seeded["store_root"], lambda _: True).replay()
        assert len(grants) == 3 and grants[:2] == first_grants
        assert grants[-1].epoch == 3 and grants[-1].binding.prior_head_sha == first_head
        assert grants[-1].binding.proposed_head_sha == seeded["delta_head"]
        assert grants[-1].binding.authority_digest == grants[-1].request.authority_digest
        assert len(reviews) == 2 and reviews[0][1] != reviews[1][1]
        assert seeded["transaction"].checkpoint_path.read_bytes() == transaction_bytes
        state = read_ledger(ledger)
        assert state[node.node_id].head_sha == seeded["delta_head"] and "_train_review_" not in state
        provenance = fab_gate.read_provenance(fixture.repo, fixture.RUN)
        assert provenance.candidate.head_sha == seeded["candidate_head"]
        assert [round_.delta_head_sha for round_ in provenance.delta_chain] == [first_head, seeded["delta_head"]]
        gate = fab_gate.compose_gate_status(repo=fixture.repo, run_id=fixture.RUN, live_base_ref_name="main",
            live_head_sha=seeded["delta_head"], origin="fetchsrc")
        assert gate.status == fab_provenance.GATE_STATUS_PASS
        # Same-head retry uses the stored admission; only an explicit successful
        # review may now create the approval row, and review-only still cannot merge.
        final = run(review_only=True, _train_review_fn=approved)
        assert final["status"] == "review_approved" and final["review_packet_sha256"] == reviews[-1][1]
        assert len(LinearizableAdmissionStore(seeded["store_root"], lambda _: True).replay()) == 3
    finally:
        if client is not None:
            client.close()
        fixture.doCleanups()


def test_real_broker_wrong_original_publish_head_refuses_first_hop(tmp_path):
    """A valid delta cannot replace the original transaction's candidate binding."""
    from phase_loop_runtime import train_runner as tr, fab_gate
    from test_fab_delta_consumer import DeltaReadmitTransactionTest

    fixture = DeltaReadmitTransactionTest()
    fixture.setUp()
    try:
        seeded = fixture._setup_broker_readmit_candidate()
        checkpoint = seeded["transaction"].checkpoint_path
        payload = json.loads(checkpoint.read_text())
        payload["committed_head_sha"] = seeded["base"]
        checkpoint.write_text(json.dumps(payload))
        before = seeded["ledger_path"].read_bytes(), tuple(seeded["store"].replay())
        result = fixture._readmit_with_broker(tr, fixture.repo, seeded["ledger_path"], node_id="n1",
            run_id=fixture.RUN, branch=seeded["branch"], pr_url="u", merge_order=0,
            admitted_head_sha=seeded["candidate_head"], live_head_sha=seeded["delta_head"],
            delta_review_fn=fixture._review_fn, owned_paths=fixture.OWNED, fab_fetch_origin="fetchsrc",
            broker_store=seeded["store"], evidence_store=seeded["evidence"])
        assert result is None
        assert before == (seeded["ledger_path"].read_bytes(), tuple(seeded["store"].replay()))
        provenance = fab_gate.read_provenance(fixture.repo, fixture.RUN)
        assert provenance.candidate.head_sha == seeded["candidate_head"] and not provenance.delta_chain
    finally:
        fixture.doCleanups()


def test_sibling_pre_recovery_drift_after_prior_recovery_preserves_ledger(candidate, monkeypatch):
    from phase_loop_runtime import train_runner as tr
    from phase_loop_runtime.convergence.broker.live import repository_broker_namespace
    c = candidate
    enable_fab(c, monkeypatch)
    second, repo = add_sibling(c)
    repository_broker_namespace(repo).mkdir(parents=True, exist_ok=True)
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    for row in c["state"].values():
        append_record(ledger, row)
    before, effects = ledger.read_bytes(), []
    def recover(ws, *args, **kwargs):
        effects.append(ws)
        c["lives"][c["state"][second.node_id].pr_url]["baseRefName"] = "retargeted"
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", recover)
    monkeypatch.setattr(tr, "_fab_delta_readmit", never)
    result = run_candidate(c, monkeypatch, review_only=False, _train_review_fn=never, _merge_pr_fn=never)
    assert result["status"] == "merge_halted" and result["reason"] == "retargeted_base", result
    assert result["node_id"] == second.node_id and effects == [c["repo"]]
    assert ledger.read_bytes() == before


def test_near_recursion_limit_stored_json_always_yields_preview_receipt(candidate):
    import sys
    c = candidate
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    built = c["build"]()
    stored = packet.store_review_packet(built, ledger.parent / "review-packets")
    append_record(ledger, LedgerRecord("_train_review_", "approved", usable_reviewers=4, review_packet_sha256=built.sha256))
    metadata = json.loads((stored / "packet.json").read_text())
    metadata["nodes"][0]["material"]["acceptance"][0]["text"] = "DEPTH_SENTINEL"
    template = json.dumps(metadata)
    before = ledger.read_bytes()
    # Decoder and renderer have different stack depths. Exercise that boundary
    # without constructing or encoding the nested Python object in this fixture.
    for depth in range(sys.getrecursionlimit() - 100, sys.getrecursionlimit() + 5):
        raw = template.replace('"DEPTH_SENTINEL"', "[" * depth + "0" + "]" * depth)
        (stored / "packet.json").write_text(raw)
        output = c["tmp"] / ("preview-depth-" + str(depth))
        receipt = packet.preview_review_packet(c["roadmap"], ledger, lambda _: c["repo"], c["material_path"], output,
            _pr_metadata_fn=never)
        assert receipt["ready"] is False and receipt["errors"], (depth, receipt)
        assert json.loads((output / "receipt.json").read_text()) == receipt
        assert ledger.read_bytes() == before


@pytest.mark.parametrize("first_readmitted", [False, True])
@pytest.mark.parametrize("reversal", ["readiness", "promotion_store"])
def test_later_proposed_eligibility_reversal_preserves_prior_effects(candidate, monkeypatch, first_readmitted, reversal):
    from dataclasses import replace
    from phase_loop_runtime import train_runner as tr, governed_premerge as gp
    from phase_loop_runtime.convergence.broker.live import repository_broker_namespace
    c = candidate
    enable_fab(c, monkeypatch)
    second, repo = add_sibling(c)
    repository_broker_namespace(repo).mkdir(parents=True, exist_ok=True)
    first_head = proposed_candidate(c) if first_readmitted else c["head"]
    (repo / "code.py").write_text("second_proposed_delta = 4\n")
    second_head = commit(repo, "second proposed delta")
    material = c["material"]["nodes"][second.node_id]
    material["head_sha"] = material["verification"][0]["head_sha"] = second_head
    c["lives"][c["state"][second.node_id].pr_url]["headRefOid"] = second_head
    update_material(c)
    ledger = c["tmp"] / "ledger/train.ledger.jsonl"
    for row in c["state"].values():
        append_record(ledger, row)
    original_store = tr._train_revocation_store
    effects, second_reads, before_refusal = [], [], []
    def store(workspace, record):
        if workspace == repo:
            second_reads.append(1)
            if len(second_reads) == 2:
                before_refusal.append(ledger.read_bytes())
                if reversal == "readiness":
                    monkeypatch.setattr(gp, "_FAB_DELTA_BROKER_READMIT_READY", False)
                else:
                    # Real resolver returns None under the existing promotion-off policy.
                    monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "0")
        return original_store(workspace, record)
    def recover(workspace, *args, **kwargs):
        effects.append(("recover", workspace))
        assert workspace == c["repo"], "second node must not begin recovery"
    def readmit(workspace, path, **kwargs):
        # Inject only the first admission outcome; Git snapshot and fresh store/identity checks are real.
        effects.append(("readmit", workspace))
        assert first_readmitted and workspace == c["repo"]
        append_record(path, replace(read_ledger(path)[c["node"].node_id], head_sha=first_head))
        return first_head
    monkeypatch.setattr(tr, "_train_revocation_store", store)
    monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", recover)
    monkeypatch.setattr(tr, "_fab_delta_readmit", readmit)
    result = run_candidate(c, monkeypatch, review_only=False, fab_delta_shortcut=True,
        _live_pr_head_sha_fn=lambda ws, br: first_head if ws == c["repo"] else second_head,
        _delta_review_fn=never, _train_review_fn=never, _merge_pr_fn=never)
    assert result["reason"] == "stale_head", result
    assert result["node_id"] == second.node_id, result
    assert effects == [("recover", c["repo"])] + ([("readmit", c["repo"])] if first_readmitted else [])
    state = read_ledger(ledger)
    assert state[c["node"].node_id].head_sha == first_head
    assert state[second.node_id].head_sha == c["head"] and state[second.node_id].status == "pr_open"
    assert len(before_refusal) == 1 and ledger.read_bytes() == before_refusal[0]
    assert result["status"] == "merge_halted", result
