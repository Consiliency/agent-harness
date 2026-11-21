"""``ci/agy_catalog_promote.py`` and the intake workflow (ROLLJOB-detail §4.3, §4.5, §6.4).

Nothing here reaches GitHub. The API is a fake that keeps issues, pull requests, commits,
workflow runs and branch rules in memory and checks the PROMOTION App's JWT; the checkout is
a local git repository whose ``origin`` is a local bare repository.
"""
from __future__ import annotations

import base64
import copy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from phase_loop_runtime import agy_catalog_policy as policy

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "ci" / "agy_catalog_promote.py"
WORKFLOW = REPO / ".github" / "workflows" / "agy-catalog-intake.yml"
SLUG = "Consiliency/agent-harness"
INTAKE = policy.AppIdentity(app_id=11, bot_user_id=111)
PROMOTION = policy.AppIdentity(app_id=22, bot_user_id=222)
MAIN_RULESET, CATALOG_RULESET = 5, 6
TOKEN = "ghs_PROMOTIONTOKEN0123456789"
WORKFLOW_TOKEN = "ghs_WORKFLOWTOKEN"
RUN_ID = "4242"

pytestmark = pytest.mark.skipif(not SCRIPT.is_file() or shutil.which("git") is None,
                                reason="the script is repository source and needs git")


def _load():
    spec = importlib.util.spec_from_file_location("agy_catalog_promote_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _iso(timestamp):
    return policy.rfc3339(timestamp)


def _attestation(**overrides):
    document = {"schema": policy.ATTESTATION_SCHEMA, "status": "attested",
                "intake_app": {"app_id": INTAKE.app_id, "bot_user_id": INTAKE.bot_user_id},
                "promotion_app": {"app_id": PROMOTION.app_id, "bot_user_id": PROMOTION.bot_user_id},
                "main_ruleset": {"id": MAIN_RULESET, "target": "refs/heads/main", "enforcement": "active",
                                 "bypass_actors": [], "strict_required_status_checks": True,
                                 "required_checks": ["agy catalog provenance", "agy catalog contract"]},
                "catalog_ruleset": {"id": CATALOG_RULESET, "target": "refs/heads/agy-catalog/**",
                                    "enforcement": "active", "rules": ["creation", "update", "deletion"],
                                    "bypass_actors": [{"actor_type": "Integration", "actor_id": PROMOTION.app_id,
                                                       "bypass_mode": "always"}]},
                "promotion_environment": {"name": "agy-promotion", "branches": ["main"], "required_reviewers": 0,
                                          "admin_bypass": False},
                "attested_by": "owner", "attested_at": "2026-11-21T00:00:00Z"}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(document.get(key), dict):
            document[key] = {**document[key], **value}
        else:
            document[key] = value
    return json.dumps(document, indent=2)


def _record(version):
    image = sha256(f"image {version}".encode()).hexdigest()
    asset = sha256(f"asset {version}".encode()).hexdigest()
    from phase_loop_runtime.agy_qualification import seat_qci
    record = json.loads((REPO / "plans/evidence/agy-1.5.3-linux-x64-qualification.json").read_text())
    url = f"https://github.com/{policy.UPSTREAM_REPO}/releases/tag/{version}"
    record.update(release_version=version, image_sha256=image, help_sha256="e" * 64, upstream_asset_sha256=asset,
                  upstream_release_url=url, qci=seat_qci(), qualified_under="0.7.38", signatures=[])
    record["upstream"] = {"asset_sha256": asset, "release_url": url, "attestation": "absent", "second_channel": "match"}
    for row in record["records"]:
        row.update(image_sha256=image, help_sha256="e" * 64)
        row["profile"] = dict(row["profile"], image_sha256=image)
    return record


def _member(version, *, age_days=30, pinned=False):
    return {**policy.candidate_member(_record(version)), "published_at": _iso(time.time() - age_days * 86_400),
            "pinned": pinned}


# ---------------------------------------------------------------------------- the checkout

class Checkout:
    """The workflow's checkout of main (a local repository) and its origin (a bare one)."""

    def __init__(self, tmp_path, versions=("1.5.2", "1.5.3")):
        self.tmp = tmp_path
        self.origin = tmp_path / "origin.git"
        self.path = tmp_path / "checkout"
        subprocess.run(["git", "init", "-q", "--bare", str(self.origin)], check=True)
        self.path.mkdir()
        self.git("init", "-q", "-b", "main")
        for key, value in (("user.email", "w@example.invalid"), ("user.name", "writer"), ("commit.gpgsign", "false")):
            self.git("config", key, value)
        self.git("remote", "add", "origin", str(self.origin))
        self.write(policy.ATTESTATION_PATH, _attestation())
        self.set_members([_member(v) for v in versions])
        self.commit("base")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.path), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def write(self, rel, text):
        path = self.path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def set_members(self, members):
        self.write(policy.CATALOG_PATH, policy.render_catalog(members))

    def members(self):
        return policy.parse_catalog((self.path / policy.CATALOG_PATH).read_text())

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        self.git("push", "-q", "origin", "HEAD:refs/heads/main")
        self.head = self.git("rev-parse", "HEAD")
        return self.head

    def origin_refs(self):
        listed = subprocess.run(["git", "ls-remote", str(self.origin)], capture_output=True, text=True,
                                check=True).stdout
        return {ref: oid for oid, ref in (line.split("\t") for line in listed.splitlines())}

    def decision(self, version="1.6.0", **overrides):
        """An ``auto`` decision directory, as ``--intake`` writes it for this run and commit."""
        directory = self.tmp / f"decision-{version}-{len(list(self.tmp.glob('decision-*')))}"
        directory.mkdir()
        record = _record(version)
        record_text = json.dumps(record, indent=2, sort_keys=True) + "\n"
        built = policy.build_catalog(self.members(), record, published_at=_iso(time.time() - 3600), now=time.time())
        catalog_text = policy.render_catalog(built)
        (directory / f"agy-{version}-linux-x64-qualification.json").write_text(record_text)
        (directory / "agy_catalog.json").write_text(catalog_text)
        decision = {"class": "auto", "issue": 700, "record_sha256": sha256(record_text.encode()).hexdigest(),
                    "version": version, "base_sha": self.head, "catalog_sha256": sha256(catalog_text.encode()).hexdigest(),
                    "run_id": RUN_ID, "reasons": []}
        decision.update(overrides)
        (directory / "decision.json").write_text(json.dumps(decision))
        return directory


# ---------------------------------------------------------------------------------- the API

