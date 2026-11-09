"""``agent-harness-placement --client agent-harness|agent-toolkit reserve|release|reap|version``.

The placement process boundary (v13 PLACECLI, IF-0-PLACECLI-1). One JSON request on stdin
(``version``: empty stdin), one compact JSON response line on stdout, and the exit class of
``x-cli.exit_codes``:

* ``0``  settled: version, an admitted reservation, a release, a complete reap;
* ``10`` nothing created or nothing held;
* ``20`` an effect may remain (a ``(client, reservation)`` barrier is armed);
* ``70`` internal or protocol failure: stdout is absent and stderr carries one closed code.

``--client`` is required and alone selects the operator configuration, certificate OU and
inventory; no environment variable selects or overrides any of them. stderr is empty for
every schema-valid outcome and never carries an input value, a credential, a policy
document or an exception chain.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import warnings
from typing import Sequence

from . import placement_process_contract as contract

__all__ = ["build_lifecycle", "legacy_reap", "main", "version_response"]

PROGRAM = "agent-harness-placement"
_STDIN_LIMIT = contract.MAX_INPUT_BYTES + 1
_HELP = """usage: agent-harness-placement --client agent-harness|agent-toolkit reserve|release|reap|version

reserve, release and reap read one placement request (JSON) on stdin; version reads empty stdin.
One JSON response line is written to stdout. Exit: 0 settled, 10 nothing created or held,
20 an effect may remain, 70 internal or protocol failure (stdout absent).
--client alone selects the operator configuration, certificate and inventory.
"""


def build_lifecycle(client: str):
    """The production lifecycle for ``client``: landed caps loader and readiness, host
    observation, the backend registry (no production OpenShell backend is registered)."""
    from .sandbox_placement import PlacementLifecycle

    return PlacementLifecycle(client)


def version_response(client_config) -> contract.VersionResponse:
    """``VersionResponse`` for one client's effective configuration: the packaged protocol
    schema digest, ``config_sha256`` and the effective local-headroom thresholds."""
    return contract.VersionResponse(
        client_config.client, contract.protocol_schema_sha256(), client_config.config_sha256,
        contract.LocalHeadroomConfig.from_json(client_config.local_headroom),
    )


def _diagnostic(code: str) -> int:
    """One bounded, closed diagnostic line; the exit class of an internal failure."""
    try:
        os.write(2, f"{PROGRAM}: {code}\n".encode("ascii", "replace")[:256])
    except OSError:
        pass
    return 70


def _write_stdout(data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(1, view):]


def _read_stdin() -> bytes:
    chunks: list[bytes] = []
    size = 0
    stream = sys.stdin.buffer if sys.stdin is not None else None
    if stream is None:
        return b""
    while size < _STDIN_LIMIT:
        chunk = stream.read(_STDIN_LIMIT - size)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def _parse(argv: Sequence[str]) -> tuple[str | None, str | None, bool] | None:
    """``(client, verb, help)``; ``None`` for anything else. Values are never echoed."""
    client = verb = None
    wants_help = False
    items = list(argv)
    index = 0
    while index < len(items):
        item = items[index]
        if item in ("-h", "--help"):
            wants_help = True
        elif item == "--client":
            if client is not None or index + 1 >= len(items):
                return None
            index += 1
            client = items[index]
        elif item.startswith("--client="):
            if client is not None:
                return None
            client = item.split("=", 1)[1]
        elif item in contract.VERBS and verb is None:
            verb = item
        else:
            return None
        index += 1
    if client is not None and client not in contract.CLIENTS:
        return None
    return client, verb, wants_help


def _caps_line(client: str | None) -> str:
    try:
        readable, _digest = build_lifecycle(client or "agent-harness").caps_state()
    except Exception:
        readable = False
    if readable:
        return "seat resource caps: available"
    return "seat resource caps: unavailable (seat_resource_caps_unavailable)"


def _run(client: str, verb: str, raw: bytes, cancelled: threading.Event) -> tuple[bytes, int]:
    lifecycle = build_lifecycle(client)
    if verb == "version":
        contract.require_empty_version_input(raw)
        response = version_response(lifecycle.config())
    else:
        request = contract.decode_request(verb, raw)
        response = getattr(lifecycle, verb)(request, cancelled=cancelled)
    return contract.encode_response(response), contract.exit_class(response)


def main(argv: Sequence[str] | None = None) -> int:
    """``placement_cli.main(argv: Sequence[str] | None = None) -> int``."""
    from .sandbox_placement import LifecycleError
    from .sandbox_policy import PlacementConfigError

    arguments = list(sys.argv[1:] if argv is None else argv)
    parsed = _parse(arguments)
    if parsed is None:
        return _diagnostic("invocation_invalid")
    client, verb, wants_help = parsed
    if wants_help:
        _write_stdout((_HELP + _caps_line(client) + "\n").encode("utf-8"))
        return 0
    if client is None or verb is None:
        return _diagnostic("invocation_invalid")
    cancelled = threading.Event()
    previous = {}
    for number in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[number] = signal.signal(number, lambda _n, _f: cancelled.set())
        except ValueError:  # not the main thread (an in-process caller)
            pass
    root = logging.getLogger()
    quiet = logging.NullHandler()
    root.addHandler(quiet)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = _read_stdin()
            data, code = _run(client, verb, raw, cancelled)
    except contract.ProtocolError as exc:
        return _diagnostic(f"protocol_failure {exc.code}")
    except (LifecycleError, PlacementConfigError) as exc:
        return _diagnostic(str(exc))
    except Exception:
        return _diagnostic("placement_internal")
    finally:
        root.removeHandler(quiet)
        for number, handler in previous.items():
            signal.signal(number, handler)
    try:
        _write_stdout(data)
    except OSError:
        return 70
    return code


def legacy_reap(client: str, *, out=None) -> int:
    """``phase-loop placement reap --client CLIENT``: the same caller-scoped service, in
    process, for the selected client's inventory only."""
    import secrets

    out = out if out is not None else sys.stdout
    request = contract.ReapRequest(f"legacy-reap-{secrets.token_hex(8)}", 30000, 1000)
    response = build_lifecycle(client).reap(request, cancelled=threading.Event())
    result = response.inventory
    print(f"placement reap: {result.destroyed} destroyed, {result.pending} pending "
          f"({result.examined} examined, client {result.client})", file=out)
    return 0 if response.state == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
