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
profile construction and immediately before launch.

## Projection and lifecycle

Only declared files are projected. Each jail or generic seat profile receives
its own reopened descriptors and deterministic read-only file mounts, declared
directories, and relative destination links. Source or release directories are
never broadly mounted. Destination/source collisions, case-fold collisions,
protected destinations, source or ancestor links, escaping/absolute links,
chains, cycles, undeclared targets, and owner/mode mismatches refuse.

The existing qualified base jail digest remains distinct from the executable
dependency projection digest. Production and probe reopen descriptors from the
same admitted object and must carry the same projection digest and destination
set. Authority and declaration descriptors are never provider `pass_fds`.

Provider-capable managed methods bind one main task lease. Worker-pool jobs,
panel legs, and convergence callbacks acquire a child lease before submission,
bind it inside the worker, and release it in `finally`; cancelled unstarted work
is released explicitly. A session cannot close with a live task. Resetting a
parent `ContextVar` does not revoke an already-created child lease.

Provider-free subcommands may use the same package-pinned startup entry without
a dependency task lease. This API coordinates trusted in-process code; it is not
a boundary against malicious Python running in the same interpreter.
