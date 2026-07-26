"""Governed, version-pinned PMCP research for advisor-board seats."""

from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.advisor_board import (
    Board,
    BoardObserver,
    CollectingSink,
    ResearchPolicy,
    ResearchLedger,
    Seat,
    claude_mcp_config,
    codex_mcp_args,
    materialize_research_run,
    mcp_tool_names,
    probe_research_capability,
    reduce_research_audit,
)
from phase_loop_runtime.advisor_board.research import ResearchUnavailable


_ACTIVATION = [
    "explicit_policy",
    "gateway_tool_filtering",
    "typed_correlations",
    "explicit_audit_jsonl",
    "unique_lock_dir",
    "terminal_completion_fsync",
]


def _probe_result(*, version: str = "1.20.0", activation: list[str] | None = None):
    payload = {
        "pmcp_version": version,
        "capabilities": [
            {
                "name": "scoped_advisor_audit.v1",
                "activation_requires": _ACTIVATION if activation is None else activation,
            }
        ],
    }
    return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")


def _audit_records(config, invocations):
    session_id = "audit-session"
    records = [
        {
            "event": "audit.started",
            "schema": "scoped_advisor_audit.v1",
            "audit_session_id": session_id,
            "policy_digest": config.policy_digest,
        }
    ]
    records.extend(invocations)
    count = len(records) + 1
    records.append(
        {
            "event": "audit.completed",
            "schema": "scoped_advisor_audit.v1",
            "audit_session_id": session_id,
            "policy_digest": config.policy_digest,
            "first_sequence": 1,
            "last_sequence": count,
            "record_count": count,
        }
    )
    for sequence, record in enumerate(records, 1):
        record["sequence"] = sequence
        record.setdefault("audit_session_id", session_id)
        record.setdefault("policy_digest", config.policy_digest)
    return records


def _write_audit(config, records) -> None:
    config.audit_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


