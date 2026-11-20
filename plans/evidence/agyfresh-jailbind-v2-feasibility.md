# AGYFRESH HOLD amendment SL-7 (JAILPROBE2): staged-copy feasibility

Result of lane SL-7 of `plans/amendments/agyroll-HOLD-jailbind-v2.md`: the checks V1–V9 and the
decision rule of `plans/artifacts/agyfresh-jailbind-v2.md` §6 (v2 contract, r3). It decides
whether the staged-copy design works in the standalone Gemini jail, and whether the
unprivileged harness can observe the provider's executing image after the seat-uid drop
(§4.4: "observed" or "custody only").

Redaction posture: metadata only. No agy, no network call, no credential and no provider call
were used, and there is no production change. The probe cases are
`phase-loop-runtime/tests/test_agy_hold_jail.py` on the lane's scratch branch. That file is not
merged by SL-7; SL-3 takes it over.

## Outcome: recommend GO, observed

V1, V2, V3, V6 and V7 hold, V4 holds and V5 holds. Under the §6 decision rule the report
recommends GO with the runtime check ("observed").

One V5(b) outcome falls outside the two that V5(b) lists, and is recorded here for the
coordinator. A provider that execs a distinct file at once was sampled on the staged image
before the exec. In every final run the exec'd file had then exited before the end-of-leg
sample, so the start passed by the first row of §4.3. This is the limit §4.1 states ("it does
not show ... what a process did between samples"). Every decision equals the one §4.3
assigns to the samples taken, and no output was used before the decision. Whenever an exec'd
file was still alive at a sample, the start was a mismatch. If V5(b)'s list is read as
exhaustive, V5 does not hold, and the rule gives STOP.

**Coordinator ruling: V5 holds; the outcome is GO, observed.** V5(b)'s two named outcomes are
read as the outcomes expected, not as an exhaustive list. The outcome recorded above is the
sampling limit §4.1 already states, and the v2 contract treats the runtime check as a
fail-closed integrity backstop on top of custody of the staged file, not as attestation of
everything a process executes. Every recorded decision is the one §4.3 assigns to the samples
taken, and no output was used before the decision. SL-3 keeps the observer's ordered launch-chain
rule (see "Notes for SL-3" below).

**V8:** hosted CI can launch a seat jail. On `ubuntu-24.04` the D8 prerequisites are present,
and the live D8 jail cases execute and pass on `main` (run 44812999409: 18 passed, no
prerequisite skip).

## How the probes run

Each launch goes through the real owner launch chain. The jail is built by the unmodified
`seat_jail.build_seat_jail`, through `panel_invoker._build_jail_with_owned_inputs`, as
`_prepare_jailed_gemini` builds it, with the staged spelling as the provider executable. The
launch prefix is `panel_invoker._compose_seat_jail_prefix`: the keyring shim, `nsenter` into the
seat-uid holder, the hand-off, bwrap, `setpriv_drop`, `seat_cwd`, `seat_fd_closer` and the
provider. The holder is the proxy-only namespace the jailed Gemini route uses. Its bridge
answers a local stub that refuses every request, so the holder has no uplink and makes no name
lookup.

The staging rules, the root and launch locks, the sweep, the observer and the start gate are a
test-local prototype of v2 contract §2.2–§2.4 and §4.2–§4.3. The provider is the conformance
stand-in (`tests/fixtures/agy_conformance/standin.c`, mode 0) or a small static variant of it.
The observer is the test process itself: uid 1000, unconfined, every capability set empty. No
privilege was added.

## Checks (V1–V9)

| # | Check | Result | Observed |
|---|---|---|---|
| V1 | Name and mount | **holds** | See "V1 detail" below. The no-follow walk of `<home>/.local/state/phase-loop/seat-images/<random>/gemini` passes. At bwrap's position the spelling resolves to itself, and the pinned directory and inode are the ones seen. Inside the jail `/seat/bin/gemini` is a read-only bind of that inode. |
| V2 | Binds by that spelling; the stand-in executes as the seat uid in both jails | **holds** | Both jails carry the identical token `--ro-bind <spelling> /seat/bin/gemini`, and `provider_path` equals the spelling in both. The production identity probe (J6/J15) passes on the probe-shaped jail. In both jails `id -u` is the leased seat id, `--help` prints the stand-in's usage, and a gated start returns its `SUCCESS` result. |
| V3 | Actual equals canonical; every leg's digest and the launch key unchanged | **holds** | See the digest comparison below. |
| V4 | Unprivileged observer after the seat-uid drop | **holds** | The slot is identified and a `pidfd` is held. `/proc/<pid>/exe` opens, its identity is the pinned inode and its hash is the admitted digest, in every matched start (45 across both interpreters). See "The observer" below. |
| V5 | Decisions through the chain | **holds** (one outcome recorded, above) | See the V5 table below. |
| V6 | The seat cannot write or see the staging; a subordinate uid cannot open it on the host | **holds** | Inside the jail, as the seat uid: a write to `/seat/bin/gemini` is refused (mount `ro,nosuid,nodev,relatime`). The stand-in's descriptors are `0 1 2`, the declared set. Its running image hashes to the admitted digest. The staged file, the per-launch directory, `seat-images/`, `phase-loop/` and the stand-in source are not visible. On the host, a process at the seat's subordinate uid (`nsenter -U` into the holder, then `setpriv_drop`) gets `EACCES` for opening and stat-ing the staged name and for listing the per-launch directory and `seat-images/`. This holds in the host's mount namespace and in the holder's. |
| V7 | Lifetime, cleanup and locks | **holds** | After two starts of the production jail and one of the probe jail, the name's inode is still the pinned inode. The pinned inode re-hashes to the admitted digest, the re-check passes, and the per-launch directory holds only the staged file. During each start, 2 mountinfo lines (the jail's processes) name the entry. After the leg the entry is gone, and none of the 798–850 readable mountinfo tables names it. An entry whose launch lock was held survived another staging's sweep. An entry whose lock was free, a crashed launch, was removed by the next staging's sweep, which kept both held entries. |
| V8 | Hosted CI can launch a seat jail | **fact: yes** | See "V8 detail" below. |
| V9 | Data | recorded | See "V9 detail" below. |

