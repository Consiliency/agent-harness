"""SEATS CLAUDE, EC-CLAUDE-4 and EC-CLAUDE-6: the ratification-order audit.

Every control enters through ``audit-order`` (the CLI's ``main``, or the module run as a
process) on a disposable git tree with a base and a head commit, and each must fail. The
cited PR's merge state is the only stand-in: the CLI's read-only GitHub lookup is replaced
by a fixed table, so no control needs the network.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from phase_loop_runtime import claude_seat_transport as ct

MERGED = {1775, 1901, 1902}

RECORD_HEAD = (
    "# Decision note\n\n"
    "## 4. EC-REVIEWTRUTH-15 ratification statement\n\nStage 1b.\n\n"
    "## 4a. Amendment to §4, proposed 2026-10-20: the jailed Claude seat\n\nPrint, explicit.\n\n"
    "## 5. Relation to v10 and v11\n\nUnchanged.\n"
)
# Appended sections follow the last line directly: a blank separator would change the
# previous section's bytes, and sections are append-only.
SDK_SECTION = "## 4b. OD-3a: the jailed Claude transports\n\nThe amendment.\n"


def od3b(letter: str, value: str) -> str:
    line = ("**Jailed Claude default:** none admitted" if value == "none"
            else f"**Jailed Claude default:** `{value}`")
    return f"## 4{letter}. OD-3b: the jailed Claude default\n\n{line}\n\nCites W0.\n"


def digest(record: str, section: str) -> str:
    raw = ct.section_bytes(record.encode(), section)
    assert raw is not None
    return hashlib.sha256(raw).hexdigest()


def citation(record: str, section: str, pr: int, *, sha: str | None = None) -> str:
    return (f'RecordCitation("{ct.DECISION_RECORD}", "{section}", '
            f'"{sha or digest(record, section)}", "agent-harness#{pr}")')


def transport_source(default: str = "tui", authority: str = "None") -> str:
    return (f'JAILED_CLAUDE_DEFAULT: ClaudeTransport = "{default}"\n'
            f"JAILED_DEFAULT_AUTHORITY: RecordCitation | None = {authority}\n")


def module_source(admitted: bool, activation: str | None) -> str:
    return f"ADMITTED = {admitted}\n" + (f"ACTIVATION = {activation}\n" if activation else "")


CARD_OK = ("# Card\n\n**Jailed Claude default:** `print` -- chosen by OD-3b; runs on open egress "
           "until CLAUDENET exits; awaits its row window.\n")


class Tree:
    """A disposable repository: ``commit(files)`` writes and commits, returning the SHA."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@e.st"], ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(root), *args], check=True)
        self.files: dict[str, str] = {}

    def commit(self, raw: dict[str, str | None] | None = None,
               links: dict[str, str] | None = None, **changes: str | None) -> str:
        paths = {"record": ct.DECISION_RECORD, "transport": ct.TRANSPORT_SOURCE,
                 "print": ct.MODULE_SOURCES["print"], "sdk": ct.MODULE_SOURCES["sdk"],
                 "card": ct.CARD}
        for relpath, content in [*((paths[k], v) for k, v in changes.items()),
                                 *(raw or {}).items()]:
            path = self.root / relpath
            if content is None:
                path.unlink(missing_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        for relpath, target in (links or {}).items():
            path = self.root / relpath
            path.unlink(missing_ok=True)
            path.symlink_to(target)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "commit.gpgsign=false", "commit",
                        "-qm", "x", "--allow-empty"], check=True)
        return subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()


def audit(tree: Tree, base: str | None, head: str, *, pr: int = 1999,
          event_base: str | None = None, capsys=None) -> int:
    argv = ["audit-order", "--repo", str(tree.root), "--head", head, "--pr", str(pr)]
    if base is not None:
        argv += ["--base", base]
    if event_base is not None:
        event = tree.root.parent / f"event-{event_base[:8]}.json"
        event.write_text(json.dumps({"pull_request": {"number": pr, "base": {"sha": event_base}}}))
        argv += ["--event", str(event)]
    return ct.main(argv, pr_merged=lambda n: n in MERGED)


@pytest.fixture
def tree(tmp_path) -> Tree:
    return Tree(tmp_path / "repo")


