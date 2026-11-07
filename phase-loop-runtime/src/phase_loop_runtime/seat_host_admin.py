"""Print-only administrator checklist renderer for TEAMHOST seat prerequisites."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence


ACTIONS: Mapping[str, str] = {
    "LA1-SUBID": (
        "Configure non-overlapping subordinate uid and gid ranges for every operator account."
    ),
    "LA1-TIOCSTI": "Set dev.tty.legacy_tiocsti to 0 and persist the sysctl.",
    "LA1-APPARMOR": (
        "Apply the Ubuntu user-namespace/setpriv override printed by "
        "python3 -m phase_loop_runtime.seat_jail_apparmor."
    ),
    "LA1-USERNS": (
        "Set kernel.unprivileged_userns_clone to 1 on hosts that expose that sysctl."
    ),
    "LA1-PACKAGES": (
        "Install bwrap, setpriv, nsenter, newuidmap, newgidmap, slirp4netns and iptables."
    ),
    "LA1-MACHINE-ID": "Provision a stable, readable /etc/machine-id.",
    "LA1-RELEASE": (
        "Install a managed release that carries every declared seat dependency."
    ),
    "LA1-AUTHORITY-PIN": (
        "Write the root-owned seat-authority pin with one entry per release and leg."
    ),
}

_CODE_ITEMS = {
    "authority_missing": "LA1-AUTHORITY-PIN",
    "authority_invalid": "LA1-AUTHORITY-PIN",
}


def _items(report: object) -> tuple[str, ...]:
    if not isinstance(report, dict):
        raise ValueError("doctor JSON must be an object")
    selected: set[str] = set()
    rows = report.get("seat_jail_prerequisites", [])
    if not isinstance(rows, list):
        raise ValueError("seat_jail_prerequisites must be an array")
    for row in rows:
        if isinstance(row, dict) and row.get("status") == "missing":
            checklist = row.get("checklist")
            if checklist in ACTIONS:
                selected.add(checklist)
    qualifications = report.get("seat_cli_qualification", [])
    if isinstance(qualifications, list):
        for row in qualifications:
            if isinstance(row, dict) and row.get("status") == "refuses":
                checklist = _CODE_ITEMS.get(row.get("code"))
                if checklist is not None:
                    selected.add(checklist)
    return tuple(item for item in ACTIONS if item in selected)


def _read(source: str) -> object:
    if source == "-":
        return json.load(sys.stdin)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("doctor_json", nargs="?")
    parser.add_argument("--all", action="store_true", dest="show_all")
    args = parser.parse_args(argv)
    if args.show_all and args.doctor_json is not None:
        parser.error("--all does not take a doctor JSON file")
    items = tuple(ACTIONS) if args.show_all or args.doctor_json is None else _items(
        _read(args.doctor_json)
    )
    for item in items:
        print(f"{item}: {ACTIONS[item]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
