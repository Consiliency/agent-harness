# Supervised worker: local admission seam

ENVELOPE implements the local fixture freeze for agent-harness#1818 and
agent-harness#1819. It provides no public CLI, provider integration, installed-tool
qualification, contract conformance, sandbox or live-use authority. The acceptance
criteria and closed capability matrix are in
[`specs/phase-plans-v12.md`](../specs/phase-plans-v12.md); observed offline evidence
is in [the ENVELOPE receipt](../plans/evidence/supervised-worker/ENVELOPE.md).

## Frozen Python boundary

`phase_loop_runtime.supervised_launch` exports:

- `prepare_launch(envelope_bytes, *, validator, decoder, config)` returns
  `PreparedLaunch` or typed `Refused(reason)`. It never launches processes,
  probes tools or writes evidence. There is no default validator or codec.
- `Validator(view)` returns exactly `Admit(launch_digest, attempt_id)` or
  `Refused`. Exceptions, booleans, strings, unavailable bindings and mismatched
  identities refuse. Subclasses and duck-typed admits do not confer admission.
- `PreparedLaunch` holds the immutable `EnvelopeView`, typed verdict and a
  process-local token. `LaunchInputs` holds captured instruction/baseline bytes,
  their hashes, closed argv, absolute executable/wrapper identities, workspace
  classification and root device/inode, tier, constraints, timeout and trusted
  configuration/template/qualification digests.
- `consume_admission(prepared)` atomically spends the token and returns
  `LaunchInputs` or `Refused`. It checks the original object and launch binding,
  workspace classification, device/inode and executable/wrapper hashes again.
  The registry binds a separate snapshot of the admitted digest and inputs.
  A failed consumption also spends the token. A copy cannot consume the original
  object's token. JOURNAL must add durable reservation; WORKER must consume
  immediately before the bounded attempt and recheck identities before each
  probe or worker spawn. Consumed assignment/run/attempt identities refuse reuse
  within the process. Retries require fresh validation and attempt identity.

The trusted injected codec consumes an immutable `EnvelopeCapture(raw_bytes,
raw_digest, envelope)` and returns `(decoded_mapping, codec_envelope_digest)`.
The boundary parses JSON and hashes the captured raw bytes once, then supplies
the frozen mapping to the codec; codecs must consume it without reparsing bytes.
The returned mapping must equal the captured mapping; rewriting fields refuses
before validation. Callback exceptions, including SystemExit and KeyboardInterrupt,
become typed refusals. The ambiguity check precedes codec invocation. The envelope digest follows the
supplied codec. The harness launch
digest uses the domain `agent-harness:supervised-launch:v1`, NUL termination,
and three eight-byte big-endian length-prefixed values: raw-envelope hash,
canonical LaunchInputs and attempt id. Canonical inputs use sorted compact JSON;
reference bytes are represented by their bound SHA-256 hashes. The validator
sees both digests and every effective launch input. Caller context is preserved
opaquely, never read as executable configuration. Later journal/evidence consumers
must retain only its digest, not context, prompts or raw source bytes.

The labelled synthetic fixture in
`phase-loop-runtime/tests/fixtures/supervised_launch_local/` documents local field
vocabulary, not a public schema. `launch_inputs` includes references, executable,
wrappers, workspace/target, tier, constraints and timeout. Unknown launch keys
(including argv tails), missing inputs, duplicate JSON keys and nonfinite values
refuse. Admission snapshots references before calling the validator; replacing
a source file afterward cannot change the admitted bytes.

## Trusted operator configuration

`LaunchConfig(config_path, template_path, qualification_path=None)` names explicit
absolute files. The local config has explicit positive `envelope_cap`,
`reference_cap`, `aggregate_cap`, `timeout_max`, `reference_roots`,
`executable_path` and `qualified_version` members. These local limits and member
names must be reconciled when SCHEMA pins the public bundle. Missing bytes do
not fall back to environment defaults. The closed template is a JSON argv array
beginning with `{executable}` and containing only literal remaining arguments.
Wrappers and their digests are admitted with the executable.

Reference locators contain `root`, relative `path` and `digest`. Reads walk from
`/` using held directory descriptors and `O_NOFOLLOW` at every component; roots
must be declared, traversal, non-regular files and multiply linked references
refuse. Final components are inspected with `O_PATH` before opening for reads;
descriptors use `O_CLOEXEC`. Reads loop to EOF or the configured cap. The per-file and total
caps apply before validation. Linux `O_PATH` directory descriptors support
search-only ancestor directories without requiring directory listing access.

