"""#4 Bollinger Band + RSI reversion with an ADX range filter (5m signals).

Rules (defaults from phase1_findings.md + Phase 2 brief):
* 5m close below the lower Bollinger Band (20, 2) and RSI(14) < rsi_lo and ADX(14) < adx_max -> long
  at the next 1m open (market). Short is the mirror (close above upper band, RSI > 100 - rsi_lo).
* Hard stop (fixed, not tuned): 1.5 x ATR(14) of 5m bars from the fill.
* Exit: resting limit at the 5m middle band (updated each 5m close) or after 45 minutes.
Tuned (in-sample only): adx_max (999 = no filter), rsi_lo.
"""
import numpy as np

from core.engine import candidates, empty_candidates
from core.indicators import adx, atr, bollinger, rsi

NAME = "bb_rsi"
TITLE = "Bollinger + RSI reversion"
DAILY = False
GRID = {"adx_max": [15, 20, 25, 30, 999], "rsi_lo": [25, 30, 35]}
DEFAULT = {"adx_max": 20, "rsi_lo": 30}
ATR_MULT = 1.5
TIME_STOP = 45


def _ind(m):
    if "bbrsi" not in m._cache:
        b = m.bars(5)
        lo, mid, up = bollinger(b["c"], 20, 2.0)
        m._cache["bbrsi"] = (b, lo.to_numpy(), mid.to_numpy(), up.to_numpy(), rsi(b["c"], 14).to_numpy(),
                             adx(b["h"], b["l"], b["c"], 14).to_numpy(), atr(b["h"], b["l"], b["c"], 14).to_numpy())
    return m._cache["bbrsi"]


def build(m, p):
    b, lo, mid, up, r, a, at = _ind(m)
    c = b["c"].to_numpy()
    rl, amax = float(p["rsi_lo"]), float(p["adx_max"])
    calm = a < amax
    long_ = (c < lo) & (r < rl) & calm
    short = (c > up) & (r > 100 - rl) & calm
    idx = np.flatnonzero(long_ | short)
    if not idx.size:
        return empty_candidates(), None, None
    act = b["act"].to_numpy()[idx]
    d = np.where(long_[idx], 1, -1)
    dyn = m.to_1m(b, mid)
    return candidates(sig=act, fill=act, dir=d, sdist=ATR_MULT * at[idx], dyn=1, maxb=TIME_STOP), dyn, dyn
