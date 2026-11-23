"""Review-runner image recipe CLI (RRIMAGE contract §3, IF-0-RRIMAGE-2).

Three subcommands, none of which builds, pushes, pulls or starts anything:

- ``plan --source-commit <sha>`` prints the §3 build recipe as a shell command plan. It reads
  no file and runs no subprocess; the operator runs the printed commands under G-RR-BUILD.
- ``record --layout <dir> --meta <json>`` reads an extracted OCI layout (§3.4) through
  :func:`review_runner_pin.assemble_built_record`, checks it with
  :func:`review_runner_pin.validate_pin_record` against ``--repo-root`` and commits the raw
  manifest, the raw config and the ``built`` record under ``plans/evidence/review-runner/``.
  It validates a staged copy first, then switches in a complete new evidence directory in one
  rename, so a refusal or a crash never leaves a mixed set. Existing evidence is replaced only
  with ``--replace``, which records a NEW build as a ``built`` record; it never confers
  ``pinned`` and never clears the stale marker (contract §2.1).
- ``verify-receipt --receipt <json> --registry <host> --repository <name>`` is the separate
  promotion step that completes a pin or re-pin. It promotes the committed ``built`` record
  with ai-stack's receipt through :func:`review_runner_pin.apply_receipt`, then requires a
  strict ``pinned`` verdict. The record file is rewritten only on success; otherwise it stays
  ``built``.

Refusals print ``<rule> <code>: <field>`` from :class:`review_runner_pin.PinRecordError` and
exit 2. Messages never carry record values.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence

from phase_loop_runtime import review_runner_pin as rp
from phase_loop_runtime.review_runner_pin import (
    PinRecordError,
    apply_receipt,
    assemble_built_record,
    validate_pin_record,
)

CONTAINERFILE_PATH = "phase-loop-runtime/images/review-runner/Containerfile"
EVIDENCE_DIR = "plans/evidence/review-runner"
RECORD_PATH = f"{EVIDENCE_DIR}/pin-record.json"
PLATFORM = "linux/amd64"
BUILDER_NAME = "rrimage"

# §3.2: the helper source, as pinned by the Containerfile and tests/data/landlock-exec/PIN.json.
HELPER_REPOSITORY = "Consiliency/agent-toolkit"
HELPER_COMMIT = "d945fdd060aab9ad9471845f4f8e78406a0ac841"
HELPER_SOURCE_PATH = "harnesses/pi/sandbox/landlock"

# §3.3: the BuildKit image the docker-container driver runs, named by digest. The release is
# at least two weeks old and at least v0.13.0, the first with ``rewrite-timestamp``.
BUILDKIT_MIN_VERSION = (0, 13, 0)
BUILDKIT_REPOSITORY = "docker.io/moby/buildkit"
BUILDKIT_VERSION = "v0.18.2"
BUILDKIT_DIGEST: str | None = (  # the v0.18.2 image index, as served by the registry
    "sha256:86c0ad9d1137c186e9d455912167df20e530bdf7f7c19de802e892bb8ca16552")
EXIT_REFUSED = 2

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


class RecipeError(Exception):
    """A refusal outside the pin record's closed codes (CLI input, BuildKit pin)."""


def buildkit_image() -> str:
    """The digest-pinned BuildKit reference, ``<repo>:<version>@sha256:<hex>``."""
    match = _VERSION.match(BUILDKIT_VERSION)
    if match is None or tuple(int(part) for part in match.groups()) < BUILDKIT_MIN_VERSION:
        raise RecipeError("buildkit_version_unsupported: BUILDKIT_VERSION")
    if not isinstance(BUILDKIT_DIGEST, str) or _DIGEST.match(BUILDKIT_DIGEST) is None:
        raise RecipeError("buildkit_unpinned: BUILDKIT_DIGEST")
    return f"{BUILDKIT_REPOSITORY}:{BUILDKIT_VERSION}@{BUILDKIT_DIGEST}"


# -- plan --------------------------------------------------------------------------------------

