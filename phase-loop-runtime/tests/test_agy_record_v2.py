"""Record v2 and its migration (AGYROLL §3.2, §3.5; RECBIND SL-1).

The ``check`` cases drive ``scripts/convert_agy_record_v2.py`` against a throwaway git
repository whose history holds a v1 record and the tree it was recorded on, so the record
commit, the profile-digest equality and the validator-closure equality are all exercised on
real git objects. The profile digest is computed through the converter's ``digests`` seam
(the real one imports each tree in an isolated interpreter; the stop gate runs it for real).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def converter():
    return _load("convert_agy_record_v2")


VALIDATOR = '''"""Fixture driver."""
from . import gemini_heartbeat as gh


def _panel():
    from . import panel_invoker
    return panel_invoker


def _helper(value):
    return value == gh.PROFILE_ID


def validate_records(record, **expected):
    if not _helper(record["profile"]):
        raise ValueError("rejected")
    return _panel().terminal_verdict(record["text"])


def validate_directory(root, **expected):
    return validate_records(root, **expected)


def _classify_failure(root, operation):
    return "failed"
'''
HEARTBEAT = 'PROFILE_ID = "agy_memfd_home_deny_all_v1"\n'
PANEL = 'def terminal_verdict(text):\n    return "AGREE" if text.endswith("AGREE") else None\n'
RECORD = "agy-9.9.9-linux-x64-qualification.json"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


class FixtureRepo:
    def __init__(self, root: Path, converter):
        self.root, self.converter = root, converter
        self.package = root / "phase-loop-runtime/src/phase_loop_runtime"
        self.package.mkdir(parents=True)
        (root / "phase-loop-runtime/scripts").mkdir()
        (root / "plans/evidence").mkdir(parents=True)
        _git(root, "init", "-q", "-b", "main")
        _git(root, "config", "user.email", "fixture@example.invalid")
        _git(root, "config", "user.name", "fixture")
        _git(root, "config", "commit.gpgsign", "false")
        self.write("__init__.py", '__version__ = "0.0.1"\n')
        self.write("agy_qualification.py", VALIDATOR)
        self.write("gemini_heartbeat.py", HEARTBEAT)
        self.write("panel_invoker.py", PANEL)
        self.write("unrelated.py", "VALUE = 1\n")
        (self.package / "PROFILE").write_text("profile-a\n")
        (root / "phase-loop-runtime/scripts/qualify_gemini_heartbeat.py").write_text("# shim\n")
        (root / "plans/evidence/qualified-provider-images.json").write_text(json.dumps({
            "schema": "qualified_provider_images.v2",
            "routes": {"gemini_heartbeat_linux_x64": {"images": [
                {"release_version": "9.9.9", "image_sha256": "a" * 64, "help_sha256": "b" * 64, "record": RECORD}]}}}))

    def write(self, name, text):
        (self.package / name).write_text(text)

    def record_v1(self):
        record = {"schema": "agy_redacted_qualification_summary.v1", "release_version": "9.9.9",
                  "image_sha256": "a" * 64, "help_sha256": "b" * 64,
                  "upstream_asset_name": "agy_cli_linux_x64.tar.gz", "upstream_asset_sha256": "c" * 64,
                  "upstream_release_url": "https://github.com/google-antigravity/antigravity-cli/releases/tag/9.9.9",
                  "source_sha256": self.converter.tree_sources(self.root, "HEAD"), "records": [],
                  "validator": {"validated": 3, "operations": ["cancel", "completion", "owner-loss"],
                                "route_qualified": True}}
        (self.root / "plans/evidence" / RECORD).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        return record

    def commit(self, message):
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", message)
        return _git(self.root, "rev-parse", "HEAD")

    @staticmethod
    def digests(src_root, python):
        """The fixture's profile digest: a hash of the tree's PROFILE file."""
        value = sha256((Path(src_root) / "phase_loop_runtime/PROFILE").read_bytes()).hexdigest()
        return value, value


@pytest.fixture
def repo(tmp_path, converter):
    fixture = FixtureRepo(tmp_path / "repo", converter)
    fixture.commit("tree")
    fixture.record_v1()
    fixture.record_commit = fixture.commit("record")
    return fixture


def test_check_finds_the_record_commit(repo, converter):
    repo.write("unrelated.py", "VALUE = 2\n")  # head's sources now differ from the pins
    repo.commit("an ordinary change outside the validator")
    rows = converter.check(repo.root, digests=repo.digests)
    assert [row["record_commit"] for row in rows] == [repo.record_commit]
    assert rows[0]["qualified_under"] == "0.0.1"


def test_check_skips_a_record_touch_whose_tree_does_not_match(repo, converter):
    repo.write("unrelated.py", "VALUE = 3\n")
    path = repo.root / "plans/evidence" / RECORD
    path.write_text(path.read_text() + "\n")  # reformatted later, on a different tree
    repo.commit("touch the record")
    assert converter.check(repo.root, digests=repo.digests)[0]["record_commit"] == repo.record_commit


def test_check_refuses_when_there_is_no_record_commit(repo, converter):
    path = repo.root / "plans/evidence" / RECORD
    record = json.loads(path.read_text())
    record["source_sha256"]["agy_qualification.py"] = "0" * 64
    path.write_text(json.dumps(record))
    repo.commit("pins that no tree ever had")
    with pytest.raises(converter.ConversionRefused, match="no record commit"):
        converter.check(repo.root, digests=repo.digests)


def test_check_refuses_an_agy_profile_digest_mismatch(repo, converter):
    (repo.package / "PROFILE").write_text("profile-b\n")
    repo.commit("the owned profile changed")
    with pytest.raises(converter.ConversionRefused, match="agy_profile_digest"):
        converter.check(repo.root, digests=repo.digests)


@pytest.mark.parametrize(("module", "old", "new", "named"), [
    ("agy_qualification.py", 'raise ValueError("rejected")', 'return None', "agy_qualification:validate_records"),
    # transitive: a callee of an entry point, and a callee in another module
    ("agy_qualification.py", "return value == gh.PROFILE_ID", "return True", "agy_qualification:_helper"),
    ("panel_invoker.py", 'text.endswith("AGREE")', 'True', "panel_invoker:terminal_verdict"),
    ("gemini_heartbeat.py", "agy_memfd_home_deny_all_v1", "other", "gemini_heartbeat:PROFILE_ID"),
])
def test_check_refuses_a_validator_closure_mismatch(repo, converter, module, old, new, named):
    path = repo.package / module
    path.write_text(path.read_text().replace(old, new))
    repo.commit("the validator changed")
    with pytest.raises(converter.ConversionRefused, match="validator closure") as refused:
        converter.check(repo.root, digests=repo.digests)
    assert named in str(refused.value)


def test_closure_resolves_relative_imports_against_the_containing_package(tmp_path, converter):
    """``from .registries import X`` inside ``advisor/backing.py`` is ``advisor.registries``,
    never a top-level ``registries`` (agent-harness#1937 review B2)."""
    package = tmp_path / "phase_loop_runtime"
    (package / "advisor").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "advisor" / "__init__.py").write_text("")
    (package / "agy_qualification.py").write_text(
        "def _harden(model):\n    from .advisor.backing import harden\n    return harden(model)\n\n\n"
        "def validate_records(record):\n    return _harden(record)\n\n\n"
        "def validate_directory(root):\n    return None\n\n\n"
        "def _classify_failure(root, operation):\n    return 'failed'\n")
    (package / "advisor" / "backing.py").write_text(
        "from .registries import runnable\nfrom . import mapping\n\n\n"
        "def harden(model):\n    return runnable(model) and mapping.allowed(model)\n")
    (package / "advisor" / "registries.py").write_text("SPECS = ('gemini',)\n\n\ndef runnable(model):\n    return model in SPECS\n")
    (package / "advisor" / "mapping.py").write_text("def allowed(model):\n    return True\n")
    (package / "registries.py").write_text("def runnable(model):\n    return True\n")  # the wrong target
    table = converter.validator_closure(package)
    assert {"advisor.backing:harden", "advisor.registries:runnable", "advisor.registries:SPECS",
            "advisor.mapping:allowed"} <= set(table)
    assert not any(key.startswith("registries:") for key in table)
    before = converter.closure_digest(table)
    (package / "advisor" / "registries.py").write_text("SPECS = ('gemini', 'codex')\n\n\ndef runnable(model):\n    return model in SPECS\n")
    assert converter.closure_digest(converter.validator_closure(package)) != before


