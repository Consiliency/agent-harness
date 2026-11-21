"""The verifier's ``--intake`` and ``--catalog-pr`` modes and the provenance workflow (ROLLJOB-detail §4.2, §4.4, §6.4).

Nothing here reaches the network: the GitHub API and the upstream archives are fakes, the
catalog and its records live in a temporary directory, ``--catalog-pr`` reads a local git
repository, and the job key is generated per run with ``ssh-keygen``.
"""
from __future__ import annotations

import gzip
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import textwrap
from urllib.error import HTTPError

import pytest
import yaml

from phase_loop_runtime import agy_catalog_policy as policy

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_qualified_agy_image.py"
REPO = Path(__file__).resolve().parents[2]
PROVENANCE = REPO / ".github" / "workflows" / "agy-catalog-provenance.yml"
RELEASES = f"https://api.github.com/repos/{policy.UPSTREAM_REPO}/releases"
DOWNLOAD = f"https://github.com/{policy.UPSTREAM_REPO}/releases/download/"
ASSET = policy.ASSET
NOW = 1_800_000_000.0
DAY = 86_400
INTAKE = policy.AppIdentity(app_id=11, bot_user_id=111)
PROMOTION = policy.AppIdentity(app_id=22, bot_user_id=222)
HAS_SSH_KEYGEN = shutil.which("ssh-keygen") is not None

pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="the verifier is repository source")
needs_ssh_keygen = pytest.mark.skipif(not HAS_SSH_KEYGEN, reason="ssh-keygen is not installed (hosted CI has it)")


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_qualified_agy_image_promotion", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive(image: bytes) -> bytes:
    """A deterministic archive (no gzip time stamp), so a writer's copy of upstream's bytes is
    byte-for-byte upstream's."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as bundle:
        info = tarfile.TarInfo("antigravity")
        info.size = len(image)
        bundle.addfile(info, io.BytesIO(image))
    return gzip.compress(buffer.getvalue(), mtime=0)


def _iso(timestamp):
    return policy.rfc3339(timestamp)


def _qci():
    from phase_loop_runtime.agy_qualification import seat_qci
    return seat_qci()


def _record(version, image_sha256, asset_sha256, *, qci=None, help_sha256="e" * 64):
    record = json.loads((REPO / "plans/evidence/agy-1.5.3-linux-x64-qualification.json").read_text())
    url = f"https://github.com/{policy.UPSTREAM_REPO}/releases/tag/{version}"
    record.update(release_version=version, image_sha256=image_sha256, help_sha256=help_sha256,
                  upstream_asset_sha256=asset_sha256, upstream_release_url=url, qci=qci or _qci(),
                  qualified_under="0.7.38", signatures=[])
    record["upstream"] = {"asset_sha256": asset_sha256, "release_url": url, "attestation": "present_unverified",
                          "second_channel": "match"}
    for row in record["records"]:
        row.update(image_sha256=image_sha256, help_sha256=help_sha256)
        row["profile"] = dict(row["profile"], image_sha256=image_sha256)
    return record


class Upstream:
    """The GitHub API (issues, releases, pull requests) and the archive downloads."""

    def __init__(self):
        self.releases, self.blobs, self.issues, self.calls, self.downloads = {}, {}, {}, [], []

    def add(self, version, image: bytes, *, published_at=None, prerelease=False, digest=None):
        archive = _archive(image)
        url = f"{DOWNLOAD}{version}/{ASSET}"
        self.blobs[url] = archive
        self.releases[version] = {
            "tag_name": version, "draft": False, "prerelease": prerelease,
            "published_at": published_at or _iso(NOW - DAY),
            "assets": [{"name": ASSET, "browser_download_url": url,
                        "digest": digest or "sha256:" + sha256(archive).hexdigest()}]}
        return sha256(image).hexdigest(), sha256(archive).hexdigest()

    def fetch(self, url):
        self.calls.append(url)
        if url.startswith(f"{RELEASES}/tags/"):
            version = url.rsplit("/", 1)[1]
            if version not in self.releases:
                raise HTTPError(url, 404, "Not Found", {}, None)
            return json.loads(json.dumps(self.releases[version]))
        if url.startswith("https://api.github.com/repos/Consiliency/agent-harness/issues/"):
            return json.loads(json.dumps(self.issues[int(url.rsplit("/", 1)[1])]))
        raise AssertionError(f"unexpected read {url}")

    def download(self, url, target):
        self.downloads.append(url)
        Path(target).write_bytes(self.blobs[url])


def _attestation(**overrides):
    document = {"schema": policy.ATTESTATION_SCHEMA, "status": "attested",
                "intake_app": {"app_id": INTAKE.app_id, "bot_user_id": INTAKE.bot_user_id},
                "promotion_app": {"app_id": PROMOTION.app_id, "bot_user_id": PROMOTION.bot_user_id},
                "main_ruleset": {"id": 5, "target": "refs/heads/main", "enforcement": "active", "bypass_actors": [],
                                 "strict_required_status_checks": True,
                                 "required_checks": ["agy catalog provenance", "agy catalog contract"]},
                "catalog_ruleset": {"id": 6, "target": "refs/heads/agy-catalog/**", "enforcement": "active",
                                    "rules": ["creation", "update", "deletion"],
                                    "bypass_actors": [{"actor_type": "Integration", "actor_id": PROMOTION.app_id,
                                                       "bypass_mode": "always"}]},
                "promotion_environment": {"name": "agy-promotion", "branches": ["main"], "required_reviewers": 0,
                                          "admin_bypass": False},
                "attested_by": "owner", "attested_at": "2026-11-21T00:00:00Z"}
    document.update(overrides)
    return json.dumps(document)


# ------------------------------------------------------------------------------ --intake

class Intake:
    """A checkout whose catalog, records, signer list and attestation are temporary files."""

    def __init__(self, tmp_path, monkeypatch, members=(("1.5.3", False, 30),)):
        self.tmp, self.verifier, self.upstream = tmp_path, _load_verifier(), Upstream()
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        catalog_members = []
        for version, pinned, age_days in members:
            image, asset = self.upstream.add(version, f"member {version}".encode(), published_at=_iso(NOW - age_days * DAY))
            record = _record(version, image, asset)
            (evidence / f"agy-{version}-linux-x64-qualification.json").write_text(json.dumps(record, indent=2))
            catalog_members.append({**policy.candidate_member(record), "published_at": _iso(NOW - age_days * DAY),
                                    "pinned": pinned})
        catalog = tmp_path / "agy_catalog.json"
        catalog.write_text(policy.render_catalog(catalog_members))
        self.attestation = tmp_path / "attestation.json"
        self.attestation.write_text(_attestation())
        self.signers = tmp_path / "agy-allowed-signers"
        self.signers.write_text("# no key\n")
        self.key = None
        if HAS_SSH_KEYGEN:
            keys = tmp_path / "keys"
            keys.mkdir(mode=0o700)
            for name in ("job", "other"):
                subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(keys / name)],
                               check=True, capture_output=True)
            kind, blob = (keys / "job.pub").read_text().split()[:2]
            self.signers.write_text(f'agy-watch namespaces="agy-qualification" {kind} {blob}\n')
            self.key, self.other_key = keys / "job", keys / "other"
        for name, value in (("CATALOG", catalog), ("EVIDENCE", evidence), ("ATTESTATION_FILE", self.attestation),
                            ("ALLOWED_SIGNERS_FILE", self.signers)):
            monkeypatch.setattr(self.verifier, name, value)
        self.out = tmp_path / "out"
        self.next = 500

    def release(self, version, image=None, **kwargs):
        return self.upstream.add(version, image or f"agy {version}".encode(), **kwargs)

    def signed(self, version, *, key=None, image_sha256=None, **record_kwargs):
        """A record for ``version`` (released upstream if it is not yet), signed with the job key."""
        if version not in self.upstream.releases:
            self.release(version)
        archive = self.upstream.blobs[f"{DOWNLOAD}{version}/{ASSET}"]
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            image = sha256(bundle.extractfile("antigravity").read()).hexdigest()
        record = _record(version, image_sha256 or image, sha256(archive).hexdigest(), **record_kwargs)
        return policy.sign_record(record, key or self.key)

    def issue(self, body, *, user=None, via=None):
        self.next += 1
        self.upstream.issues[self.next] = {
            "number": self.next, "body": body, "state": "open",
            "user": user if user is not None else {"login": "agy-intake[bot]", "id": INTAKE.bot_user_id, "type": "Bot"},
            "performed_via_github_app": via if via is not None else {"id": INTAKE.app_id, "slug": "agy-intake"}}
        return self.next

    def run(self, number, **kwargs):
        shutil.rmtree(self.out, ignore_errors=True)
        return self.verifier.intake(number, self.out, fetch=self.upstream.fetch, download=self.upstream.download,
                                    environ={"GITHUB_RUN_ID": "555", "GITHUB_REPOSITORY": "Consiliency/agent-harness"},
                                    now=NOW, base_sha="a" * 40, **kwargs)


@pytest.fixture
def intake(tmp_path, monkeypatch):
    return Intake(tmp_path, monkeypatch)


@pytest.mark.parametrize("user,via", [
    ({"login": "someone", "id": 9, "type": "User"}, {}),                                   # a person
    ({"login": "other[bot]", "id": 777, "type": "Bot"}, {"id": 33}),                      # another App
    ({"login": "agy-intake[bot]", "id": 112, "type": "Bot"}, {"id": INTAKE.app_id}),      # matching login, other id
    ({"login": "agy-intake[bot]", "id": INTAKE.bot_user_id, "type": "Bot"}, {}),         # no App object
])
def test_an_issue_not_created_by_the_intake_app_is_ignored(intake, user, via):
    number = intake.issue("anything at all", user=user, via=via or {"none": True})
    if via == {}:
        intake.upstream.issues[number]["performed_via_github_app"] = None
    decision = intake.run(number)
    assert decision["class"] == "ignored" and decision["issue"] == number
    assert sorted(p.name for p in intake.out.iterdir()) == ["decision.json"]
    assert intake.upstream.calls == [f"https://api.github.com/repos/Consiliency/agent-harness/issues/{number}"]


def test_with_an_unattested_file_every_issue_is_ignored(intake):
    intake.attestation.write_text((REPO / policy.ATTESTATION_PATH).read_text())
    assert intake.run(intake.issue("x"))["class"] == "ignored"


@needs_ssh_keygen
def test_one_new_newest_release_is_auto(intake):
    record = intake.signed("1.6.0")
    number = intake.issue(policy.render_intake(record))
    decision = intake.run(number)
    assert decision["class"] == "auto" and decision["reasons"] == [] and decision["version"] == "1.6.0"
    assert (decision["issue"], decision["run_id"], decision["base_sha"]) == (number, "555", "a" * 40)
    files = {p.name: p.read_bytes() for p in intake.out.iterdir()}
    assert sorted(files) == ["agy-1.6.0-linux-x64-qualification.json", "agy_catalog.json", "decision.json"]
    assert decision["record_sha256"] == sha256(files["agy-1.6.0-linux-x64-qualification.json"]).hexdigest()
    assert decision["catalog_sha256"] == sha256(files["agy_catalog.json"]).hexdigest()
    built = policy.parse_catalog(files["agy_catalog.json"].decode())
    assert [m["release_version"] for m in built] == ["1.5.3", "1.6.0"]
    # published_at is upstream's (the API), never the submission's
    assert built[-1]["published_at"] == intake.upstream.releases["1.6.0"]["published_at"]
    assert json.loads(files["agy-1.6.0-linux-x64-qualification.json"]) == record
    assert json.loads((intake.out / "decision.json").read_text()) == decision
    # every upstream read went to the fixed upstream
    assert all(url.startswith(RELEASES) for url in intake.upstream.calls[1:])
    assert intake.upstream.downloads == [f"{DOWNLOAD}1.6.0/{ASSET}"]


@needs_ssh_keygen
def test_auto_drops_an_aged_member_and_keeps_a_pinned_one(tmp_path, monkeypatch):
    intake = Intake(tmp_path, monkeypatch, members=(("1.5.0", True, 60), ("1.5.1", False, 50),
                                                    ("1.5.2", False, 40), ("1.5.3", False, 30)))
    decision = intake.run(intake.issue(policy.render_intake(intake.signed("1.6.0"))))
    assert decision["class"] == "auto"
    built = policy.parse_catalog((intake.out / "agy_catalog.json").read_text())
    assert [m["release_version"] for m in built] == ["1.5.0", "1.5.2", "1.5.3", "1.6.0"]
    assert built[0]["pinned"] is True


def _refusal_cases():
    def malformed(intake):
        return "not an intake body"

    def header(intake):
        return policy.render_intake(intake.signed("1.6.0")).replace("agy-intake.v1 1.6.0", "agy-intake.v1 1.6.1", 1)

    def oversize(intake):
        body = policy.render_intake(intake.signed("1.6.0"))
        return body + " " * policy.MAX_RECORD_BYTES

    def unsigned(intake):
        record = intake.signed("1.6.0")
        return policy.render_intake(dict(record, signatures=[]))

    def unenrolled(intake):
        return policy.render_intake(intake.signed("1.6.0", key=intake.other_key))

    def altered(intake):
        record = intake.signed("1.6.0")
        record["qualified_under"] = "9.9.9"
        return policy.render_intake(record)

    def stale_qci(intake):
        return policy.render_intake(intake.signed("1.6.0", qci="0" * 64))

    def withdrawn(intake):
        record = intake.signed("1.6.0")
        intake.upstream.releases["1.6.0"]["assets"][0]["digest"] = "sha256:" + "1" * 64
        return policy.render_intake(record)

    def other_member(intake):
        # the asset digest is upstream's, but the record claims another member digest
        return policy.render_intake(intake.signed("1.6.0", image_sha256="f" * 64))

    def prerelease(intake):
        record = intake.signed("1.6.0")
        intake.upstream.releases["1.6.0"]["prerelease"] = True
        return policy.render_intake(record)

    return {"malformed": (malformed, "body_malformed"), "header": (header, "body_malformed"),
            "oversize": (oversize, "body_malformed"), "unsigned": (unsigned, "no_verified_signer"),
            "unenrolled": (unenrolled, "no_verified_signer"), "altered": (altered, "no_verified_signer"),
            "stale_qci": (stale_qci, "record_qci_stale"), "withdrawn": (withdrawn, "upstream_mismatch"),
            "other_member": (other_member, "upstream_mismatch"), "prerelease": (prerelease, "upstream_mismatch")}


@needs_ssh_keygen
@pytest.mark.parametrize("case", sorted(_refusal_cases()))
def test_each_refusal(intake, case):
    make, reason = _refusal_cases()[case]
    decision = intake.run(intake.issue(make(intake)))
    assert decision["class"] == "refused" and decision["reasons"][0].startswith(reason), decision
    assert sorted(p.name for p in intake.out.iterdir()) == ["decision.json"]


@needs_ssh_keygen
@pytest.mark.parametrize("version,reason", [("1.5.3", "already a member"), ("1.4.0", "not the newest")])
def test_an_existing_or_older_version_is_manual(intake, monkeypatch, version, reason):
    seen = []
    real_candidate, real_build = policy.candidate_member, policy.build_catalog
    monkeypatch.setattr(policy, "candidate_member", lambda record: seen.append("candidate") or real_candidate(record))

    def build(*args, **kwargs):
        seen.append("build")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(policy, "build_catalog", build)
    if version == "1.5.3":
        record = policy.sign_record(json.loads(
            (intake.verifier.EVIDENCE / "agy-1.5.3-linux-x64-qualification.json").read_text()), intake.key)
    else:
        record = intake.signed(version)
    decision = intake.run(intake.issue(policy.render_intake(record)))
    assert decision["class"] == "manual" and reason in decision["reasons"][0]
    assert seen[0] == "candidate" and "build" in seen  # validity first; eligibility is build_catalog's
    assert sorted(p.name for p in intake.out.iterdir()) == ["decision.json"]


@needs_ssh_keygen
def test_an_upstream_outage_writes_no_decision(intake):
    record = intake.signed("1.6.0")
    number = intake.issue(policy.render_intake(record))

    def down(url, target):
        raise OSError("network down")

    with pytest.raises(OSError):
        intake.verifier.intake(number, intake.out, fetch=intake.upstream.fetch, download=down,
                               environ={"GITHUB_RUN_ID": "555"}, now=NOW, base_sha="a" * 40)
    assert not (intake.out / "decision.json").exists()


def test_a_pull_request_is_never_an_intake(intake):
    number = intake.issue("x")
    intake.upstream.issues[number]["pull_request"] = {"url": "..."}
    assert intake.run(number)["class"] == "ignored"


# --------------------------------------------------------------------------- --catalog-pr

class Repo:
    """A local git repository holding the catalog and its records."""

    def __init__(self, tmp_path, upstream):
        self.path, self.upstream = tmp_path / "repo", upstream
        self.path.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "w@example.invalid")
        self.git("config", "user.name", "writer")
        self.git("config", "commit.gpgsign", "false")
        members = []
        for version in ("1.5.2", "1.5.3"):
            image, asset = upstream.add(version, f"member {version}".encode())
            record = _record(version, image, asset)
            self.write(f"plans/evidence/agy-{version}-linux-x64-qualification.json", json.dumps(record, indent=2))
            members.append({**policy.candidate_member(record),
                            "published_at": upstream.releases[version]["published_at"], "pinned": False})
        self.write(policy.CATALOG_PATH, policy.render_catalog(members))
        self.write("README.md", "hello\n")
        self.base = self.commit("base")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.path), *args], check=True, capture_output=True).stdout

    def write(self, rel, text):
        path = self.path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def members(self):
        return policy.parse_catalog((self.path / policy.CATALOG_PATH).read_text())

    def set_members(self, members):
        self.write(policy.CATALOG_PATH, policy.render_catalog(members))

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").decode().strip()

    def add_member(self, version, image: bytes, *, upstream_image=None):
        """A writer's member for ``version``; upstream serves ``upstream_image`` (default: the same)."""
        archive_image = upstream_image if upstream_image is not None else image
        self.upstream.add(version, archive_image)
        digest, asset = sha256(image).hexdigest(), sha256(_archive(image)).hexdigest()
        record = _record(version, digest, asset)
        self.write(f"plans/evidence/agy-{version}-linux-x64-qualification.json", json.dumps(record, indent=2))
        member = {**policy.candidate_member(record), "published_at": self.upstream.releases[version]["published_at"],
                  "pinned": False}
        self.set_members(self.members() + [member])
        return record


