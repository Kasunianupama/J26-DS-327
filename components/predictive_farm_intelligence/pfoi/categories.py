"""Category vocabularies shared by the loaders, the rate estimator and the engine.

They mirror the `model_input.day_cell` contract (see the component AGENTS.md, section 4).
"""
from __future__ import annotations

STATES = (
    "calf",
    "heifer_open",
    "heifer_pregnant",
    "milking",
    "dry_open",
    "dry_pregnant",
    "bull",
    "unknown",
)

# Cow parity groups used inside the engine (milking and dry cows).
COW_PARITIES = ("1", "2", "3+", "unknown")
# Parity after the next calving, as indices into COW_PARITIES.
NEXT_PARITY = (1, 2, 2, 3)
# A heifer's first calving makes her parity "1".
FIRST_PARITY = 0

GENERATIONS = ("0", "1", "2", "3+", "unknown")

# Calves are held by sex: only female calves become heifers, male calves may become bulls.
SEXES = ("female", "male")
# Calf generation = dam generation + 1, capped at "3+"; unknown stays unknown.
CHILD_GENERATION = (1, 2, 3, 3, 4)

# Days-in-milk bands, inclusive bounds. "305+" starts at 306.
DIM_BANDS = ("0-60", "61-150", "151-305", "305+")
DIM_BAND_BOUNDS = ((0, 60), (61, 150), (151, 305), (306, None))
UNKNOWN_BAND = "unknown"
NA_BAND = "na"

# Panel columns, as named in model_input.day_panel.
STOCK_COLUMNS = (
    "n_herd",
    "calves",
    "heifers_open",
    "heifers_pregnant",
    "milking",
    "dry_open",
    "dry_pregnant",
    "bulls",
    "unknown_state",
)
EVENT_COLUMNS = (
    "calvings",
    "dry_offs",
    "ais",
    "real_abortions",
    "deaths",
    "culls",
    "sales",
    "exits",
    "births",
    "external_entries",
)
EXIT_TYPES = ("deaths", "culls", "sales")

# Engine state -> day_panel stock column.
STATE_TO_STOCK = {
    "calf": "calves",
    "heifer_open": "heifers_open",
    "heifer_pregnant": "heifers_pregnant",
    "milking": "milking",
    "dry_open": "dry_open",
    "dry_pregnant": "dry_pregnant",
    "bull": "bulls",
    "unknown": "unknown_state",
}


def dim_band(dim: int) -> str:
    """Band label for a days-in-milk value (negative values are treated as 0)."""
    for label, (lo, hi) in zip(DIM_BANDS, DIM_BAND_BOUNDS):
        if dim >= lo and (hi is None or dim <= hi):
            return label
    return DIM_BANDS[0]


def cow_parity_index(parity_group: str) -> int:
    """Index into COW_PARITIES; '0' or anything unexpected on a cow maps to unknown."""
    return COW_PARITIES.index(parity_group) if parity_group in COW_PARITIES else 3


def generation_index(generation_group: str) -> int:
    return GENERATIONS.index(generation_group) if generation_group in GENERATIONS else 4
