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
the required Ubuntu 24.04+ override. Root action: install the printed AppArmor policy. A host
that installed it before agent-harness#1915 runs the printed script again, so that jailed seats
reach their egress proxy.

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
`base_profile_sha256`. Root action: the administrator, or the administrator's root-owned release
updater under contract §7, writes the pin. The updater may write an entry only for a release it
built and admitted through the release runtime in the same run, before promotion. It takes
`release_id` and all three entry values from that same admitted build record, binds the identity
to the exact bytes built and admitted in that run, and refuses a reused identity whose bytes
differ. All updater instances serialize on a root-owned exclusive lock held across re-reading,
validating, merging or pruning, and atomically replacing the pin. A malformed pin or entry, or
any absent required field, refuses; a conflicting release entry is never overwritten; only
entries for releases confirmed no longer retained are pruned. The replacement is root-owned,
mode 0644, and reached through root-only ancestors. Every written or pruned entry is logged to a
root-owned, non-group-or-world-writable updater log. Release bytes never establish their own
authority at seat time. The pin path is `/etc/consiliency/tooling/seat-authority.json`.