@pytest.fixture
def repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    return Repo(tmp_path, Upstream())


def _catalog_pr(repo, head, **kwargs):
    verifier = _load_verifier()
    git = lambda *args: subprocess.run(["git", "-C", str(repo.path), *args], check=True,  # noqa: E731
                                       capture_output=True).stdout
    return verifier.catalog_pr(repo.base, head, 7, fetch=repo.upstream.fetch, download=repo.upstream.download,
                               git=git, **kwargs)


def test_a_pull_request_that_leaves_the_catalog_alone_passes_without_any_network_read(repo):
    repo.write("README.md", "changed\n")
    repo.write("phase-loop-runtime/src/phase_loop_runtime/other.py", "x = 1\n")
    result = _catalog_pr(repo, repo.commit("unrelated"))
    assert result == {"agy_catalog_provenance": "pass", "pr": 7, "checked": [], "reason": "catalog untouched"}
    assert repo.upstream.calls == [] and repo.upstream.downloads == []


def test_a_writers_member_with_non_upstream_bytes_fails(repo):
    repo.add_member("1.6.0", b"a writer's own build", upstream_image=b"upstream's real build")
    with pytest.raises(ValueError, match="digest mismatch"):
        _catalog_pr(repo, repo.commit("add 1.6.0"))


