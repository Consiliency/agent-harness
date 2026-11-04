"""Offline lifecycle controls for agent-harness#1824."""

import hashlib
import json
from unittest.mock import Mock

import pytest

from phase_loop_runtime import cli, discovery, legible_evidence as evidence, roadmap_lint as lint
from phase_loop_runtime import plan_manifest
from phase_loop_runtime.roadmap_ownership import RoadmapUnreadable, resolve_roadmap
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
    ADVISORY + "\n" + ACTIVE]


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


@pytest.mark.parametrize("banner", [ADVISORY])
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
    assert cli.main(argv) == 2
    sentinel.assert_not_called()


def test_prior_registry_vocabulary_fails_closed(tmp_path, monkeypatch):
    repo, _, registry = paired_repo(tmp_path)
    monkeypatch.setattr(lint, "ROADMAP_STATUSES", ("active", "delivered", "superseded"))
    with pytest.raises(lint.MalformedRegistryError, match="unrecognized"):
        lint.parse_roadmap_status_manifest(registry.read_text())
    with pytest.raises(lint.MalformedRegistryError, match="unrecognized"):
        discovery.select_roadmap(repo)
    sentinel = Mock(side_effect=AssertionError("dispatch reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    assert cli.main(["run", "--repo", str(repo)]) == 2
    sentinel.assert_not_called()
    _write_banner_roadmap(repo, B, BANNER_LINE3["specs/phase-plans-v1.md"])
    _write_status_registry(repo, {A: "active", B: "delivered"}, selected=A)
    assert discovery.select_roadmap(repo) == (repo / A).resolve()


@pytest.mark.parametrize("text", [
    "> # Advisory — not runner-selected (2026-11-04)",
    "> # ADVISORY (2026-11-04)",
    "> This roadmap is not runner-selected.",
    "\n" + ADVISORY,
    "## Body\n" + ADVISORY,
])
def test_near_miss_is_legacy_with_validator_warning(tmp_path, monkeypatch, capsys, text):
    repo = _init_repo(tmp_path)
    target = _write_banner_roadmap(repo, A, text)
    assert discovery.select_roadmap(repo) == target.resolve()
    assert lint.declared_active_roadmap(repo) == target.resolve()
    assert resolve_roadmap(repo) == target.resolve()
    sentinel = Mock(side_effect=RuntimeError("dispatch reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    with pytest.raises(RuntimeError, match="dispatch reached"):
        cli.main(["dry-run", "--repo", str(repo)])
    sentinel.assert_called_once()
    # Use valid content to prove the warning itself cannot fail validation.
    target.write_text("# R\n\n" + text + "\n" + _VALID_ROADMAP.split("\n", 1)[1])
    assert cli.main(["validate-roadmap", "--repo", str(repo), "--roadmap", str(target)]) == 0
    assert "WARNING: line " in capsys.readouterr().err


@pytest.mark.parametrize("banner", [
    "> Status: cancelled — do not run", "> Status: draft",
    "> # STATUS: RETIRED", "> **Status:** Closed", "> Status: on hold",
    "> Status: inactive", "> Status: advisory",
    "> **Status (2026-11-04): ADVISORY**",
    "> Status of advisory seats: open.",
])
def test_status_attempts_preserve_main_refusal(tmp_path, monkeypatch, banner):
    # Main's pre-advisory gate refuses all nine shapes from the round-4 report;
    # its historical singleton accessor still returns the candidate.
    repo = _init_repo(tmp_path)
    target = _write_banner_roadmap(repo, A, banner)
    assert lint.declared_active_roadmap(repo) == target.resolve()
    assert resolve_roadmap(repo) == target.resolve()
    with pytest.raises(lint.MalformedBannerError):
        discovery.select_roadmap(repo)
    sentinel = Mock(side_effect=AssertionError("dispatch reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    for command in ("run", "dry-run"):
        assert cli.main([command, "--repo", str(repo)]) == 2
    assert cli.main(["validate-roadmap", "--repo", str(repo)]) == 2
    sentinel.assert_not_called()


@pytest.mark.parametrize("prefix", ["Title\n\n", "# R\nx\n", "# R\n \n", "\ufeff# R\n\n", "## R\n\n"])
def test_exact_banner_with_malformed_header_stops_dispatch(tmp_path, monkeypatch, prefix):
    repo = _init_repo(tmp_path)
    target = _write_banner_roadmap(repo, A, ADVISORY)
    target.write_text(prefix + ADVISORY + "\n")
    with pytest.raises(lint.MalformedBannerError):
        discovery.select_roadmap(repo)
    sentinel = Mock(side_effect=AssertionError("dispatch reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    for command in ("run", "dry-run"):
        assert cli.main([command, "--repo", str(repo)]) == 2
    sentinel.assert_not_called()


@pytest.mark.parametrize("registered", [False, True])
def test_active_and_sibling_advisory_prose_does_not_block(tmp_path, registered):
    repo = _init_repo(tmp_path)
    prose = "\n> Status: advisory\n" + ADVISORY + "\n\n## Body\nUses ADVISORY locks.\n> Formerly ADVISORY.\n"
    target = _write_banner_roadmap(repo, A, ACTIVE + prose)
    if registered:
        _write_banner_roadmap(repo, B, ADVISORY + prose)
        _write_status_registry(repo, {A: "active", B: "advisory"}, selected=A)
        _commit_all(repo)
    assert lint.parse_roadmap_banner_status(target.read_text(), A) == "active"
    assert discovery.select_roadmap(repo) == target.resolve()
    assert lint.declared_active_roadmap(repo) == target.resolve()
    assert resolve_roadmap(repo) == target.resolve()


def test_exact_banner_warning_exclusion_and_location():
    assert lint.advisory_text_warnings("# R\n\n" + ADVISORY) == []
    assert lint.advisory_text_warnings("# R\n\n" + ACTIVE) == []
    assert lint.advisory_text_warnings("# R\n\n" + ADVISORY + "\n" + ADVISORY)[0].startswith("line 4:")
    assert lint.advisory_text_warnings("# R\n\n" + ADVISORY.replace("2026-11-04", "2026-02-30"))


@pytest.mark.parametrize("line", [
    ADVISORY + " ", ADVISORY.replace("2026-11-04", "2026-02-30"),
    ADVISORY.replace("—", "-"),
    "> # ADVISORY — not runner-selected",
])
def test_near_banner_is_not_exact(line):
    assert not lint.has_exact_advisory_banner("# R\n\n" + line)


@pytest.mark.parametrize("command", ["run", "resume", "dry-run", "execute"])
def test_no_registry_exact_banner_stops_dispatch(tmp_path, monkeypatch, command):
    repo = _init_repo(tmp_path)
    target = _write_banner_roadmap(repo, A, ADVISORY)
    sentinel = Mock(side_effect=AssertionError("dispatch reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    argv = [command, "--repo", str(repo), "--roadmap", str(target)]
    if command == "execute":
        argv += ["BODY", "--output", str(tmp_path / "out")]
    assert cli.main(argv) == 2
    sentinel.assert_not_called()


@pytest.mark.parametrize("banner", [ACTIVE, BANNER_LINE3[A], BANNER_LINE3["specs/phase-plans-v7.md"]])
def test_recognized_singleton_with_advisory_prose(tmp_path, banner):
    repo = _init_repo(tmp_path)
    target = _write_banner_roadmap(repo, A, banner + "\n\n> ADVISORY ONLY: prose")
    assert lint.declared_active_roadmap(repo) == target.resolve()
    assert resolve_roadmap(repo) == target.resolve()
    if banner == ACTIVE:
        assert discovery.select_roadmap(repo) == target.resolve()


@pytest.mark.parametrize("defect", ["encoding", "symlink", "outside-symlink", "directory"])
def test_unreadable_singleton_is_typed(tmp_path, defect):
    repo = _init_repo(tmp_path)
    target = repo / A
    target.parent.mkdir(exist_ok=True)
    if defect == "encoding":
        target.write_bytes(b"\xff")
    elif defect == "symlink":
        target.symlink_to("missing.md")
    elif defect == "outside-symlink":
        target.symlink_to("/nonexistent-outside/missing.md")
    else:
        target.mkdir()
    with pytest.raises(lint.MalformedBannerError) as declared_error:
        lint.declared_active_roadmap(repo)
    assert str(repo) not in str(declared_error.value)
    assert str(declared_error.value).startswith(A + ": cannot read")
    with pytest.raises(lint.MalformedBannerError) as error:
        discovery.select_roadmap(repo)
    assert str(repo) not in str(error.value)
    assert str(error.value).startswith("specs/")


@pytest.mark.parametrize("defect", ["encoding", "symlink", "outside-symlink", "directory"])
def test_unreadable_multi_candidate_is_typed(tmp_path, defect):
    repo = _init_repo(tmp_path)
    _write_banner_roadmap(repo, A, ACTIVE)
    target = repo / B
    if defect == "encoding":
        target.write_bytes(b"\xff")
    elif defect == "symlink":
        target.symlink_to("missing.md")
    elif defect == "outside-symlink":
        target.symlink_to("/nonexistent-outside/missing.md")
    else:
        target.mkdir()
    with pytest.raises(lint.MalformedBannerError, match=B + ": cannot read") as error:
        lint.declared_active_roadmap(repo)
    assert str(repo) not in str(error.value)
    with pytest.raises(RoadmapUnreadable):
        resolve_roadmap(repo)


def test_singleton_refusal_uses_relative_path(tmp_path):
    repo = _init_repo(tmp_path)
    _write_banner_roadmap(repo, A, ADVISORY)
    with pytest.raises(lint.NonActiveSelectionError) as exc:
        lint.declared_active_roadmap(repo)
    assert str(exc.value).startswith(A + ":")
    assert str(repo) not in str(exc.value)


def test_cli_status_refusal_is_clean(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    target = _write_banner_roadmap(repo, A, ADVISORY)
    assert cli.main(["run", "--repo", str(repo), "--roadmap", str(target)]) == 2
    err = capsys.readouterr().err
    assert "roadmap status refusal" in err
    assert "Traceback" not in err
    assert A in err
    assert str(repo) not in err


def test_outside_repo_refusal_uses_filename(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path / "repo")
    target = tmp_path / "phase-plans-outside.md"
    target.write_text("# R\n\n" + ADVISORY + "\n")
    sentinel = Mock(side_effect=AssertionError("dispatch reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    assert cli.main(["run", "--repo", str(repo), "--roadmap", str(target)]) == 2
    err = capsys.readouterr().err
    assert target.name in err
    assert str(tmp_path) not in err
    sentinel.assert_not_called()


def test_no_sole_active_refusal_has_no_absolute_path(tmp_path):
    repo = _init_repo(tmp_path)
    _write_banner_roadmap(repo, A, ADVISORY)
    _write_banner_roadmap(repo, B, ADVISORY)
    with pytest.raises(lint.NonActiveSelectionError) as error:
        lint.declared_active_roadmap(repo)
    assert str(error.value) == "cannot determine the sole active roadmap in specs/"
    assert str(repo) not in str(error.value)


def test_symlinked_singleton_returns_resolved_path(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "roadmap.md"
    target.write_text("# R\n\n" + ACTIVE + "\n")
    link = repo / A
    link.parent.mkdir(exist_ok=True)
    link.symlink_to(target)
    assert discovery.select_roadmap(repo) == target.resolve()
    assert lint.declared_active_roadmap(repo) == target.resolve()


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
