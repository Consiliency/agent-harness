"""Retention provenance, never verification acceptance (agent-harness#1772).

Prospective receipts are written at the actual verification producer boundary.
Historical custody requires an SSH signature trusted by the operator outside the
repository. Neither mechanism authenticates against a hostile local filesystem
owner; see the generated-output audit's existing threat model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timezone

SCHEMA = "phase-loop.artifact-retention.v1"
NAMESPACE = "phase-loop-artifact-custody-v1"
STORE = ".phase-loop/artifact-retention"
PRODUCER = "phase_loop_runtime.verification_evidence.run_verification"
MAX_RECORD = 1024 * 1024
_FIELDS = {
    "schema",
    "mode",
    "repo",
    "source_commit",
    "run_id",
    "phases",
    "recorded_at",
    "custodian",
    "limitations",
    "files",
}


class RetentionError(ValueError):
    """Cannot establish retention provenance; callers must surface the failure."""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10
    )
    if result.returncode:
        raise RetentionError("cannot establish repository identity or ancestry")
    return result.stdout.strip()


def _identity(repo: Path) -> dict:
    return {
        "root": str(repo.resolve()),
        "common_dir": str(
            Path(
                _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
            ).resolve()
        ),
        "object_format": _git(repo, "rev-parse", "--show-object-format"),
    }


def _path(repo: Path, relative: str) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise RetentionError("invalid artifact path")
    parts = relative.split("/")
    if (
        any(p in {"", ".", ".."} for p in parts)
        or PurePosixPath(relative).is_absolute()
    ):
        raise RetentionError("artifact path must be normalized and repository-relative")
    path = repo.resolve()
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise RetentionError("symlink in retention path")
    return path


def _artifact_path(repo: Path, relative: str) -> Path:
    path = _path(repo, relative)
    parts = relative.split("/")
    if len(parts) < 4 or parts[:2] not in (
        [".dev-skills", "runs"],
        [".dev-skills", "reviews"],
        [".dev-skills", "evidence"],
    ):
        raise RetentionError("unsupported retained artifact family")
    return path


def _digest(path: Path) -> tuple[int, str]:
    # O_NOFOLLOW also rejects replacement of the leaf between checking and open.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise RetentionError("artifact is not a regular file")
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _canonical(statement: dict) -> bytes:
    return (
        json.dumps(statement, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _load(raw: bytes, limit: int = MAX_RECORD) -> dict:
    if len(raw) > limit:
        raise RetentionError("retention record exceeds size limit")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RetentionError("duplicate retention record key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise RetentionError("retention record must be an object")
    return value


def _read(path: Path, limit: int = MAX_RECORD) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise RetentionError("retention metadata is not a regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise RetentionError("retention record exceeds size limit")
    return raw


def _validate(repo: Path, statement: dict) -> None:
    if set(statement) != _FIELDS or statement["schema"] != SCHEMA:
        raise RetentionError("unsupported retention statement")
    if statement["mode"] not in {"observed_verification", "historical_custody"}:
        raise RetentionError("unsupported retention mode")
    if statement["repo"] != _identity(repo):
        raise RetentionError("retention repository identity mismatch")
    commit = statement["source_commit"]
    if not isinstance(commit, str) or not re.fullmatch(
        r"[0-9a-f]{40}|[0-9a-f]{64}", commit
    ):
        raise RetentionError("invalid source commit")
    _git(repo, "merge-base", "--is-ancestor", commit, "HEAD")
    phases = statement["phases"]
    if (
        not isinstance(phases, list)
        or not phases
        or len(phases) > 100
        or any(
            not isinstance(p, str) or not re.fullmatch(r"[A-Z][A-Z0-9._-]*", p)
            for p in phases
        )
        or len(set(phases)) != len(phases)
    ):
        raise RetentionError("explicit consuming phases required")
    for key in ("run_id", "custodian", "limitations"):
        if (
            not isinstance(statement[key], str)
            or not statement[key].strip()
            or len(statement[key]) > 4096
        ):
            raise RetentionError("missing retention identity or limitations")
    if not re.fullmatch(r"[A-Za-z0-9._@+-]+", statement["custodian"]):
        raise RetentionError("invalid custodian principal")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", statement["run_id"]) or statement[
        "run_id"
    ] in {".", ".."}:
        raise RetentionError("invalid run identity")
    stamp = datetime.fromisoformat(statement["recorded_at"])
    if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
        raise RetentionError("invalid custody timestamp")
    files = statement["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= 1000:
        raise RetentionError("invalid artifact inventory")
    seen = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
            raise RetentionError("invalid artifact entry")
        path = _artifact_path(repo, item["path"])
        if item["path"] in seen:
            raise RetentionError("duplicate artifact path")
        seen.add(item["path"])
        if (
            type(item["bytes"]) is not int
            or item["bytes"] < 0
            or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        ):
            raise RetentionError("invalid artifact digest or length")
        if _digest(path) != (item["bytes"], item["sha256"]):
            raise RetentionError("retained artifact bytes changed")
    if statement["mode"] == "observed_verification":
        expected = {
            f".dev-skills/runs/{statement['run_id']}/{name}"
            for name in ("verification.json", "verification.log")
        }
        if seen != expected or statement["custodian"] != PRODUCER or len(phases) != 1:
            raise RetentionError("invalid observed verification producer binding")
        from .verification_evidence import MAX_ARTIFACT_BYTES

        artifact = _load(
            _read(
                repo / f".dev-skills/runs/{statement['run_id']}/verification.json",
                MAX_ARTIFACT_BYTES,
            ),
            MAX_ARTIFACT_BYTES,
        )
        if (
            artifact.get("run_id") != statement["run_id"]
            or artifact.get("phase_alias") != phases[0]
        ):
            raise RetentionError("verification run or phase mismatch")
        log_hash = next(
            item["sha256"]
            for item in files
            if item["path"].endswith("/verification.log")
        )
        if artifact.get("log_sha256") != log_hash:
            raise RetentionError("verification log binding mismatch")


def _statement(
    repo: Path,
    paths: list[str],
    *,
    mode: str,
    phases: list[str],
    run_id: str,
    custodian: str,
    limitations: str,
    source_commit: str,
) -> dict:
    files = []
    for relative in sorted(paths):
        size, digest = _digest(_artifact_path(repo, relative))
        files.append({"path": relative, "bytes": size, "sha256": digest})
    result = dict(
        schema=SCHEMA,
        mode=mode,
        repo=_identity(repo),
        source_commit=source_commit,
        run_id=run_id,
        phases=phases,
        recorded_at=datetime.now(timezone.utc).isoformat(),
        custodian=custodian,
        limitations=limitations,
        files=files,
    )
    _validate(repo, result)
    return result


def _record_path(repo: Path, relative: str) -> Path:
    key = hashlib.sha256(relative.encode("utf-8")).hexdigest()
    return _path(repo, f"{STORE}/{key}.json")


def _store(repo: Path, statement: dict, signature: str | None) -> None:
    _validate(repo, statement)
    raw = _canonical({"statement": statement, "signature": signature})
    if len(raw) > MAX_RECORD:
        raise RetentionError("retention record exceeds size limit")
    for item in statement["files"]:
        dest = _record_path(repo, item["path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".receipt-", dir=dest.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, dest)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def verification_start(repo: Path, run_path: Path, phase: str | None) -> str | None:
    """Capture the actual producer's pre-run commit for the supported family."""
    try:
        relative = run_path.relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None
    parts = relative.split("/")
    if len(parts) != 3 or parts[:2] != [".dev-skills", "runs"] or phase is None:
        return None
    _path(repo, relative)
    if not re.fullmatch(r"[A-Z][A-Z0-9._-]*", phase):
        raise RetentionError("explicit valid phase required for verification retention")
    return _git(repo, "rev-parse", "HEAD")