class GitHub:
    """The GitHub API in memory. Records every call with the token it carried."""

    def __init__(self, checkout, public_key):
        self.checkout, self.public_key = checkout, public_key
        self.calls, self.issues, self.pulls, self.commits, self.runs = [], {}, {}, {}, []
        self.dispatches, self.graphql = [], []
        self.fail = set()
        self.grant = {"contents": "write", "pull_requests": "write", "metadata": "read"}
        self.grant_repositories, self.grant_token = [{"full_name": SLUG}], TOKEN
        self.status = {}  # "METHOD /path" -> an HTTP status returned instead of the answer
        self.main_rules = [
            {"type": "pull_request", "ruleset_id": MAIN_RULESET, "parameters": {}},
            {"type": "required_status_checks", "ruleset_id": MAIN_RULESET, "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [{"context": "agy catalog provenance"}, {"context": "agy catalog contract"},
                                           {"context": "pytest"}]}}]
        self.branch_rules = [{"type": kind, "ruleset_id": CATALOG_RULESET} for kind in ("creation", "update", "deletion")]
        self.next = 900
        self.tip_override = None

    # -- builders
    def intake_issue(self, version, *, number=None, age_s=3600, app=INTAKE, user_type="Bot", labels=("agy-intake",)):
        number = number or self._number()
        body = f"agy-intake.v1 {version} {'9' * 64} {'a' * 64}\n\n```json\n{{}}\n```\n"
        self.issues[number] = {"number": number, "state": "open", "body": body, "title": f"agy intake: {version}",
                               "created_at": _iso(time.time() - age_s), "labels": [{"name": n} for n in labels],
                               "user": {"login": "agy-intake[bot]", "id": app.bot_user_id, "type": user_type},
                               "performed_via_github_app": {"id": app.app_id}, "comments": []}
        return number

    def promotion_pull(self, version, issue, *, run_id=None, base=None, state="open", merged=False, age_s=1800,
                       armed=True, app=PROMOTION, trailer=True, title=None):
        number = self._number()
        run_id = run_id or self._number()
        sha = sha256(f"commit {number}".encode()).hexdigest()[:40]
        message = "feat(agy): add\n\n" + (f"Agy-Intake-Issue: {issue}\nAgy-Record-Sha256: {'b' * 64}\n" if trailer else "")
        # ``base`` is the commit the promotion was built on: its head commit's sole parent.
        self.commits[sha] = {"sha": sha, "commit": {"message": message},
                             "parents": [{"sha": base or self.checkout.head}]}
        created = _iso(time.time() - age_s)
        self.pulls[number] = {"number": number, "state": state, "merged_at": created if merged else None,
                              "created_at": created, "title": title or f"agy catalog {version}",
                              "head": {"ref": f"agy-catalog/{version}-{run_id}-1", "sha": sha,
                                       "repo": {"full_name": SLUG}},
                              "base": {"sha": base or self.checkout.head},
                              "auto_merge": {"merge_method": "squash"} if armed else None,
                              "node_id": f"PR_{number}", "labels": [{"name": "agy-catalog-auto"}]}
        self.issues[number] = {"number": number, "state": state, "pull_request": {}, "created_at": created,
                               "user": {"login": "agy-promotion[bot]", "id": app.bot_user_id, "type": "Bot"},
                               "performed_via_github_app": {"id": app.app_id}, "comments": [], "body": "",
                               "labels": []}
        return number

    def run(self, issue, *, status="completed", conclusion="failure", age_s=600, run_id=None, title=None):
        run_id = run_id or self._number() * 10
        self.runs.append({"id": run_id, "display_title": title or f"agy-intake-{issue}", "status": status,
                          "conclusion": conclusion if status == "completed" else None,
                          "created_at": _iso(time.time() - age_s), "head_branch": "main"})
        return run_id

    def _number(self):
        self.next += 1
        return self.next

    # -- the API
    def request(self, method, path, body=None, *, token=None):
        self.calls.append((method, path, copy.deepcopy(body), token))
        bare = path.split("?")[0]
        if any(f"{method} {bare}".startswith(prefix) for prefix in self.fail):
            raise OSError("api down")
        for prefix, status in self.status.items():
            if f"{method} {bare}".startswith(prefix):
                return status, {"message": "server error"}
        query = {k: v[0] for k, v in parse_qs(urlsplit(path).query).items()}
        page, per_page = int(query.get("page", 1)), int(query.get("per_page", 30))

        def paged(items):
            return items[(page - 1) * per_page:page * per_page]

        if bare == f"/repos/{SLUG}/installation":
            self._check_jwt(token)
            return 200, {"id": 31337}
        if bare == "/app/installations/31337/access_tokens":
            self._check_jwt(token)
            assert body == {"repositories": ["agent-harness"], "permissions": {"contents": "write",
                                                                               "pull_requests": "write"}}
            return 201, {"token": self.grant_token, "permissions": dict(self.grant),
                         "repositories": copy.deepcopy(self.grant_repositories)}
        if bare == f"/repos/{SLUG}/git/ref/heads/main":
            return 200, {"object": {"sha": self.tip_override or self.checkout.head}}
        if bare == f"/repos/{SLUG}/issues" and method == "GET":
            listed = sorted((i for i in self.issues.values() if i["state"] == query.get("state", "open")),
                            key=lambda i: policy.parse_instant(i["created_at"]))
            return 200, paged(listed)
        if bare.startswith(f"/repos/{SLUG}/issues/"):
            rest = bare[len(f"/repos/{SLUG}/issues/"):].split("/")
            issue = self.issues.get(int(rest[0]))
            if issue is None:
                return 404, {}
            if len(rest) == 1 and method == "GET":
                return 200, copy.deepcopy(issue)
            if len(rest) == 1 and method == "PATCH":
                issue["state"] = body["state"]
                if int(rest[0]) in self.pulls:
                    self.pulls[int(rest[0])]["state"] = body["state"]
                return 200, copy.deepcopy(issue)
            if rest[1] == "comments":
                issue["comments"].append(body["body"])
                return 201, {}
            if rest[1] == "labels":
                issue["labels"] += [{"name": n} for n in body["labels"]]
                return 200, issue["labels"]
        if bare == f"/repos/{SLUG}/pulls" and method == "GET":
            listed = sorted((p for p in self.pulls.values() if p["state"] == query["state"]),
                            key=lambda p: policy.parse_instant(p["created_at"]), reverse=True)
            # As GitHub does, ``base.sha`` follows the base ref: it is the tip of main now,
            # whatever commit the promotion was built on.
            tip = self.tip_override or self.checkout.head
            return 200, paged([{**pull, "base": {"sha": tip}} for pull in listed])
        if bare == f"/repos/{SLUG}/pulls" and method == "POST":
            assert token == TOKEN and body["base"] == "main" and body["maintainer_can_modify"] is False
            sha = self.checkout.origin_refs()[f"refs/heads/{body['head']}"]
            number = self._number()
            self.pulls[number] = {"number": number, "state": "open", "merged_at": None, "created_at": _iso(time.time()),
                                  "head": {"ref": body["head"], "sha": sha, "repo": {"full_name": SLUG}},
                                  "base": {"sha": self.checkout.head}, "auto_merge": None, "node_id": f"PR_{number}",
                                  "title": body["title"], "body": body["body"]}
            self.issues[number] = {"number": number, "state": "open", "pull_request": {}, "labels": [],
                                   "created_at": _iso(time.time()), "comments": [],
                                   "user": {"login": "agy-promotion[bot]", "id": PROMOTION.bot_user_id, "type": "Bot"},
                                   "performed_via_github_app": {"id": PROMOTION.app_id}}
            return 201, {"number": number, "node_id": f"PR_{number}"}
        if bare.startswith(f"/repos/{SLUG}/pulls/") and method == "PATCH":
            number = int(bare.rsplit("/", 1)[1])
            self.pulls[number]["state"] = body["state"]
            self.issues[number]["state"] = body["state"]
            return 200, {}
        if bare.startswith(f"/repos/{SLUG}/commits/"):
            return 200, self.commits[bare.rsplit("/", 1)[1]]
        if bare.startswith(f"/repos/{SLUG}/git/refs/heads/") and method == "DELETE":
            return 204, None
        if bare == f"/repos/{SLUG}/rules/branches/main":
            return 200, paged(self.main_rules)
        if bare.startswith(f"/repos/{SLUG}/rules/branches/"):
            return 200, paged(self.branch_rules)
        if bare == "/graphql":
            self.graphql.append(body)
            pull = next(p for p in self.pulls.values() if p["node_id"] == body["variables"]["pr"])
            if body["variables"]["oid"] != pull["head"]["sha"]:
                return 200, {"errors": [{"message": "expected head oid does not match"}]}
            pull["auto_merge"] = {"merge_method": "squash"}
            return 200, {"data": {"enablePullRequestAutoMerge": {"clientMutationId": None}}}
        if bare == f"/repos/{SLUG}/actions/workflows/agy-catalog-intake.yml/runs":
            assert query["branch"] == "main"
            runs = sorted(self.runs, key=lambda r: policy.parse_instant(r["created_at"]), reverse=True)  # newest first
            return 200, {"total_count": len(runs), "workflow_runs": paged(runs)}
        if bare == f"/repos/{SLUG}/actions/workflows/agy-catalog-intake.yml/dispatches":
            self.dispatches.append(body)
            return 204, None
        raise AssertionError(f"unexpected API call {method} {path}")

    def _check_jwt(self, jwt):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        head, claims, signature = jwt.split(".")

        def decode(part):
            return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))

        self.public_key.verify(decode(signature), f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
        assert json.loads(decode(claims))["iss"] == str(PROMOTION.app_id)

    def mutations(self):
        return [c for c in self.calls if c[0] in ("POST", "PATCH", "DELETE", "PUT")
                and not c[1].endswith("/access_tokens")]

    def history_pages(self):
        return [int(parse_qs(urlsplit(c[1]).query)["page"][0]) for c in self.calls if "/runs?" in c[1]]


@pytest.fixture(scope="module")
def app_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return SimpleNamespace(pem=pem, public=key.public_key())


@pytest.fixture
def world(tmp_path, monkeypatch, app_key):
    module = _load()
    checkout = Checkout(tmp_path)
    monkeypatch.setattr(module, "REPO", checkout.path)
    api = GitHub(checkout, app_key.public)
    environ = {"GITHUB_REPOSITORY": SLUG, "GITHUB_RUN_ID": RUN_ID, "GITHUB_RUN_ATTEMPT": "1",
               "GITHUB_SHA": checkout.head, "AGY_PROMOTION_APP_ID": str(PROMOTION.app_id),
               "AGY_PROMOTION_APP_PRIVATE_KEY": app_key.pem, "AGY_CATALOG_AUTOMERGE": "true",
               "GH_TOKEN": WORKFLOW_TOKEN, "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "GITHUB_OUTPUT": str(tmp_path / "github_output"), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary")}
    out = []

    def run(*argv, **kwargs):
        out.clear()
        code = module.main(list(argv), api=api, environ=environ, out=out.append, **kwargs)
        return code, json.loads(out[-1]) if out else None

    return SimpleNamespace(module=module, checkout=checkout, api=api, environ=environ, run=run, tmp=tmp_path)


