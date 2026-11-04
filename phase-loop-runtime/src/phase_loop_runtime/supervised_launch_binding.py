"""Explicit operator bindings; no discovery, ambient imports or default codec."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from types import ModuleType
from typing import Callable

from .supervised_launch import (
    LaunchConfig, Refused, Validator, _Refusal, _json, _require, sha256, trusted_bytes,
)


@dataclass(frozen=True)
class ValidatorBinding:
    validator: Validator
    decoder: Callable
    config: LaunchConfig
    binding_digest: str
    implementation_digests: tuple[str, str]


def _load_absolute(path: Path, data: bytes) -> ModuleType:
    # Execute exactly the verified bytes; importlib loaders can reread a swapped path
    # or prefer a stale bytecode cache. Isolated Python supplies transitive imports.
    module = ModuleType("_supervised_binding_" + sha256(data))
    module.__file__ = str(path)
    exec(compile(data, str(path), "exec"), module.__dict__)
    return module


def load_validator_binding(path: Path | None, *, workspace: Path, target: Path) -> ValidatorBinding | Refused:
    """Load only in the trusted installed interpreter's isolated (-I) mode.

    WORKER must call route preflight before this API or any envelope file read.
    The callable injection API in supervised_launch remains available offline.
    """
    try:
        _require(sys.flags.isolated, "isolated_python_required")
        _require(path is not None, "binding_unavailable")
        excluded = (workspace, target)
        raw = trusted_bytes(path, excluded=excluded)
        binding = _json(raw)
        _require(set(binding) == {"validator", "codec", "config", "template", "qualification"}, "binding_fields")
        config = LaunchConfig(Path(binding["config"]), Path(binding["template"]),
                              Path(binding["qualification"]) if binding["qualification"] else None)
        settings = _json(trusted_bytes(config.config_path, excluded=excluded))
        excluded += tuple(Path(root) for root in settings["reference_roots"])
        trusted_bytes(path, excluded=excluded)
        trusted_bytes(config.config_path, excluded=excluded)
        trusted_bytes(config.template_path, excluded=excluded)
        if config.qualification_path is not None:
            trusted_bytes(config.qualification_path, excluded=excluded)
        functions = []
        digests = []
        for kind, symbol in (("validator", "validate"), ("codec", "decode")):
            path = Path(binding[kind])
            data = trusted_bytes(path, excluded=excluded)
            module = _load_absolute(path, data)
            function = getattr(module, symbol, None)
            _require(callable(function), "binding_callable")
            functions.append(function)
            digests.append(sha256(data))
        return ValidatorBinding(functions[0], functions[1], config, sha256(raw), tuple(digests))
    except Exception as exc:
        return Refused(str(exc) if isinstance(exc, _Refusal) else "binding_invalid")
