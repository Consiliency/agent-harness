"""Synthetic local corpus, deliberately not public contract conformance."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

import pytest

from phase_loop_runtime import supervised_launch as launch


@pytest.fixture
def case():
    mask = os.umask(0o077)
    try:
        # /tmp is intentionally unsuitable for trusted executable/binding paths.
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory).absolute()
            for name in ("workspace", "target", "references", "tools", "operator"):
                (root / name).mkdir()
            executable = root / "tools/tool"
            executable.write_bytes(b"synthetic executable, never launched")
            executable.chmod(0o700)
            wrapper = root / "tools/wrapper"
            wrapper.write_bytes(b"synthetic wrapper, never launched")
            wrapper.chmod(0o700)
            for name, data in (("instruction", b"synthetic instructions"), ("baseline", b"synthetic baseline")):
                (root / "references" / name).write_bytes(data)
            config = launch.LaunchConfig(root / "operator/config.json", root / "operator/template.json")
            settings = {"reference_roots": [str(root / "references")], "executable_path": [str(root / "tools")],
                        "envelope_cap": 16384, "reference_cap": 1024, "aggregate_cap": 2048,
                        "timeout_max": 60, "qualified_version": "synthetic-v1"}
            config.config_path.write_text(json.dumps(settings))
            config.template_path.write_text('["{executable}", "readonly-proposal"]')
            envelope = json.loads((Path(__file__).parent / "fixtures/supervised_launch_local/envelope.json").read_bytes())
            envelope["run_id"] = root.name
            envelope["launch_inputs"] = {
                "instruction": {"root": str(root / "references"), "path": "instruction",
                                "digest": launch.sha256((root / "references/instruction").read_bytes())},
                "baseline": {"root": str(root / "references"), "path": "baseline",
                             "digest": launch.sha256((root / "references/baseline").read_bytes())},
                "executable": str(executable), "wrappers": [str(wrapper)],
                "workspace": str(root / "workspace"), "target": str(root / "target"),
                "tier": "post_write_audit_only", "constraints": [], "timeout": 30}
            yield SimpleNamespace(root=root, config=config, settings=settings, envelope=envelope,
                                  executable=executable, wrapper=wrapper)
    finally:
        os.umask(mask)


def codec(capture):
    return capture.envelope, capture.raw_digest


def admit(view):
    return launch.Admit(view.launch_digest, view.envelope["attempt_id"])


def prepare(case, module=launch, validator=None, decoder=codec):
    if validator is None:
        validator = lambda view: module.Admit(view.launch_digest, view.envelope["attempt_id"])
    return module.prepare_launch(json.dumps(case.envelope).encode(), validator=validator,
                                 decoder=decoder, config=case.config)


def refused(case, module=launch, reason=None, validator=None, decoder=codec):
    sinks = []
    def spawn(*args, **kwargs):
        sinks.append("spawn")
        raise AssertionError("unexpected process creation")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(subprocess, "Popen", spawn)
        for name in ("system", "fork", "posix_spawn", "posix_spawnp"):
            patch.setattr(os, name, spawn)
        result = prepare(case, module, validator, decoder)
    assert isinstance(result, module.Refused), result
    assert sinks == []
    if reason:
        assert result.reason == reason


def qualify(case):
    case.envelope["launch_inputs"]["tier"] = "provider_readonly_patch_return_audit"
    record = {"executable": {"path": str(case.executable), "digest": launch.sha256(case.executable.read_bytes())},
              "wrappers": [{"path": str(case.wrapper), "digest": launch.sha256(case.wrapper.read_bytes())}],
              "template_digest": launch.sha256(case.config.template_path.read_bytes()),
              "version": "synthetic-v1", "write_attempt_refused": True, "proposal_return": True, "audit": True}
    path = case.root / "operator/qualification.json"
    path.write_text(json.dumps(record))
    case.config = replace(case.config, qualification_path=path)
    return path


def capture_witness(case, module, monkeypatch):
    raw = json.dumps(case.envelope).encode()
    counts = {"parse": 0, "hash": 0}
    original_json, original_sha = module._json, module.sha256
    def parsed(data):
        counts["parse"] += data == raw
        return original_json(data)
    def hashed(data):
        counts["hash"] += data == raw
        return original_sha(data)
    monkeypatch.setattr(module, "_json", parsed)
    monkeypatch.setattr(module, "sha256", hashed)
    result = prepare(case, module)
    assert isinstance(result, module.PreparedLaunch)
    assert counts == {"parse": 1, "hash": 1}
    return result


def test_single_use_immutable_snapshots_and_identities(case, monkeypatch):
    result = capture_witness(case, launch, monkeypatch)
    assert isinstance(result, launch.PreparedLaunch)
    assert result.view.envelope["caller_context"]["opaque"] == ("preserved", 1)
    for key in ("run_id", "attempt_id", "snapshot_reference", "assignment_digest", "redaction_posture"):
        assert result.view.envelope[key] == case.envelope[key]
    assert result.view.envelope["target_unit_ids"] == ("unit-a",)
    assert result.view.envelope["readonly_neighbor_unit_ids"] == ("unit-b",)
    assert result.view.envelope["obligation_references"] == ("synthetic-obligation",)
    with pytest.raises(TypeError):
        result.view.envelope["caller_context"]["opaque"] = "changed"
    (case.root / "references/instruction").write_bytes(b"replacement")
    assert launch.consume_admission(result).instruction == b"synthetic instructions"
    assert launch.consume_admission(result) == launch.Refused("token_spent")


@pytest.mark.parametrize("value", [True, "admit", None, 1])
def test_non_admit(case, value):
    refused(case, validator=lambda view: value, reason="admit_required")


@pytest.mark.parametrize("field", ["launch_digest", "attempt_id"])
def test_verdict_binding(case, field):
    refused(case, validator=lambda view: replace(admit(view), **{field: "stale"}), reason="admit_binding")


def test_exception_and_unavailable_validator(case):
    def failure(view):
        raise RuntimeError("synthetic failure")
    refused(case, validator=failure)
    result = launch.prepare_launch(b"{}", validator=None, decoder=codec, config=case.config)
    assert result == launch.Refused("binding_unavailable")


@pytest.mark.parametrize("field", ["instruction", "baseline", "executable", "wrappers", "workspace", "target",
                                  "tier", "constraints", "timeout"])
def test_every_launch_input_substitution(case, field):
    first = prepare(case)
    assert isinstance(first, launch.PreparedLaunch)
    values = {"instruction": dict(case.envelope["launch_inputs"]["baseline"]),
              "baseline": dict(case.envelope["launch_inputs"]["instruction"]),
              "executable": str(case.wrapper), "wrappers": [], "workspace": str(case.root / "target"),
              "target": str(case.root / "workspace"), "tier": "provider_readonly_patch_return_audit",
              "constraints": ["network_denial"], "timeout": 31}
    case.envelope["launch_inputs"][field] = values[field]
    refused(case, validator=lambda view: first.admit)


@pytest.mark.parametrize("tier", ["os_enforced", "unknown"])
def test_tier_refusal(case, tier):
    case.envelope["launch_inputs"]["tier"] = tier
    refused(case, reason="tier_unsupported")


@pytest.mark.parametrize("constraint", ["write_scope", "command_denial", "network_denial", "unknown"])
@pytest.mark.parametrize("provider", [False, True])
def test_constraint_matrix(case, constraint, provider):
    if provider:
        qualify(case)
    case.envelope["launch_inputs"]["constraints"] = [constraint]
    refused(case, reason="constraints_unsupported")


def test_qualification_missing_mismatched_and_positive(case):
    case.envelope["launch_inputs"]["tier"] = "provider_readonly_patch_return_audit"
    refused(case, reason="qualification_missing")
    path = qualify(case)
    assert isinstance(prepare(case), launch.PreparedLaunch)
    data = json.loads(path.read_bytes())
    data["write_attempt_refused"] = False
    path.write_text(json.dumps(data))
    refused(case, reason="qualification_invalid")


@pytest.mark.parametrize("storage", ["gitfile", "hardlink", "symlink", "alternates", "commondir"])
def test_workspace_provider_storage(case, storage):
    qualify(case)
    workspace = case.root / "workspace"
    if storage == "gitfile":
        (workspace / ".git").write_text("gitdir: ../target/.git")
    elif storage == "hardlink":
        os.link(case.executable, workspace / "linked")
    elif storage == "symlink":
        (workspace / "linked").symlink_to(case.root / "target")
    else:
        (workspace / storage).write_text("../target")
    refused(case)


def test_audit_worktree_and_in_place(case):
    (case.root / "workspace/.git").write_text("gitdir: ../target/.git")
    assert prepare(case).view.inputs.workspace_class == "worktree"
    case.envelope["launch_inputs"]["workspace"] = str(case.root / "target")
    assert prepare(case).view.inputs.workspace_class == "in_place"


def test_provider_uninspectable_storage(case, monkeypatch):
    storage_witness(case, launch, monkeypatch, "workspace_uninspectable")


def storage_witness(case, module, monkeypatch, control):
    qualify(case)
    if control == "workspace_uninspectable":
        def inaccessible(root, **kwargs):
            kwargs["onerror"](PermissionError("synthetic unreadable subtree"))
            return iter(())
        monkeypatch.setattr(module.os, "walk", inaccessible)
    else:
        shared = case.root / "workspace/objects"
        shared.mkdir()
        target = case.root / "target/objects"
        target.mkdir()
        original = Path.lstat
        def aliased(path, *args, **kwargs):
            return original(target if path == shared else path, *args, **kwargs)
        monkeypatch.setattr(Path, "lstat", aliased)
    refused(case, module, reason=control)


def test_provider_physical_shared_storage(case, monkeypatch):
    storage_witness(case, launch, monkeypatch, "workspace_shared")


@pytest.mark.parametrize("mode", ["relative_path", "empty_path", "workspace", "writable", "symlink", "missing"])
def test_executable_path_refusal(case, mode):
    if mode in {"relative_path", "empty_path"}:
        case.envelope["launch_inputs"]["executable"] = "tool"
        case.settings["executable_path"] = ["relative" if mode == "relative_path" else ""]
        case.config.config_path.write_text(json.dumps(case.settings))
    elif mode == "workspace":
        path = case.root / "workspace/tool"
        path.write_bytes(b"local")
        path.chmod(0o700)
        case.envelope["launch_inputs"]["executable"] = str(path)
    elif mode == "writable":
        case.executable.parent.chmod(0o770)
    elif mode == "symlink":
        case.executable.unlink()
        case.executable.symlink_to(case.wrapper)
    else:
        case.executable.unlink()
    refused(case)


@pytest.mark.parametrize("control", ["reference_root", "reference_nofollow", "reference_regular", "reference_cap",
                                     "aggregate_cap", "envelope_cap"])
def test_reference_controls(case, control):
    reference_witness(case, launch, control)


def reference_witness(case, module, control):
    spec = case.envelope["launch_inputs"]["instruction"]
    if control == "reference_root":
        spec["root"] = str(case.root / "operator")
        (case.root / "operator/instruction").write_bytes(b"synthetic instructions")
    elif control == "reference_nofollow":
        path = case.root / "references/instruction"
        path.unlink()
        path.symlink_to(case.root / "references/baseline")
        spec["digest"] = launch.sha256(b"synthetic baseline")
    elif control == "reference_regular":
        path = case.root / "references/instruction"
        path.unlink()
        os.mkfifo(path)
        spec["digest"] = launch.sha256(b"")
    else:
        key, value = {"reference_cap": ("reference_cap", len(b"synthetic instructions") - 1), "aggregate_cap": ("aggregate_cap", 30),
                      "envelope_cap": ("envelope_cap", 1)}[control]
        case.settings[key] = value
        case.config.config_path.write_text(json.dumps(case.settings))
    refused(case, module)


@pytest.mark.parametrize("control", ["consume_class", "consume_device", "consume_inode", "consume_executable", "consume_wrapper"])
def test_consumption_rechecks(case, monkeypatch, control):
    consumption_witness(case, launch, monkeypatch, control)


def consumption_witness(case, module, monkeypatch, control):
    prepared = prepare(case, module)
    assert isinstance(prepared, module.PreparedLaunch)
    if control == "consume_class":
        (case.root / "workspace/.git").write_text("gitdir: ../target/.git")
    elif control in {"consume_device", "consume_inode"}:
        # A synthetic stat return is needed for device changes without live mount trials.
        original = os.stat
        def changed(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == case.root / "workspace":
                values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
                values["st_dev" if control == "consume_device" else "st_ino"] += 10**12
                return SimpleNamespace(**values)
            return info
        monkeypatch.setattr(os, "stat", changed)
    else:
        (case.executable if control == "consume_executable" else case.wrapper).write_bytes(b"changed")
    reason = {"consume_class": "workspace_changed", "consume_device": "device_changed",
              "consume_inode": "inode_changed", "consume_executable": "executable_changed",
              "consume_wrapper": "wrapper_changed"}[control]
    assert module.consume_admission(prepared) == module.Refused(reason)


def test_identity_only_launch_digest(case):
    identity_witness(case, launch)


def test_root_owned_executable_identity(case, monkeypatch):
    executable_owner_witness(case, launch, monkeypatch)


def executable_owner_witness(case, module, monkeypatch):
    original = os.fstat
    inodes = {case.executable.stat().st_ino, case.wrapper.stat().st_ino}
    def root_owned(fd):
        info = original(fd)
        if info.st_ino in inodes:
            values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            values["st_uid"] = 0
            return SimpleNamespace(**values)
        return info
    monkeypatch.setattr(os, "fstat", root_owned)
    prepared = prepare(case, module)
    assert isinstance(prepared, module.PreparedLaunch)
    assert isinstance(module.consume_admission(prepared), module.LaunchInputs)


def identity_witness(case, module):
    first = prepare(case, module)
    case.executable.write_bytes(b"changed identity, identical envelope")
    refused(case, module, validator=lambda view: first.admit)
    second = prepare(case, module)
    assert first.view.raw_digest == second.view.raw_digest
    assert first.view.launch_digest != second.view.launch_digest
    assert asdict(first.view.inputs.executable) != asdict(second.view.inputs.executable)


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_ambiguous_json_before_codec(case, raw):
    calls = []
    result = launch.prepare_launch(raw, validator=lambda view: calls.append("validator"),
                                   decoder=lambda data: calls.append("decoder"), config=case.config)
    assert isinstance(result, launch.Refused)
    assert calls == []


def test_side_channels_and_missing_inputs(case):
    case.envelope["launch_inputs"]["argv_tail"] = ["override"]
    refused(case, reason="launch_fields")
    del case.envelope["launch_inputs"]["argv_tail"]
    del case.envelope["launch_inputs"]["instruction"]
    refused(case, reason="launch_fields")


def finite_witness(case, module, literal="1e400"):
    case.envelope["caller_context"] = {"nested": ["NUMBER"]}
    raw = json.dumps(case.envelope).replace('"NUMBER"', literal).encode()
    calls = []
    def decode(capture):
        calls.append("decoder")
        return capture.envelope, capture.raw_digest
    def validate(view):
        calls.append("validator")
        return module.Admit(view.launch_digest, view.envelope["attempt_id"])
    result = module.prepare_launch(raw, validator=validate, decoder=decode, config=case.config)
    assert result == module.Refused("nonfinite")
    assert calls == []


@pytest.mark.parametrize("literal", ["1e400", "-1e400"])
def test_numeric_capture(case, literal):
    finite_witness(case, launch, literal)


def codec_witness(case, module, field="tier"):
    calls = []
    def decode(capture):
        envelope = json.loads(capture.raw_bytes)
        if field == "dependency_declaration":
            envelope[field] = []
        else:
            key = "timeout" if field == "numeric_type" else field
            envelope["launch_inputs"][key] = case.envelope["launch_inputs"][key]
        return envelope, capture.raw_digest
    raw = json.loads(json.dumps(case.envelope))
    if field == "dependency_declaration":
        raw[field] = ["synthetic-required"]
    else:
        key = "timeout" if field == "numeric_type" else field
        raw["launch_inputs"][key] = {"tier": "os_enforced", "constraints": ["network_denial"],
                                    "timeout": 31, "executable": str(case.wrapper), "numeric_type": 30.0}[field]
    def validate(view):
        calls.append("validator")
        return module.Admit(view.launch_digest, view.envelope["attempt_id"])
    result = module.prepare_launch(json.dumps(raw).encode(), validator=validate, decoder=decode, config=case.config)
    assert result == module.Refused("codec_changed_envelope")
    assert calls == []


@pytest.mark.parametrize("field", ["tier", "constraints", "dependency_declaration", "timeout", "executable", "numeric_type"])
def test_codec_capture_agreement(case, field):
    codec_witness(case, launch, field)


def root_storage_witness(case, module, monkeypatch):
    qualify(case)
    target_child = case.root / "target/objects"
    target_child.mkdir()
    original = os.stat
    def aliased(path, *args, **kwargs):
        return original(target_child if path == case.root / "workspace" else path, *args, **kwargs)
    monkeypatch.setattr(os, "stat", aliased)
    refused(case, module, reason="workspace_root_shared")


def test_workspace_root_identity(case, monkeypatch):
    root_storage_witness(case, launch, monkeypatch)


def location_witness(case, module, monkeypatch, kind="executable"):
    # Model another directory spelling using real metadata from the fixture.
    original = os.fstat
    protected = (case.root / "workspace").stat()
    tools = case.executable.parent.stat()
    if kind == "wrapper":
        case.envelope["launch_inputs"]["executable"] = str(case.root / "operator/tool")
        (case.root / "operator/tool").write_bytes(b"synthetic")
        (case.root / "operator/tool").chmod(0o700)
    elif kind == "trusted":
        tools = case.config.config_path.parent.stat()
    def aliased(fd):
        info = original(fd)
        return protected if (info.st_dev, info.st_ino) == (tools.st_dev, tools.st_ino) else info
    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", aliased)
        refused(case, module, reason="untrusted_location")


@pytest.mark.parametrize("kind", ["executable", "wrapper", "trusted"])
def test_location_identity(case, monkeypatch, kind):
    location_witness(case, launch, monkeypatch, kind)


def nesting_witness(case, module, monkeypatch):
    directory = case.root / "alias"
    directory.mkdir()
    workspace = directory / "workspace"
    workspace.mkdir()
    case.envelope["launch_inputs"]["workspace"] = str(workspace)
    original = os.stat
    def aliased(path, *args, **kwargs):
        return original(case.root / "target" if path == directory else path, *args, **kwargs)
    monkeypatch.setattr(os, "stat", aliased)
    refused(case, module, reason="workspace_unknown")


def test_workspace_ancestor_identity(case, monkeypatch):
    nesting_witness(case, launch, monkeypatch)


@pytest.mark.parametrize("field", ["workspace", "target", "executable", "wrappers"])
def test_canonical_locations(case, field):
    inputs = case.envelope["launch_inputs"]
    if field == "wrappers":
        inputs[field] = ["/" + inputs[field][0]]
    else:
        inputs[field] = "/" + inputs[field]
    refused(case, reason="canonical_path_required")


@pytest.mark.parametrize("name", ["workspace", "target", "references"])
def test_excluded_root_kind(case, name):
    root = case.root / name
    directory = root.with_name(name + "_real")
    root.rename(directory)
    root.symlink_to(directory, target_is_directory=True)
    refused(case, reason="excluded_root_invalid")


@pytest.mark.parametrize("setting", ["nested", "worktree", "include", "includeif", "extensions", "http-alternates"])
def test_workspace_git_data(case, setting):
    git_data_witness(case, launch, setting)


def git_data_witness(case, module, setting="nested"):
    qualify(case)
    workspace = case.root / "workspace"
    if setting == "nested":
        (workspace / "sub").mkdir()
        (workspace / "sub/.git").write_text("gitdir: ../../target/.git")
        reason = "workspace_gitfile"
    else:
        (workspace / ".git").mkdir()
        name = "http-alternates" if setting == "http-alternates" else "config"
        data = {"worktree": "[core]\n worktree = ../target", "include": "[include]\n path = ../target/config",
                "includeif": '[includeIf "gitdir:*"]\n path = ../target/config',
                "extensions": "[extensions]\n worktreeConfig = true", "http-alternates": "../target"}[setting]
        (workspace / ".git" / name).write_text(data)
        reason = "workspace_storage" if setting == "http-alternates" else "workspace_gitconfig"
    refused(case, module, reason=reason)


def test_process_attempt_reservation(case):
    first = prepare(case)
    second = prepare(case, validator=lambda view: first.admit)
    assert isinstance(launch.consume_admission(first), launch.LaunchInputs)
    assert launch.consume_admission(second) == launch.Refused("attempt_replayed")


@pytest.mark.parametrize("name", ["instruction", "baseline"])
def test_reference_link_identity(case, name):
    os.link(case.root / "references" / name, case.root / "linked")
    refused(case, reason="reference_links")


@pytest.mark.parametrize("callback", ["validator", "decoder"])
@pytest.mark.parametrize("error", [SystemExit, KeyboardInterrupt])
def test_callback_refusal(case, callback, error):
    def failure(_view):
        raise error()
    kwargs = {"validator": admit, "decoder": codec}
    kwargs[callback] = failure
    assert launch.prepare_launch(json.dumps(case.envelope).encode(), config=case.config, **kwargs) == launch.Refused(
        "validator_exception" if callback == "validator" else "codec_exception")


def test_registry_binding(case):
    prepared = prepare(case)
    inputs = replace(prepared.view.inputs, timeout=31)
    view = replace(prepared.view, inputs=inputs,
                   launch_digest=launch._launch_digest(prepared.view.raw_digest, inputs, prepared.admit.attempt_id))
    object.__setattr__(prepared, "view", view)
    object.__setattr__(prepared, "admit", launch.Admit(view.launch_digest, prepared.admit.attempt_id))
    assert launch.consume_admission(prepared) == launch.Refused("consume_binding")


def test_file_capture_reads_to_eof(case, monkeypatch):
    original = os.read
    monkeypatch.setattr(os, "read", lambda fd, count: original(fd, min(count, 3)))
    assert isinstance(prepare(case), launch.PreparedLaunch)


def test_file_capture_metadata_before_read(case, monkeypatch):
    calls = []
    original = os.open
    def opened(path, flags, *args, **kwargs):
        calls.append((str(path), flags))
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", opened)
    with pytest.raises(launch._Refusal, match="reference_regular"):
        launch._read_file(Path("/dev/null"), cap=10)
    assert all(flags & os.O_PATH and flags & os.O_CLOEXEC for _, flags in calls)


def config_grammar_witness(case, module, data='[core]\n filemode = "true"'):
    qualify(case)
    directory = case.root / "workspace/.git"
    directory.mkdir()
    (directory / "config").write_text(data)
    refused(case, module, reason="workspace_gitconfig")


@pytest.mark.parametrize("data", [
    '[core]\n filemode = "true"', '[core]\n filemode = true\\\n bare = false',
    '["core"]\n bare = false', '[include]\n path = config',
    '[core]\n fsmonitor = true', '[other]\n key = value',
])
def test_config_grammar(case, data):
    config_grammar_witness(case, launch, data)


def test_config_clean_clone(case):
    qualify(case)
    directory = case.root / "workspace/.git"
    directory.mkdir()
    (directory / "config").write_text(
        '[core]\n repositoryformatversion = 0\n filemode = true\n bare = false\n logallrefupdates = true\n'
        '[remote "origin"]\n url = https://example.invalid/repo\n fetch = +refs/heads/*:refs/remotes/origin/*\n'
        '[branch "main"]\n remote = origin\n merge = refs/heads/main\n[extensions]\n objectformat = sha256\n')
    assert isinstance(prepare(case), launch.PreparedLaunch)


def path_spelling_witness(case, module, kind="ancestor"):
    alias = case.root / "alias"
    if kind == "ancestor":
        alias.symlink_to(case.root / "operator", target_is_directory=True)
        path = alias / "config.json"
    else:
        alias.symlink_to(case.config.config_path)
        path = alias
    case.config = replace(case.config, config_path=path)
    refused(case, module, reason="path_symlink")


@pytest.mark.parametrize("kind", ["ancestor", "alias"])
def test_path_spelling_refusal(case, kind):
    path_spelling_witness(case, launch, kind)


def callback_value_witness(case, module, kind):
    class Text(str):
        pass
    if kind == "codec_invalid":
        refused(case, module, decoder=lambda capture: (capture.envelope, Text(capture.raw_digest)),
                reason="codec_invalid")
    elif kind == "admit_fields":
        refused(case, module, validator=lambda view: module.Admit(Text(view.launch_digest), view.envelope["attempt_id"]),
                reason="admit_fields")
    elif kind == "outer_refusal":
        from collections.abc import Mapping
        class Deferred(Mapping):
            def __iter__(self):
                raise SystemExit()
            def __len__(self):
                raise KeyboardInterrupt()
            def __getitem__(self, key):
                raise SystemExit()
        refused(case, module, decoder=lambda capture: (Deferred(), capture.raw_digest), reason="launch_invalid")
    else:
        prepared = prepare(case, module)
        result = module.consume_admission(prepared)
        assert isinstance(result, module.LaunchInputs)
        assert result == prepared.view.inputs
        assert result is not prepared.view.inputs


@pytest.mark.parametrize("kind", ["codec_invalid", "admit_fields", "outer_refusal", "registry_inputs"])
def test_callback_values(case, kind):
    callback_value_witness(case, launch, kind)


def trusted_links_witness(case, module, kind="config"):
    path = {"config": case.config.config_path, "template": case.config.template_path,
            "executable": case.executable, "wrapper": case.wrapper}[kind]
    os.link(path, case.root / "linked")
    refused(case, module, reason="reference_links")


@pytest.mark.parametrize("kind", ["config", "template", "executable", "wrapper"])
def test_trusted_links(case, kind):
    trusted_links_witness(case, launch, kind)
