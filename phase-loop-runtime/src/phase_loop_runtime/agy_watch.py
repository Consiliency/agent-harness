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
   fully qualified destination) and opens a DRAFT PR from it that names, but does not
   touch, the own older PRs it supersedes. Exactly one ref write (the new branch) and one
   object create (the new PR) per tick; it never updates, force-pushes, adopts, closes,
   edits or deletes anything that existed before the tick, and never merges
   (agent-harness#1130 r3/r4).

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
PUSHED_LABEL = "agy-watch-pushed-oid:"


def _label_value(body, label):
    """The value of ``<label> <value>`` on its own line; CRLF-tolerant (a body edited in the
    web UI may be stored with ``\r\n``)."""
    for line in (body or "").splitlines():
        line = line.strip()
        if line.startswith(label + " "):
            return line[len(label):].strip()
    return None
_OPEN_PRS_QUERY = (
    "query($owner:String!,$repo:String!,$endCursor:String){repository(owner:$owner,name:$repo){"
    "pullRequests(states:OPEN,first:100,after:$endCursor){totalCount pageInfo{hasNextPage endCursor}"
    "nodes{number body headRefName headRefOid isCrossRepository author{login} headRepositoryOwner{login}}}}}"
)


class IncompleteListing(ValueError):
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
        if not pages or pages[-1]["pageInfo"]["hasNextPage"] is not False:
            raise IncompleteListing("agy watch: PR listing did not reach its last page")
        nodes = [node for page in pages for node in page["nodes"]]
        totals = {page["totalCount"] for page in pages}
        numbers = [node["number"] for node in nodes]
        distinct = len(set(numbers))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        if isinstance(exc, IncompleteListing):
            raise
        raise IncompleteListing("agy watch: unparseable PR listing") from exc
    if len(totals) != 1 or distinct != len(numbers) or len(nodes) != totals.pop():
        raise IncompleteListing("agy watch: PR listing is truncated, has duplicates or changed while paging")
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
            and _label_value(pr.get("body"), VERSION_LABEL) == version]


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


def _push_state(store=None):
    """The watch's OWN record of what it pushed (agent-harness#1130 r5, codex B1): an
    HMAC-bound ``watch_push`` entry in the operator-only per-user, per-host store (0700/0600,
    owner-checked, O_NOFOLLOW). The PR body's oid is display-only and never read back."""
    from .agy_qualification import Store
    return store or Store()


def _push_context(branch: str, version: str, base: str) -> dict:
    # The version and route-core base are bound into the MAC too (claude N3 on
    # agent-harness#1130 r6): a body relabelled to the current base cannot reuse an old push.
    return {"branch": branch, "version": version, "base": base}


def ensure_push_state(store=None) -> bool:
    """Pre-flight (claude N2 on agent-harness#1130 r6): the store must be writable and read
    back BEFORE anything is pushed, so a verified push can always be recorded."""
    try:
        store = _push_state(store)
        if store.status() == "absent":
            store.create()
        context = {"branch": "\0preflight", "version": "", "base": ""}
        store.put("watch_push", context, context, {"oid": "preflight"})
        ok = (store.get("watch_push", context, context) or {}).get("oid") == "preflight"
        store._path("watch_push", context).unlink(missing_ok=True)
        return ok
    except (OSError, ValueError):
        return False


def record_push(branch: str, oid: str, version: str, base: str, store=None) -> None:
    store = _push_state(store)
    if store.status() == "absent":
        store.create()
    context = _push_context(branch, version, base)
    store.put("watch_push", context, context, {"oid": oid})


def recorded_push(branch: str, version: str, base: str, store=None) -> str | None:
    """The oid this watch pushed to ``branch`` for ``version`` at route-core ``base``, or None
    when missing, tampered, foreign or for another branch/version/base (then the PR is simply
    not up to date: a duplicate PR, never adoption)."""
    context = _push_context(branch, version, base)
    try:
        payload = _push_state(store).get("watch_push", context, context)
    except (OSError, ValueError):
        return None
    value = payload.get("oid") if payload else None
    return value if isinstance(value, str) and value else None


def single_push_url(runner, tree: Path) -> str | None:
    """``origin``'s push URL iff git lists exactly ONE push destination; display text only.

    Counts git's raw output lines, blanks included (an older git keeps an empty
    ``pushurl =`` as an entry of its own). The value is never compared with anything and
    never passed back to git: the push goes to the remote NAME ``origin``, which git resolves
    to exactly this list (agent-harness#1130 r7).
    """
    listed = _run(runner, ["git", "-C", str(tree), "remote", "get-url", "--push", "--all", "origin"], check=False)
    if getattr(listed, "returncode", 1) != 0:
        return None
    lines = (listed.stdout or "").splitlines()
    return lines[0].strip() if len(lines) == 1 and lines[0].strip() else None


def _push_argv(tree: Path, ref: str, *, dry_run: bool) -> list:
    # --no-verify: a pre-push hook runs even for --dry-run, and must never run here.
    return ["git", "-C", str(tree), "push", *(["--dry-run"] if dry_run else []), "--porcelain",
            "--no-verify", "--no-follow-tags", "--recurse-submodules=no", f"--force-with-lease={ref}:",
            "--", "origin", f"HEAD:{ref}"]


def _to_blocks(result) -> int:
    return sum(1 for line in (result.stdout or "").splitlines() if line.startswith("To "))


