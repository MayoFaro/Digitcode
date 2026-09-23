from digitcode.native.panels.endgame_format import ENDGAME_PENDING_TEXT, format_endgame


def _question_result():
    return {
        "complete": True, "n_public": 5, "n_mine": 5, "p_win": 0.53,
        "decision": "question",
        "guess_now": {"code": "123 456", "p_win": 0.40},
        "best_question": {
            "qtype": "seg", "label": "X.e on/off ?", "p_win": 0.53,
            "branches": [
                {"answer": "on", "n": 2, "prob": 0.4, "action": "guess", "code": "123 456", "value": 0.5},
                {"answer": "off", "n": 3, "prob": 0.6, "action": "wait", "code": None, "value": 5 / 9},
            ],
        },
        "ranked_questions": [{"qtype": "seg", "label": "X.e on/off ?", "p_win": 0.53}],
    }


def test_question_decision_shows_the_question_the_alternative_and_each_branch():
    text = format_endgame(_question_result())
    assert "Fin de partie" in text and "53%" in text
    assert "Poser : X.e on/off ?" in text
    assert "proposer 123 456 tout de suite : 40%" in text
    assert "on (2 sol., 40%) → proposer 123 456 (50%)" in text
    assert "off (3 sol., 60%) → attendre (56%)" in text


def test_guess_now_decision_shows_the_code_and_the_best_question_as_alternative():
    res = _question_result()
    res["decision"] = "guess_now"
    res["p_win"] = 0.625
    res["guess_now"] = {"code": "654 321", "p_win": 0.625}
    text = format_endgame(res)
    assert "Proposer 654 321 maintenant" in text
    assert "meilleure question : X.e on/off ? : 53%" in text
    assert "→" not in text  # branches are only listed for a question decision


def test_none_decision():
    res = {"complete": True, "n_public": 3, "n_mine": 1, "p_win": 0.0, "decision": "none",
           "guess_now": None, "best_question": None, "ranked_questions": []}
    assert "Aucun coup possible" in format_endgame(res)


def test_incomplete_result():
    text = format_endgame({"complete": False, "n_public": 20})
    assert "calcul trop long" in text and "20" in text


def test_pending_text_mentions_the_endgame():
    assert "Fin de partie" in ENDGAME_PENDING_TEXT
