# Name Reaction Daily: how a daily question is added

This repository (branch `main`) is the source of truth; GitHub Actions deploys it to https://qdher.github.io/Daily-name-reaction-puzzle/ on every push to `main`. It contains the page and everything needed to extend it:

| Path | Content |
|---|---|
| `index.html` | the page (built; questions and key function embedded) |
| `data/problems.json` | schedule and all daily questions |
| `src/index.src.html` | page template |
| `src/chemkey.js` | structure comparison (stereo, E/Z, protonation, counterions ignored; tautomers only when protons move to or from N, O or S); same as One-Pot Puzzles |
| `src/curate.py` | atom hints (up to 5) and difficulty score (steps, intermediates, bond changes) |
| `src/validate_problems.js` | checks before publishing |
| `src/build.js` | builds `index.html` |
| `src/test_chemkey.js` | unit tests of the key |
| `rdkit/RDKit_minimal.wasm` | RDKit runtime (never changes in a daily run) |
| `ketcher/` | Ketcher structure editor (standalone build, loaded by the page in an iframe; rebuilt only as described in `ketcher-build/README.md`) |

## 1. Set up

```bash
cd <repository clone>              # run everything from the repository root
npm init -y >/dev/null && npm install @rdkit/rdkit@2026.9.1
pip download --no-deps rdkit==2026.9.1 -d whl        # a plain `pip install rdkit` can stall
pip install --break-system-packages --no-deps whl/rdkit-*.whl
node src/test_chemkey.js            # every case must pass (last line: N/N as expected)
```

## 2. Which date

One question per day, shown from 10:00 America/New_York (`schedule`). Add one set for the earliest date, from tomorrow on, that has no set. If tomorrow and the day after already have sets, add nothing.

## 3. Choosing the reaction and its example

- A named reaction that has a page in at least one of these repositories, each page linked in `repositories`:
  - TCI name reactions: `https://www.tcichemicals.com/CA/en/product/name_reaction/index` (pages `https://www.tcichemicals.com/product/name_reaction/<Name>`). The scheme image has a general reaction, a general mechanism and example reactions numbered 1), 2) that correspond to the cited references (with DOIs).
  - Organic Chemistry Portal: `https://www.organic-chemistry.org/namedreactions/` (pages `<name>.shtm`; mechanism text and "Recent Literature" entries, each with an abstract page).
  - Named Reactions Explorer: `https://say-my-name.net/reactions/<A-Z>/` lists reactions; pages are `https://say-my-name.net/reaction/<slug>/` (scheme and mechanism are SVG images).
  Link every repository that has a page for the reaction; open each link before adding it.
- The example is taken directly from a repository page:
  - TCI: an example reaction drawn on the page (examples 1), 2) = references 1), 2)). `source.doi` = that reference.
  - Organic Chemistry Portal: one "Recent Literature" entry. `source.doi` = that reference.
  - Named Reactions Explorer: the general equation of the page (`static/images/equations/<Name>.svg`), with each R / R′ / EDG replaced by the simplest group the equation allows (H where allowed, otherwise Me; Ph on aryl positions; OMe for an EDG); state the substitution in `source.context`. No DOI: set `source.url` to the reaction page. The intermediates follow the page's mechanism image (`static/images/mechanisms/<Name>.svg`).
  `source.repository` names the repository. Images: download with `curl -sSL` (works only if the domain is in the allowed network domains), render SVG with `python3 -c "import cairosvg; cairosvg.svg2png(url='x.svg', write_to='x.png', scale=3, background_color='white')"` (`pip install --break-system-packages cairosvg`) and view the PNG. If the images cannot be obtained, get the structures from the reference (abstract, full text, SI); a Named Reactions Explorer equation that cannot be viewed cannot be used. `verificationNote` says what was viewed.
- The mechanism follows the repository page(s) and the established mechanism of the named reaction (give references).
- At least 2 distinct intermediates after the key is applied.
- The product can be deduced from substrate + reagents.
- A reaction may come back after 14 sets (validator; the scheduled prompt still says 90) with another example; the same example (DOI or page, plus `source.entry`) and the same substrate and product never come back. Vary the reaction class (rearrangement, olefination, heterocycle synthesis, oxidation, reduction, C–C bond formation, etc.) over the week.
- There are no levels on this page: no `level` or `textbookLevel` fields.

## 4. Writing an entry

Copy the shape of an existing entry in `data/problems.json`. Fields beyond One-Pot Puzzles:

