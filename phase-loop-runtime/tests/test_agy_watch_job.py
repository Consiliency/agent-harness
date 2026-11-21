"""The rolling catalog job's tick (ROLLJOB-detail §2, §6.3).

Nothing here reaches the network or runs a provider. The upstream release API and archives,
the GitHub API the INTAKE App talks to, the git and qualification subprocesses and the agy
login are all fakes; the RSA App key and the ed25519 job key are generated per run.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import tracemalloc
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from phase_loop_runtime import agy_attestation
from phase_loop_runtime import agy_catalog_policy as policy
from phase_loop_runtime import agy_intake
from phase_loop_runtime import agy_provenance as prov
from phase_loop_runtime import agy_qualification as q
from phase_loop_runtime import agy_watch
from phase_loop_runtime import agy_watch_units
from phase_loop_runtime import gemini_heartbeat as gh
from phase_loop_runtime import panel_invoker as panel

REPO = Path(__file__).resolve().parents[2]
HOST = prov.HostPlatform("linux", "x64", "glibc")
MACHINE = "b" * 32
APP_ID, INSTALLATION_ID, BOT_ID = 1001, 2002, 5005
TOKEN = "ghs_FAKEINSTALLATIONTOKEN0123456789"
SLUG = "Consiliency/agent-harness"
QCI = q.seat_qci()
NEW = "9.9.9"
HAS_SSH_KEYGEN = shutil.which("ssh-keygen") is not None


# ----------------------------------------------------------------------------- the fakes

def _archive(image: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("antigravity")
        info.size = len(image)
        bundle.addfile(info, io.BytesIO(image))
    return buffer.getvalue()


class Upstream:
    """``agy_provenance``'s transport: the paged listing, by-tag reads and the archives."""

    def __init__(self):
        self.releases, self.blobs, self.calls, self.images = [], {}, [], {}

    def add(self, version, image: bytes, *, published_at="2026-11-07T08:38:26Z"):
        archive = _archive(image)
        url = f"{prov.DOWNLOAD_PREFIX}{version}/{HOST.asset}"
        self.blobs[url], self.images[version] = archive, image
        self.releases.insert(0, {"tag_name": version, "draft": False, "prerelease": False,
                                 "published_at": published_at,
                                 "assets": [{"name": HOST.asset, "browser_download_url": url,
                                             "digest": "sha256:" + sha256(archive).hexdigest()}]})
        return SimpleNamespace(image_sha256=sha256(image).hexdigest(), asset_sha256=sha256(archive).hexdigest())

    def open(self, url, *, accept):
        self.calls.append(url)
        if "/releases/tags/" in url:
            tag = url.rsplit("/", 1)[1]
            return io.BytesIO(json.dumps(next(r for r in self.releases if r["tag_name"] == tag)).encode())
        if url.startswith(f"https://{prov.API_HOST}/"):
            query = parse_qs(urlsplit(url).query)
            per_page, page = int(query["per_page"][0]), int(query.get("page", ["1"])[0])
            return io.BytesIO(json.dumps(self.releases[(page - 1) * per_page:page * per_page]).encode())
        return io.BytesIO(self.blobs[url])

    def downloads(self):
        return [url for url in self.calls if "/releases/download/" in url]


class GitHub:
    """The GitHub API as the INTAKE App sees it: the token exchange and the issues."""

    def __init__(self, public_key):
        self.public_key, self.issues, self.calls, self.next = public_key, {}, [], 7000
        self.fail, self.lose_create_response = set(), False
        self.grant = {"issues": "write", "metadata": "read"}
        self.repositories = [{"full_name": SLUG}]

    def own_issue(self, body, *, state="open", age_s=60, app_id=APP_ID, bot_id=BOT_ID, user_type="Bot"):
        number = self.next = self.next + 1
        created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_s))
        self.issues[number] = {"number": number, "state": state, "body": body, "title": "agy intake",
                               "labels": [{"name": policy.INTAKE_LABEL}], "created_at": created,
                               "user": {"login": "agy-intake[bot]", "id": bot_id, "type": user_type},
                               "performed_via_github_app": {"id": app_id, "slug": "agy-intake"}}
        return number

    def request(self, method, path, *, authorization, body=None):
        self.calls.append((method, path, authorization, body))
        key = f"{method} {path.split('?')[0]}"
        if any(key.startswith(prefix) for prefix in self.fail):
            raise OSError("api down")
        if method == "POST" and path == f"/app/installations/{INSTALLATION_ID}/access_tokens":
            self.check_jwt(authorization.removeprefix("Bearer "))
            return 201, {"token": TOKEN, "expires_at": "2099-01-01T00:00:00Z", "permissions": dict(self.grant),
                         "repositories": self.repositories}
        assert authorization == f"Bearer {TOKEN}", "every issue call carries the installation token"
        if method == "GET" and path.startswith(f"/repos/{SLUG}/issues?"):
            query = parse_qs(urlsplit(path).query)
            assert query["state"] == ["open"] and query["labels"] == [policy.INTAKE_LABEL]
            per_page, page = int(query["per_page"][0]), int(query["page"][0])
            listed = [i for i in sorted(self.issues.values(), key=lambda i: -i["number"]) if i["state"] == "open"]
            return 200, listed[(page - 1) * per_page:page * per_page]
        if method == "GET" and path.startswith(f"/repos/{SLUG}/issues/"):
            number = int(path.rsplit("/", 1)[1])
            return (200, self.issues[number]) if number in self.issues else (404, {"message": "Not Found"})
        if method == "POST" and path == f"/repos/{SLUG}/issues":
            assert set(body) == {"title", "body", "labels"} and body["labels"] == [policy.INTAKE_LABEL]
            number = self.own_issue(body["body"])
            self.issues[number]["title"] = body["title"]
            if self.lose_create_response:
                raise OSError("connection reset after the issue was created")
            return 201, self.issues[number]
        raise AssertionError(f"unexpected API call {method} {path}")

    def check_jwt(self, jwt):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        header, claims, signature = jwt.split(".")

        def decode(part):
            return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))

        self.public_key.verify(decode(signature), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
        assert json.loads(decode(header)) == {"alg": "RS256", "typ": "JWT"}
        claimed = json.loads(decode(claims))
        assert claimed["iss"] == str(APP_ID) and claimed["iat"] < time.time() < claimed["exp"]
        assert claimed["exp"] - claimed["iat"] <= 600

    def token_requests(self):
        return [call for call in self.calls if call[1].endswith("/access_tokens")]

    def creates(self):
        return [call for call in self.calls if call[0] == "POST" and call[1] == f"/repos/{SLUG}/issues"]


class Runner:
    """git and the prepared tree's Python programs. Anything else is recorded as foreign."""

    def __init__(self, layout: Path, *, help_bytes=b"synthetic help\n"):
        self.layout, self.help_bytes, self.calls = layout, help_bytes, []
        self.attempts = []          # per series attempt: "pass" | ("fail", operation, classification)
        self.validate_fails = False
        self.trees = []

    def __call__(self, argv, **kwargs):
        argv = [str(part) for part in argv]
        self.calls.append(argv)
        ok = subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:1] == ["git"]:
            if "worktree" in argv and "add" in argv:
                tree = Path(argv[argv.index("--detach") + 1])
                shutil.copytree(self.layout, tree)
                self.trees.append(tree)
            return ok
        if argv[1:3] == ["-I", "-c"] and argv[3] == agy_watch._IDENTITY_PROGRAM:
            from phase_loop_runtime import __version__
            return subprocess.CompletedProcess(argv, 0, f"{QCI}\n{__version__}\n", "")
        if argv[1:3] == ["-I", "-c"] and argv[3] == agy_watch._CLASSIFY_PROGRAM:
            attempt = self.attempts[len(self.series()) - 1]
            return subprocess.CompletedProcess(argv, 0, attempt[2] + "\n", "")
        script = Path(argv[1]).name if len(argv) > 1 else ""
        if script == "qualify_gemini_heartbeat.py":
            if "--measure-help" in argv:
                Path(argv[argv.index("--output") + 1]).write_bytes(self.help_bytes)
                return ok
            if "--validate" in argv:
                if self.validate_fails:
                    raise subprocess.CalledProcessError(2, argv)
                return ok
            operation = argv[argv.index("--operation") + 1]
            output = Path(argv[argv.index("--output") + 1])
            index = len(self.series()) - 1
            attempt = self.attempts[index] if index < len(self.attempts) else "pass"
            output.mkdir(parents=True, exist_ok=True)
            if attempt != "pass" and attempt[1] == operation:
                raise subprocess.CalledProcessError(1, argv)
            return ok
        if script == "verify_qualified_agy_image.py":
            assert argv[2:] == ["--contract"]
            return ok
        return ok

    def series(self):
        """Every series attempt, in order (one per series directory that was started)."""
        roots = []
        for argv in self.calls:
            if "--operation" in argv and argv[argv.index("--operation") + 1] == "completion":
                roots.append(Path(argv[argv.index("--output") + 1]).parent)
        return roots

    def operations(self):
        return [argv for argv in self.calls if "--operation" in argv]

    def foreign(self):
        """Calls outside what the job may run: any git verb but fetch/worktree, and gh."""
        bad = []
        for argv in self.calls:
            if argv and Path(argv[0]).name == "gh":
                bad.append(argv)
            elif argv[:1] == ["git"]:
                verb = argv[3] if argv[1] == "-C" else argv[1]
                if verb not in ("fetch", "worktree") or "push" in argv:
                    bad.append(argv)
        return bad


