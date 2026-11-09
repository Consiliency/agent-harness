"""Convert v1 agy qualification records to record v2 through their record commit (AGYROLL §3.5).

``--check`` proves, for every catalog member, that its v1 evidence still applies to this tree
without a live run:

1. the **record commit** is the newest commit in ``git log -- plans/evidence/<record>`` whose
   package sources equal the record's ``source_sha256`` exactly;
2. ``agy_profile_digest()`` at the record commit equals ``agy_profile_digest()`` at head
   (a v1 record commit has no ``seat_qci()``; the two are equal at ``agy_validator_v1``);
3. the validator's source-hash closure (AGYROLL §2.1: the AST call-graph closure of
   ``validate_records``, ``validate_directory`` and ``_classify_failure`` within
   ``phase_loop_runtime``) is equal at both commits.

Any refusal stops RECBIND (SL-1.2): that member needs one owner-approved live
requalification. Nothing converts by assumption. A member whose record is already v2 passes
``--check`` when its ``qci`` equals the tree's ``seat_qci()``.

``--write`` converts each checked v1 record in place: it drops ``source_sha256`` and adds
``qci``, ``qualified_under`` (the record commit's ``__version__``, informational),
``upstream`` and an empty ``signatures`` list.
"""
from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import io

REPO = Path(__file__).resolve().parents[2]
PACKAGE_REL = "phase-loop-runtime/src/phase_loop_runtime"
SHIM_REL = "phase-loop-runtime/scripts/qualify_gemini_heartbeat.py"
EVIDENCE_REL = "plans/evidence"
OLD_CATALOG_REL = "plans/evidence/qualified-provider-images.json"
DATA_CATALOG_REL = PACKAGE_REL + "/data/agy_catalog.json"
V1 = "agy_redacted_qualification_summary.v1"
V2 = "agy_redacted_qualification_summary.v2"
# Every function that turns provider output or image facts into a verdict (AGYROLL §2.1;
# agent-harness#1937 review B1): the validator entry points (which hold the recorded image
# and isolation predicates), the helper image-identity policy, and the stream parser that
# decides a provider stream's outcome. The driver's launch machinery (``run_operation``) is
# proven by the strict conformance suite instead; hashing it would pull in every launch module.
ENTRY_POINTS = (
    ("agy_qualification", "validate_records"),
    ("agy_qualification", "validate_directory"),
    ("agy_qualification", "_classify_failure"),
    ("agy_qualification", "HelperObserver"),
    ("panel_invoker", "_broker_gemini_stream_result"),
)


class ConversionRefused(ValueError):
    """A member's v1 evidence cannot be carried forward without a live requalification."""


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


# ---------------------------------------------------------------- record commit

def tree_sources(repo: Path, commit: str) -> dict[str, str]:
    """The ``source_sha256`` table v1 records pin, read from ``commit``'s tree."""
    listing = git(repo, "ls-tree", "-r", commit, "--", PACKAGE_REL, SHIM_REL).decode().splitlines()
    table = {}
    for line in listing:
        meta, path = line.split("\t", 1)
        if not path.endswith(".py"):
            continue
        key = path.removeprefix(PACKAGE_REL + "/") if path.startswith(PACKAGE_REL + "/") else Path(path).name
        table[key] = sha256(git(repo, "cat-file", "blob", meta.split()[2])).hexdigest()
    return table


def record_commit(repo: Path, record_name: str, pins: dict[str, str]) -> str:
    """The newest commit touching the record whose package sources match its pins exactly."""
    if not isinstance(pins, dict) or not pins:
        raise ConversionRefused(f"{record_name}: the record pins no sources")
    for commit in git(repo, "log", "--format=%H", "--", f"{EVIDENCE_REL}/{record_name}").decode().split():
        if tree_sources(repo, commit) == pins:
            return commit
    raise ConversionRefused(f"{record_name}: no record commit (no commit's sources match source_sha256)")


def export_package(repo: Path, commit: str, dest: Path) -> Path:
    """``commit``'s ``phase-loop-runtime/src`` exported under ``dest``; returns the src root."""
    archive = git(repo, "archive", "--format=tar", commit, "phase-loop-runtime/src")
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(dest, filter="data")
    return dest / "phase-loop-runtime" / "src"


_DIGEST_PROGRAM = ("import sys; sys.path.insert(0, sys.argv[1]); "
                   "from phase_loop_runtime import agy_qualification as q; "
                   "print(q.agy_profile_digest()); "
                   "print(q.seat_qci() if hasattr(q, 'seat_qci') else q.agy_profile_digest())")


