// Checks data/problems.json before publishing. Exit code 1 if anything fails.
// Usage (from the project root, after `npm install @rdkit/rdkit@2026.9.1`):
//   node src/validate_problems.js [data/problems.json]
const path = require('path');
const fs = require('fs');
const init = require('@rdkit/rdkit');
const { chemKey, substrateFingerprint } = require('./chemkey.js');
const file = process.argv[2] || path.join(__dirname, '..', 'data', 'problems.json');
const data = JSON.parse(fs.readFileSync(file, 'utf8'));

const MAX_HINTS = 5;
const REPEAT_WINDOW = 90;          // a reaction may not come back within this many sets
const REPO_HOSTS = ['say-my-name.net', 'www.organic-chemistry.org', 'www.tcichemicals.com'];
const norm = s => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/[‐-―−-]/g, ' ').replace(/[^a-z0-9 ]/g, ' ')
  .split(/\s+/).filter(w => w && !['reaction', 'the', 'rxn'].includes(w)).join(' ');

init().then(R => {
  const errors = [];
  const err = (where, msg) => errors.push(`${where}: ${msg}`);

  const dates = data.sets.map(s => s.date);
  if ([...dates].sort().join() !== dates.join()) err('sets', 'dates are not in ascending order');
  if (new Set(dates).size !== dates.length) err('sets', 'duplicate date');
  const ids = new Map(), steps = new Map(), lastSeen = new Map();

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
      const sk = chemKey(R, P.substrate.smiles, fp), pk = chemKey(R, P.product.smiles, fp);
      if (!sk) err(w, 'substrate SMILES unreadable');
      if (!pk) err(w, 'product SMILES unreadable');
      if (sk && sk === pk) err(w, 'product has the same key as the substrate');
      for (const st of P.steps) for (const r of st.reagents)
        if (r.smiles) { const m = R.get_mol(r.smiles); if (!m || !m.is_valid()) err(w, `reagent ${r.text}: SMILES unreadable`); if (m) m.delete(); }
      const seen = new Map([[sk, 'substrate'], [pk, 'product']]);
      let distinct = 0;
      for (const st of P.steps) for (const [k, it] of st.intermediates.entries()) {
        const keys = it.forms.map(f => chemKey(R, f, fp));
        if (!it.forms.length || keys.some(x => !x)) err(w, `step ${st.n} intermediate ${k + 1}: unreadable or missing form`);
        const uniq = [...new Set(keys.filter(Boolean))];
        const clash = uniq.filter(x => seen.has(x)).map(x => seen.get(x));
        if (clash.length) err(w, `step ${st.n} intermediate ${k + 1} has the same key as ${clash.join(', ')} (tautomer / protonation state / resonance form); merge or remove it`);
        else distinct++;
        uniq.forEach(x => seen.has(x) || seen.set(x, `step ${st.n} intermediate ${k + 1}`));
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
