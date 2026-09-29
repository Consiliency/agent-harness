"""The runtime's only remote-mutation surface (PANEL SL-1, plans/phase-plan-v10-PANEL.md item 7).

Every remote-mutating ``git``/``gh`` command the runtime issues sits in the body of exactly
one function here:

* :func:`guarded_merge` -- ``gh pr merge --merge --match-head-commit`` (with ``gh pr ready``
  for a draft) and the leased push to a landing target. It merges only on an authority: the
  admitted :class:`~phase_loop_runtime.panel_invoker.LandingDecision` that ``invoke_board``
  registered with its bindings, or a :class:`NoLandingToken` minted by an autonomous entry.
* :func:`publish_nontarget` -- pushes to and GitHub operations on non-target branches, each
  checked against a closed grammar; it resolves the protected destinations itself.
* :func:`publish_new_branch` -- the create-only branch push (and draft PR) of the agy watch,
  keeping agent-harness#1130 r7's push-to-remote-NAME rule and count gates.
* :func:`dequeue` -- the GraphQL ``dequeuePullRequest`` mutation plus ``gh pr merge
  --disable-auto``; it can only remove.

Later phases add remote mutations only as new named functions here, and read-only commands
only to :data:`READ_ONLY_ALLOWLIST`. Every ``git`` call runs as ``git -c
core.hooksPath=/dev/null`` and every push passes ``--no-verify``, so no repository hook runs
inside a merge-guard call. The gateway scan (``test_panel_sl1_contracts``) is a regression
tripwire over these rules, not a security boundary (maintainer decision, agent-harness#1111).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

# Read-only commands this module issues (documentation for the tripwire's extension seam).
READ_ONLY_ALLOWLIST: frozenset[str] = frozenset({
    "git rev-parse", "git merge-base", "git fetch", "git ls-remote", "git config", "git remote get-url",
    "gh pr view", "gh pr list", "gh repo view", "gh api -X GET", "gh api graphql query",
})

_HEX = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_REDIRECT_KEYS = re.compile(
    r"^(url\..*\.(insteadof|pushinsteadof)|core\.sshcommand|core\.gitproxy|credential\..*|remote\.[^.]+\.pushurl"
    r"|remote\.[^.]+\.receivepack|remote\.[^.]+\.uploadpack|http\..*proxy)$"
)


class MergeGuardRefusal(RuntimeError):
    """A typed refusal: nothing remote was changed by the refused step."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


