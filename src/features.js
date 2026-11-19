// Problem features for the selection models (ML_PLAN.md): one entry per published or queued problem, from
// data/problems.json and data/archive.json.gz, written to data/features.json. Same file in
// QDher/Daily-organic-chemistry-puzzles and QDher/Daily-name-reaction-puzzle.
// Called at the end of src/build.js; needs @rdkit/rdkit (npm install @rdkit/rdkit@2026.9.1). If RDKit is missing the
// build goes on without features. The output has no time stamp, so it changes only when the problems change.
// Usage alone: node src/features.js            (from the repository root)
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const round = (x, d = 2) => (x === null || x === undefined || Number.isNaN(x) ? null : Math.round(x * 10 ** d) / 10 ** d);

function loadSets(root) {
  const sets = JSON.parse(fs.readFileSync(path.join(root, 'data', 'problems.json'), 'utf8')).sets;
  const arch = path.join(root, 'data', 'archive.json.gz');
  const old = fs.existsSync(arch) ? JSON.parse(zlib.gunzipSync(fs.readFileSync(arch)).toString('utf8')).sets : [];
  return [...old, ...sets];
}

function molInfo(R, smiles) {
  const m = smiles ? R.get_mol(smiles) : null;
  if (!m || !m.is_valid()) { if (m) m.delete(); return null; }
  const d = JSON.parse(m.get_descriptors());
  m.delete();
  return { heavyAtoms: d.NumHeavyAtoms, rings: d.NumRings, aromaticRings: d.NumAromaticRings, heteroatoms: d.NumHeteroatoms,
    stereocentres: d.NumAtomStereoCenters, fsp3: round(d.FractionCSP3), mw: round(d.exactmw, 1) };
}

function features(R, p, date) {
  const steps = p.steps || [];
  const reagents = steps.flatMap(s => s.reagents || []);
  const sub = molInfo(R, p.substrate && p.substrate.smiles), prod = molInfo(R, p.product && p.product.smiles);
  const src = p.source || {};
  const idSource = (/^([a-z]+?)(\d{4})-/.exec(p.id) || []);
  return {
    id: p.id, date,
    level: p.level || null, textbookLevel: p.textbookLevel || null,           // One-Pot only
    reaction: p.reaction || null,
    source: src.repository || idSource[1] || null,                            // repository (Name Reaction) or journal prefix of the id
    sourceYear: idSource[2] ? Number(idSource[2]) : null,
    steps: steps.length,
    intermediates: steps.reduce((a, s) => a + (s.intermediates || []).length, 0),
    forms: steps.reduce((a, s) => a + (s.intermediates || []).reduce((b, it) => b + (it.forms || []).length, 0), 0),
    stepLevels: steps.map(s => s.stepLevel || null),
    reagents: reagents.length, reagentsWithSmiles: reagents.filter(r => r.smiles).length,
    uncommonReagents: reagents.filter(r => r.uncommon).length,
    hints: (p.hints || []).length,
    difficultyScore: p.difficulty ? p.difficulty.score : null,
    sigmaBondEvents: p.difficulty ? p.difficulty.sigmaBondEvents : null,
    substrate: sub, product: prod,
    heavyAtomChange: sub && prod ? prod.heavyAtoms - sub.heavyAtoms : null,
    ringChange: sub && prod ? prod.rings - sub.rings : null,
    verified: !!p.verified,
  };
}

async function writeFeatures(root) {
  const R = await require('@rdkit/rdkit')();
  const out = [];
  for (const s of loadSets(root)) for (const p of s.problems) out.push(features(R, p, s.date));
  out.sort((a, b) => (a.date === b.date ? (a.id < b.id ? -1 : 1) : a.date < b.date ? -1 : 1));
  fs.writeFileSync(path.join(root, 'data', 'features.json'), JSON.stringify({ version: 1, problems: out }, null, 1) + '\n');
  return out.length;
}

module.exports = { writeFeatures, features };
if (require.main === module) {
  writeFeatures(path.join(__dirname, '..')).then(n => console.log(`features: ${n} problems -> data/features.json`))
    .catch(e => { console.error(e); process.exit(1); });
}
