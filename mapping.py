from __future__ import annotations
from typing import Dict, List, Tuple, Optional

# 7-seg naming: a (top), b (top-right), c (bottom-right),
#               d (bottom), e (bottom-left), f (top-left), g (middle)

DIGIT_TO_SEGS: Dict[int, set] = {
    0: set("abcdef"),     # no 'g'
    1: set("bc"),
    2: set("abdeg"),
    3: set("abcdg"),
    4: set("fgbc"),
    5: set("acdfg"),
    6: set("acdefg"),
    7: set("abc"),
    8: set("abcdefg"),
    9: set("abcdfg"),
}

# Six positions for two rows of three 7-seg digits (top: T U V, bottom: W X Y)
POSITIONS = ["T","U","V","W","X","Y"]

# Adjacency (no equal value horizontally/vertically)
ADJACENT = [
    ("T","U"), ("U","V"), ("W","X"), ("X","Y"),
    ("T","W"), ("U","X"), ("V","Y"),
]

# Grid overlay
ROW_TOP = ["J","K","L","M","N"]
ROW_BOTTOM = ["O","P","Q","R","S"]
COLS = list("ABCDEFGHI")

def column_to_block_and_side(col: str) -> Tuple[int, str]:
    """A..C -> block0 (T/W), D..F -> block1 (U/X), G..I -> block2 (V/Y).
       side: left/mid/right within a block."""
    idx = COLS.index(col)
    block = idx // 3  # 0,1,2
    side_index = idx % 3  # 0 left, 1 mid, 2 right
    side = ["left","mid","right"][side_index]
    return block, side

def block_positions(block: int) -> Tuple[str, str]:
    """Return (top, bottom) position labels for a block."""
    if block == 0: return "T","W"
    if block == 1: return "U","X"
    if block == 2: return "V","Y"
    raise ValueError("block must be 0,1,2")

def grid_to_segment(pos: str, row: str, col: str) -> Optional[str]:
    """Map a (pos, row-letter, col-letter) to a single segment ('a'..'g').
       Validates pos belongs to the block for the given column.
        Returns None if the triple does not correspond to an addressable segment."""
    block, side = column_to_block_and_side(col)
    top, bottom = block_positions(block)
    is_top = pos in ("T","U","V")
    if (is_top and pos != top) or ((not is_top) and pos != bottom):
        # column not matching the position's block
        return None

    # Row mapping
    if row in ("J","O"):  # a
        return "a" if side == "mid" else None
    if row in ("L","Q"):  # g
        return "g" if side == "mid" else None
    if row in ("N","S"):  # d
        return "d" if side == "mid" else None
    if row in ("K","P"):  # f (left) / b (right)
        if side == "left": return "f"
        if side == "right": return "b"
        return None
    if row in ("M","R"):  # e (left) / c (right)
        if side == "left": return "e"
        if side == "right": return "c"
        return None
    return None

def row_contributors(row: str) -> List[Tuple[str,str]]:
    """For a row letter, list the contributing (pos, seg) pairs for the sum constraint."""
    out: List[Tuple[str,str]] = []
    if row in ROW_TOP:
        pos_list = ["T","U","V"]
    elif row in ROW_BOTTOM:
        pos_list = ["W","X","Y"]
    else:
        raise ValueError("invalid row letter")
    if row in ("J","O"): segs = ["a"]
    elif row in ("L","Q"): segs = ["g"]
    elif row in ("N","S"): segs = ["d"]
    elif row in ("K","P"): segs = ["f","b"]
    elif row in ("M","R"): segs = ["e","c"]
    else: segs = []
    for p in pos_list:
        for s in segs:
            out.append((p,s))
    return out

def col_contributors(col: str) -> List[Tuple[str,str]]:
    """For a column letter, list contributing (pos, seg) pairs for the sum constraint."""
    block, side = column_to_block_and_side(col)
    top, bottom = block_positions(block)
    if side == "left": segs = ["f","e"]
    elif side == "mid": segs = ["a","g","d"]
    elif side == "right": segs = ["b","c"]
    else: segs = []
    out: List[Tuple[str,str]] = []
    for p in (top, bottom):
        for s in segs:
            out.append((p,s))
    return out
