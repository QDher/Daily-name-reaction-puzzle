# Handoff: Name Reaction Daily, catalogue and open-access examples (2026-11-14)

Repository QDher/Daily-name-reaction-puzzle, branch `main` (state checked at commit `0c49a19`). Written by the interactive maintenance session that ran from 2026-11-11 to 2026-11-14. Brief and neutral; no raw transcript, visitor data or remark text.

## 1. Scope of this session

- Goal: let the same named reaction come back with a different example structure and conditions, and never show the same problem twice.
- Built: a catalogue of named reactions (Wikidata), a selection script, validator rules for examples taken from open-access articles (Europe PMC), a licence display on the page, and a draft of the scheduled-prompt steps that use them.
- Not touched: the feedback worker and results store, Tier A, the scoring rule, `ML_PLAN.md`, the sibling repositories, `src/chemkey.js`, `src/tier_a.py`, `src/curate.py`, the ketcher and rdkit folders.

## 2. Decisions

| Date | Decision |
|---|---|
| 2026-11-11 | Examples may come from open-access articles found through Europe PMC. Licence policy "all open/free licences": implemented as cc0, cc by, cc by-sa, cc by-nc, cc by-nc-sa, as Europe PMC reports them. No-derivatives licences are refused (this exclusion is the session's reading of the instruction, not stated by the user). |
| 2026-11-11 | A reaction may come back after 14 sets (was 90). The same example and the same substrate and product never come back. |
| 2026-11-11 | The user added Wikimedia domains to the allowed domains of the environment used by the scheduled task and by other sessions: en.wikipedia.org, www.wikidata.org, query.wikidata.org, commons.wikimedia.org, upload.wikimedia.org. europepmc.org was not added; www.ebi.ac.uk (the Europe PMC API) was already reachable. |
| 2026-11-11 | Hybrid catalogue: load the names once from Wikidata, then check one reaction per daily run (plan; not in the live prompt). |
| 2026-11-11 | One Claude scheduled task plus scripts, not two tasks. Basis: a 5-reaction pilot (8.1 min, USD 3.38 for the whole session, 35 requests, no refused host) against the daily run (3.3 min, USD 1.10). Proposed review criterion (two or more failures, or runs over 6.6 min, in the first 14 runs with the new step) was not confirmed. |
| 2026-11-11 | Catalogue layout: `data/catalog/index.json` plus one file per checked reaction. A simulation of 365 daily commits grew the repository by 0.3 MB per year against 1.2 to 3.0 MB for a single file. |
| 2026-11-11 | The page shows the licence from the start and the credit (citation, DOI, licence link, note on adaptation) with the answer, because article titles can name the reaction. |
| 2026-11-11 | Pull requests 3 to 6 were opened and merged at the user's request. |
| 2026-11-14 | This file was committed directly to `main` at the user's instruction. |

## 3. Current state per component

| Component | Done | Verified | Not verified |
|---|---|---|---|
| Catalogue `data/catalog/index.json` | 442 reactions (Wikidata class Q1049494, CC0; 378 with an English Wikipedia page; items without an English label not loaded). All `pending`, no shard files. Migrated from the earlier single file. | `--self-test`, `--check` | A live refresh on the new layout: the Wikidata query service answered HTTP 429 (rate limit) in every attempt |
| Loader `src/catalog_load.py` | `--offline`, `--check`, `--mark`, `--example`, `--from-file`, `--self-test` | Self-test; dry run of the command sequence on a scratch copy | Defects: see section 4 |
| Selection `src/pick.py` | `next` and `check` (deterministic) | Self-test; dry run; on real data `next` returns "procedure" (0 of 30 reactions complete) | `check` orders pending reactions alphabetically (no information on open-access supply) |
| Validator `src/validate_problems.js` | 14-set cooldown, source type "Open-access article" (licence list, optional `licenseUrl`, `pmcid`, `entry`), same substrate and product refused, `en.wikipedia.org` accepted | 16 cases in `src/test_validate.js`; the scheduled runs of 2026-11-12, 2026-11-13 and 2026-11-14 passed with it | – |
| Page `src/index.src.html`, `index.html` | Licence line from the start; credit block with the answer | Headless render with a test copy; deployed to Pages | Phone width, dark mode |
| Draft prompt `TASK_PROMPT_DRAFT.md` | Step 3d (check one reaction), step 4 with route A (catalogue) and route B (repository pages), catalogue commands in steps 6 to 8 | One no-push test run on 2026-11-13 followed it to the end: 4 reactions checked (1 complete, 3 without a usable example), one question built that passes the validator, about 7 min | Not applied; the wording defects of section 4 |
| Scheduled task | Unchanged | Prompt last updated 2026-11-11 03:43 UTC (checked 2026-11-14); still says 90 sets and repository pages only; last run 2026-11-14 01:31 UTC succeeded in 3 min 39 s | – |
| Queue buffer | Not changed | Latest set is 2026-11-14; each run adds one set the evening before it is shown | A failed run leaves the next day without a question. One run (evening of 2026-11-09) produced no commit; the cause is unknown |

## 4. Open items, blockers, items waiting for the user

Waiting for the user:
1. Approve one change that fixes the draft wording, the loader defects and the documentation duplicate (below), followed by a short re-test.
2. Apply the draft prompt to the scheduled task (`update_trigger` with identical text, `TASK_PROMPT.md`, network row, "Backed up on" line).
3. Decide a rule for the queue buffer (for example two sets in a run when the buffer is short).
4. Decide how to reach 30 complete reactions, which route A needs: a one-time batch of checks (about USD 0.7 per reaction in the pilot) or `pick.py check --n 2`.
5. Decide whether to pre-count open-access articles for all 442 reactions to order the checks.

Wording defects found in the draft test (to fix):
- Step 3d e drops an example when PubChem does not know a compound name; this removed valid examples and contradicts step 5b. Proposed: use PubChem when it has the compound, otherwise draw the SMILES from the name or scheme, check the formula against the article, and note it.
- Step 3d intro: "403, run `--mark pending`" is ambiguous. Proposed: a refused reaction page only drops that site; a refused Europe PMC search or download means `--mark pending` and go to step 4.
- Step 3d a lacks how to find each site's page (Named Reactions Explorer titles use U+2212 minus signs); step 3d c does not say whether "at most 6 articles" means titles or full texts, and the authors come from the search result; step 3d d: conditions are often in a general-procedure paragraph; step 3d h: `skip` versus `no-example` when a name covers two transformations.
- Step 4: the JSON key is `exampleNumber`; no rule when the mechanism pages disagree; `previousClass` is null after a route B set; step 5: keep the 2-space indent of `problems.json`; PubChem returns the key `SMILES` when `IsomericSMILES` is requested (also in step 5b).

Defects in this session's changes:
- `catalog_load.py --offline` sets `meta.retrieved` to today; it should keep the date of the last Wikidata retrieval. The loader also prints a traceback after the last failed retry.
- `src/PIPELINE.md` contains the `usedOn` paragraph twice; the older copy still mentions the 90-set rule.

Blockers and limits: the Wikidata query service rate limit; the TCI index returns HTTP 403 to the sandbox; some Organic Chemistry Portal pages return 403. The question built in the test run has not been reviewed by a chemist; `curate.py` mapped an incoming oxygen as a new atom, so that question has the minimum of 2 hints.

## 5. Files and commits (all on `main`)

| Pull request | Commits | Content |
|---|---|---|
| 3 | `682e51f`, merge `6d7926a` | `src/catalog_load.py`, first catalogue (single file, replaced later), docs |
| 4 | `7d10f33`, merge `0d17a75` | Layout per reaction, validator changes, `src/test_validate.js`, docs |
| 5 | `d559ec2`, merge `dea2944` | Page licence display, validator `licenseUrl`, `index.html` rebuilt |
| 6 | `23025fb`, merge `17f2fe6` | `src/pick.py`, `--mark` and `--example`, `TASK_PROMPT_DRAFT.md` |

Daily runs after these merges: `b2c4d34` (2026-11-12), `bec0c19` (2026-11-13), `0c49a19` (2026-11-14). Files changed overall: `src/catalog_load.py`, `src/pick.py`, `src/validate_problems.js`, `src/test_validate.js`, `src/index.src.html`, `index.html`, `data/catalog/index.json`, `TASK_PROMPT_DRAFT.md`, `CLAUDE.md`, `src/PIPELINE.md`. This file: `docs/handoff/name-reaction-catalogue_2026-11-14.md`.

## 6. Assumptions and interfaces other sessions must check

- The environment of the scheduled task is shared by other sessions; its allowed domains (now including Wikimedia) apply to all of them.
- `src/chemkey.js` and `src/tier_a.py` are shared with Daily-organic-chemistry-puzzles; they were not changed. The validator's same-substrate-and-product check uses `speciesInfo` and `matches` from `chemkey.js`.
- Constants kept in two places: `ALLOWED_LICENSES` (`src/validate_problems.js`, `src/catalog_load.py`); the cooldown 14 (`REPEAT_WINDOW` in the validator, `COOLDOWN` in `src/pick.py`); `MIN_COMPLETE` 30 in `src/pick.py`.
- `.github/workflows/pages.yml` copies all of `data/` to the public site, so the catalogue and its shard files are public. Store only bibliographic data and short factual conditions: no article text, supplementary files, figures or visitor data.
- The live prompt (90 sets, repository pages) and the validator (14 sets, article sources) differ; the difference is on the safe side (the validator is looser, the prompt stricter).
- Requests to Wikimedia, Europe PMC and PubChem use a descriptive User-Agent without personal or project names; Wikimedia rate limits apply.
- `CLAUDE.md` says commits go to `main`; in this session pushes went to the designated branch and pull requests were opened only on request, except this file.
- The feedback worker, site key `namerxn` and the score rule were not changed; the page change collects no new visitor data.

## 7. Next steps in priority order

1. One change: the draft wording fixes, the `--offline` retrieval-date fix and a one-line error after the last failed retry, the duplicate paragraph in `src/PIPELINE.md`. Run `--self-test` of both scripts, `node src/test_validate.js`, and re-test steps 3d and 4 once.
2. Decide the queue buffer rule (independent of the catalogue).
3. Apply the prompt to the scheduled task and `TASK_PROMPT.md` (identical text, network row, backup line).
4. Grow the catalogue to 30 complete reactions; pre-count open-access supply to order the checks; retry the live Wikidata refresh when the rate limit is lifted.
5. Chemist review of article-built questions and of hints for rearrangements.
6. After 14 runs with the new step, review the split criterion (section 2).
