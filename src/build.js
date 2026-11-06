// Builds index.html (the published page) from src/index.src.html, src/chemkey.js and
// data/problems.json. Layout (same as the published artifact):
//   index.html  data/problems.json  data/archive.json.gz  src/*  rdkit/RDKit_minimal.wasm (already published)
// Sets older than 32 days are first moved to data/archive.json.gz (src/archive.js); the page embeds the rest.
// Usage: node src/build.js            (run from the project root)
const fs = require('fs');
const path = require('path');
const { archiveOldSets, ARCHIVE_AFTER_DAYS } = require('./archive.js');
const root = path.join(__dirname, '..');
const problemsFile = path.join(root, 'data', 'problems.json');

const moved = archiveOldSets(problemsFile);
if (moved) console.log(`archived ${moved} set(s) older than ${ARCHIVE_AFTER_DAYS} days into data/archive.json.gz`);
const tpl = fs.readFileSync(path.join(__dirname, 'index.src.html'), 'utf8');
const chemkey = fs.readFileSync(path.join(__dirname, 'chemkey.js'), 'utf8');
const problems = JSON.stringify(JSON.parse(fs.readFileSync(problemsFile, 'utf8')));
const html = tpl.replace('/*CHEMKEY*/', () => chemkey).replace('/*PROBLEMS*/', () => problems);
fs.writeFileSync(path.join(root, 'index.html'), html);
console.log('built', path.join(root, 'index.html'), (html.length / 1024).toFixed(0) + ' KB');
