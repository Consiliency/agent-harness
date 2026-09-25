"""run-train --monitoring-policy (agent-harness#906): the train review can run heartbeat-only.

The advisor-board CLI already had ``--monitoring-policy heartbeat_only`` (no model deadline, the
frozen four-vendor default board, no native host seat); the train's default review path always
ran ``bounded``. These pin that the policy reaches BOTH the authorization and ``invoke_board``
(which refuse a mismatch), that unsupported routes are refused before any effect, that the
default path is unchanged, and that the real CLI parses and previews it.
"""
from __future__ import annotations

import json

import pytest

from test_train_review_packet import candidate, never  # noqa: F401  (fixture, by name below; helper)
from test_train_review_packet import synthetic_train_packet  # noqa: F401  (fixture)

from phase_loop_runtime import governed_review as gr
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import train_runner as tr
from phase_loop_runtime.advisor_board import backing as backing_mod
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from phase_loop_runtime.advisor_board.schema import Board
from phase_loop_runtime.train_ledger import append_record

from test_train_review_authorization import (  # noqa: E402
    _approval_with_panel_review_fn,
    _board,
    _canonical_repo,
    _legs,
    _ledger,
    _run_review,
)

HB = "heartbeat_only"


def _gate(tmp_path, monkeypatch, *, policy=HB, compose=None, native_leg_fills=None,
          emit_native_request=False, preflight_error=None):
    """Drive the gate with the REAL composition choice (no compose seam unless given)."""
    repo = _canonical_repo(tmp_path)
    seen: dict = {"composed": 0}
    monkeypatch.setattr(backing_mod, "prepare_review_composition_authorization", lambda: None)
    monkeypatch.setattr(backing_mod, "clear_review_composition_authorization", lambda: None)

    def _preflight(board, monitoring_policy, env=None):
        seen["preflight"] = (board, monitoring_policy)
        if preflight_error is not None:
            raise preflight_error

    monkeypatch.setattr(pi, "_preflight_gemini_heartbeat", _preflight)

    def _mint(board_, artifact_, **kw):
        seen["mint_kwargs"] = kw
        return "authorization"

    monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", _mint)

    def _invoke(board_, artifact_, **kw):
        seen["invoke_board"] = board_
        seen["invoke_kwargs"] = kw
        return _legs(board_)

    def _counting_compose():
        seen["composed"] += 1
        return compose()

    gate = gr.governed_board_gate(
        artifact="# Train-level bundle review\n\nbundle\n", author_executor="train-coordinator",
        run_mode="governed", canonical_repo_authority=repo, invoke=_invoke,
        compose=_counting_compose if compose is not None else None,
        native_leg_fills=native_leg_fills, emit_native_request=emit_native_request,
        **({"monitoring_policy": policy} if policy is not None else {}),
    )
    return gate, seen


