#!/usr/bin/env python3
"""Reaction catalogue: loader and checker.

Layout (data/catalog/):
  index.json     one line per reaction: id (Wikidata item), name, aliases, wikidata and wikipedia links,
                 wikidataClasses, usedOn, lastUsed, status, nExamples, nUnused. The selection step reads only this file.
  <id>.json      one file per checked reaction (written by the per-reaction check, never by the loader):
                 repositories, class, template (general mechanism), examples (open-access articles with
                 doi, pmcid, license, entry, conditions, substrate, product, status, problemId), note.
Wikidata data are CC0; Wikipedia is used for page titles and links only (no Wikipedia text is copied).

What the loader writes on every run (from Wikidata, with one SPARQL query): id, name, aliases, wikidata,
wikipedia, wikidataClasses. Computed locally: usedOn (reactions of data/problems.json and data/archive.json.gz that
match by name: match "exact" = same normalized name or alias, "core" = same name once words such as "synthesis" or
"rearrangement" are removed, so it can be a different reaction, e.g. Claisen condensation and Claisen rearrangement),
lastUsed (latest date in usedOn), nExamples and nUnused (from the shard of the reaction). Never overwritten: status
("pending" | "complete" | "no-example" | "skip") and any other field added later. Items that disappear from
Wikidata are kept with "wikidataMissing": true. Items without an English label are not loaded.

Usage (repository root; standard library only):
  python3 src/catalog_load.py                       query Wikidata and merge into data/catalog/index.json
  python3 src/catalog_load.py --offline             no network: recompute usedOn, lastUsed and the counts (after a shard changed)
  python3 src/catalog_load.py --from-file r.json    use a saved SPARQL JSON result instead of the network
  python3 src/catalog_load.py --check               validate index and shards (exit code 1 if anything is wrong)
  python3 src/catalog_load.py --self-test
The first run migrates the earlier single file data/reaction_catalog.json (status kept; completion moves to a shard).
Wikimedia asks for a descriptive User-Agent; set CATALOG_USER_AGENT to override the default.
"""
import argparse
import gzip
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_DIR = os.path.join(ROOT, "data", "catalog")
LEGACY_FILE = os.path.join(ROOT, "data", "reaction_catalog.json")
CLASS_QID = "Q1049494"  # eponymous chemical reaction
ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = os.environ.get("CATALOG_USER_AGENT", "reaction-catalog-loader/0.1 (educational project)")
SEP = "||"
KEY_ORDER = ["id", "name", "aliases", "wikidata", "wikipedia", "wikidataClasses", "usedOn", "lastUsed",
             "status", "nExamples", "nUnused"]
STATUSES = ["pending", "complete", "no-example", "skip"]
EXAMPLE_STATUSES = ["unused", "used", "rejected"]
# licences as Europe PMC reports them (lower case); same list as ALLOWED_LICENSES in src/validate_problems.js
ALLOWED_LICENSES = ["cc0", "cc by", "cc by-sa", "cc by-nc", "cc by-nc-sa"]
MAX_UNUSED = 10  # unused examples kept per reaction; more can be found again with the DOI-based search
# class of a reaction (field "class" of the shard; also used by src/pick.py to avoid the class of the previous set)
CLASSES = ["rearrangement", "olefination", "heterocycle synthesis", "oxidation", "reduction", "C-C bond formation",
           "cycloaddition", "multicomponent", "substitution", "elimination", "addition", "condensation",
           "functional group interconversion", "coupling", "other"]
EXAMPLE_FIELDS = ["doi", "license", "citation", "substrate", "product", "status"]
# licence pages (same mapping as LICENSE_PATH in src/validate_problems.js)
LICENSE_PATH = {"cc0": "/publicdomain/zero/", "cc by": "/licenses/by/", "cc by-sa": "/licenses/by-sa/",
                "cc by-nc": "/licenses/by-nc/", "cc by-nc-sa": "/licenses/by-nc-sa/"}

