"""The unregistered Codex profile's declared runtime and window inputs."""
from dataclasses import replace

import pytest

from phase_loop_runtime import seat_jail as jail, seat_profiles
from phase_loop_runtime import seat_profile_codex as codex
from phase_loop_runtime.seat_route_contract import ArgvInputs, EnvInputs


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


def test_window_rows_reach_the_generic_plant_kit(codex_profile):
    from phase_loop_runtime import seat_jail_qualification as q, seat_window
    assert seat_window.window_rows_for("codex") is codex.CODEX_WINDOW_ROWS
    layout = q.plant_layout(plugin_form="nested", window=codex_profile.window)
    assert {row.row_id for row in layout.rows} == {
        location + ":" + path for location, _, _ in codex.CODEX_WINDOW_ROWS.plant_locations
        for path in codex.CODEX_PLANTED_PATHS}


@pytest.mark.parametrize("execute", [False, True])
def test_admission_preconditions_and_shape(monkeypatch, execute):
    from types import SimpleNamespace
    from phase_loop_runtime import panel_invoker as pi, seat_codex_credential as credential
    monkeypatch.setattr(credential, "read_auth", lambda env: b"fixture")
    order = []
    for name in ("subscription_login_problem", "token_margin_problem", "scope_problem"):
        monkeypatch.setattr(credential, name,
                            lambda raw, _name=name, **k: order.append(_name))
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda *a: (SimpleNamespace(subject_path="fixture"), None))
    monkeypatch.setattr(pi, "run_provider", lambda *a, **k: SimpleNamespace(returncode=0, stdout=""))
    verdict = codex.codex_admission_gate("codex", {}, execute)
    assert order == ["subscription_login_problem", "token_margin_problem", "scope_problem"]
    assert (verdict.code == "codex_seat_cli_shape" if execute else verdict.reason == "launch_measurement")


@pytest.mark.parametrize("mutation", [None, "missing", "subject", "resources", "extra"])
def test_projected_runtime_is_the_declared_file_set(mutation):
    from types import SimpleNamespace
    from phase_loop_runtime.executable_dependency import ExecutableDependencyError
    from phase_loop_runtime.seat_codex_runtime import CODEX_RUNTIME_DESTINATIONS, CODEX_RUNTIME_ROOT
    paths = list(CODEX_RUNTIME_DESTINATIONS)
    if mutation == "missing":
        paths.pop()
    if mutation == "resources":
        paths.append("/run/phase-loop-seat/codex-runtime/codex-resources/bwrap")
    if mutation == "extra":
        paths.append(f"{CODEX_RUNTIME_ROOT}/codex-path/extra")
    entries = [SimpleNamespace(destination=path, kind="file") for path in paths]
    entries.extend(SimpleNamespace(destination=path, kind="directory")
                   for path in codex._CODEX_RUNTIME_DIRECTORIES)
    dependency = SimpleNamespace(entries=entries,
        subject_destination="/other" if mutation == "subject" else CODEX_RUNTIME_DESTINATIONS[0])
    if mutation is None:
        codex.validate_codex_projection(dependency)
    else:
        with pytest.raises(ExecutableDependencyError, match="authority_invalid"):
            codex.validate_codex_projection(dependency)


def test_preconditions_return_the_auth_file_code(tmp_path, monkeypatch):
    auth = tmp_path / ".codex/auth.json"
    auth.parent.mkdir()
    auth.write_text("{}")
    auth.chmod(0o644)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    for precondition in codex.CODEX_PROFILE.preconditions:
        assert precondition.check() == "seat_sandbox_refused:token_file_unsafe"


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