def test_check_ignores_an_edit_outside_the_validator_closure(repo, converter):
    repo.write("unrelated.py", "def other():\n    return 4\n")
    repo.commit("outside the closure")
    assert converter.check(repo.root, digests=repo.digests)[0]["schema"] == converter.V1


def test_check_passes_for_a_converted_fixture(repo, converter):
    converter.write(repo.root, digests=repo.digests)
    record = json.loads((repo.root / "plans/evidence" / RECORD).read_text())
    assert record["schema"] == converter.V2 and "source_sha256" not in record
    assert record["qci"] == repo.digests(repo.root / "phase-loop-runtime/src", None)[1]
    assert record["qualified_under"] == "0.0.1" and record["signatures"] == []
    assert record["upstream"] == {"asset_sha256": "c" * 64, "release_url": record["upstream_release_url"],
                                  "attestation": "not_checked", "second_channel": "not_checked"}
    rows = converter.check(repo.root, digests=repo.digests)
    assert rows == [{"member": "9.9.9", "record": RECORD, "schema": converter.V2, "qci": record["qci"]}]


def test_check_refuses_a_converted_record_whose_qci_differs(repo, converter):
    converter.write(repo.root, digests=repo.digests)
    (repo.package / "PROFILE").write_text("profile-b\n")
    with pytest.raises(converter.ConversionRefused, match="qci differs"):
        converter.check(repo.root, digests=repo.digests)