def _record_for(version, image_sha256, asset_sha256, help_sha256, qci, *, attestation="present_unverified",
                second_channel="match"):
    """A closed v2 record of the shipped shape for these digests (the fake ``summarize``)."""
    record = json.loads((REPO / "plans/evidence/agy-1.5.3-linux-x64-qualification.json").read_text())
    url = f"https://github.com/{policy.UPSTREAM_REPO}/releases/tag/{version}"
    record.update(release_version=version, image_sha256=image_sha256, help_sha256=help_sha256,
                  upstream_asset_sha256=asset_sha256, upstream_release_url=url, qci=qci, qualified_under="0.7.38",
                  signatures=[])
    record["upstream"] = {"asset_sha256": asset_sha256, "release_url": url, "attestation": attestation,
                          "second_channel": second_channel}
    for row in record["records"]:
        row.update(image_sha256=image_sha256, help_sha256=help_sha256)
        row["profile"] = dict(row["profile"], image_sha256=image_sha256)
    return record


@pytest.fixture(scope="module")
def app_key(tmp_path_factory):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path_factory.mktemp("intake") / "intake_app_key.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    os.chmod(path, 0o600)
    return SimpleNamespace(path=path, public=key.public_key())


@pytest.fixture
def job(tmp_path, monkeypatch, app_key):
    """A prepared-tree layout, the fakes, a private state home and a fresh login."""
    layout = tmp_path / "layout"
    catalog = layout / policy.CATALOG_PATH
    catalog.parent.mkdir(parents=True)
    shutil.copy(REPO / policy.CATALOG_PATH, catalog)
    shutil.copytree(REPO / "plans/evidence", layout / "plans/evidence",
                    ignore=shutil.ignore_patterns("*.md", "agy-allowed-signers"))
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    signing_key = keys / "signing_key"
    allowed = tmp_path / "agy-allowed-signers"
    if HAS_SSH_KEYGEN:
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "job", "-f", str(signing_key)],
                       check=True, capture_output=True)
        kind, blob = (keys / "signing_key.pub").read_text().split()[:2]
        allowed.write_text(f'agy-watch namespaces="agy-qualification" {kind} {blob}\n')
    else:  # the fake signer below stands in; only the verification test needs the real one
        signing_key.write_text("fake key\n")
        os.chmod(signing_key, 0o600)

        def fake_sign(record, key_path, *, runner=None):
            if not agy_watch._signing_key_safe(key_path):
                raise ValueError(policy.SIGNING_UNAVAILABLE)
            return {**record, "signatures": [{"principal": "agy-watch", "namespace": "agy-qualification",
                                              "signature": "-----BEGIN SSH SIGNATURE-----\nfake\n"}]}

        monkeypatch.setattr(policy, "sign_record", fake_sign)
    environ = {"HOME": str(tmp_path / "home"), "XDG_STATE_HOME": str(tmp_path / "state"),
               "XDG_CONFIG_HOME": str(tmp_path / "config"),
               agy_intake.APP_KEY_ENV: str(app_key.path), agy_intake.APP_ID_ENV: str(APP_ID),
               agy_intake.INSTALLATION_ID_ENV: str(INSTALLATION_ID), policy.SIGNING_KEY_ENV: str(signing_key)}
    upstream, github = Upstream(), GitHub(app_key.public)
    new = upstream.add(NEW, b"#!/bin/sh\necho agy 9.9.9\n" + os.urandom(64))
    runner = Runner(layout)
    login = SimpleNamespace(left=3600.0, refresh_to=3600.0, awaited=[], refreshed=[], admitted=[],
                            admission=None, admission_error=None)

    def left_s(home):
        return login.left

    def admit_seat(env, subject_path, *, first_use=False, **kwargs):
        login.admitted.append((dict(env), subject_path, first_use))
        if login.admission_error is not None:
            raise login.admission_error
        return login.admission

    def refresh(home, image):
        login.refreshed.append((Path(home), image))
        login.left = login.refresh_to

    monkeypatch.setattr(panel, "_gemini_login_left_s", left_s)
    monkeypatch.setattr(panel, "_await_gemini_login", lambda command, env, **k: login.awaited.append((command, env)))
    monkeypatch.setattr(panel, "_refresh_gemini_credential", refresh)
    monkeypatch.setattr(q, "admit_seat", admit_seat)
    monkeypatch.setattr(agy_attestation, "attestation_status", lambda asset, transport=None: "present_unverified")
    monkeypatch.setattr(agy_attestation, "second_channel_status",
                        lambda asset, member, *, host, transport=None: "match")
    summaries = []

    def summarize(tree, series, asset, image_sha256, help_sha256, *, qci, qualified_under, template_name=None,
                  attestation="not_checked", second_channel="not_checked"):
        summaries.append(SimpleNamespace(version=asset.version, series=series, template=template_name,
                                         attestation=attestation, second_channel=second_channel))
        return _record_for(asset.version, image_sha256, asset.digest, help_sha256, qci, attestation=attestation,
                           second_channel=second_channel if second_channel is not None else "not_checked")

    monkeypatch.setattr(agy_watch, "summarize", summarize)
    store = q.Store(root=tmp_path / "store", machine_id=MACHINE)
    out = []

    def run(**kwargs):
        out.clear()
        work = tmp_path / f"work-{len(runner.trees)}"
        kwargs.setdefault("workdir", work)
        code = agy_watch.main(repo=tmp_path / "repo", runner=runner, host=HOST, transport=upstream,
                              intake_transport=github, environ=environ, store=store, out=out.append, **kwargs)
        return code, [json.loads(line) for line in out]

    return SimpleNamespace(tmp=tmp_path, layout=layout, runner=runner, upstream=upstream, github=github,
                           environ=environ, store=store, login=login, new=new, run=run, out=out, allowed=allowed,
                           signing_key=signing_key, summaries=summaries, app_key=app_key)


