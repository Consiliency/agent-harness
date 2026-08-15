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
REPO_ROOT="$(cd "$PKG_ROOT/.." && pwd)"

# The dotfiles checkout root (must NOT appear in any resolved runtime path).
#
# Found by searching UP for the dotfiles markers, never by assuming a depth. A
# fleet checkout nests this repo two levels under the dotfiles tree, but that is
# a coincidence of one layout: off a fleet checkout the fixed `$PKG_ROOT/../..`
# guess names some unrelated ancestor, and in the containerised offload (repo
# mounted at /src) it resolves to `/` -- at which point EVERY path is trivially
# "under the dotfiles checkout", including the isolated venv, and the probe
# fails a clean room that is in fact clean (agent-harness#536).
#
# With no dotfiles tree above the repo there is nothing to prove independence
# *of* except the source checkout itself, so the sentinel degrades to the repo
# root: strictly stronger than the old ancestor guess (which named a directory
# that merely contained the repo), and never degenerate.
is_dotfiles_root() {
  [ -d "$1/claude-config" ] && [ -f "$1/bootstrap.sh" ]
}

DOTFILES_ROOT="$REPO_ROOT"
_candidate="$REPO_ROOT"
while [ "$_candidate" != "/" ]; do
  if is_dotfiles_root "$_candidate"; then
    DOTFILES_ROOT="$_candidate"
    break
  fi
  _candidate="$(dirname "$_candidate")"
done
unset _candidate

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Gate A's per-node evidence. It must live OUTSIDE $WORK: the EXIT trap above wipes
# that tree, and the suite runs under `env -i`, so the destination cannot travel as
# an environment variable either -- it is passed positionally into the heredoc and
# forwarded to pytest as --junitxml. Defaults beside the package so a local run also
# leaves the artifact behind; CI overrides it to a runner path it can upload.
GATE_A_JUNIT="${GATE_A_JUNIT:-$PKG_ROOT/gate-a-standalone.junit.xml}"
mkdir -p "$(dirname "$GATE_A_JUNIT")"

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
# locked-down index here. Pull in the `visual` extra (Pillow) too -- the full
# standalone suite run below (step 4) includes the FAV visual-evidence gate's
# decode-requiring tests, which need Pillow installed in THIS venv or they'd
# error at test time (agent-harness#91 round-4 CR).
env -u PYTHONPATH "$PY" -m pip install --quiet --no-compile "${WHEEL}[visual]" >/dev/null

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

# --- Full standalone test suite (TESTDECOUPLE) -------------------------------
# After the import/execute/bridge smoke, run the FULL runtime test suite against
# the INSTALLED wheel with no dotfiles tree reachable. The tests/ tree is copied
# under $WORK (whose parents are not a dotfiles checkout), so any test that still
# resolves `parents[3]` overshoots to a marker-less dir and the dotfiles tree
# detector reports absent. `-m "not dotfiles_integration"` deselects the
# integration bucket (which legitimately needs the fleet skill-source/profile
# overlay); the module-level skip guards keep import-time fleet readers from
# erroring collection. The gate FAILS on any non-integration failure.
#
# Skippable via PHASE_LOOP_SKIP_GATE_A_SUITE=1 for the rare host without pytest
# (recorded, not silent) — the smoke above still runs.
if [ "${PHASE_LOOP_SKIP_GATE_A_SUITE:-0}" = "1" ]; then
  echo "-- full standalone suite: SKIPPED (PHASE_LOOP_SKIP_GATE_A_SUITE=1) --"
else
  echo "-- full standalone suite: pytest -m 'not dotfiles_integration' vs installed wheel --"
  env -u PYTHONPATH "$PY" -m pip install --quiet pytest build "setuptools>=68" >/dev/null
  set +e
  env -u PYTHONPATH PYTHONNOUSERSITE=1 "$PY" - <<'PYEOF'
import importlib.util
raise SystemExit(
    0
    if importlib.util.find_spec(
        "phase_loop_runtime.conformance.outside_agent_conform_evidence"
    ) is not None
    else 10
)
PYEOF
  CONFORM_CAPABILITY_STATUS=$?
  set -e
  # Seeded unconditionally: the capability-absent branch below never repopulates
  # this array, and the junit evidence must be emitted in either posture.
  CONFORM_STANDALONE_DESELECTS=("--junitxml=$GATE_A_JUNIT")
  if [ "$CONFORM_CAPABILITY_STATUS" -eq 0 ]; then
    # CONFORM's final mutation/lifecycle proof needs source and Git history as
    # immutable data. A sparse private clone supplies those bytes while scripts
    # stay absent and PYTHONPATH still resolves production from the installed wheel.
    STANDALONE_ROOT="$WORK/standalone"
    SOURCE_REPO="$PKG_ROOT/.."
    SOURCE_HEAD="$(git -C "$SOURCE_REPO" rev-parse HEAD)"
    git clone --quiet --no-local --no-checkout "$SOURCE_REPO" "$STANDALONE_ROOT"
    git -C "$STANDALONE_ROOT" sparse-checkout init --no-cone
    git -C "$STANDALONE_ROOT" sparse-checkout set \
      /phase-loop-runtime/tests/ \
      /phase-loop-runtime/src/ \
      /phase-loop-runtime/protocol/ \
      /phase-loop-runtime/pyproject.toml \
      /phase-loop-runtime/MANIFEST.in \
      /phase-loop-runtime/README.md \
      /docs/ \
      /specs/ \
      /plans/phase-plan-v10-CONFORM.md \
      /plans/phase-plan-v10-GOVLEAN.md \
      /skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py \
      /CHANGELOG.md
    git -C "$STANDALONE_ROOT" checkout --quiet --detach "$SOURCE_HEAD"
    SUITE_TREE="$STANDALONE_ROOT/phase-loop-runtime"
    # tests/__init__.py prepends a sibling src tree unless that exact path is
    # already present. Add it after site-packages so candidate source remains
    # immutable evidence while the installed wheel retains import authority in
    # the outer suite process. Test-owned mutation and EC children deliberately
    # execute candidate or mutant source and bind that source identity as evidence.
    env -u PYTHONPATH "$PY" - "$SUITE_TREE/src" <<'PYEOF'
