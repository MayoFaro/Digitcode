from __future__ import annotations

ENDGAME_PENDING_TEXT = "Fin de partie : calcul exact en cours…"


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def format_endgame(result: dict) -> str:
    """Multi-line text for the "Fin de partie" block (see
    endgame.evaluate_endgame for the dict shape)."""
    if not result["complete"]:
        return (
            f"Fin de partie ({result['n_public']} solutions) : calcul trop long, "
            "suivez la recommandation ci-dessus."
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
