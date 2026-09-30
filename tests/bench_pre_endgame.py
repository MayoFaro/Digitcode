"""Reproduce the N=60 archive without depending on a private archive file.

    python -m tests.bench_pre_endgame --seconds 55
"""
import argparse
import json

from digitcode.pre_endgame import evaluate_pre_endgame
from tests.test_pre_endgame import n60_clue


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=55)
    args = parser.parse_args()
    seen = set()
    def progress(result):
        for q in result['questions']:
            key = q['label'], q['status']
            if q['status'] != 'incomplete' and key not in seen:
                seen.add(key)
                print(json.dumps(dict(elapsed_s=result['elapsed_s'], question=q), ensure_ascii=False), flush=True)
    result = evaluate_pre_endgame(n60_clue(), 2, 2, time_budget_s=args.seconds, on_progress=progress)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
