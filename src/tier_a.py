#!/usr/bin/env python3
"""Tier A changes (ML_PLAN.md): add a visitor's drawing to an intermediate's "forms" when it is a resonance form
of that intermediate. Same file in QDher/Daily-organic-chemistry-puzzles and QDher/Daily-name-reaction-puzzle.

Input: the output of the feedback Worker's check_clusters (structures the page answered "not on the path" for,
with the number of different visitors who drew them), saved to a file by the scheduled run:
  curl -sS -X POST -H "Content-Type: application/json" -d '{"p_site": "<site>"}' \
    https://puzzle-feedback.dailyorgchem.workers.dev/rpc/check_clusters > <clusters.json>
Usage (from the repository root):
  python3 src/tier_a.py data/problems.json <clusters.json>            report only
  python3 src/tier_a.py data/problems.json <clusters.json> --write    apply (at most --max changes, default 3)
Prints a JSON report: {"applied": [...], "skipped": [...]}.

A drawing is added only when all of these hold:
- at least --min-visitors (default 3) different visitors drew it;
- the problem is in data/problems.json (archived problems and unknown ids, such as test rows, are skipped);
- one fragment of the drawing is a resonance form of exactly one intermediate of the problem, and of no other
  intermediate, the substrate or the product. Resonance forms have the same atoms, sigma bonds and hydrogens; only
  pi bonds, lone pairs and charges differ. They come from RDKit's resonance enumeration plus the heteroatom shift
  C+-X <-> C=X+ (X = N, O, S). No hydrogen is moved, so tautomers and protonation states (already handled by the
  comparison key) and proton moves from one carbon to another (different species) are never added here.
The new form is the fragment as canonical SMILES without stereochemistry, appended after the existing forms, so
the order of intermediates, the hints (computed from forms[0]) and the progress stored by visitors do not change.
"""
import argparse
import json
import sys

from rdkit import Chem, RDLogger
from rdkit.Chem.rdMolDescriptors import CalcMolFormula

RDLogger.DisableLog("rdApp.*")

# no charge-separated forms of neutral species: they multiply the enumeration on large conjugated systems
FLAGS = Chem.ALLOW_INCOMPLETE_OCTETS | Chem.UNCONSTRAINED_CATIONS | Chem.UNCONSTRAINED_ANIONS
HETERO = (7, 8, 16)
MAX_FORMS = 400            # resonance forms enumerated per species (RDKit maxStructs and overall cap)
# allowed (formal charge, total valence) of N and O in a resonance form (octet kept: no oxenium or nitrenium ions)
VALENCE = {7: {(0, 3), (1, 4), (-1, 2)}, 8: {(0, 2), (1, 3), (-1, 1)}}


def canon(mol):
    m = Chem.Mol(mol)
    Chem.RemoveStereochemistry(m)
    return Chem.MolToSmiles(m)


def resonance(mol):
    out = {canon(mol)}
    try:
        for i, r in enumerate(Chem.ResonanceMolSupplier(mol, FLAGS, MAX_FORMS)):
            if i >= MAX_FORMS:
                break
            if r is not None:
                out.add(canon(r))
    except Exception:  # noqa: BLE001 - enumeration failure: keep the drawing itself
        pass
    return out


def hetero_shifts(mol):
    """C+-X -> C=X+ and C=X+ -> C+-X for X = N, O, S (non-aromatic bonds), hydrogens kept."""
    out = []
    for b in mol.GetBonds():
        for c, x in ((b.GetBeginAtom(), b.GetEndAtom()), (b.GetEndAtom(), b.GetBeginAtom())):
            if c.GetAtomicNum() != 6 or x.GetAtomicNum() not in HETERO or c.GetNumRadicalElectrons():
                continue
            if b.GetBondType() == Chem.BondType.SINGLE and c.GetFormalCharge() == 1 and x.GetFormalCharge() == 0:
                new = (Chem.BondType.DOUBLE, 0, 1)
            elif b.GetBondType() == Chem.BondType.DOUBLE and c.GetFormalCharge() == 0 and x.GetFormalCharge() == 1:
                new = (Chem.BondType.SINGLE, 1, 0)
            else:
                continue
            rw = Chem.RWMol(mol)
            for idx in (c.GetIdx(), x.GetIdx()):
                at = rw.GetAtomWithIdx(idx)
                at.SetNumExplicitHs(at.GetTotalNumHs())
                at.SetNoImplicit(True)
            rw.GetBondBetweenAtoms(c.GetIdx(), x.GetIdx()).SetBondType(new[0])
            rw.GetAtomWithIdx(c.GetIdx()).SetFormalCharge(new[1])
            rw.GetAtomWithIdx(x.GetIdx()).SetFormalCharge(new[2])
            try:
                m = rw.GetMol()
                Chem.SanitizeMol(m)
                out.append(m)
            except Exception:  # noqa: BLE001 - not a valid structure
                pass
    return out