def _outputs(world):
    path = Path(world.environ["GITHUB_OUTPUT"])
    return dict(line.split("=", 1) for line in path.read_text().splitlines()) if path.exists() else {}


# ---------------------------------------------------------------------------- authenticate

def test_authenticate_passes_only_the_attested_intake_app(world):
    good = world.api.intake_issue("1.6.0")
    assert world.run("authenticate", "--issue", str(good)) == (0, {"agy_catalog": "authenticated", "issue": good})
    assert _outputs(world) == {"authenticated": "true", "issue": str(good)}
    for kwargs in ({"app": policy.AppIdentity(33, 111)}, {"app": policy.AppIdentity(11, 999)}, {"user_type": "User"}):
        Path(world.environ["GITHUB_OUTPUT"]).unlink()
        number = world.api.intake_issue("1.6.0", **kwargs)
        assert world.run("authenticate", "--issue", str(number))[1]["agy_catalog"] == "not_authenticated"
        assert _outputs(world)["authenticated"] == "false"
    assert world.api.mutations() == []  # a look-alike issue: no comment, no label, nothing


@pytest.mark.parametrize("value", ["12a", "-1", "1 2", "1234567890", "", "$(id)"])
def test_the_dispatch_input_must_be_a_number(world, value):
    code, out = world.run("authenticate", "--issue", value)
    assert code == 1 and out == {"agy_catalog": "issue_number_malformed"}
    assert _outputs(world) == {"authenticated": "false"} and world.api.calls == []


def test_with_an_unattested_file_nobody_authenticates(world):
    world.checkout.write(policy.ATTESTATION_PATH, (REPO / policy.ATTESTATION_PATH).read_text())
    number = world.api.intake_issue("1.6.0")
    assert world.run("authenticate", "--issue", str(number))[1]["agy_catalog"] == "not_authenticated"


# --------------------------------------------------------------------------------- promote

