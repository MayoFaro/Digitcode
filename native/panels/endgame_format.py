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


def format_tempo_endgame(result: dict) -> str:
    """Phase-specific advice; retain both routes before a question."""
    def pct(v):
        return f"{100 * v:.1f} %"

    phase = result["phase"]
    lines = [f"Fin de partie — P(je gagne) estimée : {pct(result['p_win'])}"]
    lines.append(f"{result['n_public']} codes publics · {result['n_mine']} pour moi · "
                 f"{result['null_questions_remaining']} questions nulles disponibles")
    first = "moi" if phase in ("my_turn", "opp_post_question") else "l'adversaire"
    if result["null_questions_remaining"] % 2:
        first = "l'adversaire" if first == "moi" else "moi"
    decision, guess = result["decision"], result["guess_now"]
    if decision == "won":
        lines.append("Partie gagnée : l'adversaire n'a plus de tentative.")
        return "\n".join(lines)
    if decision == "none":
        lines.append("Partie terminée : aucune tentative restante.")
        return "\n".join(lines)
    if phase == "my_post_question":
        lines.append("À moi — question déjà posée. Choisir uniquement entre :")
        if guess:
            lines.append(f"• Proposer {guess['code']} : {pct(guess['p_win'])}")
        lines.append(f"• Terminer mon tour sans proposer : {pct(result['end_turn_p_win'])}")
        lines.append("Conseil : " + (f"proposer {guess['code']}." if decision == "guess_now"
                                    else "terminer mon tour sans proposer."))
        lines.append("Une nouvelle question n'est pas autorisée ce tour.")
    elif phase == "opp_post_question":
        lines.append("À l'adversaire — question déjà posée ; il peut proposer ou terminer son tour.")
        lines.append("Mes chances selon son choix :")
        lines.append(f"• Il propose : {pct(result['opponent_guess_p_win'])}")
        lines.append(f"• Il termine sans proposer : {pct(result['opponent_end_turn_p_win'])}")
        lines.append("Aucun coup à jouer pour moi pour l'instant.")
    elif phase == "opp_turn":
        lines.append("À l'adversaire — il peut poser une question et/ou proposer un code.")
        lines.append("Aucun coup à jouer pour moi pour l'instant.")
    else:
        lines.append("À moi — question pas encore posée.")
        if guess:
            lines.append(f"• Proposer directement {guess['code']} : {pct(guess['p_win'])}")
        for key, title in (("best_informative_question", "Question informative"),
                           ("best_null_question", "Question nulle, sans révéler d'information")):
            q = result.get(key)
            if q:
                lines.append(f"• {title} : {q['label']} — {pct(q['p_win'])}")
        best = result.get("best_question")
        if decision == "guess_now":
            lines.append(f"Conseil : proposer {guess['code']} directement.")
        elif best:
            lines.append(f"Conseil : poser {best['label']}")
        # Preserve the contingent plan even if the direct guess wins the comparison.
        for key, title in (("best_informative_question", "Après la question informative"),
                           ("best_null_question", "Après la question nulle")):
            q = result.get(key)
            if not q:
                continue
            lines.append(title + " :")
            for b in q["branches"]:
                action = f"proposer {b['code']}" if b["action"] == "guess" else "terminer le tour sans proposer"
                lines.append(f"  {b['answer']} ({b['n']} codes, {pct(b['prob'])}) → {action} ; victoire {pct(b['value'])}")
    lines.append(f"Si chacun ne joue que des questions nulles : {first} devra agir sans cette option en premier.")
    lines.append("Probabilités estimées sous le modèle de jeu.")
    return "\n".join(lines)