def _status(job):
    return policy.read_tick_status(job.environ)


def _submitted_records(job):
    return [policy.parse_intake(call[3]["body"]) for call in job.github.creates()]


def _add_member(job, version, image: bytes, *, qci, pinned=False):
    """Add a catalog member (and its record) to the prepared-tree layout, served upstream."""
    made = job.upstream.add(version, image)
    help_sha256 = sha256(job.runner.help_bytes).hexdigest()
    path = job.layout / policy.CATALOG_PATH
    catalog = json.loads(path.read_text())
    catalog["routes"]["linux-x64"].append({
        "release_version": version, "image_sha256": made.image_sha256, "help_sha256": help_sha256,
        "asset_sha256": made.asset_sha256, "qci": qci, "published_at": "2026-11-01T00:00:00Z", "pinned": pinned,
        "record": f"agy-{version}-linux-x64-qualification.json"})
    path.write_text(json.dumps(catalog, indent=2) + "\n")
    record = _record_for(version, made.image_sha256, made.asset_sha256, help_sha256, qci)
    (job.layout / "plans/evidence" / f"agy-{version}-linux-x64-qualification.json").write_text(json.dumps(record))
    # The new release stays the newest in the listing.
    job.upstream.releases.sort(key=lambda r: policy.release_key(r["tag_name"]), reverse=True)
    return made


# ------------------------------------------------------------------- the whole tick, passing

def test_a_tick_qualifies_the_new_release_signs_and_submits_it_with_no_git_write(job):
    code, out = job.run()
    assert code == 0 and out[-1] == {"agy_watch": "submitted", "version": NEW, "issues": [7001]}
    (record,) = _submitted_records(job)
    assert record["release_version"] == NEW and record["qci"] == QCI and record["signatures"]
    assert policy.candidate_member(record)["image_sha256"] == job.new.image_sha256
    assert job.runner.foreign() == [] and not [c for c in job.runner.calls if "push" in c or c[:1] == ["gh"]]
    assert {(call[0], call[1].split("?")[0]) for call in job.github.calls} == {
        ("POST", f"/app/installations/{INSTALLATION_ID}/access_tokens"), ("GET", f"/repos/{SLUG}/issues"),
        ("POST", f"/repos/{SLUG}/issues")}
    (create,) = job.github.creates()
    assert create[3]["title"] == f"agy intake: {NEW}"
    assert _status(job)["status"] == "submitted" and _status(job)["exit"] == 0


@pytest.mark.skipif(not HAS_SSH_KEYGEN, reason="ssh-keygen is not installed (hosted CI has it)")
def test_the_submitted_record_verifies_against_a_fixture_signer_list(job):
    assert job.run()[0] == 0
    (record,) = _submitted_records(job)
    assert policy.verified_signers(record, job.allowed) == ["agy-watch"]


def test_the_token_request_names_only_this_repository_and_issues_write(job):
    job.run()
    requests = job.github.token_requests()
    assert requests and all(call[3] == {"repositories": ["agent-harness"], "permissions": {"issues": "write"}}
                            for call in requests)


@pytest.mark.parametrize("grant,repositories", [
    ({"issues": "write", "contents": "write"}, [{"full_name": SLUG}]),
    ({"issues": "read"}, [{"full_name": SLUG}]),
    ({"issues": "write"}, [{"full_name": SLUG}, {"full_name": "Consiliency/other"}]),
    ({"issues": "write"}, None),
])
def test_a_wider_or_narrower_grant_than_asked_is_refused(job, grant, repositories):
    job.github.grant, job.github.repositories = grant, repositories
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (2, agy_intake.UNAVAILABLE)
    assert job.runner.operations() == [] and job.github.creates() == []


def test_the_issue_body_round_trips_through_parse_intake(job):
    job.run()
    (create,) = job.github.creates()
    record = policy.parse_intake(create[3]["body"])
    assert policy.render_intake(record) == create[3]["body"]


def test_the_key_and_the_token_appear_in_no_output(job):
    job.run()
    key_text = job.app_key.path.read_text()
    seen = [json.dumps(line) for line in job.out] + [policy.tick_status_path(job.environ).read_text()]
    seen += [" ".join(argv) for argv in job.runner.calls]
    seen += [json.dumps(call[3]) for call in job.github.calls if call[3]]
    for text in seen:
        assert TOKEN not in text and str(job.app_key.path) not in text
        assert key_text.strip().splitlines()[1] not in text


# ----------------------------------------------------------------------------- the work set

def test_with_every_member_at_the_trees_qci_only_the_new_release_is_fetched_and_run(job):
    for version in ("9.9.1", "9.9.2"):
        _add_member(job, version, f"member {version}".encode(), qci=QCI)
    assert len(agy_watch._catalog_members(job.layout)) == 3
    assert job.run()[0] == 0
    assert job.upstream.downloads() == [f"{prov.DOWNLOAD_PREFIX}{NEW}/{HOST.asset}"]
    assert len(job.runner.series()) == 1 and [s.version for s in job.summaries] == [NEW]


def test_a_member_at_another_qci_is_requalified_too(job):
    stale = _add_member(job, "9.9.1", b"member 9.9.1", qci="0" * 64)
    _add_member(job, "9.9.2", b"member 9.9.2", qci=QCI)
    code, out = job.run()
    assert code == 0 and out[-1]["issues"] == [7001, 7002]
    assert job.upstream.downloads() == [f"{prov.DOWNLOAD_PREFIX}{v}/{HOST.asset}" for v in (NEW, "9.9.1")]
    assert [(s.version, s.template, s.second_channel) for s in job.summaries] == [
        (NEW, None, "match"), ("9.9.1", "agy-9.9.1-linux-x64-qualification.json", None)]
    records = _submitted_records(job)
    assert [r["release_version"] for r in records] == [NEW, "9.9.1"]
    assert records[1]["image_sha256"] == stale.image_sha256 and records[1]["qci"] == QCI