def test_check_closure_reaches_the_real_validator_callees(converter):
    table = converter.validator_closure(Path(__file__).resolve().parents[1] / "src/phase_loop_runtime")
    for key in ("agy_qualification:validate_records", "agy_qualification:validate_directory",
                "agy_qualification:_classify_failure", "panel_invoker:terminal_verdict",
                "panel_invoker:_render_broker_inline_prompt", "advisor_board.backing:harden_subscription_model",
                "gemini_heartbeat:PROFILE_ID"):
        assert key in table


# ------------------------------------------------- verifier --contract / --release

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def verifier():
    return _load("verify_qualified_agy_image")


@pytest.fixture
def evidence(verifier, tmp_path, monkeypatch):
    """A private copy of the shipped catalog and its members' records for the verifier."""
    from phase_loop_runtime import gemini_heartbeat as gh

    catalog = Path(gh.__file__).resolve().parent / "data" / "agy_catalog.json"
    records = tmp_path / "evidence"
    records.mkdir()
    for member in gh.parse_catalog(catalog.read_text()):
        (records / member["record"]).write_bytes((REPO / "plans/evidence" / member["record"]).read_bytes())
    (tmp_path / "agy_catalog.json").write_bytes(catalog.read_bytes())
    monkeypatch.setattr(verifier, "CATALOG", tmp_path / "agy_catalog.json")
    monkeypatch.setattr(verifier, "EVIDENCE", records)
    return tmp_path


def _edit_json(path, change):
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value))


def _record_path(evidence):
    return next((evidence / "evidence").glob("agy-*-linux-x64-qualification.json"))


def test_contract_passes_on_the_shipped_evidence(verifier, evidence):
    records = verifier.contract()
    assert records and all(r["schema"] == "agy_redacted_qualification_summary.v2" for r in records)


