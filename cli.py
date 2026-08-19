import re
from typing import Optional, Tuple, List, Dict

from digitcode.solver import DigitcodeSolver, Clue
from digitcode.mapping import grid_to_segment
from digitcode.strategy import evaluate_race_strategy

HELP = """
Entrées (séparées par virgules ou une par ligne) :

  Sommes colonnes (A..I) :    A3, B5, C- (supprime)
  Sommes lignes (J..S)   :    L4, J- (supprime)
  Parité (T..Y)          :    U pair, V impair, T none (supprime)
  Comparaisons           :    W>X, T<U, del T>U (supprime)
  Segments ON/OFF        :    TAM off, XBR on, TBR- (supprime)

Commandes :
  show   -> domaines + trace + résumé + alertes
  hint   -> opportunités (issues à ≤2)   [hint all/rows/cols/50]
  risk   -> alias de hint
  race     -> stratégie de course exacte (P(gagner), meilleure question, deviner ou non)
  opp-miss -> enregistre un échec de proposition de l'adversaire
  my-miss  -> enregistre un de vos échecs de proposition (choix parmi les solutions affichées)
  rank   -> classement EV (imm), P(plateau|mauvaise), EV profondeur [rank 20 cap=20000 rows/cols/parity/cmp/seg]
  undo   -> annule la dernière modification
  reset  -> remet tout à zéro
  help / quit
"""

ROW_LETTERS = set("JKLMNOPQRS")
COL_LETTERS = set("ABCDEFGHI")
POS = set("TUVWXY")

def clone_clue(c: Clue) -> Clue:
    nc = Clue()
    nc.row_totals = dict(c.row_totals)
    nc.col_totals = dict(c.col_totals)
    nc.parity = dict(c.parity)
    nc.comparisons = list(c.comparisons)
    nc.segment_state = dict(c.segment_state)
    nc.max_two = c.max_two
    nc.forbid_equal_adjacent = c.forbid_equal_adjacent
    return nc

def ask_confirm(msg: str) -> bool:
    try:
        ans = input(f"⚠️  {msg} Confirmer ? [o/N] ").strip().lower()
    except EOFError:
        return False
    return ans in ("o","oui","y","yes")

def print_trace(s: DigitcodeSolver):
    for line in s.trace:
        print("•", line)

def _sol_tuple(sol: Dict[str, int]): return (sol["T"],sol["U"],sol["V"],sol["W"],sol["X"],sol["Y"])
def _is_swap_pair(a, b):
    diffs = [i for i in range(6) if a[i] != b[i]]
    return len(diffs)==2 and a[diffs[0]]==b[diffs[1]] and a[diffs[1]]==b[diffs[0]]

def print_solution_summary(s: DigitcodeSolver, clue: Clue) -> None:
    sols = s.enumerate_solutions(clue, limit=5)
    if len(sols)==0:
        print("⚠️  Aucune solution complète (contradiction)."); return
    if len(sols)==1:
        print("✅ Solution unique :", s.solution_to_string(sols[0])); return
    if len(sols)<=4:
        tuples = [_sol_tuple(sol) for sol in sols]
        labels = [s.solution_to_string(sol) for sol in sols]
        n = len(sols); used=set(); tokens=[]
        for i in range(n):
            if i in used: continue
            paired=False
            for j in range(i+1,n):
                if j in used: continue
                if _is_swap_pair(tuples[i], tuples[j]):
                    tokens.append(f"{labels[i]} / {labels[j]}")
                    used.add(i); used.add(j); paired=True; break
            if not paired:
                tokens.append(labels[i]); used.add(i)
        print("🧩 Solutions possibles (≤4) :", " ; ".join(tokens)); return
    print("… Plus de 4 solutions (liste non affichée).")

def show_hints(s: DigitcodeSolver, clue: Clue, top: Optional[int]=30, only_types: Optional[set]=None):
    qs = s.evaluate_global_questions(clue)
    if only_types: qs = [q for q in qs if q["qtype"] in only_types]
    if not qs: print("(aucune opportunité immédiate)"); return
    if top is not None: qs = qs[:top]
    print("Opportunités (issues pouvant tomber à ≤2 solutions) :")
    for q in qs:
        tag = " (garanti ≤2)" if q["guarantee"] else ""
        print(f"- {q['label']}{tag}")
        for out in q["outcomes"]:
            if out["n"]==1:
                print(f"    • {out['answer']} -> ✅ {out['codes'][0]}")
            elif out["n"]==2:
                codes = out.get("codes",[])
                if len(codes)==2:
                    print(f"    • {out['answer']} -> 🔀 {codes[0]} / {codes[1]}")
                else:
                    print(f"    • {out['answer']} -> 🔀 deux solutions")
        print("")

