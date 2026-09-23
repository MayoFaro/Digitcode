"""Endgame engine benchmark (not a test -- run by hand).

    .venv/bin/python -m tests.bench_endgame perf
    .venv/bin/python -m tests.bench_endgame selfplay

perf: solve time vs N on boards reached by random real games.
selfplay: exact expected win rate of the new engine (all extensions on)
against the legacy model (strategy.py-equivalent), exhaustive over every
possible secret code and both seat orders, on random endgame boards.
"""
import random
import sys
import time

from digitcode.endgame import ME, EndgameSolver, build_universe, code_consistent
from digitcode.solver import Clue, DigitcodeSolver

NEW = dict(choose_guess=True, interior_direct_guess=True, track_opp_fail=True)
LEGACY = dict(choose_guess=False, interior_direct_guess=False, track_opp_fail=False)


def random_board(seed: int, target: int):
    """Play random questions against a random secret code until at most
    `target` solutions remain. Returns (solver, clue)."""
    rng = random.Random(seed)
    while True:
        code = tuple(rng.randint(0, 9) for _ in range(6))
        if code_consistent(code, Clue()):
            break
    clue = Clue()
    while True:
        s = DigitcodeSolver()
        s.propagate(clue)
        if s.count_solutions_exact(clue, cap=target + 1) <= target:
            return s, clue
        q = rng.choice(s.enumerate_all_questions(clue))
        for out in q["outcomes"]:
            child = s._apply_answer_to_clue(clue, q, out["answer"], 0)
            if code_consistent(code, child):
                clue = child
                break


def perf() -> None:
    for target in (6, 10, 14, 20):
        worst = 0.0
        for k in range(5):
            s, clue = random_board(1000 * target + k, target)
            t0 = time.monotonic()
            candidates, questions = build_universe(s, clue, n_max=40)
            t1 = time.monotonic()
            n = len(candidates)
            EndgameSolver(n, questions, **NEW).analyze((1 << n) - 1, -1, 2, 2, 0)
            t2 = time.monotonic()
            worst = max(worst, t2 - t0)
            print(f"target<={target:2d} N={n:2d} Q={len(questions):2d} universe {t1 - t0:.2f}s solve {t2 - t1:.2f}s", flush=True)
        print(f"  worst total for target<={target}: {worst:.2f}s", flush=True)


def play(questions, n: int, truth: int, agents, first: int):
    """One game; returns the winning seat, or None for a draw."""
    S = (1 << n) - 1
    e, a, m_fail = [-1, -1], [2, 2], [0, 0]
    mover = first
    for _ in range(100):
        i, j = mover, 1 - mover
        if a[i] == 0 and a[j] == 0:
            return None
        if a[i] == 0:
            return j
        if a[j] == 0:
            return i
        ei = e[i] if e[i] >= 0 and (S >> e[i]) & 1 else -1
        r = agents[i].analyze(S, ei, a[i], a[j], m_fail[j])

        def guess(g: int) -> bool:
            if g == truth:
                return True
            a[i] -= 1
            e[i] = g
            if a[i] == 1:
                m_fail[i] = S.bit_count()
            return False

        if r["decision"] == "guess_now":
            if guess(r["direct"]["g"]):
                return i
        elif r["decision"] == "question":
            best = r["questions"][0]
            q = questions[best["qi"]]
            ci = next(k for k, c in enumerate(q.classes) if (c >> truth) & 1)
            S &= q.classes[ci]
            b = next(b for b in best["branches"] if b["ci"] == ci)
            if b["action"] == "guess" and guess(b["g"]):
                return i
        mover = j
    return None


def selfplay() -> None:
    """new vs legacy over every truth and both seat orders, plus a
    CALIBRATION report per board: the engine's own predicted root p_win
    for the first mover next to the realised new-vs-new win rate of the
    first mover (averaged exhaustively over every truth). This is not a
    sanity check -- new-vs-new at a fixed seat order is not 0.5 by
    construction, unlike new-vs-new averaged over both seat orders would
    be for any deterministic engine. It is informational: the model is
    pessimistic about the opponent (see endgame.py's approximation), so
    realised is usually >= predicted, but this is not asserted."""
    new_wins = games = 0.0
    calibrated = boards = 0
    for k in range(20):
        s, clue = random_board(77 + k, 12)
        candidates, questions = build_universe(s, clue, n_max=40)
        n = len(candidates)
        if n < 3:
            continue
        full = (1 << n) - 1
        new, legacy, new2 = (
            EndgameSolver(n, questions, **NEW),
            EndgameSolver(n, questions, **LEGACY),
            EndgameSolver(n, questions, **NEW),
        )
        pred = new.analyze(full, -1, 2, 2, 0)["p_win"]
        board_new = board_games = 0.0
        realised_new = realised_games = 0.0
        for truth in range(n):
            for first in (0, 1):
                w = play(questions, n, truth, [new, legacy], first)
                board_new += 0.5 if w is None else (1.0 if w == 0 else 0.0)
                board_games += 1
            w2 = play(questions, n, truth, [new, new2], first=0)
            realised_new += 0.5 if w2 is None else (1.0 if w2 == 0 else 0.0)
            realised_games += 1
        realised = realised_new / realised_games
        boards += 1
        if realised >= pred - 1e-9:
            calibrated += 1
        new_wins += board_new
        games += board_games
        print(f"board {k:2d} N={n:2d}: new vs legacy {board_new / board_games:.3f}", flush=True)
        print(f"  calibration: pred {pred:.4f} realised {realised:.4f}", flush=True)
    print(f"OVERALL new vs legacy: {new_wins / games:.4f} over {int(games)} games")
    print(f"CALIBRATION: realised >= pred - 1e-9 on {calibrated}/{boards} boards")


if __name__ == "__main__":
    {"perf": perf, "selfplay": selfplay}[sys.argv[1]]()