def test_a_genuine_member_with_no_signature_passes(repo):
    record = repo.add_member("1.6.0", b"upstream's real build")
    assert record["signatures"] == []
    result = _catalog_pr(repo, repo.commit("add 1.6.0"))
    assert result["agy_catalog_provenance"] == "pass" and result["checked"] == ["1.6.0"]
    assert repo.upstream.downloads == [f"{DOWNLOAD}1.6.0/{ASSET}"]
    assert all(url.startswith(RELEASES) for url in repo.upstream.calls)  # no review, no pull request read


@pytest.mark.parametrize("change", ["pinned_flip", "removal"])
def test_a_pinned_flip_or_a_removal_passes_and_reads_nothing_upstream(repo, change):
    members = repo.members()
    if change == "pinned_flip":
        members[0]["pinned"] = True
    else:
        members = members[1:]
    repo.set_members(members)
    result = _catalog_pr(repo, repo.commit(change))
    assert result["agy_catalog_provenance"] == "pass" and result["checked"] == []
    assert repo.upstream.downloads == []


def test_a_changed_member_whose_new_digest_is_not_upstreams_fails(repo):
    members = repo.members()
    image = sha256(b"something else").hexdigest()
    record = json.loads((repo.path / "plans/evidence/agy-1.5.3-linux-x64-qualification.json").read_text())
    record["image_sha256"] = image
    for row in record["records"]:
        row["image_sha256"] = image
        row["profile"]["image_sha256"] = image
    repo.write("plans/evidence/agy-1.5.3-linux-x64-qualification.json", json.dumps(record, indent=2))
    members[1]["image_sha256"] = image
    repo.set_members(members)
    with pytest.raises(ValueError, match="executable digest mismatch"):
        _catalog_pr(repo, repo.commit("change 1.5.3"))