def print_risk_alert(s: DigitcodeSolver, clue: Clue, top: int = 6):
    qs = s.evaluate_global_questions(clue)
    if not qs: return
    print("⚡ Portes de finish (≤2) à envisager :")
    for q in qs[:top]:
        issues = ", ".join(out["answer"] for out in q["outcomes"])
        gar = " (garanti ≤2)" if q["guarantee"] else ""
        print(f"   - {q['label']}{gar} [{issues}]")
    if len(qs) > top: print("   … 'hint' pour le détail.")

def _format_pct(x: float) -> str:
    return f"{round(100*x, 2):.2f}%"

def show_race(s: DigitcodeSolver, clue: Clue, a_me: int, a_opp: int, my_excluded: frozenset) -> None:
    res = evaluate_race_strategy(s, clue, a_me, a_opp, my_excluded)
    tag = "exact" if res["exact"] else "estimation (N trop grand)"
    print(f"🎲 Stratégie de course [{tag}] — essais: moi {a_me}/2, adversaire {a_opp}/2")
    print(f"   P(je gagne) = {_format_pct(res['p_win'])}")
    if res["guess_now"]:
        print("   -> PROPOSER UNE SOLUTION MAINTENANT.")
    if res["best_question"] is not None:
        print(f"   Meilleure question : {res['best_question']['label']}")
    for alt in res["ranked_alternatives"][:5]:
        print(f"     · {alt['label']} — P(gagner)={_format_pct(alt['p_win'])}")

def show_rank(s: DigitcodeSolver, clue: Clue, top: int = 20, cap: int = None, only_types: Optional[set]=None):
    try:
        s2 = DigitcodeSolver(); s2.domains = {k:set(v) for k,v in s.domains.items()}
        s2.propagate(clue)
        qs = s2.enumerate_all_questions(clue)
        if only_types: qs = [q for q in qs if q["qtype"] in only_types]
        rows = []
        for q in qs:
            m = s2.ev_metrics_for_question(clue, q, cap=cap)
            rows.append((m["ev_depth1"], m["ev_imm"], m["p_plateau_if_bad"], q["qtype"], q["label"]))
        if not rows:
            print("(aucune question candidate)")
            return
        rows.sort(key=lambda t: (-t[0], -t[1], t[2]))
        if top is not None:
            rows = rows[:top]
        print("Classement (meilleur d'abord):")
        for evd, evi, pplt, qt, lab in rows:
            print(f"- {lab}  |  EV(imm)={_format_pct(evi)}  |  P(plateau|mauvaise)={_format_pct(pplt)}  |  EV profondeur={_format_pct(evd)}")
    except Exception as e:
        print(f"Erreur (rank): {e}")

