"""Fetch the public frozen commit and compare its distribution with sealed inputs."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from phase_loop_runtime.supervised_contracts import (
    INPUT_ARTIFACT_SHA256, PUBLICATION_PINS, SOURCE_COMMIT, load_contract_bundle,
)

MANIFEST_ANCHOR = "b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285"


def compare_publication(upstream, blobs, bundle, *, include_excluded=True):
    names = set(PUBLICATION_PINS) - (set() if include_excluded else {"provenance.json"})
    if set(upstream) != names or set(blobs) != set(PUBLICATION_PINS):
        raise ValueError("publication_mismatch")
    for name in names:
        digest, blob = PUBLICATION_PINS[name]
        if sha256(upstream[name]).hexdigest() != digest or blobs[name] != blob:
            raise ValueError("publication_mismatch")
        if name != "provenance.json" and bundle.resource_bytes(name) != upstream[name]:
            raise ValueError("publication_mismatch")


def verify_seal(repo):
    artifact = (repo / "plans/artifacts/v12-SCHEMA-inputs.md").read_bytes()
    entry = next(r for r in json.loads((repo / "plans/manifest.json").read_bytes())["plans"] if r["slug"] == "v12-SCHEMA")
    sealed = entry["frozen_inputs"]["plans/artifacts/v12-SCHEMA-inputs.md"]["sha256"]
    if sha256(artifact).hexdigest() != sealed or sealed != INPUT_ARTIFACT_SHA256:
        raise ValueError("publication_mismatch")
    inventory = {n: (d, b) for n, d, b in re.findall(
        r"^\| `([^`]+)` \| `([0-9a-f]{64})` \| `([0-9a-f]{40})` \|$", artifact.decode(), re.M)}
    if inventory != dict(PUBLICATION_PINS) or inventory["conformance/SHA256SUMS"][0] != MANIFEST_ANCHOR:
        raise ValueError("publication_mismatch")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify_seal(args.repo)
    bundle = load_contract_bundle()
    def command(argv, cwd=None):
        return subprocess.check_output(argv, cwd=cwd, timeout=180)
    public = json.loads(command(["gh", "api", "repos/Consiliency/consiliency-contract"]))
    if public["private"] or public["default_branch"] != "main":
        raise ValueError("publication_mismatch")
    branch = json.loads(command(["gh", "api", "repos/Consiliency/consiliency-contract/branches/main"]))
    if branch["protected"] is not True:
        raise ValueError("publication_mismatch")
    with tempfile.TemporaryDirectory(prefix="schema-publication-") as scratch:
        clone = Path(scratch) / "contract"
        command(["git", "clone", "--filter=blob:none", "--no-checkout", "--single-branch", "--branch", "main",
                 "https://github.com/Consiliency/consiliency-contract.git", str(clone)])
        command(["git", "merge-base", "--is-ancestor", SOURCE_COMMIT, "origin/main"], clone)
        observed_head = command(["git", "rev-parse", "origin/main"], clone).decode().strip()
        if observed_head != branch["commit"]["sha"]:
            raise ValueError("publication_mismatch")
        upstream, blobs = {}, {}
        for name in PUBLICATION_PINS:
            ref = SOURCE_COMMIT + ":core/supervised-run/" + name
            upstream[name] = command(["git", "show", ref], clone)
            blobs[name] = command(["git", "rev-parse", ref], clone).decode().strip()
        compare_publication(upstream, blobs, bundle)
    result = {
        "source_commit": SOURCE_COMMIT, "protected": branch["protected"],
        "default_branch": "main", "default_branch_head": observed_head,
        "input_artifact_sha256": INPUT_ARTIFACT_SHA256,
        "resources": {n: {"sha256": sha256(b).hexdigest(), "blob": blobs[n]} for n, b in upstream.items()},
        "hosted_run_id": os.environ["GITHUB_RUN_ID"], "hosted_job": os.environ["GITHUB_JOB"],
        "hosted_head": os.environ.get("SCHEMA_HEAD_SHA", os.environ["GITHUB_SHA"]), "outcome": "passed",
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
