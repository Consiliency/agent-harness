#!/usr/bin/env python3
"""The trusted half of the rolling catalog job (AGYROLL ROLLJOB, ROLLJOB-detail §4.3, §4.5).

Run only by ``.github/workflows/agy-catalog-intake.yml`` on ``main``:

``authenticate --issue N``  the issue's author is the attested INTAKE App, or no later job runs
``decision-class --decision-dir D``  the class ``--intake`` decided, as a job output
``promote --decision-dir D``  under the job lock: re-check the intake decision against this
    run and the current tip of ``main``, mint the PROMOTION token, create one commit that
    writes exactly the catalog and one record on ``agy-catalog/<version>-<run>-<attempt>``,
    open the pull request, and arm auto-merge only when the four-part gate passes
``report --decision-dir D --issue N``  comment the class; close ``refused``; label and close
    ``manual`` for a writer to take into an ordinary pull request
``reconcile``  (scheduled) the oldest item that needs work, one per run, from facts an
    issues-only credential cannot edit: the App-authored pull requests and their head
    commits' trailers, and this workflow's own run history; never from labels

Nothing here parses a submission's record: where one must be verified again, reconcile
dispatches a normal run, which goes through ``authenticate``, ``intake`` and ``promote``.
Tokens never reach an argv, a log line or an output. "Update branch" is never used.
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "phase-loop-runtime" / "src"))
from phase_loop_runtime import agy_catalog_policy as policy  # noqa: E402

API = "https://api.github.com"
WORKFLOW_FILE = "agy-catalog-intake.yml"
RUN_NAME = "agy-intake-{}"
MANUAL_LABEL = "agy-intake-manual"
PROMOTION_PERMISSIONS = {"contents": "write", "pull_requests": "write"}
REQUIRED_CHECKS = ("agy catalog provenance", "agy catalog contract")
PER_PAGE = 100
MAX_PAGES = 30
MAX_HISTORY_RESULTS = 1000  # the runs listing returns at most this many results when filtered by branch
ACTIVE_RUN_STATES = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})
_NUMBER = re.compile(r"[0-9]{1,9}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_HEADER = re.compile(r"agy-intake\.v1 ((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)) [0-9a-f]{64} [0-9a-f]{64}")
_ISSUE_TRAILER = re.compile(r"^Agy-Intake-Issue: ([0-9]{1,9})$", re.MULTILINE)
_RECORD_TRAILER = re.compile(r"^Agy-Record-Sha256: ([0-9a-f]{64})$", re.MULTILINE)


class Refusal(Exception):
    """A typed stop: ``str()`` is the outcome printed and recorded."""


# ---------------------------------------------------------------------------------- the API

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a redirect is an error here; the token never follows one


class GitHub:
    """The REST and GraphQL API on ``api.github.com`` only, no redirect. ``request`` returns
    ``(status, value)``; any transport failure raises ``OSError``."""

    def __init__(self, token, *, opener=None):
        self.token, self.opener = token, opener or build_opener(_NoRedirect())

    def request(self, method, path, body=None, *, token=None):
        if not path.startswith("/") or "\n" in path:
            raise ValueError("an API path must be absolute")
        data = None if body is None else json.dumps(body).encode()
        request = Request(API + path, data=data, method=method, headers={
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-harness-agy-catalog-promote",
            "Authorization": f"Bearer {token or self.token}", **({"Content-Type": "application/json"} if data else {})})
        try:
            with self.opener.open(request, timeout=30) as response:
                text = response.read(16_000_000)
                return response.status, (json.loads(text) if text else None)
        except HTTPError as exc:
            text = exc.read(1_000_000)
            try:
                value = json.loads(text) if text else None
            except ValueError:
                value = None
            return exc.code, value
        except URLError as exc:
            raise OSError("the GitHub API is unavailable") from exc


def _call(api, method, path, body=None, *, token=None, expect=(200,)):
    status, value = api.request(method, path, body, token=token)
    if status not in expect:
        raise Refusal(f"api_{method.lower()}_failed")
    return value


def _paged(api, path, *, token=None, key=None, stop=None):
    """Every item of a listing, paged to a short page; ``Refusal`` when it cannot be proven
    complete. ``stop(item)`` ends the listing early, as complete, at the first item it accepts."""
    items = []
    for page in range(1, MAX_PAGES + 1):
        joiner = "&" if "?" in path else "?"
        value = _call(api, "GET", f"{path}{joiner}per_page={PER_PAGE}&page={page}", token=token)
        listed = value.get(key) if key and isinstance(value, dict) else value
        if not isinstance(listed, list):
            raise Refusal("listing_unreadable")
        for item in listed:
            if stop is not None and stop(item):
                return items, True
            items.append(item)
        if len(listed) < PER_PAGE:
            return items, True
    raise Refusal("listing_incomplete")


def _repository(environ):
    value = environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise Refusal("repository_unknown")
    return value


def _attestation():
    return policy.load_attestation((REPO / policy.ATTESTATION_PATH).read_text(encoding="utf-8"))


def _issue_version(issue):
    body = issue.get("body") if isinstance(issue, dict) else None
    match = _HEADER.fullmatch(body.split("\n", 1)[0]) if isinstance(body, str) else None
    return match.group(1) if match else None


def _output(environ, **values):
    path = environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")


# ------------------------------------------------------------------------------ the token

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def app_jwt(app_id, pem: str, *, now=None) -> str:
    """An RS256 App JWT (PKCS#1 v1.5, SHA-256), signed with ``cryptography``."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise Refusal("promotion_key_unusable")
    issued = int(time.time() if now is None else now)
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = _b64(json.dumps({"iat": issued - 60, "exp": issued + 540, "iss": str(app_id)},
                             separators=(",", ":")).encode())
    signature = key.sign(f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{claims}.{_b64(signature)}"


def promotion_token(api, environ, repository) -> str:
    """The PROMOTION App's installation token, limited to this repository with contents and
    pull-requests write. A wider grant is refused."""
    app_id, pem = environ.get("AGY_PROMOTION_APP_ID", ""), environ.get("AGY_PROMOTION_APP_PRIVATE_KEY", "")
    if not _NUMBER.fullmatch(app_id) or "PRIVATE KEY" not in pem:
        raise Refusal("promotion_app_unconfigured")
    jwt = app_jwt(app_id, pem)
    installation = _call(api, "GET", f"/repos/{repository}/installation", token=jwt)
    granted = _call(api, "POST", f"/app/installations/{int(installation['id'])}/access_tokens",
                    {"repositories": [repository.split("/", 1)[1]], "permissions": dict(PROMOTION_PERMISSIONS)},
                    token=jwt, expect=(201,))
    if not isinstance(granted, dict):
        raise Refusal("promotion_grant_malformed")
    permissions = granted.get("permissions")
    if (not isinstance(permissions, dict) or {k: v for k, v in permissions.items() if k != "metadata"}
            != PROMOTION_PERMISSIONS or permissions.get("metadata", "read") != "read"):
        raise Refusal("promotion_grant_wider_than_asked")
    # The whole repository grant must be exactly this repository: one well-formed entry, nothing
    # filtered away first, and a non-empty token.
    repositories, token = granted.get("repositories"), granted.get("token")
    if (not isinstance(repositories, list) or len(repositories) != 1 or not isinstance(repositories[0], dict)
            or repositories[0].get("full_name") != repository or not isinstance(token, str) or not token):
        raise Refusal("promotion_grant_malformed")
    return token


# ---------------------------------------------------------------------------------- git

def _git(runner, *args, env=None, token=None, check=True):
    """git over this checkout. A token reaches git only through its environment."""
    extra = {}
    if token is not None:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        extra = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraheader",
                 "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}"}
    done = runner(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False,
                  env={**os.environ, **(env or {}), **extra}, timeout=120)
    if check and done.returncode != 0:
        raise Refusal(f"git_{args[0]}_failed")
    return done


def _create_commit(runner, base_sha, files, message):
    """One commit on ``base_sha`` writing exactly ``files`` (path -> bytes), built with plumbing
    in a private index so nothing else in the checkout can enter it."""
    with tempfile.TemporaryDirectory(prefix="agy-promote-") as scratch:
        index = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        _git(runner, "read-tree", base_sha, env=index)
        for path, data in files.items():
            blob_file = Path(scratch) / "blob"
            blob_file.write_bytes(data)
            blob = _git(runner, "hash-object", "-w", "--no-filters", str(blob_file)).stdout.strip()
            _git(runner, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=index)
        tree = _git(runner, "write-tree", env=index).stdout.strip()
    identity = {"GIT_AUTHOR_NAME": "agy catalog promotion", "GIT_AUTHOR_EMAIL": "agy-promotion@users.noreply.github.com",
                "GIT_COMMITTER_NAME": "agy catalog promotion",
                "GIT_COMMITTER_EMAIL": "agy-promotion@users.noreply.github.com"}
    return _git(runner, "commit-tree", tree, "-p", base_sha, "-m", message, env=identity).stdout.strip()


def changed_files(runner, base_sha, commit):
    """``[(status, source mode, destination mode, path)]`` between two commits, renames off."""
    raw = _git(runner, "diff", "--raw", "-z", "--no-renames", "--no-ext-diff", base_sha, commit).stdout
    parts, entries = raw.split("\0"), []
    for header, path in zip(parts[0::2], parts[1::2]):
        src_mode, dst_mode, _a, _b, status = header[1:].split(" ")
        entries.append((status, src_mode, dst_mode, path))
    return entries


# ------------------------------------------------------------------------ the merge gate

def gate(api, attestation, environ, repository, branch, *, token):
    """The four-part gate (ROLLJOB-detail §4.5): ``(True, [])`` only when all of it holds,
    else ``(False, reasons)``. Nothing is inferred from an omitted field, and an unreadable
    attestation file, a short read or an API error leaves auto-merge off."""
    reasons = []
    if attestation is None:
        return False, ["attestation_unreadable"]
    if not attestation.attested:
        return False, ["unattested"]
    if attestation.main_ruleset["bypass_actors"] != []:
        reasons.append("main_bypass_not_empty")
    if attestation.catalog_ruleset["bypass_actors"] != [
            {"actor_type": "Integration", "actor_id": attestation.promotion_app.app_id, "bypass_mode": "always"}]:
        reasons.append("catalog_bypass_not_only_the_promotion_app")
    if not set(REQUIRED_CHECKS) <= set(attestation.main_ruleset["required_checks"]):
        reasons.append("attested_checks_incomplete")
    if environ.get("AGY_CATALOG_AUTOMERGE") != "true":
        reasons.append("switch_off")
    if reasons:
        return False, reasons
    try:
        main_rules, _ = _paged(api, f"/repos/{repository}/rules/branches/main", token=token)
        branch_rules, _ = _paged(api, f"/repos/{repository}/rules/branches/{branch}", token=token)
    except (Refusal, OSError, ValueError):
        return False, ["rules_unreadable"]
    main_id, catalog_id = attestation.main_ruleset["id"], attestation.catalog_ruleset["id"]

    def from_ruleset(rules, kind, ruleset_id):
        return [rule for rule in rules if isinstance(rule, dict) and rule.get("type") == kind
                and rule.get("ruleset_id") == ruleset_id]

    if not from_ruleset(main_rules, "pull_request", main_id):
        reasons.append("main_pull_request_rule_missing")
    checks = from_ruleset(main_rules, "required_status_checks", main_id)
    if not checks:
        reasons.append("main_required_checks_rule_missing")
    else:
        parameters = checks[0].get("parameters") or {}
        contexts = {check.get("context") for check in parameters.get("required_status_checks") or []
                    if isinstance(check, dict)}
        if parameters.get("strict_required_status_checks_policy") is not True:
            reasons.append("main_checks_not_strict")
        if not set(attestation.main_ruleset["required_checks"]) <= contexts:
            reasons.append("main_required_check_missing")
    if [rule for rule in main_rules if isinstance(rule, dict) and rule.get("type") in (
            "pull_request", "required_status_checks") and rule.get("ruleset_id") != main_id]:
        reasons.append("main_rule_from_an_unexpected_ruleset")
    for kind in ("creation", "update", "deletion"):
        if not from_ruleset(branch_rules, kind, catalog_id):
            reasons.append(f"catalog_{kind}_rule_missing")
    return not reasons, reasons


_AUTOMERGE = ("mutation($pr: ID!, $oid: GitObjectID!) { enablePullRequestAutoMerge(input: "
              "{pullRequestId: $pr, mergeMethod: SQUASH, expectedHeadOid: $oid}) { clientMutationId } }")


# ------------------------------------------------------------------------------- commands

def _decision(directory):
    directory = Path(directory)
    decision = json.loads((directory / "decision.json").read_text(encoding="utf-8"))
    if not isinstance(decision, dict) or decision.get("class") not in ("ignored", "refused", "manual", "auto"):
        raise Refusal("decision_unreadable")
    return decision


def cmd_authenticate(args, *, api, environ, out):
    """The issue's author is the attested INTAKE App: the only output that lets a later job run.
    A look-alike issue ends here, with no comment, no label and no further job."""
    if not _NUMBER.fullmatch(str(args.issue or "")):
        _output(environ, authenticated="false")
        out(json.dumps({"agy_catalog": "issue_number_malformed"}))
        return 1
    attestation = _attestation()
    issue = _call(api, "GET", f"/repos/{_repository(environ)}/issues/{int(args.issue)}")
    ok = (isinstance(issue, dict) and "pull_request" not in issue
          and policy.authentic_author(issue.get("user"), issue.get("performed_via_github_app"), attestation.intake_app))
    _output(environ, authenticated="true" if ok else "false", issue=str(int(args.issue)))
    out(json.dumps({"agy_catalog": "authenticated" if ok else "not_authenticated", "issue": int(args.issue)}))
    return 0


def cmd_decision_class(args, *, environ, out, **_):
    decision = _decision(args.decision_dir)
    _output(environ, **{"class": decision["class"]})
    out(json.dumps({"agy_catalog": "decision", "class": decision["class"]}))
    return 0


def cmd_promote(args, *, api, environ, runner, out, now=None):
    """ROLLJOB-detail §4.3 ``promote``, class ``auto`` only."""
    repository = _repository(environ)
    directory = Path(args.decision_dir)
    decision = _decision(directory)
    run_id, sha, attempt = environ.get("GITHUB_RUN_ID", ""), environ.get("GITHUB_SHA", ""), environ.get(
        "GITHUB_RUN_ATTEMPT", "1")
    if decision["class"] != "auto":
        raise Refusal("not_auto")
    # 1. this run's decision, on this run's commit, and the files it names, unchanged
    if decision.get("run_id") != run_id or decision.get("base_sha") != sha or not _NUMBER.fullmatch(attempt):
        raise Refusal("decision_from_another_run_or_base")
    version = decision.get("version")
    record_name = f"agy-{version}-linux-x64-qualification.json"
    record_bytes = (directory / record_name).read_bytes()
    catalog_bytes = (directory / "agy_catalog.json").read_bytes()
    if (sha256(record_bytes).hexdigest() != decision.get("record_sha256")
            or sha256(catalog_bytes).hexdigest() != decision.get("catalog_sha256")):
        raise Refusal("decision_files_changed")
    base_members = policy.parse_catalog((REPO / policy.CATALOG_PATH).read_text(encoding="utf-8"))
    built = policy.parse_catalog(catalog_bytes.decode("utf-8"))
    record = json.loads(record_bytes)
    change = policy.catalog_change(base_members, built, now=time.time() if now is None else now)
    candidate = policy.candidate_member(record)
    if not change.auto or len(change.added) != 1 or any(change.added[0][k] != candidate[k] for k in candidate):
        raise Refusal("not_the_auto_diff_class")
    # 2. the current base
    tip = _call(api, "GET", f"/repos/{repository}/git/ref/heads/main")
    if not isinstance(tip, dict) or (tip.get("object") or {}).get("sha") != sha:
        out(json.dumps({"agy_catalog": "stale_base", "version": version}))
        return 0
    # 3. the PROMOTION token, this repository only, contents and pull requests
    token = promotion_token(api, environ, repository)
    # 4. one commit, its link to the issue in two trailers, created only
    branch = f"{policy.CATALOG_BRANCH_PREFIX}{version}-{run_id}-{attempt}"
    message = (f"feat(agy): add agy {version} to the qualified catalog\n\n"
               f"Promoted from the intake issue {repository}#{decision['issue']} by the catalog workflow.\n\n"
               f"Agy-Intake-Issue: {decision['issue']}\nAgy-Record-Sha256: {decision['record_sha256']}\n")
    commit = _create_commit(runner, sha, {policy.CATALOG_PATH: catalog_bytes,
                                          f"plans/evidence/{record_name}": record_bytes}, message)
    _git(runner, "push", "--no-verify", "--porcelain", f"--force-with-lease=refs/heads/{branch}:", "origin",
         f"{commit}:refs/heads/{branch}", token=token)
    listed = _git(runner, "ls-remote", "origin", f"refs/heads/{branch}", token=token).stdout.split()
    expected = [("M", "100644", "100644", policy.CATALOG_PATH), ("A", "000000", "100644", f"plans/evidence/{record_name}")]
    if listed[:1] != [commit] or sorted(changed_files(runner, sha, commit)) != sorted(expected):
        raise Refusal("created_commit_not_the_two_files")
    # 5. the pull request
    pull = _call(api, "POST", f"/repos/{repository}/pulls", {
        "title": f"feat(agy): add agy {version} to the qualified catalog", "head": branch, "base": "main",
        "body": (f"Automated catalog promotion of agy {version} from {repository}#{decision['issue']}, verified "
                 f"by the intake workflow run {run_id}. The head commit's trailers link it to the issue."),
        "maintainer_can_modify": False}, token=token, expect=(201,))
    number = int(pull["number"])
    _call(api, "POST", f"/repos/{repository}/issues/{number}/labels", {"labels": [policy.CATALOG_LABEL]},
          token=token, expect=(200,))
    # 6. the merge gate, then auto-merge with the created commit as the expected head
    try:
        attestation = _attestation()
    except (OSError, ValueError):
        attestation = None  # the pull request stays open, unarmed, and the job green
    armed, reasons = gate(api, attestation, environ, repository, branch, token=token)
    if armed:
        result = _call(api, "POST", "/graphql", {"query": _AUTOMERGE, "variables": {
            "pr": pull["node_id"], "oid": commit}}, token=token)
        if not isinstance(result, dict) or result.get("errors"):
            raise Refusal("automerge_refused")
    out(json.dumps({"agy_catalog": "promoted", "version": version, "pull_request": number, "commit": commit,
                    "automerge": armed, "gate": reasons}))
    return 0


def cmd_report(args, *, api, environ, out, **_):
    """Bookkeeping on the issue: nothing reads these comments or labels as authority."""
    repository = _repository(environ)
    if not _NUMBER.fullmatch(str(args.issue or "")):
        raise Refusal("issue_number_malformed")
    number = int(args.issue)
    try:
        decision = _decision(args.decision_dir)
    except (OSError, ValueError, Refusal):
        out(json.dumps({"agy_catalog": "no_decision", "issue": number}))  # reconcile retries it
        return 0
    if decision["class"] == "ignored":
        return 0
    reasons = "; ".join(decision.get("reasons") or []) or "none"
    body = f"agy intake decision: **{decision['class']}** (run {environ.get('GITHUB_RUN_ID', '?')}). Reasons: {reasons}."
    _call(api, "POST", f"/repos/{repository}/issues/{number}/comments", {"body": body}, expect=(201,))
    if decision["class"] == "manual":
        _call(api, "POST", f"/repos/{repository}/issues/{number}/labels", {"labels": [MANUAL_LABEL]}, expect=(200,))
    if decision["class"] in ("refused", "manual"):
        _call(api, "PATCH", f"/repos/{repository}/issues/{number}", {"state": "closed"})
    out(json.dumps({"agy_catalog": "reported", "issue": number, "class": decision["class"]}))
    return 0


# ------------------------------------------------------------------------------ reconcile

class World:
    """What reconcile reads, once per run."""

    def __init__(self, api, environ, *, now):
        self.api, self.environ, self.now = api, environ, now
        self.repository = _repository(environ)
        self.attestation = _attestation()
        self.members = policy.parse_catalog((REPO / policy.CATALOG_PATH).read_text(encoding="utf-8"))
        self.versions = {member["release_version"] for member in self.members}
        tip = _call(api, "GET", f"/repos/{self.repository}/git/ref/heads/main")
        ref = tip.get("object") if isinstance(tip, dict) else None
        sha = ref.get("sha") if isinstance(ref, dict) else None
        if not isinstance(sha, str) or not _COMMIT.fullmatch(sha):
            raise Refusal("main_ref_unreadable")  # before any listing: nothing is acted on
        self.tip = sha
        issues, _ = _paged(api, f"/repos/{self.repository}/issues?state=open&sort=created&direction=asc")
        self.issues = [issue for issue in issues if "pull_request" not in issue and policy.authentic_author(
            issue.get("user"), issue.get("performed_via_github_app"), self.attestation.intake_app)
            and _issue_version(issue) is not None]
        self.issues.sort(key=lambda issue: (policy.parse_instant(issue.get("created_at")) or 0, issue["number"]))
        self.open_pulls = self._promotions("open")
        oldest = min((policy.parse_instant(issue.get("created_at")) or 0 for issue in self.issues), default=self.now)
        self.closed_pulls = self._promotions("closed", since=oldest)

    def _promotions(self, state, since=None):
        """Pull requests on ``agy-catalog/…`` in this repository authored by the PROMOTION App,
        each with the issue its head commit's trailer names (labels, titles and bodies are
        never read)."""
        stop = None
        if since is not None:
            def stop(pull):
                created = policy.parse_instant(pull.get("created_at"))
                return created is not None and created < since
        pulls, _ = _paged(self.api, f"/repos/{self.repository}/pulls?state={state}&sort=created&direction=desc",
                          stop=stop)
        found = []
        for pull in pulls:
            head = pull.get("head") or {}
            if not str(head.get("ref", "")).startswith(policy.CATALOG_BRANCH_PREFIX) or (
                    head.get("repo") or {}).get("full_name") != self.repository:
                continue
            issue = _call(self.api, "GET", f"/repos/{self.repository}/issues/{int(pull['number'])}")
            if not policy.authentic_author(issue.get("user"), issue.get("performed_via_github_app"),
                                           self.attestation.promotion_app):
                continue
            commit = _call(self.api, "GET", f"/repos/{self.repository}/commits/{head.get('sha')}")
            message = ((commit or {}).get("commit") or {}).get("message") or ""
            link = _ISSUE_TRAILER.findall(message)
            if len(link) != 1 or len(_RECORD_TRAILER.findall(message)) != 1:
                continue
            # The commit the promotion was built and verified on is the head commit's sole
            # parent (promote writes exactly one commit on it). Unlike the pull request's
            # ``base.sha``, which follows the base ref as main advances, it never changes.
            parents = (commit or {}).get("parents")
            built_on = (parents[0].get("sha") if isinstance(parents, list) and len(parents) == 1
                        and isinstance(parents[0], dict) else None)
            found.append({**pull, "linked_issue": int(link[0]), "built_on": built_on})
        found.sort(key=lambda pull: (policy.parse_instant(pull.get("created_at")) or 0, pull["number"]))
        return found

    def issue(self, number):
        return next((issue for issue in self.issues if issue["number"] == number), None)

    def eligible(self, version):
        key = policy.release_key(version)
        return key is not None and version not in self.versions and all(
            (policy.release_key(v) or (-1,)) < key for v in self.versions)


def _pull_version(pull):
    match = re.fullmatch(re.escape(policy.CATALOG_BRANCH_PREFIX) + r"(\d+\.\d+\.\d+)-[0-9]+-[0-9]+",
                         str((pull.get("head") or {}).get("ref", "")))
    return match.group(1) if match else None


def _dispatch(world, number):
    _call(world.api, "POST", f"/repos/{world.repository}/actions/workflows/{WORKFLOW_FILE}/dispatches",
          {"ref": "main", "inputs": {"issue": str(number)}}, expect=(204,))


def _close_issue(world, number, body):
    _call(world.api, "POST", f"/repos/{world.repository}/issues/{number}/comments", {"body": body}, expect=(201,))
    _call(world.api, "PATCH", f"/repos/{world.repository}/issues/{number}", {"state": "closed"})


def history(world, issue):
    """This workflow's runs on ``main`` named exactly for ``issue``, created since it, read
    back to its creation time (or the end of the history). ``Refusal("history_unavailable")``
    when any page fails, a run carries no usable run name, or the listing ends at the API's
    result limit before that boundary: an unreadable history is never a verified count."""
    created = policy.parse_instant(issue.get("created_at"))
    if created is None:
        raise Refusal("history_unavailable")
    name, runs, read = RUN_NAME.format(issue["number"]), [], 0
    path = f"/repos/{world.repository}/actions/workflows/{WORKFLOW_FILE}/runs?branch=main"
    try:
        for page in range(1, MAX_HISTORY_RESULTS // PER_PAGE + 1):
            value = _call(world.api, "GET", f"{path}&per_page={PER_PAGE}&page={page}")
            listed = value.get("workflow_runs") if isinstance(value, dict) else None
            if not isinstance(listed, list):
                raise Refusal("history_unavailable")
            for run in listed:
                read += 1
                at = policy.parse_instant(run.get("created_at"))
                title = run.get("display_title")
                if at is None or not isinstance(title, str) or type(run.get("id")) is not int:
                    raise Refusal("history_unavailable")
                if at < created:
                    return runs  # the issue-age boundary
                if title == name:
                    runs.append(run)
            if len(listed) < PER_PAGE:
                return runs  # the end of the history
    except (Refusal, OSError, ValueError, KeyError, TypeError, AttributeError):
        # A non-200 page (``api_get_failed``) is as unreadable as a malformed one.
        raise Refusal("history_unavailable") from None
    raise Refusal("history_unavailable")  # stopped at the result limit before the boundary


def _ended_without_a_pull(world, run, version):
    prefix = f"{policy.CATALOG_BRANCH_PREFIX}{version}-{run['id']}-"
    return not any(str((pull.get("head") or {}).get("ref", "")).startswith(prefix)
                   for pull in world.open_pulls + world.closed_pulls)


def _attempts(world, issue_number):
    """Promotions for an issue that ended unmerged: closed, unmerged pull requests authored by
    the PROMOTION App whose head commit's trailer names the issue. Read from GitHub on every
    run, so the count survives a reconcile that stopped part-way."""
    return sum(1 for pull in world.closed_pulls
               if pull["linked_issue"] == issue_number and not pull.get("merged_at"))


def _supersede(world, pull, reason, *, rebuild):
    token = promotion_token(world.api, world.environ, world.repository)
    number = int(pull["number"])
    _call(world.api, "POST", f"/repos/{world.repository}/issues/{number}/comments",
          {"body": f"Superseded by the catalog workflow: {reason}."}, token=token, expect=(201,))
    _call(world.api, "PATCH", f"/repos/{world.repository}/pulls/{number}", {"state": "closed"}, token=token)
    _call(world.api, "DELETE", f"/repos/{world.repository}/git/refs/heads/{pull['head']['ref']}", token=token,
          expect=(204,))
    if rebuild:
        _dispatch(world, pull["linked_issue"])


def cmd_reconcile(args, *, api, environ, out, now=None, **_):
    """The oldest item that needs work, one per run; the cases in order, the first that
    applies the only one acted on (ROLLJOB-detail §4.3)."""
    world = World(api, environ, now=time.time() if now is None else now)
    switch_on = environ.get("AGY_CATALOG_AUTOMERGE") == "true"
    # (a) an intake issue whose version is now a member
    for issue in world.issues:
        version = _issue_version(issue)
        if version in world.versions:
            _close_issue(world, issue["number"], f"agy {version} is now a catalog member.")
            out(json.dumps({"agy_catalog": "closed_member", "issue": issue["number"], "version": version}))
            return 0
    # (b) a promotion built on a commit that is no longer the tip, or unarmed while the switch is on
    for pull in world.open_pulls:
        stale = pull.get("built_on") is None or pull["built_on"] != world.tip
        unarmed = switch_on and pull.get("auto_merge") is None
        if not (stale or unarmed):
            continue
        version = _pull_version(pull)
        linked = world.issue(pull["linked_issue"])
        rebuild = version is not None and world.eligible(version) and linked is not None
        reason = ("its base is no longer the tip of main" if stale else "created while auto-merge was off")
        if not rebuild:
            reason = "its version is no longer newer than every catalog member"
        elif _attempts(world, pull["linked_issue"]) + 1 >= policy.MAX_PROMOTION_ATTEMPTS:
            # Counted before anything is closed or dispatched, this supersession included: the
            # limit is reached, so no rebuild. The next run's case (c) closes the issue `stalled`.
            rebuild, reason = False, f"{reason}; the attempt limit is reached"
        _supersede(world, pull, reason, rebuild=rebuild)
        out(json.dumps({"agy_catalog": "superseded", "pull_request": int(pull["number"]), "rebuild": rebuild,
                        "reason": reason}))
        return 0
    # (c) an issue whose promotion has been superseded MAX_PROMOTION_ATTEMPTS times
    for issue in world.issues:
        superseded = _attempts(world, issue["number"])
        if superseded >= policy.MAX_PROMOTION_ATTEMPTS:
            _close_issue(world, issue["number"], "stalled: its promotion was superseded "
                                                 f"{superseded} times.")
            out(json.dumps({"agy_catalog": "stalled", "issue": issue["number"], "cause": "superseded"}))
            return 0
    # (d) an issue with no open promotion: the stall threshold first, then a dispatch
    for issue in world.issues:
        if any(pull["linked_issue"] == issue["number"] for pull in world.open_pulls):
            continue
        runs = history(world, issue)
        if any(run.get("status") in ACTIVE_RUN_STATES for run in runs):
            continue  # a matching run is queued or in progress: nothing this time
        completed = [run for run in runs if run.get("status") == "completed"][:policy.MAX_PREPR_FAILURES]
        version = _issue_version(issue)
        if len(completed) >= policy.MAX_PREPR_FAILURES and all(
                _ended_without_a_pull(world, run, version) for run in completed):
            _close_issue(world, issue["number"], f"stalled: the {len(completed)} latest runs for it ended "
                                                 "without a pull request.")
            out(json.dumps({"agy_catalog": "stalled", "issue": issue["number"], "cause": "no_pull_request"}))
            return 0
        _dispatch(world, issue["number"])
        out(json.dumps({"agy_catalog": "dispatched", "issue": issue["number"]}))
        return 0
    out(json.dumps({"agy_catalog": "nothing_to_reconcile"}))
    return 0


COMMANDS = {"authenticate": cmd_authenticate, "decision-class": cmd_decision_class, "promote": cmd_promote,
            "report": cmd_report, "reconcile": cmd_reconcile}


def main(argv=None, *, api=None, environ=None, runner=subprocess.run, out=print, now=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--issue")
    parser.add_argument("--decision-dir")
    args = parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    if args.command in ("decision-class", "promote", "report") and not args.decision_dir:
        parser.error("--decision-dir is required")
    if args.command in ("authenticate", "report") and args.issue is None:
        parser.error("--issue is required")
    api = api or GitHub(environ.get("GH_TOKEN", ""))
    command = COMMANDS[args.command]
    try:
        kwargs = {"api": api, "environ": environ, "out": out}
        if args.command == "promote":
            kwargs.update(runner=runner, now=now)
        if args.command == "reconcile":
            kwargs["now"] = now
        return command(args, **kwargs)
    except Refusal as exc:
        out(json.dumps({"agy_catalog": str(exc)}))
        summary = environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as stream:
                stream.write(f"agy catalog {args.command}: {exc}\n")
        return 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        out(json.dumps({"agy_catalog": "failed", "error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
