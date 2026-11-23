"""Review-runner image recipe CLI (RRIMAGE contract §3, IF-0-RRIMAGE-2).

Three subcommands, none of which builds, pushes, pulls or starts anything:

- ``plan --source-commit <sha>`` prints the §3 build recipe as a shell command plan. It reads
  no file and runs no subprocess; the operator runs the printed commands under G-RR-BUILD.
- ``record --layout <dir> --meta <json>`` reads an extracted OCI layout (§3.4) through
  :func:`review_runner_pin.assemble_built_record`, checks it with
  :func:`review_runner_pin.validate_pin_record` against ``--repo-root`` and commits the raw
  manifest, the raw config and the ``built`` record under ``plans/evidence/review-runner/``.
  It validates a staged copy first and publishes the three files as one set, so a refusal
  never touches existing evidence; replacing existing evidence needs ``--replace``.
- ``verify-receipt --receipt <json> --registry <host> --repository <name>`` promotes the
  committed ``built`` record with ai-stack's receipt through
  :func:`review_runner_pin.apply_receipt`, then requires a strict ``pinned`` verdict. The
  record file is rewritten only on success; otherwise it stays ``built``.

Refusals print ``<rule> <code>: <field>`` from :class:`review_runner_pin.PinRecordError` and
exit 2. Messages never carry record values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
from typing import Any, Mapping, Sequence

from phase_loop_runtime import review_runner_pin as rp
from phase_loop_runtime.review_runner_pin import (
    PinRecordError,
    apply_receipt,
    assemble_built_record,
    load_pin_record,
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


def _write_atomic(path: Path, data: bytes) -> None:
    _publish({path: data})


def _publish(files: Mapping[Path, bytes]) -> None:
    """Replace ``files`` as one set: stage every file, then swap them in, rolling back on error.

    Existing targets are first moved aside as hidden backups in the same directory; if any
    replacement fails, every target is restored from its backup (or removed if it was new).
    """
    staged: dict[Path, str] = {}
    backups: dict[Path, str | None] = {}
    try:
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
            staged[path] = tmp
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        for path, tmp in list(staged.items()):
            backup = None
            if os.path.lexists(path):
                backup = str(path.parent / f".{path.name}.bak.{secrets.token_hex(8)}")
                os.link(path, backup)  # fails on a name collision; the target stays in place
            backups[path] = backup
            os.replace(tmp, path)
            del staged[path]
    except BaseException:
        for path, backup in backups.items():
            if path in staged:
                continue
            if backup is not None:
                os.replace(backup, path)
            else:
                Path(path).unlink(missing_ok=True)
        for tmp in staged.values():
            Path(tmp).unlink(missing_ok=True)
        for backup in backups.values():
            if backup is not None:
                Path(backup).unlink(missing_ok=True)
        raise
    for backup in backups.values():
        if backup is not None:
            Path(backup).unlink(missing_ok=True)


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
            (stage / rel).parent.mkdir(parents=True, exist_ok=True)
            (stage / rel).write_bytes(data)
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
    targets = (RECORD_PATH, f"{EVIDENCE_DIR}/manifest.json", f"{EVIDENCE_DIR}/config.json")
    if not args.replace:
        for rel in targets:
            if os.path.lexists(root / rel):
                raise RecipeError(f"evidence_exists: {rel} (pass --replace to re-record)")
    assembled = assemble_built_record(args.layout, meta)
    record = assembled.record
    verdict = _validate_staged(record, root, assembled.manifest_bytes, assembled.config_bytes)
    _publish({
        root / record["artifact"]["manifest_path"]: assembled.manifest_bytes,
        root / record["artifact"]["config_path"]: assembled.config_bytes,
        root / RECORD_PATH: _record_bytes(record),
    })
    print(f"recorded {verdict.record_status} {RECORD_PATH} record_sha256={verdict.record_sha256}")
    return 0


# -- verify-receipt ----------------------------------------------------------------------------

def cmd_verify_receipt(args: argparse.Namespace) -> int:
    root = Path(args.repo_root)
    record_path = root / RECORD_PATH
    record = load_pin_record(record_path)
    receipt = _read_json(args.receipt, "receipt")
    if not isinstance(receipt, dict):
        raise PinRecordError("pin_schema_invalid", "P1", "receipt")
    image = {"registry": args.registry, "repository": args.repository}
    pinned = apply_receipt(record, receipt, image=image, recorded_at=args.recorded_at)
    verdict = validate_pin_record(pinned, root)
    verdict.require_pinned()
    _write_atomic(record_path, _record_bytes(pinned))
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
                        help="re-record over existing evidence (a re-pin, contract §2.1)")

    verify = sub.add_parser("verify-receipt", help="promote the built record with a receipt")
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