class MergeGuardEscalation(RuntimeError):
    """A typed escalation for a human: the remote may have changed (e.g. a moved base)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


# --- the process seam ---------------------------------------------------------------------


# A publishing caller's own run callable (agent-harness#1078 amendment #3): while a
# ``publish_nontarget`` / ``publish_new_branch`` call runs with ``run=``, every command --
# the guard's own lookups included -- goes through it. The checks stay here.
_CALLER_RUN: ContextVar[Any] = ContextVar("merge_guard_caller_run", default=None)


@contextmanager
def _caller_run(run):
    token = _CALLER_RUN.set(run)
    try:
        yield
    finally:
        _CALLER_RUN.reset(token)


def _spawn(argv: Sequence[str], *, cwd: str | Path | None = None, env: Mapping[str, str] | None = None,
           input: str | None = None) -> subprocess.CompletedProcess:
    """Run one command. Every command this module issues goes through here."""
    caller = _CALLER_RUN.get()
    if caller is not None:
        kwargs: dict[str, Any] = {"capture_output": True, "text": True, "check": False}
        if cwd is not None:
            kwargs["cwd"] = str(cwd)
        if env is not None:
            kwargs["env"] = dict(env)
        if input is not None:
            kwargs["input"] = input
        return caller(list(argv), **kwargs)
    base = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in ("GH_REPO", "GH_HOST")}
    if env is not None:
        base = dict(env)
    return subprocess.run(list(argv), cwd=str(cwd) if cwd is not None else None, env=base, input=input,
                          capture_output=True, text=True, check=False, timeout=180)


def _git(repo_dir: str | Path, *args: str) -> subprocess.CompletedProcess:
    return _spawn(["git", "-C", str(repo_dir), "-c", "core.hooksPath=/dev/null", *args])


def _git_out(repo_dir: str | Path, *args: str) -> str | None:
    done = _git(repo_dir, *args)
    return done.stdout.strip() if done.returncode == 0 else None


def _repo_slug(repo_dir: str | Path) -> str:
    """The host-qualified ``host/owner/repo`` of ``origin`` (raises for a non-GitHub origin)."""
    from .convergence.broker.credsep import resolve_broker_repo_identity

    caller = _CALLER_RUN.get()
    try:
        return resolve_broker_repo_identity(Path(repo_dir), run=caller if caller is not None else subprocess.run)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise MergeGuardRefusal("panel_merge_repo_unknown", f"the repository's GitHub identity cannot be read: {exc}") from exc


def repo_slug(repo_dir: str | Path) -> str:
    """The broker-validated ``host/owner/repo`` of ``repo_dir``'s ``origin`` (the ``--repo``
    every merge_guard GitHub operation must name)."""
    return _repo_slug(repo_dir)


def _slug_parts(slug: str) -> tuple[str, str, str]:
    parts = slug.split("/")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return "github.com", parts[0], parts[1]
    raise MergeGuardRefusal("panel_merge_repo_unknown", f"unparseable repository slug {slug!r}")


def _gh_json(args: Sequence[str], cwd: str | Path | None = None) -> Any:
    done = _spawn(["gh", *args], cwd=cwd)
    if done.returncode != 0:
        raise MergeGuardRefusal("panel_merge_read_failed", f"gh {' '.join(args[:2])} failed")
    try:
        return json.loads(done.stdout or "null")
    except ValueError as exc:
        raise MergeGuardRefusal("panel_merge_read_failed", "unparseable gh output") from exc


def _common_dir(repo_dir: str | Path) -> str | None:
    return _git_out(repo_dir, "rev-parse", "--path-format=absolute", "--git-common-dir")


def _common_dir_direct(repo_dir: str | Path) -> str | None:
    """``--git-common-dir`` read with ``Popen`` directly: a local, read-only lookup that a
    caller's command seam need not answer."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        proc = subprocess.Popen(
            ["git", "-C", str(repo_dir), "-c", "core.hooksPath=/dev/null", "rev-parse", "--path-format=absolute",
             "--git-common-dir"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env,
        )
        out, _ = proc.communicate(timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.strip() if proc.returncode == 0 and out.strip() else None


def _origin_url(repo_dir: str | Path) -> str | None:
    return _git_out(repo_dir, "remote", "get-url", "origin")


def _refuse_config_redirects(repo_dir: str | Path) -> None:
    """Repository-local config that redirects a push or runs a command is refused, never
    overridden (only ``core.hooksPath`` is set with ``-c`` here)."""
    done = _git(repo_dir, "config", "--local", "--list", "--name-only")
    if done.returncode not in (0, 1):
        raise MergeGuardRefusal("panel_merge_config_unreadable", "repository config cannot be read")
    for key in done.stdout.split():
        if _REDIRECT_KEYS.match(key.lower()):
            raise MergeGuardRefusal("panel_merge_config_redirect", f"repository config {key} redirects git")


# --- branch rules --------------------------------------------------------------------------


def _branch_rules(slug: str, branch: str) -> dict[str, bool]:
    """Rulesets and classic protection of ``branch``: ``protected`` and ``queue``.
    An unreadable lookup raises ``panel_merge_queue_unknown``."""
    host, owner, name = _slug_parts(slug)
    rules = _spawn(["gh", "api", "-X", "GET", f"repos/{owner}/{name}/rules/branches/{branch}", "--hostname", host])
    if rules.returncode != 0:
        raise MergeGuardRefusal("panel_merge_queue_unknown", f"branch rules of {branch!r} cannot be read")
    try:
        ruleset = json.loads(rules.stdout or "[]")
    except ValueError as exc:
        raise MergeGuardRefusal("panel_merge_queue_unknown", "unparseable branch rules") from exc
    if not isinstance(ruleset, list):
        raise MergeGuardRefusal("panel_merge_queue_unknown", "unexpected branch rules shape")
    classic = _spawn(["gh", "api", "-X", "GET", f"repos/{owner}/{name}/branches/{branch}/protection",
                      "--hostname", host])
    if classic.returncode != 0:
        if "404" not in (classic.stderr or "") and "Not Found" not in (classic.stderr or ""):
            raise MergeGuardRefusal("panel_merge_queue_unknown", f"classic protection of {branch!r} cannot be read")
        protection: dict = {}
        classic_protected = False
    else:
        try:
            protection = json.loads(classic.stdout or "{}")
        except ValueError as exc:
            raise MergeGuardRefusal("panel_merge_queue_unknown", "unparseable classic protection") from exc
        classic_protected = True
    queue = any(isinstance(rule, Mapping) and rule.get("type") == "merge_queue" for rule in ruleset) or bool(
        isinstance(protection, Mapping) and (protection.get("required_merge_queue") or protection.get("merge_queue"))
    )
    return {"protected": bool(ruleset) or classic_protected, "queue": queue}


# --- authority -----------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeBindings:
    """What an admitted decision is bound to, read by the runtime at decision time."""

    git_common_dir: str
    origin_url: str
    target_branch: str
    reviewed_head: str
    repo_slug: str | None
    pr: Mapping[str, Any] | None = None


@dataclass
class _DecisionEntry:
    decision: object
    digest: str
    context: object
    tier: str
    bindings: MergeBindings | None
    state: str = "registered"


_DECISIONS: dict[int, _DecisionEntry] = {}
_LANDING_CALLS: set[str] = set()
_MINTED: dict[int, "NoLandingToken"] = {}


def _digest(value: object) -> str:
    from .advisor_board.config import panel_content_digest

    return panel_content_digest(value)


def record_landing_call(repo_dir: str | Path | None) -> None:
    """``invoke_board`` notes every landing call; a ``NoLandingToken`` is refused afterwards."""
    if repo_dir is None:
        return
    common = _common_dir(repo_dir)
    _LANDING_CALLS.add(common or str(Path(repo_dir).resolve()))


def read_landing_bindings(context: object, *, target_branch: str | None, reviewed_head: str | None,
                          reviewed_pr: int | None) -> MergeBindings | None:
    """Read the bindings of an admitted decision; ``None`` when it is not merge-capable
    (no cross-checks, a context without a validated head, a head other than the review
    packet's, or a PR whose live state disagrees with the cross-checks)."""
    from .advisor_board.config import verify_panel_object

    facts = verify_panel_object(context)
    if facts is None or target_branch is None or reviewed_head is None:
        return None
    repo = facts.get("repo_dir")
    validated = facts.get("validated_head")
    if repo is None or validated is None:
        return None
    head = _git_out(repo, "rev-parse", "--verify", f"{reviewed_head}^{{commit}}")
    if head is None or head != _git_out(repo, "rev-parse", "--verify", f"{validated}^{{commit}}"):
        return None
    common, origin = _common_dir(repo), _origin_url(repo)
    if common is None or origin is None:
        return None
    try:
        slug = _repo_slug(repo)
    except Exception:
        slug = None
    pr = None
    if reviewed_pr is not None:
        if slug is None:
            return None
        try:
            live = _gh_json(["pr", "view", str(int(reviewed_pr)), "--repo", slug, "--json",
                             "number,baseRefName,headRefOid,headRepository,url"], cwd=repo)
        except MergeGuardRefusal:
            return None
        if not isinstance(live, Mapping) or live.get("number") != int(reviewed_pr) \
                or live.get("headRefOid") != head or live.get("baseRefName") != target_branch:
            return None
        pr = {key: live.get(key) for key in ("number", "baseRefName", "headRefOid", "headRepository", "url")}
    return MergeBindings(git_common_dir=common, origin_url=origin, target_branch=target_branch,
                         reviewed_head=head, repo_slug=slug, pr=pr)


def register_landing_decision(decision: object, *, context: object, tier: str,
                              bindings: MergeBindings | None) -> None:
    """Register an admitted decision by identity plus content digest. Only ``invoke_board``
    calls this (the tripwire allowlists that one reference)."""
    _DECISIONS[id(decision)] = _DecisionEntry(decision, _digest(decision), context, tier, bindings)


class NoLandingToken:
    """Authority for today's primitive on a path that makes no panel landing, minted only
    by :func:`mint_no_landing_token`. It carries the minting entry's own run mode."""

    __slots__ = ("_used", "run_mode")

    def __init__(self, run_mode: str) -> None:
        self._used = False
        self.run_mode = run_mode


def mint_no_landing_token(*, run_mode: str) -> NoLandingToken:
    """Mint a token for the entry's ``run_mode`` (the entry's own argument, never an
    environment variable). ``guarded_merge`` accepts it for an ``autonomous`` run, and
    for a ``governed`` run only in a repository before the GOVLEAN authority switch
    (maintainer decision on agent-harness#1078, option C)."""
    token = NoLandingToken(str(run_mode))
    _MINTED[id(token)] = token
    return token


# --- actions -------------------------------------------------------------------------------


@dataclass(frozen=True)
class GhPrMerge:
    """A PR landing: every field must equal the decision's bindings."""

    repo_slug: str
    pr_number: int
    head_sha: str
    target_branch: str
    context: object = field(default=None, compare=False)


@dataclass(frozen=True)
class GitPush:
    """A push landing of exactly the bound head, leased against the fetched target."""

    remote: str
    target_branch: str
    commit: str
    context: object = field(default=None, compare=False)


@dataclass(frozen=True)
class GitMergePush:
    """A push landing of a local merge commit whose parents are exactly [B0, the bound
    reviewed head] and whose tree is the clean ``git merge-tree --write-tree`` of the two,
    leased at B0. Scoped to ``runner._run_legible_pr_transition`` (maintainer ruling Q7,
    agent-harness#1078): an item-7 extension for that single site."""

    remote: str
    target_branch: str
    commit: str
    context: object = field(default=None, compare=False)


@dataclass(frozen=True)
class LegacyPrMerge:
    """Today's ``train_runner._live_merge_pr`` primitive, for the autonomous path only."""

    branch: str
    repo_args: tuple[str, ...]
    head_sha: str | None
    delete_branch: bool
    cwd: str
    env: Mapping[str, str] | None = None
    ready_first: bool = False


@dataclass(frozen=True)
class LegacyPush:
    """Today's closeout / transition push, for the autonomous path only."""

    remote: str
    refspec: str
    cwd: str


# --- guarded_merge -------------------------------------------------------------------------


def guarded_merge(repo_dir: str | Path, *, authority: object, action: object) -> str:
    """Perform one landing, or refuse it before any attempt.

    With a registered decision: re-verify the decision and its context, require the action
    and repository to equal the bindings, refuse a queue-protected or unreadable target,
    fetch the target (B0), require the gated revision to be an ancestor of B0, refuse on a
    re-gate or a changed user file, re-read a PR's live state, and only then act -- once."""

    def _no_landing(repo_dir: Path, token: NoLandingToken, action: object) -> str:
        """Today's primitive, byte-for-byte, only for an autonomous run with no landing call."""
        if _MINTED.get(id(token)) is not token or getattr(token, "_used", True):
            raise MergeGuardRefusal("panel_merge_authority_missing", "the no-landing token is not a minted one")
        mode = getattr(token, "run_mode", None)
        if mode not in ("autonomous", "governed"):
            raise MergeGuardRefusal("panel_merge_authority_missing", f"run mode {mode!r} is unreadable")
        if mode == "governed":
            # Option C (agent-harness#1078): a governed merge is not a PANEL landing only in a
            # repository before the switch, read from that repository's own authority state.
            # An unreadable state fails closed, as switched.
            from .panel_invoker import _govlean_authority_switched

            try:
                switched = _govlean_authority_switched(repo_dir)
            except Exception as exc:
                raise MergeGuardRefusal(
                    "panel_merge_authority_missing", f"the repository's authority state is unreadable: {exc}",
                ) from exc
            if switched:
                raise MergeGuardRefusal(
                    "panel_merge_authority_missing", "a governed merge past the authority switch needs a landing decision",
                )
        # Read only when a landing call was made at all in this process, and read directly
        # (a local rev-parse outside the command seam), so the token path adds no command
        # to today's primitive as its caller observes it.
        common = (_common_dir_direct(repo_dir) or str(repo_dir.resolve())) if _LANDING_CALLS else None
        if common is not None and common in _LANDING_CALLS:
            raise MergeGuardRefusal("panel_merge_authority_missing", "a landing call was made for this repository")
        token._used = True
        if isinstance(action, LegacyPrMerge):
            if action.ready_first:
                ready_argv = ["gh", "pr", "ready", action.branch, *action.repo_args]
                ready = _spawn(ready_argv, cwd=action.cwd, env=action.env)
                if ready.returncode != 0:
                    raise subprocess.CalledProcessError(ready.returncode, ready_argv, ready.stdout, ready.stderr)
            argv = ["gh", "pr", "merge", action.branch, *action.repo_args, "--merge"]
            if action.delete_branch:
                argv.append("--delete-branch")
            if action.head_sha:
                argv += ["--match-head-commit", action.head_sha]
            done = _spawn(argv, cwd=action.cwd, env=action.env)
            if done.returncode != 0:
                raise subprocess.CalledProcessError(done.returncode, argv, done.stdout, done.stderr)
            return done.stdout
        if isinstance(action, LegacyPush):
            # Today's push inherits the caller's environment (a host may authenticate
            # through it); only the hook suppression is added.
            push_argv = ["git", "-C", action.cwd, "-c", "core.hooksPath=/dev/null", "push", "--no-verify",
                         action.remote, action.refspec]
            done = _spawn(push_argv, env=dict(os.environ))
            if done.returncode != 0:
                raise subprocess.CalledProcessError(done.returncode, push_argv, done.stdout, done.stderr)
            return action.refspec
        raise MergeGuardRefusal("panel_merge_action_unknown", f"unknown no-landing action {type(action).__name__}")

    def _merge_pr(repo_dir: Path, bindings: MergeBindings, b0: str) -> str:
        slug = bindings.repo_slug or ""
        pr = bindings.pr or {}
        number = str(pr.get("number"))
        live = _gh_json(["pr", "view", number, "--repo", slug, "--json",
                         "number,baseRefName,headRefOid,headRepository,url,isDraft"], cwd=repo_dir)
        for key in ("number", "baseRefName", "headRefOid", "headRepository"):
            if not isinstance(live, Mapping) or live.get(key) != pr.get(key):
                raise MergeGuardRefusal("panel_merge_pr_changed", f"the PR's live {key} changed since the decision")
        if live.get("isDraft"):
            ready = _spawn(["gh", "pr", "ready", number, "--repo", slug], cwd=repo_dir)
            if ready.returncode != 0:
                raise MergeGuardRefusal("panel_merge_ready_failed", "the draft PR could not be readied")
        merged = _spawn(["gh", "pr", "merge", number, "--repo", slug, "--merge", "--match-head-commit",
                         bindings.reviewed_head], cwd=repo_dir)
        try:
            after = _gh_json(["pr", "view", number, "--repo", slug, "--json",
                              "state,mergeCommit,baseRefName,headRepository,url"], cwd=repo_dir)
        except MergeGuardRefusal as exc:
            raise MergeGuardEscalation("panel_merge_base_moved", "the PR state after the merge cannot be read") from exc
        state = after.get("state") if isinstance(after, Mapping) else None
        if state == "MERGED":
            commit = (after.get("mergeCommit") or {}).get("oid") if isinstance(after.get("mergeCommit"), Mapping) else None
            if after.get("baseRefName") != bindings.target_branch or after.get("headRepository") != pr.get("headRepository") \
                    or not commit:
                raise MergeGuardEscalation("panel_merge_base_moved", "the merged PR's base or merge commit is not the bound one")
            _git(repo_dir, "fetch", "--no-tags", "--no-recurse-submodules", bindings.origin_url,
                 f"refs/heads/{bindings.target_branch}")
            parent = _git_out(repo_dir, "rev-parse", "--verify", f"{commit}^1")
            if parent != b0:
                raise MergeGuardEscalation("panel_merge_base_moved", "the merge commit's first parent is not B0")
            return commit
        if state != "OPEN":
            raise MergeGuardEscalation("panel_merge_base_moved", f"unexpected PR state {state!r} after the merge")
        host = _slug_parts(slug)[0]
        # Membership is read on every still-open outcome (bound to the broker host); an
        # accepted merge that left the PR open, or any membership that is not "no", is
        # treated as enqueued.
        membership = _in_merge_queue(slug, host, int(number))
        queued = merged.returncode == 0 or membership is not False
        if queued:
            if not dequeue(repo_dir, repo_slug=slug, pr_number=int(number), host=host):
                raise MergeGuardEscalation("panel_merge_dequeue_failed", "the enqueued PR could not be dequeued")
            raise MergeGuardRefusal("panel_merge_enqueued", "the merge came back enqueued; dequeued and refused")
        raise MergeGuardRefusal("panel_merge_not_merged", "GitHub rejected the merge; the PR is still open")

    def _merge_push(repo_dir: Path, bindings: MergeBindings, b0: str, commit_ref: str) -> str:
        commit = _git_out(repo_dir, "rev-parse", "--verify", f"{commit_ref}^{{commit}}")
        listed = _git_out(repo_dir, "rev-list", "--parents", "-n", "1", commit) if commit else None
        parents = (listed or "").split()[1:]
        if commit is None or parents != [b0, bindings.reviewed_head]:
            raise MergeGuardRefusal("panel_merge_binding_mismatch",
                                    "the merge commit's parents are not exactly [B0, the reviewed head]")
        tree = _git_out(repo_dir, "rev-parse", "--verify", f"{commit}^{{tree}}")
        clean = _git(repo_dir, "merge-tree", "--write-tree", b0, bindings.reviewed_head)
        clean_tree = (clean.stdout or "").splitlines()[0].strip() if clean.returncode == 0 and clean.stdout else None
        if tree is None or clean_tree is None or tree != clean_tree:
            raise MergeGuardRefusal("panel_merge_binding_mismatch",
                                    "the merge commit's tree is not the clean merge of B0 and the reviewed head")
        target = f"refs/heads/{bindings.target_branch}"
        done = _spawn(["git", "-C", str(repo_dir), "-c", "core.hooksPath=/dev/null", "push", "--no-verify", "--porcelain",
                       f"--force-with-lease={target}:{b0}", bindings.origin_url, f"{commit}:{target}"])
        if done.returncode != 0:
            raise MergeGuardRefusal("panel_merge_rejected", "the leased merge push was rejected")
        return commit

    def _push(repo_dir: Path, bindings: MergeBindings, b0: str) -> str:
        commit = bindings.reviewed_head
        if _git(repo_dir, "merge-base", "--is-ancestor", b0, commit).returncode != 0:
            raise MergeGuardRefusal("panel_merge_not_fast_forward", "the commit does not descend from the target head")
        target = f"refs/heads/{bindings.target_branch}"
        done = _spawn(["git", "-C", str(repo_dir), "-c", "core.hooksPath=/dev/null", "push", "--no-verify", "--porcelain",
                       f"--force-with-lease={target}:{b0}", bindings.origin_url, f"{commit}:{target}"])
        if done.returncode != 0:
            raise MergeGuardRefusal("panel_merge_rejected", "the leased push was rejected")
        return commit

    def _decided_merge(repo_dir: Path, entry: _DecisionEntry, action: object) -> str:
        from .advisor_board import config

        bindings = entry.bindings
        if bindings is None:
            raise MergeGuardRefusal("panel_merge_not_merge_capable", "the decision has no bound target or head")
        context = entry.context
        if getattr(action, "context", None) is not context or config.verify_panel_object(context) is None:
            raise MergeGuardRefusal("panel_merge_context_unverified", "the context is not the decision's own")
        if _common_dir(repo_dir) != bindings.git_common_dir or _origin_url(repo_dir) != bindings.origin_url:
            raise MergeGuardRefusal("panel_merge_binding_mismatch", "repository substitution")
        if getattr(action, "target_branch", None) != bindings.target_branch:
            raise MergeGuardRefusal("panel_merge_binding_mismatch", "target substitution")
        if isinstance(action, GhPrMerge):
            pr = bindings.pr
            if pr is None or action.pr_number != pr.get("number") or action.repo_slug != bindings.repo_slug \
                    or action.head_sha != bindings.reviewed_head:
                raise MergeGuardRefusal("panel_merge_binding_mismatch", "PR, repository or head substitution")
        elif isinstance(action, GitPush):
            if bindings.pr is not None or action.remote != bindings.origin_url or action.commit != bindings.reviewed_head:
                raise MergeGuardRefusal("panel_merge_binding_mismatch", "remote or head substitution")
        elif isinstance(action, GitMergePush):
            if bindings.pr is not None or action.remote != bindings.origin_url:
                raise MergeGuardRefusal("panel_merge_binding_mismatch", "remote substitution")
        else:
            raise MergeGuardRefusal("panel_merge_action_unknown", f"unknown landing action {type(action).__name__}")
        _refuse_config_redirects(repo_dir)
        slug = bindings.repo_slug
        if slug is None:
            raise MergeGuardRefusal("panel_merge_queue_unknown", "the target's branch rules cannot be read (not GitHub)")
        rules = _branch_rules(slug, bindings.target_branch)
        if rules["queue"]:
            raise MergeGuardRefusal("panel_merge_queue_target", f"{bindings.target_branch!r} is queue-protected")
        fetched = _git(repo_dir, "fetch", "--no-tags", "--no-recurse-submodules", bindings.origin_url,
                       f"refs/heads/{bindings.target_branch}")
        b0 = _git_out(repo_dir, "rev-parse", "--verify", "FETCH_HEAD^{commit}") if fetched.returncode == 0 else None
        if b0 is None:
            raise MergeGuardRefusal("panel_merge_fetch_failed", "the target could not be fetched")
        gated = context.gated_revision
        if _git(repo_dir, "merge-base", "--is-ancestor", str(gated), b0).returncode != 0:
            raise MergeGuardRefusal("panel_merge_base_not_ancestor", "the gated revision is not an ancestor of the target")
        try:
            regate = config.panel_regate_required(repo_dir, gated_revision=str(gated), target_head=b0)
        except Exception as exc:
            raise MergeGuardRefusal("panel_merge_regate_required", f"re-gate check failed: {exc}") from exc
        if regate:
            raise MergeGuardRefusal("panel_merge_regate_required", "the target changed [panel.*] or the profile")
        facts = config.verify_panel_object(context) or {}
        user_path = facts.get("user_path")
        now = config.read_user_file_digest(user_path) if user_path else None
        if now != context.snapshot.user_digest:
            raise MergeGuardRefusal("panel_merge_user_file_changed", "the user board file changed")
        if isinstance(action, GhPrMerge):
            return _merge_pr(repo_dir, bindings, b0)
        if isinstance(action, GitMergePush):
            return _merge_push(repo_dir, bindings, b0, action.commit)
        return _push(repo_dir, bindings, b0)
    repo_dir = Path(repo_dir)
    if isinstance(authority, NoLandingToken):
        return _no_landing(repo_dir, authority, action)
    entry = _DECISIONS.get(id(authority))
    if entry is None or entry.decision is not authority or _digest(authority) != entry.digest \
            or not getattr(authority, "admitted", False):
        raise MergeGuardRefusal("panel_merge_authority_missing", "no registered landing decision")
    if entry.state == "retired":
        raise MergeGuardRefusal("panel_merge_authority_retired", "the decision was refused once and is retired")
    if entry.state == "consumed":
        raise MergeGuardRefusal("panel_merge_authority_consumed", "the decision already merged")
    try:
        result = _decided_merge(repo_dir, entry, action)
    except BaseException:
        entry.state = "retired"
        raise
    entry.state = "consumed"
    return result








def _in_merge_queue(slug: str, host: str, number: int) -> bool | None:
    _host, owner, name = _slug_parts(slug)
    done = _spawn(["gh", "api", "graphql", "--hostname", host, "-f", f"query={_MEMBERSHIP_QUERY}",
                   "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={int(number)}"])
    if done.returncode != 0:
        return None
    try:
        pr = json.loads(done.stdout)["data"]["repository"]["pullRequest"]
    except (ValueError, KeyError, TypeError):
        return None
    value = pr.get("isInMergeQueue") if isinstance(pr, Mapping) else None
    return None if value is None else bool(value)


_MEMBERSHIP_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name)"
    "{pullRequest(number:$number){isInMergeQueue}}}"
)




