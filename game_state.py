from __future__ import annotations

from typing import Callable

from .mapping import POSITIONS, ROW_TOP, ROW_BOTTOM, COLS, row_contributors, col_contributors
from .solver import Cancelled, DigitcodeSolver, Clue
from .strategy import evaluate_race_strategy
from .endgame import OPP_FAIL_COUNT_CAP, evaluate_endgame

# Cap for the per-question solution-count display (how many solutions each
# reachable answer could leave). Must stay a lower bound, never a fabricated
# exact number -- see _question_solution_counts. Independent of strategy.py's
# own fallback_cap: this one is tuned for UI latency on the handful of
# questions actually rendered, not for scoring the full question set. Must
# match web/static/app.js's MAX_ALTERNATIVES_SHOWN (how many alternatives
# get counts computed at all) -- and, since the native app was added, also
# native/panels/solutions_panel.py's own MAX_ALTERNATIVES_SHOWN = 10. That's
# three independent copies of the same constant (this module, app.js, and
# solutions_panel.py); all three must stay in sync by hand.
RANGE_DISPLAY_CAP = 2000
MAX_ALTERNATIVES_WITH_RANGE = 10

# Race-strategy compute budget used by payload() below. Shorter deadline
# than strategy.py's CLI-tuned default (3.0s), and a tighter beam ceiling to
# match: N up to 9 reliably completes the beam-limited race search inside
# ~1.1s, whereas N 10-12 would usually burn the whole budget only to fall
# back. Both the web and native UIs are interactive surfaces that must not
# routinely stall for over a second, unlike the CLI. Commit 9d5be82
# deliberately raised the CLI's own beam ceiling to N=12 while holding these
# two numbers lower for latency reasons -- do not "fix" the discrepancy by
# unifying them. A future desktop-specific tuning could afford to raise
# these (the native window is a local always-on-top companion, not a
# request/response server), but that would be a deliberate change to this
# shared logic path's callers, not a bug.
RACE_TIME_BUDGET_S = 1.5
RACE_N_BEAM_MAX = 9

# "Coups à solution unique" (see _ev_plus_questions): only scanned when the
# board is already this narrow. A singleton branch is negligible noise on
# a wide-open board, and scanning every candidate question (not just the
# top-ranked ones) for one would be needless cost that early.
EV_SCAN_MAX_N = 50

# A branch landing at 2..EV_TRAP_MAX solutions is a trap, not progress: if
# forced to guess there and wrong, the failed guess hands the opponent a
# near-certain win next turn. Deliberately the same boundary as
# native/panels/question_format.py's SOLUTION_COUNT_EXACT_THRESHOLD (the UI
# already only displays exact counts up to there) -- kept as an
# independent literal rather than an import, since native/ depends on this
# module and not the other way around; keep the two values in sync by hand.
EV_TRAP_MAX = 4

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
    propagation without appearing in any globally valid solution (same root
    cause as the count-mismatch documented on strategy.py's
    `_clue_signature`). When the candidate list is exhaustive (its count
    matches `n_solutions_total`, not just capped at the display limit),
    the true per-position possibilities
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


def _question_solution_counts(
    solver: DigitcodeSolver, clue: Clue, q: dict, cap: int, excluded: frozenset = frozenset(),
    should_cancel: Callable[[], bool] = lambda: False,
) -> list[dict]:
    """Sorted, deduplicated list of {"n", "capped"} for every reachable
    answer's resulting solution count. A min/max range can't tell apart a
    question whose branches are exactly {1, 6} from one that spans every
    value 1..6 -- those play very differently (the former never risks
    leaving the opponent at 2-4), so every distinct reachable count is
    reported. `capped` means the true count was >= `cap` but unknown beyond
    that -- never presented as an exact value."""
    counts: dict[int, bool] = {}
    for out in q["outcomes"]:
        if should_cancel():
            raise Cancelled()
        child_clue = solver._apply_answer_to_clue(clue, q, out["answer"], 0)
        child = _child_solver(solver, child_clue)
        if child is None:
            continue
        n = child.count_solutions_capped(child_clue, cap=cap, excluded=excluded, should_cancel=should_cancel)
        if n == 0:
            continue
        counts[n] = counts.get(n, False) or (n >= cap)
    return [{"n": n, "capped": capped} for n, capped in sorted(counts.items())]


