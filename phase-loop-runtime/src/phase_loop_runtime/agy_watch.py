"""Upstream agy release watch (agent-harness#1076), run from a timer on a subscribed host.

It is deliberately OUTSIDE ``agy_qualification.ROUTE_CORE``: a watch-only fix never forces
a requalification. For the newest stable release not yet pinned on ``main`` it:

1. is idempotent per version: an open, same-repository PR authored by the running
   identity, labelled for that version with the CURRENT ``main`` route-core digest, whose
   head is still exactly the commit on its branch, makes the tick a no-op;
2. builds a VerifiedImage from the provenance-checked archive member stream (no install);
3. in a fresh checkout of current ``main`` with the constants and catalog edited, measures
   help with THAT tree's owned profile and runs the manual qualification (the shim) from
   that tree, handing the image over as a sealed fd (``--image-fd``, the worker's seal
   check applies). The tree's own release constant satisfies the worker gate, so the
   record matches the tree -- what ``--route-core`` requires -- and never depends on the
   recency window. Adding a member edits ``gemini_heartbeat.py``, which every existing
   record pins, so EVERY catalog member is requalified on the prepared tree: each existing
   member's image is re-fetched from its own release and must match its record's asset
   and image digests;
4. pushes a FRESH, unique branch ``agy-watch/<version>-<utc>-<random>`` with create-only
   semantics (``--force-with-lease=refs/heads/<name>:``, an empty expected value, to a
   fully qualified destination), opens a DRAFT PR from it, and then closes its own older
   open watch PRs for that version. It never updates, force-pushes, adopts or deletes an
   existing branch, and never merges (agent-harness#1130 r3: ownership of an existing
   branch is not something the watch tries to prove).

Only the release route (Linux x64 glibc; ``qualified_provider_images.v2`` has only that
route) is proposed; any other platform reports and opens nothing.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone
import secrets
import shutil
import subprocess
import sys
import tempfile

from . import agy_provenance
from . import gemini_heartbeat as gh

RELEASE_ROUTE_PLATFORM = "linux-x64"
BRANCH_PREFIX = "agy-watch/"
MARKER = "agy-watch-base-route-core:"
CATALOG = "plans/evidence/qualified-provider-images.json"
HEARTBEAT = "phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py"
OPERATIONS = ("completion", "cancel", "owner-loss")
REPO_SLUG = "Consiliency/agent-harness"
REPO_OWNER = REPO_SLUG.split("/")[0]


VERSION_LABEL = "agy-watch-version:"
_OPEN_PRS_QUERY = (
    "query($owner:String!,$repo:String!,$endCursor:String){repository(owner:$owner,name:$repo){"
    "pullRequests(states:OPEN,first:100,after:$endCursor){totalCount pageInfo{hasNextPage endCursor}"
    "nodes{number body headRefName headRefOid isCrossRepository author{login} headRepositoryOwner{login}}}}}"
)


class IncompleteListing(RuntimeError):
    """The open-PR listing could not be proven complete."""


def open_prs(runner, repo: Path) -> list[dict]:
    """EVERY open PR of this repository, paginated to the end, or IncompleteListing.

    Completeness is established, not assumed: the pages must end with ``hasNextPage``
    false and together hold exactly ``totalCount`` nodes. No fixed limit anywhere."""
    owner, name = REPO_SLUG.split("/")
    listed = _run(runner, ["gh", "api", "graphql", "--paginate", "-f", f"query={_OPEN_PRS_QUERY}",
                           "-F", f"owner={owner}", "-F", f"repo={name}"], cwd=repo)
    decoder, text, pages = json.JSONDecoder(), (listed.stdout or "").strip(), []
    try:
        while text:
            page, index = decoder.raw_decode(text)
            pages.append(page["data"]["repository"]["pullRequests"])
            text = text[index:].strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise IncompleteListing("agy watch: unparseable PR listing") from exc
    if not pages or pages[-1]["pageInfo"]["hasNextPage"] is not False:
        raise IncompleteListing("agy watch: PR listing did not reach its last page")
    nodes = [node for page in pages for node in page["nodes"]]
    totals = {page["totalCount"] for page in pages}
    if len(totals) != 1 or len(nodes) != totals.pop():
        raise IncompleteListing("agy watch: PR listing is truncated or changed while paging")
    return nodes


def _fresh_name_re(version: str):
    return re.compile(rf"{re.escape(BRANCH_PREFIX + version)}-\d{{8}}T\d{{6}}Z-[0-9a-f]{{8}}")


def own_version_prs(nodes: list[dict], login: str, version: str) -> list[dict]:
    """Open PRs the watch opened for ``version``: same repository, authored by the running
    identity, head on a fresh ``agy-watch/<version>-<utc>-<random>`` branch, carrying the
    version label."""
    name = _fresh_name_re(version)
    return [pr for pr in nodes
            if bool(login) and pr.get("isCrossRepository") is False
            and (pr.get("headRepositoryOwner") or {}).get("login") == REPO_OWNER
            and (pr.get("author") or {}).get("login") == login
            and name.fullmatch(str(pr.get("headRefName") or "")) is not None
            and f"{VERSION_LABEL} {version}\n" in (pr.get("body") or "")]


def remote_branch_head(runner, repo: Path, branch: str) -> str | None:
    """The oid of EXACTLY ``refs/heads/<branch>`` in origin (``ls-remote`` matches refs by
    tail pattern, so ``refs/heads/x/refs/heads/<branch>`` would also be listed). Any
    exact-ref line counts as existing, whatever its oid format."""
    listed = _run(runner, ["git", "-C", str(repo), "ls-remote", "origin", f"refs/heads/{branch}"])
    for line in (listed.stdout or "").splitlines():
        oid, _, ref = line.partition("\t")
        if ref.strip() == f"refs/heads/{branch}":
            return oid.strip() or "unknown"
    return None


def fresh_branch_name(version: str, *, now=None, token=None) -> str:
    """A sibling of every other watch branch, never a child: ``<version>/...`` would be
    blocked (a git directory/file ref conflict) by anyone pushing a plain
    ``agy-watch/<version>``, including the pre-agent-harness#1130-r3 watch's own name."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"{BRANCH_PREFIX}{version}-{stamp}-{token or secrets.token_hex(4)}"


