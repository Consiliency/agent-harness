#!/usr/bin/env bash
# Report the agy catalog lag rule as one labelled GitHub issue (ROLLJOB-detail §5.2).
#
# Runs as the last step of the nightly `upstream` job in
# .github/workflows/qualified-agy-image.yml, after
# `verify_qualified_agy_image.py --upstream-only --report "$AGY_LAG_REPORT"`, whether that
# step passed or not. It follows ci/main-red.sh: one canonical open issue, labelled `agy-lag`.
#
#   no report                       -> change nothing (the verifier failed before deciding)
#   report-only ("enforced": false) -> change nothing, whatever the lag status
#   enforced, lag "fail"            -> no open agy-lag issue: create one; exactly one: comment
#                                      on it; more than one: comment on the lowest-numbered
#                                      and close the rest
#   enforced, "ok" or "warn_*"      -> close every open agy-lag issue with a comment
#
# Headroom never opens or closes the issue. The lag status changes the run's exit only when
# enforced (the verifier decides that); this script only reports.
#
# Inputs (env): AGY_LAG_REPORT (the report path), GH_TOKEN (issues: write on this job only),
# GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_SERVER_URL. Requires `gh` and `python3`.
set -euo pipefail

: "${AGY_LAG_REPORT:?AGY_LAG_REPORT is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
: "${GITHUB_SERVER_URL:?GITHUB_SERVER_URL is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"

LABEL="agy-lag"
TITLE="agy catalog lag: the newest upstream agy is not a catalog member"
RUN_URL="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"

if [ ! -f "$AGY_LAG_REPORT" ]; then
  echo "no lag report at $AGY_LAG_REPORT; nothing to report" >&2
  exit 0
fi

# "<enforced> <status> <release>" from the report, or nothing when it is unreadable.
read_report() {
  python3 -I - "$AGY_LAG_REPORT" <<'PY'
import json, re, sys
try:
    lag = json.load(open(sys.argv[1], encoding="utf-8"))["lag"]
    enforced, status, release = lag["enforced"], lag["status"], lag["release"]
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(0)
if type(enforced) is bool and status in ("ok", "warn_inside_bound", "warn_pr_open", "fail") \
        and isinstance(release, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", release):
    print("true" if enforced else "false", status, release)
PY
}

parsed="$(read_report)"
if [ -z "$parsed" ]; then
  echo "the lag report is unreadable; nothing to report" >&2
  exit 0
fi
read -r enforced status release <<<"$parsed"

if [ "$enforced" != "true" ]; then
  echo "lag rule is report-only (status $status); no issue is created, commented on or closed" >&2
  exit 0
fi

# Every open agy-lag issue number, lowest first.
open_issues() {
  gh issue list --repo "$GITHUB_REPOSITORY" --state open --label "$LABEL" --limit 100 --json number \
    | python3 -I -c 'import json, sys; [print(n) for n in sorted(i["number"] for i in json.load(sys.stdin))]'
}

listed="$(open_issues)"   # a failed listing stops the script (set -e): never a guess
numbers=()
for number in $listed; do
  numbers+=("$number")
done

if [ "$status" != "fail" ]; then
  for number in "${numbers[@]}"; do
    gh issue close "$number" --repo "$GITHUB_REPOSITORY" \
      --comment "agy catalog lag cleared: newest upstream agy $release is $status. Run: $RUN_URL"
    echo "closed agent-harness#$number" >&2
  done
  exit 0
fi

body="The newest upstream agy release, $release, is not a member of the shipped catalog, is older than the 48 h lag bound, and no promotion pull request for it is in flight (AGYROLL §6.3). Run: $RUN_URL"
if [ "${#numbers[@]}" -eq 0 ]; then
  gh label create "$LABEL" --repo "$GITHUB_REPOSITORY" --force --color D93F0B \
    --description "the agy catalog lags upstream" >/dev/null
  gh issue create --repo "$GITHUB_REPOSITORY" --label "$LABEL" --title "$TITLE" --body "$body"
  echo "created the agy-lag issue" >&2
  exit 0
fi
lowest="${numbers[0]}"
gh issue comment "$lowest" --repo "$GITHUB_REPOSITORY" --body "$body"
echo "commented on agent-harness#$lowest" >&2
for number in "${numbers[@]:1}"; do
  gh issue close "$number" --repo "$GITHUB_REPOSITORY" --comment "Duplicate of the open agy-lag issue $lowest."
  echo "closed duplicate agent-harness#$number" >&2
done