def test_a_changed_published_at_must_be_upstreams(repo):
    members = repo.members()
    members[1]["published_at"] = "2020-01-01T00:00:00Z"
    repo.set_members(members)
    with pytest.raises(ValueError, match="published_at"):
        _catalog_pr(repo, repo.commit("backdate"))


def test_a_renamed_catalog_fails(repo):
    repo.git("mv", policy.CATALOG_PATH, "phase-loop-runtime/src/phase_loop_runtime/data/agy_catalog.old.json")
    with pytest.raises(ValueError, match="removed or renamed"):
        _catalog_pr(repo, repo.commit("rename"))


def test_a_catalog_turned_into_a_symlink_fails(repo):
    path = repo.path / policy.CATALOG_PATH
    target = path.with_name("elsewhere.json")
    target.write_text(path.read_text())
    path.unlink()
    path.symlink_to(target.name)
    with pytest.raises(ValueError, match="changed type|not a regular file"):
        _catalog_pr(repo, repo.commit("symlink"))


def test_a_record_turned_into_a_symlink_fails(repo):
    path = repo.path / "plans/evidence/agy-1.5.3-linux-x64-qualification.json"
    path.unlink()
    path.symlink_to("agy-1.5.2-linux-x64-qualification.json")
    with pytest.raises(ValueError, match="changed type|not a regular file"):
        _catalog_pr(repo, repo.commit("symlinked record"))


