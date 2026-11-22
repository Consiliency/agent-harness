"""Registry and built-in definitions for jailed-seat provider profiles.

Provider-specific policy lives here.  The jail builders and route resolver consume the
frozen :class:`~phase_loop_runtime.seat_route_contract.JailProfile` callbacks and therefore
do not grow a new ``leg == ...`` branch when another vendor registers a profile.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
from types import MappingProxyType
from typing import Mapping

from .seat_route_contract import (
    ArgvInputs,
    ConfigSurface,
    ContainmentEvidence,
    CredentialDelivery,
    EnvInputs,
    JailProfile,
    OwnerPaths,
    Precondition,
    WindowRows,
    OD10_CLASSES,
)


_REGISTRY: dict[str, JailProfile] = {}


@dataclass(frozen=True)
class WindowVendorData:
    """Vendor-owned record and launch vocabulary for the generic window kit.

    This is deliberately separate from the frozen :class:`WindowRows` shape.  Later
    provider lanes add one data row beside their profile; ``seat_window`` does not gain a
    provider branch.
    """

    leg: str
    vendor: str
    record_fields: Mapping[str, str]
    board_fields: Mapping[str, str]
    route_literal: str
    containment_outcomes: Mapping[str, frozenset[str]]
    control_launcher: str
    board_launcher: str
    model_leg: str
    dependency_provider: str
    co_seats: frozenset[str]
    qualification_candidate_code: str | None = None
    default: bool = False
    # IF-K1-1 version 2 (K-1 window-kit contract §3).
    supplier: str | None = None
    contract_sha256: str | None = None
    windows: frozenset[str] = frozenset()
    launch_kinds: frozenset[str] = frozenset()
    credential_kinds: frozenset[str] = frozenset()
    launch_cap: int = 0


_WINDOW_DATA: dict[str, WindowVendorData] = {}

#: I-11's closed launch kinds (the FIRSTSEAT interfaces, frozen).
WINDOW_LAUNCH_KINDS = frozenset({
    "help", "plugin_validation", "tree_control", "runtime_control",
    "credentialed_tree_control", "credentialed_runtime_control", "measured", "expired_copy",
})
#: The board result's subject fields, the same for every vendor (§3).
WINDOW_BOARD_FIELDS: Mapping[str, str] = MappingProxyType({
    "canonical": "canonical", "leg": "leg_observation",
})
#: The plan tier's required legs: the policy's fable, sol, gemini and grok seats by vendor.
WINDOW_PLAN_TIER_LEGS = frozenset({"claude", "codex", "gemini", "grok"})
_WINDOW_IDS = frozenset({"W1", "row"})


def register(profile: JailProfile) -> JailProfile:
    """Register one immutable profile, refusing ambiguous import-order overrides."""
    if not isinstance(profile, JailProfile):
        raise TypeError("profile must be a JailProfile")
    if not profile.leg or not profile.vendor:
        raise ValueError("profile leg and vendor are required")
    if not profile.config_surface.closed:
        raise ValueError("profile config surface must be closed")
    if OD10_CLASSES.get(profile.output_secret_code) != "security":
        raise ValueError("profile output-secret code must be OD-10 security")
    from . import seat_resource_caps as caps
    profile = replace(
        profile,
        preconditions=(
            *(item for item in profile.preconditions if item.name != "resource_caps"),
            Precondition("resource_caps", lambda: caps.readiness_code()),
        ),
        notice_codes=frozenset((*profile.notice_codes, caps.CODE)),
    )
    unknown = set(profile.notice_codes) - set(OD10_CLASSES)
    if unknown:
        raise ValueError(f"profile notice codes are unclassified: {sorted(unknown)}")
    previous = _REGISTRY.get(profile.leg)
    if previous is not None and previous != profile:
        raise ValueError(f"jail profile already registered for {profile.leg}")
    _REGISTRY[profile.leg] = profile
    return profile


def profile_for(leg: str) -> JailProfile | None:
    return _REGISTRY.get(leg)


def registered_legs() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def register_window_data(data: WindowVendorData) -> WindowVendorData:
    """Register one immutable vendor row, refusing ambiguous overrides."""
    if not isinstance(data, WindowVendorData):
        raise TypeError("window data must be WindowVendorData")
    if not data.leg or not data.vendor or set(data.record_fields) != {"canonical", "route"}:
        raise ValueError("window data identity or record fields unavailable")
    if set(data.board_fields) != {"canonical", "leg"}:
        raise ValueError("window data board fields unavailable")
    if set(data.containment_outcomes) != {
        "credential_scope", "refresh_detection", "project_settings", "hooks",
        "mcp_servers", "provider_overrides",
    }:
        raise ValueError("window data outcome fields unavailable")
    if not data.co_seats or data.leg in data.co_seats:
        raise ValueError("window data co-seats unavailable")
    _check_window_data_v2(data)
    previous = _WINDOW_DATA.get(data.vendor)
    if previous is not None and previous != data:
        raise ValueError(f"window data already registered for {data.vendor}")
    _WINDOW_DATA[data.vendor] = data
    return data


def _check_window_data_v2(data: WindowVendorData) -> None:
    """IF-K1-1 §3: every refusal ``register_window_data`` applies to version 2 data."""
    import re
    from .seat_window_supply import SUPPLIERS

    names = tuple(data.record_fields.values())
    if (len(set(names)) != len(names)
            or any(type(name) is not str or data.vendor not in name for name in names)):
        raise ValueError("window data record fields must name their vendor")
    for other in _WINDOW_DATA.values():
        if other.vendor != data.vendor and set(other.record_fields.values()) & set(names):
            raise ValueError("window data record fields are another vendor's")
    if dict(data.board_fields) != dict(WINDOW_BOARD_FIELDS):
        raise ValueError("window data board fields unavailable")
    if set(data.co_seats) != WINDOW_PLAN_TIER_LEGS - {data.leg}:
        raise ValueError("window data co-seats are not the plan tier less this leg")
    kinds = frozenset(data.launch_kinds)
    if (not kinds or not kinds <= WINDOW_LAUNCH_KINDS
            or not {"measured", "expired_copy"} <= kinds):
        raise ValueError("window data launch kinds unavailable")
    if not frozenset(data.credential_kinds) <= kinds:
        raise ValueError("window data credential kinds outside its launch kinds")
    if type(data.launch_cap) is not int or data.launch_cap != len(data.credential_kinds) + 1:
        raise ValueError("window data launch cap unavailable")
    if SUPPLIERS.get(data.vendor) != data.supplier:
        raise ValueError("window data supplier is outside the table")
    if (not isinstance(data.contract_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", data.contract_sha256) is None):
        raise ValueError("window data contract digest unavailable")
    windows = frozenset(data.windows)
    if not windows or not windows <= _WINDOW_IDS or ("W1" in windows) != data.default:
        raise ValueError("window data windows unavailable")


def window_data_for(vendor: str) -> WindowVendorData | None:
    return _WINDOW_DATA.get(vendor)


def registered_window_data() -> tuple[WindowVendorData, ...]:
    return tuple(_WINDOW_DATA[vendor] for vendor in sorted(_WINDOW_DATA))


def window_provider_start(argv, *, boundary: str = "launch"):
    """K-1 §9.1 provider boundary, reached from ``panel_invoker.launch_provider`` and
    ``run_provider``: inside a row window a provider start reserves one unit of its scoped
    ledger item before it happens. Outside a window it does nothing."""
    from . import seat_window_supply
    return seat_window_supply.provider_start(argv, boundary=boundary)


def default_window_data() -> WindowVendorData | None:
    matches = [data for data in _WINDOW_DATA.values() if data.default]
    return matches[0] if len(matches) == 1 else None


def _claude_binds(_paths: OwnerPaths) -> tuple[str, ...]:
    return ()


def _gemini_binds(paths: OwnerPaths) -> tuple[str, ...]:
    # TEAMHOST owns seat_jail._gemini_binds.  The profile delegates to that sanctioned
    # symbol without changing its implementation.
    from . import seat_jail

    return tuple(seat_jail._gemini_binds(paths.home, paths.provider_config, paths.egress_ca))


def _claude_env(inputs: EnvInputs) -> Mapping[str, str]:
    from . import seat_jail

    values = {
        "CLAUDE_CONFIG_DIR": seat_jail.SEAT_CLAUDE_CONFIG,
        "CLAUDE_CODE_TMPDIR": seat_jail.SEAT_TMP,
    }
    if inputs.token_fd is not None:
        values[seat_jail.CLAUDE_TOKEN_FD_ENV] = str(inputs.token_fd)
    return MappingProxyType(values)


def _gemini_env(inputs: EnvInputs) -> Mapping[str, str]:
    from . import seat_jail

    if inputs.egress_proxy is None:
        return MappingProxyType({})
    return MappingProxyType({
        "HTTPS_PROXY": inputs.egress_proxy,
        "SSL_CERT_FILE": seat_jail.SEAT_EGRESS_CA,
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/dev/null",
    })


def _claude_placeholders(_paths: OwnerPaths) -> Mapping[str, str]:
    return MappingProxyType({})


def _gemini_placeholders(paths: OwnerPaths) -> Mapping[str, str]:
    from . import seat_jail

    values: dict[str, str] = {}
    if paths.provider_config is not None:
        values[paths.provider_config] = "<gemini-config>"
    if paths.egress_ca is not None:
        values[paths.egress_ca] = "<egress-ca>"
    if paths.egress_proxy is not None:
        values[paths.egress_proxy] = "<egress-proxy>"
    for name in (*seat_jail.GEMINI_WRITABLE_CONFIG_DIRS,
                 *seat_jail.GEMINI_WRITABLE_DOTDIR_DIRS):
        values[seat_jail._gemini_writable_source(paths.home, name)] = (
            seat_jail._gemini_writable_source("<home>", name)
        )
    return MappingProxyType(values)


def _claude_mount_points(_paths: OwnerPaths) -> tuple[str, ...]:
    return ()


def _gemini_mount_points(_paths: OwnerPaths) -> tuple[str, ...]:
    from . import seat_jail

    return (
        seat_jail.SEAT_GEMINI_DOTDIR,
        seat_jail.SEAT_EGRESS_CA,
        *(f"{seat_jail.SEAT_GEMINI_CONFIG}/{name}"
          for name in seat_jail.GEMINI_WRITABLE_CONFIG_DIRS),
        *(f"{seat_jail.SEAT_GEMINI_DOTDIR}/{name}"
          for name in seat_jail.GEMINI_WRITABLE_DOTDIR_DIRS),
    )


def _claude_argv(inputs: ArgvInputs) -> tuple[str, ...]:
    if inputs.transport == "tui":
        return (inputs.provider_argv0, "--ax-screen-reader", "--safe-mode", "--no-chrome")
    values = [inputs.provider_argv0, "-p"]
    if inputs.model:
        values.extend(("--model", inputs.model))
    if inputs.output_path:
        values.extend(("--output-format", "json"))
    return tuple(values)


def _gemini_argv(inputs: ArgvInputs) -> tuple[str, ...]:
    values = [inputs.provider_argv0]
    if inputs.model:
        values.extend(("--model", inputs.model))
    values.append("--dangerously-skip-permissions")
    return tuple(values)


def _claude_credential_present() -> bool:
    from .seat_credentials import claude_seat_credential_present

    return claude_seat_credential_present()


def _gemini_credential_present() -> bool:
    from .seat_jail import gemini_operator_credential_present

    return gemini_operator_credential_present()


def _gemini_profile_qualified() -> str | None:
    # The tooled profile is qualified only while the registry still names the shipped
    # Gemini profile.  The live EC-EXECFIND-2 pass remains L8's keyed qualification.
    profile = profile_for("gemini")
    return (None if profile is not None and profile.vendor == "gemini"
            else "gemini_seat_profile_unqualified")


def _claude_variant(_env: Mapping[str, str]) -> tuple[str | None, str | None]:
    from .claude_seat_transport import resolve_jailed_claude_transport

    return resolve_jailed_claude_transport()


def _auth_unavailable() -> str:
    # Runtime auth state is recorded by leg_exec_record; profile declarations remain pure
    # until a provider phase supplies a non-launching probe.
    return "unavailable"


_GEMINI_TREE_ROWS = (
    *((path, "provider_overrides") for path in (
        "AGENTS.md", "GEMINI.md", ".agent/AGENTS.md", ".agent/GEMINI.md",
        ".agents/AGENTS.md", ".agents/GEMINI.md", "_agent/AGENTS.md",
        "_agent/GEMINI.md", "_agents/AGENTS.md", "_agents/GEMINI.md",
        ".agent/rules/r.md", ".agents/rules/r.md", ".agent/rules.json",
        ".agents/rules.json", ".agents/workflows/w.md", ".agent/skills/s/SKILL.md",
        ".agents/skills/s/SKILL.md", ".agent/skills.json", ".agent/skills.txt",
        ".agents/skills.json", ".agents/skills.txt", ".agent/agents.json",
        ".agent/agents.txt", ".agent/plugins/p/", ".agents/plugins/p/",
        ".agent/plugins.json", ".agent/plugins.txt", ".agents/plugins.json",
        ".agents/plugins.txt",
    )),
    *((path, "hooks") for path in (
        ".agents/hooks.json", ".agent/hooks.json", ".gemini/hooks.json",
    )),
    *((path, "mcp_servers") for path in (
        ".agents/mcp_config.json", ".mcp.json",
    )),
    *((path, "project_settings") for path in (
        ".gemini/settings.json", ".gemini/config.json",
        ".gemini/antigravity-cli/settings.json", "codeium.yaml", "codeium.yml",
    )),
)


GEMINI_WINDOW = WindowRows(
    canonical_record_field="canonical_gemini",
    route_record_field="gemini_route",
    route_literal="jailed",
    plant_locations=(
        ("tree", "/seat/tree", "reviewed-tree"),
        ("workdir", "/seat/home/workspace", "seat-home/workspace"),
        ("home", "/seat/home", "seat-home"),
        ("provider_config", "/seat/home/.gemini/antigravity-cli",
         "gemini-config/antigravity-cli"),
    ),
    tree_rows=tuple(_GEMINI_TREE_ROWS),
)


GEMINI_WINDOW_DATA = register_window_data(WindowVendorData(
    leg="gemini",
    vendor="gemini",
    record_fields=MappingProxyType({
        "canonical": "canonical_gemini",
        "route": "gemini_route",
    }),
    board_fields=WINDOW_BOARD_FIELDS,
    route_literal="jailed",
    containment_outcomes=MappingProxyType({
        "credential_scope": frozenset({
            "pass", "gemini_seat_token_scope_excess", "unavailable",
        }),
        "refresh_detection": frozenset({
            "pass", "gemini_seat_token_refreshed_in_jail", "unavailable",
        }),
        "project_settings": frozenset({"not_loaded", "loaded", "unavailable"}),
        "hooks": frozenset({"not_loaded", "loaded", "unavailable"}),
        "mcp_servers": frozenset({"not_loaded", "loaded", "unavailable"}),
        "provider_overrides": frozenset({"not_loaded", "loaded", "unavailable"}),
    }),
    control_launcher="window_control_launch",
    board_launcher="window_board_launch",
    model_leg="gemini",
    dependency_provider="gemini",
    # Every other seat of the plan-tier board (I-12 `co_seats`): the policy requires
    # fable, sol, gemini and grok, so a terminated W1 board always carries all three.
    co_seats=frozenset({"claude", "codex", "grok"}),
    qualification_candidate_code="gemini_seat_qualification_candidate",
    default=True,
    supplier="seat_window_supply_gemini",
    # Gemini's own containment contract (§10.A), unchanged.
    contract_sha256="a57d46f722e22973f0522a8bc254856e6224d50b1b67893cab2b80522c4942a6",
    windows=frozenset({"W1", "row"}),
    launch_kinds=WINDOW_LAUNCH_KINDS,
    credential_kinds=frozenset({
        "credentialed_tree_control", "credentialed_runtime_control", "measured",
        "expired_copy",
    }),
    launch_cap=5,
))


CLAUDE = register(JailProfile(
    leg="claude",
    vendor="claude",
    owner_binds=_claude_binds,
    env=_claude_env,
    home_dirs=(),
    digest_placeholders=_claude_placeholders,
    mount_points=_claude_mount_points,
    new_session=False,
    token_fd=True,
    argv=_claude_argv,
    projection="optional",
    credential=CredentialDelivery(channel="token_fd", scope_evidence=None),
    credential_present=_claude_credential_present,
    credential_missing_code="claude_seat_token_missing",
    preconditions=(),
    recorded_stop=None,
    config_surface=ConfigSurface(
        closed=True,
        planted_paths=(".claude/settings.json", ".claude/settings.local.json", ".mcp.json"),
    ),
    auth_probe=_auth_unavailable,
    output_secret_code="claude_seat_token_in_output",
    containment=ContainmentEvidence(None, None, None, "EC-CLAUDENET-3"),
    allowlist_id=None,
    variant=_claude_variant,
    notice_codes=frozenset({
        "claude_seat_token_missing", "claude_seat_token_in_output",
        "panel_claude_route_invalid", "panel_claude_transport_not_admitted",
    }),
    window=None,
))


GEMINI = register(JailProfile(
    leg="gemini",
    vendor="gemini",
    owner_binds=_gemini_binds,
    env=_gemini_env,
    home_dirs=(
        "workspace",
        ".agy-rw",
        *(f".agy-rw/{name}" for name in ("bin", "cache", "log", "config")),
    ),
    digest_placeholders=_gemini_placeholders,
    mount_points=_gemini_mount_points,
    new_session=True,
    token_fd=False,
    argv=_gemini_argv,
    projection="optional",
    credential=CredentialDelivery(
        channel="home_file",
        scope_evidence="plans/evidence/seat-jail-1132/p4-agy-d7-credential.json",
    ),
    credential_present=_gemini_credential_present,
    credential_missing_code="gemini_seat_credential_missing",
    preconditions=(Precondition("tooled_profile", _gemini_profile_qualified),),
    recorded_stop=None,
    config_surface=ConfigSurface(
        closed=True,
        planted_paths=tuple(path for path, _role in _GEMINI_TREE_ROWS),
    ),
    auth_probe=_auth_unavailable,
    output_secret_code="gemini_seat_token_in_output",
    containment=ContainmentEvidence(
        credential_scope="plans/evidence/seat-jail-1132/p4-agy-d7-credential.json",
        refresh_detection="plans/evidence/seat-jail-1132/p4-containment-egress.json",
        unlisted_endpoint_refused="plans/evidence/seat-jail-1132/p4-containment-egress.json",
        deferred_to=None,
    ),
    allowlist_id="gemini",
    variant=None,
    notice_codes=frozenset({
        "gemini_seat_credential_missing", "gemini_seat_profile_unqualified",
        "gemini_seat_token_in_output", "gemini_seat_token_refreshed_in_jail",
        "gemini_seat_token_scope_excess", "gemini_seat_credential_unusable",
    }),
    window=GEMINI_WINDOW,
))


# OD-4 accepted 2026-11-08; profile and launch wiring enable together (CODEX SL-3).
from .seat_profile_codex import register_codex

register_codex()


def _digest_receipt() -> dict[str, object]:
    from . import seat_jail

    return {
        "schema": "seat_jail_profile_digest_receipt.v1",
        "profiles": {
            leg: {
                arch: seat_jail.jail_profile_digest(leg, arch)
                for arch in ("x86_64", "aarch64")
            }
            for leg in registered_legs()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("digest-receipt",))
    args = parser.parse_args(argv)
    if args.action == "digest-receipt":
        print(json.dumps(_digest_receipt(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "WindowVendorData", "profile_for", "register", "registered_legs",
    "default_window_data", "register_window_data", "registered_window_data",
    "window_data_for",
]