# --- dequeue -------------------------------------------------------------------------------

_DEQUEUE_MUTATION = "mutation($id:ID!){dequeuePullRequest(input:{id:$id}){clientMutationId}}"


def dequeue(workspace: str | Path, *, repo_slug: str, host: str, pr_number: int | None = None,
            selector: str | None = None, confirm: bool = True) -> bool:
    """Remove a PR from the merge queue and cancel auto-merge. It issues only
    ``dequeuePullRequest`` and ``gh pr merge --disable-auto``, plus read-only reads, each
    bound to the broker-validated host and repository. The PR is ``pr_number``, or the
    caller's head-branch ``selector`` (``gh``'s own branch-to-PR resolution, as
    ``train_runner`` has always used). With ``confirm`` (a number is then required) it
    returns True only when membership and auto-merge are both confirmed gone; a caller that
    confirms by its own read passes ``confirm=False`` and gets True once both were attempted."""
    if (pr_number is None) == (selector is None):
        raise MergeGuardRefusal("panel_merge_grammar", "dequeue needs exactly one of a PR number or a selector")
    target = str(int(pr_number)) if pr_number is not None else str(selector)
    if target.startswith("-") or "://" in target:
        raise MergeGuardRefusal("panel_merge_grammar", f"dequeue selector {target!r} is not a number or a branch")
    view = _spawn(["gh", "pr", "view", target, "--repo", repo_slug, "--json", "id"], cwd=workspace)
    try:
        node_id = json.loads(view.stdout).get("id") if view.returncode == 0 else None
    except (ValueError, AttributeError):
        node_id = None
    if node_id:
        _spawn(["gh", "api", "graphql", "--hostname", host, "-f", f"query={_DEQUEUE_MUTATION}", "-f",
                f"id={node_id}"], cwd=workspace)
    _spawn(["gh", "pr", "merge", target, "--repo", repo_slug, "--disable-auto"], cwd=workspace)
    if not confirm:
        return True
    if pr_number is None:
        raise MergeGuardRefusal("panel_merge_grammar", "a confirmed dequeue needs the PR number")
    queued = _in_merge_queue(repo_slug, host, int(pr_number))
    state = _spawn(["gh", "pr", "view", target, "--repo", repo_slug, "--json", "autoMergeRequest"], cwd=workspace)
    try:
        auto = json.loads(state.stdout).get("autoMergeRequest") if state.returncode == 0 else "unreadable"
    except (ValueError, AttributeError):
        auto = "unreadable"
    return queued is False and auto is None


