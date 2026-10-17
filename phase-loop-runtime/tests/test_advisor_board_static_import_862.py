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
import os
from pathlib import Path
import platform
import subprocess
import sys

settings = json.loads(sys.stdin.read())
root = Path(settings["module_root"])
sys.path.insert(0, str(root))
assert not any(n.startswith("phase_loop_runtime") for n in sys.modules)
platform.system = lambda: settings["platform"]
effects, admissions, callbacks, imports = [], [], [], []
permitted_git = None
permitted_git_spawn = None
execute_child_code = subprocess.Popen._execute_child.__code__
posix_spawn_code = subprocess.Popen._posix_spawn.__code__
callback_codes = set()

def audit(event, args):
    global permitted_git_spawn
    if event == "subprocess.Popen":
        permitted_git_spawn = None
        argv = list(args[1])
        effects.append({"event": event, "argv": argv})
        if permitted_git is not None and Path(argv[0]).name == "git" and Path(argv[0]).is_absolute():
            assert argv[1:] == ["--version"] or all(value in argv for value in (
                "--no-replace-objects", "core.hooksPath=/dev/null", "core.fsmonitor=false"))
            caller = sys._getframe(1)
            assert caller.f_code is execute_child_code, "unexpected subprocess caller"
            assert args[0] == argv[0], "unexpected subprocess executable"
            owner = caller.f_locals["self"]
            permitted_git_spawn = (owner, caller, args[0], tuple(argv), dict(args[3]), effects[-1])
            return
        raise AssertionError("unexpected subprocess effect")
    if event == "os.posix_spawn":
        caller = sys._getframe(1)
        permitted, permitted_git_spawn = permitted_git_spawn, None
        if permitted_git is not None and caller.f_code is posix_spawn_code and permitted is not None:
            owner = caller.f_locals["self"]
            ancestor = caller.f_back
            while ancestor is not None and ancestor is not permitted[1]:
                ancestor = ancestor.f_back
            if (permitted[0] is owner and ancestor is permitted[1] and
                    permitted[2] == args[0] == caller.f_locals["executable"] and
                    permitted[3] == tuple(args[1]) == tuple(caller.f_locals["args"]) and
                    permitted[4] == args[2] == caller.f_locals["env"]):
                permitted[5]["spawn_backend"] = "posix_spawn"
                return
    if event.startswith("socket.") or event in {
        "os.system", "os.posix_spawn", "os.fork", "os.forkpty", "os.exec",
    }:
        effects.append({"event": event})
        raise AssertionError("unexpected process or network effect: " + event)

def profile(frame, event, arg):
    global permitted_git_spawn
    if event == "return" and permitted_git_spawn is not None and frame is permitted_git_spawn[1]:
        permitted_git_spawn = None
    if event != "call":
        return
    if frame.f_code.co_name == "prepare_review_composition_authorization":
        admissions.append(frame.f_globals.get("__name__"))
    if frame.f_code in callback_codes:
        callbacks.append(frame.f_code.co_name)

