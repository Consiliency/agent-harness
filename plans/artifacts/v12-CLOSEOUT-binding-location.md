# v12 CLOSEOUT: location of the production launch binding

Frozen input for `plans/phase-plan-v12-CLOSEOUT.md`, sealed by the manifest
amendment row `v12-CLOSEOUT-amend-binding-location`. It resolves one gap that the
CLOSEOUT build reported at preflight, and adds no other change.

## Gap

`plans/artifacts/v12-CLOSEOUT-inputs.md:369` requires that the "Production CLI
always selects the installed v2 binding from trusted operator configuration".
The landed loader, `supervised_launch_binding.load_validator_binding(path, ...)`,
takes an explicit path and refuses `binding_unavailable` when it is `None`. The
landed `supervised_worker_cli._production_codec()` is a pathless stub. Neither
frozen artifact said where the trusted operator configuration lives.

## Decision (coordinator, 2026-11-09, revised after the build's ownership check)

The landed loader is written for **operator-owned** configuration. `LaunchConfig`
describes "operator-owned config", and `load_validator_binding` reads the binding
and every file it references through `trusted_bytes`. With its default
`operator_owned=True`, that check accepts only the current uid as the final
file's owner (`supervised_launch.py:133`). A root-owned record therefore cannot
satisfy it. The binding is an operator record, not a root-managed one.

1. `supervised_launch_binding.MANAGED_BINDING` resolves to
   `<home>/.local/state/phase-loop/supervised-launch-binding.json`, where
   `<home>` is the operator's home directory from the password database
   (`pwd.getpwuid(os.getuid()).pw_dir`). It is the only path the production CLI
   passes to `load_validator_binding`.
2. Nothing else can select a different binding: no argv flag, environment
   variable (`HOME`, `XDG_STATE_HOME` and `XDG_CONFIG_HOME` included),
   controller document, config file or working-directory lookup. The CLI never
   discovers a binding.
3. The file and everything it references are read through the existing,
   unchanged `trusted_bytes` checks:
   - the final file is owned by the operator;
   - no path component is group- or other-writable;
   - every directory is owned by root or the operator;
   - nothing is followed through a symlink, and the file has a single link;
   - the excluded roots are honoured.
   
   No reader is weakened.
4. If the file is absent or fails a check, the result is the existing refusal
   (`binding_unavailable`, or the trusted-read refusal), and nothing runs. That
   is today's production behaviour, so the CLI keeps refusing until the operator
   installs the record.
5. Tests reach a binding only through the existing in-process seam (the
   keyword-only test parameters). No test writes into the real home directory.
6. Provisioning the record on hosts is deployment work outside CLOSEOUT, and
   EC-CLOSEOUT acceptance stays as the plan states.
