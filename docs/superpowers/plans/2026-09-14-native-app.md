# App native (fenêtre indépendante) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a native (non-browser) PySide6 window that replicates the web solver's behavior exactly, split into 3 switchable panels (tab-style selector) instead of 3 side-by-side web columns, with the solutions-remaining count visible on all 3.

**Architecture:** Extract the current Flask closure's game logic (`web/app.py`'s `state` dict + `current_state_payload()`) into a framework-agnostic `game_state.py` module (a `GameState` class), used by both the (now thin) Flask adapter and the new native app. The native app is a `QMainWindow` holding a `QStackedWidget` of 3 panels; switching panels is a plain `setCurrentIndex` call — no recompute, no network — so it's instant regardless of how long `GameState.payload()` takes to compute the race strategy.

**Tech Stack:** Python 3.10+, PySide6 (Qt 6) for the native UI, pytest for tests (existing Flask/solver stack untouched).

**Spec:** `docs/superpowers/specs/2026-09-14-native-app-design.md`

## Global Constraints

- Python >= 3.10 (existing `pyproject.toml` floor) — no new floor needed.
- PySide6 >= 6.5, added as an **optional** dependency group (`native`), not a hard dependency of the base package — the web app must keep working with no PySide6 installed.
- All UI copy (button labels, headings) is in French, copied verbatim from `web/static/index.html` / `web/static/app.js` where an equivalent exists — no re-wording.
- `tests/test_web.py` must keep passing unmodified after Task 1 — it is the regression guard proving the extraction didn't change web behavior.
- Every native Qt test must run headless: set `QT_QPA_PLATFORM=offscreen` before any `QApplication` is constructed (done once, in `tests/conftest.py`).
- Target platform for "always on top" is Linux/X11 (the dev machine); Qt's `WindowStaysOnTopHint` is cross-platform but only verified on Linux in this plan.

---

## Task 1: Extract `GameState` from `web/app.py`

**Files:**
- Create: `game_state.py` (repo root, alongside `solver.py`/`strategy.py`/`mapping.py`)
- Create: `tests/test_game_state.py`
- Modify: `web/app.py` (becomes a thin Flask adapter over `GameState`)

