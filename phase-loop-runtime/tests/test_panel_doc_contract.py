"""PANEL SL-0 frozen corpus: EC-PANEL-7 -- documented, both ways.

Frozen byte-equal from SL-0's landing until the phase merges (``content_tdd_receipt.v1``;
see ``panel_content_tdd_adapter.py``). Every node keys on
``advisor_board.lens_frame.render_lens_section`` (slice 2, which lands with SL-3's docs):
it skips in an ordinary run while that symbol is absent and FAILS under
``PHASE_LOOP_TDD_EXPECT_PANEL=1``.

Both directions:
* a documented key the loader refuses -- every ```toml example carrying a ``[panel.*]``
  table in either doc must load through ``resolve_panel_table``;
* a key the loader accepts, or a label a result emits, that is undocumented -- the
  accepted ``[panel.*]`` keys (EC-PANEL-1/4) and every ``PanelLabels`` field (read from
  the implementation, so a new label cannot be added silently) must appear in both docs.
Plus the ``[president]`` pointer for a single-vendor user, the recovery section for an
invalid base table, the "one distinct vendor" meaning of a minimum of 1, and the
entry-doc check covering the onboarding doc that carries those sections.
"""
from __future__ import annotations

import dataclasses
import json
import re
import types
from pathlib import Path

import pytest

from panel_content_tdd_adapter import SLICE2, require_ready
from test_panel_lanes import (
    LABEL_FIELDS,
    REPLACED_LABEL,
    SEAT_LABEL_FIELDS,
    _context,
    _invoke,
    _labels,
    _names,
    _rotated_cr_table,
    _user_file,
)

from phase_loop_runtime import panel_invoker as pi

REPO = Path(__file__).resolve().parents[2]
CARD = "docs/advisor-board-capabilities-card.md"
ONBOARDING = "docs/TEAM-ONBOARDING.md"
DOCS = (CARD, ONBOARDING)
# Hardcoded on purpose: neither IF-0-PANEL-1 nor any existing symbol exposes the loader's
# accepted [panel.*] key set, so "an accepted key that is undocumented" is checked against
# the keys EC-PANEL-1/4 name (disclosed on agent-harness#1092).
ACCEPTED_KEYS = ("lanes", "lens", "vendors", "lenses", "min_distinct_vendors")
LABEL_VALUES = ("prompt", "metadata-only", REPLACED_LABEL, "built-in", "declared")
_TOML_BLOCK = re.compile(r"```toml\n(.*?)```", re.DOTALL)
_PANEL_HEADER = re.compile(r"(?m)^\[panel\.([A-Za-z0-9_-]+)\]\s*$")


def slice2() -> types.SimpleNamespace:
    require_ready(SLICE2)
    return _names()


def _doc(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _label_fields(tmp_path, monkeypatch) -> list[str]:
    """Every label field a result actually EMITS (read from a real ``invoke_board`` result, so
    a dataclass or a ``to_dict()`` ``PanelLabels`` both count), plus the frozen names."""
    s = _names()
    c = _context(
        s, tmp_path, monkeypatch, user=_rotated_cr_table(minimum=1),
        repository_profile=lambda base: s.ExplicitProfileSeats(
            seats=("grok",), path=".phase-loop/governance.toml", provenance=base),
    )
    emitted = _labels(_invoke(c.ctx, "plan").panel_labels)
    names = set(emitted)
    for seat in emitted["seats"]:
        names |= set(seat)
    assert isinstance(emitted.get("explicit_profile"), dict), "the explicit profile label was not emitted"
    for key in ("minimum_source", "table_source", "explicit_profile"):
        if isinstance(emitted.get(key), dict):
            names |= set(emitted[key])
    labels = pi.PanelLabels
    if dataclasses.is_dataclass(labels):
        names |= {f.name for f in dataclasses.fields(labels)}
    return sorted(names | set(LABEL_FIELDS) | set(SEAT_LABEL_FIELDS))


@pytest.mark.parametrize("doc", DOCS)
def test_ec7_every_documented_panel_example_loads(tmp_path, monkeypatch, doc):
    s = slice2()
    blocks = [block for block in _TOML_BLOCK.findall(_doc(doc)) if "[panel." in block]
    assert blocks, f"{doc} documents no [panel.*] lane table example"
    for index, block in enumerate(blocks):
        user = _user_file(tmp_path / f"example-{index}", monkeypatch, block)
        tasks = _PANEL_HEADER.findall(block)
        assert tasks, f"{doc} example {index} has no [panel.<task>] header"
        for task in tasks:
            try:
                s.resolve(task, user_path=user, repo_dir=None, base_revision=None)
            except s.BoardConfigError as exc:
                pytest.fail(f"{doc} example {index} documents [panel.{task}] the loader refuses: {exc}")


@pytest.mark.parametrize("doc", DOCS)
def test_ec7_every_accepted_key_is_documented(doc):
    slice2()
    text = _doc(doc)
    missing = [key for key in ACCEPTED_KEYS if f"`{key}`" not in text and f"{key} =" not in text]
    assert not missing, f"{doc} does not document accepted [panel.*] key(s) {missing}"
    assert "[panel." in text


@pytest.mark.parametrize("doc", DOCS)
def test_ec7_every_emitted_label_is_documented(tmp_path, monkeypatch, doc):
    slice2()
    text = _doc(doc)
    missing = [name for name in _label_fields(tmp_path, monkeypatch) if name not in text]
    assert not missing, f"{doc} does not document emitted label(s) {missing}"
    absent = [value for value in LABEL_VALUES if value not in text]
    assert not absent, f"{doc} does not document label value(s) {absent}"


@pytest.mark.parametrize("doc", DOCS)
def test_ec7_a_single_vendor_user_is_pointed_to_the_president_table(doc):
    slice2()
    text = _doc(doc)
    assert "[president]" in text, f"{doc} has no [president] pointer"
    assert re.search(r"single[- ]vendor", text, re.IGNORECASE), f"{doc} does not address a single-vendor user"


@pytest.mark.parametrize("doc", DOCS)
def test_ec7_a_minimum_of_one_is_documented_as_one_distinct_vendor(doc):
    slice2()
    text = _doc(doc)
    assert "min_distinct_vendors" in text
    assert re.search(r"one distinct vendor", text, re.IGNORECASE), (
        f"{doc} does not say a minimum of 1 means one distinct vendor, not one seat"
    )


def test_ec7_the_invalid_base_table_recovery_is_documented():
    slice2()
    text = _doc(ONBOARDING)
    assert REPLACED_LABEL in text
    assert re.search(r"recover", text, re.IGNORECASE), f"{ONBOARDING} has no recovery section"


def test_ec7_the_entry_doc_check_covers_the_panel_sections():
    slice2()
    from phase_loop_runtime import entry_doc_check

    uncovered = [doc for doc in DOCS if doc not in entry_doc_check.ENTRY_DOCS]
    assert not uncovered, f"not entry-doc-checked surfaces: {uncovered}"
    suppressions = json.loads((REPO / entry_doc_check.SUPPRESSIONS).read_text(encoding="utf-8"))
    for entry in suppressions.get("suppressions", []):
        if entry.get("file") in DOCS:
            token = str(entry.get("token", ""))
            assert "panel" not in token.lower() and not any(key in token for key in ACCEPTED_KEYS), (
                f"a suppression hides a PANEL section finding: {entry}"
            )
