"""v13 LANEEXEC erratum LANEEXEC-v1-errata-1 (agent-harness#1988), checked on the frozen bytes.

These tests hold the planning artifact to its wire erratum: the local
``pi-runner`` template form (E1), what that form means for
registration and for a stale ``template_sha256`` (E2(i), E2(ii)), the wire identity
against the previous bytes (E3), and the citations that the landed binding and the
phase plan make into the artifact. The production LaneExec tests that discharge
E1-E3 are owned by the LANEEXEC SL-3.1 and SL-5.1 rows.

Every expectation here is an input: the previous artifact digest, the previous
operator record's ``template_sha256``, and two digests read from the previous bytes
(the cited sentences, and everything outside the members the erratum declares).
Erratum 7 also holds the wire to the exact bytes repinned by erratum 6.
"""

from __future__ import annotations

import copy
from hashlib import sha256
import json
from pathlib import Path
import re

import pytest
import rfc8785

REPO = Path(__file__).resolve().parents[2]
ARTIFACT = REPO / "plans/artifacts/v13-LANEEXEC-contract-v1.schema.json"
PACKAGED_WIRE = (
    REPO / "phase-loop-runtime/src/phase_loop_runtime/contracts/placement/launch-v1.schema.json"
)
BINDING = REPO / "plans/artifacts/v13-LANEEXEC-landed-binding.md"
PLAN = REPO / "plans/phase-plan-v13-LANEEXEC.md"
REMOTE_PLAN = REPO / "plans/phase-plan-v1-seats-REMOTE.md"
MANIFEST = REPO / "plans/manifest.json"

pytestmark = pytest.mark.skipif(
    not (ARTIFACT.is_file() and BINDING.is_file() and PLAN.is_file()),
    reason="planning artifacts absent in standalone clean-room",
)

#: The LANEEXEC artifact bytes before the erratum (an input, never an output).
PREVIOUS_SHA256 = "bd0e6694e6df9e4ae0bc640c138645adf6b49e8f56aa3f5af7488107062676f3"
#: The installed operator record's local template_sha256 under the previous bytes.
PRE_ERRATUM_TEMPLATE_SHA256 = "0905bff04c6976d8eaf096579e2398ada265fcc2980c024919b2527c20257449"
ERRATUM_ID = "LANEEXEC-v1-errata-1"

ERRATUM_FORM = ["--tmpfs", "/var/log", "--remount-ro", "/var/log"]
PREVIOUS_FORM = ["--ro-bind", "/var/log", "/var/log"]
USR_BIND = ["--ro-bind", "/usr", "/usr"]
BIND_FLAGS = {"--bind", "--ro-bind", "--bind-try", "--ro-bind-try", "--dev-bind", "--dev-bind-try"}

#: The local template argv in its erratum form, literal tokens and slot objects as frozen.
FROZEN_LOCAL_ARGV = [
    "/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session",
    "--cap-drop", "ALL", "--clearenv", "--proc", "/proc", "--dev", "/dev",
    "--tmpfs", "/tmp",
    "--ro-bind", "/etc", "/etc", "--ro-bind", "/lib", "/lib", "--ro-bind", "/usr", "/usr",
    "--tmpfs", "/var/log", "--remount-ro", "/var/log",
    "<host symlink entries>", "<ro_trees binds>",
    "--bind", {"slot": "tree"}, {"slot": "tree_dest"},
    "--bind", {"slot": "scratch"}, {"slot": "scratch"},
    "--chdir", {"slot": "tree_dest"},
    "--", "<node>", "<remote_inner>",
]

