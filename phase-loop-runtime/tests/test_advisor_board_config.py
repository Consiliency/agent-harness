"""ABDREG — user-editable board config loader (Phase 2, lane 4).

Proves: presets load from config and self-validate; ``allow_api_key_fallback``
defaults false; unknown keys ERROR (never a silent drop); a matrix-invalid user
board is rejected at load time; the frozen example TOML parses; and the shipped
example fixture round-trips.
"""
from __future__ import annotations

import unittest
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from phase_loop_runtime import sandbox_policy
from phase_loop_runtime.advisor_board import config


from phase_loop_runtime.advisor_board import (
    DEFAULT_BOARD,
    BoardConfigError,
    default_matrix,
    load_boards,
)

def _ALL_PRESENT(cli):  # noqa: ANN001, ARG001
    return True


_MATRIX = default_matrix(probe=_ALL_PRESENT, env={})


def _write(tmp: str, body: str) -> Path:
    p = Path(tmp) / "advisor-boards.toml"
    p.write_text(body, encoding="utf-8")
    return p


class PresetSelfValidationTests(unittest.TestCase):
    def test_load_with_no_user_config_self_validates_every_preset(self) -> None:
        # No file -> presets only. This is the guardrail: if any preset seat used
        # an unregistered model or an incompatible lane, this raises.
        cfg = load_boards(Path("/nonexistent/advisor-boards.toml"), matrix=_MATRIX)
        self.assertEqual(
            set(cfg.names()),
            {
                "default", "code-review", "brainstorm", "doc-edit",
                "legal-review", "legal-strategy-review", "legal-brainstorm",
                "general", "solo",
            },
        )

    def test_default_board_resolves_to_four_vendor_seats(self) -> None:
        cfg = load_boards(Path("/nonexistent/advisor-boards.toml"), matrix=_MATRIX)
        self.assertIs(cfg.get("default"), DEFAULT_BOARD)
        self.assertIs(cfg.get(), DEFAULT_BOARD)  # bare advisor-board -> default
        self.assertEqual(len(cfg.get().seats), 4)


