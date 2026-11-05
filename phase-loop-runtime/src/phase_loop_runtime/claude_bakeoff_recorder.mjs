// The W0 capture twin's request recorder (SEATS CLAUDE lane D, IF-0-CLAUDE-2).
//
// It runs on the host, for one capture twin, on the verified srt install the seat egress
// layer uses; seat_egress/ is not edited. srt terminates TLS with a per-window private CA
// (trusted only through the twin's CA variable) and calls filterRequest for every request,
// which this recorder allows and records as METHOD, HOST and a TEMPLATED PATH: never a
// header, a query, a body or an untemplated identifier. A front in front of srt splices only
// a positively parsed TLS ClientHello whose SNI names the CONNECT target, so every recorded
// connection is one srt terminated; any other first flight is closed and recorded as not
// terminated. A set is complete only when every connection the recorder saw was terminated
// and had a request parsed. Traffic that bypasses the proxy is not seen at all.
//
// argv: <srt dist/index.js> <config.json>. config: {ca_cert, ca_key, out}. One JSON line on
// stdout when ready: {"port": N, "token": "..."} (the token goes only into the twin's proxy
// variable). It exits when stdin closes. Output lines (appended to config.out, mode 0600):
//   {"kind":"request","method":..., "host":..., "path_template":...}
//   {"kind":"connection","terminated":bool,"parsed":bool}
import { appendFileSync, readFileSync } from 'node:fs';
import { createServer, connect } from 'node:net';

const { SandboxManager } = await import(process.argv[2]);
const config = JSON.parse(readFileSync(process.argv[3], 'utf8'));

const IDENTIFIER = /^(?:[0-9a-f]{8}-[0-9a-f-]{27,}|[0-9]{4,}|[0-9a-f]{12,}|[A-Za-z0-9_-]{24,}|.*[0-9].*[0-9].*[0-9].*)$/i;
const LITERAL = /^(?:[a-z][a-z0-9._-]{0,63}|v[0-9]{1,3})$/;

function template(pathname) {
  const segments = pathname.split('/').slice(1).map(segment => {
    if (segment === '') return '';
    let decoded = segment;
    try { decoded = decodeURIComponent(segment); } catch { return '{id}'; }
    if (IDENTIFIER.test(decoded) || !LITERAL.test(decoded)) return '{id}';
    return decoded;
  });
  return '/' + segments.join('/');
}

function record(line) {
  appendFileSync(config.out, JSON.stringify(line) + '\n', { mode: 0o600 });
}

const parsedHosts = new Map();

async function filterRequest(request) {
  let url;
  try { url = new URL(request.url); } catch { return { action: 'allow' }; }
  const host = url.hostname.toLowerCase();
  parsedHosts.set(host, (parsedHosts.get(host) || 0) + 1);
  record({ kind: 'request', method: String(request.method).toUpperCase(), host,
           path_template: template(url.pathname) });
  return { action: 'allow' };
}

await SandboxManager.initialize({
  network: {
    allowedDomains: ['*'],
    deniedDomains: [],
    tlsTerminate: { caCertPath: config.ca_cert, caKeyPath: config.ca_key },
    filterRequest,
  },
  filesystem: { denyRead: [], allowWrite: [], denyWrite: [] },
});
const ca = SandboxManager.getMitmCA();
const srtSocket = SandboxManager.getLinuxHttpSocketPath();
const token = SandboxManager.getProxyAuthToken();
if (!ca || !srtSocket || !token) {
  process.stderr.write('tls termination is not active\n');
  process.exit(3);
}
const expectedAuth = 'Basic ' + Buffer.from(`srt:${token}`, 'utf8').toString('base64');
const MAX_HEADER = 16 * 1024;
const MAX_FIRST_RECORD = 18 * 1024;