def test_promote_writes_one_commit_with_exactly_two_files_and_arms_its_merge(world):
    decision = world.checkout.decision()
    code, out = world.run("promote", "--decision-dir", str(decision))
    assert code == 0 and out["agy_catalog"] == "promoted" and out["automerge"] is True and out["gate"] == []
    branch = f"refs/heads/agy-catalog/1.6.0-{RUN_ID}-1"
    commit = world.checkout.origin_refs()[branch]
    assert out["commit"] == commit
    files = subprocess.run(["git", "-C", str(world.checkout.origin), "diff", "--raw", "--no-renames",
                            world.checkout.head, commit], capture_output=True, text=True, check=True).stdout
    rows = sorted(line.split("\t")[1] + " " + line.split()[4] for line in files.splitlines())
    assert rows == [f"{policy.CATALOG_PATH} M", "plans/evidence/agy-1.6.0-linux-x64-qualification.json A"]
    message = subprocess.run(["git", "-C", str(world.checkout.origin), "log", "-1", "--format=%B", commit],
                             capture_output=True, text=True, check=True).stdout
    assert "Agy-Intake-Issue: 700" in message and "Agy-Record-Sha256: " in message
    parent = subprocess.run(["git", "-C", str(world.checkout.origin), "rev-parse", f"{commit}^"],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert parent == world.checkout.head
    (graphql,) = world.api.graphql
    assert graphql["variables"]["oid"] == commit and "SQUASH" in graphql["query"]
    pull = next(p for p in world.api.pulls.values() if p["head"]["ref"] == branch[len("refs/heads/"):])
    assert "Consiliency/agent-harness#700" in pull["body"]
    assert world.api.issues[pull["number"]]["labels"] == [{"name": policy.CATALOG_LABEL}]
    writes = [c for c in world.api.mutations() if c[1] != f"/repos/{SLUG}/actions"]
    assert all(call[3] == TOKEN for call in writes)  # every write is the PROMOTION App's
    assert not [c for c in world.api.calls if "update-branch" in c[1]]


def test_the_token_never_reaches_an_argv_or_the_output(world):
    seen, printed = [], []
    real = subprocess.run

    def runner(argv, **kwargs):
        seen.append(list(argv))
        return real(argv, **kwargs)

    assert world.module.main(["promote", "--decision-dir", str(world.checkout.decision())], api=world.api,
                             environ=world.environ, runner=runner, out=printed.append) == 0
    assert seen and not any(TOKEN in part or "PRIVATE KEY" in part for argv in seen for part in argv)
    assert not any(TOKEN in line for line in printed)
    outputs = Path(world.environ["GITHUB_OUTPUT"])
    assert not outputs.exists() or TOKEN not in outputs.read_text()


@pytest.mark.parametrize("change", [{"run_id": "1"}, {"base_sha": "f" * 40}, {"record_sha256": "0" * 64},
                                    {"catalog_sha256": "0" * 64}])
def test_a_decision_from_another_run_or_base_or_with_changed_files_is_rejected(world, change):
    code, out = world.run("promote", "--decision-dir", str(world.checkout.decision(**change)))
    assert code == 1 and out["agy_catalog"] in ("decision_from_another_run_or_base", "decision_files_changed")
    assert world.api.mutations() == [] and not [r for r in world.checkout.origin_refs() if "agy-catalog" in r]


def test_a_non_auto_built_catalog_is_rejected(world):
    decision = world.checkout.decision()
    catalog = decision / "agy_catalog.json"
    members = policy.parse_catalog(catalog.read_text())
    members[0]["pinned"] = True  # a surviving member changed: not the auto diff class
    catalog.write_text(policy.render_catalog(members))
    data = json.loads((decision / "decision.json").read_text())
    data["catalog_sha256"] = sha256(catalog.read_bytes()).hexdigest()
    (decision / "decision.json").write_text(json.dumps(data))
    assert world.run("promote", "--decision-dir", str(decision)) == (1, {"agy_catalog": "not_the_auto_diff_class"})


def test_main_moved_since_the_runs_commit_is_stale_base_and_nothing_is_written(world):
    world.api.tip_override = "c" * 40
    code, out = world.run("promote", "--decision-dir", str(world.checkout.decision()))
    assert (code, out["agy_catalog"]) == (0, "stale_base")
    assert world.api.mutations() == [] and not [c for c in world.api.calls if c[1].endswith("/access_tokens")]
    assert not [r for r in world.checkout.origin_refs() if "agy-catalog" in r]


@pytest.mark.parametrize("extra", ["third_path", "mode_change", "symlink"])
def test_a_created_commit_with_anything_but_the_two_files_stops_before_the_pull_request(world, monkeypatch, extra):
    module, checkout = world.module, world.checkout
    real = module._create_commit

    def create(runner, base_sha, files, message):
        files = dict(files)
        if extra == "third_path":
            files["README.md"] = b"sneaked in\n"
            return real(runner, base_sha, files, message)
        commit = real(runner, base_sha, files, message)
        mode = "100755" if extra == "mode_change" else "120000"
        path = policy.CATALOG_PATH
        with_index = {"GIT_INDEX_FILE": str(checkout.tmp / f"index-{extra}")}
        tree_env = {**os.environ, **with_index}
        subprocess.run(["git", "-C", str(checkout.path), "read-tree", commit], env=tree_env, check=True)
        blob = subprocess.run(["git", "-C", str(checkout.path), "rev-parse", f"{commit}:{path}"], capture_output=True,
                              text=True, check=True).stdout.strip()
        subprocess.run(["git", "-C", str(checkout.path), "update-index", "--cacheinfo", f"{mode},{blob},{path}"],
                       env=tree_env, check=True)
        tree = subprocess.run(["git", "-C", str(checkout.path), "write-tree"], env=tree_env, capture_output=True,
                              text=True, check=True).stdout.strip()
        return subprocess.run(["git", "-C", str(checkout.path), "commit-tree", tree, "-p", base_sha, "-m", message],
                              capture_output=True, text=True, check=True).stdout.strip()

    monkeypatch.setattr(module, "_create_commit", create)
    code, out = world.run("promote", "--decision-dir", str(world.checkout.decision()))
    assert (code, out["agy_catalog"]) == (1, "created_commit_not_the_two_files")
    assert not [c for c in world.api.calls if c[1] == f"/repos/{SLUG}/pulls" and c[0] == "POST"]


def test_an_existing_branch_is_never_overwritten(world):
    decision = world.checkout.decision()
    subprocess.run(["git", "-C", str(world.checkout.path), "push", "-q", "origin",
                    f"HEAD:refs/heads/agy-catalog/1.6.0-{RUN_ID}-1"], check=True)
    before = world.checkout.origin_refs()
    code, out = world.run("promote", "--decision-dir", str(decision))
    assert (code, out["agy_catalog"]) == (1, "git_push_failed") and world.checkout.origin_refs() == before


def _gate_case(world, case):
    api = world.api
    if case == "unattested":
        world.checkout.write(policy.ATTESTATION_PATH, (REPO / policy.ATTESTATION_PATH).read_text())
    elif case == "absent_main_bypass":
        document = json.loads(_attestation())
        del document["main_ruleset"]["bypass_actors"]
        world.checkout.write(policy.ATTESTATION_PATH, json.dumps(document))
    elif case == "main_bypass_not_empty":
        world.checkout.write(policy.ATTESTATION_PATH, _attestation(main_ruleset={"bypass_actors": [
            {"actor_type": "OrganizationAdmin", "actor_id": 1, "bypass_mode": "always"}]}))
    elif case == "second_catalog_bypass":
        world.checkout.write(policy.ATTESTATION_PATH, _attestation(catalog_ruleset={"bypass_actors": [
            {"actor_type": "Integration", "actor_id": PROMOTION.app_id, "bypass_mode": "always"},
            {"actor_type": "Team", "actor_id": 9, "bypass_mode": "always"}]}))
    elif case == "switch_unset":
        del world.environ["AGY_CATALOG_AUTOMERGE"]
    elif case == "switch_other":
        world.environ["AGY_CATALOG_AUTOMERGE"] = "True"
    elif case == "rules_cut_short":
        api.main_rules = api.main_rules + [dict(api.main_rules[0])] * 98  # a full page, then an error
        real = api.request

        def request(method, path, body=None, *, token=None):
            if "/rules/branches/main" in path and "page=2" in path:
                raise OSError("connection reset")
            return real(method, path, body, token=token)

        api.request = request
    elif case == "unexpected_ruleset":
        api.main_rules = [dict(rule, ruleset_id=99) for rule in api.main_rules]
    elif case == "rule_from_a_second_ruleset":
        api.main_rules = api.main_rules + [{"type": "required_status_checks", "ruleset_id": 77, "parameters": {
            "strict_required_status_checks_policy": False, "required_status_checks": []}}]
    elif case == "non_strict":
        api.main_rules[1]["parameters"]["strict_required_status_checks_policy"] = False
    elif case == "missing_required_check":
        api.main_rules[1]["parameters"]["required_status_checks"] = [{"context": "agy catalog contract"}]
    elif case == "branch_rule_missing":
        api.branch_rules = [rule for rule in api.branch_rules if rule["type"] != "deletion"]
    elif case == "branch_rule_other_ruleset":
        api.branch_rules = [dict(rule, ruleset_id=42) for rule in api.branch_rules]


@pytest.mark.parametrize("case", ["unattested", "absent_main_bypass", "main_bypass_not_empty", "second_catalog_bypass",
                                  "switch_unset", "switch_other", "rules_cut_short", "unexpected_ruleset",
                                  "rule_from_a_second_ruleset", "non_strict", "missing_required_check",
                                  "branch_rule_missing", "branch_rule_other_ruleset"])
def test_any_gate_condition_left_unmet_leaves_auto_merge_off_with_the_pull_request_open(world, case):
    decision = world.checkout.decision()
    _gate_case(world, case)
    code, out = world.run("promote", "--decision-dir", str(decision))
    assert code == 0 and out["agy_catalog"] == "promoted" and out["automerge"] is False and out["gate"]
    assert world.api.graphql == []
    (pull,) = [p for p in world.api.pulls.values() if p["state"] == "open"]
    assert pull["auto_merge"] is None


def test_a_rejected_expected_head_guard_stops(world, monkeypatch):
    decision = world.checkout.decision()
    real = world.api.request

    def request(method, path, body=None, *, token=None):
        if path == "/graphql":
            body = copy.deepcopy(body)
            body["variables"]["oid"] = "d" * 40  # GitHub sees another head than the one created
        return real(method, path, body, token=token)

    world.api.request = request
    code, out = world.run("promote", "--decision-dir", str(decision))
    assert (code, out["agy_catalog"]) == (1, "automerge_refused")


@pytest.mark.parametrize("grant", [
    {"contents": "write", "pull_requests": "write", "workflows": "write"},
    {"contents": "write", "pull_requests": "write", "metadata": "write"},
    {"contents": "write", "pull_requests": "write", "administration": "read"},
    {"contents": "read", "pull_requests": "write"},
])
def test_a_wider_or_other_promotion_permission_grant_is_refused(world, grant):
    world.api.grant = grant
    code, out = world.run("promote", "--decision-dir", str(world.checkout.decision()))
    assert (code, out["agy_catalog"]) == (1, "promotion_grant_wider_than_asked")
    assert not [r for r in world.checkout.origin_refs() if "agy-catalog" in r]


@pytest.mark.parametrize("repositories,token", [
    ([{"full_name": SLUG}, "junk"], TOKEN),                                     # a malformed extra entry
    ([{"full_name": SLUG}, {"full_name": "Consiliency/other"}], TOKEN),         # a wider repository grant
    ([{"full_name": SLUG}, {"full_name": SLUG}], TOKEN),                        # a repeated entry
    (["junk", {"full_name": SLUG}], TOKEN),
    ([{"name": "agent-harness"}], TOKEN),                                       # no full name
    ([], TOKEN), (None, TOKEN), (SLUG, TOKEN), ({"full_name": SLUG}, TOKEN),
    ([{"full_name": SLUG}], ""), ([{"full_name": SLUG}], None), ([{"full_name": SLUG}], 42),
])
def test_a_malformed_repository_grant_or_token_is_refused(world, repositories, token):
    world.api.grant_repositories, world.api.grant_token = repositories, token
    code, out = world.run("promote", "--decision-dir", str(world.checkout.decision()))
    assert (code, out["agy_catalog"]) == (1, "promotion_grant_malformed")
    assert not [r for r in world.checkout.origin_refs() if "agy-catalog" in r]
    assert not [c for c in world.api.calls if c[0] == "POST" and c[1] == f"/repos/{SLUG}/pulls"]


# ---------------------------------------------------------------------------------- report

@pytest.mark.parametrize("kind,closed,label", [("refused", True, False), ("manual", True, True), ("auto", False, False)])
def test_report_comments_and_closes_by_class(world, kind, closed, label):
    number = world.api.intake_issue("1.6.0")
    decision = world.checkout.decision(**{"class": kind, "reasons": ["why"]})
    assert world.run("report", "--decision-dir", str(decision), "--issue", str(number))[0] == 0
    issue = world.api.issues[number]
    assert kind in issue["comments"][-1] and "why" in issue["comments"][-1]
    assert (issue["state"] == "closed") is closed
    assert ({"name": "agy-intake-manual"} in issue["labels"]) is label
    assert all(call[3] is None for call in world.api.mutations())  # the workflow token, never the App's


def test_report_without_a_decision_changes_nothing(world):
    number = world.api.intake_issue("1.6.0")
    assert world.run("report", "--decision-dir", str(world.tmp / "absent"), "--issue", str(number)) == (
        0, {"agy_catalog": "no_decision", "issue": number})
    assert world.api.mutations() == []


# ------------------------------------------------------------------------------- reconcile

def _reconcile(world):
    return world.run("reconcile")


def test_reconcile_promotes_an_authenticated_issue_whose_event_run_never_happened(world):
    number = world.api.intake_issue("1.6.0")
    assert _reconcile(world) == (0, {"agy_catalog": "dispatched", "issue": number})
    assert world.api.dispatches == [{"ref": "main", "inputs": {"issue": str(number)}}]


def test_reconcile_never_acts_on_a_label_alone(world):
    world.api.intake_issue("1.6.0", app=policy.AppIdentity(33, 444), labels=("agy-intake", "agy-catalog-auto"))
    assert _reconcile(world) == (0, {"agy_catalog": "nothing_to_reconcile"})
    assert world.api.mutations() == []


def test_reconcile_closes_an_issue_whose_version_became_a_member(world):
    number = world.api.intake_issue("1.5.3")
    assert _reconcile(world) == (0, {"agy_catalog": "closed_member", "issue": number, "version": "1.5.3"})
    assert world.api.issues[number]["state"] == "closed" and world.api.dispatches == []


def test_reconcile_supersedes_an_unarmed_pull_request_once_the_switch_is_on(world):
    issue = world.api.intake_issue("1.6.0")
    pull = world.api.promotion_pull("1.6.0", issue, armed=False)
    code, out = _reconcile(world)
    assert code == 0 and out["agy_catalog"] == "superseded" and out["rebuild"] is True
    assert out["reason"] == "created while auto-merge was off"
    assert world.api.pulls[pull]["state"] == "closed"
    ref = world.api.pulls[pull]["head"]["ref"]
    assert [c for c in world.api.calls if c[0] == "DELETE"] == [
        ("DELETE", f"/repos/{SLUG}/git/refs/heads/{ref}", None, TOKEN)]
    assert world.api.dispatches == [{"ref": "main", "inputs": {"issue": str(issue)}}]
    assert not [c for c in world.api.calls if "update-branch" in c[1]]


def test_reconcile_leaves_an_unarmed_pull_request_while_the_switch_is_off(world):
    issue = world.api.intake_issue("1.6.0")
    world.api.promotion_pull("1.6.0", issue, armed=False)
    world.environ["AGY_CATALOG_AUTOMERGE"] = ""
    assert _reconcile(world) == (0, {"agy_catalog": "nothing_to_reconcile"})


def test_a_pull_request_is_matched_to_its_issue_by_the_trailer_alone(world):
    issue = world.api.intake_issue("1.6.0")
    pull = world.api.promotion_pull("1.6.0", issue, base="e" * 40, title="something unrelated")
    world.api.pulls[pull]["labels"] = []
    world.api.issues[pull]["body"] = "Fixes Consiliency/agent-harness#1"
    code, out = _reconcile(world)
    assert out["agy_catalog"] == "superseded" and out["pull_request"] == pull
    assert world.api.dispatches == [{"ref": "main", "inputs": {"issue": str(issue)}}]


def test_a_look_alike_pull_request_by_another_author_is_ignored(world):
    issue = world.api.intake_issue("1.6.0")
    world.api.promotion_pull("1.6.0", issue, base="e" * 40, app=policy.AppIdentity(99, 999))
    world.api.promotion_pull("1.6.0", issue, base="e" * 40, trailer=False)
    assert _reconcile(world) == (0, {"agy_catalog": "dispatched", "issue": issue})
    assert all(p["state"] == "open" for p in world.api.pulls.values())


def test_two_racing_promotions_a_merges_first_b_is_superseded_and_rebuilt(world):
    old_tip = world.checkout.head
    issue_a, issue_b = world.api.intake_issue("1.6.0", age_s=7200), world.api.intake_issue("1.7.0", age_s=7000)
    world.api.promotion_pull("1.6.0", issue_a, base=old_tip, merged=True, state="closed")
    pull_b = world.api.promotion_pull("1.7.0", issue_b, base=old_tip)
    world.checkout.set_members(world.checkout.members() + [_member("1.6.0", age_days=0)])
    world.checkout.commit("A merged")
    world.api.issues[issue_a]["state"] = "closed"
    code, out = _reconcile(world)
    assert out == {"agy_catalog": "superseded", "pull_request": pull_b, "rebuild": True,
                   "reason": "its base is no longer the tip of main"}
    assert world.api.dispatches == [{"ref": "main", "inputs": {"issue": str(issue_b)}}]


def test_two_racing_promotions_b_merges_first_a_is_closed_and_not_rebuilt(world):
    old_tip = world.checkout.head
    issue_a, issue_b = world.api.intake_issue("1.6.0", age_s=7200), world.api.intake_issue("1.7.0", age_s=7000)
    pull_a = world.api.promotion_pull("1.6.0", issue_a, base=old_tip)
    world.api.promotion_pull("1.7.0", issue_b, base=old_tip, merged=True, state="closed")
    world.checkout.set_members(world.checkout.members() + [_member("1.7.0", age_days=0)])
    world.checkout.commit("B merged")
    # the first reconcile closes B's issue (its version is now a member); the next one acts on A
    assert _reconcile(world)[1] == {"agy_catalog": "closed_member", "issue": issue_b, "version": "1.7.0"}
    code, out = _reconcile(world)
    assert out == {"agy_catalog": "superseded", "pull_request": pull_a, "rebuild": False,
                   "reason": "its version is no longer newer than every catalog member"}
    assert world.api.pulls[pull_a]["state"] == "closed" and world.api.dispatches == []
    assert "no longer newer" in world.api.issues[pull_a]["comments"][-1]


def test_main_advancing_under_an_open_armed_promotion_is_superseded_and_rebuilt(world):
    issue = world.api.intake_issue("1.6.0")
    pull = world.api.promotion_pull("1.6.0", issue, armed=True)  # built on the current tip
    assert _reconcile(world) == (0, {"agy_catalog": "nothing_to_reconcile"})
    world.checkout.write("README.md", "an unrelated change lands on main\n")
    world.checkout.commit("unrelated")
    # The listing's base.sha now names the new tip, as GitHub's does; it cannot show staleness.
    listed = world.api.request("GET", f"/repos/{SLUG}/pulls?state=open&per_page=100&page=1")[1]
    assert [p["base"]["sha"] for p in listed] == [world.checkout.head]
    code, out = _reconcile(world)
    assert out == {"agy_catalog": "superseded", "pull_request": pull, "rebuild": True,
                   "reason": "its base is no longer the tip of main"}
    assert world.api.dispatches == [{"ref": "main", "inputs": {"issue": str(issue)}}]


def test_a_promotion_head_without_a_single_parent_is_treated_as_stale(world):
    issue = world.api.intake_issue("1.6.0")
    pull = world.api.promotion_pull("1.6.0", issue)
    world.api.commits[world.api.pulls[pull]["head"]["sha"]]["parents"] = [{"sha": world.checkout.head},
                                                                           {"sha": "f" * 40}]
    assert _reconcile(world)[1]["agy_catalog"] == "superseded"


@pytest.mark.parametrize("answer", [{"ref": "refs/heads/main"}, {"object": {}}, {"object": {"sha": None}},
                                    {"object": {"sha": "abc123"}}, [], {"object": "sha"}])
def test_an_unreadable_main_ref_refuses_before_acting(world, answer):
    issue = world.api.intake_issue("1.6.0")
    pull = world.api.promotion_pull("1.6.0", issue)
    world.api.commits[world.api.pulls[pull]["head"]["sha"]]["parents"] = [{"sha": world.checkout.head},
                                                                           {"sha": "f" * 40}]
    real = world.api.request

    def request(method, path, body=None, *, token=None):
        if path == f"/repos/{SLUG}/git/ref/heads/main":
            world.api.calls.append((method, path, body, token))
            return 200, answer
        return real(method, path, body, token=token)

    world.api.request = request
    assert _reconcile(world) == (1, {"agy_catalog": "main_ref_unreadable"})
    assert "agy catalog reconcile: main_ref_unreadable" in Path(world.environ["GITHUB_STEP_SUMMARY"]).read_text()
    assert world.api.mutations() == [] and world.api.dispatches == []
    assert world.api.issues[issue]["state"] == "open" and world.api.pulls[pull]["state"] == "open"


def test_a_policy_change_on_main_supersedes_a_pending_promotion_and_rebuilds_on_the_new_main(world):
    issue = world.api.intake_issue("1.6.0")
    pull = world.api.promotion_pull("1.6.0", issue, base=world.checkout.head)
    world.checkout.write(policy.ALLOWED_SIGNERS, "# the signer list changed\n")
    world.checkout.commit("rotate the signer list")
    code, out = _reconcile(world)
    assert out["agy_catalog"] == "superseded" and out["pull_request"] == pull and out["rebuild"] is True
    # the rebuild is a normal run on main, so its --intake verifies against the new signer list
    assert world.api.dispatches == [{"ref": "main", "inputs": {"issue": str(issue)}}]


def test_reconcile_stops_after_max_promotion_attempts(world):
    issue = world.api.intake_issue("1.6.0", age_s=20_000)
    for _ in range(policy.MAX_PROMOTION_ATTEMPTS):
        world.api.promotion_pull("1.6.0", issue, state="closed", age_s=10_000)
    code, out = _reconcile(world)
    assert out == {"agy_catalog": "stalled", "issue": issue, "cause": "superseded"}
    assert world.api.issues[issue]["state"] == "closed" and world.api.dispatches == []
    assert "stalled" in world.api.issues[issue]["comments"][-1]


def test_superseding_an_open_promotion_at_the_limit_rebuilds_nothing_and_the_issue_then_stalls(world):
    issue = world.api.intake_issue("1.6.0", age_s=20_000)
    for _ in range(policy.MAX_PROMOTION_ATTEMPTS - 1):
        world.api.promotion_pull("1.6.0", issue, state="closed", age_s=10_000)
    pull = world.api.promotion_pull("1.6.0", issue, base="e" * 40, age_s=1_000)  # open, stale
    code, out = _reconcile(world)
    assert code == 0 and out["agy_catalog"] == "superseded" and out["pull_request"] == pull
    assert out["rebuild"] is False and "attempt limit" in out["reason"]
    assert world.api.dispatches == [] and world.api.pulls[pull]["state"] == "closed"
    assert _reconcile(world)[1] == {"agy_catalog": "stalled", "issue": issue, "cause": "superseded"}
    assert _reconcile(world)[1] == {"agy_catalog": "nothing_to_reconcile"}
    assert world.api.dispatches == []


def test_repeated_runs_never_create_more_promotions_than_the_limit(world):
    issue = world.api.intake_issue("1.6.0", age_s=50_000)
    for _ in range(policy.MAX_PROMOTION_ATTEMPTS - 2):
        world.api.promotion_pull("1.6.0", issue, state="closed", age_s=40_000)
    world.api.promotion_pull("1.6.0", issue, base="e" * 40, age_s=30_000)
    outcomes = []
    for run in range(6):
        before = len(world.api.dispatches)
        code, out = _reconcile(world)
        outcomes.append(out["agy_catalog"])
        if len(world.api.dispatches) > before:
            # the dispatched rebuild opens its promotion, and main moves again before it merges
            world.api.promotion_pull("1.6.0", issue, base="d" * 40, age_s=20_000 - 100 * run)
    promotions = [p for p in world.api.pulls.values() if p["head"]["ref"].startswith("agy-catalog/")]
    assert len(promotions) == policy.MAX_PROMOTION_ATTEMPTS and len(world.api.dispatches) == 1
    assert outcomes[:4] == ["superseded", "superseded", "stalled", "nothing_to_reconcile"]
    assert world.api.issues[issue]["state"] == "closed"


def test_the_limit_survives_a_reconcile_that_stopped_after_closing(world):
    issue = world.api.intake_issue("1.6.0", age_s=50_000)
    for _ in range(policy.MAX_PROMOTION_ATTEMPTS - 2):
        world.api.promotion_pull("1.6.0", issue, state="closed", age_s=40_000)
    first = world.api.promotion_pull("1.6.0", issue, base="e" * 40, age_s=30_000)
    world.api.status = {f"POST /repos/{SLUG}/actions/workflows/agy-catalog-intake.yml/dispatches": 500}
    code, out = _reconcile(world)
    assert (code, out) == (1, {"agy_catalog": "api_post_failed"})   # closed, then the dispatch failed
    assert world.api.pulls[first]["state"] == "closed" and world.api.dispatches == []
    world.api.status = {}
    # The next run reads the closed promotion from GitHub: under the limit, it dispatches once.
    assert _reconcile(world) == (0, {"agy_catalog": "dispatched", "issue": issue})
    second = world.api.promotion_pull("1.6.0", issue, base="d" * 40, age_s=10_000)
    code, out = _reconcile(world)
    assert out["pull_request"] == second and out["rebuild"] is False and "attempt limit" in out["reason"]
    assert _reconcile(world)[1] == {"agy_catalog": "stalled", "issue": issue, "cause": "superseded"}
    assert len(world.api.dispatches) == 1


def test_reconcile_retries_a_failed_promotion(world):
    issue = world.api.intake_issue("1.6.0", age_s=20_000)
    for age in (9000, 8000):
        world.api.run(issue, age_s=age)
    assert _reconcile(world) == (0, {"agy_catalog": "dispatched", "issue": issue})


# --- the six-run stop

def _six_run_world(world, *, count=6, with_pull=None):
    issue = world.api.intake_issue("1.6.0", age_s=50_000)
    run_ids = [world.api.run(issue, age_s=40_000 - 1000 * i) for i in range(count)]
    if with_pull is not None:
        world.api.promotion_pull("1.6.0", issue, run_id=run_ids[with_pull], state="closed", age_s=30_000)
    return issue


def test_six_completed_runs_without_a_pull_request_close_the_issue_with_zero_dispatches(world):
    issue = _six_run_world(world)
    assert _reconcile(world) == (0, {"agy_catalog": "stalled", "issue": issue, "cause": "no_pull_request"})
    assert world.api.dispatches == [] and world.api.issues[issue]["state"] == "closed"
    assert _reconcile(world) == (0, {"agy_catalog": "nothing_to_reconcile"}) and world.api.dispatches == []


def test_five_such_runs_give_exactly_one_dispatch(world):
    issue = _six_run_world(world, count=5)
    assert _reconcile(world) == (0, {"agy_catalog": "dispatched", "issue": issue})
    assert len(world.api.dispatches) == 1


def test_six_runs_where_one_produced_a_superseded_pull_request_are_not_the_stall_case(world):
    issue = _six_run_world(world, with_pull=2)
    assert _reconcile(world) == (0, {"agy_catalog": "dispatched", "issue": issue})


def test_runs_for_another_issue_older_than_the_issue_or_in_progress_are_not_counted(world):
    issue = _six_run_world(world, count=5)
    world.api.run(issue + 1000, age_s=1000)                        # named for another issue
    world.api.run(issue, age_s=60_000)                             # older than the issue
    assert _reconcile(world) == (0, {"agy_catalog": "dispatched", "issue": issue})
    world.api.dispatches.clear()
    world.api.run(issue, status="in_progress", age_s=500)          # a matching run in progress
    assert _reconcile(world) == (0, {"agy_catalog": "nothing_to_reconcile"}) and world.api.dispatches == []


def test_an_older_queued_match_beyond_six_completed_ones_means_no_dispatch_and_no_stall(world):
    issue = world.api.intake_issue("1.6.0", age_s=90_000)
    world.api.run(issue, status="queued", age_s=80_000)            # the oldest matching run, still queued
    for i in range(150):                                           # unrelated runs: the match is on page 2
        world.api.run(0, title="agy-catalog-reconcile", age_s=70_000 - i)
    for i in range(6):                                             # six newer completed matches
        world.api.run(issue, age_s=10_000 - 100 * i)
    assert _reconcile(world) == (0, {"agy_catalog": "nothing_to_reconcile"})
    assert world.api.dispatches == [] and world.api.issues[issue]["state"] == "open"
    assert world.api.history_pages() == [1, 2]  # paged past the sixth completed match


def test_a_history_that_cannot_reach_the_issue_age_boundary_is_unavailable(world):
    issue = world.api.intake_issue("1.6.0", age_s=900_000)
    for i in range(1000):  # the result limit, every run newer than the issue
        world.api.run(0, title="agy-catalog-reconcile", age_s=800_000 - i)
    code, out = _reconcile(world)
    assert (code, out) == (1, {"agy_catalog": "history_unavailable"})
    assert world.api.dispatches == [] and world.api.issues[issue]["state"] == "open"
    assert "history_unavailable" in Path(world.environ["GITHUB_STEP_SUMMARY"]).read_text()


@pytest.mark.parametrize("failure", ["error", "truncated", "no_run_name"])
def test_an_unreadable_history_is_unavailable_never_a_count(world, failure):
    issue = _six_run_world(world, count=6)
    if failure == "error":
        world.api.fail = {f"GET /repos/{SLUG}/actions/workflows/agy-catalog-intake.yml/runs"}
    elif failure == "truncated":
        real = world.api.request

        def request(method, path, body=None, *, token=None):
            if "/runs?" in path:
                return 200, {"total_count": 6}
            return real(method, path, body, token=token)

        world.api.request = request
    else:
        del world.api.runs[0]["display_title"]
    code, out = _reconcile(world)
    assert (code, out) == (1, {"agy_catalog": "history_unavailable"})
    assert world.api.dispatches == [] and world.api.issues[issue]["state"] == "open"


@pytest.mark.parametrize("status", [404, 500, 502])
@pytest.mark.parametrize("on_page", [1, 2])
def test_a_non_200_history_page_is_history_unavailable(world, status, on_page):
    issue = world.api.intake_issue("1.6.0", age_s=900_000)
    for i in range(150 if on_page == 2 else 6):
        world.api.run(0, title="agy-catalog-reconcile", age_s=800_000 - i)
    real = world.api.request

    def request(method, path, body=None, *, token=None):
        if "/runs?" in path and f"page={on_page}" in path and "per_page" in path:
            world.api.calls.append((method, path, body, token))
            return status, {"message": "unavailable"}
        return real(method, path, body, token=token)

    world.api.request = request
    code, out = _reconcile(world)
    assert (code, out) == (1, {"agy_catalog": "history_unavailable"})
    assert world.api.dispatches == [] and world.api.issues[issue]["state"] == "open"
    assert "agy catalog reconcile: history_unavailable" in Path(world.environ["GITHUB_STEP_SUMMARY"]).read_text()


def test_labels_and_comments_change_none_of_the_outcomes(world):
    issue = _six_run_world(world)
    world.api.issues[issue]["labels"] += [{"name": "agy-catalog-auto"}, {"name": "stalled"}]
    world.api.issues[issue]["comments"] += ["stalled", "do not close"]
    assert _reconcile(world)[1] == {"agy_catalog": "stalled", "issue": issue, "cause": "no_pull_request"}


def test_with_an_unattested_file_reconcile_does_nothing(world):
    world.checkout.write(policy.ATTESTATION_PATH, (REPO / policy.ATTESTATION_PATH).read_text())
    world.api.intake_issue("1.6.0")
    assert _reconcile(world) == (0, {"agy_catalog": "nothing_to_reconcile"}) and world.api.mutations() == []


# --------------------------------------------------------------------------- workflow shape

def _workflow():
    value = yaml.safe_load(WORKFLOW.read_text())
    return value, value.get("on", value.get(True))


pytestmark_workflow = pytest.mark.skipif(not WORKFLOW.is_file(), reason="the workflow is repository source")


@pytestmark_workflow
def test_every_job_runs_only_on_main_and_authenticate_comes_first():
    workflow, triggers = _workflow()
    assert set(triggers) == {"issues", "workflow_dispatch", "schedule"}
    assert triggers["issues"] == {"types": ["opened"]} and "pull_request_target" not in triggers
    assert not [line for line in WORKFLOW.read_text().splitlines()
                if "pull_request_target" in line and not line.lstrip().startswith("#")]
    assert workflow["permissions"] == {} and "concurrency" not in workflow
    jobs = workflow["jobs"]
    for name, job in jobs.items():
        assert job["if"].startswith("github.ref == 'refs/heads/main'") or job["if"].startswith(
            "always() && github.ref == 'refs/heads/main'"), name
    assert "needs" not in jobs["authenticate"] and "concurrency" not in jobs["authenticate"]
    for name in ("intake", "promote", "report"):
        needs = jobs[name]["needs"]
        assert "authenticate" in (needs if isinstance(needs, list) else [needs])
        assert "needs.authenticate.outputs.authenticated == 'true'" in jobs[name]["if"]
    assert jobs["report"]["if"].startswith("always()")
    assert "schedule" in jobs["reconcile"]["if"] and "needs" not in jobs["reconcile"]
    assert workflow["run-name"].count("agy-intake-{0}") == 1


@pytestmark_workflow
def test_no_issue_field_or_dispatch_input_is_interpolated_into_a_run():
    workflow, _ = _workflow()
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), step
    text = WORKFLOW.read_text()
    assert "github.event.issue.number || inputs.issue" in text  # only into env and run-name
    (author,) = [s for s in workflow["jobs"]["authenticate"]["steps"] if s.get("id") == "author"]
    assert author["env"]["ISSUE_NUMBER"] == "${{ github.event.issue.number || inputs.issue }}"