class CodeReviewAvailabilityAwareTests(unittest.TestCase):
    """The LIVE convening path — ``load_boards().get("code-review")`` — reflects
    vendor availability, so a convened panel never collapses to 1–2 reviewers. This
    is the integration proof (the pure composer is proven in
    test_advisor_board_composition.py); it guards against the code-review board
    silently reverting to a frozen all-vendors-up snapshot on the runtime path."""

    _NONEXISTENT = Path("/nonexistent/advisor-boards.toml")

    def _load_code_review(self, absent: set[str]):
        # A matrix whose PATH probe reports every vendor's CLI present EXCEPT the
        # `absent` ones — the same probe seam load_boards single-sources for
        # composition. (gemini's CLI is `agy`, so name it here, not "gemini".)
        cli_absent = {"grok": "grok", "claude": "claude", "codex": "codex", "gemini": "agy"}
        down = {cli_absent[v] for v in absent}
        matrix = default_matrix(probe=lambda cli: cli not in down, env={})
        # Isolate the AVAILABILITY dimension: pin auth to pass-through so the loader
        # never shells out to the real auth probe (the auth dimension is proven
        # separately below and in test_advisor_board_composition.py).
        return load_boards(
            self._NONEXISTENT, matrix=matrix, auth_ok=lambda _v: True
        ).get("code-review")

    def test_all_vendors_up_is_the_four_vendor_board(self) -> None:
        board = self._load_code_review(absent=set())
        self.assertEqual(len(board.seats), 4)
        self.assertEqual({s.harness for s in board.seats}, {"grok", "claude", "codex", "gemini"})

    def test_grok_down_backfills_rather_than_leaving_a_dead_grok_seat(self) -> None:
        # THE regression guard: a frozen preset would keep a grok seat that then
        # fails-closed to DEGRADED; the availability-aware path drops grok and
        # backfills a 4th seat onto an available vendor with a distinct lens.
        board = self._load_code_review(absent={"grok"})
        self.assertEqual(len(board.seats), 4)  # still a full board, never choked
        self.assertTrue(all(s.harness != "grok" for s in board.seats))
        keys = [(s.harness, s.model, s.lens) for s in board.seats]
        self.assertEqual(len(keys), len(set(keys)))  # no duplicate seat

    def test_two_vendors_down_still_yields_a_full_four_seat_board(self) -> None:
        board = self._load_code_review(absent={"grok", "gemini"})
        self.assertEqual(len(board.seats), 4)
        self.assertTrue(all(s.harness in {"claude", "codex"} for s in board.seats))

    def test_explicit_auth_ok_drops_an_unauthed_vendor_on_the_live_path(self) -> None:
        # REVIEWGOV-W1 / #151: an explicit ``auth_ok`` on the LIVE convening path
        # drops a PATH-present-but-unauthed vendor (grok) and backfills it, exactly
        # like a PATH-absent one. Availability all-up, grok unauthed. (The DEFAULT
        # gate is exercised in test_auth_ok_defaults_to_the_real_auth_gate...)
        matrix = default_matrix(probe=lambda cli: True, env={})
        board = load_boards(
            self._NONEXISTENT, matrix=matrix,
            auth_ok=lambda v: v != "grok",
        ).get("code-review")
        self.assertEqual(len(board.seats), 4)                       # never choked
        self.assertTrue(all(s.harness != "grok" for s in board.seats))

    def test_auth_ok_defaults_to_the_real_auth_gate_on_the_live_path(self) -> None:
        # #151: with no explicit ``auth_ok`` the live path defaults to the REAL
        # (cached, fail-closed) auth gate — it is not silently availability-only.
        # Patch the module default so grok is PATH-present but unauthed, with no
        # subprocess: grok is dropped and backfilled.
        import phase_loop_runtime.advisor_board.config as cfg_mod

        matrix = default_matrix(probe=lambda cli: True, env={})
        with patch.object(cfg_mod, "default_board_auth_ok", lambda v: v != "grok"):
            board = load_boards(self._NONEXISTENT, matrix=matrix).get("code-review")
        self.assertEqual(len(board.seats), 4)                       # never choked
        self.assertTrue(all(s.harness != "grok" for s in board.seats))

    def test_user_defined_code_review_overrides_the_composed_board(self) -> None:
        # A user board named code-review wins over availability-aware composition.
        body = """
[[boards]]
name = "code-review"
purpose = "code-review"
  [[boards.seats]]
  model = "gpt-5.6-sol"
  effort = "high"
  harness = "codex"
"""
        with TemporaryDirectory() as tmp:
            cfg = load_boards(_write(tmp, body), matrix=_MATRIX)
        board = cfg.get("code-review")
        self.assertEqual(len(board.seats), 1)
        self.assertEqual(board.seats[0].model, "gpt-5.6-sol")


class GptSixSolSeatTests(unittest.TestCase):
    def test_gpt_6_sol_loads_as_an_explicit_seat_in_a_user_board(self) -> None:
        # Before registration the whole file was rejected with "unknown model 'gpt-6-sol'".
        # A user/ad-hoc board only: on a governed review it counts as a second `sol`
        # seat and cannot fill a required `grok` seat.
        body = """
[[boards]]
name = "code-review"
purpose = "code-review"
  [[boards.seats]]
  model = "gpt-6-sol"
  effort = "max"
  harness = "codex"
  lens = "adversarial"
  [[boards.seats]]
  model = "gpt-6-astra"
  effort = "max"
  harness = "codex"
  lens = "red-team"
"""
        with TemporaryDirectory() as tmp:
            board = load_boards(_write(tmp, body), matrix=_MATRIX).get("code-review")
        self.assertEqual([(s.model, s.lens) for s in board.seats],
                         [("gpt-6-sol", "adversarial"), ("gpt-6-astra", "red-team")])


    def test_gpt_6_sol_cannot_fill_a_governed_grok_seat(self) -> None:
        # It answers to the `sol` alias: a governed policy requiring grok rejects a
        # board that seats gpt-6-sol in grok's place (two sol seats, no grok).
        from phase_loop_runtime import panel_invoker as invoker
        from phase_loop_runtime.advisor_board.schema import Board, Seat

        seats = (
            Seat(model="claude-opus-5-5", effort="max", harness="claude", lens="correctness"),
            Seat(model="gpt-6-astra", effort="max", harness="codex", lens="red-team"),
            Seat(model="gemini-3.8-flash", effort="high", harness="gemini", lens="alternative-approach"),
            Seat(model="gpt-6-sol", effort="max", harness="codex", lens="adversarial"),
        )
        policy = invoker.review_policy_for_tier("production_code")
        with self.assertRaises(invoker.PresidentPolicyError) as ctx:
            invoker._validate_review_board_policy(
                Board(name="code-review", purpose="code-review", seats=seats), policy, None
            )
        self.assertEqual(ctx.exception.code, "review_board_policy_mismatch")
        self.assertIn("'sol': 2", str(ctx.exception))


