"""Curation tool: atom hints and difficulty score for each problem in problems.json.

For each problem, the mechanism path is substrate -> intermediates (first form of each,
in order) -> product. Consecutive structures are aligned by maximum common substructure
(elements must match; repeated on the unmatched remainder, so a rearrangement that
splits the common substructure is still aligned). Three settings are tried for the first
fragment (any bond order; ring bonds only to ring bonds; exact bond order) and the
alignment with the fewest bond changes is kept (minimum chemical distance). Every atom keeps an
identity along the path:
  ("S", i)     atom i of the substrate SMILES (same index as in RDKit.js)
  ("R", k, j)  atom j of the k-th reagent that has a SMILES
  ("X", t, n)  heavy atom entering at transition t from a species without SMILES (e.g. water)
A bond is "made/broken" when a heavy-atom bond appears or disappears between two identities
(sigma change); a change of bond order between the same atoms is a pi change. H atoms are
not tracked. A reagent's own bonds count as pre-existing; a bond between two atoms that
both leave (e.g. inside Ph3PO) is not counted as broken.

Hints (up to 5 per question; fewer when the mechanism has fewer atoms that change): one atom per transition with a sigma change, in mechanism order, substrate
atoms preferred; with more such transitions than hints, an evenly spread subset including
the first and last is kept; with fewer, extra sigma atoms and then pi atoms are added.

Difficulty score = 2 x (steps - 1) + intermediates + 0.5 x sigma bond events.

Usage: python3 curate.py [problems.json] [--write]
"""
import json
import sys
from rdkit import Chem, RDLogger
from rdkit.Chem import rdFMCS

RDLogger.DisableLog("rdApp.*")



def mol(smi):
    m = Chem.MolFromSmiles(smi)
    if m is None:
        raise ValueError("bad SMILES " + smi)
    return m


def bond_table(m, labels):
    """{frozenset(labelA, labelB): bond order} for heavy-atom bonds."""
    t = {}
    for b in m.GetBonds():
        a, c = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        t[frozenset((labels[a], labels[c]))] = b.GetBondTypeAsDouble()
    return t


def mcs_maps(a, b, bond_any=True, ring_only=False, timeout=20):
    """All atom maps a->b for one maximum common substructure."""
    p = rdFMCS.MCSParameters()
    p.AtomTyper = rdFMCS.AtomCompare.CompareElements
    p.BondTyper = rdFMCS.BondCompare.CompareAny if bond_any else rdFMCS.BondCompare.CompareOrder
    p.BondCompareParameters.RingMatchesRingOnly = ring_only
    p.BondCompareParameters.CompleteRingsOnly = False
    p.AtomCompareParameters.MatchValences = False
    p.AtomCompareParameters.RingMatchesRingOnly = ring_only
    p.Timeout = timeout
    r = rdFMCS.FindMCS([a, b], p)
    if not r.smartsString:
        return []
    q = Chem.MolFromSmarts(r.smartsString)
    mas = a.GetSubstructMatches(q, uniquify=False, maxMatches=300, useChirality=False)
    mbs = b.GetSubstructMatches(q, uniquify=False, maxMatches=300, useChirality=False)
    seen, out = set(), []
    for ma in mas:  # both sides: the query can embed in more than one way in either molecule
        for mb in mbs:
            key = frozenset(zip(ma, mb))
            if key not in seen:
                seen.add(key)
                out.append(dict(zip(ma, mb)))
    return out


def fragment(m, atoms):
    """Sub-molecule made of the given atoms; returns (mol, new -> old index map)."""
    rw = Chem.RWMol(m)
    keep = sorted(atoms)
    for i in sorted(set(range(m.GetNumAtoms())) - set(keep), reverse=True):
        rw.RemoveAtom(i)
    f = rw.GetMol()
    f.UpdatePropertyCache(strict=False)
    return f, {n: o for n, o in enumerate(keep)}


def bond_cost(curr, lab, prev_t):
    """2 x sigma changes + pi changes between curr (atoms labelled in lab) and prev_t.
    Bonds from a placed atom to an atom not placed count as made/broken."""
    cost, seen = 0, set()
    for b in curr.GetBonds():
        x, y = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        if x in lab and y in lab:
            k = frozenset((lab[x], lab[y]))
            seen.add(k)
            if k not in prev_t:
                cost += 2
            elif prev_t[k] != b.GetBondTypeAsDouble():
                cost += 1
        elif x in lab or y in lab:
            cost += 2
    placed = set(lab.values())
    for k in prev_t:
        if k not in seen and k & placed:
            cost += 2
    return cost


