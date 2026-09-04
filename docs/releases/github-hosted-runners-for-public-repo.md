# Public-repo CI runs on GitHub-hosted runners

`agent-harness` is a public repository, so GitHub Actions minutes on standard
GitHub-hosted runners are free and unmetered. Every job in this repo therefore
uses `ubuntu-latest` rather than a Blacksmith label: paid runner minutes on a
public repo buy nothing that GitHub does not already give away for free.

Blacksmith remains in use for the org's private repositories, where minutes are
metered and its per-minute rate is the cheaper of the two. Treat a new
`runs-on: blacksmith-*` line in this repo as a cost regression.

## Why the legacy hosted lanes are still skipped (2026-09-04)

Moving off Blacksmith invalidated the stated reason for a guard, without
invalidating the guard.

`test.yml`'s `pytest` and `clean-room` jobs carry
`if: needs.elig.outputs.eligible != 'true'`, and their comments used to explain
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
