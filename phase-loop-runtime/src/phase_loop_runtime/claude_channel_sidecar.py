from __future__ import annotations

import argparse
import json
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


ACK_POLICY_TOOL_REQUIRED = "tool_ack_required"
REPLY_STATUSES = {"received", "working", "blocked", "done", "error"}
FORBIDDEN_ATTACHMENT_FIELDS = {"content", "data", "text", "payload", "secret", "token", "api_key", "private_key"}


@dataclass(frozen=True)
class ChannelEventEnvelope:
    event_id: str
    session_id: str
    sender: str
    content: str
    attachments: tuple[dict[str, Any], ...]
    created_at: str
    ack_policy: str = ACK_POLICY_TOOL_REQUIRED

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["attachments"] = list(self.attachments)
        return data


@dataclass(frozen=True)
class ChannelReplyPayload:
    event_id: str
    status: str
    text: str = ""
    artifacts: tuple[dict[str, Any], ...] = ()
    error: str | None = None
    final: bool = False

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["artifacts"] = list(self.artifacts)
        return data


@dataclass
class ChannelEventState:
    envelope: ChannelEventEnvelope
    replies: list[ChannelReplyPayload] = field(default_factory=list)
    acknowledged: bool = False
    acknowledged_at: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            **self.envelope.to_json(),
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at,
            "replies": [reply.to_json() for reply in self.replies],
        }


class ChannelSidecar:
    def __init__(self) -> None:
        self._events_by_session: dict[str, list[str]] = {}
        self._events_by_id: dict[str, ChannelEventState] = {}
        self._lock = threading.RLock()

    def create_message(
        self,
        session_id: str,
        *,
        sender: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> ChannelEventEnvelope:
        if not session_id:
            raise ValueError("session_id is required")
        if not isinstance(sender, str) or not sender:
            raise ValueError("sender is required")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        clean_attachments = tuple(_metadata_only_attachments(attachments or []))
        envelope = ChannelEventEnvelope(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            sender=sender,
            content=content,
            attachments=clean_attachments,
            created_at=_utc_now(),
        )
        with self._lock:
            self._events_by_id[envelope.event_id] = ChannelEventState(envelope=envelope)
            self._events_by_session.setdefault(session_id, []).append(envelope.event_id)
        return envelope

    def list_events(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            event_ids = list(self._events_by_session.get(session_id, []))
            return [self._events_by_id[event_id].to_json() for event_id in event_ids]

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._events_by_id.get(event_id)
            return state.to_json() if state else None

    def record_reply(self, payload: ChannelReplyPayload | dict[str, Any]) -> dict[str, Any]:
        reply = payload if isinstance(payload, ChannelReplyPayload) else _reply_payload(payload)
        with self._lock:
            state = self._events_by_id.get(reply.event_id)
            if state is None:
                raise KeyError(f"unknown event_id: {reply.event_id}")
            state.replies.append(reply)
            if reply.final:
                state.acknowledged = True
                state.acknowledged_at = _utc_now()
            return state.to_json()

    def record_status(self, payload: ChannelReplyPayload | dict[str, Any]) -> dict[str, Any]:
        return self.record_reply(payload)


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def make_handler(sidecar: ChannelSidecar) -> type[BaseHTTPRequestHandler]:
    class ChannelSidecarHandler(BaseHTTPRequestHandler):
        server_version = "PhaseLoopChannelSidecar/0.1"

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._handle_post()
            except ValueError as exc:
                self._write_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except KeyError as exc:
                self._write_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)

        def do_GET(self) -> None:  # noqa: N802
            if self._path_parts()[:1] != ["sessions"]:
                self._write_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            parts = self._path_parts()
            if len(parts) != 3 or parts[2] != "events":
                self._write_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            events = sidecar.list_events(parts[1])
            if "text/event-stream" in self.headers.get("Accept", ""):
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for event in events:
                    self.wfile.write(f"data: {json.dumps(event, sort_keys=True)}\n\n".encode("utf-8"))
                return
            self._write_json({"events": events})

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _handle_post(self) -> None:
            parts = self._path_parts()
            if len(parts) != 3 or parts[0] != "sessions":
                self._write_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            payload = self._read_json()
            session_id = parts[1]
            if parts[2] == "message":
                envelope = sidecar.create_message(
                    session_id,
                    sender=payload.get("sender", ""),
                    content=payload.get("content", ""),
                    attachments=payload.get("attachments", []),
                )
                self._write_json(envelope.to_json(), HTTPStatus.CREATED)
                return
            if parts[2] in {"reply", "status"}:
                payload.setdefault("event_id", payload.get("eventId"))
                state = sidecar.record_reply(payload) if parts[2] == "reply" else sidecar.record_status(payload)
                self._write_json(state)
                return
            self._write_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def _path_parts(self) -> list[str]:
            return [part for part in urlparse(self.path).path.split("/") if part]

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("payload must be a JSON object")
            return data

        def _write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ChannelSidecarHandler


def build_server(host: str = "127.0.0.1", port: int = 0, sidecar: ChannelSidecar | None = None) -> ThreadingHTTPServer:
    if not is_loopback_host(host):
        raise ValueError("claude channel sidecar binds to loopback hosts only")
    return ThreadingHTTPServer((host, port), make_handler(sidecar or ChannelSidecar()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local phase-loop Claude Channel sidecar.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = build_server(args.host, args.port)
    sys.stderr.write(f"phase-loop channel sidecar listening on http://{args.host}:{args.port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def _metadata_only_attachments(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(attachments, list):
        raise ValueError("attachments must be a list")
    clean: list[dict[str, Any]] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            raise ValueError("attachments must contain metadata objects")
        forbidden = FORBIDDEN_ATTACHMENT_FIELDS.intersection({str(key).lower() for key in attachment})
        if forbidden:
            raise ValueError(f"attachment contains non-metadata fields: {', '.join(sorted(forbidden))}")
        clean.append(dict(attachment))
    return clean


def _reply_payload(payload: dict[str, Any]) -> ChannelReplyPayload:
    event_id = payload.get("event_id")
    status = payload.get("status")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id is required")
    if status not in REPLY_STATUSES:
        raise ValueError("status must be one of: " + ", ".join(sorted(REPLY_STATUSES)))
    artifacts = payload.get("artifacts") or []
    if not isinstance(artifacts, list):
        raise ValueError("artifacts must be a list")
    return ChannelReplyPayload(
        event_id=event_id,
        status=status,
        text=str(payload.get("text") or ""),
        artifacts=tuple(_metadata_only_attachments(artifacts)),
        error=payload.get("error"),
        final=bool(payload.get("final", False)),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