#: The wire sentences the binding and the phase plan cite by member path. The erratum
#: must leave each of them byte-identical.
CITED = (
    ("x-launch-inputs", "order"),
    ("x-prepare", "values"),
    ("x-snapshot", "upload"),
    ("x-seed", "provisioning"),
    ("x-envelope-construction", "rule"),
    ("x-envelope-construction", "fields", "launch.grants.egress_policy_sha256"),
    ("x-exec", "one_exec"),
    ("x-exec", "claim_rollback"),
    ("x-exec", "after_start"),
    ("x-local-cgroup", "automatic_paths"),
    ("x-local-cgroup", "parent"),
    ("x-local-cgroup", "refusal"),
    ("x-lifetime", "supervisor_death"),
    ("x-return", "patch"),
    ("x-return", "termination"),
)
#: sha256 of the RFC 8785 bytes of [[path, value], ...] over CITED, read from the
#: previous artifact bytes.
CITED_SENTENCES_SHA256 = "d1ca7cb54bdaa8e576857e5795e8603c2c1e62817ca31546df89d4bad92518df"
#: SHA-256 of the RFC 8785 bytes of the previous artifact after excluding the local
#: template changes declared by x-errata and the fields authorized by repin_rule.
UNCHANGED_SHA256 = "dc6c07a7dcbd70f332a210413f8e24f7766ad70d347d673aab71710e484d6a52"
#: Fragments the binding quotes from a cited sentence, matched without regard to case.
QUOTED = {
    ("x-envelope-construction", "rule"): "admits it through the v12 admission seam",
    ("x-exec", "one_exec"): "sets LeaseFlags.exec_claimed and reserves the",
    ("x-local-cgroup", "automatic_paths"): "including the caps contract §1a tmpfs carve-out",
    ("x-exec", "claim_rollback"): "rollback is never inferred",
}

_BACKTICKED = re.compile(r"`([^`\n]*)`")
_MEMBER_PATH = re.compile(r'x-[a-z0-9-]+(?:\.[A-Za-z0-9_-]+|\["[^"\]]+"\])*')
_SEGMENT = re.compile(r'\.([A-Za-z0-9_-]+)|\["([^"\]]+)"\]')
#: A citation of the wire artifact by line number, in any case, the possessive included.
_LINE_CITATION = re.compile(
    r"(?:artifact|wire|contract|schema\.json`?)\s+lines?\s+\d+"
    r"|\blines?\s+\d+(?:\s*(?:,|and)\s*\d+)*'s",
    re.IGNORECASE,
)


def document():
    return json.loads(ARTIFACT.read_bytes())


def local_template(doc):
    return doc["x-argv-templates"]["pi_runner_templates"]["local"]


def index_of(argv, tokens):
    for i in range(len(argv) - len(tokens) + 1):
        if argv[i:i + len(tokens)] == tokens:
            return i
    return -1


def swap(argv, old, new):
    i = index_of(argv, old)
    return argv if i < 0 else argv[:i] + new + argv[i + len(old):]


def expand(template_argv):
    """Expand the template with fixed per-registration values (x-argv-templates.local)."""
    fills = {
        "<host symlink entries>": ["--symlink", "usr/bin", "/bin", "--symlink", "usr/lib64", "/lib64"],
        "<ro_trees binds>": ["--ro-bind", "/opt/node", "/opt/node", "--ro-bind", "/opt/toolkit", "/opt/toolkit"],
        "<node>": ["/opt/node/bin/node"],
        "<remote_inner>": ["/opt/toolkit/harnesses/pi/sandbox/remote-inner.mjs"],
    }
    slots = {"tree": "/state/r1/tree", "tree_dest": "/state/r1/tree", "scratch": "/state/r1/scratch"}
    out = []
    for token in template_argv:
        if isinstance(token, dict):
            out.append(slots[token["slot"]])
        else:
            out.extend(fills.get(token, [token]))
    return out


def var_log_is_erratum_form(argv):
    """E1: the four erratum tokens directly after the /usr bind, and no bind from /var/log."""
    usr = index_of(argv, USR_BIND)
    if usr < 0 or argv[usr + 3:usr + 7] != ERRATUM_FORM:
        return False
    return not any(
        flag in BIND_FLAGS and (src == "/var/log" or str(src).startswith("/var/log/"))
        for flag, src in zip(argv, argv[1:])
    )


