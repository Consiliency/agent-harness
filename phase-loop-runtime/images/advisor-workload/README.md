# Native advisor workload source recipe

This recipe prepares one linux/amd64 image with Claude Code 2.1.321, Codex
0.167.0, Gemini through **agy 1.5.3**, and Grok 1.0.77. It is a build input,
not a published image or an authentication qualification. It does not change
`review-runner`, the remote execution driver, or gateway configuration.

## Payload and dependency provenance

`payload.lock.json` records upstream npm archive URLs and SHA-512 integrity,
the agy release URL and SHA-512 from its maintained installer receipt, Node
24.22.2's installer pin, Debian library archive URLs and SHA-256, and SHA-256
for every exported file. The native file hashes were measured from the pinned
maintained installation; they are not vendor signatures. Archive integrity and
installed-file hashes are separate evidence. agy is not the generic Gemini CLI.

`prepare.py` copies only the enumerated files from explicitly supplied release
roots. It validates every source before creating a new output directory, rejects
escaping realpaths and duplicate destinations, and verifies copied bytes again.
It never discovers user installations or reads user authentication. Grok is the
maintained installer's Brotli-decoded native payload; its original compressed
npm archive remains pinned. Node is included for interpreter availability.
The complete Codex platform vendor tree retains its adjacent helper executables,
resources, libraries and license notices. No npm install scripts are executed.

The base is the same immutable Python 3.12 Bookworm image used by
`../review-runner/Containerfile`. Two pinned Debian archives supply the GCC and
C++ runtime libraries; extraction does not run maintainer scripts. Their hashes
are checked before extraction. No host libraries are copied into the image.
The final account database contains `sandbox` UID/GID 10001 and the OCI config
uses `USER 10001:10001`, with a writable home and `/work`.

The build runs `check.py` as that user. It checks every payload hash, ELF machine
and interpreter, dynamic dependencies and realpaths, including optional Codex
native resources. It emits library hashes and rejects unresolved dependencies.
The check does not launch advisors or contact providers. Host ELF inspection
cannot replace this in-image check. It does not prove runtime `dlopen`, tool
execution, authentication, egress, or streaming behavior. General development
toolchains and Git are not installed by this opinion-workload recipe.

## Reproduce after build admission

Use fresh directories outside the repository; do not use a home directory as a
build context. Download the two exact `debian` URLs in the lock into `$DEBS`;
`prepare.py` validates their bytes. `$TOOLING` must be the maintained release
root matching the lock and `$AGY` the matching agy release directory. These
variables are paths, never credential values.

```sh
python phase-loop-runtime/images/advisor-workload/prepare.py \
  --tooling "$TOOLING" --agy "$AGY" --debian "$DEBS" --output "$PAYLOAD"
# Only after shared-host admission and capacity checks:
docker buildx build --platform linux/amd64 --network=none \
  --build-context payload="$PAYLOAD" \
  --output type=oci,dest="$OCI_ARCHIVE" \
  -f phase-loop-runtime/images/advisor-workload/Containerfile \
  phase-loop-runtime/images/advisor-workload
```

The OCI output digest must be measured after building; no workload digest is
claimed here. The base pull may need registry access; RUN steps require none.
Use a builder with bounded resources/concurrency. Retain its metadata and
closure output, inspect the final OCI architecture and numeric user, and use
only that immutable manifest digest for subsequent qualification. There is no
push, deployment, gateway start, or provider-import step in this recipe.

Small source checks (one process, no vendor calls):

```sh
timeout 900 python -m unittest discover \
  -s phase-loop-runtime/images/advisor-workload -p test_workload.py -v
```

## Subscription authentication requirements

