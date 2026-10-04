"""Scripted stand-ins for ``_baml_worker.py`` (agent-harness#1135 framing tests).

The client launches this script in place of the real worker through the
``baml_modular._spawn_popen`` seam: ``argv[1]`` is the scripted mode and the
worker's own argv follows.  Every mode answers ``init`` correctly (echoing the
fingerprint of the files it was sent) and then misbehaves on the first op.
Imports only the standard library.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time


def _fingerprint(files: dict) -> str:
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _write(data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(1, view):]


def _frame(obj: dict) -> bytes:
    return (json.dumps(obj, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def _lines():
    buf = b""
    while True:
        chunk = os.read(0, 1 << 16)
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield json.loads(line)


OK_CLOSEOUT = json.dumps(
    {
        "terminal_status": "complete",
        "verification_status": "passed",
        "dirty_paths": [],
        "produced_if_gates": ["G"],
        "next_action": None,
        "blocker_class": None,
        "blocker_summary": None,
        "human_required": None,
        "required_human_inputs": [],
        "visual_evidence_path": None,
        "visual_evidence_non_black_pixels": None,
        "visual_evidence_pixel_min": None,
        "visual_evidence_pixel_max": None,
        "visual_evidence_opt_out": None,
        "visual_render_declared": None,
    }
)


def main(mode: str) -> None:
    fp = None
    for req in _lines():
        if req.get("op") == "init":
            if mode == "hang_init":
                while True:  # never answer init
                    time.sleep(3600)
            fp = _fingerprint(req["files"])
            _write(_frame({"id": req["id"], "fingerprint": fp, "ok": {"version": "peer", "pid": os.getpid()}}))
            if mode == "stall_after_init":
                while True:  # never read stdin again
                    time.sleep(3600)
            continue
        rid = req.get("id")
        if mode == "echo":
            _write(_frame({"id": rid, "fingerprint": fp, "ok": OK_CLOSEOUT}))
        elif mode == "slow_echo":
            time.sleep(float(os.environ.get("PEER_SLEEP", "0") or 0) or 2.0)
            _write(_frame({"id": rid, "fingerprint": fp, "ok": OK_CLOSEOUT}))
        elif mode == "unterminated_eof":
            _write(b'{"id":' + str(rid).encode() + b',"fingerprint"')
            os._exit(0)
        elif mode == "non_json":
            _write(b"this is not json\n")
        elif mode == "json_array":
            _write(b"[1,2,3]\n")
        elif mode == "wrong_id":
            _write(_frame({"id": rid + 1000, "fingerprint": fp, "ok": OK_CLOSEOUT}))
        elif mode == "wrong_fingerprint":
            _write(_frame({"id": rid, "fingerprint": "0" * 64, "ok": OK_CLOSEOUT}))
        elif mode == "extra_key":
            _write(_frame({"id": rid, "fingerprint": fp, "ok": OK_CLOSEOUT, "extra": 1}))
        elif mode == "non_json_ok":
            _write(_frame({"id": rid, "fingerprint": fp, "ok": "this is not json"}))
        elif mode == "over_cap":
            _write(_frame({"id": rid, "fingerprint": fp, "ok": "x" * (18 * 1024 * 1024)}))
        elif mode == "hang":
            while True:
                time.sleep(3600)
        else:
            raise SystemExit(f"unknown peer mode {mode!r}")


if __name__ == "__main__":
    main(sys.argv[1])
