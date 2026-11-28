"""Explicit Claude and Gemini qualification using the production route key."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path

from . import seat_egress_proxy, seat_jail, seat_jail_qualification as reducer
from .executable_dependency import ExecutableDependencyError
from .seat_profiles import profile_for
from .seat_qualification_key import key_for_launch


def _explicit_route_key(profile, env):
    from .seat_route import _allowlist_digest_for_launch, _projection_for_launch

    variant = None
    if profile.variant is not None:
        variant, code = profile.variant(env)
        if code is not None:
            raise reducer.QualificationError(code)
    try:
        allowlist_digest = _allowlist_digest_for_launch(profile)
        projection = _projection_for_launch(profile, env)
    except seat_egress_proxy.EgressLayerUnavailable as exc:
        raise reducer.QualificationError(exc.code) from exc
    except FileNotFoundError as exc:
        raise reducer.QualificationError("seat_provider_unavailable") from exc
    except ExecutableDependencyError as exc:
        raise reducer.QualificationError(seat_jail.refused("identity")) from exc
    return key_for_launch(profile, variant=variant, allowlist_digest=allowlist_digest,
                          projection=projection)


def qualify(leg: str = "claude", *, _mutate_jail=None) -> dict[str, object]:
    """Run the frozen falsifiers with the resolved launch subject and record an exact pass."""
    from . import panel_invoker

    key = None
    env = dict(os.environ)
    with ExitStack() as resources:
        def resolve_probe_subject(probe_leg):
            nonlocal key
            if probe_leg != leg or key is not None:
                raise reducer.QualificationError("unexpected qualification probe")
            current_key = _explicit_route_key(profile_for(leg), env)
            try:
                subject, dependency = panel_invoker._resolved_jail_subject(leg, env)
            except (FileNotFoundError, ExecutableDependencyError) as exc:
                raise reducer.QualificationError("qualification subject is no longer available") from exc
            if dependency is not None and getattr(dependency, "_jailcore_owned", False):
                resources.callback(dependency.close)
            if getattr(dependency, "projection_digest", None) != current_key.projection_digest:
                raise reducer.QualificationError("qualification probe projection does not match the route key")
            standalone_runtime = None
            if leg == "codex":
                from . import seat_codex_runtime as codex_runtime
                from .seat_profile_codex import validate_codex_projection

                try:
                    validate_codex_projection(dependency)
                    if subject.source != "standalone" and dependency is None:
                        raise reducer.QualificationError("Codex projection unavailable")
                    if dependency is None:
                        resolved = codex_runtime.subject_runtime(subject)
                        if isinstance(resolved, codex_runtime.AdmittedStandaloneRuntime):
                            standalone_runtime = resolved
                        elif isinstance(resolved, codex_runtime.CodexRuntime):
                            standalone_runtime = codex_runtime.admit_runtime(
                                resolved, lookup_chain=getattr(subject, "lookup_chain", ()),
                            )
                        else:
                            raise reducer.QualificationError("standalone Codex runtime unavailable")
                        resources.callback(standalone_runtime.close)
                except (ExecutableDependencyError, seat_jail.SeatSandboxRefused) as exc:
                    raise reducer.QualificationError("qualification subject is no longer available") from exc
            executable = (
                Path(dependency.subject_source)
                if dependency is not None
                else Path(standalone_runtime.subject_source)
                if standalone_runtime is not None
                else subject.subject_path
            )
            if executable is None:
                raise reducer.QualificationError("qualification subject is no longer available")
            key = current_key
            if standalone_runtime is not None:
                return executable, dependency, standalone_runtime
            return executable, dependency

        # The reducer checks its prerequisites first and calls the builder for its D8 probe.
        token = seat_jail._QUALIFICATION_PROBE_SUBJECT.set(resolve_probe_subject)
        prefix = panel_invoker._EGRESS_LAUNCH_PREFIX
        prefix_token = prefix.set(prefix.get())
        try:
            evidence = reducer.qualify(leg, record=False, _mutate_jail=_mutate_jail)
        finally:
            # The reducer resets its prefix after a successful jail build.
            prefix.reset(prefix_token)
            seat_jail._QUALIFICATION_PROBE_SUBJECT.reset(token)
    if evidence["result"] == "pass":
        if key is None:
            raise reducer.QualificationError("qualification probe did not resolve the route key")
        evidence["recorded_pass"] = str(reducer._record_pass(evidence, key))
    return evidence


def main(argv: list[str]) -> int:
    if argv and argv not in (["--leg", "claude"], ["--leg", "gemini"]):
        return reducer.main(argv)
    evidence = qualify(argv[1]) if argv else qualify()
    summary = {key: evidence.get(key) for key in (
        "result", "profile_digest", "falsifier_layout", "checks", "run_outcome", "recorded_pass",
    )}
    if argv:
        summary.update(leg=evidence.get("leg"), key_digest=evidence.get("key_digest"))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if evidence["result"] == "pass" else 1