function clientHelloSNI(buf) {
  if (buf.length < 5) return 'need-more';
  if (buf[0] !== 0x16 || buf[1] !== 0x03 || buf[2] > 0x03) return null;
  const recLen = (buf[3] << 8) | buf[4];
  if (recLen < 4 || recLen > MAX_FIRST_RECORD) return null;
  if (buf.length < 5 + recLen) return 'need-more';
  let p = 5;
  if (buf[p] !== 0x01) return null;
  const hsEnd = p + 4 + ((buf[p + 1] << 16) | (buf[p + 2] << 8) | buf[p + 3]);
  if (hsEnd > 5 + recLen) return null;
  p += 4 + 2 + 32;
  if (p + 1 > hsEnd) return null;
  p += 1 + buf[p];
  if (p + 2 > hsEnd) return null;
  p += 2 + ((buf[p] << 8) | buf[p + 1]);
  if (p + 1 > hsEnd) return null;
  p += 1 + buf[p];
  if (p + 2 > hsEnd) return null;
  let extEnd = p + 2 + ((buf[p] << 8) | buf[p + 1]);
  p += 2;
  if (extEnd > hsEnd) extEnd = hsEnd;
  while (p + 4 <= extEnd) {
    const type = (buf[p] << 8) | buf[p + 1];
    const len = (buf[p + 2] << 8) | buf[p + 3];
    p += 4;
    if (p + len > extEnd) return null;
    if (type === 0x0000) {
      let q = p + 2;
      while (q + 3 <= p + len) {
        const nameLen = (buf[q + 1] << 8) | buf[q + 2];
        if (buf[q] === 0x00) return buf.slice(q + 3, q + 3 + nameLen).toString('ascii').toLowerCase();
        q += 3 + nameLen;
      }
      return null;
    }
    p += len;
  }
  return null;
}

function connection(state) {
  if (state.recorded) return;
  state.recorded = true;
  const parsed = state.terminated && (parsedHosts.get(state.target) || 0) > state.before;
  record({ kind: 'connection', terminated: state.terminated, parsed });
}

const front = createServer(client => {
  const state = { target: null, terminated: false, before: 0, recorded: false };
  client.on('error', () => client.destroy());
  client.once('close', () => { if (state.target !== null) connection(state); });
  let buf = Buffer.alloc(0);
  let phase = 'connect';
  client.on('data', chunk => {
    if (phase === 'spliced') return;
    buf = Buffer.concat([buf, chunk]);
    if (phase === 'connect') {
      const idx = buf.indexOf('\r\n\r\n');
      if (idx === -1) { if (buf.length > MAX_HEADER) client.destroy(); return; }
      const header = buf.slice(0, idx).toString('latin1');
      buf = buf.slice(idx + 4);
      const auth = /\r\nproxy-authorization:[ \t]*([^\r\n]+)/i.exec('\r\n' + header);
      const m = /^CONNECT[ \t]+([^\s:]+):(\d+)[ \t]/i.exec(header.split('\r\n')[0]);
      if (!auth || auth[1].trim() !== expectedAuth || !m) { client.destroy(); return; }
      state.target = m[1].toLowerCase();
      state.port = m[2];
      state.before = parsedHosts.get(state.target) || 0;
      phase = 'firstflight';
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (buf.length === 0) return;
    }
    const sni = clientHelloSNI(buf);
    if (sni === 'need-more') { if (buf.length > MAX_FIRST_RECORD) client.destroy(); return; }
    if (sni !== state.target) { client.destroy(); return; }
    phase = 'spliced';
    state.terminated = true;
    const up = connect({ path: srtSocket });
    up.on('error', () => client.destroy());
    up.once('connect', () => up.write(
      `CONNECT ${state.target}:${state.port} HTTP/1.1\r\nHost: ${state.target}:${state.port}\r\n` +
      `Proxy-Authorization: ${expectedAuth}\r\n\r\n`));
    let head = Buffer.alloc(0);
    const first = buf;
    const onHead = data => {
      head = Buffer.concat([head, data]);
      const at = head.indexOf('\r\n\r\n');
      if (at === -1) { if (head.length > MAX_HEADER) up.destroy(); return; }
      if (!/^HTTP\/1\.[01] 200/.test(head.slice(0, head.indexOf('\r\n')).toString('latin1'))) {
        state.terminated = false; client.destroy(); up.destroy(); return;
      }
      up.removeListener('data', onHead);
      up.write(first);
      if (head.length > at + 4) client.write(head.slice(at + 4));
      up.pipe(client);
      client.pipe(up);
    };
    up.on('data', onHead);
    client.once('close', () => up.destroy());
    up.once('close', () => client.destroy());
  });
});
front.on('error', err => { process.stderr.write(`front: ${err.message}\n`); process.exit(3); });
front.listen(0, '127.0.0.1', () => {
  process.stdout.write(JSON.stringify({ port: front.address().port, token }) + '\n');
});
process.stdin.resume();
process.stdin.on('end', async () => {
  try { front.close(); } catch { /* closing */ }
  await SandboxManager.reset();
  process.exit(0);
});
