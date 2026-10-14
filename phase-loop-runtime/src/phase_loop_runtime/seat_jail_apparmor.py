"""AppArmor override that lets the seat jail switch uid on Ubuntu 24.04+ / 26.04 (agent-harness#1276).

Ubuntu's `bwrap-userns-restrict` profile runs every child of `/usr/bin/bwrap` as
`bwrap//&unpriv_bwrap`, whose `audit deny capability` rule denies every capability. The
jail's last step before the provider is `setpriv --reuid N ...` inside bwrap, and it needs
CAP_SETUID, CAP_SETGID and CAP_SETPCAP, so on such a host it fails with
`setpriv: setresuid failed: Operation not permitted` and the jail cannot qualify.

A deny rule cannot be undone by a local `allow`, so the override does not touch
`unpriv_bwrap`. It adds one stacked exec transition for `/usr/bin/setpriv` alone (through the
local include the shipped `bwrap` profile already provides) into a small named profile that
grants exactly those three capabilities, and that profile hands the seat back to the same
`bwrap//&unpriv_bwrap` confinement on its next exec. Measured on Ubuntu 26.04 (bubblewrap
0.11.1, util-linux 2.41.3): after the drop the seat is the seat uid with empty permitted,
effective and bounding sets and no-new-privs, it cannot switch uid again, other bwrap
children keep `bwrap//&unpriv_bwrap`, and a plain `setpriv` elsewhere is unaffected.

The runtime never installs this: it needs root and changes host security policy, so a host
administrator runs the printed script. `python -m phase_loop_runtime.seat_jail_apparmor`
prints it; `--revert` prints the script that removes it; `--profile` and `--local` print the
two policy files.

`--codex` selects the separate, unqualified agent-harness#1335 candidate. The runtime
does not load it; administrator approval and complete nested-sandbox qualification are
required. See docs/seat-codex-apparmor.md for the scope and rollback protocol.
"""

from __future__ import annotations

import sys

PROFILE_NAME = "phase_loop_seat_uid_drop"
PROFILE_FILE = "phase-loop-seat-jail"        # under /etc/apparmor.d/
LOCAL_FILE = "local/bwrap-userns-restrict"   # the hook the shipped bwrap profile includes
BEGIN_MARK = "# BEGIN agent-harness seat jail (agent-harness#1276)"
END_MARK = "# END agent-harness seat jail (agent-harness#1276)"

#: The named profile. It has NO path attachment, so it is entered only through the explicit
#: transition in LOCAL_TEXT and a plain `setpriv` run elsewhere on the host is untouched.
PROFILE_TEXT = f"""\
# agent-harness seat jail (agent-harness#1276): lets ONLY the jail's `setpriv` step switch to the
# seat uid inside bwrap. Ubuntu 24.04+/26.04 run bwrap's children under `unpriv_bwrap`, which
# denies every capability, so `setpriv --reuid N` fails with EPERM. This profile has NO path
# attachment: it is entered only through the explicit transition in
# local/bwrap-userns-restrict, so a plain `setpriv` elsewhere on the host is untouched. It is
# stacked with `bwrap`, so the seat's effective capabilities are the intersection (setuid,
# setgid, setpcap only), and the exec rule hands the seat back to the confinement it had before.
abi <abi/5.0>,
include <tunables/global>

profile {PROFILE_NAME} flags=(attach_disconnected,mediate_deleted) {{
  allow capability setuid,
  allow capability setgid,
  allow capability setpcap,
  allow file rwlkm /{{**,}},
  allow signal,
  allow unix,
  allow pix /** -> &bwrap//&unpriv_bwrap,
}}
"""

#: The block added to the local include of the shipped `bwrap` profile. It is more specific
#: than the shipped `/**` rule and stacked like it.
LOCAL_TEXT = f"""\
{BEGIN_MARK}
# Run the jail's uid-drop step under its own narrow profile instead of `unpriv_bwrap`.
allow pix /usr/bin/setpriv -> &bwrap//&{PROFILE_NAME},
{END_MARK}
"""

