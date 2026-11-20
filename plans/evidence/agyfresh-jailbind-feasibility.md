# AGYFRESH HOLD SL-1 (JAILPROBE): sealed-image jail feasibility

Result of lane SL-1 of `plans/phase-plan-v1-agyroll-HOLD.md`, the check list in
`plans/artifacts/agyfresh-hold-lanes.md` §D. It decides whether the one mount form admitted by
`plans/artifacts/agyfresh-hold-amendment.md` §2.8 (AGYFRESH §2.11) works in the standalone
Gemini jail. That form is `--ro-bind /proc/self/fd/<fd> /seat/bin/gemini`, where `<fd>` is a
sealed memfd from `VerifiedImage.from_fd`.

Redaction posture: metadata only. No agy, no network call, no credential and no provider call
were used, and there is no production change. The probe cases are
`phase-loop-runtime/tests/test_agy_hold_jail.py` on the lane's scratch branch. On a STOP
branch that file is not merged (lanes artifact §K2), and this report is what is kept.

## Decision: STOP

**P1 fails.** The other launch checks (P2, P4, P5, P7 and the after-mount half of P6) fail for
the same reason, because no jail can be built. P3 and the before-mount half of P6 hold.

Through the real owner launch chain, bubblewrap exits with status 1 before it builds the jail:

```
bwrap: Can't find source path /proc/self/fd/<fd>: No such file or directory
```

The cause is bwrap, not the kernel, the image mode or the uid drop. bubblewrap 0.11.1
canonicalizes a bind source by reading each link's text. An strace of one launch through the
real chain shows:

```
readlink("/proc/<pid>/fd/<fd>", "/memfd:agy-image (deleted)", 1023) = 26
readlink("/memfd:agy-image (deleted)", ...) = -1 ENOENT (No such file or directory)
```

A memfd has no path, so its link text names nothing, and bwrap never reaches `mount(2)` with
the descriptor. There is no second form to fall back to (amendment §2.8). Under the decision
rule (lanes artifact §D), SL-3 does not run, and the owner decides between accepting the gap
and a new amendment (§A).

## Checks (P1–P7)

Every launch ran through `panel_invoker._compose_seat_jail_prefix`, in this order: the keyring
shim, `nsenter` into the seat-uid egress holder, the hand-off, bwrap, `setpriv_drop`,
`seat_cwd`, `seat_fd_closer`, and then the provider position. The seat id came from the
`flock` lease, and the holder was mapped by the real `newuidmap`/`newgidmap`.

Each jail was built the way `_prepare_jailed_gemini` builds its jails, by the unmodified
`seat_jail.build_seat_jail` through `_build_jail_with_owned_inputs`. Its provider executable
was `/proc/self/fd/<fd>`, with `<fd>` a descriptor from `image.reopen()` that was passed in
`pass_fds`. The provider was the conformance stand-in (`tests/fixtures/agy_conformance/standin.c`,
mode 0), compiled for the run.

| # | Check | Result | Observed |
|---|---|---|---|
| P1 | bwrap mounts the form for a sealed memfd from `from_fd` | **fails** | bwrap exits 1: `Can't find source path /proc/self/fd/<fd>`; the mount is never attempted |
| P2 | the stand-in executes from the mount after the uid drop; 0500 or 0555 | **fails** (not reachable) | the same bwrap error at the image's `from_fd` mode 0500 and again after `fchmod` to 0555. Whether 0555 would be required is **not observed** |
| P3 | `actual_profile_digest(jail) == jail_profile_digest("gemini")` with the provider path `/proc/self/fd/<fd>`; every leg's canonical digest is unchanged; the launch key is unchanged | **holds** | the digest comparison table below |
| P4 | the jail's mountinfo equals `expected_mount_points(jail)` | **fails** (not reachable) | no jail; the production identity probe (J6/J15) on the probe-shaped jail refuses with `seat_sandbox_refused:identity`, because bwrap fails the same way inside it |
| P5 | read-only mount; exactly the declared descriptors (`0 1 2` for this profile); no host provider, store or vendor path visible | **fails** (not reachable) | no jail |
| P6 | two `reopen()` descriptors: one inode and the admitted digest before mounting; the same digest inside each jail | **half holds** | before mounting: the image and both descriptors have one `(st_dev, st_ino)` and hash to the image digest. After mounting: neither the production-shaped nor the probe-shaped jail is built |
| P7 | one jail launched twice executes the stand-in both times | **fails** (not reachable) | both launches stop at the same bwrap error; the image descriptor stays open in the parent across both |

**Control (not a check).** The same chain, the same Gemini jail shape and the same stand-in,
with today's path bind of the stand-in's host file. The production identity probe passes on the
probe-shaped jail. `/seat/bin/gemini --help` runs as the leased seat uid and prints the
stand-in's usage. So this host jails the seat as its uid, and the failure belongs to the form,
not to the host.