def _build_command(commit: str, attempt: int, image: str) -> list[str]:
    return [
        f"# Attempt {attempt}.",
        f'SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH" docker buildx build --builder {BUILDER_NAME} \\',
        f'  --file "$RR_WORK/context/{CONTAINERFILE_PATH}" \\',
        '  --build-context landlock-source="$RR_WORK/landlock-source" \\',
        f"  --platform {PLATFORM} \\",
        '  --build-arg SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH" \\',
        "  --provenance=false --sbom=false --no-cache \\",
        f"  --label {rp.REVISION_LABEL}={commit} \\",
        f'  --label {rp.CONTAINERFILE_LABEL}="$CONTAINERFILE_SHA256" \\',
        f'  --output type=oci,dest="$RR_WORK/attempt-{attempt}.tar",rewrite-timestamp=true \\',
        '  "$RR_WORK/context"',
        f'sha256sum "$RR_WORK/attempt-{attempt}.tar"',
        f'mkdir -m 0700 "$RR_WORK/layout-{attempt}"',
        f'tar -x -C "$RR_WORK/layout-{attempt}" -f "$RR_WORK/attempt-{attempt}.tar"',
    ]


def render_plan(commit: str) -> str:
    """The §3 recipe for ``commit``. Pure: no file read, no subprocess."""
    if not isinstance(commit, str) or _COMMIT.match(commit) is None:
        raise RecipeError("source_commit_invalid: --source-commit")
    image = buildkit_image()
    lines = [
        "# RRIMAGE §3 review-runner build recipe. Run under G-RR-BUILD on the build host,",
        "# from the agent-harness checkout, with heavy-work admission held.",
        "# Archives stay in $RR_WORK until SL-5; this recipe transfers no bytes.",
        "# Run with bash from the checkout at the source commit, so `record` checks P4 there.",
        "set -euo pipefail",
        'RR_WORK="${RR_WORK:?set RR_WORK to a new private directory}"',
        'test -d "$RR_WORK"',
        'test -z "$(ls -A "$RR_WORK")"',
        "",
        "# 1. Source export: tracked files at the source commit only.",
        'mkdir -m 0700 "$RR_WORK/context"',
        f'git archive --format=tar {commit} | tar -x -C "$RR_WORK/context"',
        f'SOURCE_DATE_EPOCH="$(git show -s --format=%ct {commit})"',
        f'CONTAINERFILE_SHA256="$(git show {commit}:{CONTAINERFILE_PATH} | sha256sum | cut -d" " -f1)"',
        "",
        f"# 2. Helper source: read-only fetch of {HELPER_REPOSITORY} at {HELPER_COMMIT}.",
        "#    The Containerfile's hash checks are the verification; no token enters the build.",
        'mkdir -m 0700 "$RR_WORK/landlock-source"',
        f"gh api repos/{HELPER_REPOSITORY}/tarball/{HELPER_COMMIT} \\",
        f"  | tar -xz -C \"$RR_WORK/landlock-source\" --strip-components=5 --wildcards '*/{HELPER_SOURCE_PATH}/*'",
        "",
        f"# 3. Builder: docker-container driver, BuildKit {BUILDKIT_VERSION} by digest.",
        f"docker buildx create --name {BUILDER_NAME} --driver docker-container \\",
        f"  --driver-opt image={image} --bootstrap",
        "docker buildx version",
        "",
        "# 4. Two OCI-archive builds with the same options. Attempt 1 is the hand-over artifact.",
    ]
    lines += _build_command(commit, 1, image)
    lines += _build_command(commit, 2, image)
    lines += [
        "",
        "# 9. Local evidence: read the helper's sha256 from the attempt-1 layer holding",
        "#    /usr/libexec/agent-toolkit/landlock-exec. No container is run.",
        "",
        "# Record: write the build metadata file, then commit the built record.",
        "python3 phase-loop-runtime/scripts/review_runner_image.py record \\",
        '  --layout "$RR_WORK/layout-1" --archive "$RR_WORK/attempt-1.tar" \\',
        '  --second-layout "$RR_WORK/layout-2" --meta "$RR_WORK/build-meta.json" --repo-root .',
        "",
        f"docker buildx rm {BUILDER_NAME}",
    ]
    return "\n".join(lines) + "\n"


