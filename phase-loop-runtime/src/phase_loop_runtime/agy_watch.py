"""Upstream agy release watch (agent-harness#1076), run from a timer on a subscribed host.

It is deliberately OUTSIDE ``agy_qualification.ROUTE_CORE``: a watch-only fix never forces
a requalification. For the newest stable release not yet pinned on ``main`` it:

1. is idempotent per version: an open PR for that version whose recorded base route-core
   digest matches current ``main`` is a no-op; if ``main``'s route-core moved, it
   regenerates and force-updates only its own branch;
2. builds a VerifiedImage from the provenance-checked archive member stream (no install);
3. in a fresh checkout of current ``main`` with the constants and catalog edited, measures
   help with THAT tree's owned profile and runs the manual qualification (the shim) from
   that tree, handing the image over as a sealed fd (``--image-fd``, the worker's seal
   check applies). The tree's own release constant satisfies the worker gate, so the
   record matches the tree -- what ``--route-core`` requires -- and never depends on the
   recency window;
4. opens a DRAFT PR. It never merges.

Only the release route (Linux x64 glibc; ``qualified_provider_images.v2`` has only that
route) is proposed; any other platform reports and opens nothing.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
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


def summarize(tree: Path, series: Path, asset, image_sha256: str, help_sha256: str) -> dict:
    """The redacted record, in the shape of the newest committed record (see the release
    process's regeneration rule): each operation row is its receipt restricted to the
    template row's keys."""
    catalog = json.loads((tree / CATALOG).read_text())
    members = catalog["routes"]["gemini_heartbeat_linux_x64"]["images"]
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
         python=sys.executable, workdir=None, out=print) -> int:
    host = host or agy_provenance.detect_platform()
    if host.name != RELEASE_ROUTE_PLATFORM:
        out(json.dumps({"agy_watch": "platform_not_proposed", "platform": host.name}))
        return 0
    repo = Path(repo or ".").resolve()
    transport = transport or agy_provenance._Transport()
    releases = agy_provenance.stable_releases(transport, window=1)
    if not releases:
        out(json.dumps({"agy_watch": "no_stable_release"}))
        return 0
    asset = agy_provenance.release_asset(releases[0], host)
    _run(runner, ["git", "-C", str(repo), "fetch", "origin", "main"])
    workdir = Path(workdir or tempfile.mkdtemp(prefix="agy-watch-"))
    tree = workdir / "tree"
    branch = BRANCH_PREFIX + asset.version
    _run(runner, ["git", "-C", str(repo), "worktree", "add", "--force", "-B", branch, str(tree), "origin/main"])
    try:
        if asset.version in pinned_versions(tree):
            out(json.dumps({"agy_watch": "already_pinned", "version": asset.version}))
            return 0
        base = route_core_digest(tree)
        existing = _run(runner, ["gh", "pr", "list", "--repo", "Consiliency/agent-harness", "--head", branch,
                                 "--state", "open", "--json", "number,body"], cwd=repo)
        prs = json.loads(existing.stdout or "[]")
        if any(f"{MARKER} {base}" in (pr.get("body") or "") for pr in prs):
            out(json.dumps({"agy_watch": "up_to_date", "version": asset.version}))
            return 0
        member_sha256, member = agy_provenance.fetch_member(transport, asset, keep_bytes=True)
        image = gh.VerifiedImage.from_bytes(member)
        del member
        try:
            env = dict(os.environ)
            edit_constants(tree, image.sha256, "0" * 64, asset.version)
            help_path = workdir / "agy-help.txt"
            fd = image.reopen()
            try:
                _tree_python(tree, python, ["--measure-help", "--output", str(help_path)], image_fd=fd,
                             runner=runner, env=env)
            finally:
                os.close(fd)
            help_sha256 = sha256(help_path.read_bytes()).hexdigest()
            edit_constants(tree, image.sha256, help_sha256, asset.version)
            series = workdir / "series"
            series.mkdir()
            for operation in OPERATIONS:
                fd = image.reopen()
                try:
                    _tree_python(tree, python, ["--operation", operation, "--output", str(series / operation),
                                                "--help-evidence", str(help_path)], image_fd=fd, runner=runner, env=env)
                finally:
                    os.close(fd)
            _run(runner, [python, str(tree / "phase-loop-runtime/scripts/qualify_gemini_heartbeat.py"),
                          "--validate", str(series)], cwd=tree / "phase-loop-runtime",
                 env={**env, "PYTHONPATH": str(tree / "phase-loop-runtime/src")})
            record = summarize(tree, series, asset, image.sha256, help_sha256)
            (tree / "plans/evidence" / f"agy-{asset.version}-linux-x64-qualification.json").write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n")
            _run(runner, [python, str(tree / "phase-loop-runtime/scripts/verify_qualified_agy_image.py"),
                          "--route-core"], cwd=tree)
        finally:
            image.close()
        if dry_run:
            out(json.dumps({"agy_watch": "dry_run_verified", "version": asset.version, "tree": str(tree),
                            "image_sha256": member_sha256}))
            return 0
        _run(runner, ["git", "-C", str(tree), "add", "-A"])
        _run(runner, ["git", "-C", str(tree), "-c", "commit.gpgsign=false", "commit", "-m",
                      f"feat(agy): qualify the {asset.version} entry image (agy watch, agent-harness#1076)"])
        _run(runner, ["git", "-C", str(tree), "push", "--force-with-lease", "origin", f"{branch}:{branch}"])
        body = (f"Automated upstream-watch qualification of agy {asset.version} (agent-harness#1076).\n\n"
                f"Record produced from this branch's own tree; `verify_qualified_agy_image.py --route-core` passed.\n"
                f"Never merged by the watch.\n\n{MARKER} {base}\n")
        if prs:
            _run(runner, ["gh", "pr", "edit", str(prs[0]["number"]), "--repo", "Consiliency/agent-harness",
                          "--body", body], cwd=repo)
        else:
            _run(runner, ["gh", "pr", "create", "--draft", "--repo", "Consiliency/agent-harness", "--base", "main",
                          "--head", branch, "--title", f"feat(agy): qualify agy {asset.version} (upstream watch)",
                          "--body", body], cwd=repo)
        out(json.dumps({"agy_watch": "draft_pr", "version": asset.version}))
        return 0
    finally:
        if not dry_run:
            _run(runner, ["git", "-C", str(repo), "worktree", "remove", "--force", str(tree)], check=False)
            shutil.rmtree(workdir, ignore_errors=True)
