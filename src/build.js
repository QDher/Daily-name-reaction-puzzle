// Builds index.html (the page served by GitHub Pages) from src/index.src.html, src/chemkey.js and
// data/problems.json. Repository layout:
//   index.html  data/problems.json  data/archive.json.gz  src/*  rdkit/RDKit_minimal.wasm  ketcher/
// Sets older than 32 days are first moved to data/archive.json.gz (src/archive.js); the page embeds the rest.
// The template is wrapped in a complete HTML document (doctype, charset, viewport), so the page renders
// in standards mode and at device width on phones.
// Usage: node src/build.js            (run from the project root; also writes data/features.json, see src/features.js)
const fs = require('fs');
const path = require('path');
const { archiveOldSets, ARCHIVE_AFTER_DAYS } = require('./archive.js');
const root = path.join(__dirname, '..');
const problemsFile = path.join(root, 'data', 'problems.json');

const HEAD = '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' +
  '<style>:root{color-scheme:light;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);' +
  'padding-bottom:env(safe-area-inset-bottom,0px)}html{scroll-padding-top:env(safe-area-inset-top,0px)}' +
  'body{margin:0;padding:0;font:14px -apple-system,BlinkMacSystemFont,sans-serif}img{max-width:100%}' +
  '[hidden]{display:none!important}</style></head><body>\n';
const TAIL = '\n</body></html>\n';

const moved = archiveOldSets(problemsFile);
if (moved) console.log(`archived ${moved} set(s) older than ${ARCHIVE_AFTER_DAYS} days into data/archive.json.gz`);
const tpl = fs.readFileSync(path.join(__dirname, 'index.src.html'), 'utf8');
const chemkey = fs.readFileSync(path.join(__dirname, 'chemkey.js'), 'utf8');
const problems = JSON.stringify(JSON.parse(fs.readFileSync(problemsFile, 'utf8')));
const html = HEAD + tpl.replace('/*CHEMKEY*/', () => chemkey).replace('/*PROBLEMS*/', () => problems) + TAIL;
fs.writeFileSync(path.join(root, 'index.html'), html);
console.log('built', path.join(root, 'index.html'), (html.length / 1024).toFixed(0) + ' KB');

// Problem features for the selection models (src/features.js, data/features.json). Needs @rdkit/rdkit; without it
// the page is still built and the features file is left as it was.
let featuresModule = null;
try { featuresModule = require('./features.js'); require.resolve('@rdkit/rdkit'); } catch (e) { featuresModule = null; }
if (featuresModule) {
  featuresModule.writeFeatures(root)
    .then(n => console.log(`features: ${n} problems -> data/features.json`))
    .catch(e => console.warn('features not written:', e.message));
} else {
  console.warn('features not written: @rdkit/rdkit is not installed');
}
