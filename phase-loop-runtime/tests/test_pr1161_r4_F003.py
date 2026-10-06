from phase_loop_runtime import panel_invoker, sandbox_policy


def test_private_tmp_exception_does_not_require_host_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda path: "tmpfs")
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", "1")
    env = panel_invoker._broker_leg_env(
        {"PATH": "/usr/bin", "HOME": str(tmp_path)}, "gemini", private_tmp=True)
    assert env == {"PATH": "/usr/bin", "HOME": str(tmp_path)}
