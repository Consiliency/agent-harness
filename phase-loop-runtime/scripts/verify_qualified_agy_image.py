"""Verify the current qualified agy record against source and Google's release asset."""

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import tarfile
import tempfile
from urllib.request import Request, urlopen


REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "phase-loop-runtime/src/phase_loop_runtime"
EVIDENCE = REPO / "plans/evidence"
ASSET = "agy_cli_linux_x64.tar.gz"
API = "https://api.github.com/repos/google-antigravity/antigravity-cli/releases/latest"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest_file(path):
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def image_constants():
    tree = ast.parse((PACKAGE / "gemini_heartbeat.py").read_text())
    names = {"QUALIFIED_IMAGE_SHA256", "QUALIFIED_HELP_SHA256", "PROFILE_ID"}
    return {target.id: ast.literal_eval(node.value)
            for node in tree.body if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name) and target.id in names}


def validate_record():
    catalog = json.loads((EVIDENCE / "qualified-provider-images.json").read_text())
    require(catalog["schema"] == "qualified_provider_images.v1", "catalog schema mismatch")
    require(set(catalog["routes"]) == {"gemini_heartbeat_linux_x64"}, "catalog route mismatch")
    route = catalog["routes"]["gemini_heartbeat_linux_x64"]
    for key, value in {"provider": "gemini", "route": "brokered_subscription_heartbeat_only",
                       "platform": "linux", "architecture": "x86_64"}.items():
        require(route[key] == value, f"catalog {key} mismatch")
    name = route["record"]
    require(Path(name).name == name and name.startswith("agy-") and
            name.endswith("-linux-x64-qualification.json"), "unsafe catalog record path")
    record = json.loads((EVIDENCE / name).read_text())
    for key, value in {"provider": route["provider"], "route": route["route"],
                       "platform": route["platform"], "architecture": route["architecture"]}.items():
        require(record[key] == value, f"record {key} mismatch")
    constants = image_constants()
    require(record["image_sha256"] == constants["QUALIFIED_IMAGE_SHA256"], "admitted image mismatch")
    require(record["help_sha256"] == constants["QUALIFIED_HELP_SHA256"], "help digest mismatch")
    require(record["isolation_profile"] == constants["PROFILE_ID"], "isolation profile mismatch")
    pins = record["source_sha256"]
    actual = {str(path.relative_to(PACKAGE)): digest_file(path) for path in PACKAGE.rglob("*.py")}
    actual["qualify_gemini_heartbeat.py"] = digest_file(REPO / "phase-loop-runtime/scripts/qualify_gemini_heartbeat.py")
    require(pins == actual, "qualification source hashes differ from this checkout")
    require(record["validator"] == {"validated": 3,
                                    "operations": ["cancel", "completion", "owner-loss"],
                                    "route_qualified": True}, "qualification validation mismatch")
    require({row["operation"] for row in record["records"]} ==
            {"cancel", "completion", "owner-loss"}, "qualification operations mismatch")
    require(all(row["image_sha256"] == record["image_sha256"] and
                row["help_sha256"] == record["help_sha256"] and
                row["profile"]["id"] == record["isolation_profile"]
                for row in record["records"]), "qualification record image or profile mismatch")
    return record, len(actual)


def verify_archive(record, archive):
    require(digest_file(archive) == record["upstream_asset_sha256"], "archive digest mismatch")
    with tarfile.open(archive, "r:gz") as bundle:
        member = bundle.getmember("antigravity")
        require(member.isfile() and member.size <= 250_000_000, "archive member invalid")
        stream = bundle.extractfile(member)
        require(stream is not None, "archive member missing")
        h = sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    require(h.hexdigest() == record["image_sha256"], "executable digest mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="verify a locally downloaded official asset")
    args = parser.parse_args()
    record, source_count = validate_record()
    request = Request(API, headers={"Accept": "application/vnd.github+json",
                                    "User-Agent": "agent-harness-qualified-image-check"})
    with urlopen(request, timeout=30) as response:
        release = json.load(response)
    require(release["tag_name"] == record["release_version"], "qualified release is no longer latest")
    asset, = (item for item in release["assets"] if item["name"] == ASSET)
    require(asset["digest"] == "sha256:" + record["upstream_asset_sha256"], "vendor asset digest mismatch")
    require(asset["browser_download_url"].startswith(
        f"https://github.com/google-antigravity/antigravity-cli/releases/download/{record['release_version']}/"
    ), "vendor asset URL mismatch")
    if args.archive is not None:
        verify_archive(record, args.archive)
    else:
        with tempfile.TemporaryDirectory(prefix="agy-qualification-") as scratch:
            archive = Path(scratch) / ASSET
            request = Request(asset["browser_download_url"], headers={"User-Agent": "agent-harness-qualified-image-check"})
            with urlopen(request, timeout=60) as response, archive.open("wb") as target:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
                    require(target.tell() <= 128_000_000, "release asset exceeds expected size")
            verify_archive(record, archive)
    print(json.dumps({"latest_release": release["tag_name"], "source_files": source_count,
                      "asset_sha256": record["upstream_asset_sha256"],
                      "image_sha256": record["image_sha256"], "verified": True}))


if __name__ == "__main__":
    main()
