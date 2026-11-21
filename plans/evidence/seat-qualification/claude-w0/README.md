# W0 bake-off records (SEATS CLAUDE, EC-CLAUDE-5)

One `claude-bakeoff-record.v1` record per W0 run, `<run_id>.json`, written by
`python -m phase_loop_runtime.claude_bakeoff run --plan PLAN --session 1` (later
`--session 2`) in the owner's W0 window and landed in a
reviewed records PR (G2). The schema is closed and metadata-only: meter readings and raw
request captures stay in the operator's private storage, and a record carries their
digests. `python -m phase_loop_runtime.claude_bakeoff validate` is the shape check (V7);
`python -m phase_loop_runtime.claude_bakeoff digest` is the evidence digest an OD-3b
section cites. V7 never runs a W0 head's code: each record's head must be on `main`, and
the TUI jail digest is computed by the validating runtime itself, for a head whose jail
source is byte-identical to its own. For any other head, validate from a checkout at that
head or pass `--tui-digest`. Native observations travel only over the launching parent's
inherited descriptor, and capture-twin descendants are gone before a native run begins. That
boundary is against the jailed seat: a process of the owner's own uid stays outside it, so an
observation is sound only if no such process misbehaved in the window, and a record names its
unconfined co-seats in `co_seats_unconfined`.
No record is here until W0 runs.

## Sessions

OQ-4 of `plans/phase-plan-v1-seats-CLAUDE.md` was decided on 2026-11-21. The owner chose
"Early session", whose wording was: "Session 1 runs now-ish: 3 jailed print boards, 1
capture run and 3 control runs on `ai`'s Claude login. It produces the records the network
lockdown needs. The SDK session follows once that route is admitted." This records-only
amendment fixes the following. The 18-run plan and its six blocks do not change.

- **Commands.** Run `python -m phase_loop_runtime.claude_bakeoff run --plan PLAN --session 1`
  for blocks 1 and 2 (print, control), and later `... --session 2` for blocks 3 to 6 (sdk,
  sdk, control, print). Use the same `--window` (default `w0`) for both, and do not
  archive its private directory between them.
- **Gate.** A session holds a lock on this directory from before its gate to its end, so a
  second session, under any `--window`, refuses. Before any private directory, credential,
  CA or reading, the gate refuses in these cases:
  - an arm of the session that is not admitted;
  - for `sdk`, one that is not ready: it needs its capture twin, the ratified OD-3a
    section and a current GL-2 worker receipt;
  - records of this or a later session already here;
  - for session 2, session 1's records not complete here;
  - a private ledger that is not this session's starting point;
  - for session 2, a different bundle, model, effort or board from session 1's.

  Session 1 checks only its own arms, so it does not need `sdk`. Records are created
  exclusively and never replaced.
- **Coverage.** A session is complete when every block holds runs `r1` to `r3` of its
  planned arm. A security stop may end a block early, but only on its last run, and a
  block whose arm stopped earlier holds no record. `validate` names the complete sessions
  and any incomplete one. Session 1 alone is an interim set and never the complete
  bake-off. EC-CLAUDE-5 is proven only by the records PR that completes session 2. Its
  run count was fixed before the window and is unchanged.
- **Meter.** Each session opens with a reading, and each block closes with one after the
  5-minute settle. Openings have no settle. That gives three readings in session 1 and five
  in session 2, eight in all (`meter_readings: 8`, `sessions: 2`), at fixed private
  positions filled once and in order. A block's bracket is the reading before it in its
  own session, so block 3 opens on session 2's first reading.
  - Each reading has three values: subscription usage, extra-usage spend, and API spend.
  - A value is a number (`12%`, `$3.40`), `none` (the account has no such meter) or
    `unavailable`. A blank or malformed answer is asked again, then recorded `unavailable`.
  - A block whose API spend rose is `api`, then one whose extra-usage spend rose is
    `extra_usage`, then one whose subscription usage rose is `subscription`.
  - A spend that cannot be resolved (unavailable, a meter on one side only, or lower at the
    close) makes the block `unknown`, and so does a block where nothing rose.
  - Session 2 starts only on session 1's ledger and salt. Those must still reproduce every
    session-1 record's `meter_digest`.
- **Security stops.** A security outcome is written to the private
  `security-outcomes.txt` the moment it is seen, before any reading or record. A later
  session keeps that arm stopped, as it does for a published `withheld_private` record.
  Report the outcome privately (OD-10) before any rerun.
- **OD-3b (V7).** Only the latest OD-3b section, by letter, is checked here. Earlier
  sections are history. The latest section needs exactly one line of each of these:
  - `**Jailed Claude default:**`, naming `print`, `sdk` or `none admitted`;
  - `**W0 sessions:**`, naming `1` or `1 and 2`, all of which must be complete here;
  - `**W0 evidence digest:**`, which must equal
    `python -m phase_loop_runtime.claude_bakeoff digest --through-session N` over those
    sessions alone.

  A section over session 1 may pick only `print` or `none admitted`, and a transport it
  picks must have records in its sessions.
- **Landing order.**
  1. Session 1's records PR (G2).
  2. Optionally an interim OD-3b section (GL-5) citing session 1. It is provisional: it
     does not prove EC-CLAUDE-5, and it closes EC-CLAUDE-6 only for the current setting.
  3. Session 2's records PR. V7 keeps verifying the interim section against session 1's
     records, which stay unchanged.
  4. A later OD-3b section with the next free letter. It cites `--through-session 2`, says
     `1 and 2`, and may switch the pick through GL-5 and GL-6.
- **EC-CLAUDE-6.** It is satisfied by the latest section. An interim section meets it
  while `sdk` is unadmitted, because it picks among the admitted transports.
- **Reviewing records before G2.** V7 checks shape, not meaning.
  - Read every slug a record carries, such as a control `claude_code_entrypoint` or a
    request host, for private meaning before approving.
  - A `withheld_private` record keeps its block's request set, which came from the
    block's capture twin and not from the withheld run.
  - The twin's output is discarded and its success taken from its exit status. Its request
    set is a measurement, never a board result.
  - Control records are self-reported. The kit checks that each control file reports the
    run plan's model and that each file is fresh and given once. It cannot observe the
    control's launches or account.