**V1 detail.** The walk opens every component with `O_DIRECTORY|O_NOFOLLOW`. `/` and `/home`
are root-owned and 0755; the rest are operator-owned: home 0700, `.local` and `state` 0755,
`phase-loop`, `seat-images` and the per-launch directory 0700. No component is group- or
other-writable, and none carries a named-user or named-group ACL entry. The group of each
operator-owned component is the operator's user-private group.

The spelling was also examined from inside the real chain, at the point bwrap runs: as H-root,
in the holder's user and mount namespaces, after the hand-off. There `realpath` of the spelling
is the spelling and no component is a symlink. The per-launch directory and the file have the
pinned `(st_dev, st_ino)`. The covering mount is the root filesystem (ext4 on `252:1`,
`rw,relatime`).

Inside the jail, the mountinfo entry for `/seat/bin/gemini` has that filesystem, the root
`<spelling>` and the options `ro,nosuid,nodev,relatime`, and the file is the pinned inode at
0555. The staging filesystem is ext4, not `noexec`, with about 61 GB free.

The alias: `<home>/code` is a bind mount, not a symlink. It is mount 225, root
`/users/<operator>/code` of the workspace ext4 volume `252:2`, `rw,nosuid,nodev,relatime`.
`<home>/workspace` is a symlink to the workspace volume. The staging spelling traverses
neither: every component is on the root filesystem (mount 51).

As data, a staging root spelled through `<home>/code` walks through the mount point (it is not
a symlink) and binds the same inode on `252:2`.

**V8 detail.** The `pytest (py3.12)` and `clean-room (Gate A)` jobs run on `ubuntu-24.04`
(`.github/workflows/test.yml`). They install `bubblewrap slirp4netns iptables util-linux` and
set `kernel.apparmor_restrict_unprivileged_userns=0`. The subordinate ids and uid-map helpers
come from the runner image; `phase-loop doctor` reports them present.

In run 44812999409 on `main`, `tests/test_seat_jail_live_d8.py` had 18 cases passed (among them
`test_j6_live_identity_probe_passes_through_the_production_prefix`) and 1 skipped for a
missing Claude credential. No skip in that run names a D8 prerequisite. Under §7, tier 2 is
therefore also required in hosted CI.

Not covered by this answer: the seat egress layer is not usable there (`tests/test_gemini_seat_egress_1170.py` skips with "the seat egress layer is not installed here").
Whether the image has `socat`, which the proxy-only holder used here needs, was not checked.

**V9 detail.** `$XDG_RUNTIME_DIR` is a tmpfs: `rw,nosuid,nodev,relatime`, `size=3141604k`
(3.0 GiB), mode 700, not `noexec`.

The kernel supports fs-verity for ext4 (`/sys/fs/ext4/features/verity` exists). On the state
filesystem, `FS_IOC_ENABLE_VERITY` returns `EOPNOTSUPP`, because the filesystem's verity
feature is not enabled.

The observer can stat `/proc/<pid>/root/seat/bin/gemini`, and it is the pinned inode.