# -- record ------------------------------------------------------------------------------------

def _read_json(path: str | os.PathLike[str], field: str) -> Any:
    try:
        return rp._parse_json(rp._read_regular(Path(path)))
    except (OSError, UnicodeDecodeError, ValueError):
        raise PinRecordError("pin_schema_invalid", "P1", field) from None


def _file_sha256(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        raise PinRecordError("pin_digest_mismatch", "P9", "artifact.oci_archive_sha256") from None
    return digest.hexdigest()


def _layers(manifest_bytes: bytes) -> list[str]:
    manifest = json.loads(manifest_bytes)
    return [layer.get("digest") for layer in manifest.get("layers", ())
            if isinstance(layer, Mapping)]


def _second_attempt(meta: Mapping[str, Any], layout: Path, second: Path,
                    deferred_finding: str | None) -> dict[str, Any]:
    """P10 fields from both attempts; each layout passes the same §3.4 and P9 checks."""
    single = json.loads(json.dumps(meta))
    single["build"]["reproduced"] = {"attempted": False, "second_manifest_digest": None,
                                     "equal": None, "differing_layers": [],
                                     "deferred_finding": None}
    first = assemble_built_record(layout, single)
    try:
        other = assemble_built_record(second, single)
    except PinRecordError as error:
        raise PinRecordError(error.code, error.rule, "second_layout." + error.field) from None
    first_digest = first.record["artifact"]["manifest_digest"]
    second_digest = other.record["artifact"]["manifest_digest"]
    first_layers, second_layers = _layers(first.manifest_bytes), _layers(other.manifest_bytes)
    equal = first_digest == second_digest
    differing = [] if equal else sorted(
        {d for a, b in zip(first_layers, second_layers) if a != b for d in (a, b)}
        | set(first_layers[len(second_layers):]) | set(second_layers[len(first_layers):]))
    if not equal and not differing:
        # Only the config differs. P10 requires a non-empty layer list for unequal digests,
        # and the schema holds layer digests only, so no record can describe this truthfully.
        raise PinRecordError("pin_reproducibility_inconsistent", "P10",
                             "build.reproduced.differing_layers")
    return {
        "attempted": True,
        "second_manifest_digest": second_digest,
        "equal": equal,
        "differing_layers": differing,
        "deferred_finding": None if equal else deferred_finding,
    }


# -- evidence publication ----------------------------------------------------------------------
#
# ``record`` publishes the whole ``plans/evidence/review-runner`` directory as one generation:
# it stages a complete copy in a private transaction directory beside it and switches the two
# with one rename (``renameat2(RENAME_EXCHANGE)`` when the live directory exists). The live
# name therefore always resolves to one complete generation, even after a crash. Every path
# below the trusted checkout root is opened relative to its parent without following symlinks,
# and one exclusive lock on ``plans/evidence`` covers the existence check and the switch.

EVIDENCE_PARENT = ("plans", "evidence")
LIVE_NAME = "review-runner"
TXN_NAME = ".review-runner.txn"
TARGET_NAMES = ("pin-record.json", "manifest.json", "config.json")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_RENAME_EXCHANGE = 2


def _unsafe(rel: str) -> RecipeError:
    return RecipeError(f"evidence_unsafe: {rel}")


def _open_dir(parent_fd: int, name: str, rel: str, *, create: bool) -> int | None:
    """Open ``name`` under ``parent_fd`` as a real directory, never through a symlink.

    A missing directory is created when ``create`` is set, else ``None`` is returned. A
    symlink or a non-directory is refused as ``evidence_unsafe``.
    """
    for attempt in range(2):
        try:
            return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            if not create:
                return None
            if attempt:
                raise _unsafe(rel) from None
            try:
                os.mkdir(name, 0o777, dir_fd=parent_fd)
            except FileExistsError:
                pass
        except OSError:  # ELOOP for a symlink, ENOTDIR for a non-directory
            raise _unsafe(rel) from None
    raise _unsafe(rel)


class _Evidence:
    """The locked ``plans/evidence`` directory and, if present, the live evidence directory."""

    def __init__(self, root: Path, *, create: bool):
        self.fds: list[int] = []
        try:
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            self.fds.append(fd)
            rel = ""
            for name in EVIDENCE_PARENT:
                rel = f"{rel}/{name}" if rel else name
                child = _open_dir(fd, name, rel, create=create)
                if child is None:
                    raise RecipeError(f"evidence_missing: {EVIDENCE_DIR}")
                self.fds.append(child)
                fd = child
            self.parent = fd
            fcntl.flock(self.parent, fcntl.LOCK_EX)
            self.live = _open_dir(self.parent, LIVE_NAME, EVIDENCE_DIR, create=False)
            if self.live is not None:
                self.fds.append(self.live)
        except BaseException:
            self.close()
            raise

    def exists(self, name: str) -> bool:
        if self.live is None:
            return False
        try:
            os.stat(name, dir_fd=self.live, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    def close(self) -> None:
        for fd in reversed(self.fds):
            os.close(fd)
        self.fds.clear()

    def __enter__(self) -> "_Evidence":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _write_new(dir_fd: int, name: str, data: bytes, mode: int = 0o600) -> None:
    """Create ``name`` exclusively (no-follow) at ``mode``, write ``data`` and fsync it."""
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=dir_fd)
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy_entries(src_fd: int, dst_fd: int, skip: frozenset[str], rel: str) -> None:
    """Copy ``src_fd``'s entries into ``dst_fd`` without following symlinks, keeping modes."""
    for name in sorted(os.listdir(src_fd)):
        if name in skip:
            continue
        info = os.stat(name, dir_fd=src_fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            os.symlink(os.readlink(name, dir_fd=src_fd), name, dir_fd=dst_fd)
        elif stat.S_ISREG(info.st_mode):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=src_fd)
            try:
                with os.fdopen(os.dup(fd), "rb") as stream:
                    data = stream.read()
            finally:
                os.close(fd)
            _write_new(dst_fd, name, data, stat.S_IMODE(info.st_mode))
        elif stat.S_ISDIR(info.st_mode):
            os.mkdir(name, 0o700, dir_fd=dst_fd)
            sub_src = os.open(name, _DIR_FLAGS, dir_fd=src_fd)
            sub_dst = os.open(name, _DIR_FLAGS, dir_fd=dst_fd)
            try:
                _copy_entries(sub_src, sub_dst, frozenset(), f"{rel}/{name}")
                os.fchmod(sub_dst, stat.S_IMODE(info.st_mode))
                os.fsync(sub_dst)
            finally:
                os.close(sub_src)
                os.close(sub_dst)
        else:
            raise _unsafe(f"{rel}/{name}")


def _clear_abandoned(evidence: _Evidence) -> None:
    """Remove a transaction directory left by an interrupted publication, if it is ours."""
    try:
        info = os.stat(TXN_NAME, dir_fd=evidence.parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise _unsafe(f"plans/evidence/{TXN_NAME}")
    shutil.rmtree(TXN_NAME, dir_fd=evidence.parent)


def _rename_exchange(src_fd: int, src: str, dst_fd: int, dst: str) -> None:
    """Swap two directory entries in one operation (Linux ``renameat2(RENAME_EXCHANGE)``)."""
    libc = ctypes.CDLL(None, use_errno=True) if sys.platform.startswith("linux") else None
    function = getattr(libc, "renameat2", None)
    if function is None:
        raise RecipeError(f"evidence_exchange_unsupported: {EVIDENCE_DIR}")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
                         ctypes.c_uint]
    if function(src_fd, os.fsencode(src), dst_fd, os.fsencode(dst), _RENAME_EXCHANGE) != 0:
        code = ctypes.get_errno()
        if code in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP):
            raise RecipeError(f"evidence_exchange_unsupported: {EVIDENCE_DIR}")
        raise OSError(code, os.strerror(code))


