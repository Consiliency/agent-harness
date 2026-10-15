// Generate this host's seat egress CA (agent-harness#1170) with srt's own generator.
// argv: <srt dist/index.js> <directory>. The key file is created 0600 and never overwritten.
import { writeFileSync } from 'node:fs';

const { generateCa } = await import(process.argv[2]);
const directory = process.argv[3];
const ca = generateCa({ cn: 'phase-loop seat egress CA' });
writeFileSync(`${directory}/ca.key`, ca.keyPem, { mode: 0o600, flag: 'wx' });
writeFileSync(`${directory}/ca.crt`, ca.certPem, { mode: 0o644, flag: 'wx' });
