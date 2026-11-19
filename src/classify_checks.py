#!/usr/bin/env python3
"""Classify the structures visitors checked that the page rejected ("not on the path"), relative to the species of the
problem (substrate, intermediates, product, reagents). Offline, from data already collected; nothing is shown to
visitors and no problem is changed. Same file in QDher/Daily-organic-chemistry-puzzles and
QDher/Daily-name-reaction-puzzle (uses src/tier_a.py for resonance forms).

Input: the output of the feedback Worker's check_clusters with p_min 1 (every rejected structure, with the number of
different visitors who drew it):
  curl -sS -X POST -H "Content-Type: application/json" -d '{"p_site": "<site>", "p_min": 1}' \
    https://puzzle-feedback.dailyorgchem.workers.dev/rpc/check_clusters > /tmp/rejected.json
Usage (from the repository root):
  python3 src/classify_checks.py data/problems.json /tmp/rejected.json                          report (JSON on stdout)
  python3 src/classify_checks.py data/problems.json /tmp/rejected.json --write data/wrong_answers.json

Categories (first that applies, against the most similar species of the problem):
  resonance_form       a resonance form of a species (candidate for Tier A once drawn by 3 visitors)
  same_skeleton        same atoms and connections as a species, different bond orders, hydrogens or charges
                       (e.g. double bond in the wrong place, proton moved from one carbon to another)
  fragment_difference  formula of a species plus or minus a small molecule (H2O, HCl, CO2, MeOH, ...)
  isomer               same molecular formula as a species, different connections (regio- or constitutional isomer)
  reagent_or_byproduct a reagent of the problem drawn alone
  other                none of the above
(matches_species: identical to a listed species; should not occur, since the page accepts these.)
The written file keeps counts per problem and category; structures themselves only when drawn by at least
--min-examples different visitors (default 2).
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import rdFingerprintGenerator
from rdkit.Chem.rdMolDescriptors import CalcMolFormula

RDLogger.DisableLog("rdApp.*")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tier_a  # noqa: E402

SMALL = {"H2O": {"H": 2, "O": 1}, "HCl": {"H": 1, "Cl": 1}, "HBr": {"H": 1, "Br": 1}, "HI": {"H": 1, "I": 1},
         "CO2": {"C": 1, "O": 2}, "CO": {"C": 1, "O": 1}, "MeOH": {"C": 1, "H": 4, "O": 1}, "EtOH": {"C": 2, "H": 6, "O": 1},
         "NH3": {"N": 1, "H": 3}, "N2": {"N": 2}, "H2": {"H": 2}, "HF": {"H": 1, "F": 1}, "CH2O": {"C": 1, "H": 2, "O": 1},
         "AcOH": {"C": 2, "H": 4, "O": 2}, "SO2": {"S": 1, "O": 2}, "H": {"H": 1}}
FPGEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def mol(smiles):
    m = Chem.MolFromSmiles(smiles or "")
    if m is None:
        return None
    frags = Chem.GetMolFrags(m, asMols=True, sanitizeFrags=True)
    return max(frags, key=lambda f: f.GetNumHeavyAtoms()) if frags else None


def canon(m):
    c = Chem.Mol(m)
    Chem.RemoveStereochemistry(c)
    return Chem.MolToSmiles(c)


def skeleton(m):
    """Heavy atoms and connections only (bond orders, hydrogens, charges and aromaticity removed)."""
    rw = Chem.RWMol(Chem.RemoveHs(m))
    for b in rw.GetBonds():
        b.SetBondType(Chem.BondType.SINGLE)
        b.SetIsAromatic(False)
    for a in rw.GetAtoms():
        a.SetFormalCharge(0)
        a.SetIsAromatic(False)
        a.SetNoImplicit(False)
        a.SetNumExplicitHs(0)
        a.SetNumRadicalElectrons(0)
    s = rw.GetMol()
    s.UpdatePropertyCache(strict=False)
    Chem.GetSymmSSSR(s)
    return Chem.MolToSmiles(s)


def composition(m):
    c = Counter()
    for a in m.GetAtoms():
        c[a.GetSymbol()] += 1
        c["H"] += a.GetTotalNumHs()
    return c


def neutral_formula(m):
    return re.sub(r"[+-]\d*$", "", CalcMolFormula(m))      # charge suffix removed


def species(p):
    out = [("substrate", p["substrate"]["smiles"]), ("product", p["product"]["smiles"])]
    for st in p["steps"]:
        for k, it in enumerate(st["intermediates"]):
            for f in it["forms"]:
                out.append((f"step {st['n']} intermediate {k + 1}", f))
    reagents = [r["smiles"] for st in p["steps"] for r in st.get("reagents", []) if r.get("smiles")]
    return out, reagents


def classify(smiles, p, cache):
    m = mol(smiles)
    if m is None:
        return "unreadable", None, None
    targets, reagents = species(p)
    tm = [(name, mol(s), s) for name, s in targets]
    tm = [(n, x, s) for n, x, s in tm if x is not None]
    fp = FPGEN.GetFingerprint(m)
    sims = sorted(((DataStructs.TanimotoSimilarity(fp, FPGEN.GetFingerprint(x)), n, x, s) for n, x, s in tm), key=lambda t: -t[0])
    nearest = sims[0][1] if sims else None
    sim = round(sims[0][0], 2) if sims else None

    def var(s):
        if s not in cache:
            cache[s] = tier_a.variants(s)
        return cache[s]
    c = canon(m)
    for _, n, x, _s in sims:
        if canon(x) == c:
            return "matches_species", n, sim      # should not occur: the page accepts these
    v = var(c)
    for _, n, x, s in sims:
        if v & var(canon(x)):
            return "resonance_form", n, sim
    sk, comp, formula = skeleton(m), composition(m), neutral_formula(m)
    for _, n, x, _s in sims:
        if skeleton(x) == sk:
            return "same_skeleton", n, sim
    for _, n, x, _s in sims:
        diff = comp.copy()
        diff.subtract(composition(x))
        plus = {k: v_ for k, v_ in diff.items() if v_ > 0}
        minus = {k: -v_ for k, v_ in diff.items() if v_ < 0}
        for name, small in SMALL.items():
            if (plus == small and not minus) or (minus == small and not plus):
                return f"fragment_difference ({'+' if plus else '-'}{name})", n, sim
    for _, n, x, _s in sims:
        if neutral_formula(x) == formula:
            return "isomer", n, sim
    for r in reagents:
        rm = mol(r)
        if rm is not None and skeleton(rm) == sk:
            return "reagent_or_byproduct", "reagent", sim
    return "other", nearest, sim


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("problems")
    ap.add_argument("rejected")
    ap.add_argument("--write")
    ap.add_argument("--min-examples", type=int, default=2)
    a = ap.parse_args()
    problems = {p["id"]: p for s in json.load(open(a.problems, encoding="utf-8"))["sets"] for p in s["problems"]}
    rows = json.load(open(a.rejected, encoding="utf-8"))
    cache, per = {}, {}
    for r in rows:
        p = problems.get(r.get("problem_id"))
        if p is None:
            continue                       # archived problem or test row
        cat, near, sim = classify(r.get("smiles"), p, cache)
        e = per.setdefault(p["id"], {"rejected": 0, "visitors": 0, "categories": Counter(), "examples": []})
        e["rejected"] += 1
        e["visitors"] += int(r.get("visitors", 0))
        e["categories"][cat.split(" ")[0]] += int(r.get("visitors", 0))
        if int(r.get("visitors", 0)) >= a.min_examples:
            e["examples"].append({"smiles": r["smiles"], "visitors": int(r["visitors"]), "category": cat, "nearest": near, "similarity": sim})
    out = {"version": 1, "problems": {k: {**v, "categories": dict(v["categories"])} for k, v in sorted(per.items())}}
    text = json.dumps(out, ensure_ascii=False, indent=1) + "\n"
    if a.write:
        open(a.write, "w", encoding="utf-8").write(text)
    total = Counter()
    for v in per.values():
        total.update(v["categories"])
    print(json.dumps({"problems": len(per), "rejected_structures": sum(v["rejected"] for v in per.values()),
                      "by_category (visitors)": dict(total)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
