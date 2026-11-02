// chemkey.js — comparison key for drawn structures (RDKit.js >= 2026.09)
// Ignores: stereocentres, E/Z, H-tautomers (incl. keto/enol), protonation state,
// counterions and by-products (only the fragment most similar to the substrate is kept).
// Not merged: some tautomer classes (e.g. nitro/aci-nitro) and resonance forms of
// delocalized anions/cations — store every accepted form.

const HETERO = new Set([7, 8, 15, 16]); // N, O, P, S

function popcount(bytes) {
  let n = 0;
  for (let b of bytes) { while (b) { n += b & 1; b >>= 1; } }
  return n;
}

function fingerprint(mol) {
  return mol.get_morgan_fp_as_uint8array(JSON.stringify({ radius: 2, nBits: 2048 }));
}

function tanimoto(a, b) {
  let both = 0;
  for (let i = 0; i < a.length; i++) both += popcount([a[i] & b[i]]);
  const tot = popcount(a) + popcount(b) - both;
  return tot ? both / tot : 0;
}

// Keep the fragment most similar to the reference (substrate) fingerprint;
// without a reference, keep the largest fragment.
function mainFragment(RDKit, mol, refFp) {
  const parts = mol.get_smiles().split('.');
  if (parts.length === 1) return mol;
  mol.delete();
  let best = null, bestScore = -1, bestN = -1;
  for (const p of parts) {
    const m = RDKit.get_mol(p);
    if (!m || !m.is_valid()) continue;
    const n = m.get_num_atoms();
    const score = refFp ? tanimoto(fingerprint(m), refFp) : 0;
    if (score > bestScore || (score === bestScore && n > bestN)) {
      if (best) best.delete();
      best = m; bestScore = score; bestN = n;
    } else m.delete();
  }
  return best;
}

// Neutralize protonation-type charges only:
//  - carbanions gain H (ylides become onium salts)
//  - heteroatom anions gain H, unless bonded to a cation (nitro, N-oxide, azide, sulfoxide)
//  - N/O/P/S cations bearing H lose H
//  - carbocations, oxocarbenium and quaternary onium ions keep their charge
function neutralize(RDKit, mol) {
  mol.remove_hs_in_place();
  const doc = JSON.parse(mol.get_json());
  const d = doc.defaults.atom;
  const m = doc.molecules[0];
  const atoms = m.atoms.map(a => ({ ...d, ...a }));
  const nbrs = atoms.map(() => []);
  for (const b of m.bonds || []) { nbrs[b.atoms[0]].push(b.atoms[1]); nbrs[b.atoms[1]].push(b.atoms[0]); }
  let changed = false;
  atoms.forEach((a, i) => {
    if (a.chg < 0 && (a.z === 6 || !nbrs[i].some(j => atoms[j].chg > 0))) {
      a.impHs += -a.chg; a.chg = 0; changed = true;
    } else if (a.chg > 0 && HETERO.has(a.z) && a.impHs >= a.chg) {
      a.impHs -= a.chg; a.chg = 0; changed = true;
    }
  });
  if (!changed) return mol;
  m.atoms = atoms.map(a => ({ z: a.z, impHs: a.impHs, chg: a.chg, nRad: a.nRad, isotope: a.isotope }));
  delete m.extensions;
  delete m.conformers; // RDKit.js cannot re-read its own exported 2D coordinates
  const out = RDKit.get_mol(JSON.stringify(doc));
  mol.delete();
  return out;
}

const inchiOf = mol => mol.get_inchi('-SNon -KET -15T').replace(/\/p[+-]\d+/, '');

// Prototropic tautomers that InChI does not merge (e.g. dienol / α,β-enone / β,γ-enone,
// nitro / aci-nitro): enumerate 1,3 and 1,5 H-shifts with at least one N/O/S end,
// away from aromatic rings and radicals (end atoms uncharged), and keep the smallest InChI.
const TAUT_ENDS = new Set([7, 8, 16]);
const TAUT_ATOMS = new Set([6, 7, 8, 16]);
const TAUT_CAP = 400;

