# agy upstream watch (agent-harness#1076)

The watch proposes the newest stable upstream agy release as a release-qualified image.
It runs `phase-loop agy-qualification watch` from a **host timer on a subscribed host**,
because a qualification needs a real Gemini subscription. It does not run on a
GitHub-hosted runner (which has no subscription), and it needs no self-hosted runner
registration. The hosted nightly `qualified-agy-image` provenance check is unchanged.

Nothing in this repository installs the timer. An operator installs it on one
subscribed host, once.

## What one tick does

1. It detects the host platform. It proposes only the release route, Linux x64 glibc,
   because `qualified_provider_images.v2` has only that route. On any other platform it
   prints `platform_not_proposed` and opens nothing.
2. It reads the newest stable release. If that version is already pinned on `origin/main`,
   the tick is a no-op. It is also a no-op if an open `agy-watch/<version>` PR already
   records the current `main` route-core digest in its body marker. If `main`'s route-core
   has moved since then, the tick regenerates the record and force-updates only its own
   branch.
3. It fetches the release asset through the pinned provenance transport, checks the
   published archive digest, and builds a sealed memfd from the archive's single
   `antigravity` member. Nothing is installed on disk.
4. It works in a fresh checkout of `origin/main` with the runtime constants and catalog
   edited. From that tree it measures `--help` in the tree's own owned profile, then runs
   the three live operations through the tree's shim. It hands the image over as
   `--image-fd`, and the worker applies its seal check. The tree's release constant
   satisfies the worker gate, so the record matches the tree and never depends on the
   recency window.
5. It writes the redacted record, runs `verify_qualified_agy_image.py --route-core` on
   the prepared tree, commits, pushes and opens a **draft** PR. It never merges.

Budget about a minute of real inference per new release.

## Installing the timer (operator, one host)

Prerequisites:
- `phase-loop` installed, from the current release;
- `agy` authenticated for the operator user;
- `gh` authenticated with permission to push a branch and open a draft PR;
- a clone of this repository at `~/code/agent-harness`.

```bash
install -m 0644 docs/ops/agy-upstream-watch/agy-upstream-watch.service ~/.config/systemd/user/
install -m 0644 docs/ops/agy-upstream-watch/agy-upstream-watch.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agy-upstream-watch.timer
```

For a dry run, which qualifies and verifies but opens no PR:
`phase-loop agy-qualification watch --repo ~/code/agent-harness --dry-run`. A dry run
keeps its prepared tree and prints its path.

## Related commands

- `phase-loop agy-qualification status` prints this host's store state, its entry types,
  whether self-qualification is enabled, and the runtime identity.
- `phase-loop agy-qualification run` pre-qualifies the `agy` on `PATH` (first use).
- `phase-loop agy-qualification clear [--all]` removes failed entries, or every entry.
