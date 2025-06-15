# Diagnostic planning skill evaluation

`phase-loop-skill-eval` prepares a preregistered Linux/Codex pilot comparing the
pinned planning skill independently with two candidate edits. It neither installs
skills nor promotes results into editor or CI policy. Live model/tool operational
qualification and editor gating remain pending until an explicitly started pilot
delivers complete evidence. Offline acceptance never calls a model.

## Commands

Run the installed command from any directory:

```sh
phase-loop-skill-eval validate --spec pilot.json
phase-loop-skill-eval prepare --spec pilot.json --out /private/experiment
phase-loop-skill-eval packet --experiment /private/experiment --calibration --out /private/gold
# A blind human completes gold/scores.json with Boolean judgments and output quotes.
phase-loop-skill-eval reduce --experiment /private/experiment --calibration --scores /private/gold/scores.json --out /private/gold-result
# Explicitly starting run incurs provider usage; implementation acceptance does not run this.
phase-loop-skill-eval run --experiment /private/experiment
phase-loop-skill-eval packet --experiment /private/experiment --out /private/judge
# The same blind human seals judge/scores.json before allocation reveal.
phase-loop-skill-eval reduce --experiment /private/experiment --scores /private/judge/scores.json --out /private/result
```

Every output directory must be new. Store experiments outside repositories with
owner-only access; never commit allocation, transcripts, human scores or experiment
receipts. Packet exports contain only approved fields; give the human only the
packet and empty score form, never the experiment directory or this guide's
candidate descriptions. The scorer must not have seen allocation or gold answers.
This is procedural blinding; it does not prevent a human from opening operator files.

## Version 1 input

The complete synthetic example is
`phase-loop-runtime/tests/fixtures/skill_eval/pilot.json`. It is repository test
data, not a runtime import dependency. Copy it to private operator storage before a
pilot. Its executable pin is deliberately nonoperational: set an absolute regular
native executable path, its SHA-256, and exact `--version` stdout for the installed Codex.
Do not use a symlink as the pin. Choose the explicit model and effort before
preparation; do not edit an existing experiment.

Unknown fields and duplicate JSON keys are refused. The required fields are:

- `version: 1`, `profile: "plan"`, explicit `model`, and Codex `effort`
  (`low`, `medium`, `high`, or `xhigh`).
- `executable: {path, sha256, version, diagnostic_allowlist: []}`.
  Unexpected merged non-JSON output invalidates completion. This protocol
  preregisters no diagnostic exceptions.
- `baseline_commit` and immutable `baseline` skill bytes from the pinned research
  input `b9892d298aa23297e3f37eea5e2b4995c67ec60e`.
- Two `comparisons`, IDs `layer` and `oracle`, each with the exact reviewed
  `edit: {old, new}`, three target cases and one negative control.
- Each case's unique `id`, `kind` (`target` or `negative_control`), natural
  `prompt`, `files` (relative path to UTF-8 content), `required` fixture paths,
  and `rubric` (item ID to binary behavioral criterion).
- `repetitions: 3`, integer `allocation_seed`, and
  `decision: {target_wins: 3, target_losses: 0, control_losses: 0}`.
- `gold`: independently annotated good and wrong outputs for every case, each
  with `case_id`, `text`, Boolean `annotations`, and output-span `citations`.

Fixture names cannot escape the snapshot, collide with directories, or replace
`.git`, `AGENTS.md` or `.guidance`. Files are copied as regular files, never
links. The common `AGENTS.md` directs both arms to `.guidance/plan.md`; only
that guide differs. Natural prompts request a final-response plan using fixture
facts and relative evidence; manifest, artifact, handoff and reflection writes
are equally overridden in this plain non-Git snapshot.

Preparation freezes input/configuration/runtime hashes, independent variant bytes,
opaque allocations and the whole 48-trial schedule. Each comparison has 12 pairs;
six are baseline-first and six treatment-first. Allocation randomness is not a
model sampling seed; repetitions are not independent incidents. A changed runtime
or input requires a new experiment. Sequential execution claims each trial
atomically under an exclusive lock. A started trial is never retried or replaced;
later runs can execute only untouched trials. A crash without terminal evidence
remains incomplete. Cancellation preserves receipts and stops the batch.
This includes cancellation returned by the launcher: the trial stays invalid,
even with exit zero and a complete response. Private launch receipts retain the
returned interruption flag and cleanup evidence (null when unavailable); the
terminal receipt records interruption before cancellation propagates. Later
trials remain unclaimed until another explicit run.
Elapsed time and emitted usage are retained, otherwise usage is unknown.

## Launch and access boundary

The existing owned review launcher provides fresh private seat environments,
read-only roots and filtered egress. Preimage and final staged copy both live
below the runtime staging root, outside every Git worktree and the experiment.
Git discovery runs in C locale: a repository refuses; only return 128 with
`fatal: not a git repository` establishes absence; other failures refuse.
Stage resolution uses `log_path=None` so experiment/log placement cannot
place fixtures inside a repository.