class CapabilityContractTests(unittest.TestCase):
    def test_exact_published_capability_is_required(self) -> None:
        policy = ResearchPolicy(enabled=True)
        payload = probe_research_capability(
            policy, env={}, run=lambda *args, **kwargs: _probe_result()
        )
        self.assertEqual(payload["pmcp_version"], "1.20.0")

        with self.assertRaisesRegex(ResearchUnavailable, "pmcp_version_mismatch"):
            probe_research_capability(
                policy,
                env={},
                run=lambda *args, **kwargs: _probe_result(version="1.19.0"),
            )
        with self.assertRaisesRegex(ResearchUnavailable, "pmcp_capability_incomplete"):
            probe_research_capability(
                policy,
                env={},
                run=lambda *args, **kwargs: _probe_result(
                    activation=_ACTIVATION[:-1]
                ),
            )

    def test_policy_surface_is_fixed_to_two_research_servers(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly firecrawl and brightdata"):
            ResearchPolicy(enabled=True, servers=("firecrawl", "github"))
        with self.assertRaisesRegex(ValueError, "downstream patterns"):
            ResearchPolicy(enabled=True, tool_patterns=("*",))


class PerSeatIsolationTests(unittest.TestCase):
    def test_four_seats_get_unique_locks_and_audits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "research-run"
            run = materialize_research_run(
                ResearchPolicy(enabled=True),
                [("codex", "c"), ("claude", "a"), ("grok", "g"), ("gemini", "m")],
                root=root,
                probe_run=lambda *args, **kwargs: _probe_result(),
            )
            try:
                self.assertEqual(len({seat.lock_dir for seat in run.seats}), 4)
                self.assertEqual(len({seat.audit_path for seat in run.seats}), 4)
                self.assertTrue(all(seat.lock_dir.is_dir() for seat in run.seats))
                self.assertTrue(
                    all(seat.policy_digest == run.policy_digest for seat in run.seats)
                )
            finally:
                run.close()

    def test_client_command_builders_receive_the_isolated_profile(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run = materialize_research_run(
                ResearchPolicy(enabled=True),
                [("codex", "c")],
                root=Path(td) / "research-run",
                probe_run=lambda *args, **kwargs: _probe_result(),
            )
            try:
                seat = run.seats[0]
                claude_command = pi._claude_tui_command(
                    Path(td) / "review", Path(td), research_seat=seat
                )
                self.assertIn("--strict-mcp-config", claude_command)
                self.assertNotIn("--safe-mode", claude_command)
                self.assertIn("--no-chrome", claude_command)
                add_dirs = [
                    claude_command[index + 1]
                    for index, value in enumerate(claude_command)
                    if value == "--add-dir"
                ]
                self.assertEqual(add_dirs, [str(Path(td) / "review")])
                self.assertNotIn(str(Path(td)), add_dirs)
                self.assertEqual(
                    tuple(
                        json.loads(
                            claude_command[claude_command.index("--mcp-config") + 1]
                        )["mcpServers"]
                    ),
                    ("pmcp_advisor",),
                )
                tools = claude_command[claude_command.index("--tools") + 1]
                allowed = claude_command[
                    claude_command.index("--allowedTools") + 1
                ]
                self.assertEqual(tools, allowed)
                for tool_name in mcp_tool_names():
                    self.assertIn(tool_name, allowed.split(","))

                review = Path(td) / "codex-review"
                output = Path(td) / "codex-output"
                review.mkdir()
                output.mkdir()
                captured = {}

                def fake_run(command, **kwargs):
                    captured["command"] = command
                    captured["env"] = kwargs["env"]
                    out_path = Path(
                        command[command.index("--output-last-message") + 1]
                    )
                    out_path.write_text("Grounded advice.\nRecommendation: proceed.")
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

                with (
                    patch.object(pi, "_leg_auth_ok", return_value=(True, "")),
                    patch.object(pi, "_run_leg_with_liveness", side_effect=fake_run),
                ):
                    rc, _, _ = pi._exec_leg(
                        "codex",
                        review,
                        output,
                        60,
                        "artifact",
                        "advisory",
                        "gpt-5.6-sol",
                        deadline_s=60,
                        env={
                            "PATH": "/usr/bin",
                            "PMCP_POLICY": "ambient-policy",
                            "PMCP_AUDIT_JSONL": "ambient-audit",
                            "PMCP_LOCK_DIR": "ambient-lock",
                            "PMCP_CONFIG": "ambient-config",
                            "PMCP_MANIFEST_PATH": "ambient-manifest",
                            "PMCP_AUTH_TOKEN": "ambient-auth",
                        },
                        research_seat=seat,
                    )
                self.assertEqual(rc, 0)
                command = captured["command"]
                self.assertEqual(
                    command[:4],
                    ["codex", "--ask-for-approval", "never", "exec"],
                )
                self.assertIn("--ignore-user-config", command)
                self.assertIn("--strict-config", command)
                self.assertIn('web_search="disabled"', command)
                self.assertIn("features.apps=false", command)
                self.assertIn("features.remote_plugin=false", command)
                self.assertFalse(
                    any(key.startswith("PMCP_") for key in captured["env"])
                )
            finally:
                run.close()

    def test_clients_receive_only_session_local_pmcp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run = materialize_research_run(
                ResearchPolicy(enabled=True),
                [("codex", "c")],
                root=Path(td) / "research-run",
                probe_run=lambda *args, **kwargs: _probe_result(),
            )
            try:
                seat = run.seats[0]
                claude = json.loads(claude_mcp_config(seat))
                self.assertEqual(tuple(claude["mcpServers"]), ("pmcp_advisor",))
                self.assertEqual(
                    claude["mcpServers"]["pmcp_advisor"]["command"], "uvx"
                )
                server = claude["mcpServers"]["pmcp_advisor"]
                self.assertEqual(
                    server["env"],
                    {"PMCP_MANIFEST_PATH": str(seat.manifest_path)},
                )
                self.assertIn("--project", server["args"])
                self.assertIn(str(run.root), server["args"])
                self.assertIn("--config", server["args"])
                self.assertIn(str(seat.provider_config_path), server["args"])
                providers = json.loads(seat.provider_config_path.read_text())
                self.assertEqual(
                    tuple(providers["mcpServers"]), ("firecrawl", "brightdata")
                )
                manifest = json.loads(seat.manifest_path.read_text())
                self.assertEqual(
                    tuple(manifest["servers"]), ("firecrawl", "brightdata")
                )

                codex = codex_mcp_args(seat)
                self.assertIn("--ignore-user-config", codex)
                self.assertIn("--strict-config", codex)
                self.assertIn('web_search="disabled"', codex)
                self.assertIn("features.apps=false", codex)
                self.assertIn("features.remote_plugin=false", codex)
                self.assertTrue(any("pmcp==1.20.0" in arg for arg in codex))
                self.assertTrue(any("default_tools_approval_mode" in arg and "approve" in arg for arg in codex))
                self.assertTrue(any("enabled_tools" in arg and "gateway.invoke" in arg for arg in codex))

                self.assertEqual(
                    mcp_tool_names(),
                    (
                        "mcp__pmcp_advisor__gateway_health",
                        "mcp__pmcp_advisor__gateway_catalog_search",
                        "mcp__pmcp_advisor__gateway_describe",
                        "mcp__pmcp_advisor__gateway_invoke",
                    ),
                )
            finally:
                run.close()

    def test_materialization_failure_is_typed_and_cleans_partial_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "research-run"
            with (
                patch.object(Path, "write_text", side_effect=OSError("read-only")),
                self.assertRaisesRegex(
                    ResearchUnavailable, "research_materialization_failed"
                ),
            ):
                materialize_research_run(
                    ResearchPolicy(enabled=True),
                    [("codex", "c")],
                    root=root,
                    probe_run=lambda *args, **kwargs: _probe_result(),
                )
            self.assertFalse(root.exists())

    def test_existing_root_is_never_removed_on_materialization_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "research-run"
            root.mkdir()
            sentinel = root / "caller-owned.txt"
            sentinel.write_text("preserve")
            with self.assertRaisesRegex(
                ResearchUnavailable, "research_materialization_failed"
            ):
                materialize_research_run(
                    ResearchPolicy(enabled=True),
                    [("codex", "c")],
                    root=root,
                    probe_run=lambda *args, **kwargs: _probe_result(),
                )
            self.assertEqual(sentinel.read_text(), "preserve")

    def test_disabled_claude_command_retains_safe_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            command = pi._claude_tui_command(Path(td), Path(td))
        self.assertIn("--safe-mode", command)
        self.assertNotIn("--no-chrome", command)


class AuditReductionTests(unittest.TestCase):
    def _run(self, td: str):
        return materialize_research_run(
            ResearchPolicy(enabled=True),
            [("codex", "c")],
            root=Path(td) / "research-run",
            probe_run=lambda *args, **kwargs: _probe_result(),
        )

    def test_success_requires_complete_correlated_audit_and_authored_label(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run = self._run(td)
            try:
                config = run.seats[0]
                source_hash = hashlib.sha256(b"https://example.com/source").hexdigest()
                invocation = {
                    "event": "audit.invocation",
                    "gateway_tool": "gateway.invoke",
                    "run_correlation_id": config.run_correlation_id,
                    "seat_correlation_id": config.seat_correlation_id,
                    "evidence_label_digest": config.evidence_label_digest,
                    "downstream_tool_id": "firecrawl::search",
                    "terminal_status": "success",
                    "source_reference_hash": source_hash,
                }
                described = {
                    **invocation,
                    "gateway_tool": "gateway.describe",
                    "run_correlation_id": None,
                    "seat_correlation_id": None,
                    "evidence_label_digest": None,
                }
                _write_audit(config, _audit_records(config, [described, invocation]))
                ledger = reduce_research_audit(
                    config, f"Source-backed result {config.evidence_label}"
                )
                self.assertEqual(ledger.status, "success")
                self.assertEqual(len(ledger.invocations), 1)
                self.assertEqual(ledger.invocations[0].claim_status, "verified")
                self.assertNotIn("example.com", json.dumps(ledger.to_safe_dict()))

                unjoined = reduce_research_audit(config, "same prose, missing label")
                self.assertEqual(unjoined.status, "failed")
                self.assertEqual(unjoined.invocations[0].claim_status, "unverified")

                mismatched = {
                    **invocation,
                    "seat_correlation_id": "other-seat",
                }
                _write_audit(
                    config, _audit_records(config, [invocation, mismatched])
                )
                mixed = reduce_research_audit(
                    config, f"Source-backed result {config.evidence_label}"
                )
                self.assertEqual(mixed.status, "failed")
                self.assertEqual(mixed.detail, "audit_correlation_mismatch")
                self.assertEqual(
                    [entry.claim_status for entry in mixed.invocations],
                    ["verified", "unverified"],
                )
            finally:
                run.close()

    def test_truncation_gap_mismatch_denial_and_failure_stay_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run = self._run(td)
            try:
                config = run.seats[0]
                denied = {
                    "event": "audit.invocation",
                    "gateway_tool": "gateway.invoke",
                    "run_correlation_id": config.run_correlation_id,
                    "seat_correlation_id": config.seat_correlation_id,
                    "evidence_label_digest": config.evidence_label_digest,
                    "downstream_tool_id": None,
                    "terminal_status": "denied",
                    "source_reference_hash": None,
                }
                records = _audit_records(config, [denied])
                _write_audit(config, records)
                self.assertEqual(reduce_research_audit(config, "").status, "denied")

                _write_audit(config, records[:-1])
                self.assertEqual(
                    reduce_research_audit(config, "").detail,
                    "audit_completion_invalid",
                )

                records = _audit_records(config, [denied])
                records[1]["sequence"] = 9
                _write_audit(config, records)
                self.assertEqual(
                    reduce_research_audit(config, "").detail, "audit_sequence_gap"
                )

                records = _audit_records(config, [denied])
                records[1] = None
                _write_audit(config, records)
                self.assertEqual(
                    reduce_research_audit(config, "").detail,
                    "audit_record_invalid",
                )

                records = _audit_records(config, [denied])
                records[1]["policy_digest"] = "0" * 64
                _write_audit(config, records)
                self.assertEqual(
                    reduce_research_audit(config, "").detail, "audit_policy_mismatch"
                )
            finally:
                run.close()


class InvocationAndCompatibilityTests(unittest.TestCase):
    def test_one_policy_source_rejects_board_and_request_mismatches(self) -> None:
        disabled = ResearchPolicy()
        enabled = ResearchPolicy(enabled=True)
        request = pi.PanelRequest(artifact="a", research_policy=disabled)
        with self.assertRaisesRegex(ValueError, "research policy mismatch"):
            pi.invoke_panel_request(request, research_policy=enabled)

        board = Board(
            name="b",
            purpose="advisory",
            seats=(Seat(model="gpt-5.6-sol", effort="max", harness="codex"),),
            research_policy=disabled,
        )
        with self.assertRaisesRegex(ValueError, "research policy mismatch"):
            pi.invoke_board(board, "a", research_policy=enabled)

    def test_disabled_result_serializer_is_unchanged(self) -> None:
        result = pi.PanelLegResult(leg="codex", status="OK", text="AGREE")
        self.assertEqual(
            asdict(result),
            {
                "leg": "codex",
                "status": "OK",
                "text": "AGREE",
                "detail": None,
                "seat_key": "codex",
            },
        )
        self.assertIsNone(result.research_status)
        self.assertNotIn("research", json.dumps(asdict(result)))

    def test_observability_emits_only_research_status_and_digests(self) -> None:
        result = pi.PanelLegResult(
            leg="codex", status="OK", text="PRIVATE QUERY AND RESULT"
        )
        ledger = ResearchLedger(
            status="success",
            policy_digest="1" * 64,
            audit_digest="2" * 64,
            ledger_digest="3" * 64,
        )
        pi.attach_research_ledger(result, ledger)
        sink = CollectingSink()
        observer = BoardObserver(sink, board_name="b")
        observer.seat_result(
            Seat(model="gpt-5.6-sol", effort="max", harness="codex"), result
        )
        payload = sink.events[-1].payload
        self.assertEqual(payload["research_status"], "success")
        self.assertEqual(payload["research_ledger_digest"], "3" * 64)
        self.assertEqual(payload["research_audit_digest"], "2" * 64)
        self.assertNotIn("PRIVATE", json.dumps(payload))

    def test_board_research_maps_configs_and_cleans_the_run_root(self) -> None:
        policy = ResearchPolicy(enabled=True)
        board = Board(
            name="research-board",
            purpose="advisory",
            research_policy=policy,
            seats=(
                Seat(model="gpt-5.6-sol", effort="max", harness="codex"),
                Seat(model="claude-opus-5", effort="max", harness="claude"),
                Seat(model="grok-4.5", effort="max", harness="grok"),
            ),
        )
        with tempfile.TemporaryDirectory() as td:
            run = materialize_research_run(
                policy,
                [(seat.harness or "", seat.seat_key) for seat in board.seats],
                root=Path(td) / "research-run",
                probe_run=lambda *args, **kwargs: _probe_result(),
            )
            seen = []

            def fake_provider(leg, artifact, **kwargs):
                config = kwargs["research_seat"]
                seen.append(
                    (
                        leg,
                        config.seat_correlation_id,
                        kwargs["brief_append"],
                        artifact,
                    )
                )
                source_hash = hashlib.sha256(f"source-{leg}".encode()).hexdigest()
                _write_audit(
                    config,
                    _audit_records(
                        config,
                        [
                            {
                                "event": "audit.invocation",
                                "gateway_tool": "gateway.invoke",
                                "run_correlation_id": config.run_correlation_id,
                                "seat_correlation_id": config.seat_correlation_id,
                                "evidence_label_digest": config.evidence_label_digest,
                                "downstream_tool_id": "firecrawl::firecrawl_search",
                                "terminal_status": "success",
                                "source_reference_hash": source_hash,
                            }
                        ],
                    ),
                )
                return "OK", f"Grounded {leg}: {config.evidence_label}"

            with (
                patch.object(pi, "materialize_research_run", return_value=run),
                patch.object(
                    pi, "_default_spawn_via_provider", side_effect=fake_provider
                ),
            ):
                result = pi.invoke_board(board, "material under review")

            self.assertEqual(
                [(leg.status, leg.research_status) for leg in result.legs],
                [("OK", "success"), ("OK", "success"), ("UNAVAILABLE", "unavailable")],
            )
            self.assertEqual(
                {(leg, seat_id) for leg, seat_id, _, _ in seen},
                {("codex", "seat-0000"), ("claude", "seat-0001")},
            )
            self.assertTrue(
                all("## Governed advisor research" in brief for _, _, brief, _ in seen)
            )
            self.assertTrue(
                all("Governed advisor research" not in artifact for _, _, _, artifact in seen)
            )
            self.assertFalse(run.root.exists())

    def test_gemini_grok_and_custom_spawn_fail_closed_when_research_is_enabled(self) -> None:
        policy = ResearchPolicy(enabled=True)
        with patch.object(pi, "materialize_research_run") as materialize:
            custom = pi.invoke_panel(
                "a",
                ("codex",),
                spawn=lambda leg, artifact: ("OK", "AGREE"),
                research_policy=policy,
            )
        materialize.assert_not_called()
        self.assertEqual(custom.legs[0].status, "UNAVAILABLE")
        self.assertEqual(custom.legs[0].research_status, "unavailable")

        with tempfile.TemporaryDirectory() as td:
            run = materialize_research_run(
                policy,
                [("gemini", "gemini")],
                root=Path(td) / "research-run",
                probe_run=lambda *args, **kwargs: _probe_result(),
            )
            with patch.object(pi, "materialize_research_run", return_value=run):
                result = pi.invoke_panel("a", ("gemini",), research_policy=policy)
            self.assertEqual(result.legs[0].status, "UNAVAILABLE")
            self.assertEqual(
                result.legs[0].detail, "research_profile_unenforceable"
            )

        for leg in ("gemini", "grok"):
            with tempfile.TemporaryDirectory() as td:
                run = materialize_research_run(
                    policy,
                    [(leg, leg)],
                    root=Path(td) / "research-run",
                    probe_run=lambda *args, **kwargs: _probe_result(),
                )
                with patch.object(pi, "materialize_research_run", return_value=run):
                    result = pi.invoke_panel("a", (leg,), research_policy=policy)
                self.assertEqual(result.legs[0].status, "UNAVAILABLE")
                self.assertEqual(
                    result.legs[0].detail, "research_profile_unenforceable"
                )

    def test_research_is_additive_keyword_only(self) -> None:
        parameter = inspect.signature(pi.invoke_panel).parameters["research_policy"]
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(parameter.default)


if __name__ == "__main__":
    unittest.main()
