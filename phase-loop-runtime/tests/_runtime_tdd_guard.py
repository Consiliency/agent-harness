"""RUNTIME SL-0 tests-only guard: lazy capability probes and typed RED anchors.

This module is test/support bytes only. It never imports a production capability
eagerly, never creates production capability markers, and never edits production.

Default mode (``PHASE_LOOP_TDD_EXPECT_RUNTIME`` unset) skips a mapped case only
when its lazily probed capability is absent. Activated mode turns that same
absence into a single typed ``RUNTIME-RED-ANCHOR::<case>`` assertion carrying the
generic recorder's frozen ``RED_ANCHOR_MARKER``.

A broken path-entered control -- an unresolvable production symbol, a symbol
whose source file is not the declared production path, or a missing/duplicated
anchor -- is a hard failure in *both* modes. It is never RED evidence.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import subprocess
import sysconfig
from pathlib import Path
from typing import Callable, Iterable

import pytest

from phase_loop_runtime.tdd_receipts import RED_ANCHOR_MARKER

RUNTIME_ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_RUNTIME"
RUNTIME_RED_ANCHOR_PREFIX = "RUNTIME-RED-ANCHOR::"

#: Broker symbols an SL-0 test/support byte may never import. RUNTIME performs no
#: credential-bearing broker effect, so naming these here is the enforced fence.
FORBIDDEN_BROKER_SYMBOLS: tuple[str, ...] = (
    "GitHubBrokerAdapter",
    "BrokerEnvironmentBoundary",
    "BrokerProviderAdapter",
    "BrokerClient",
    "BrokerService",
    "build_github_broker_client",
    "build_routing_broker_client",
    "publish_committed_branch_idempotency_key",
)

#: Pure, non-credential-bearing helpers RUNTIME is explicitly permitted to import
#: even though they live beneath a broker module prefix. No module-prefix ban may
#: reject these, so the fence is symbol-scoped rather than prefix-scoped.
PERMITTED_BROKER_MODULE_SYMBOLS: tuple[str, ...] = (
    "strip_mutation_credentials",
    "MUTATION_CREDENTIAL_KEYS",
    "REPO_REDIRECT_KEYS",
)


class RuntimeCapabilityMissing(Exception):
    """Raised by a RUNTIME falsifier probe when the expected capability is absent."""


def runtime_red_active() -> bool:
    """True when RUNTIME RED mode is activated through the environment."""

    return os.environ.get(RUNTIME_ACTIVATION_ENV) == "1"


def runtime_red_message(case_id: str) -> str:
    """The unique typed RED anchor emitted for ``case_id``."""

    return f"{RUNTIME_RED_ANCHOR_PREFIX}{case_id}"


def repo_root() -> Path:
    """Absolute repository root, resolved through git rather than path arithmetic."""

    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parent,
    )
    return Path(completed.stdout.strip()).resolve()


def _dotted_module(production_path: str) -> str:
    relative = production_path.split("phase-loop-runtime/src/", 1)[-1]
    return relative[: -len(".py")].replace("/", ".")


def resolve_production_symbol(production_path: str, symbol: str) -> tuple[object, str]:
    """Import ``production_path`` and resolve ``symbol``, returning it and its source.

    Entering the real module and resolving the real attribute is the path-entered
    control: a case that cannot reach its production construction site fails hard
    instead of quietly recording a RED anchor it never earned.
    """

    module = importlib.import_module(_dotted_module(production_path))
    obj: object = module
    for part in symbol.split("."):
        obj = getattr(obj, part)
    source_file = inspect.getsourcefile(obj)
    assert source_file is not None, f"{production_path}::{symbol} has no resolvable source file"
    resolved = Path(source_file).resolve()
    source_relative = Path(production_path.split("phase-loop-runtime/src/", 1)[-1])
    checkout_path = (repo_root() / production_path).resolve()
    expected_paths = {checkout_path}
    for scheme_path in ("purelib", "platlib"):
        library_root = sysconfig.get_path(scheme_path)
        if library_root:
            expected_paths.add((Path(library_root) / source_relative).resolve())
    assert resolved in expected_paths, (
        f"{symbol} resolves to {resolved}, not the declared production path in "
        f"{sorted(str(path) for path in expected_paths)}"
    )
    if resolved != checkout_path:
        assert resolved.read_bytes() == checkout_path.read_bytes(), (
            f"installed {symbol} source bytes differ from the reviewed checkout path "
            f"{checkout_path}"
        )
    return obj, inspect.getsource(obj)


def enter_production_symbol(case_id: str, production_path: str, symbol: str, anchor: str) -> str:
    """Enter the production symbol and validate this case's unique typed anchor.

    This is the EC-RUNTIME-0 path-entered control: the case records its exact
    resolved production symbol -- imported from the real module and proven to be
    defined in the declared production file, never a re-export, test, helper, or
    guard -- *before* its unique assertion is allowed to fire.

    The anchor is the case's unique typed RED marker, deliberately not a snapshot
    of a production source line: SL-1/SL-2/SL-3 must be free to rewrite the very
    lines they repair, and SL-0 is immutable after its landing.
    """

    assert anchor == f"{RUNTIME_RED_ANCHOR_PREFIX}{case_id}", (
        f"{case_id}: anchor {anchor!r} is not this case's unique typed marker"
    )
    file_path = repo_root() / production_path
    assert file_path.is_file(), f"declared production path is absent: {production_path}"
    _obj, source = resolve_production_symbol(production_path, symbol)
    return source


def run_runtime_case(
    case_id: str,
    *,
    production_path: str,
    symbol: str,
    anchor: str,
    probe: Callable[[], None],
    assertion: Callable[[], None],
) -> None:
    """Run one mapped RUNTIME falsifier under the default/activated contract.

    ``probe`` raises :class:`RuntimeCapabilityMissing` when the production
    capability this case falsifies is still absent. ``assertion`` carries the
    real behavioural claim and runs unchanged in both modes once the capability
    exists, so a landed repair is proven by the same bytes that recorded RED.
    """

    enter_production_symbol(case_id, production_path, symbol, anchor)
    try:
        probe()
    except RuntimeCapabilityMissing as exc:
        if runtime_red_active():
            raise AssertionError(f"{RED_ANCHOR_MARKER} {runtime_red_message(case_id)}") from exc
        pytest.skip(f"RUNTIME capability absent for {case_id}: {exc}")
    assertion()


def require_source_capability(production_path: str, symbol: str, needle: str) -> None:
    """Probe helper: the capability is absent until ``needle`` enters ``symbol``.

    Used only where the repair is observable exclusively through a call the
    skeleton never makes. The mapped case still asserts the *behaviour*; this
    probe only decides skip-versus-RED.
    """

    _obj, source = resolve_production_symbol(production_path, symbol)
    if needle not in source:
        raise RuntimeCapabilityMissing(f"{production_path}::{symbol} does not yet use {needle}")


def _imported_symbols(path: Path) -> Iterable[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                yield module, alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, alias.name.rsplit(".", 1)[-1]


def assert_no_forbidden_broker_imports(paths: Iterable[str]) -> None:
    """Fail if any SL-0 byte imports a forbidden broker symbol.

    The fence is symbol-scoped on purpose: RUNTIME requires the pure
    ``credsep`` scrubber, which lives under the broker package, so a
    module-prefix ban would reject a required import.
    """

    root = repo_root()
    violations: list[str] = []
    for relative in paths:
        path = root / relative
        for module, name in _imported_symbols(path):
            if name in PERMITTED_BROKER_MODULE_SYMBOLS:
                continue
            if name in FORBIDDEN_BROKER_SYMBOLS:
                violations.append(f"{relative}: {module}.{name}")
    assert not violations, f"SL-0 bytes import forbidden broker symbols: {violations}"
