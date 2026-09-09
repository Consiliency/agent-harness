#!/usr/bin/env python3
"""Probe whether the ``phase_loop_runtime`` this interpreter imports is v3-aware.

Lane D5 of ``plans/detailed-789d-fabpub-partition-rotation-20260908.md`` requires
every installed runtime on a host that can write FABPUB state to recognise
``LegacyRepositoryPartitionReceipt.v3`` before the omniagent-plus partition is
rotated.  The version string cannot prove that: the v3 receipt landed on
``main`` after the ``0.7.14`` release, so a PyPI ``0.7.14`` and a
``git+…@<main sha>`` pin report the same version.  This probe imports the
runtime and checks the symbols the ceremony and the successor resolver need.

Run it with the interpreter whose runtime you are asking about::

    <venv>/bin/python fabpub_v3_probe.py [--json]
    uv tool run --from phase-loop-runtime python fabpub_v3_probe.py   # the uv tool

Exit 0 when v3-aware, 2 when not, 3 when the runtime does not import.
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import sys

V3_SCHEMA = "LegacyRepositoryPartitionReceipt.v3"
REQUIRED_SYMBOLS = (
    "RotatedPartitionReceipt",
    "rotate_blocked_partition",
    "PartitionRotationRefused",
    "active_store_root",
)


def probe() -> dict:
    report: dict = {
        "schema": "FabpubV3Probe.v1",
        "python": sys.executable,
        "version": None,
        "install_source": None,
        "module": None,
        "missing_symbols": [],
        "v3_schema": None,
        "cli_verb": False,
        "v3_aware": False,
    }
    try:
        report["version"] = metadata.version("phase-loop-runtime")
        direct = metadata.distribution("phase-loop-runtime").read_text(
            "direct_url.json"
        )
        report["install_source"] = (
            json.loads(direct) if direct else "index (no direct_url.json)"
        )
    except metadata.PackageNotFoundError:
        report["install_source"] = "not installed as a distribution"
    # ``cli`` first: importing the broker before the package's closeout
    # modules trips a circular-import warning that is noise for this probe.
    try:
        from phase_loop_runtime import cli

        report["cli_verb"] = hasattr(cli, "_fabpub_rotate_partition_command")
    except Exception as error:  # noqa: BLE001 - the probe reports, never raises
        report["cli_import_error"] = f"{type(error).__name__}: {error}"
    try:
        from phase_loop_runtime.convergence.broker import live
    except Exception as error:  # noqa: BLE001
        report["import_error"] = f"{type(error).__name__}: {error}"
        return report
    report["module"] = live.__file__
    report["missing_symbols"] = [
        name for name in REQUIRED_SYMBOLS if not hasattr(live, name)
    ]
    receipt_class = getattr(live, "RotatedPartitionReceipt", None)
    report["v3_schema"] = getattr(receipt_class, "SCHEMA", None)
    report["v3_aware"] = (
        not report["missing_symbols"]
        and report["v3_schema"] == V3_SCHEMA
        and report["cli_verb"]
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--json", action="store_true", help="print the full report as JSON"
    )
    args = parser.parse_args(argv)
    report = probe()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        state = "v3-aware" if report["v3_aware"] else "NOT v3-aware"
        print(
            f"phase-loop-runtime {report['version']} at {report['module'] or '<no import>'}: {state}"
            f" (schema={report['v3_schema']!r}, missing={report['missing_symbols']},"
            f" cli_verb={report['cli_verb']})"
        )
        for key in ("import_error", "cli_import_error"):
            if key in report:
                print(f"  {key}: {report[key]}")
    if "import_error" in report:
        return 3
    return 0 if report["v3_aware"] else 2


if __name__ == "__main__":
    sys.exit(main())
