"""A fake Claude TUI's session journal on the owned route (agent-harness#1222).

An owned seat's answer counts only with its complete session journal, which the host
collects from ``$CLAUDE_CONFIG_DIR/projects/<cwd slug>/<session id>.jsonl``. A ``sh -c``
fake provider is started as ``sh -c SCRIPT --session-id <id>``, so ``$1`` is the id.
"""

from __future__ import annotations

import json

_PATH = ('"$CLAUDE_CONFIG_DIR/projects/$(printf %s "$PWD" | sed \'s/[^A-Za-z0-9.-]/-/g\')/$1.jsonl"')


def journal_sh(answer: str = "AGREE") -> str:
    """Shell that writes one complete turn whose final assistant text is ``answer``."""
    records = [
        {"type": "user", "uuid": "user-1", "message": {"role": "user", "content": "review"}},
        {"type": "assistant", "uuid": "assistant-1", "message": {
            "id": "message-1", "role": "assistant", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": answer}]}},
    ]
    body = "".join(json.dumps(record) + "\n" for record in records)
    return "printf '%s' " + _shell_quote(body) + " > " + _PATH + "; "


def append_sh(record: dict) -> str:
    """Shell that appends one record to the session journal."""
    return "printf '%s\\n' " + _shell_quote(json.dumps(record)) + " >> " + _PATH + "; "


def _shell_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"
