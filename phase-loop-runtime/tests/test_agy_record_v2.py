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
