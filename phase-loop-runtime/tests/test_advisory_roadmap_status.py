"""Offline lifecycle controls for agent-harness#1824."""

import hashlib
import json
from unittest.mock import Mock

import pytest

from phase_loop_runtime import cli, discovery, legible_evidence as evidence, roadmap_lint as lint
from phase_loop_runtime import plan_manifest
from test_legible_roadmap_contract import (
    BANNER_LINE3, SELECTOR_SOURCES, _build_source_fixture, _commit_all,
    _init_repo, _write_banner_roadmap, _write_status_registry,
)
from test_phase_loop_roadmap_validate import _VALID_ROADMAP

ADVISORY = "> # ADVISORY — not runner-selected (2026-11-04)"
ACTIVE = "> **Status (2026-11-04): ACTIVE — created this date, nothing executed yet.**"
A = "specs/phase-plans-v1.md"
B = "specs/phase-plans-v2.md"


def paired_repo(tmp_path):
    repo = _init_repo(tmp_path)
    _write_banner_roadmap(repo, A, ACTIVE)
    target = _write_banner_roadmap(repo, B, ADVISORY)
    registry = _write_status_registry(repo, {A: "active", B: "advisory"}, selected=A)
    _commit_all(repo)
    return repo, target, registry


def test_acceptance_reporting_and_evidence(tmp_path):
    repo, target, registry = paired_repo(tmp_path)
    assert lint.parse_roadmap_status_manifest(registry.read_text())["roadmaps"][1]["status"] == "advisory"
    assert lint.read_roadmap_status(repo, registry)["roadmaps"][1]["status"] == "advisory"
    assert lint.validate_roadmap_status_coherence(repo, required=True)["selected_roadmap"] == A
    assert discovery.select_roadmap(repo) == (repo / A).resolve()
    assert lint.declared_active_roadmap(repo) == (repo / A).resolve()
    assert plan_manifest.check(repo).exit_code == 0
    record = evidence.collect_roadmap_status(repo)
    assert record["roadmaps"][1] == {
        "path": B, "registry_status": "advisory", "banner_status": "advisory",
        "declaration_line": 3,
        "declaration_sha256": hashlib.sha256(ADVISORY.encode()).hexdigest(),
    }
    assert evidence.validate_roadmap_status_evidence(repo, record).ok


@pytest.mark.parametrize("line,status", [(ACTIVE, "active"), (ADVISORY, "advisory"),
    (BANNER_LINE3["specs/phase-plans-v1.md"], "delivered"),
    (BANNER_LINE3["specs/phase-plans-v7.md"], "superseded")])
def test_banner_grammar(line, status):
    assert lint.parse_roadmap_banner_status(f"# R\n\n{line}\n\n> ADVISORY ONLY: prose\n", B) == status


BAD_BANNERS = ["", ADVISORY.replace("not runner-selected", "draft"),
    ADVISORY.replace("2026-11-04", "2026-02-30"), "\n" + ADVISORY,
    ADVISORY + "\n" + ADVISORY, ADVISORY + "\n" + ACTIVE]


@pytest.mark.parametrize("banner", BAD_BANNERS)
def test_bad_banner(tmp_path, banner):
    repo, target, _ = paired_repo(tmp_path)
    _write_banner_roadmap(repo, B, banner)
    with pytest.raises(lint.MalformedBannerError):
        lint.validate_roadmap_status_coherence(repo, required=True)
    assert cli.main(["validate-roadmap", "--repo", str(repo), "--roadmap", str(target)]) == 1


@pytest.mark.parametrize("defect", ["selected", "only-advisory", "mismatch", "coverage"])
def test_registry_defects(tmp_path, defect):
    repo, _, registry = paired_repo(tmp_path)
    data = json.loads(registry.read_text())
    error = lint.StatusCoherenceError
    if defect == "selected":
        data["selected_roadmap"] = B
        error = lint.MalformedRegistryError
    elif defect == "only-advisory":
        data["roadmaps"][0]["status"] = "advisory"
        _write_banner_roadmap(repo, A, ADVISORY)
        error = lint.MalformedRegistryError
    elif defect == "mismatch":
        _write_banner_roadmap(repo, B, ACTIVE)
    else:
        data["roadmaps"].pop()
    registry.write_text(json.dumps(data))
    with pytest.raises(error):
        lint.validate_roadmap_status_coherence(repo, required=True)


@pytest.mark.parametrize("source", SELECTOR_SOURCES)
def test_selection_routes(tmp_path, monkeypatch, source):
    check_selection_route(tmp_path, monkeypatch, source, registered=False)


@pytest.mark.parametrize("source", ["explicit", "authority", "state", "manifest-disabled"])
def test_registered_selection_routes(tmp_path, monkeypatch, source):
    check_selection_route(tmp_path, monkeypatch, source, registered=True)