def charged(mol):
    return sum(1 for a in mol.GetAtoms() if a.GetFormalCharge())


def sane(mol):
    for a in mol.GetAtoms():
        if a.GetNumRadicalElectrons():
            return False
        ok = VALENCE.get(a.GetAtomicNum())
        if ok is not None and (a.GetFormalCharge(), a.GetTotalValence()) not in ok:
            return False
    return True


def variants(smiles):
    """Canonical SMILES (no stereo) of the resonance forms of one species: same formula and charge as the drawing,
    no more charged atoms (no charge-separated forms), N and O with complete octets. Radicals are not enumerated
    (only the drawing itself). Empty if unreadable."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return set()
    if any(a.GetNumRadicalElectrons() for a in mol.GetAtoms()):
        return {canon(mol)}
    limit, formula = charged(mol), CalcMolFormula(mol)
    result, frontier = set(), [mol]
    for _ in range(3):
        nxt = []
        for m in frontier:
            if len(result) > MAX_FORMS:
                break
            for s in resonance(m):
                if s in result:
                    continue
                result.add(s)
                y = Chem.MolFromSmiles(s)
                if y is not None:
                    nxt.extend(hetero_shifts(y))
        frontier = nxt
        if not frontier or len(result) > MAX_FORMS:
            break
    keep = {canon(mol)}
    for s in result:
        m = Chem.MolFromSmiles(s)
        if m is not None and charged(m) <= limit and CalcMolFormula(m) == formula and sane(m):
            keep.add(s)
    return keep


def fragments(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return []
    return [canon(f) for f in Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True)]


def run(data, clusters, max_changes, min_visitors):
    problems = {p["id"]: p for s in data["sets"] for p in s["problems"]}
    applied, skipped, cache = [], [], {}

    def var(smi):
        if smi not in cache:
            cache[smi] = variants(smi)
        return cache[smi]

    order = sorted(clusters, key=lambda c: (-int(c.get("visitors", 0)), str(c.get("problem_id")), str(c.get("smiles"))))
    for c in order:
        pid, smi, n = c.get("problem_id"), c.get("smiles"), int(c.get("visitors", 0))
        rec = {"problemId": pid, "smiles": smi, "visitors": n}
        if n < min_visitors:
            skipped.append({**rec, "reason": f"fewer than {min_visitors} visitors"})
            continue
        p = problems.get(pid)
        if p is None:
            skipped.append({**rec, "reason": "problem not in data/problems.json (archived or test row)"})
            continue
        frags = fragments(smi or "")
        if not frags:
            skipped.append({**rec, "reason": "unreadable SMILES"})
            continue
        targets = [("substrate", None, p["substrate"]["smiles"]), ("product", None, p["product"]["smiles"])]
        for st in p["steps"]:
            for k, it in enumerate(st["intermediates"]):
                for f in it["forms"]:
                    targets.append(("intermediate", (st["n"], k), f))
        hits, form = set(), None
        for fr in frags:
            v = var(fr)
            for kind, where, t in targets:
                if v & var(t):
                    hits.add((kind, where))
                    if kind == "intermediate":
                        form = fr
        inter = [h for h in hits if h[0] == "intermediate"]
        if not hits:
            skipped.append({**rec, "reason": "not a resonance form of a species of this problem"})
            continue
        if len(hits) > 1 or not inter:
            skipped.append({**rec, "reason": "resonance form of " + ", ".join(
                h[0] if h[1] is None else f"step {h[1][0]} intermediate {h[1][1] + 1}" for h in sorted(hits, key=str))
                + " (not exactly one intermediate)"})
            continue
        (step_n, k) = inter[0][1]
        it = next(st for st in p["steps"] if st["n"] == step_n)["intermediates"][k]
        if form in {canon(Chem.MolFromSmiles(f)) for f in it["forms"] if Chem.MolFromSmiles(f) is not None}:
            skipped.append({**rec, "reason": "already listed"})
            continue
        if len(applied) >= max_changes:
            skipped.append({**rec, "reason": f"limit of {max_changes} changes per run reached"})
            continue
        it["forms"].append(form)
        applied.append({**rec, "step": step_n, "intermediate": k + 1, "label": it["label"], "addedForm": form})
    return applied, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("problems")
    ap.add_argument("clusters")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--max", type=int, default=3, dest="max_changes")
    ap.add_argument("--min-visitors", type=int, default=3)
    a = ap.parse_args()
    data = json.load(open(a.problems, encoding="utf-8"))
    clusters = json.load(open(a.clusters, encoding="utf-8"))
    if not isinstance(clusters, list):
        sys.exit("clusters file must hold the JSON array returned by check_clusters")
    applied, skipped = run(data, clusters, a.max_changes, a.min_visitors)
    if a.write and applied:
        with open(a.problems, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"written": bool(a.write and applied), "applied": applied, "skipped": skipped},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
