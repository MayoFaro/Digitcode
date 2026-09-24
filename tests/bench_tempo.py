"""Time the current endgame rules, without comparing against the old engine.

Run: python3 -m tests.bench_tempo
"""
import json
import time

from digitcode.endgame_tempo import evaluate_endgame
from .bench_endgame import random_board


def main():
    for seed in range(20000, 20005):
        solver, clue = random_board(seed, 20)
        start = time.monotonic()
        result = evaluate_endgame(solver, clue, 2, 2, frozenset())
        print(json.dumps({
            "seed": seed, "seconds": round(time.monotonic() - start, 3),
            "n": result.get("n_public"), "complete": result["complete"],
            "p_win": result.get("p_win"),
            "null_questions": result.get("null_questions_remaining"),
        }), flush=True)


if __name__ == "__main__":
    main()
