# Consiliency/agent-harness#875: choose the bounded integration

Status: proposal for architectural review, not an executable plan or authority
to change dotfiles' accepted gate. No source/runtime/operator change is proposed
for landing by this document alone.

## Consumer and verified facts

ViperJuice/dotfiles is evaluating CLIProxyAPI subscription pooling. Its accepted
CONTRACT child plan is one serial offline lane producing a compatibility matrix
and a stdlib metadata checker. It permits no installation of a gateway, OAuth,
credential reads, live requests, account changes or native session changes.
Nevertheless its pre-dispatch IF-0-VC-2 requires independently authenticated owner
decision reduction and a protected final-closeout handoff before even offline
implementation. Final readiness/PILOT requires actual product/provider/billing/
host/account/window decisions, original-message binding, currentness/revocation,
fresh invocation/report binding and observation expiry. These must not be faked.

The plan calls this a pre-existing "human_required decision-reduction route";
the author failed to qualify such a route. `human_required` is a workflow field.
Four reviewers accepted the plan subject to the explicit qualification gate;
their agreement did not create the missing capability.

Read-only source observations on Agent Harness main
`d29a5d2db5e11fb912a29f7f6f312eab353eabb8`:

- `phase-loop-runtime/src/phase_loop_runtime/cli.py`: `_init_command` creates
  folders/ignore entries; `status` calls `status_snapshot`, `write_state` and
  `write_tui_handoff`. Status is not a pure read. The latter creates the expected
  isolated CONTRACT snapshot in a disposable fixture.
- `verification_evidence.py:append_evidence_entry` preserves bytes and wraps
  caller metadata in a runtime timestamp. It has no owner-authentication check.
  `events.py:append_payload` is likewise storage, not authorization.
- `task_message_resolver.py:CodexAppServerTaskMessageResolver.resolve` uses an
  authenticated app-server connection, finds exactly two ordered `userMessage`
  items by client IDs, requires an approval JSON body with `authorized=true`,
  an allowlisted contract version and matching source IDs/hash; it enforces a
  bounded message age. Recognized bodies are embedding deploy/bootstrap and
  GPU install/fence contracts. There is no general product-decision contract.
- `task_message_broker.py` and `task_message_broker_client.py` already implement
  authenticated bounded probe/resolve requests and metadata result validation.
  Prefer reuse over building a second approval transport.
- `deploy/phase-loop-task-message-broker.service` runs `User=viperjuice` and
  mounts that user's app-server control socket into the service sandbox. This
  does not establish that an unrestricted same-user executor cannot access the
  original socket or forge source history by another allowed API. No exploit is
  claimed or attempted. The authority qualification must cover the upstream
  source, not just the worker's ability to invoke the append helper.
- Repo-local state differs by worktree, while `roadmap_authority.py` resolves
  authority markers via Git's common directory. A linked worktree is not an OS
  trust boundary. A digest or a second model is not independent administration.

Prior bounded qualification on `347dde90ceb28fba58d4d6225cd71f3aaf640d00` compared
205 installed Python modules to the Git export. Seven import tests and seven
installed blocking controls passed. Merged Consiliency/agent-harness#827 repairs
the import warning. No full-runtime or authority qualification is inferred.

## Candidate A: enforce the existing consumer gate

Reuse the task-message transport. Separately establish a trusted operator/source
and supervisor inaccessible to the CONTRACT worker, including its credential,
control-socket, process, filesystem and task-message write surfaces. The worker
gets a bounded isolated snapshot and cannot mint/alter decisions or final
receipts. A source `userMessage` type alone is insufficient if the worker can
create matching history. Scope/digest/currentness/revocation and authenticated
source binding must be independently checked before final reduction; report
identity/expiry and serial final writer must be checked after worker completion.

Only after that boundary is identified can a bounded additive owner-decision
schema/resolver integration and its tests be planned. Extending the allowlist
alone, adding an `approved` boolean, or signing with an executor-readable key
is not the solution. Qualification must include a genuine independent positive
case, intended negative controls and no broadening of existing approval bodies.
Source/admin setup and live qualification would be separate work with explicitly
named ownership. The consumer stays stopped until the original gate is proven.

## Candidate B: review the placement of the prerequisite

Propose an explicit consumer plan amendment that permits ONLY offline, non-
authoritative matrix/checker implementation before the independent owner route
exists. Keep unresolved owner/provider/billing facts blocked; the offline checker
continues to state `owner_decision_authenticity=not_checked`. Keep the full
independent route mandatory for CONTRACT acceptance, IF-0-CONTRACT-1, PILOT and
all live/account/deprecation work. Do not report offline completion as readiness.

This changes the accepted pre-dispatch policy; it cannot be applied silently or
presented as satisfying current IF-0-VC-2. It needs a concrete amendment, fresh
panel reconciliation and owner disposition on the policy change. It might allow
useful adoption research without immediately building a new approval service,
but does not resolve the ultimate live-acceptance dependency.

## Decision requested from the reviewers

Recommend the smallest defensible next step: A, B, or an existing concrete route
we missed. Identify hidden assumptions and whether the consumer author created
an unnecessary early dependency. Which exact changes, if any, are safe to plan
now, and which require real operator/source isolation evidence first? If B is
recommended, distinguish an explicit reviewed prerequisite relocation from
bypassing the currently accepted gate. Do not declare either approach implemented.

No account/RC/Display changes, canonical state changes, root service deployment,
provider API fallback, retired native feature credit, or frozen-stack changes are
authorized by this proposal. ViperJuice/dotfiles#256 and ViperJuice/dotfiles#248
remain frozen. Consiliency/agent-harness#752's president operation remains
distinct; owner-authorized manual presidency covers review disposition only.