## The observer (V4)

**Process shape.** The launch process execs, in place, through the keyring shim, `nsenter` and
the hand-off into bwrap. bwrap's only child is its namespace init (NSpid 1, H-root). The init's
first child is the command child (NSpid 2): the provider slot.

The slot's executable then moves through bwrap, `setpriv`, `env` and `python3` (the descriptor
closer), and then the staged inode. On this host `/usr/bin/env` is one of 116 hard links of a
multicall coreutils binary; `/usr/bin/sleep` is another.

**Identity.** The slot is identified structurally: the launch process, once it is bwrap; its
only child; that child's first child. Its identity is a `pidfd` plus the start time from
`/proc/<pid>/stat`. Both are re-checked after every open of `/proc/<pid>/exe`, so a pid reused
in between is never accepted.

**What was in force.**

| | Observer | Provider slot |
|---|---|---|
| uid | 1000, initial user namespace | 100000 (seat 1) |
| user namespace | initial | the holder's, owned by the operator; map `0 1000 1`, `1 100000 256` |
| capabilities | `CapEff` 0 | `CapEff` 0, `NoNewPrivs` 1, `Seccomp` 2 |
| LSM label | unconfined | `bwrap//&unpriv_bwrap (enforce)` |

- `kernel.yama.ptrace_scope` is 1 and `fs.suid_dumpable` is 2.
- `/proc` is mounted with no `hidepid` and no `subset`.
- LSMs: `lockdown,capability,landlock,yama,apparmor,bpf,ima,evm`.
- `kernel.apparmor_restrict_unprivileged_userns` is 0.

**Timings.**

- **Spawn to first match:** 128–479 ms over 45 matched starts. The median was 188 ms on Python
  3.12 and 167 ms on 3.14.
- **Spawn to slot identified:** at most 422 ms.
- **The 16,504-byte stand-in:** the observer hashes it in under 0.1 ms.
- **A full-size image** (the stand-in padded to `MAX_MEMBER_BYTES`, 512,000,000 bytes),
  Python 3.12 / 3.14:

  | Step | 3.12 | 3.14 |
  |---|---|---|
  | Observer's hash through `/proc/<pid>/exe` | 371 ms | 242 ms |
  | Staging: write | 2.7 s | 0.74 s |
  | Staging: verify | 0.40 s | 0.28 s |
  | `VerifiedImage.from_fd` | 0.71 s | 0.83 s |

  The peak traced Python allocation while staging was 1.03 MiB, within the caps lane's
  2 MiB `OVERHEAD_CEILING`.

The probes used a 10 s bound. SL-3 fixes the production bound.

## Decisions (V5)

Final runs, Python 3.12.14 and 3.14.10. Every refusal tore the jail tree down. The launch was
reaped, every descendant seen before the kill exited, and no process was left in the slot's pid
namespace or running as the seat's host uid. No refused start released its stream. For (c)
the jail's `seat-out` directory was also checked: it was removed with the seat directories.

