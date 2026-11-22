"""The Grok jail profile (GROK SL-2), registered with its tool-surface gate closed.

Registering it moves Grok off the ``unconfined`` exception (``seat_window.readiness_rows``):
the vendor row reads ``jailed`` with no exception and no expiry. Every Grok launch still
stops at L6 with ``grok_tool_surface_unverified``, whatever receipts exist, until SL-3's
``grok_jail_surface`` is installed (jail contract §4.1).

The mounts are main's Gemini-style projection (jail contract §2.3, option A): the staged
``<review_dir>/grok-config/`` directory bound read-only at ``/seat/home/.grok`` through
``OwnerPaths.provider_config``, the two writable entries as tmpfs, the two lock files bound
from seat-home, the CA by read-only path bind, then the home and tree masks of §2.4. The
builder, ``_owner_argv`` and ``seat_uid`` are not edited; this module is data and callbacks.
"""

from __future__ import annotations

import os
import posixpath
import stat
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .seat_route_contract import (
    ArgvInputs, ConfigSurface, ContainmentEvidence, CredentialDelivery, EnvInputs,
    JailProfile, OwnerPaths, Precondition, WindowRows,
)

LEG = "grok"
TOOL_SURFACE_UNVERIFIED = "grok_tool_surface_unverified"

SEAT_TREE = "/seat/tree"
SEAT_HOME = "/seat/home"
SEAT_GROK_DOTDIR = SEAT_HOME + "/.grok"
SEAT_EGRESS_CA = "/seat/egress-ca.pem"

#: Host layout beside ``seat-home`` in the review directory (jail contract §2.3).
HOST_GROK_CONFIG_DIRNAME = "grok-config"
HOST_GROK_MASKS_DIRNAME = "grok-masks"
MASK_FILE = "empty"
MASK_DIRECTORY = "empty.d"
#: Inside seat-home, so ``seat_uid.handoff`` hands it to the seat with the rest of the home.
HOST_GROK_WRITABLE_DIRNAME = ".grok-rw"
#: The staged directory's writable entries: tmpfs over the two empty directories, and the
#: two lock files the client writes bound from ``<home>/.grok-rw/``.
WRITABLE_TMPFS = ("logs", "sessions")
WRITABLE_LOCKS = (".config-init.lock", "managed_config.lock")
#: The protected ancestor of ``.config/grove`` (a tmpfs mount point, §2.4).
HOME_CONFIG_DIRNAME = ".config"
#: The per-image project discovery inventory: main's ``grok_tool_surface.DISCOVERY_PATHS``,
#: transcribed so the jail profile's import closure stays this module (a test pins the two
#: equal).
DISCOVERY_PATHS = (".agents", ".claude", ".cursor", ".grok", ".mcp.json")

# --- The protection table (jail contract §2.4) -------------------------------------------

PROJECTED = "projected"
ABSENT_IN_READ_ONLY_DOTDIR = "absent_in_read_only_dotdir"
ABSENT_OUTSIDE_WRITABLE_MOUNTS = "absent_outside_writable_mounts"
MASKED_FILE = "masked_file"
MASKED_DIRECTORY = "masked_directory"
TREATMENTS = frozenset({PROJECTED, ABSENT_IN_READ_ONLY_DOTDIR, ABSENT_OUTSIDE_WRITABLE_MOUNTS,
                        MASKED_FILE, MASKED_DIRECTORY})
#: Where a row's path is resolved: the seat home, the host and jail root, or the tree copy.
HOME, ABSOLUTE, TREE = "home", "absolute", "tree"

#: grok 1.0.92, the image erratum 8 measured (its tolerated-refusal row in
#: ``grok_tool_surface.TOLERATED_REFUSALS_BY_IMAGE`` has the same key).
GROK_1_0_92_SHA256 = "add4d201dbf2c0bd6077a36feb55a76939de30bae48dbb06f16b2307d38ceacb"

