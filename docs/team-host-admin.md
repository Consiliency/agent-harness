# Team-host administrator checklist

This is the root-owned LA-1 checklist for hosts that run confined review seats. Operators can
render every action with `python3 -m phase_loop_runtime.seat_host_admin --all`, or pass a
`phase-loop doctor --json` file to print only actions for rows reported missing. The renderer is
print-only; it never applies an action.

Operators whose `$HOME` or XDG directory is reached through a symlink should set those variables
to the resolved path. TEAMHOST's no-follow walk refuses linked ancestors.

## LA1-SUBID — subordinate identities

Serves EC-TEAMHOST-2. Read-only check: inspect `getent passwd`, `getent group`, `/etc/subuid` and
`/etc/subgid` and confirm each operator's ranges overlap neither another account's ranges nor a
real uid/gid. Root action: allocate disjoint uid and gid ranges for every operator account.

## LA1-TIOCSTI — legacy TIOCSTI setting

Serves EC-TEAMHOST-3. Read-only check: `sysctl dev.tty.legacy_tiocsti`. Root action: set the value
to `0` and persist it.

## LA1-APPARMOR — Ubuntu user namespaces

Serves EC-TEAMHOST-3. Read-only check: `python3 -m phase_loop_runtime.seat_jail_apparmor` prints
the required Ubuntu 24.04+ override. Root action: install the printed AppArmor policy.

## LA1-USERNS — unprivileged user namespaces

Serves EC-TEAMHOST-3. Read-only check: `sysctl kernel.unprivileged_userns_clone` where the sysctl
exists. Root action: set it to `1` when the host exposes it.

## LA1-PACKAGES — host tools

Serves EC-TEAMHOST-3. Read-only checks: `command -v bwrap setpriv nsenter newuidmap newgidmap
slirp4netns iptables`. Root action: install all missing packages.

## LA1-MACHINE-ID — host identity

Serves EC-TEAMHOST-3. Read-only check: verify `/etc/machine-id` is readable and non-empty. Root
action: provision a stable machine id using the host operating system's supported procedure.

## LA1-RELEASE — declared seat dependencies

Serves EC-TEAMHOST-3. Read-only check: inspect the active managed release's declared seat files.
Root action: install a managed release that carries every declared seat dependency.

## LA1-AUTHORITY-PIN — managed-release authority

Serves EC-TEAMHOST-1. Read-only check: inspect the root-owned seat-authority pin for an entry for
each active release and leg, containing `authority_sha256`, `authority_id` and
`base_profile_sha256`. Root action: write the pin from the independently reviewed declaration;
release bytes never establish their own authority. The pin path is
`/etc/consiliency/tooling/seat-authority.json`.