FIRST_PASS = [dict(bond_any=True, ring_only=False),
              dict(bond_any=True, ring_only=True),
              dict(bond_any=False, ring_only=False)]


def map_pieces(prev, prev_labels, curr, prev_t, first, min_size=2):
    """Greedy multi-fragment MCS: curr atom index -> label carried over from prev."""
    lab = {}
    left_p = set(range(prev.GetNumAtoms()))
    left_c = set(range(curr.GetNumAtoms()))
    opts = first
    while left_p and left_c:
        fp, back_p = fragment(prev, left_p)
        fc, back_c = fragment(curr, left_c)
        best, best_cost = None, None
        for mp in mcs_maps(fp, fc, **opts):
            if len(mp) < min_size:
                break
            trial = dict(lab)
            trial.update({back_c[j]: prev_labels[back_p[i]] for i, j in mp.items()})
            c = bond_cost(curr, trial, prev_t)
            if best_cost is None or c < best_cost:
                best, best_cost = mp, c
        opts = FIRST_PASS[0]
        if not best:
            if lab:
                break
            continue
        for i, j in best.items():
            lab[back_c[j]] = prev_labels[back_p[i]]
            left_p.discard(back_p[i])
            left_c.discard(back_c[j])
    return lab


def best_pieces(prev, prev_labels, curr, prev_t):
    """Mapping with the fewest bond changes over several first-pass MCS settings."""
    best, best_cost = {}, None
    for first in FIRST_PASS:
        lab = map_pieces(prev, prev_labels, curr, prev_t, first)
        c = bond_cost(curr, lab, prev_t)
        if best_cost is None or c < best_cost:
            best, best_cost = lab, c
    return best


def label_structures(problem):
    sub = mol(problem["substrate"]["smiles"])
    reagents = []
    for st in problem["steps"]:
        for r in st["reagents"]:
            if r.get("smiles"):
                reagents.append((len(reagents), st["n"], r["text"], mol(r["smiles"])))
    path = [("substrate", sub, 0)]
    for st in problem["steps"]:
        for k, it in enumerate(st["intermediates"]):
            path.append((f"step {st['n']} int {k + 1}", mol(it["forms"][0]), st["n"]))
    path.append(("product", mol(problem["product"]["smiles"]), problem["steps"][-1]["n"]))

    labels = [[("S", i) for i in range(sub.GetNumAtoms())]]
    for t in range(1, len(path)):
        prev, curr, step_n = path[t - 1][1], path[t][1], path[t][2]
        prev_t = bond_table(prev, labels[t - 1])
        lab = best_pieces(prev, labels[t - 1], curr, prev_t)
        # atoms new in this structure: reagents of steps up to this one, largest overlap first
        pool = [r for r in reagents if r[1] <= step_n]
        while True:
            free = [j for j in range(curr.GetNumAtoms()) if j not in lab]
            if not free:
                break
            frag, back = fragment(curr, free)
            best = None
            for ri, _, _, rm in pool:
                for m2 in mcs_maps(rm, frag)[:1]:
                    ok = len(m2) >= 2 or rm.GetNumAtoms() == 1
                    if ok and (best is None or len(m2) > len(best[1])):
                        best = (ri, m2)
            if not best:
                break
            ri, m2 = best
            for rj, fj in m2.items():
                lab[back[fj]] = ("R", ri, rj)
        free = [j for j in range(curr.GetNumAtoms()) if j not in lab]
        for n, j in enumerate(free):
            lab[j] = ("X", t, n)
        labels.append([lab[j] for j in range(curr.GetNumAtoms())])
    return sub, reagents, path, labels


def transitions(path, labels, reagents):
    out = []
    seen = set(labels[0])
    for t in range(1, len(path)):
        a = bond_table(path[t - 1][1], labels[t - 1])
        b = bond_table(path[t][1], labels[t])
        present = set(labels[t])
        entering = present - seen
        for ri, _, _, rm in reagents:  # a reagent's own bonds exist before it enters
            for bd in rm.GetBonds():
                k = frozenset((("R", ri, bd.GetBeginAtomIdx()), ("R", ri, bd.GetEndAtomIdx())))
                if k not in a and k & entering:
                    a[k] = bd.GetBondTypeAsDouble()
        seen |= present
        made = [k for k in b if k not in a]
        broken = [k for k in a if k not in b and k & present]
        order = [k for k in b if k in a and a[k] != b[k]]
        sigma, pi = {}, {}
        for k in made + broken:
            for l in k:
                sigma[l] = sigma.get(l, 0) + 1
        for k in order:
            for l in k:
                pi[l] = pi.get(l, 0) + 1
        out.append({"name": path[t][0], "made": made, "broken": broken, "order": order,
                    "sigma": sigma, "pi": pi})
    return out