@pytest.fixture
def seam(tree) -> str:
    """The base of every control: the record with §4a, the seam with the TUI default."""
    return tree.commit(record=RECORD_HEAD, transport=transport_source(),
                       print=module_source(False, None), sdk=module_source(False, None))


# --------------------------------------------------------------------------------------
# What must pass.
# --------------------------------------------------------------------------------------

def test_the_print_landing_ordered_by_content_passes(tree, seam):
    head = tree.commit(print=module_source(True, citation(RECORD_HEAD, "4a", 1775)))
    assert audit(tree, seam, head, event_base=seam) == 0


def test_the_seam_landing_onto_a_tree_without_it_passes(tree):
    base = tree.commit(record=RECORD_HEAD)
    head = tree.commit(transport=transport_source(), print=module_source(False, None),
                       sdk=module_source(False, None))
    assert audit(tree, base, head) == 0


def test_a_records_only_landing_passes(tree, seam):
    head = tree.commit(record=RECORD_HEAD + SDK_SECTION)
    assert audit(tree, seam, head) == 0


def test_a_recorded_but_unshipped_od3b_value_passes(tree, seam):
    record = RECORD_HEAD + SDK_SECTION + od3b("c", "print")
    base = tree.commit(record=record)
    head = tree.commit(card="# Card\n")  # an unrelated later landing
    assert audit(tree, base, head) == 0


def test_a_switch_citing_the_latest_od3b_section_passes(tree, seam):
    record = RECORD_HEAD + od3b("c", "print")
    base = tree.commit(record=record, print=module_source(True, citation(RECORD_HEAD, "4a", 1775)))
    head = tree.commit(transport=transport_source("print", citation(record, "4c", 1902)),
                       card=CARD_OK)
    assert audit(tree, base, head) == 0


def test_a_tui_default_may_cite_an_od3b_section(tree, seam):
    record = RECORD_HEAD + od3b("c", "none")
    base = tree.commit(record=record)
    head = tree.commit(transport=transport_source("tui", citation(record, "4c", 1902)))
    assert audit(tree, base, head) == 0