def publish_branch(runner, tree: Path, name: str) -> None:
    """Create ``refs/heads/<name>`` in origin, or fail atomically if it exists: the lease's
    EMPTY expected value means "must not exist", and the destination is fully qualified."""
    _run(runner, ["git", "-C", str(tree), "push", "--porcelain", f"--force-with-lease=refs/heads/{name}:",
                  "origin", f"HEAD:refs/heads/{name}"])


def _run(runner, argv, **kwargs):
    kwargs.setdefault("check", True)
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return runner(argv, **kwargs)


def route_core_digest(tree: Path) -> str:
    from .agy_qualification import ROUTE_CORE
    package = tree / "phase-loop-runtime/src/phase_loop_runtime"
    return sha256(json.dumps({name: sha256((package / name).read_bytes()).hexdigest() for name in ROUTE_CORE},
                             sort_keys=True).encode()).hexdigest()


def pinned_versions(tree: Path) -> set[str]:
    catalog = json.loads((tree / CATALOG).read_text())
    return {member["release_version"] for route in catalog["routes"].values() for member in route["images"]}


def edit_constants(tree: Path, image_sha256: str, help_sha256: str, version: str) -> None:
    """Add (or replace) one member in the runtime literal and the catalog."""
    path = tree / HEARTBEAT
    text = path.read_text()
    text = re.sub(rf'\n    # agy {re.escape(version)}\n    "[0-9a-f]{{64}}":\n        "[0-9a-f]{{64}}",', "", text)
    entry = f'    # agy {version}\n    "{image_sha256}":\n        "{help_sha256}",\n}}\nPROFILE_ID'
    text, count = re.subn(r"\}\nPROFILE_ID", entry, text, count=1)
    if count != 1:
        raise ValueError("agy watch cannot locate QUALIFIED_IMAGES")
    path.write_text(text)
    catalog_path = tree / CATALOG
    catalog = json.loads(catalog_path.read_text())
    route = catalog["routes"]["gemini_heartbeat_linux_x64"]
    route["images"] = [m for m in route["images"] if m["release_version"] != version] + [{
        "release_version": version, "image_sha256": image_sha256, "help_sha256": help_sha256,
        "record": f"agy-{version}-linux-x64-qualification.json"}]
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")