def _switch(evidence: _Evidence, txn_fd: int) -> None:
    """The commit point: the staged directory becomes the live one in a single rename."""
    if evidence.live is None:
        os.rename(LIVE_NAME, LIVE_NAME, src_dir_fd=txn_fd, dst_dir_fd=evidence.parent)
    else:
        _rename_exchange(txn_fd, LIVE_NAME, evidence.parent, LIVE_NAME)


def _publish_generation(evidence: _Evidence, files: Mapping[str, bytes]) -> None:
    """Stage a complete evidence directory with ``files`` and switch it in atomically."""
    _clear_abandoned(evidence)
    os.mkdir(TXN_NAME, 0o700, dir_fd=evidence.parent)
    txn_fd = os.open(TXN_NAME, _DIR_FLAGS, dir_fd=evidence.parent)
    switched = False
    try:
        os.fchmod(txn_fd, 0o700)
        os.mkdir(LIVE_NAME, 0o700, dir_fd=txn_fd)
        stage_fd = os.open(LIVE_NAME, _DIR_FLAGS, dir_fd=txn_fd)
        try:
            if evidence.live is not None:
                _copy_entries(evidence.live, stage_fd, frozenset(files), EVIDENCE_DIR)
                os.fchmod(stage_fd, stat.S_IMODE(os.fstat(evidence.live).st_mode))
            else:
                os.fchmod(stage_fd, 0o777 & ~_umask())
            for name, data in files.items():
                _write_new(stage_fd, name, data)
            os.fsync(stage_fd)
        finally:
            os.close(stage_fd)
        os.fsync(txn_fd)
        _switch(evidence, txn_fd)
        switched = True
        os.fsync(evidence.parent)
        os.fsync(txn_fd)
    finally:
        os.close(txn_fd)
        if not switched:
            shutil.rmtree(TXN_NAME, dir_fd=evidence.parent, ignore_errors=True)
    # The transaction directory now holds the previous generation; an error here leaves it
    # for the next publication to clear.
    shutil.rmtree(TXN_NAME, dir_fd=evidence.parent)


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


