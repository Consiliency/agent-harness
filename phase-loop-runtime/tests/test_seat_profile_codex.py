"""The unregistered Codex profile's declared runtime and window inputs."""
from dataclasses import replace

import pytest

from phase_loop_runtime import seat_jail as jail, seat_profiles
from phase_loop_runtime import seat_profile_codex as codex
from phase_loop_runtime.seat_route_contract import ArgvInputs, EnvInputs, OwnerPaths


@pytest.fixture
def codex_profile(monkeypatch):
    from phase_loop_runtime import seat_admission, seat_subject
    monkeypatch.setattr(seat_profiles, "_REGISTRY", dict(seat_profiles._REGISTRY))
    monkeypatch.setattr(seat_admission, "_GATES", dict(seat_admission._GATES))
    monkeypatch.setattr(seat_subject, "_PROVIDER_EXECUTABLES", dict(seat_subject._PROVIDER_EXECUTABLES))
    codex.register_codex()
    return seat_profiles.profile_for("codex")


def test_profile_is_inert_until_registered():
    assert seat_profiles.profile_for("codex") is None
    profile = codex.CODEX_PROFILE
    assert (profile.leg, profile.vendor, profile.new_session, profile.token_fd) == ("codex", "codex", True, False)
    assert profile.home_dirs == (".codex", "workspace")
    assert [item.name for item in profile.preconditions] == ["subscription_login", "token_margin", "scope_ceiling"]
    assert profile.credential.scope_evidence == "codex-credential-scope"
    assert profile.window is codex.CODEX_WINDOW_ROWS
    assert profile.config_surface.planted_paths == tuple(path for path, _ in codex.CODEX_TREE_ROWS)
    assert {row[0] for row in profile.window.plant_locations} == {"tree", "workdir", "home", "provider_config"}


def test_argv_and_environment_literals():
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime.seat_codex_runtime import CODEX_RUNTIME_ROOT
    command = codex.jailed_codex_command(ArgvInputs("ignored", model="model", effort="xhigh"))
    assert command[0] == CODEX_RUNTIME_ROOT + "/bin/codex"
    assert command[command.index("exec"):] == (
        "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--json",
        "--cd", "/seat/home/workspace", "--skip-git-repo-check", "--sandbox", "danger-full-access",
        "-c", 'approval_policy="never"', "-c", 'cli_auth_credentials_store="file"',
        "--model", "model", "-c", 'model_reasoning_effort="xhigh"',
        "--output-last-message", "/seat/out/panel-codex.txt", "-")
    forbidden = {"--dangerously-bypass-approvals-and-sandbox", "--dangerously-bypass-hook-trust",
                 "--add-dir", "--worktree", "--oss", "--profile"}
    assert not forbidden.intersection(command)
    assert set(codex.JAILED_CODEX_DISABLED_FEATURES) == (
        set(pi._BROKER_CODEX_DISABLED_FEATURES) - {"shell_tool", "code_mode_host"}
        | {"daemon_auto_start", "plugin_discovery_prefetch"})
    assert codex.CODEX_PROFILE.env(EnvInputs(None, egress_proxy="fixture")) == {
        "CODEX_HOME": "/seat/home/.codex", "HTTPS_PROXY": "fixture",
        "SSL_CERT_FILE": "/seat/egress-ca.pem", "CODEX_CA_CERTIFICATE": "/seat/egress-ca.pem",
        "PATH": CODEX_RUNTIME_ROOT + "/codex-path:/seat/bin:/usr/bin:/bin"}


def _jail(tmp_path, *, dependency=False):
    directory = tmp_path / "jail"
    tree = directory / "reviewed-tree"
    tree.mkdir(parents=True)
    provider = tmp_path / "vendor/x86_64-unknown-linux-musl/bin/codex"
    provider.parent.mkdir(parents=True)
    provider.write_bytes(b"fixture")
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"certificate")
    built = jail.build_seat_jail(
        "codex", directory, provider, tree=tree,
        bundle_memfd=jail.memfd_with("b", b"b"), instructions_memfd=jail.memfd_with("i", b"i"),
        seat_ids=(1, 1), egress_ca=ca, egress_proxy="http://fixture:password@127.0.0.1:3128")
    if not dependency:
        return built
    from phase_loop_runtime.seat_codex_runtime import CODEX_RUNTIME_DESTINATIONS
    owner = list(built.process_owner)
    provider_index = owner.index(str(provider)) - 1
    del owner[provider_index:provider_index + 3]
    for destination in CODEX_RUNTIME_DESTINATIONS:
        index = owner.index(destination) - 2
        del owner[index:index + 3]
    mounts = tuple(arg for i, dst in enumerate(CODEX_RUNTIME_DESTINATIONS)
                   for arg in ("--perms", "0555", "--ro-bind-data", str(900+i), dst))
    anchor = owner.index("--remount-ro")
    owner[anchor:anchor] = mounts
    return replace(built, process_owner=tuple(owner), dependency_mount_args=mounts,
                   dependency_destinations=CODEX_RUNTIME_DESTINATIONS,
                   provider_argv0=CODEX_RUNTIME_DESTINATIONS[0])


@pytest.mark.parametrize("dependency", [False, True])
def test_registered_profile_has_the_canonical_digest(tmp_path, codex_profile, dependency):
    built = _jail(tmp_path, dependency=dependency)
    try:
        assert jail.actual_profile_digest(built) == jail.jail_profile_digest("codex")
    finally:
        jail.close_jail_fds(built)


@pytest.mark.parametrize("dependency", [False, True])
@pytest.mark.parametrize("mutation", ["extra", "missing", "altered", "source", "arbitrary"])
def test_runtime_bind_mutations_remain_observable(tmp_path, codex_profile, dependency, mutation):
    from phase_loop_runtime.seat_codex_runtime import CODEX_RUNTIME_DESTINATIONS
    built = _jail(tmp_path, dependency=dependency)
    try:
        owner = list(built.process_owner)
        width = 5 if dependency else 3
        index = owner.index(CODEX_RUNTIME_DESTINATIONS[-1]) - width + 1
        if mutation == "extra":
            owner[index:index] = owner[index:index + width]
        elif mutation == "missing":
            del owner[index:index + width]
        elif mutation == "altered":
            owner[index + (2 if dependency else 0)] = "--bind"
        elif mutation == "source":
            owner[index + width - 2] = "/different/source"
        else:
            owner.extend(("--ro-bind", "/unrelated", "/unrelated"))
        changed = replace(built, process_owner=tuple(owner))
        try:
            assert jail.actual_profile_digest(changed) != jail.jail_profile_digest("codex")
        except jail.SeatSandboxRefused:
            pass
    finally:
        jail.close_jail_fds(built)
