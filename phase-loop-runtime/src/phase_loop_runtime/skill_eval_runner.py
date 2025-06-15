"""Owned read-only subject execution. Observation begins after all preparation."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time

from . import launcher, panel_invoker, review_stage, sandbox_egress, sandbox_policy
from .models import ModelSelection
from .seat_tool_evidence import launcher_diagnostic_in
from .skill_eval_access import AccessObserver


def command_for(root, spec, prompt):
    command = launcher.build_codex_command(
        root, ModelSelection(profile="plan", model=spec.model, effort=spec.effort),
        prompt, read_only=True, json_output=True)
    flags = ["--ephemeral", "--ignore-rules", "--strict-config", "-c", 'web_search="disabled"']
    flags.extend(word for feature in panel_invoker._BROKER_CODEX_DISABLED_FEATURES
                 if feature not in panel_invoker._BROKER_CODEX_SANDBOX_ENABLED_FEATURES
                 for word in ("-c", f"features.{feature}=false"))
    # Explicit enables prevent a future CLI default from silently removing read tools.
    flags.extend(word for feature in panel_invoker._BROKER_CODEX_SANDBOX_ENABLED_FEATURES
                 for word in ("-c", f"features.{feature}=true"))
    command[-1:-1] = flags
    command[0] = spec.executable.path
    return command


def require_non_git(path):
    if os.environ.get("LC_ALL") != "C":
        raise ValueError("C locale required before Git discovery")
    try:
        result = review_stage.host_git(path, "rev-parse", "--git-dir",
                                       capture_output=True, text=True, check=False)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError("Git discovery unavailable") from exc
    if result.returncode == 0:
        raise ValueError("staging inside Git refused")
    if result.returncode != 128 or not result.stderr.startswith("fatal: not a git repository"):
        raise ValueError("Git discovery unavailable")


def verify_tree(root, files):
    from .skill_eval import digest
    found = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("staged link refused")
        if path.is_dir():
            continue
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("staged non-private regular file refused")
        found[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    if found != {name: digest(text.encode()) for name, text in files.items()}:
        raise ValueError("staged fixture integrity mismatch")
    return found


@contextmanager
def staged(command, files, parent):
    parent = parent.resolve(strict=True)
    require_non_git(parent)
    materialized = []
    with tempfile.TemporaryDirectory(prefix="eval-", dir=parent) as source:
        preimage = Path(source)
        require_non_git(preimage)
        for name, text in files.items():
            path = preimage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
        command = command(preimage)
        try:
            resolved = launcher._resolve_review_stage(
                command, launcher.CODEX_REVIEW_STAGE_PREFIX, log_path=None, materialized=materialized)
            if any(launcher.CODEX_REVIEW_STAGE_PREFIX in arg for arg in resolved):
                raise ValueError("unresolved review placeholder")
            root = Path(resolved[resolved.index("--cd") + 1]).resolve(strict=True)
            if (root == preimage or root not in [Path(p).resolve() for p in materialized] or
                    root.parent != parent):
                raise ValueError("unowned or escaping final stage")
            require_non_git(root)
            verify_tree(root, files)
            yield resolved, root, preimage
        finally:
            from .sandbox_retention import release_scratch_dir
            for name in materialized:
                owned = Path(name)
                # Only the resolver's recorded copies are ever removed.
                shutil.rmtree(owned)
                release_scratch_dir(owned)


def verify_executable(spec):
    from .skill_eval import digest
    path = Path(spec.executable.path)
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("pinned executable unavailable or linked")
    if digest(path.read_bytes()) != spec.executable.sha256:
        raise ValueError("executable identity changed")
    harness, native = panel_invoker._seat_provider_source(str(path), os.environ)
    if harness != "codex" or Path(native).resolve() != path.resolve():
        raise ValueError("pin the actual native Codex executable, not a wrapper")
    result = panel_invoker._run_leg_with_liveness(
        [str(path), "--version"], cwd=sandbox_policy.staging_root(), env=os.environ,
        deadline_s=panel_invoker._CODEX_SANDBOX_PROBE_TIMEOUT_S)
    if result.returncode != 0 or result.stdout.strip() != spec.executable.version or result.stderr.strip():
        raise ValueError("executable version changed or unavailable")


def probe_sandbox(resolved, owned_command, profile, root):
    probe = panel_invoker._codex_sandbox_probe_command(resolved)
    if probe is None:
        raise ValueError("unsupported inner-sandbox probe")
    probe[0] = owned_command[0]
    proc = panel_invoker.launch_owned(
        probe, role=panel_invoker.SeatLaunchRole.PROVIDER_REVIEW, profile=profile,
        cwd=str(root), env=dict(profile.env), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        panel_invoker._anchor_process_group(proc)
        stdout, stderr = proc.communicate(timeout=panel_invoker._CODEX_SANDBOX_PROBE_TIMEOUT_S)
        if proc.returncode != 0:
            diagnostic = (stdout + stderr).decode(errors="replace")
            raise ValueError("seat_tool_sandbox_unavailable" if launcher_diagnostic_in(diagnostic)
                             else "inner-sandbox probe failed")
    finally:
        try:
            panel_invoker._terminate_process_group(proc)
        finally:
            proc.communicate()


def parse_stream(output, allowlist):
    import json
    message = None
    started = False
    completed = False
    usage = None
    for line in output.splitlines():
        if not line.strip() or line in allowlist:
            continue
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise ValueError("unexpected non-JSON diagnostic") from exc
        if not isinstance(event, dict) or completed:
            raise ValueError("unexpected event after turn completion")
        kind = event.get("type")
        if kind in {"turn.failed", "error"}:
            raise ValueError("failed Codex turn")
        if kind not in {"thread.started", "turn.started", "item.started", "item.updated",
                        "item.completed", "turn.completed"}:
            raise ValueError("unknown Codex event")
        if kind == "thread.started":
            if started:
                raise ValueError("unexpected thread start during turn")
        elif kind == "turn.started":
            if started:
                raise ValueError("multiple Codex turns refused")
            started = True
        elif not started:
            raise ValueError("Codex event before turn start")
        if kind.startswith("item."):
            item = event.get("item")
            if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                raise ValueError("malformed Codex item")
            if kind == "item.completed" and item["type"] == "agent_message":
                message = item.get("text")
                if not isinstance(message, str) or not message.strip():
                    raise ValueError("empty final message")
        if kind == "turn.completed":
            if message is None:
                raise ValueError("missing completed final message")
            completed = True
            usage = event.get("usage")
    if not completed or message is None:
        raise ValueError("incomplete Codex stream")
    return message, usage


def run_trial(experiment, frozen, spec, trial):
    from .skill_eval import ENVELOPE, binding, case_for, digest, files_for, write_new
    directory = experiment / "trials" / trial["id"]
    bound = binding(frozen, spec, trial)
    files = files_for(frozen, spec, trial)
    output = ""
    transcript = ""
    access = {"events": {}, "errors": ["observation_not_started"]}
    launched = {"returncode": None, "probe": "not_passed", "stream_valid": False, "usage": None,
                "interrupted": None, "cleanup_evidence": None}
    status = "invalid"
    reason = "not_started"
    begin = time.monotonic()
    interrupted = None
    try:
        os.environ["LC_ALL"] = "C"
        verify_executable(spec)
        parent = sandbox_policy.staging_root().resolve()
        if parent == experiment.resolve() or experiment.resolve() in parent.parents:
            raise ValueError("stage must be outside experiment")
        with staged(lambda root: command_for(root, spec, ENVELOPE + case_for(spec, trial).prompt),
                    files, parent) as (resolved, root, preimage):
            with ExitStack() as stack:
                prefix = stack.enter_context(sandbox_egress.isolated_network(required=True, timeout_s=None))
                if not prefix:
                    raise ValueError("isolated network unavailable")
                token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
                stack.callback(panel_invoker._EGRESS_LAUNCH_PREFIX.reset, token)
                owned, profile = stack.enter_context(panel_invoker._seat_command_profile(
                    resolved, env={**os.environ, "LC_ALL": "C"}, cwd=root, readonly_paths=(root,)))
                launched.update(command=resolved, owned_executable=owned[0], stage=str(root))
                # The profile can inspect/copy files. Measure only after it and the probe.
                probe_sandbox(resolved, owned, profile, root)
                launched["probe"] = "passed"
                verify_tree(root, files)
                observer = AccessObserver(root, list(files))
                with observer:
                    result = launcher.launch(
                        owned, action="review", _review_profile=profile, cwd=root,
                        env=dict(profile.env), log_path=directory / "subject.log", ephemeral_monitor=True)
                transcript = result.output
                launched.update(returncode=result.returncode, interrupted=result.interrupted,
                                cleanup_evidence=result.cleanup_evidence)
                if result.interrupted:
                    interrupted = KeyboardInterrupt()
                access = observer.receipt()
                if interrupted is not None:
                    raise interrupted
                verify_tree(root, files)
                if result.returncode != 0 or result.timed_out or result.stalled:
                    raise ValueError("subject launch failed")
                output, launched["usage"] = parse_stream(transcript, spec.executable.diagnostic_allowlist)
                launched["stream_valid"] = True
                if access["errors"]:
                    raise ValueError("invalid access observation")
                status, reason = "completed", None
    except BaseException as exc:
        # Terminal evidence survives cancellation; no exception text can leak credentials.
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            interrupted = exc
    finally:
        if not transcript and (directory / "subject.log").is_file():
            transcript = (directory / "subject.log").read_text()
        joined = {**bound, "output_digest": digest(output.encode())}
        launched.update(binding=joined, elapsed_seconds=time.monotonic() - begin,
                        transcript_digest=digest(transcript.encode()))
        access["binding"] = joined
        (directory / "transcript.txt").write_text(transcript)
        write_new(directory / "launch.json", launched)
        write_new(directory / "access.json", access)
        write_new(directory / "terminal.json", {
            "binding": bound, "status": status, "reason": reason, "output": output,
            "interrupted": interrupted is not None,
            "output_digest": joined["output_digest"], "launch_digest": digest(launched),
            "access_digest": digest(access)})
    if interrupted is not None:
        raise interrupted