def parse_one(token: str, clue: Clue) -> str:
    t = token.strip()
    if not t: return ""
    if t.lower() in ("help","aide"): return HELP

    # UNSET
    m = re.fullmatch(r"([J-Z])\s*[-?]", t, flags=re.IGNORECASE)
    if m:
        row = m.group(1).upper()
        if row in ROW_LETTERS:
            clue.row_totals.pop(row, None); return f"(supprimé) Ligne {row}"
    m = re.fullmatch(r"([A-I])\s*[-?]", t, flags=re.IGNORECASE)
    if m:
        col = m.group(1).upper()
        clue.col_totals.pop(col, None); return f"(supprimé) Colonne {col}"
    m = re.fullmatch(r"([TUVWXY])\s*(none|\?|-)\s*", t, flags=re.IGNORECASE)
    if m:
        pos = m.group(1).upper()
        clue.parity.pop(pos, None); return f"(supprimé) Parité {pos}"
    m = (re.fullmatch(r"([TUVWXY])\s*([A-I])\s*([J-Z])\s*[-?]", t, flags=re.IGNORECASE)
         or re.fullmatch(r"([TUVWXY])\s*([A-I])([J-Z])\s*[-?]", t, flags=re.IGNORECASE))
    if m:
        pos, col, row = m.group(1).upper(), m.group(2).upper(), m.group(3).upper()
        seg = grid_to_segment(pos, row, col)
        if seg is None: return f"Cellule {col}{row} invalide pour {pos}."
        clue.segment_state.pop((pos, seg), None); return f"(supprimé) Segment {pos}{col}{row}"
    m = re.fullmatch(r"del\s+([TUVWXY])\s*([<>])\s*([TUVWXY])", t, flags=re.IGNORECASE)
    if m:
        left, rel, right = m.group(1).upper(), m.group(2), m.group(3).upper()
        try:
            if (left,rel,right) in clue.comparisons:
                clue.comparisons.remove((left,rel,right)); return f"(supprimé) {left}{rel}{right}"
            inv = '<' if rel == '>' else '>'
            if (right,inv,left) in clue.comparisons:
                clue.comparisons.remove((right,inv,left)); return f"(supprimé) {left}{rel}{right}"
            return f"Aucune comparaison {left}{rel}{right} à supprimer."
        except ValueError:
            return f"Aucune comparaison {left}{rel}{right} à supprimer."

    # SET
    m = re.fullmatch(r"([J-Z])\s*=\s*([0-9]+)", t, flags=re.IGNORECASE) \
        or re.fullmatch(r"([J-Z])\s*([0-9]+)", t, flags=re.IGNORECASE)
    if m:
        row, n = m.group(1).upper(), int(m.group(2))
        if row in ROW_LETTERS and 0 <= n <= 9:
            prev = clue.row_totals.get(row, None)
            if prev is not None and prev != n:
                if not ask_confirm(f"modification de Ligne {row} : {prev} -> {n}."):
                    return f"(annulé) Ligne {row} reste {prev}"
            clue.row_totals[row] = n; return f"Ligne {row} = {n}"

    m = re.fullmatch(r"([A-I])\s*=\s*([0-9]+)", t, flags=re.IGNORECASE) \
        or re.fullmatch(r"([A-I])\s*([0-9]+)", t, flags=re.IGNORECASE)
    if m:
        col, n = m.group(1).upper(), int(m.group(2))
        prev = clue.col_totals.get(col, None)
        if prev is not None and prev != n:
            if not ask_confirm(f"modification de Colonne {col} : {prev} -> {n}."):
                return f"(annulé) Colonne {col} reste {prev}"
        clue.col_totals[col] = n; return f"Colonne {col} = {n}"

    m = re.fullmatch(r"([TUVWXY])\s+(pair|impair)", t, flags=re.IGNORECASE)
    if m:
        pos, par = m.group(1).upper(), m.group(2).capitalize()
        prev = clue.parity.get(pos, None)
        if prev is not None and prev != par:
            if not ask_confirm(f"modification de Parité {pos} : {prev} -> {par}."):
                return f"(annulé) Parité {pos} reste {prev}"
        clue.parity[pos] = par; return f"{pos} {par}"

    m = re.fullmatch(r"([TUVWXY])\s*([<>])\s*([TUVWXY])", t, flags=re.IGNORECASE)
    if m:
        left, rel, right = m.group(1).upper(), m.group(2), m.group(3).upper()
        def existing(a,b):
            for (x,r,y) in clue.comparisons:
                if (x,y)==(a,b): return r
                if (x,y)==(b,a): return '>' if r=='<' else '<'
            return None
        cur = existing(left,right)
        if cur is None:
            clue.comparisons.append((left,rel,right)); return f"{left} {rel} {right}"
        if cur == rel:
            return f"(inchangé) {left}{rel}{right} déjà présent"
        stored = (left,cur,right) if (left,cur,right) in clue.comparisons else (right, '<' if cur=='>' else '>', left)
        if ask_confirm(f"remplacer {stored[0]}{stored[1]}{stored[2]} par {left}{rel}{right} ?"):
            try: clue.comparisons.remove(stored)
            except ValueError: pass
            clue.comparisons.append((left,rel,right))
            return f"(remplacé) {stored[0]}{stored[1]}{stored[2]} -> {left}{rel}{right}"
        return f"(annulé) {left}{rel}{right}"

    m = (re.fullmatch(r"([TUVWXY])\s*([A-I])\s*([J-Z])\s+(on|off)", t, flags=re.IGNORECASE)
         or re.fullmatch(r"([TUVWXY])\s*([A-I])([J-Z])\s+(on|off)", t, flags=re.IGNORECASE))
    if m:
        pos, col, row, state = m.group(1).upper(), m.group(2).upper(), m.group(3).upper(), m.group(4).lower()
        seg = grid_to_segment(pos, row, col)
        if seg is None: return f"Cellule {col}{row} invalide pour {pos}."
        key, newv = (pos, seg), (state=="on")
        prev = clue.segment_state.get(key, None)
        if prev is not None and prev != newv:
            if not ask_confirm(f"modification de Segment {pos}{col}{row} : {'ON' if prev else 'OFF'} -> {'ON' if newv else 'OFF'}."):
                return f"(annulé) Segment {pos}{col}{row} inchangé"
        clue.segment_state[key] = newv; return f"Segment {pos}{col}{row} {'ON' if newv else 'OFF'}"

    return f"Incompris: “{t}”. Tape 'help' pour la syntaxe."