def spawn_control(attack):
    global permitted_git, permitted_git_spawn
    permitted_git = ["git"]
    argv, env = ["/usr/bin/git", "--version"], {"PATH": "/usr/bin"}
    saved = {}

    class ProbePopen(subprocess.Popen):
        def _posix_spawn(self, args, executable, environment, *rest):
            saved.update(owner=self, args=(list(args), executable, dict(environment), *rest),
                         pending=permitted_git_spawn)
            if attack == "argv":
                args.append("--version")
            elif attack == "env":
                environment["STATIC_AUDIT_CONTROL"] = "changed"
            elif attack == "executable":
                executable = "/bin/true"
            elif attack == "owner":
                return subprocess.Popen._posix_spawn(
                    object.__new__(ProbePopen), args, executable, environment, *rest)
            elif attack == "missing":
                globals()["permitted_git_spawn"] = None
            super()._posix_spawn(args, executable, environment, *rest)
            if attack == "replay":
                os.waitpid(self.pid, 0)
                self.returncode = 0
                super()._posix_spawn(args, executable, environment, *rest)

    def launch(**kwargs):
        with ProbePopen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        close_fds=False, **kwargs) as child:
            child.communicate()
            assert child.returncode == 0

    if attack in {"fork-cleanup", "error-cleanup"}:
        if attack == "fork-cleanup":
            launch(preexec_fn=lambda: None)
            assert "spawn_backend" not in effects[-1]
        else:
            try:
                launch(cwd="/static-audit-missing-directory")
            except FileNotFoundError:
                pass
            else:
                raise AssertionError("missing cwd was accepted")
        assert permitted_git_spawn is None, "pending Git spawn survived owner return"
        record["control_passed"] = True
        return

    try:
        if attack in {"after", "stale", "closed"}:
            launch()
            assert permitted_git_spawn is None
        if attack == "stale":
            permitted_git_spawn = saved["pending"]
            subprocess.Popen._posix_spawn(saved["owner"], *saved["args"])
        elif attack == "forged":
            sys.audit("subprocess.Popen", argv[0], argv, None, env)
            sys.audit("os.posix_spawn", argv[0], argv, env)
        elif attack in {"before", "after", "non-git", "closed"}:
            if attack == "closed":
                permitted_git = None
            executable = "/bin/true" if attack == "non-git" else argv[0]
            pid = os.posix_spawn(executable, [executable, "--version"], env)
            os.waitpid(pid, 0)
        elif attack.startswith("forbidden-"):
            event = attack.removeprefix("forbidden-")
            if event == "subprocess.Popen":
                sys.audit(event, "/bin/true", ["/bin/true"], None, env)
            else:
                sys.audit(event)
        elif attack == "primary-executable":
            launch(executable="/bin/true")
        else:
            launch()
    except AssertionError as exc:
        assert str(exc).startswith(("unexpected process", "unexpected subprocess")), str(exc)
        assert permitted_git_spawn is None
        record["refusal"] = str(exc)
        record["control_passed"] = True
    else:
        raise AssertionError("forbidden spawn control was accepted: " + attack)

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

    if settings["case"] == "audit_control":
        spawn_control(settings["spawn_attack"])
        assert admissions == [] and callbacks == []
    elif settings["case"] == "static":
        expected = [
            ("grok-4.7", "high", "grok", "adversarial"),
            ("claude-opus-5-5", "high", "claude", "correctness"),
            ("gpt-6-astra", "high", "codex", "red-team"),
            ("gemini-4-argon", "medium", "gemini", "alternative-approach"),
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
            if settings["forged_spawn"]:
                def forge_spawn(event, args):
                    if event == "subprocess.Popen":
                        os.posix_spawn(args[0], args[1], args[3])

                sys.addaudithook(forge_spawn)
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
    if settings["case"] == "audit_control":
        assert record["control_passed"]
    elif permitted_git is None:
        assert effects == [], effects
    else:
        assert effects and all(row["event"] == "subprocess.Popen" for row in effects)
        assert any("--show-toplevel" in row["argv"] for row in effects)
    record["passed"] = True
finally:
    permitted_git = permitted_git_spawn = None
    sys.setprofile(None)
    Path(settings["receipt"]).write_text(json.dumps(record, indent=2) + "\n")
'''


def _probe(tmp_path, platform_policy, case, *, forged_spawn=False, spawn_attack=None):
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
                    platform=platform_policy, case=case, receipt=str(receipt),
                    forged_spawn=forged_spawn, spawn_attack=spawn_attack)
    (tmp_path / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-I", str(script)], input=json.dumps(settings),
        capture_output=True, text=True, env=env, timeout=30,
    )
    (tmp_path / "stdout.txt").write_text(completed.stdout)
    (tmp_path / "stderr.txt").write_text(completed.stderr)
    if forged_spawn:
        assert completed.returncode != 0
        assert "unexpected process or network effect: os.posix_spawn" in completed.stderr
        result = json.loads(receipt.read_text())
        assert result["imports_complete"] and not result.get("passed")
        assert result["effects"][-1]["event"] == "os.posix_spawn"
        return
    assert completed.returncode == 0, completed.stderr
    result = json.loads(receipt.read_text())
    assert result["passed"] and result["imports_complete"]
    return result


@pytest.mark.parametrize("platform_policy", ["Linux", "Darwin"])
def test_static_imports_are_pure_and_preserve_boards_and_scrubber(tmp_path, platform_policy):
    _probe(tmp_path, platform_policy, "static")


@pytest.mark.parametrize("case", [
    "bare", "availability_only", "registry_availability", "default_auth", "config",
    "factory", "public",
])
def test_static_imports_do_not_admit_live_review_on_darwin(tmp_path, case):
    result = _probe(tmp_path, "Darwin", case)
    if case == "public" and hasattr(os, "POSIX_SPAWN_CLOSEFROM") and subprocess._USE_POSIX_SPAWN:
        assert any(row.get("spawn_backend") == "posix_spawn" for row in result["effects"])


def test_static_audit_rejects_a_direct_spawn_during_an_allowed_git_probe(tmp_path):
    _probe(tmp_path, "Darwin", "public", forged_spawn=True)


@pytest.mark.parametrize("attack", [
    "before", "after", "non-git", "closed", "forged", "stale", "missing",
    "primary-executable", "executable", "argv", "env", "owner", "replay", "fork-cleanup", "error-cleanup",
    "forbidden-subprocess.Popen", "forbidden-socket.connect", "forbidden-os.system",
    "forbidden-os.fork", "forbidden-os.forkpty", "forbidden-os.exec",
])
def test_static_audit_preserves_process_refusals_and_scope_cleanup(tmp_path, attack):
    _probe(tmp_path, "Darwin", "audit_control", spawn_attack=attack)
