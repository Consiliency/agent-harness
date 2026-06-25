#!/usr/bin/env bash
# Gate A (DECOUPLE / IF-0-DECOUPLE-1): mechanical clean-room independence proof.
#
# Build a wheel, install it into an isolated venv with NO dotfiles checkout
# reachable and user-site disabled, then assert that:
#   - the runtime imports and `phase-loop --version` works (gp bridge smoke);
#   - version / status / dry-run / execute --bundle all run against that exact
#     wheel artifact;
#   - no resolved BAML / skill-root / manifest / import path points under the
#     dotfiles checkout; everything resolves under the isolated site-packages.
#
# The phase PASSES iff this script exits 0. Usable standalone or via
# tests/test_gate_a_wheel_isolation.py.
set -euo pipefail

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The dotfiles checkout root (must NOT appear in any resolved runtime path).
DOTFILES_ROOT="$(cd "$PKG_ROOT/../.." && pwd)"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== Gate A clean-room =="
echo "package root : $PKG_ROOT"
echo "dotfiles root: $DOTFILES_ROOT"
echo "workdir      : $WORK"

# --- 1. Build the wheel -----------------------------------------------------
DIST="$WORK/dist"
mkdir -p "$DIST"
( cd "$PKG_ROOT" && python3 -m build --wheel --outdir "$DIST" ) >/dev/null
WHEEL="$(ls "$DIST"/*.whl | head -1)"
echo "wheel        : $WHEEL"

# --- 2. Isolated venv (no user-site, no dotfiles on sys.path) ---------------
VENV="$WORK/venv"
python3 -m venv "$VENV"
# shellcheck disable=SC1091
PY="$VENV/bin/python"
# Drop PYTHONPATH for pip: a source-tree PYTHONPATH (e.g. PYTHONPATH=src under
# pytest) makes pip treat phase_loop_runtime as already-satisfied and SKIP the
# wheel install, leaving the venv empty.
env -u PYTHONPATH "$PY" -m pip install --quiet --upgrade pip >/dev/null
# Install the wheel plus its declared runtime deps from the ambient environment
# cache. The clean-room invariant is enforced by env at *run* time, not by a
# locked-down index here.
env -u PYTHONPATH "$PY" -m pip install --quiet "$WHEEL" >/dev/null

# The non-empty profile_commands group must now actually ship in the installed
# dist-info (empty groups were dropped by setuptools before Option A).
# env -u PYTHONPATH + PYTHONNOUSERSITE so this resolves the VENV's dist-info, not a
# source-tree .egg-info (PYTHONPATH=src under pytest) or the stale ~/.local install.
DISTINFO_EP="$(env -u PYTHONPATH PYTHONNOUSERSITE=1 "$PY" - <<'PYEOF'
import importlib.metadata as m
d = m.distribution("phase-loop-runtime")
print(d.locate_file(f"{d._path.name}/entry_points.txt"))
PYEOF
)"
if ! grep -q "phase_loop_runtime.profile_commands" "$DISTINFO_EP" 2>/dev/null; then
  echo "GATE-A FAIL: installed dist-info has no phase_loop_runtime.profile_commands group ($DISTINFO_EP)" >&2
  exit 1
fi
echo "entry_points : $DISTINFO_EP (profile_commands group present)"

# --- 3. Minimal valid repo OUTSIDE the dotfiles checkout --------------------
CLEAN_HOME="$WORK/home"
mkdir -p "$CLEAN_HOME"
PROBE="$PKG_ROOT/scripts/_gate_a_probe.py"
BUNDLE="$PKG_ROOT/tests/fixtures/phase_loop_pipeline_bundle/minimal-phase-source-bundle.json"

make_rundir() {
  local rd="$1"
  mkdir -p "$rd/specs" "$rd/plans"
  git -C "$rd" init -q
  git -C "$rd" config user.email "gate-a@example.com"
  git -C "$rd" config user.name "Gate A"
  git -C "$rd" config commit.gpgsign false
  cat > "$rd/specs/phase-plans-v1.md" <<'ROADMAP'
# Phase Plan v1

## GATEA — Clean-room smoke phase

- Depends on: (none)
ROADMAP
  cat > "$rd/plans/phase-plan-v1-GATEA.md" <<'PLAN'
---
phase: GATEA
roadmap: specs/phase-plans-v1.md
---
# GATEA
PLAN
  git -C "$rd" add -A
  git -C "$rd" commit -qm "gate-a fixture"
}

run_probe() {  # $1=rundir  $2=expect(present|absent)
  # Hard clean-room env: empty HOME (stale ~/.local cannot leak), PYTHONNOUSERSITE,
  # PATH/PYTHONPATH cleared, cwd outside dotfiles. PHASE_LOOP_PROFILE_PLUGINS is
  # deliberately NOT set: command presence must come from the installed dist-info
  # entry point, not an env opt-in.
  env -i \
    HOME="$CLEAN_HOME" \
    PATH="$VENV/bin:/usr/bin:/bin" \
    PYTHONNOUSERSITE=1 \
    DOTFILES_ROOT="$DOTFILES_ROOT" \
    GATE_A_BUNDLE="$BUNDLE" \
    GATE_A_RUNDIR="$1" \
    GATE_A_EXPECT_COMMANDS="$2" \
    "$PY" "$PROBE"
}

# --- Config 2 (default fleet install): commands PRESENT, paths clean ----------
RUNDIR_PRESENT="$WORK/run-present"
make_rundir "$RUNDIR_PRESENT"
echo "-- config: profile plugin registered (fleet install) --"
run_probe "$RUNDIR_PRESENT" present

# --- Config 1 (the seam): strip the group from the venv -> commands ABSENT ----
# Prove the seam against the ARTIFACT: removing the profile_commands group from the
# installed entry_points.txt makes the dotfiles commands disappear (env unset alone
# would not, since they load from dist-info, not the env).
"$PY" - "$DISTINFO_EP" <<'PYEOF'
import sys, configparser, io
path = sys.argv[1]
cp = configparser.ConfigParser()
cp.read(path)
if cp.has_section("phase_loop_runtime.profile_commands"):
    cp.remove_section("phase_loop_runtime.profile_commands")
buf = io.StringIO()
cp.write(buf)
open(path, "w").write(buf.getvalue())
PYEOF
RUNDIR_ABSENT="$WORK/run-absent"
make_rundir "$RUNDIR_ABSENT"
echo "-- config: profile_commands group stripped (seam) --"
run_probe "$RUNDIR_ABSENT" absent

echo "== Gate A PASSED =="
