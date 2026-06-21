import json
import threading
import unittest
from urllib import request
from urllib.error import HTTPError

from phase_loop_runtime.claude_channel_sidecar import ClaudeRouteResult, ChannelSidecar, build_server


class ClaudeChannelSecurityTest(unittest.TestCase):
    def test_loopback_default_and_remote_bind_refusal_are_frozen(self):
        server = build_server("127.0.0.1", 0)
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
        finally:
            server.server_close()

        for host in ("0.0.0.0", "192.0.2.10"):
            with self.subTest(host=host):
                with self.assertRaisesRegex(ValueError, "loopback"):
                    build_server(host, 0)

    def test_bearer_auth_protects_message_verdict_reply_and_status_writes(self):
        server = build_server("127.0.0.1", 0, bearer_token="local-token", allowed_senders={"phase-loop"})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            event = self._post_json(
                f"{base}/sessions/s1/message",
                {"sender": "phase-loop", "content": "channel-ping"},
                bearer_token="local-token",
            )

            for route in ("reply", "status"):
                with self.subTest(route=route):
                    req = request.Request(
                        f"{base}/sessions/s1/{route}",
                        data=json.dumps({"event_id": event["event_id"], "status": "done", "final": True}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with self.assertRaises(HTTPError) as missing:
                        request.urlopen(req, timeout=5).read()
                    self.assertEqual(missing.exception.code, 401)

            permission_request = self._post_json(
                f"{base}/sessions/s1/permission/request",
                {
                    "tool_name": "Bash",
                    "description": "Run a harmless command",
                    "input_preview": "echo ok",
                    "risk_class": "low",
                },
            )
            verdict = self._post_json(
                f"{base}/sessions/s1/permission/verdict",
                {
                    "request_id": permission_request["request_id"],
                    "verdict": "allow",
                    "actor": "operator",
                    "reason": "metadata-only approval",
                },
                bearer_token="local-token",
            )
            self.assertEqual(verdict["request_id"], permission_request["request_id"])
            self._post_json(
                f"{base}/sessions/s1/reply",
                {"event_id": event["event_id"], "status": "done", "final": True},
                bearer_token="local-token",
            )
        finally:
            server.shutdown()
            server.server_close()

    def test_sender_allowlist_blocks_before_event_enqueue_with_non_secret_summary(self):
        sidecar = ChannelSidecar(allowed_senders={"phase-loop"})

        with self.assertRaisesRegex(PermissionError, "sender is not allowed") as ctx:
            sidecar.create_message("s1", sender="unknown", content="hello")

        self.assertEqual(sidecar.list_events("s1"), [])
        self.assertNotIn("hello", str(ctx.exception))

    def test_verdict_actor_allowlist_blocks_http_verdict_before_audit(self):
        server = build_server("127.0.0.1", 0, bearer_token="local-token", allowed_verdict_actors={"operator"})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            permission_request = self._post_json(
                f"{base}/sessions/s1/permission/request",
                {
                    "tool_name": "Bash",
                    "description": "Run a harmless command",
                    "input_preview": "echo ok",
                    "risk_class": "low",
                },
            )
            req = request.Request(
                f"{base}/sessions/s1/permission/verdict",
                data=json.dumps(
                    {
                        "request_id": permission_request["request_id"],
                        "verdict": "allow",
                        "actor": "intruder",
                        "reason": "unknown",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer local-token"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as blocked:
                request.urlopen(req, timeout=5).read()
            self.assertEqual(blocked.exception.code, 403)
            audit = json.loads(request.urlopen(f"{base}/sessions/s1/permission/audit", timeout=5).read().decode("utf-8"))["audit"]
            self.assertEqual(audit, [])
        finally:
            server.shutdown()
            server.server_close()

    def test_redaction_rejects_secret_like_channel_and_permission_payloads(self):
        sidecar = ChannelSidecar(bearer_token="local-token")
        serialized_session = json.dumps(
            sidecar.register_session(
                {
                    "session_id": "s1",
                    "adapter": "claude_channel",
                    "cwd": "/repo",
                    "auth_posture": {"provider": "subscription"},
                    "trust_state": {"workspace": "trusted"},
                }
            ),
            sort_keys=True,
        )
        self.assertNotIn("local-token", serialized_session)

        with self.assertRaisesRegex(ValueError, "non-metadata"):
            sidecar.create_message("s1", sender="phase-loop", content="x", attachments=[{"payload": "raw provider payload"}])
        with self.assertRaisesRegex(ValueError, "raw or secret-like"):
            sidecar.create_permission_request(
                "s1",
                {
                    "tool_name": "Bash",
                    "description": "bad",
                    "input_preview": "redacted",
                    "risk_class": "high",
                    "raw_input": "terminal transcript",
                },
            )
        # B1 regression: a secret-like VALUE in a whitelisted field (not just a
        # forbidden field name) must be rejected on the permission-relay path,
        # matching every other channel boundary's value-level scan.
        for secret_value in (
            'curl -H "Authorization: Bearer <SECRET-REDACTED>" https://api',
            "token github_pat_11ABCDEF",
        ):
            with self.assertRaisesRegex(ValueError, "secret-like"):
                sidecar.create_permission_request(
                    "s1",
                    {
                        "tool_name": "Bash",
                        "description": "run a command",
                        "input_preview": secret_value,
                        "risk_class": "low",
                    },
                )
        with self.assertRaisesRegex(ValueError, "secret-like"):
            sidecar.register_session(
                {
                    "session_id": "bad",
                    "adapter": "claude_channel",
                    "cwd": "/repo",
                    "trust_state": {"oauth": "keychain payload"},
                }
            )

    def test_route_result_rejects_raw_payload_values_and_secret_shaped_fields(self):
        forbidden_cases = (
            {"text": "raw prompt: inspect this repo"},
            {"artifacts": ({"path": "logs/raw-terminal-transcript.txt"},)},
            {"artifacts": ({"summary": "raw provider payload"},)},
            {"artifacts": ({"token": "redacted"},)},
            {"trust_state": {"oauth": "keychain payload"}},
            {"permission_state": {"input": "raw tool input"}},
            {"warnings": ("Authorization: Bearer local-token",)},
            {"evidence_refs": ({"summary": "local env value"},)},
        )
        for overrides in forbidden_cases:
            with self.subTest(overrides=overrides):
                payload = {
                    "route": "claude_channel",
                    "session_id": "session-a",
                    "event_id": "event-a",
                    "status": "blocked",
                    "auth_posture": "subscription_local",
                    "billing_posture": "subscription_included",
                }
                payload.update(overrides)
                with self.assertRaisesRegex(ValueError, "secret-like|raw metadata"):
                    ClaudeRouteResult(**payload)

    def _post_json(self, url: str, payload: dict[str, object], *, bearer_token: str | None = None) -> dict[str, object]:
        headers = {"Content-Type": "application/json"}
        if bearer_token is not None:
            headers["Authorization"] = f"Bearer {bearer_token}"
        req = request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        return json.loads(request.urlopen(req, timeout=5).read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