N_HINTS = 5


def pick_hints(trans, n_hints=3):
    def rank(l, tr):
        return (0 if l[0] == "S" else 1,
                -(tr["sigma"].get(l, 0) + tr["pi"].get(l, 0)), str(l))

    used, per_t = set(), []
    for t, tr in enumerate(trans):
        cands = [l for l in sorted(tr["sigma"], key=lambda l: rank(l, tr))
                 if l[0] != "X" and l not in used]
        if cands:
            used.add(cands[0])
            per_t.append((t, cands[0]))
    if len(per_t) > n_hints:  # spread evenly over the mechanism, first and last included
        keep = sorted({round(k * (len(per_t) - 1) / (n_hints - 1)) for k in range(n_hints)})
        used = {per_t[i][1] for i in keep}
        per_t = [per_t[i] for i in keep]
    if len(per_t) < n_hints:  # extra sigma atoms, then pi atoms, as far as the mechanism allows
        for key in ("sigma", "pi"):
            for t, tr in enumerate(trans):
                for l in sorted(tr[key], key=lambda l: rank(l, tr)):
                    if len(per_t) < n_hints and l[0] != "X" and l not in used:
                        used.add(l)
                        per_t.append((t, l))
        per_t.sort(key=lambda x: x[0])
    return per_t


def describe(l, sub, reagents):
    if l[0] == "S":
        return f"substrate atom {l[1]} ({sub.GetAtomWithIdx(l[1]).GetSymbol()})"
    if l[0] == "R":
        rm = reagents[l[1]]
        return f"reagent '{rm[2]}' atom {l[2]} ({rm[3].GetAtomWithIdx(l[2]).GetSymbol()})"
    return f"new atom {l}"


def curate(problem):
    sub, reagents, path, labels = label_structures(problem)
    trans = transitions(path, labels, reagents)
    hints = pick_hints(trans, N_HINTS)
    sigma_events = sum(len(tr["made"]) + len(tr["broken"]) for tr in trans)
    n_int = sum(len(s["intermediates"]) for s in problem["steps"])
    score = 2 * (len(problem["steps"]) - 1) + n_int + 0.5 * sigma_events
    hint_json = []
    for t, l in hints:
        h = {"transition": trans[t]["name"]}
        if l[0] == "S":
            h.update({"mol": "substrate", "atom": l[1]})
        else:
            h.update({"mol": "reagent", "step": reagents[l[1]][1], "reagent": reagents[l[1]][2],
                      "atom": l[2]})
        hint_json.append(h)
    fmt = lambda ks: [" - ".join(sorted(describe(l, sub, reagents) for l in k)) for k in ks]
    report = {
        "transitions": [(tr["name"], fmt(tr["made"]), fmt(tr["broken"]), fmt(tr["order"]))
                        for tr in trans],
        "hints": [f"{trans[t]['name']} -> {describe(l, sub, reagents)}" for t, l in hints],
        "difficulty": {"steps": len(problem["steps"]), "intermediates": n_int,
                       "sigmaBondEvents": sigma_events, "score": score},
    }
    return hint_json, report


def main():
    path = next((a for a in sys.argv[1:] if not a.startswith("--")), "problems.json")
    data = json.load(open(path, encoding="utf-8"))
    for day in data["sets"]:
        for p in day["problems"]:
            hints, rep = curate(p)
            p["hints"] = hints
            p["difficulty"] = rep["difficulty"]
            print(f"\n== {day['date']} {p['id']}  score {rep['difficulty']['score']}")
            for name, made, broken, order in rep["transitions"]:
                print(f"   -> {name}")
                for x in made:
                    print(f"        made   {x}")
                for x in broken:
                    print(f"        broken {x}")
                for x in order:
                    print(f"        order  {x}")
            for h in rep["hints"]:
                print("   HINT", h)
    if "--write" in sys.argv:
        json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("\nwritten", path)


if __name__ == "__main__":
    main()
