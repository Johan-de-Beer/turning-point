"""Expected threat (xT): a zone grid fitted by value iteration on other synthetic matches.

This follows Karun Singh's method (2018). The pitch is split into a 12 x 8 grid in the
attacking direction. From a set of training matches the fit counts, for each zone z:

* s(z), the share of actions there that are shots, and m(z) = 1 - s(z) the share that
  are moves (passes, failed or completed, and carries);
* g(z), the chance a shot from z is scored. A few dozen synthetic matches have too few
  goals per zone, so g(z) is the mean xG of the shots taken there (a smoothed scoring
  rate from the transparent xG model);
* T(z, z'), the share of moves from z that arrive under control in z'. A failed pass
  counts as a move that arrives nowhere, which is how losing the ball lowers threat.

xT(z) = s(z) g(z) + m(z) sum_z' T(z, z') xT(z') is iterated to a fixed point. An action's
xT is xT(end zone) - xT(start zone), for completed passes and carries only, as in the
original method.

Unlike the possession value surface in ``chances`` (a hand-set formula), this grid is
learned from how play actually moves in the synthetic training matches. Those matches
use the same generator as the demo match but different seeds, never the demo seed, so
the demo match is out of sample. ``python -m scripts.fit_xt`` refits and rewrites the
committed grid; a backend test checks that the committed grid matches a fresh fit.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .chances import shot_quality
from .ingest import canonical_order
from .movement import GRID_X, GRID_Y, cell

GRID_PATH = Path(__file__).with_name("xt_grid.json")
TRAINING_SEEDS = tuple(range(1, 25))
DEMO_SEED = 24017
TOLERANCE = 1e-7
MAX_ITERATIONS = 200


def fit(seeds=TRAINING_SEEDS) -> dict:
    from .generator import generate_fixture

    assert DEMO_SEED not in seeds, "The demo match must stay out of the training sample"
    zones = GRID_X * GRID_Y
    shots, moves, xg_sum = [0] * zones, [0] * zones, [0.0] * zones
    arrivals = [[0] * zones for _ in range(zones)]
    actions = 0
    for seed in seeds:
        _match, events = generate_fixture(seed)
        records = {e.event_id: e for e in events if e.revision == 1 and e.payload}
        ordered = canonical_order(records)
        quality = shot_quality(records, ordered)
        # Where the team in possession holds the ball, while it still does.
        held: tuple[str, int] | None = None
        for record in ordered:
            e = record.payload
            if e.kind == "TACKLE":
                continue
            if held and (e.kind in ("POSSESSION", "STOPPAGE", "PERIOD_END") or e.possession_id != held[0]):
                # The possession ended with the ball still held: dispossessed, intercepted after
                # a completed pass, or out of play. That is a move from there that arrives nowhere.
                moves[held[1]] += 1
                actions += 1
                held = None
            if e.kind == "POSSESSION":
                held = (e.possession_id, cell(e.detail.start.x, e.detail.start.y))
            elif e.kind in ("PASS", "CARRY"):
                a = cell(e.detail.start.x, e.detail.start.y)
                moves[a] += 1
                actions += 1
                held = None
                if e.kind == "CARRY" or e.detail.completed:
                    b = cell(e.detail.end.x, e.detail.end.y)
                    arrivals[a][b] += 1
                    held = (e.possession_id, b)
            elif e.kind == "SHOT" and record.event_id in quality:
                z = cell(e.detail.position.x, e.detail.position.y)
                shots[z] += 1
                xg_sum[z] += quality[record.event_id].xg
                actions += 1
                held = None
    total = [shots[z] + moves[z] for z in range(zones)]
    s = [shots[z] / total[z] if total[z] else 0.0 for z in range(zones)]
    g = [xg_sum[z] / shots[z] if shots[z] else 0.0 for z in range(zones)]
    m = [moves[z] / total[z] if total[z] else 0.0 for z in range(zones)]
    transition = [[arrivals[z][w] / moves[z] if moves[z] else 0.0 for w in range(zones)] for z in range(zones)]
    values = [0.0] * zones
    iterations = 0
    for iterations in range(1, MAX_ITERATIONS + 1):
        new = [s[z] * g[z] + m[z] * sum(transition[z][w] * values[w] for w in range(zones) if transition[z][w]) for z in range(zones)]
        change = max(abs(a - b) for a, b in zip(new, values))
        values = new
        if change < TOLERANCE:
            break
    return {"grid_x": GRID_X, "grid_y": GRID_Y, "values": [round(v, 5) for v in values],
            "training": {"matches": len(seeds), "seeds": [min(seeds), max(seeds)], "actions": actions, "shots": sum(shots),
                         "moves": sum(moves), "iterations": iterations}}


def write(path: Path = GRID_PATH) -> dict:
    grid = fit()
    path.write_text(json.dumps(grid, indent=1) + "\n", encoding="utf-8")
    return grid


@lru_cache(maxsize=1)
def grid() -> dict:
    return json.loads(GRID_PATH.read_text(encoding="utf-8"))


def threat(x: float, y: float) -> float:
    """xT of the zone holding (x, y), team-relative coordinates."""
    return grid()["values"][cell(x, y)]
