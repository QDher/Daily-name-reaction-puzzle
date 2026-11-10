# Ketcher build recipe

Source of the `ketcher/` folder served with the puzzle page: the standalone build of [Ketcher](https://lifescience.opensource.epam.com/ketcher/) (EPAM, Apache 2.0), which runs in the browser without a server. The page loads `ketcher/index.html` in an iframe and talks to it through `window.ketcher` (same origin).

The same recipe and the same build are used by both puzzle sites (QDher/Daily-organic-chemistry-puzzles and QDher/Daily-name-reaction-puzzle); keep the two copies identical.

## Versions

Locked in `package-lock.json`: ketcher-react, ketcher-standalone and ketcher-core 3.18.0 (Indigo 1.46.0, no-render WebAssembly build), React 18.3.1, Vite 5.4.10. Built on 2026-11-03.

## Files

| File | Role |
|---|---|
| `index.html` | page loaded in the iframe |
| `src/main.jsx` | mounts the Ketcher `Editor` with the standalone (no-render) structure service; sets `window.ketcher` and posts `ketcher-ready` to the parent |
| `src/shim.js` | ketcher-core calls `require('raphael')` when it loads; this provides it in the browser bundle |
| `vite.config.js` | relative paths (`base: './'`), browser aliases for `events` and `buffer`, ES-module workers |

## Rebuild or upgrade

```bash
cd ketcher-build
npm ci                      # exact versions from package-lock.json (use npm install <pkg>@<version> to upgrade)
npx vite build              # writes dist/ (about 17 MB; largest file 7.8 MB)
rm -rf ../ketcher && cp -r dist ../ketcher
```

Then:

1. Test the page locally: draw or load a structure, check it, and confirm there are no console errors. The page uses only `getMolfile('v2000')`, `setMolecule(smiles)`, `setMolecule('')` and `editor.struct().atoms.size`; check that an upgraded Ketcher still provides them.
2. Commit `ketcher/` (and this folder, if it changed) in both repositories. The Pages workflow copies `ketcher/` to the site; this `ketcher-build/` folder is not published. Asset file names contain content hashes, so remove the old files from `ketcher/assets/` (the `rm -rf ../ketcher` above does this).
