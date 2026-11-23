"""#5 EMA pullback continuation (5m entries in the 1h trend direction).

Rules (defaults from phase1_findings.md):
* 1h trend: EMA(21) above EMA(50) on 1h closes = up, below = down (last closed 1h bar).
* Up-trend: a 5m bar whose low touches or pierces the 5m EMA(21) but closes above it -> long at the
  next 1m open (market). Down-trend: mirror.
* Stop: `stop_pct`% from entry; target: `ratio` x stop distance (default 1.1% / 1.35%). No time stop.
Tuned (in-sample only): stop_pct, ratio.
Simplification: the source script's extra MACD/RSI/ADX filters are not used (exact values unknown).
"""
import numpy as np

from core.engine import candidates, empty_candidates
from core.indicators import ema

NAME = "ema_pullback"
TITLE = "EMA pullback continuation"
DAILY = False
GRID = {"stop_pct": [0.4, 0.6, 0.8, 1.1, 1.5], "ratio": [0.8, 1.0, 1.23, 1.5, 2.0]}
DEFAULT = {"stop_pct": 1.1, "ratio": 1.23}


def _sig(m):
    if "emapb" not in m._cache:
        b5, h1 = m.bars(5), m.bars(60)
        e21 = ema(b5["c"], 21).to_numpy()
        trend = np.sign(ema(h1["c"], 21) - ema(h1["c"], 50)).to_numpy()
        act = b5["act"].to_numpy()
        tr = m.to_1m(h1, trend)[act]
        c, l, h = b5["c"].to_numpy(), b5["l"].to_numpy(), b5["h"].to_numpy()
        long_ = (tr > 0) & (l <= e21) & (c > e21)
        short = (tr < 0) & (h >= e21) & (c < e21)
        m._cache["emapb"] = (act, c, long_, short)
    return m._cache["emapb"]


def build(m, p):
    act, c, long_, short = _sig(m)
    idx = np.flatnonzero(long_ | short)
    if not idx.size:
        return empty_candidates(), None, None
    d = np.where(long_[idx], 1, -1)
    sdist = c[idx] * float(p["stop_pct"]) / 100
    return candidates(sig=act[idx], fill=act[idx], dir=d, sdist=sdist, rr=float(p["ratio"])), None, None