def _ev_plus_questions(
    solver: DigitcodeSolver, clue: Clue, all_questions_by_label: dict, n_solutions_total: int,
    excluded: frozenset, should_cancel: Callable[[], bool] = lambda: False,
) -> list[dict]:
    """Questions with a branch that can end the game outright (exactly 1
    remaining solution), kept only when landing on that winning branch is
    at least as likely as landing on a "trap" branch (2..EV_TRAP_MAX
    solutions -- not a win, but few enough that a wrong guess there next
    hands the opponent a near-certain win). A branch beyond the trap zone
    is treated as neutral -- no better or worse than not having asked --
    so it never counts against a question.

    This is a DIFFERENT criterion from evaluate_race_strategy's ranking
    (unaffected by this function): that heuristic minimizes the *expected*
    remaining-solution fraction, so it ranks a lopsided 1-vs-11 split far
    below a balanced 6-vs-6 one even though only the former can win this
    turn -- correct for "reduce fastest", useless for "can I win right
    now". Also unrelated to solver.py's ev_metrics_for_question (used by
    the CLI's `rank` command): that one gives a 2-solution branch *partial
    win credit*, the opposite of treating it as a trap.

    EV here is p_win - p_trap: the fraction of the N current candidates
    that resolve to an immediate win, minus the fraction that resolve to
    the trap zone. Only questions with ev > 0 are returned, sorted best
    first."""
    if n_solutions_total > EV_SCAN_MAX_N or n_solutions_total == 0:
        return []
    cap = EV_TRAP_MAX + 1  # only need "<=EV_TRAP_MAX" vs ">EV_TRAP_MAX", not the exact large count
    found = []
    for q in all_questions_by_label.values():
        if should_cancel():
            raise Cancelled()
        n_win = 0
        n_trap = 0
        counts: dict[int, bool] = {}
        for out in q["outcomes"]:
            child_clue = solver._apply_answer_to_clue(clue, q, out["answer"], 0)
            child = _child_solver(solver, child_clue)
            if child is None:
                continue
            n = child.count_solutions_capped(
                child_clue, cap=cap, excluded=excluded, should_cancel=should_cancel,
            )
            if n == 0:
                continue
            counts[n] = counts.get(n, False) or (n >= cap)
            if n == 1:
                n_win += n
            elif n <= EV_TRAP_MAX:
                n_trap += n
        if n_win == 0:
            continue
        ev = (n_win - n_trap) / n_solutions_total
        if ev <= 0:
            continue
        found.append({
            "qtype": q["qtype"],
            "label": q["label"],
            "ev": ev,
            "p_win": n_win / n_solutions_total,
            "p_trap": n_trap / n_solutions_total,
            "solution_counts": [{"n": n, "capped": capped} for n, capped in sorted(counts.items())],
        })
    found.sort(key=lambda e: e["ev"], reverse=True)
    return found


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
        # Public solution count when the opponent failed its FIRST guess (0 =
        # no failure yet). The endgame engine needs it to estimate the
        # opponent's odds on its next guess (its failed code may still be in
        # the pool) -- see endgame.opp_hit_probability. Only the first failure
        # matters: a second one leaves it at 0 attempts, a terminal state.
        self.opp_fail_pool_size = 0

    def payload(self) -> dict:
        return self.build_payload_from(self.clue, self.a_me, self.a_opp, self.my_excluded)

    @staticmethod
    def build_quick_payload_from(clue: Clue) -> dict:
        """Cheap subset of `build_payload_from`: only the fields derivable
        from a bare `propagate()` (fast -- no solution counting, race
        strategy, or question enumeration, the parts that can take seconds
        on a wide-open board). For the native app: rendered immediately
        after `apply_clue_fast`, merged over the last full payload, so a
        just-set total/comparison/parity/segment shows up on screen right
        away (as "already set", chip highlighted) instead of looking like
        the click did nothing until the much slower background worker
        eventually delivers the full payload. Not a substitute for it --
        n_solutions_total/race/reachable sums here would be silently wrong
        if used beyond that immediate-feedback purpose."""
        solver = DigitcodeSolver()
        solver.propagate(clue)  # may raise ValueError; callers must catch it
        return {
            "domains": solver.snapshot(),
            "row_totals": clue.row_totals,
            "col_totals": clue.col_totals,
            "parity": clue.parity,
            "comparisons": clue.comparisons,
            "segment_state": {f"{p}{s}": v for (p, s), v in clue.segment_state.items()},
        }

    @staticmethod
    def build_payload_from(
        clue: Clue, a_me: int, a_opp: int, excluded: frozenset,
        should_cancel: Callable[[], bool] = lambda: False,
    ) -> dict:
        """The guts of `payload()`, parameterized on explicit inputs instead
        of `self.*` so it can run against a `clone_clue` snapshot from a
        background thread while the live `GameState` keeps mutating its own
        `self.clue` for the next move. `should_cancel` is threaded down into
        every expensive solver/strategy call; passing it raises
        `solver.Cancelled` (propagated to the caller) as soon as a newer
        move makes this computation stale. Callers that don't pass it (the
        web app, the CLI, `payload()` above) get the previous, uncancellable
        behavior unchanged."""
        solver = DigitcodeSolver()
        solver.propagate(clue)  # may raise ValueError; callers must catch it
        snap = solver.snapshot()
        n_solutions_total = solver.count_solutions_capped(
            clue, cap=None, excluded=excluded, should_cancel=should_cancel,
        )
        sols = solver.enumerate_solutions(clue, limit=6, excluded=excluded, should_cancel=should_cancel)
        # See RACE_TIME_BUDGET_S / RACE_N_BEAM_MAX above for the rationale
        # behind these two values.
        race = evaluate_race_strategy(
            solver,
            clue,
            a_me,
            a_opp,
            excluded,
            time_budget_s=RACE_TIME_BUDGET_S,
            n_beam_max=RACE_N_BEAM_MAX,
            should_cancel=should_cancel,
        )
        all_questions_by_label = {
            q["label"]: q for q in solver.enumerate_all_questions(clue, should_cancel=should_cancel)
            if len(q["outcomes"]) > 1
        }

        def _annotate(entry: dict) -> None:
            q = all_questions_by_label.get(entry["label"])
            if q is None:
                return
            counts = _question_solution_counts(
                solver, clue, q, RANGE_DISPLAY_CAP, excluded=excluded, should_cancel=should_cancel,
            )
            if counts:
                entry["solution_counts"] = counts

        if race["best_question"] is not None:
            _annotate(race["best_question"])
        for alt in race["ranked_alternatives"][:MAX_ALTERNATIVES_WITH_RANGE]:
            _annotate(alt)
        ev_plus_questions = _ev_plus_questions(
            solver, clue, all_questions_by_label, n_solutions_total, excluded, should_cancel=should_cancel,
        )
        return {
            "domains": _display_domains(snap, sols, n_solutions_total),
            "solutions": [solver.solution_to_string(s) for s in sols],
            "n_solutions_total": n_solutions_total,
            "trace": solver.trace,
            "ev_plus_questions": ev_plus_questions,
            "a_me": a_me,
            "a_opp": a_opp,
            "my_excluded": [f"{c[0]}{c[1]}{c[2]} {c[3]}{c[4]}{c[5]}" for c in excluded],
            "race": race,
            "row_totals": clue.row_totals,
            "col_totals": clue.col_totals,
            "parity": clue.parity,
            "comparisons": clue.comparisons,
            "segment_state": {f"{p}{s}": v for (p, s), v in clue.segment_state.items()},
            "reachable_row_sums": {
                row: solver._reachable_sums(row_contributors(row))
                for row in ROW_TOP + ROW_BOTTOM
                if row not in clue.row_totals
            },
            "reachable_col_sums": {
                col: solver._reachable_sums(col_contributors(col))
                for col in COLS
                if col not in clue.col_totals
            },
        }

    @staticmethod
    def build_endgame_from(
        clue: Clue, a_me: int, a_opp: int, excluded: frozenset, opp_fail_pool_size: int,
        should_cancel: Callable[[], bool] = lambda: False,
    ) -> dict | None:
        """Exact endgame recommendation (see endgame.evaluate_endgame), or
        None when the board still has more than endgame.ENDGAME_N_MAX
        public solutions. Deliberately separate from build_payload_from: it
        may take seconds (budget: endgame.ENDGAME_TIME_BUDGET_S), so the
        native app runs it on its own worker after the fast payload is
        already on screen."""
        solver = DigitcodeSolver()
        solver.propagate(clue)  # may raise ValueError; callers must catch it
        return evaluate_endgame(
            solver, clue, a_me, a_opp, excluded, opp_fail_pool_size, should_cancel=should_cancel,
        )

    def endgame(self) -> dict | None:
        return self.build_endgame_from(
            self.clue, self.a_me, self.a_opp, self.my_excluded, self.opp_fail_pool_size,
        )

    def _apply_mutation(self, clue_type: str, /, **fields) -> None:
        # `clue_type` (and `self`) are positional-only so that a `fields`
        # dict containing a key literally named "clue_type" (or "self")
        # can never collide with this signature and raise a confusing
        # "got multiple values for argument" TypeError -- such a key just
        # lands harmlessly inside **fields instead, unused. Mirrors the
        # pre-refactor web handler, which read specific keys by name and
        # silently ignored anything else.
        #
        # Shared by `apply_clue` and `apply_clue_fast`: both need the exact
        # same field validation + history bookkeeping + `Clue` mutation, and
        # differ only in how they validate the *result* (a full payload vs.
        # a cheap propagate-only check) -- see each method's docstring.
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

    def apply_clue(self, clue_type: str, /, **fields) -> dict:
        self._apply_mutation(clue_type, **fields)
        try:
            return self.payload()
        except ValueError:
            self.clue = self.history.pop()
            raise

    def apply_clue_fast(self, clue_type: str, /, **fields) -> None:
        """Like `apply_clue`, but validates the result with a cheap
        `propagate()` call instead of computing the full display payload
        (the expensive counts, race strategy, and per-question annotations).
        For a caller that wants instant accept/reject feedback -- e.g. the
        native app's UI thread, so the window is never blocked while typing
        -- and will separately request the expensive payload on its own
        schedule (typically on a background thread it can cancel and
        restart as newer moves arrive; see native/solve_worker.py)."""
        self._apply_mutation(clue_type, **fields)
        try:
            DigitcodeSolver().propagate(self.clue)
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
        if last_error is None:
            raise ValueError(f"apply_clue_with_fallback({clue_type!r}, []) called with no attempts")
        raise last_error

    def apply_clue_with_fallback_fast(self, clue_type: str, attempts: list[dict]) -> None:
        """Like `apply_clue_with_fallback`, but tries each attempt via
        `apply_clue_fast` (mutate + cheap validation only) instead of the
        full `apply_clue`. See `apply_clue_fast` for why."""
        last_error: ValueError | None = None
        for fields in attempts:
            try:
                self.apply_clue_fast(clue_type, **fields)
                return
            except ValueError as e:
                last_error = e
        if last_error is None:
            raise ValueError(f"apply_clue_with_fallback_fast({clue_type!r}, []) called with no attempts")
        raise last_error

    def guess_failed(self, body: dict) -> dict:
        who = body.get("who")
        if who == "opponent":
            if self.a_opp == 2:
                solver = DigitcodeSolver()
                solver.propagate(self.clue)
                self.opp_fail_pool_size = solver.count_solutions_capped(self.clue, cap=OPP_FAIL_COUNT_CAP)
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
        self.opp_fail_pool_size = 0
        return self.payload()
