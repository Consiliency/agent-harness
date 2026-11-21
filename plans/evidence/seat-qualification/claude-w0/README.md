# W0 bake-off records (SEATS CLAUDE, EC-CLAUDE-5)

One `claude-bakeoff-record.v1` record per W0 run, `<run_id>.json`, written by
`python -m phase_loop_runtime.claude_bakeoff run` in the owner's W0 window and landed in a
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

- **Sessions.** `run --session 1` runs blocks 1 and 2 (print, control). Its preflight checks
  only those arms, so it does not need `sdk`. `run --session 2` runs blocks 3 to 6 (sdk,
  sdk, control, print). It refuses before any reading until `sdk` is admitted and session
  1's records are in this directory. An arm stopped on a security outcome in session 1 stays
  stopped in session 2. Neither session overwrites a record that is already here.
- **Meter.** Each session opens with a reading, and each block closes with one: three
  readings in session 1 and five in session 2, eight in all (`meter_readings: 8`,
  `sessions: 2`). A block's bracket is the reading before it in its own session, so block
  3 opens on session 2's first reading and never on block 2's closing one. Each reading
  covers subscription usage and extra-usage spend, plus API spend if the account has an API
  organization. A block that moves extra usage or API spend sets `billing` for all its
  records, and an ambiguous block records `unknown`.
- **Interim, never complete.** Session 1's records are an interim set. `validate` names the
  sessions the directory holds, and with session 1 alone it says the set is not the
  complete bake-off. EC-CLAUDE-5 is proven only by the records PR that completes session 2.
  Its run count was fixed before the window and is unchanged.
- **OD-3b (V7).** Only the latest OD-3b section, by letter, is checked against this
  directory, and earlier sections are history. The latest section must cite this
  directory's `evidence_digest` on its `**W0 evidence digest:**` line, and its
  `**W0 sessions:**` line must name exactly the sessions held here, as `1` or `1 and 2`. A
  native transport it names must have records here. So an interim section after session 1
  says `1` and can name only `print` or "none admitted". After session 2's records land, a
  later section with the next free letter cites the new digest, says `1 and 2`, and may
  switch the pick through GL-5 and GL-6. Records of session 2 without session 1's fail V7.
- **EC-CLAUDE-6.** It is satisfied by the latest section. An interim section meets it
  while `sdk` is unadmitted, because it picks among the admitted transports.