def registered_record(argv):
    """A local record as registered; template_sha256 is per x-argv-templates.template_hash_rule."""
    template = local_template(document())
    return {"template_id": template["template_id"], "target_kind": "local",
            "workload": template["workload"], "argv": argv}


def template_sha256(record):
    return sha256(rfc8785.dumps(record)).hexdigest()


def launch_template_check(named_sha256, registered_sha256):
    """The x-argv-templates rule: a template_sha256 other than the registered bytes refuses."""
    return None if named_sha256 == registered_sha256 else "sandbox_launch_template_refused"


def version_check(pinned_sha256, observed_sha256):
    """PLACECLI T3 shape: a pinned client calls version first and refuses on a difference."""
    return "proceed" if pinned_sha256 == observed_sha256 else "refuse"


def erratum_entry(doc):
    entries = doc.get("x-errata", {}).get("entries", [])
    return next((e for e in entries if e.get("id") == ERRATUM_ID), {})


def member(doc, path):
    value = doc
    for key in path:
        value = value[key]
    return value


def parse_member_path(text):
    match = _MEMBER_PATH.fullmatch(text)
    if match is None:
        return None
    first = re.match(r"x-[a-z0-9-]+", text).group(0)
    keys = [first]
    for name, quoted in _SEGMENT.findall(text[len(first):]):
        keys.append(name or quoted)
    return tuple(keys)


def cited_member_paths():
    found = {}
    for path in (BINDING, PLAN):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for text in _BACKTICKED.findall(line):
                if text.startswith("x-") and text != "x-*":
                    found.setdefault(text, f"{path.name}:{lineno}")
    return found


# -- E1: the local template form --------------------------------------------------------

def test_e1_the_local_template_is_exactly_its_erratum_form():
    template = local_template(document())
    assert template["template_id"] == "pi-runner.local.v1"
    assert template["argv"] == FROZEN_LOCAL_ARGV
    assert var_log_is_erratum_form(expand(template["argv"]))


def test_e1_mutation_control_the_previous_bind_fails_the_predicate():
    argv = expand(local_template(document())["argv"])
    assert not var_log_is_erratum_form(swap(argv, ERRATUM_FORM, PREVIOUS_FORM))
    # A bind from /var/log anywhere else fails too, even with the erratum tokens in place.
    assert not var_log_is_erratum_form(argv + ["--ro-bind", "/var/log", "/srv/log"])


def test_e1_the_rule_sentence_states_the_erratum_form_in_neutral_terms():
    rule = local_template(document())["argv_rule"]
    assert ("/var/log is an empty read-only directory, as in the image "
            "(--tmpfs /var/log --remount-ro /var/log), at its vector position") in rule
    assert "/usr and /var/log binds" not in rule
    assert "Nothing else may appear." in rule


# -- E2(i): registration accepts only the erratum form ----------------------------------

def test_e2i_registration_refuses_the_pre_erratum_argv():
    template = local_template(document())
    expected = expand(template["argv"])
    previous = swap(expected, ERRATUM_FORM, PREVIOUS_FORM)
    # "Nothing else may appear": registration accepts exactly the expanded frozen form,
    # so the pre-erratum argv is a different argv and is refused.
    assert previous != expected
    assert not var_log_is_erratum_form(previous)
    assert "Nothing else may appear." in template["argv_rule"]


# -- E2(ii): a stale template_sha256 refuses --------------------------------------------