Evidence baseline: official OpenShell 0.1.7 source
`5d25211b25a8fc887e8d5c606d57d6ab22f1d76c`. Its provider catalog consists of
explicitly imported examples, not preconfigured subscription accounts.
The source `crates/openshell-cli/src/commands/common.rs::parse_credential_pairs`
accepts literal `KEY=value` arguments or a `KEY` environment lookup. It does
not implement a credential-file or stdin flag. `--from-existing` discovers
credentials; it is not an access-only filter. No such commands are run here.
Proxy placeholders are supported by OpenShell, but their acceptance by each
subscription CLI must be separately demonstrated. Do not put credentials into
image layers, argv, environment, logs, output or build contexts; do not upload
refresh tokens or substitute account/provider/API billing.

| Advisor | Exact evidence | Required qualification |
| --- | --- | --- |
| Claude | Native help supports print/JSON modes and subscription auth commands. OpenShell `providers/claude-code.yaml` supplies API-key authentication. | A supported subscription access-only delivery channel and placeholder compatibility. The API-key example is not that channel. |
| Codex | Native help advertises `login --with-access-token` on stdin. Exact `rust-v0.167.0` source (commit `086ccc833bc9cf01024ad2dd6af7dbd421b6bf9a`) `codex-rs/login/src/auth/access_token.rs` and `manager.rs::login_with_access_token` select personal access token or Agent Identity authentication. OpenShell's example requires refresh-token fields. | Do not treat the stdin flag as support for existing subscription OAuth access-token import. Establish the approved same-account subscription flow, expiry handling and credential-free delivery separately. |
| Gemini / agy | agy 1.5.3 help supports print, model, effort and stream JSON. Existing harness integration uses its home-file credential layout. | Document supported access-only semantics, delivery, expiry and placeholder compatibility. Google Cloud/Vertex profiles do not establish agy support. |
| Grok | Native help supports single-turn, prompt-file and streaming JSON. Existing harness integration references `.grok/auth.json` and `.grok/agent_id`. | Document the supported subscription schema and secure access-only delivery, expiry and provider profile; the observed file layout is not permission to copy credentials. |

No supported end-to-end all-four credential delivery path is established by
these sources. Keep activation gated until the provider/control owners supply
that evidence. This recipe implements no token converter or credential loader.

## Invocation integration boundary

Keep existing provider, account, model/effort selection and result parsers. The
minimal later adapter must map each selected advisor to these realpaths:

| Advisor | Executable realpath | Observed output surface |
| --- | --- | --- |
| Claude | `/opt/advisors/bin/claude` | `-p`, `--output-format stream-json` |
| Codex | `/opt/advisors/codex/bin/codex` | `exec --json`, read-only sandbox and ephemeral options |
| Gemini / agy | `/opt/advisors/bin/agy` | `-p`, `--output-format stream-json`, explicit model/effort |
| Grok | `/opt/advisors/bin/grok` | `--prompt-file`, `--output-format streaming-json` |

These are observed syntax surfaces, not authorized live commands. Preserve
stdin, stdout, stderr, exit status, timeouts and cancellation through the
existing upload/exec/download primitives; do not reinterpret single-turn mode
as isolation. Reject missing image/auth qualification or unsupported selection,
with no host fallback. Do not enable the currently false remote driver merely
because the binaries exist. This change adds no execution adapter.

Egress candidates must be qualified against the exact binary realpaths above.
The stock Claude example lists `api.anthropic.com:443` plus optional telemetry;
Codex lists `chatgpt.com:443`, `api.openai.com:443`, `auth.openai.com:443` and
`ab.chatgpt.com:443`. These examples are not subscription allowlists. Existing
agy 1.3.3 measured policy in `seat_egress/gemini-allowlist.json` permits POST
`daily-cloudcode-pa.googleapis.com:443/v1internal:*`, GET
`www.googleapis.com:443/oauth2/v2/userinfo`, and GET
`lh3.googleusercontent.com:443/a/*`; it does not qualify agy 1.5.3. No exact Grok
subscription endpoint set is established here. Preserve that uncertainty and
require exact endpoint/path/credential-binding evidence before execution.