def test_a_member_whose_upstream_image_changed_ends_the_tick_unverified(job):
    _add_member(job, "9.9.1", b"member 9.9.1", qci="0" * 64)
    # Upstream now serves other bytes under the same tag and URL: the archive digest refuses.
    job.upstream.blobs[f"{prov.DOWNLOAD_PREFIX}9.9.1/{HOST.asset}"] = _archive(b"substituted upstream image")
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (2, prov.UNVERIFIED) and job.github.creates() == []


# ------------------------------------------------------------------------------- retries

def test_two_transient_series_then_a_pass_give_one_record_after_three_attempts(job):
    job.runner.attempts = [("fail", "completion", "transient"), ("fail", "cancel", "transient"), "pass"]
    code, out = job.run()
    assert code == 0 and out[-1]["agy_watch"] == "submitted"
    assert len(job.runner.series()) == 3 and len(set(job.runner.series())) == 3  # a fresh directory each time
    assert len(_submitted_records(job)) == 1 and job.summaries[0].series == job.runner.series()[-1]
    classify = [argv for argv in job.runner.calls if argv[3:4] == [agy_watch._CLASSIFY_PROGRAM]]
    assert [argv[-1] for argv in classify] == ["completion", "cancel"]
    tree = job.runner.trees[0]
    assert all(argv[4] == str(tree / "phase-loop-runtime/src") for argv in classify)  # the PREPARED tree's


def test_three_transients_give_series_unavailable(job):
    job.runner.attempts = [("fail", "owner-loss", "transient")] * 3
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (2, "series_unavailable")
    assert len(job.runner.series()) == policy.SERIES_RETRIES and job.github.creates() == []


def test_a_failed_classification_stops_at_once_with_series_violation_and_no_submission(job):
    job.runner.attempts = [("fail", "completion", "failed"), "pass"]
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (2, "series_violation")
    assert len(job.runner.series()) == 1 and job.github.creates() == []


def test_a_validator_refusal_is_a_violation(job):
    job.runner.validate_fails = True
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (2, "series_violation") and len(job.runner.series()) == 1


# ------------------------------------------------------------------------------- signing

@pytest.mark.parametrize("problem", ["missing", "group_readable", "unset"])
def test_no_usable_signing_key_gives_signing_unavailable_and_no_submission(job, problem):
    if problem == "missing":
        job.signing_key.unlink()
    elif problem == "group_readable":
        job.signing_key.chmod(0o640)
    else:
        del job.environ[policy.SIGNING_KEY_ENV]
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (2, policy.SIGNING_UNAVAILABLE)
    assert job.github.calls == [] and job.runner.calls == [] and job.upstream.calls == []


def test_a_signing_failure_after_qualification_submits_nothing(job, monkeypatch):
    def refuse(record, key_path, *, runner=None):
        raise ValueError(policy.SIGNING_UNAVAILABLE)

    monkeypatch.setattr(policy, "sign_record", refuse)
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (2, policy.SIGNING_UNAVAILABLE) and job.github.creates() == []
    assert agy_intake.kept(QCI, environ=job.environ) == []


# --------------------------------------------------------------------------------- login

def _image(data=b"#!/bin/sh\necho the host agy\n"):
    return gh.VerifiedImage.from_bytes(data)


def test_a_fresh_login_makes_no_renewal_and_no_admission_call(job):
    assert job.run()[0] == 0
    assert (job.login.admitted, job.login.awaited, job.login.refreshed) == ([], [], [])


def test_a_stale_login_is_renewed_with_the_admitted_host_subject(job):
    job.login.left = 120.0
    subject = _image()
    job.login.admission = gh.Admission(subject, "e" * 64, "release_qualified", Path("/usr/bin/agy"), source="subject")
    assert job.run()[0] == 0
    ((env, subject_path, first_use),) = job.login.admitted
    assert subject_path is None and first_use is False and env["HOME"] == job.environ["HOME"]
    assert [command for command, _env in job.login.awaited] == [["agy", "models"]]
    ((home, image),) = job.login.refreshed
    assert home == Path(job.environ["HOME"]) and image is subject
    assert image.sha256 != job.new.image_sha256  # never the unqualified candidate
    assert subject.fd is None  # the admission is closed after the renewal


def test_a_stale_login_is_renewed_with_a_held_image_when_hold_admits_one(job, monkeypatch, tmp_path):
    """The subject is not admitted; the REAL ``admit_seat`` reaches the hold, which returns a
    held image (``source="lkg"``), and that image renews the login."""
    from phase_loop_runtime import agy_hold
    monkeypatch.undo()  # back to the real admit_seat; re-apply the other fakes
    job = _refake(job, monkeypatch)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "agy").write_bytes(b"#!/bin/sh\necho unqualified subject\n")
    (bindir / "agy").chmod(0o755)
    held = _image(b"#!/bin/sh\necho a held, qualified agy\n")
    seen = {}
    monkeypatch.setattr(panel, "_broker_subscription_env", lambda base_env=None: {"PATH": str(bindir)})
    monkeypatch.setattr(gh, "_local_capabilities", lambda: None)
    monkeypatch.setattr(q, "_admit_subject", lambda *a, **k: (_ for _ in ()).throw(
        q._SubjectNotAdmitted("subject_unqualified", ValueError(gh._CAPABILITY), "d" * 64)))
    monkeypatch.setattr(agy_hold, "hold_enabled", lambda: True)
    monkeypatch.setattr(q, "_names_managed_release", lambda *names: False)
    monkeypatch.setattr(q, "_host", lambda: HOST)

    def admit_held(env, *, reason, subject_sha256, store=None, cancel_event=None):
        seen.update(reason=reason, subject=subject_sha256)
        return gh.Admission(held, "e" * 64, "locally_qualified", None, source="lkg", hold_reason=reason,
                            subject_sha256=subject_sha256)

    monkeypatch.setattr(q, "admit_held", admit_held)
    job.login.left = 0.0
    code, out = job.run()
    assert code == 0, out
    ((home, image),) = job.login.refreshed
    assert image is held and seen == {"reason": "subject_unqualified", "subject": "d" * 64}
    assert image.sha256 != job.new.image_sha256


def _refake(job, monkeypatch):
    """Re-apply the job fixture's fakes after ``monkeypatch.undo()`` (all but ``admit_seat``)."""
    login = job.login

    def refresh(home, image):
        login.refreshed.append((Path(home), image))
        login.left = login.refresh_to

    monkeypatch.setattr(panel, "_gemini_login_left_s", lambda home: login.left)
    monkeypatch.setattr(panel, "_await_gemini_login", lambda command, env, **k: login.awaited.append((command, env)))
    monkeypatch.setattr(panel, "_refresh_gemini_credential", refresh)
    monkeypatch.setattr(agy_attestation, "attestation_status", lambda asset, transport=None: "present_unverified")
    monkeypatch.setattr(agy_attestation, "second_channel_status",
                        lambda asset, member, *, host, transport=None: "match")
    monkeypatch.setattr(agy_watch, "summarize", lambda tree, series, asset, image_sha256, help_sha256, **k:
                        _record_for(asset.version, image_sha256, asset.digest, help_sha256, k["qci"]))
    if not HAS_SSH_KEYGEN:
        monkeypatch.setattr(policy, "sign_record", lambda record, key_path, **k: {
            **record, "signatures": [{"principal": "agy-watch", "namespace": "agy-qualification",
                                      "signature": "-----BEGIN SSH SIGNATURE-----\nfake\n"}]})
    return job


