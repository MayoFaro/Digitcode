"""Private-information belief model used by the next DG2 search layer.

Unlike DG1's scalar hit-rate approximation, a world records both the true
public candidate and the opponent's hidden failed proposal.  A policy can
therefore condition its simulated move on information it legally owns while
the player being evaluated only sees the resulting posterior distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class World:
    secret: int
    opponent_failed: int | None


def initial_worlds(public_mask: int, opponent_failures: int) -> tuple[World, ...]:
    """Uniform posterior before any later public answer.

    Only one hidden failure needs representation: a second failure is
    terminal by rule.  The failed code cannot equal the secret.
    """
    candidates = [i for i in range(public_mask.bit_length()) if public_mask & (1 << i)]
    if opponent_failures == 0:
        return tuple(World(secret, None) for secret in candidates)
    if opponent_failures != 1:
        raise ValueError("Un joueur avec deux échecs ne possède pas de croyance non terminale.")
    return tuple(World(secret, failed)
                 for secret in candidates for failed in candidates if failed != secret)


def condition(worlds: Iterable[World], public_mask: int) -> tuple[World, ...]:
    """Apply a public answer; hidden failures remain hidden but may vanish."""
    return tuple(
        World(world.secret, world.opponent_failed if world.opponent_failed is not None
              and public_mask & (1 << world.opponent_failed) else None)
        for world in worlds if public_mask & (1 << world.secret)
    )


def opponent_hit_rate(worlds: Iterable[World], public_mask: int) -> float:
    """Exact next-guess rate under uniform choice from the opponent's pool."""
    worlds = tuple(worlds)
    if not worlds:
        return 0.0
    total = 0.0
    for world in worlds:
        pool = public_mask
        if world.opponent_failed is not None:
            pool &= ~(1 << world.opponent_failed)
        total += 1 / pool.bit_count()
    return total / len(worlds)
