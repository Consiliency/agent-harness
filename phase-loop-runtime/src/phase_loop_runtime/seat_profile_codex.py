"""Codex jail profile; production registration awaits OD-4."""

from pathlib import Path
import time
from types import MappingProxyType

from . import seat_codex_credential as credential
from .seat_codex_cli_shape import JAILED_CODEX_DISABLED_FEATURES, codex_cli_shape_problem
from .seat_codex_runtime import CODEX_RUNTIME_ROOT, CODEX_RUNTIME_FILES, CODEX_RUNTIME_DESTINATIONS
from .seat_route_contract import (
    ArgvInputs, ConfigSurface, ContainmentEvidence, CredentialDelivery, JailProfile,
    Precondition, WindowRows,
)

CODEX_TREE_ROWS = (
    *((path, "provider_overrides") for path in (
        "AGENTS.md", "AGENTS.override.md", ".codex/rules/default.rules",
        ".codex/skills/s/SKILL.md", ".agents/skills/s/SKILL.md")),
    (".codex/config.toml", "project_settings"),
    (".codex/hooks.json", "hooks"), (".mcp.json", "mcp_servers"),
)
CODEX_PLANTED_PATHS = tuple(path for path, _role in CODEX_TREE_ROWS)
CODEX_WINDOW_ROWS = WindowRows(
    "canonical_codex", "codex_route", "jailed",
    (("tree", "/seat/tree", "reviewed-tree"),
     ("workdir", "/seat/home/workspace", "seat-home/workspace"),
     ("home", "/seat/home", "seat-home"),
     ("provider_config", "/seat/home/.codex", "seat-home/.codex")), CODEX_TREE_ROWS,
)


def jailed_codex_command(inputs: ArgvInputs) -> tuple[str, ...]:
    return (
        f"{CODEX_RUNTIME_ROOT}/bin/codex",
        *(arg for feature in JAILED_CODEX_DISABLED_FEATURES for arg in ("--disable", feature)),
        "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--json",
        "--cd", "/seat/home/workspace", "--skip-git-repo-check",
        "--sandbox", "danger-full-access", "-c", 'approval_policy="never"',
        "-c", 'cli_auth_credentials_store="file"',
        *(("--model", inputs.model) if inputs.model else ()),
        "-c", f'model_reasoning_effort="{inputs.effort or "high"}"',
        "--output-last-message", inputs.output_path or "/seat/out/panel-codex.txt", "-",
    )


def _runtime_sources(provider):
    root = "<runtime>" if provider == "<provider>" else str(Path(provider).parent.parent)
    return tuple(provider if path == "bin/codex" else f"{root}/{path}"
                 for path in CODEX_RUNTIME_FILES)


def _binds(paths):
    if paths.egress_ca is None:
        from .seat_jail import SeatSandboxRefused, refused
        raise SeatSandboxRefused(refused("jail_build"))
    # Explicit traversable parents for the runtime's file mounts.
    directories = ("/run", "/run/phase-loop-seat", CODEX_RUNTIME_ROOT,
                   f"{CODEX_RUNTIME_ROOT}/bin", f"{CODEX_RUNTIME_ROOT}/codex-path")
    return (
        *(arg for directory in directories for arg in ("--perms", "0755", "--dir", directory)),
        "--ro-bind", paths.egress_ca, "/seat/egress-ca.pem",
        *(arg for source, destination in zip(_runtime_sources(paths.provider), CODEX_RUNTIME_DESTINATIONS)
          for arg in ("--ro-bind", source, destination) if paths.provider_bind),
    )


def _placeholders(paths):
    values = dict(zip(_runtime_sources(paths.provider), _runtime_sources("<provider>")))
    # The provider itself is also one runtime source; both use the canonical runtime name.
    if paths.egress_ca:
        values[paths.egress_ca] = "<egress-ca>"
    if paths.egress_proxy:
        values[paths.egress_proxy] = "<egress-proxy>"
    return MappingProxyType(values)


