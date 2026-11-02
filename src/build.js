// Builds index.html (the published page) from src/index.src.html, src/chemkey.js and
// data/problems.json. Layout (same as the published artifact):
//   index.html  data/problems.json  src/*  rdkit/RDKit_minimal.wasm (already published)
// Usage: node src/build.js            (run from the project root)
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..');

const tpl = fs.readFileSync(path.join(__dirname, 'index.src.html'), 'utf8');
const chemkey = fs.readFileSync(path.join(__dirname, 'chemkey.js'), 'utf8');
const problems = JSON.stringify(JSON.parse(fs.readFileSync(path.join(root, 'data', 'problems.json'), 'utf8')));
const html = tpl.replace('/*CHEMKEY*/', () => chemkey).replace('/*PROBLEMS*/', () => problems);
fs.writeFileSync(path.join(root, 'index.html'), html);
console.log('built', path.join(root, 'index.html'), (html.length / 1024).toFixed(0) + ' KB');