@pytestmark_workflow
def test_only_promote_and_reconcile_take_the_lock_and_name_the_promotion_environment():
    workflow, _ = _workflow()
    for name, job in workflow["jobs"].items():
        if name in ("promote", "reconcile"):
            assert job["environment"] == "agy-promotion"
            assert job["concurrency"] == {"group": "agy-catalog-promotion", "cancel-in-progress": False}
        else:
            assert "environment" not in job and "concurrency" not in job, name
            assert "secrets." not in json.dumps(job), name


@pytestmark_workflow
def test_the_intake_job_holds_no_secret_and_no_write_permission():
    workflow, _ = _workflow()
    intake = workflow["jobs"]["intake"]
    assert intake["permissions"] == {"contents": "read", "issues": "read"}
    assert "secrets." not in json.dumps(intake) and "environment" not in intake
    assert workflow["jobs"]["authenticate"]["permissions"] == {"contents": "read", "issues": "read"}
    assert workflow["jobs"]["promote"]["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["report"]["permissions"] == {"contents": "read", "issues": "write"}
    assert workflow["jobs"]["reconcile"]["permissions"] == {"contents": "read", "issues": "write", "actions": "write"}


@pytestmark_workflow
def test_third_party_actions_are_pinned_by_commit_and_no_cache_or_foreign_artifact_is_used():
    workflow, _ = _workflow()
    uses = [step["uses"] for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step]
    assert uses and all(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}", ref) for ref in uses)
    assert not [ref for ref in uses if "cache" in ref]
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "download-artifact" in step.get("uses", ""):
                assert set(step["with"]) == {"name", "path"}  # this run's own artifact: no run-id, no token
    for name in ("authenticate", "intake", "promote", "report", "reconcile"):
        assert workflow["jobs"][name]["runs-on"] == "ubuntu-latest"