class TestGate:
    def test_heartbeat_only_seats_the_default_board_and_binds_the_policy_twice(self, tmp_path, monkeypatch):
        gate, seen = _gate(tmp_path, monkeypatch)
        assert gate.promoted, gate
        assert seen["invoke_board"] is DEFAULT_BOARD, "no availability backfill under heartbeat_only"
        assert [s.harness for s in DEFAULT_BOARD.seats] == ["codex", "gemini", "claude", "grok"]
        assert seen["preflight"] == (DEFAULT_BOARD, HB), "agy capability is checked before minting"
        # invoke_board refuses review_monitoring_policy_mismatch unless both carry it.
        assert seen["mint_kwargs"]["monitoring_policy"] == HB
        assert seen["invoke_kwargs"]["monitoring_policy"] == HB
        assert seen["invoke_kwargs"]["review_authorization"] == "authorization"

    def test_the_default_policy_passes_no_policy_keyword(self, tmp_path, monkeypatch):
        board = _board("codex", "gemini", "grok")
        for policy in (None, "bounded"):
            (tmp_path / str(policy)).mkdir()
            gate, seen = _gate(tmp_path / str(policy), monkeypatch, policy=policy, compose=lambda: board)
            assert gate.promoted
            assert "monitoring_policy" not in seen["mint_kwargs"]
            assert "monitoring_policy" not in seen["invoke_kwargs"]
            assert "preflight" not in seen

    @pytest.mark.parametrize("route", ["native_leg_fills", "emit_native_request"])
    def test_a_native_route_is_refused_before_composition(self, tmp_path, monkeypatch, route):
        kwargs = {"native_leg_fills": ("fill",)} if route == "native_leg_fills" else {"emit_native_request": True}
        gate, seen = _gate(tmp_path, monkeypatch, compose=lambda: DEFAULT_BOARD, **kwargs)
        assert not gate.promoted and gate.reason == "review_isolation_unavailable"
        assert "review_monitoring_unsupported_route:native_fill" in gate.findings[0].reason
        assert seen["composed"] == 0 and "mint_kwargs" not in seen and "invoke_kwargs" not in seen

    @pytest.mark.parametrize("board", [
        # agent-harness#1061 r1 (codex): an injected composer must not replace the frozen board,
        # even with seats that would pass the policy's own route checks.
        Board(name="default", purpose="premerge-review", seats=DEFAULT_BOARD.seats[:3], allow_api_key_fallback=False),
        Board(name="x", purpose="code-review", seats=DEFAULT_BOARD.seats, allow_api_key_fallback=True),
    ], ids=["three-default-seats", "api-fallback"])
    def test_any_board_but_the_frozen_default_is_refused_before_minting(self, tmp_path, monkeypatch, board):
        gate, seen = _gate(tmp_path, monkeypatch, compose=lambda: board)
        assert not gate.promoted
        assert "requires the frozen four-vendor default board" in gate.findings[0].reason
        assert "preflight" not in seen and "mint_kwargs" not in seen and "invoke_kwargs" not in seen

    @pytest.mark.parametrize("error", [ValueError("gemini_heartbeat_unqualified"), OSError("agy missing")])
    def test_a_failed_agy_capability_check_is_refused_before_minting(self, tmp_path, monkeypatch, error):
        gate, seen = _gate(tmp_path, monkeypatch, preflight_error=error)
        assert seen["preflight"] == (DEFAULT_BOARD, HB)
        assert not gate.promoted and str(error) in gate.findings[0].reason
        assert "mint_kwargs" not in seen and "invoke_kwargs" not in seen

    def test_an_unknown_policy_is_refused(self, tmp_path, monkeypatch):
        gate, seen = _gate(tmp_path, monkeypatch, policy="silence_deadline", compose=lambda: DEFAULT_BOARD)
        assert not gate.promoted and seen["composed"] == 0

    def test_the_real_authorization_carries_the_policy(self, tmp_path):
        """The production factory accepts and records the policy the gate forwards."""
        from harden_tdd_guard import harden_require
        harden_require("review-leg-isolation")
        repo = _canonical_repo(tmp_path)
        auth = backing_mod.prepare_review_isolation_authorization(
            DEFAULT_BOARD, "bundle\n", mode="review", canonical_repo_authority=repo, monitoring_policy=HB,
        )
        assert auth.monitoring_policy == HB


