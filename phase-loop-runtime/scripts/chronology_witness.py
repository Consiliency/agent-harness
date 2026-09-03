"""Witness the CONFORM chronology node's fate in a pytest junit file.

Every consumer that deselects (or retains) the chronology node proves the
decision against the junit it produced, through this one script, so that:

* ``--expect present`` holds only when the node RAN and passed -- a row that
  carries ``<skipped>``, ``<failure>`` or ``<error>`` is not a proof that the
  chronology property was evaluated;
* ``--expect absent`` holds only when no row names the node at all -- a
  deselect that silently matched nothing (node renamed or moved) shows up as
  ``present`` here, not never;
* the row is bound by module AND function name, so a same-named test in
  another module, or a parametrized variant, cannot stand in for the node.

Exit 0 when the junit witnesses the expectation, 1 otherwise, 2 on bad input.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_OUTCOME_TAGS = ("skipped", "failure", "error")


# The classname roots pytest emits for the node, by rootdir: the package
# directory (``tests.<module>``) or the repository root
# (``phase-loop-runtime.tests.<module>``). Any other root is a different module,
# so a same-named test elsewhere cannot stand in for the node.
_CLASSNAME_ROOTS = ("", "phase-loop-runtime.")


def _same_module(classname: str, module_dotted: str) -> bool:
    """Bind by whole dotted components under a known root: ``notests.x`` and ``shadow.tests.x`` are not ``tests.x``."""
    return any(classname == root + module_dotted for root in _CLASSNAME_ROOTS)


def classify(junit_path: Path, node: str) -> str:
    """Return ``present``, ``absent``, or ``<tag>`` for a row that did not pass."""
    module_path, _, name = node.rpartition("::")
    if not module_path or not name:
        raise ValueError(f"node id must look like path/to/test_mod.py::test_name, got {node!r}")
    module = module_path[:-3] if module_path.endswith(".py") else module_path
    module_dotted = module.replace("/", ".")
    root = ET.parse(junit_path).getroot()
    rows = [
        case
        for case in root.iter("testcase")
        if case.get("name") == name
        and _same_module(case.get("classname") or "", module_dotted)
    ]
    if not rows:
        return "absent"
    outcomes = sorted({tag for case in rows for tag in _OUTCOME_TAGS if case.find(tag) is not None})
    if outcomes:
        return "+".join(outcomes)
    return "present"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--node", required=True, help="pytest node id, e.g. tests/test_x.py::test_y")
    parser.add_argument("--expect", required=True, choices=("present", "absent"))
    args = parser.parse_args(argv)
    if not args.junit.is_file():
        print(f"chronology witness: junit {args.junit} does not exist", file=sys.stderr)
        return 2
    try:
        found = classify(args.junit, args.node)
    except (ValueError, ET.ParseError) as exc:
        print(f"chronology witness: {exc}", file=sys.stderr)
        return 2
    if found != args.expect:
        print(
            f"chronology witness: expected the node {args.expect} in {args.junit}, found it {found}",
            file=sys.stderr,
        )
        return 1
    print(f"chronology witness: node {args.expect} in {args.junit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
