# Executable dependency admission and projection

`phase-loop-runtime` can admit a required executable and its declared read-only
files before a managed provider-capable route performs credential, output,
sandbox, or process effects. The interface is deployment-neutral: the caller
supplies a typed `DependencyRequirement`, one borrowed authority file descriptor,
an expected authority digest, and a qualified public runtime identity.

The public API is `open_dependency_startup(DependencyStartupSpec(...))`. It
returns a same-process `DependencyStartupSession` with pinned `run_cli`,
`run_skill_eval`, and `run_seat_jail_qualification` methods. It also exposes
explicit task leases for trusted in-process thread-pool work. Session context is
not claimed to survive `exec`.

## Admission rules

The requirement exists independently of the authority bytes. A required
dependency with a missing or mismatched authority refuses; authority supplied
without a requirement also refuses. Existing standalone behavior is selected
only when both are absent. A required route never falls back to a wrapper,
direct payload, adjacent file, or ambient executable.

Authority and declaration inputs must be RFC 8785 canonical JSON with no BOM,
duplicate key, insignificant whitespace, trailing newline, unknown field, or
unsafe integer. Booleans do not satisfy integer fields. The packaged public
schemas are:

- `dependency-requirement-v1.schema.json`
- `executable-dependency-authority-v1.schema.json`
- `executable-dependency-declaration-v1.schema.json`

The authority parser retains the fixed public ceilings: 128 KiB authority,
16 MiB declaration, 1,024 entries, 512 MiB per file, and 2 GiB aggregate file
bytes. Public, launch-host, and local-authority restrictions intersect; a local
authority can only narrow paths, owners, modes, and numeric limits. These are
parser and projection bounds, not CPU, memory, disk, process, time, credential,
account, billing, network, or sandbox grants.

The borrowed authority descriptor remains caller-owned. Admission checks its
regular-file identity, ownership, mode, link count, size, stable bytes, and
digest, then owns a close-on-exec duplicate. It no-follow opens and validates the
declaration, selected executable, source roots, and every declared file. The
session retains those file descriptors and revalidates identity and bytes before
profile construction and immediately before launch. Group- or world-writable
file, declared directory entries, and source roots are outside the
non-overridable public ceiling even if a caller or local authority names them.

## Projection and lifecycle

Only declared files are projected. Admission copies each verified file into a
sealed snapshot; each jail or generic seat profile reopens that snapshot with an
independent open-file description and byte offset. It receives deterministic
read-only file mounts, declared directories, and relative destination links.
Source or release directories are never broadly mounted. Destination/source
collisions, case-fold collisions, protected destinations, source or ancestor
links, escaping/absolute links, chains, cycles, undeclared targets, and
owner/mode mismatches refuse.

The seat jail adds its own non-overridable destination floor before creating
jail directories. Dependency destinations may not equal, descend from, or be
ancestors of harness-owned or system mount points. The sole `/seat` exception is
the selected subject itself at the exact canonical `/seat/bin/<leg>` slot.

The generic seat view also rejects overlap with its system, private-home, review,
input, writable, output, broker, and keyring layers. Its only exception is the
selected subject at `/run/phase-loop-seat/provider`. The destination check runs
before projection reopening and again at the final owned-launch boundary.

The existing qualified base jail digest remains distinct from the executable
dependency projection digest. Production and probe reopen descriptors from the
same admitted object and must carry the same projection digest and destination
set. The jailed broker evidence records the projection, authority, and
declaration digests alongside the qualified base profile, and explicitly flags
sources owned or owner-writable by the runtime effective user. Authority and
declaration descriptors are never provider `pass_fds`.

Provider-capable managed methods bind one main task lease. Worker-pool jobs,
panel legs, and convergence callbacks acquire a child lease before submission,
bind it inside the worker, and release it in `finally`; cancelled unstarted work
is released explicitly. A session cannot close with a live task. Resetting a
parent `ContextVar` does not revoke an already-created child lease.

Provider-free subcommands use a closed command inventory and may use the same
package-pinned startup entry without a dependency task lease. Unknown commands
and provider-launching commands whose launch seam is not dependency-wired refuse
in a required session; they never default to provider-free. The direct executor
route is path-and-inode checked immediately before its path-based spawn, but its
declared closure is not projected into a jail. This API coordinates trusted
in-process code; it is not a boundary against malicious Python running in the
same interpreter.