@pytest.mark.usefixtures("synthetic_train_packet")
class TestTrainWiring:
    def test_default_train_review_forwards_the_policy_to_the_gate(self, monkeypatch):
        from phase_loop_runtime import governed_premerge as gp_mod
        captured: dict = {}
        monkeypatch.setattr(gp_mod, "run_governed_premerge_loop",
                            lambda **kw: captured.setdefault("invoke", kw["invoke"]))
        tr._default_train_review("bundle", "governed", canonical_repo_authority="/repo", monitoring_policy=HB)
        assert captured["invoke"].func is gr.governed_board_gate
        assert captured["invoke"].keywords == {"canonical_repo_authority": "/repo", "monitoring_policy": HB}
        captured.clear()
        tr._default_train_review("bundle", "governed", canonical_repo_authority="/repo")
        assert captured["invoke"].keywords == {"canonical_repo_authority": "/repo"}, "default unchanged"

    def test_run_train_hands_the_policy_to_the_default_review(self, tmp_path, monkeypatch):
        seen: dict = {}

        def _capture(artifact, run_mode, **kw):
            seen.update(kw)
            return _approval_with_panel_review_fn(artifact, run_mode)

        monkeypatch.setattr(tr, "_default_train_review", _capture)
        monkeypatch.setattr(pi, "_preflight_gemini_heartbeat", lambda *a, **k: None)
        result, merged = _run_review(tmp_path, _ledger(tmp_path), review_only=True, review_fn=None,
                                     review_monitoring_policy=HB)
        assert result["status"] == "review_approved", result
        assert seen["monitoring_policy"] == HB and merged == []

    @pytest.mark.parametrize("error", [ValueError("gemini_heartbeat_unqualified"), OSError("agy missing")])
    def test_run_train_refuses_an_unqualified_agy_route_before_any_effect(self, tmp_path, monkeypatch, error):
        """agent-harness#1061 r1 (codex, grok): a DIRECT caller is refused before publication,
        ledger or broker work, not only later at the review gate."""
        def _raise(board, policy, env=None):
            assert board is DEFAULT_BOARD and policy == HB
            raise error

        monkeypatch.setattr(pi, "_preflight_gemini_heartbeat", _raise)
        ledger = _ledger(tmp_path)
        before = ledger.read_bytes()
        publish = never
        result, merged = _run_review(tmp_path, ledger, review_only=False, review_fn=never, publish=publish,
                                     merge_pr=never, review_monitoring_policy=HB)
        assert result["status"] == "review_halted" and result["reason"] == str(error), result
        assert result["terminal_blocker"]["human_required"] is False
        assert ledger.read_bytes() == before and merged == []

    def test_run_train_refuses_heartbeat_only_outside_governed_mode(self, tmp_path):
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        result = tr.run_train(None, ledger, run_mode="autonomous", resolve_workspace=never,
                              review_monitoring_policy=HB)
        assert result["status"] == "review_halted"
        assert result["reason"] == "review_monitoring_requires_governed"
        assert not ledger.parent.exists()

    @pytest.mark.parametrize("route", ["emit_native_request", "native_leg_fills"])
    def test_run_train_refuses_a_native_route_before_any_effect(self, tmp_path, route):
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        kwargs = {"emit_native_request": True} if route == "emit_native_request" else {"native_leg_fills": ("fill",)}
        result = tr.run_train(None, ledger, run_mode="governed", resolve_workspace=never,
                              review_monitoring_policy=HB, **kwargs)
        assert result["status"] == "review_halted"
        assert result["reason"] == "review_monitoring_unsupported_route:native_fill"
        assert result["terminal_blocker"]["human_required"] is False
        assert not ledger.parent.exists()


TRAIN_MD = "# Release Train: packet boundary\n\n## Nodes\n\n### Node: repo-a / CHANGELOG.md\n\n**Depends on:** (none)\n**Channel:** (none)\n"


def _cli_candidate(c, monkeypatch):
    from phase_loop_runtime import train_review_packet as packet
    from phase_loop_runtime.convergence import broker
    from phase_loop_runtime.convergence.broker import live
    train = c["tmp"] / "train.md"
    train.write_text(TRAIN_MD)
    ledger = c["tmp"] / "ledger/train-train.ledger.jsonl"
    append_record(ledger, c["state"][c["node"].node_id])
    monkeypatch.setattr(packet, "read_pr_metadata", lambda *_: dict(c["live"]))
    monkeypatch.setattr(live, "fabpub_capability_active", never)
    monkeypatch.setattr(live, "fabpub_activation_barrier", never)
    monkeypatch.setattr(broker, "build_routing_broker_client", never)
    monkeypatch.setattr(tr, "run_train", never)
    return train, ledger


