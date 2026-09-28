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
   the tick is a no-op. It then lists **every** open PR, paginated to the end; if it
   cannot prove the listing complete (`totalCount` against the nodes, and the last page
   reached), it refuses with `refused_incomplete_pr_listing` and exit 2. The tick is a
   no-op (`up_to_date`) if one of its own open PRs for that version carries the current
   `main` route-core label and its head is still exactly the commit on its branch.
3. It fetches the release asset through the pinned provenance transport, checks the
   published archive digest, and builds a sealed memfd from the archive's single
   `antigravity` member. Nothing is installed on disk.
4. It works in a fresh checkout of `origin/main` with the runtime constants and catalog
   edited. From that tree it measures `--help` in the tree's own owned profile, then runs
   the three live operations through the tree's shim. It hands the image over as
   `--image-fd`, and the worker applies its seal check. The tree's release constant
   satisfies the worker gate, so the record matches the tree and never depends on the
   recency window.
   Adding a member edits `gemini_heartbeat.py`, a route-core file that every existing
   record pins, so the tick requalifies **every** catalog member on the prepared tree.
   It re-fetches each existing member's image from that member's own release and
   refuses unless the asset and image digests equal the committed record's.
5. It writes the redacted record, runs `verify_qualified_agy_image.py --route-core` on
   the prepared tree, and commits. It pushes a **fresh**, unique branch
   `agy-watch/<version>-<utc>-<random>` with create-only semantics
   (`--force-with-lease=refs/heads/<name>:`, an empty expected value, to a fully qualified
   destination). If that ref already exists, the push fails atomically and the tick exits 2
   (`refused_branch_exists`). It opens a **draft** PR from the branch, and then closes its
   own older open PRs for that version. It never merges.

The watch never updates, force-pushes, adopts or deletes an existing branch, so it never
has to decide who owns one. "Its own PRs" means open, same-repository PRs authored by the
identity running the watch, on a fresh-named branch, carrying the version label. It only
ever *closes* those, and never pushes to their branches. A PR a maintainer has pushed onto
is not up to date, so it is superseded (closed), never overwritten. The fresh name is a
sibling (`<version>-...`), not a child (`<version>/...`), because a plain
`agy-watch/<version>` branch pushed by anyone would otherwise block the whole namespace
with a git directory/file ref conflict.

Budget about a minute of real inference per catalog member per new release.

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
keeps its prepared tree and prints its path. `--version <tag>` picks a specific in-window
stable release, and `--base-ref <ref>` (dry run only) prepares from a ref other than
`origin/main`.

## Related commands

- `phase-loop agy-qualification status` prints this host's store state, its entry types,
  whether self-qualification is enabled, and the runtime identity.
- `phase-loop agy-qualification run` pre-qualifies the `agy` on `PATH` (first use).
- `phase-loop agy-qualification clear [--all]` removes failed entries, or every entry.