def main():
    s = DigitcodeSolver()
    clue = Clue()
    history: List[Clue] = []
    a_me = 2
    a_opp = 2
    my_excluded: frozenset = frozenset()

    print("Digitcode CLI (risques + zugzwang). Tape 'help' pour l'aide.")
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line: continue

        low = line.lower()
        if low == "quit": break
        if low == "help": print(HELP); continue

        if low == "reset":
            s = DigitcodeSolver(); clue = Clue(); history.clear()
            a_me, a_opp, my_excluded = 2, 2, frozenset()
            print("Réinitialisé."); continue

        if low == "undo":
            if history:
                clue = history.pop()
                try:
                    s = DigitcodeSolver(); s.propagate(clue)
                    print_trace(s)
                    snap = s.snapshot()
                    print("(undo) ", {k: snap[k] for k in ["T","U","V","W","X","Y"]})
                    print_solution_summary(s, clue)
                    print_risk_alert(s, clue)
                    show_race(s, clue, a_me, a_opp, my_excluded)
                except Exception as e:
                    print(f"Erreur: {e}")
            else:
                print("Rien à annuler.")
            continue

        if low.startswith("hint") or low == "risk":
            try:
                s = DigitcodeSolver(); s.propagate(clue); print_trace(s)
                only, top = None, 30
                parts = low.split()
                if len(parts)>=2:
                    arg = parts[1]
                    if arg=="all": top=None
                    elif arg in ("rows","lignes"): only={"row"}; top=None
                    elif arg in ("cols","colonnes"): only={"col"}; top=None
                    elif arg.isdigit(): top=int(arg)
                show_hints(s, clue, top=top, only_types=only)
            except Exception as e:
                print(f"Erreur: {e}")
            continue

        if low == "race":
            try:
                s = DigitcodeSolver(); s.propagate(clue); print_trace(s)
                show_race(s, clue, a_me, a_opp, my_excluded)
            except Exception as e:
                print(f"Erreur: {e}")
            continue

        if low == "opp-miss":
            if a_opp <= 0:
                print("L'adversaire n'a plus d'essai.")
            else:
                a_opp -= 1
                print(f"Échec adverse enregistré. Adversaire : {a_opp}/2 essai(s) restant(s).")
            continue

        if low == "my-miss":
            if a_me <= 0:
                print("Vous n'avez plus d'essai.")
            else:
                try:
                    s = DigitcodeSolver(); s.propagate(clue)
                    sols = s.enumerate_solutions(clue, limit=6)
                    if not sols:
                        print("Aucune solution candidate à exclure.")
                    else:
                        print("Quelle solution avez-vous tentée ?")
                        for i, sol in enumerate(sols):
                            print(f"  {i}: {s.solution_to_string(sol)}")
                        idx_raw = input("  index > ").strip()
                        if idx_raw.isdigit() and int(idx_raw) < len(sols):
                            tried = _sol_tuple(sols[int(idx_raw)])
                            my_excluded = my_excluded | {tried}
                            a_me -= 1
                            print(f"Échec enregistré pour {s.solution_to_string(sols[int(idx_raw)])}. Vous : {a_me}/2 essai(s) restant(s).")
                        else:
                            print("Index invalide, rien d'enregistré.")
                except Exception as e:
                    print(f"Erreur: {e}")
            continue

        if low.startswith("rank"):
            try:
                s = DigitcodeSolver(); s.propagate(clue); print_trace(s)
                parts = low.split()
                top = 20
                cap = None
                only = None
                for arg in parts[1:]:
                    if arg.isdigit(): top = int(arg)
                    elif arg.startswith("cap="):
                        try: cap = int(arg.split("=",1)[1])
                        except: cap = None
                    elif arg in ("rows","lignes"): only = {"row"}
                    elif arg in ("cols","colonnes"): only = {"col"}
                    elif arg in ("parity","cmp","seg"): only = {arg}
                show_rank(s, clue, top=top, cap=cap, only_types=only)
            except Exception as e:
                print(f"Erreur: {e}")
            continue

        if low == "show":
            try:
                s = DigitcodeSolver(); s.propagate(clue)
                print_trace(s)
                snap = s.snapshot()
                print({k: snap[k] for k in ["T","U","V","W","X","Y"]})
                print_solution_summary(s, clue)
                print_risk_alert(s, clue)
                show_race(s, clue, a_me, a_opp, my_excluded)
            except Exception as e:
                print(f"Erreur: {e}")
            continue

        # saisie normale
        history.append(clone_clue(clue))
        parts = [p for p in line.split(",") if p.strip()]
        msgs: List[str] = []
        for tok in parts:
            msg = parse_one(tok, clue)
            if msg: msgs.append(msg)

        try:
            s = DigitcodeSolver(); s.propagate(clue)
            print_trace(s)
            snap = s.snapshot()
            if msgs: print(" ; ".join(msgs))
            print({k: snap[k] for k in ["T","U","V","W","X","Y"]})
            print_solution_summary(s, clue)
            print_risk_alert(s, clue)
            show_race(s, clue, a_me, a_opp, my_excluded)
        except Exception as e:
            print(f"Erreur: {e}")

if __name__ == "__main__":
    main()
