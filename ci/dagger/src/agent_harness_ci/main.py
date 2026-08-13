"""agent-harness heavy CI, executed in containers on the offload host.

The workflow decides *where* this runs (see the elig/offload/hosted/gate graph in
`.github/workflows/test.yml`); this module decides *what* runs, identically in
either place. Three properties are load-bearing and are asserted here rather than
assumed, because each one has a recorded failure mode behind it:

* **Per-container lane selection.** There is no `matrix.python-version` inside
  Dagger, so the two-lane chronology rule has to be reimplemented per container or
  the offload silently reintroduces three ~40-minute executions of the heavy node.
* **A complete `.git` object database.** The chronology proof walks real history
  and reads historical blobs. A commit-count probe passes on a blob-filtered
  clone, so the probe below touches every object `rev-list --objects` names.
* **Exported junit.** The two-lane plan's evidence contract says the retaining
  lanes emit junit; that contract has to survive the move off the hosted runner.
"""

import dagger
from dagger import dag, function, object_type

# The heavy CONFORM chronology node (~40 min). Two-lane rule: it runs in the 3.10
# container and in the Gate A stage, nowhere else.
CHRONOLOGY_NODE = (
    "tests/test_outside_agent_conform_evidence.py::"
    "test_mutation_definitions_are_frozen_but_not_executed_preimplementation"
)

# Oldest supported interpreter. It keeps the chronology node because the node
# drives version-sensitive subprocess machinery -- the 3.10-vs-3.12 egg-info
# divergence recorded in agent-harness#382.
CHRONOLOGY_PYTHON = "3.10"
PYTHON_VERSIONS = ("3.10", "3.11", "3.12")

# The suite needs a real git binary (the chronology proof shells out to it) and
# `git merge-tree --write-tree`, which is git >= 2.38. Debian bookworm ships 2.39.
#
BASE_PACKAGES = ["git", "ca-certificates"]

# A SECOND, higher interpreter must be on PATH. Several suite tests resolve an
# interpreter PIN (`automation.python: python3.12`) and assert the runtime honours
# it, so they need python3.12 present regardless of which interpreter runs pytest.
# A hosted GitHub runner satisfies that incidentally -- it ships a system
# python3.12 alongside whatever setup-python selected -- so the requirement is
# invisible there. A single-version container does not:
# `test_hotfix_threads_python_pin` failed on the first offloaded run with
# `suite interpreter unavailable: automation.python pin 'python3.12' not found on
# host` (exit 127).
#
# Debian bookworm has no python3.12 apt package (it ships 3.11), so this is taken
# from the official image rather than installed -- the same interpreter bytes the
# 3.12 lane itself runs, with no third-party PPA in the trust path.
#
# It is grafted in ONLY for the lanes that lack it. Doing it unconditionally broke
# the 3.12 lane on the third offloaded run: in the 3.12 base `/usr/local/bin/
# python3.12` IS the container's own interpreter and `python` -> `python3` ->
# `python3.12`, so the symlink hijacked `python` itself. `sys.prefix` flipped to
# /opt/python3.12 and `python -m pip install` wrote the console scripts to
# /opt/python3.12/bin, which is not on PATH -- pip said so in the run log, and
# `codex-phase-loop` then failed to spawn. The 3.10 and 3.11 lanes ran the same
# test green, which is what localises the fault to the graft.
PIN_INTERPRETER_IMAGE = "python:3.12-bookworm"
PIN_INTERPRETER_PATH = "/usr/local/bin/python3.12"
# The version whose own interpreter already satisfies the pin, so it must be left
# strictly alone. Derived from the image tag rather than restated.
PIN_INTERPRETER_VERSION = PIN_INTERPRETER_IMAGE.split(":")[1].split("-")[0]


