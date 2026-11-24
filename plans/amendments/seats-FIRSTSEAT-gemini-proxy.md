# FIRSTSEAT amendment for Gemini credential-free proxy admission

**Owner approval recorded on 2026-11-24** in the agent-harness coordination record, for [Consiliency/agent-harness#2157](https://github.com/Consiliency/agent-harness/issues/2157): a standalone amendment (no frozen-contract edit), with qualification under the owner account on the owner's primary board host.
This record amends the [FIRSTSEAT phase plan](../phase-plan-v1-seats-FIRSTSEAT.md)
ownership rule and the application of FIRSTSEAT §§11 and 14 to the opt-in mode.
The [implementation plan](../detailed-2157-gemini-proxy-20261124.md) owns the work.

## Frozen inputs

| Input | SHA-256 |
| --- | --- |
| [FIRSTSEAT containment contract](../seats-firstseat-containment-contract.md) | `a57d46f722e22973f0522a8bc254856e6224d50b1b67893cab2b80522c4942a6` |
| [FIRSTSEAT interfaces](../artifacts/seats-firstseat-interfaces.md) | `b50a3a85e2f89d47b0d83f7a7cea117fc52ad04616e6616a7c4064816654ec79` |
| [K1 window-kit contract](../artifacts/seats-window-kit-k1-contract.md) | `aa30ce0a2f947fd004476ac62f1c964c57a1e6554cc273e16366c92a2088e967` |

Keep all three files byte-identical. The roadmap goals, IF-0 bindings, W1 schedule,
and historical receipts retain their existing interpretation and content bindings.

## Proxy ownership and §14

Authorize the host front to support an explicit launch-local mode for jailed Gemini.
Reject opt-in by any other provider. In this mode Gemini receives
`http://127.0.0.1:3128`, the IPv4 loopback listener in its private network namespace.
The private host front admits CONNECT without client auth and injects canonical
authentication on its private hop to SRT. A matching client header admits the
request to the same policy checks and SRT still receives host-injected auth.
A nonmatching `Proxy-Authorization` yields 407 before observation or dialing.
The readiness probe sends a dummy `Proxy-Authorization` and requires 407 through
the launch's bound bridge. Verify listener, holder namespace, bridge and socket
identity to establish that the response came from this launch's front.

The FIRSTSEAT SL-0 proxy-unchanged rule and §14's “fences are the only addition
to the proxy's lifecycle” remain binding on the default authenticated mode,
including the existing request matrix and unmodified egress tests. Both modes
keep the existing readiness-line keys and values, with a socket and token
generated per launch. Both modes keep the allowlists, fence and EOF protocol,
and complete request accounting. The following matrix applies to the new mode.

| Case | Required evidence |
| --- | --- |
| Allowed request with no client header | CONNECT and allowed inner request succeed through SRT, with canonical auth only on the private hop. |
| Present, matching client header | With a synthetic credential, the request reaches the same allowlist checks as header-free CONNECT and the front injects canonical auth on the private hop. |
| Present, invalid client header | Readiness yields 407 with zero upstream bytes and zero observations before the start fence. |
| Policy refusals | Forbidden CONNECT authority, inner host, method or path, and refuse-all each retain their decision and reason. Bad or mismatched ClientHello/SNI fails closed. |
| Direct and cross-launch access | Direct IPv4, IPv6, DNS, host and peer namespace paths remain blocked. A cross-wired, misplaced or dead bridge/front fails readiness. Host sockets stay outside the jail. |
| Lifecycle | Requests stay inside their acknowledged fences, including immediate client close. Malformed control input, EOF, and teardown retain §14 behavior. |

## §11 fail-closed-front check

In the measured leg's existing §9 bracket, `b_fail_closed_front` requires
`HTTPS_PROXY` to equal `http://127.0.0.1:3128` exactly. Any other value,
including a URL with userinfo, exits with a nonqualifying code before dialing.
The probe sends CONNECT without `Proxy-Authorization`.
Require a successful CONNECT to the pinned allowed authority before sending the
two existing mismatched-SNI ClientHello variants. Require a completed attempt
with the expected refusal signature and zero upstream bytes for both variants.
A 407 at this step, a timeout, or a client or harness failure leaves the row
unavailable. The readiness 407 is a distinct pre-fence proof. Preserve the pinned
targets, bracket event rules and all other §11 rows.

## Qualification authority

Run one integrated Gemini W1 with the admitted agy image and the owner's
delivered Gemini credential under the owner account on the owner's primary
board host. That integrated run belongs to the owner account and stays outside CI.
Then record a fresh provider-free EC-EXECFIND-2 pass for every host and account
pair that launches jailed Gemini, including collaborator accounts on every host.
Each collaborator runs their own pass with the shared-host headroom check.