# Candidate for agent-harness#1335. Printing this policy never installs it. It requires
# separate administrator approval and qualification of the complete nested launch.
CODEX_OWNER_PATH = "/run/phase-loop-seat/codex-owner"
CODEX_BWRAP_PATH = "/run/phase-loop-seat/codex-sandbox-bin/bwrap"
CODEX_PROVIDER_PATH = "/run/phase-loop-seat/codex-runtime/bin/codex"
CODEX_PROFILE_FILE = "phase-loop-codex-nesting"
CODEX_BEGIN_MARK = "# BEGIN agent-harness codex nesting (agent-harness#1335)"
CODEX_END_MARK = "# END agent-harness codex nesting (agent-harness#1335)"
CODEX_PROFILE_TEXT = f"""\
# Candidate host policy for agent-harness#1335; qualify before deployment.
abi <abi/5.0>,
include <tunables/global>

profile phase_loop_codex_owner flags=(attach_disconnected,mediate_deleted) {{
  allow file rwlkm /{{**,}},
  allow network,
  allow unix,
  allow ptrace,
  allow signal,
  allow mqueue,
  allow io_uring,
  allow userns,
  allow mount,
  allow umount,
  allow pivot_root,
  allow dbus,
  allow px {CODEX_OWNER_PATH} -> bwrap//&phase_loop_codex_owner,
  allow px {CODEX_PROVIDER_PATH} -> bwrap//&phase_loop_codex_owner,
  allow px {CODEX_BWRAP_PATH} -> bwrap//&phase_loop_codex_setup,
  allow px /** -> bwrap//&unpriv_bwrap,
}}

profile phase_loop_codex_setup flags=(attach_disconnected,mediate_deleted) {{
  # bubblewrap 0.11.1 REQUIRED_CAPS_0; Linux still confines them to its user namespace.
  allow capability sys_admin,
  allow capability sys_chroot,
  allow capability net_admin,
  allow capability setuid,
  allow capability setgid,
  allow capability sys_ptrace,
  allow file rwlkm /{{**,}},
  allow network,
  allow unix,
  allow ptrace,
  allow signal,
  allow mqueue,
  allow io_uring,
  allow userns,
  allow mount,
  allow umount,
  allow pivot_root,
  allow dbus,
  # Includes Codex's post-bwrap seccomp stage: no arbitrary payload keeps setup rights.
  allow px /** -> bwrap//&unpriv_bwrap,
}}
"""
CODEX_LOCAL_TEXT = f"""\
{CODEX_BEGIN_MARK}
# Fixed read-only paths supplied only to a native Codex workspace-write review seat.
allow px {CODEX_OWNER_PATH} -> bwrap//&phase_loop_codex_owner,
allow px {CODEX_PROVIDER_PATH} -> bwrap//&phase_loop_codex_owner,
allow px {CODEX_BWRAP_PATH} -> bwrap//&phase_loop_codex_setup,
{CODEX_END_MARK}
"""

# sed address forms of the markers (the slash is the address delimiter). Built outside the
# f-strings below: a backslash inside an f-string expression is a syntax error before 3.12.
_BEGIN_SED = BEGIN_MARK.replace("/", "\\/")
_END_SED = END_MARK.replace("/", "\\/")

_SCRIPT_HEAD = """\
#!/bin/sh
# agent-harness seat jail: AppArmor override for Ubuntu 24.04+/26.04 (agent-harness#1276).
# Run as root. Idempotent. AA_DIR and APPARMOR_PARSER exist so it can be tried against a
# scratch directory.
set -eu
AA_DIR="${AA_DIR:-/etc/apparmor.d}"
PARSER="${APPARMOR_PARSER:-apparmor_parser}"
"""


