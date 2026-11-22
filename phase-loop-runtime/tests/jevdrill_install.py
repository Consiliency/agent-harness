"""Resolve and preflight the installed JEV Drill the installed-JEV tests use.

JEVHOST §6 [C1] [C2]. ``conftest.py`` skips a ``jevdrill_installed`` test only when
neither ``JEVDRILL_TEST_CLI`` nor ``JEVDRILL_TEST_PYTHON`` is set. Once either is set,
the test runs, and ``resolve_install()`` validates the installation before any use. A
configured but missing, non-executable or wrong installation **fails** the test with a
message naming the variable and the reason. This module never skips.

Derivation:

- only ``JEVDRILL_TEST_PYTHON``: the CLI argv is ``[<python>, "-m", "jevdrill.cli"]``;
- only ``JEVDRILL_TEST_CLI``: the interpreter is the ``python`` (``python.exe``) beside
  the CLI;
- both: both are used as given, and they must come from one install (the same
  ``sys.prefix``).

On native Windows the CLI argv is the interpreter's ``-m jevdrill.cli`` form, as the
draft's route test used.

JEV Drill's CLI at the pinned commit has no schema, version or digest command, and its
wheel ships no ``schemas/``. The pin check is the companion workflow's checkout
comparison. The digest comparison here is best-effort only: it runs when
``jevdrill.__file__`` resolves inside a source tree that has ``schemas/`` (an editable
install), and it is never a skip path.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ENV_CLI = "JEVDRILL_TEST_CLI"
ENV_PYTHON = "JEVDRILL_TEST_PYTHON"
USAGE_PREFIX = "usage: jevdrill"
FIXTURES = Path(__file__).parent / "fixtures" / "jevdrill"
_TIMEOUT_SECONDS = 60
_PROBE = (
    "import json, sys\n"
    "import jevdrill\n"
    "print(json.dumps({'prefix': sys.prefix, 'file': getattr(jevdrill, '__file__', None)}))\n"
)
_PREFIX_PROBE = "import sys; print(sys.prefix)"


@dataclass(frozen=True)
class JevDrillInstall:
    """A preflighted JEV Drill installation."""

    python: str
    cli_argv: tuple[str, ...]
    prefix: str
    package_file: str | None


def _fail(variable: str, reason: str) -> None:
    pytest.fail(f"JEV Drill install preflight: {variable}: {reason}", pytrace=False)


def _sibling_python(cli: str) -> Path:
    name = "python.exe" if os.name == "nt" else "python"
    return Path(cli).parent / name


def _check_executable(variable: str, label: str, path: str) -> None:
    candidate = Path(path)
    if not path or not candidate.exists():
        _fail(variable, f"{label} {path!r} does not exist")
    if not candidate.is_file():
        _fail(variable, f"{label} {path!r} is not a file")
    if not os.access(candidate, os.X_OK):
        _fail(variable, f"{label} {path!r} is not executable")


def _run(variable: str, label: str, argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        _fail(variable, f"{label} did not answer within {_TIMEOUT_SECONDS}s")
    except OSError as exc:
        _fail(variable, f"{label} could not start: {exc}")
    raise AssertionError("unreachable")


def _probe_python(variable: str, python: str) -> dict:
    done = _run(variable, f"interpreter {python!r}", [python, "-I", "-c", _PROBE])
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()[-1:] or [""]
        _fail(variable, f"interpreter {python!r} cannot import jevdrill (exit {done.returncode}: {detail[0]})")
    try:
        value = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        _fail(variable, f"interpreter {python!r} gave an unreadable import probe")
    return value


def _prefix_of(variable: str, python: str) -> str:
    done = _run(variable, f"interpreter {python!r}", [python, "-I", "-c", _PREFIX_PROBE])
    if done.returncode != 0:
        _fail(variable, f"interpreter {python!r} cannot report sys.prefix (exit {done.returncode})")
    return done.stdout.strip()


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def _check_cli(variable: str, argv: tuple[str, ...]) -> None:
    done = _run(variable, f"CLI {list(argv)!r}", [*argv, "--help"])
    if done.returncode != 0:
        _fail(variable, f"CLI {list(argv)!r} --help exited {done.returncode}, so it is not JEV Drill")
    if not done.stdout.startswith(USAGE_PREFIX):
        _fail(variable, f"CLI {list(argv)!r} --help output does not start with {USAGE_PREFIX!r}, "
                        "so it is not JEV Drill")


def _check_editable_digests(variable: str, package_file: str | None) -> None:
    """Best-effort: compare an editable install's schemas with the synced digests."""
    if not package_file:
        return
    expected = json.loads((FIXTURES / "digests.json").read_text(encoding="utf-8"))
    for parent in list(Path(package_file).resolve().parents)[:4]:
        schemas = parent / "schemas"
        if not (schemas.is_dir() and (parent / "pyproject.toml").is_file()):
            continue
        mismatched = sorted(
            name for name, digest in expected.items()
            if not (schemas / name).is_file()
            or hashlib.sha256((schemas / name).read_bytes()).hexdigest() != digest
        )
        if mismatched:
            _fail(variable, f"contract mismatch: the source tree at {str(parent)!r} has schemas that "
                            f"differ from tests/fixtures/jevdrill/digests.json: {', '.join(mismatched)}")
        return


def resolve_install(environ: dict[str, str] | None = None) -> JevDrillInstall:
    """Derive and preflight the installation named by the two variables, or fail."""
    env = os.environ if environ is None else environ
    cli = env.get(ENV_CLI)
    python = env.get(ENV_PYTHON)
    if cli is None and python is None:
        _fail(f"{ENV_CLI} and {ENV_PYTHON}", "neither is set; only conftest may skip an installed-JEV test")

    # The paths as given first, then the derived ones.
    if cli is not None:
        _check_executable(ENV_CLI, "CLI", cli)
    if python is not None:
        python_var = ENV_PYTHON
        _check_executable(ENV_PYTHON, "interpreter", python)
    else:
        python_var = ENV_CLI
        python = str(_sibling_python(cli))
        _check_executable(ENV_CLI, "derived interpreter (beside the CLI)", python)

    if cli is not None:
        cli_var = ENV_CLI
        if os.name == "nt":
            sibling = str(_sibling_python(cli))
            _check_executable(ENV_CLI, "derived interpreter (beside the CLI)", sibling)
            cli_argv: tuple[str, ...] = (sibling, "-m", "jevdrill.cli")
        else:
            cli_argv = (cli,)
    else:
        cli_var = ENV_PYTHON
        cli_argv = (python, "-m", "jevdrill.cli")

    probe = _probe_python(python_var, python)
    _check_cli(cli_var, cli_argv)

    if cli is not None and env.get(ENV_PYTHON) is not None:
        siblings = [_sibling_python(cli), _sibling_python(str(Path(cli).resolve()))]
        sibling = next((str(path) for path in siblings if path.is_file() and os.access(path, os.X_OK)), None)
        if sibling is None:
            _fail(ENV_CLI, f"no interpreter beside the CLI {cli!r}, so one install with {ENV_PYTHON} "
                           "cannot be confirmed")
        cli_prefix = _prefix_of(ENV_CLI, sibling)
        if not _same_path(cli_prefix, probe["prefix"]):
            _fail(ENV_CLI, f"mixed pair: the CLI's interpreter has sys.prefix {cli_prefix!r}, but "
                           f"{ENV_PYTHON} has {probe['prefix']!r}")

    _check_editable_digests(python_var, probe.get("file"))
    return JevDrillInstall(python=python, cli_argv=cli_argv, prefix=probe["prefix"],
                           package_file=probe.get("file"))