_ABSENT_DOTDIR_INPUTS = (
    "managed_config.toml", "requirements.toml", "managed_config_cache.json",
    "managed_config.sig.json", "managed_identity.sig.json", "staged/managed_config_refresh.json",
    "models_cache.json", "experiments_state.json", "campaigns_state.json", "skills", "agents",
    "bundled/agents", "bundled/skills", "commands", "plugins", "installed-plugins", "hooks",
    "hooks-paths", "disabled-hooks", "workflows", "lsp.json", "sandbox.toml", "trusted-plugins",
    "trusted-hook-projects", "trusted_folders.toml", "mcp_preferences.json",
    "mcp_credentials.json", "settings.json",
)
#: ``(scope, path, treatment)`` rows, in the table's order. Home and tree mask rows are
#: mounted in this order (§2.3 items 5 and 6).
_PROTECTION_1_0_92 = (
    (HOME, ".grok/config.toml", PROJECTED),
    (HOME, ".grok/auth.json", PROJECTED),
    (HOME, ".grok/agent_id", PROJECTED),
    (HOME, ".grok/rules", ABSENT_IN_READ_ONLY_DOTDIR),
    *((HOME, f".grok/{name}", ABSENT_IN_READ_ONLY_DOTDIR) for name in _ABSENT_DOTDIR_INPUTS),
    *((ABSOLUTE, path, ABSENT_OUTSIDE_WRITABLE_MOUNTS) for path in (
        "/etc/grok/managed_config.toml", "/etc/grok/requirements.toml",
        "/etc/claude-code/managed-settings.json")),
    (HOME, ".claude.json", MASKED_FILE),
    (HOME, ".mcp.json", MASKED_FILE),
    (HOME, ".claude", MASKED_DIRECTORY),
    (HOME, ".cursor", MASKED_DIRECTORY),
    (HOME, ".agents", MASKED_DIRECTORY),
    (HOME, ".config/grove", MASKED_DIRECTORY),
    (TREE, ".agents", MASKED_DIRECTORY),
    (TREE, ".claude", MASKED_DIRECTORY),
    (TREE, ".cursor", MASKED_DIRECTORY),
    (TREE, ".grok", MASKED_DIRECTORY),
    (TREE, ".mcp.json", MASKED_FILE),
)
#: ``seat_profile_grok.JAIL_PROTECTION``: the §2.4 table per image sha256. An image with no
#: entry has no eligible ``staged`` (eligibility condition 2, checked by SL-3).
JAIL_PROTECTION: Mapping[str, tuple[tuple[str, str, str], ...]] = MappingProxyType({
    GROK_1_0_92_SHA256: _PROTECTION_1_0_92,
})


def _masks(scope: str) -> tuple[tuple[str, str], ...]:
    """``(path, treatment)`` of one scope's masks, in table order. The masks are the same for
    every pinned image: the mounts do not depend on the binary."""
    return tuple((path, treatment) for row_scope, path, treatment in _PROTECTION_1_0_92
                 if row_scope == scope and treatment in {MASKED_FILE, MASKED_DIRECTORY})


HOME_MASKS = _masks(HOME)
TREE_MASKS = _masks(TREE)

# --- Sources, the ordered mount list and the digest placeholders (jail contract §2.3) ----


def masks_source(provider_config: str, name: str) -> str:
    """``<review_dir>/grok-masks/<name>``, the sibling of the staged ``grok-config``.

    The one derivation of a mask source: applied to the real config path for the mounts
    and to main's ``"<gemini-config>"`` placeholder for the digest (president note B2)."""
    return posixpath.join(posixpath.dirname(provider_config), HOST_GROK_MASKS_DIRNAME, name)


def writable_source(home: str, name: str) -> str:
    """``<home>/.grok-rw/<name>``, applied to the real home and to ``"<home>"``."""
    return f"{home}/{HOST_GROK_WRITABLE_DIRNAME}/{name}"


def _mask_source_name(treatment: str) -> str:
    return MASK_FILE if treatment == MASKED_FILE else MASK_DIRECTORY


def _mask_root(scope: str) -> str:
    return SEAT_HOME if scope == HOME else SEAT_TREE


