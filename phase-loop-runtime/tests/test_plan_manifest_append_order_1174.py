"""plans/manifest.json writers must not rewrite rows they did not change (agent-harness#1174).

The manifest is append-only history. On main its rows are neither in slug order nor
key-sorted within a row, so any writer that re-sorts the ``plans`` array, or that
re-serializes untouched rows through the typed model with ``sort_keys``, rewrites
thousands of lines to add one entry. The fixture below is built to catch both.
"""

import dataclasses
import json
from pathlib import Path

from phase_loop_runtime import plan_manifest as pm


TIMESTAMP = "2026-09-29T00:00:00Z"


def _row(slug: str, status: str = "committed") -> dict:
    return {
        "acceptance_criteria_count": 1,
        "created_at": TIMESTAMP,
        "file": f"plans/{slug}.md",
        "handoff_ref": None,
        "if_gates_produced": [],
        "lanes": [],
        "lifecycle": [],
        "owner_skill": "claude-plan-detailed",
        "phase_alias": None,
        "reflection_ref": None,
        "roadmap_ref": None,
        "slug": slug,
        "status": status,
        "task_summary": f"plan {slug}",
        "type": "detailed",
        "updated_at": TIMESTAMP,
    }


def _seed(repo: Path) -> bytes:
    # Rows out of slug order, and one row whose keys are out of alphabetical order
    # with an extension key and a non-ASCII value -- the shapes main actually has.
    unsorted_keys = _row("mm-unsorted-keys")
    lifecycle = unsorted_keys.pop("lifecycle")
    unsorted_keys["plan_authority_history"] = [{"decision": "maintainer — option (a)", "at": TIMESTAMP}]
    unsorted_keys["lifecycle"] = lifecycle
    document = {"plans": [_row("zz-first"), unsorted_keys, _row("aa-last")], "schema_version": pm.SCHEMA_VERSION}
    for row in document["plans"]:
        (repo / row["file"]).parent.mkdir(parents=True, exist_ok=True)
        (repo / row["file"]).write_text("# plan\n", encoding="utf-8")
    text = json.dumps(document, indent=2) + "\n"
    (repo / "plans/manifest.json").write_text(text, encoding="utf-8")
    return text.encode("utf-8")


def _prior_rows_prefix(before: bytes) -> bytes:
    # Everything up to (not including) the newline that closes the last prior row.
    return before[: before.rindex(b"\n    }\n  ]")] + b"\n    }"


def _entry(slug: str) -> pm.DotfilesPlanEntry:
    return pm.DotfilesPlanEntry(
        slug=slug,
        file=f"plans/{slug}.md",
        type="detailed",
        status="committed",
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
        owner_skill="claude-plan-detailed",
        task_summary=f"plan {slug}",
        acceptance_criteria_count=1,
    )


def test_append_entry_preserves_prior_rows_byte_for_byte(tmp_path):
    before = _seed(tmp_path)
    (tmp_path / "plans/bb-new.md").write_text("# plan\n", encoding="utf-8")

    pm.append_entry(tmp_path, _entry("bb-new"))

    after = (tmp_path / "plans/manifest.json").read_bytes()
    assert after.startswith(_prior_rows_prefix(before))
    slugs = [row["slug"] for row in json.loads(after)["plans"]]
    assert slugs == ["zz-first", "mm-unsorted-keys", "aa-last", "bb-new"]
    assert pm.validate_manifest(tmp_path / "plans/manifest.json").valid


def test_append_entry_replaces_an_existing_slug_in_place(tmp_path):
    before = _seed(tmp_path)
    replacement = dataclasses.replace(_entry("aa-last"), status="executing")

    pm.append_entry(tmp_path, replacement)

    after = (tmp_path / "plans/manifest.json").read_bytes()
    rows = json.loads(after)["plans"]
    assert [row["slug"] for row in rows] == ["zz-first", "mm-unsorted-keys", "aa-last"]
    assert rows[2]["status"] == "executing"
    # The rows before the replaced one are untouched.
    untouched = before[: before.index(b'"slug": "aa-last"')]
    untouched = untouched[: untouched.rindex(b"\n    {")]
    assert after.startswith(untouched)


def test_append_entry_to_a_missing_manifest_writes_sorted_keys(tmp_path):
    pm.append_entry(tmp_path, _entry("only"))
    data = json.loads((tmp_path / "plans/manifest.json").read_text(encoding="utf-8"))
    assert list(data) == ["plans", "schema_version"]
    assert list(data["plans"][0]) == sorted(data["plans"][0])


def test_update_lifecycle_touches_only_the_updated_row(tmp_path):
    before = _seed(tmp_path)

    pm.update_lifecycle(tmp_path, "aa-last", "executing", "claude-execute-detailed", {"run_id": "r1"})

    after = (tmp_path / "plans/manifest.json").read_bytes()
    untouched = before[: before.index(b'"slug": "aa-last"')]
    untouched = untouched[: untouched.rindex(b"\n    {")]
    assert after.startswith(untouched)
    rows = json.loads(after)["plans"]
    assert [row["slug"] for row in rows] == ["zz-first", "mm-unsorted-keys", "aa-last"]
    assert rows[2]["status"] == "executing"
    assert [event["transition"] for event in rows[2]["lifecycle"]] == ["executing"]
    assert pm.validate_manifest(tmp_path / "plans/manifest.json").valid


def test_update_lifecycle_keeps_the_updated_rows_key_order(tmp_path):
    _seed(tmp_path)

    pm.update_lifecycle(tmp_path, "mm-unsorted-keys", "executing", "claude-execute-detailed", {"run_id": "r1"})

    row = json.loads((tmp_path / "plans/manifest.json").read_text(encoding="utf-8"))["plans"][1]
    assert list(row)[-2:] == ["plan_authority_history", "lifecycle"]
    assert row["plan_authority_history"][0]["decision"] == "maintainer — option (a)"


def test_rewriting_an_unchanged_manifest_is_a_byte_noop(tmp_path):
    before = _seed(tmp_path)
    pm.append_entry(tmp_path, pm.read_manifest(tmp_path).plans[0])
    assert (tmp_path / "plans/manifest.json").read_bytes() == before
