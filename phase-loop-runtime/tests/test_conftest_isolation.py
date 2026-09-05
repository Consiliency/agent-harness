"""The suite-wide host-state isolation fixture (Consiliency/agent-harness#779).

Deleting ``_isolate_host_state`` from ``conftest.py`` must red these nodes on any
host carrying either leak (an ACTIVE fabpub bootstrap under ``$XDG_STATE_HOME``,
or a ``GEMINI_*``/``AGY_*``/``XDG_CONFIG_*`` export). Run with e.g.
``GEMINI_POISON=1`` and ``PHASE_LOOP_FABPUB_AUTHORITY_ROOT`` unset to falsify.
"""
from __future__ import annotations

import os
from pathlib import Path

from phase_loop_runtime.agy_canary_evidence import (
    _CUSTOMIZATION_ENV_EXEMPT,
    _CUSTOMIZATION_ENV_PREFIXES,
    inventory_customizations,
)
from phase_loop_runtime.convergence.broker.live import (
    FABPUB_AUTHORITY_ROOT_ENV,
    default_fabpub_authority_root,
)


def test_fabpub_authority_root_is_pinned_to_an_empty_tmp_dir(tmp_path: Path) -> None:
    pinned = os.environ.get(FABPUB_AUTHORITY_ROOT_ENV)
    assert pinned, f"{FABPUB_AUTHORITY_ROOT_ENV} must be set per test"
    root = Path(pinned)
    assert root.is_dir()
    assert not any(root.iterdir()), "isolated authority root must carry no bootstrap"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    assert default_fabpub_authority_root() == root.resolve()


def test_customization_env_prefixes_are_absent_from_the_real_environment(tmp_path: Path) -> None:
    leaked = sorted(
        name for name in os.environ
        if name.startswith(_CUSTOMIZATION_ENV_PREFIXES) and name not in _CUSTOMIZATION_ENV_EXEMPT
    )
    assert leaked == []
    # The production default path (env=None -> os.environ) must see a clean host.
    found = inventory_customizations(home=tmp_path, project_dir=None, env=None)
    assert found["environment_overrides"] == []


def test_isolation_does_not_mask_an_explicit_poison(monkeypatch, tmp_path: Path) -> None:
    """A test that sets a customization name itself still trips the guard."""
    import pytest
    from phase_loop_runtime.agy_canary_evidence import AgyCanaryEvidenceError

    monkeypatch.setenv("GEMINI_ISOLATION_PROBE", "1")
    with pytest.raises(AgyCanaryEvidenceError, match="customization source"):
        inventory_customizations(home=tmp_path, project_dir=None, env=None)
