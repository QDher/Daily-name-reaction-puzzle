// Checks data/problems.json before publishing. Exit code 1 if anything fails.
// Usage (from the project root, after `npm install @rdkit/rdkit@2026.9.1`):
//   node src/validate_problems.js [data/problems.json]
const path = require('path');
const fs = require('fs');
const init = require('@rdkit/rdkit');
const { speciesInfo, matches, substrateFingerprint } = require('./chemkey.js');
const { readArchive } = require('./archive.js');
const file = process.argv[2] || path.join(__dirname, '..', 'data', 'problems.json');
const data = JSON.parse(fs.readFileSync(file, 'utf8'));

const MAX_HINTS = 5;
const REPEAT_WINDOW = 90;          // a reaction may not come back within this many sets
const REPO_HOSTS = ['say-my-name.net', 'www.organic-chemistry.org', 'www.tcichemicals.com'];
const norm = s => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/[‐-―−-]/g, ' ').replace(/[^a-z0-9 ]/g, ' ')
  .split(/\s+/).filter(w => w && !['reaction', 'the', 'rxn'].includes(w)).join(' ');

// Text shown before solving (substrate label, reagent text, conditions) must not indicate the mechanism,
// fragments lost or reacting atoms. Mechanistic wording belongs in intermediate labels and "reaction".
const LEAK = /intramolecular|intermolecular|cycli[sz]|annulation|fragment|eliminat|rearrang|sigmatropic|\[\d,\d\]|migrat|loss of|\blost\b|extru|decarboxyl|tautomer|aldol|michael|wittig|ylide|acceptor|\bdonor|\bsource\b|carbamic|isocyanate|intermediate|\bvia\b|attack|nucleophil|electrophil|modification|procedure/i;
function leakErrors(P) {
  const out = [], seen = (where, s) => { const m = String(s || '').match(LEAK); if (m) out.push(`${where} "${s}" contains "${m[0]}"`); };
  seen('substrate label', P.substrate && P.substrate.label);
  for (const st of P.steps || []) {
    seen(`step ${st.n} conditions`, st.conditions);
    for (const r of st.reagents || []) {
      seen(`step ${st.n} reagent`, r.text);
      if (r.smiles && /^\[[A-Z][a-z]?H?[0-3]?\+\]$/.test(r.smiles)) out.push(`step ${st.n} reagent "${r.text}" drawn as a bare cation (${r.smiles}); give the real reagent`);
    }
  }
  return out;
}