def test_a_head_catalog_that_does_not_parse_fails(repo):
    repo.write(policy.CATALOG_PATH, "{")
    with pytest.raises(ValueError, match="does not parse"):
        _catalog_pr(repo, repo.commit("broken"))


def test_the_arguments_are_checked(repo):
    with pytest.raises(ValueError, match="commit ids"):
        _load_verifier().catalog_pr("main", "HEAD", 7)
    with pytest.raises(ValueError, match="pull request number"):
        _load_verifier().catalog_pr("a" * 40, "b" * 40, "7; rm -rf /")


def test_main_prints_pass_or_fail_and_exits_accordingly(repo, monkeypatch, capsys):
    verifier = _load_verifier()
    repo.add_member("1.6.0", b"a writer's own build", upstream_image=b"upstream's real build")
    head = repo.commit("add 1.6.0")
    monkeypatch.setattr(verifier, "_git", lambda *args: subprocess.run(
        ["git", "-C", str(repo.path), *args], check=True, capture_output=True).stdout)
    real = verifier.catalog_pr
    monkeypatch.setattr(verifier, "catalog_pr", lambda base, head_, pr: real(
        base, head_, pr, fetch=repo.upstream.fetch, download=repo.upstream.download))
    assert verifier.main(["--catalog-pr", "--base", repo.base, "--head", head, "--pr", "7"]) == 1
    assert json.loads(capsys.readouterr().out)["agy_catalog_provenance"] == "fail"
    with pytest.raises(SystemExit):
        verifier.main(["--catalog-pr", "--base", repo.base])


