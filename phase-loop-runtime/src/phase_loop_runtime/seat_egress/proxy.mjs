// The egress proxy of one jailed Gemini seat (agent-harness#1170): srt's TLS-terminating
// proxy with a request-level allowlist, behind a fail-closed inspecting front. It runs on
// the host, outside the seat. argv: <srt dist/index.js> <config.json>. One JSON line on
// stdout when ready; it exits when stdin closes.
//
// Observation (plans/seats-firstseat-containment-contract.md section 14). After the ready
// line, stdout carries one metadata-only line per request decision -- method, host,
// templated path, decision; never a query, header, body or credential -- and one
// acknowledgement per fence read from stdin. Neither changes a decision, its reason, the
// allowlist or the ready line.
//
// Why the front (F006/grok-A). srt's forward proxy decides to TERMINATE a CONNECT only when
// the first flight looks like a TLS ClientHello (record type 0x16, legacy version <=0x0303);
// anything else it OPAQUE-tunnels straight to the CONNECT target's address, running none of
// the inner Host/method/path (filterRequest) or inner-SNI (SNICallback) checks. That fallback
// is unconditional on the terminated path and cannot be turned off through
// SandboxManager.initialize. A client that sends a first flight with a non-standard record
// version byte (e.g. 0x04), then a disallowed SNI, is opaque-tunnelled to a Google frontend
// that routes by SNI to another API. The front closes that: the seat reaches ONLY this front,
// which forwards to srt ONLY a positively-inspected ClientHello whose SNI is on the allowlist;
// every other first flight is refused and no bytes reach any upstream. So srt always
// terminates (never opaque-tunnels) and its inner checks always run.
import { readFileSync } from 'node:fs';
import { createServer, connect } from 'node:net';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const { SandboxManager } = await import(process.argv[2]);
const config = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const FRONT_IDLE_MS = config.front_idle_ms ?? 30000;
if (!Number.isInteger(FRONT_IDLE_MS) || FRONT_IDLE_MS < 1 || FRONT_IDLE_MS > 30000) {
  process.stderr.write('front idle bound is invalid\n');
  process.exit(3);
}
const rules = config.allow;
const hosts = new Set(rules.map(rule => rule.host.toLowerCase()));

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
    observe(request.method, url.hostname, url.pathname, 'deny');
    return { action: 'deny', reason: 'the inner Host does not name the tunnel host' };
  }
  if (!allowed(request.method, url.hostname, url.pathname)) {
    observe(request.method, url.hostname, url.pathname, 'deny');
    return { action: 'deny', reason: 'not on the seat request allowlist' };
  }
  observe(request.method, url.hostname, url.pathname, 'allow');
  return { action: 'allow' };
}

// --- request observation and fences -----------------------------------------------------
// Closed vocabulary: a host outside the allowlist, the token-endpoint table and the
// reserved canary form is `<other>`; a path is the matching rule's template.
const TOKEN_HOSTS = new Set(['oauth2.googleapis.com', 'accounts.google.com',
  'sts.googleapis.com', 'iamcredentials.googleapis.com', 'www.googleapis.com']);
const METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'CONNECT']);
const QUIET_MS = 2000;
let openFront = 0;
let openSrt = 0;
let pendingFence = null;
let quietFrom = 0;

function observedHost(host) {
  return hosts.has(host) || TOKEN_HOSTS.has(host) || /^[0-9a-f]{32}\.invalid$/.test(host)
    ? host : '<other>';
}

function observedPath(host, path) {
  if (path === null) return null;
  const rule = rules.find(r => r.host === host
    && (r.path !== undefined ? path === r.path : path.startsWith(r.path_prefix)));
  if (rule) return rule.path !== undefined ? rule.path : rule.path_prefix + '*';
  if (path === '/oauth2/v2/userinfo') return path;
  return path.startsWith('/oauth2/') ? '/oauth2/*' : '<other>';
}

function observe(method, host, path, decision) {
  const name = String(host || '').toLowerCase();
  process.stdout.write(JSON.stringify({
    event: 'request', method: METHODS.has(method) ? method : '<other>',
    host: observedHost(name), path: observedPath(name, path), decision,
  }) + '\n');
  quietFrom = Date.now();
}

function activity() { quietFrom = Date.now(); }