function tautomerKey(RDKit, mol) {
  const doc = JSON.parse(mol.get_json());
  const d = doc.defaults.atom, db = doc.defaults.bond, m = doc.molecules[0];
  const arom = new Set(((m.extensions || []).find(e => e.aromaticAtoms) || {}).aromaticAtoms || []);
  const atoms = m.atoms.map(a => ({ ...d, ...a }));
  const bonds = (m.bonds || []).map(b => ({ a: b.atoms[0], b: b.atoms[1], bo: b.bo ?? db.bo }));
  const adj = atoms.map(() => []);
  bonds.forEach((b, i) => { adj[b.a].push([b.b, i]); adj[b.b].push([b.a, i]); });
  const ok = i => TAUT_ATOMS.has(atoms[i].z) && !arom.has(i) && atoms[i].chg === 0 && atoms[i].nRad === 0;

  const build = (hs, bos) => {
    const j = { rdkitjson: { version: 12 }, defaults: doc.defaults, molecules: [{
      atoms: atoms.map((a, i) => ({ z: a.z, impHs: hs[i], chg: a.chg, nRad: a.nRad, isotope: a.isotope })),
      bonds: bonds.map((b, i) => ({ atoms: [b.a, b.b], bo: bos[i] })) }] };
    return RDKit.get_mol(JSON.stringify(j));
  };
  const moves = (hs, bos) => {
    const out = [];
    const saturated = i => adj[i].every(([, bi]) => bos[bi] === 1);
    for (let x = 0; x < atoms.length; x++) {
      if (!hs[x] || !ok(x) || !saturated(x)) continue;
      for (const [y, xy] of adj[x]) {
        if (!TAUT_ATOMS.has(atoms[y].z) || arom.has(y) || atoms[y].nRad) continue; // middle atom may be charged (nitro)
        for (const [z, yz] of adj[y]) {
          if (z === x || bos[yz] !== 2 || !ok(z)) continue;
          if (TAUT_ENDS.has(atoms[x].z) || TAUT_ENDS.has(atoms[z].z)) {
            const h = hs.slice(), b = bos.slice();
            h[x]--; h[z]++; b[xy] = 2; b[yz] = 1; out.push([h, b]);
          }
          for (const [w, zw] of adj[z]) {
            if (w === y || bos[zw] !== 1 || !ok(w)) continue;
            for (const [v, wv] of adj[w]) {
              if (v === z || bos[wv] !== 2 || !ok(v)) continue;
              if (!TAUT_ENDS.has(atoms[x].z) && !TAUT_ENDS.has(atoms[v].z)) continue;
              const h = hs.slice(), b = bos.slice();
              h[x]--; h[v]++; b[xy] = 2; b[yz] = 1; b[zw] = 2; b[wv] = 1; out.push([h, b]);
            }
          }
        }
      }
    }
    return out;
  };

  let best = inchiOf(mol);
  const seen = new Set([mol.get_smiles()]);
  const queue = [[atoms.map(a => a.impHs), bonds.map(b => b.bo)]];
  while (queue.length && seen.size < TAUT_CAP) {
    const [hs, bos] = queue.shift();
    for (const [h, b] of moves(hs, bos)) {
      const t = build(h, b);
      if (!t || !t.is_valid()) { if (t) t.delete(); continue; }
      const smi = t.get_smiles();
      if (!seen.has(smi)) {
        seen.add(smi);
        const k = inchiOf(t);
        if (k < best) best = k;
        queue.push([h, b]);
      }
      t.delete();
    }
  }
  return best;
}

// input: SMILES or molfile. refFp: fingerprint of the substrate (optional).
// Returns the key string, or null if the structure is invalid or empty.
function chemKey(RDKit, input, refFp) {
  let mol = RDKit.get_mol(input);
  if (!mol || !mol.is_valid() || mol.get_num_atoms() === 0) return null;
  mol = mainFragment(RDKit, mol, refFp);
  if (!mol) return null;
  mol = neutralize(RDKit, mol);
  if (!mol || !mol.is_valid()) return null;
  const key = tautomerKey(RDKit, mol);
  mol.delete();
  return key || null;
}

function substrateFingerprint(RDKit, smiles) {
  const m = RDKit.get_mol(smiles);
  const fp = fingerprint(m);
  m.delete();
  return fp;
}

if (typeof module !== 'undefined') module.exports = { chemKey, substrateFingerprint };
if (typeof window !== 'undefined') Object.assign(window, { chemKey, substrateFingerprint });
