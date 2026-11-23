"""Phase 3 survivor: 4h price vs moving-average trend filter, fixed holding period.

Built from the only signal that survived the zero-cost edge screen ("4h|price_vs_ma200|H120"):
* Signal at each 4h close: long if close > SMA(ma_len) of 4h closes, short if below.
* Entry: market order at the next bar open, in the signal's direction, whenever flat.
* Exit: after `hold_4h` 4-hour bars (120 = 20 days), then a new trade opens at the next 4h close
  in the then-current direction; or earlier at the hard stop.
* Hard stop (my addition; the screen had none, but 0.5%-risk sizing needs one): 2 x ATR(20) of daily
  bars from the fill ("2N" Turtle convention). Fixed, not tuned.
Walk-forward tuned: ma_len, hold_4h.
Runs on any Market (Delta 1m or Binance 1h); signals use only closed 4h/1D bars.
"""
import numpy as np

from core.engine import candidates, empty_candidates
from core.indicators import atr, sma

NAME = "trend_ma_4h"
TITLE = "4h price vs SMA trend filter, fixed hold"
GRID = {"ma_len": [100, 150, 200, 250, 300], "hold_4h": [60, 120, 180]}
DEFAULT = {"ma_len": 200, "hold_4h": 120}
STOP_ATR_MULT = 2.0


def build(m, p):
    b4, b1d = m.bars(240), m.bars(1440)
    c = b4["c"]
    d = np.sign(c - sma(c, int(p["ma_len"]))).fillna(0).to_numpy()
    act = b4["act"].to_numpy()
    a1d = m.to_1m(b1d, atr(b1d["h"], b1d["l"], b1d["c"], 20))  # value known at each bar open
    sdist = STOP_ATR_MULT * a1d[act]
    ok = (d != 0) & np.isfinite(sdist)
    if not ok.any():
        return empty_candidates(), None, None
    maxb = int(p["hold_4h"]) * 240 * 60 // m.step
    return candidates(sig=act[ok], fill=act[ok], dir=d[ok].astype(np.int64), sdist=sdist[ok], maxb=maxb), None, None