def test_contract_passes_a_drift_outside_the_qci(verifier, evidence, monkeypatch):
    """No live run for an ordinary change: version, file hashes and the runtime set are not the QCI."""
    import phase_loop_runtime
    from phase_loop_runtime import agy_qualification as q
    from phase_loop_runtime import gemini_heartbeat as gh

    monkeypatch.setattr(phase_loop_runtime, "__version__", "99.0.0")
    monkeypatch.setattr(q, "ROUTE_CORE", ("unrelated.py",))
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})
    assert verifier.contract()


def test_contract_fails_a_qci_drift_naming_the_member(verifier, evidence, monkeypatch, capsys):
    from phase_loop_runtime import agy_qualification as q

    first, *rest = q.OPERATIONS_CONTRACT
    monkeypatch.setattr(q, "OPERATIONS_CONTRACT", (first._replace(pass_predicate_id="mutant_v1"), *rest))
    members = [m["release_version"] for m in json.loads((evidence / "agy_catalog.json").read_text())["routes"]["linux-x64"]]
    with pytest.raises(verifier.RequalifyRequired) as refused:
        verifier.contract()
    assert refused.value.members == members
    assert verifier.main(["--contract"]) == 1
    assert capsys.readouterr().err.strip() == "requalify: " + ", ".join(members)


def test_contract_fails_a_record_whose_qci_differs(verifier, evidence):
    _edit_json(_record_path(evidence), lambda r: r.update(qci="0" * 64))
    with pytest.raises(verifier.RequalifyRequired):
        verifier.contract()


@pytest.mark.parametrize("change", [
    lambda r: r.update(source_sha256={"x.py": "0" * 64}),   # a v1 field is no longer allowed
    lambda r: r.pop("signatures"),
    lambda r: r.update(schema="agy_redacted_qualification_summary.v1"),
    lambda r: r["upstream"].update(extra=True),
    lambda r: r["upstream"].update(asset_sha256="0" * 64),
    lambda r: r.update(image_sha256="0" * 64),
])
def test_contract_requires_a_closed_matching_v2_record(verifier, evidence, change):
    _edit_json(_record_path(evidence), change)
    with pytest.raises(ValueError):
        verifier.contract()


def test_contract_fails_a_member_with_no_record(verifier, evidence):
    _record_path(evidence).unlink()
    with pytest.raises(ValueError, match="has no record"):
        verifier.contract()


def test_contract_ignores_an_unlisted_record(verifier, evidence):
    (evidence / "evidence" / "agy-0.0.1-linux-x64-qualification.json").write_text("not even json")
    assert verifier.contract()


@pytest.mark.parametrize("text", ['{"schema": "qualified_agy_catalog.v3", "routes": {"linux-x64": []}}',
                                  "{malformed", ""])
def test_contract_fails_an_empty_or_malformed_catalog(verifier, evidence, text):
    (evidence / "agy_catalog.json").write_text(text)
    with pytest.raises(ValueError, match="agy catalog"):
        verifier.contract()
    assert verifier.main(["--contract"]) == 1


IDENTITY = {"agy_conformance_strict": "1", "agy_conformance_commit": "c" * 40,
            "agy_conformance_source_sha256": "d" * 64}


def _report(path, cases, identity=IDENTITY, **counts):
    rows = []
    for ident, outcome in cases:
        child = {"pass": "", "skipped": '<skipped message="no bwrap"/>',
                 "xfail": '<skipped type="pytest.xfail" message="xfail"/>',
                 "failure": '<failure message="x"/>', "error": '<error message="x"/>'}[outcome]
        rows.append(f'<testcase classname="tests.test_agy_route_conformance" name="test_obligation[{ident}]" '
                    f'time="1">{child}</testcase>')
    attributes = " ".join(f'{key}="{value}"' for key, value in {"errors": 0, "failures": 0, "skipped": 0, **counts}.items())
    properties = "".join(f'<property name="{name}" value="{value}"/>' for name, value in (identity or {}).items())
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite name="pytest" {attributes}>'
                    + (f"<properties>{properties}</properties>" if properties else "")
                    + "".join(rows) + "</testsuite></testsuites>")
    return path


@pytest.fixture
def obligations(verifier):
    return verifier.conformance_obligations()