def _catalog_members(tree: Path) -> list[dict]:
    return list(json.loads((tree / CATALOG).read_text())["routes"]["gemini_heartbeat_linux_x64"]["images"])


def _pinned_member(tree: Path, member: dict, host, transport):
    """Re-fetch an already-pinned member's image; its release asset digest and image digest
    must equal its committed record's."""
    record = json.loads((tree / "plans/evidence" / member["record"]).read_text())
    asset = agy_provenance.release_asset(agy_provenance.release_by_tag(transport, member["release_version"]), host)
    if asset.digest != record["upstream_asset_sha256"]:
        raise agy_provenance.ProvenanceError(agy_provenance.UNVERIFIED)
    digest, data = agy_provenance.fetch_member(transport, asset, keep_bytes=True)
    if digest != member["image_sha256"] or digest != record["image_sha256"]:
        raise agy_provenance.ProvenanceError(agy_provenance.UNVERIFIED)
    return asset, gh.VerifiedImage.from_bytes(data), member["help_sha256"]


def summarize(tree: Path, series: Path, asset, image_sha256: str, help_sha256: str, *,
              template_name: str | None = None) -> dict:
    """The redacted record, in the shape of a committed record (see the release process's
    regeneration rule): each operation row is its receipt restricted to the template row's
    keys. A requalified member is its own template; a new one takes the newest other."""
    catalog = json.loads((tree / CATALOG).read_text())
    members = catalog["routes"]["gemini_heartbeat_linux_x64"]["images"]
    if template_name is None:
        template_name = next(m["record"] for m in reversed(members) if m["release_version"] != asset.version)
    template = json.loads((tree / "plans/evidence" / template_name).read_text())

    def restrict(value, shape):
        if isinstance(shape, dict):
            source = value if isinstance(value, dict) else {}
            return {key: restrict(source.get(key), shape[key]) for key in shape}
        return value

    shapes = {row["operation"]: row for row in template["records"]}
    rows, sources = [], set()
    for operation in sorted(OPERATIONS):
        raw = (series / operation / "qualification.json").read_bytes()
        receipt = json.loads(raw)
        sources.add(json.dumps(receipt["source_sha256"], sort_keys=True))
        row = {}
        for key in shapes[operation]:
            if key == "raw_receipt_sha256":
                row[key] = sha256(raw).hexdigest()
            elif key == "request_digests":
                row[key] = receipt["request"]
            else:
                row[key] = restrict(receipt.get(key), shapes[operation][key])
        rows.append(row)
    if len(sources) != 1:
        raise ValueError("agy watch receipts disagree on source pins")
    record = dict(template)
    record.update({
        "schema": "agy_redacted_qualification_summary.v1", "release_version": asset.version,
        "image_sha256": image_sha256, "help_sha256": help_sha256,
        "upstream_asset_name": asset.name, "upstream_asset_sha256": asset.digest,
        "upstream_release_url": f"https://github.com/{agy_provenance.REPO}/releases/tag/{asset.version}",
        "records": rows, "source_sha256": json.loads(sources.pop()),
        "validator": {"validated": 3, "operations": ["cancel", "completion", "owner-loss"], "route_qualified": True},
    })
    return record