class ConfigLoadTests(unittest.TestCase):
    def test_user_board_layers_over_presets(self) -> None:
        body = """
default_board = "mine"

[[boards]]
name = "mine"
purpose = "custom"

  [[boards.seats]]
  model = "claude-sonnet-5"
  effort = "high"
  harness = "claude"
"""
        with TemporaryDirectory() as tmp:
            cfg = load_boards(_write(tmp, body), matrix=_MATRIX)
        self.assertIn("mine", cfg.names())
        self.assertIn("default", cfg.names())  # presets still present
        self.assertEqual(cfg.default_board, "mine")
        self.assertEqual(cfg.get().name, "mine")

    def test_allow_api_key_fallback_defaults_false(self) -> None:
        body = """
[[boards]]
name = "sub-only"
purpose = "x"
  [[boards.seats]]
  model = "gpt-5.6-sol"
  effort = "high"
  harness = "codex"
"""
        with TemporaryDirectory() as tmp:
            cfg = load_boards(_write(tmp, body), matrix=_MATRIX)
        self.assertFalse(cfg.get("sub-only").allow_api_key_fallback)

    def test_research_enabled_is_explicit_and_defaults_false(self) -> None:
        body = """
[[boards]]
name = "research-board"
purpose = "advisory"
research_enabled = true
  [[boards.seats]]
  model = "gpt-5.6-sol"
  effort = "high"
  harness = "codex"

[[boards]]
name = "ordinary-board"
purpose = "advisory"
  [[boards.seats]]
  model = "gpt-5.6-sol"
  effort = "high"
  harness = "codex"
"""
        with TemporaryDirectory() as tmp:
            cfg = load_boards(_write(tmp, body), matrix=_MATRIX)
        self.assertTrue(cfg.get("research-board").research_policy.enabled)
        self.assertFalse(cfg.get("ordinary-board").research_policy.enabled)

    def test_api_key_seat_without_optin_is_rejected(self) -> None:
        body = """
[[boards]]
name = "leaky"
purpose = "x"
  [[boards.seats]]
  model = "gpt-5.6-sol"
  effort = "high"
  harness = "codex"
  auth = "api_key"
"""
        with TemporaryDirectory() as tmp:
            with self.assertRaises(BoardConfigError):
                load_boards(_write(tmp, body), matrix=_MATRIX)

    def test_api_key_seat_with_optin_is_accepted(self) -> None:
        body = """
[[boards]]
name = "keyed"
purpose = "x"
allow_api_key_fallback = true
  [[boards.seats]]
  model = "gpt-5.6-sol"
  effort = "high"
  harness = "codex"
  auth = "api_key"
"""
        with TemporaryDirectory() as tmp:
            cfg = load_boards(_write(tmp, body), matrix=_MATRIX)
        self.assertTrue(cfg.get("keyed").allow_api_key_fallback)