class TestCli:
    def test_preview_shows_the_heartbeat_board_without_effects(self, request, monkeypatch, capsys):
        from phase_loop_runtime import cli
        c = request.getfixturevalue("candidate")
        train, ledger = _cli_candidate(c, monkeypatch)
        checked = []
        monkeypatch.setattr(pi, "_preflight_gemini_heartbeat", lambda b, p, env=None: checked.append((b, p)))
        before = ledger.read_bytes()
        args = ["run-train", "--train", str(train), "--governed", "--review-only", "--review-material",
                str(c["material_path"]), "--preview-review", str(c["tmp"] / "preview"), "--monitoring-policy", HB,
                "--workspace", "repo-a=" + str(c["repo"]), "--ledger-dir", str(ledger.parent), "--json"]
        assert cli.main(args) == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["ready"] and receipt["model_calls"] == 0
        assert receipt["review_monitoring_policy"] == HB
        assert receipt["review_board"] == [
            {"harness": s.harness, "model": s.model, "effort": s.effort} for s in DEFAULT_BOARD.seats]
        assert checked == [(DEFAULT_BOARD, HB)]
        assert ledger.read_bytes() == before and not (ledger.parent / "broker").exists()

    def test_preview_default_policy_is_bounded_with_no_fixed_board(self, request, monkeypatch, capsys):
        from phase_loop_runtime import cli
        c = request.getfixturevalue("candidate")
        train, ledger = _cli_candidate(c, monkeypatch)
        monkeypatch.setattr(pi, "_preflight_gemini_heartbeat", never)
        args = ["run-train", "--train", str(train), "--governed", "--review-only", "--review-material",
                str(c["material_path"]), "--preview-review", str(c["tmp"] / "preview"),
                "--workspace", "repo-a=" + str(c["repo"]), "--ledger-dir", str(ledger.parent), "--json"]
        assert cli.main(args) == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["review_monitoring_policy"] == "bounded" and receipt["review_board"] is None

    @pytest.mark.parametrize("extra, message", [
        ([], "--monitoring-policy heartbeat_only requires --governed"),
        (["--governed", "--review-only", "--emit-native-request"], "cannot combine with --emit-native-request"),
    ])
    def test_unsupported_combinations_are_usage_errors(self, request, monkeypatch, capsys, extra, message):
        from phase_loop_runtime import cli
        c = request.getfixturevalue("candidate")
        train, ledger = _cli_candidate(c, monkeypatch)
        before = ledger.read_bytes()
        with pytest.raises(SystemExit) as error:
            cli.main(["run-train", "--train", str(train), "--monitoring-policy", HB, *extra,
                      "--workspace", "repo-a=" + str(c["repo"]), "--ledger-dir", str(ledger.parent)])
        assert error.value.code == 2 and message in capsys.readouterr().err
        assert ledger.read_bytes() == before

    def test_a_native_leg_is_refused_before_effects(self, request, monkeypatch, capsys):
        from phase_loop_runtime import cli
        c = request.getfixturevalue("candidate")
        train, ledger = _cli_candidate(c, monkeypatch)
        monkeypatch.setattr(pi, "load_native_leg_fills", never)
        before = ledger.read_bytes()
        rc = cli.main(["run-train", "--train", str(train), "--governed", "--review-only", "--monitoring-policy", HB,
                       "--native-leg", "claude=" + str(c["tmp"]), "--workspace", "repo-a=" + str(c["repo"]),
                       "--ledger-dir", str(ledger.parent)])
        assert rc == 2
        assert "review_monitoring_unsupported_route:native_fill" in capsys.readouterr().err
        assert ledger.read_bytes() == before and not (ledger.parent / "broker").exists()

    @pytest.mark.parametrize("flag, expected", [([], "bounded"), (["--monitoring-policy", HB], HB)])
    def test_the_cli_hands_the_policy_to_run_train(self, request, monkeypatch, flag, expected):
        from phase_loop_runtime import cli
        from phase_loop_runtime.convergence import broker
        from phase_loop_runtime.convergence.broker import live
        c = request.getfixturevalue("candidate")
        train, ledger = _cli_candidate(c, monkeypatch)
        monkeypatch.setattr(pi, "_preflight_gemini_heartbeat", lambda *a, **k: None)
        monkeypatch.setattr(live, "fabpub_capability_active", lambda: False)
        monkeypatch.setattr(broker, "build_routing_broker_client", lambda **k: None)
        seen: dict = {}

        def _run_train(*a, **kw):
            seen.update(kw)
            return {"status": "review_approved", "nodes": {}}

        monkeypatch.setattr(tr, "run_train", _run_train)
        cli.main(["run-train", "--train", str(train), "--governed", "--review-only", *flag,
                  "--workspace", "repo-a=" + str(c["repo"]), "--ledger-dir", str(ledger.parent)])
        assert seen["review_monitoring_policy"] == expected