def verification_finished(
    repo: Path, run_path: Path, phase: str, started_commit: str
) -> None:
    if _git(repo, "rev-parse", "HEAD") != started_commit:
        raise RetentionError(
            "HEAD changed during verification; no retention receipt recorded"
        )
    paths = [
        (run_path / name).relative_to(repo.resolve()).as_posix()
        for name in ("verification.json", "verification.log")
    ]
    statement = _statement(
        repo,
        paths,
        mode="observed_verification",
        phases=[phase],
        run_id=run_path.name,
        custodian=PRODUCER,
        limitations="Runtime-observed file production only; no model attribution, successful verification, or phase acceptance is implied.",
        source_commit=started_commit,
    )
    _store(repo, statement, None)


def _allowed_signers() -> Path:
    # Deliberately not controlled by repository config, statement, or CLI input.
    return Path.home() / ".config/consiliency/artifact-adoption-allowed-signers"


def _verify_signature(repo: Path, statement: dict, signature: str) -> None:
    signers = _allowed_signers()
    for root in (repo.resolve(), Path(statement["repo"]["common_dir"])):
        if signers.resolve().is_relative_to(root):
            raise RetentionError("adoption trust must be outside the repository")
    if not signers.is_file():
        raise RetentionError("operator adoption allowed-signers file is missing")
    if (
        not isinstance(signature, str)
        or not signature.startswith("-----BEGIN SSH SIGNATURE-----\n")
        or len(signature) > 16384
    ):
        raise RetentionError("missing or invalid custody signature")
    with tempfile.TemporaryDirectory(prefix="artifact-custody-") as tmp:
        sig = Path(tmp) / "statement.sig"
        sig.write_text(signature, encoding="ascii")
        result = subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "verify",
                "-f",
                str(signers),
                "-I",
                statement["custodian"],
                "-n",
                NAMESPACE,
                "-s",
                str(sig),
            ],
            input=_canonical(statement),
            capture_output=True,
            timeout=10,
        )
    if result.returncode:
        raise RetentionError(
            "custody signature is not authorized by the operator trust store"
        )