# --- publish_nontarget ---------------------------------------------------------------------

_PUSH_FLAGS = frozenset({"--no-verify", "--porcelain", "--quiet"})
_EDIT_FLAGS = frozenset({"--title", "--body", "--body-file", "--add-label", "--remove-label", "--add-reviewer"})


def _protected_destinations(repo_dir: Path, slug: str, name: str) -> bool:
    """True when ``name`` is protected: the default branch, a registered landing target,
    or a branch under classic protection or a ruleset. An unreadable lookup refuses."""
    default = _gh_json(["repo", "view", slug, "--json", "defaultBranchRef"], cwd=repo_dir)
    default_name = (default or {}).get("defaultBranchRef", {}).get("name") if isinstance(default, Mapping) else None
    if not default_name:
        raise MergeGuardRefusal("panel_merge_protection_unknown", "the default branch cannot be read")
    if name == default_name or name in {"main", "master"}:
        return True
    if any(entry.bindings is not None and entry.bindings.target_branch == name for entry in _DECISIONS.values()):
        return True
    try:
        rules = _branch_rules(slug, name)
    except MergeGuardRefusal as exc:
        raise MergeGuardRefusal("panel_merge_protection_unknown", str(exc)) from exc
    return rules["protected"]


def _open_prs_with_head(repo_dir: Path, slug: str, host: str, branch: str) -> list[Mapping[str, Any]]:
    prs = _gh_json(["pr", "list", "--repo", slug, "--head", branch, "--state", "open", "--json",
                    "number,autoMergeRequest,baseRefName,headRefName"], cwd=repo_dir)
    if not isinstance(prs, list):
        raise MergeGuardRefusal("panel_merge_pr_state_unreadable", "open PRs cannot be read")
    return prs


