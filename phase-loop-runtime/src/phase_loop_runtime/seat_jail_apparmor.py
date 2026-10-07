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

_SCRIPT_HEAD = """\
#!/bin/sh
# agent-harness seat jail: AppArmor override for Ubuntu 24.04+/26.04 (agent-harness#1276).
# Run as root. Idempotent. AA_DIR and APPARMOR_PARSER exist so it can be tried against a
# scratch directory.
set -eu
AA_DIR="${AA_DIR:-/etc/apparmor.d}"
PARSER="${APPARMOR_PARSER:-apparmor_parser}"
"""


def install_script() -> str:
    """The root script that installs the override. It never overwrites an administrator's
    existing `local/bwrap-userns-restrict`: the block is appended once, between markers."""
    return (
        _SCRIPT_HEAD
        + f"""\
[ -f "$AA_DIR/bwrap-userns-restrict" ] || {{
  echo "no $AA_DIR/bwrap-userns-restrict: this host does not confine bwrap, nothing to do" >&2
  exit 0
}}
mkdir -p "$AA_DIR/local"
cat > "$AA_DIR/{PROFILE_FILE}" <<'PROFILE_EOF'
{PROFILE_TEXT}PROFILE_EOF
chmod 0644 "$AA_DIR/{PROFILE_FILE}"
if ! grep -qF '{BEGIN_MARK}' "$AA_DIR/{LOCAL_FILE}" 2>/dev/null; then
  cat >> "$AA_DIR/{LOCAL_FILE}" <<'LOCAL_EOF'
{LOCAL_TEXT}LOCAL_EOF
fi
chmod 0644 "$AA_DIR/{LOCAL_FILE}"
"$PARSER" -r "$AA_DIR/{PROFILE_FILE}"
"$PARSER" -r "$AA_DIR/bwrap-userns-restrict"
echo "installed; now run: phase-loop seat-sandbox qualify"
"""
    )


def revert_script() -> str:
    """The root script that removes the override and reloads the shipped profile."""
    return (
        _SCRIPT_HEAD
        + f"""\
if [ -f "$AA_DIR/{LOCAL_FILE}" ]; then
  sed -i '/{BEGIN_MARK.replace("/", "\\/")}/,/{END_MARK.replace("/", "\\/")}/d' "$AA_DIR/{LOCAL_FILE}"
  [ -s "$AA_DIR/{LOCAL_FILE}" ] || rm -f "$AA_DIR/{LOCAL_FILE}"
fi
"$PARSER" -r "$AA_DIR/bwrap-userns-restrict" || true
if [ -f "$AA_DIR/{PROFILE_FILE}" ]; then
  "$PARSER" -R "$AA_DIR/{PROFILE_FILE}" || true
  rm -f "$AA_DIR/{PROFILE_FILE}"
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
    }
    render = table.get(tuple(args))
    if render is None:
        print("usage: python -m phase_loop_runtime.seat_jail_apparmor "
              "[--revert | --profile | --local]", file=sys.stderr)
        return 2
    sys.stdout.write(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
