// The egress proxy of one jailed Gemini seat (agent-harness#1170): srt's TLS-terminating
// proxy with a request-level allowlist, behind a fail-closed inspecting front. It runs on
// the host, outside the seat. argv: <srt dist/index.js> <config.json>. One JSON line on
// stdout when ready; it exits when stdin closes.
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
const srtSocket = SandboxManager.getLinuxHttpSocketPath();
const token = SandboxManager.getProxyAuthToken();
if (!srtSocket || !token) {
  process.stderr.write('no srt proxy socket\n');
  process.exit(3);
}
const expectedAuth = 'Basic ' + Buffer.from(`srt:${token}`, 'utf8').toString('base64');

// --- the fail-closed inspecting front -------------------------------------------------
const MAX_HEADER = 16 * 1024;
const MAX_FIRST_RECORD = 18 * 1024; // a ClientHello record; larger is refused, not grown

// Parse ONE complete TLS handshake record holding a ClientHello and return its SNI host, or
// null when the bytes are not positively a ClientHello, or 'need-more' when a longer
// (bounded) read might complete the first record. Never treats a non-ClientHello as allowed.
function clientHelloSNI(buf) {
  if (buf.length < 5) return 'need-more';
  if (buf[0] !== 0x16 || buf[1] !== 0x03 || buf[2] > 0x03) return null; // not a TLS handshake record
  const recLen = (buf[3] << 8) | buf[4];
  if (recLen < 4 || recLen > MAX_FIRST_RECORD) return null;
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
  let extEnd = p + 2 + ((buf[p] << 8) | buf[p + 1]);
  p += 2;
  if (extEnd > hsEnd) extEnd = hsEnd;
  while (p + 4 <= extEnd) {
    const type = (buf[p] << 8) | buf[p + 1];
    const len = (buf[p + 2] << 8) | buf[p + 3];
    p += 4;
    if (p + len > extEnd) return null;
    if (type === 0x0000) { // server_name
      let q = p + 2; // skip server_name_list length
      while (q + 3 <= p + len) {
        const nameType = buf[q];
        const nameLen = (buf[q + 1] << 8) | buf[q + 2];
        q += 3;
        if (q + nameLen > p + len) return null;
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
  client.on('error', () => client.destroy());
  let buf = Buffer.alloc(0);
  let phase = 'connect';
  let target = null;
  client.on('data', chunk => {
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
      if (buf.length > MAX_FIRST_RECORD) client.destroy(); // never grow unbounded; fail closed
      return;
    }
    if (sni && hosts.has(sni)) {
      phase = 'spliced';
      spliceToSrt(client, target, buf);
    } else {
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
process.stdin.resume();
process.stdin.on('end', async () => {
  try { front.close(); } catch { /* closing */ }
  await SandboxManager.reset();
  process.exit(0);
});
