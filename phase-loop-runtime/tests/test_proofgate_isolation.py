"""test_proofgate_isolation.py — PROOFGATE sandbox and isolation tests."""

from __future__ import annotations

import hashlib
import json

import pytest

from .proofgate_tdd_guard import (
    ATTENDED_REAL_PROVIDER_CASES,
    ProofgateMissingCapabilityError,
    guard_proofgate_nodeid,
    proofgate_attended_live,
    proofgate_attended_runner_envelope,
    run_proofgate_contract,
)


def test_isolation_preflight_masks_host_sibling_receipt_logs_fds_and_credentials():
    nodeid = "phase-loop-runtime/tests/test_proofgate_isolation.py::test_isolation_preflight_masks_host_sibling_receipt_logs_fds_and_credentials"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_isolation
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_isolation module missing") from err

        if not hasattr(proofgate_isolation, "BubblewrapIsolationBuilder") and not hasattr(proofgate_isolation, "IsolationPreflight"):
            raise ProofgateMissingCapabilityError("proofgate_isolation missing BubblewrapIsolationBuilder or IsolationPreflight capability")

        builder_cls = getattr(proofgate_isolation, "BubblewrapIsolationBuilder", getattr(proofgate_isolation, "IsolationPreflight", None))
        builder = builder_cls()

        # Execute syscall/namespace/reciprocal owner visibility matrix probes
        probe_code = (
            "import os, sys, socket, errno, ctypes, struct\n"
            "matrix = {}\n"
            "for host_path in ['/root/.ssh/id_rsa', '/etc/shadow', '/proc/1/mem', '/tmp/proofgate_receipts.log']:\n"
            "    try:\n"
            "        with open(host_path, 'r') as f: f.read()\n"
            "        matrix[f'read:{host_path}'] = 'ACCESSIBLE'\n"
            "    except (PermissionError, OSError) as e:\n"
            "        if getattr(e, 'errno', None) in (errno.EPERM, errno.EACCES):\n"
            "            matrix[f'read:{host_path}'] = 'DENIED'\n"
            "        else:\n"
            "            matrix[f'read:{host_path}'] = f'ERROR_{getattr(e, \"errno\", \"UNKNOWN\")}'\n"
            "libc = ctypes.CDLL(None, use_errno=True)\n"
            "raw_pid = os.environ.get('PROOFGATE_BOUND_OWNER_PID')\n"
            "if not raw_pid:\n"
            "    raise ValueError('Missing PROOFGATE_BOUND_OWNER_PID')\n"
            "try:\n"
            "    owner_pid = int(raw_pid)\n"
            "except (ValueError, TypeError):\n"
            "    raise ValueError(f'Malformed PROOFGATE_BOUND_OWNER_PID: {raw_pid}')\n"
            "if owner_pid <= 0 or owner_pid == os.getpid():\n"
            "    raise ValueError(f'Invalid non-self PROOFGATE_BOUND_OWNER_PID: {owner_pid}')\n"
            "r_pipe, w_pipe = os.pipe()\n"
            "valid_fd_bytes = struct.pack('i', r_pipe)\n"
            "buf = ctypes.create_string_buffer(64)\n"
            "class IOVec(ctypes.Structure):\n"
            "    _fields_ = [('iov_base', ctypes.c_void_p), ('iov_len', ctypes.c_size_t)]\n"
            "local_iov = IOVec(ctypes.cast(buf, ctypes.c_void_p), 64)\n"
            "remote_iov = IOVec(ctypes.cast(buf, ctypes.c_void_p), 64)\n"
            "def _pidfd_signal_probe():\n"
            "    pfd = libc.syscall(434, owner_pid, 0)\n"
            "    if pfd < 0:\n"
            "        return -1\n"
            "    res = libc.syscall(424, pfd, 0, None, 0)\n"
            "    try:\n"
            "        os.close(pfd)\n"
            "    except Exception:\n"
            "        pass\n"
            "    return res\n"
            "def _scm_probe():\n"
            "    sock_path = '/run/proofgate/intended-inference.sock'\n"
            "    if not os.path.exists(sock_path):\n"
            "        raise OSError(errno.ENOENT, 'Missing socket')\n"
            "    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)\n"
            "    try:\n"
            "        s.sendto(b'x', sock_path)\n"
            "    except Exception:\n"
            "        pass\n"
            "    return s.sendmsg([b'x'], [(socket.SOL_SOCKET, getattr(socket, 'SCM_RIGHTS', 1), valid_fd_bytes)], 0, (sock_path,))\n"
            "PTRACE_ATTACH = 16\n"
            "for probe_name, syscall_fn in [\n"
            "    ('openat', lambda: os.open('/root/.ssh/id_rsa', os.O_RDONLY)),\n"
            "    ('readlink', lambda: os.readlink('/proc/1/exe')),\n"
            "    ('proc_paths', lambda: os.listdir('/proc/1/mem')),\n"
            "    ('ptrace', lambda: libc.ptrace(PTRACE_ATTACH, owner_pid, None, None)),\n"
            "    ('process_vm_readv', lambda: libc.process_vm_readv(owner_pid, ctypes.byref(local_iov), 1, ctypes.byref(remote_iov), 1, 0)),\n"
            "    ('pidfd_open', lambda: libc.syscall(434, owner_pid, 0)),\n"
            "    ('pidfd_send_signal', _pidfd_signal_probe),\n"
            "    ('scm_rights', _scm_probe),\n"
            "    ('alternate_sockets', lambda: socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 0)),\n"
            "    ('keyctl', lambda: libc.syscall(250, 0)),\n"
            "    ('coredump', lambda: os.open('/proc/sys/kernel/core_pattern', os.O_RDONLY)),\n"
            "    ('raw_network', lambda: socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)),\n"
            "]:\n"
            "    ctypes.set_errno(0)\n"
            "    try:\n"
            "        res = syscall_fn()\n"
            "        err = ctypes.get_errno()\n"
            "        if res == -1:\n"
            "            if err in (errno.EPERM, errno.EACCES, errno.ENOSYS) and err != 0:\n"
            "                matrix[probe_name] = 'DENIED'\n"
            "            elif err in (errno.ESRCH, errno.ENOENT, errno.EBADF) or err == 0:\n"
            "                matrix[probe_name] = f'NON_PROBATIVE_{err}'\n"
            "            else:\n"
            "                matrix[probe_name] = f'ERROR_{err}'\n"
            "        else:\n"
            "            matrix[probe_name] = 'EXECUTED'\n"
            "    except OSError as e:\n"
            "        if e.errno in (errno.EPERM, errno.EACCES, errno.ENOSYS) and e.errno != 0:\n"
            "            matrix[probe_name] = 'DENIED'\n"
            "        elif e.errno in (errno.ESRCH, errno.ENOENT, errno.EBADF):\n"
            "            matrix[probe_name] = f'NON_PROBATIVE_{e.errno}'\n"
            "        else:\n"
            "            matrix[probe_name] = f'ERROR_{e.errno}'\n"
            "os.close(r_pipe); os.close(w_pipe)\n"
            "try:\n"
            "    os.kill(1, 0)\n"
            "    matrix['pid1_signal'] = 'ALLOWED'\n"
            "except (PermissionError, OSError) as e:\n"
            "    matrix['pid1_signal'] = 'DENIED'\n"
            "try:\n"
            "    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
            "    s.sendto(b'ping', ('8.8.8.8', 53))\n"
            "    matrix['network'] = 'ALLOWED'\n"
            "except (PermissionError, OSError) as e:\n"
            "    matrix['network'] = 'DENIED'\n"
            "print('ISOLATION_MATRIX:' + str(matrix))\n"
        )

        res = builder.run_bwrap_probe(probe_code=probe_code)
        if not isinstance(res, dict) or res.get("status") != "success":
            raise AssertionError("Bubblewrap isolation probe execution failed")

        matrix = res.get("matrix", {})
        for path_key in ["read:/root/.ssh/id_rsa", "read:/etc/shadow", "read:/proc/1/mem", "read:/tmp/proofgate_receipts.log", "openat", "readlink", "proc_paths", "ptrace", "process_vm_readv", "pidfd_open", "pidfd_send_signal", "scm_rights", "alternate_sockets", "keyctl", "coredump", "raw_network"]:
            assert matrix.get(path_key) == "DENIED", f"{path_key} must be DENIED in isolation matrix"
        assert matrix.get("pid1_signal") == "DENIED"
        assert matrix.get("network") == "DENIED"

        # Credential and FD masking checks
        env_raw = {
            "AWS_SECRET_ACCESS_KEY": "secret123",
            "GITHUB_TOKEN": "ghp_tok",
            "PROOFLOG_KEY": "plk_99",
            "SESSION_TOKEN": "st_55",
            "SLACK_BOT_TOKEN": "xoxb-999",
            "PATH": "/usr/bin:/bin",
            "LANG": "en_US.UTF-8",
            "SAFE_VAR": "value",
        }
        masked_env = builder.mask_credentials_and_config(env_raw)
        denied_credentials = {"AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "PROOFLOG_KEY", "SESSION_TOKEN", "SLACK_BOT_TOKEN"}
        allowed_vars = {"PATH", "LANG", "SAFE_VAR"}

        for cred in denied_credentials:
            assert cred not in masked_env, f"Credential {cred} must be denied in masked_env"
        for var in allowed_vars:
            assert var in masked_env and masked_env[var] == env_raw[var], f"Allowed var {var} must be preserved"
        assert len(masked_env) == 3

        assert builder.verify_open_fds_masked(inherited_fds=[0, 1, 2, 3, 4, 5, 9, 11]) is False
        assert builder.verify_open_fds_masked(inherited_fds=[0, 1, 2]) is True

    run_proofgate_contract(nodeid, _contract)


def test_provider_projection_allows_only_selected_vendor_subscription_material(record_property):
    nodeid = "phase-loop-runtime/tests/test_proofgate_isolation.py::test_provider_projection_allows_only_selected_vendor_subscription_material"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_isolation
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_isolation module missing") from err

        if not hasattr(proofgate_isolation, "project_vendor_subscription") and not hasattr(proofgate_isolation, "AttendedProviderSupervisor"):
            raise ProofgateMissingCapabilityError("proofgate_isolation missing project_vendor_subscription or AttendedProviderSupervisor capability")

        if not hasattr(proofgate_isolation, "verify_response_canary"):
            raise ProofgateMissingCapabilityError("proofgate_isolation missing verify_response_canary capability")

        if not proofgate_attended_live():
            for prov_case in ATTENDED_REAL_PROVIDER_CASES:
                record_property(prov_case, "not_executed_in_ordinary_mode")

            clean_eval = proofgate_isolation.verify_response_canary({
                "response_chunks": (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n", b'{"content":"clean"}'),
                "max_bytes": 1024,
                "transform_closure": "credential_transform_closure.v1",
            })
            assert clean_eval.get("schema") == "taint_clean_bounded_content_frame.v1"
            assert clean_eval.get("refused") is False
            assert clean_eval.get("downstream_bytes") == b'{"content":"clean"}'
            assert clean_eval.get("session_mutations") == 0
            assert clean_eval.get("followup_requests") == 0

            response_canaries = {
                "set_cookie": (b"HTTP/1.1 200 OK\r\nSet-Cookie: sid=synthetic\r\n\r\n",),
                "rotated_token": (b"HTTP/1.1 200 OK\r\nX-Rotated-Token: synthetic\r\n\r\n",),
                "auth_challenge": (b"HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Bearer\r\n\r\n",),
                "redirect": (b"HTTP/1.1 302 Found\r\nLocation: /refresh\r\n\r\n",),
                "refresh_response": (b"HTTP/1.1 200 OK\r\nX-Refresh-Token: synthetic\r\n\r\n",),
                "unsupported_control_metadata": (b"HTTP/1.1 200 OK\r\nX-Upstream-Control: mutate-session\r\n\r\n",),
                "split_transform": (
                    b"HTTP/1.1 200 OK\r\nX-Rotated-Token: c3ludG", b"hldGlj\r\n\r\n",
                ),
                "overflow_encoding": (
                    b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n\r\n" + b"A" * 2048,
                ),
            }
            for canary_id, response_chunks in response_canaries.items():
                refusal_eval = proofgate_isolation.verify_response_canary({
                    "canary_id": canary_id,
                    "response_chunks": response_chunks,
                    "max_bytes": 1024,
                    "transform_closure": "credential_transform_closure.v1",
                    "followup_request_probe": True,
                })
                assert refusal_eval.get("schema") == "proofgate_response_canary.v1"
                assert refusal_eval.get("refused") is True
                assert refusal_eval.get("downstream_bytes") == b""
                assert refusal_eval.get("session_mutations") == 0
                assert refusal_eval.get("followup_requests") == 0
                assert refusal_eval.get("request_count") == 0
        else:
            runner_envelope = proofgate_attended_runner_envelope()
            assert isinstance(runner_envelope, dict) and set(runner_envelope) == {
                "runner_stage",
                "module_identity",
                "head_identity",
                "nonces",
                "broker_digests",
                "profile_digests",
                "provider_receipts",
                "provider_receipts_sha256",
            }
            provider_receipts = runner_envelope["provider_receipts"]
            assert isinstance(provider_receipts, dict)
            assert set(provider_receipts) == set(ATTENDED_REAL_PROVIDER_CASES)
            assert runner_envelope["provider_receipts_sha256"] == hashlib.sha256(
                json.dumps(
                    provider_receipts,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            supervisor = proofgate_isolation.AttendedProviderSupervisor()
            turn_results = supervisor.execute_attended_turn_matrix()
            assert isinstance(turn_results, dict)
            assert turn_results.get("schema") == "proofgate_attended_turn_matrix.v1"
            assert set(turn_results.get("records", {})) == set(ATTENDED_REAL_PROVIDER_CASES)

            for prov_case in ATTENDED_REAL_PROVIDER_CASES:
                record = turn_results["records"][prov_case]
                receipt = provider_receipts[prov_case]
                assert receipt.get("schema") == "proofgate_attended_provider_receipt.v1"
                assert receipt.get("provider_case") == prov_case
                assert receipt.get("subscription_transport_observed") is True
                assert receipt.get("process_start_token")
                for digest_field in (
                    "first_party_executable_sha256",
                    "protocol_sha256",
                    "request_transcript_sha256",
                    "response_transcript_sha256",
                ):
                    assert len(receipt.get(digest_field, "")) == 64
                assert record.get("request_count", 0) >= 2
                assert record.get("turn_count", 0) >= 2
                assert record.get("tool_round_trip_count", 0) >= 1
                assert record.get("fixed_socket") == "/run/proofgate/intended-inference.sock"
                assert record.get("transport_schema") == "subscription_auth_transport_adapter.v1"
                assert record.get("response_provenance") == "subscription_transport_broker.v1"
                expected_property = {
                    "runner_stage": runner_envelope["runner_stage"],
                    "module_identity": runner_envelope["module_identity"],
                    "head_identity": runner_envelope["head_identity"],
                    "nonce": runner_envelope["nonces"][prov_case],
                    "broker_digest": runner_envelope["broker_digests"][prov_case],
                    "profile_digest": runner_envelope["profile_digests"][prov_case],
                    "fixed_socket": "/run/proofgate/intended-inference.sock",
                    "transport_schema": "subscription_auth_transport_adapter.v1",
                    "response_provenance": "subscription_transport_broker.v1",
                    "request_count": record["request_count"],
                    "turn_count": record["turn_count"],
                    "tool_round_trip_count": record["tool_round_trip_count"],
                }
                property_value = json.loads(record["property_value"])
                assert property_value == expected_property
                assert record.get("nonce") == expected_property["nonce"]
                record_property(
                    prov_case,
                    json.dumps(expected_property, sort_keys=True, separators=(",", ":")),
                )

        # Closed 4-provider subscription projection & reciprocal denial
        all_subs = {
            "fable": {"key": "fable-secret", "session_selector": "fable-sess-1"},
            "sol": {"key": "sol-secret", "session_selector": "sol-sess-2"},
            "gemini": {"key": "gemini-secret", "session_selector": "gemini-sess-3"},
            "grok": {"key": "grok-secret", "session_selector": "grok-sess-4"},
        }
        for selected in ("gemini", "sol", "fable", "grok"):
            proj = proofgate_isolation.project_vendor_subscription(all_subs, selected_vendor=selected)
            assert selected in proj, f"Selected vendor {selected} must be present"
            for unselected in {"gemini", "sol", "fable", "grok"} - {selected}:
                assert unselected not in proj, f"Unselected vendor {unselected} must be reciprocally denied"
            assert "key" not in proj[selected], f"Raw secret key must be stripped from {selected}"

    run_proofgate_contract(nodeid, _contract)


def test_capability_socket_rejects_privileged_unknown_replayed_or_wrong_peer_requests():
    nodeid = "phase-loop-runtime/tests/test_proofgate_isolation.py::test_capability_socket_rejects_privileged_unknown_replayed_or_wrong_peer_requests"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_isolation
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_isolation module missing") from err

        if not hasattr(proofgate_isolation, "CapabilitySocketController"):
            raise ProofgateMissingCapabilityError("proofgate_isolation missing CapabilitySocketController capability")

        sock = proofgate_isolation.CapabilitySocketController(allowed_peer_uid=1000)

        # Closed structured request cases over AF_UNIX peer/replay/preregistered-byte/network-counter matrix
        req_priv1 = {"action": "sudo_exec", "peer_uid": 1000, "nonce": "n1"}
        req_priv2 = {"action": "root_write", "peer_uid": 1000, "nonce": "n1b"}
        for req_priv in (req_priv1, req_priv2):
            with pytest.raises(proofgate_isolation.CapabilitySocketError, match="privileged"):
                sock.handle_request(req_priv)

        req_unk1 = {"action": "unknown_cmd", "peer_uid": 1000, "nonce": "n2"}
        req_unk2 = {"action": "exec_raw", "peer_uid": 1000, "nonce": "n2b"}
        for req_unk in (req_unk1, req_unk2):
            with pytest.raises(proofgate_isolation.CapabilitySocketError, match="unknown"):
                sock.handle_request(req_unk)

        req_valid = {"action": "read_status", "peer_uid": 1000, "nonce": "n3"}
        sock.handle_request(req_valid)
        with pytest.raises(proofgate_isolation.CapabilitySocketError, match="replayed"):
            sock.handle_request(req_valid)

        req_wrong_peer = {"action": "read_status", "peer_uid": 9999, "nonce": "n4"}
        with pytest.raises(proofgate_isolation.CapabilitySocketError, match="wrong_peer"):
            sock.handle_request(req_wrong_peer)

    run_proofgate_contract(nodeid, _contract)


def test_execute_and_panel_routes_use_remote_less_assigned_clone_or_refuse():
    nodeid = "phase-loop-runtime/tests/test_proofgate_isolation.py::test_execute_and_panel_routes_use_remote_less_assigned_clone_or_refuse"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_isolation
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_isolation module missing") from err

        if not hasattr(proofgate_isolation, "ExecuteAndPanelRoute"):
            raise ProofgateMissingCapabilityError("proofgate_isolation missing ExecuteAndPanelRoute capability")

        route = proofgate_isolation.ExecuteAndPanelRoute()

        clone_config = route.prepare_assigned_clone(source_repo="/tmp/repo", remotes=["origin", "upstream", "fork", "mirror"])
        assert clone_config["remotes"] == []
        assert clone_config["is_remote_less"] is True

        for bad_remote in ("origin", "upstream", "fork", "mirror"):
            with pytest.raises(proofgate_isolation.IsolationRouteError, match="refuse_remotes_attached"):
                route.validate_assigned_clone(clone_dir="/tmp/clone", remaining_remotes=[bad_remote])

    run_proofgate_contract(nodeid, _contract)
