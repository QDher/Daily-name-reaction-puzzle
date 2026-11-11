#!/usr/bin/env python3
"""Reaction catalogue loader (step 1 of the catalogue plan).

Reads the named reactions from Wikidata with one SPARQL query and merges them into
data/reaction_catalog.json. Wikidata data are CC0; Wikipedia is used for page titles and links only
(no Wikipedia text is copied).

Fields written from Wikidata on every run (mechanical): id (Wikidata item), name, aliases, wikidata,
wikipedia, wikidataClasses, usedOn (reactions of data/problems.json and data/archive.json.gz that match
by name: match "exact" = same normalized name or alias, "core" = same name once words such as
"synthesis" or "rearrangement" are removed, so it can be a different reaction, e.g. Claisen condensation
and Claisen rearrangement).
Fields never overwritten: status ("pending" | "complete" | "no-example" | "skip"), completion (filled by
the per-reaction check: repositories, class, open-access example, note) and any other field added later.
Items that disappear from Wikidata are kept with "wikidataMissing": true.

Usage (repository root; standard library only):
  python3 src/catalog_load.py                       query Wikidata and merge
  python3 src/catalog_load.py --from-file r.json    use a saved SPARQL JSON result (no network)
  python3 src/catalog_load.py --self-test
Wikimedia asks for a descriptive User-Agent; set CATALOG_USER_AGENT to override the default.
"""
import argparse
import gzip
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASS_QID = "Q1049494"  # eponymous chemical reaction
ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = os.environ.get("CATALOG_USER_AGENT", "reaction-catalog-loader/0.1 (educational project)")
SEP = "||"
KEY_ORDER = ["id", "name", "aliases", "wikidata", "wikipedia", "wikidataClasses", "usedOn", "status", "completion"]

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
        out[qid] = {
            "name": name,
            "enwikiTitle": g("enwikiTitle").strip() or None,
            "aliases": [a for a in parts(g("aliases")) if a != name],
            "wikidataClasses": parts(g("classes")),
        }
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


# ---------- merge ----------
def wiki_url(title):
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="_(),!*'~:@$&;=-.")


def merge(old_entries, loaded, idx):
    old = {e["id"]: e for e in old_entries}
    merged, added, changed = {}, 0, 0
    for qid, d in loaded.items():
        mech = {"id": qid, "name": d["name"], "aliases": d["aliases"],
                "wikidata": "https://www.wikidata.org/wiki/" + qid,
                "wikipedia": wiki_url(d["enwikiTitle"]) if d["enwikiTitle"] else None,
                "wikidataClasses": d["wikidataClasses"], "usedOn": used_on(idx, d["name"], d["aliases"])}
        base = old.get(qid)
        entry = dict(base) if base else {}
        entry.update(mech)
        entry.pop("wikidataMissing", None)
        entry.setdefault("status", "pending")
        entry.setdefault("completion", None)
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
            merged[qid] = entry
            missing += 1
    ordered = []
    for e in sorted(merged.values(), key=lambda e: (e["name"].casefold(), e["id"])):
        ordered.append({**{k: e[k] for k in KEY_ORDER if k in e}, **{k: v for k, v in e.items() if k not in KEY_ORDER}})
    return ordered, added, changed, missing


def write_catalog(path, entries, today):
    meta = {
        "description": "Named reactions from Wikidata with their check status; one entry per Wikidata item",
        "source": f"Wikidata items with instance of eponymous chemical reaction ({CLASS_QID}), CC0 1.0; Wikipedia: titles and links only",
        "retrieved": today,
        "count": len(entries),
        "statuses": ["pending", "complete", "no-example", "skip"],
    }
    lines = ['{', ' "meta": ' + json.dumps(meta, ensure_ascii=False) + ',', ' "entries": [']
    lines += [("  " + json.dumps(e, ensure_ascii=False) + ("," if i < len(entries) - 1 else "")) for i, e in enumerate(entries)]
    lines += [' ]', '}']
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


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
    sets = [{"date": "2026-01-01", "problems": [{"reaction": "Claisen condensation", "names": ["Claisen condensation", "Claisen reaction"]}]}]
    idx = used_index(sets)
    old = [{"id": "Q2", "name": "Claisen rearrangement", "status": "complete", "completion": {"note": "kept"}, "extra": 1},
           {"id": "Q9", "name": "Gone reaction", "status": "skip", "completion": None}]
    entries, added, changed, missing = merge(old, loaded, idx)
    by = {e["id"]: e for e in entries}
    assert (added, missing) == (2, 1), (added, missing)
    assert by["Q1"]["usedOn"][0]["match"] == "exact" and by["Q1"]["status"] == "pending"
    assert by["Q2"]["usedOn"][0]["match"] == "core"                # possible, not certain
    assert by["Q2"]["status"] == "complete" and by["Q2"]["completion"] == {"note": "kept"} and by["Q2"]["extra"] == 1
    assert by["Q4"]["usedOn"] == [] and by["Q4"]["wikipedia"].endswith("Wolff%E2%80%93Kishner_reduction")
    assert by["Q9"]["wikidataMissing"] is True and by["Q9"]["status"] == "skip"
    entries2, added2, changed2, missing2 = merge(entries, loaded, idx)
    assert entries2 == entries and (added2, changed2) == (0, 0)     # second run changes nothing
    print("self-test OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "reaction_catalog.json"))
    ap.add_argument("--problems", default=os.path.join(ROOT, "data", "problems.json"))
    ap.add_argument("--archive", default=os.path.join(ROOT, "data", "archive.json.gz"))
    ap.add_argument("--from-file", help="saved SPARQL JSON result instead of querying Wikidata")
    ap.add_argument("--force", action="store_true", help="write even if the result has far fewer items than the catalogue")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.from_file:
        with open(a.from_file, encoding="utf-8") as f:
            result = json.load(f)
    else:
        result = run_sparql(QUERY)
    loaded = parse_result(result)
    old = []
    if os.path.exists(a.out):
        with open(a.out, encoding="utf-8") as f:
            old = json.load(f).get("entries", [])
    live_old = [e for e in old if not e.get("wikidataMissing")]
    if live_old and len(loaded) < 0.8 * len(live_old) and not a.force:
        sys.exit(f"only {len(loaded)} items returned (catalogue has {len(live_old)}); nothing written (use --force to override)")
    if not loaded:
        sys.exit("no items returned; nothing written")
    idx = used_index(read_sets(a.problems, a.archive))
    entries, added, changed, missing = merge(old, loaded, idx)
    write_catalog(a.out, entries, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    with_wp = sum(1 for e in entries if e.get("wikipedia"))
    used = sum(1 for e in entries if e["usedOn"])
    print(f"{len(entries)} entries ({with_wp} with an English Wikipedia article); added {added}, changed {changed}, "
          f"not in Wikidata result {missing}; {used} match a used reaction")


if __name__ == "__main__":
    main()
