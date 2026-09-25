from __future__ import annotations

ENDGAME_PENDING_TEXT = "Fin de partie : calcul exact en cours…"


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def format_endgame(result: dict) -> str:
    """Multi-line text for the "Fin de partie" block (see
    endgame.evaluate_endgame for the dict shape)."""
    if result.get("model") == "tempo" and result["complete"]:
        return format_tempo_endgame(result)
    if not result["complete"]:
        count = result.get("n_public")
        pool = f" ({count} solutions)" if count is not None else ""
        return (
            f"Fin de partie{pool} : calcul trop long, "
            "EV de fin de partie non disponible ; vérifiez la phase avant de jouer."
        )
    lines = [f"Fin de partie — P(je gagne) = {_pct(result['p_win'])} (exact)"]
    decision = result["decision"]
    guess = result["guess_now"]
    best = result["best_question"]
    if decision == "opp_turn":
        lines.append("Tour de l'adversaire : rien à jouer pour l'instant.")
    elif result.get("phase") == "my_post_question":
        end = _pct(result["end_turn_p_win"])
        if decision == "guess_now":
            lines.append(f"➡️ Question posée ce tour : proposer {guess['code']} maintenant ({_pct(guess['p_win'])})")
            lines.append(f"   (finir le tour sans proposer : {end})")
        else:
            lines.append(f"➡️ Question posée ce tour : ne rien proposer, finir le tour ({end})")
            if guess is not None:
                lines.append(f"   (proposer {guess['code']} : {_pct(guess['p_win'])})")
    elif decision == "guess_now":
        lines.append(f"➡️ Proposer {guess['code']} maintenant ({_pct(guess['p_win'])})")
        if best is not None:
            lines.append(f"   (meilleure question : {best['label']} : {_pct(best['p_win'])})")
    elif decision == "question":
        lines.append(f"➡️ Poser : {best['label']} ({_pct(best['p_win'])})")
        if guess is not None:
            lines.append(f"   (proposer {guess['code']} tout de suite : {_pct(guess['p_win'])})")
        for b in best["branches"]:
            action = f"proposer {b['code']}" if b["action"] == "guess" else "attendre"
            lines.append(
                f"   • {b['answer']} ({b['n']} sol., {_pct(b['prob'])}) → {action} ({_pct(b['value'])})"
            )
    else:
        lines.append("Aucun coup possible (plus d'essai).")
    return "\n".join(lines)


def _tempo_pct(value: float) -> str:
    return f"{100 * value:.1f} %".replace(".", ",")