init().then(R => {
  const errors = [];
  const err = (where, msg) => errors.push(`${where}: ${msg}`);

  const dates = data.sets.map(s => s.date);
  if ([...dates].sort().join() !== dates.join()) err('sets', 'dates are not in ascending order');
  if (new Set(dates).size !== dates.length) err('sets', 'duplicate date');
  const ids = new Map(), steps = new Map(), lastSeen = new Map();
  // archived sets (data/archive.json.gz) count for ids, examples and the repeat window (negative set indices)
  const archived = readArchive();
  archived.forEach((day, k) => { for (const P of day.problems) {
    const tag = day.date + ' (archived)';
    ids.set(P.id, tag);
    steps.set((P.source && (P.source.doi || P.source.url)) + ' | ' + P.reaction, tag);
    lastSeen.set(norm(P.reaction), { i: k - archived.length, date: tag });
  } });
  const archivedDates = new Set(archived.map(s => s.date));
  for (const d of dates) if (archivedDates.has(d)) err(d, 'date also present in data/archive.json.gz');

  data.sets.forEach((day, di) => {
    if (day.problems.length !== 1) err(day.date, `exactly one problem per day (found ${day.problems.length})`);
    for (const P of day.problems) {
      const w = `${day.date} ${P.id}`;
      if (ids.has(P.id)) err(w, `id already used on ${ids.get(P.id)}`); else ids.set(P.id, day.date);
      const stepKey = (P.source && (P.source.doi || P.source.url)) + ' | ' + P.reaction;
      if (steps.has(stepKey)) err(w, `same example and reaction already used on ${steps.get(stepKey)}`); else steps.set(stepKey, day.date);
      for (const k of ['reaction', 'names', 'repositories', 'source', 'substrate', 'steps', 'product', 'mechanismRefs', 'hints', 'difficulty'])
        if (!(k in P)) err(w, `missing field "${k}"`);
      if ('level' in P || 'textbookLevel' in P) err(w, 'no level fields on this page (remove "level" / "textbookLevel")');
      // example source: a DOI, or (for an example drawn on a Named Reactions Explorer page) that page's URL
      const src = P.source || {};
      if (src.doi && !/^10\.\d{4,9}\//.test(src.doi)) err(w, 'source.doi malformed');
      if (!src.doi) {
        if (src.repository !== 'Named Reactions Explorer') err(w, 'source.doi is required unless the example is the equation of a Named Reactions Explorer page');
        else if (!/^https:\/\/say-my-name\.net\/reaction\/[a-z0-9-]+\/$/.test(src.url || '')) err(w, 'source.url must be the say-my-name.net reaction page (https://say-my-name.net/reaction/<slug>/)');
      }

      // names and repositories
      leakErrors(P).forEach(m => err(w, 'mechanism indicated before solving: ' + m));
      { const shown = [P.substrate && P.substrate.label, ...P.steps.flatMap(st => [st.conditions, ...st.reagents.map(r => r.text)])].map(norm).join(' | ');
        const generic = /\b(synthesis|rearrangement|olefination|reaction|formylation|degradation|cyclization|annulation|reduction|oxidation|condensation|coupling|alkyne|pyrrole|indole)\b/g;
        for (const n of P.names || []) { const core = norm(n).replace(generic, ' ').replace(/\s+/g, ' ').trim(); if (core.length > 3 && shown.includes(core)) err(w, `answer "${n}" appears in the text shown before solving`); } }
      const names = P.names || [];
      if (!names.length || !names.includes(P.reaction)) err(w, '"names" must be a non-empty list that includes "reaction"');
      const rk = norm(P.reaction);
      if (lastSeen.has(rk) && di - lastSeen.get(rk).i < REPEAT_WINDOW) err(w, `reaction already used on ${lastSeen.get(rk).date} (less than ${REPEAT_WINDOW} sets ago)`);
      lastSeen.set(rk, { i: di, date: day.date });
      const repos = P.repositories || [];
      if (!repos.length) err(w, 'at least one repository page is required');
      for (const r of repos) {
        let host = '';
        try { host = new URL(r.url).host; } catch (e) { err(w, 'repository url unreadable: ' + r.url); continue; }
        if (!REPO_HOSTS.includes(host)) err(w, `repository host ${host} not in ${REPO_HOSTS.join(', ')}`);
        if (!r.site) err(w, 'repository entry without "site"');
      }
      if (!P.source || !repos.some(r => r.site === P.source.repository)) err(w, 'source.repository must name the repository page the example was taken from (one of the "repositories" sites)');

      // structures
      let fp;
      try { fp = substrateFingerprint(R, P.substrate.smiles); } catch (e) { err(w, 'substrate SMILES unreadable'); continue; }
      // species are compared as on the page: same structure up to protonation, counterions, stereo and
      // tautomers in which protons move to or from N, O or S (chemkey.js)
      const sub = speciesInfo(R, P.substrate.smiles, fp), prod = speciesInfo(R, P.product.smiles, fp);
      if (!sub.key) err(w, 'substrate SMILES unreadable');
      if (!prod.key) err(w, 'product SMILES unreadable');
      if (matches(sub, prod)) err(w, 'product is the same species as the substrate');
      for (const st of P.steps) for (const r of st.reagents)
        if (r.smiles) { const m = R.get_mol(r.smiles); if (!m || !m.is_valid()) err(w, `reagent ${r.text}: SMILES unreadable`); if (m) m.delete(); }
      const seen = [{ label: 'substrate', infos: [sub] }, { label: 'product', infos: [prod] }];
      let distinct = 0;
      for (const st of P.steps) for (const [k, it] of st.intermediates.entries()) {
        const infos = it.forms.map(f => speciesInfo(R, f, fp));
        if (!it.forms.length || infos.some(x => !x.key)) err(w, `step ${st.n} intermediate ${k + 1}: unreadable or missing form`);
        const clash = seen.filter(o => o.infos.some(a => infos.some(b => matches(a, b)))).map(o => o.label);
        if (clash.length) err(w, `step ${st.n} intermediate ${k + 1} is the same species as ${clash.join(', ')} (tautomer with a proton moved to or from N/O/S, protonation state or resonance form); merge or remove it`);
        else distinct++;
        seen.push({ label: `step ${st.n} intermediate ${k + 1}`, infos });
      }
      if (distinct < 2) err(w, `only ${distinct} distinct intermediate(s); at least 2 are required`);

      // hints
      const nh = (P.hints || []).length;
      if (nh < 2 || nh > MAX_HINTS) err(w, `${nh} hints (expected 2 to ${MAX_HINTS}); run curate.py --write`);
      for (const h of P.hints || []) {
        let smi = P.substrate.smiles;
        if (h.mol === 'reagent') {
          const st = P.steps.find(s => s.n === h.step);
          const r = st && st.reagents.find(r => r.text === h.reagent);
          smi = r && r.smiles;
        }
        const m = smi && R.get_mol(smi);
        if (!m || !(h.atom >= 0 && h.atom < m.get_num_atoms())) err(w, 'hint atom does not exist: ' + JSON.stringify(h));
        if (m) m.delete();
      }
      console.log(`${w}: ${P.reaction}; ${distinct} intermediates, ${nh} hints, score ${P.difficulty && P.difficulty.score}`);
    }
  });
  if (errors.length) { console.log('\nFAILED\n- ' + errors.join('\n- ')); process.exit(1); }
  console.log('\nALL OK');
});
