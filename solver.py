from __future__ import annotations
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set, Optional

from .mapping import (
    DIGIT_TO_SEGS,
    POSITIONS,
    ADJACENT,
    row_contributors,
    col_contributors,
    grid_to_segment,
)

Digit = int
Pos = str
Seg = str

@dataclass
class Clue:
    row_totals: Dict[str, int] = field(default_factory=dict)
    col_totals: Dict[str, int] = field(default_factory=dict)
    parity: Dict[Pos, str] = field(default_factory=dict)
    comparisons: List[Tuple[Pos, str, Pos]] = field(default_factory=list)
    segment_state: Dict[Tuple[Pos, Seg], bool] = field(default_factory=dict)
    max_two: bool = True
    forbid_equal_adjacent: bool = True

class DigitcodeSolver:
    def __init__(self):
        self.domains: Dict[Pos, Set[Digit]] = {p: set(range(10)) for p in POSITIONS}
        self.trace: List[str] = []

    # ----------------------- utils trace -----------------------
    def clear_trace(self) -> None:
        self.trace.clear()
    def log(self, msg: str) -> None:
        self.trace.append(msg)

    # ------------------- contraintes locales -------------------
    def apply_parity(self, parity: Dict[Pos, str]) -> bool:
        changed = False
        for p, par in parity.items():
            if par not in ("Pair", "Impair"):
                continue
            before = set(self.domains[p])
            keep = {d for d in before if (d % 2 == 0) == (par == "Pair")}
            if keep != before:
                removed = sorted(before - keep)
                if removed:
                    self.log(f"[parité {p}={par}] retrait {removed}")
                self.domains[p] = keep
                changed = True
        return changed

    def apply_segment_states(self, seg_states: Dict[Tuple[Pos, Seg], bool]) -> bool:
        changed = False
        for (p, s), must_on in seg_states.items():
            before = set(self.domains[p])
            keep = {d for d in before if (s in DIGIT_TO_SEGS[d]) == must_on}
            if keep != before:
                removed = sorted(before - keep)
                if removed:
                    self.log(f"[segment {p}.{s}={'ON' if must_on else 'OFF'}] retrait {removed}")
                self.domains[p] = keep
                changed = True
        return changed

    def apply_comparisons(self, comps: List[Tuple[Pos, str, Pos]]) -> bool:
        changed = False
        for left, rel, right in comps:
            if rel not in (">", "<"):
                continue
            L_before, R_before = set(self.domains[left]), set(self.domains[right])
            L_after = {d for d in L_before if any((d > e) if rel==">" else (d < e) for e in R_before)}
            R_after = {e for e in R_before if any((v > e) if rel==">" else (v < e) for v in L_after)}
            if L_after != L_before:
                removed = sorted(L_before - L_after)
                if removed:
                    self.log(f"[comparaison {left}{rel}{right}] {left}: retrait {removed}")
                self.domains[left] = L_after; changed = True
            if R_after != R_before:
                removed = sorted(R_before - R_after)
                if removed:
                    self.log(f"[comparaison {left}{rel}{right}] {right}: retrait {removed}")
                self.domains[right] = R_after; changed = True
        return changed

    def apply_no_equal_adjacent(self) -> bool:
        changed = False
        for a, b in ADJACENT:
            if len(self.domains[a]) == 1:
                v = next(iter(self.domains[a]))
                if v in self.domains[b] and len(self.domains[b]) > 1:
                    nb = set(self.domains[b]); nb.discard(v)
                    if nb != self.domains[b]:
                        self.log(f"[≠ voisins {a}-{b}] {b}: retrait {v} (égal à {a})")
                        self.domains[b] = nb; changed = True
            if len(self.domains[b]) == 1:
                v = next(iter(self.domains[b]))
                if v in self.domains[a] and len(self.domains[a]) > 1:
                    na = set(self.domains[a]); na.discard(v)
                    if na != self.domains[a]:
                        self.log(f"[≠ voisins {a}-{b}] {a}: retrait {v} (égal à {b})")
                        self.domains[a] = na; changed = True
        return changed

    def apply_max_two(self) -> bool:
        changed = False
        fixed: Dict[int, int] = {}
        for p in POSITIONS:
            if len(self.domains[p]) == 1:
                v = next(iter(self.domains[p])); fixed[v] = fixed.get(v, 0) + 1
        for v, k in fixed.items():
            if k >= 2:
                for p in POSITIONS:
                    if len(self.domains[p]) > 1 and v in self.domains[p]:
                        nd = set(self.domains[p]); nd.discard(v)
                        if nd != self.domains[p]:
                            self.log(f"[≤2 occurrences] {p}: retrait {v} (déjà {k} fixés)")
                            self.domains[p] = nd; changed = True
        return changed

    # -------------------- totaux exacts (DP) -------------------
    def apply_total(self, contributors: List[Tuple[Pos, Seg]], target: int, label: str) -> bool:
        changed = False
        by_pos: Dict[Pos, List[Seg]] = {}
        for p, s in contributors:
            by_pos.setdefault(p, []).append(s)

        pos_map: Dict[Pos, Dict[int, int]] = {}
        pos_vals: Dict[Pos, Set[int]] = {}
        for p, segs in by_pos.items():
            dp, vals = {}, set()
            for d in self.domains[p]:
                c = sum(1 if s in DIGIT_TO_SEGS[d] else 0 for s in segs)
                dp[d] = c; vals.add(c)
            pos_map[p] = dp; pos_vals[p] = vals

        glob_min = sum(min(vs) if vs else 0 for vs in pos_vals.values())
        glob_max = sum(max(vs) if vs else 0 for vs in pos_vals.values())
        if not (glob_min <= target <= glob_max):
            # Genuinely unreachable, not merely "nothing to prune": returning
            # False here would silently let propagate() converge as if this
            # constraint had no effect, since the post-loop "domaine vide"
            # check only fires when SOME domain is emptied. Empty every
            # contributing position so that check catches it and the clue is
            # correctly rejected as a contradiction.
            self.log(f"[{label}] cible {target} impossible (min={glob_min}, max={glob_max}) — contradiction")
            for p in by_pos:
                if self.domains[p]:
                    self.domains[p] = set()
                    changed = True
            return changed

        def reachable_sum_set(pos_list: List[Pos]) -> Set[int]:
            sums = {0}
            for q in pos_list:
                nxt = set()
                for s0 in sums:
                    for v in pos_vals[q]:
                        nxt.add(s0 + v)
                sums = nxt
            return sums

        positions = list(by_pos.keys())
        for p in positions:
            others = [q for q in positions if q != p]
            other_sums = reachable_sum_set(others)
            before = set(self.domains[p]); keep: Set[int] = set()
            for d in before:
                need = target - pos_map[p][d]
                if need in other_sums:
                    keep.add(d)
            if keep != before:
                removed = sorted(before - keep)
                if removed:
                    self.log(f"[{label}] {p}: retrait {removed}")
                self.domains[p] = keep; changed = True
        return changed

    def apply_row_totals(self, row_totals: Dict[str, int]) -> bool:
        changed = False
        for row, tgt in row_totals.items():
            if tgt is None: continue
            changed |= self.apply_total(row_contributors(row), tgt, f"ligne {row}={tgt}")
        return changed

    def apply_col_totals(self, col_totals: Dict[str, int]) -> bool:
        changed = False
        for col, tgt in col_totals.items():
            if tgt is None: continue
            changed |= self.apply_total(col_contributors(col), tgt, f"colonne {col}={tgt}")
        return changed

    def propagate(self, clue: Clue) -> None:
        self.clear_trace()
        progress = True
        while progress:
            progress = False
            progress |= self.apply_parity(clue.parity)
            progress |= self.apply_segment_states(clue.segment_state)
            progress |= self.apply_comparisons(clue.comparisons)
            if clue.forbid_equal_adjacent:
                progress |= self.apply_no_equal_adjacent()
            progress |= self.apply_row_totals(clue.row_totals)
            progress |= self.apply_col_totals(clue.col_totals)
            if clue.max_two:
                progress |= self.apply_max_two()
            for p in POSITIONS:
                if not self.domains[p]:
                    self.log(f"[contradiction] domaine vide pour {p}")
                    raise ValueError(f"Domaine vide pour {p} (contradiction).")

    # -------------------- énumération codes --------------------
    def snapshot(self) -> Dict[str, List[int]]:
        return {p: sorted(list(v)) for p, v in self.domains.items()}

    def _code_from_domains(self, dom: Dict[Pos, Set[int]]) -> Optional[Dict[Pos,int]]:
        assign = {}
        for p in POSITIONS:
            if len(dom[p]) != 1: return None
            assign[p] = next(iter(dom[p]))
        return assign

    def _best_var(self, dom: Dict[Pos, Set[int]]) -> Optional[Pos]:
        cand = [p for p in POSITIONS if len(dom[p]) > 1]
        if not cand: return None
        return min(cand, key=lambda p: len(dom[p]))

    def _clone_domains(self, dom: Dict[Pos, Set[int]]) -> Dict[Pos, Set[int]]:
        return {p: set(vs) for p, vs in dom.items()}

    def enumerate_solutions(self, clue: Clue, limit: int = 3) -> List[Dict[Pos, int]]:
        start = self._clone_domains(self.domains)
        out: List[Dict[Pos,int]] = []
        def dfs(dom):
            if len(out) >= limit: return
            full = self._code_from_domains(dom)
            if full is not None: out.append(full); return
            var = self._best_var(dom)
            if var is None: return
            for val in sorted(dom[var]):
                child = DigitcodeSolver()
                nd = self._clone_domains(dom); nd[var] = {val}; child.domains = nd
                try: child.propagate(clue)
                except Exception: continue
                dfs(child.domains)
                if len(out) >= limit: return
        dfs(start); return out

    def solution_to_string(self, sol: Dict[Pos, int]) -> str:
        return f"{sol['T']}{sol['U']}{sol['V']} {sol['W']}{sol['X']}{sol['Y']}"

    # ------------------ questions “global risk” ------------------
    def _clone_clue(self, clue: Clue) -> Clue:
        nc = Clue()
        nc.row_totals = dict(clue.row_totals)
        nc.col_totals = dict(clue.col_totals)
        nc.parity = dict(clue.parity)
        nc.comparisons = list(clue.comparisons)
        nc.segment_state = dict(clue.segment_state)
        nc.max_two = clue.max_two
        nc.forbid_equal_adjacent = clue.forbid_equal_adjacent
        return nc

    def _reachable_sums(self, contributors: List[Tuple[Pos,Seg]]) -> List[int]:
        by_pos: Dict[Pos, List[Seg]] = {}
        for p,s in contributors: by_pos.setdefault(p, []).append(s)
        pos_vals: Dict[Pos, Set[int]] = {}
        for p,segs in by_pos.items():
            vals = set()
            for d in self.domains[p]:
                vals.add(sum(1 if s in DIGIT_TO_SEGS[d] else 0 for s in segs))
            pos_vals[p] = vals
        sums = {0}
        for p in by_pos.keys():
            nxt = set()
            for s0 in sums:
                for v in pos_vals[p]: nxt.add(s0+v)
            sums = nxt
        return sorted(sums)

    def _count_solutions_under(self, clue: Clue, limit: int = 3) -> int:
        child = DigitcodeSolver(); child.domains = self._clone_domains(self.domains)
        try: child.propagate(clue)
        except Exception: return 0
        return len(child.enumerate_solutions(clue, limit=limit))

    def _solutions_under(self, clue: Clue, limit: int = 2) -> List[Dict[Pos,int]]:
        child = DigitcodeSolver(); child.domains = self._clone_domains(self.domains)
        try: child.propagate(clue)
        except Exception: return []
        return child.enumerate_solutions(clue, limit=limit)

    def evaluate_global_questions(self, clue: Clue):
        res = []
        # LIGNES
        for row in "JKLMNOPQRS":
            if row in clue.row_totals: continue
            outs, all_n = [], []
            for val in self._reachable_sums(row_contributors(row)):
                c2 = self._clone_clue(clue); c2.row_totals[row] = val
                n = self._count_solutions_under(c2, 3); all_n.append(n)
                if 0 < n <= 2:
                    sols = self._solutions_under(c2, 2)
                    outs.append({"answer": str(val), "n": n,
                                 "codes": [self.solution_to_string(s) for s in sols]})
            if outs:
                res.append({"qtype":"row","label": f"Combien en ligne {row} ?",
                            "outcomes": outs, "guarantee": all(0 < n <= 2 for n in all_n)})

        # COLONNES
        for col in "ABCDEFGHI":
            if col in clue.col_totals: continue
            outs, all_n = [], []
            for val in self._reachable_sums(col_contributors(col)):
                c2 = self._clone_clue(clue); c2.col_totals[col] = val
                n = self._count_solutions_under(c2, 3); all_n.append(n)
                if 0 < n <= 2:
                    sols = self._solutions_under(c2, 2)
                    outs.append({"answer": str(val), "n": n,
                                 "codes": [self.solution_to_string(s) for s in sols]})
            if outs:
                res.append({"qtype":"col","label": f"Combien en colonne {col} ?",
                            "outcomes": outs, "guarantee": all(0 < n <= 2 for n in all_n)})

        # PARITÉ
        for p in POSITIONS:
            if p in clue.parity: continue
            ev = any(d % 2 == 0 for d in self.domains[p])
            od = any(d % 2 == 1 for d in self.domains[p])
            if not (ev or od): continue
            outs, all_n = [], []
            if ev:
                c2 = self._clone_clue(clue); c2.parity[p] = "Pair"
                n = self._count_solutions_under(c2, 3); all_n.append(n)
                if 0 < n <= 2:
                    outs.append({"answer":"Pair","n":n,
                                 "codes":[self.solution_to_string(s) for s in self._solutions_under(c2,2)]})
            if od:
                c2 = self._clone_clue(clue); c2.parity[p] = "Impair"
                n = self._count_solutions_under(c2, 3); all_n.append(n)
                if 0 < n <= 2:
                    outs.append({"answer":"Impair","n":n,
                                 "codes":[self.solution_to_string(s) for s in self._solutions_under(c2,2)]})
            if outs:
                res.append({"qtype":"parity","label": f"{p} pair/impair ?",
                            "outcomes": outs, "guarantee": all(0 < n <= 2 for n in all_n)})

        # COMPARAISONS
        for (a,b) in ADJACENT:
            outs, all_n = [], []
            gt = any(x > y for x in self.domains[a] for y in self.domains[b])
            lt = any(x < y for x in self.domains[a] for y in self.domains[b])
            if gt:
                c2 = self._clone_clue(clue); c2.comparisons.append((a,">",b))
                n = self._count_solutions_under(c2,3); all_n.append(n)
                if 0 < n <= 2:
                    outs.append({"answer":f"{a}>{b}","n":n,
                                 "codes":[self.solution_to_string(s) for s in self._solutions_under(c2,2)]})
            if lt:
                c2 = self._clone_clue(clue); c2.comparisons.append((a,"<",b))
                n = self._count_solutions_under(c2,3); all_n.append(n)
                if 0 < n <= 2:
                    outs.append({"answer":f"{a}<{b}","n":n,
                                 "codes":[self.solution_to_string(s) for s in self._solutions_under(c2,2)]})
            if outs:
                res.append({"qtype":"cmp","label": f"Qui est plus grand, {a} ou {b} ?",
                            "outcomes": outs, "guarantee": all(0 < n <= 2 for n in all_n)})

        # SEGMENTS
        for p in POSITIONS:
            for seg in "abcdefg":
                on_possible  = any(seg in  DIGIT_TO_SEGS[d] for d in self.domains[p])
                off_possible = any(seg not in DIGIT_TO_SEGS[d] for d in self.domains[p])
                if not (on_possible and off_possible): continue
                outs, all_n = [], []
                c2 = self._clone_clue(clue); c2.segment_state[(p,seg)] = True
                n = self._count_solutions_under(c2,3); all_n.append(n)
                if 0 < n <= 2:
                    outs.append({"answer":"on","n":n,
                                 "codes":[self.solution_to_string(s) for s in self._solutions_under(c2,2)]})
                c3 = self._clone_clue(clue); c3.segment_state[(p,seg)] = False
                n = self._count_solutions_under(c3,3); all_n.append(n)
                if 0 < n <= 2:
                    outs.append({"answer":"off","n":n,
                                 "codes":[self.solution_to_string(s) for s in self._solutions_under(c3,2)]})
                if outs:
                    res.append({"qtype":"seg","label": f"{p}.{seg} on/off ?",
                                "outcomes": outs, "guarantee": all(0 < n <= 2 for n in all_n)})

        type_rank = {"row":0, "col":0, "parity":1, "cmp":2, "seg":3}
        res.sort(key=lambda r: (type_rank.get(r["qtype"],3), not r["guarantee"], -len(r["outcomes"])))
        return res

    # ------------------ énumération “toutes questions” ------------------
    def enumerate_all_questions(self, clue: Clue):
        res = []

        # rows
        for row in "JKLMNOPQRS":
            if row in clue.row_totals: continue
            outs = []
            for val in self._reachable_sums(row_contributors(row)):
                c2 = self._clone_clue(clue); c2.row_totals[row] = val
                n = self._count_solutions_under(c2, limit=3)
                outs.append({"answer": str(val), "n": n})
            if outs: res.append({"qtype":"row","label": f"Combien en ligne {row} ?", "outcomes": outs})

        # cols
        for col in "ABCDEFGHI":
            if col in clue.col_totals: continue
            outs = []
            for val in self._reachable_sums(col_contributors(col)):
                c2 = self._clone_clue(clue); c2.col_totals[col] = val
                n = self._count_solutions_under(c2, limit=3)
                outs.append({"answer": str(val), "n": n})
            if outs: res.append({"qtype":"col","label": f"Combien en colonne {col} ?", "outcomes": outs})

        # parity
        for p in POSITIONS:
            if p in clue.parity: continue
            ev = any(d % 2 == 0 for d in self.domains[p])
            od = any(d % 2 == 1 for d in self.domains[p])
            outs = []
            if ev:
                c2 = self._clone_clue(clue); c2.parity[p] = "Pair"
                outs.append({"answer":"Pair","n": self._count_solutions_under(c2,3)})
            if od:
                c2 = self._clone_clue(clue); c2.parity[p] = "Impair"
                outs.append({"answer":"Impair","n": self._count_solutions_under(c2,3)})
            if outs: res.append({"qtype":"parity","label": f"{p} pair/impair ?", "outcomes": outs})

        # comparisons (adjacents)
        for (a,b) in ADJACENT:
            outs = []
            gt = any(x > y for x in self.domains[a] for y in self.domains[b])
            lt = any(x < y for x in self.domains[a] for y in self.domains[b])
            if gt:
                c2 = self._clone_clue(clue); c2.comparisons.append((a,">",b))
                outs.append({"answer":f"{a}>{b}","n": self._count_solutions_under(c2,3)})
            if lt:
                c2 = self._clone_clue(clue); c2.comparisons.append((a,"<",b))
                outs.append({"answer":f"{a}<{b}","n": self._count_solutions_under(c2,3)})
            if outs: res.append({"qtype":"cmp","label": f"Qui est plus grand, {a} ou {b} ?", "outcomes": outs})

        # segments
        for p in POSITIONS:
            for seg in "abcdefg":
                on_possible  = any(seg in  DIGIT_TO_SEGS[d] for d in self.domains[p])
                off_possible = any(seg not in DIGIT_TO_SEGS[d] for d in self.domains[p])
                if not (on_possible and off_possible): continue
                outs = []
                c2 = self._clone_clue(clue); c2.segment_state[(p,seg)] = True
                outs.append({"answer":"on","n": self._count_solutions_under(c2,3)})
                c3 = self._clone_clue(clue); c3.segment_state[(p,seg)] = False
                outs.append({"answer":"off","n": self._count_solutions_under(c3,3)})
                res.append({"qtype":"seg","label": f"{p}.{seg} on/off ?", "outcomes": outs})

        type_rank = {"row":0, "col":0, "parity":1, "cmp":2, "seg":3}
        res.sort(key=lambda r: (type_rank.get(r["qtype"],3), r["label"]))
        return res

    # ----------------- détection des “forcing” -----------------
    def evaluate_forcing_questions(self, clue: Clue, strict: bool = True):
        results = []
        my_qs = self.enumerate_all_questions(clue)

        def child_has_safe_question(child_clue: Clue) -> bool:
            tmp = DigitcodeSolver()
            tmp.domains = self._clone_domains(self.domains)
            try:
                tmp.propagate(child_clue)
            except Exception:
                return False

            opp_all = tmp.enumerate_all_questions(child_clue)

            def is_safe(q2):
                return all(o["n"] is None or o["n"] >= 3 for o in q2["outcomes"])

            return any(is_safe(q2) for q2 in opp_all)

        for q in my_qs:
            forcing_answers = []
            samples_next = set()
            total_answers = len(q["outcomes"])
            if total_answers == 0:
                continue

            for out in q["outcomes"]:
                ans = out["answer"]

                child = self._clone_clue(clue)
                if q["qtype"] == "row":
                    row = q["label"].split()[-2]
                    child.row_totals[row] = int(ans)
                elif q["qtype"] == "col":
                    col = q["label"].split()[-2]
                    child.col_totals[col] = int(ans)
                elif q["qtype"] == "parity":
                    p = q["label"].split()[0]
                    if ans in ("Pair", "Impair"):
                        child.parity[p] = ans
                elif q["qtype"] == "cmp":
                    parts = q["label"].split()
                    a, b = parts[-4], parts[-2]
                    child.comparisons.append((a, ">", b) if ">" in ans else (a, "<", b))
                elif q["qtype"] == "seg":
                    p, seg = q["label"].split()[0].split(".")
                    child.segment_state[(p, seg)] = (ans == "on")

                if strict:
                    tmp_now = DigitcodeSolver()
                    tmp_now.domains = self._clone_domains(self.domains)
                    try:
                        tmp_now.propagate(child)
                    except Exception:
                        continue
                    n_now = len(tmp_now.enumerate_solutions(child, limit=3))
                    if n_now <= 2:
                        forcing_answers = []
                        samples_next = set()
                        total_answers = 0
                        break

                if not child_has_safe_question(child):
                    forcing_answers.append(ans)
                    tmp = DigitcodeSolver()
                    tmp.domains = self._clone_domains(self.domains)
                    try:
                        tmp.propagate(child)
                        risky = tmp.evaluate_global_questions(child)
                        for r in risky[:2]:
                            samples_next.add(r["label"])
                    except Exception:
                        pass

            if forcing_answers and total_answers > 0:
                results.append({
                    "qtype": q["qtype"],
                    "label": q["label"],
                    "coverage": f"{len(forcing_answers)}/{total_answers}",
                    "guarantee": (len(forcing_answers) == total_answers),
                    "forcing_answers": forcing_answers,
                    "samples": sorted(samples_next)
                })

        type_rank = {"row": 0, "col": 0, "parity": 1, "cmp": 2, "seg": 3}
        def cov_key(x):
            a, b = x["coverage"].split("/")
            return (type_rank.get(x["qtype"], 3), not x["guarantee"], -(int(a) / int(b) if int(b) else 0))
        results.sort(key=cov_key)
        return results

    # ===================== EV METRICS (exact, uniform over solutions) =====================
    def _dfs_count(self, dom, clue: Clue, cap: Optional[int]=None) -> int:
        count = 0
        def dfs(local_dom):
            nonlocal count
            if cap is not None and count >= cap:
                return
            full = self._code_from_domains(local_dom)
            if full is not None:
                count += 1
                return
            var = self._best_var(local_dom)
            if var is None:
                return
            for val in sorted(local_dom[var]):
                child = DigitcodeSolver()
                nd = self._clone_domains(local_dom); nd[var] = {val}; child.domains = nd
                try:
                    child.propagate(clue)
                except Exception:
                    continue
                dfs(child.domains)
                if cap is not None and count >= cap:
                    return
        dfs(dom)
        return count

    def count_solutions_exact(self, clue: Clue, cap: Optional[int]=None) -> int:
        child = DigitcodeSolver()
        child.domains = self._clone_domains(self.domains)
        try:
            child.propagate(clue)
        except Exception:
            return 0
        return child._dfs_count(child.domains, clue, cap=cap)

    def count_solutions_capped(self, clue: Clue, cap: Optional[int] = None) -> int:
        """Exact solution count via direct constraint-checking over the
        (already-propagated) domains, without the per-node solver-object
        creation and full re-propagation that makes `count_solutions_exact`
        slow on large domains (~10x faster on an empty board).

        Parity and segment_state are pure per-position domain filters with
        no cross-position interaction, so `self.domains` already reflects
        them exactly and they need no re-check here. Adjacency, max-two,
        row/col totals and comparisons all constrain COMBINATIONS of
        positions, and domain-narrowing alone does not guarantee every
        surviving combination jointly satisfies them (see the confluence
        note on strategy.py's `_clue_signature`), so those are re-checked
        directly against each full candidate tuple.

        With `cap` set, stops as soon as `cap` matches are found; the
        returned count is then a lower bound, not the true total.
        """
        pos_idx = {p: i for i, p in enumerate(POSITIONS)}
        doms = [sorted(self.domains[p]) for p in POSITIONS]
        adj_idx = [(pos_idx[a], pos_idx[b]) for a, b in ADJACENT]
        cmp_idx = [(pos_idx[l], rel, pos_idx[r]) for (l, rel, r) in clue.comparisons if rel in (">", "<")]
        row_checks = [
            ([(pos_idx[p], s) for p, s in row_contributors(row)], tgt)
            for row, tgt in clue.row_totals.items() if tgt is not None
        ]
        col_checks = [
            ([(pos_idx[p], s) for p, s in col_contributors(col)], tgt)
            for col, tgt in clue.col_totals.items() if tgt is not None
        ]

        count = 0
        for combo in itertools.product(*doms):
            if any(combo[i] == combo[j] for i, j in adj_idx):
                continue
            occurrences: Dict[int, int] = {}
            over_max = False
            for v in combo:
                c = occurrences.get(v, 0) + 1
                if c > 2:
                    over_max = True
                    break
                occurrences[v] = c
            if over_max:
                continue
            if any((combo[i] <= combo[j]) if rel == ">" else (combo[i] >= combo[j]) for i, rel, j in cmp_idx):
                continue
            if any(
                sum(1 for idx, seg in contribs if seg in DIGIT_TO_SEGS[combo[idx]]) != tgt
                for contribs, tgt in row_checks
            ):
                continue
            if any(
                sum(1 for idx, seg in contribs if seg in DIGIT_TO_SEGS[combo[idx]]) != tgt
                for contribs, tgt in col_checks
            ):
                continue
            count += 1
            if cap is not None and count >= cap:
                return count
        return count

    def _list_question_values(self, clue: Clue, q: dict) -> List[Tuple[str,int]]:
        res = []
        qt = q["qtype"]
        if qt == "row":
            row = q["label"].split()[-2]
            for val in self._reachable_sums(row_contributors(row)):
                res.append((str(val), val))
        elif qt == "col":
            col = q["label"].split()[-2]
            for val in self._reachable_sums(col_contributors(col)):
                res.append((str(val), val))
        elif qt == "parity":
            p = q["label"].split()[0]
            ev = any(d % 2 == 0 for d in self.domains[p])
            od = any(d % 2 == 1 for d in self.domains[p])
            if ev: res.append(("Pair", 1))
            if od: res.append(("Impair", 0))
        elif qt == "cmp":
            parts = q["label"].split()
            a, b = parts[-4], parts[-2]
            gt = any(x > y for x in self.domains[a] for y in self.domains[b])
            lt = any(x < y for x in self.domains[a] for y in self.domains[b])
            if gt: res.append((f"{a}>{b}", 1))
            if lt: res.append((f"{a}<{b}", -1))
        elif qt == "seg":
            p, seg = q["label"].split()[0].split(".")
            on_possible  = any(seg in  DIGIT_TO_SEGS[d] for d in self.domains[p])
            off_possible = any(seg not in DIGIT_TO_SEGS[d] for d in self.domains[p])
            if on_possible:  res.append(("on", 1))
            if off_possible: res.append(("off", 0))
        return res

    def _apply_answer_to_clue(self, base: Clue, q: dict, ans_label: str, ans_meta: int) -> Clue:
        child = self._clone_clue(base)
        qt = q["qtype"]
        if qt == "row":
            row = q["label"].split()[-2]
            child.row_totals[row] = int(ans_label)
        elif qt == "col":
            col = q["label"].split()[-2]
            child.col_totals[col] = int(ans_label)
        elif qt == "parity":
            p = q["label"].split()[0]
            child.parity[p] = "Pair" if ans_label == "Pair" else "Impair"
        elif qt == "cmp":
            parts = q["label"].split()
            a, b = parts[-4], parts[-2]
            if ">" in ans_label:
                child.comparisons.append((a,">",b))
            else:
                child.comparisons.append((a,"<",b))
        elif qt == "seg":
            p, seg = q["label"].split()[0].split(".")
            child.segment_state[(p, seg)] = (ans_label == "on")
        return child

    def _ev_immediate_for_question(self, clue: Clue, q: dict, cap: Optional[int]=None) -> Tuple[float, int, List[Tuple[str,int,int]]]:
        N = self.count_solutions_exact(clue, cap=cap)
        if N == 0:
            return 0.0, 0, []
        ev = 0.0
        details = []
        for (ans_label, meta) in self._list_question_values(clue, q):
            child = self._apply_answer_to_clue(clue, q, ans_label, meta)
            n_r = self.count_solutions_exact(child, cap=cap)
            win_flag = 0
            if n_r == 1:
                ev += (n_r / N) * 1.0
                win_flag = 1
            elif n_r == 2:
                ev += (n_r / N) * 0.5
                win_flag = 2
            details.append((ans_label, n_r, win_flag))
        return ev, N, details

    def _best_opponent_ev_immediate(self, clue: Clue, cap: Optional[int]=None) -> float:
        tmp = DigitcodeSolver()
        tmp.domains = self._clone_domains(self.domains)
        try:
            tmp.propagate(clue)
        except Exception:
            return 0.0
        qs = tmp.enumerate_all_questions(clue)
        best = 0.0
        for q in qs:
            ev, _, _ = tmp._ev_immediate_for_question(clue, q, cap=cap)
            if ev > best: best = ev
        return best

    def ev_metrics_for_question(self, clue: Clue, q: dict, cap: Optional[int]=None) -> Dict[str, float]:
        ev_imm, N, details = self._ev_immediate_for_question(clue, q, cap=cap)
        if N == 0:
            return {"ev_imm": 0.0, "p_plateau_if_bad": 0.0, "ev_depth1": 0.0}

        mass_bad = 0
        mass_plateau = 0
        ev_depth1 = 0.0
        for (ans_label, n_r, win_flag) in details:
            if n_r == 0: 
                continue
            prob = n_r / N
            if win_flag == 1:
                ev_depth1 += prob * 1.0
            elif win_flag == 2:
                ev_depth1 += prob * 0.5
            else:
                child = self._apply_answer_to_clue(clue, q, ans_label, 0)
                opp_ev = self._best_opponent_ev_immediate(child, cap=cap)
                ev_depth1 += prob * (1.0 - opp_ev)
                mass_bad += n_r
                if opp_ev > 0:
                    mass_plateau += n_r

        p_plateau = (mass_plateau / mass_bad) if mass_bad > 0 else 0.0
        return {"ev_imm": ev_imm, "p_plateau_if_bad": p_plateau, "ev_depth1": ev_depth1}