def _refuse_merge_bound_prs(repo_dir: Path, slug: str, branch: str) -> None:
    """Refuse when any open PR whose head is ``branch`` has auto-merge on, is queued, or has
    a queue-protected base; unreadable state refuses."""
    host = _slug_parts(slug)[0]
    for pr in _open_prs_with_head(repo_dir, slug, host, branch):
        if not isinstance(pr, Mapping) or "number" not in pr:
            raise MergeGuardRefusal("panel_merge_pr_state_unreadable", "open PR state cannot be read")
        if pr.get("autoMergeRequest"):
            raise MergeGuardRefusal("panel_merge_pr_auto_merge", f"PR #{pr['number']} has auto-merge enabled")
        queued = _in_merge_queue(slug, host, int(pr["number"]))
        if queued is not False:
            raise MergeGuardRefusal("panel_merge_pr_queued", f"PR #{pr['number']} is queued or unreadable")
        try:
            base_rules = _branch_rules(slug, str(pr.get("baseRefName")))
        except MergeGuardRefusal as exc:
            raise MergeGuardRefusal("panel_merge_pr_state_unreadable", str(exc)) from exc
        if base_rules["queue"]:
            raise MergeGuardRefusal("panel_merge_pr_queue_base", f"PR #{pr['number']}'s base is queue-protected")