def publish_branch(runner, tree: Path, name: str) -> str:
    """Create ``refs/heads/<name>`` at exactly ONE destination; ``"created"`` or a typed refusal.

    Nothing is resolved twice (codex B2 on agent-harness#1130 r5-r7). ``git remote get-url
    --push --all origin`` must list exactly one destination, and the push goes to the remote
    NAME ``origin`` -- the same list -- never to a printed string. So no URL is compared with
    git's display form (which rewrites scp-style and credentialed URLs): the gates are COUNTS.
    A ``--dry-run`` pre-flight must print exactly one ``To`` block (none = unavailable), and
    the real push exactly one ``To`` block and one row for exactly ``refs/heads/<name>``.

    The lease's EMPTY expected value means "must not exist", but a zero exit is NOT proof of
    creation (a ref already at HEAD is "up to date", exit 0): creation is read from
    ``--porcelain`` -- flag ``*``. ``--no-follow-tags --recurse-submodules=no`` keep host
    config from widening the push; ``--no-verify`` keeps pre-push hooks from running. The
    bot host's own git/ssh configuration (``core.sshCommand``, ``receivepack``, remote
    helpers) is trusted; it is read at each git invocation (docs/ops/agy-upstream-watch.md).
    """
    ref = f"refs/heads/{name}"
    if single_push_url(runner, tree) is None:
        return "refused_push_destination_ambiguous"  # zero or several push destinations: push nothing
    preflight = _run(runner, _push_argv(tree, ref, dry_run=True), check=False)
    blocks = _to_blocks(preflight)
    if blocks == 0:
        return "push_unavailable"  # auth, network or a hook failure before any status
    if blocks != 1:
        return "refused_push_destination_ambiguous"  # git would push to several places: push nothing
    result = _run(runner, _push_argv(tree, ref, dry_run=False), check=False)
    lines = [line.split("\t") for line in (result.stdout or "").splitlines() if "\t" in line]
    rows = [row for row in lines if len(row) >= 2]
    if _to_blocks(result) != 1 or len(rows) != 1 or rows[0][1] != f"HEAD:{ref}":
        return "push_unavailable"  # no single row for exactly our ref at a single destination
    flag, summary = rows[0][0].strip(), (rows[0][2] if len(rows[0]) > 2 else "")
    if flag == "*" and getattr(result, "returncode", 1) == 0:
        return "created"
    if flag == "=":
        return "refused_branch_exists"  # already there, even at our own HEAD: never adopted
    if flag == "!" and "stale info" in summary:
        return "refused_branch_exists"
    if flag == "!" and "refname conflict" in summary:
        return "refused_ref_conflict"  # a directory/file ref conflict, e.g. a plain `agy-watch`
    if flag == "!" and "remote rejected" in summary:
        return "refused_push_remote_rejected"  # hook, ruleset, protection
    return "refused_push_failed"


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
        # Up to date only when an own PR for this version carries the CURRENT base label and
        # its head is still exactly the commit the watch pushed: the recorded oid, GitHub's
        # headRefOid and the branch's ls-remote oid must all agree. A maintainer push is
        # visible in BOTH live reads, so the recorded oid is what exposes it (r4 B3).
        # The pushed oid comes from the watch's OWN local record (r5), never the editable body.
        if any(_label_value(pr.get("body"), MARKER) == base
               and recorded_push(pr["headRefName"], asset.version, base) is not None
               and recorded_push(pr["headRefName"], asset.version, base) == pr.get("headRefOid")
               == remote_branch_head(runner, repo, pr["headRefName"])
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
        pushed = _run(runner, ["git", "-C", str(tree), "rev-parse", "HEAD"]).stdout.strip()
        if not ensure_push_state():
            out(json.dumps({"agy_watch": "refused_push_state_unavailable"}))
            return 2  # nothing pushed: a push the watch could not record must never happen
        outcome = publish_branch(runner, tree, branch)
        if outcome != "created":
            out(json.dumps({"agy_watch": outcome, "branch": branch}))
            return 2
        record_push(branch, pushed, asset.version, base)
        if recorded_push(branch, asset.version, base) != pushed:
            out(json.dumps({"agy_watch": "push_record_unverified", "branch": branch}))
            return 2  # the branch is an orphan (documented); no PR is opened for it
        supersedes = ", ".join(f"#{pr['number']}" for pr in prs)
        body = (f"Automated upstream-watch qualification of agy {asset.version} (agent-harness#1076).\n\n"
                f"Record produced from this branch's own tree; `verify_qualified_agy_image.py --route-core` passed.\n"
                f"Never merged by the watch.\n\n"
                + (f"Supersedes (maintainer to close): {supersedes}\n\n" if supersedes else "")
                + f"{VERSION_LABEL} {asset.version}\n{MARKER} {base}\n"
                f"{PUSHED_LABEL} {pushed} (display only; the watch reads its own local record)\n")
        # If this fails after the push, the fresh branch is left as an orphan: the watch never
        # deletes a ref (docs/ops/agy-upstream-watch.md).
        created = _run(runner, ["gh", "pr", "create", "--draft", "--repo", REPO_SLUG, "--base", "main",
                                "--head", branch, "--title", f"feat(agy): qualify agy {asset.version} (upstream watch)",
                                "--body", body], cwd=repo)
        # Read the PR back (read-only): it must sit on exactly the commit the watch pushed.
        url = (created.stdout or "").strip().splitlines()[-1] if (created.stdout or "").strip() else branch
        head = _run(runner, ["gh", "pr", "view", url, "--repo", REPO_SLUG, "--json", "headRefOid",
                             "-q", ".headRefOid"], cwd=repo, check=False)
        if (head.stdout or "").strip() != pushed:
            out(json.dumps({"agy_watch": "pr_head_mismatch", "branch": branch}))
            return 2
        out(json.dumps({"agy_watch": "draft_pr", "version": asset.version}))
        return 0
    finally:
        if not dry_run:
            _run(runner, ["git", "-C", str(repo), "worktree", "remove", "--force", str(tree)], check=False)
            shutil.rmtree(workdir, ignore_errors=True)
