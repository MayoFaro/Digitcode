import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random

import pytest

from digitcode.solver import DigitcodeSolver, Clue


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication for native Qt widget tests. Offscreen
    platform is forced above, before PySide6 is ever imported, so this
    works in a headless CI/dev environment with no X server."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def make_solver(free_positions: dict, tries: int = 500) -> DigitcodeSolver:
    """Builds a DigitcodeSolver whose domains are exactly `free_positions`
    for the given keys (each mapped to a set of >=1 candidate values) and a
    single random fixed value for every other position among T,U,V,W,X,Y.
    Retries with a fixed seed until propagating the identity Clue leaves
    every domain unchanged, so the constructed state is guaranteed valid
    under the real adjacency/max-two rules rather than hand-derived."""
    keys = ["T", "U", "V", "W", "X", "Y"]
    rng = random.Random(0)
    for _ in range(tries):
        domains = {}
        for k in keys:
            if k in free_positions:
                domains[k] = set(free_positions[k])
            else:
                domains[k] = {rng.randint(0, 9)}
        s = DigitcodeSolver()
        s.domains = {k: set(v) for k, v in domains.items()}
        before = {k: set(v) for k, v in domains.items()}
        try:
            s.propagate(Clue())
        except ValueError:
            continue
        if s.domains == before:
            return s
    raise RuntimeError(f"could not build a valid state for {free_positions} in {tries} tries")
