# AGENTS.md (phase-loop-runtime)

Repo-wide guidance is in the root `AGENTS.md` and `CONTRIBUTING.md`. This file adds
one rule for running tests here.

## Test load on shared hosts

Team hosts (`/etc/consiliency/team-host` exists) and other shared machines run many
people's agents at once. A whole-suite parallel run on such a host can exhaust memory,
swap and I/O and stall every other user's work. This happened on 2026-11-04.

On a shared host, agents must not run:

- `scripts/local_check.py --full`, because it starts `pytest -n auto`;
- `pytest -n auto`, or any `-n` above 2;
- `make check` or any other whole-suite run;
- several test runs in parallel from one task.

On a shared host, agents may run:

- named test files or `-k` selectors for the code they changed;
- serially, without `-n` (pytest-xdist is not in the locked environment), and with
  `-p no:cacheprovider`;
- with a time limit per command, such as `timeout 900 uv run pytest ...`;
- mutation checks one test file at a time;
- one test command at a time, after checking host load first (`uptime`, `free -g`,
  `cat /proc/pressure/io`). Stop and defer to CI if load, swap or I/O pressure is
  already high or rises during the run.

Run whole-suite verification on hosted CI. Push the branch and let the required checks
run, or dispatch Gate A (`gh workflow run test.yml --ref <branch> -f chronology=false`,
see `CONTRIBUTING.md`). CI's own offload lane decides where the suite runs. Do not
start a heavy run on another shared host by hand. If heavy local compute is needed,
the owner arranges it with explicit CPU, memory, time and concurrency limits.

When you report results, say which checks ran locally, which were deferred to CI, and
whether any run was interrupted. An interrupted run is neither a pass nor a fail.