def check_selection_route(tmp_path, monkeypatch, source, registered):
    # Registry takes priority over manifest/handoff/glob; those routes are only
    # reachable without it. The registry route itself has a positive control above.
    home = tmp_path / "home"
    home.mkdir()
    fixture = _build_source_fixture(tmp_path / "repo", source, monkeypatch, ADVISORY, home=home)
    reached = []
    gate = discovery._return_selectable_roadmap
    def observe(repo, candidate, label):
        reached.append(label)
        return gate(repo, candidate, label)
    monkeypatch.setattr(discovery, "_return_selectable_roadmap", observe)
    if registered:
        _write_banner_roadmap(fixture.repo, A, ACTIVE)
        _write_status_registry(fixture.repo, {A: "active", "specs/phase-plans-v7.md": "advisory"}, selected=A)
        _commit_all(fixture.repo, "registry")
    with pytest.raises(lint.NonActiveSelectionError):
        fixture.select()
    assert reached == [fixture.gate_source]
    if not registered:
        # Same source, same repo, active companion: a blanket rejection fails.
        fixture.target.write_text(fixture.target.read_text().replace(ADVISORY, ACTIVE))
        # Authority pins bytes, so refresh its fixture rather than invalidate it.
        if source == "authority":
            fixture = _build_source_fixture(tmp_path / "active", source, monkeypatch, ACTIVE, home=home)
        assert fixture.select() == fixture.target.resolve()


@pytest.mark.parametrize("banner", [ADVISORY, *BAD_BANNERS[1:4]])
def test_singleton_attempts(tmp_path, banner):
    repo = _init_repo(tmp_path)
    _write_banner_roadmap(repo, A, banner)
    with pytest.raises(lint.NonActiveSelectionError):
        lint.declared_active_roadmap(repo)
    with pytest.raises(lint.RoadmapStatusError):
        discovery.select_roadmap(repo)


@pytest.mark.parametrize("banner", ["", ACTIVE, BANNER_LINE3["specs/phase-plans-v1.md"],
    BANNER_LINE3["specs/phase-plans-v7.md"]])
def test_singleton_legacy_unchanged(tmp_path, banner):
    repo = _init_repo(tmp_path)
    target = _write_banner_roadmap(repo, A, banner)
    assert lint.declared_active_roadmap(repo) == target.resolve()
    if banner in ("", ACTIVE):
        assert discovery.select_roadmap(repo) == target.resolve()
    else:
        with pytest.raises(lint.NonActiveSelectionError):
            discovery.select_roadmap(repo)


@pytest.mark.parametrize("command", ["run", "resume", "dry-run", "execute"])
def test_dispatch_never_reached(tmp_path, monkeypatch, command):
    repo, target, _ = paired_repo(tmp_path)
    sentinel = Mock(side_effect=AssertionError("dispatch reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    argv = [command, "--repo", str(repo), "--roadmap", str(target)]
    if command == "execute":
        argv += ["BODY", "--output", str(tmp_path / "out")]
    with pytest.raises(lint.NonActiveSelectionError):
        cli.main(argv)
    sentinel.assert_not_called()


def test_old_reader_fails_closed(tmp_path, monkeypatch):
    repo, _, registry = paired_repo(tmp_path)
    monkeypatch.setattr(lint, "ROADMAP_STATUSES", ("active", "delivered", "superseded"))
    with pytest.raises(lint.MalformedRegistryError, match="unrecognized"):
        lint.parse_roadmap_status_manifest(registry.read_text())
    with pytest.raises(lint.MalformedRegistryError, match="unrecognized"):
        discovery.select_roadmap(repo)
    sentinel = Mock(side_effect=AssertionError("dispatch reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    with pytest.raises(lint.MalformedRegistryError, match="unrecognized"):
        cli.main(["run", "--repo", str(repo)])
    sentinel.assert_not_called()
    _write_banner_roadmap(repo, B, BANNER_LINE3["specs/phase-plans-v1.md"])
    _write_status_registry(repo, {A: "active", B: "delivered"}, selected=A)
    assert discovery.select_roadmap(repo) == (repo / A).resolve()


@pytest.mark.parametrize("drift", ["banner", "registry", "record"])
def test_evidence_drift(tmp_path, drift):
    repo, target, registry = paired_repo(tmp_path)
    record = evidence.collect_roadmap_status(repo)
    if drift == "banner":
        target.write_text(target.read_text().replace("2026-11-04", "2026-11-03"))
        code = "roadmap_status_digest_drift"
    elif drift == "registry":
        registry.write_text(registry.read_text() + "\n")
        code = "roadmap_status_registry_drift"
    else:
        record["roadmaps"].pop()
        code = "roadmap_status_path_set_drift"
    with pytest.raises(evidence.LegibleStatusEvidenceError) as exc:
        evidence.validate_roadmap_status_evidence(repo, record)
    assert exc.value.code == code


def test_explicit_content_validation(tmp_path):
    repo, target, _ = paired_repo(tmp_path)
    # The banner does not exempt advisory content from ordinary phase lint.
    body = _VALID_ROADMAP.split("\n", 1)[1]
    target.write_text(target.read_text() + body)
    assert cli.main(["validate-roadmap", "--repo", str(repo), "--roadmap", str(target)]) == 0
    target.write_text(target.read_text() + "\n### Phase 2 - Bad (bad)\n")
    assert cli.main(["validate-roadmap", "--repo", str(repo), "--roadmap", str(target)]) != 0
