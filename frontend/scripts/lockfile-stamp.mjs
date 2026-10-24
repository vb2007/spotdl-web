// v52 (D4): the stamp of what `npm ci` installs from package-lock.json, for the dev `web`
// container (frontend/Dockerfile's dev stage writes it, docker-compose.override.yml's dev command
// compares it). The app's own version is left out: every slice bumps it, and it changes nothing
// npm installs, so a bump alone never reinstalls.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const lock = JSON.parse(readFileSync(process.argv[2] ?? 'package-lock.json', 'utf8'));
delete lock.version;
if (lock.packages?.['']) delete lock.packages[''].version;
process.stdout.write(createHash('sha256').update(JSON.stringify(lock)).digest('hex'));