**Observation (not a check, for the owner's decision).** bwrap takes the source through the
descriptor's name, not through the descriptor. For a regular file opened and then unlinked
before the launch, the link text ends in `(deleted)` and bwrap fails with the same error.

A diagnostic was also run, which is not evidence under §D because it is hand-built bwrap
without the chain. For a regular file still in place, it showed bwrap mounting the resolved
path (`mount("/oldroot<path>", ...)`), not the descriptor. On this bwrap, then, the form is a
path bind for any descriptor that has a name, and it fails for one that has none.

**Side note on relaunching a jail.** bwrap reads the seccomp program and the bundle and
instructions data from their descriptors' shared offset. A second launch of the same jail, or
the identity probe after a launch, therefore needs those descriptors back at offset 0. Without
that rewind, the identity probe refused with `seccomp descriptor is not at offset 0`. The probe
cases rewind before each launch. This is existing behaviour, not part of the form.

## Digest comparison: Form A vs canonical (P3)

Host arch x86_64. The base tree is `origin/main` at `5c0f4a399`. This branch has no
production change; `git diff origin/main -- phase-loop-runtime/src` is empty.

| Value | Digest |
|---|---|
| canonical Gemini, `jail_profile_digest("gemini")` | `09827a0ed4f51ac2bfac6510e9d0f5b111abcf33a66638046e67ebdca2d097c2` |
| actual, Form A jail (`provider_path = /proc/self/fd/<fd>`), unmodified `actual_profile_digest` | `09827a0ed4f51ac2bfac6510e9d0f5b111abcf33a66638046e67ebdca2d097c2` |
| actual, path-bound jail (control shape) | `09827a0ed4f51ac2bfac6510e9d0f5b111abcf33a66638046e67ebdca2d097c2` |
| `key_for_launch(gemini).profile_digest`; the key is equal for both forms | `09827a0ed4f51ac2bfac6510e9d0f5b111abcf33a66638046e67ebdca2d097c2` |

The Form A argv carries the literal token `--ro-bind /proc/self/fd/<fd> /seat/bin/gemini`, and
`jail.provider_path` is the same literal. `_require_canonical_jail` accepts both jails.

Canonical digest of every registered leg, before and after building the Form A jail, and from
a pristine export of the base tree run by a separate interpreter:

| Leg | This branch (before = after) | Base tree export | Recorded receipt (`plans/evidence/seat-jailcore/digest-equality.json`, x86_64) |
|---|---|---|---|
| claude | `5ccd7e8669f41716754787d8bde9bb6a64450774e2c5bf9b8862d7e0acaa2b00` | equal | equal |
| codex | `d905feb08208bce2ae6fcaad0f78083ab86ce463b8dfc031e9dd8265e8f5e488` | equal | not in the receipt |
| gemini | `09827a0ed4f51ac2bfac6510e9d0f5b111abcf33a66638046e67ebdca2d097c2` | equal | equal |

So Form A would keep every canonical digest and the launch key as they are, as amendment §2.8
expects. The form fails only because bwrap cannot mount it (P1).

## Runs

- Host: dev0, local only, after a headroom check. `ai` and other hosts were not used.
- Ubuntu 26.04.1 LTS, kernel `7.0.0-43-generic`, x86_64.
- bubblewrap 0.11.1 at `/usr/bin/bwrap` (root-owned, mode 0755, not setuid).
- `kernel.apparmor_restrict_unprivileged_userns = 0`; the AppArmor profiles `bwrap-userns-restrict`
  and the `phase-loop-seat-jail` override are present; uidmap is installed; the operator has a
  65536-id subordinate range.
- `PYTHONPATH=src:tests timeout 600 .venv/bin/python -m pytest -v -p no:cacheprovider tests/test_agy_hold_jail.py -k probe`
  under Python 3.12.14: 3 passed (P3, the control, the observation), 6 failed (P1, P2, P4, P5,
  P6, P7).
- The same file under Python 3.14.10 (`uv run --python 3.14.10 --locked --offline`, a separate
  environment): the same 3 passed and 6 failed, with the same error.
- Cleanup was verified after the final runs. No probe or holder process remains, no mount
  references the run directories, and no file there is owned by a subordinate uid. An earlier
  run had left the probe-shaped jails' handed-off directories behind. They were removed through
  a namespace mapped like H, and the test now tears the probe directory down as its own
  parent, as production does.
- Raw records are kept outside the repository, in the coordinator's engagement directory
  (`sl1-jailprobe/`): per-case JSON lines (`HOLD_JAILPROBE_RECORD`), pytest output and JUnit for both
  interpreters, and the strace extract.

## Supported configurations, for the ordinary-launch follow-up only

This inventory does not gate anything. It is the starting list for the follow-up (lanes
artifact §J, Q-A), which needs this particular bind observed through the owner chain and
uid drop on each configuration.

| Configuration | Source | Proc-descriptor bind of a sealed memfd |
|---|---|---|
| Ubuntu 26.04.1, kernel 7.0.0-43, bubblewrap 0.11.1 (user namespaces, not setuid), AppArmor `bwrap-userns-restrict` plus the seat-jail override (dev0) | this run | **observed: fails** (P1) |
| Ubuntu 26.04 with bubblewrap 0.11.1 and the override, other hosts | `docs/advisor-board-capabilities-card.md` | not observed (same bwrap version as dev0) |
| Ubuntu 24.04 (no `unpriv_bwrap` denial as measured) and Ubuntu 22.04 | `docs/advisor-board-capabilities-card.md` | not observed |
| kernel 6.8.0-138, bubblewrap 0.6.1 | `plans/evidence/seat-jail-1132/p5-seat-uid.json` | not observed |
| claw (EC-EXECFIND-2 jail qualification) | `plans/evidence/seat-jail-1132/execfind2-jail-qualification-claw.json` | not observed |
| hosted CI runners (seat-jail and conformance jobs) | CI | not observed |
| setuid bubblewrap | none recorded | not observed |
| `ai` | never used by this lane | not observed |

Whether another bubblewrap version resolves a bind source differently was not observed. A
run on a second host is a separate request to the coordinator.