| Case | Starts | Decisions (3.12 / 3.14) |
|---|---|---|
| (a) a stand-in that exits at once | 8 | last row with custody intact, pass: 6 / 6; first row (sampled before the exit), pass: 2 / 2 |
| (b) execs a distinct file at once (`/bin/sh`, which exits when its stdin closes) | 3 | first row, pass: 3 / 3; the exec happened after the first match and the file had exited before the end-of-leg sample. In an iteration run of the same case, 2 of 3 were sampled at `/bin/sh` while it was alive (mismatch, refuse) and 1 of 3 as here. |
| (b) execs `/usr/bin/sleep 30` at once (shares `env`'s inode) | 3 | mismatch, refuse: 3 / 3; at the end-of-leg sample, or as a step back in the chain order |
| (b) the same, with the chain read as an unordered set | 1 | mismatch at the end-of-leg sample, refuse: 1 / 1 |
| (b) forks and exits at once | 5 | first row, pass: 5 / 2; last row with custody intact, pass: 0 / 3 |
| (c) staged file renamed over by a wrong image after the last re-check | 1 | mismatch (inode), refuse: 1 / 1. On 3.12 the wrong image's output was withheld (19 bytes) and not used; on 3.14 the start was refused before it wrote. |
| (c) staged inode rewritten in place by a wrong image | 1 | mismatch (digest at the first matching sample), refuse: 1 / 1; output withheld and not used |
| (d) the provider position stays in a chain executable (`python3`), 2 s bound | 1 | alive at the bound with neither, refuse: 1 / 1 |
| (d) the stand-in with a 0.02 s bound | 1 | alive at the bound with neither (the slot had not appeared yet), refuse: 1 / 1 |

**Chain order.** The prototype observer reads the chain's executables in their fixed order: a
step back to an earlier one is a mismatch. This is needed on this host, because the exec'd
`sleep` is the same inode as the chain's `env`.

In an earlier iteration run that read the chain as an unordered set, the same case was refused
3 of 3 times as "alive at the bound with neither", never as a mismatch. Both readings refuse it
while it is alive. Under the unordered reading, such a file exiting before the bound would
reach the last row instead.

## Digest comparison (V3)

Host arch x86_64. The base tree is `origin/main` at `0308fa2af`, the scratch branch's base.
`git diff --quiet 0308fa2af -- phase-loop-runtime/src` exits 0: no production change.

| Value | Digest |
|---|---|
| canonical Gemini, `jail_profile_digest("gemini")` | `09827a0ed4f51ac2bfac6510e9d0f5b111abcf33a66638046e67ebdca2d097c2` |
| actual, staged-image production-shaped jail, unmodified `actual_profile_digest` | `09827a0ed4f51ac2bfac6510e9d0f5b111abcf33a66638046e67ebdca2d097c2` |
| actual, staged-image probe-shaped jail | `09827a0ed4f51ac2bfac6510e9d0f5b111abcf33a66638046e67ebdca2d097c2` |
| `key_for_launch(gemini).profile_digest` | `09827a0ed4f51ac2bfac6510e9d0f5b111abcf33a66638046e67ebdca2d097c2` |

`_require_canonical_jail` accepts both jails. The launch key is equal, field for field, to the
one computed from a pristine export of the base tree by a separate interpreter.

Every registered leg's canonical digest was taken before and after building the staged-image
jails, and from that base-tree export:

| Leg | This branch (before = after) | Base tree export |
|---|---|---|
| claude | `5ccd7e8669f41716754787d8bde9bb6a64450774e2c5bf9b8862d7e0acaa2b00` | equal |
| codex | `d905feb08208bce2ae6fcaad0f78083ab86ce463b8dfc031e9dd8265e8f5e488` | equal |
| gemini | `09827a0ed4f51ac2bfac6510e9d0f5b111abcf33a66638046e67ebdca2d097c2` | equal |

These equal the values `plans/evidence/agyfresh-jailbind-feasibility.md` records.

## Runs

- **Host:** dev0, local only, after a headroom check before each run. `ai` and other hosts were
  not used.
- **Platform:** Ubuntu 26.04.1 LTS, kernel `7.0.0-43-generic`, x86_64, bubblewrap 0.11.1.
  `kernel.apparmor_restrict_unprivileged_userns = 0`; uidmap is installed, and the operator
  has a subordinate range.
- **Command:**
  `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 PYTHONPATH=src:tests timeout 600 .venv/bin/python -m pytest -v -p no:cacheprovider tests/test_agy_hold_jail.py -k probe`.
  The run was serial: pytest-xdist is not installed.
- **Python 3.12.14:** 13 passed in 71 s.
- **Python 3.14.10**, in a separate locked environment: 13 passed in 70 s.
- **Not part of the chain observed here:** the per-seat caps scope. As in SL-1, the suite's
  autouse fixture stands in for `seat_resource_caps.capped_popen` with a plain spawn, so the
  `systemd-run --scope` wrapper that production puts around the prefix was not observed with
  the observer.
- **Cleanup**, verified after each final run:
  - `seat-images/` did not exist before the runs, and it is removed again.
  - No process runs in the operator's subordinate uid range.
  - No readable mountinfo names `seat-images` or the probe directories.
  - No file under the run's temporary directories is owned by another uid.
  - The alias-spelling scratch directory and the stub socket directories are gone.
- **Raw records** are kept outside the repository, in the coordinator's engagement directory
  (`sl7-jailprobe2/`). They hold:
  - per-case JSON lines (`HOLD_JAILPROBE2_RECORD`) for both interpreters and for the
    iteration runs;
  - pytest output and JUnit;
  - the headroom gate output;
  - the cleanup proofs.

## Notes for SL-3

- Keep the observer's ordered launch-chain rule (bwrap, then setpriv, then env, then python3,
  then the staged inode). A set-membership reading misclassifies a provider that execs a file
  sharing an inode with a chain executable, such as a multicall coreutils binary (see the V5
  table above).
- These probes replaced the per-seat caps wrapper with a plain spawn, through the test fixture.
  SL-3's tier 2 confirms that the observer identifies the provider slot the same way under the
  real caps wrapper.
- Whether the hosted runner image provides `socat`, which the proxy-only holder needs, is
  unchecked; SL-3's CI tiers decide whether that matters.