class UnknownKeyErrorsTests(unittest.TestCase):
    def test_unknown_top_level_key_errors(self) -> None:
        body = 'wat = 1\n[[boards]]\nname="x"\npurpose="y"\n'
        with TemporaryDirectory() as tmp:
            with self.assertRaises(BoardConfigError) as ctx:
                load_boards(_write(tmp, body), matrix=_MATRIX)
        self.assertIn("wat", str(ctx.exception))

    def test_unknown_board_key_errors(self) -> None:
        body = '[[boards]]\nname="x"\npurpose="y"\ncolor="blue"\n'
        with TemporaryDirectory() as tmp:
            with self.assertRaises(BoardConfigError) as ctx:
                load_boards(_write(tmp, body), matrix=_MATRIX)
        self.assertIn("color", str(ctx.exception))

    def test_unknown_seat_key_errors(self) -> None:
        body = """
[[boards]]
name = "x"
purpose = "y"
  [[boards.seats]]
  model = "gpt-5.6-sol"
  effort = "high"
  harness = "codex"
  temperature = 0.7
"""
        with TemporaryDirectory() as tmp:
            with self.assertRaises(BoardConfigError) as ctx:
                load_boards(_write(tmp, body), matrix=_MATRIX)
        self.assertIn("temperature", str(ctx.exception))


class StrictBoolParseTests(unittest.TestCase):
    """A boolean config key is read STRICTLY — a present value MUST be a literal
    TOML boolean, never coerced. Coercion would silently flip an opt-in gate:
    ``bool("false")`` is ``True``, so a quoted ``allow_api_key_fallback = "false"``
    would enable the api-key fallback (a no-silent-key hole)."""

    def test_quoted_false_allow_api_key_fallback_is_rejected_not_coerced(self) -> None:
        # The hole: the string "false" is truthy under bool(), so coercion would
        # ENABLE the fallback the author meant to disable. Strict parse rejects it.
        body = """
[[boards]]
name = "leaky"
purpose = "x"
allow_api_key_fallback = "false"
  [[boards.seats]]
  model = "gpt-5.6-sol"
  effort = "high"
  harness = "codex"
"""
        with TemporaryDirectory() as tmp:
            with self.assertRaises(BoardConfigError) as ctx:
                load_boards(_write(tmp, body), matrix=_MATRIX)
        msg = str(ctx.exception)
        self.assertIn("allow_api_key_fallback", msg)
        self.assertIn("boolean", msg)

    def test_nonbool_host_leg_is_rejected_not_coerced(self) -> None:
        body = """
[[boards]]
name = "b"
purpose = "x"
  [[boards.seats]]
  model = "gpt-5.6-sol"
  effort = "high"
  harness = "codex"
  host_leg = "true"
"""
        with TemporaryDirectory() as tmp:
            with self.assertRaises(BoardConfigError) as ctx:
                load_boards(_write(tmp, body), matrix=_MATRIX)
        msg = str(ctx.exception)
        self.assertIn("host_leg", msg)
        self.assertIn("boolean", msg)

    def test_literal_bool_still_accepted(self) -> None:
        body = """
[[boards]]
name = "keyed"
purpose = "x"
allow_api_key_fallback = true
  [[boards.seats]]
  model = "gpt-5.6-sol"
  effort = "high"
  harness = "codex"
  auth = "api_key"
  host_leg = true
"""
        with TemporaryDirectory() as tmp:
            cfg = load_boards(_write(tmp, body), matrix=_MATRIX)
        board = cfg.get("keyed")
        self.assertTrue(board.allow_api_key_fallback)
        self.assertTrue(board.seats[0].host_leg)


class MatrixInvalidBoardRejectedTests(unittest.TestCase):
    def test_invalid_pairing_in_user_board_rejected_at_load(self) -> None:
        body = """
[[boards]]
name = "bad"
purpose = "x"
  [[boards.seats]]
  model = "gpt-5.6-sol"
  effort = "high"
  harness = "claude"
"""
        with TemporaryDirectory() as tmp:
            with self.assertRaises(BoardConfigError) as ctx:
                load_boards(_write(tmp, body), matrix=_MATRIX)
        msg = str(ctx.exception)
        self.assertIn("gpt-5.6-sol", msg)
        self.assertIn("bad", msg)  # board name located


