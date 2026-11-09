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

## Decision (coordinator, 2026-11-09)

The repository's managed operator records follow one convention: a fixed,
root-owned path under `/etc/consiliency/tooling/`, installed by the root release
updater and read with trusted-file checks. Examples are
`seat_resource_caps.MANAGED_RECORD` (`seat-resource-caps.json`) and
`seat_subject.MANAGED_AUTHORITY_PIN` (`seat-authority.json`). The production
launch binding follows the same convention.

1. `supervised_launch_binding.MANAGED_BINDING = Path("/etc/consiliency/tooling/supervised-launch-binding.json")`
   is the only path the production CLI passes to `load_validator_binding`.
2. Nothing else can select a different binding: no argv flag, environment
   variable, controller document, config file or working-directory lookup.
   The CLI never discovers a binding.
3. The file is read through the existing `trusted_bytes` checks (ownership,
   mode, no-follow, excluded roots), exactly as `load_validator_binding` already
   does for every path it reads.
4. If the file is absent or fails a check, the result is the existing refusal
   (`binding_unavailable`, or the trusted-read refusal), and nothing runs. That
   is today's production behaviour, so the CLI keeps refusing until an operator
   installs the record.
5. Tests reach a binding only through the existing in-process seam (the
   keyword-only test parameters). No test writes under `/etc`.
6. Installing the record on hosts is deployment work for the root release
   updater (Consiliency/dotfiles). It is not part of CLOSEOUT, and EC-CLOSEOUT
   acceptance stays as the plan states.