def test_e2ii_a_pre_erratum_template_sha256_refuses_before_any_effect():
    doc = document()
    expected = expand(local_template(doc)["argv"])
    registered = template_sha256(registered_record(expected))
    stale = template_sha256(registered_record(swap(expected, ERRATUM_FORM, PREVIOUS_FORM)))
    assert stale != registered
    assert launch_template_check(stale, registered) == "sandbox_launch_template_refused"
    assert launch_template_check(PRE_ERRATUM_TEMPLATE_SHA256, registered) == "sandbox_launch_template_refused"
    assert launch_template_check(registered, registered) is None
    rule = doc["x-argv-templates"]["pi_runner_templates"]["rule"]
    assert "a template_sha256 that differs from the registered bytes, refuses sandbox_launch_template_refused before snapshot or any effect" in rule
    assert "sandbox_launch_template_refused" in doc["$defs"]["LaunchCode"]["enum"]


# -- E3: the wire identity against the previous bytes -----------------------------------

def test_e3_a_client_pinned_to_the_previous_bytes_refuses_at_version():
    observed = sha256(ARTIFACT.read_bytes()).hexdigest()
    assert erratum_entry(document()).get("previous_sha256") == PREVIOUS_SHA256
    assert observed != PREVIOUS_SHA256
    assert version_check(PREVIOUS_SHA256, observed) == "refuse"
    assert version_check(observed, observed) == "proceed"


# -- the x-errata member ----------------------------------------------------------------

def test_the_erratum_entry_is_class_c_with_its_obligations_and_approval():
    doc = document()
    assert list(doc)[-3:] == ["x-test-obligations", "x-errata", "$defs"]
    rule = doc["x-errata"]["version_rule"]
    assert "(c) replace a fixed x-argv-templates literal together with the rule sentence that prescribes it" in rule
    assert "LaunchVersionResponse.protocol_schema_sha256" in rule
    entry = erratum_entry(doc)
    assert [c["class"] for c in entry["changes"]] == ["c"]
    assert entry["changes"][0]["member"] == (
        "x-argv-templates.pi_runner_templates.local.argv, "
        "x-argv-templates.pi_runner_templates.local.argv_rule")
    assert [o.split(" ", 1)[0] for o in entry["test_obligations"]] == ["E1", "E2(i)", "E2(ii)", "E3"]
    assert PRE_ERRATUM_TEMPLATE_SHA256 in entry["test_obligations"][2]
    assert "Owner approval: 2026-11-16, recorded on Consiliency/agent-harness#1988." in entry["approval"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["date"])


def outside_the_erratum(doc):
    """Keep the wire members outside the template erratum and toolkit repin."""
    doc = copy.deepcopy(doc)
    doc.pop("x-errata", None)
    toolkit_pin = doc["x-contract-pins"]["toolkit_pins"]
    del toolkit_pin["toolkit_commit"], toolkit_pin["sha256"], toolkit_pin["byte_length"]
    local = local_template(doc)
    del local["argv"], local["argv_rule"]
    return doc


def test_the_erratum_changes_only_the_members_it_declares():
    # Every constant, member, verb, exit class, code, policy name, template id and the
    # openshell template keep their previous bytes.
    assert sha256(rfc8785.dumps(outside_the_erratum(document()))).hexdigest() == UNCHANGED_SHA256


def test_mutation_control_a_change_outside_the_erratum_is_detected():
    doc = document()
    doc["x-argv-templates"]["pi_runner_templates"]["openshell"]["template_id"] = "pi-runner.openshell.v2"
    assert sha256(rfc8785.dumps(outside_the_erratum(doc))).hexdigest() != UNCHANGED_SHA256


# -- citations of the wire artifact -----------------------------------------------------

def test_the_cited_sentences_are_byte_identical_to_the_previous_bytes():
    doc = document()
    rows = [[list(path), member(doc, path)] for path in CITED]
    assert sha256(rfc8785.dumps(rows)).hexdigest() == CITED_SENTENCES_SHA256


def test_the_quoted_fragments_still_occur_in_their_sentences():
    doc = document()
    missing = [".".join(p) for p, text in QUOTED.items() if text.lower() not in member(doc, p).lower()]
    assert not missing