class ShippedExampleFixtureTests(unittest.TestCase):
    def test_frozen_example_toml_parses_and_validates(self) -> None:
        # Resolve via the INSTALLED package (works from source AND from the
        # standalone-from-wheel clean room, where only tests/ is copied and the
        # package lives in site-packages — a source-tree-relative path fails there).
        import phase_loop_runtime.advisor_board as _ab

        example = Path(_ab.__file__).resolve().parent / "fixtures" / "advisor-boards.example.toml"
        self.assertTrue(example.exists(), example)
        cfg = load_boards(example, matrix=_MATRIX)
        # the example defines default + code-review; presets fill the rest.
        self.assertIn("default", cfg.names())
        self.assertIn("code-review", cfg.names())


def test_driver_settings_layers_are_per_key_and_environment_is_authoritative(tmp_path, monkeypatch):
    user = tmp_path / "user.toml"
    user.write_text('[sandbox.driver]\nadmit_wait_s = 17\ntransfer_allowance_s = 19\nmax_live_workers = 2\n')
    repo = tmp_path / "repo"
    path = config.repo_board_config_path(repo)
    path.parent.mkdir(parents=True)
    path.write_text('[sandbox.driver]\nadmit_wait_s = 23\ntransfer_allowance_s = " "\n')
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ADMIT_WAIT_S", "invalid ambient")
    settings = sandbox_policy.placement_driver_settings(repo, path=user, env={})
    assert (settings.admit_wait_s, settings.transfer_allowance_s, settings.max_live_workers) == (23, 19, 2)
    assert sandbox_policy.placement_driver_settings(path=user, env={}).admit_wait_s == 17
    assert sandbox_policy.placement_driver_settings(repo, path=user, env={
        "PHASE_LOOP_SANDBOX_ADMIT_WAIT_S": "29",
        "PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S": " ",
    }).admit_wait_s == 29
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(repo)
    assert sandbox_policy.placement_driver_settings(env={}) == sandbox_policy.placement_driver_settings(
        env={"PHASE_LOOP_SANDBOX_ADMIT_WAIT_S": " ", "PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S": ""},
    )
    user.write_text('[sandbox.driver]\nadmit_wait_s = "invalid shadowed"\n')
    with pytest.raises(sandbox_policy.SandboxConfigError):
        sandbox_policy.placement_driver_settings(repo, path=user, env={"PHASE_LOOP_SANDBOX_ADMIT_WAIT_S": "31"})


@pytest.mark.parametrize("body", [
    '[sandbox]\nroots = {}', '[sandbox]\norder = []', '[sandbox]\nenabled = true',
    '[sandbox.driver]\nendpoint = "private"', '[sandbox]\ndriver = []',
    '[sandbox.driver]\nlast_rung = "local"', '[boards]',
])
def test_driver_repository_authority_stays_narrow(tmp_path, body):
    path = config.repo_board_config_path(tmp_path)
    path.parent.mkdir()
    path.write_text(body)
    with pytest.raises(sandbox_policy.SandboxConfigError):
        sandbox_policy.placement_driver_settings(tmp_path, env={})
    with pytest.raises(BoardConfigError):
        config.load_president_ladder(tmp_path, env={})


