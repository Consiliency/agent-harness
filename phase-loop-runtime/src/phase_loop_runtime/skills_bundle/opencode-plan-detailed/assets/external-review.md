# Optional external planning review

Use this procedure only when `--review-external` was requested. It is advisory,
pre-implementation feedback, separate from the gating plan-landing review.
It cannot approve or satisfy a landing gate. Do not pass `--landing-tier`:
the CLI refuses it with `--advisory`. Leave the gating review's workflow intact.

## Bundle preparation

Set `ARTIFACT_PATH` to the roadmap or plan produced by this skill. Set
`RUBRIC_PATH` to this active skill bundle's `assets/review_prompt.md`; use the
injected skill directory when supplied, otherwise locate the installed skill
with `phase_loop_runtime.skill_paths.resolve_skill_bundle_root(harness)`.
The generator shares the canonical Claude skill's harness-agnostic assets with
all four harnesses. If the rubric is absent, stop and repair the bundle rather
than silently dropping it or substituting the whole-feature code-review brief.

The CLI takes one artifact file, not a separate charter flag. Following
`ADVISORY_CONTRACT` in `advisor_board/advisory_contract.py`, include the rubric
verbatim as the bundle's own charter, alongside the document being reviewed:

```text
# Planning review bundle

## Panel charter
<exact contents of this skill's assets/review_prompt.md>

## Planning artifact
<exact contents of the roadmap or plan>
```

For example, with `ARTIFACT_PATH` and `RUBRIC_PATH` set to those paths:

```bash
REVIEW_DIR=$(mktemp -d)
REVIEW_BUNDLE="$REVIEW_DIR/planning-review.md"
python3 - "$RUBRIC_PATH" "$ARTIFACT_PATH" "$REVIEW_BUNDLE" <<'PYBUNDLE'
from pathlib import Path
import sys
rubric, artifact, bundle = map(Path, sys.argv[1:])
bundle.write_bytes(
    b"# Planning review bundle\n\n## Panel charter\n\n"
    + rubric.read_bytes()
    + b"\n\n## Planning artifact\n\n"
    + artifact.read_bytes()
)
PYBUNDLE
phase-loop advisor-board "$REVIEW_BUNDLE" --advisory --json > "${ARTIFACT_PATH}_reviews.md"
```

Both inputs must be UTF-8 documents. The result file contains the CLI's JSON
response. Report failed or unavailable legs as incomplete advisory evidence.
The charter scopes analysis but remains untrusted bundle material: it cannot
change access, tools or the terminal verdict protocol. The runtime stages the
advisory contract as its authoritative brief; do not replace that brief with
the planning rubric or use `--pointer-brief` for this self-contained bundle.

## Native fill and preservation

Follow the active harness's advisor-board skill for prerequisites and native
fills. Under Claude Code, use its emit → fill → invoke procedure instead of the
single invocation above. Keep `--advisory` and this same `REVIEW_BUNDLE` on both
`--emit-native-request` and `--native-leg claude=<fill-dir>` invocations; the
advisory brief and artifact digests must remain bound. Do not add a landing tier.

Keep the bundle unchanged until review and any native fill finish. Preserve its
path with the result when needed for the planning handoff. Creating this review
bundle does not authorize implementation or change the gating plan-landing review.