def _flag_values(args: Sequence[str], start: int, allowed: frozenset[str], where: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    i = start
    while i < len(args):
        flag = args[i]
        if flag == "--draft":
            values.setdefault(flag, []).append("")
            i += 1
            continue
        if flag not in allowed or i + 1 >= len(args):
            raise MergeGuardRefusal("panel_merge_grammar", f"{where}: {flag!r} is not allowed")
        values.setdefault(flag, []).append(args[i + 1])
        i += 2
    return values


def publish_nontarget(repo_dir: str | Path, tool: str, args: Sequence[str], *,
                      declared_target: str | None = None, run=None) -> subprocess.CompletedProcess:
    """Push to, or operate on, a non-target branch -- checked against a closed grammar
    before anything runs. It resolves protected destinations and merge-bound PRs itself."""

    def _publish_push(repo_dir: Path, slug: str, args: list[str], declared_target: str | None) -> subprocess.CompletedProcess:
        if not args or args[0] != "push":
            raise MergeGuardRefusal("panel_merge_grammar", "only git push publishes")
        flags = [a for a in args[1:] if a.startswith("-")]
        positional = [a for a in args[1:] if not a.startswith("-")]
        if "--no-verify" not in flags or any(f not in _PUSH_FLAGS for f in flags) or len(positional) != 2:
            raise MergeGuardRefusal("panel_merge_grammar", "push needs --no-verify, one remote and one refspec")
        remote, refspec = positional
        if remote != _origin_url(repo_dir):
            raise MergeGuardRefusal("panel_merge_grammar", "the remote must be the bound origin URL")
        src, sep, dst = refspec.partition(":")
        if not sep or not dst.startswith("refs/heads/") or src.startswith("+") or not src \
                or not (_HEX.match(src) or src.startswith("refs/heads/")):
            raise MergeGuardRefusal("panel_merge_grammar", f"refspec {refspec!r} is not <sha|refs/heads/x>:refs/heads/<name>")
        name = dst[len("refs/heads/"):]
        if not name or (declared_target is not None and declared_target != name):
            raise MergeGuardRefusal("panel_merge_grammar", "the refspec's destination is not the declared one")
        _refuse_config_redirects(repo_dir)
        if _protected_destinations(repo_dir, slug, name):
            raise MergeGuardRefusal("panel_merge_protected", f"{name!r} is protected")
        _refuse_merge_bound_prs(repo_dir, slug, name)
        extra = [f for f in flags if f != "--no-verify"]
        return _spawn(["git", "-C", str(repo_dir), "-c", "core.hooksPath=/dev/null", "push", "--no-verify", *extra,
                       remote, refspec])
    if run is not None:
        with _caller_run(run):
            return publish_nontarget(repo_dir, tool, args, declared_target=declared_target)
    repo_dir = Path(repo_dir)
    args = [str(a) for a in args]
    slug = _repo_slug(repo_dir)
    if tool == "git":
        return _publish_push(repo_dir, slug, args, declared_target)
    if tool != "gh":
        raise MergeGuardRefusal("panel_merge_grammar", f"unknown tool {tool!r}")
    op = tuple(args[:2])
    if op == ("pr", "create"):
        values = _flag_values(args, 2, frozenset({"--repo", "--head", "--base", "--title", "--body", "--body-file"}),
                              "gh pr create")
        if values.get("--repo") != [slug] or len(values.get("--head", [])) != 1 or not values.get("--base") \
                or not values.get("--title") or not (values.get("--body") or values.get("--body-file")):
            raise MergeGuardRefusal("panel_merge_grammar", "gh pr create needs --repo --head --base --title --body")
        owner, _, branch = values["--head"][0].partition(":")
        if owner != _slug_parts(slug)[1] or not branch:
            raise MergeGuardRefusal("panel_merge_grammar", "gh pr create --head must be <owner>:<branch> in this repo")
        local = _git_out(repo_dir, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}")
        origin = _origin_url(repo_dir)
        remote = _git_out(repo_dir, "ls-remote", origin or "", f"refs/heads/{branch}") if origin else None
        published = remote.split()[0] if remote else None
        if local is None or published != local:
            raise MergeGuardRefusal("panel_merge_unpublished", f"{branch!r} is not published at its local SHA")
    elif op in (("pr", "comment"), ("pr", "edit"), ("pr", "ready"), ("issue", "comment")):
        if len(args) < 3 or not args[2].isdigit():
            raise MergeGuardRefusal("panel_merge_grammar", f"gh {' '.join(op)} needs a PR/issue number selector")
        allowed = {("pr", "comment"): frozenset({"--repo", "--body", "--body-file"}),
                   ("pr", "edit"): _EDIT_FLAGS | {"--repo"},
                   ("pr", "ready"): frozenset({"--repo"}),
                   ("issue", "comment"): frozenset({"--repo", "--body", "--body-file"})}[op]
        values = _flag_values(args, 3, allowed, f"gh {' '.join(op)}")
        if values.get("--repo") != [slug]:
            raise MergeGuardRefusal("panel_merge_grammar", "the operation must name this repository with --repo")
        if op == ("pr", "ready"):
            view = _gh_json(["pr", "view", args[2], "--repo", slug, "--json", "headRefName"], cwd=repo_dir)
            head = view.get("headRefName") if isinstance(view, Mapping) else None
            if not head:
                raise MergeGuardRefusal("panel_merge_pr_state_unreadable", "the PR's head cannot be read")
            _refuse_merge_bound_prs(repo_dir, slug, str(head))
    elif op == ("issue", "create"):
        values = _flag_values(args, 2, frozenset({"--repo", "--title", "--body", "--body-file"}), "gh issue create")
        if values.get("--repo") != [slug]:
            raise MergeGuardRefusal("panel_merge_grammar", "the operation must name this repository with --repo")
    else:
        raise MergeGuardRefusal("panel_merge_grammar", f"gh {' '.join(args[:2])} is not a publish operation")
    return _spawn(["gh", *args], cwd=repo_dir)




# --- publish_new_branch (agy_watch; agent-harness#1130 r7) ---------------------------------


def publish_new_branch(repo_dir: str | Path, *, name: str, sha: str, title: str | None = None,
                       body: str | None = None, base: str = "main", repo_slug: str | None = None,
                       push: bool = True, run=None) -> str:
    """Create ``refs/heads/<name>`` at exactly one destination, create-only; or, with
    ``push=False`` and a ``title``, open the draft PR for a branch this function created.

    The push (agent-harness#1130 r7): ``origin`` must list exactly one push destination,
    and the push goes to the remote NAME ``origin`` (never a printed URL); a ``--dry-run``
    pre-flight must print exactly one ``To`` block, and the real push exactly one ``To``
    block and one row for exactly ``refs/heads/<name>``. The lease's empty expected value
    means "must not exist"; creation is read from ``--porcelain`` flag ``*``. Returns
    ``"created"`` or the typed refusal (``refused_push_destination_ambiguous``,
    ``push_unavailable``, ``refused_branch_exists``, ``refused_ref_conflict``,
    ``refused_push_remote_rejected``, ``refused_push_failed``). The draft PR is created only
    for a branch published at exactly ``sha`` (read live with ``ls-remote``), with
    ``--head <owner>:<name>``; it returns ``gh pr create``'s output."""
    if run is not None:
        with _caller_run(run):
            return publish_new_branch(repo_dir, name=name, sha=sha, title=title, body=body, base=base,
                                      repo_slug=repo_slug, push=push)
    repo_dir = Path(repo_dir)
    if not _HEX.match(sha) or not name or name.startswith("-"):
        raise MergeGuardRefusal("panel_merge_grammar", "publish_new_branch needs an exact SHA and a branch name")
    ref = f"refs/heads/{name}"
    if not push:
        if title is None:
            raise MergeGuardRefusal("panel_merge_grammar", "publish_new_branch without a push opens a PR")
        slug = repo_slug or _repo_slug(repo_dir)
        owner = slug.split("/")[-2] if slug.count("/") >= 1 else ""
        listed = _git(repo_dir, "ls-remote", "origin", ref)
        published = (listed.stdout or "").split()[:1] if listed.returncode == 0 else []
        if not owner or published != [sha]:
            raise MergeGuardRefusal("panel_merge_unpublished", f"{ref} is not published at {sha}")
        created = _spawn(["gh", "pr", "create", "--draft", "--repo", slug, "--base", base, "--head",
                          f"{owner}:{name}", "--title", title, "--body", body or ""], cwd=repo_dir)
        if created.returncode != 0:
            raise MergeGuardRefusal("panel_merge_pr_create_failed", "the draft PR could not be created")
        return created.stdout or ""
    listed = _git(repo_dir, "remote", "get-url", "--push", "--all", "origin")
    lines = (listed.stdout or "").splitlines() if listed.returncode == 0 else []
    if len(lines) != 1 or not lines[0].strip():
        return "refused_push_destination_ambiguous"  # zero or several push destinations: push nothing

    def _argv(dry_run: bool) -> list[str]:
        return ["git", "-C", str(repo_dir), "-c", "core.hooksPath=/dev/null", "push",
                *(["--dry-run"] if dry_run else []), "--porcelain", "--no-verify", "--no-follow-tags",
                "--recurse-submodules=no", f"--force-with-lease={ref}:", "--", "origin", f"{sha}:{ref}"]

    def _to_blocks(result) -> int:
        return sum(1 for line in (result.stdout or "").splitlines() if line.startswith("To "))

    preflight = _spawn(_argv(True))
    blocks = _to_blocks(preflight)
    if blocks == 0:
        return "push_unavailable"  # auth, network or a hook failure before any status
    if blocks != 1:
        return "refused_push_destination_ambiguous"
    result = _spawn(_argv(False))
    rows = [row for row in (line.split("\t") for line in (result.stdout or "").splitlines() if "\t" in line)
            if len(row) >= 2]
    if _to_blocks(result) != 1 or len(rows) != 1 or rows[0][1] != f"{sha}:{ref}":
        return "push_unavailable"  # no single row for exactly our ref at a single destination
    flag, summary = rows[0][0].strip(), (rows[0][2] if len(rows[0]) > 2 else "")
    if flag == "*" and getattr(result, "returncode", 1) == 0:
        return "created"
    if flag == "=":
        return "refused_branch_exists"  # already there, even at our own commit: never adopted
    if flag == "!" and "stale info" in summary:
        return "refused_branch_exists"
    if flag == "!" and "refname conflict" in summary:
        return "refused_ref_conflict"
    if flag == "!" and "remote rejected" in summary:
        return "refused_push_remote_rejected"  # hook, ruleset, protection
    return "refused_push_failed"


# --- runtime-authored text -----------------------------------------------------------------


def neutralize_fragment(text: str) -> str:
    """A relayed fragment can never start a slash command or a mention."""
    text = str(text)
    return "​" + text if text.startswith(("/", "@")) else text


def fence_fragment(text: str) -> str:
    """Code-fence a relayed fragment with a fence longer than any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r"`+", str(text))), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def content_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
