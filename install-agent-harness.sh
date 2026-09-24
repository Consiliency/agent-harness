#!/usr/bin/env bash
# install-agent-harness.sh — off-tailnet collaborator installer for the PUBLIC
# agent-harness (https://github.com/Consiliency/agent-harness).
#
# Needs NO dotfiles clone, NO 1Password, NO Homebrew, NO tailnet. Cross-OS
# (macOS / Linux). Installs:
#   1. the phase-loop runtime CLI (pinned published release) via `uv tool`
#   2. the workflow skills for your harness, from the public skills bundle
# pulling everything from the public agent-harness repo.
#
# Usage:
#   ./install-agent-harness.sh [--harness claude|codex|gemini|opencode|all] [--ref vX.Y.Z]
#   (--harness all installs the skills for EVERY harness; the runtime is shared.)
# Env overrides:
#   AGENT_HARNESS_REPO   (default https://github.com/Consiliency/agent-harness)
#   AGENT_HARNESS_REF    (default: auto-resolved from the checked-in RELEASE_PIN;
#                         set to override — no hardcoded stale ref)
#   AGENT_HARNESS_HARNESS (default claude; use "all" for every harness)
#   AGENT_HARNESS_HOME   (persistent clone dir; default ~/.local/share/agent-harness)
#   AGENT_HARNESS_SKILL_DEST (override the harness skill root)
set -euo pipefail

REPO="${AGENT_HARNESS_REPO:-https://github.com/Consiliency/agent-harness}"

# Resolve the release ref WITHOUT a hardcoded pin. Order:
#   1. AGENT_HARNESS_REF override (explicit wins);
#   2. the checked-in RELEASE_PIN sibling (cloned checkout — the common path);
#   3. RELEASE_PIN fetched from the repo's default branch (curl-pipe path).
# RELEASE_PIN is kept == the published package version by the release-consistency
# CI gate, so it always names the current release (auto-track, not a stale const).
resolve_ref() {
    if [ -n "${AGENT_HARNESS_REF:-}" ]; then printf '%s' "$AGENT_HARNESS_REF"; return 0; fi
    local here pin
    # Only trust a sibling RELEASE_PIN when $0 is a REAL script file (a cloned
    # checkout). Under curl-pipe, $0 is "bash" (not a file), so `[ -f "$0" ]` is
    # false and we fall through to the fetch — a stray $PWD/RELEASE_PIN cannot
    # hijack the ref.
    if [ -f "$0" ]; then
        here="$(cd "$(dirname "$0")" 2>/dev/null && pwd)" || here=""
        if [ -n "$here" ] && [ -f "$here/RELEASE_PIN" ]; then
            tr -d '[:space:]' < "$here/RELEASE_PIN"; return 0
        fi
    fi
    # `|| true` so a curl/network failure under `set -euo pipefail` does NOT abort
    # the script mid-substitution — it leaves pin empty and falls to the friendly
    # error below (which explains AGENT_HARNESS_REF / the pin URL).
    pin="$(curl -fsSL "${REPO%.git}/raw/main/RELEASE_PIN" 2>/dev/null | tr -d '[:space:]' || true)"
    if [ -n "$pin" ]; then printf '%s' "$pin"; return 0; fi
    echo "ERROR: could not resolve the release pin. Set AGENT_HARNESS_REF=vX.Y.Z, or" >&2
    echo "       ensure network access to ${REPO%.git}/raw/main/RELEASE_PIN." >&2
    return 1
}
REF=""  # populated after arg parsing (an explicit --ref overrides RELEASE_PIN)
REF_EXPLICIT=""          # set when --ref was passed; drives the update-advice footer
REF_FROM_LOCAL_PIN=""    # set by resolve_ref when the ref came from a sibling RELEASE_PIN
HARNESS="${AGENT_HARNESS_HARNESS:-claude}"
HOME_DIR="${AGENT_HARNESS_HOME:-$HOME/.local/share/agent-harness}"

while [ $# -gt 0 ]; do
    case "$1" in
        --harness) HARNESS="$2"; shift 2 ;;
        --ref)     REF="$2"; REF_EXPLICIT=1; shift 2 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1 (see --help)" >&2; exit 2 ;;
    esac
done

# No explicit --ref? Auto-resolve from RELEASE_PIN (sibling file, else fetched).
if [ -z "$REF" ]; then
    # Determine the ref SOURCE here, in the parent shell. `REF="$(resolve_ref)"` runs in a
    # subshell, so any variable resolve_ref sets is discarded -- the update-advice footer
    # must not depend on one. Mirror resolve_ref's compound rule exactly: a file-backed $0
    # AND a sibling RELEASE_PIN.
    if [ -f "$0" ]; then
        _here="$(cd "$(dirname "$0")" 2>/dev/null && pwd)" || _here=""
        if [ -n "$_here" ] && [ -f "$_here/RELEASE_PIN" ]; then
            REF_FROM_LOCAL_PIN="$_here/RELEASE_PIN"
        fi
    fi
    REF="$(resolve_ref)" || exit 1
