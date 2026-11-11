// Tests of the rules of validate_problems.js (14-set cooldown, article sources with a licence, same substrate
// and product never twice, one article giving several examples) on small problem files built from the first
// problems of data/problems.json. Usage (project root, after `npm install @rdkit/rdkit@2026.9.1`):
//   node src/test_validate.js        the last line reads N/N as expected; exit code 1 otherwise
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const root = path.join(__dirname, '..');
const validator = path.join(__dirname, 'validate_problems.js');
const base = JSON.parse(fs.readFileSync(path.join(root, 'data', 'problems.json'), 'utf8'));
const probs = base.sets.map(s => s.problems[0]);
if (probs.length < 4) { console.log('need at least 4 problems in data/problems.json'); process.exit(1); }

const clone = o => JSON.parse(JSON.stringify(o));
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'test_validate-'));
let n = 0, ok = 0;

// one problem per day from 2030-01-01
const build = list => ({ schedule: base.schedule, sets: list.map((p, i) => ({ date: new Date(Date.UTC(2030, 0, 1 + i)).toISOString().slice(0, 10), problems: [p] })) });
const article = (p, over = {}) => {
  const q = clone(p);
  q.source = Object.assign({ repository: 'Open-access article', citation: 'A. Author, B. Author. Title. J. Test 2020, 1, 1-9.', doi: '10.1000/test-' + p.id, pmcid: 'PMC1234567', license: 'cc by', context: 'test' }, over);
  q.repositories = [{ site: 'Wikipedia', url: 'https://en.wikipedia.org/wiki/Test_reaction' }];
  return q;
};
const renamed = (p, from) => { const q = clone(p); q.reaction = from.reaction; q.names = clone(from.names); return q; };

function check(name, list, { env = {}, ok: wantOk, msg }) {
  n++;
  const file = path.join(dir, `t${n}.json`);
  fs.writeFileSync(file, JSON.stringify(build(list)));
  const r = spawnSync('node', [validator, file], { env: { ...process.env, ...env }, encoding: 'utf8' });
  const out = (r.stdout || '') + (r.stderr || '');
  const passed = (r.status === 0) === wantOk && (wantOk || !msg || out.includes(msg));
  if (passed) ok++; else console.log(`FAIL ${name}: exit ${r.status}, expected ${wantOk ? 'ALL OK' : 'failure containing "' + msg + '"'}\n${out.split('\n').slice(-8).join('\n')}`);
  console.log(`${passed ? 'ok  ' : 'FAIL'} ${name}`);
}

const [p0, p1, p2, p3] = probs;

check('unchanged problems pass', [p0, p1, p2], { ok: true });
check('article example with licence cc by passes', [article(p0), p1], { ok: true });
check('article example with licence cc by-nc-sa passes', [article(p0, { license: 'cc by-nc-sa' }), p1], { ok: true });
check('article example without licence fails', [article(p0, { license: undefined }), p1], { ok: false, msg: 'source.license' });
check('article example with no-derivatives licence fails', [article(p0, { license: 'cc by-nd' }), p1], { ok: false, msg: 'source.license' });
check('article example with a matching licenseUrl passes', [article(p0, { licenseUrl: 'https://creativecommons.org/licenses/by/4.0/' }), p1], { ok: true });
check('article example with a licenseUrl of another licence fails', [article(p0, { licenseUrl: 'https://creativecommons.org/licenses/by-nc/4.0/' }), p1], { ok: false, msg: 'source.licenseUrl' });
check('article example with a licenseUrl outside creativecommons.org fails', [article(p0, { licenseUrl: 'https://example.org/licenses/by/4.0/' }), p1], { ok: false, msg: 'source.licenseUrl' });
check('article example without DOI fails', [article(p0, { doi: undefined }), p1], { ok: false, msg: 'source.doi is required' });
check('article example without citation fails', [article(p0, { citation: '' }), p1], { ok: false, msg: 'source.citation' });
check('same substrate and product fails', [p0, Object.assign(article(p0, { doi: '10.1000/other' }), { id: 'dup-id', reaction: 'Zzyzx reaction', names: ['Zzyzx reaction'] })], { ok: false, msg: 'same substrate and product as' });
check('reaction repeated after 3 sets fails with the default cooldown (14)', [p0, p1, p2, renamed(p3, p0)], { ok: false, msg: 'less than 14 sets ago' });
check('reaction repeated after 3 sets passes with a window of 3', [p0, p1, p2, renamed(p3, p0)], { env: { REPEAT_WINDOW: '3' }, ok: true });
check('reaction repeated after 3 sets fails with a window of 4', [p0, p1, p2, renamed(p3, p0)], { env: { REPEAT_WINDOW: '4' }, ok: false, msg: 'less than 4 sets ago' });
check('same article and reaction twice fails', [article(p0, { doi: '10.1000/same' }), article(renamed(p3, p0), { doi: '10.1000/same' })], { env: { REPEAT_WINDOW: '1' }, ok: false, msg: 'same example and reaction already used' });
check('same article, different entry passes', [article(p0, { doi: '10.1000/same', entry: '1' }), article(renamed(p3, p0), { doi: '10.1000/same', entry: '2' })], { env: { REPEAT_WINDOW: '1' }, ok: true });

fs.rmSync(dir, { recursive: true, force: true });
console.log(`${ok}/${n} as expected`);
process.exit(ok === n ? 0 : 1);
