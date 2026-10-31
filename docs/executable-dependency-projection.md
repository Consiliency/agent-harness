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

The requirement exists independently of the authority bytes. The expected authority
digest must come from an operator-controlled channel independent of the borrowed
authority bytes; hashing the descriptor being lent does not establish authority. A
required dependency with a missing or mismatched authority refuses; authority supplied
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

The borrowed authority descriptor must be read-only and remains caller-owned.
Admission checks its regular-file identity, ownership, mode, link count, size, stable bytes, and
digest, then owns a close-on-exec duplicate. It no-follow opens and validates the
declaration, selected executable, source roots, and every declared file. The
session retains those file descriptors and revalidates identity and bytes before
profile construction and immediately before launch. Group- or world-writable
files, declared directory entries, source roots, and intermediate source directories
are outside the non-overridable public ceiling even if a caller or local authority names them.
Intermediate directories beneath the trusted source root must also satisfy the
effective owner/group/mode policy. Their descriptors are retained, their identity
and permissions rechecked, and they are closed with the dependency. Ancestors
above an explicitly trusted source root are traversed without following symlinks;
their ownership and modes are not part of the root's permission floor. File opens
are nonblocking so a FIFO replacement refuses through the regular-file check.

## Projection and lifecycle

Only declared files are projected. Admission copies each verified file into a
sealed snapshot; each jail or generic seat profile reopens that snapshot with an
independent open-file description and byte offset. It receives deterministic
read-only file mounts, declared directories, and relative destination links.
Source or release directories are never broadly mounted. Destination/source
collisions, case-fold collisions, protected destinations, source or ancestor
links, escaping/absolute links, chains, cycles, undeclared targets, and
owner/mode mismatches refuse.

The seat jail adds its own non-overridable destination floor at entry to both
provider preparation functions, before creating seat directories, resolving or
copying credentials, waiting for login, refreshing credentials, or writing config.
The builder repeats that check before creating jail directories. Dependency
destinations may not equal, descend from, or be ancestors of harness-owned or system mount points. The sole `/seat` exception is
the selected subject itself at the exact canonical `/seat/bin/<leg>` slot.

The generic seat view also rejects overlap with its system, private-home, review,
input, writable, output, broker, and keyring layers. Its only exception is the
selected subject at `/run/phase-loop-seat/provider`. The destination check runs
before projection reopening and again at the final owned-launch boundary.

The existing qualified base jail digest remains distinct from the executable
dependency projection digest. Production and probe reopen descriptors from the
same admitted object and must carry the same projection digest and destination
set. Generic identity probes inherit their own projection descriptors and declared
filesystem layers, with harmless marker and credential differences; draining the
probe cannot consume production offsets. Partial jail construction closes reopened
projections, and caller input descriptors transfer to a jail only on success. A
required preparation failure also removes its newly created seat directory,
including credential config; cleanup failures are attached to the primary refusal.
The jailed broker evidence records the projection, authority, and declaration digests alongside the qualified base profile, and explicitly flags
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
in a required session; they never default to provider-free.

## Supported routes and explicit refusals

Required dependencies are supported by the generic review/admin seat profiles and
Claude/Gemini seat jails. Provider identity comes from the trusted requirement;
wrapper basenames need not match the provider. Projected launches execute the
selected snapshot at its declared destination with the original argument tail.

The following compositions raise `dependency_route_unwired` in required sessions:

- Direct trusted host execution, including direct `launch()` calls and executor
  lease-supervisor transports. `launch_with_spec` refuses these before command
  context staging or output allocation; `launch` and `launch_owned` also guard their
  entry boundaries. Path-based host execution and its ambient dependency closure
  are not supported by this API.
- Claude Channel and Agent View, before invoking either transport or staging
  command context. Their operations are not bound to the selected wrapper.
- `maintain-skills`, at CLI classification before dispatch.
- Gemini heartbeat profiles, before ambient image admission or capability checks,
  credential copies, output allocation, or spawn. Combining a projection with the
  heartbeat gate/settings descriptor protocol is not implemented.
- Gemini host credential renewal. A required Gemini review/jail launch needs a
  fresh pre-existing login; otherwise it refuses before output/config writes and
  credential projection. It never refreshes by executing the declared subject on
  the host with the real HOME. Operators renew credentials outside the required
  launch session. Standalone renewal behavior is unchanged.

With no requirement and no authority, the existing standalone transports and
launch paths remain unchanged. This API coordinates trusted in-process code; it
is not a boundary against malicious Python running in the same interpreter.

## Qualification status

Offline fixtures establish admission, projection bytes, launch-boundary refusal,
probe descriptor agreement, and cleanup. They do not demonstrate a working
interpreter/wrapper program inside a live jail. Canonical zero-provider launch and
owned-stage cleanup qualification, production seat/lease qualification, deployment
adapters, and authenticated provider acceptance remain unqualified. No private
repository, fleet root, or private commit is part of this public contract.
