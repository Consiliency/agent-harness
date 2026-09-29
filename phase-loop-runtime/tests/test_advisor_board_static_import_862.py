"""Static imports must not acquire the authority required by live review calls."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


_CHILD = r'''
from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys

settings = json.loads(sys.stdin.read())
root = Path(settings["module_root"])
sys.path.insert(0, str(root))
assert not any(n.startswith("phase_loop_runtime") for n in sys.modules)
platform.system = lambda: settings["platform"]
effects, admissions, callbacks, imports = [], [], [], []
permitted_git = None
callback_codes = set()

def audit(event, args):
    if event == "subprocess.Popen":
        argv = list(args[1])
        effects.append({"event": event, "argv": argv})
        if permitted_git is not None and argv == permitted_git:
            return
        raise AssertionError("unexpected subprocess effect")
    if event.startswith("socket.") or event in {
        "os.system", "os.posix_spawn", "os.fork", "os.forkpty", "os.exec",
    }:
        effects.append({"event": event})
        raise AssertionError("unexpected process or network effect: " + event)

def profile(frame, event, arg):
    if event != "call":
        return
    if frame.f_code.co_name == "prepare_review_composition_authorization":
        admissions.append(frame.f_globals.get("__name__"))
    if frame.f_code in callback_codes:
        callbacks.append(frame.f_code.co_name)

sys.addaudithook(audit)
sys.setprofile(profile)
record = {"effects": effects, "admissions": admissions, "callbacks": callbacks,
          "imports": imports, "platform_policy": settings["platform"]}
try:
    for name in (
        "phase_loop_runtime.convergence",
        "phase_loop_runtime.advisor_board.backing",
        "phase_loop_runtime.advisor_board.presets",
        "phase_loop_runtime.advisor_board.resolver",
    ):
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        relative = str(path.relative_to(root))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == settings["module_hashes"][relative], name
        imports.append({"module": name, "path": str(path), "sha256": digest})
    record["imports_complete"] = True
    assert effects == [], effects

    from phase_loop_runtime.advisor_board import backing, composition, config
    from phase_loop_runtime.advisor_board import fixtures, presets, resolver
    from phase_loop_runtime.advisor_board.registries import DEFAULT_HARNESS_REGISTRY

    if settings["case"] == "static":
        expected = [
            ("grok-4.7", "max", "grok", "adversarial"),
            ("claude-opus-5-5", "max", "claude", "correctness"),
            ("gpt-6-astra", "max", "codex", "red-team"),
            ("gemini-3.8-flash", "high", "gemini", "alternative-approach"),
        ]
        seats = [dict(model=model, effort=effort, harness=harness, lens=lens,
                      auth="subscription", backing="homebrew", host_leg=False)
                 for model, effort, harness, lens in expected]
        for board in (presets.CODE_REVIEW_BOARD, resolver._STANDIN_CODE_REVIEW):
            assert board.name == "code-review" and board.purpose == "code-review"
            assert [asdict(seat) for seat in board.seats] == seats
        assert presets.PRESETS["default"] is fixtures.DEFAULT_BOARD
        assert resolver.STANDIN_BOARDS[fixtures.DEFAULT_BOARD.name] is fixtures.DEFAULT_BOARD
        source_env = {key: "test-only" for key in (
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
            "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
        )}
        source_env["PATH"] = "/usr/bin"
        original = dict(source_env)
        assert backing.scrub_subscription_env(source_env) == {"PATH": "/usr/bin"}
        assert source_env == original
        record["static_data_checks_passed"] = True
        assert admissions == [], admissions
    else:
        def available(vendor):
            return True

        def authenticated(vendor):
            return True

        callback_codes.update({
            available.__code__, authenticated.__code__,
            composition.default_board_auth_ok.__code__,
            type(DEFAULT_HARNESS_REGISTRY).is_available.__code__,
        })
        case = settings["case"]
        composition_calls = {
            "bare": lambda: composition.compose_review_board(),
            "availability_only": lambda: composition.compose_review_board(is_available=available),
            "registry_availability": lambda: composition.compose_review_board(
                is_available=DEFAULT_HARNESS_REGISTRY.is_available, auth_ok=authenticated),
            "default_auth": lambda: composition.compose_review_board(
                is_available=available, auth_ok=composition.default_board_auth_ok),
            "config": lambda: config.load_boards(is_available=available, auth_ok=authenticated),
        }
        if case in composition_calls:
            try:
                composition_calls[case]()
            except ValueError as exc:
                assert str(exc) == "HARDEN review composition requires Linux"
                record["refusal"] = str(exc)
            else:
                raise AssertionError("live composition was admitted on Darwin")
        elif case == "factory":
            try:
                backing.prepare_review_isolation_authorization(
                    presets.CODE_REVIEW_BOARD, "Static import refusal control.", mode="review")
            except ValueError as exc:
                assert str(exc) == "HARDEN review isolation requires a Linux review operation"
                record["refusal"] = str(exc)
            else:
                raise AssertionError("live isolation was admitted on Darwin")
        else:
            assert case == "public"
            from phase_loop_runtime import panel_invoker
            repo = Path.cwd()
            permitted_git = ["git", "-C", str(repo), "rev-parse", "--show-toplevel"]
            result = panel_invoker.invoke_board(
                presets.CODE_REVIEW_BOARD, "Static import refusal control.",
                repo_dir=repo, mode="review",
                review_policy=panel_invoker.ReviewLandingPolicy(
                    required_seats=("fable", "sol", "gemini", "grok"), requires_president=False),
            )
            rows = [dict(leg=leg.leg, seat_key=leg.seat_key, status=leg.status,
                         usable=leg.usable, detail=leg.detail) for leg in result.legs]
            record["legs"] = rows
            assert [row["seat_key"] for row in rows] == [s.seat_key for s in presets.CODE_REVIEW_BOARD.seats]
            assert all(row["status"] == "UNAVAILABLE" and not row["usable"] and
                       row["detail"] == "HARDEN review isolation requires a Linux review operation"
                       for row in rows)
        assert callbacks == [], callbacks
    expected_effects = ([] if permitted_git is None else
                        [{"event": "subprocess.Popen", "argv": permitted_git}])
    assert effects == expected_effects, effects
    record["passed"] = True
finally:
    sys.setprofile(None)
    Path(settings["receipt"]).write_text(json.dumps(record, indent=2) + "\n")
'''


def _probe(tmp_path, platform_policy, case):
    spec = importlib.util.find_spec("phase_loop_runtime")
    root = Path(spec.origin).resolve().parent.parent
    module_hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "phase_loop_runtime").rglob("*.py")
    }
    script = tmp_path / "probe.py"
    script.write_text(_CHILD)
    receipt = tmp_path / "receipt.json"
    settings = dict(module_root=str(root), module_hashes=module_hashes,
                    platform=platform_policy, case=case, receipt=str(receipt))
    (tmp_path / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-I", str(script)], input=json.dumps(settings),
        capture_output=True, text=True, env=env, timeout=30,
    )
    (tmp_path / "stdout.txt").write_text(completed.stdout)
    (tmp_path / "stderr.txt").write_text(completed.stderr)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(receipt.read_text())
    assert result["passed"] and result["imports_complete"]


@pytest.mark.parametrize("platform_policy", ["Linux", "Darwin"])
def test_static_imports_are_pure_and_preserve_boards_and_scrubber(tmp_path, platform_policy):
    _probe(tmp_path, platform_policy, "static")


@pytest.mark.parametrize("case", [
    "bare", "availability_only", "registry_availability", "default_auth", "config",
    "factory", "public",
])
def test_static_imports_do_not_admit_live_review_on_darwin(tmp_path, case):
    _probe(tmp_path, "Darwin", case)
