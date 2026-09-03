# Public-repo CI runs on GitHub-hosted runners

`agent-harness` is a public repository, so GitHub Actions minutes on standard
GitHub-hosted runners are free and unmetered. Every job in this repo therefore
uses `ubuntu-latest` rather than a Blacksmith label: paid runner minutes on a
public repo buy nothing that GitHub does not already give away for free.

Blacksmith remains in use for the org's private repositories, where minutes are
metered and its per-minute rate is the cheaper of the two. Treat a new
`runs-on: blacksmith-*` line in this repo as a cost regression.
