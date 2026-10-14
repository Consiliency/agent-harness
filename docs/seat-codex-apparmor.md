# Codex nested sandbox candidate (agent-harness#1335)

Status: prepared for review; not installed or qualified on dev0. Installation changes host
security policy and requires separate administrator approval. This does not complete the
required review board or authorize a merge.

## Scope and prerequisites

The actual owned `codex sandbox ... -- true` probe on dev0 fails with bubblewrap's namespace
permission diagnostic. Host `unshare` and standalone bubblewrap controls succeed. Kernel
audit reports `unpriv_bwrap` denies `sys_admin` to nested bubblewrap; the provider has empty
Linux capability sets, no-new-privs and the keyring seccomp filter. The shipped
[AppArmor bubblewrap profile](https://gitlab.com/apparmor/apparmor/-/blob/master/profiles/apparmor/profiles/extras/bwrap-userns-restrict)
places children under an explicit capability denial. An allow added to that denying profile
cannot repair this.

The runtime candidate supplies fixed read-only executable paths to a native ELF Codex
workspace-write review seat with its checked, disposable staged tree. Its Python keyring
and descriptor-closer links use `/run/phase-loop-seat/codex-owner`. The provider stays at
`/run/phase-loop-seat/codex-runtime/bin/codex`. The seat's PATH starts with a read-only system
bubblewrap at `/run/phase-loop-seat/codex-sandbox-bin/bwrap`.
[Codex 0.162.1 discovers system bubblewrap through PATH](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/linux-sandbox/src/launcher.rs).
No sandbox flag, UID mapping, outer capability drop, egress rule, credential, output grant,
or staged-tree write boundary changes. Read-only, admin, script and unknown-layout routes
keep their existing launch paths. The existing no-inference probe still decides whether
the seat can run tools; a failed launcher remains DEGRADED before inference.

The candidate adds two named profiles, without attachment paths, and three specific stacked
exec transitions in the shipped profile's local include. The owner profile permits no
capabilities. Only the inner bubblewrap setup profile permits `sys_admin`, `sys_chroot`,
`net_admin`, `setuid`, `setgid` and `sys_ptrace`, the six capabilities in
[bubblewrap 0.11.1's setup set](https://github.com/containers/bubblewrap/blob/v0.11.1/bubblewrap.c).
Linux must continue to deny them over the ancestor egress namespace. Every exec from setup
adds `unpriv_bwrap`, including
[Codex's final seccomp stage](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/linux-sandbox/src/linux_run_main.rs),
which explicitly checks empty effective/permitted sets before running the payload.

The paths identify the runtime's route, not the identity of an arbitrary binary. An operator
able to construct a different bubblewrap view can reproduce them. This host-wide exception
therefore permits additional nested-user-namespace setup through those paths; it is not an
authentication mechanism. The actual seat sees immutable trusted binds at them, and its
model's ordinary commands must receive the denying profile. This exposure must be accepted
explicitly before installation; do not describe the exception as exclusive to this runtime.

No-new-privs is preserved. Linux 7.0's
[AppArmor domain code](https://github.com/torvalds/linux/blob/v7.0/security/apparmor/domain.c)
checks transitions against the label saved when no-new-privs is first observed, not a
Python set intersection of the immediately preceding profiles. The candidate depends on
the first saved label being `bwrap` and on all three specific transitions being selected
in each stacked component. Compilation does not prove this: actual labels and denials
must be measured during a separately approved trial. Failure must not trigger a broader
grant, removal of no-new-privs, inner-sandbox bypass or a reviewer substitution.

## Review and offline checks

Print the policy and scripts from the exact candidate runtime:

```sh
python -m phase_loop_runtime.seat_jail_apparmor --codex --profile
python -m phase_loop_runtime.seat_jail_apparmor --codex --local
python -m phase_loop_runtime.seat_jail_apparmor --codex
python -m phase_loop_runtime.seat_jail_apparmor --codex --revert
```

These commands only print. Compile the policy and a private copy of the shipped profile
with the candidate local block, using `apparmor_parser -Q -T` (skip kernel load/cache).
Scratch installer/reverter tests use a fake parser. Existing Claude policy and administrator
rules must survive repeated install/revert. A conflicting policy file, local block or
symlink must refuse before writes or loads. Runtime tests use synthetic credentials and a
copied system Python image to exercise the real owner: all capability sets remain empty,
no-new-privs is 1, seccomp is enabled, and keyctl is denied. These checks do not establish
that the new AppArmor transitions work or confine payloads under the installed candidate.

## Separately approved trial and rollback

Before requesting installation, retain the candidate commit, runtime source and generated
policy/script hashes, compile receipts, test receipts and independent review findings.
Keep the PR in draft while the required board is incomplete.

After approval, coordinate with the host administrator and retain exact backups plus
original presence/modes of `/etc/apparmor.d/local/bwrap-userns-restrict` and
`/etc/apparmor.d/phase-loop-codex-nesting`. Existing different candidate files are refused
rather than overwritten. Review the generated scripts before running them as root. Only
that profile file and the marked local block are owned by this trial. No sysctl, shipped
profile, Claude exception or other user files are to be changed.

Use the private candidate runtime first for no-inference probes, not a model review:

1. Run `true` through the exact owned Codex workspace sandbox with the checked staged tree.
   Record executable identity, labels and empty parent capability sets without credentials.
2. Read a fresh staged sentinel and write inside that tree. Attempts to alter sibling output,
   host checkout and protected files must fail. Capture only sentinel/permission metadata.
3. Verify command payloads include the denying profile, have empty capability sets and
   no-new-privs, cannot acquire parent capabilities, change the egress firewall, join the
   operator's keyring, or retain setup rights by re-executing an alias. Use local controlled
   falsifiers; do not contact `ai` or a model provider for these checks.
4. Verify ordinary bubblewrap and the Claude UID-drop route retain their prior confinement.
   Run a required live review board only after the no-inference qualification passes;
   retain full seat coverage and a president. Claude's separate agent-harness#1461 failure
   remains a blocker until independently repaired and qualified.

On any failure, stop only trial-owned processes by PID. Run the reviewed Codex revert
script as root, confirm the local block is absent, the candidate profiles are unloaded,
the retained administrator and Claude policy bytes match, and baseline denials recur.
The revert script must return failure if reload/unload fails; investigate and restore the
retained exact backups rather than reporting rollback complete. Do not keep adding grants
to an installed trial. Successful qualification is evidence for a reviewed deployment
decision, not permission to install the runtime fleet-wide or merge a PR.
