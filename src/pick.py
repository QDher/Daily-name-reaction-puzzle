#!/usr/bin/env python3
"""Selection from the reaction catalogue (data/catalog/, see src/catalog_load.py and src/PIPELINE.md).

  python3 src/pick.py next [--min-complete 30]   the reaction and the example for the next question
  python3 src/pick.py check [--n 1]              the next reaction(s) whose example is to be looked up
  python3 src/pick.py --self-test

Prints JSON on stdout. Deterministic (same files, same answer; no randomness). Standard library only.

next: among reactions with status "complete" that have an unused example and are off cooldown (a reaction may come
back after COOLDOWN sets; same value as REPEAT_WINDOW in src/validate_problems.js), the best is the one that
  1. is not of the same class as the previous set (field "class" of its shard; unknown classes are not penalised),
  2. has been used the fewest times,
  3. has been unused the longest (never used first),
  4. has the most unused examples, then by name.
Cooldown and use are counted from data/problems.json and data/archive.json.gz by name and alias (exact match, or
"core" match when words such as "synthesis" are removed, which is conservative). The index is not trusted for this:
usedOn is recomputed here. With fewer than --min-complete complete reactions, or no eligible one, the answer is
{"mode": "procedure"} and the run uses the repository-page procedure of the prompt.

check: among reactions with status "pending", the ones not attempted yet first (then the oldest attempt), those with an
English Wikipedia article before those without, those never used in a question before those used.
"""
import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog_load as cl  # noqa: E402

COOLDOWN = 14        # sets (days) before a reaction may come back; same as REPEAT_WINDOW in src/validate_problems.js
MIN_COMPLETE = 30    # complete reactions needed before the catalogue is used for the questions


def load(directory, problems_path, archive_path):
    sets = sorted(cl.read_sets(problems_path, archive_path), key=lambda s: s["date"])
    entries = cl.read_index(directory) or []
    shards = cl.read_shards(directory)
    idx = cl.used_index(sets)
    pos = {s["date"]: i for i, s in enumerate(sets)}
    usage = {}
    for e in entries:
        used = cl.used_on(idx, e["name"], e.get("aliases", []))
        exact = {u["date"] for u in used if u["match"] == "exact"}
        positions = [pos[u["date"]] for u in used if u["date"] in pos]
        usage[e["id"]] = {"timesUsed": len(exact), "last": max(positions) if positions else None,
                          "dates": {u["date"] for u in used if u["match"] == "exact"}}
    return sets, entries, shards, usage


def previous_class(sets, entries, shards, usage):
    if not sets:
        return None
    last_date = sets[-1]["date"]
    for e in entries:
        if last_date in usage[e["id"]]["dates"]:
            cls = (shards.get(e["id"]) or {}).get("class")
            if cls:
                return cls
    return None


def pick_next(directory, problems_path, archive_path, min_complete=MIN_COMPLETE):
    sets, entries, shards, usage = load(directory, problems_path, archive_path)
    complete = [e for e in entries if e.get("status") == "complete"]
    prev = previous_class(sets, entries, shards, usage)
    ranked = []
    for e in complete:
        sh = shards.get(e["id"]) or {}
        unused = [i for i, x in enumerate(sh.get("examples", []), 1) if x.get("status") == "unused"]
        u = usage[e["id"]]
        since = None if u["last"] is None else len(sets) - u["last"]
        if not unused or (since is not None and since < COOLDOWN):
            continue
        same = bool(prev) and sh.get("class") == prev
        ranked.append(((same, u["timesUsed"], -1 if u["last"] is None else u["last"], -len(unused), e["name"].casefold(), e["id"]),
                       e, sh, unused, since, same))
    ranked.sort(key=lambda r: r[0])
    info = {"complete": len(complete), "eligible": len(ranked), "previousClass": prev}
    if len(complete) < min_complete:
        return {"mode": "procedure", "reason": f"fewer than {min_complete} complete reactions in the catalogue", **info}
    if not ranked:
        return {"mode": "procedure", "reason": "no complete reaction with an unused example is off cooldown", **info}
    _, e, sh, unused, since, same = ranked[0]
    n = unused[0]
    return {"mode": "catalogue",
            "reaction": {"id": e["id"], "name": e["name"], "aliases": e.get("aliases", []), "wikipedia": e.get("wikipedia"),
                         "class": sh.get("class"), "repositories": sh.get("repositories", [])},
            "exampleNumber": n, "example": sh["examples"][n - 1],
            "timesUsed": usage[e["id"]]["timesUsed"], "setsSinceLastUse": since,
            "ranking": [{"id": r[1]["id"], "name": r[1]["name"], "timesUsed": usage[r[1]["id"]]["timesUsed"],
                         "setsSinceLastUse": r[4], "class": r[2].get("class"), "sameClassAsPrevious": r[5],
                         "unusedExamples": len(r[3])} for r in ranked[:5]],
            **info}


