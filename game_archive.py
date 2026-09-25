"""Local, atomic archives written before a played game is reset."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
from uuid import uuid4
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game_state import GameState
    from .solver import Clue


def archive_directory() -> Path:
    override = os.environ.get("DIGITCODE_ARCHIVE_DIR")
    if override:
        return Path(override).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "digitcode" / "parties"


def _clue_record(clue: Clue) -> dict:
    return {
        "row_totals": dict(clue.row_totals),
        "col_totals": dict(clue.col_totals),
        "parity": dict(clue.parity),
        "comparisons": list(clue.comparisons),
        # JSON objects cannot use the solver's (position, segment) tuple keys.
        "segment_state": [
            {"pos": pos, "segment": seg, "on": value}
            for (pos, seg), value in sorted(clue.segment_state.items())
        ],
        "max_two": clue.max_two,
        "forbid_equal_adjacent": clue.forbid_equal_adjacent,
    }


def _tracking_record(snapshot: dict) -> dict:
    return {**snapshot, "excluded": [list(code) for code in sorted(snapshot["excluded"])]}


def save_game(game: GameState) -> Path:
    """Persist all recorded game state. Never mutate the game on failure.

    Write a private temporary file, flush it, then atomically publish it.
    A unique name keeps successive resets and separate app instances apart.
    Only recorded information is saved: the opponent's guessed codes and an
    unrecorded final secret/result are not inferred.
    """
    saved_at = datetime.now(timezone.utc)
    record = {
        "schema_version": 1,
        "started_at": game.started_at.isoformat(),
        "saved_at": saved_at.isoformat(),
        "reason": "reset",
        "state": {
            "clue": _clue_record(game.clue),
            "a_me": game.a_me,
            "a_opp": game.a_opp,
            "my_excluded": [list(code) for code in sorted(game.my_excluded)],
            "opp_fail_pool_size": game.opp_fail_pool_size,
            "opp_starts": game.opp_starts,
            "failed_guesses": list(game.failed_guesses),
            "endgame_phase": game._endgame_phase,
            "endgame_manual": game._endgame_manual,
            "effective_turn_phase": game.endgame_turn_phase(),
        },
        "history": [_clue_record(clue) for clue in game.history],
        "state_history": [_tracking_record(snap) for snap in game._state_history],
    }
    directory = archive_directory()
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"partie-{saved_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex}.json"
        target = directory / filename
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".partie-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        return target
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Sauvegarde impossible dans {directory} : {exc}. "
            "Réinitialisation annulée ; la partie en cours est conservée."
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Keep the original write error; never discard the live game.
