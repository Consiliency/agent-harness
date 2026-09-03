#!/usr/bin/env bash
# Report the suite gate's result on main as a labelled GitHub issue.
#
# Runs from the `main-red` job in .github/workflows/test.yml after `gate`
# completes on a push to main or the nightly schedule. A PR defers the heavy
# CONFORM chronology node to the landing push (ci/chronology-scope.sh), so a
# regression the PR could not see surfaces HERE, not on the PR -- this script
# is what makes that visible without anyone watching the Actions tab.
#
# Contract (one canonical issue, labelled `ci-main-red`):
#   gate failed  -> create the issue if none exists, comment on it if it is
#                   open, reopen + comment if it was closed.
#   gate passed  -> close every open `ci-main-red` issue with a comment.
#   stale run    -> a run whose head is no longer the tip of main reports
#                   nothing (exit 0); the tip's own run is the authority.
#
# Inputs (env): GATE_RESULT (needs.gate.result: success|failure|...),
# GITHUB_RUN_ID, GITHUB_SERVER_URL, GITHUB_REPOSITORY, GITHUB_SHA, GH_TOKEN.
# Requires `gh`, `git` (full history: checkout fetch-depth 0) and `jq`.
set -euo pipefail

: "${GATE_RESULT:?GATE_RESULT is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
: "${GITHUB_SERVER_URL:?GITHUB_SERVER_URL is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_SHA:?GITHUB_SHA is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"

LABEL="ci-main-red"
TITLE="suite gate is red on main"
RUN_URL="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"

tip="$(gh api "repos/$GITHUB_REPOSITORY/branches/main" --jq .commit.sha)"
if [ "$tip" != "$GITHUB_SHA" ]; then
  echo "stale run: head $GITHUB_SHA is not the tip of main ($tip); not reporting" >&2
  exit 0
fi

case "$GATE_RESULT" in
  failure|success) ;;
  *)
    echo "GATE_RESULT=$GATE_RESULT is neither failure nor success; nothing to report" >&2
    exit 2 ;;
esac

gh label create "$LABEL" --force --color B60205 --description "suite gate is red on main" >/dev/null

if [ "$GATE_RESULT" = "success" ]; then
  gh issue list --state open --label "$LABEL" --limit 50 --json number --jq '.[].number' \
    | while IFS= read -r number; do
        [ -n "$number" ] || continue
        gh issue close "$number" --comment "suite gate green again on main: run $RUN_URL"
        echo "closed #$number" >&2
      done
  exit 0
fi

# ---- gate failed: build the report --------------------------------------------
green="$(gh run list --workflow test.yml --branch main --event push --status success \
  --limit 1 --json headSha --jq '.[0].headSha // empty')"
if [ -n "$green" ] && git cat-file -e "$green^{commit}" 2>/dev/null; then
  # --first-parent: one line per LANDING on main, whether it was a merge commit
  # or a squash; the commits inside a merged branch are not listed.
  range_label="Landings since the last green push run ($green):"
  range="$(git log --first-parent --oneline "$green..HEAD" || true)"
  [ -n "$range" ] || range="(no commits on main since $green)"
else
  range_label="No green push run found on main; last 20 commits:"
  range="$(git log --oneline -20)"
fi
failing="$(gh run view "$GITHUB_RUN_ID" --json jobs \
  --jq '[.jobs[] | select(.conclusion=="failure") | .name] | join(", ")')"
[ -n "$failing" ] || failing="(no failed job reported by the API; see the run)"

body_file="$(mktemp)"
trap 'rm -f "$body_file"' EXIT
{
  echo "suite gate is red on main at \`$GITHUB_SHA\`."
  echo
  echo "- run: $RUN_URL"
  echo "- failing jobs: $failing"
  echo
  echo "$range_label"
  echo
  echo '```'
  echo "$range"
  echo '```'
  echo
  echo "PRs defer the CONFORM chronology node to the landing push (\`ci/chronology-scope.sh\`), so a red here may be a regression no PR run could see. This issue closes itself when the gate is green again on main."
} >"$body_file"

existing="$(gh issue list --state all --label "$LABEL" --limit 1 --json number,state \
  --jq '.[0] // empty | "\(.number) \(.state)"')"
if [ -z "$existing" ]; then
  gh issue create --label "$LABEL" --title "$TITLE" --body-file "$body_file"
  echo "created issue" >&2
  exit 0
fi
number="${existing%% *}"
state="${existing##* }"
case "$state" in
  OPEN)
    gh issue comment "$number" --body-file "$body_file"
    echo "commented on open #$number" >&2 ;;
  CLOSED)
    gh issue reopen "$number"
    gh issue comment "$number" --body-file "$body_file"
    echo "reopened + commented on #$number" >&2 ;;
  *)
    echo "unexpected issue state '$state' for #$number" >&2
    exit 2 ;;
esac