def _ordered_mounts(provider_config: str, home: str, egress_ca: str
                    ) -> tuple[tuple[tuple[str, ...], str | None], ...]:
    """§2.3's ordered list: ``(owner argv words, mount destination or None)`` per entry.
    ``None`` marks a ``--dir`` inside a tmpfs, which creates a directory, not a mount."""
    entries: list[tuple[tuple[str, ...], str | None]] = [
        (("--ro-bind", provider_config, SEAT_GROK_DOTDIR), SEAT_GROK_DOTDIR),
    ]
    for name in WRITABLE_TMPFS:
        destination = f"{SEAT_GROK_DOTDIR}/{name}"
        entries.append((("--perms", "1777", "--tmpfs", destination), destination))
    for name in WRITABLE_LOCKS:
        destination = f"{SEAT_GROK_DOTDIR}/{name}"
        entries.append((("--bind", writable_source(home, name), destination), destination))
    entries.append((("--ro-bind", egress_ca, SEAT_EGRESS_CA), SEAT_EGRESS_CA))
    for scope, masks in ((HOME, HOME_MASKS), (TREE, TREE_MASKS)):
        for path, treatment in masks:
            destination = f"{_mask_root(scope)}/{path}"
            parent = posixpath.dirname(path)
            if parent:
                # `.config/grove`: its ancestor is a tmpfs mount point and the mask point is
                # a read-only directory inside it (§2.4).
                ancestor = f"{_mask_root(scope)}/{parent}"
                entries.append((("--perms", "1777", "--tmpfs", ancestor), ancestor))
                entries.append((("--perms", "0555", "--dir", destination), None))
            source = masks_source(provider_config, _mask_source_name(treatment))
            entries.append((("--ro-bind", source, destination), destination))
    return tuple(entries)


def _owner_binds(paths: OwnerPaths) -> tuple[str, ...]:
    if not paths.provider_config or not paths.egress_ca:
        from .seat_jail import SeatSandboxRefused, refused
        raise SeatSandboxRefused(refused("jail_build"), "the grok jail needs its config and CA")
    return tuple(word for words, _destination in _ordered_mounts(
        paths.provider_config, paths.home, paths.egress_ca) for word in words)


def _mount_points(paths: OwnerPaths) -> tuple[str, ...]:
    """Every destination of the ordered list (president note B4), from the same table."""
    return tuple(destination for _words, destination in _ordered_mounts(
        paths.provider_config or "<gemini-config>", paths.home, paths.egress_ca or "<egress-ca>")
        if destination is not None)


def _placeholders(paths: OwnerPaths) -> Mapping[str, str]:
    from . import seat_jail

    values: dict[str, str] = {}
    canonical_config = seat_jail._PLACEHOLDERS["gemini_config"]
    if paths.provider_config is not None:
        # Main's canonical digest feeds this literal (president note B2).
        values[paths.provider_config] = canonical_config
        for name in (MASK_FILE, MASK_DIRECTORY):
            values[masks_source(paths.provider_config, name)] = masks_source(
                canonical_config, name)
    if paths.egress_ca is not None:
        values[paths.egress_ca] = seat_jail._PLACEHOLDERS["egress_ca"]
    if paths.egress_proxy is not None:
        values[paths.egress_proxy] = seat_jail._PLACEHOLDERS["egress_proxy"]
    for name in WRITABLE_LOCKS:
        values[writable_source(paths.home, name)] = writable_source(
            seat_jail._PLACEHOLDERS["home"], name)
    return MappingProxyType(values)


def _env(inputs: EnvInputs) -> Mapping[str, str]:
    if inputs.egress_proxy is None:
        return MappingProxyType({})
    return MappingProxyType({"HTTPS_PROXY": inputs.egress_proxy, "SSL_CERT_FILE": SEAT_EGRESS_CA})


def jailed_grok_command(inputs: ArgvInputs) -> tuple[str, ...]:
    """Main's ``staged`` form for the production model and effort, with only argv0 and the
    ``--cwd`` value replaced (jail contract §2.1); the prompt stays on stdin."""
    from .panel_invoker import grok_runtime_forms

    command = list(grok_runtime_forms(model=inputs.model, effort=inputs.effort or "high")["staged"])
    command[0] = inputs.provider_argv0
    command[command.index("--cwd") + 1] = SEAT_TREE
    return tuple(command)


# --- The closed gate (jail contract §4.1) ------------------------------------------------


def tool_surface_code() -> str | None:
    """L6: the fixed refusal while ``grok_jail_surface`` is absent from the installed
    package. Reads no receipt. SL-3 creates the module and its opening check; anything
    short of a callable check that answers ``None`` or a code refuses."""
    try:
        from . import grok_jail_surface  # type: ignore[attr-defined]
    except ImportError:
        return TOOL_SURFACE_UNVERIFIED
    check = getattr(grok_jail_surface, "precondition_code", None)
    if not callable(check):
        return TOOL_SURFACE_UNVERIFIED
    try:
        code = check()
    except Exception:  # noqa: BLE001 - the opening check fails closed
        return TOOL_SURFACE_UNVERIFIED
    return code if code is None or isinstance(code, str) and code else TOOL_SURFACE_UNVERIFIED


