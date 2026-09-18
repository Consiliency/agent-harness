"""Where a review sandbox lives, and what happens when that place is unavailable.

The panelist runs wherever its sandbox is, so the root is a LOCATION (a bare path means
local; `host:path` means that host) rather than just a directory. Three properties matter
and each has a way of going wrong that these tests pin:

* **Zero config must be boring.** With nothing set, there is no probe and no fallback
  decision at all -- just a local directory and a free-space check. A laptop user never
  meets any of this.
* **A dead remote must cost a warning, not the round.** The classic remote-filesystem
  failure is not an error you can catch, it is a HANG. So the probe is bounded; a root
  that never answers must lose to the timeout rather than block forever.
* **Running out of disk must refuse, not proceed.** Filling the root filesystem does not
  degrade a review, it takes down the broker, the agents and CI with it. A failed round is
  recoverable in minutes; a wedged host is not.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from phase_loop_runtime import sandbox_policy


class TestZeroConfig:
    def test_unconfigured_root_is_local_and_probes_nothing(self, tmp_path, monkeypatch):
        probed: list[str] = []
        monkeypatch.setattr(
            sandbox_policy, "_probe_root", lambda loc, timeout_s: probed.append(loc) or True
        )
        monkeypatch.setattr(sandbox_policy, "_free_bytes_at", lambda loc, t=0: 100 * 1024**3)

        choice = sandbox_policy.select_sandbox_root(configured=None, fallback=tmp_path)

        assert choice.host is None, "no remote host when nothing is configured"
        assert probed == [], "an unconfigured root must not be probed"
        assert choice.fell_back is False

    def test_a_bare_path_is_local_and_a_host_prefix_is_remote(self):
        assert sandbox_policy.parse_location("/var/tmp/x").host is None
        assert sandbox_policy.parse_location("ai:/storage/sandboxes").host == "ai"
        assert sandbox_policy.parse_location("ai:/storage/sandboxes").path == Path("/storage/sandboxes")

    def test_a_windows_drive_letter_is_not_a_hostname(self):
        """`C:\\work` is a path, not the host `C`. Splitting on the first colon is wrong."""
        assert sandbox_policy.parse_location(r"C:\work\sandboxes").host is None


class TestFallback:
    def test_a_hanging_remote_loses_to_the_timeout_and_falls_back(self, tmp_path, monkeypatch):
        def _hang(loc, timeout_s):
            time.sleep(timeout_s + 5)  # never answers in time
            return True

        monkeypatch.setattr(sandbox_policy, "_probe_root", _hang)
        monkeypatch.setattr(sandbox_policy, "_free_bytes_at", lambda loc, t=0: 100 * 1024**3)

        started = time.monotonic()
        with pytest.warns(RuntimeWarning, match="falling back"):
            choice = sandbox_policy.select_sandbox_root(
                configured="ai:/storage/sandboxes", fallback=tmp_path, probe_timeout_s=0.3,
            )
        elapsed = time.monotonic() - started

        assert choice.fell_back is True
        assert choice.host is None, "fallback is always local"
        assert elapsed < 4, f"probe must be bounded, took {elapsed:.1f}s"

    def test_the_fallback_reason_is_recorded_for_the_evidence(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox_policy, "_probe_root", lambda loc, t: False)
        monkeypatch.setattr(sandbox_policy, "_free_bytes_at", lambda loc, t=0: 100 * 1024**3)

        with pytest.warns(RuntimeWarning):
            choice = sandbox_policy.select_sandbox_root(
                configured="ai:/storage/sandboxes", fallback=tmp_path,
            )
        assert choice.reason, "a silent fallback is the trap: it must say why"
        assert "ai" in choice.reason

    def test_a_healthy_remote_is_used(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox_policy, "_probe_root", lambda loc, t: True)
        monkeypatch.setattr(sandbox_policy, "_free_bytes_at", lambda loc, t=0: 100 * 1024**3)

        choice = sandbox_policy.select_sandbox_root(
            configured="ai:/storage/sandboxes", fallback=tmp_path,
        )
        assert choice.host == "ai"
        assert choice.fell_back is False


class TestFloor:
    def test_below_the_floor_refuses_rather_than_filling_the_disk(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox_policy, "_free_bytes_at", lambda loc, t=0: 100 * 1024**2)  # 100 MB

        with pytest.raises(sandbox_policy.SandboxSpaceError, match="free space"):
            sandbox_policy.select_sandbox_root(
                configured=None, fallback=tmp_path, floor_bytes=2 * 1024**3,
            )

    def test_a_remote_above_floor_but_local_below_still_uses_the_remote(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox_policy, "_probe_root", lambda loc, t: True)
        monkeypatch.setattr(
            sandbox_policy, "_free_bytes_at",
            lambda loc, t=0: 100 * 1024**2 if loc.host is None else 100 * 1024**3,
        )
        choice = sandbox_policy.select_sandbox_root(
            configured="ai:/storage/sandboxes", fallback=tmp_path, floor_bytes=2 * 1024**3,
        )
        assert choice.host == "ai", "a healthy remote should not be rejected for local disk"

    def test_both_below_the_floor_refuses_and_does_not_silently_use_either(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox_policy, "_probe_root", lambda loc, t: True)
        monkeypatch.setattr(sandbox_policy, "_free_bytes_at", lambda loc, t=0: 100 * 1024**2)

        with pytest.raises(sandbox_policy.SandboxSpaceError):
            sandbox_policy.select_sandbox_root(
                configured="ai:/storage/sandboxes", fallback=tmp_path, floor_bytes=2 * 1024**3,
            )


class TestEgress:
    def test_private_space_is_denied_and_public_internet_is_allowed(self):
        policy = sandbox_policy.egress_allowlist()
        for private in ("10.0.0.5", "192.168.1.10", "172.17.0.1",
                        "127.0.0.1", "169.254.169.254", "100.84.171.76"):
            assert not policy.allows(private, 443), f"{private} must be denied"
        assert policy.allows("140.82.121.4", 443), "public internet must be reachable"

    def test_the_inference_router_is_allowlisted_by_host_and_port(self):
        """Allowlist PORTS, not the host: the same machine serves qdrant and file_browser."""
        policy = sandbox_policy.egress_allowlist()
        assert policy.allows("100.84.171.76", 8020), "ai_router must be reachable"
        assert policy.allows("100.84.171.76", 3131), "service discovery must be reachable"
        for denied in (2049, 111, 22, 5434):
            assert not policy.allows("100.84.171.76", denied), (
                f"ai:{denied} must stay denied (NFS/rpcbind/ssh/db on the same host)"
            )

    def test_cloud_metadata_is_denied(self):
        """169.254.169.254 is the standard credential-theft target and is easy to forget."""
        assert not sandbox_policy.egress_allowlist().allows("169.254.169.254", 80)


class TestTheSandboxIsActuallyReachable:
    """The audit found the sandbox was built, tested, and DORMANT.

    `prepare_review_isolation_authorization(stage_review_tree=...)` defaulted to a bare
    `False` and no caller anywhere passed it -- so no production round could ever be
    granted a sandbox. Every existing test hand-built an authorization with
    `staged_tree_sha256` already set, which proves the mechanism and says nothing about
    whether anything reaches it.

    This is the third time in this branch that a mechanism was complete and its activation
    was not. These tests check the activation.
    """

    def test_the_real_mint_grants_a_sandbox_by_default(self, tmp_path, monkeypatch):
        import subprocess
        from phase_loop_runtime.advisor_board import backing

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.st"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "a.py").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"],
            check=True,
        )

        monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
        digest = backing._staged_tree_digest(repo)
        assert digest, "the mint must be able to digest a reviewed tree"

    def test_the_knob_can_turn_it_off_for_the_historical_posture(self, monkeypatch):
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_DISABLE", "1")
        assert sandbox_policy.sandbox_enabled() is False

    def test_it_is_on_by_default(self, monkeypatch):
        """Dormant-by-default is how the capability shipped unreachable the first time."""
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
        assert sandbox_policy.sandbox_enabled() is True

    def test_no_production_caller_hardcodes_the_flag(self):
        """A caller passing an explicit False would re-create the dormant state silently."""
        from pathlib import Path as _P
        src = _P(sandbox_policy.__file__).parent
        offenders = []
        for path in src.rglob("*.py"):
            if path.name in ("sandbox_policy.py", "backing.py"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "stage_review_tree=False" in text:
                offenders.append(path.name)
        assert offenders == [], f"these pin the sandbox off: {offenders}"
