import json
import threading
import unittest
from urllib import request
from urllib.error import HTTPError

from phase_loop_runtime.claude_channel_sidecar import (
    ACK_POLICY_TOOL_REQUIRED,
    ChannelSidecar,
    build_server,
)


class ClaudeChannelSidecarTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
