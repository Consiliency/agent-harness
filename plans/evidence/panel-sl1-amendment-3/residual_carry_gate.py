"""SL-3.3 verify command: the PANEL-RESIDUAL-SL1B closeout gate (plan amendment #3).

Standard library only; it imports nothing from the repository, so it runs on any
checkout.

Inputs
  RESIDUAL  phase-loop-runtime/tests/data/panel_residual_sl1b.json, written by
            SL-1 and only ever shrunk by SL-1b (agent-harness#1168):
              {"schema": "panel_residual_sl1b.v1",
               "sites": [{"path": str, "function": str, "finding": str}, ...]}
  MANIFEST  plans/manifest.json; the v10-PANEL row's optional
            ``panel_residual_carry``.

Exit 0 when the residual file exists and lists no sites, or when it lists sites
and the carry record is valid AND ratifies exactly that site set. Exit 1 in
every other case, including a missing or malformed residual file.

A valid carry record has exactly these keys, with exact types:
  issue        "agent-harness#1168"
  ratified     true (bool)
  ratified_by  a GitHub login
  date         "YYYY-MM-DD", a real date
  evidence     {"kind": "issue_comment", "issue": 1168, "comment_id": <int > 0>}
               -- the gate builds the comment URL itself
  sites        the residual's site objects; as a set, equal to the file's
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys

RESIDUAL_PATH = "phase-loop-runtime/tests/data/panel_residual_sl1b.json"
RESIDUAL_SCHEMA = "panel_residual_sl1b.v1"
RESIDUAL_KEYS = frozenset({"schema", "sites"})
SITE_KEYS = frozenset({"path", "function", "finding"})
CARRY_ISSUE = "agent-harness#1168"
CARRY_ISSUE_NUMBER = 1168
CARRY_KEYS = frozenset(
    {"issue", "ratified", "ratified_by", "date", "evidence", "sites"}
)
EVIDENCE_KEYS = frozenset({"kind", "issue", "comment_id"})
EVIDENCE_URL = "https://github.com/Consiliency/agent-harness/issues/{issue}#issuecomment-{comment_id}"
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _is_int(value: object) -> bool:
    return type(value) is int


def _is_text(value: object) -> bool:
    return (
        type(value) is str
        and value != ""
        and value == value.strip()
        and value.isprintable()
    )


def parse_sites(value: object, where: str) -> tuple[frozenset | None, list[str]]:
    """Return the site set, or None with the problems found."""
    if type(value) is not list:
        return None, [f"{where} must be a list, got {type(value).__name__}"]
    problems, keys = [], []
    for i, site in enumerate(value):
        if type(site) is not dict or set(site) != SITE_KEYS:
            problems.append(
                f"{where}[{i}] must be an object with exactly {sorted(SITE_KEYS)}"
            )
            continue
        if not all(_is_text(site[k]) for k in SITE_KEYS):
            problems.append(f"{where}[{i}] fields must be non-empty printable strings")
            continue
        keys.append((site["path"], site["function"], site["finding"]))
    if len(set(keys)) != len(keys):
        problems.append(f"{where} lists a site more than once")
    return (None, problems) if problems else (frozenset(keys), [])


def load_residual(path: str) -> tuple[frozenset | None, list[str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError:
        return None, [
            f"residual file {path} is absent (SL-1 writes it; SL-1b empties it, never deletes it)"
        ]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [f"residual file {path} is unreadable: {exc}"]
    if type(payload) is not dict or set(payload) != RESIDUAL_KEYS:
        return None, [
            f"residual file must be an object with exactly {sorted(RESIDUAL_KEYS)}"
        ]
    if payload["schema"] != RESIDUAL_SCHEMA:
        return None, [f"residual schema must be {RESIDUAL_SCHEMA!r}"]
    return parse_sites(payload["sites"], "residual sites")


def carry_problems(carry: object, residual: frozenset) -> list[str]:
    if carry is None:
        return ["panel_residual_carry is absent"]
    if type(carry) is not dict:
        return [f"panel_residual_carry must be an object, got {type(carry).__name__}"]
    if set(carry) != CARRY_KEYS:
        missing, extra = (
            sorted(CARRY_KEYS - set(carry)),
            sorted(set(carry) - CARRY_KEYS),
        )
        return [
            f"carry keys must be exactly {sorted(CARRY_KEYS)} (missing {missing}, extra {extra})"
        ]
    problems = []
    if type(carry["issue"]) is not str or carry["issue"] != CARRY_ISSUE:
        problems.append(f"issue must be {CARRY_ISSUE!r}, got {carry['issue']!r}")
    if carry["ratified"] is not True:
        problems.append(f"ratified must be true, got {carry['ratified']!r}")
    by = carry["ratified_by"]
    if type(by) is not str or LOGIN_RE.fullmatch(by) is None:
        problems.append(f"ratified_by must be a GitHub login, got {by!r}")
    date = carry["date"]
    try:
        if type(date) is not str or DATE_RE.fullmatch(date) is None:
            raise ValueError
        datetime.date.fromisoformat(date)
    except ValueError:
        problems.append(f"date must be a real YYYY-MM-DD date, got {date!r}")
    ev = carry["evidence"]
    if (
        type(ev) is not dict
        or set(ev) != EVIDENCE_KEYS
        or type(ev["kind"]) is not str
        or ev["kind"] != "issue_comment"
        or not _is_int(ev["issue"])
        or ev["issue"] != CARRY_ISSUE_NUMBER
        or not _is_int(ev["comment_id"])
        or ev["comment_id"] <= 0
    ):
        problems.append(
            "evidence must be exactly "
            f'{{"kind": "issue_comment", "issue": {CARRY_ISSUE_NUMBER}, "comment_id": <int > 0>}}, '
            f"got {ev!r}"
        )
    sites, site_problems = parse_sites(carry["sites"], "carry sites")
    problems.extend(site_problems)
    if sites is not None and sites != residual:
        problems.append(
            "carry sites must equal the live residual "
            f"(unratified {sorted(residual - sites)}, no longer present {sorted(sites - residual)})"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="plans/manifest.json")
    ap.add_argument("--residual", default=RESIDUAL_PATH)
    args = ap.parse_args(argv)
    residual, problems = load_residual(args.residual)
    if residual is None:
        print("PANEL-RESIDUAL-SL1B: fail")
        for p in problems:
            print(f"  - {p}")
        return 1
    if not residual:
        print("PANEL-RESIDUAL-SL1B empty: pass")
        return 0
    with open(args.manifest, encoding="utf-8") as fh:
        plans = json.load(fh)["plans"]
    row = next(p for p in plans if p.get("slug") == "v10-PANEL")
    problems = carry_problems(row.get("panel_residual_carry"), residual)
    if problems:
        print(
            f"PANEL-RESIDUAL-SL1B has {len(residual)} open site(s) and no valid carry:"
        )
        for p in problems:
            print(f"  - {p}")
        return 1
    ev = row["panel_residual_carry"]["evidence"]
    print(
        f"PANEL-RESIDUAL-SL1B has {len(residual)} open site(s), carried by a valid record "
        f"ratified at {EVIDENCE_URL.format(**ev)}: pass"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