def verify_retention(
    repo: Path, relative: str, phase: str | None, cache: dict | None = None
) -> tuple[bool, str]:
    if not relative.startswith(
        (".dev-skills/runs/", ".dev-skills/reviews/", ".dev-skills/evidence/")
    ):
        return False, "not a retained artifact path"
    try:
        raw = _read(_record_path(repo, relative))
        key = hashlib.sha256(raw).hexdigest()
        if cache is not None and key in cache:
            paths, reason = cache[key]
            if relative in paths:
                return True, reason
        record = _load(raw)
        if set(record) != {"statement", "signature"} or not isinstance(
            record["statement"], dict
        ):
            raise RetentionError("invalid retention receipt")
        statement = record["statement"]
        _validate(repo, statement)
        if phase not in statement["phases"]:
            raise RetentionError("retention receipt does not name the consuming phase")
        if relative not in [item["path"] for item in statement["files"]]:
            raise RetentionError("retention receipt does not name this artifact")
        if statement["mode"] == "historical_custody":
            _verify_signature(repo, statement, record["signature"])
        elif record["signature"] is not None:
            raise RetentionError("unexpected signature on producer receipt")
        reason = f"{statement['mode']}: retention only, not acceptance"
        if cache is not None:
            cache[key] = ({item["path"] for item in statement["files"]}, reason)
        return True, reason
    except FileNotFoundError:
        return (
            False,
            "no retention receipt or a required artifact/trust file is missing; legacy files require signed custody adoption",
        )
    except RetentionError as exc:
        return False, str(exc)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return (
            False,
            "retention receipt, artifact identity/bytes, phase, ancestry or custody authorization could not be verified",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "prepare", help="write a custody proposal; grants no trust"
    )
    prepare.add_argument("--repo", required=True, type=Path)
    prepare.add_argument("--phase", required=True, action="append")
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--custodian", required=True)
    prepare.add_argument("--limitations", required=True)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("paths", nargs="+")
    adopt = commands.add_parser(
        "adopt", help="verify operator signature and record custody"
    )
    adopt.add_argument("--repo", required=True, type=Path)
    adopt.add_argument("--statement", required=True, type=Path)
    adopt.add_argument("--signature", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            statement = _statement(
                args.repo,
                args.paths,
                mode="historical_custody",
                phases=args.phase,
                run_id=args.run_id,
                custodian=args.custodian,
                limitations=args.limitations,
                source_commit=_git(args.repo, "rev-parse", "HEAD"),
            )
            with args.output.open("xb") as stream:
                stream.write(_canonical(statement))
            print("Custody proposal written; no artifacts adopted or accepted.")
        else:
            statement = _load(_read(args.statement))
            _validate(args.repo, statement)
            if statement["mode"] != "historical_custody":
                raise RetentionError("adopt requires a historical custody statement")
            signature = _read(args.signature).decode("ascii")
            _verify_signature(args.repo, statement, signature)
            _store(args.repo, statement, signature)
            print(
                "Signed custody recorded; verification and phase acceptance are unchanged."
            )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            f"Retention operation refused ({type(exc).__name__}); original evidence was not modified."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