def _archive(executable: bytes) -> bytes:
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("antigravity")
        info.size = len(executable)
        bundle.addfile(info, io.BytesIO(executable))
    return buffer.getvalue()


@pytest.fixture
def release_io(verifier, evidence):
    """The release gate's network, offline: each member becomes a synthetic image whose
    official archive the fake upstream serves by tag."""
    catalog_path = evidence / "agy_catalog.json"
    catalog = json.loads(catalog_path.read_text())
    archives, metadata = {}, {}
    for member in catalog["routes"]["linux-x64"]:
        executable = f"synthetic agy {member['release_version']}".encode()
        archive = _archive(executable)
        image, asset = sha256(executable).hexdigest(), sha256(archive).hexdigest()
        member.update(image_sha256=image, asset_sha256=asset)
        record_path = evidence / "evidence" / member["record"]
        record = json.loads(record_path.read_text())
        record.update(image_sha256=image, upstream_asset_sha256=asset)
        record["upstream"]["asset_sha256"] = asset
        for row in record["records"]:
            row["image_sha256"] = image
            row["profile"]["image_sha256"] = image
        record_path.write_text(json.dumps(record))
        version = member["release_version"]
        url = f"https://github.com/{verifier.UPSTREAM}/releases/download/{version}/{verifier.ASSET}"
        archives[url] = archive
        metadata[f"{verifier.RELEASES}/tags/{version}"] = {"tag_name": version, "assets": [{
            "name": verifier.ASSET, "digest": "sha256:" + asset, "browser_download_url": url}]}
    catalog_path.write_text(json.dumps(catalog))
    return {"fetch": metadata.__getitem__, "download": lambda url, target: Path(target).write_bytes(archives[url]),
            "identity": IDENTITY, "_metadata": metadata, "_archives": archives}


def _io(release_io):
    return {key: value for key, value in release_io.items() if not key.startswith("_")}


def test_release_reads_the_suites_eight_obligations(obligations):
    conformance = _load_suite()
    assert obligations == conformance.CONFORMANCE_OBLIGATIONS and len(obligations) == 8


