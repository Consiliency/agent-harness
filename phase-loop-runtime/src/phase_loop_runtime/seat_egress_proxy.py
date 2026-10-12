"""The egress layer of a jailed Gemini seat (agent-harness#1170; plan agent-harness#1244,
rulings S3 and S4).

The seat's network namespace has no uplink. Its only way out is one loopback port, bridged
to a proxy that runs on the host, outside the seat: the TLS-terminating proxy of srt
(`@anthropic-ai/sandbox-runtime`, pinned below). The proxy answers only the requests on the
pinned allowlist (`seat_egress/gemini-allowlist.json`, measured from agy's real traffic),
checks the Host the client names inside each tunnel, and holds no credential. HTTPS_PROXY in
the seat is routing, not the boundary: a client that ignores it has no route at all.

The interception CA is this host's own (``ca_paths``): its directory is 0700 and its key
0600, owned by the operator. Only the certificate enters the seat, as the seat's whole trust
bundle; the key is read by the proxy alone and is never mounted, and the CA is never added to
the host's trust store.

Nothing here is fetched at run time. ``install`` runs ``npm ci`` against the shipped lockfile
(npm checks every package's integrity), and every launch re-checks the installed version,
the recorded integrities and the digest of the installed files.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Iterator, Mapping

__all__ = [
    "EgressLayerUnavailable",
    "SeatEgressProxy",
    "SRT_VERSION",
    "allowlist",
    "egress_evidence",
    "install",
    "start_proxy",
    "unavailable_reason",
]

SRT_PACKAGE = "@anthropic-ai/sandbox-runtime"
SRT_VERSION = "0.0.79"
SRT_INTEGRITY = ("sha512-WjBmS9fbTpnQwQkM9SU+JjhM2CcXo9eWEELktY1100RMvTy/jPhP44yZ3NXhh+GHB350"
                 "OgPbM3+FubE5WVRtSA==")
#: sha256 over every installed file (``tree_sha256``) of a clean ``npm ci`` of the shipped
#: lockfile: what was verified at install is what runs.
SRT_TREE_SHA256 = "a5039f84e95ab8f7994ef2a4e64b9293306811ba1eb7b67a055b7c8d7ea2aeaf"
NODE_MIN_VERSION = (22, 12, 0)
#: The seat's loopback port; the bridge listens here inside the seat's namespace.
SEAT_PROXY_PORT = 3128
UNAVAILABLE_CODE = "gemini_seat_egress_unavailable"
INSTALL_FIX = "phase-loop seat-egress install"
_DATA = "seat_egress"
_READY_TIMEOUT_S = 60.0
_CA_CAP_BYTES = 64 * 1024


class EgressLayerUnavailable(RuntimeError):
    """The seat's egress layer cannot run on this host; ``str()`` is the one reason."""


def _data_path(name: str) -> Path:
    return Path(str(resources.files("phase_loop_runtime").joinpath(_DATA, name)))


def allowlist() -> dict[str, object]:
    """The pinned request allowlist of the Gemini seat."""
    return json.loads(_data_path("gemini-allowlist.json").read_text(encoding="utf-8"))


def _data_home() -> Path:
    configured = os.environ.get("XDG_DATA_HOME")
    return Path(configured) if configured and os.path.isabs(configured) else (
        Path.home() / ".local" / "share")


def install_root() -> Path:
    return _data_home() / "phase-loop" / "seat-egress" / f"srt-{SRT_VERSION}"


def ca_dir() -> Path:
    from .seat_jail import state_home

    return state_home() / "phase-loop" / "seat-egress-ca"


def ca_paths() -> tuple[Path, Path]:
    """``(certificate, key)`` of this host's seat egress CA."""
    return ca_dir() / "ca.crt", ca_dir() / "ca.key"


def tree_sha256(root: Path) -> str:
    """sha256 over ``(path, sha256(bytes))`` of every regular file under ``root``, in path
    order, leaving out npm's own record (``.package-lock.json``) and the ``.bin`` links."""
    digest = hashlib.sha256()
    entries = []
    for directory, _dirs, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative == ".package-lock.json" or relative.startswith(".bin/") or path.is_symlink():
                continue
            entries.append((relative, path))
    for relative, path in sorted(entries):
        digest.update(relative.encode("utf-8") + b"\0"
                      + hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest()


def _node() -> str:
    from .review_stage import trusted_host_executable

    try:
        node = trusted_host_executable("node")
    except ValueError as exc:
        raise EgressLayerUnavailable("node is not installed") from exc
    try:
        found = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30,
                               env=_proxy_env(node, None), check=False).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise EgressLayerUnavailable("node does not run") from exc
    match = re.match(r"v(\d+)\.(\d+)\.(\d+)", found.strip())
    if match is None or tuple(int(part) for part in match.groups()) < NODE_MIN_VERSION:
        raise EgressLayerUnavailable(
            "node {}.{}.{} or newer is required".format(*NODE_MIN_VERSION))
    return node