QUERY = """
SELECT ?item
  (SAMPLE(?label) AS ?name)
  (SAMPLE(?title) AS ?enwikiTitle)
  (GROUP_CONCAT(DISTINCT ?alias; separator="%(sep)s") AS ?aliases)
  (GROUP_CONCAT(DISTINCT ?clsLabel; separator="%(sep)s") AS ?classes)
WHERE {
  ?item wdt:P31 wd:%(cls)s .
  ?item rdfs:label ?label . FILTER(LANG(?label) = "en")
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?title . }
  OPTIONAL { ?item skos:altLabel ?alias . FILTER(LANG(?alias) = "en") }
  OPTIONAL { ?item wdt:P31 ?cls . FILTER(?cls != wd:%(cls)s) ?cls rdfs:label ?clsLabel . FILTER(LANG(?clsLabel) = "en") }
}
GROUP BY ?item
""" % {"sep": SEP, "cls": CLASS_QID}


# ---------- names (same normalization as src/validate_problems.js) ----------
STOP = {"reaction", "the", "rxn"}
GENERIC = {"synthesis", "rearrangement", "olefination", "reaction", "formylation", "degradation", "cyclization",
           "annulation", "reduction", "oxidation", "condensation", "coupling", "alkyne", "pyrrole", "indole"}


def norm(s):
    s = unicodedata.normalize("NFD", str(s))
    s = re.sub(r"[̀-ͯ]", "", s).lower()
    s = re.sub(r"[‐-―−\-]", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(w for w in s.split() if w not in STOP)


def core(s):
    return " ".join(w for w in norm(s).split() if w not in GENERIC)


# ---------- Wikidata ----------
def wiki_url(title):
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="_(),!*'~:@$&;=-.")


def run_sparql(query, tries=5):
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504) or i == tries - 1:
                raise
            try:
                wait = int(e.headers.get("Retry-After", "10"))
            except ValueError:
                wait = 10
            wait = min(wait, 120) + 5 * (i + 1)
            print(f"HTTP {e.code}; waiting {wait} s before retry {i + 2}/{tries}", file=sys.stderr)
            time.sleep(wait)


def parse_result(result):
    out = {}
    for b in result["results"]["bindings"]:
        g = lambda k: b.get(k, {}).get("value", "")
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        name = g("name").strip()
        if not name or re.fullmatch(r"Q\d+", name):
            continue
        parts = lambda s: sorted({x.strip() for x in s.split(SEP) if x.strip()}, key=lambda x: (x.casefold(), x))
        title = g("enwikiTitle").strip()
        out[qid] = {"name": name, "wikipedia": wiki_url(title) if title else None,
                    "aliases": [a for a in parts(g("aliases")) if a != name], "wikidataClasses": parts(g("classes"))}
    return out


# ---------- used reactions ----------
def read_sets(problems_path, archive_path):
    sets = []
    if os.path.exists(problems_path):
        with open(problems_path, encoding="utf-8") as f:
            sets += json.load(f).get("sets", [])
    if archive_path and os.path.exists(archive_path):
        with gzip.open(archive_path, "rt", encoding="utf-8") as f:
            sets += json.load(f).get("sets", [])
    return sets


def used_index(sets):
    idx = []
    for s in sets:
        for p in s.get("problems", []):
            names = [p.get("reaction", "")] + list(p.get("names", []))
            idx.append({"date": s.get("date"), "reaction": p.get("reaction"),
                        "exact": {norm(n) for n in names if norm(n)},
                        "core": {core(n) for n in names if core(n)}})
    return idx


def used_on(idx, name, aliases):
    keys = {norm(x) for x in [name] + aliases if norm(x)}
    cores = {core(x) for x in [name] + aliases if core(x)}
    out = []
    for u in idx:
        if keys & u["exact"]:
            out.append({"date": u["date"], "reaction": u["reaction"], "match": "exact"})
        elif cores & u["core"]:
            out.append({"date": u["date"], "reaction": u["reaction"], "match": "core"})
    return sorted(out, key=lambda x: x["date"] or "")