@object_type
class AgentHarnessCi:
    """Containerised agent-harness CI stages."""

    def _base(self, source: dagger.Directory, python_version: str) -> dagger.Container:
        """A container with the repo mounted and the runtime installed."""
        container = (
            dag.container()
            .from_(f"python:{python_version}-bookworm")
            .with_exec(["apt-get", "update"])
            .with_exec(["apt-get", "install", "-y", "--no-install-recommends", *BASE_PACKAGES])
            # Cache pip across runs, keyed per interpreter so wheels never cross versions.
            .with_mounted_cache(
                "/root/.cache/pip", dag.cache_volume(f"pip-{python_version}")
            )
        )
        if python_version != PIN_INTERPRETER_VERSION:
            # The pinned second interpreter, copied from the official 3.12 image.
            # Skipped in the 3.12 lane, where the container's own interpreter
            # already satisfies the pin and grafting over it hijacks `python`.
            container = container.with_directory(
                "/opt/python3.12",
                dag.container().from_(PIN_INTERPRETER_IMAGE).directory("/usr/local"),
            ).with_exec(
                ["ln", "-sf", "/opt/python3.12/bin/python3.12", PIN_INTERPRETER_PATH]
            )
        return (
            container
            .with_mounted_directory("/src", source)
            .with_workdir("/src")
            .with_exec(
                [
                    "python", "-m", "pip", "install", "--quiet",
                    "./phase-loop-runtime[visual]", "pytest", "build==1.5.1",
                    "setuptools>=68",
                ]
            )
        )

    @function
    async def git_probe(self, source: dagger.Directory) -> str:
        """Prove the mounted source carries a COMPLETE object database.

        A commit-count check is not sufficient: a blob-filtered (`--filter=blob:none`)
        clone has every commit and almost no blobs, and the chronology proof reads
        historical blobs. `cat-file --batch-check` over `rev-list --objects` forces
        every named object to be resolved locally, so a partial clone fails here
        instead of deep inside an 80-minute proof.
        """
        return await (
            self._base(source, CHRONOLOGY_PYTHON)
            .with_exec(["git", "config", "--global", "--add", "safe.directory", "/src"])
            .with_exec(
                [
                    "bash", "-euo", "pipefail", "-c",
                    # Any unresolvable object makes `--batch-check` print "missing"
                    # and we fail on it explicitly; `rev-list --objects --all` names
                    # commits, trees and blobs alike.
                    # `rev-list --objects` prints "<sha> [path]" -- the path must be
                    # stripped or cat-file reads the whole line as one bad query and
                    # reports every pathed object "missing" on a HEALTHY clone.
                    'missing=$(git rev-list --objects --all '
                    "| awk '{print $1}' "
                    '| git cat-file --batch-check="%(objectname) %(objecttype)" '
                    '| grep -c missing || true); '
                    'if [ "$missing" != "0" ]; then '
                    '  echo "git object database is incomplete: $missing missing objects" >&2; '
                    '  exit 1; '
                    'fi; '
                    'echo "git object database complete: '
                    '$(git rev-list --objects --all | wc -l) objects resolved"',
                ]
            )
            .stdout()
        )

    def _suite(self, source: dagger.Directory, python_version: str) -> dagger.Container:
        """The standalone suite for one interpreter, with the two-lane selection."""
        keeps_chronology = python_version == CHRONOLOGY_PYTHON
        if keeps_chronology:
            selection = f'suite_args=("--junitxml=/junit/junit-py{python_version.replace(".", "")}.xml")'
        else:
            selection = f'suite_args=("--deselect={CHRONOLOGY_NODE}")'

        script = f"""
set -euo pipefail
git config --global --add safe.directory /src
cd /src/phase-loop-runtime
mkdir -p /junit

{selection}

# The deselect must never become a silent no-op: if the node is renamed,
# `--deselect` matches nothing and pytest says nothing. Assert collectability
# first, in every container, so a rename fails loudly in all three.
PYTHONPATH=src:tests python -m pytest --collect-only -q \\
  "{CHRONOLOGY_NODE}" >/dev/null

PYTHONPATH=src:tests python -m pytest -m "not dotfiles_integration" \\
  "${{suite_args[@]}}" \\
  --ignore tests/test_legible_roadmap_contract.py \\
  --ignore tests/test_legible_evidence.py

# The two frozen LEGIBLE files distinguish a canonical source checkout from an
# installed consumer; run them from a copied tests tree so this stage also
# exercises the standalone-consumer posture.
suite_root="$(mktemp -d)/phase-loop-runtime"
mkdir -p "$suite_root" "$(dirname "$suite_root")/specs"
cp -r tests "$suite_root/tests"
cp ../specs/phase-plans-v10.md "$(dirname "$suite_root")/specs/phase-plans-v10.md"
PYTHONPATH="$suite_root/tests" python -m pytest \\
  "$suite_root/tests/test_legible_roadmap_contract.py" \\
  "$suite_root/tests/test_legible_evidence.py" \\
  -m "not dotfiles_integration"
"""
        return self._base(source, python_version).with_exec(["bash", "-c", script])

    @function
    def suite(self, source: dagger.Directory, python_version: str) -> dagger.Container:
        """Run the standalone suite for one interpreter (3.10 keeps the chronology node)."""
        return self._suite(source, python_version)

    @function
    def gate_a(self, source: dagger.Directory) -> dagger.Container:
        """Run the Gate A clean-room stage (py3.12), which retains the chronology node."""
        script = """
set -euo pipefail
git config --global --add safe.directory /src
cd /src/phase-loop-runtime
mkdir -p /junit
export GATE_A_JUNIT=/junit/junit-gate-a.xml
bash scripts/gate_a_cleanroom.sh
"""
        return self._base(source, "3.12").with_exec(["bash", "-c", script])

    @function
    async def junit(self, source: dagger.Directory) -> dagger.Directory:
        """Export the junit evidence from the retaining stages.

        The two-lane plan requires the chronology node's per-run verdict to be
        durable. Returning a Directory lets the workflow `export` it and upload it
        as an artifact, exactly as the hosted lanes do.
        """
        py310 = self._suite(source, CHRONOLOGY_PYTHON)
        gate = self.gate_a(source)
        return (
            dag.directory()
            .with_directory("py310", py310.directory("/junit"))
            .with_directory("gate-a", gate.directory("/junit"))
        )

    @function
    async def all(self, source: dagger.Directory) -> str:
        """The full offloaded gate: object-database probe, three suites, Gate A.

        Ordered cheapest-falsifier-first: the probe costs seconds and catches the
        incomplete-clone class before an ~80-minute proof is spent on it.
        """
        results = [await self.git_probe(source)]
        for version in PYTHON_VERSIONS:
            await self._suite(source, version).sync()
            results.append(f"suite py{version}: ok")
        await self.gate_a(source).sync()
        results.append("gate-a: ok")
        return "\n".join(results)