def test_every_backticked_member_path_in_the_binding_and_plan_resolves():
    doc = document()
    found = cited_member_paths()
    unresolved = []
    for text, where in sorted(found.items()):
        path = parse_member_path(text)
        try:
            if path is None:
                raise KeyError(text)
            member(doc, path)
        except (KeyError, TypeError):
            unresolved.append(f"{where}: `{text}`")
    assert not unresolved
    # The hard-coded citation list stays tied to the documents.
    cited_paths = {parse_member_path(t) for t in found}
    assert set(CITED) <= cited_paths


def test_no_line_number_citation_of_the_wire_artifact_remains():
    hits = [f"{p.name}:{n}: {m.group(0)}"
            for p in (BINDING, PLAN)
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            for m in _LINE_CITATION.finditer(line)]
    assert not hits


@pytest.mark.parametrize("text,cites", [
    ("(artifact line 252)", True),
    ("Artifact line 529's rule", True),
    ("wire lines 471, 482 and 540", True),
    ("`plans/x.schema.json` line 509", True),
    ("line 482's ownership rule", True),
    ("`seat_resource_caps.py:247`", False),
    ("(`x-launch-inputs.order`)", False),
])
def test_the_line_citation_check_catches_each_form(text, cites):
    assert bool(_LINE_CITATION.search(text)) is cites


def test_the_member_path_check_refuses_a_mistyped_path():
    doc = document()
    with pytest.raises(KeyError):
        member(doc, parse_member_path("x-exec.one_exce"))
    assert parse_member_path('x-envelope-construction.fields["launch.grants.egress_policy_sha256"]') == (
        "x-envelope-construction", "fields", "launch.grants.egress_policy_sha256")


def test_the_cited_digest_detects_a_changed_sentence():
    doc = copy.deepcopy(document())
    doc["x-local-cgroup"]["refusal"] += " Changed."
    rows = [[list(path), member(doc, path)] for path in CITED]
    assert sha256(rfc8785.dumps(rows)).hexdigest() != CITED_SENTENCES_SHA256


# -- pin sites --------------------------------------------------------------------------

@pytest.mark.skipif(not (MANIFEST.is_file() and REMOTE_PLAN.is_file()), reason="plans absent")
def test_every_pin_site_holds_the_erratum_digest():
    contract = sha256(ARTIFACT.read_bytes()).hexdigest()
    assert contract == "57bc376cc629e762130a3f43aa5bef8cfaeebb1042a3963fc54a5708d5adba7d"
    assert PACKAGED_WIRE.read_bytes() == ARTIFACT.read_bytes()
    binding = sha256(BINDING.read_bytes()).hexdigest()
    rows = [r for r in json.loads(MANIFEST.read_bytes())["plans"] if r.get("slug") == "v13-LANEEXEC"]
    assert len(rows) == 1
    frozen = rows[0]["frozen_inputs"]
    assert frozen["plans/artifacts/v13-LANEEXEC-contract-v1.schema.json"]["sha256"] == contract
    assert frozen["plans/artifacts/v13-LANEEXEC-landed-binding.md"]["sha256"] == binding
    binding_text = BINDING.read_text(encoding="utf-8")
    assert f"LaneExec launch protocol v1 with {ERRATUM_ID} and LANEEXEC-v1-errata-6 | " \
           f"`plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`, sha256 `{contract}`" in binding_text
    remote = REMOTE_PLAN.read_text(encoding="utf-8")
    assert re.search(r"v13-LANEEXEC-contract-v1\.schema\.json`, sha256\s+`" + contract + "`", remote)
    for path in (BINDING, PLAN, REMOTE_PLAN, MANIFEST):
        assert PREVIOUS_SHA256 not in path.read_text(encoding="utf-8"), path.name
    assert ARTIFACT.read_text(encoding="utf-8").count(PREVIOUS_SHA256) == 1
