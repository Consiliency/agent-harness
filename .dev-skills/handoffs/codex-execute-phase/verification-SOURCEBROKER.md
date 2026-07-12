# Verification: SOURCEBROKER

Summary: PASSED locally at `086b73feb2c1d00c7d5758d6097b3d430ab78b88`
— focused broker/resolver suite 89 passed, 1 skipped; standalone Gate A 2,407
passed, 35 skipped, 597 deselected. Git diff checks passed. The 0.7.1 sdist and
wheel build passed, roadmap validation reported seven phases, and the plan-phase
validator reported three lanes against the exact amended roadmap hash. Its one
release-shape heuristic warning is non-applicable: this plan explicitly
dispatches no tag, release, or workflow. All seven GitHub checks on
ViperJuice/agent-harness#180 passed at the same exact head.

- Redaction posture: metadata only.
- Permanent live deployment: deferred until the corrected Agent Harness PR
  merges; no broker listener, environment, `/opt` venv, or Tailscale route was
  created by these gates.
- System-unit boundary: disposable claw root-manager transients ran as
  `viperjuice:viperjuice` with zero permitted/effective/ambient capabilities and
  `NoNewPrivileges=1`.
- Mount confinement: `ProtectHome=tmpfs` created a distinct mount namespace;
  only the exact owner socket was rebound read-only with host-matching device
  and inode. Adjacent Codex and unrelated home content were hidden.
- Runtime compatibility: Python thread start/join, exact owner-socket connect,
  `PrivateDevices`, `ProtectKernelModules`, and deny-all/allow-localhost IP
  policy passed together. `MemoryDenyWriteExecute` is omitted because an
  isolated trace proved it denied the Python 3.13/glibc executable thread-stack
  `mprotect` with `EPERM`.
- Procfs confinement: a same-UID control proved both hidden-home escape paths
  readable through `/proc/<pid>/root`. All supported `ProtectProc` modes remained
  insufficient. `InaccessiblePaths=/proc` removed both escape paths while the
  thread, socket-connect, capability, and no-new-privileges checks still passed.
- User-manager rejection: claw systemd 249 accepted but did not enforce the
  former user-unit mount controls (`PrivateMounts=no`), so the deployment
  artifact is now a root-managed system unit with a root-owned immutable `/opt`
  venv and root-owned digest-only `/etc` environment.
- Privileged provisioning: the operator procedure requires the `/opt`
  destination to be absent inside one root-owned `sh -eu` transaction, uses
  root-owned `/usr/bin/python3` and the resulting root-owned venv Python with
  isolated mode (`-I`), changes to trusted `/`, and starts from an empty
  environment with trusted root home/PATH and pip config disabled. The SHA is
  passed as one positional argument and validated as exactly 40 lowercase hex
  characters before pip can execute build code. System Python reports
  `ensurepip` available and `/usr/bin/env` supports the required `-C`
  working-directory boundary.
- Review status: prior Grok/Gemini findings and Sol's same-UID procfs,
  deploy-v2/bootstrap-v3 compatibility, duplicate-key JSON, and untyped-version
  findings are remediated. Exact final-head four-seat re-review remains required
  before merge; an unavailable seat is not agreement.