def test_packaged_driver_settings_are_the_authority(tmp_path, monkeypatch):
    import threading
    from phase_loop_runtime import sandbox_placement as sp

    resource = tmp_path / "fixtures" / "placement-driver.defaults.toml"
    resource.parent.mkdir()
    resource.write_text('[sandbox.driver]\nadmit_wait_s = 37\ntransfer_allowance_s = 41\nmax_live_workers = 2\n')
    monkeypatch.setattr(config.resources, "files", lambda package: tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "absent"))
    for name in ("ADMIT_WAIT_S", "TRANSFER_ALLOWANCE_S"):
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_" + name, raising=False)
    assert sandbox_policy.admit_wait_s() == 37
    assert sandbox_policy.transfer_allowance_s() == 41
    assert sp.lifetime_sufficient(78, 0) and not sp.lifetime_sufficient(77, 0)
    calls = sp._Calls()
    release = threading.Event()
    workers = []
    def hang():
        workers.append(threading.current_thread())
        release.wait(5)
    try:
        for _ in range(2):
            with pytest.raises(sp.PlacementUnavailable):
                calls.run(hang, 0.03)
        with pytest.raises(sp.PlacementUnavailable):
            calls.run(lambda: pytest.fail("default cap ignored"), 1)
        assert len(workers) == 2
    finally:
        release.set()
        calls.close()
        for worker in workers:
            worker.join(2)
    resource.unlink()
    with pytest.raises(sandbox_policy.SandboxConfigError):
        sandbox_policy.placement_driver_settings(env={})
    resource.write_text('invalid packaged TOML =')
    with pytest.raises(sandbox_policy.SandboxConfigError):
        sandbox_policy.placement_driver_settings(env={})


def test_driver_settings_trusted_base_and_unavailable_base(tmp_path):
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("init", "-b", "main")
    path = config.repo_board_config_path(repo)
    path.parent.mkdir()
    path.write_text('[sandbox.driver]\nadmit_wait_s = 43\n')
    # No base commit: candidate is ignored.
    assert sandbox_policy.placement_driver_settings(repo, env={}, review_base=True) == sandbox_policy.placement_driver_settings(env={})
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "base")
    path.write_text('[sandbox.driver]\nadmit_wait_s = 47\n')
    git("add", ".")
    assert sandbox_policy.placement_driver_settings(repo, env={}, review_base=True).admit_wait_s == 43
    assert sandbox_policy.placement_driver_settings(repo, env={}).admit_wait_s == 47


def test_valid_driver_subsection_is_accepted_by_shared_loaders(tmp_path):
    path = _write(str(tmp_path), '[sandbox.driver]\nadmit_wait_s = 53\n')
    assert config.load_sandbox_roots(path=path) == ()
    assert config.load_president_ladder(path=path, env={})
    assert load_boards(path, matrix=_MATRIX).names()


def test_driver_defaults_have_no_code_or_current_prose_duplicates():
    import ast
    import inspect
    import re
    from phase_loop_runtime import sandbox_placement as sp

    keys = r"(?:admit_wait_s|transfer_allowance_s|max_live_workers)"
    for module in (sandbox_policy, sp, config):
        source = inspect.getsource(module)
        assert not re.search(r"_DEFAULT_(?:ADMIT_WAIT_S|TRANSFER_ALLOWANCE_S|MAX_LIVE_WORKERS)", source)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if node.value is not None and any(re.search(keys, ast.unparse(target), re.I) for target in targets):
                    assert not any(isinstance(child, ast.Constant) and type(child.value) is int
                                   and child.value > 0 for child in ast.walk(node.value)), ast.unparse(node)
    for function in (sandbox_policy.admit_wait_s, sandbox_policy.transfer_allowance_s,
                     config.load_placement_driver_settings, sp._Calls.__init__):
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        assert not any(isinstance(node, ast.Constant) and type(node.value) is int
                       and node.value > 0 for node in ast.walk(tree))

    root = Path(__file__).resolve().parents[2]
    documents = [
        root / "docs/phase-loop/convergence-runtime.md",
        Path(config.__file__).with_name("CONTRACTS.md"),
        Path(config.__file__).parent / "fixtures/advisor-boards.example.toml",
        root / "CHANGELOG.md",
    ]
    for document in documents:
        text = document.read_text()
        if document.name == "CHANGELOG.md":
            text = text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        assert not re.search(keys + r"[^\n]{0,50}(?:default\s+|=\s*|\|\s*`)[0-9]+", text, re.I), document


if __name__ == "__main__":
    unittest.main()