def tree_digests(src_root: Path, python: str = sys.executable) -> tuple[str, str]:
    """(``agy_profile_digest()``, ``seat_qci()``) of the package under ``src_root``, computed by
    that tree's own code in an isolated interpreter."""
    done = subprocess.run([python, "-I", "-c", _DIGEST_PROGRAM, str(src_root)],
                          capture_output=True, text=True, timeout=300)
    lines = done.stdout.split()
    if done.returncode != 0 or len(lines) != 2 or not all(re.fullmatch(r"[0-9a-f]{64}", x) for x in lines):
        raise ConversionRefused(f"cannot compute the profile digest under {src_root}: {done.stderr[-300:]}")
    return lines[0], lines[1]


# ------------------------------------------------------------- validator closure

class _Module:
    def __init__(self, name: str, path: Path):
        self.name, self.source = name, path.read_text()
        # The package a relative import resolves against (agent-harness#1937 review B2): the
        # module's own package, or the package itself for an ``__init__``.
        self.package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        self.defs: dict[str, ast.AST] = {}
        self.aliases: dict[str, str] = {}             # name -> module
        self.imported: dict[str, tuple[str, str]] = {}  # name -> (module, name)
        tree = ast.parse(self.source)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.defs[node.name] = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        self.defs[target.id] = node
            elif isinstance(node, ast.ImportFrom):
                self._bind(node, self.aliases, self.imported)

    def _base(self, node: ast.ImportFrom) -> str | None:
        """The dotted module (relative to ``phase_loop_runtime``) an import names, or ``None``
        for an import from outside the package."""
        if node.level == 0:
            module = node.module or ""
            if module != "phase_loop_runtime" and not module.startswith("phase_loop_runtime."):
                return None
            return module.removeprefix("phase_loop_runtime").lstrip(".")
        parts = self.package.split(".") if self.package else []
        if node.level - 1 > len(parts):
            return None
        parts = parts[:len(parts) - (node.level - 1)]
        return ".".join([*parts, *([node.module] if node.module else [])])

    def _bind(self, node: ast.ImportFrom, aliases, imported) -> None:
        base = self._base(node)
        if base is None:
            return
        for alias in node.names:
            bound = alias.asname or alias.name
            if node.module:
                imported[bound] = (base, alias.name)
            else:
                aliases[bound] = ".".join(part for part in (base, alias.name) if part)

    def module_returning(self, name: str) -> str | None:
        """``def _panel(): from . import panel_invoker; return panel_invoker`` -> its module."""
        node = self.defs.get(name)
        if not isinstance(node, ast.FunctionDef):
            return None
        local: dict[str, str] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.ImportFrom):
                self._bind(stmt, local, {})
            if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Name):
                return local.get(stmt.value.id) or self.aliases.get(stmt.value.id)
        return None


def validator_closure(package_dir: Path) -> dict[str, str]:
    """``{"module:name": sha256(source)}`` over the validator's transitive closure."""
    cache: dict[str, _Module | None] = {}

    def module(name: str) -> _Module | None:
        if name not in cache:
            base = package_dir.joinpath(*name.split(".")) if name else package_dir
            path = base.with_suffix(".py") if name else base / "__init__.py"
            if not path.is_file():
                path = base / "__init__.py"
            cache[name] = _Module(name, path) if path.is_file() else None
        return cache[name]

    table: dict[str, str] = {}
    pending = list(ENTRY_POINTS)
    while pending:
        mod_name, name = pending.pop()
        key = f"{mod_name}:{name}"
        mod = module(mod_name)
        if key in table or mod is None:
            continue
        if name not in mod.defs:
            if name in mod.imported:
                pending.append(mod.imported[name])
            continue
        node = mod.defs[name]
        table[key] = sha256(ast.get_source_segment(mod.source, node).encode()).hexdigest()
        local_imports: dict[str, tuple[str, str]] = {}
        local_aliases: dict[str, str] = {}
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom):
                mod._bind(sub, local_aliases, local_imports)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                if sub.id in local_imports:
                    pending.append(local_imports[sub.id])
                elif sub.id in mod.defs:
                    pending.append((mod_name, sub.id))
                elif sub.id in mod.imported:
                    pending.append(mod.imported[sub.id])
            elif isinstance(sub, ast.Attribute):
                base = sub.value
                target = None
                if isinstance(base, ast.Name):
                    target = local_aliases.get(base.id) or mod.aliases.get(base.id)
                elif isinstance(base, ast.Call) and isinstance(base.func, ast.Name):
                    target = mod.module_returning(base.func.id)
                if target is not None:
                    pending.append((target, sub.attr))
    return dict(sorted(table.items()))


