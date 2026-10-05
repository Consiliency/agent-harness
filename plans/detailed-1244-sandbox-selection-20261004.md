---
status: planned
issue: agent-harness#1244
role: sandbox selection evidence and the ruled PR-B inputs (S1-S4); referenced by plans/detailed-1244-seat-route-resolver-20261004.md
---

# agent-harness#1244: sandbox selection (evidence) and PR-B inputs

## Sandbox selection

Each claim below was checked against the project's own README, source or registry on
2026-10-04 by a research pass. Cells marked "unverified" were not confirmed against primary
docs.

| Candidate | Linux | macOS | Windows | Unprivileged | FS allowlist | Egress domain allowlist | Wraps any CLI | License | Health | Install |
|---|---|---|---|---|---|---|---|---|---|---|
| **sandbox-runtime `srt`** ([anthropics/sandbox-runtime](https://github.com/anthropics/sandbox-runtime)) | bubblewrap + seccomp | Seatbelt | **alpha**: a dedicated sandbox account, WFP filters and a restricted token | yes; Windows needs one elevated install | yes (allow/deny read and write) | **yes**: built-in HTTP and SOCKS5 proxies with allowed/denied domains, deny by default | yes (`srt <cmd>`) | Apache-2.0 | npm 0.0.78, 2026-09-30; active | `npm i -g`; Linux also needs bwrap, socat and ripgrep |
| Codex CLI sandbox ([openai/codex](https://github.com/openai/codex)) | bubblewrap | Seatbelt | native (sandbox users, WFP, restricted token) | Windows elevated mode needs admin | yes | yes (`network-proxy`) | `codex sandbox <cmd>` | Apache-2.0 | active | **ships inside one vendor's CLI** |
| bubblewrap | yes | no | no | yes | yes | **no** (no network or loopback only) | yes | LGPL-2.1 | v0.13.0 | distro package |
| nsjail / firejail | yes | no | no | nsjail unverified; firejail is SUID (**no**) | yes | no | yes | Apache-2.0 / GPL-2.0 | active | build or package |
| Podman / Docker rootless | yes | via a VM | via WSL2 or a VM | yes, rootless (unverified) | mounts | not built in (unverified) | inside an image | Apache-2.0 | active | **high** (images, plus a VM on macOS and Windows) |
| Apple `container`, Lima/colima | via the host | macOS 26 on Apple silicon / yes | no | unverified | mounts | unverified | inside a VM | Apache-2.0 / MIT | active | medium |
| gVisor, Kata, Firecracker | Linux; Kata and Firecracker need KVM | no | no | gVisor `--rootless`; others need `/dev/kvm` | yes | no | as an OCI image | Apache-2.0 | active | medium to high |
| microsandbox ([superradcompany/microsandbox](https://github.com/superradcompany/microsandbox)) | KVM | Apple silicon | yes (WHP) | unverified | VM | yes (`allowed_hosts`) | `msb run <image> -- <cmd>` | Apache-2.0 | active | medium (microVM plus image) |
| E2B runtime (self-host) | Linux + KVM | no | no | unverified | yes | yes (nftables plus SNI/Host) | yes | Apache-2.0 | active | high; already planned as agent-harness#896 cloud (agent-harness#1165) |
| Daytona | — | — | — | — | — | — | — | unclear | **repository archived 2026-10-03** | out |

**Ruled (S1–S3, 2026-10-04): `srt` is the adopted local sandbox, introduced OS by OS.** It is
the only maintained, standalone and harness-neutral candidate that covers Linux, macOS and
Windows without a container or VM, and that has both a filesystem allowlist and a domain
egress allowlist. Codex's sandbox is equivalent, but it ships inside one vendor's CLI.
bubblewrap, nsjail, gVisor, Kata and Firecracker have no domain allowlist and run only on
Linux. Containers and VMs carry the most install friction.

| OS | Step 1, local sandbox | Rule |
|---|---|---|
| **macOS** | **srt first** (Seatbelt) | S1. Where srt is unusable, go to step 2. |
| **Linux** | **agent-harness#1166's jail stays** until srt passes the Linux conformance suite below; then srt replaces it | S1 |
| **Windows** | **none yet**: seats go to step 2 (tailnet/LAN via #896 plan 3, or E2B). There is no Windows-specific sandbox work. Revisit srt when its Windows support leaves alpha. | S2 |
| Linux without user namespaces (e.g. Ubuntu 24.04+ with `apparmor_restrict_unprivileged_userns=1`) | none: step 2, with the sysctl named as the fix | — |

**Linux conformance suite (S1, a gate in PR-B).** srt must pass this suite before it replaces
the jail. The suite runs the same probes against both #1166's jail and srt, and srt must
match the jail on every row:
- **Capability bounding.** CapBnd is 0 inside the seat, carrying over #1166's invariant and
  its codex exception unchanged.
- **Private home.** The seat sees a private `$HOME`, not the host's, and no host
  credential store is readable.
- **Egress allowlist.** Only the allowlisted hosts answer, measured with real replies.
- **fd hygiene.** No inherited host fds beyond stdio and the declared channels.
- **uid isolation.** The seat runs under its own uid or namespace mapping, and it cannot
  signal or ptrace host processes.
- **No host-path leaks.** Only the staged tree and declared paths are visible. Host paths
  are absent from the environment, `/proc/self/mounts` and error text.

Each row has a mutation that turns it red, such as removing a bind-mount restriction or
widening the allowlist.

**Egress: srt's proxy for every seat that needs network (ruled S3; supersedes
agent-harness#1170).** srt's proxy is deny-by-default, with a domain allowlist and a refusal of
loopback and metadata addresses. It is the egress layer for every networked seat, including
a tooled Gemini seat. agent-harness#1170 is superseded, and PR-B closes it with a link. srt's
proxy is checked against what #1170 required:
- **(a)** only a short-lived access token enters the sandbox. This holds already on
  #1166's evidence and is re-checked under srt.
- **(b)** a containment probe with real replies: the agy inference host is reachable, and
  every other Google API host on the same front-end addresses is refused. This includes a
  request that tunnels through an allowed host but names another host inside TLS (SNI or
  Host).
- A mutation that widens the allowlist, or allows direct egress, turns the probe red.
- The proxy runs outside the seat, holds no credentials, and the seat cannot reconfigure it.
- The allowlist is measured from agy's real traffic, pinned as config, and not specific to
  the fleet.

**Ruled S4:** suppose (b)'s inner-host row shows that srt's plain CONNECT proxy cannot
block a request that tunnels through an allowed host but names another host inside TLS. Then
the tooled Gemini seat uses **srt's TLS-terminating proxy**. It does not fall back to a
remote-only Gemini. The requirements:
- **Interception CA:**
  - generated per host and owner-only: the key file is 0600 and its directory 0700;
  - trusted **only inside the seat's sandbox**, through the sandbox's own trust bundle or
    env, and never added to the host trust store.
- **The CA private key never enters the sandbox.** Only the CA certificate is mounted.
- **Inner check:** the proxy verifies the inner Host and SNI against the allowlist, and
  refuses on a mismatch.
- **Probe (b) passes with inspection on:** the allowed host is reachable, and a different
  Google API host is refused, with real replies.
- **Evidence:** the seat's evidence records `egress.tls_inspection: true|false`.

Each requirement has a mutation that turns it red:
- trusting the CA in the host store;
- mounting the key;
- skipping the inner-host check;
- dropping the evidence field.