fi

# Resolve the harness list: "all" => every supported harness (the runtime is shared;
# only the skills are per-harness, installed into each harness's own skill root).
if [ "$HARNESS" = all ]; then
    HARNESSES="claude codex gemini opencode"
else
    HARNESSES="$HARNESS"
fi

# Per-harness default skill root (the documented user-local roots).
skill_dest() {
    case "$1" in
        claude)   printf '%s\n' "$HOME/.claude/skills" ;;
        codex)    printf '%s\n' "$HOME/.codex/skills" ;;
        gemini)   printf '%s\n' "$HOME/.gemini/skills" ;;
        opencode) printf '%s\n' "$HOME/.config/opencode/skills" ;;
        *) echo "unknown --harness: $1 (claude|codex|gemini|opencode|all)" >&2; return 2 ;;
    esac
}
# Validate every requested harness up front.
for _h in $HARNESSES; do skill_dest "$_h" >/dev/null || exit 2; done

# A rerun may update only a clean, standalone checkout of the configured repo.
# Remove terminal / and /. components so they cannot hide a symlink below.
while [ "$HOME_DIR" != / ]; do
    case "$HOME_DIR" in
        */) HOME_DIR="${HOME_DIR%/}" ;;
        */.) HOME_DIR="${HOME_DIR%/.}"; HOME_DIR="${HOME_DIR:-/}" ;;
        *) break ;;
    esac
done
if [ -e "$HOME_DIR" ] || [ -L "$HOME_DIR" ]; then
    if [ -L "$HOME_DIR" ] || [ ! -d "$HOME_DIR/.git" ] || [ -L "$HOME_DIR/.git" ] ||
       [ ! -f "$HOME_DIR/install-agent-harness.sh" ] || [ ! -f "$HOME_DIR/RELEASE_PIN" ] ||
       [ ! -d "$HOME_DIR/phase-loop-skills" ] ||
       ! _origin="$(git -C "$HOME_DIR" config --local --get remote.origin.url 2>/dev/null)" ||
       [ "${_origin%.git}" != "${REPO%.git}" ] ||
       ! _root="$(git -C "$HOME_DIR" rev-parse --show-toplevel 2>/dev/null)" ||
       [ "$_root" != "$(cd "$HOME_DIR" && pwd -P)" ] ||
       ! _changes="$(git -C "$HOME_DIR" status --porcelain --untracked-files=all 2>/dev/null)" ||
       [ -n "$_changes" ]; then
        echo "ERROR: refusing existing AGENT_HARNESS_HOME: $HOME_DIR" >&2
        echo "Choose an absent directory, or a clean standalone agent-harness checkout with the configured origin." >&2
        echo "Existing files, symlinks, linked worktrees and local changes are preserved." >&2
        exit 1
    fi
fi

say() { printf '\033[1;32m%s\033[0m\n' "$*"; }

# --- 1) resolve the ref to ONE commit and check it out, before installing anything ---
# agent-harness#980: `git clone --branch` accepts a branch or tag but not a commit SHA,
# so a fresh full-SHA pin installed the runtime and THEN failed at the skill clone. Now
# the skill-source checkout is fetched and checked out FIRST (init + fetch takes a
# branch, a tag or a full SHA), before uv is even bootstrapped, and the runtime is then
# installed from that same commit. A fresh home is built in a private stage and
# published by one rename only when complete, so a failed or interrupted run leaves no
# half-initialised home that a rerun would refuse, and deletes nothing it did not
# create; after publication, a later failure leaves a clean, valid checkout that a
# rerun accepts.
say "[1/4] resolving ${REF} from ${REPO}…"
# git's repository-redirecting environment would point every `git -C` below at some
# other repository (hook contexts, bare-repo dotfile setups); `git clone` ignored it.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_OBJECT_DIRECTORY || true
# A fresh home is BUILT in a private staging directory beside it and PUBLISHED with one
# rename only once the resolved commit is checked out. Cleanup only ever removes that
# private stage (an unguessable mktemp name this run created), never the home pathname,
# which another process could have replaced meanwhile. An existing checkout is updated in
# place exactly as before.
_stage=""
_remove_stage() {
    if [ -n "$_stage" ]; then rm -rf -- "$_stage"; fi
}
trap '_remove_stage' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
if [ -d "$HOME_DIR/.git" ]; then
    _work="$HOME_DIR"