Codex is pinned and configured explicitly: ephemeral session, strict config,
no user config or execpolicy files, no web search, apps or remote plugins.
Frozen feature controls preserve `shell_tool` and `code_mode_host` for local
reads. No MCP servers are added. The same owned profile first runs
`codex sandbox ... -- true` with a finite 30-second process-group bound;
only a positive result admits a subject invocation. Unknown and failed probes
refuse. Actual model/tool qualification still requires a completed fixture-reading
turn in a later pilot. The subject retains existing review monitoring without
a quiet wall-clock deadline.

Filtered egress denies private networks but leaves public networking; disabling
web search is separate. This capability makes no air-gap or arbitrary
shell-network prevention claim.

The Linux host observer watches the **final copy's** regular file inodes after
hashing, profile construction and probing. It records open and access separately.
No parent content reads occur while it watches. Observation ends after owned
process completion and before post-run integrity checks. Overflow, watch loss,
unmount, mutation/replacement or hash drift invalidates evidence. Unsupported
hosts cannot produce passing trials.

An access event establishes that a file was accessed during that isolated trial.
It does not identify the reader or prove comprehension. Inotify does not observe
all mmap accesses and can coalesce repeated events; event counts are not scores.
Keep roots private and prohibit concurrent inspection. See the
[Linux inotify manual](https://man7.org/linux/man-pages/man7/inotify.7.html).
Real owned-process read/open-only/no-read/self-report controls establish the
observer boundary; they do not establish real Codex usability.

Completion requires successful launch, one turn start, a completed agent message
within that turn and subsequent successful turn completion in the pinned CLI JSON
stream. Items before turn start, repeated turn starts and events after completion
are refused; tool/item lifecycle events within the turn remain supported. Failed, partial,
unknown, truncated or unexpectedly diagnostic streams are invalid.
Launch/access/terminal evidence joins experiment, scheduled trial, fixture, guide
and final-output digests; missing or swapped records refuse.

## Blinded scoring and interpretation

Packets contain random output IDs, task, fixture facts, delivered plan, rubric and
relative fixture access. They exclude guide/arm/model/effort labels, order,
rationale and operator paths. A preregistered scan detects opaque arm IDs, full
model IDs and operator/staging prefixes; ordinary words like producer, consumer
and control are allowed. Identity-disclosing outputs stay original in private
evidence, are not rewritten, and invalidate their comparison.
Identity markers in natural tasks, fixture names/content or rubrics refuse packet
export before any output can be omitted. Gold outputs with identity markers also
refuse calibration export. Scans inspect raw strings, including structured keys
and values, so JSON escaping does not hide path markers. Unblinded model outputs
are excluded from the score form and reported as invalid scheduled trials during
reduction; no scores are invented for them.

Score forms require the same scorer ID, experiment, packet and rubric digests,
and exactly one score for every scoreable output. Each rubric item requires an
actual Boolean and a nonempty verbatim output span in `quote`. Invalid/no-output
trials need no invented votes. Citations locate the judged behavior; software
cannot establish the semantic correctness of human judgments.

Both calibration commands hold the experiment lock. Export creates one opaque
packet, not an attempt. Calibration reduction claims the single attempt before
evaluating scores and stores score bytes/digest, scorer/experiment/packet/rubric/
gold identities and verdict. Failed or interrupted attempts cannot be retried
with fresh IDs. Malformed UTF-8 JSON score documents or score shapes are refused
with exit 2 and `skill-eval refused:`. For readable UTF-8 score bytes, calibration
stores a failed receipt before that refusal, preserving the submitted bytes/digest;
an absent or malformed scorer ID stays null. Missing/unreadable files, invalid UTF-8,
or interruption can leave only the started claim, which still consumes the attempt.
Well-formed judgments with wrong gold answers or declared prior exposure return a
failed calibration result. All gold Booleans must match; annotations are never returned.
The checked-in public examples are software test data; a human who has seen them
must use a fresh independently annotated gold pack rather than claiming blinding.
The scorer declares no prior gold exposure. Previously disclosed examples are
practice and cannot be reused for blind qualification. Ordinary reduction requires
this experiment's successful unchanged receipt and the same scorer before any
promising conclusion; foreign receipts never qualify. Ordinary reduction seals the
score bytes before revealing conclusions and refuses changed judgments on later runs.

Missing guide access means unexposed/invalid and makes the comparison inconclusive.
After exposure, missing required case-fixture access is a behavioral failure.
Every valid trial passes only if **all** rubric items and required fixture reads
pass. A treatment pass/baseline fail is a win; the reverse is a loss; equal
Booleans tie. Partial totals never create wins. Report nine target and three
negative-control pairs separately.

Any invalid/missing/unblinded trial makes its comparison inconclusive.
All three negative-control baseline trials must pass to establish sensitivity;
all-FAIL ties cannot qualify. Otherwise at least three target wins, no target
losses and no negative-control losses yield promising. Other valid comparisons
show no demonstrated improvement. This small diagnostic pilot supplies evidence
for review, with no significance, fleet-generalization or automatic adoption claim.
Do not tune rubrics after seeing results.
