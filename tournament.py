"""Resumable, paired DG1-vs-challenger tournaments.

Run a small bounded slice from an interactive shell, or repeat the command
until the checkpoint reports completion::

    python -m digitcode.tournament --games 500 --checkpoint /tmp/dg1-dg2.json --pairs 2
    python -m digitcode.tournament --games 500 --checkpoint /tmp/dg1-dg3.json --engine dg3 --pairs 2

Every secret is played twice (DG1 starts, then the challenger starts).  The
checkpoint is atomically replaced after each completed pair, so an
interrupted run never invalidates previous measurements.  The checkpoint
schema itself does not record which engine was used -- give each engine its
own ``--checkpoint`` path, the same discipline the existing DG1-vs-DG2
benchmarks already rely on, rather than a new field that would break
resuming those already-committed, in-progress files.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import random
import tempfile
import time
from typing import Callable

from .dg2 import DG2Policy
from .mapping import ADJACENT, POSITIONS
from .selfplay import DG1Policy, MatchResult, Policy, play_match

Candidate = tuple[int, int, int, int, int, int]
SCHEMA_VERSION = 1


def _make_dg2(seed: int) -> Policy:
    return DG2Policy(seed=seed)


def _make_dg3(seed: int) -> Policy:
    from .dg3 import DG3Policy
    return DG3Policy()


ENGINES: dict[str, Callable[[int], Policy]] = {"dg2": _make_dg2, "dg3": _make_dg3}


def _valid_secret(code: Candidate) -> bool:
    values = dict(zip(POSITIONS, code))
    return (not any(values[a] == values[b] for a, b in ADJACENT)
            and max(code.count(value) for value in set(code)) <= 2)


def generate_secrets(count: int, seed: int) -> list[Candidate]:
    rng = random.Random(seed)
    result: list[Candidate] = []
    while len(result) < count:
        code = tuple(rng.randrange(10) for _ in range(6))
        if _valid_secret(code) and code not in result:
            result.append(code)
    return result


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
    temporary.replace(path)


def _new_checkpoint(games: int, seed: int, dg1_time_budget_s: float) -> dict:
    if games <= 0 or games % 2:
        raise ValueError("Le nombre de matchs doit être positif et pair.")
    secrets = generate_secrets(games // 2, seed)
    return {
        "schema_version": SCHEMA_VERSION,
        "config": {"games": games, "seed": seed, "dg1_time_budget_s": dg1_time_budget_s},
        "secrets": ["".join(map(str, code)) for code in secrets],
        "pairs": [],
    }


def load_or_create(path: Path, *, games: int, seed: int, dg1_time_budget_s: float) -> dict:
    if not path.exists():
        state = _new_checkpoint(games, seed, dg1_time_budget_s)
        _atomic_json(path, state)
        return state
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Version de checkpoint de tournoi non prise en charge.")
    expected = {"games": games, "seed": seed, "dg1_time_budget_s": dg1_time_budget_s}
    if state.get("config") != expected:
        raise ValueError("Le checkpoint existe mais sa configuration diffère de la commande demandée.")
    return state


def _play_pair(
    secret: Candidate, index: int, *, seed: int, dg1_time_budget_s: float,
    make_challenger: Callable[[int], Policy] = _make_dg2, label: str = "DG2",
) -> dict:
    games = []
    for dg1_starts in (True, False):
        # A fresh policy per match makes the only randomness explicit in the
        # record.  DG1 remains deterministic; the challenger's seed is
        # reproducible (DG3 ignores it -- it has no randomness to seed).
        dg2_seed = seed * 1_000_003 + index * 2 + int(not dg1_starts)
        dg1 = DG1Policy(time_budget_s=dg1_time_budget_s)
        dg2 = make_challenger(dg2_seed)
        started = time.monotonic()
        result: MatchResult = play_match(
            secret,
            dg1 if dg1_starts else dg2,
            dg2 if dg1_starts else dg1,
            starter=0,
        )
        winner = ("DG1", label)[result.winner] if dg1_starts else (label, "DG1")[result.winner]
        games.append({
            "dg1_starts": dg1_starts,
            "dg2_seed": dg2_seed,
            "winner": winner,
            "questions": sum(event.kind == "ask" for event in result.events),
            "guesses": sum(event.kind == "guess" for event in result.events),
            "duration_s": round(time.monotonic() - started, 3),
        })
    return {"index": index, "secret": "".join(map(str, secret)), "games": games}


def run_chunk(path: Path, *, games: int = 500, seed: int = 20261102,
              dg1_time_budget_s: float = 0.25, pairs: int = 1,
              play_pair: Callable[..., dict] = _play_pair,
              on_pair_complete: Callable[[dict, dict], None] | None = None,
              label: str = "DG2") -> dict:
    """Run at most ``pairs`` unfinished secret pairs and checkpoint each one."""
    state = load_or_create(path, games=games, seed=seed, dg1_time_budget_s=dg1_time_budget_s)
    done = {pair["index"] for pair in state["pairs"]}
    secrets = [tuple(map(int, code)) for code in state["secrets"]]
    for index, secret in enumerate(secrets):
        if index in done:
            continue
        pair = play_pair(secret, index, seed=seed, dg1_time_budget_s=dg1_time_budget_s)
        state["pairs"].append(pair)
        state["pairs"].sort(key=lambda pair: pair["index"])
        _atomic_json(path, state)
        if on_pair_complete is not None:
            on_pair_complete(pair, summary(state, label))
        if len({pair["index"] for pair in state["pairs"]} - done) >= pairs:
            break
    return summary(state, label)


def summary(state: dict, label: str = "DG2") -> dict:
    completed_games = [game for pair in state["pairs"] for game in pair["games"]]
    winners = Counter(game["winner"] for game in completed_games)
    return {
        "completed_games": len(completed_games),
        "target_games": state["config"]["games"],
        "completed_pairs": len(state["pairs"]),
        "target_pairs": len(state["secrets"]),
        "wins": {"DG1": winners["DG1"], label: winners[label]},
        "win_rate": {
            "DG1": winners["DG1"] / len(completed_games) if completed_games else 0,
            label: winners[label] / len(completed_games) if completed_games else 0,
        },
        "mean_questions": (sum(game["questions"] for game in completed_games) / len(completed_games)
                           if completed_games else 0),
        "mean_guesses": (sum(game["guesses"] for game in completed_games) / len(completed_games)
                         if completed_games else 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Tournoi DG1 contre un challenger (DG2 ou DG3), avec reprise")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--games", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--pairs", type=int, default=1, help="paires de secrets à calculer pendant cet appel")
    parser.add_argument("--dg1-time-budget", type=float, default=0.25)
    parser.add_argument("--engine", choices=sorted(ENGINES), default="dg2", help="moteur opposé à DG1")
    args = parser.parse_args()
    label = args.engine.upper()
    make_challenger = ENGINES[args.engine]
    def play_pair(secret: Candidate, index: int, *, seed: int, dg1_time_budget_s: float) -> dict:
        return _play_pair(secret, index, seed=seed, dg1_time_budget_s=dg1_time_budget_s,
                          make_challenger=make_challenger, label=label)
    def progress(pair: dict, current: dict) -> None:
        wins = dict(current["wins"])
        for game in pair["games"]:
            wins[game["winner"]] -= 1
        completed = current["completed_games"] - len(pair["games"])
        for game in pair["games"]:
            completed += 1
            wins[game["winner"]] += 1
            starter = "DG1" if game["dg1_starts"] else label
            duration = game.get("duration_s")
            duration_text = f"{duration:.3f} s" if duration is not None else "durée non disponible"
            print(
                f"[{completed}/{current['target_games']}] "
                f"secret {pair['secret']} — {starter} commence — "
                f"{game['winner']} gagne — {duration_text} | "
                f"DG1 {wins['DG1']}/{completed} ({wins['DG1'] / completed:.1%}), "
                f"{label} {wins[label]}/{completed} ({wins[label] / completed:.1%})",
                flush=True,
            )
    print(json.dumps(run_chunk(args.checkpoint, games=args.games, seed=args.seed,
                               dg1_time_budget_s=args.dg1_time_budget, pairs=args.pairs,
                               play_pair=play_pair, on_pair_complete=progress, label=label),
                     ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