def test_the_cli_runs_as_a_process_from_a_bare_checkout(tree, seam):
    head = tree.commit(card="# Card\n")
    runtime = Path(ct.__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(runtime)}
    done = subprocess.run([sys.executable, "-m", "phase_loop_runtime.claude_seat_transport",
                           "audit-order", "--repo", str(tree.root), "--base", seam, "--head",
                           head], capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "audit-order: OK"


# --------------------------------------------------------------------------------------
# The controls: each must fail.
# --------------------------------------------------------------------------------------

def test_an_unset_base_fails(tree, seam):
    head = tree.commit(card="# Card\n")
    assert audit(tree, None, head) == 1
    assert audit(tree, "0" * 40, head) == 1


def test_an_untrusted_base_fails(tree, seam):
    """A base that is not the event's pull_request.base.sha."""
    other = tree.commit(card="# other\n")
    head = tree.commit(print=module_source(True, citation(RECORD_HEAD, "4a", 1775)))
    assert audit(tree, other, head, event_base=seam) == 1


def test_an_event_that_is_not_a_pull_request_fails(tree, seam, tmp_path):
    head = tree.commit(card="# Card\n")
    event = tmp_path / "push.json"
    event.write_text(json.dumps({"ref": "refs/heads/main"}))
    assert ct.main(["audit-order", "--repo", str(tree.root), "--base", seam, "--head", head,
                    "--event", str(event)], pr_merged=lambda n: True) == 1


def test_a_cited_section_only_on_the_head_fails(tree, seam):
    record = RECORD_HEAD + SDK_SECTION
    head = tree.commit(record=record, sdk=module_source(True, citation(record, "4b", 1901)))
    assert audit(tree, seam, head) == 1


def test_a_section_added_after_its_citation_fails(tree, seam):
    """The section must be on the BASE tree: a head that adds it under an admission that
    already cites it does not make that admission ordered."""
    record = RECORD_HEAD + SDK_SECTION
    base = tree.commit(sdk=module_source(True, citation(record, "4b", 1901)))
    head = tree.commit(record=record)
    assert audit(tree, base, head) == 1


def test_an_activation_on_a_base_without_its_section_fails(tree, seam):
    record = RECORD_HEAD + SDK_SECTION
    head = tree.commit(sdk=module_source(True, citation(record, "4b", 1901)))
    assert audit(tree, seam, head) == 1


@pytest.mark.parametrize("transport, section", [("sdk", "4a"), ("print", "4b"), ("print", "4")])
def test_a_real_section_of_another_purpose_fails(tree, transport, section):
    record = RECORD_HEAD + SDK_SECTION
    base = tree.commit(record=record, transport=transport_source(),
                       print=module_source(False, None), sdk=module_source(False, None))
    head = tree.commit(**{transport: module_source(True, citation(record, section, 1775))})
    assert audit(tree, base, head) == 1


def test_a_digest_that_differs_on_the_base_fails(tree, seam):
    head = tree.commit(print=module_source(True, citation(RECORD_HEAD, "4a", 1775, sha="1" * 64)))
    assert audit(tree, seam, head) == 1


def test_an_unmerged_cited_pr_fails(tree, seam):
    head = tree.commit(print=module_source(True, citation(RECORD_HEAD, "4a", 1500)))
    assert audit(tree, seam, head) == 1


def test_a_citation_of_the_pr_under_check_fails(tree, seam):
    head = tree.commit(print=module_source(True, citation(RECORD_HEAD, "4a", 1775)))
    assert audit(tree, seam, head, pr=1775) == 1


def test_one_pr_carrying_the_record_and_the_switch_fails(tree, seam):
    record = RECORD_HEAD + od3b("c", "print")
    base = tree.commit(print=module_source(True, citation(RECORD_HEAD, "4a", 1775)))
    head = tree.commit(record=record, card=CARD_OK,
                       transport=transport_source("print", citation(record, "4c", 1902)))
    assert audit(tree, base, head) == 1


def test_a_landing_that_activates_and_edits_the_record_fails(tree):
    record = RECORD_HEAD + SDK_SECTION
    base = tree.commit(record=record, transport=transport_source(),
                       print=module_source(False, None), sdk=module_source(False, None))
    head = tree.commit(record=record + "\nA later note.\n",
                       sdk=module_source(True, citation(record, "4b", 1901)))
    assert audit(tree, base, head) == 1


@pytest.mark.parametrize("variant", ["no-authority", "older-section", "other-value",
                                     "not-admitted", "unknown-value", "tui-citing-4a"])
def test_a_default_that_breaks_the_rule_fails(tree, variant):
    record = RECORD_HEAD + SDK_SECTION + od3b("c", "print") + od3b("d", "sdk")
    admitted = module_source(True, citation(RECORD_HEAD, "4a", 1775))
    base = tree.commit(record=record, transport=transport_source(), print=admitted,
                       sdk=module_source(False, None))
    transport = {
        "no-authority": transport_source("sdk"),
        "older-section": transport_source("print", citation(record, "4c", 1902)),
        "other-value": transport_source("print", citation(record, "4d", 1902)),
        "not-admitted": transport_source("sdk", citation(record, "4d", 1902)),
        "unknown-value": transport_source("bare"),
        "tui-citing-4a": transport_source("tui", citation(record, "4a", 1775)),
    }[variant]
    head = tree.commit(transport=transport, card=CARD_OK.replace("`print`", "`sdk`"))
    assert audit(tree, base, head) == 1


@pytest.mark.parametrize("card", [
    "# Card\n",
    "**Jailed Claude default:** chosen; open egress until CLAUDENET exits; awaits its row window.\n",
    "**Jailed Claude default:** `print`; awaits its row window.\n",
    "**Jailed Claude default:** `print`; runs on open egress until CLAUDENET exits.\n",
])
def test_a_card_whose_default_statement_omits_a_part_fails(tree, card):
    record = RECORD_HEAD + od3b("c", "print")
    base = tree.commit(record=record, transport=transport_source(),
                       print=module_source(True, citation(RECORD_HEAD, "4a", 1775)),
                       sdk=module_source(False, None))
    head = tree.commit(transport=transport_source("print", citation(record, "4c", 1902)),
                       card=card)
    assert audit(tree, base, head) == 1


def test_a_landing_that_edits_a_cited_section_fails(tree, seam):
    """Sections are append-only: a later landing may not rewrite what a citation names."""
    base = tree.commit(print=module_source(True, citation(RECORD_HEAD, "4a", 1775)))
    head = tree.commit(record=RECORD_HEAD.replace("Print, explicit.", "Print, by default."))
    assert audit(tree, base, head) == 1


def test_a_non_literal_admission_fails(tree, seam):
    head = tree.commit(print="FLAG = True\nADMITTED = FLAG\n")
    assert audit(tree, seam, head) == 1


# --------------------------------------------------------------------------------------
# Admission and the default are read only from the one shape the audit can read.
# --------------------------------------------------------------------------------------

RUNTIME = ct.RUNTIME_DIR
SDK_RECORD = RECORD_HEAD + SDK_SECTION


def _sdk_shapes() -> dict[str, dict]:
    cite = citation(SDK_RECORD, "4b", 1901)
    sdk = ct.MODULE_SOURCES["sdk"]
    return {
        "nested": {"sdk": f"if True:\n    ADMITTED = True\n    ACTIVATION = {cite}\n"},
        "tuple-target": {"sdk": f"ADMITTED, ACTIVATION = True, {cite}\n"},
        "augmented": {"sdk": f"ADMITTED = False\nACTIVATION = {cite}\nADMITTED |= True\n"},
        "walrus": {"sdk": f"ACTIVATION = {cite}\n(ADMITTED := True)\n"},
        "module-getattr": {"sdk": f"ACTIVATION = {cite}\n"
                                  "def __getattr__(name):\n    return name == 'ADMITTED'\n"},
        "globals": {"sdk": f"globals().update(ADMITTED=True, ACTIVATION={cite})\n"},
        "vars": {"sdk": f"ACTIVATION = {cite}\nvars()['ADMITTED'] = True\n"},
        "imported": {"sdk": "from ._sdk_values import ADMITTED, ACTIVATION\n",
                     "raw": {f"{RUNTIME}/_sdk_values.py": f"ADMITTED = True\nACTIVATION = {cite}\n"}},
        "star-import": {"sdk": "from ._sdk_values import *\n",
                        "raw": {f"{RUNTIME}/_sdk_values.py": f"ADMITTED = True\nACTIVATION = {cite}\n"}},
        "class": {"sdk": f"ACTIVATION = {cite}\nclass ADMITTED:\n    pass\n"},
        "package": {"sdk": None,
                    "raw": {f"{RUNTIME}/claude_seat_sdk/__init__.py": module_source(True, cite)}},
        "symlink": {"sdk": None, "raw": {f"{RUNTIME}/_sdk_real.py": module_source(True, cite)},
                    "links": {sdk: "_sdk_real.py"}},
        "compiled": {"raw": {f"{RUNTIME}/claude_seat_sdk.cpython-312-x86_64-linux-gnu.so": "x"}},
        "set-from-another-module": {"raw": {f"{RUNTIME}/panel_invoker.py":
                                            "from . import claude_seat_sdk\n"
                                            "claude_seat_sdk.ADMITTED = True\n"}},
        "setattr-from-another-module": {"raw": {f"{RUNTIME}/panel_invoker.py":
                                                "import importlib\n"
                                                "setattr(importlib.import_module('x'), 'ADMITTED', True)\n"}},
    }


def test_a_plain_literal_sdk_activation_on_a_ratified_base_passes(tree):
    """The control for the shapes below: the one readable shape, §4b on the base."""
    base = tree.commit(record=SDK_RECORD, transport=transport_source(),
                       print=module_source(False, None), sdk=module_source(False, None))
    head = tree.commit(sdk=module_source(True, citation(SDK_RECORD, "4b", 1901)))
    assert audit(tree, base, head) == 0


@pytest.mark.parametrize("shape", sorted(_sdk_shapes()))
def test_an_admission_in_any_other_shape_fails(tree, shape):
    base = tree.commit(record=SDK_RECORD, transport=transport_source(),
                       print=module_source(False, None), sdk=module_source(False, None))
    spec = _sdk_shapes()[shape]
    changes = {key: value for key, value in spec.items() if key == "sdk"}
    head = tree.commit(spec.get("raw"), spec.get("links"), **changes)
    assert audit(tree, base, head) == 1, shape


@pytest.mark.parametrize("extra", [
    "if True:\n    JAILED_CLAUDE_DEFAULT = 'print'\n",
    "JAILED_CLAUDE_DEFAULT, OTHER = 'print', 1\n",
    "def _switch():\n    global JAILED_CLAUDE_DEFAULT\n    JAILED_CLAUDE_DEFAULT = 'print'\n",
    "globals()['JAILED_CLAUDE_DEFAULT'] = 'print'\n",
])
def test_a_default_set_in_any_other_shape_fails(tree, seam, extra):
    head = tree.commit(transport=transport_source() + extra)
    assert audit(tree, seam, head) == 1


# --------------------------------------------------------------------------------------
# Every section and the preamble are append-only, cited yet or not.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("edit", ["uncited-section", "preamble", "separator", "removed"])
def test_any_edit_of_the_records_existing_bytes_fails(tree, seam, edit):
    base = tree.commit(record=SDK_RECORD)  # §4b ratified; nothing cites it yet
    record = {
        "uncited-section": SDK_RECORD.replace("The amendment.", "The amendment, revised."),
        "preamble": SDK_RECORD.replace("# Decision note", "# Decision notes"),
        "separator": SDK_RECORD + "\n" + od3b("c", "print"),
        "removed": None,
    }[edit]
    head = tree.commit(record=record)
    assert audit(tree, base, head) == 1, edit


def test_an_appended_section_passes(tree, seam):
    base = tree.commit(record=SDK_RECORD)
    head = tree.commit(record=SDK_RECORD + od3b("c", "print"))
    assert audit(tree, base, head) == 0


def test_an_unverifiable_merge_state_fails(tree, seam):
    head = tree.commit(print=module_source(True, citation(RECORD_HEAD, "4a", 1775)))

    def offline(_n):
        raise OSError("no network")

    assert ct.main(["audit-order", "--repo", str(tree.root), "--base", seam, "--head", head],
                   pr_merged=offline) == 1


# --------------------------------------------------------------------------------------
# The required CI step and the shipped tree.
# --------------------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[2]


def _audit_step() -> dict:
    import yaml

    workflow = yaml.safe_load((REPO / ".github/workflows/test.yml").read_text())
    job = workflow["jobs"]["lint"]
    assert job["name"] == "lint (pyflakes)"
    assert job.get("permissions", {}).get("pull-requests") == "read"
    steps = [step for step in job["steps"] if "audit-order" in str(step.get("run", ""))]
    assert len(steps) == 1
    return steps[0]


def test_the_required_lint_job_runs_audit_order_on_every_pull_request_and_push_to_main():
    step = _audit_step()
    assert step["if"] == ("github.event_name == 'pull_request' || (github.event_name == 'push'"
                          " && github.ref == 'refs/heads/main')")
    assert step["env"]["BASE_SHA"] == ("${{ github.event_name == 'pull_request' && "
                                       "github.event.pull_request.base.sha || github.event.before }}")
    run = step["run"]
    assert run.startswith("set -euo pipefail\n")
    assert '--base "$BASE_SHA"' in run and '--event "$GITHUB_EVENT_PATH"' in run
    assert "|| true" not in run and "continue-on-error" not in step


def _run_step(tree: "Tree", tmp_path: Path, base: str, head: str, event: str) -> subprocess.CompletedProcess:
    """The step's own script, run in the disposable tree. Only the fetch, which needs the
    hosted remote, is replaced; ``python`` is this interpreter."""
    run = _audit_step()["run"]
    fetch = 'git fetch --no-tags --depth=1 origin "$BASE_SHA" "$HEAD_SHA"'
    fetch_main = 'git fetch --no-tags --depth=1 origin "+refs/heads/main:refs/remotes/origin/main"'
    assert fetch in run and fetch_main in run
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    (shim / "python").unlink(missing_ok=True)
    (shim / "python").symlink_to(sys.executable)
    payload = tmp_path / "event.json"
    payload.write_text(json.dumps({"pull_request": {"number": 1999, "base": {"sha": base}}}))
    temp = tmp_path / "runner-temp"
    temp.mkdir(exist_ok=True)
    env = {"PATH": f"{shim}:{os.environ['PATH']}", "HOME": str(tmp_path), "EVENT_NAME": event,
           "BASE_SHA": base, "HEAD_SHA": head, "GITHUB_EVENT_PATH": str(payload),
           "RUNNER_TEMP": str(temp)}
    return subprocess.run(["bash", "-c", run.replace(fetch, "true").replace(fetch_main, "true")],
                          cwd=tree.root, env=env, capture_output=True, text=True, timeout=300)


@pytest.mark.parametrize("event", ["pull_request", "push"])
def test_the_ci_step_runs_the_base_trees_auditor(tree, tmp_path, event):
    """A landing that rewrites its own auditor to pass is still checked by the base's copy,
    on a pull request and on a push to main alike, and the change is flagged."""
    auditor = Path(ct.__file__).read_text()
    base = tree.commit(record=RECORD_HEAD, transport=auditor,
                       print=module_source(False, None), sdk=module_source(False, None))
    tampered = auditor.replace('JAILED_CLAUDE_DEFAULT: ClaudeTransport = "tui"',
                               'JAILED_CLAUDE_DEFAULT: ClaudeTransport = "sdk"').replace(
        "    repo = Path(repo)\n    pr_merged = pr_merged or github_pr_merged\n",
        "    return ()\n", 1)
    assert tampered.count("return ()\n") > auditor.count("return ()\n")
    head = tree.commit(transport=tampered)
    done = _run_step(tree, tmp_path, base, head, event)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "the shipped default `sdk` has no authority" in done.stderr
    assert "::warning::audit-order: this landing changes the auditor" in done.stdout


def test_the_ci_step_runs_the_heads_auditor_only_for_the_seam_landing(tree, tmp_path):
    base = tree.commit(record=RECORD_HEAD)
    head = tree.commit(transport=Path(ct.__file__).read_text(),
                       print=module_source(False, None), sdk=module_source(False, None))
    done = _run_step(tree, tmp_path, base, head, "pull_request")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "the base has no auditor yet" in done.stdout


def test_a_landing_that_removes_the_auditor_fails(tree, seam):
    """Once the seam has landed, a landing may not delete the auditor: the next landing
    would otherwise find no base copy and run its own."""
    head = tree.commit(transport=None)
    assert audit(tree, seam, head) == 1


def test_the_ci_step_runs_protected_mains_auditor_when_the_base_has_none(tree, tmp_path):
    """A base without the auditor does not fall back to the head's copy while protected
    main has one: main's copy audits the landing."""
    auditor = Path(ct.__file__).read_text()
    main = tree.commit(record=RECORD_HEAD, transport=auditor,
                       print=module_source(False, None), sdk=module_source(False, None))
    subprocess.run(["git", "-C", str(tree.root), "update-ref", "refs/remotes/origin/main", main],
                   check=True)
    base = tree.commit(transport=None)
    tampered = auditor.replace('JAILED_CLAUDE_DEFAULT: ClaudeTransport = "tui"',
                               'JAILED_CLAUDE_DEFAULT: ClaudeTransport = "sdk"').replace(
        "    repo = Path(repo)\n    pr_merged = pr_merged or github_pr_merged\n",
        "    return ()\n", 1)
    head = tree.commit(transport=tampered)
    done = _run_step(tree, tmp_path, base, head, "pull_request")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "running protected main's copy" in done.stdout
    assert "the shipped default `sdk` has no authority" in done.stderr


def test_the_shipped_tree_satisfies_the_default_rule():
    record = (REPO / ct.DECISION_RECORD).read_bytes()
    admitted = [t for t in ("print", "sdk") if ct.transport_module(t) is not None]
    assert ct.default_rule_failures(ct.JAILED_CLAUDE_DEFAULT, ct.JAILED_DEFAULT_AUTHORITY,
                                    record, admitted) == []
    card = (REPO / ct.CARD).read_bytes()
    assert ct.card_failures(ct.JAILED_CLAUDE_DEFAULT, card) == []


def test_the_print_route_section_digest_is_the_plan_pin():
    """§4a (agent-harness#1775) under the plan's byte rule."""
    record = (REPO / ct.DECISION_RECORD).read_bytes()
    assert ct.record_sections(record)["4a"][1] == (
        "7af0fb700ef10d444a904b01169c8b08aa056ba25ca496c7adcca7c646852cdb")
