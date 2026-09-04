"""agent-harness heavy CI, executed in containers on the offload host.

The workflow decides *where* this runs (see the elig/offload/hosted/gate graph in
`.github/workflows/test.yml`); this module decides *what* runs, identically in
either place. Three properties are load-bearing and are asserted here rather than
assumed, because each one has a recorded failure mode behind it:

* **Per-container lane selection.** There is no `matrix.python-version` inside
  Dagger, so the chronology selection has to be reimplemented per container or
  the offload silently reintroduces three ~50-minute executions of the heavy node.
  Whether the node runs AT ALL in this execution is decided outside (the
  ``chronology`` argument, computed by ``ci/chronology-scope.sh``): it is ~88% of
  the per-PR wall clock and its verdict depends only on an enumerable set of
  inputs, so a PR touching none of them does not pay for it. Push-to-main,
  nightly and dispatch always retain it.
* **A complete `.git` object database.** The chronology proof walks real history
  and reads historical blobs. A commit-count probe passes on a blob-filtered
  clone, so the probe below touches every object `rev-list --objects` names.
* **Exported junit.** The two-lane plan's evidence contract says the retaining
  lanes emit junit; that contract has to survive the move off the hosted runner.
  It is a byproduct of `all`, never a second `dagger call` -- a separate call is a
  separate session, and on a cold engine it re-executed the two heaviest stages
  and blew the job budget (agent-harness#550).
"""

import asyncio

import dagger
from dagger import dag, function, object_type

# The heavy CONFORM chronology node (~50 min). When retained, it runs in the 3.10
# container and in the Gate A stage, nowhere else. Kept in lockstep with
# ci/chronology-scope.sh (`--node`) by tests/test_ci_chronology_scope.py.
CHRONOLOGY_NODE = (
    "tests/test_outside_agent_conform_evidence.py::"
    "test_mutation_definitions_are_frozen_but_not_executed_preimplementation"
)

# Oldest supported interpreter. It keeps the chronology node because the node
# drives version-sensitive subprocess machinery -- the 3.10-vs-3.12 egg-info
# divergence recorded in agent-harness#382.
CHRONOLOGY_PYTHON = "3.10"
PYTHON_VERSIONS = ("3.10", "3.11", "3.12")

# The per-stage verdict roll-up, written into the exported evidence directory
# alongside the junit. `all` returns a Directory, so this is where the roll-up
# that used to be its stdout now lives.
VERDICTS_FILE = "verdicts.txt"

