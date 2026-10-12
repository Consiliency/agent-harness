// The egress proxy of one jailed Gemini seat (agent-harness#1170): srt's TLS-terminating
// proxy with a request-level allowlist. It runs on the host, outside the seat, and holds no
// credential. argv: <srt dist/index.js> <config.json>. One JSON line on stdout when ready;
// it exits when stdin closes.
import { readFileSync } from 'node:fs';

const { SandboxManager } = await import(process.argv[2]);
const config = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const rules = config.allow;
const hosts = new Set(rules.map(rule => rule.host));

function allowed(method, host, path) {
  return rules.some(rule => rule.host === host && rule.method === method
    && (rule.path !== undefined ? path === rule.path : path.startsWith(rule.path_prefix)));
}

// The inner Host must name the tunnel's own host: a request that names another host inside
// an allowed tunnel is refused, not forwarded.
function innerHost(request, url) {
  const named = (request.headers.get('host') || '').toLowerCase().replace(/:443$/, '');
  return named === '' || named === url.hostname.toLowerCase();
}

async function filterRequest(request) {
  const url = new URL(request.url);
  if (!innerHost(request, url)) {
    return { action: 'deny', reason: 'the inner Host does not name the tunnel host' };
  }
  if (!allowed(request.method, url.hostname, url.pathname)) {
    return { action: 'deny', reason: 'not on the seat request allowlist' };
  }
  return { action: 'allow' };
}

await SandboxManager.initialize({
  network: {
    allowedDomains: rules.map(rule => `${rule.host}:${rule.port}`),
    deniedDomains: [],
    tlsTerminate: { caCertPath: config.ca_cert, caKeyPath: config.ca_key },
    filterRequest,
  },
  filesystem: { denyRead: [], allowWrite: [], denyWrite: [] },
});

const ca = SandboxManager.getMitmCA();
if (!ca || !ca.secureContexts) {
  process.stderr.write('tls termination is not active\n');
  process.exit(3);
}
if (config.inner_sni_check) {
  // The inner SNI must name an allowed host: the terminating server mints its leaf through
  // this cache, so a refusal here ends the handshake.
  const contexts = ca.secureContexts;
  const lookup = contexts.get.bind(contexts);
  contexts.get = name => {
    if (!hosts.has(String(name).toLowerCase())) {
      throw new Error('the inner SNI is not on the seat allowlist');
    }
    return lookup(name);
  };
  let refused = false;
  try { contexts.get('sni-self-test.invalid'); } catch { refused = true; }
  if (!refused) {
    process.stderr.write('inner SNI check is not in force\n');
    process.exit(3);
  }
}
const socket = SandboxManager.getLinuxHttpSocketPath();
if (!socket) {
  process.stderr.write('no proxy socket\n');
  process.exit(3);
}
process.stdout.write(JSON.stringify({
  socket, token: SandboxManager.getProxyAuthToken(), tls_inspection: true,
  inner_sni_check: Boolean(config.inner_sni_check),
}) + '\n');
process.stdin.resume();
process.stdin.on('end', async () => {
  await SandboxManager.reset();
  process.exit(0);
});
