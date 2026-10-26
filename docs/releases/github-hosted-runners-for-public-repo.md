# Public-repo CI runs on GitHub-hosted runners

`agent-harness` is a public repository, so GitHub Actions minutes on standard
GitHub-hosted runners are free and unmetered. Every job in this repo therefore
uses a standard GitHub-hosted label rather than a Blacksmith label: paid runner
minutes on a public repo buy nothing that GitHub does not already give away for free.
Most jobs use `ubuntu-latest`; see the pin below for the three that do not.

Blacksmith remains in use for the org's private repositories, where minutes are
metered and its per-minute rate is the cheaper of the two. Treat a new
`runs-on: blacksmith-*` line in this repo as a cost regression.

## Native-test jobs pinned to `ubuntu-24.04` (2026-10-25)

`test.yml`'s `pytest`, `clean-room` and `wheel-smoke` jobs pin
`runs-on: ubuntu-24.04`. `ubuntu-latest` began resolving to an Ubuntu 26.04
image. Under it, a PR run of agent-harness#1763 failed 17 tests, in 8 test files
that are byte-identical to main. The last successful PR run had used an
ubuntu-24.04 image. The failures were in sandbox and process tests: canonical
paths to `true` and to multicall coreutils, `unshare` and `setpriv` being
denied, owner death signals and timeouts.

This pins the job input back to the venue that previously passed. It is not a
claim that the failures are understood, or that the suite is incompatible with
Ubuntu 26.04: compatibility with 26.04 is unproven, and the failed runs are kept
as evidence. Test selection, assertions, timeouts, sandbox policy and
`OFFLOAD_SANDBOX_READY` are unchanged. Moving these jobs to a newer image needs
its own validation.

## Why the legacy hosted lanes are still skipped (2026-09-04)

**2026-09-20 update (agent-harness#892):** the complete hosted Python matrix and
clean-room lane now run because the current rootless offload engine does not
provide `/dev/net/tun` inside its exec containers. The real egress tests require
that device. `OFFLOAD_SANDBOX_READY` in `test.yml` is explicitly false; changing
it requires a reviewed offload environment with passing real egress checks.
Trust and secret availability remain necessary for offloading but do not prove
sandbox capability. Dagger also checks the device before starting its suites.
No test selection or timeout changes, automatic retry after offload failure,
host configuration changes, or AI-stack deployment are part of this routing
change. The historical explanation below describes the previous eligible path.

Moving off Blacksmith invalidated the stated reason for a guard, without
invalidating the guard.

`test.yml`'s `pytest` and `clean-room` jobs carry
`if: needs.elig.outputs.eligible != 'true'` (`clean-room` additionally skips pull
requests, agent-harness#1029), and their comments used to explain
that skip as avoiding Blacksmith billing for work already done on `ai`. On
GitHub-hosted runners this repo bills nothing, so read literally the comment said
the guard was a spend control that no longer had anything to control.

It is not a spend control. The offload graph owns the suite on the eligible path;
these lanes exist for the fork/no-secret path, where secrets are withheld, the
offload is unreachable, and `hosted` is the suite of record. That reason is
unchanged by the runner move, so the condition is unchanged too — only the
comments were corrected.

Worth keeping in mind when the next cost decision lands here: a guard justified
by a cost that has since disappeared is easy to delete for the wrong reason. The
fork path would lose its only suite of record.