def _proxy_env(node: str, home: Path | None) -> dict[str, str]:
    """The proxy's whole environment: nothing from the operator's, so no credential, proxy
    or trust setting reaches it."""
    env = {"PATH": f"{Path(node).parent}:/usr/bin:/bin", "LANG": "C.UTF-8"}
    if home is not None:
        env["HOME"] = str(home)
    return env


def verify_install(root: Path | None = None) -> Path:
    """The installed srt entry point, after checking it is the pinned package, byte for
    byte. Raises :class:`EgressLayerUnavailable`."""
    root = root or install_root()
    modules = root / "node_modules"
    try:
        installed = json.loads((modules / SRT_PACKAGE / "package.json").read_text(encoding="utf-8"))
        recorded = json.loads((modules / ".package-lock.json").read_text(encoding="utf-8"))
        shipped = json.loads(_data_path("package-lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EgressLayerUnavailable("srt is not installed") from exc
    if installed.get("version") != SRT_VERSION:
        raise EgressLayerUnavailable("the installed srt is not the pinned version")
    packages = recorded.get("packages") if isinstance(recorded, dict) else None
    if not isinstance(packages, dict):
        raise EgressLayerUnavailable("the installed srt has no package record")
    for name, entry in shipped["packages"].items():
        if not name:
            continue
        if (packages.get(name, {}).get("integrity") != entry["integrity"]
                or packages.get(name, {}).get("version") != entry["version"]):
            raise EgressLayerUnavailable("the installed packages are not the pinned ones")
    if packages.get(f"node_modules/{SRT_PACKAGE}", {}).get("integrity") != SRT_INTEGRITY:
        raise EgressLayerUnavailable("the installed srt is not the pinned package")
    try:
        if tree_sha256(modules) != SRT_TREE_SHA256:
            raise EgressLayerUnavailable("the installed srt files changed after install")
    except OSError as exc:
        raise EgressLayerUnavailable("the installed srt cannot be read") from exc
    return modules / SRT_PACKAGE / "dist" / "index.js"


def install(root: Path | None = None) -> Path:
    """Install the pinned srt with ``npm ci`` (integrity-checked against the shipped
    lockfile; no install scripts run), then verify it."""
    from .review_stage import trusted_host_executable

    root = root or install_root()
    node = _node()
    try:
        npm = trusted_host_executable("npm")
    except ValueError as exc:
        raise EgressLayerUnavailable("npm is not installed") from exc
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("package.json", "package-lock.json"):
        shutil.copyfile(_data_path(name), root / name)
    with tempfile.TemporaryDirectory(prefix="pl-seat-egress-npm-") as home:
        done = subprocess.run(
            [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--omit=dev"],
            cwd=root, env=_proxy_env(node, Path(home)), capture_output=True, text=True,
            timeout=600, check=False)
    if done.returncode != 0:
        raise EgressLayerUnavailable(f"npm ci failed: {done.stderr.strip()[-200:]}")
    return verify_install(root)


def _private_dir_problem(path: Path) -> str | None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        return "not owned"
    if stat.S_IMODE(info.st_mode) & 0o077:
        return "not 0700"
    return None


def _private_file_problem(path: Path, *, key: bool) -> str | None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        return "not owned"
    if stat.S_IMODE(info.st_mode) & (0o077 if key else 0o022):
        return "not 0600" if key else "writable by others"
    if info.st_size > _CA_CAP_BYTES:
        return "too large"
    return None


def ensure_ca(srt_index: Path, node: str) -> tuple[Path, Path]:
    """This host's CA, generated on first use with srt's own generator. Its directory must
    be the operator's alone (0700), its key 0600; anything else refuses."""
    directory = ca_dir()
    cert, key = ca_paths()
    problem = _private_dir_problem(directory)
    if problem == "missing":
        directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.mkdir(mode=0o700)
        problem = None
    if problem is not None:
        raise EgressLayerUnavailable(f"the seat egress CA directory is {problem}: {directory}")
    if not os.path.lexists(cert) and not os.path.lexists(key):
        done = subprocess.run([node, str(_data_path("ca.mjs")), str(srt_index), str(directory)],
                              env=_proxy_env(node, directory), capture_output=True, text=True,
                              timeout=120, check=False)
        if done.returncode != 0:
            raise EgressLayerUnavailable("the seat egress CA could not be generated")
    for path, is_key in ((cert, False), (key, True)):
        problem = _private_file_problem(path, key=is_key)
        if problem is not None:
            raise EgressLayerUnavailable(f"the seat egress CA {path.name} is {problem}")
    return cert, key


def unavailable_reason() -> str | None:
    """``None`` when this host can run the seat's egress layer, else the one reason. Read
    only, except that it creates this host's CA on first use."""
    try:
        node = _node()
        ensure_ca(verify_install(), node)
    except EgressLayerUnavailable as exc:
        return str(exc)
    return None


@dataclass
class SeatEgressProxy:
    """One running proxy. ``proxy_url`` carries the proxy's per-launch session token (it
    admits a client to this proxy and grants nothing else); it is placeholdered wherever an
    argv is recorded."""

    socket: str
    proxy_url: str = field(repr=False)
    ca_cert: Path
    ca_sha256: str
    inner_sni_check: bool
    process: "subprocess.Popen[str]" = field(repr=False)


def ca_fingerprint(cert: Path) -> str:
    """sha256 of the CA certificate's DER bytes, the form trust stores are keyed by."""
    import ssl

    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text(encoding="ascii"))).hexdigest()


@contextlib.contextmanager
def start_proxy(*, inner_sni_check: bool = True) -> Iterator[SeatEgressProxy]:
    """Run the seat's proxy for the life of the context. Raises
    :class:`EgressLayerUnavailable` before anything runs when the layer is unavailable."""
    node = _node()
    srt_index = verify_install()
    cert, key = ensure_ca(srt_index, node)
    with tempfile.TemporaryDirectory(prefix="pl-seat-egress-") as work:
        config = Path(work) / "proxy.json"
        config.write_text(json.dumps({
            "allow": allowlist()["allow"], "ca_cert": str(cert), "ca_key": str(key),
            "inner_sni_check": inner_sni_check,
        }), encoding="utf-8")
        process = subprocess.Popen(
            [node, str(_data_path("proxy.mjs")), str(srt_index), str(config)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=_proxy_env(node, Path(work)), cwd=work, text=True, start_new_session=True)
        try:
            ready = _read_ready(process)
            if not ready.get("tls_inspection") or bool(ready.get("inner_sni_check")) != inner_sni_check:
                raise EgressLayerUnavailable("the proxy did not start with TLS inspection")
            token = str(ready["token"])
            yield SeatEgressProxy(
                socket=str(ready["socket"]),
                proxy_url=f"http://srt:{token}@127.0.0.1:{SEAT_PROXY_PORT}",
                ca_cert=cert, ca_sha256=ca_fingerprint(cert),
                inner_sni_check=inner_sni_check, process=process)
        finally:
            with contextlib.suppress(OSError):
                if process.stdin is not None:
                    process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()


def _read_ready(process: "subprocess.Popen[str]") -> Mapping[str, object]:
    import select

    assert process.stdout is not None
    readable, _, _ = select.select([process.stdout], [], [], _READY_TIMEOUT_S)
    line = process.stdout.readline() if readable else ""
    try:
        ready = json.loads(line)
    except ValueError:
        ready = None
    if not isinstance(ready, dict) or not ready.get("socket") or not ready.get("token"):
        raise EgressLayerUnavailable("the seat egress proxy did not start")
    return ready


def egress_evidence(proxy: SeatEgressProxy) -> dict[str, object]:
    """What the seat's egress layer enforced, for the leg's evidence."""
    rules = allowlist()["allow"]
    return {
        "mechanism": "namespace without uplink; one loopback port bridged to srt's "
                     "TLS-terminating proxy on the host",
        "tls_inspection": True,
        "inner_host_check": True,
        "inner_sni_check": proxy.inner_sni_check,
        "proxy": {"package": SRT_PACKAGE, "version": SRT_VERSION, "integrity": SRT_INTEGRITY,
                  "tree_sha256": SRT_TREE_SHA256},
        "ca_sha256": proxy.ca_sha256,
        "allow": [f"{r['method']} https://{r['host']}{r.get('path', r.get('path_prefix', '') + '*')}"
                  for r in rules],
        "direct_egress": "no route",
    }


def cli_main(args) -> int:
    """``phase-loop seat-egress {status,install}`` (agent-harness#1170)."""
    if args.action == "install":
        try:
            install()
        except EgressLayerUnavailable as exc:
            print(json.dumps({"installed": False, "reason": str(exc)}, sort_keys=True))
            return 1
    reason = unavailable_reason()
    print(json.dumps({"available": reason is None, "reason": reason, "srt_version": SRT_VERSION,
                      "install_root": str(install_root()), "ca_dir": str(ca_dir())},
                     sort_keys=True))
    return 0 if reason is None else 1