def _env(inputs):
    return MappingProxyType({
        "CODEX_HOME": "/seat/home/.codex", "HTTPS_PROXY": inputs.egress_proxy or "",
        "SSL_CERT_FILE": "/seat/egress-ca.pem", "CODEX_CA_CERTIFICATE": "/seat/egress-ca.pem",
        "PATH": f"{CODEX_RUNTIME_ROOT}/codex-path:/seat/bin:/usr/bin:/bin",
    })


def _check(name):
    raw = credential.read_auth()
    return (credential.token_margin_problem(raw, now=time.time()) if name == "token_margin"
            else getattr(credential, name)(raw))


def _subscription():
    return _check("subscription_login_problem")


def _margin():
    return _check("token_margin")


def _scope():
    return _check("scope_problem")


def _auth_probe():
    from .panel_invoker import _parent_auth_state
    return _parent_auth_state("codex")


def codex_admission_gate(leg, env, execute):
    from . import panel_invoker as pi, seat_admission, seat_jail
    try:
        raw = credential.read_auth(env)
        for check in (credential.subscription_login_problem,
                      lambda data: credential.token_margin_problem(data, now=time.time()),
                      credential.scope_problem):
            code = check(raw)
            if code:
                return seat_admission.Verdict(leg, "refuses", code=code)
    except seat_jail.SeatSandboxRefused as exc:
        return seat_admission.Verdict(leg, "refuses", code=exc.code)
    if not execute:
        return seat_admission.Verdict(leg, "unknown", reason="launch_measurement")
    from .seat_subject import resolve_seat_subject
    subject = resolve_seat_subject(leg, env)
    texts = []
    for args in (("exec", "--help"), ("features", "list")):
        done = pi.run_provider([str(subject.subject_path), *args], env=dict(env),
                               capture_output=True, text=True, timeout=30)
        texts.append(done.stdout if done.returncode == 0 else "")
    if codex_cli_shape_problem(*texts):
        return seat_admission.Verdict(leg, "refuses", code="codex_seat_cli_shape")
    return None


CODEX_PROFILE = JailProfile(
    leg="codex", vendor="codex", owner_binds=_binds, env=_env,
    home_dirs=(".codex", "workspace"), digest_placeholders=_placeholders,
    mount_points=lambda _paths: ("/seat/egress-ca.pem", *CODEX_RUNTIME_DESTINATIONS),
    new_session=True, token_fd=False, argv=jailed_codex_command, projection="optional",
    credential=CredentialDelivery("home_file", "codex-credential-scope"),
    credential_present=credential.present, credential_missing_code="codex_seat_credential_missing",
    preconditions=(Precondition("subscription_login", _subscription), Precondition("token_margin", _margin),
                   Precondition("scope_ceiling", _scope)),
    recorded_stop=None, variant=None, config_surface=ConfigSurface(True, CODEX_PLANTED_PATHS),
    auth_probe=_auth_probe, output_secret_code="codex_seat_token_in_output",
    containment=ContainmentEvidence("codex-credential-scope", "codex-refresh-detection",
                                    "codex-unlisted-endpoint", None),
    allowlist_id="codex", notice_codes=frozenset({
        "codex_seat_credential_missing", "codex_seat_api_key_refused", "codex_seat_token_expiring",
        "codex_seat_token_scope_excess", "codex_seat_token_in_output",
        "codex_seat_token_refreshed_in_jail", "codex_seat_cli_shape",
        "codex_seat_tools_unavailable", "codex_seat_unknown_event",
    }), window=CODEX_WINDOW_ROWS,
)


def register_codex():
    from . import seat_admission, seat_profiles
    from .seat_subject import register_provider_executable
    seat_profiles.register(CODEX_PROFILE)
    register_provider_executable("codex", "codex")
    seat_admission.register("codex", codex_admission_gate)