def closure_digest(table: dict[str, str]) -> str:
    return sha256(json.dumps(table, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---------------------------------------------------------------------- members

def catalog_members(repo: Path) -> list[dict]:
    """Every catalog member (data catalog v3 when present, else the v1 evidence catalog)."""
    data = repo / DATA_CATALOG_REL
    if data.is_file():
        catalog = json.loads(data.read_text())
        members = catalog["routes"]["linux-x64"]
    else:
        catalog = json.loads((repo / OLD_CATALOG_REL).read_text())
        members = catalog["routes"]["gemini_heartbeat_linux_x64"]["images"]
    if not members:
        raise ConversionRefused("the catalog has no members")
    return members


def _record_path(repo: Path, member: dict) -> Path:
    name = member["record"]
    if Path(name).name != name or not re.fullmatch(r"agy-\d+\.\d+\.\d+-linux-x64-qualification\.json", name):
        raise ConversionRefused(f"unsafe record name {name!r}")
    return repo / EVIDENCE_REL / name


def version_at(repo: Path, commit: str) -> str:
    text = git(repo, "show", f"{commit}:{PACKAGE_REL}/__init__.py").decode()
    match = re.search(r'^__version__ = "([^"]+)"', text, re.M)
    if match is None:
        raise ConversionRefused(f"{commit}: no __version__ literal")
    return match.group(1)


def check(repo: Path = REPO, *, python: str = sys.executable, digests=tree_digests) -> list[dict]:
    """The stop gate: one row per member, or ``ConversionRefused``."""
    head_src = repo / "phase-loop-runtime" / "src"
    head_profile, head_qci = digests(head_src, python)
    head_closure = validator_closure(head_src / "phase_loop_runtime")
    rows = []
    for member in catalog_members(repo):
        path = _record_path(repo, member)
        record = json.loads(path.read_text())
        if record.get("schema") == V2:
            if record.get("qci") != head_qci:
                raise ConversionRefused(f"{path.name}: qci differs from this tree's seat_qci()")
            rows.append({"member": member["release_version"], "record": path.name, "schema": V2, "qci": head_qci})
            continue
        if record.get("schema") != V1:
            raise ConversionRefused(f"{path.name}: unknown record schema")
        commit = record_commit(repo, path.name, record.get("source_sha256"))
        with tempfile.TemporaryDirectory(prefix="agy-record-commit-") as scratch:
            src = export_package(repo, commit, Path(scratch))
            profile, _ = digests(src, python)
            closure = validator_closure(src / "phase_loop_runtime")
        if profile != head_profile:
            raise ConversionRefused(f"{path.name}: agy_profile_digest() at record commit {commit} differs from head")
        if closure != head_closure:
            changed = sorted(key for key in set(closure) | set(head_closure) if closure.get(key) != head_closure.get(key))
            raise ConversionRefused(f"{path.name}: validator closure at record commit {commit} differs from head: "
                                    + ", ".join(changed))
        rows.append({"member": member["release_version"], "record": path.name, "schema": V1,
                     "record_commit": commit, "agy_profile_digest": profile,
                     "validator_closure_sha256": closure_digest(closure), "qci": head_qci,
                     "qualified_under": version_at(repo, commit)})
    return rows


def convert(record: dict, *, qci: str, qualified_under: str) -> dict:
    """The v2 form of a checked v1 record (AGYROLL §3.2); no signatures in RECBIND."""
    if record.get("schema") != V1:
        raise ConversionRefused("only a v1 record converts")
    value = {key: item for key, item in record.items() if key != "source_sha256"}
    value.update({
        "schema": V2, "qci": qci, "qualified_under": qualified_under,
        "upstream": {"asset_sha256": record["upstream_asset_sha256"], "release_url": record["upstream_release_url"],
                     "attestation": "not_checked", "second_channel": "not_checked"},
        "signatures": [],
    })
    return value


def write(repo: Path = REPO, *, python: str = sys.executable, digests=tree_digests) -> list[dict]:
    rows = check(repo, python=python, digests=digests)
    for row in rows:
        if row["schema"] != V1:
            continue
        path = repo / EVIDENCE_REL / row["record"]
        record = convert(json.loads(path.read_text()), qci=row["qci"], qualified_under=row["qualified_under"])
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="prove each member's record commit (the stop gate)")
    mode.add_argument("--write", action="store_true", help="check, then write each v1 record as v2")
    args = parser.parse_args(argv)
    try:
        rows = write() if args.write else check()
    except ConversionRefused as exc:
        print(f"convert_agy_record_v2: refused: {exc}", file=sys.stderr)
        print("requalify: the member above needs one owner-approved live requalification", file=sys.stderr)
        return 1
    print(json.dumps({"converted" if args.write else "checked": rows}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
