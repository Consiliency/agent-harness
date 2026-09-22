"""Immutable Git-object review material for coordinator-owned train reviews.

The packet is review data, never publication or sandbox authority. Local evidence
and disposal scope remain explicitly attributed operator attestations.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


class PacketError(ValueError):
    """A named, pre-model material hold."""


def _fail(reason, detail=""):
    raise PacketError(f"{reason}: {detail}")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def escape_text(text):
    """Reversible presentation; source bytes are hashed before this operation."""
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\r":
            out.append("\\r")
        elif ch not in "\n\t" and unicodedata.category(ch) in {"Cc", "Cf", "Cs", "Zl", "Zp"}:
            out.append(f"\\u{ord(ch):04x}" if ord(ch) <= 0xffff else f"\\U{ord(ch):08x}")
        else:
            out.append(ch)
    return "".join(out)


def _text(data, label):
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError:
        _fail("invalid_utf8", label)
    if "\x00" in text:
        _fail("binary_source", label)
    escaped = escape_text(text)
    from .panel_invoker import _broker_untrusted_transport_text
    try:
        _broker_untrusted_transport_text(escaped.encode(), label)
    except ValueError as exc:
        _fail("forbidden_review_framing", f"{label}: {exc}")
    return {"text": escaped, "raw_bytes": len(data), "raw_sha256": _sha(data),
            "escaped_bytes": len(escaped.encode()), "escaped_sha256": _sha(escaped.encode())}


def _object(obj, required, optional=(), label="material"):
    if not isinstance(obj, dict) or set(obj) - set(required) - set(optional) or set(required) - set(obj):
        _fail("invalid_material_fields", label)
    return obj


def _string(value, label):
    if not isinstance(value, str) or not value.strip():
        _fail("invalid_material_value", label)
    return value


def _oid(value, length, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value):
        _fail("invalid_git_oid", label)
    return value


def _path(value):
    _string(value, "path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in {"", ".", ".."} for p in value.split("/")) or "\x00" in value:
        _fail("invalid_relative_path", value)
    return value


def _timestamp(value):
    _string(value, "observed_at")
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)", value):
        _fail("invalid_observed_at", value)
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
    except ValueError:
        _fail("invalid_observed_at", value)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_material_field", key)
        result[key] = value
    return result


def _parse(data, label):
    try:
        return json.loads(data, object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail("invalid_json", f"{label}: {exc}")


def _read_relative(root, name):
    """Open every relative component with O_NOFOLLOW using a directory fd."""
    _path(name)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = name.split("/")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            if not stat.S_ISREG(os.fstat(leaf).st_mode):
                _fail("evidence_not_regular", name)
            with os.fdopen(leaf, "rb", closefd=False) as fh:
                return fh.read()
        finally:
            os.close(leaf)
    except OSError as exc:
        _fail("evidence_unavailable", f"{name}: {exc.strerror}")
    finally:
        os.close(fd)


def _evidence(root, ref):
    _object(ref, {"path", "sha256"}, label="evidence")
    if not isinstance(ref["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", ref["sha256"]):
        _fail("invalid_evidence_digest", ref["path"])
    data = _read_relative(root, ref["path"])
    if _sha(data) != ref["sha256"]:
        _fail("evidence_digest_mismatch", ref["path"])
    return {**ref, "content": _text(data, ref["path"])}, data


def _env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_ATTR_NOSYSTEM="1",
               GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1", LC_ALL="C")
    return env


_DIFF = ["--no-color", "--no-ext-diff", "--no-textconv", "--full-index", "--no-renames",
         "--src-prefix=a/", "--dst-prefix=b/", "--ignore-submodules=none",
         "--diff-algorithm=myers", "--unified=3"]
_CONFIG = ["-c", "diff.relative=false", "-c", "diff.orderFile=/dev/null", "-c", "diff.noprefix=false",
           "-c", "diff.mnemonicPrefix=false", "-c", "core.quotepath=true", "-c", "core.attributesFile=/dev/null"]


class _GitReader:
    def __init__(self, workspace, scratch):
        workspace = Path(workspace)
        if not workspace.is_dir():
            _fail("missing_workspace", str(workspace))
        env = _env()
        def discover(*args):
            proc = subprocess.run(["git", "-C", str(workspace), "rev-parse", *args], env=env, capture_output=True)
            if proc.returncode:
                _fail("git_object_store_unavailable", str(workspace))
            return proc.stdout.decode().strip()
        common = Path(discover("--path-format=absolute", "--git-common-dir"))
        self.object_format = discover("--show-object-format")
        self.length = {"sha1": 40, "sha256": 64}.get(self.object_format)
        if self.length is None:
            _fail("unsupported_object_format", self.object_format)
        self.root = Path(scratch) / "reader.git"
        proc = subprocess.run(["git", "init", "--bare", "--template=", f"--object-format={self.object_format}",
                               str(self.root)], env=env, capture_output=True)
        if proc.returncode:
            _fail("git_reader_unavailable", proc.stderr.decode(errors="replace"))
        self.env = dict(env, GIT_OBJECT_DIRECTORY=str(common / "objects"))
        self.version = self.run("--version").decode().strip()

    def run(self, *args, input=None, optional=False):
        proc = subprocess.run(["git", "--git-dir=" + str(self.root), *_CONFIG, *args],
                              env=self.env, input=input, capture_output=True)
        if proc.returncode and not optional:
            _fail("missing_git_object", f"{' '.join(args)}; make objects available explicitly before retrying")
        return None if proc.returncode else proc.stdout

    def resolve(self, name, optional=False):
        raw = self.run("rev-parse", "--verify", name, optional=optional)
        return raw.decode().strip() if raw is not None else None

    def inventory(self, base, head):
        raw = self.run("diff-tree", "-r", "--raw", "-z", "--no-renames", "--no-abbrev", base, head)
        parts = raw.split(b"\0")
        rows = []
        for i in range(0, len(parts) - 1, 2):
            fields = parts[i].decode().split()
            if len(fields) != 5:
                _fail("invalid_git_inventory", repr(parts[i]))
            try:
                path = parts[i + 1].decode("utf-8")
            except UnicodeError:
                _fail("invalid_utf8_path", repr(parts[i + 1]))
            rows.append(dict(path=path, old_mode=fields[0][1:], new_mode=fields[1],
                             old_oid=fields[2], new_oid=fields[3], status=fields[4]))
        return sorted(rows, key=lambda row: row["path"])

    def patch(self, base, head, paths):
        return self.run("diff-tree", "--no-commit-id", "-r", "-p", *_DIFF, base, head,
                        "--", *(":(literal)" + p for p in paths))

    def sizes(self, oids):
        oids = sorted(set(oids))
        result = self.run("cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                          input=("\n".join(oids) + "\n").encode())
        sizes = {}
        for line in result.decode().splitlines():
            values = line.split()
            if len(values) != 3 or values[1] != "blob":
                _fail("missing_git_object", line)
            sizes[values[0]] = int(values[2])
        return sizes


def read_pr_metadata(workspace, pr_url):
    proc = subprocess.run(["gh", "pr", "view", pr_url, "--json",
        "url,state,headRefOid,baseRefName,baseRefOid,mergeCommit"], cwd=workspace, env=_env(), capture_output=True)
    if proc.returncode:
        _fail("pr_metadata_unavailable", pr_url)
    return _parse(proc.stdout, "PR metadata")


def _pr_identity(url):
    parsed = urlparse(url)
    match = re.fullmatch(r"/([^/]+)/([^/]+)/pull/([1-9][0-9]*)/?", parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or not match or parsed.query or parsed.fragment:
        _fail("invalid_pr_identity", url)
    return "/".join(match.groups()[:2])


def read_check_run(workspace, repo, check_id):
    proc = subprocess.run(["gh", "api", f"repos/{repo}/check-runs/{check_id}"], cwd=workspace,
                          env=_env(), capture_output=True)
    if proc.returncode:
        _fail("check_run_unavailable", str(check_id))
    return _parse(proc.stdout, "check run")


def _check_snapshot(record, data, head, repo):
    if not isinstance(data, dict) or type(data.get("id")) is not int or data.get("id") != record["check_run_id"] or data.get("head_sha") != head:
        _fail("check_run_identity_mismatch", record["id"])
    suite = data.get("check_suite") or {}
    if not isinstance(suite, dict):
        _fail("malformed_check_run", record["id"])
    for container in (suite, data):
        if "repository" in container and not isinstance(container["repository"], dict):
            _fail("malformed_check_run", record["id"])
    repository = suite.get("repository", data.get("repository", {}))
    if not isinstance(repository, dict) or not isinstance(repository.get("full_name", repo), str):
        _fail("malformed_check_run", record["id"])
    api_url = data.get("url", "")
    if repository.get("full_name", repo).lower() != repo.lower() or api_url != f"https://api.github.com/repos/{repo}/check-runs/{record['check_run_id']}":
        _fail("check_run_repository_mismatch", record["id"])
    app = data.get("app") or {}
    if not isinstance(app, dict) or type(app.get("id")) is not int or not isinstance(app.get("slug"), str) or not app["slug"] or type(suite.get("id")) is not int:
        _fail("malformed_check_run", record["id"])
    if record.get("expected_name", data.get("name")) != data.get("name") or record.get("expected_app_slug", app["slug"]) != app["slug"]:
        _fail("check_run_expectation_mismatch", record["id"])
    status, conclusion = data.get("status"), data.get("conclusion")
    if not isinstance(status, str) or status not in {"queued", "in_progress", "completed", "waiting", "pending", "requested"} or not isinstance(data.get("name"), str) or (conclusion is not None and not isinstance(conclusion, str)):
        _fail("malformed_check_run", record["id"])
    result = "unknown"
    if status == "completed":
        result = ({"success": "passed", "failure": "failed", "timed_out": "failed", "cancelled": "failed",
                   "action_required": "failed", "skipped": "skipped", "neutral": "skipped"}.get(conclusion, "unknown"))
    output = data.get("output")
    if not isinstance(output, dict):
        _fail("malformed_check_run", record["id"])
    if any(output.get(k) is not None and not isinstance(output[k], str) for k in ("title", "summary", "text")):
        _fail("malformed_check_run", record["id"])
    content = {k: _text((output.get(k) or "").encode(), f"check {record['id']} {k}") for k in ("title", "summary", "text")}
    return {**record, "head_sha": head, "repository": repo, "name": data["name"], "status": status,
            "conclusion": conclusion, "result": result, "app": {"id": app["id"], "slug": app["slug"]},
            "check_suite_id": suite["id"], "workflow_run_id": suite.get("workflow_run_id"),
            "name_pinned": "expected_name" in record, "app_pinned": "expected_app_slug" in record,
            "attribution": "reported by GitHub App " + app["slug"], "output": content}


def _material_snapshot(raw, root, head, length, workspace, repo, check_fn):
    _object(raw, {"head_sha", "acceptance", "verification"}, {"context", "generated_removals"}, "node")
    if _oid(raw["head_sha"], length, "material head") != head:
        _fail("stale_material_head", head)
    out = {"head_sha": head, "acceptance": [], "verification": [], "context": [], "generated_removals": [],
           "declaration_sha256": _sha(_json(raw).encode())}
    for kind in ("acceptance", "verification"):
        records = raw[kind]
        if not isinstance(records, list) or not records:
            _fail("missing_" + kind, head)
        ids = set()
        for record in records:
            if not isinstance(record, dict) or not _string(record.get("id"), "record id") or record["id"] in ids:
                _fail("duplicate_material_record", kind)
            ids.add(record["id"])
            if kind == "acceptance":
                _object(record, {"id", "text", "provenance"}, label=kind)
                _string(record["text"], "acceptance text")
                evidence, _ = _evidence(root, record["provenance"])
                out[kind].append({**record, "provenance": evidence})
            elif record.get("kind") == "attested_command":
                _object(record, {"id", "kind", "head_sha", "argv", "exit_code", "result", "attested_by", "observed_at", "evidence"})
                if record["head_sha"] != head:
                    _fail("unbound_verification", record["id"])
                argv = record["argv"]
                if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a for a in argv):
                    _fail("invalid_command", record["id"])
                result, code = record["result"], record["exit_code"]
                valid = isinstance(result, str) and ((result == "passed" and type(code) is int and code == 0) or
                         (result == "failed" and type(code) is int and code != 0) or
                         (result in {"skipped", "unknown"} and code is None))
                if not valid:
                    _fail("invalid_verification_result", record["id"])
                _string(record["attested_by"], "attested_by")
                _timestamp(record["observed_at"])
                evidence, _ = _evidence(root, record["evidence"])
                out[kind].append({**record, "evidence": evidence, "attribution": "operator-supplied attestation; not independently authenticated execution"})
            elif record.get("kind") == "github_check_run":
                _object(record, {"id", "kind", "check_run_id"}, {"expected_name", "expected_app_slug"})
                if type(record["check_run_id"]) is not int or record["check_run_id"] <= 0:
                    _fail("invalid_check_run_id", record["id"])
                for field in ("expected_name", "expected_app_slug"):
                    if field in record:
                        _string(record[field], field)
                out[kind].append(_check_snapshot(record, check_fn(workspace, repo, record["check_run_id"]), head, repo))
            else:
                _fail("invalid_verification_kind", record["id"])
    paths = raw.get("context", [])
    groups = raw.get("generated_removals", [])
    if not isinstance(paths, list) or not isinstance(groups, list):
        _fail("invalid_material_list", "context/generated_removals")
    for path in paths:
        _path(path)
        if path in out["context"]:
            _fail("duplicate_context", path)
        out["context"].append(path)
    for group in groups:
        _object(group, {"path", "base_tree_oid", "rationale", "attestation"})
        _path(group["path"])
        _oid(group["base_tree_oid"], length, group["path"])
        _string(group["rationale"], "rationale")
        evidence, data = _evidence(root, group["attestation"])
        attestation = _parse(data, group["path"])
        _object(attestation, {"attested_by", "observed_at", "base_tip_sha", "merge_base_sha", "head_sha", "path", "base_tree_oid", "disposal_scope"})
        _string(attestation["attested_by"], "attested_by")
        _string(attestation["disposal_scope"], "disposal_scope")
        _timestamp(attestation["observed_at"])
        out["generated_removals"].append({**group, "attestation": evidence, "assertion": attestation})
    return out


def _bounded_histogram(rows):
    items = sorted(rows.items())
    return {"first_20": [{"name": k, "count": v[0], "bytes": v[1]} for k, v in items[:20]],
            "remainder_rows": len(items[20:]), "remainder_count": sum(v[0] for _, v in items[20:]),
            "remainder_bytes": sum(v[1] for _, v in items[20:])}


def _certificates(reader, identity, inventory, groups):
    certified, certificates, sidecar = set(), [], []
    for group in groups:
        path = group["path"]
        if path == ".github" or path.startswith(".github/"):
            _fail("governance_removal_group", path)
        if any(path == old["path"] or path.startswith(old["path"] + "/") or old["path"].startswith(path + "/") for old in certificates):
            _fail("overlapping_removal_groups", path)
        tree = reader.resolve(identity["merge_base_sha"] + ":" + path)
        if tree != group["base_tree_oid"] or reader.run("cat-file", "-t", tree).strip() != b"tree":
            _fail("removal_tree_mismatch", path)
        if reader.resolve(identity["base_tip_sha"] + ":" + path, optional=True) != tree:
            _fail("removal_base_subtree_changed", path)
        if reader.resolve(identity["head_sha"] + ":" + path, optional=True) is not None:
            _fail("removal_subtree_survives", path)
        rows = [row for row in inventory if row["path"].startswith(path + "/")]
        if not rows or any(row["status"] != "D" for row in rows):
            _fail("removal_not_whole_deletion", path)
        if any(PurePosixPath(row["path"]).name == "CODEOWNERS" for row in rows):
            _fail("governance_removal_group", path)
        attestation = group["assertion"]
        expected = {k: identity[k] for k in ("base_tip_sha", "merge_base_sha", "head_sha")}
        expected.update(path=path, base_tree_oid=tree)
        if any(attestation.get(k) != v for k, v in expected.items()):
            _fail("disposal_attestation_mismatch", path)
        deleted_oids = {row["old_oid"] for row in rows}
        if any(row["status"] == "A" and not row["path"].startswith(path + "/") and row["new_oid"] in deleted_oids for row in inventory):
            _fail("new_copy_out", path)
        sizes = reader.sizes(deleted_oids)
        extensions, children = {}, {}
        for row in rows:
            size = sizes[row["old_oid"]]
            for table, key in ((extensions, PurePosixPath(row["path"]).suffix or "(none)"),
                               (children, row["path"][len(path) + 1:].split("/")[0])):
                count, total = table.get(key, (0, 0))
                table[key] = count + 1, total + size
        full_patch = reader.patch(identity["merge_base_sha"], identity["head_sha"], [path])
        certificate = {"path": path, "base_tree_oid": tree, "count": len(rows),
            "mode_totals": dict(sorted(Counter(row["old_mode"] for row in rows).items())),
            "total_deleted_bytes": sum(sizes[row["old_oid"]] for row in rows),
            "inventory_sha256": _sha(_json(rows).encode()), "full_diff_sha256": _sha(full_patch),
            "full_diff_bytes": len(full_patch), "extensions": _bounded_histogram(extensions),
            "first_level_children": _bounded_histogram(children), "rationale": group["rationale"],
            "attestation": group["attestation"], "assertion": attestation,
            "representation": "explicit disposal assertion; not proof of generatedness; deleted bodies and individual rows were not presented to the model; exact-blob new-copy-out check only"}
        certificates.append(certificate)
        sidecar.append({"node_id": identity["node_id"], "path": path, "inventory": rows})
        certified.update(row["path"] for row in rows)
    return certified, certificates, sidecar


def admission_binding(record):
    return {key: getattr(record, key) for key in ("node_id", "branch", "pr_url", "head_sha", "fab_run_id")}


def _live_identity(node, record, workspace, pr_fn, *, merged=False, proposed_head=None):
    if not Path(workspace).is_dir():
        _fail("missing_workspace", str(workspace))
    if record is None or not record.head_sha or not record.pr_url or not record.branch:
        _fail("unadmitted_node", node.node_id)
    live = pr_fn(workspace, record.pr_url)
    if not isinstance(live, dict) or live.get("url") != record.pr_url:
        _fail("pr_identity_mismatch", node.node_id)
    repo = _pr_identity(live["url"])
    from .train_runner import _DEFAULT_BASE
    if live.get("baseRefName") != _DEFAULT_BASE:
        _fail("retargeted_base", node.node_id)
    if live.get("headRefOid") != (proposed_head or record.head_sha):
        _fail("stale_head", node.node_id)
    if merged:
        if live.get("state") != "MERGED" or not record.upstream_merge_sha or (live.get("mergeCommit") or {}).get("oid") != record.upstream_merge_sha:
            _fail("historical_merge_outcome_mismatch", node.node_id)
    elif record.status not in {"pr_open", "approved", "blocked"} or live.get("state") != "OPEN":
        _fail("pr_not_open", node.node_id)
    return live, repo


def _node_snapshot(node, record, workspace, material, raw, material_root, pr_fn, check_fn, scratch, proposed_head=None):
    live, repo = _live_identity(node, record, workspace, pr_fn, proposed_head=proposed_head)
    reader = _GitReader(workspace, scratch)
    head = _oid(proposed_head or record.head_sha, reader.length, "review head")
    base = _oid(live.get("baseRefOid"), reader.length, "base tip")
    for oid in (base, head):
        reader.run("cat-file", "-e", oid + "^{commit}")
    merge_bases = reader.run("merge-base", "--all", base, head).decode().split()
    if len(merge_bases) != 1:
        _fail("ambiguous_merge_base", node.node_id)
    merge_base = merge_bases[0]
    identity = dict(node_id=node.node_id, pr_url=record.pr_url, repository=repo,
                    base_ref=live["baseRefName"], base_tip_sha=base, merge_base_sha=merge_base, head_sha=head,
                    base_tree_oid=reader.resolve(base + "^{tree}"),
                    comparison_tree_oid=reader.resolve(merge_base + "^{tree}"), head_tree_oid=reader.resolve(head + "^{tree}"),
                    object_format=reader.object_format,
                    admission={**admission_binding(record), "head_sha": head})
    if material is None:
        material = _material_snapshot(raw, material_root, head, reader.length, workspace, repo, check_fn)
    if material["head_sha"] != head:
        _fail("stale_material_head", node.node_id)
    inventory = reader.inventory(merge_base, head)
    certified, certificates, sidecar = _certificates(reader, identity, inventory, material["generated_removals"])
    visible = [row for row in inventory if row["path"] not in certified]
    inventory_headers = {b"diff --git " + _git_quote_path("a/" + row["path"]) + b" " +
                         _git_quote_path("b/" + row["path"]): row["path"] for row in inventory}
    patches = []
    for row in visible:
        for mode, oid in ((row["old_mode"], row["old_oid"]), (row["new_mode"], row["new_oid"])):
            if mode == "160000":
                _fail("submodule_change", row["path"])
            if mode != "000000":
                _text(reader.run("cat-file", "blob", oid), row["path"])
        patch = reader.patch(merge_base, head, [row["path"]])
        expected_header = b"diff --git " + _git_quote_path("a/" + row["path"]) + b" " + _git_quote_path("b/" + row["path"])
        selected = []
        for block in filter(None, re.split(rb"(?m)(?=^diff --git )", patch)):
            header = block.split(b"\n", 1)[0]
            if header == expected_header:
                selected.append(block)
            elif not inventory_headers.get(header, "").startswith(row["path"] + "/"):
                _fail("patch_inventory_mismatch", row["path"])
        # A literal pathspec also includes descendants at a directory/file swap.
        # Account for those through their own inventory rows, exactly once.
        if len(selected) != (2 if row["status"] == "T" else 1):
            _fail("patch_inventory_mismatch", row["path"])
        if row["status"] == "T":
            zero = "0" * reader.length
            pairs = [(row["old_oid"], zero), (zero, row["new_oid"])]
            for block, kind, mode in zip(selected, ("deleted", "new"), (row["old_mode"], row["new_mode"])):
                if f"{kind} file mode {mode}".encode() not in block.split(b"\n"):
                    _fail("patch_inventory_mode_mismatch", row["path"])
        else:
            pairs = [(row["old_oid"], row["new_oid"])] if row["old_oid"] != row["new_oid"] else []
        for block, (old_oid, new_oid) in zip(selected, pairs):
            expected_index = f"index {old_oid}..{new_oid}".encode()
            if not any(line == expected_index or line.startswith(expected_index + b" ") for line in block.split(b"\n")):
                _fail("patch_inventory_object_mismatch", row["path"])
        patches.extend(selected)
    context = []
    for path in material["context"]:
        oid = reader.resolve(head + ":" + path, optional=True)
        if oid is None:
            context.append({"path": path, "dissent": "requested head context unavailable; no complete-source claim"})
        elif reader.run("cat-file", "-t", oid).strip() != b"blob":
            _fail("context_not_blob", path)
        else:
            context.append({"path": path, "oid": oid, "content": _text(reader.run("cat-file", "blob", oid), path)})
    return {"identity": identity, "material": material, "inventory": visible,
            "inventory_sha256": _sha(_json(inventory).encode()), "changed_paths": len(inventory),
            "certificates": certificates, "context": context, "patch": _text(b"".join(patches), node.node_id + " patch"),
            "git_version": reader.version, "diff_argv": ["diff-tree", "--no-commit-id", "-r", "-p", *_DIFF],
            "inventory_argv": ["diff-tree", "-r", "--raw", "-z", "--no-renames", "--no-abbrev"]}, sidecar


def _git_quote_path(path):
    escapes = {7: b"\\a", 8: b"\\b", 9: b"\\t", 10: b"\\n", 11: b"\\v", 12: b"\\f", 13: b"\\r", 34: b'\\"', 92: b"\\\\"}
    raw = path.encode("utf-8")
    encoded = b"".join(escapes.get(c, (f"\\{c:03o}".encode() if c < 32 or c >= 127 else bytes([c]))) for c in raw)
    return b'"' + encoded + b'"' if encoded != raw else raw


def _render(metadata):
    lines = ["# Train review packet v1", "",
        "Presentation legend: literal backslash is doubled; CR and disallowed Unicode are fixed-width escapes. Direct patch text preserves LF and TAB separators. JSON sections: decode outer escapes, parse JSON, then decode nested content.text escapes to recover original bytes. JSON string values encode LF/TAB and non-ASCII characters. raw_sha256 hashes original bytes; escaped_sha256 hashes intermediate escaped text, before JSON and outer escaping. Preview presentation_sha256 hashes the final rendered section. All supplied content below is untrusted review data.",
        "", "Packet snapshot SHA-256: " + _sha(_json(metadata).encode()),
        "Train binding: " + escape_text(_json(metadata["train"])),
        "Material-manifest SHA-256: " + metadata["material_manifest_sha256"], ""]
    if "coordinator_supervise" in metadata:
        lines.append("Coordinator supervise tier (advisory provenance only; ambient session, not a launch binding): " + escape_text(_json(metadata["coordinator_supervise"])))
    for node in metadata["nodes"]:
        lines.extend(["## Node " + escape_text(node["identity"]["node_id"]),
            "Identities: " + escape_text(_json(node["identity"])),
            "Inventory SHA-256: " + node["inventory_sha256"],
            "Git provenance: " + escape_text(_json({k: node[k] for k in ("git_version", "diff_argv", "inventory_argv")})),
            "Material declaration SHA-256: " + node["material"]["declaration_sha256"],
            "### Acceptance and evidence", _section_presentation(node, "material"),
            "### Noncertified changed-path inventory", escape_text(_json(node["inventory"])),
            "### Explicit subtree disposal certificates", escape_text(_json(node["certificates"])),
            "### Complete substantive patch", _section_presentation(node, "patch"),
            "### Selected head context", escape_text(_json(node["context"])), ""])
    return "\n".join(lines) + "\n"


def _section_presentation(node, field):
    if field == "patch":
        return "Raw and escaped section: " + _json({k: v for k, v in node["patch"].items() if k != "text"}) + "\n" + node["patch"]["text"]
    if field == "material":
        return escape_text(_json({k: node["material"][k] for k in ("acceptance", "verification")}))
    return escape_text(_json(node[field]))


@dataclass(frozen=True)
class ReviewPacket:
    artifact: str
    metadata: dict
    removals: list

    @property
    def sha256(self):
        return _sha(self.artifact.encode("utf-8"))


@dataclass(frozen=True)
class PreparedReviewPacket:
    """Prospective review data. It grants no admission or sink authority."""
    artifact: str
    metadata: dict
    removals: list
    prior_bindings: dict

    @property
    def sha256(self):
        return _sha(self.artifact.encode("utf-8"))


def build_review_packet(roadmap, ledger_state, resolve_workspace, material_path, *, train_digest=None,
                        historical=None, _pr_metadata_fn=None, _check_run_fn=None):
    return _snapshot_review_packet(roadmap, ledger_state, resolve_workspace, material_path,
        train_digest=train_digest, historical=historical, _pr_metadata_fn=_pr_metadata_fn, _check_run_fn=_check_run_fn)


def prepare_review_packet(roadmap, ledger_state, resolve_workspace, material_path, *, proposed_heads, **kwargs):
    if set(proposed_heads) - {n.node_id for n in roadmap.topo_order()}:
        _fail("unknown_proposed_node")
    result = _snapshot_review_packet(roadmap, ledger_state, resolve_workspace, material_path,
                                    proposed_heads=proposed_heads, **kwargs)
    return PreparedReviewPacket(result.artifact, result.metadata, result.removals,
        {n.node_id: admission_binding(ledger_state[n.node_id]) for n in roadmap.topo_order()})


def finalize_review_packet(prepared, roadmap, ledger_state, resolve_workspace, **kwargs):
    if type(prepared) is not PreparedReviewPacket:
        _fail("invalid_prepared_packet")
    recheck_packet_identities(prepared, roadmap, ledger_state, resolve_workspace, **kwargs)
    return ReviewPacket(prepared.artifact, prepared.metadata, prepared.removals)


def _snapshot_review_packet(roadmap, ledger_state, resolve_workspace, material_path, *, train_digest=None,
                           historical=None, _pr_metadata_fn=None, _check_run_fn=None, proposed_heads=None):
    pr_fn = _pr_metadata_fn or read_pr_metadata
    check_fn = _check_run_fn or read_check_run
    order = roadmap.topo_order()
    train = {"title": roadmap.title, "node_order": [n.node_id for n in order],
             "nodes": [asdict(n) for n in roadmap.nodes], "edges": [asdict(e) for e in roadmap.edges]}
    train["content_sha256"] = train_digest or _sha(_json(train).encode())
    raw = None
    root = None
    if material_path is not None:
        path = Path(material_path).absolute()
        root = path.parent
        data = _read_relative(root, path.name)
        raw = _parse(data, "material manifest")
        _object(raw, {"schema_version", "nodes"})
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 1 or not isinstance(raw["nodes"], dict) or set(raw["nodes"]) != {n.node_id for n in order}:
            _fail("material_node_set_mismatch")
        material_digest = _sha(data)
    elif historical is not None:
        material_digest = historical.metadata["material_manifest_sha256"]
    else:
        _fail("review_material_required")
    previous = {n["identity"]["node_id"]: n for n in historical.metadata["nodes"]} if historical else {}
    if historical and historical.metadata["train"] != train and raw is None:
        _fail("review_material_required", "train scope changed")
    nodes, removals = [], []
    with tempfile.TemporaryDirectory(prefix="train-packet-") as scratch:
        for index, node in enumerate(order):
            record = ledger_state.get(node.node_id)
            workspace = Path(resolve_workspace(node))
            old = previous.get(node.node_id)
            if record is not None and record.status == "merged":
                if old is None:
                    _fail("historical_packet_unavailable", node.node_id)
                _live_identity(node, record, workspace, pr_fn, merged=True)
                if old["identity"].get("admission") != admission_binding(record):
                    _fail("historical_packet_identity_mismatch", node.node_id)
                if raw and _sha(_json(raw["nodes"][node.node_id]).encode()) != old["material"]["declaration_sha256"]:
                    _fail("historical_material_changed", node.node_id)
                nodes.append(old)
                removals.extend(r for r in historical.removals if r["node_id"] == node.node_id)
                continue
            if record is None:
                _fail("unadmitted_node", node.node_id)
            work = Path(scratch) / str(index)
            work.mkdir()
            node_data, sidecar = _node_snapshot(node, record, workspace,
                old["material"] if raw is None and old else None,
                raw["nodes"][node.node_id] if raw else None, root, pr_fn, check_fn, work,
                (proposed_heads or {}).get(node.node_id))
            nodes.append(node_data)
            removals.extend(sidecar)
    from .profiles import supervise_selection
    metadata = {"schema_version": 1, "train": train, "material_manifest_sha256": material_digest, "nodes": nodes,
                "coordinator_supervise": asdict(supervise_selection("claude")),
                "removals_sha256": _sha(_json(removals).encode())}
    artifact = _render(metadata)
    if len(artifact.encode()) > 1024 * 1024:
        _fail("packet_parser_bound", "packet exceeds 1 MiB")
    preflight_packet(artifact)
    return ReviewPacket(artifact, metadata, removals)


def preflight_packet(artifact, *, instructions=None, board=None):
    """Pure renderer preflight; the bounded path is not staged-tree authority."""
    from . import panel_invoker as pi
    instructions = instructions if instructions is not None else pi._resolve_brief("review", None)
    generated = pi._broker_review_inputs_generated(artifact, instructions)
    instruction_frames = pi._digest_bound_broker_delimiters("AUTHORITATIVE-INSTRUCTIONS", instructions.encode(), validated_generated_payload=generated)
    artifact_frames = pi._digest_bound_broker_delimiters("UNTRUSTED-REVIEW-BUNDLE", artifact.encode(), validated_generated_payload=generated)
    if board is not None:
        for seat in board.seats:
            if seat.auth != pi.AUTH_SUBSCRIPTION or seat.backing != pi.BACKING_HOMEBREW or seat.host_leg:
                _fail("unsupported_review_route", str(seat.harness))
            pi.harden_subscription_model((seat.harness or "").lower(), seat.model, seat.effort)
    variants = {}
    for name, preamble in (("sealed_no_tools", pi._BROKER_REVIEW_SEALED_PREAMBLE),
                           ("sandbox_path_bound", pi._broker_review_sandbox_preamble(Path("/" + "p" * 4095)))):
        prompt = pi._assemble_broker_inline_prompt(artifact, instructions, preamble.rstrip("\n"), instruction_frames, artifact_frames)
        variants[name] = len(prompt.encode())
    return {"rendered_prompt_bytes": max(variants.values()), "route_prompt_bytes": variants,
            "sandbox_path_bytes_bound": 4096, "sandbox_path_validated": False}


def recheck_packet_identities(packet, roadmap, ledger_state, resolve_workspace, *, node_ids=None, _pr_metadata_fn=None, prior_bindings=None):
    pr_fn = _pr_metadata_fn or read_pr_metadata
    for stored in packet.metadata["nodes"]:
        ident = stored["identity"]
        nid = ident["node_id"]
        if node_ids is not None and nid not in node_ids:
            continue
        record = ledger_state.get(nid)
        expected = prior_bindings[nid] if prior_bindings is not None else ident.get("admission")
        if record is None or expected != admission_binding(record):
            _fail("admission_identity_drift", nid)
        if record is not None and record.status == "merged":
            _live_identity(roadmap.node_by_id(nid), record, resolve_workspace(roadmap.node_by_id(nid)), pr_fn, merged=True)
            continue
        node = roadmap.node_by_id(nid)
        live, _ = _live_identity(node, record, resolve_workspace(node), pr_fn,
                                 proposed_head=ident["head_sha"] if prior_bindings is not None else None)
        if live.get("baseRefOid") != ident["base_tip_sha"] or live.get("headRefOid") != ident["head_sha"]:
            _fail("observed_identity_drift", nid)


def _files(packet):
    result = {"packet.md": packet.artifact.encode(), "packet.json": (_json(packet.metadata) + "\n").encode()}
    if packet.removals:
        result["removals.json"] = (_json(packet.removals) + "\n").encode()
    return result


def store_review_packet(packet, root):
    if type(packet) is not ReviewPacket:
        _fail("unfinalized_packet")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    dest = root / packet.sha256
    expected = _files(packet)
    if dest.exists():
        if not dest.is_dir() or dest.is_symlink() or set(p.name for p in dest.iterdir()) != set(expected):
            _fail("stored_packet_corrupt", packet.sha256)
        if any(_read_relative(dest, name) != data for name, data in expected.items()):
            _fail("stored_packet_corrupt", packet.sha256)
    else:
        scratch = Path(tempfile.mkdtemp(prefix=".packet-", dir=root))
        try:
            for name, data in expected.items():
                (scratch / name).write_bytes(data)
            scratch.rename(dest)
        finally:
            if scratch.exists():
                shutil.rmtree(scratch)
    if _sha(_read_relative(dest, "packet.md")) != packet.sha256:
        _fail("stored_packet_digest_mismatch", packet.sha256)
    return dest


def load_review_packet(root, digest):
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        _fail("stored_packet_digest_invalid")
    directory = Path(root) / digest
    try:
        data = _read_relative(directory, "packet.md")
        metadata = _parse(_read_relative(directory, "packet.json"), "stored packet")
        if _sha(data) != digest or _render(metadata).encode() != data or metadata["schema_version"] != 1:
            _fail("stored_packet_corrupt", digest)
        removals = _parse(_read_relative(directory, "removals.json"), "removals") if (directory / "removals.json").exists() else []
        if _sha(_json(removals).encode()) != metadata["removals_sha256"]:
            _fail("stored_packet_corrupt", digest)
        artifact = data.decode("utf-8")
        preflight_packet(artifact)
        return ReviewPacket(artifact, metadata, removals)
    except (OSError, KeyError, TypeError, UnicodeError) as exc:
        _fail("stored_packet_unavailable", f"{digest}: {exc}")


def _output_directory(output, forbidden):
    output = Path(output).absolute()
    if ".phase-loop" in output.parts:
        _fail("preview_output_forbidden", str(output))
    for part in (output, *output.parents):
        if part.is_symlink():
            _fail("preview_output_symlink", str(part))
    output = Path(os.path.normpath(output))
    for root in forbidden:
        root = Path(root).resolve()
        if output == root or root in output.parents:
            _fail("preview_output_forbidden", str(output))
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        _fail("preview_output_nonempty", str(output))
    output.mkdir(parents=True, exist_ok=True)
    return output


def preview_review_packet(roadmap, ledger_path, resolve_workspace, material_path, output, *, train_digest=None,
                          _pr_metadata_fn=None, _check_run_fn=None):
    receipt = {"schema_version": 1, "ready": False, "errors": [], "model_calls": 0,
               "read_only_checks": ["no broker", "no lease", "no admission", "no recovery", "no ledger writes"],
               "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "runtime_source": str(Path(__file__).resolve()), "runtime_source_sha256": _sha(Path(__file__).read_bytes())}
    receipt["runtime_sources_sha256"] = {name: _sha(Path(__file__).with_name(name).read_bytes()) for name in
        ("train_review_packet.py", "train_runner.py", "train_ledger.py", "cli.py", "panel_invoker.py", "governed_review.py")}
    directory = None
    try:
        directory = _output_directory(output, [Path(ledger_path).parent, *(resolve_workspace(n) for n in roadmap.nodes)])
        from .train_ledger import read_ledger
        ledger_bytes = Path(ledger_path).read_bytes()
        if not ledger_bytes.endswith(b"\n"):
            _fail("torn_ledger", "preview never repairs admission state")
        for line in ledger_bytes.splitlines():
            if line.strip():
                _parse(line, "ledger")
        state = read_ledger(Path(ledger_path))
        approval = state.get("_train_review_")
        historical = load_review_packet(Path(ledger_path).parent / "review-packets", approval.review_packet_sha256) if approval and approval.review_packet_sha256 else None
        packet = build_review_packet(roadmap, state, resolve_workspace, material_path, train_digest=train_digest,
            historical=historical, _pr_metadata_fn=_pr_metadata_fn, _check_run_fn=_check_run_fn)
        if Path(ledger_path).read_bytes() != ledger_bytes:
            _fail("admission_changed_during_preview")
        for name, data in _files(packet).items():
            temp = directory / ("." + name + ".tmp")
            temp.write_bytes(data)
            temp.rename(directory / name)
        if _sha((directory / "packet.md").read_bytes()) != packet.sha256:
            _fail("packet_readback_mismatch")
        receipt.update(preflight_packet(packet.artifact), ready=True, packet_sha256=packet.sha256,
            packet_bytes=len(packet.artifact.encode()), material_manifest_sha256=packet.metadata["material_manifest_sha256"],
            changed_paths=sum(n["changed_paths"] for n in packet.metadata["nodes"]),
            substantive_paths=sum(len(n["inventory"]) for n in packet.metadata["nodes"]),
            exclusions=[c for n in packet.metadata["nodes"] for c in n["certificates"]],
            sections=[{"node_id": n["identity"]["node_id"], "section": field,
                "snapshot_bytes": len(_json(n[field]).encode()), "snapshot_sha256": _sha(_json(n[field]).encode()),
                "presentation_bytes": len(_section_presentation(n, field).encode()),
                "presentation_sha256": _sha(_section_presentation(n, field).encode())}
                for n in packet.metadata["nodes"] for field in ("identity", "material", "inventory", "certificates", "patch", "context")],
            identities=[n["identity"] for n in packet.metadata["nodes"]])
    except (OSError, ValueError, TypeError) as exc:
        receipt["errors"].append(str(exc))
    if directory is not None:
        temp = directory / ".receipt.json.tmp"
        temp.write_text(_json(receipt) + "\n", encoding="utf-8")
        temp.rename(directory / "receipt.json")
    return receipt
