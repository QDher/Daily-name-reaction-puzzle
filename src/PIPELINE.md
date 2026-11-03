# Name Reaction Daily: how a daily question is added

The published artifact is the source of truth. It contains the page and everything needed to extend it:

| Path | Content |
|---|---|
| `index.html` | the page (built; questions and key function embedded) |
| `data/problems.json` | schedule and all daily questions |
| `src/index.src.html` | page template |
| `src/chemkey.js` | comparison key (stereo, E/Z, tautomers, protonation, counterions ignored); same as One-Pot Puzzles |
| `src/curate.py` | atom hints (up to 5) and difficulty score (steps, intermediates, bond changes) |
| `src/validate_problems.js` | checks before publishing |
| `src/build.js` | builds `index.html` |
| `src/test_chemkey.js` | unit tests of the key |
| `rdkit/RDKit_minimal.wasm` | RDKit runtime (already published; never needs re-uploading) |
| `ketcher/` | Ketcher structure editor (standalone build, loaded by the page in an iframe; already published; never needs re-uploading) |

## 1. Set up

```bash
mkdir -p work && cd work            # artifact files here: index.html, data/, src/
npm init -y >/dev/null && npm install @rdkit/rdkit@2026.9.1
pip download --no-deps rdkit==2026.9.1 -d whl        # a plain `pip install rdkit` can stall
pip install --break-system-packages --no-deps whl/rdkit-*.whl
node src/test_chemkey.js            # expect 22/22
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
- Not used in the previous 90 questions (validator). Vary the reaction class (rearrangement, olefination, heterocycle synthesis, oxidation, reduction, C–C bond formation, etc.) over the week.
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
```

`names` lists the usual names and variants (with and without "reaction", "synthesis", "rearrangement", "olefination", common alternative names). Matching on the page ignores case, accents, hyphens and the word "reaction", and tolerates 1 typo (2 for names of 14+ characters); do not add names of other reactions.

Structure rules are those of One-Pot Puzzles: no stereochemistry needed; intermediates in mechanism order, derived from the substrate; charges as charged atoms, radicals as `[C]`; `forms` lists every reasonable drawing (resonance forms, tautomers the key does not merge); reagents whose atoms enter get a SMILES. `hints` and `difficulty` are written by `curate.py`. New entries have `"verified": false`.

## 5. Check, build, publish

```bash
python3 src/curate.py data/problems.json --write     # read the printed bond changes
node src/validate_problems.js data/problems.json     # must end with ALL OK
node src/build.js                                    # writes index.html
```

Publish to the same artifact URL with `file_path` = `index.html`, `root` = the work folder and `files`:

```json
{
  "data/problems.json": "data/problems.json",
  "src/index.src.html": { "from": "src/index.src.html", "contentType": "text/plain" },
  "src/chemkey.js": "src/chemkey.js",
  "src/curate.py": { "from": "src/curate.py", "contentType": "text/plain" },
  "src/validate_problems.js": "src/validate_problems.js",
  "src/build.js": "src/build.js",
  "src/test_chemkey.js": "src/test_chemkey.js",
  "src/PIPELINE.md": { "from": "src/PIPELINE.md", "contentType": "text/markdown" }
}
```
