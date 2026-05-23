import json
import tempfile
import unittest
from pathlib import Path

from phase_loop_runtime.provenance import event_provenance, phase_sha256, roadmap_sha256
from phase_loop_runtime.reconcile import _event_dedup_key, reconcile
from phase_loop_test_utils import make_repo, utc_now, write_phase_plan


class PhaseLoopLedgerDedupTest(unittest.TestCase):
    def test_identical_invalid_events_warn_once_and_record_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            timestamp = utc_now()
            event = _raw_event(repo, roadmap, "contract", "run", "plan_skipped", timestamp)
            _append_raw_event(repo, event)
            _append_raw_event(repo, {**event, "phase": "CONTRACT"})

            snapshot = reconcile(repo, roadmap)

            self.assertEqual(len(snapshot.ledger_warnings), 1)
            self.assertEqual(snapshot.ledger_warnings[0]["reason"], "not_in_allowed_status_set")
            self.assertEqual(len(snapshot.ledger_duplicates_skipped), 1)
            duplicate = snapshot.ledger_duplicates_skipped[0]
            self.assertEqual(duplicate["phase"], "CONTRACT")
            self.assertEqual(duplicate["duplicate_key"]["status"], "plan_skipped")

    def test_first_event_wins_and_duplicate_does_not_update_closeout(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            write_phase_plan(repo, "CONTRACT", roadmap)
            timestamp = utc_now()
            first = _raw_event(repo, roadmap, "CONTRACT", "execute", "complete", timestamp)
            first["metadata"] = {"closeout": {"closeout_commit": "firstcommit", "closeout_action": "commit"}}
            duplicate = dict(first)
            duplicate["metadata"] = {"closeout": {"closeout_commit": "secondcommit", "closeout_action": "commit"}}
            _append_raw_event(repo, first)
            _append_raw_event(repo, duplicate)

            snapshot = reconcile(repo, roadmap)

            self.assertEqual(snapshot.phases["CONTRACT"], "complete")
            self.assertEqual(snapshot.closeout_summary["closeout_commit"], "firstcommit")
            self.assertEqual(len(snapshot.ledger_duplicates_skipped), 1)

    def test_timestamp_different_events_are_not_dedupped(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            _append_raw_event(repo, _raw_event(repo, roadmap, "CONTRACT", "run", "plan_skipped", "2026-05-23T00:00:00Z"))
            _append_raw_event(repo, _raw_event(repo, roadmap, "CONTRACT", "run", "plan_skipped", "2026-05-23T00:00:01Z"))

            snapshot = reconcile(repo, roadmap)

            self.assertEqual(len(snapshot.ledger_warnings), 2)
            self.assertEqual(snapshot.ledger_duplicates_skipped, ())

    def test_different_identity_fields_are_not_dedupped(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            events = (
                _raw_event(repo, roadmap, "CONTRACT", "run", "plan_skipped", "2026-05-23T00:00:00Z"),
                _raw_event(repo, roadmap, "RUNNER", "run", "plan_skipped", "2026-05-23T00:00:00Z"),
                _raw_event(repo, roadmap, "CONTRACT", "plan", "plan_skipped", "2026-05-23T00:00:00Z"),
                _raw_event(repo, roadmap, "CONTRACT", "run", "dry_run", "2026-05-23T00:00:00Z"),
                _raw_event(
                    repo,
                    roadmap,
                    "CONTRACT",
                    "run",
                    "plan_skipped",
                    "2026-05-23T00:00:00Z",
                    automation_status="blocked",
                ),
                _raw_event(
                    repo,
                    roadmap,
                    "CONTRACT",
                    "run",
                    "plan_skipped",
                    "2026-05-23T00:00:00Z",
                    blocker_class="dirty_worktree_conflict",
                ),
            )
            for event in events:
                _append_raw_event(repo, event)

            snapshot = reconcile(repo, roadmap)

            self.assertEqual(len(snapshot.ledger_warnings), 6)
            self.assertEqual(snapshot.ledger_duplicates_skipped, ())

    def test_duplicate_key_reads_nested_automation_status_and_blocker_class(self):
        event = {
            "timestamp": "2026-05-23T00:00:00Z",
            "phase": "contract",
            "action": "execute",
            "status": "blocked",
            "metadata": {
                "child_automation": {
                    "automation_status": "blocked",
                    "automation_blocker_class": "dirty_worktree_conflict",
                }
            },
        }

        self.assertEqual(
            _event_dedup_key(event),
            (
                "2026-05-23T00:00:00Z",
                "CONTRACT",
                "execute",
                "blocked",
                "blocked",
                "dirty_worktree_conflict",
            ),
        )


def _raw_event(
    repo: Path,
    roadmap: Path,
    phase: str,
    action: str,
    status: str,
    timestamp: str,
    *,
    automation_status: str | None = None,
    blocker_class: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "timestamp": timestamp,
        "repo": str(repo),
        "roadmap": str(roadmap),
        "phase": phase,
        "action": action,
        "status": status,
        "source": "fixture",
        "schema_version": 2,
        "roadmap_sha256": roadmap_sha256(roadmap),
        "phase_sha256": phase_sha256(roadmap, phase.upper()),
    }
    if automation_status:
        payload["metadata"] = {"child_automation": {"automation_status": automation_status}}
    if blocker_class:
        payload["blocker"] = {
            "human_required": False,
            "blocker_class": blocker_class,
            "blocker_summary": "fixture blocker",
            "required_human_inputs": (),
        }
    return payload


def _append_raw_event(repo: Path, payload: dict[str, object]) -> None:
    path = repo / ".phase-loop" / "events.jsonl"
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