def pick_check(directory, problems_path, archive_path, n=1):
    sets, entries, shards, usage = load(directory, problems_path, archive_path)
    pending = [e for e in entries if e.get("status") == "pending"]
    pending.sort(key=lambda e: (e.get("lastAttempt") or "", e.get("wikipedia") is None, usage[e["id"]]["timesUsed"] > 0,
                                e["name"].casefold(), e["id"]))
    counts = {s: sum(1 for e in entries if e.get("status") == s) for s in cl.STATUSES}
    return {"reactions": [{"id": e["id"], "name": e["name"], "aliases": e.get("aliases", []), "wikipedia": e.get("wikipedia"),
                           "wikidataClasses": e.get("wikidataClasses", []), "timesUsed": usage[e["id"]]["timesUsed"],
                           "lastAttempt": e.get("lastAttempt")} for e in pending[:n]],
            "counts": counts}


def self_test():
    sets = [{"date": f"2026-01-{i + 1:02d}", "problems": [{"id": f"p{i}", "reaction": f"Reaction r{i}", "names": [f"Reaction r{i}"]}]}
            for i in range(20)]
    # names used at set indices: Alpha 0, Zeta 1, Beta 10, Delta 19 (the previous set)
    for i, nm in {0: "Alpha reaction", 1: "Zeta reaction", 10: "Beta reaction", 19: "Delta reaction"}.items():
        sets[i]["problems"][0]["reaction"] = nm
        sets[i]["problems"][0]["names"] = [nm]

    def ex(doi, status="unused"):
        return {"doi": doi, "license": "cc by", "status": status, "citation": "c", "substrate": {"smiles": "CC"}, "product": {"smiles": "CCO"}}

    def entry(qid, name, status="complete", wiki=True, **kw):
        return {"id": qid, "name": name, "aliases": [], "wikidata": "w", "wikipedia": "https://en.wikipedia.org/wiki/x" if wiki else None,
                "wikidataClasses": [], "usedOn": [], "lastUsed": None, "status": status, "nExamples": 0, "nUnused": 0, **kw}

    def shard(qid, cls, examples):
        return {"id": qid, "class": cls, "repositories": [{"site": "Wikipedia", "url": "https://en.wikipedia.org/wiki/x"}], "examples": examples}

    entries = [entry("QA", "Alpha reaction"), entry("QB", "Beta reaction"), entry("QC", "Gamma reaction"), entry("QD", "Delta reaction"),
               entry("QE", "Epsilon reaction"), entry("QF", "Zeta reaction"), entry("QG", "Eta reaction"),
               entry("P1", "Pending one", "pending"), entry("P2", "Pending two", "pending", wiki=False),
               entry("P3", "Pending three", "pending", lastAttempt="2026-01-01"), entry("P4", "Alpha reaction", "pending")]
    shards = [shard("QA", "olefination", [ex("10.1/a1")]), shard("QB", "oxidation", [ex("10.1/b1")]), shard("QC", "oxidation", [ex("10.1/c1")]),
              shard("QD", "olefination", [ex("10.1/d1")]), shard("QE", "olefination", [ex("10.1/e1"), ex("10.1/e2")]),
              shard("QF", "rearrangement", [ex("10.1/f1", "used"), ex("10.1/f2")]), shard("QG", "oxidation", [ex("10.1/g1", "used")])]
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, "catalog")
        cl.write_index(d, entries, "2026-01-01")
        for sh in shards:
            cl.write_shard(d, sh)
        prob = os.path.join(tmp, "problems.json")
        with open(prob, "w", encoding="utf-8") as f:
            json.dump({"sets": sets}, f)
        none = os.path.join(tmp, "no-archive.json.gz")
        r = pick_next(d, prob, none, min_complete=1)
        assert r["mode"] == "catalogue" and r["previousClass"] == "olefination", r
        # off cooldown and with an unused example: Alpha (used at 0), Gamma (never), Epsilon (never), Zeta (used at 1); not Beta (10),
        # Delta (19), Eta (no unused example). Same class as the previous set (olefination) comes last; then fewest uses.
        assert [x["name"] for x in r["ranking"]] == ["Gamma reaction", "Zeta reaction", "Epsilon reaction", "Alpha reaction"], r["ranking"]
        assert r["reaction"]["id"] == "QC" and r["exampleNumber"] == 1 and r["example"]["doi"] == "10.1/c1"
        assert pick_next(d, prob, none, min_complete=1) == r                       # deterministic
        # the second unused example of Zeta is number 2 (number 1 is used)
        z = pick_next(d, prob, none, min_complete=1)["ranking"]
        assert next(x for x in z if x["id"] == "QF")["unusedExamples"] == 1
        # not enough complete reactions
        assert pick_next(d, prob, none)["mode"] == "procedure" and "fewer than 30" in pick_next(d, prob, none)["reason"]
        # cooldown counts sets: with 4 more sets Beta (used at 10) is off cooldown (24 - 10 = 14), with 3 it is not
        more = lambda k: {"sets": sets + [{"date": f"2026-02-{i + 1:02d}", "problems": [{"id": f"q{i}", "reaction": f"Other {i}", "names": [f"Other {i}"]}]} for i in range(k)]}
        for k, expect in ((3, False), (4, True)):
            with open(prob, "w", encoding="utf-8") as f:
                json.dump(more(k), f)
            names = [x["name"] for x in pick_next(d, prob, none, min_complete=1)["ranking"]]
            assert ("Beta reaction" in names) == expect, (k, names)
        # nothing eligible
        with open(prob, "w", encoding="utf-8") as f:
            json.dump({"sets": sets}, f)
        for q in ("QA", "QC", "QE", "QF"):
            sh = next(s for s in shards if s["id"] == q)
            for x in sh["examples"]:
                x["status"] = "used"
            cl.write_shard(d, sh)
        assert pick_next(d, prob, none, min_complete=1)["mode"] == "procedure"
        # check: not attempted first (with Wikipedia before without, unused before used), then the oldest attempt
        c = pick_check(d, prob, none, n=10)
        assert [x["id"] for x in c["reactions"]] == ["P1", "P4", "P2", "P3"], c
        assert c["counts"]["pending"] == 4 and c["counts"]["complete"] == 7
        assert pick_check(d, prob, none)["reactions"][0]["id"] == "P1"
    print("self-test OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["next", "check"])
    ap.add_argument("--dir", default=cl.CATALOG_DIR)
    ap.add_argument("--problems", default=os.path.join(cl.ROOT, "data", "problems.json"))
    ap.add_argument("--archive", default=os.path.join(cl.ROOT, "data", "archive.json.gz"))
    ap.add_argument("--min-complete", type=int, default=MIN_COMPLETE)
    ap.add_argument("--n", type=int, default=1, help="check: number of reactions")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.command:
        ap.error("command (next or check) or --self-test required")
    if cl.read_index(a.dir) is None:
        sys.exit(f"{a.dir}/index.json is missing")
    out = pick_next(a.dir, a.problems, a.archive, a.min_complete) if a.command == "next" else pick_check(a.dir, a.problems, a.archive, a.n)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