import site
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve()
site_packages = Path(site.getsitepackages()[0]).resolve()
(site_packages / "gate_a_candidate_source_data.pth").write_text(
    str(source) + "\n", encoding="utf-8"
)
PYEOF
    if ! env -i \
        HOME="$CLEAN_HOME" \
        PATH="$VENV/bin:/usr/bin:/bin" \
        PYTHONNOUSERSITE=1 \
        PYTHONDONTWRITEBYTECODE=1 \
        PYTHONPATH="$SUITE_TREE/tests" \
        "$PY" - "$SUITE_TREE" <<'PYEOF'
import site
import sys
from pathlib import Path

suite = Path(sys.argv[1]).resolve()
source = (suite / "src").resolve()
site_packages = Path(site.getsitepackages()[0]).resolve()
import phase_loop_runtime

runtime_file = Path(phase_loop_runtime.__file__).resolve()
if runtime_file.is_relative_to(suite):
    raise SystemExit("candidate source shadowed the installed wheel")
if str(source) not in sys.path:
    raise SystemExit("candidate source evidence path is absent")
if sys.path.index(str(site_packages)) >= sys.path.index(str(source)):
    raise SystemExit("candidate source precedes installed site-packages")
PYEOF
    then
      echo "GATE-A FAIL: CONFORM candidate source can shadow the installed wheel" >&2
      exit 1
    fi
    # The four final-document nodes consume runner-owned B0/B2 evidence that a
    # standalone wheel gate cannot manufacture. CONFORM's frozen A2 selector
    # excludes the same exact identities; every other non-integration test runs.
    CONFORM_STANDALONE_DESELECTS=(
      "${CONFORM_STANDALONE_DESELECTS[@]}"
      "--rootdir=$SUITE_TREE"
      "--deselect=tests/test_outside_agent_contract_drift.py::test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes"
      "--deselect=tests/test_outside_agent_release_surface.py::test_v7_disposition_records_merged_contract_and_final_installed_behavior"
      "--deselect=tests/test_outside_agent_release_surface.py::test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary"
      "--deselect=tests/test_outside_agent_release_surface.py::test_public_docs_point_to_handoff_without_claiming_release_dispatch"
    )
    echo "-- full standalone suite: CONFORM repository evidence staged at $SOURCE_HEAD --"
  elif [ "$CONFORM_CAPABILITY_STATUS" -eq 10 ]; then
    SUITE_TREE="$WORK/standalone/phase-loop-runtime"
    mkdir -p "$SUITE_TREE"
    cp -r "$PKG_ROOT/tests" "$SUITE_TREE/tests"
    # Repo-contract tests resolve canonical roadmap fixtures from the monorepo
    # root (tests/../..). Keep those immutable inputs available without exposing
    # the source package tree to the installed-wheel test process.
    cp -r "$PKG_ROOT/../specs" "$WORK/standalone/specs"
  else
    echo "GATE-A FAIL: CONFORM capability probe errored ($CONFORM_CAPABILITY_STATUS)" >&2
    exit 1
  fi
  # Sanity: the copied tree's parents[3] must NOT be a dotfiles checkout.
  if env -i "$PY" - "$SUITE_TREE/tests" <<'PYEOF'
import sys
from pathlib import Path
root = Path(sys.argv[1], "x").resolve().parents[3]
present = (root / "claude-config").is_dir() and (root / "bootstrap.sh").is_file()
sys.exit(1 if present else 0)
PYEOF
  then
    :
  else
    echo "GATE-A FAIL: standalone suite tree resolves a dotfiles checkout at parents[3] -- not a clean room" >&2
    exit 1
  fi
  # Clean env: empty HOME, user-site disabled, only the tests dir + the installed
  # wheel on the path. No PYTHONPATH to a source tree (would shadow the wheel).
  if ! env -i \
      HOME="$CLEAN_HOME" \
      PATH="$VENV/bin:/usr/bin:/bin" \
      PYTHONNOUSERSITE=1 \
      PYTHONDONTWRITEBYTECODE=1 \
      PYTHONPATH="$SUITE_TREE/tests" \
      "$PY" - "$SUITE_TREE" "${CONFORM_STANDALONE_DESELECTS[@]}" <<'PYEOF'
import sys
from pathlib import Path

suite = Path(sys.argv[1]).resolve()
extra_pytest_args = sys.argv[2:]
import phase_loop_runtime

runtime_file = Path(phase_loop_runtime.__file__).resolve()
if runtime_file.is_relative_to(suite):
    raise SystemExit("candidate source shadowed the installed wheel before pytest")

import pytest

raise SystemExit(
    pytest.main(
        [
            str(suite / "tests"),
            "-q",
            "-p",
            "no:cacheprovider",
            "-m",
            "not dotfiles_integration",
            *extra_pytest_args,
        ]
    )
)
PYEOF
  then
    echo "GATE-A FAIL: standalone test suite is not green (see failures above)" >&2
    exit 1
  fi
  echo "-- full standalone suite: GREEN --"
fi

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