DRIVER = textwrap.dedent('''
    import importlib.util, io, json, subprocess, sys, tarfile
    from hashlib import sha256
    script, repo_path, base, head, archive_path, release_path = sys.argv[1:7]
    spec = importlib.util.spec_from_file_location("verify_closure", script)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    release = json.load(open(release_path))
    def fetch(url):
        return json.loads(json.dumps(release))
    def download(url, target):
        open(target, "wb").write(open(archive_path, "rb").read())
    def git(*args):
        return subprocess.run(["git", "-C", repo_path, *args], check=True, capture_output=True).stdout
    result = verifier.catalog_pr(base, head, 7, fetch=fetch, download=download, git=git)
    assert result["checked"] == ["1.6.0"], result
    names = sorted(name for name in sys.modules if name.split(".")[0] not in sys.stdlib_module_names)
    print(json.dumps(names))
''')


def test_the_catalog_pr_modes_import_closure_is_the_standard_library_and_the_policy(repo, tmp_path):
    repo.add_member("1.6.0", b"upstream's real build")
    head = repo.commit("add 1.6.0")
    archive = tmp_path / "archive.tar.gz"
    archive.write_bytes(repo.upstream.blobs[f"{DOWNLOAD}1.6.0/{ASSET}"])
    release = tmp_path / "release.json"
    release.write_text(json.dumps(repo.upstream.releases["1.6.0"]))
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER)
    # -S: no site hooks, so only what the mode itself imports is loaded
    done = subprocess.run([sys.executable, "-I", "-S", str(driver), str(SCRIPT), str(repo.path), repo.base, head,
                           str(archive), str(release)], capture_output=True, text=True, timeout=120,
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    assert done.returncode == 0, done.stderr
    loaded = set(json.loads(done.stdout.strip().splitlines()[-1]))
    assert loaded <= {"__main__", "verify_closure", "phase_loop_runtime", "phase_loop_runtime.agy_catalog_policy"}
    assert "phase_loop_runtime.agy_catalog_policy" in loaded


# ----------------------------------------------------------------------- workflow shape

def _workflow(path):
    value = yaml.safe_load(path.read_text())
    return value, value.get("on", value.get(True))


@pytest.mark.skipif(not PROVENANCE.is_file(), reason="the workflow is repository source")
def test_the_provenance_workflow_runs_the_base_verifier_on_every_pull_request_with_no_write():
    workflow, triggers = _workflow(PROVENANCE)
    assert set(triggers) == {"pull_request"} and "pull_request_target" not in PROVENANCE.read_text()
    assert triggers["pull_request"] == {"branches": ["main"]}  # no path filter
    assert workflow["permissions"] == {"contents": "read"}
    (job,) = workflow["jobs"].values()
    assert job["name"] == "agy catalog provenance" and "permissions" not in job
    assert "environment" not in job and "secrets" not in PROVENANCE.read_text()
    fetch, verify = job["steps"]
    assert 'checkout -q --detach "$BASE_SHA"' in fetch["run"] and '"$HEAD_SHA"' in fetch["run"]
    assert "checkout" not in fetch["run"].replace('checkout -q --detach "$BASE_SHA"', "")  # only the base
    assert fetch["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert "--catalog-pr" in verify["run"] and verify["working-directory"] == "base"
    assert "pip" not in verify["run"] and "uv " not in verify["run"]  # nothing installed
    for step in job["steps"]:
        assert "${{" not in step.get("run", "")  # values reach the shell only as environment variables
    uses = [step["uses"] for step in job["steps"] if "uses" in step]
    assert all(len(ref.rsplit("@", 1)[1]) == 40 for ref in uses)  # third-party actions pinned by commit


@pytest.mark.skipif(not PROVENANCE.is_file(), reason="the workflow is repository source")
def test_the_token_reaches_git_only_through_the_environment():
    workflow, _ = _workflow(PROVENANCE)
    fetch = workflow["jobs"]["provenance"]["steps"][0]
    assert fetch["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "GIT_CONFIG_VALUE_0" in fetch["run"] and "-c http" not in fetch["run"]