# The suite needs a real git binary (the chronology proof shells out to it) and
# `git merge-tree --write-tree`, which is git >= 2.38. Debian bookworm ships 2.39.
#
BASE_PACKAGES = ["git", "ca-certificates", "jq"]  # jq: ci/main-red.sh tests run a jq-backed gh stub

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

    def _base(
        self,
        source: dagger.Directory,
        python_version: str,
        cache_scope: str = "suite",
    ) -> dagger.Container:
        """A container with the repo mounted and the runtime installed.

        ``cache_scope`` keys the pip cache. The stages run CONCURRENTLY (see
        ``all``), and a Dagger cache volume is SHARED by default, so two stages on
        the same interpreter would otherwise have two pips writing one cache
        directory at once. Giving Gate A its own scope removes that class outright
        rather than reasoning about pip's atomicity.
        """
        container = (
            dag.container()
            .from_(f"python:{python_version}-bookworm")
            .with_exec(["apt-get", "update"])
            .with_exec(["apt-get", "install", "-y", "--no-install-recommends", *BASE_PACKAGES])
            # Cache pip across runs, keyed per interpreter so wheels never cross
            # versions, and per scope so concurrent stages never share one volume.
            .with_mounted_cache(
                "/root/.cache/pip",
                dag.cache_volume(f"pip-{python_version}-{cache_scope}"),
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

    def _suite(
        self, source: dagger.Directory, python_version: str, chronology: bool = True
    ) -> dagger.Container:
        """The standalone suite for one interpreter, with the chronology selection.

        The retaining lane always writes junit, even when ``chronology`` is off:
        the exported evidence then WITNESSES the deselection (the node id is absent
        from the xml) instead of the artifact silently disappearing.
        """
        keeps_chronology = chronology and python_version == CHRONOLOGY_PYTHON
        suite_args = []
        if python_version == CHRONOLOGY_PYTHON:
            suite_args.append(f"--junitxml=/junit/junit-py{python_version.replace('.', '')}.xml")
        if not keeps_chronology:
            suite_args.append(f"--deselect={CHRONOLOGY_NODE}")
        selection = "suite_args=(" + " ".join(f'"{a}"' for a in suite_args) + ")"
        if python_version == CHRONOLOGY_PYTHON:
            # The junit must WITNESS the decision: the node present (ran, passed)
            # when retained, absent when deselected. A deselect that silently
            # matched nothing, or a retain that skipped, fails here, not never.
            expect = "present" if keeps_chronology else "absent"
            witness = f"""
python scripts/chronology_witness.py \\
  --junit /junit/junit-py{python_version.replace(".", "")}.xml --node "$CHRONOLOGY_NODE" --expect {expect}
"""
        else:
            witness = ""

        script = f"""
set -euo pipefail
git config --global --add safe.directory /src
cd /src/phase-loop-runtime
mkdir -p /junit

CHRONOLOGY_NODE="{CHRONOLOGY_NODE}"
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
{witness}
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
    def suite(
        self, source: dagger.Directory, python_version: str, chronology: bool = True
    ) -> dagger.Container:
        """Run the standalone suite for one interpreter (3.10 keeps the chronology node)."""
        return self._suite(source, python_version, chronology)

    @function
    def gate_a(self, source: dagger.Directory, chronology: bool = True) -> dagger.Container:
        """Run the Gate A clean-room stage (py3.12), which retains the chronology node.

        With ``chronology`` off the clean-room script deselects the node itself
        (``GATE_A_DESELECT_CHRONOLOGY=1``) and proves the deselection against its
        own junit, so the skip is witnessed at the same place the run would be.
        """
        deselect = "" if chronology else "export GATE_A_DESELECT_CHRONOLOGY=1\n"
        script = f"""
set -euo pipefail
git config --global --add safe.directory /src
cd /src/phase-loop-runtime
mkdir -p /junit
export GATE_A_JUNIT=/junit/junit-gate-a.xml
{deselect}bash scripts/gate_a_cleanroom.sh
"""
        return self._base(source, "3.12", cache_scope="gate-a").with_exec(
            ["bash", "-c", script]
        )

    @function
    async def all(self, source: dagger.Directory, chronology: bool = True) -> dagger.Directory:
        """The full offloaded gate: object-database probe, three suites, Gate A.

        ``chronology`` is the scope decision from ``ci/chronology-scope.sh``. It
        defaults to True so a caller that forgets to decide gets the expensive
        answer, and the decision is recorded in ``verdicts.txt`` so the artifact
        says which kind of run it witnesses.

        The probe runs FIRST and alone: it costs seconds and catches the
        incomplete-clone class before ~40 minutes of chronology proof is spent on
        it, which is the whole reason it exists. Gate A reads history too, so it
        must not start before the probe clears either.

        The four heavy stages then run CONCURRENTLY. Run sequentially they cost
        43:32 + 4:41 + 4:54 + Gate A -- over the 100-minute job budget, and slower
        end-to-end than the hosted lanes, which run in parallel (hosted total is
        ~87 min, with Gate A the long pole at 86:36). Concurrently the wall clock
        is max(py3.10, Gate A), which is what makes the offload a win rather than
        a rearrangement. The host has 32 cores.

        Failures are AGGREGATED, not short-circuited. Sequential composition
        aborted at the first red, so each of the first three offloaded runs cost
        ~45 minutes to surface exactly ONE defect -- and Gate A was never reached
        at all until run 4. Gathering with ``return_exceptions=True`` reports every
        stage's verdict from a single run.

        The junit evidence is a BYPRODUCT of those same stage executions, which is
        why this returns a Directory rather than a verdict string. It used to be a
        separate ``junit`` function that re-declared ``suite(source, "3.10")`` and
        ``gate_a(source)``, and ``ci/offload-gate.sh`` reached it in a SECOND
        ``dagger call``. A second call is a second session with its own host
        upload of ``--source``, so the stages dedupe only if the upload hashes
        identically AND the engine still holds their layers. When both held (warm
        engine, run 6 and the preflight) the export returned in 5 seconds; when
        they did not, the export re-ran the two heaviest stages. Run 31751696509
        is the record: Gate A ran twice (50m59s and 49m44s) and py3.10 twice
        (41m55s, plus an instance that never completed), and the job hit its
        120-minute ceiling looking like a hang. Reading ``/junit`` off the
        containers this function already awaited puts every stage in ONE session
        as ONE DAG node, so re-execution is impossible by construction instead of
        prevented by cache luck -- and the exported artifact provably comes from
        the execution that gated the run.
        """
        results = [
            f"chronology: {'retained' if chronology else 'deselected'}",
            await self.git_probe(source),
        ]

        # (label, junit export subdirectory or None, container). Only the two
        # chronology-retaining stages emit junit -- also when the node is
        # deselected, so the export witnesses its absence; the export names are
        # derived so they cannot drift from the lane they came from.
        stages: list[tuple[str, str | None, dagger.Container]] = [
            *(
                (
                    f"suite py{v}",
                    f"py{v.replace('.', '')}" if v == CHRONOLOGY_PYTHON else None,
                    self._suite(source, v, chronology),
                )
                for v in PYTHON_VERSIONS
            ),
            ("gate-a", "gate-a", self.gate_a(source, chronology)),
        ]
        outcomes = await asyncio.gather(
            *(container.sync() for _, _, container in stages),
            return_exceptions=True,
        )

        failures: list[str] = []
        # The EVALUATED container per stage, keyed by its export subdirectory.
        # `sync()` returns the container it forced, so the junit below is read
        # from the instance whose verdict is recorded above -- not from a
        # re-declared one that a cold engine would execute again.
        executed: list[tuple[str, dagger.Container]] = []
        for (name, junit_dir, _), outcome in zip(stages, outcomes):
            if isinstance(outcome, BaseException):
                failures.append(f"{name}: FAILED")
                results.append(f"{name}: FAILED -- {outcome}")
            else:
                results.append(f"{name}: ok")
                if junit_dir is not None:
                    executed.append((junit_dir, outcome))
        if failures:
            # Every verdict is already in `results`; surface the roll-up too, so a
            # multi-stage red is legible from the exception line alone.
            raise RuntimeError(
                "offloaded stages failed: "
                + ", ".join(failures)
                + "\n"
                + "\n".join(results)
            )

        # The verdict roll-up used to be this function's stdout. It travels with
        # the junit now so it is still readable in the job log (offload-gate.sh
        # prints it) and, unlike stdout, it lands in the uploaded artifact.
        evidence = dag.directory().with_new_file(
            VERDICTS_FILE, "\n".join(results) + "\n"
        )
        for junit_dir, container in executed:
            evidence = evidence.with_directory(junit_dir, container.directory("/junit"))
        return evidence