def _refused(with_reason):
    refusal = ValueError(gh._CAPABILITY)
    if with_reason:
        refusal = q.provenance_refusal(prov.ProvenanceError(prov.UNVERIFIED, prov.BUDGET_EXHAUSTED))
    return refusal


@pytest.mark.parametrize("with_reason", [False, True])
def test_an_admission_refusal_ends_the_tick_expired_with_no_renewal_or_work(job, with_reason):
    job.login.left = None
    job.login.admission_error = _refused(with_reason)
    assert hasattr(job.login.admission_error, "reason") is with_reason
    code, out = job.run()
    assert (code, out) == (2, [{"agy_watch": "gemini_login_expired"}])
    assert job.login.awaited == [] and job.login.refreshed == []
    assert job.upstream.calls == [] and job.runner.calls == [] and job.github.creates() == []
    assert _status(job)["status"] == "gemini_login_expired"


@pytest.mark.parametrize("with_reason", [False, True])
def test_a_refusal_from_the_real_admit_seat_hold_path_is_expired(job, monkeypatch, tmp_path, with_reason):
    """Nothing held: the REAL ``admit_seat`` re-raises the subject's original refusal, with or
    without ``reason``; the tick reads no ``reason`` and reports the login expired."""
    from phase_loop_runtime import agy_hold
    monkeypatch.undo()
    job = _refake(job, monkeypatch)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "agy").write_bytes(b"#!/bin/sh\necho unqualified subject\n")
    (bindir / "agy").chmod(0o755)
    monkeypatch.setattr(panel, "_broker_subscription_env", lambda base_env=None: {"PATH": str(bindir)})
    monkeypatch.setattr(gh, "_local_capabilities", lambda: None)
    refusal = _refused(with_reason)
    monkeypatch.setattr(q, "_admit_subject", lambda *a, **k: (_ for _ in ()).throw(
        q._SubjectNotAdmitted("provenance_unverified", refusal, "d" * 64)))
    monkeypatch.setattr(agy_hold, "hold_enabled", lambda: True)
    monkeypatch.setattr(q, "_names_managed_release", lambda *names: False)
    monkeypatch.setattr(q, "_host", lambda: HOST)
    monkeypatch.setattr(q, "admit_held", lambda env, **k: None)
    job.login.left = 30.0
    code, out = job.run()
    assert (code, out) == (2, [{"agy_watch": "gemini_login_expired"}])
    assert job.login.refreshed == [] and job.upstream.calls == [] and job.runner.calls == []


def test_a_typed_non_refusal_failure_from_admission_propagates(job):
    from phase_loop_runtime import sandbox_egress
    job.login.left = None
    job.login.admission_error = sandbox_egress.EgressUnavailable("seat_egress_unavailable")
    with pytest.raises(sandbox_egress.EgressUnavailable):
        job.run()
    assert _status(job) is None and job.login.refreshed == []


@pytest.mark.parametrize("renewal", ["no_effect", "near_expiry"])
def test_a_login_still_stale_after_renewal_exits_expired_and_check_reports_it(job, monkeypatch, renewal):
    from phase_loop_runtime import sandbox_egress
    job.login.left, job.login.refresh_to = 100.0, 100.0
    job.login.admission = gh.Admission(_image(), "e" * 64, "release_qualified", Path("/usr/bin/agy"))
    if renewal == "near_expiry":
        def refresh(home, image):
            job.login.refreshed.append((home, image))
            raise sandbox_egress.SeatIdentityUnverified("gemini_credential_near_expiry")
        monkeypatch.setattr(panel, "_refresh_gemini_credential", refresh)
    code, out = job.run()
    assert (code, out) == (2, [{"agy_watch": "gemini_login_expired"}])
    assert len(job.login.refreshed) == 1 and job.github.creates() == [] and job.upstream.calls == []
    checkout = job.tmp / "checkout"
    shutil.copytree(REPO / agy_watch_units.UNIT_DIR, checkout / agy_watch_units.UNIT_DIR)

    def systemctl(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "enabled\n", "")

    agy_watch_units.install_units(checkout, runner=systemctl, environ=job.environ, out=lambda line: None)
    assert agy_watch_units.check_state(checkout, runner=systemctl, environ=job.environ) == (
        "failed: gemini_login_expired", "gemini_login_expired")


def test_another_renewal_failure_propagates(job, monkeypatch):
    from phase_loop_runtime import sandbox_egress
    job.login.left = 10.0
    job.login.admission = gh.Admission(_image(), "e" * 64, "release_qualified", Path("/usr/bin/agy"))

    def refresh(home, image):
        raise sandbox_egress.SeatIdentityUnverified("seat_resource_caps_unavailable")

    monkeypatch.setattr(panel, "_refresh_gemini_credential", refresh)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified):
        job.run()


# ------------------------------------------------------------------------------- streaming

def test_at_most_one_image_is_open_across_a_two_member_tick(job, monkeypatch):
    _add_member(job, "9.9.1", b"member 9.9.1" * 1000, qci="0" * 64)
    open_now, peak, real_from_fd, real_close = [0], [0], gh.VerifiedImage.from_fd.__func__, gh.VerifiedImage.close

    def from_fd(cls, fd, *, path=None):
        image = real_from_fd(cls, fd, path=path)
        open_now[0] += 1
        peak[0] = max(peak[0], open_now[0])
        return image

    def close(self):
        if self.fd is not None:
            open_now[0] -= 1
        real_close(self)

    monkeypatch.setattr(gh.VerifiedImage, "from_fd", classmethod(from_fd))
    monkeypatch.setattr(gh.VerifiedImage, "close", close)
    monkeypatch.setattr(gh.VerifiedImage, "from_bytes", classmethod(
        lambda cls, data, path=None: pytest.fail("the watch never builds an image from bytes")))
    assert job.run()[0] == 0
    assert peak[0] == 1 and open_now[0] == 0 and len(job.summaries) == 2


def test_streaming_a_multi_megabyte_member_stays_under_four_mib_of_traced_allocation(job, tmp_path):
    image = os.urandom(12 * 1024 * 1024)
    job.upstream.add("9.9.20", image)
    asset = prov.release_asset(job.upstream.releases[0], HOST)
    work = tmp_path / "stream"
    work.mkdir(mode=0o700)
    stream = io.BytesIO(job.upstream.blobs[asset.url])  # the response exists before tracing starts
    served = SimpleNamespace(open=lambda url, *, accept: stream)
    tracemalloc.start()
    try:
        built = agy_watch.stream_image(served, asset, work)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    try:
        assert built.sha256 == sha256(image).hexdigest()
    finally:
        built.close()
    assert peak < 4 * 1024 * 1024, peak
    assert list(work.iterdir()) == []  # the sink was anonymous and is gone