else
    mkdir -p -- "$(dirname -- "$HOME_DIR")"
    _stage="$(mktemp -d -- "$(dirname -- "$HOME_DIR")/.agent-harness-install.XXXXXXXX")"
    _work="$_stage"
    git -C "$_work" init -q
    git -C "$_work" remote add origin "$REPO"
fi
# writeFetchHEAD is forced on: with a user `fetch.writeFetchHEAD=false`, a stale FETCH_HEAD
# from an earlier run would otherwise resolve as this ref.
if ! git -C "$_work" -c fetch.writeFetchHEAD=true fetch --depth 1 origin "$REF" ||
   ! RESOLVED="$(git -C "$_work" rev-parse --verify -q 'FETCH_HEAD^{commit}')"; then
    echo "ERROR: could not resolve ${REF} from ${REPO}; nothing was installed." >&2
    exit 1
fi
git -C "$_work" checkout --no-overwrite-ignore --detach -q "$RESOLVED"
if [ -n "$_stage" ]; then
    # Publish with an ATOMIC no-replace rename: GNU `mv -T -n` issues
    # renameat2(RENAME_NOREPLACE), so a home that appeared at any moment -- even an empty
    # directory created an instant before -- is refused, never replaced. `mv -n` exits 0
    # when it skips (coreutils 8.x), so success is judged by where the stage ended up.
    mv -T -n -- "$_stage" "$HOME_DIR" || true
    if [ -e "$_stage" ] ||
       [ "$(git -C "$HOME_DIR" rev-parse -q --verify HEAD 2>/dev/null)" != "$RESOLVED" ]; then
        echo "ERROR: ${HOME_DIR} appeared during installation; refusing to replace it." >&2
        exit 1
    fi
    _stage=""
fi
trap - EXIT INT TERM HUP
say "  ${REF} -> ${RESOLVED}"

# --- 2) uv (cross-OS official installer; no Homebrew dependency) -----------
if ! command -v uv >/dev/null 2>&1; then
    say "[2/4] installing uv (astral.sh official installer)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || { echo "ERROR: uv not on PATH after install; add ~/.local/bin to PATH and re-run." >&2; exit 1; }

# --- 3) phase-loop runtime CLI from the resolved commit -----------------------
say "[3/4] installing phase-loop-runtime ${RESOLVED} from ${REPO}…"
uv tool install --force "git+${REPO}@${RESOLVED}#subdirectory=phase-loop-runtime"
hash -r 2>/dev/null || true
export PATH="$HOME/.local/bin:$PATH"
phase-loop --version

# --- 4) workflow skills for each harness, from the resolved checkout ----------
say "[4/4] installing workflow skills (${HARNESSES}) from ${REF} (${RESOLVED})…"
for _h in $HARNESSES; do
    # An explicit AGENT_HARNESS_SKILL_DEST override is only honored for a single harness.
    if [ "$HARNESS" != all ] && [ -n "${AGENT_HARNESS_SKILL_DEST:-}" ]; then
        _dest="$AGENT_HARNESS_SKILL_DEST"
    else
        _dest="$(skill_dest "$_h")"
    fi
    mkdir -p "$_dest"
    phase-loop --repo "$HOME_DIR" install --harness "$_h" \
        --source "$HOME_DIR/phase-loop-skills" --destination "$_dest" --copy --apply
    echo "  ✓ ${_h} skills → ${_dest}"
done

say "Done — phase-loop CLI + skills (${HARNESSES}) installed from public agent-harness ${REF} (${RESOLVED})."
echo "  runtime : $(command -v phase-loop)  ($(phase-loop --version 2>/dev/null))"
echo "  bundle  : ${HOME_DIR}/phase-loop-skills"
# Report the update path from where THIS run's ref actually came, not from a proxy.
# resolve_ref's local-pin branch needs BOTH a file-backed $0 AND a sibling RELEASE_PIN;
# testing only [ -f "$0" ] misreports the documented fetch-to-a-file form (a real file
# with no RELEASE_PIN beside it), and an explicit --ref/AGENT_HARNESS_REF outranks both.
if [ -n "${AGENT_HARNESS_REF:-}" ] || [ -n "${REF_EXPLICIT:-}" ]; then
    echo "  update  : you pinned ${REF}; re-running keeps it. Drop the pin to follow releases."
elif [ -n "${REF_FROM_LOCAL_PIN:-}" ]; then
    echo "  update  : this ref came from ${REF_FROM_LOCAL_PIN}. git pull there FIRST, or re-running reinstalls ${REF}."
else
    echo "  update  : re-run (this run resolved ${REF} from the remote release pin)."
fi
echo "No fleet / 1Password / tailnet / dotfiles clone required."