# ---------- files ----------
def read_index(directory):
    path = os.path.join(directory, "index.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("entries", [])


def read_shards(directory):
    out = {}
    if os.path.isdir(directory):
        for fn in sorted(os.listdir(directory)):
            if fn.endswith(".json") and fn != "index.json":
                with open(os.path.join(directory, fn), encoding="utf-8") as f:
                    out[fn[:-5]] = json.load(f)
    return out


def shard_counts(shard):
    ex = shard.get("examples", []) if shard else []
    return len(ex), sum(1 for e in ex if e.get("status") == "unused")


def from_legacy(path):
    """Entries and shards of the earlier single file (data/reaction_catalog.json)."""
    with open(path, encoding="utf-8") as f:
        entries = json.load(f).get("entries", [])
    shards = {}
    for e in entries:
        comp = e.pop("completion", None)
        if comp:
            shards[e["id"]] = {"id": e["id"], "name": e["name"], **comp}
    return entries, shards


def write_index(directory, entries, today):
    os.makedirs(directory, exist_ok=True)
    meta = {
        "description": "Named reactions from Wikidata with their check status; one entry per Wikidata item; "
                       "checked reactions have a file <id>.json in this folder",
        "source": f"Wikidata items with instance of eponymous chemical reaction ({CLASS_QID}), CC0 1.0; Wikipedia: titles and links only",
        "retrieved": today,
        "count": len(entries),
        "statuses": STATUSES,
    }
    lines = ['{', ' "meta": ' + json.dumps(meta, ensure_ascii=False) + ',', ' "entries": [']
    lines += [("  " + json.dumps(e, ensure_ascii=False) + ("," if i < len(entries) - 1 else "")) for i, e in enumerate(entries)]
    lines += [' ]', '}']
    path = os.path.join(directory, "index.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(path + ".tmp", path)


def write_shard(directory, shard):
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, shard["id"] + ".json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(shard, ensure_ascii=False, indent=1) + "\n")


def read_meta(directory):
    with open(os.path.join(directory, "index.json"), encoding="utf-8") as f:
        return json.load(f).get("meta", {})


# ---------- merge ----------
def merge(old_entries, loaded, idx, shards):
    old = {e["id"]: e for e in old_entries}
    merged, added, changed = {}, 0, 0
    for qid, d in loaded.items():
        used = used_on(idx, d["name"], d["aliases"])
        n, unused = shard_counts(shards.get(qid))
        mech = {"id": qid, "name": d["name"], "aliases": d["aliases"], "wikidata": "https://www.wikidata.org/wiki/" + qid,
                "wikipedia": d["wikipedia"], "wikidataClasses": d["wikidataClasses"], "usedOn": used,
                "lastUsed": max((u["date"] for u in used if u["date"]), default=None),
                "nExamples": n, "nUnused": unused}
        base = old.get(qid)
        entry = dict(base) if base else {}
        entry.update(mech)
        entry.pop("wikidataMissing", None)
        entry.setdefault("status", "pending")
        if not base:
            added += 1
        elif {k: base.get(k) for k in mech} != mech or "wikidataMissing" in base:
            changed += 1
        merged[qid] = entry
    missing = 0
    for qid, base in old.items():
        if qid not in merged:
            entry = dict(base)
            entry["wikidataMissing"] = True
            entry["nExamples"], entry["nUnused"] = shard_counts(shards.get(qid))
            merged[qid] = entry
            missing += 1
    ordered = []
    for e in sorted(merged.values(), key=lambda e: (e["name"].casefold(), e["id"])):
        ordered.append({**{k: e[k] for k in KEY_ORDER if k in e}, **{k: v for k, v in e.items() if k not in KEY_ORDER}})
    return ordered, added, changed, missing


# ---------- offline refresh and edits of status and examples ----------
def refresh_offline(directory, problems_path, archive_path):
    """Recompute usedOn, lastUsed and the example counts from the problems and the shards (no network)."""
    old = read_index(directory)
    loaded = {e["id"]: {"name": e["name"], "aliases": e.get("aliases", []), "wikipedia": e.get("wikipedia"),
                        "wikidataClasses": e.get("wikidataClasses", [])} for e in old if not e.get("wikidataMissing")}
    idx = used_index(read_sets(problems_path, archive_path))
    entries, added, changed, missing = merge(old, loaded, idx, read_shards(directory))
    write_index(directory, entries, read_meta(directory).get("retrieved"))
    return entries


def _write_checked(directory, writer, problems_path, archive_path):
    """Applies writer(), then checks the catalogue; on errors the files are restored and the errors returned."""
    index_path = os.path.join(directory, "index.json")
    snapshot = {fn: open(os.path.join(directory, fn), "rb").read() for fn in os.listdir(directory) if fn.endswith(".json")}
    writer()
    errors = check(directory, problems_path, archive_path)
    if errors:
        for fn in os.listdir(directory):
            if fn.endswith(".json") and fn not in snapshot:
                os.remove(os.path.join(directory, fn))
        for fn, data in snapshot.items():
            with open(os.path.join(directory, fn), "wb") as f:
                f.write(data)
    return errors


def mark(directory, qid, status, today, problems_path=None, archive_path=None):
    """Sets the status of a reaction and the date of the attempt; refused (files restored) if the check fails."""
    if status not in STATUSES:
        return [f"status {status!r} not in {STATUSES}"]
    if qid not in {e["id"] for e in read_index(directory)}:
        return [f"{qid} is not in the index"]
    def writer():
        entries = read_index(directory)
        for e in entries:
            if e["id"] == qid:
                e["status"] = status
                e["lastAttempt"] = today
        write_index(directory, entries, read_meta(directory).get("retrieved"))
    return _write_checked(directory, writer, problems_path, archive_path)


def set_example(directory, qid, n, status, problem_id, note, problems_path=None, archive_path=None):
    """Sets the status of example n (1-based) of a reaction (used / rejected / unused) and recomputes the counts."""
    shard = read_shards(directory).get(qid)
    if not shard or not (1 <= n <= len(shard.get("examples", []))):
        return [f"{qid}: no example {n}"]
    if status not in EXAMPLE_STATUSES:
        return [f"example status {status!r} not in {EXAMPLE_STATUSES}"]
    def writer():
        ex = shard["examples"][n - 1]
        ex["status"] = status
        if status != "used":
            ex.pop("problemId", None)
        if problem_id:
            ex["problemId"] = problem_id
        if note:
            ex["note"] = note
        write_shard(directory, shard)
        refresh_offline(directory, problems_path or os.path.join(ROOT, "data", "problems.json"),
                        archive_path or os.path.join(ROOT, "data", "archive.json.gz"))
    return _write_checked(directory, writer, problems_path, archive_path)


# ---------- check ----------
def check(directory, problems_path=None, archive_path=None):
    errors = []
    entries = read_index(directory)
    if entries is None:
        return [f"{directory}/index.json is missing"]
    with open(os.path.join(directory, "index.json"), encoding="utf-8") as f:
        meta = json.load(f).get("meta", {})
    if meta.get("count") != len(entries):
        errors.append(f"index: meta.count {meta.get('count')} differs from {len(entries)} entries")
    ids = {}
    for e in entries:
        for k in ("id", "name", "status", "nExamples", "nUnused"):
            if k not in e:
                errors.append(f"index entry {e.get('id') or e.get('name')}: missing field {k}")
        if e.get("id") in ids:
            errors.append(f"index: duplicate id {e.get('id')}")
        ids[e.get("id")] = e
        if e.get("status") not in STATUSES:
            errors.append(f"{e.get('id')}: status {e.get('status')!r} not in {STATUSES}")
    known = None
    if problems_path:
        known = {p["id"] for s in read_sets(problems_path, archive_path) for p in s.get("problems", [])}
    shards = read_shards(directory)
    for sid, sh in shards.items():
        if sid not in ids:
            errors.append(f"{sid}.json: no index entry with this id")
            continue
        if sh.get("id") != sid:
            errors.append(f"{sid}.json: id {sh.get('id')!r} differs from the file name")
        if sh.get("class") not in CLASSES:
            errors.append(f"{sid}.json: class {sh.get('class')!r} not in {CLASSES}")
        repos = sh.get("repositories")
        if not isinstance(repos, list) or not all(isinstance(r, dict) and r.get("site") and str(r.get("url", "")).startswith("https://") for r in repos):
            errors.append(f"{sid}.json: repositories must be a list of {{site, url}} with https urls")
        for k, ex in enumerate(sh.get("examples", []), 1):
            w = f"{sid}.json example {k}"
            for fld in EXAMPLE_FIELDS:
                if fld not in ex:
                    errors.append(f"{w}: missing field {fld}")
            if not re.match(r"^10\.\d{4,9}/", str(ex.get("doi", ""))):
                errors.append(f"{w}: doi missing or malformed")
            if ex.get("license") not in ALLOWED_LICENSES:
                errors.append(f"{w}: license {ex.get('license')!r} not in {ALLOWED_LICENSES}")
            if ex.get("licenseUrl") is not None and not str(ex["licenseUrl"]).startswith("https://creativecommons.org" + LICENSE_PATH.get(ex.get("license"), "/?")):
                errors.append(f"{w}: licenseUrl {ex.get('licenseUrl')!r} is not the creativecommons.org page of the licence")
            if ex.get("status") not in EXAMPLE_STATUSES:
                errors.append(f"{w}: status {ex.get('status')!r} not in {EXAMPLE_STATUSES}")
            if ex.get("status") == "unused":
                for side in ("substrate", "product"):
                    if not (isinstance(ex.get(side), dict) and ex[side].get("smiles")):
                        errors.append(f"{w}: {side}.smiles missing")
                if not isinstance(ex.get("reagents", []), list):
                    errors.append(f"{w}: reagents must be a list")
            if ex.get("status") == "used":
                if not ex.get("problemId"):
                    errors.append(f"{w}: used without problemId")
                elif known is not None and ex["problemId"] not in known:
                    errors.append(f"{w}: problemId {ex['problemId']} is not in data/problems.json or the archive")
        if shard_counts(sh)[1] > MAX_UNUSED:
            errors.append(f"{sid}.json: more than {MAX_UNUSED} unused examples")
    for qid, e in ids.items():
        n, unused = shard_counts(shards.get(qid))
        if (e.get("nExamples"), e.get("nUnused")) != (n, unused):
            errors.append(f"{qid}: index counts {e.get('nExamples')}/{e.get('nUnused')} differ from the shard {n}/{unused}; run --offline")
        if e.get("status") == "complete" and n < 1:
            errors.append(f"{qid}: status complete without examples")
        if e.get("status") == "complete" and not (shards.get(qid) or {}).get("repositories"):
            errors.append(f"{qid}: status complete without reaction pages (repositories)")
        if e.get("status") == "no-example" and n > 0:
            errors.append(f"{qid}: status no-example but the shard has examples")
    return errors


# ---------- self-test ----------
def self_test():
    assert norm("Hell–Volhard–Zelinsky reaction") == "hell volhard zelinsky"
    assert norm("Schöllkopf  Reaction") == "schollkopf"
    assert core("Paal–Knorr pyrrole synthesis") == core("Paal-Knorr synthesis") == "paal knorr"
    res = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q1"}, "name": {"value": "Claisen condensation"},
         "enwikiTitle": {"value": "Claisen condensation"}, "aliases": {"value": "Claisen reaction||Claisen"},
         "classes": {"value": "condensation reaction"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q2"}, "name": {"value": "Claisen rearrangement"},
         "aliases": {"value": ""}, "classes": {"value": ""}},
        {"item": {"value": "http://www.wikidata.org/entity/Q3"}, "name": {"value": "Q3"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q4"}, "name": {"value": "Wolff-Kishner reduction"},
         "enwikiTitle": {"value": "Wolff–Kishner reduction"}, "aliases": {"value": ""}, "classes": {"value": ""}},
    ]}}
    loaded = parse_result(res)
    assert set(loaded) == {"Q1", "Q2", "Q4"}, loaded            # Q3 has no English label
    assert loaded["Q1"]["aliases"] == ["Claisen", "Claisen reaction"]
    assert loaded["Q4"]["wikipedia"].endswith("Wolff%E2%80%93Kishner_reduction")
    sets = [{"date": "2026-01-01", "problems": [{"id": "p-claisen", "reaction": "Claisen condensation", "names": ["Claisen condensation", "Claisen reaction"]}]}]
    idx = used_index(sets)
    def ex(doi, lic, status, **kw):
        return {"doi": doi, "license": lic, "status": status, "citation": "A. Author. Title. J. 2020, 1, 1.",
                "substrate": {"label": "s", "smiles": "CC(=O)C"}, "reagents": [], "conditions": "", "product": {"label": "p", "smiles": "CC(O)C"}, **kw}
    shard2 = {"id": "Q2", "class": "rearrangement", "repositories": [{"site": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Claisen_rearrangement"}],
              "examples": [ex("10.1000/a", "cc by", "unused"), ex("10.1000/b", "cc0", "used", problemId="p-claisen")]}
    old = [{"id": "Q2", "name": "Claisen rearrangement", "status": "complete", "extra": 1},
           {"id": "Q9", "name": "Gone reaction", "status": "skip"}]
    entries, added, changed, missing = merge(old, loaded, idx, {"Q2": shard2})
    by = {e["id"]: e for e in entries}
    assert (added, missing) == (2, 1), (added, missing)
    assert by["Q1"]["usedOn"][0]["match"] == "exact" and by["Q1"]["status"] == "pending" and by["Q1"]["lastUsed"] == "2026-01-01"
    assert by["Q2"]["usedOn"][0]["match"] == "core"                # possible, not certain
    assert by["Q2"]["status"] == "complete" and by["Q2"]["extra"] == 1 and (by["Q2"]["nExamples"], by["Q2"]["nUnused"]) == (2, 1)
    assert by["Q4"]["usedOn"] == [] and by["Q4"]["lastUsed"] is None
    assert by["Q9"]["wikidataMissing"] is True and by["Q9"]["status"] == "skip"
    entries2, added2, changed2, _ = merge(entries, loaded, idx, {"Q2": shard2})
    assert entries2 == entries and (added2, changed2) == (0, 0)     # second run changes nothing

    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, "catalog")
        prob = os.path.join(tmp, "problems.json")
        with open(prob, "w", encoding="utf-8") as f:
            json.dump({"sets": sets}, f)
        # migration of the earlier single file: status kept, completion moves to a shard
        legacy = os.path.join(tmp, "legacy.json")
        with open(legacy, "w", encoding="utf-8") as f:
            json.dump({"entries": [dict(e, completion=None) for e in by.values() if e["id"] != "Q2"] +
                       [dict(by["Q2"], completion={**{k: v for k, v in shard2.items() if k != "id"}, "note": "kept"})]}, f)
        old_entries, shards = from_legacy(legacy)
        assert set(shards) == {"Q2"} and shards["Q2"]["note"] == "kept" and "completion" not in old_entries[0]
        entries3, *_ = merge(old_entries, loaded, idx, shards)
        write_index(d, entries3, "2026-01-02")
        write_shard(d, shards["Q2"])
        assert read_index(d) == entries3 and read_shards(d)["Q2"]["note"] == "kept"
        assert check(d, prob) == [], check(d, prob)
        # status and example edits: allowed changes are written, refused ones restore the files
        before = open(os.path.join(d, "index.json"), "rb").read()
        assert mark(d, "Q2", "complete", "2026-01-03", prob) == []
        assert next(e for e in read_index(d) if e["id"] == "Q2")["lastAttempt"] == "2026-01-03"
        errs = mark(d, "Q1", "complete", "2026-01-03", prob)            # Q1 has no shard: refused
        assert errs and next(e for e in read_index(d) if e["id"] == "Q1")["status"] == "pending", errs
        assert mark(d, "Q1", "no-example", "2026-01-03", prob) == []
        assert set_example(d, "Q2", 1, "used", "p-claisen", "n", prob) == []
        assert next(e for e in read_index(d) if e["id"] == "Q2")["nUnused"] == 0
        assert set_example(d, "Q2", 1, "unused", None, None, prob) == []      # back to unused: problemId cleared
        assert "problemId" not in read_shards(d)["Q2"]["examples"][0]
        assert set_example(d, "Q2", 1, "used", None, None, prob)               # used without problemId: refused, restored
        assert read_shards(d)["Q2"]["examples"][0]["status"] == "unused"
        assert set_example(d, "Q2", 1, "used", "p-claisen", None, prob) == []
        assert set_example(d, "Q2", 5, "used", "x", None, prob) == ["Q2: no example 5"]
        assert mark(d, "Q2", "bogus", "2026-01-03", prob)
        # check finds mistakes
        bad = dict(shards["Q2"])
        bad["examples"] = [ex("10.1000/a", "cc by-nd", "unused"),
                           ex("nodoi", "cc by", "used", problemId="unknown-id"),
                           ex("10.1000/c", "cc by", "unused", licenseUrl="https://creativecommons.org/licenses/by-nc/4.0/"),
                           dict(ex("10.1000/d", "cc by", "unused"), substrate={"label": "s"})]   # 4 examples, 3 unused: index says 2/1
        bad["class"] = "bogus"
        write_shard(d, bad)
        write_shard(d, {"id": "Q77", "examples": []})
        msgs = " | ".join(check(d, prob))
        for part in ("license 'cc by-nd'", "doi missing or malformed", "problemId unknown-id", "Q77.json: no index entry", "index counts",
                     "class 'bogus'", "creativecommons.org page of the licence", "substrate.smiles missing"):
            assert part in msgs, (part, msgs)
    print("self-test OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=CATALOG_DIR)
    ap.add_argument("--problems", default=os.path.join(ROOT, "data", "problems.json"))
    ap.add_argument("--archive", default=os.path.join(ROOT, "data", "archive.json.gz"))
    ap.add_argument("--from-file", help="saved SPARQL JSON result instead of querying Wikidata")
    ap.add_argument("--offline", action="store_true", help="no network: recompute usedOn, lastUsed and the example counts")
    ap.add_argument("--check", action="store_true", help="validate index and shards")
    ap.add_argument("--mark", nargs=2, metavar=("ID", "STATUS"), help="set the status of a reaction (and lastAttempt = today)")
    ap.add_argument("--example", nargs=3, metavar=("ID", "N", "STATUS"), help="set the status of example N (1-based): used, rejected or unused")
    ap.add_argument("--problem-id", help="with --example ... used: id of the problem that uses the example")
    ap.add_argument("--note", help="with --example: short note (for example why it was rejected)")
    ap.add_argument("--force", action="store_true", help="write even if the result has far fewer items than the catalogue")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.check:
        errors = check(a.dir, a.problems, a.archive)
        if errors:
            print("FAILED\n- " + "\n- ".join(errors))
            sys.exit(1)
        n = len(read_index(a.dir) or [])
        print(f"catalogue OK: {n} entries, {len(read_shards(a.dir))} shard file(s)")
        return
    if a.mark or a.example:
        if a.mark:
            errors = mark(a.dir, a.mark[0], a.mark[1], datetime.now(timezone.utc).strftime("%Y-%m-%d"), a.problems, a.archive)
        else:
            errors = set_example(a.dir, a.example[0], int(a.example[1]), a.example[2], a.problem_id, a.note, a.problems, a.archive)
        if errors:
            print("REFUSED (files restored)\n- " + "\n- ".join(errors))
            sys.exit(1)
        print("done")
        return
    old = read_index(a.dir)
    legacy_shards = {}
    if old is None and os.path.exists(LEGACY_FILE):
        old, legacy_shards = from_legacy(LEGACY_FILE)
        print(f"migrating {os.path.relpath(LEGACY_FILE, ROOT)} ({len(old)} entries, {len(legacy_shards)} with completion data)")
    old = old or []
    if a.offline:
        if not old:
            sys.exit("--offline needs an existing catalogue")
        loaded = {e["id"]: {"name": e["name"], "aliases": e.get("aliases", []), "wikipedia": e.get("wikipedia"),
                            "wikidataClasses": e.get("wikidataClasses", [])} for e in old if not e.get("wikidataMissing")}
    else:
        if a.from_file:
            with open(a.from_file, encoding="utf-8") as f:
                result = json.load(f)
        else:
            result = run_sparql(QUERY)
        loaded = parse_result(result)
        live_old = [e for e in old if not e.get("wikidataMissing")]
        if live_old and len(loaded) < 0.8 * len(live_old) and not a.force:
            sys.exit(f"only {len(loaded)} items returned (catalogue has {len(live_old)}); nothing written (use --force to override)")
        if not loaded:
            sys.exit("no items returned; nothing written")
    shards = {**read_shards(a.dir), **legacy_shards}
    idx = used_index(read_sets(a.problems, a.archive))
    entries, added, changed, missing = merge(old, loaded, idx, shards)
    write_index(a.dir, entries, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    for sid, sh in legacy_shards.items():
        write_shard(a.dir, sh)
    with_wp = sum(1 for e in entries if e.get("wikipedia"))
    used = sum(1 for e in entries if e["usedOn"])
    print(f"{len(entries)} entries ({with_wp} with an English Wikipedia article); added {added}, changed {changed}, "
          f"not in Wikidata result {missing}; {used} match a used reaction; {len(shards)} shard file(s)")


if __name__ == "__main__":
    main()
