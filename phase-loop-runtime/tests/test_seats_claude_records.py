"""SEATS CLAUDE lane A (records): the OD-3a amendment, §4b of the print-route record
(EC-CLAUDE-8; OD-3a).

The parser below reads the record as an auditor would. Every control is a disposable copy of
the record, edited one way, entered through the same parser, and each must fail: a
responsibility under two owners, a missing condition row, an edited earlier section.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from phase_loop_runtime import claude_seat_transport as ct

REPO = Path(__file__).resolve().parents[2]
RECORD = REPO / ct.DECISION_RECORD
V11 = REPO / "specs/phase-plans-v11.md"
#: The record as the SEATS roadmap pins it (External Inputs): every byte before §4b.
PINNED_RECORD_SHA256 = "14d424ad85fe97dcbaabc5df1f8d8beffc12a8eefdd2678694da19612fe59381"
#: The OD-3a heading and the responsibilities EC-CLAUDE-8 names, each with its one owner.
AMENDMENT = "4b"
RESPONSIBILITIES = {
    "The jailed transport seam": "SEATS CLAUDE",
    "Jailed-seat live qualification": "SEATS CLAUDENET",
    "Jailed-default promotion": "SEATS CLAUDE",
    "The mechanical module extraction of `panel_invoker.py`": "v11 PANELSPLIT",
}
STAGE3_CONDITIONS = ("Executable identity", "Subscription provenance", "Process environment",
                     "In-band evidence", "Capabilities", "Lifecycle", "Evidence limits")
DISPOSITIONS = ("applies", "replaced by a named jail control", "waived")
V11_NOTE_MARKER = "SEATS CLAUDE OD-3a consumption note"


class RecordError(ValueError):
    pass


def _table(body: str, header: str) -> list[list[str]]:
    lines = body.splitlines()
    for at, line in enumerate(lines):
        if line.strip().startswith(f"| {header} |"):
            rows = []
            for row in lines[at + 2:]:
                row = row.strip()
                if not row.startswith("|"):
                    break
                rows.append([cell.strip() for cell in row.strip("|").split("|")])
            return rows
    raise RecordError(f"no table headed {header!r}")


def parse_amendment(raw: bytes) -> dict:
    """The OD-3a amendment's auditable content, or :class:`RecordError`."""
    if b"## 4b. OD-3a" not in raw:
        raise RecordError("no OD-3a section")
    prefix = raw[:raw.index(b"## 4b. OD-3a")]
    if hashlib.sha256(prefix).hexdigest() != PINNED_RECORD_SHA256:
        raise RecordError("an earlier section was edited")
    body = (ct.section_bytes(raw, AMENDMENT) or b"").decode("utf-8")
    owners: dict[str, list[str]] = {}
    for responsibility, owner in _table(body, "Responsibility"):
        owners.setdefault(responsibility, []).append(owner)
    for responsibility, listed in owners.items():
        if len(listed) != 1:
            raise RecordError(f"{responsibility!r} has {len(listed)} owners")
    conditions: dict[str, str] = {}
    for condition, disposition in _table(body, "Condition"):
        match = re.fullmatch(r"([1-7])\. (.+)", condition)
        if match is None:
            raise RecordError(f"unnumbered condition row {condition!r}")
        if match.group(2) in conditions:
            raise RecordError(f"condition {match.group(2)!r} has two rows")
        if not any(disposition.startswith(d) for d in DISPOSITIONS):
            raise RecordError(f"condition {match.group(2)!r} has no disposition")
        if disposition.startswith("waived") and "reason" not in disposition.lower():
            raise RecordError(f"condition {match.group(2)!r} is waived without a reason")
        conditions[match.group(2)] = disposition
    return {"owners": {k: v[0] for k, v in owners.items()}, "conditions": conditions,
            "body": body}


def check_amendment(raw: bytes) -> dict:
    parsed = parse_amendment(raw)
    if parsed["owners"] != RESPONSIBILITIES:
        raise RecordError("EC-CLAUDE-8: a responsibility is missing, extra or misassigned")
    missing = [c for c in STAGE3_CONDITIONS if c not in parsed["conditions"]]
    if missing:
        raise RecordError(f"missing condition row(s): {missing}")
    return parsed


# --------------------------------------------------------------------------------------
# The shipped record.
# --------------------------------------------------------------------------------------

def test_the_amendment_gives_each_responsibility_exactly_one_owner():
    parsed = check_amendment(RECORD.read_bytes())
    assert parsed["owners"] == RESPONSIBILITIES


