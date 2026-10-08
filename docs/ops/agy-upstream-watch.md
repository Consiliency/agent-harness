# agy upstream watch (agent-harness#1076)

The watch proposes the newest stable upstream agy release as a release-qualified image.
It runs `phase-loop agy-qualification watch` from a **host timer on a subscribed host**,
because a qualification needs a real Gemini subscription. It does not run on a
GitHub-hosted runner (which has no subscription), and it needs no self-hosted runner
registration. The hosted nightly `qualified-agy-image` provenance check still runs, and
since agent-harness#1333 (PR1) upstream membership is advisory there: a newest upstream
release that is not yet a shipped member only prints a `::warning::`, because each host
self-qualifies it on first use. The newest shipped member's vendor asset digest, URL and
archive are still checked and still fail the job. The watch is how a new release becomes
a shipped member.

Nothing in this repository installs the timer. An operator installs it on one
subscribed host, once.

## What one tick does

1. It detects the host platform. It proposes only the release route, Linux x64 glibc,
   because `qualified_provider_images.v2` has only that route. On any other platform it
   prints `platform_not_proposed` and opens nothing.
2. It reads the newest stable release. If that version is already pinned on `origin/main`,
   the tick is a no-op. It then lists **every** open PR, paginated to the end; if it
   cannot prove the listing complete (`totalCount` against distinct nodes, and the last
   page reached), it refuses with `refused_incomplete_pr_listing` and exit 2. The tick is a
   no-op (`up_to_date`) only if one of its own open PRs for that version carries the
   current `main` route-core label AND three oids agree: the one the watch recorded when it
   pushed the branch, GitHub's `headRefOid`, and the branch's `ls-remote` oid. The recorded
   oid lives in the watch's own operator-only state: an HMAC-bound `watch_push` entry in
   the per-user, per-host store, owner-only, no symlinks. It is never read from the PR
   body, which anyone with write access can edit. A maintainer push onto the branch, even
   one paired with an edited body, is therefore detected. A missing or tampered record
   means "not up to date": the result is a duplicate PR, never adoption.
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
   the prepared tree, and commits. It resolves `git remote get-url --push --all origin`
   and refuses (`refused_push_destination_ambiguous`, exit 2, nothing pushed) unless there
   is exactly one push URL, because `git push origin` writes to every configured push URL.
   It then pushes to the remote NAME `origin`, which is exactly the list git just
   enumerated. It never pushes to the printed string, because git would resolve that again:
   first as a remote name, then through `insteadOf`/`pushInsteadOf`. The URL is never
   compared with anything, since git's display form rewrites scp-style and credentialed
   URLs; it appears only as display text. The gates are counts:
   - a `--dry-run` pre-flight must print exactly one `To` block (none gives
     `push_unavailable`, several give `refused_push_destination_ambiguous`);
   - the real push must print exactly one `To` block and one row for exactly the new ref.

   Both pushes carry `--no-verify`, so no pre-push hook runs; a pre-push hook runs even for
   `--dry-run` otherwise. No URL or token appears on argv. Before pushing, the watch also
   checks that its own state store can be written and read back
   (`refused_push_state_unavailable` otherwise, nothing pushed).

   **Trusted configuration.** The bot host's own git and ssh configuration is trusted:
   `core.sshCommand`, `remote.origin.receivepack`, remote helpers, and `url.*` rewrites.
   Whoever controls it controls where the push goes. Git reads that configuration afresh at
   each invocation, so it could change between `get-url` and the push (a time-of-check to
   time-of-use gap). Keep the bot's config and checkout writable only by the bot.
   The branch is a **fresh**, unique `agy-watch/<version>-<utc>-<random>`, pushed with
   create-only semantics:
   `--force-with-lease=refs/heads/<name>:` (an empty expected value), a fully qualified
   destination, `--no-follow-tags --recurse-submodules=no`, and `--porcelain`. A zero exit
   status is not trusted, because a ref that already exists at exactly HEAD is reported
   "up to date" with exit 0. The push counts as done only when the porcelain output shows
   exactly one row, for exactly that ref, with the `*` (new ref) flag. Otherwise the tick
   exits 2 with a typed reason:
   - `refused_branch_exists`: stale info, or the ref is already up to date;
   - `refused_ref_conflict`: for example a plain `agy-watch` branch (the wording is
     git-version dependent, and older servers report `refused_push_remote_rejected`);
   - `refused_push_remote_rejected`: a hook or ruleset;
   - `refused_push_failed`;
   - `push_unavailable`: no single row for exactly our ref, which covers auth or network
     failures and also a wrong or extra row.

   After a verified push it records the pushed oid locally (bound to the branch, the
   version and the route-core base) and reads that record back (`push_record_unverified`
   otherwise: the branch is left as an orphan, no PR), then opens a **draft** PR whose
   body names the own older PRs it supersedes ("Supersedes (maintainer to close): #a,
   #b") and shows the pushed oid for display only. It then reads the PR back
   (`gh pr view --json headRefOid`, read-only). If the PR's head is not the pushed commit,
   the tick reports `pr_head_mismatch` with exit 2 and edits nothing. It never merges.

Each tick makes exactly one ref write (the new branch) and one object create (the new PR).
The watch never updates, force-pushes, adopts, closes, edits or deletes anything that
existed before the tick, so it never has to decide who owns an existing object. Its own
PRs are open, same-repository PRs, authored by the identity running the watch, on a
fresh-named branch, and carrying the version label. They only ever affect the no-op
decision and the "Supersedes" list. Run the watch under a dedicated bot identity; under a
shared human identity, that person's hand-made PRs matching every one of those conditions
would also be listed.

The fresh name is a sibling (`<version>-...`), not a child (`<version>/...`). With a child
name, any plain `agy-watch/<version>` branch would cause a git directory/file ref conflict
and block the version's whole namespace.

If `gh pr create` fails after the push succeeded, the fresh branch is left as an orphan.
The watch never deletes a ref, so a persistently failing `gh pr create` leaves one orphan
branch per tick until an operator notices the `gh` failures and removes the
`agy-watch/*` orphans.

A watch PR that is "up to date" keys on the route-core label, but its evidence pins EVERY
package file. So when other package code lands on `main`, the PR's full source-pin check
goes red, while the watch still considers it up to date and does nothing. To refresh it, a
maintainer closes the PR; the next tick then opens a fresh one against current `main`.

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