def grok_admission_gate(leg, env, execute, *, executable=None, dependency=None):
    """The doctor's Grok gate. It adds no predicate of its own while the gate is closed:
    the route's own order (L3 host, L5 credential, L6 tool surface) then decides, so the
    doctor and a launch report the same first refusal."""
    return None


# --- Profile data -------------------------------------------------------------------------


def _credential_present() -> bool:
    from .seat_grok_credential import grok_seat_credential_present

    return grok_seat_credential_present()


def _auth_probe():
    from .panel_invoker import _parent_auth_state

    return _parent_auth_state(LEG)


GROK_WINDOW_ROWS = WindowRows(
    "canonical_grok", "grok_route", "jailed",
    (("tree", SEAT_TREE, "reviewed-tree"),
     ("home", SEAT_HOME, "seat-home"),
     ("provider_config", SEAT_GROK_DOTDIR, HOST_GROK_CONFIG_DIRNAME)),
    # Every tree discovery path is masked and `.grok` is a read-only projection: no row
    # plants into a projection or a mask.
    (),
)

NOTICE_CODES = frozenset({
    "grok_seat_credential_missing", "grok_seat_credential_refused", "grok_seat_token_expired",
    "grok_seat_token_in_output", "grok_seat_token_refreshed_in_jail", TOOL_SURFACE_UNVERIFIED,
})

GROK_PROFILE = JailProfile(
    leg=LEG, vendor="grok", owner_binds=_owner_binds, env=_env, home_dirs=(".grok",),
    digest_placeholders=_placeholders, mount_points=_mount_points,
    new_session=True, token_fd=False, argv=jailed_grok_command, projection="none",
    credential=CredentialDelivery("home_file", "grok-credential-scope"),
    credential_present=_credential_present, credential_missing_code="grok_seat_credential_missing",
    preconditions=(Precondition("tool_surface", tool_surface_code),),
    recorded_stop=None, variant=None,
    config_surface=ConfigSurface(True, DISCOVERY_PATHS),
    auth_probe=_auth_probe, output_secret_code="grok_seat_token_in_output",
    containment=ContainmentEvidence("grok-credential-scope", "grok-refresh-detection",
                                    "grok-unlisted-refusal", None),
    allowlist_id="grok-review", notice_codes=NOTICE_CODES, window=GROK_WINDOW_ROWS,
)


def register_grok():
    from . import seat_admission, seat_profiles
    from .seat_subject import register_provider_executable

    seat_profiles.register(GROK_PROFILE)
    register_provider_executable(LEG, "grok")
    seat_admission.register(LEG, grok_admission_gate)


# --- The provider-free qualification's shape (jail contract §2.3, president note B3) ------


def write_mask_sources(review_dir: Path) -> Path:
    """``<review_dir>/grok-masks/``: ``empty`` (zero bytes, 0444) and ``empty.d/`` (0555)."""
    from .seat_jail import _O_DIR, open_dir_nofollow

    root = open_dir_nofollow(review_dir)
    try:
        os.mkdir(HOST_GROK_MASKS_DIRNAME, 0o700, dir_fd=root)
        masks = os.open(HOST_GROK_MASKS_DIRNAME, _O_DIR, dir_fd=root)
        try:
            fd = os.open(MASK_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                         | os.O_CLOEXEC, 0o600, dir_fd=masks)
            try:
                os.fchmod(fd, 0o444)
            finally:
                os.close(fd)
            os.mkdir(MASK_DIRECTORY, 0o700, dir_fd=masks)
            empty = os.open(MASK_DIRECTORY, _O_DIR, dir_fd=masks)
            try:
                os.fchmod(empty, 0o555)
            finally:
                os.close(empty)
            os.fchmod(masks, 0o555)
        finally:
            os.close(masks)
    finally:
        os.close(root)
    return Path(review_dir) / HOST_GROK_MASKS_DIRNAME