def _load_suite():
    spec = importlib.util.spec_from_file_location(
        "agy_route_conformance_for_release", Path(__file__).resolve().parent / "test_agy_route_conformance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_passes_a_strict_complete_report(verifier, evidence, obligations, release_io, tmp_path):
    report = _report(tmp_path / "conformance.xml", [(o, "pass") for o in obligations])
    records, seen = verifier.release(report, **_io(release_io))
    assert seen == sorted(obligations) and records


@pytest.mark.parametrize("outcome", ["skipped", "xfail", "failure", "error"])
def test_release_fails_a_report_with_a_non_passing_obligation(verifier, evidence, obligations, release_io, tmp_path, outcome):
    cases = [(o, "pass") for o in obligations]
    cases[0] = (cases[0][0], outcome)
    report = _report(tmp_path / "conformance.xml", cases)
    with pytest.raises(ValueError):
        verifier.release(report, **_io(release_io))


def test_release_fails_a_skipped_run_even_by_its_counts(verifier, evidence, obligations, release_io, tmp_path):
    report = _report(tmp_path / "conformance.xml", [(o, "pass") for o in obligations], skipped=1)
    with pytest.raises(ValueError, match="skipped"):
        verifier.release(report, **_io(release_io))


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unknown"])
def test_release_fails_a_partial_or_repeated_report(verifier, evidence, obligations, release_io, tmp_path, kind):
    cases = [(o, "pass") for o in obligations]
    if kind == "missing":
        cases = cases[1:]
    elif kind == "duplicate":
        cases.append(cases[0])
    else:
        cases.append(("neg_invented", "pass"))
    with pytest.raises(ValueError, match=kind if kind != "duplicate" else "repeats"):
        verifier.release(_report(tmp_path / "conformance.xml", cases), **_io(release_io))


def test_release_fails_without_a_report(verifier, evidence, release_io, tmp_path, capsys):
    with pytest.raises(ValueError, match="unavailable"):
        verifier.release(tmp_path / "absent.xml", **_io(release_io))
    with pytest.raises(SystemExit):
        verifier.main(["--release"])  # --conformance-report is required


def test_release_fails_an_asset_mismatch(verifier, evidence, obligations, release_io, tmp_path):
    for release in release_io["_metadata"].values():
        release["assets"][0]["digest"] = "sha256:" + "0" * 64
    report = _report(tmp_path / "conformance.xml", [(o, "pass") for o in obligations])
    with pytest.raises(ValueError, match="asset digest mismatch"):
        verifier.release(report, **_io(release_io))


def test_release_fails_an_operations_contract_edit(verifier, evidence, obligations, release_io, tmp_path, monkeypatch):
    from phase_loop_runtime import agy_qualification as q

    first, *rest = q.OPERATIONS_CONTRACT
    monkeypatch.setattr(q, "OPERATIONS_CONTRACT", (first._replace(argv_template=first.argv_template[:-1]), *rest))
    report = _report(tmp_path / "conformance.xml", [(o, "pass") for o in obligations])
    with pytest.raises(verifier.RequalifyRequired):
        verifier.release(report, **_io(release_io))


def test_release_refuses_a_report_with_a_dtd(verifier, evidence, obligations, release_io, tmp_path):
    report = tmp_path / "conformance.xml"
    report.write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><testsuites/>')
    with pytest.raises(ValueError, match="DTD"):
        verifier.release(report, **_io(release_io))


@pytest.mark.parametrize(("change", "match"), [
    (lambda identity: None, "no agy_conformance_strict"),
    (lambda identity: {**identity, "agy_conformance_strict": "0"}, "agy_conformance_strict"),
    (lambda identity: {**identity, "agy_conformance_commit": "e" * 40}, "agy_conformance_commit"),
    (lambda identity: {**identity, "agy_conformance_source_sha256": "e" * 64}, "agy_conformance_source_sha256"),
    (lambda identity: {key: value for key, value in identity.items() if key != "agy_conformance_commit"},
     "no agy_conformance_commit"),
])
def test_release_requires_the_report_identity_of_a_strict_run_at_this_checkout(
        verifier, evidence, obligations, release_io, tmp_path, change, match):
    """Eight bare <testcase> elements are not a conformance run (agent-harness#1937 B4)."""
    report = _report(tmp_path / "conformance.xml", [(o, "pass") for o in obligations], identity=change(IDENTITY))
    with pytest.raises(ValueError, match=match):
        verifier.release(report, **_io(release_io))


def test_release_identity_is_this_checkouts_commit_and_sources(verifier):
    identity = verifier.conformance_identity()
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    assert identity == {"agy_conformance_strict": "1", "agy_conformance_commit": head,
                        "agy_conformance_source_sha256": verifier.conformance_source_sha256()}
    assert verifier.conformance_identity(strict=False)["agy_conformance_strict"] == "0"


def test_release_fails_an_executable_that_is_not_the_official_archive_member(
        verifier, evidence, obligations, release_io, tmp_path):
    """The record and catalog name another image, the official archive is unchanged: the
    extracted executable must be the recorded image (agent-harness#1937 B3)."""
    catalog_path = evidence / "agy_catalog.json"
    catalog = json.loads(catalog_path.read_text())
    for member in catalog["routes"]["linux-x64"]:
        member["image_sha256"] = "a" * 64
        record_path = evidence / "evidence" / member["record"]
        record = json.loads(record_path.read_text())
        record["image_sha256"] = "a" * 64
        for row in record["records"]:
            row["image_sha256"] = "a" * 64
            row["profile"]["image_sha256"] = "a" * 64
        record_path.write_text(json.dumps(record))
    catalog_path.write_text(json.dumps(catalog))
    report = _report(tmp_path / "conformance.xml", [(o, "pass") for o in obligations])
    with pytest.raises(ValueError, match="executable digest mismatch"):
        verifier.release(report, **_io(release_io))