def format_tempo_endgame(result: dict) -> str:
    """Concise action comparisons, all measured as final victory probability."""
    pct = _tempo_pct
    phase, decision = result["phase"], result["decision"]
    guess = result["guess_now"]
    lines = ["Fin de partie", "P = probabilité estimée de gagner la partie, suite des tours comprise."]
    if decision in ("won", "none"):
        lines.append("Partie gagnée : l'adversaire n'a plus de tentative." if decision == "won"
                     else "Partie terminée : aucune tentative restante.")
    elif phase == "my_post_question":
        lines.append("À moi — question déjà posée.")
        if guess:
            lines.append(f"• Proposer {guess['code']} : P = {pct(guess['p_win'])}")
        lines.append(f"• Terminer mon tour sans proposer : P = {pct(result['end_turn_p_win'])}")
        lines.append("Mon conseil : " + (f"proposer {guess['code']}." if decision == "guess_now"
                                        else "terminer mon tour sans proposer."))
        lines.append("Une nouvelle question n'est pas autorisée ce tour.")
    elif phase == "opp_post_question":
        lines.append("À l'adversaire — question déjà posée.")
        lines.append(f"• Il propose : mes chances de victoire = {pct(result['opponent_guess_p_win'])}")
        lines.append(f"• Il termine sans proposer : mes chances de victoire = {pct(result['opponent_end_turn_p_win'])}")
        lines.append("Attendre son choix avant de jouer.")
    elif phase == "opp_turn":
        lines.append("À l'adversaire — question et/ou proposition.")
        lines.append(f"Mes chances de victoire estimées : {pct(result['p_win'])}.")
        lines.append("Aucun coup à jouer pour moi pour l'instant.")
    else:
        lines.append("À moi — avant question.")
        if guess:
            lines.append(f"• Proposer sans question ({guess['code']}) : P = {pct(guess['p_win'])}")
        question = result.get("best_question_then_guess")
        null = result.get("null_without_guess")
        lines.append(f"• Poser une question puis proposer : P = {pct(question['p_win'])} — {question['label']}"
                     if question else "• Question puis proposition : aucune question informative disponible.")
        lines.append(f"• Question nulle sans proposer : P = {pct(null['p_win'])}"
                     if null else "• Question nulle sans proposer : aucune disponible.")
        best = result.get("best_question")
        if decision == "guess_now":
            lines.append(f"Mon conseil : proposer {guess['code']} sans question.")
        elif best:
            branches = best["branches"]
            if best.get("is_null"):
                b = branches[0]
                if b["action"] == "guess":
                    # Do not hide a better policy just because it is outside
                    # the three fixed-action comparisons requested by the UI.
                    lines.append(f"• Question nulle puis proposition : P = {pct(best['p_win'])}")
                    lines.append(f"Mon conseil : poser {best['label']} puis proposer {b['code']}.")
                else:
                    lines.append(f"Mon conseil : poser {best['label']} puis terminer sans proposer.")
            else:
                if any(b["action"] == "wait" for b in branches):
                    lines.append(f"• Question puis décision selon la réponse : P = {pct(best['p_win'])}")
                lines.append(f"Mon conseil : poser {best['label']}")
                for b in branches:
                    action = f"proposer {b['code']}" if b["action"] == "guess" else "terminer sans proposer"
                    lines.append(f"  Si la réponse est {b['answer']} : {action}.")
    return "\n".join(lines)


def format_endgame_details(result: dict) -> str:
    """Optional explanation: response odds, immediate hit and final victory."""
    if not result.get("complete") or result.get("model") != "tempo":
        return ""
    pct = _tempo_pct
    lines = [f"{result['n_public']} codes publics ; {result['n_mine']} pour moi.",
             f"{result['null_questions_remaining']} questions nulles disponibles."]
    guess = result.get("guess_now")
    if guess and result["n_mine"]:
        lines.append(f"Proposition directe : réussite immédiate {pct(1 / result['n_mine'])}, "
                     f"victoire finale {pct(guess['p_win'])}.")
    q = result.get("best_question_then_guess")
    if q:
        lines.append(f"Question puis proposition — {q['label']}")
        for b in q["branches"]:
            lines.append(f"Réponse {b['answer']} : probabilité {pct(b['prob'])}, {b['n']} codes.")
            lines.append(f"  Proposer {b['guess_code']} : réussite immédiate {pct(b['immediate_hit'])} ; "
                         f"victoire finale {pct(b['guess_value'])}.")
        immediate = sum(b["prob"] * b["immediate_hit"] for b in q["branches"])
        terms = " + ".join(f"{pct(b['prob'])} × {pct(b['guess_value'])}" for b in q["branches"])
        lines.append(f"Victoire dès la proposition suivant la question : {pct(immediate)}.")
        lines.append(f"Victoire finale : {terms} = {pct(q['p_win'])}.")
    first = "moi" if result["phase"] in ("my_turn", "opp_post_question") else "l'adversaire"
    if result["null_questions_remaining"] % 2:
        first = "l'adversaire" if first == "moi" else "moi"
    lines.append(f"Si chacun ne joue que des questions nulles : {first} devra agir sans cette option en premier.")
    lines.append("La victoire finale inclut les suites après un échec et les coups adverses, "
                 "sous les hypothèses du modèle actuel.")
    return "\n".join(lines)
