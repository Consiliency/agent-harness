#!/usr/bin/env python3
"""Refresh source bindings after successful producer revalidation.

The operator must revalidate the receipt's named checks before invocation.
This tool preserves all outcome and authority fields, including timestamps.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re


def stamp(receipt: Path, *, repo: Path) -> None:
    text = receipt.read_text()
    blocks = list(re.finditer(r"```json\n(.*?)\n```", text, re.S))
    if len(blocks) != 1:
        raise ValueError("expected exactly one JSON receipt")
    block = blocks[0]
    record = json.loads(block.group(1))
    hashes = {}
    for relative in record["source_hashes"]:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("source path must be repository relative")
        hashes[relative] = sha256((repo / path).read_bytes()).hexdigest()
    # Exact derivation in both ENVELOPE and JOURNAL receipt validators.
    record["source_hashes"] = hashes
    record["runner_stamp"]["source_tree_digest"] = sha256(
        json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    replacement = json.dumps(record, indent=2, ensure_ascii=False)
    updated = text[:block.start(1)] + replacement + text[block.end(1):]
    if updated != text:
        receipt.write_text(updated)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    stamp(args.receipt, repo=args.repo)


if __name__ == "__main__":
    main()