```json
"reaction": "Vilsmeier–Haack reaction",                    // display name
"names": ["Vilsmeier–Haack reaction", "Vilsmeier reaction", ...],   // accepted answers; must include "reaction"
"repositories": [ { "site": "Named Reactions Explorer", "url": "https://say-my-name.net/reaction/.../" },
                  { "site": "Organic Chemistry Portal", "url": "https://www.organic-chemistry.org/namedreactions/....shtm" },
                  { "site": "TCI name reactions", "url": "https://www.tcichemicals.com/product/name_reaction/..." } ],
"source": { "repository": "TCI name reactions", "citation": "...", "doi": "10.xxxx/...", "context": "where the example is on the page; conditions and yield" }
// Named Reactions Explorer equation: { "repository": "Named Reactions Explorer", "citation": "Named Reactions Explorer, <Reaction> (general equation, R = Me, R′ = H)", "url": "https://say-my-name.net/reaction/<slug>/", "context": "..." }
// Open-access article (not used by the scheduled prompt yet): { "repository": "Open-access article", "citation": "authors, title, journal, year", "doi": "10.xxxx/...", "pmcid": "PMC...", "entry": "compound or entry number", "license": "cc by", "licenseUrl": "https://creativecommons.org/licenses/by/4.0/" (optional, as given by the article), "context": "where the example is; conditions and yield; structures redrawn" }
// "repositories" then lists reaction pages (Wikipedia, Named Reactions Explorer, ...); source.repository need not be one of them.
```

`names` lists the usual names and variants (with and without "reaction", "synthesis", "rearrangement", "olefination", common alternative names). Matching on the page ignores case, accents, hyphens and the word "reaction", and tolerates 1 typo (2 for names of 14+ characters); do not add names of other reactions.

Structure rules are those of One-Pot Puzzles: no stereochemistry needed; intermediates in mechanism order, derived from the substrate; charges as charged atoms, radicals as `[C]`; `forms` lists every reasonable drawing (resonance forms, tautomers the key does not merge; the key merges only tautomers in which protons move to or from N, O or S); reagents whose atoms enter get a SMILES. `hints` and `difficulty` are written by `curate.py`. New entries have `"verified": false`.

## 5. Check, build, publish

```bash
python3 src/curate.py data/problems.json --write     # read the printed bond changes
node src/validate_problems.js data/problems.json     # must end with ALL OK
node src/build.js                                    # writes index.html
```

Commit and push: `git add index.html data && git commit -m "Add daily question <date>" && git push origin main` (only `index.html` and `data/` change in a daily run). GitHub Pages deploys the pushed commit.

## Reaction catalogue (not part of a daily run yet)

`data/catalog/index.json` lists the named reactions of Wikidata (instances of "eponymous chemical reaction", Q1049494; CC0), one line per reaction: `id` (Wikidata item), `name`, `aliases`, `wikidata` and `wikipedia` links, `wikidataClasses`, `usedOn`, `lastUsed`, `status` (`pending`, `complete`, `no-example`, `skip`), `nExamples` and `nUnused`. A selection step reads only this file. `data/catalog/<id>.json` exists only for a reaction that has been checked: `repositories` (reaction pages), `class`, `template` (general mechanism), `examples` (open-access articles: `doi`, `pmcid`, `license`, `entry`, `conditions`, `substrate`, `product`, `status` = `unused` / `used` / `rejected`, `problemId` once used, `note`; at most 10 unused) and `note`. Only pointers are stored (no article text, supplementary files or images). One shard per reaction keeps each daily commit to one small file.

`src/catalog_load.py` creates and refreshes the Wikidata fields of the index with one SPARQL query and keeps `status`, the shards and any added field; `--offline` recomputes `usedOn`, `lastUsed` and the counts from the shards without network; `--check` validates the layout (licences in the allowed list, statuses, counts, `problemId` present in `data/problems.json` or the archive). Allowed licences (as Europe PMC reports them): cc0, cc by, cc by-sa, cc by-nc, cc by-nc-sa (same list in `src/validate_problems.js`).

`usedOn` compares the normalized name and aliases with the reaction names of `data/problems.json` and the archive: `exact` = same name, `core` = same name once words such as "synthesis" or "rearrangement" are removed (can be a different reaction, e.g. Claisen condensation and Claisen rearrangement). It is a hint; the validator still applies the cooldown. Items without an English label are not loaded. Wikipedia is used for titles and links only; no Wikipedia text is copied.

`usedOn` compares the normalized name and aliases with the reaction names of `data/problems.json` and the archive: `exact` = same name, `core` = same name once words such as "synthesis" or "rearrangement" are removed (can be a different reaction, e.g. Claisen condensation and Claisen rearrangement). It is a hint; the 90-set rule of `validate_problems.js` still applies. Items without an English label are not loaded. Wikipedia is used for titles and links only; no Wikipedia text is copied.

## Archive and date list

`src/build.js` first calls `src/archive.js`: sets dated more than 32 days before today (schedule time zone) are moved from `data/problems.json` into `data/archive.json.gz` (gzip of `{"sets": [...]}`), then the page is built from what remains. The page lists the last 31 days that have a set in a drop-down, with the visitor's progress for each day (stored in the browser). Archived sets are not shown on the page; `validate_problems.js` still reads them for ids, paper + reaction pairs and repeated reactions. Read the archive with `zcat data/archive.json.gz`. Results and ratings of archived problems stay in Supabase.