def test_the_amendment_has_one_row_per_stage3_condition():
    parsed = check_amendment(RECORD.read_bytes())
    assert list(parsed["conditions"]) == list(STAGE3_CONDITIONS)
    rows = parsed["conditions"]
    for applies in ("Executable identity", "In-band evidence", "Evidence limits"):
        assert rows[applies].startswith("applies")
    assert rows["Subscription provenance"].startswith("applies") and "IF-0-CLAUDE-4" in rows[
        "Subscription provenance"] and "Pro/Max" in rows["Subscription provenance"]
    for replaced in ("Process environment", "Capabilities", "Lifecycle"):
        assert rows[replaced].startswith("replaced by a named jail control")
    assert "setting_sources=[]" in rows["Process environment"]
    assert "allowed_tools" in rows["Capabilities"] and "runner-CLI oracle" in rows["Capabilities"]


def test_no_earlier_section_is_edited():
    raw = RECORD.read_bytes()
    prefix = raw[:raw.index(b"## 4b. OD-3a")]
    assert hashlib.sha256(prefix).hexdigest() == PINNED_RECORD_SHA256
    sections = ct.record_sections(raw)
    assert sections["4a"][1] == "7af0fb700ef10d444a904b01169c8b08aa056ba25ca496c7adcca7c646852cdb"


@pytest.mark.parametrize("required", [
    "EC-REVIEWTRUTH-18", "Stage 3 §4", "seat-token pipe", "EC-CLAUDE-4", "§4a item 9",
    "EC-REVIEWTRUTH-15", "operator selection only", "open egress", "CLAUDENET", "GL-6",
    "OQ-8", "experimental and unqualified", "row window",
])
def test_the_amendment_covers_what_od3a_lists(required):
    assert required in " ".join(check_amendment(RECORD.read_bytes())["body"].split())


def test_the_amendment_is_a_candidate_until_its_own_merge():
    body = check_amendment(RECORD.read_bytes())["body"]
    assert "**Status:** CANDIDATE" in body and "its own reviewed PR" in body


def test_the_v11_note_once_landed_carries_the_consumption():
    """Only after G1: then specs/phase-plans-v11.md carries the note, citing the EC IDs."""
    text = V11.read_text(encoding="utf-8")
    if V11_NOTE_MARKER not in text:
        # The note lands after G1, so before it the amendment is still a candidate.
        assert "**Status:** CANDIDATE" in check_amendment(RECORD.read_bytes())["body"]
        return
    note = text[text.index(V11_NOTE_MARKER):][:4000]
    for required in ("EC-PANEL-6", "EC-CLAUDE-1", "EC-CLAUDE-4", "EC-CLAUDE-6",
                     "EC-CLAUDENET-1", "EC-REVIEWTRUTH-15"):
        assert required in note


# --------------------------------------------------------------------------------------
# Path-entered controls on disposable copies: each must fail.
# --------------------------------------------------------------------------------------

def _copy(tmp_path: Path, edit) -> bytes:
    path = tmp_path / "record.md"
    path.write_bytes(edit(RECORD.read_text(encoding="utf-8")).encode("utf-8"))
    return path.read_bytes()


@pytest.mark.parametrize("name, edit", [
    ("two-owners", lambda t: t.replace(
        "| Jailed-default promotion | SEATS CLAUDE |",
        "| Jailed-default promotion | SEATS CLAUDE |\n    | Jailed-default promotion | v11 PANEL |")),
    ("misassigned", lambda t: t.replace("| Jailed-seat live qualification | SEATS CLAUDENET |",
                                        "| Jailed-seat live qualification | v11 PANEL |")),
    ("no-owner", lambda t: t.replace("    | The jailed transport seam | SEATS CLAUDE |\n", "")),
    ("missing-condition", lambda t: re.sub(r"    \| 6\. Lifecycle \|[^\n]*\n", "", t)),
    ("duplicate-condition", lambda t: t.replace(
        "    | 7. Evidence limits | applies |",
        "    | 7. Evidence limits | applies |\n    | 7. Evidence limits | applies |")),
    ("waived-without-reason", lambda t: t.replace("| 7. Evidence limits | applies |",
                                                  "| 7. Evidence limits | waived |")),
    ("edited-earlier-section", lambda t: t.replace("Live smoke through the runtime on dev0",
                                                   "Live smoke through the runtime")),
    ("edited-4a", lambda t: t.replace("Opt-in neither", "Opt-in never")),
    ("no-amendment", lambda t: t[:t.index("## 4b. OD-3a")]),
])
def test_an_edited_copy_fails_the_records_parser(tmp_path, name, edit):
    raw = _copy(tmp_path, edit)
    assert raw != RECORD.read_bytes(), name
    with pytest.raises(RecordError):
        check_amendment(raw)