// A fence is acknowledged once no front client and no socket to srt is open and nothing
// has been observed for QUIET_MS. It never closes the front or touches a decision.
function checkFence() {
  if (pendingFence === null) return;
  if (openFront === 0 && openSrt === 0 && Date.now() - quietFrom >= QUIET_MS) {
    const id = pendingFence;
    pendingFence = null;
    process.stdout.write(JSON.stringify({ event: 'fence', id }) + '\n');
    return;
  }
  setTimeout(checkFence, 50);
}

function controlLine(line) {
  let id = null;
  try {
    const doc = JSON.parse(line);
    if (doc && typeof doc.id === 'string' && /^[0-9a-f]{32}$/.test(doc.id)
        && line === JSON.stringify({ op: 'fence', id: doc.id })) id = doc.id;
  } catch { /* not a fence: no output */ }
  if (id === null || pendingFence !== null) return;
  pendingFence = id;
  quietFrom = Date.now();
  setTimeout(checkFence, 50);
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
const srtSocket = SandboxManager.getLinuxHttpSocketPath();
const token = SandboxManager.getProxyAuthToken();
if (!srtSocket || !token) {
  process.stderr.write('no srt proxy socket\n');
  process.exit(3);
}
const expectedAuth = 'Basic ' + Buffer.from(`srt:${token}`, 'utf8').toString('base64');

// --- the fail-closed inspecting front -------------------------------------------------
const MAX_HEADER = 16 * 1024;
const FRONT_MAX_HELLO_BYTES = 16389; // TLS header plus the maximum one-record payload

// Parse ONE complete TLS handshake record holding a ClientHello and return its SNI host, or
// null when the bytes are not positively a ClientHello, or 'need-more' when a longer
// (bounded) read might complete the first record. Never treats a non-ClientHello as allowed.
function clientHelloSNI(buf) {
  if (buf.length < 5) return 'need-more';
  if (buf[0] !== 0x16 || buf[1] !== 0x03 || buf[2] > 0x03) return null; // not a TLS handshake record
  const recLen = (buf[3] << 8) | buf[4];
  if (recLen < 4 || 5 + recLen > FRONT_MAX_HELLO_BYTES) return null;
  if (buf.length < 5 + recLen) return 'need-more';
  let p = 5;
  if (buf[p] !== 0x01) return null; // not ClientHello
  const hsLen = (buf[p + 1] << 16) | (buf[p + 2] << 8) | buf[p + 3];
  const hsEnd = p + 4 + hsLen;
  if (hsEnd > 5 + recLen) return null;
  p += 4;
  p += 2 + 32; // client_version + random
  if (p + 1 > hsEnd) return null;
  p += 1 + buf[p]; // session_id
  if (p + 2 > hsEnd) return null;
  p += 2 + ((buf[p] << 8) | buf[p + 1]); // cipher_suites
  if (p + 1 > hsEnd) return null;
  p += 1 + buf[p]; // compression_methods
  if (p + 2 > hsEnd) return null;
  const extEnd = p + 2 + ((buf[p] << 8) | buf[p + 1]);
  p += 2;
  if (extEnd > hsEnd) return null;
  while (p + 4 <= extEnd) {
    const type = (buf[p] << 8) | buf[p + 1];
    const len = (buf[p + 2] << 8) | buf[p + 3];
    p += 4;
    if (p + len > extEnd) return null;
    if (type === 0x0000) { // server_name
      if (len < 2) return null;
      const listLen = (buf[p] << 8) | buf[p + 1];
      const listEnd = p + 2 + listLen;
      if (listEnd !== p + len) return null;
      let q = p + 2;
      while (q + 3 <= listEnd) {
        const nameType = buf[q];
        const nameLen = (buf[q + 1] << 8) | buf[q + 2];
        q += 3;
        if (q + nameLen > listEnd) return null;
        if (nameType === 0x00) return buf.slice(q, q + nameLen).toString('ascii').toLowerCase();
        q += nameLen;
      }
      return null; // server_name extension without a host_name
    }
    p += len;
  }
  return null; // no SNI: cannot positively inspect an allowed-SNI ClientHello -> refuse
}

function refuse(socket, status) {
  try { socket.end(`HTTP/1.1 ${status}\r\n\r\n`); } catch { socket.destroy(); }
}

function spliceToSrt(client, target, firstFlight) {
  const up = connect({ path: srtSocket });
  openSrt += 1;
  activity();
  up.once('close', () => { openSrt -= 1; activity(); });
  up.on('error', () => client.destroy());
  client.on('error', () => up.destroy());
  up.once('connect', () => {
    up.write(`CONNECT ${target}:443 HTTP/1.1\r\nHost: ${target}:443\r\n` +
             `Proxy-Authorization: ${expectedAuth}\r\n\r\n`);
  });
  let head = Buffer.alloc(0);
  const onSrtHead = chunk => {
    head = Buffer.concat([head, chunk]);
    const idx = head.indexOf('\r\n\r\n');
    if (idx === -1) { if (head.length > MAX_HEADER) up.destroy(); return; }
    const status = head.slice(0, head.indexOf('\r\n')).toString('latin1');
    if (!/^HTTP\/1\.[01] 200/.test(status)) { client.destroy(); up.destroy(); return; }
    up.removeListener('data', onSrtHead);
    const rest = head.slice(idx + 4);
    up.write(firstFlight);
    if (rest.length) client.write(rest);
    up.pipe(client);
    client.pipe(up);
  };
  up.on('data', onSrtHead);
  client.once('close', () => up.destroy());
  up.once('close', () => client.destroy());
}

const front = createServer(client => {
  openFront += 1;
  activity();
  const idle = setTimeout(() => client.destroy(), FRONT_IDLE_MS);
  idle.unref();
  client.once('close', () => { clearTimeout(idle); openFront -= 1; activity(); });
  client.on('error', () => client.destroy());
  let buf = Buffer.alloc(0);
  let phase = 'connect';
  let target = null;
  client.on('data', chunk => {
    if (phase === 'spliced') return; // nothing is buffered after the splice
    idle.refresh();
    buf = Buffer.concat([buf, chunk]);
    if (phase === 'connect') {
      const idx = buf.indexOf('\r\n\r\n');
      if (idx === -1) { if (buf.length > MAX_HEADER) refuse(client, '400 Bad Request'); return; }
      const header = buf.slice(0, idx).toString('latin1');
      buf = buf.slice(idx + 4);
      const line = header.split('\r\n')[0];
      const auth = /\r\nproxy-authorization:[ \t]*([^\r\n]+)/i.exec('\r\n' + header);
      if (!auth || auth[1].trim() !== expectedAuth) {
        return refuse(client, '407 Proxy Authentication Required');
      }
      const m = /^CONNECT[ \t]+([^\s:]+):(\d+)[ \t]/i.exec(line);
      if (!m || m[2] !== '443' || !hosts.has(m[1].toLowerCase())) {
        observe(m ? 'CONNECT' : line.split(/[ \t]/)[0].toUpperCase(), m ? m[1] : '', null, 'deny');
        return refuse(client, '403 Forbidden');
      }
      target = m[1].toLowerCase();
      phase = 'firstflight';
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (buf.length) inspect();
      return;
    }
    if (phase === 'firstflight') inspect();
  });
  function inspect() {
    const sni = clientHelloSNI(buf);
    if (sni === 'need-more') {
      if (buf.length > FRONT_MAX_HELLO_BYTES) { // never grow unbounded; fail closed
        phase = 'refused';
        observe('CONNECT', target, null, 'deny');
        client.destroy();
      }
      return;
    }
    if (sni && sni === target && hosts.has(sni)) {
      phase = 'spliced';
      clearTimeout(idle); // the idle bound is PRE-SPLICE only
      spliceToSrt(client, target, buf);
    } else {
      phase = 'refused';
      observe('CONNECT', target, null, 'deny');
      client.destroy(); // not a positively-inspected allowed-SNI ClientHello: no bytes upstream
    }
  }
});
front.on('error', err => { process.stderr.write(`front: ${err.message}\n`); process.exit(3); });
const frontSocket = join(mkdtempSync(join(tmpdir(), 'pl-seat-front-')), 'front.sock');
front.listen(frontSocket, () => {
  process.stdout.write(JSON.stringify({
    socket: frontSocket, token, tls_inspection: true,
    inner_sni_check: Boolean(config.inner_sni_check), fail_closed_front: true,
  }) + '\n');
});
front.unref();
// The parent may stop reading; an observation write must never end the proxy.
process.stdout.on('error', () => {});
let control = '';
let discarding = false;
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  control += chunk;
  let at;
  while ((at = control.indexOf('\n')) !== -1) {
    const line = control.slice(0, at);
    control = control.slice(at + 1);
    if (discarding) { discarding = false; continue; }
    controlLine(line);
  }
  if (control.length > 4096) { control = ''; discarding = true; } // over-long: never a fence
});
process.stdin.resume();
process.stdin.on('end', async () => {
  try { front.close(); } catch { /* closing */ }
  await SandboxManager.reset();
  process.exit(0);
});