def _tree_python(tree: Path, python: str, args, *, image_fd: int, runner, env):
    return _run(runner, [python, str(tree / "phase-loop-runtime/scripts/qualify_gemini_heartbeat.py"), *args,
                         "--image-fd", str(image_fd)],
                cwd=tree / "phase-loop-runtime", env={**env, "PYTHONPATH": str(tree / "phase-loop-runtime/src")},
                pass_fds=(image_fd,))


def main(*, repo=None, dry_run=False, runner=subprocess.run, host=None, transport=None,
         python=sys.executable, workdir=None, out=print, version=None, base_ref="origin/main") -> int:
    """One watch tick. ``version`` selects a specific in-window stable release instead of
    the newest (an operator re-run, or a dry run against a non-pinned build). ``base_ref``
    is for a dry run only: a published tick always prepares from ``origin/main``."""
    if base_ref != "origin/main" and not dry_run:
        raise ValueError("agy watch: --base-ref is only for --dry-run")
    host = host or agy_provenance.detect_platform()
    if host.name != RELEASE_ROUTE_PLATFORM:
        out(json.dumps({"agy_watch": "platform_not_proposed", "platform": host.name}))
        return 0
    repo = Path(repo or ".").resolve()
    transport = transport or agy_provenance._Transport()
    releases = agy_provenance.stable_releases(transport, window=1 if version is None else agy_provenance.RECENCY_WINDOW)
    if version is not None:
        releases = [r for r in releases if r.get("tag_name") == version]
    if not releases:
        out(json.dumps({"agy_watch": "no_stable_release"}))
        return 0
    asset = agy_provenance.release_asset(releases[0], host)
    _run(runner, ["git", "-C", str(repo), "fetch", "origin", "main"])
    workdir = Path(workdir or tempfile.mkdtemp(prefix="agy-watch-"))
    tree = workdir / "tree"
    # Detached: the watch never creates or moves a named branch, locally or in origin,
    # except the one fresh branch it publishes below.
    _run(runner, ["git", "-C", str(repo), "worktree", "add", "--force", "--detach", str(tree), base_ref])
    try:
        if asset.version in pinned_versions(tree):
            out(json.dumps({"agy_watch": "already_pinned", "version": asset.version}))
            return 0
        base = route_core_digest(tree)
        login = _run(runner, ["gh", "api", "user", "-q", ".login"], cwd=repo).stdout.strip()
        try:
            prs = own_version_prs(open_prs(runner, repo), login, asset.version)
        except IncompleteListing as exc:
            out(json.dumps({"agy_watch": "refused_incomplete_pr_listing", "reason": str(exc)}))
            return 2
        # Up to date only when an own PR for this version carries the CURRENT base label AND
        # its head is still exactly the commit on its branch (nobody pushed onto it).
        if any(f"{MARKER} {base}" in (pr.get("body") or "")
               and remote_branch_head(runner, repo, pr["headRefName"]) == pr.get("headRefOid")
               for pr in prs):
            out(json.dumps({"agy_watch": "up_to_date", "version": asset.version}))
            return 0
        member_sha256, member = agy_provenance.fetch_member(transport, asset, keep_bytes=True)
        images = {asset.version: (asset, gh.VerifiedImage.from_bytes(member), None)}
        del member
        try:
            for existing_member in _catalog_members(tree):
                images[existing_member["release_version"]] = _pinned_member(tree, existing_member, host, transport)
            env = dict(os.environ)
            new_image = images[asset.version][1]
            edit_constants(tree, new_image.sha256, "0" * 64, asset.version)
            help_paths = {}
            for version_key, (member_asset, image, pinned_help) in images.items():
                help_path = workdir / f"agy-help-{version_key}.txt"
                fd = image.reopen()
                try:
                    _tree_python(tree, python, ["--measure-help", "--output", str(help_path)], image_fd=fd,
                                 runner=runner, env=env)
                finally:
                    os.close(fd)
                measured = sha256(help_path.read_bytes()).hexdigest()
                if pinned_help is not None and measured != pinned_help:
                    raise ValueError(f"agy watch: pinned member {version_key} help changed")
                help_paths[version_key] = help_path
            help_sha256 = sha256(help_paths[asset.version].read_bytes()).hexdigest()
            edit_constants(tree, new_image.sha256, help_sha256, asset.version)
            for version_key, (member_asset, image, _) in images.items():
                series = workdir / "series" / version_key
                series.mkdir(parents=True)
                for operation in OPERATIONS:
                    fd = image.reopen()
                    try:
                        _tree_python(tree, python, ["--operation", operation, "--output", str(series / operation),
                                                    "--help-evidence", str(help_paths[version_key])],
                                     image_fd=fd, runner=runner, env=env)
                    finally:
                        os.close(fd)
                _run(runner, [python, str(tree / "phase-loop-runtime/scripts/qualify_gemini_heartbeat.py"),
                              "--validate", str(series)], cwd=tree / "phase-loop-runtime",
                     env={**env, "PYTHONPATH": str(tree / "phase-loop-runtime/src")})
                member_help = sha256(help_paths[version_key].read_bytes()).hexdigest()
                record_name = f"agy-{version_key}-linux-x64-qualification.json"
                record = summarize(tree, series, member_asset, image.sha256, member_help,
                                   template_name=None if version_key == asset.version else record_name)
                (tree / "plans/evidence" / record_name).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            _run(runner, [python, str(tree / "phase-loop-runtime/scripts/verify_qualified_agy_image.py"),
                          "--route-core"], cwd=tree)
        finally:
            for _, image, _ in images.values():
                image.close()
        if dry_run:
            out(json.dumps({"agy_watch": "dry_run_verified", "version": asset.version, "tree": str(tree),
                            "image_sha256": member_sha256}))
            return 0
        _run(runner, ["git", "-C", str(tree), "add", "-A"])
        _run(runner, ["git", "-C", str(tree), "-c", "commit.gpgsign=false", "commit", "-m",
                      f"feat(agy): qualify the {asset.version} entry image (agy watch, agent-harness#1076)\n\n"
                      f"{MARKER} {base}"])
        branch = fresh_branch_name(asset.version)
        try:
            publish_branch(runner, tree, branch)
        except subprocess.CalledProcessError:
            out(json.dumps({"agy_watch": "refused_branch_exists", "branch": branch}))
            return 2
        body = (f"Automated upstream-watch qualification of agy {asset.version} (agent-harness#1076).\n\n"
                f"Record produced from this branch's own tree; `verify_qualified_agy_image.py --route-core` passed.\n"
                f"Never merged by the watch.\n\n{VERSION_LABEL} {asset.version}\n{MARKER} {base}\n")
        created = _run(runner, ["gh", "pr", "create", "--draft", "--repo", REPO_SLUG, "--base", "main",
                                "--head", branch, "--title", f"feat(agy): qualify agy {asset.version} (upstream watch)",
                                "--body", body], cwd=repo)
        new_url = (created.stdout or "").strip()
        for pr in prs:  # supersede: CLOSE our own older PRs for this version; never push, never delete
            _run(runner, ["gh", "pr", "close", str(pr["number"]), "--repo", REPO_SLUG,
                          "--comment", f"Superseded by {new_url or branch} (agy watch)."], cwd=repo)
        out(json.dumps({"agy_watch": "draft_pr", "version": asset.version}))
        return 0
    finally:
        if not dry_run:
            _run(runner, ["git", "-C", str(repo), "worktree", "remove", "--force", str(tree)], check=False)
            shutil.rmtree(workdir, ignore_errors=True)