def install_script(*, codex: bool = False) -> str:
    """The root script that installs the override. It never overwrites an administrator's
    existing `local/bwrap-userns-restrict`: the block is appended once, between markers."""
    profile_file = CODEX_PROFILE_FILE if codex else PROFILE_FILE
    profile_text = CODEX_PROFILE_TEXT if codex else PROFILE_TEXT
    local_text = CODEX_LOCAL_TEXT if codex else LOCAL_TEXT
    begin_mark = CODEX_BEGIN_MARK if codex else BEGIN_MARK
    next_step = "qualify the complete Codex nested sandbox before deployment" if codex else "phase-loop seat-sandbox qualify"
    preflight = ""
    if codex:
        preflight = f"""\
for target in "$AA_DIR/{profile_file}" "$AA_DIR/{LOCAL_FILE}"; do
  [ ! -L "$target" ] || {{ echo "refusing symlink policy target" >&2; exit 1; }}
done
if [ -e "$AA_DIR/{profile_file}" ] && ! cmp -s "$AA_DIR/{profile_file}" - <<'PROFILE_EXPECTED'
{profile_text}PROFILE_EXPECTED
then
  echo "refusing an existing different Codex policy" >&2
  exit 1
fi
if grep -qF '{begin_mark}' "$AA_DIR/{LOCAL_FILE}" 2>/dev/null || grep -qF '{CODEX_END_MARK}' "$AA_DIR/{LOCAL_FILE}" 2>/dev/null; then
  codex_existing_block=$(sed -n '/{CODEX_BEGIN_MARK}/,/{CODEX_END_MARK}/p' "$AA_DIR/{LOCAL_FILE}")
  codex_expected_block=$(cat <<'LOCAL_EXPECTED'
{local_text}LOCAL_EXPECTED
)
  [ "$codex_existing_block" = "$codex_expected_block" ] || {{ echo "refusing a different Codex local block" >&2; exit 1; }}
fi
"""
    return (
        (_SCRIPT_HEAD.replace("seat jail", "codex nesting").replace("agent-harness#1276", "agent-harness#1335")
         if codex else _SCRIPT_HEAD)
        + f"""\
[ -f "$AA_DIR/bwrap-userns-restrict" ] || {{
  echo "no $AA_DIR/bwrap-userns-restrict: this host does not confine bwrap, nothing to do" >&2
  exit 0
}}
{preflight}mkdir -p "$AA_DIR/local"
cat > "$AA_DIR/{profile_file}" <<'PROFILE_EOF'
{profile_text}PROFILE_EOF
chmod 0644 "$AA_DIR/{profile_file}"
if ! grep -qF '{begin_mark}' "$AA_DIR/{LOCAL_FILE}" 2>/dev/null; then
  cat >> "$AA_DIR/{LOCAL_FILE}" <<'LOCAL_EOF'
{local_text}LOCAL_EOF
fi
chmod 0644 "$AA_DIR/{LOCAL_FILE}"
"$PARSER" -r "$AA_DIR/{profile_file}"
"$PARSER" -r "$AA_DIR/bwrap-userns-restrict"
echo "installed; now run: {next_step}"
"""
    )


def revert_script(*, codex: bool = False) -> str:
    """The root script that removes the override and reloads the shipped profile."""
    profile_file = CODEX_PROFILE_FILE if codex else PROFILE_FILE
    begin_sed = CODEX_BEGIN_MARK.replace("/", "\\/") if codex else _BEGIN_SED
    end_sed = CODEX_END_MARK.replace("/", "\\/") if codex else _END_SED
    ignore_failure = "" if codex else " || true"
    return (
        (_SCRIPT_HEAD.replace("seat jail", "codex nesting").replace("agent-harness#1276", "agent-harness#1335")
         if codex else _SCRIPT_HEAD)
        + f"""\
if [ -f "$AA_DIR/{LOCAL_FILE}" ]; then
  sed -i '/{begin_sed}/,/{end_sed}/d' "$AA_DIR/{LOCAL_FILE}"
  [ -s "$AA_DIR/{LOCAL_FILE}" ] || rm -f "$AA_DIR/{LOCAL_FILE}"
fi
"$PARSER" -r "$AA_DIR/bwrap-userns-restrict"{ignore_failure}
if [ -f "$AA_DIR/{profile_file}" ]; then
  "$PARSER" -R "$AA_DIR/{profile_file}"{ignore_failure}
  rm -f "$AA_DIR/{profile_file}"
fi
echo "removed"
"""
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    table = {
        (): install_script,
        ("--revert",): revert_script,
        ("--profile",): lambda: PROFILE_TEXT,
        ("--local",): lambda: LOCAL_TEXT,
        ("--codex",): lambda: install_script(codex=True),
        ("--codex", "--revert"): lambda: revert_script(codex=True),
        ("--codex", "--profile"): lambda: CODEX_PROFILE_TEXT,
        ("--codex", "--local"): lambda: CODEX_LOCAL_TEXT,
    }
    render = table.get(tuple(args))
    if render is None:
        print("usage: python -m phase_loop_runtime.seat_jail_apparmor "
              "[--codex] [--revert | --profile | --local]", file=sys.stderr)
        return 2
    sys.stdout.write(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
