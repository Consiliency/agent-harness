"""Console-script coverage (agent-harness#542).

The smoke suites used to invoke `codex-phase-loop` and `phase-loop` by bare name,
so a broken or missing console script surfaced as a test failure. Those call sites
are now interpreter-anchored (`sys.executable -m phase_loop_runtime.cli`), which is
the right call -- resolving a repo-shipped entry point through ambient PATH is a
hidden precondition, and it is what broke when execution moved into containers.

But the conversion would leave the console scripts with NO coverage anywhere: Gate
A's clean-room probe exercises `phase-loop` only, and nothing at all would notice
`codex-phase-loop` disappearing from `[project.scripts]`. This file is the
replacement.

Two arms, because the two postures can disagree and both matter:

* **Declaration** -- the checkout's `pyproject.toml` must declare both scripts,
  pointing at a real callable. Always runs; a source checkout is enough.
* **Installation** -- when the distribution is installed, its recorded metadata
  must carry both as `console_scripts`. This is what would actually catch a build
  backend silently dropping one. Skipped in an installed-wheel clean room that has
  no distribution to interrogate, rather than passing vacuously.

Mutation-coupled: delete either line from `[project.scripts]` and the declaration
arm fails; both names are asserted by name, not counted.
"""

from __future__ import annotations

import importlib
import inspect
import importlib.metadata as importlib_metadata
from pathlib import Path

import pytest

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # 3.10 backport (a dev/test dependency)
    import tomli as tomllib

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = PACKAGE_ROOT / "pyproject.toml"
DISTRIBUTION = "phase-loop-runtime"

# Both names are load-bearing: `phase-loop` is the neutral entry point Gate A's
# clean-room probe drives, and `codex-phase-loop` is the name the fleet's installed
# shims and the smoke fixtures historically used.
#
# `roadmap-ownership` is load-bearing for a third reason: under `uv tool install`
# isolation the module form fails to import and exits 1, which `--preflight`
# defines as "claimed by another phase" -- so losing the script turns the guard
# into a phantom block on every path rather than a visible breakage (ah#633).
REQUIRED_SCRIPTS = ("phase-loop", "codex-phase-loop", "roadmap-ownership")


def _declared_scripts() -> dict[str, str]:
    if not PYPROJECT.is_file():
        pytest.skip("no pyproject.toml in this tree (installed-consumer posture)")
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["scripts"]


@pytest.mark.parametrize("script", REQUIRED_SCRIPTS)
def test_pyproject_declares_the_console_script(script: str) -> None:
    scripts = _declared_scripts()
    assert script in scripts, (
        f"[project.scripts] must declare {script!r}; the smoke suites no longer "
        f"invoke it by name, so this file is its only remaining guard. Declared: "
        f"{sorted(scripts)}"
    )


@pytest.mark.parametrize("script", REQUIRED_SCRIPTS)
def test_declared_console_script_target_is_importable_and_callable(script: str) -> None:
    """A declared entry point pointing at nothing is a script that fails at runtime."""
    target = _declared_scripts()[script]
    module_path, _, attribute = target.partition(":")
    assert attribute, f"{script} target {target!r} names no callable"
    module = importlib.import_module(module_path)
    assert callable(getattr(module, attribute, None)), (
        f"{script} points at {target!r}, which is not a callable on the imported module"
    )


@pytest.mark.parametrize("script", REQUIRED_SCRIPTS)
def test_declared_console_script_target_is_invocable_with_no_arguments(script: str) -> None:
    """Callable is not enough: a console script is invoked with NO arguments.

    `importlib` resolving the attribute proves it exists, not that it can be
    CALLED the way a launcher calls it. Declaring `...:main` for a `main(argv)`
    satisfies every other arm here and then raises TypeError on first use --
    visible only to whoever runs the installed command. `phase-loop` survives
    because its `main` defaults `argv=None`; a target without that default would
    not, and nothing said so until now.

    Mutation that must kill this: point any REQUIRED_SCRIPTS entry at a callable
    taking a required positional argument.
    """
    target = _declared_scripts()[script]
    module_path, _, attribute = target.partition(":")
    function = getattr(importlib.import_module(module_path), attribute)
    required = [
        parameter.name
        for parameter in inspect.signature(function).parameters.values()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            # A required KEYWORD_ONLY parameter is just as fatal under a launcher
            # that passes nothing, and omitting it here let one through.
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]
    assert not required, (
        f"{script} points at {target!r}, which requires {required}; a "
        f"[project.scripts] launcher passes no arguments, so this fails at runtime"
    )


@pytest.mark.parametrize("script", REQUIRED_SCRIPTS)
def test_installed_distribution_records_the_console_script(script: str) -> None:
    try:
        distribution = importlib_metadata.distribution(DISTRIBUTION)
    except importlib_metadata.PackageNotFoundError:
        pytest.skip(f"{DISTRIBUTION} is not installed in this interpreter")
    console_scripts = {
        entry.name
        for entry in distribution.entry_points
        if entry.group == "console_scripts"
    }
    assert script in console_scripts, (
        f"the installed {DISTRIBUTION} records console_scripts {sorted(console_scripts)}, "
        f"missing {script!r} -- an install that drops it breaks every consumer that "
        f"invokes the script by name, including Gate A's clean-room probe."
    )