def _validate_staged(record: Mapping[str, Any], root: Path, manifest: bytes,
                     config: bytes) -> Any:
    """Strict ``validate_pin_record`` on a private copy, before any evidence path changes.

    The copy holds the candidate manifest and config plus the checkout's Containerfile and
    PIN.json, the only other files the validator reads under strict P4.
    """
    with tempfile.TemporaryDirectory(prefix="rrimage-record-") as staging:
        stage = Path(staging)
        inputs = {
            record["artifact"]["manifest_path"]: manifest,
            record["artifact"]["config_path"]: config,
        }
        for rel, field, code, rule in (
                (record["source"]["containerfile_path"], "source.containerfile_path",
                 "pin_containerfile_stale", "P4"),
                (rp.PIN_JSON_PATH, "helper", "pin_helper_mismatch", "P5")):
            try:
                inputs[rel] = rp._read_regular(root / rel)
            except OSError:
                raise PinRecordError(code, rule, field) from None
        for rel, data in inputs.items():
            target = stage / rel
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            dir_fd = os.open(target.parent, _DIR_FLAGS)
            try:
                _write_new(dir_fd, target.name, data)
            finally:
                os.close(dir_fd)
        return validate_pin_record(record, stage)


def _record_bytes(record: Mapping[str, Any]) -> bytes:
    return (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def cmd_record(args: argparse.Namespace) -> int:
    meta = _read_json(args.meta, "build_meta")
    if not isinstance(meta, dict):
        raise PinRecordError("pin_schema_invalid", "P1", "build_meta")
    meta = json.loads(json.dumps(meta))
    if args.archive is not None:
        meta["oci_archive_sha256"] = _file_sha256(args.archive)
    if args.second_layout is not None:
        build = meta.get("build")
        if not isinstance(build, dict):
            raise PinRecordError("pin_schema_invalid", "P1", "build_meta")
        build["reproduced"] = _second_attempt(meta, Path(args.layout), Path(args.second_layout),
                                              args.deferred_finding)
    root = Path(args.repo_root)
    assembled = assemble_built_record(args.layout, meta)
    record = assembled.record
    verdict = _validate_staged(record, root, assembled.manifest_bytes, assembled.config_bytes)
    with _Evidence(root, create=True) as evidence:
        if not args.replace:
            for name in TARGET_NAMES:
                if evidence.exists(name):
                    raise RecipeError(
                        f"evidence_exists: {EVIDENCE_DIR}/{name} (pass --replace to record a new build)")
        _publish_generation(evidence, {
            "manifest.json": assembled.manifest_bytes,
            "config.json": assembled.config_bytes,
            "pin-record.json": _record_bytes(record),
        })
    print(f"recorded {verdict.record_status} {RECORD_PATH} record_sha256={verdict.record_sha256}")
    return 0


# -- verify-receipt ----------------------------------------------------------------------------

def _read_record(live_fd: int) -> dict[str, Any]:
    try:
        fd = os.open("pin-record.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=live_fd)
    except OSError:
        raise PinRecordError("pin_schema_invalid", "P1") from None
    try:
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(rp.MAX_RECORD_BYTES + 1)
    finally:
        os.close(fd)
    try:
        if len(raw) > rp.MAX_RECORD_BYTES:
            raise ValueError("too large")
        value = rp._parse_json(raw)
    except (UnicodeDecodeError, ValueError):
        raise PinRecordError("pin_schema_invalid", "P1") from None
    if not isinstance(value, dict):
        raise PinRecordError("pin_schema_invalid", "P1")
    return value


def _replace_file(dir_fd: int, name: str, data: bytes) -> None:
    """Write a private temporary file beside ``name`` and rename it over ``name``."""
    tmp = f".{name}.{secrets.token_hex(8)}"
    _write_new(dir_fd, tmp, data)
    try:
        os.rename(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        os.unlink(tmp, dir_fd=dir_fd)
        raise
    os.fsync(dir_fd)


def cmd_verify_receipt(args: argparse.Namespace) -> int:
    root = Path(args.repo_root)
    receipt = _read_json(args.receipt, "receipt")
    if not isinstance(receipt, dict):
        raise PinRecordError("pin_schema_invalid", "P1", "receipt")
    image = {"registry": args.registry, "repository": args.repository}
    with _Evidence(root, create=False) as evidence:
        if evidence.live is None:
            raise RecipeError(f"evidence_missing: {EVIDENCE_DIR}")
        record = _read_record(evidence.live)
        pinned = apply_receipt(record, receipt, image=image, recorded_at=args.recorded_at)
        verdict = validate_pin_record(pinned, root)
        verdict.require_pinned()
        _replace_file(evidence.live, "pin-record.json", _record_bytes(pinned))
    print(f"pinned {RECORD_PATH} record_sha256={verdict.record_sha256}")
    return 0


# -- entry point -------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review_runner_image.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="print the §3 build recipe; runs nothing")
    plan.add_argument("--source-commit", required=True)

    record = sub.add_parser("record", help="commit the built record from an OCI layout")
    record.add_argument("--layout", required=True)
    record.add_argument("--meta", required=True)
    record.add_argument("--archive")
    record.add_argument("--second-layout")
    record.add_argument("--deferred-finding")
    record.add_argument("--repo-root", default=".")
    record.add_argument("--replace", action="store_true",
                        help="replace existing evidence with a validated built record")

    verify = sub.add_parser("verify-receipt", help="promote the built record to pinned with ai-stack's receipt "
                                 "(the separate step that completes a pin or re-pin)")
    verify.add_argument("--receipt", required=True)
    verify.add_argument("--registry", required=True)
    verify.add_argument("--repository", required=True)
    verify.add_argument("--recorded-at")
    verify.add_argument("--repo-root", default=".")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            sys.stdout.write(render_plan(args.source_commit))
            return 0
        if args.command == "record":
            return cmd_record(args)
        return cmd_verify_receipt(args)
    except (PinRecordError, RecipeError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
