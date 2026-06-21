import json
import threading
import time
import unittest
from urllib import request
from urllib.error import HTTPError

from phase_loop_runtime.claude_channel_sidecar import (
    ACK_POLICY_TOOL_REQUIRED,
    CLAUDE_AUTH_POSTURES,
    CLAUDE_BILLING_POSTURES,
    CLAUDE_ROUTE_NAMES,
    ClaudeRouteResult,
    ChannelSidecar,
    ChannelSidecarClient,
    ChannelSidecarClientError,
    PermissionAuditEntry,
    PermissionRequestEnvelope,
    PermissionVerdictPayload,
    build_server,
)


class ClaudeChannelSidecarTest(unittest.TestCase):
    def test_claude_route_result_serializes_if_0_dfchcontract_1_fields(self):
        result = ClaudeRouteResult(
            route="claude_channel",
            session_id="session-a",
            event_id="event-a",
            status="done",
            text="complete",
            artifacts=({"name": "summary", "ref": "artifact://summary", "sha256": "a" * 64},),
            auth_posture="subscription_local",
            billing_posture="subscription_included",
            trust_state={"workspace": "trusted", "mcp": "approved"},
            permission_state={"pending": 0, "last_verdict": "allow"},
            warnings=("channel notifications require reply-tool acknowledgements",),
            evidence_refs=({"path": ".phase-loop/runs/session-a/terminal-summary.json", "sha256": "b" * 64},),
        )

        payload = result.to_json()

        self.assertEqual(
            set(payload),
            {
                "route",
                "session_id",
                "event_id",
                "status",
                "text",
                "artifacts",
                "auth_posture",
                "billing_posture",
                "trust_state",
                "permission_state",
                "warnings",
                "evidence_refs",
            },
        )
        self.assertEqual(payload["route"], "claude_channel")
        self.assertEqual(payload["auth_posture"], "subscription_local")
        self.assertEqual(payload["billing_posture"], "subscription_included")
        self.assertEqual(payload["permission_state"], {"pending": 0, "last_verdict": "allow"})
        self.assertEqual(payload["artifacts"][0]["ref"], "artifact://summary")
        self.assertEqual(payload["evidence_refs"][0]["path"], ".phase-loop/runs/session-a/terminal-summary.json")
        serialized = json.dumps(payload)
        self.assertNotIn("Authorization", serialized)
        self.assertNotIn("provider payload", serialized)
        self.assertNotIn("raw prompt", serialized)

    def test_claude_route_result_literal_contract_covers_routes_and_billing(self):
        for route in sorted(CLAUDE_ROUTE_NAMES):
            with self.subTest(route=route):
                payload = ClaudeRouteResult(
                    route=route,
                    session_id=f"{route}-session",
                    event_id=f"{route}-event",
                    status="blocked" if route == "claude_print" else "done",
                    auth_posture="api_key" if route == "claude_print" else "subscription_local",
                    billing_posture="api_key_billed" if route == "claude_print" else "subscription_included",
                ).to_json()
                self.assertEqual(payload["route"], route)

        self.assertTrue({"subscription_local", "api_key", "unknown"}.issubset(CLAUDE_AUTH_POSTURES))
        self.assertTrue({"subscription_included", "api_key_billed", "usage_credit", "unknown"}.issubset(CLAUDE_BILLING_POSTURES))

        with self.assertRaisesRegex(ValueError, "Claude route"):
            ClaudeRouteResult(route="claude_tui", session_id="s", event_id="e", status="done")
        with self.assertRaisesRegex(ValueError, "Claude billing posture"):
            ClaudeRouteResult(route="claude_channel", session_id="s", event_id="e", status="done", billing_posture="free")

    def test_session_registry_exposes_if_0_session_1_fields_without_secrets(self):
        sidecar = ChannelSidecar(bearer_token="local-token")

        session = sidecar.register_session(
            {
                "session_id": "session-a",
                "adapter": "claude_channel",
                "cwd": "/repo",
                "auth_posture": {"logged_in": True, "provider": "subscription"},
                "trust_state": {"workspace": "trusted", "mcp": "approved"},
                "channel_health": "starting",
            }
        )

        expected_fields = {
            "session_id",
            "adapter",
            "cwd",
            "state",
            "auth_posture",
            "trust_state",
            "channel_health",
            "last_event_id",
            "last_reply_at",
            "permission_state",
        }
        self.assertEqual(set(session), expected_fields)
        self.assertEqual(session["adapter"], "claude_channel")
        self.assertEqual(session["state"], "starting")
        self.assertEqual(session["last_event_id"], None)
        self.assertEqual(sidecar.list_sessions(), [session])
        serialized = json.dumps(session)
        self.assertNotIn("local-token", serialized)
        self.assertNotIn("payload", serialized)

        with self.assertRaisesRegex(ValueError, "secret-like"):
            sidecar.register_session(
                {
                    "session_id": "bad",
                    "adapter": "claude_channel",
                    "cwd": "/repo",
                    "auth_posture": {"token": "redacted"},
                }
            )

    def test_session_state_health_reply_permission_and_stale_transitions(self):
        sidecar = ChannelSidecar()
        sidecar.register_session(
            {
                "session_id": "session-a",
                "adapter": "claude_channel",
                "cwd": "/repo",
                "process_pid": 999999999,
            }
        )

        event = sidecar.create_message("session-a", sender="phase-loop", content="channel-ping")
        after_event = sidecar.get_session("session-a")
        self.assertEqual(after_event["last_event_id"], event.event_id)
        self.assertEqual(after_event["state"], "starting")

        sidecar.record_status({"event_id": event.event_id, "status": "working", "text": "seen", "final": False})
        ready = sidecar.get_session("session-a")
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["channel_health"], "ready")
        self.assertEqual(ready["last_event_id"], event.event_id)
        self.assertTrue(ready["last_reply_at"].endswith("Z"))

        permission_request = sidecar.create_permission_request(
            "session-a",
            {
                "tool_name": "Bash",
                "description": "Run a harmless command",
                "input_preview": "echo ok",
                "risk_class": "low",
            },
        )
        pending = sidecar.get_session("session-a")
        self.assertEqual(pending["permission_state"]["pending"], 1)
        self.assertEqual(pending["permission_state"]["last_request_id"], permission_request.request_id)
        self.assertEqual(pending["state"], "needs_permission")
        self.assertEqual(permission_request.event_id, event.event_id)
        self.assertTrue(permission_request.audit_ref.startswith("claude_permission:session-a:"))
        sidecar.record_permission_verdict(
            "session-a",
            {
                "request_id": permission_request.request_id,
                "verdict": "deny",
                "actor": "operator",
                "reason": "policy",
            },
        )
        blocked = sidecar.get_session("session-a")
        self.assertEqual(blocked["state"], "blocked")
        self.assertEqual(blocked["channel_health"], "blocked")
        self.assertEqual(blocked["permission_state"]["pending"], 0)
        self.assertEqual(blocked["permission_state"]["last_verdict"], "deny")
        self.assertEqual(blocked["permission_state"]["last_audit_ref"], permission_request.audit_ref)

        stopped = sidecar.update_session_state("session-a", state="stopped", channel_health="stopped")
        self.assertEqual(stopped["state"], "stopped")
        sidecar.update_session_state("session-a", state="starting", channel_health="starting")
        stale = sidecar.mark_stale_sessions(older_than_seconds=0, live_pids=set())
        self.assertEqual(stale[0]["state"], "stale")
        self.assertEqual(stale[0]["channel_health"], "stopped")

    def test_message_envelope_has_stable_event_id_and_metadata_attachments(self):
        sidecar = ChannelSidecar()

        event = sidecar.create_message(
            "session-a",
            sender="phase-loop",
            content="channel-ping",
            attachments=[{"name": "summary", "ref": "artifact://summary", "mime_type": "text/plain"}],
        )

        self.assertTrue(event.event_id)
        self.assertEqual(event.session_id, "session-a")
        self.assertEqual(event.sender, "phase-loop")
        self.assertEqual(event.ack_policy, ACK_POLICY_TOOL_REQUIRED)
        self.assertEqual(event.attachments[0]["ref"], "artifact://summary")
        listed = sidecar.list_events("session-a")[0]
        self.assertEqual(listed["event_id"], event.event_id)
        self.assertFalse(listed["acknowledged"])

        sidecar.record_status({"event_id": event.event_id, "status": "working", "text": "seen", "final": False})
        after_non_final = sidecar.get_event(event.event_id)
        self.assertFalse(after_non_final["acknowledged"])

        sidecar.record_reply({"event_id": event.event_id, "status": "done", "text": "pong", "final": True})
        after_final = sidecar.get_event(event.event_id)
        self.assertTrue(after_final["acknowledged"])
        self.assertEqual(after_final["event_id"], event.event_id)

    def test_attachment_payload_fields_are_rejected(self):
        sidecar = ChannelSidecar()

        with self.assertRaisesRegex(ValueError, "non-metadata"):
            sidecar.create_message("session-a", sender="phase-loop", content="x", attachments=[{"content": "secret"}])

    def test_permission_request_envelope_has_metadata_only_fields(self):
        sidecar = ChannelSidecar()

        permission_request = sidecar.create_permission_request(
            "session-a",
            {
                "tool_name": "Bash",
                "description": "Run a harmless command",
                "input_preview": "echo ok",
                "risk_class": "low",
            },
        )

        self.assertIsInstance(permission_request, PermissionRequestEnvelope)
        self.assertTrue(permission_request.request_id)
        self.assertEqual(permission_request.session_id, "session-a")
        self.assertIsNone(permission_request.event_id)
        self.assertEqual(permission_request.tool_name, "Bash")
        self.assertEqual(permission_request.description, "Run a harmless command")
        self.assertEqual(permission_request.input_preview, "echo ok")
        self.assertEqual(permission_request.risk_class, "low")
        self.assertTrue(permission_request.audit_ref.startswith("claude_permission:session-a:"))
        self.assertTrue(permission_request.requested_at.endswith("Z"))
        self.assertEqual(sidecar.list_permission_requests("session-a")[0]["request_id"], permission_request.request_id)
        serialized = json.dumps(permission_request.to_json())
        self.assertNotIn("payload", serialized)
        self.assertNotIn("token", serialized)

        with self.assertRaisesRegex(ValueError, "raw or secret-like"):
            sidecar.create_permission_request(
                "session-a",
                {
                    "tool_name": "Bash",
                    "description": "bad",
                    "input_preview": "redacted",
                    "risk_class": "high",
                    "payload": {"raw": "secret"},
                },
            )

    def test_permission_verdicts_are_audited_without_raw_inputs(self):
        sidecar = ChannelSidecar()
        permission_request = sidecar.create_permission_request(
            "session-a",
            {
                "tool_name": "Bash",
                "description": "Run a harmless command",
                "input_preview": "echo ok",
                "risk_class": "low",
            },
        )

        audit_entry = sidecar.record_permission_verdict(
            "session-a",
            {
                "request_id": permission_request.request_id,
                "verdict": "allow",
                "actor": "operator",
                "reason": "low risk",
            },
        )

        self.assertIsInstance(PermissionVerdictPayload(**{k: audit_entry[k] for k in ("request_id", "verdict", "actor", "reason")} | {"decided_at": audit_entry["decided_at"]}), PermissionVerdictPayload)
        self.assertIsInstance(PermissionAuditEntry(**audit_entry), PermissionAuditEntry)
        self.assertEqual(audit_entry["session_id"], "session-a")
        self.assertEqual(audit_entry["request_id"], permission_request.request_id)
        self.assertEqual(audit_entry["event_id"], permission_request.event_id)
        self.assertEqual(audit_entry["verdict"], "allow")
        self.assertEqual(audit_entry["audit_ref"], permission_request.audit_ref)
        self.assertTrue(audit_entry["decided_at"].endswith("Z"))
        self.assertEqual(sidecar.list_permission_audit("session-a"), [audit_entry])

        deny_request = sidecar.create_permission_request(
            "session-a",
            {
                "tool_name": "Bash",
                "description": "Remove files",
                "input_preview": "rm ...",
                "risk_class": "destructive_operation",
            },
        )
        deny_entry = sidecar.record_permission_verdict(
            "session-a",
            {
                "request_id": deny_request.request_id,
                "verdict": "deny",
                "actor": "operator",
                "reason": "destructive",
            },
        )
        self.assertEqual(deny_entry["verdict"], "deny")

        with self.assertRaisesRegex(KeyError, "unknown request_id"):
            sidecar.record_permission_verdict(
                "session-a",
                {"request_id": "missing", "verdict": "allow", "actor": "operator", "reason": "unknown"},
            )

    def test_verdict_actor_allowlist_fails_closed(self):
        sidecar = ChannelSidecar(allowed_verdict_actors={"operator"})
        permission_request = sidecar.create_permission_request(
            "session-a",
            {
                "tool_name": "Bash",
                "description": "Run a harmless command",
                "input_preview": "echo ok",
                "risk_class": "low",
            },
        )

        with self.assertRaisesRegex(PermissionError, "actor is not allowed"):
            sidecar.record_permission_verdict(
                "session-a",
                {"request_id": permission_request.request_id, "verdict": "allow", "actor": "intruder", "reason": "unknown"},
            )

        self.assertEqual(sidecar.list_permission_audit("session-a"), [])

    def test_auth_and_allowlist_fail_closed_for_message_and_verdict(self):
        sidecar = ChannelSidecar(bearer_token="local-token", allowed_senders={"phase-loop"})

        self.assertEqual(sidecar.authenticate(None).value, 401)
        self.assertEqual(sidecar.authenticate("Bearer wrong").value, 403)
        self.assertIsNone(sidecar.authenticate("Bearer local-token"))

        with self.assertRaisesRegex(PermissionError, "sender"):
            sidecar.create_message("session-a", sender="intruder", content="x")

    def test_loopback_host_is_required(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            build_server("0.0.0.0", 0)

    def test_http_post_and_json_get_events(self):
        server = build_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            payload = json.dumps({"sender": "phase-loop", "content": "channel-ping"}).encode("utf-8")
            req = request.Request(f"{base}/sessions/s1/message", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            event = json.loads(request.urlopen(req, timeout=5).read().decode("utf-8"))

            events = json.loads(request.urlopen(f"{base}/sessions/s1/events", timeout=5).read().decode("utf-8"))["events"]
            self.assertEqual(events[0]["event_id"], event["event_id"])
            self.assertFalse(events[0]["acknowledged"])
        finally:
            server.shutdown()
            server.server_close()

    def test_http_session_registry_routes(self):
        server = build_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            payload = json.dumps(
                {
                    "adapter": "claude_channel",
                    "cwd": "/repo",
                    "auth_posture": {"logged_in": True},
                    "trust_state": {"workspace": "trusted"},
                }
            ).encode("utf-8")
            req = request.Request(f"{base}/sessions/s1/register", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            registered = json.loads(request.urlopen(req, timeout=5).read().decode("utf-8"))
            self.assertEqual(registered["session_id"], "s1")

            sessions = json.loads(request.urlopen(f"{base}/sessions", timeout=5).read().decode("utf-8"))["sessions"]
            self.assertEqual(sessions[0]["session_id"], "s1")
            session = json.loads(request.urlopen(f"{base}/sessions/s1", timeout=5).read().decode("utf-8"))
            self.assertEqual(session["channel_health"], "starting")

            hook_payload = json.dumps({"hook": "Notification", "cwd": "/repo", "permission_mode": "default"}).encode("utf-8")
            hook_req = request.Request(f"{base}/sessions/s1/hook", data=hook_payload, headers={"Content-Type": "application/json"}, method="POST")
            hook = json.loads(request.urlopen(hook_req, timeout=5).read().decode("utf-8"))
            self.assertEqual(hook["hook"], "Notification")
        finally:
            server.shutdown()
            server.server_close()

    def test_http_get_events_as_event_stream(self):
        server = build_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            payload = json.dumps({"sender": "phase-loop", "content": "channel-ping"}).encode("utf-8")
            req = request.Request(f"{base}/sessions/s2/message", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            request.urlopen(req, timeout=5).read()

            stream_req = request.Request(f"{base}/sessions/s2/events", headers={"Accept": "text/event-stream"})
            stream = request.urlopen(stream_req, timeout=5).read().decode("utf-8")
            self.assertIn("data: {", stream)
            self.assertIn('"ack_policy": "tool_ack_required"', stream)
        finally:
            server.shutdown()
            server.server_close()

    def test_http_unknown_event_ack_fails_closed(self):
        server = build_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            payload = json.dumps({"event_id": "missing", "status": "done", "final": True}).encode("utf-8")
            req = request.Request(f"{base}/sessions/s1/reply", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with self.assertRaises(HTTPError) as ctx:
                request.urlopen(req, timeout=5).read()
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()

    def test_http_auth_and_permission_routes(self):
        server = build_server("127.0.0.1", 0, bearer_token="local-token", allowed_senders={"phase-loop"})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            payload = json.dumps({"sender": "phase-loop", "content": "channel-ping"}).encode("utf-8")
            req = request.Request(f"{base}/sessions/s1/message", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with self.assertRaises(HTTPError) as missing:
                request.urlopen(req, timeout=5).read()
            self.assertEqual(missing.exception.code, 401)

            req = request.Request(
                f"{base}/sessions/s1/message",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as wrong:
                request.urlopen(req, timeout=5).read()
            self.assertEqual(wrong.exception.code, 403)

            req = request.Request(
                f"{base}/sessions/s1/message",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": "Bearer local-token"},
                method="POST",
            )
            event = json.loads(request.urlopen(req, timeout=5).read().decode("utf-8"))
            self.assertEqual(event["sender"], "phase-loop")

            request_payload = json.dumps(
                {
                    "tool_name": "Bash",
                    "description": "Run a harmless command",
                    "input_preview": "echo ok",
                    "risk_class": "low",
                }
            ).encode("utf-8")
            req = request.Request(
                f"{base}/sessions/s1/permission/request",
                data=request_payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            permission_request = json.loads(request.urlopen(req, timeout=5).read().decode("utf-8"))
            self.assertEqual(permission_request["session_id"], "s1")

            verdict_payload = json.dumps(
                {
                    "request_id": permission_request["request_id"],
                    "verdict": "deny",
                    "actor": "operator",
                    "reason": "policy",
                }
            ).encode("utf-8")
            req = request.Request(
                f"{base}/sessions/s1/permission/verdict",
                data=verdict_payload,
                headers={"Content-Type": "application/json", "Authorization": "Bearer local-token"},
                method="POST",
            )
            audit_entry = json.loads(request.urlopen(req, timeout=5).read().decode("utf-8"))
            self.assertEqual(audit_entry["request_id"], permission_request["request_id"])
            self.assertEqual(audit_entry["session_id"], "s1")

            audit = json.loads(request.urlopen(f"{base}/sessions/s1/permission/audit", timeout=5).read().decode("utf-8"))["audit"]
            self.assertEqual(audit[0]["verdict"], "deny")
        finally:
            server.shutdown()
            server.server_close()

    def test_client_posts_message_and_returns_final_route_result(self):
        sidecar = ChannelSidecar(bearer_token="local-token", allowed_senders={"phase-loop"})
        sidecar.register_session(
            {
                "session_id": "session-client",
                "adapter": "claude_channel",
                "cwd": "/repo",
                "state": "ready",
                "channel_health": "ready",
                "auth_posture": {"status": "authenticated", "method": "subscription"},
                "trust_state": {"workspace": "trusted", "mcp": "approved"},
            }
        )
        server = build_server("127.0.0.1", 0, sidecar=sidecar, bearer_token="ignored")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def reply() -> None:
            event_id = None
            for _ in range(50):
                events = sidecar.list_events("session-client")
                if events:
                    event_id = events[0]["event_id"]
                    break
                time.sleep(0.01)
            if event_id:
                sidecar.record_reply(
                    {
                        "event_id": event_id,
                        "status": "done",
                        "text": "complete",
                        "artifacts": [{"name": "summary", "ref": "artifact://summary"}],
                        "final": True,
                    }
                )

        try:
            reply_thread = threading.Thread(target=reply, daemon=True)
            reply_thread.start()
            client = ChannelSidecarClient(
                base_url=base,
                session_id="session-client",
                bearer_token="local-token",
                timeout_seconds=2,
                poll_interval_seconds=0.01,
            )
            result = client.send_and_wait("raw prompt stays in the channel event, not in result metadata")
            reply_thread.join(timeout=1)
        finally:
            server.shutdown()
            server.server_close()

        payload = result.to_json()
        self.assertEqual(payload["route"], "claude_channel")
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["text"], "complete")
        self.assertEqual(payload["auth_posture"], "subscription_local")
        self.assertEqual(payload["billing_posture"], "subscription_included")
        self.assertEqual(payload["trust_state"]["workspace"], "trusted")
        self.assertEqual(payload["artifacts"][0]["ref"], "artifact://summary")
        rendered = json.dumps(payload)
        self.assertNotIn("raw prompt", rendered)
        self.assertNotIn("local-token", rendered)

    def test_client_preflight_and_auth_fail_closed_without_secret_echo(self):
        sidecar = ChannelSidecar(bearer_token="local-token", allowed_senders={"phase-loop"})
        sidecar.register_session(
            {
                "session_id": "session-blocked",
                "adapter": "claude_channel",
                "cwd": "/repo",
                "state": "blocked",
                "channel_health": "blocked",
            }
        )
        sidecar.register_session(
            {
                "session_id": "session-ready",
                "adapter": "claude_channel",
                "cwd": "/repo",
                "state": "ready",
                "channel_health": "ready",
            }
        )
        server = build_server("127.0.0.1", 0, sidecar=sidecar, bearer_token="ignored")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with self.assertRaisesRegex(ChannelSidecarClientError, "not ready"):
                ChannelSidecarClient(base_url=base, session_id="session-blocked", bearer_token="local-token").preflight()

            with self.assertRaisesRegex(ChannelSidecarClientError, "session not found"):
                ChannelSidecarClient(base_url=base, session_id="missing", bearer_token="local-token").preflight()

            with self.assertRaises(ChannelSidecarClientError) as ctx:
                ChannelSidecarClient(base_url=base, session_id="session-ready", bearer_token="wrong-token").send_and_wait("channel-ping")
            self.assertEqual(ctx.exception.reason, "channel sidecar authentication failed")
            self.assertNotIn("wrong-token", str(ctx.exception))
            self.assertNotIn("local-token", str(ctx.exception))
        finally:
            server.shutdown()
            server.server_close()

        with self.assertRaisesRegex(ValueError, "loopback"):
            ChannelSidecarClient(base_url="http://example.com:8765", session_id="session-blocked")

    def test_client_timeout_returns_stale_route_result(self):
        sidecar = ChannelSidecar()
        sidecar.register_session(
            {
                "session_id": "session-timeout",
                "adapter": "claude_channel",
                "cwd": "/repo",
                "state": "ready",
                "channel_health": "ready",
            }
        )
        server = build_server("127.0.0.1", 0, sidecar=sidecar)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = ChannelSidecarClient(
                base_url=f"http://127.0.0.1:{server.server_port}",
                session_id="session-timeout",
                timeout_seconds=0.02,
                poll_interval_seconds=0.01,
            )
            result = client.send_and_wait("channel-ping")
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(result.status, "stale")
        self.assertEqual(result.event_id, sidecar.list_events("session-timeout")[0]["event_id"])
        self.assertNotIn("channel-ping", json.dumps(result.to_json()))

    def test_client_timeout_reports_needs_permission_or_input_from_session_state(self):
        for state_kind in ("needs_permission", "needs_input"):
            with self.subTest(state_kind=state_kind):
                sidecar = ChannelSidecar()
                sidecar.register_session(
                    {
                        "session_id": f"session-{state_kind}",
                        "adapter": "claude_channel",
                        "cwd": "/repo",
                        "state": "ready",
                        "channel_health": "ready",
                    }
                )
                server = build_server("127.0.0.1", 0, sidecar=sidecar)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def update_state() -> None:
                    event_id = None
                    for _ in range(50):
                        events = sidecar.list_events(f"session-{state_kind}")
                        if events:
                            event_id = events[0]["event_id"]
                            break
                        time.sleep(0.01)
                    if not event_id:
                        return
                    if state_kind == "needs_permission":
                        sidecar.create_permission_request(
                            f"session-{state_kind}",
                            {
                                "tool_name": "Bash",
                                "description": "Run a harmless command",
                                "input_preview": "echo ok",
                                "risk_class": "low",
                            },
                        )
                    else:
                        sidecar.record_hook_event(f"session-{state_kind}", {"hook": "Notification", "cwd": "/repo", "permission_mode": "default"})

                try:
                    state_thread = threading.Thread(target=update_state, daemon=True)
                    state_thread.start()
                    client = ChannelSidecarClient(
                        base_url=f"http://127.0.0.1:{server.server_port}",
                        session_id=f"session-{state_kind}",
                        timeout_seconds=0.05,
                        poll_interval_seconds=0.01,
                    )
                    result = client.send_and_wait("channel-ping")
                    state_thread.join(timeout=1)
                finally:
                    server.shutdown()
                    server.server_close()

                self.assertEqual(result.status, state_kind)
                self.assertNotIn("channel-ping", json.dumps(result.to_json()))


if __name__ == "__main__":
    unittest.main()