**Interfaces:**
- Produces: `game_state.GameState` with methods `payload() -> dict`, `apply_clue(clue_type: str, **fields) -> dict` (raises `ValueError`), `apply_clue_with_fallback(clue_type: str, attempts: list[dict]) -> dict` (raises `ValueError`), `guess_failed(body: dict) -> dict` (raises `ValueError`), `undo() -> dict`, `reset() -> dict`. Also re-exports the module-level helpers `_display_domains`, `_existing_comparison`, `clone_clue`, `_child_solver`, `_question_solution_counts` (same signatures as the current `web/app.py` versions).
- Produces: `GameState` instances expose `.clue`, `.history`, `.a_me`, `.a_opp`, `.my_excluded` as plain attributes (used directly by native panels later, e.g. to read `.clue.row_totals`/`.clue.parity`/`.clue.segment_state`/`.clue.comparisons` — though panels mostly read these back out of `payload()`'s dict form instead).

- [ ] **Step 1: Write failing tests for `GameState`**

Create `tests/test_game_state.py`:

```python
import pytest

from digitcode.game_state import GameState


def test_fresh_state_has_full_domains_and_two_attempts_each():
    gs = GameState()
    payload = gs.payload()
    assert set(payload["domains"].keys()) == {"T", "U", "V", "W", "X", "Y"}
    assert all(len(v) == 10 for v in payload["domains"].values())
    assert payload["a_me"] == 2
    assert payload["a_opp"] == 2
    assert "race" in payload and "p_win" in payload["race"]


def test_apply_clue_parity_narrows_domain():
    gs = GameState()
    payload = gs.apply_clue("parity", pos="T", value="Pair")
    assert all(d % 2 == 0 for d in payload["domains"]["T"])


def test_apply_clue_unknown_type_raises():
    gs = GameState()
    with pytest.raises(ValueError, match="unknown clue type"):
        gs.apply_clue("bogus")


def test_apply_clue_missing_field_raises_without_touching_history():
    gs = GameState()
    with pytest.raises(ValueError, match="missing required field"):
        gs.apply_clue("row_total", value=3)
    assert gs.history == []


def test_apply_clue_row_total_non_numeric_value_raises_without_touching_history():
    gs = GameState()
    with pytest.raises(ValueError, match="must be an integer"):
        gs.apply_clue("row_total", row="J", value="abc")
    assert gs.history == []


def test_apply_clue_contradiction_rolls_back_and_does_not_grow_history():
    gs = GameState()
    gs.apply_clue("parity", pos="T", value="Pair")
    gs.apply_clue("segment", pos="T", seg="b", value=False)
    history_len_before = len(gs.history)
    with pytest.raises(ValueError):
        gs.apply_clue("segment", pos="T", seg="a", value=False)
    assert len(gs.history) == history_len_before
    assert gs.payload()["domains"]["T"] == [6]


def test_apply_clue_with_fallback_uses_first_non_contradicting_attempt():
    gs = GameState()
    gs.apply_clue("parity", pos="T", value="Pair")
    gs.apply_clue("segment", pos="T", seg="b", value=False)
    # "a" -> True would contradict T=6's segments; fallback must land on False.
    payload = gs.apply_clue_with_fallback(
        "segment", [{"pos": "T", "seg": "a", "value": True}, {"pos": "T", "seg": "a", "value": False}]
    )
    assert payload["segment_state"]["Ta"] is False


def test_guess_failed_opponent_decrements_a_opp():
    gs = GameState()
    payload = gs.guess_failed({"who": "opponent"})
    assert payload["a_opp"] == 1


def test_guess_failed_me_missing_candidate_raises():
    gs = GameState()
    with pytest.raises(ValueError, match="candidate"):
        gs.guess_failed({"who": "me"})


def test_guess_failed_invalid_who_raises():
    gs = GameState()
    with pytest.raises(ValueError, match="who must be"):
        gs.guess_failed({"who": "nobody"})


def test_undo_restores_previous_clue():
    gs = GameState()
    gs.apply_clue("row_total", row="J", value=3)
    payload = gs.undo()
    assert payload["row_totals"] == {}


def test_reset_clears_everything():
    gs = GameState()
    gs.apply_clue("row_total", row="J", value=3)
    gs.guess_failed({"who": "opponent"})
    payload = gs.reset()
    assert payload["row_totals"] == {}
    assert payload["a_me"] == 2
    assert payload["a_opp"] == 2
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `.venv/bin/pytest tests/test_game_state.py -v`
Expected: every test errors with `ModuleNotFoundError: No module named 'digitcode.game_state'`.

- [ ] **Step 3: Implement `game_state.py`**

Create `game_state.py`:

```python
from __future__ import annotations

from .mapping import POSITIONS, ROW_TOP, ROW_BOTTOM, COLS, row_contributors, col_contributors
from .solver import DigitcodeSolver, Clue
from .strategy import evaluate_race_strategy

# Cap for the per-question solution-count display (how many solutions each
# reachable answer could leave). Must stay a lower bound, never a fabricated
# exact number -- see _question_solution_counts. Independent of strategy.py's
# own fallback_cap: this one is tuned for UI latency on the handful of
# questions actually rendered, not for scoring the full question set.
RANGE_DISPLAY_CAP = 2000
MAX_ALTERNATIVES_WITH_RANGE = 10

_REQUIRED_FIELDS_BY_TYPE = {
    "row_total": ("row",),
    "col_total": ("col",),
    "parity": ("pos",),
    "comparison": ("left", "rel", "right"),
    "segment": ("pos", "seg"),
}


def _display_domains(snap: dict, sols: list, n_solutions_total: int) -> dict:
    """Domains to show in the "Chiffres" panel.

    `snap` (raw per-position propagation) can be strictly wider than what's
    actually reachable: `solver.py`'s `apply_no_equal_adjacent` /
    `apply_max_two` only prune a domain once the OTHER side of the
    constraint is already a singleton, so a value can survive local
    propagation without appearing in any globally valid solution. When the
    candidate list is exhaustive (its count matches `n_solutions_total`, not
    just capped at the display limit), the true per-position possibilities
    are exactly the values observed across those solutions -- free to
    compute, and always correct, unlike `snap`. Falls back to `snap` when
    the list is a truncated view (more solutions exist than are listed):
    observed-but-incomplete values would be too narrow, not too wide, which
    is a worse failure mode than the status quo."""
    if len(sols) != n_solutions_total:
        return snap
    tight = {p: set() for p in POSITIONS}
    for sol in sols:
        for p, v in sol.items():
            tight[p].add(v)
    return {p: sorted(tight[p]) for p in POSITIONS}


def _existing_comparison(comparisons, left, right):
    """Return the stored tuple describing the current relation between
    `left` and `right`, in either storage order, or None if unset."""
    for entry in comparisons:
        a, rel, b = entry
        if (a, b) == (left, right) or (a, b) == (right, left):
            return entry
    return None


def clone_clue(c: Clue) -> Clue:
    nc = Clue()
    nc.row_totals = dict(c.row_totals)
    nc.col_totals = dict(c.col_totals)
    nc.parity = dict(c.parity)
    nc.comparisons = list(c.comparisons)
    nc.segment_state = dict(c.segment_state)
    nc.max_two = c.max_two
    nc.forbid_equal_adjacent = c.forbid_equal_adjacent
    return nc


def _child_solver(base: DigitcodeSolver, clue: Clue):
    child = DigitcodeSolver()
    child.domains = {p: set(v) for p, v in base.domains.items()}
    try:
        child.propagate(clue)
    except ValueError:
        return None
    return child


def _question_solution_counts(solver: DigitcodeSolver, clue: Clue, q: dict, cap: int, excluded: frozenset = frozenset()) -> list[dict]:
    """Sorted, deduplicated list of {"n", "capped"} for every reachable
    answer's resulting solution count. `capped` means the true count was >=
    `cap` but unknown beyond that -- never presented as an exact value."""
    counts: dict[int, bool] = {}
    for out in q["outcomes"]:
        child_clue = solver._apply_answer_to_clue(clue, q, out["answer"], 0)
        child = _child_solver(solver, child_clue)
        if child is None:
            continue
        n = child.count_solutions_capped(child_clue, cap=cap, excluded=excluded)
        if n == 0:
            continue
        counts[n] = counts.get(n, False) or (n >= cap)
    return [{"n": n, "capped": capped} for n, capped in sorted(counts.items())]


class GameState:
    """In-memory, framework-agnostic game state: the current Clue plus the
    race bookkeeping (attempts, excluded candidates, undo history). Shared
    by the Flask web app (web/app.py) and the native Qt app (native/) so
    both stay behaviorally identical -- see
    docs/superpowers/specs/2026-09-14-native-app-design.md.
    """

    def __init__(self) -> None:
        self.clue = Clue()
        self.history: list[Clue] = []
        self.a_me = 2
        self.a_opp = 2
        self.my_excluded: frozenset = frozenset()

    def payload(self) -> dict:
        solver = DigitcodeSolver()
        solver.propagate(self.clue)  # may raise ValueError; callers must catch it
        snap = solver.snapshot()
        n_solutions_total = solver.count_solutions_capped(self.clue, cap=None, excluded=self.my_excluded)
        sols = solver.enumerate_solutions(self.clue, limit=6, excluded=self.my_excluded)
        race = evaluate_race_strategy(
            solver,
            self.clue,
            self.a_me,
            self.a_opp,
            self.my_excluded,
            time_budget_s=1.5,
            n_beam_max=9,
        )
        all_questions_by_label = {
            q["label"]: q for q in solver.enumerate_all_questions(self.clue)
            if len(q["outcomes"]) > 1
        }

        def _annotate(entry: dict) -> None:
            q = all_questions_by_label.get(entry["label"])
            if q is None:
                return
            counts = _question_solution_counts(solver, self.clue, q, RANGE_DISPLAY_CAP, excluded=self.my_excluded)
            if counts:
                entry["solution_counts"] = counts

        if race["best_question"] is not None:
            _annotate(race["best_question"])
        for alt in race["ranked_alternatives"][:MAX_ALTERNATIVES_WITH_RANGE]:
            _annotate(alt)
        return {
            "domains": _display_domains(snap, sols, n_solutions_total),
            "solutions": [solver.solution_to_string(s) for s in sols],
            "n_solutions_total": n_solutions_total,
            "trace": solver.trace,
            "a_me": self.a_me,
            "a_opp": self.a_opp,
            "my_excluded": [f"{c[0]}{c[1]}{c[2]} {c[3]}{c[4]}{c[5]}" for c in self.my_excluded],
            "race": race,
            "row_totals": self.clue.row_totals,
            "col_totals": self.clue.col_totals,
            "parity": self.clue.parity,
            "comparisons": self.clue.comparisons,
            "segment_state": {f"{p}{s}": v for (p, s), v in self.clue.segment_state.items()},
            "reachable_row_sums": {
                row: solver._reachable_sums(row_contributors(row))
                for row in ROW_TOP + ROW_BOTTOM
                if row not in self.clue.row_totals
            },
            "reachable_col_sums": {
                col: solver._reachable_sums(col_contributors(col))
                for col in COLS
                if col not in self.clue.col_totals
            },
        }

    def apply_clue(self, clue_type: str, **fields) -> dict:
        if clue_type not in _REQUIRED_FIELDS_BY_TYPE:
            raise ValueError(f"unknown clue type: {clue_type}")

        missing = [f for f in _REQUIRED_FIELDS_BY_TYPE[clue_type] if f not in fields]
        if missing:
            raise ValueError(f"missing required field(s) for {clue_type}: {', '.join(missing)}")

        # Validate the numeric payload BEFORE touching history: a non-numeric
        # value must be rejected without pushing an undo entry, otherwise the
        # undo stack silently desyncs by one step.
        total_value = None
        if clue_type in ("row_total", "col_total") and fields.get("value") is not None:
            try:
                total_value = int(fields["value"])
            except (TypeError, ValueError):
                raise ValueError(f"value for {clue_type} must be an integer, got: {fields['value']!r}")

        self.history.append(clone_clue(self.clue))
        clue = self.clue
        if clue_type == "row_total":
            if fields.get("value") is None:
                clue.row_totals.pop(fields["row"], None)
            else:
                clue.row_totals[fields["row"]] = total_value
        elif clue_type == "col_total":
            if fields.get("value") is None:
                clue.col_totals.pop(fields["col"], None)
            else:
                clue.col_totals[fields["col"]] = total_value
        elif clue_type == "parity":
            if fields.get("value") is None:
                clue.parity.pop(fields["pos"], None)
            else:
                clue.parity[fields["pos"]] = fields["value"]
        elif clue_type == "comparison":
            left, rel, right = fields["left"], fields["rel"], fields["right"]
            if fields.get("remove"):
                pair = (left, rel, right)
                if pair in clue.comparisons:
                    clue.comparisons.remove(pair)
            else:
                existing = _existing_comparison(clue.comparisons, left, right)
                if existing is not None:
                    clue.comparisons.remove(existing)
                clue.comparisons.append((left, rel, right))
        elif clue_type == "segment":
            key = (fields["pos"], fields["seg"])
            if fields.get("value") is None:
                clue.segment_state.pop(key, None)
            else:
                clue.segment_state[key] = bool(fields["value"])

        try:
            return self.payload()
        except ValueError:
            self.clue = self.history.pop()
            raise

    def apply_clue_with_fallback(self, clue_type: str, attempts: list[dict]) -> dict:
        """Try each fields-dict in `attempts` in order via apply_clue,
        stopping at the first that doesn't raise ValueError. Mirrors the
        web frontend's postClueWithFallback (web/static/app.js): lets a
        single native click land on a valid state instead of getting stuck
        retrying a rejected transition -- if the next state in a click
        cycle contradicts the current board, fall through to the state
        after it. `attempts` must end in a transition that can never be
        rejected (e.g. clearing the clue) so this never exhausts the list.
        """
        last_error: ValueError | None = None
        for fields in attempts:
            try:
                return self.apply_clue(clue_type, **fields)
            except ValueError as e:
                last_error = e
        assert last_error is not None
        raise last_error

    def guess_failed(self, body: dict) -> dict:
        who = body.get("who")
        if who == "opponent":
            if self.a_opp > 0:
                self.a_opp -= 1
        elif who == "me":
            if "candidate" not in body:
                raise ValueError("candidate field required when who='me'")
            if self.a_me > 0:
                self.my_excluded = self.my_excluded | {tuple(body["candidate"])}
                self.a_me -= 1
        else:
            raise ValueError("who must be 'me' or 'opponent'")
        return self.payload()

    def undo(self) -> dict:
        if self.history:
            self.clue = self.history.pop()
        return self.payload()

    def reset(self) -> dict:
        self.clue = Clue()
        self.history = []
        self.a_me = 2
        self.a_opp = 2
        self.my_excluded = frozenset()
        return self.payload()
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_game_state.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Refactor `web/app.py` to delegate to `GameState`**

Replace the full contents of `web/app.py` with:

```python
from __future__ import annotations

from flask import Flask, jsonify, request

# _question_solution_counts and _display_domains are re-exported here (not
# used directly below) because tests/test_web.py imports them from
# digitcode.web.app -- keep that import path working.
from ..game_state import GameState, _question_solution_counts, _display_domains  # noqa: F401


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="")
    game_state = GameState()

    @app.get("/api/state")
    def get_state():
        try:
            return jsonify(game_state.payload())
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/clue")
    def post_clue():
        body = request.get_json(force=True)
        t = body.get("type")
        fields = {k: v for k, v in body.items() if k != "type"}
        try:
            return jsonify(game_state.apply_clue(t, **fields))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/guess-failed")
    def post_guess_failed():
        body = request.get_json(force=True)
        try:
            return jsonify(game_state.guess_failed(body))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/undo")
    def post_undo():
        return jsonify(game_state.undo())

    @app.post("/api/reset")
    def post_reset():
        return jsonify(game_state.reset())

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    return app
```

- [ ] **Step 6: Run the full test suite**

Run: `.venv/bin/pytest -v`
Expected: every test in `tests/test_solver.py`, `tests/test_strategy.py`, `tests/test_web.py`, `tests/test_game_state.py` PASSes. `test_web.py` in particular must show no behavior change.

- [ ] **Step 7: Commit**

```bash
git add game_state.py web/app.py tests/test_game_state.py
git commit -m "$(cat <<'EOF'
refactor: extract GameState from web/app.py into a framework-agnostic module

Pulls the state dict + current_state_payload() logic out of the Flask
closure so the upcoming native app can reuse it without going through
HTTP. web/app.py becomes a thin adapter; behavior is unchanged (test_web.py
passes as-is).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: PySide6 setup and the `MainWindow` shell

**Files:**
- Modify: `pyproject.toml`
- Create: `native/__init__.py`
- Create: `native/__main__.py`
- Create: `native/main_window.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_native_main_window.py`

**Interfaces:**
- Consumes: `game_state.GameState` (Task 1) — `.payload()`, and any of its mutating methods via `MainWindow._run`.
- Produces: `native.main_window.MainWindow(game_state: GameState | None = None)`, a `QMainWindow` with `.game_state`, `.tab_buttons: list[QPushButton]`, `.stack: QStackedWidget`, `.solutions_label: QLabel`, `.error_label: QLabel`, `.panels: list[QWidget]` (empty placeholders in this task, real panels in Task 8), and `._run(fn: Callable[[], dict]) -> None` — later tasks' panels call `self._run(...)` (a callable, not a method they own) to apply a mutation and get re-rendered. Also produces `native.main_window.run() -> None`, the process entry point. Also produces `tests/conftest.py`'s `qapp` pytest fixture (session-scoped `QApplication`), reused by every later native test file.

- [ ] **Step 1: Add the `native` optional dependency and packages to `pyproject.toml`**

Edit `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0"]
native = ["PySide6>=6.5"]

[tool.setuptools]
packages = ["digitcode", "digitcode.web", "digitcode.native", "digitcode.native.panels", "digitcode.native.widgets"]
package-dir = {"digitcode" = "."}
```

- [ ] **Step 2: Install PySide6**

Run: `.venv/bin/pip install -e ".[native,dev]"`
Expected: install succeeds; `.venv/bin/python -c "import PySide6; print(PySide6.__version__)"` prints a version >= 6.5.

- [ ] **Step 3: Add the shared `qapp` fixture to `tests/conftest.py`**

Add to the top of `tests/conftest.py` (keep the existing `make_solver` below it unchanged):

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication for native Qt widget tests. Offscreen
    platform is forced above, before PySide6 is ever imported, so this
    works in a headless CI/dev environment with no X server."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
```

- [ ] **Step 4: Write failing tests for the `MainWindow` shell**

Create `tests/test_native_main_window.py`:

```python
from PySide6.QtCore import Qt

from digitcode.native.main_window import MainWindow, TAB_TITLES


def test_window_is_always_on_top(qapp):
    window = MainWindow()
    assert window.windowFlags() & Qt.WindowStaysOnTopHint


def test_window_has_three_tabs(qapp):
    window = MainWindow()
    assert len(window.tab_buttons) == 3
    assert [b.text() for b in window.tab_buttons] == TAB_TITLES


def test_clicking_a_tab_switches_the_stack_page(qapp):
    window = MainWindow()
    assert window.stack.currentIndex() == 0
    window.tab_buttons[2].click()
    assert window.stack.currentIndex() == 2


def test_solutions_label_reflects_the_fresh_board_count(qapp):
    window = MainWindow()
    expected = window.game_state.payload()["n_solutions_total"]
    assert str(expected) in window.solutions_label.text()


def test_run_on_contradiction_shows_error_and_keeps_previous_render(qapp):
    window = MainWindow()
    window.game_state.apply_clue("parity", pos="T", value="Pair")
    window.game_state.apply_clue("segment", pos="T", seg="b", value=False)
    window._run(window.game_state.payload)
    before = window.solutions_label.text()

    window._run(lambda: window.game_state.apply_clue("segment", pos="T", seg="a", value=False))

    assert window.error_label.isVisible()
    assert window.solutions_label.text() == before
```

- [ ] **Step 5: Run the tests to confirm they fail**

Run: `.venv/bin/pytest tests/test_native_main_window.py -v`
Expected: `ModuleNotFoundError: No module named 'digitcode.native'`.

- [ ] **Step 6: Implement the `native` package skeleton**

Create `native/__init__.py` (empty file).

Create `native/main_window.py`:

```python
from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..game_state import GameState

WINDOW_WIDTH = 380

# Order matches the spec's volet 1/2/3 mapping of the web layout's
# col-sums / col-digits / col-advice blocks.
TAB_TITLES = ["Chiffres", "Comparaisons", "Solutions"]


class MainWindow(QMainWindow):
    def __init__(self, game_state: GameState | None = None) -> None:
        super().__init__()
        self.game_state = game_state or GameState()

        self.setWindowTitle("Digitcode")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setFixedWidth(WINDOW_WIDTH)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.error_label = QLabel()
        self.error_label.setStyleSheet(
            "background: #fdd; color: #900; padding: 4px; border-radius: 4px;"
        )
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        tabs_row = QHBoxLayout()
        self.tab_buttons: list[QPushButton] = []
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for i, title in enumerate(TAB_TITLES):
            btn = QPushButton(title)
            btn.setCheckable(True)
            self.tab_group.addButton(btn, i)
            tabs_row.addWidget(btn)
            self.tab_buttons.append(btn)
        self.tab_buttons[0].setChecked(True)
        self.tab_group.idClicked.connect(self._on_tab_clicked)
        layout.addLayout(tabs_row)

        self.solutions_label = QLabel()
        layout.addWidget(self.solutions_label)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        # Real panels are wired in by Task 8; placeholders keep this shell
        # independently testable in the meantime.
        self.panels: list[QWidget] = []
        for _ in TAB_TITLES:
            self.stack.addWidget(QWidget())

        self._run(self.game_state.payload)

    def _on_tab_clicked(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def _run(self, fn: Callable[[], dict]) -> None:
        """Apply one GameState mutation (or a plain payload() refresh) and
        re-render. Disables the window and forces a repaint first so the
        "busy" state is visible even though the call itself is synchronous
        (see the design spec: race-strategy computation can take up to
        ~1.5s, same budget the web app uses)."""
        self.centralWidget().setEnabled(False)
        QApplication.processEvents()
        try:
            payload = fn()
        except ValueError as e:
            self.error_label.setText("⚠️ " + str(e))
            self.error_label.show()
            self.centralWidget().setEnabled(True)
            return
        self.error_label.hide()
        self.centralWidget().setEnabled(True)
        self._render(payload)

    def _render(self, payload: dict) -> None:
        self.solutions_label.setText(f"Solutions restantes : {payload['n_solutions_total']}")
        for panel in self.panels:
            panel.refresh(payload)


def run() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
```

Create `native/__main__.py`:

```python
from .main_window import run

if __name__ == "__main__":
    run()
```

- [ ] **Step 7: Run the tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_native_main_window.py -v`
Expected: all tests PASS.

- [ ] **Step 8: Manual smoke check**

Run: `.venv/bin/python -m digitcode.native`
Expected: a narrow window titled "Digitcode" appears, stays above other windows, shows 3 tab buttons ("Chiffres" / "Comparaisons" / "Solutions") and a "Solutions restantes : 61440" line (fresh board — confirm the exact number matches what `.venv/bin/python -m digitcode.web` shows on a fresh board for a sanity cross-check, not necessarily this literal figure). Close the window (Ctrl+C in the terminal or the window's close button) when done.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml native/__init__.py native/__main__.py native/main_window.py tests/conftest.py tests/test_native_main_window.py
git commit -m "$(cat <<'EOF'
feat(native): add PySide6 shell window with tab-style panel switching

QMainWindow, always-on-top, narrow, QStackedWidget with 3 placeholder
pages driven by a tab bar -- switching is a plain setCurrentIndex, no
recompute. Real panel content lands in later commits.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `ChipButton` widget

**Files:**
- Create: `native/widgets/__init__.py`
- Create: `native/widgets/chip_button.py`
- Create: `tests/test_native_chip_button.py`

**Interfaces:**
- Produces: `native.widgets.chip_button.ChipButton(text: str, selected: bool = False, is_set: bool = False, parent=None)`, a `QPushButton` subclass with `.set_state(selected: bool = False, is_set: bool = False) -> None`. No cycling logic of its own — callers (the panels, Tasks 6-7) decide what a click means, same separation as the web's `makeChip` helper in `web/static/app.js`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_native_chip_button.py`:

```python
from digitcode.native.widgets.chip_button import ChipButton


def test_chip_button_shows_its_text(qapp):
    chip = ChipButton("T=6")
    assert chip.text() == "T=6"


def test_chip_button_click_calls_handler(qapp):
    chip = ChipButton("T=6")
    calls = []
    chip.clicked.connect(lambda: calls.append(True))
    chip.click()
    assert calls == [True]


def test_selected_style_differs_from_default(qapp):
    default_chip = ChipButton("A")
    selected_chip = ChipButton("A", selected=True)
    assert default_chip.styleSheet() != selected_chip.styleSheet()


def test_set_state_updates_the_style(qapp):
    chip = ChipButton("A")
    plain_style = chip.styleSheet()
    chip.set_state(selected=True)
    assert chip.styleSheet() != plain_style
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `.venv/bin/pytest tests/test_native_chip_button.py -v`
Expected: `ModuleNotFoundError: No module named 'digitcode.native.widgets'`.

- [ ] **Step 3: Implement `ChipButton`**

Create `native/widgets/__init__.py` (empty file).

Create `native/widgets/chip_button.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QPushButton


class ChipButton(QPushButton):
    """A small pill-shaped clickable button reflecting two independent
    flags: `selected` (the option currently in effect, e.g. a picked
    parity or comparison relation) and `is_set` (a value already stored on
    the board, e.g. a fixed row/col total). Mirrors the web frontend's
    `.chip` / `.chip-selected` / `.chip-set` classes
    (web/static/style.css) -- pure display, no cycling logic of its own.
    """

    _BASE_STYLE = (
        "QPushButton {"
        " border: 1px solid #bbb; border-radius: 12px; padding: 3px 9px;"
        " background: #fff; color: #333; }"
        "QPushButton:hover { border-color: #888; }"
    )
    _SET_STYLE = "QPushButton { background: #dde9ff; border-color: #7fa8e8; font-weight: bold; }"
    _SELECTED_STYLE = "QPushButton { background: #333; color: #fff; border-color: #333; }"

    def __init__(self, text: str, selected: bool = False, is_set: bool = False, parent=None) -> None:
        super().__init__(text, parent)
        self.set_state(selected=selected, is_set=is_set)

    def set_state(self, selected: bool = False, is_set: bool = False) -> None:
        style = self._BASE_STYLE
        if is_set:
            style += self._SET_STYLE
        if selected:
            style += self._SELECTED_STYLE
        self.setStyleSheet(style)
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_native_chip_button.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/widgets/__init__.py native/widgets/chip_button.py tests/test_native_chip_button.py
git commit -m "$(cat <<'EOF'
feat(native): add ChipButton, the native equivalent of the web's chips

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `SegmentDigit` widget

**Files:**
- Create: `native/widgets/segment_digit.py`
- Create: `tests/test_native_segment_digit.py`

**Interfaces:**
- Produces: `native.widgets.segment_digit.SegmentDigit(pos: str, parent=None)`, a `QWidget` with `.set_segment_state(state: dict[str, bool | None]) -> None` and a Qt signal `segment_clicked(seg: str, current: object)` (fires on click with the segment letter and its value *before* the click, so the panel decides the transition — same separation as `ChipButton`). Also produces `native.widgets.segment_digit.SEGMENTS = ["a","b","c","d","e","f","g"]`, reused by `ComparaisonsPanel` (Task 7).
- Consumes: nothing beyond PySide6.

- [ ] **Step 1: Write failing tests**

Create `tests/test_native_segment_digit.py`:

```python
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from digitcode.native.widgets.segment_digit import SegmentDigit


def _click_at(widget, x, y):
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(event)


def test_click_inside_segment_a_emits_its_letter_and_current_value(qapp):
    widget = SegmentDigit("T")
    received = []
    widget.segment_clicked.connect(lambda seg, current: received.append((seg, current)))
    _click_at(widget, 60, 16)  # (30, 8) in the 60x100 grid, scaled x2 -- inside segment "a"
    assert received == [("a", None)]


def test_click_outside_every_segment_emits_nothing(qapp):
    widget = SegmentDigit("T")
    received = []
    widget.segment_clicked.connect(lambda seg, current: received.append((seg, current)))
    _click_at(widget, 1, 1)  # top-left corner, outside every polygon
    assert received == []


def test_set_segment_state_is_reported_on_the_next_click(qapp):
    widget = SegmentDigit("T")
    widget.set_segment_state({"a": True})
    received = []
    widget.segment_clicked.connect(lambda seg, current: received.append((seg, current)))
    _click_at(widget, 60, 16)
    assert received == [("a", True)]
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `.venv/bin/pytest tests/test_native_segment_digit.py -v`
Expected: `ModuleNotFoundError: No module named 'digitcode.native.widgets.segment_digit'`.

- [ ] **Step 3: Implement `SegmentDigit`**

Create `native/widgets/segment_digit.py`:

```python
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

SEGMENTS = ["a", "b", "c", "d", "e", "f", "g"]

# Trapezoid outlines for each of the 7 segments on a 0..60 x 0..100 grid --
# same coordinates as web/static/app.js's SEGMENT_POINTS, so the shape
# matches the web version exactly. A recognizable seven-segment digit,
# not a pixel-perfect replica of the real game's glyph.
_SEGMENT_POINTS = {
    "a": [(16, 4), (44, 4), (40, 12), (20, 12)],
    "f": [(8, 12), (16, 16), (16, 46), (8, 50)],
    "b": [(52, 12), (44, 16), (44, 46), (52, 50)],
    "g": [(16, 46), (40, 46), (44, 50), (40, 54), (16, 54), (12, 50)],
    "e": [(8, 52), (16, 56), (16, 86), (8, 90)],
    "c": [(52, 52), (44, 56), (44, 86), (52, 90)],
    "d": [(20, 88), (40, 88), (44, 96), (16, 96)],
}

_SCALE = 2.0
_GRID_WIDTH = 60
_GRID_HEIGHT = 100

_COLOR_ON = QColor("#333333")
_COLOR_OFF_HATCH = QColor("#cc6666")
_COLOR_UNKNOWN = QColor(0, 0, 0, 0)
_STROKE = QColor("#999999")
_STROKE_HOVER = QColor("#333333")


class SegmentDigit(QWidget):
    """A clickable seven-segment digit for one board position, cycling
    each segment through on / off / unknown on click -- the native
    equivalent of buildDigitSvg in web/static/app.js. Emits
    `segment_clicked(seg, current)` and leaves the actual GameState
    transition (with its fallback retries) to the owning panel, same
    separation as ChipButton.
    """

    segment_clicked = Signal(str, object)  # (segment, current value: True/False/None)

    def __init__(self, pos: str, parent=None) -> None:
        super().__init__(parent)
        self.pos = pos
        self._segment_state: dict[str, bool | None] = {s: None for s in SEGMENTS}
        self._paths: dict[str, QPainterPath] = {}
        self._hovered: str | None = None
        self.setFixedSize(int(_GRID_WIDTH * _SCALE), int(_GRID_HEIGHT * _SCALE))
        self.setMouseTracking(True)
        self._build_paths()

    def _build_paths(self) -> None:
        for seg, points in _SEGMENT_POINTS.items():
            polygon = QPolygonF([QPointF(x * _SCALE, y * _SCALE) for x, y in points])
            path = QPainterPath()
            path.addPolygon(polygon)
            path.closeSubpath()
            self._paths[seg] = path

    def set_segment_state(self, state: dict[str, bool | None]) -> None:
        """`state` maps segment letter -> True/False/None (unknown)."""
        self._segment_state = dict(state)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for seg, path in self._paths.items():
            current = self._segment_state.get(seg)
            if current is True:
                brush = QBrush(_COLOR_ON)
            elif current is False:
                brush = QBrush(_COLOR_OFF_HATCH, Qt.BDiagPattern)
            else:
                brush = QBrush(_COLOR_UNKNOWN)
            painter.setBrush(brush)
            pen = QPen(_STROKE_HOVER if seg == self._hovered else _STROKE)
            pen.setWidthF(1.5 if seg == self._hovered else 1.0)
            painter.setPen(pen)
            painter.drawPath(path)

    def _segment_at(self, pos: QPointF) -> str | None:
        for seg, path in self._paths.items():
            if path.contains(pos):
                return seg
        return None

    def mouseMoveEvent(self, event) -> None:
        seg = self._segment_at(event.position())
        if seg != self._hovered:
            self._hovered = seg
            self.update()

    def mousePressEvent(self, event) -> None:
        seg = self._segment_at(event.position())
        if seg is not None:
            self.segment_clicked.emit(seg, self._segment_state.get(seg))
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_native_segment_digit.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/widgets/segment_digit.py tests/test_native_segment_digit.py
git commit -m "$(cat <<'EOF'
feat(native): add SegmentDigit, a painted 7-segment click target

Same polygon coordinates as web/static/app.js's buildDigitSvg, hit-tested
with QPainterPath.contains() instead of SVG click events.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `SolutionsPanel` (volet 3)

**Files:**
- Create: `native/panels/__init__.py`
- Create: `native/panels/solutions_panel.py`
- Create: `tests/test_native_solutions_panel.py`

**Interfaces:**
- Consumes: `game_state.GameState` (Task 1); `run: Callable[[Callable[[], dict]], None]` (the `MainWindow._run` from Task 2, or an equivalent test double).
- Produces: `native.panels.solutions_panel.SolutionsPanel(game_state: GameState, run: Callable, parent=None)` with `.refresh(payload: dict) -> None`, matching the contract every panel must expose for `MainWindow._render` (Task 2 Step 6) to call generically.

- [ ] **Step 1: Write failing tests**

Create `tests/test_native_solutions_panel.py`:

```python
from digitcode.game_state import GameState
from digitcode.native.panels.solutions_panel import SolutionsPanel


def _n4_game_state() -> GameState:
    # Same fixture as tests/test_web.py's _n4_clue_client: narrows the
    # board to a fixed N=4 so the solutions list is short enough to render
    # inline and the combo box is easy to assert on.
    gs = GameState()
    for row, val in (("K", 6), ("S", 1)):
        gs.apply_clue("row_total", row=row, value=val)
    for col, val in (("H", 3), ("C", 3), ("E", 1)):
        gs.apply_clue("col_total", col=col, value=val)
    for pos, par in (("T", "Pair"), ("W", "Pair"), ("Y", "Pair"), ("X", "Impair")):
        gs.apply_clue("parity", pos=pos, value=par)
    return gs


def test_refresh_lists_all_solutions_when_total_is_small(qapp):
    gs = _n4_game_state()
    payload = gs.payload()
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(payload)
    assert panel.my_miss_combo.count() == 4
    assert panel.solutions_list_label.text() == "; ".join(payload["solutions"])


def test_undo_button_calls_game_state_undo(qapp):
    gs = _n4_game_state()
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    history_len_before = len(gs.history)
    panel.undo_btn.click()
    assert len(gs.history) == history_len_before - 1


def test_opp_miss_button_decrements_a_opp(qapp):
    gs = GameState()
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    panel.opp_miss_btn.click()
    assert gs.a_opp == 1


def test_my_miss_button_excludes_the_selected_candidate(qapp):
    gs = _n4_game_state()
    payload = gs.payload()
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(payload)
    panel.my_miss_combo.setCurrentIndex(0)
    panel.my_miss_btn.click()
    assert gs.a_me == 1
    assert len(gs.my_excluded) == 1


def test_refresh_shows_the_attempts_counts(qapp):
    gs = GameState()
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    assert "2" in panel.a_me_label.text()
    assert "2" in panel.a_opp_label.text()
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `.venv/bin/pytest tests/test_native_solutions_panel.py -v`
Expected: `ModuleNotFoundError: No module named 'digitcode.native.panels'`.

- [ ] **Step 3: Implement `SolutionsPanel`**

Create `native/panels/__init__.py` (empty file).

Create `native/panels/solutions_panel.py`:

```python
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...game_state import GameState

# Below the threshold, every distinct reachable solution count is listed
# exactly -- that's precisely the zone where it matters whether a question
# can leave 2-4 solutions versus jumping straight to 1. Mirrors
# web/static/app.js's SOLUTION_COUNT_EXACT_THRESHOLD.
SOLUTION_COUNT_EXACT_THRESHOLD = 4
MAX_ALTERNATIVES_SHOWN = 10


def _format_solution_counts(entry: dict) -> str:
    counts = entry.get("solution_counts")
    if not counts:
        return "?"
    small = [c["n"] for c in counts if c["n"] <= SOLUTION_COUNT_EXACT_THRESHOLD]
    has_large = any(c["n"] > SOLUTION_COUNT_EXACT_THRESHOLD for c in counts)
    parts = [str(n) for n in small]
    if has_large:
        parts.append(f">{SOLUTION_COUNT_EXACT_THRESHOLD}")
    if len(parts) == 1:
        singular = len(small) == 1 and small[0] == 1
        return f"{parts[0]} solution" + ("" if singular else "s")
    return f"{', '.join(parts[:-1])} ou {parts[-1]} solutions"


def _format_question_label(entry: dict) -> str:
    prefix = ""
    if entry.get("near_finish"):
        prefix += "\U0001f534 "  # mirrors the web's red .near-finish styling
    if entry.get("lookahead_risk"):
        prefix += "⚠️ "  # mirrors the web's amber .lookahead-risk styling
    return f"{prefix}{entry['label']} — {_format_solution_counts(entry)}"


class SolutionsPanel(QWidget):
    """Volet 3: solutions restantes, recommandation, essais, historique --
    the web layout's col-advice block."""

    def __init__(self, game_state: GameState, run: Callable[[Callable[[], dict]], None], parent=None) -> None:
        super().__init__(parent)
        self.game_state = game_state
        self._run = run
        self._solutions: list[str] = []
        layout = QVBoxLayout(self)

        self.solutions_list_label = QLabel()
        self.solutions_list_label.setWordWrap(True)
        layout.addWidget(self.solutions_list_label)

        self.p_win_label = QLabel()
        layout.addWidget(self.p_win_label)
        self.best_question_label = QLabel()
        self.best_question_label.setWordWrap(True)
        layout.addWidget(self.best_question_label)
        self.guess_now_label = QLabel()
        layout.addWidget(self.guess_now_label)

        layout.addWidget(QLabel("Alternatives"))
        self.alternatives_list = QListWidget()
        self.alternatives_list.setMaximumHeight(120)
        layout.addWidget(self.alternatives_list)

        attempts_row = QHBoxLayout()
        self.a_me_label = QLabel()
        attempts_row.addWidget(self.a_me_label)
        self.a_opp_label = QLabel()
        attempts_row.addWidget(self.a_opp_label)
        self.opp_miss_btn = QPushButton("il a raté")
        self.opp_miss_btn.clicked.connect(
            lambda: self._run(lambda: self.game_state.guess_failed({"who": "opponent"}))
        )
        attempts_row.addWidget(self.opp_miss_btn)
        layout.addLayout(attempts_row)

        my_miss_row = QHBoxLayout()
        self.my_miss_combo = QComboBox()
        my_miss_row.addWidget(self.my_miss_combo)
        self.my_miss_btn = QPushButton("j'ai tenté celle-ci, raté")
        self.my_miss_btn.clicked.connect(self._on_my_miss)
        my_miss_row.addWidget(self.my_miss_btn)
        layout.addLayout(my_miss_row)

        layout.addWidget(QLabel("Historique"))
        self.trace_view = QPlainTextEdit()
        self.trace_view.setReadOnly(True)
        self.trace_view.setMaximumHeight(120)
        layout.addWidget(self.trace_view)

        buttons_row = QHBoxLayout()
        self.undo_btn = QPushButton("Annuler (undo)")
        self.undo_btn.clicked.connect(lambda: self._run(self.game_state.undo))
        buttons_row.addWidget(self.undo_btn)
        self.reset_btn = QPushButton("Réinitialiser")
        self.reset_btn.clicked.connect(lambda: self._run(self.game_state.reset))
        buttons_row.addWidget(self.reset_btn)
        layout.addLayout(buttons_row)

    def _on_my_miss(self) -> None:
        index = self.my_miss_combo.currentIndex()
        if index < 0 or index >= len(self._solutions):
            return
        sol = self._solutions[index]
        digits = [int(c) for c in sol.replace(" ", "")]
        self._run(lambda: self.game_state.guess_failed({"who": "me", "candidate": digits}))

    def refresh(self, payload: dict) -> None:
        self._solutions = payload["solutions"]

        n_total = payload["n_solutions_total"]
        self.solutions_list_label.setText(
            "; ".join(self._solutions) if n_total <= 6 else f"{n_total} solutions possibles"
        )

        race = payload["race"]
        race_aware = race.get("race_aware", race["exact"])
        label = "P(je gagne)" if race_aware else "Qualité de réduction"
        tag = "(exact)" if race["exact"] else ("(estimation course)" if race_aware else "(estimation)")
        self.p_win_label.setText(f"{label} = {race['p_win'] * 100:.1f}% {tag}")

        best = race.get("best_question")
        self.best_question_label.setText(
            "Meilleure question : " + (_format_question_label(best) if best else "(aucune)")
        )
        self.guess_now_label.setText(
            "OUI — proposez une solution !" if race["guess_now"] else "Non, attendez."
        )

        self.alternatives_list.clear()
        for alt in race["ranked_alternatives"][:MAX_ALTERNATIVES_SHOWN]:
            self.alternatives_list.addItem(_format_question_label(alt))

        self.a_me_label.setText(f"Moi : {payload['a_me']}/2")
        self.a_opp_label.setText(f"Adversaire : {payload['a_opp']}/2")

        self.my_miss_combo.clear()
        self.my_miss_combo.addItems(self._solutions)

        self.trace_view.setPlainText("\n".join(payload["trace"]))
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_native_solutions_panel.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/panels/__init__.py native/panels/solutions_panel.py tests/test_native_solutions_panel.py
git commit -m "$(cat <<'EOF'
feat(native): add SolutionsPanel (volet 3 -- conseils/solutions)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `ChiffresPanel` (volet 1)

**Files:**
- Create: `native/panels/chiffres_panel.py`
- Create: `tests/test_native_chiffres_panel.py`

**Interfaces:**
- Consumes: `GameState` (Task 1), `ChipButton` (Task 3), `run` callback (same contract as Task 5).
- Produces: `native.panels.chiffres_panel.ChiffresPanel(game_state: GameState, run: Callable, parent=None)` with `.refresh(payload: dict) -> None`, `.domain_labels: dict[str, QLabel]` (keyed by position), `._select_row_letter(letter: str) -> None` / `._select_col_letter(letter: str) -> None` (local UI-only state, not sent to GameState -- mirrors `web/static/app.js`'s `selectedRowLetter`/`selectedColLetter`).

- [ ] **Step 1: Write failing tests**

Create `tests/test_native_chiffres_panel.py`:

```python
from digitcode.game_state import GameState
from digitcode.native.panels.chiffres_panel import ChiffresPanel


def test_refresh_shows_full_domains_on_a_fresh_board(qapp):
    gs = GameState()
    panel = ChiffresPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    assert "0" in panel.domain_labels["T"].text()
    assert "9" in panel.domain_labels["T"].text()


def test_selecting_a_row_letter_then_a_value_sets_the_row_total(qapp):
    gs = GameState()
    panel = ChiffresPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())

    panel._select_row_letter("J")
    reachable = gs.payload()["reachable_row_sums"]["J"]
    target = reachable[0]
    panel._run(lambda: gs.apply_clue("row_total", row="J", value=target))

    assert gs.clue.row_totals["J"] == target


def test_selecting_a_different_letter_does_not_mutate_game_state(qapp):
    gs = GameState()
    panel = ChiffresPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    panel._select_row_letter("K")
    assert gs.clue.row_totals == {}
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `.venv/bin/pytest tests/test_native_chiffres_panel.py -v`
Expected: `ModuleNotFoundError: No module named 'digitcode.native.panels.chiffres_panel'`.

- [ ] **Step 3: Implement `ChiffresPanel`**

Create `native/panels/chiffres_panel.py`:

```python
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...game_state import GameState
from ...mapping import COLS, POSITIONS, ROW_BOTTOM, ROW_TOP
from ..widgets.chip_button import ChipButton

ROW_LETTERS = ROW_TOP + ROW_BOTTOM
COL_LETTERS = COLS


class ChiffresPanel(QWidget):
    """Volet 1: Chiffres (domaines), Sommes ligne, Sommes colonne -- the
    web layout's col-sums block."""

    def __init__(self, game_state: GameState, run: Callable[[Callable[[], dict]], None], parent=None) -> None:
        super().__init__(parent)
        self.game_state = game_state
        self._run = run
        self._selected_row_letter: str | None = None
        self._selected_col_letter: str | None = None
        self._last_payload: dict | None = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Chiffres"))
        self.domains_grid = QGridLayout()
        layout.addLayout(self.domains_grid)
        self.domain_labels: dict[str, QLabel] = {}
        for i, pos in enumerate(POSITIONS):
            label = QLabel()
            self.domain_labels[pos] = label
            self.domains_grid.addWidget(label, i // 3, i % 3)

        layout.addWidget(QLabel("Sommes ligne"))
        self.row_letters_row = QHBoxLayout()
        layout.addLayout(self.row_letters_row)
        self.row_values_row = QHBoxLayout()
        layout.addLayout(self.row_values_row)

        layout.addWidget(QLabel("Sommes colonne"))
        self.col_letters_row = QHBoxLayout()
        layout.addLayout(self.col_letters_row)
        self.col_values_row = QHBoxLayout()
        layout.addLayout(self.col_values_row)

        layout.addStretch(1)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_letters(self, layout, letters, totals, selected, on_select) -> None:
        self._clear_layout(layout)
        for letter in letters:
            value = totals.get(letter)
            text = f"{letter}={value}" if value is not None else letter
            chip = ChipButton(text, selected=(letter == selected), is_set=(value is not None))
            chip.clicked.connect(lambda _checked=False, l=letter: on_select(l))
            layout.addWidget(chip)

    def _render_values(self, layout, letter, totals, reachable, clue_type, field_name) -> None:
        self._clear_layout(layout)
        if letter is None:
            layout.addWidget(QLabel("— choisissez une lettre ci-dessus —"))
            return
        current = totals.get(letter)
        options = [current] if current is not None else reachable.get(letter, [])
        for value in options:
            chip = ChipButton(str(value), selected=(value == current))
            chip.clicked.connect(
                lambda _checked=False, v=value: self._run(
                    lambda: self.game_state.apply_clue(clue_type, **{field_name: letter, "value": v})
                )
            )
            layout.addWidget(chip)
        raz = ChipButton("RAZ")
        raz.clicked.connect(
            lambda _checked=False: self._run(
                lambda: self.game_state.apply_clue(clue_type, **{field_name: letter, "value": None})
            )
        )
        layout.addWidget(raz)

    def _select_row_letter(self, letter: str) -> None:
        self._selected_row_letter = letter
        if self._last_payload is not None:
            self.refresh(self._last_payload)

    def _select_col_letter(self, letter: str) -> None:
        self._selected_col_letter = letter
        if self._last_payload is not None:
            self.refresh(self._last_payload)

    def refresh(self, payload: dict) -> None:
        self._last_payload = payload
        for pos in POSITIONS:
            values = ",".join(str(v) for v in payload["domains"][pos])
            self.domain_labels[pos].setText(f"<b>{pos}</b><br>{{{values}}}")

        self._render_letters(
            self.row_letters_row, ROW_LETTERS, payload["row_totals"], self._selected_row_letter,
            self._select_row_letter,
        )
        self._render_values(
            self.row_values_row, self._selected_row_letter, payload["row_totals"],
            payload["reachable_row_sums"], "row_total", "row",
        )

        self._render_letters(
            self.col_letters_row, COL_LETTERS, payload["col_totals"], self._selected_col_letter,
            self._select_col_letter,
        )
        self._render_values(
            self.col_values_row, self._selected_col_letter, payload["col_totals"],
            payload["reachable_col_sums"], "col_total", "col",
        )
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_native_chiffres_panel.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/panels/chiffres_panel.py tests/test_native_chiffres_panel.py
git commit -m "$(cat <<'EOF'
feat(native): add ChiffresPanel (volet 1 -- chiffres et sommes)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `ComparaisonsPanel` (volet 2)

**Files:**
- Create: `native/panels/comparaisons_panel.py`
- Create: `tests/test_native_comparaisons_panel.py`

**Interfaces:**
- Consumes: `GameState` (Task 1), `ChipButton` (Task 3), `SegmentDigit` + `SEGMENTS` (Task 4), `run` callback (same contract as Task 5).
- Produces: `native.panels.comparaisons_panel.ComparaisonsPanel(game_state: GameState, run: Callable, parent=None)` with `.refresh(payload: dict) -> None`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_native_comparaisons_panel.py`:

```python
from digitcode.game_state import GameState
from digitcode.native.panels.comparaisons_panel import ComparaisonsPanel


def test_refresh_reflects_an_existing_comparison(qapp):
    gs = GameState()
    gs.apply_clue("comparison", left="T", rel=">", right="U")
    panel = ComparaisonsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    lt_chip, gt_chip = panel.cmp_chip_pairs[("T", "U")]
    assert gt_chip.styleSheet() != lt_chip.styleSheet()


def test_clicking_a_comparison_chip_sets_the_relation(qapp):
    gs = GameState()
    panel = ComparaisonsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    panel._on_comparison_clicked("T", "U", ">")
    assert ("T", ">", "U") in gs.clue.comparisons


def test_clicking_the_same_comparison_chip_again_clears_it(qapp):
    gs = GameState()
    panel = ComparaisonsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    panel._on_comparison_clicked("T", "U", ">")
    panel.refresh(gs.payload())
    panel._on_comparison_clicked("T", "U", ">")
    assert gs.clue.comparisons == []


def test_clicking_a_parity_chip_cycles_through_pair_impair_unset(qapp):
    gs = GameState()
    panel = ComparaisonsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())

    panel._on_parity_clicked("T")
    assert gs.clue.parity["T"] == "Pair"

    panel.refresh(gs.payload())
    panel._on_parity_clicked("T")
    assert gs.clue.parity["T"] == "Impair"

    panel.refresh(gs.payload())
    panel._on_parity_clicked("T")
    assert "T" not in gs.clue.parity


def test_clicking_a_segment_cycles_through_on_off_unset(qapp):
    gs = GameState()
    panel = ComparaisonsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())

    panel._on_segment_clicked("T", "a", None)
    assert gs.clue.segment_state[("T", "a")] is True

    panel.refresh(gs.payload())
    panel._on_segment_clicked("T", "a", True)
    assert gs.clue.segment_state[("T", "a")] is False

    panel.refresh(gs.payload())
    panel._on_segment_clicked("T", "a", False)
    assert ("T", "a") not in gs.clue.segment_state
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `.venv/bin/pytest tests/test_native_comparaisons_panel.py -v`
Expected: `ModuleNotFoundError: No module named 'digitcode.native.panels.comparaisons_panel'`.

- [ ] **Step 3: Implement `ComparaisonsPanel`**

Create `native/panels/comparaisons_panel.py`:

```python
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...game_state import GameState
from ...mapping import POSITIONS
from ..widgets.chip_button import ChipButton
from ..widgets.segment_digit import SEGMENTS, SegmentDigit


def _current_relation(comparisons, left, right):
    for a, rel, b in comparisons:
        if a == left and b == right:
            return rel
        if a == right and b == left:
            return ">" if rel == "<" else "<"
    return None


def _find_stored_comparison(comparisons, left, right):
    for entry in comparisons:
        a, _, b = entry
        if (a == left and b == right) or (a == right and b == left):
            return entry
    return None


def _parity_label(current):
    if current == "Pair":
        return "P"
    if current == "Impair":
        return "I"
    return "?"


class ComparaisonsPanel(QWidget):
    """Volet 2: Comparaisons, Parité & segments -- the web layout's
    col-digits block."""

    def __init__(self, game_state: GameState, run: Callable[[Callable[[], dict]], None], parent=None) -> None:
        super().__init__(parent)
        self.game_state = game_state
        self._run = run
        self._last_payload: dict | None = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Comparaisons"))
        self.cmp_grid = QGridLayout()
        layout.addLayout(self.cmp_grid)
        self.cmp_chip_pairs: dict[tuple[str, str], tuple[ChipButton, ChipButton]] = {}
        self._build_comparison_grid()

        layout.addWidget(QLabel("Parité & segments"))
        self.pos_grid = QGridLayout()
        layout.addLayout(self.pos_grid)
        self.segment_widgets: dict[str, SegmentDigit] = {}
        self.parity_chips: dict[str, ChipButton] = {}
        positions_layout = [("T", 0, 0), ("U", 0, 1), ("V", 0, 2), ("W", 1, 0), ("X", 1, 1), ("Y", 1, 2)]
        for pos, row, col in positions_layout:
            cell = QVBoxLayout()
            cell.addWidget(QLabel(f"<b>{pos}</b>"))
            digit = SegmentDigit(pos)
            digit.segment_clicked.connect(
                lambda seg, current, p=pos: self._on_segment_clicked(p, seg, current)
            )
            self.segment_widgets[pos] = digit
            cell.addWidget(digit)
            chip = ChipButton("?")
            chip.clicked.connect(lambda _checked=False, p=pos: self._on_parity_clicked(p))
            self.parity_chips[pos] = chip
            cell.addWidget(chip)
            wrapper = QWidget()
            wrapper.setLayout(cell)
            self.pos_grid.addWidget(wrapper, row, col)

        layout.addStretch(1)

    def _build_comparison_grid(self) -> None:
        def letter_label(pos, row, col):
            self.cmp_grid.addWidget(QLabel(f"<b>{pos}</b>"), row, col)

        def connector(left, right, row, col):
            lt_chip = ChipButton("<")
            gt_chip = ChipButton(">")
            lt_chip.clicked.connect(lambda: self._on_comparison_clicked(left, right, "<"))
            gt_chip.clicked.connect(lambda: self._on_comparison_clicked(left, right, ">"))
            pair_row = QHBoxLayout()
            pair_row.addWidget(lt_chip)
            pair_row.addWidget(gt_chip)
            wrapper = QWidget()
            wrapper.setLayout(pair_row)
            self.cmp_grid.addWidget(wrapper, row, col)
            self.cmp_chip_pairs[(left, right)] = (lt_chip, gt_chip)

        letter_label("T", 0, 0)
        connector("T", "U", 0, 1)
        letter_label("U", 0, 2)
        connector("U", "V", 0, 3)
        letter_label("V", 0, 4)

        connector("T", "W", 1, 0)
        connector("U", "X", 1, 2)
        connector("V", "Y", 1, 4)

        letter_label("W", 2, 0)
        connector("W", "X", 2, 1)
        letter_label("X", 2, 2)
        connector("X", "Y", 2, 3)
        letter_label("Y", 2, 4)

    def _on_comparison_clicked(self, left: str, right: str, want: str) -> None:
        rel = _current_relation(self._last_payload["comparisons"], left, right)
        if rel == want:
            stored = _find_stored_comparison(self._last_payload["comparisons"], left, right)
            self._run(lambda: self.game_state.apply_clue(
                "comparison", left=stored[0], rel=stored[1], right=stored[2], remove=True,
            ))
        else:
            self._run(lambda: self.game_state.apply_clue("comparison", left=left, rel=want, right=right))

    def _on_parity_clicked(self, pos: str) -> None:
        current = self._last_payload["parity"].get(pos)
        if current is None:
            attempts = [{"pos": pos, "value": "Pair"}, {"pos": pos, "value": "Impair"}]
        elif current == "Pair":
            attempts = [{"pos": pos, "value": "Impair"}, {"pos": pos, "value": None}]
        else:
            attempts = [{"pos": pos, "value": None}]
        self._run(lambda: self.game_state.apply_clue_with_fallback("parity", attempts))

    def _on_segment_clicked(self, pos: str, seg: str, current) -> None:
        if current is None:
            attempts = [{"pos": pos, "seg": seg, "value": True}, {"pos": pos, "seg": seg, "value": False}]
        elif current is True:
            attempts = [{"pos": pos, "seg": seg, "value": False}, {"pos": pos, "seg": seg, "value": None}]
        else:
            attempts = [{"pos": pos, "seg": seg, "value": None}]
        self._run(lambda: self.game_state.apply_clue_with_fallback("segment", attempts))

    def refresh(self, payload: dict) -> None:
        self._last_payload = payload

        for (left, right), (lt_chip, gt_chip) in self.cmp_chip_pairs.items():
            rel = _current_relation(payload["comparisons"], left, right)
            lt_chip.set_state(selected=(rel == "<"))
            gt_chip.set_state(selected=(rel == ">"))

        for pos in POSITIONS:
            segment_state = {seg: payload["segment_state"].get(f"{pos}{seg}") for seg in SEGMENTS}
            self.segment_widgets[pos].set_segment_state(segment_state)
            self.parity_chips[pos].setText(_parity_label(payload["parity"].get(pos)))
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_native_comparaisons_panel.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/panels/comparaisons_panel.py tests/test_native_comparaisons_panel.py
git commit -m "$(cat <<'EOF'
feat(native): add ComparaisonsPanel (volet 2 -- comparaisons et parité/segments)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Wire the panels into `MainWindow` and verify end-to-end

**Files:**
- Modify: `native/main_window.py`
- Create: `tests/test_native_integration.py`

**Interfaces:**
- Consumes: `ChiffresPanel`, `ComparaisonsPanel`, `SolutionsPanel` (Tasks 5-7), each exposing `.refresh(payload: dict) -> None`.
- Produces: a fully wired `MainWindow` where `.panels == [chiffres_panel, comparaisons_panel, solutions_panel]`, one per stack page, in tab order.

- [ ] **Step 1: Write a failing integration test**

Create `tests/test_native_integration.py`:

```python
from digitcode.native.main_window import MainWindow


def test_setting_a_row_total_from_the_chiffres_panel_updates_every_panel(qapp):
    window = MainWindow()
    chiffres, comparaisons, solutions = window.panels

    chiffres._select_row_letter("J")
    reachable = window.game_state.payload()["reachable_row_sums"]["J"]
    target_value = reachable[0]
    window._run(lambda: window.game_state.apply_clue("row_total", row="J", value=target_value))

    after_payload = window.game_state.payload()
    assert window.solutions_label.text() == f"Solutions restantes : {after_payload['n_solutions_total']}"
    assert solutions.my_miss_combo.count() == len(after_payload["solutions"])
    assert chiffres.domain_labels["T"].text().startswith("<b>T</b>")


def test_a_rejected_clue_leaves_every_panel_unchanged(qapp):
    window = MainWindow()
    chiffres, comparaisons, solutions = window.panels

    # Same contradiction fixture as tests/test_web.py's
    # test_post_clue_contradiction_rolls_back_and_returns_400: parity Pair on
    # T plus segment b=False forces T's domain down to {6} (6 is the only
    # even digit whose segments exclude "b"), which needs segment a ON --
    # explicitly setting it OFF is a genuine contradiction, not one a
    # fallback cycle would silently step around.
    window.game_state.apply_clue("parity", pos="T", value="Pair")
    window.game_state.apply_clue("segment", pos="T", seg="b", value=False)
    window._run(window.game_state.payload)
    domains_before = chiffres.domain_labels["T"].text()
    trace_before = solutions.trace_view.toPlainText()

    window._run(lambda: window.game_state.apply_clue("segment", pos="T", seg="a", value=False))

    assert window.error_label.isVisible()
    assert chiffres.domain_labels["T"].text() == domains_before
    assert solutions.trace_view.toPlainText() == trace_before
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `.venv/bin/pytest tests/test_native_integration.py -v`
Expected: fails because `window.panels` is still empty placeholders (`QWidget()` has no `.refresh`/`my_miss_combo`/etc.).

- [ ] **Step 3: Wire the real panels into `MainWindow`**

In `native/main_window.py`, add the imports:

```python
from .panels.chiffres_panel import ChiffresPanel
from .panels.comparaisons_panel import ComparaisonsPanel
from .panels.solutions_panel import SolutionsPanel
```

Replace the placeholder-building block:

```python
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        # Real panels are wired in by Task 8; placeholders keep this shell
        # independently testable in the meantime.
        self.panels: list[QWidget] = []
        for _ in TAB_TITLES:
            self.stack.addWidget(QWidget())
```

with:

```python
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        self.panels: list[QWidget] = [
            ChiffresPanel(self.game_state, self._run),
            ComparaisonsPanel(self.game_state, self._run),
            SolutionsPanel(self.game_state, self._run),
        ]
        for panel in self.panels:
            self.stack.addWidget(panel)
```

- [ ] **Step 4: Run every native test to confirm nothing regressed**

Run: `.venv/bin/pytest tests/test_native_main_window.py tests/test_native_chip_button.py tests/test_native_segment_digit.py tests/test_native_solutions_panel.py tests/test_native_chiffres_panel.py tests/test_native_comparaisons_panel.py tests/test_native_integration.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full test suite**

Run: `.venv/bin/pytest -v`
Expected: every test in the repo PASSes, including the untouched `tests/test_web.py`.

- [ ] **Step 6: Manual QA pass**

Run: `.venv/bin/python -m digitcode.native`

Walk through, comparing against `.venv/bin/python -m digitcode.web` (via `./run.sh`) running side by side for the same sequence of inputs:

1. Window appears narrow, titled "Digitcode", stays above other windows when you click into a different app.
2. Click each of the 3 tab buttons in turn -- switching must feel instant (no visible delay), and "Solutions restantes" must read the same number on all 3 tabs at all times.
3. On "Chiffres": pick a row letter, pick a value, confirm the domains grid and solutions count update; RAZ clears it back.
4. On "Comparaisons": click a "<"/">" chip for an adjacent pair, click it again to clear it; click a parity chip through Pair -> Impair -> unset; click segments on a digit through on -> off -> unset, confirm the drawing updates (solid vs. hatched vs. empty).
5. Force a contradiction (e.g. set a segment combination the current domain can't satisfy) and confirm the error banner appears and the board does not change.
6. On "Solutions": read a recommendation, click "il a raté", pick a candidate in the combo and click "j'ai tenté celle-ci, raté", click Annuler, click Réinitialiser.
7. Note the window width (`WINDOW_WIDTH` in `native/main_window.py`) -- if any panel's content wraps awkwardly at 380px, adjust the constant and re-check.

If anything above diverges from the web app's behavior for the same inputs, fix it before considering this task done -- functional parity with the web app is the acceptance bar (per the spec).

- [ ] **Step 7: Commit**

```bash
git add native/main_window.py tests/test_native_integration.py
git commit -m "$(cat <<'EOF'
feat(native): wire ChiffresPanel/ComparaisonsPanel/SolutionsPanel into MainWindow

Completes the native app: 3 switchable volets backed by one shared
GameState, functionally at parity with the web UI.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