def test_a_sink_is_discarded_when_the_archive_digest_refuses(job, tmp_path):
    job.upstream.add("9.9.21", b"real image")
    release = dict(job.upstream.releases[0])
    release["assets"] = [dict(release["assets"][0], digest="sha256:" + "0" * 64)]
    asset = prov.release_asset(release, HOST)
    work = tmp_path / "refused"
    work.mkdir(mode=0o700)
    before = len(os.listdir("/proc/self/fd"))
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        agy_watch.stream_image(job.upstream, asset, work)
    assert list(work.iterdir()) == [] and len(os.listdir("/proc/self/fd")) == before


# ----------------------------------------------------------------------- the intake preflight

@pytest.mark.parametrize("problem", ["missing", "group_readable", "symlink", "unset", "no_ids", "not_rsa"])
def test_an_unusable_intake_key_or_ids_give_intake_unavailable_before_any_operation(job, problem, tmp_path):
    key = Path(job.environ[agy_intake.APP_KEY_ENV])
    private = tmp_path / "key.pem"
    shutil.copy(key, private)
    os.chmod(private, 0o600)
    job.environ[agy_intake.APP_KEY_ENV] = str(private)
    if problem == "missing":
        private.unlink()
    elif problem == "group_readable":
        private.chmod(0o640)
    elif problem == "symlink":
        link = tmp_path / "link.pem"
        link.symlink_to(private)
        job.environ[agy_intake.APP_KEY_ENV] = str(link)
    elif problem == "unset":
        del job.environ[agy_intake.APP_KEY_ENV]
    elif problem == "no_ids":
        job.environ[agy_intake.INSTALLATION_ID_ENV] = "not a number"
    else:
        armor = "PRIVATE " + "KEY"  # assembled at runtime: a malformed placeholder, not a key
        private.write_text(f"-----BEGIN {armor}-----\nnot a key\n-----END {armor}-----\n")
    code, out = job.run()
    assert (code, out) == (2, [{"agy_watch": agy_intake.UNAVAILABLE}])
    assert job.runner.calls == [] and job.upstream.calls == [] and job.github.calls == []
    assert job.login.admitted == [] and _status(job)["status"] == agy_intake.UNAVAILABLE


def test_without_the_extra_the_tick_ends_dependency_missing_before_any_operation(job, monkeypatch):
    for name in ("cryptography", "cryptography.hazmat", "cryptography.hazmat.primitives",
                 "cryptography.hazmat.primitives.asymmetric"):
        monkeypatch.setitem(sys.modules, name, None)
    code, out = job.run()
    assert (code, out) == (2, [{"agy_watch": agy_intake.DEPENDENCY_MISSING}])
    assert job.runner.calls == [] and job.upstream.calls == [] and job.github.calls == []


# -------------------------------------------------------------------------------- RS256

def test_the_app_jwt_verifies_with_the_public_key_and_carries_the_claims(job):
    now = time.time()
    jwt = agy_intake.app_jwt(APP_ID, job.app_key.path, now=now)
    job.github.check_jwt(jwt)
    claims = json.loads(base64.urlsafe_b64decode(jwt.split(".")[1] + "=="))
    assert claims == {"iat": int(now) - 60, "exp": int(now) + 540, "iss": str(APP_ID)}


def test_the_token_exchange_sends_that_jwt_and_asks_only_for_issues_write(job):
    assert agy_intake.installation_token(APP_ID, INSTALLATION_ID, job.app_key.path, transport=job.github) == TOKEN
    ((method, path, authorization, body),) = job.github.calls
    assert (method, path) == ("POST", f"/app/installations/{INSTALLATION_ID}/access_tokens")
    assert authorization.startswith("Bearer ") and authorization.count(".") == 2
    assert body == {"repositories": ["agent-harness"], "permissions": {"issues": "write"}}


def test_the_transport_speaks_only_to_the_api_host_with_no_proxy(monkeypatch):
    seen = {}

    class Connection:
        def __init__(self, host, port, *, context, timeout):
            seen.update(host=host, port=port)

        def request(self, method, path, body=None, headers=None):
            seen.update(method=method, path=path, headers=headers)

        def getresponse(self):
            return SimpleNamespace(status=200, read=lambda n: b"[]")

        def close(self):
            seen["closed"] = True

    transport = agy_intake._Transport(connection=Connection, context_factory=lambda: None)
    assert transport.request("GET", "/repos/x/issues", authorization="Bearer t") == (200, [])
    assert (seen["host"], seen["port"], seen["closed"]) == ("api.github.com", 443, True)
    assert seen["headers"]["Authorization"] == "Bearer t"
    with pytest.raises(agy_intake.IntakeError):
        transport.request("GET", "https://elsewhere.invalid/x", authorization="Bearer t")


# ------------------------------------------------------------------- submission and pending

def test_an_api_failure_after_qualification_keeps_the_record_and_the_next_tick_submits_it(job):
    job.github.fail = {f"POST /repos/{SLUG}/issues"}
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (2, agy_intake.SUBMIT_FAILED)
    (kept,) = agy_intake.kept(QCI, environ=job.environ)
    assert kept["release_version"] == NEW and kept["signatures"]
    operations = len(job.runner.operations())
    job.github.fail = set()
    code, out = job.run()
    assert code == 0 and out[-1]["agy_watch"] == "submitted"
    assert len(job.runner.operations()) == operations  # not re-qualified
    assert _submitted_records(job)[-1] == kept and len(job.github.issues) == 1
    assert agy_intake.kept(QCI, environ=job.environ) == []


def test_a_receipted_open_issue_makes_the_tick_up_to_date(job):
    assert job.run()[0] == 0
    downloads = len(job.upstream.downloads())
    code, out = job.run()
    assert (code, out[-1]) == (0, {"agy_watch": "up_to_date", "version": NEW})
    assert len(job.upstream.downloads()) == downloads and len(job.github.creates()) == 1


def test_an_own_open_issue_without_a_receipt_makes_the_tick_up_to_date_and_is_adopted(job):
    record = _record_for(NEW, job.new.image_sha256, "a" * 64, "e" * 64, QCI)
    number = job.github.own_issue(policy.render_intake(dict(record, signatures=[{
        "principal": "agy-watch", "namespace": "agy-qualification", "signature": "-----BEGIN SSH SIGNATURE-----"}])))
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (0, "up_to_date") and job.github.creates() == []
    assert agy_intake.read_receipt(NEW, QCI, store=job.store)["issue"] == number


@pytest.mark.parametrize("kind", ["another_app", "a_person", "other_qci"])
def test_a_look_alike_issue_is_not_a_pending_submission(job, kind):
    record = _record_for(NEW, job.new.image_sha256, "a" * 64, "e" * 64, "1" * 64 if kind == "other_qci" else QCI)
    body = policy.render_intake(record)
    if kind == "another_app":
        job.github.own_issue(body, app_id=APP_ID + 1)
    elif kind == "a_person":
        job.github.own_issue(body, user_type="User")
    else:
        job.github.own_issue(body)
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (0, "submitted") and len(job.github.creates()) == 1


