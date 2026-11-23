"""RRIMAGE SL-2: the recipe CLI ``review_runner_image.py plan|record|verify-receipt``.

Contract §3 and §4 (third bullet). ``plan`` runs under a patched ``subprocess`` and ``os`` that
refuse any process launch. ``record`` reads OCI layouts generated on disk from the templates in
``tests/fixtures/review_runner_layout``. ``verify-receipt`` runs against a synthetic checkout
holding the checked-in Containerfile and ``PIN.json``. Nothing builds, pulls or pushes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

import pytest

from phase_loop_runtime import review_runner_pin as rp

PKG_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PKG_ROOT.parent
SCRIPT = PKG_ROOT / "scripts" / "review_runner_image.py"
LAYOUT_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "review_runner_layout"
PIN_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "review_runner_pin"
CONTAINERFILE = "phase-loop-runtime/images/review-runner/Containerfile"
PIN_JSON = "phase-loop-runtime/tests/data/landlock-exec/PIN.json"
EVIDENCE = "plans/evidence/review-runner"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
SYNTHETIC_BUILDKIT = "sha256:" + "a" * 64

pytestmark = pytest.mark.skipif(not SCRIPT.is_file(),
                                reason="needs the repository's phase-loop-runtime/scripts")
needs_checkout = pytest.mark.skipif(
    not (REPO_ROOT / CONTAINERFILE).is_file() or not (REPO_ROOT / PIN_JSON).is_file(),
    reason="needs the repository checkout (Containerfile and PIN.json)")


@pytest.fixture(scope="module")
def cli():
    spec = importlib.util.spec_from_file_location("review_runner_image", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def template(name: str):
    return json.loads((LAYOUT_FIXTURES / name).read_text())


# -- generated OCI layouts ---------------------------------------------------------------------

class Layout:
    """An OCI image layout on disk: ``oci-layout``, ``index.json`` and ``blobs/sha256``."""

    def __init__(self, root: Path, *, commit: str = COMMIT, containerfile_sha256: str = "c" * 64,
                 layer: bytes = b"synthetic layer\n", config_extra: dict | None = None):
        self.root = root
        (root / "blobs" / "sha256").mkdir(parents=True)
        (root / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}')
        layer_digest = self.blob(layer)
        config = template("config.json")
        config["config"]["Labels"][rp.REVISION_LABEL] = commit
        config["config"]["Labels"][rp.CONTAINERFILE_LABEL] = containerfile_sha256
        config["rootfs"]["diff_ids"] = [layer_digest]
        config.update(config_extra or {})
        self.config_bytes = dump(config)
        manifest = template("manifest.json")
        manifest["config"].update(digest=self.blob(self.config_bytes), size=len(self.config_bytes))
        manifest["layers"][0].update(digest=layer_digest, size=len(layer))
        self.layer_digest = layer_digest
        self.manifest_bytes = dump(manifest)
        self.manifest_digest = self.blob(self.manifest_bytes)
        self.descriptors = [self.descriptor(OCI_MANIFEST, self.manifest_digest,
                                            len(self.manifest_bytes))]
        self.write_index()

    def blob(self, data: bytes) -> str:
        digest = sha(data)
        (self.root / "blobs" / "sha256" / digest).write_bytes(data)
        return "sha256:" + digest

    @staticmethod
    def descriptor(media_type: str, digest: str, size: int) -> dict:
        return {"mediaType": media_type, "digest": digest, "size": size,
                "annotations": {"org.opencontainers.image.ref.name": "latest"}}

    def write_index(self) -> None:
        index = {"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": self.descriptors}
        (self.root / "index.json").write_bytes(dump(index))


def build_meta(**overrides):
    meta = template("build-meta.json")
    meta["build"]["buildkit_image"] = f"docker.io/moby/buildkit:v0.18.2@{SYNTHETIC_BUILDKIT}"
    meta.update(overrides)
    return meta


def write_json(path: Path, value) -> Path:
    path.write_bytes(dump(value))
    return path


def run(cli, capsys, *argv):
    code = cli.main([str(part) for part in argv])
    out, err = capsys.readouterr()
    return code, out, err


# -- plan --------------------------------------------------------------------------------------

class _NoProcess(AssertionError):
    pass


@pytest.fixture
def no_subprocess(monkeypatch):
    """Refuse every process launch path for the duration of the test."""
    calls = []

    def refuse(name):
        def blocked(*args, **kwargs):
            calls.append(name)
            raise _NoProcess(name)
        return blocked

    for name in ("Popen", "run", "call", "check_call", "check_output", "getoutput",
                 "getstatusoutput"):
        monkeypatch.setattr(subprocess, name, refuse(f"subprocess.{name}"))
    for name in ("system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp",
                 "execv", "execve", "execvp", "execvpe", "spawnv", "spawnve"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, refuse(f"os.{name}"))
    return calls


@pytest.fixture
def pinned_buildkit(cli, monkeypatch):
    """A synthetic digest so ``plan`` tests do not depend on the recorded BuildKit digest."""
    monkeypatch.setattr(cli, "BUILDKIT_DIGEST", SYNTHETIC_BUILDKIT)


def plan_output(cli, capsys, no_subprocess):
    code, out, err = run(cli, capsys, "plan", "--source-commit", COMMIT)
    assert (code, err) == (0, "")
    assert no_subprocess == []
    return out


def commands(text: str) -> list[str]:
    """Command lines of the plan, with continuation lines joined and comments dropped."""
    joined = text.replace("\\\n", " ")
    return [line.strip() for line in joined.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def test_plan_prints_recipe_options(cli, capsys, no_subprocess, pinned_buildkit):
    out = plan_output(cli, capsys, no_subprocess)
    for needle in (
        f"git archive --format=tar {COMMIT}",
        "type=oci,dest=",
        "rewrite-timestamp=true",
        "--platform linux/amd64",
        "SOURCE_DATE_EPOCH",
        f"git show -s --format=%ct {COMMIT}",
        "--provenance=false",
        "--sbom=false",
        "--no-cache",
        f"--label org.opencontainers.image.revision={COMMIT}",
        '--label dev.consiliency.review-runner.containerfile-sha256="$CONTAINERFILE_SHA256"',
        f"git show {COMMIT}:{CONTAINERFILE}",
        "--build-context landlock-source=",
        "tarball/d945fdd060aab9ad9471845f4f8e78406a0ac841",
        "--driver docker-container",
    ):
        assert needle in out, needle
    builds = [line for line in commands(out) if "docker buildx build" in line]
    assert len(builds) == 2
    for attempt, line in enumerate(builds, start=1):
        argv = shlex.split(line.split("docker buildx build", 1)[1])
        for flag in ("--provenance=false", "--sbom=false", "--no-cache"):
            assert flag in argv
        assert argv[argv.index("--platform") + 1] == "linux/amd64"
        labels = [argv[i + 1] for i, token in enumerate(argv) if token == "--label"]
        assert [label.split("=", 1)[0] for label in labels] == [
            rp.REVISION_LABEL, rp.CONTAINERFILE_LABEL]
        output = argv[argv.index("--output") + 1]
        assert output.startswith("type=oci,dest=") and output.endswith(",rewrite-timestamp=true")
        assert f"attempt-{attempt}.tar" in output
        assert "--push" not in argv and "--load" not in argv


def test_plan_builder_is_digest_pinned_buildkit(cli, capsys, no_subprocess, pinned_buildkit):
    out = plan_output(cli, capsys, no_subprocess)
    images = re.findall(r"--driver-opt image=(\S+)", out)
    assert images == [f"docker.io/moby/buildkit:{cli.BUILDKIT_VERSION}@{SYNTHETIC_BUILDKIT}"]


def test_recorded_buildkit_pin(cli):
    """The checked-in BuildKit is named by digest, at v0.13.0 or later (§3.3)."""
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", cli.BUILDKIT_VERSION)
    assert match and tuple(map(int, match.groups())) >= (0, 13, 0)
    assert cli.BUILDKIT_REPOSITORY == "docker.io/moby/buildkit"
    assert isinstance(cli.BUILDKIT_DIGEST, str) and re.fullmatch(
        r"sha256:[0-9a-f]{64}", cli.BUILDKIT_DIGEST), "BuildKit digest is not recorded"
    assert cli.buildkit_image().endswith("@" + cli.BUILDKIT_DIGEST)


@pytest.mark.parametrize("version", ["v0.12.5", "v0.9.0", "0.16.0", "latest"])
def test_plan_refuses_buildkit_below_floor(cli, capsys, no_subprocess, pinned_buildkit,
                                           monkeypatch, version):
    monkeypatch.setattr(cli, "BUILDKIT_VERSION", version)
    code, out, err = run(cli, capsys, "plan", "--source-commit", COMMIT)
    assert (code, out) == (2, "") and "buildkit_version_unsupported" in err
    assert no_subprocess == []


@pytest.mark.parametrize("digest", [None, "", "sha256:" + "A" * 64, "sha256:abc"])
def test_plan_refuses_unpinned_buildkit(cli, capsys, no_subprocess, monkeypatch, digest):
    monkeypatch.setattr(cli, "BUILDKIT_DIGEST", digest)
    code, out, err = run(cli, capsys, "plan", "--source-commit", COMMIT)
    assert (code, out) == (2, "") and "buildkit_unpinned" in err


@pytest.mark.parametrize("commit", ["HEAD", "main", COMMIT[:12], COMMIT.upper(), COMMIT + "0"])
def test_plan_refuses_non_commit_source(cli, capsys, no_subprocess, pinned_buildkit, commit):
    code, out, err = run(cli, capsys, "plan", "--source-commit", commit)
    assert (code, out) == (2, "") and "source_commit_invalid" in err


def test_plan_has_no_push_or_ai_command(cli, capsys, no_subprocess, pinned_buildkit):
    out = plan_output(cli, capsys, no_subprocess)
    lowered = out.lower()
    for word in ("push", "skopeo", "regctl", "docker load", "ssh", "scp", "rsync", "--load"):
        assert word not in lowered, word
    for line in commands(out):
        tokens = re.split(r"[\s|;&()=\"']+", line)
        assert "ai" not in tokens, line
        assert not any(token.endswith("@ai") or token.startswith("ai:") for token in tokens), line


def test_plan_runs_no_process(cli, capsys, no_subprocess, pinned_buildkit):
    plan_output(cli, capsys, no_subprocess)
    source = SCRIPT.read_text()
    assert "import subprocess" not in source and "os.system" not in source


# -- record ------------------------------------------------------------------------------------

def assemble(cli, layout: Path, meta, tmp_path, capsys, *extra):
    meta_path = write_json(tmp_path / "meta.json", meta)
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    return run(cli, capsys, "record", "--layout", layout, "--meta", meta_path,
               "--repo-root", root, *extra), root


def refused(result, code, field=None):
    (status, out, err), root = result
    assert status == 2 and out == ""
    assert err.startswith("refused: ") and f" {code}: " in err
    if field is not None:
        assert err.rstrip().endswith(field)
    assert not (root / EVIDENCE / "pin-record.json").exists()
    assert not (root / EVIDENCE / "manifest.json").exists()


def test_record_refuses_nested_index_descriptor(cli, tmp_path, capsys):
    layout = Layout(tmp_path / "layout")
    nested = {"schemaVersion": 2, "mediaType": OCI_INDEX,
              "manifests": [layout.descriptor(OCI_MANIFEST, layout.manifest_digest,
                                              len(layout.manifest_bytes))]}
    nested_bytes = dump(nested)
    layout.descriptors = [layout.descriptor(OCI_INDEX, layout.blob(nested_bytes),
                                            len(nested_bytes))]
    layout.write_index()
    refused(assemble(cli, layout.root, build_meta(), tmp_path, capsys), "pin_index_refused")


def test_record_refuses_index_blob_behind_manifest_media_type(cli, tmp_path, capsys):
    layout = Layout(tmp_path / "layout")
    nested_bytes = dump({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": []})
    layout.descriptors = [layout.descriptor(OCI_MANIFEST, layout.blob(nested_bytes),
                                            len(nested_bytes))]
    layout.write_index()
    refused(assemble(cli, layout.root, build_meta(), tmp_path, capsys), "pin_index_refused")


def test_record_refuses_second_descriptor(cli, tmp_path, capsys):
    layout = Layout(tmp_path / "layout")
    other = Layout(tmp_path / "other", layer=b"another layer\n")
    layout.blob(other.manifest_bytes)
    layout.descriptors.append(layout.descriptor(OCI_MANIFEST, other.manifest_digest,
                                                len(other.manifest_bytes)))
    layout.write_index()
    refused(assemble(cli, layout.root, build_meta(), tmp_path, capsys),
            "pin_digest_mismatch", "index.json.manifests")


def test_record_refuses_empty_index(cli, tmp_path, capsys):
    layout = Layout(tmp_path / "layout")
    layout.descriptors = []
    layout.write_index()
    refused(assemble(cli, layout.root, build_meta(), tmp_path, capsys),
            "pin_digest_mismatch", "index.json.manifests")


@pytest.mark.parametrize("delta", [-1, 1])
def test_record_refuses_descriptor_size_mismatch(cli, tmp_path, capsys, delta):
    layout = Layout(tmp_path / "layout")
    layout.descriptors[0]["size"] += delta
    layout.write_index()
    refused(assemble(cli, layout.root, build_meta(), tmp_path, capsys),
            "pin_digest_mismatch", "index.json.manifests.0.size")


def test_record_refuses_descriptor_digest_mismatch(cli, tmp_path, capsys):
    layout = Layout(tmp_path / "layout")
    hex_ = layout.manifest_digest.split(":", 1)[1]
    blob = layout.root / "blobs" / "sha256" / hex_
    blob.write_bytes(layout.manifest_bytes.replace(b'"schemaVersion": 2', b'"schemaVersion":  2'))
    refused(assemble(cli, layout.root, build_meta(), tmp_path, capsys),
            "pin_digest_mismatch", "index.json.manifests.0.digest")


def test_record_refuses_descriptor_naming_absent_blob(cli, tmp_path, capsys):
    layout = Layout(tmp_path / "layout")
    layout.descriptors[0]["digest"] = "sha256:" + "9" * 64
    layout.write_index()
    refused(assemble(cli, layout.root, build_meta(), tmp_path, capsys),
            "pin_digest_mismatch", "index.json.manifests.0.digest")


class Checkout:
    """A synthetic repo root with the real Containerfile and PIN.json."""

    def __init__(self, root: Path):
        self.root = root
        for rel in (CONTAINERFILE, PIN_JSON):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / rel, root / rel)
        self.pin = json.loads((root / PIN_JSON).read_text())
        self.containerfile_sha256 = sha((root / CONTAINERFILE).read_bytes())

    def meta(self, **overrides):
        meta = build_meta(**overrides)
        meta["source"]["containerfile_sha256"] = self.containerfile_sha256
        meta["helper"] = {"sha256": self.pin["helper_sha256"],
                          "source_commit": self.pin["commit"]}
        return meta

    def layout(self, path: Path, **kwargs) -> Layout:
        return Layout(path, containerfile_sha256=self.containerfile_sha256, **kwargs)

    def record(self, cli, capsys, layout: Path, meta, *extra):
        meta_path = write_json(self.root.parent / "meta.json", meta)
        return run(cli, capsys, "record", "--layout", layout, "--meta", meta_path,
                   "--repo-root", self.root, *extra)

    def committed(self):
        return json.loads((self.root / EVIDENCE / "pin-record.json").read_text())


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return Checkout(root)


@needs_checkout
def test_record_commits_single_manifest_blob(cli, tmp_path, capsys, checkout):
    layout = checkout.layout(tmp_path / "layout")
    archive = tmp_path / "attempt-1.tar"
    archive.write_bytes(b"stand-in archive bytes")
    code, out, err = checkout.record(cli, capsys, layout.root, checkout.meta(),
                                     "--archive", archive)
    assert (code, err) == (0, "")
    evidence = checkout.root / EVIDENCE
    assert (evidence / "manifest.json").read_bytes() == layout.manifest_bytes
    assert (evidence / "config.json").read_bytes() == layout.config_bytes
    assert not (evidence / "index.json").exists()
    record = checkout.committed()
    assert record["status"] == "built" and record["image"] is None and record["receipt"] is None
    assert record["artifact"]["manifest_digest"] == layout.manifest_digest
    assert record["artifact"]["manifest_size"] == len(layout.manifest_bytes)
    assert record["artifact"]["oci_archive_sha256"] == sha(b"stand-in archive bytes")
    assert record["build"]["first_manifest_digest"] == layout.manifest_digest
    verdict = rp.validate_pin_record(record, checkout.root)
    assert verdict.status == "built"
    assert f"record_sha256={verdict.record_sha256}" in out


@needs_checkout
def test_record_reproduced_from_second_layout(cli, tmp_path, capsys, checkout):
    first = checkout.layout(tmp_path / "layout-1")
    second = checkout.layout(tmp_path / "layout-2")
    code, _, err = checkout.record(cli, capsys, first.root, checkout.meta(),
                                   "--second-layout", second.root)
    assert (code, err) == (0, "")
    assert checkout.committed()["build"]["reproduced"] == {
        "attempted": True, "second_manifest_digest": first.manifest_digest, "equal": True,
        "differing_layers": [], "deferred_finding": None}


@needs_checkout
def test_record_reproduction_mismatch_needs_deferred_finding(cli, tmp_path, capsys, checkout):
    first = checkout.layout(tmp_path / "layout-1")
    second = checkout.layout(tmp_path / "layout-2", layer=b"different layer\n")
    code, _, err = checkout.record(cli, capsys, first.root, checkout.meta(),
                                   "--second-layout", second.root)
    assert code == 2 and "P10 pin_reproducibility_inconsistent" in err
    assert not (checkout.root / EVIDENCE / "pin-record.json").exists()
    code, _, err = checkout.record(cli, capsys, first.root, checkout.meta(),
                                   "--second-layout", second.root,
                                   "--deferred-finding", "Consiliency/agent-harness#1")
    assert (code, err) == (0, "")
    reproduced = checkout.committed()["build"]["reproduced"]
    assert reproduced["equal"] is False
    assert reproduced["second_manifest_digest"] == second.manifest_digest
    assert reproduced["differing_layers"] == sorted([first.layer_digest, second.layer_digest])
    assert reproduced["deferred_finding"] == "Consiliency/agent-harness#1"


@needs_checkout
def test_record_config_only_reproduction_difference_is_named(cli, tmp_path, capsys, checkout):
    """Same layers, different config: the manifest digests differ but no layer does.

    Contract §2 P10 ("`equal=false` implies a non-empty `differing_layers`") and the schema
    (``differing_layers`` items are layer digests) leave no truthful form for this case, so
    ``record`` refuses before writing and names the field that cannot be filled."""
    first = checkout.layout(tmp_path / "layout-1")
    second = checkout.layout(tmp_path / "layout-2",
                             config_extra={"history": [{"comment": "second attempt"}]})
    assert first.layer_digest == second.layer_digest
    assert first.manifest_digest != second.manifest_digest
    code, out, err = checkout.record(cli, capsys, first.root, checkout.meta(),
                                     "--second-layout", second.root,
                                     "--deferred-finding", "Consiliency/agent-harness#1")
    assert code == 2 and out == ""
    assert err.rstrip().endswith(
        "P10 pin_reproducibility_inconsistent: build.reproduced.differing_layers")
    assert not (checkout.root / EVIDENCE).exists()


def _evidence_bytes(checkout):
    evidence = checkout.root / EVIDENCE
    return {name: (evidence / name).read_bytes()
            for name in ("pin-record.json", "manifest.json", "config.json")}


@pytest.fixture
def recorded(cli, tmp_path, capsys, checkout):
    layout = checkout.layout(tmp_path / "layout-a")
    code, _, err = checkout.record(cli, capsys, layout.root, checkout.meta())
    assert (code, err) == (0, "")
    return checkout


@needs_checkout
def test_record_rerun_without_replace_preserves_evidence(cli, tmp_path, capsys, recorded):
    before = _evidence_bytes(recorded)
    other = recorded.layout(tmp_path / "layout-b", layer=b"other layer\n")
    code, out, err = recorded.record(cli, capsys, other.root, recorded.meta())
    assert code == 2 and out == "" and "evidence_exists" in err
    assert _evidence_bytes(recorded) == before


@needs_checkout
def test_record_rejected_rerun_preserves_evidence(cli, tmp_path, capsys, recorded):
    """A replacement that fails strict P4 leaves all three evidence files byte-identical."""
    before = _evidence_bytes(recorded)
    other = Layout(tmp_path / "layout-b", containerfile_sha256="c" * 64)
    meta = recorded.meta()
    meta["source"]["containerfile_sha256"] = "c" * 64
    code, out, err = recorded.record(cli, capsys, other.root, meta, "--replace")
    assert code == 2 and out == "" and "P4 pin_containerfile_stale" in err
    assert _evidence_bytes(recorded) == before
    leftovers = sorted(p.name for p in (recorded.root / EVIDENCE).iterdir())
    assert leftovers == ["config.json", "manifest.json", "pin-record.json"]


@needs_checkout
def test_record_replace_publishes_consistent_set(cli, tmp_path, capsys, recorded):
    other = recorded.layout(tmp_path / "layout-b", layer=b"other layer\n")
    code, _, err = recorded.record(cli, capsys, other.root, recorded.meta(), "--replace")
    assert (code, err) == (0, "")
    after = _evidence_bytes(recorded)
    assert after["manifest.json"] == other.manifest_bytes
    assert after["config.json"] == other.config_bytes
    record = json.loads(after["pin-record.json"])
    assert record["artifact"]["manifest_digest"] == other.manifest_digest
    assert rp.validate_pin_record(record, recorded.root).status == "built"


@needs_checkout
def test_record_publication_failure_restores_evidence(cli, tmp_path, capsys, recorded,
                                                      monkeypatch):
    """If the last replacement fails, the earlier ones are rolled back."""
    before = _evidence_bytes(recorded)
    other = recorded.layout(tmp_path / "layout-b", layer=b"other layer\n")
    real_replace = os.replace

    def failing_replace(src, dst, *args, **kwargs):
        if Path(dst).name == "pin-record.json" and Path(src).name.startswith(".pin-record.json."):
            raise OSError("injected publication failure")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="injected"):
        recorded.record(cli, capsys, other.root, recorded.meta(), "--replace")
    monkeypatch.undo()
    assert _evidence_bytes(recorded) == before
    leftovers = sorted(p.name for p in (recorded.root / EVIDENCE).iterdir())
    assert leftovers == ["config.json", "manifest.json", "pin-record.json"]


@needs_checkout
def test_record_refuses_labels_that_differ_from_source(cli, tmp_path, capsys, checkout):
    layout = Layout(tmp_path / "layout", containerfile_sha256="c" * 64)
    code, _, err = checkout.record(cli, capsys, layout.root, checkout.meta())
    assert code == 2 and "P9 pin_source_mismatch" in err
    assert not (checkout.root / EVIDENCE / "pin-record.json").exists()


# -- verify-receipt ----------------------------------------------------------------------------

def receipt_for(record):
    receipt = json.loads((PIN_FIXTURES / "receipt.json").read_text())
    digest = record["artifact"]["manifest_digest"]
    receipt.update({
        "input_archive_sha256": record["artifact"]["oci_archive_sha256"],
        "registry_manifest_digest": digest,
        "docker_content_digest": digest,
        "raw_manifest_sha256": digest.split(":", 1)[1],
        "config_digest": record["platform"]["config_digest"],
        "helper_sha256": record["helper"]["sha256"],
    })
    return receipt


@pytest.fixture
def built(cli, tmp_path, capsys, checkout):
    layout = checkout.layout(tmp_path / "layout")
    code, _, err = checkout.record(cli, capsys, layout.root, checkout.meta())
    assert (code, err) == (0, "")
    return checkout


def verify(cli, capsys, checkout, receipt):
    path = write_json(checkout.root.parent / "receipt.json", receipt)
    return run(cli, capsys, "verify-receipt", "--receipt", path,
               "--registry", "registry.example.test:5000",
               "--repository", "openshell/review-runner",
               "--recorded-at", "2026-11-23T12:00:00Z", "--repo-root", checkout.root)


@needs_checkout
def test_verify_receipt_promotes_to_pinned(cli, capsys, built):
    code, out, err = verify(cli, capsys, built, receipt_for(built.committed()))
    assert (code, err) == (0, "")
    record = built.committed()
    assert record["status"] == "pinned"
    assert record["image"]["reference"] == (
        "registry.example.test:5000/openshell/review-runner@"
        + record["artifact"]["manifest_digest"])
    verdict = rp.validate_pin_record(record, built.root)
    assert verdict.pinned and f"record_sha256={verdict.record_sha256}" in out


OTHER_DIGEST = "sha256:" + "e" * 64
P6_MISMATCHES = [
    ("registry_manifest_digest", OTHER_DIGEST, "pin_receipt_mismatch"),
    ("docker_content_digest", OTHER_DIGEST, "pin_receipt_mismatch"),
    ("raw_manifest_sha256", "e" * 64, "pin_receipt_mismatch"),
    ("raw_manifest_media_type", "application/vnd.docker.distribution.manifest.v2+json",
     "pin_receipt_mismatch"),
    ("config_digest", OTHER_DIGEST, "pin_receipt_mismatch"),
    ("helper_sha256", "e" * 64, "pin_receipt_mismatch"),
    ("input_archive_sha256", "e" * 64, "pin_receipt_mismatch"),
    # Schema constants: the schema (P1) refuses these before P6 compares them.
    ("os", "windows", "pin_schema_invalid"),
    ("architecture", "arm64", "pin_schema_invalid"),
    ("container_state", "running", "pin_schema_invalid"),
    ("started_at_zero", False, "pin_schema_invalid"),
    ("entrypoint_started", True, "pin_schema_invalid"),
    ("raw_manifest_media_type", OCI_INDEX, "pin_index_refused"),
]


def assert_left_built(checkout, before: bytes, result, code, field=None):
    status, out, err = result
    assert status == 2 and out == ""
    assert f" {code}: " in err
    if field is not None:
        assert err.rstrip().endswith(field)
    assert (checkout.root / EVIDENCE / "pin-record.json").read_bytes() == before
    assert json.loads(before)["status"] == "built"


@needs_checkout
@pytest.mark.parametrize("key,value,code", P6_MISMATCHES,
                         ids=[f"{key}-{code}" for key, _, code in P6_MISMATCHES])
def test_verify_receipt_refuses_p6_mismatch(cli, capsys, built, key, value, code):
    before = (built.root / EVIDENCE / "pin-record.json").read_bytes()
    receipt = receipt_for(json.loads(before))
    receipt[key] = value
    result = verify(cli, capsys, built, receipt)
    assert_left_built(built, before, result, code,
                      f"receipt.{key}" if code == "pin_receipt_mismatch" else None)


@needs_checkout
def test_verify_receipt_refuses_receipt_pulled_after_record(cli, capsys, built):
    before = (built.root / EVIDENCE / "pin-record.json").read_bytes()
    receipt = receipt_for(json.loads(before))
    receipt["pulled_at"] = "2026-11-24T00:00:00Z"
    assert_left_built(built, before, verify(cli, capsys, built, receipt),
                      "pin_receipt_mismatch", "recorded_at")


def _rewrite_config(checkout, mutate):
    """Replace the committed config and re-chain manifest and record so only one P9 rule breaks."""
    evidence = checkout.root / EVIDENCE
    config = json.loads((evidence / "config.json").read_bytes())
    mutate(config)
    config_bytes = dump(config)
    manifest = json.loads((evidence / "manifest.json").read_bytes())
    manifest["config"].update(digest="sha256:" + sha(config_bytes), size=len(config_bytes))
    manifest_bytes = dump(manifest)
    (evidence / "config.json").write_bytes(config_bytes)
    (evidence / "manifest.json").write_bytes(manifest_bytes)
    record = checkout.committed()
    digest = "sha256:" + sha(manifest_bytes)
    record["artifact"].update(manifest_digest=digest, manifest_size=len(manifest_bytes))
    record["platform"]["config_digest"] = "sha256:" + sha(config_bytes)
    record["build"]["first_manifest_digest"] = digest
    (evidence / "pin-record.json").write_bytes(dump(record))


def _p9_manifest_bytes(checkout):
    path = checkout.root / EVIDENCE / "manifest.json"
    path.write_bytes(path.read_bytes() + b" ")


def _p9_manifest_size(checkout):
    evidence = checkout.root / EVIDENCE
    record = checkout.committed()
    record["artifact"]["manifest_size"] += 1
    (evidence / "pin-record.json").write_bytes(dump(record))


def _p9_first_digest(checkout):
    record = checkout.committed()
    record["build"]["first_manifest_digest"] = OTHER_DIGEST
    (checkout.root / EVIDENCE / "pin-record.json").write_bytes(dump(record))


def _p9_config_bytes(checkout):
    path = checkout.root / EVIDENCE / "config.json"
    path.write_bytes(path.read_bytes() + b" ")


def _p9_manifest_config_digest(checkout):
    evidence = checkout.root / EVIDENCE
    record = checkout.committed()
    record["platform"]["config_digest"] = OTHER_DIGEST
    (evidence / "pin-record.json").write_bytes(dump(record))


def _label(name, value):
    def mutate(config):
        config["config"]["Labels"][name] = value
    return lambda checkout: _rewrite_config(checkout, mutate)


def _config_platform(key, value):
    def mutate(config):
        config[key] = value
    return lambda checkout: _rewrite_config(checkout, mutate)


P9_MISMATCHES = [
    ("manifest-bytes", _p9_manifest_bytes, "pin_digest_mismatch", "artifact.manifest_digest"),
    ("manifest-size", _p9_manifest_size, "pin_digest_mismatch", "artifact.manifest_size"),
    ("first-manifest-digest", _p9_first_digest, "pin_digest_mismatch",
     "build.first_manifest_digest"),
    ("config-bytes", _p9_config_bytes, "pin_digest_mismatch", "artifact.config_path"),
    ("manifest-config-descriptor", _p9_manifest_config_digest, "pin_digest_mismatch",
     "platform.config_digest"),
    ("config-os", _config_platform("os", "freebsd"), "pin_digest_mismatch", "platform.os"),
    ("config-architecture", _config_platform("architecture", "arm64"), "pin_digest_mismatch",
     "platform.architecture"),
    ("revision-label", _label(rp.REVISION_LABEL, "f" * 40), "pin_source_mismatch",
     "source.commit"),
    ("containerfile-label", _label(rp.CONTAINERFILE_LABEL, "f" * 64), "pin_source_mismatch",
     "source.containerfile_sha256"),
]


@needs_checkout
@pytest.mark.parametrize("mutate,code,field", [row[1:] for row in P9_MISMATCHES],
                         ids=[row[0] for row in P9_MISMATCHES])
def test_verify_receipt_refuses_p9_mismatch(cli, capsys, built, mutate, code, field):
    """The committed bytes disagree with the record; the receipt matches the record's digests,
    so P9 itself is what refuses, and the record stays ``built``."""
    mutate(built)
    before = (built.root / EVIDENCE / "pin-record.json").read_bytes()
    result = verify(cli, capsys, built, receipt_for(json.loads(before)))
    assert_left_built(built, before, result, code, field)


@needs_checkout
def test_verify_receipt_refuses_already_pinned(cli, capsys, built):
    assert verify(cli, capsys, built, receipt_for(built.committed()))[0] == 0
    before = (built.root / EVIDENCE / "pin-record.json").read_bytes()
    status, _, err = verify(cli, capsys, built, receipt_for(json.loads(before)))
    assert status == 2 and "pin_schema_invalid: status" in err
    assert (built.root / EVIDENCE / "pin-record.json").read_bytes() == before


@needs_checkout
def test_refusal_messages_carry_no_values(cli, capsys, built):
    receipt = receipt_for(built.committed())
    receipt["helper_sha256"] = "e" * 64
    _, out, err = verify(cli, capsys, built, receipt)
    for text in (out, err):
        assert "e" * 64 not in text
        assert not re.search(r"[0-9a-f]{40,}", text)