def qualification_shape(seat_dir: Path) -> dict[str, object]:
    """The provider-free qualification's ``build_seat_jail`` inputs, in the production shape:
    a fixture staged ``grok-config/`` (the pinned seat config and placeholder credential
    files, no operator store), the mask sources and a placeholder CA. Written before the
    build; the seat-home stubs come after it (:func:`stub_mount_points`)."""
    from . import seat_grok_credential as credential

    config = Path(seat_dir) / HOST_GROK_CONFIG_DIRNAME
    try:
        credential._stage(config, (
            (credential.CONFIG_FILE_NAME, credential.seat_config_bytes()),
            (credential.AUTH_FILE_NAME, b"{}"),
            (credential.AGENT_ID_FILE_NAME, b"qualification"),
            *((lock, b"") for lock in credential.MOUNT_POINT_FILES),
        ))
        write_mask_sources(Path(seat_dir))
        certificate = Path(seat_dir) / "egress-ca.pem"
        certificate.write_text("qualification placeholder certificate\n", encoding="ascii")
        certificate.chmod(0o444)
    except BaseException:
        remove_staged(Path(seat_dir))
        raise
    return {"gemini_config": config, "egress_ca": certificate,
            "egress_proxy": "http://srt:qualification@127.0.0.1:3128"}


def qualification_key():
    """The key the route binds at L8 (``seat_route.resolve``) for this host: the canonical
    profile digest, the ``grok-review`` allow-list digest, and no dependency projection,
    the only one ``projection="none"`` admits."""
    from . import seat_egress_proxy
    from .seat_profiles import profile_for
    from .seat_qualification_key import key_for_launch

    profile = profile_for(LEG)
    return key_for_launch(
        profile, variant=None, projection=None,
        allowlist_digest=seat_egress_proxy.allowlist_ref(profile.allowlist_id).content_digest)


def _stub(parent_fd: int, name: str, directory: bool) -> None:
    """An empty mount point of the right type; an existing entry keeps its type when it
    matches, and a link or another type refuses."""
    from .seat_jail import SeatSandboxRefused, refused

    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        if directory:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        else:
            os.close(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                             | os.O_CLOEXEC, 0o600, dir_fd=parent_fd))
        return
    if (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        return
    raise SeatSandboxRefused(refused("jail_build"), f"{name}: mount point has the wrong type")


def stub_mount_points(jail) -> None:
    """The seat-home and tree mount points bwrap cannot create (no DAC capability): after
    ``build_seat_jail`` returns (it creates seat-home itself) and before ``seat_uid.handoff``
    (president note B3). In seat-home: ``.grok-rw/`` with ``sessions/`` and the two lock
    files, the home masks' points and ``.config``. In the tree copy: each discovery path."""
    from .seat_jail import HOST_HOME_DIRNAME, open_dir_nofollow

    home = open_dir_nofollow(Path(jail.review_dir) / HOST_HOME_DIRNAME)
    try:
        _stub(home, HOST_GROK_WRITABLE_DIRNAME, True)
        writable = open_dir_nofollow(HOST_GROK_WRITABLE_DIRNAME, dir_fd=home)
        try:
            _stub(writable, "sessions", True)
            for name in WRITABLE_LOCKS:
                _stub(writable, name, False)
        finally:
            os.close(writable)
        for path, treatment in HOME_MASKS:
            top = path.split("/", 1)[0]
            _stub(home, top, treatment == MASKED_DIRECTORY or "/" in path)
    finally:
        os.close(home)
    tree = open_dir_nofollow(jail.tree_dir)
    try:
        for path, treatment in TREE_MASKS:
            _stub(tree, path, treatment == MASKED_DIRECTORY)
    finally:
        os.close(tree)


def remove_staged(review_dir: Path) -> None:
    """Remove the operator-owned ``grok-config`` and ``grok-masks`` (outside seat-home, so
    the seat teardown leaves them), restoring write permission first (their directories
    are 0555); never follows a link."""
    from .seat_jail import open_dir_nofollow, remove_tree_at

    try:
        root = open_dir_nofollow(review_dir)
    except FileNotFoundError:
        return
    try:
        for name in (HOST_GROK_CONFIG_DIRNAME, HOST_GROK_MASKS_DIRNAME):
            try:
                remove_tree_at(root, name)
            except FileNotFoundError:
                continue
    finally:
        os.close(root)


__all__ = [
    "GROK_PROFILE", "JAIL_PROTECTION", "TOOL_SURFACE_UNVERIFIED", "grok_admission_gate",
    "jailed_grok_command", "masks_source", "qualification_shape", "register_grok",
    "remove_staged", "stub_mount_points", "tool_surface_code", "writable_source",
]