def test_an_own_issue_open_past_the_stale_bound_gives_intake_stalled(job):
    assert job.run()[0] == 0
    (number,) = job.github.issues
    job.github.issues[number]["created_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - policy.INTAKE_STALE_AFTER_S - 60))
    operations = len(job.runner.operations())
    code, out = job.run()
    assert (code, out[-1]) == (2, {"agy_watch": agy_intake.STALLED, "version": NEW})
    assert len(job.runner.operations()) == operations and _status(job)["status"] == agy_intake.STALLED


def test_after_a_refusal_the_tick_waits_a_day_before_qualifying_again(job):
    assert job.run()[0] == 0
    (number,) = job.github.issues
    job.github.issues[number]["state"] = "closed"  # refused by the intake workflow
    assert job.run()[1][-1]["agy_watch"] == "up_to_date"
    assert len(job.runner.series()) == 1
    receipt = agy_intake.read_receipt(NEW, QCI, store=job.store)
    agy_intake.write_receipt(NEW, QCI, receipt["issue"], receipt["record_sha256"], store=job.store,
                             now=time.time() - policy.RESUBMIT_AFTER_S - 1)
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (0, "submitted") and len(job.runner.series()) == 2
    assert len(job.github.creates()) == 2


def test_an_operator_rerun_with_version_ignores_the_wait(job):
    assert job.run()[0] == 0
    (number,) = job.github.issues
    job.github.issues[number]["state"] = "closed"
    code, out = job.run(version=NEW)
    assert (code, out[-1]["agy_watch"]) == (0, "submitted") and len(job.runner.series()) == 2


def test_an_api_failure_while_checking_for_a_pending_submission_is_unavailable(job):
    job.github.fail = {f"GET /repos/{SLUG}/issues"}
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (2, agy_intake.UNAVAILABLE) and job.runner.operations() == []


# --------------------------------------------------------------------------------- recovery

def test_a_lost_post_response_is_adopted_with_no_duplicate(job):
    job.github.lose_create_response = True
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (2, agy_intake.SUBMIT_FAILED)
    assert len(job.github.creates()) == 1 and len(job.github.issues) == 1
    job.github.lose_create_response = False
    code, out = job.run()
    (number,) = job.github.issues
    # The kept record is submitted again first: the open issue with its header is adopted.
    assert (code, out[-1]) == (0, {"agy_watch": "submitted", "version": NEW, "issues": [number], "resubmitted": True})
    assert len(job.github.creates()) == 1 and agy_intake.kept(QCI, environ=job.environ) == []
    assert agy_intake.read_receipt(NEW, QCI, store=job.store)["issue"] == number
    assert job.run()[1][-1]["agy_watch"] == "up_to_date" and len(job.github.creates()) == 1


def _fail_creates(job, *which):
    """Make the given POST /issues calls (1-based, counted from now) fail in transport."""
    real, count = job.github.request, [0]

    def request(method, path, *, authorization, body=None):
        if method == "POST" and path == f"/repos/{SLUG}/issues":
            count[0] += 1
            if count[0] in which:
                job.github.calls.append((method, path, authorization, body))
                raise OSError("api down for this call")
        return real(method, path, authorization=authorization, body=body)

    job.github.request = request
    return real


def test_a_partial_outage_across_two_ticks_retries_the_leftover_record(job):
    """The newest release's record is submitted, a requalified member's fails: the next tick
    submits the leftover without re-qualifying, though the newest release is pending."""
    _add_member(job, "9.9.1", b"member 9.9.1", qci="0" * 64)
    real = _fail_creates(job, 2)
    code, out = job.run()
    assert (code, out[-1]) == (2, {"agy_watch": agy_intake.SUBMIT_FAILED, "version": NEW})
    (leftover,) = agy_intake.kept(QCI, environ=job.environ)
    assert leftover["release_version"] == "9.9.1" and _status(job)["status"] == agy_intake.SUBMIT_FAILED
    operations = len(job.runner.operations())
    job.github.request = real
    code, out = job.run()
    second = max(job.github.issues)
    assert (code, out[-1]) == (0, {"agy_watch": "submitted", "version": NEW, "issues": [second], "resubmitted": True})
    assert policy.parse_intake(job.github.issues[second]["body"]) == leftover
    assert len(job.runner.operations()) == operations and agy_intake.kept(QCI, environ=job.environ) == []
    assert (_status(job)["status"], _status(job)["exit"]) == ("submitted", 0)
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (0, "up_to_date") and len(job.github.issues) == 2


def test_a_leftover_that_keeps_failing_keeps_the_tick_failing(job):
    _add_member(job, "9.9.1", b"member 9.9.1", qci="0" * 64)
    _fail_creates(job, 2, 3, 4)
    assert job.run()[0] == 2
    operations = len(job.runner.operations())
    for _ in range(2):
        code, out = job.run()
        assert (code, out[-1]["agy_watch"]) == (2, agy_intake.SUBMIT_FAILED)
        assert len(agy_intake.kept(QCI, environ=job.environ)) == 1 and _status(job)["exit"] == 2
    assert len(job.runner.operations()) == operations  # never re-qualified


def test_a_leftover_is_submitted_even_after_the_newest_release_became_a_member(job):
    _add_member(job, "9.9.1", b"member 9.9.1", qci="0" * 64)
    real = _fail_creates(job, 2)
    assert job.run()[0] == 2
    job.github.request = real
    catalog = job.layout / policy.CATALOG_PATH
    members = policy.parse_catalog(catalog.read_text())
    members.append({"release_version": NEW, "image_sha256": job.new.image_sha256, "help_sha256": "e" * 64,
                    "asset_sha256": job.new.asset_sha256, "qci": QCI, "published_at": "2026-11-07T08:38:26Z",
                    "pinned": False, "record": f"agy-{NEW}-linux-x64-qualification.json"})
    catalog.write_text(policy.render_catalog(members))
    code, out = job.run()
    assert (code, out[-1]["agy_watch"], out[-1]["resubmitted"]) == (0, "submitted", True)
    assert job.run()[1][-1] == {"agy_watch": "already_pinned", "version": NEW}


def test_a_kept_record_that_main_already_reflects_is_discarded(job):
    shipped = policy.parse_catalog((REPO / policy.CATALOG_PATH).read_text())[-1]
    record = _record_for(shipped["release_version"], shipped["image_sha256"], shipped["asset_sha256"],
                         shipped["help_sha256"], shipped["qci"])
    record["signatures"] = [{"principal": "agy-watch", "namespace": "agy-qualification",
                             "signature": "-----BEGIN SSH SIGNATURE-----\nkept\n"}]
    agy_intake.keep(record, environ=job.environ)
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (0, "submitted") and "resubmitted" not in out[-1]
    assert [policy.parse_intake(c[3]["body"])["release_version"] for c in job.github.creates()] == [NEW]
    assert agy_intake.kept(QCI, environ=job.environ) == []


def test_submit_adopts_an_existing_own_issue_with_the_same_header(job):
    record = dict(_record_for(NEW, job.new.image_sha256, "a" * 64, "e" * 64, QCI), signatures=[
        {"principal": "agy-watch", "namespace": "agy-qualification", "signature": "-----BEGIN SSH SIGNATURE-----"}])
    number = job.github.own_issue(policy.render_intake(record))
    assert agy_intake.submit(record, TOKEN, transport=job.github, store=job.store, app_id=APP_ID) == number
    assert job.github.creates() == []
    assert agy_intake.read_receipt(NEW, QCI, store=job.store) == {
        "issue": number, "record_sha256": agy_intake.record_sha256(record),
        "at": agy_intake.read_receipt(NEW, QCI, store=job.store)["at"]}


def test_a_historical_push_receipt_is_never_read_as_an_intake_receipt(job):
    job.store.create()
    push_context = {"branch": f"agy-watch/{NEW}-20260101T000000Z-aaaaaaaa", "version": NEW, "base": QCI}
    job.store.put("watch_push", push_context, push_context, {"oid": "a" * 40})
    receipt_context = {"kind": agy_intake.RECEIPT_KIND, "version": NEW, "qci": QCI}
    assert agy_intake.read_receipt(NEW, QCI, store=job.store) is None
    job.store.put("watch_push", receipt_context, receipt_context, {"oid": "a" * 40})  # push-shaped payload
    assert agy_intake.read_receipt(NEW, QCI, store=job.store) is None
    code, out = job.run()
    assert (code, out[-1]["agy_watch"]) == (0, "submitted")


# ------------------------------------------------------------------------ kept coverage

def test_a_dry_run_qualifies_and_verifies_but_writes_no_status_and_submits_nothing(job):
    del job.environ[agy_intake.APP_KEY_ENV]  # a dry run needs no intake credential
    code, out = job.run(dry_run=True)
    assert code == 0 and out[-1]["agy_watch"] == "dry_run_verified"
    assert out[-1]["image_sha256"] == job.new.image_sha256
    assert job.github.calls == [] and _status(job) is None and agy_intake.kept(QCI, environ=job.environ) == []
    tree = Path(out[-1]["tree"])
    record = json.loads((tree / f"plans/evidence/agy-{NEW}-linux-x64-qualification.json").read_text())
    assert record["signatures"] == []  # a dry run writes an unsigned record
    assert [argv for argv in job.runner.calls if "--contract" in argv]


def test_version_selects_a_release_that_is_not_the_newest(job):
    job.upstream.add("9.9.30", b"a newer release")
    code, out = job.run(version=NEW)
    assert code == 0 and out[-1]["version"] == NEW
    assert job.upstream.downloads() == [f"{prov.DOWNLOAD_PREFIX}{NEW}/{HOST.asset}"]


def test_the_worktree_and_work_directory_are_cleaned_up(job):
    work = job.tmp / "cleanup"
    assert job.run(workdir=work)[0] == 0
    (tree,) = job.runner.trees
    assert ["git", "-C", str((job.tmp / "repo").resolve()), "worktree", "remove", "--force", str(tree)] in job.runner.calls
    assert not work.exists()


def test_the_receipt_persists_across_ticks(job):
    assert job.run()[0] == 0
    receipt = agy_intake.read_receipt(NEW, QCI, store=q.Store(root=job.tmp / "store", machine_id=MACHINE))
    assert receipt["issue"] == 7001 and receipt["record_sha256"] == agy_intake.record_sha256(_submitted_records(job)[0])


def test_a_pinned_version_is_already_pinned_with_no_fetch(job):
    job.upstream.add("1.5.3", b"already pinned")
    code, out = job.run()
    assert (code, out[-1]) == (0, {"agy_watch": "already_pinned", "version": "1.5.3"})
    assert job.upstream.downloads() == [] and job.github.calls == []


def test_the_newest_release_costs_one_listing_request(job):
    for i in range(150):
        job.upstream.add(f"0.0.{i}", b"older")
    job.upstream.add("1.5.3", b"already pinned")
    job.run()
    assert [c for c in job.upstream.calls if c.startswith(f"https://{prov.API_HOST}/")] == [
        f"https://{prov.API_HOST}/repos/{prov.REPO}/releases?per_page=100&page=1"]


@pytest.mark.parametrize("failure", [agy_attestation.SECOND_CHANNEL_MISMATCH, prov.UNAVAILABLE])
def test_a_second_channel_mismatch_or_an_unavailable_status_submits_nothing(job, monkeypatch, failure):
    def second_channel(asset, member, *, host, transport=None):
        raise prov.ProvenanceError(failure)

    monkeypatch.setattr(agy_attestation, "second_channel_status", second_channel)
    code, out = job.run()
    assert (code, out[-1]) == (2, {"agy_watch": failure, "version": NEW})
    assert job.runner.operations() == [] and job.github.creates() == []


def test_a_listing_failure_is_a_typed_return(job):
    class Down(Upstream):
        def open(self, url, *, accept):
            raise prov.ProvenanceError(prov.UNAVAILABLE)

    code, out = agy_watch.main(repo=job.tmp, runner=job.runner, host=HOST, transport=Down(),
                               intake_transport=job.github, environ=job.environ, store=job.store,
                               out=job.out.append), [json.loads(line) for line in job.out]
    assert (code, out[-1]) == (2, {"agy_watch": prov.UNAVAILABLE})


# --------------------------------------------------------------------------------- status

@pytest.mark.parametrize("scenario", ["platform", "login", "intake", "signing", "pinned", "submitted",
                                      "violation", "unavailable", "second_channel", "submit_failed",
                                      "up_to_date", "stalled"])
def test_every_return_path_writes_the_status_it_prints(job, monkeypatch, scenario):
    host = HOST
    if scenario == "platform":
        host = prov.HostPlatform("linux", "arm64", "glibc")
    elif scenario == "login":
        job.login.left, job.login.admission_error = None, ValueError(gh._CAPABILITY)
    elif scenario == "intake":
        del job.environ[agy_intake.APP_KEY_ENV]
    elif scenario == "signing":
        del job.environ[policy.SIGNING_KEY_ENV]
    elif scenario == "pinned":
        job.upstream.add("1.5.3", b"pinned")
    elif scenario == "violation":
        job.runner.attempts = [("fail", "completion", "failed")]
    elif scenario == "unavailable":
        job.runner.attempts = [("fail", "completion", "transient")] * 3
    elif scenario == "second_channel":
        monkeypatch.setattr(agy_attestation, "second_channel_status", lambda *a, **k: (_ for _ in ()).throw(
            prov.ProvenanceError(agy_attestation.SECOND_CHANNEL_MISMATCH)))
    elif scenario == "submit_failed":
        job.github.fail = {f"POST /repos/{SLUG}/issues"}
    elif scenario in ("up_to_date", "stalled"):
        assert job.run()[0] == 0
        if scenario == "stalled":
            (number,) = job.github.issues
            job.github.issues[number]["created_at"] = "2020-01-01T00:00:00Z"
    job.out.clear()
    code = agy_watch.main(repo=job.tmp / "repo", runner=job.runner, host=host, transport=job.upstream,
                          intake_transport=job.github, environ=job.environ, store=job.store, out=job.out.append,
                          workdir=job.tmp / f"status-{scenario}")
    printed = json.loads(job.out[-1])
    status = _status(job)
    assert (status["status"], status["exit"]) == (printed["agy_watch"], code)
    assert status["version"] == printed.get("version")