Executables are resolved before any chdir using only absolute, nonempty configured
search entries, or an explicit absolute path. This local implementation requires
canonical non-symlink paths. This stricter local restriction is an explicit plan
amendment pending WORKER reconciliation. Workspace, target and reference-root
locations are excluded by comparing device/inode identities during the held
descriptor walk, including ancestors. Missing or non-directory excluded roots refuse.
Executable files may belong to root or the operator. Group/world-writable components refuse conservatively, even with user-private
groups and umask 002. Use explicit trusted, non-writable paths; there is no silent
downgrade. Trusted input files must belong to the operator; ancestor directories
may belong to the operator or root and must also be non-writable by group/world.

Symlinks at any component, including ancestors above declared roots, refuse.
File capture reports `path_symlink`; workspace and target classification retain
their typed root refusals. Configure the canonical physical paths (for example,
use `realpath` during operator setup) for every root and trusted input, including
reference locators. A second spelling does not change the identity exclusions.
Trusted inputs, executables and wrappers must also have `st_nlink == 1`;
multiply linked installed tools require a separate single-link installation.
Identity exclusion recognizes mounts of excluded roots and their ancestors.
It does not identify a mount whose source is strictly inside an excluded root;
operators must keep such mounts outside the admitted path set.

`supervised_launch_binding.load_validator_binding(path, *, workspace, target)`
requires isolated Python (`-I`) and an explicit operator-owned binding manifest
outside workspace, target and reference roots. Its local manifest names
`validator`, `codec`, `config`, `template` and nullable `qualification` paths.
Validator and codec modules export `validate` and `decode`. The loader checks
uid, mode, regular-file status and component-wise no-follow paths for all inputs,
then executes the verified module bytes from the absolute location. It performs
no entry-point discovery, cwd imports or environment-based binding selection.
Transitive imports use the trusted installed isolated interpreter; WORKER owns
its placement and CLI integration. Offline children explicitly insert the checkout
source root, assert package provenance and record the resolved module path.
Trusted input and executable captures have a local 1 MiB file cap; reference and
envelope caps additionally come from the explicit operator configuration.
The 1 MiB executable limit excludes many installed provider binaries. WORKER
must reconcile that limit and preserve complete streaming hashes when raising
it, pin interpreter chains as wrappers, and construct PATH from trusted config.

Provider eligibility requires an operator-owned qualification record matching
executable/wrapper paths and SHA-256 identities, template digest and configured
version, with `write_attempt_refused`, `proposal_return` and `audit` evidence.
Synthetic records establish only mechanics. Filesystem inspection rejects provider
worktrees/gitfiles (including nested entries), nested/shared workspace roots,
hardlinks, symlinks, alternates and commondir storage. Git config is read as data;
worktree and include redirections refuse without executing git. Audit-only classification permits worktree/in-place use
with detection-only posture. Unknown classifications refuse. Every requested
constraint is currently unsupported on both tiers; `os_enforced` always refuses.

Provider config accepts only clean-clone core, remote, branch and object-format
keys. Standard remote/branch subsection headers are permitted; quoted section
names, quoted values, escapes, continuations, includes and other keys refuse.
WORKER must never run git under the workspace's own configuration: later audit
and patch capture must use controlled local, global and system configuration.

## Standalone guard order and remaining authority

`supervised_dependency.classify_supervised_command` classifies namespaced
`supervised-launch` and `supervised-cancel` as dependency-unwired;
`supervised-status` is provider-free. These names are reserved for WORKER's module
CLI and do not replace generic `phase-loop status` or add generic subcommands.
The generic classifier retains refusal for these unknown command names in
required sessions; only the supervised namespace grants status readiness.
`preflight_supervised_route` runs before envelope file reads, binding imports,
credentials, output effects or probes. WORKER must preserve this composition.
The admission API independently calls the existing startup guard before decode
or validation. Direct unleased required-session calls preserve `task_unbound`;
bound unwired routes preserve `dependency_route_unwired`. Startup-session
propagation semantics remain unchanged. A separate exec loses that in-process
context; declared envelope dependencies still refuse standalone admission.

There is no same-login containment, network denial or protection of on-disk
git/gh credentials. User-owned tools remain writable by the same login. Without
descriptor execution there is a residual check-to-exec race; WORKER must disclose
it and repeat checks. JOURNAL's future durable records cannot prove trust against
a same-login writer. WORKER/JOURNAL own cancellation, durable replay prevention,
bounded subprocesses and journal implementation; a `finished` result will not
prove all descendants are gone. The external controller owns apply/acceptance.

The public schema and semantic vector pin, installed-provider qualification,
registry activation, exact-head CI/Gate A, independent review and live-use
authority remain separate pending gates. Fixture freezes must be amended if
public bytes differ, and CLOSEOUT must run pinned semantics through production.

Documentation decision: these local APIs are documented here. ENVELOPE adds no
public CLI or release, so README and release notes remain current. WORKER closeout
owns the integrated feature's CHANGELOG update; no CHANGELOG handoff is required
for ENVELOPE completion.
