"""#7 Intraday momentum: first half-hour return predicts the last half-hour (Shen, Urquhart, Wang 2022).

Rules (defaults from phase1_findings.md):
* Day anchor "utc": 00:00-24:00 UTC. Anchor "ny": the US equity session 09:30-16:00 America/New_York
  (DST-aware, weekdays).
* If the first 30 minutes' return (open of first bar to close of 30th bar) is at least
  `min_move_pct` in absolute value, trade in its direction during the last 30 minutes of the day:
  market entry at the open of the last half-hour, exit at the session end (30-minute time stop).
* Hard stop (my addition, the paper has none): 1.5 x ATR(14) of 5m bars from the fill.
Tuned (in-sample only): anchor, min_move_pct.
"""
import numpy as np

from core.engine import candidates, empty_candidates
from core.indicators import atr

NAME = "intraday_momentum"
TITLE = "Intraday momentum (first to last half-hour)"
DAILY = True
GRID = {"anchor": ["utc", "ny"], "min_move_pct": [0.0, 0.1, 0.2, 0.3]}
DEFAULT = {"anchor": "utc", "min_move_pct": 0.0}
ATR_MULT = 1.5


def build(m, p):
    if "atr5_1m" not in m._cache:
        b = m.bars(5)
        m._cache["atr5_1m"] = m.to_1m(b, atr(b["h"], b["l"], b["c"], 14))
    a1 = m._cache["atr5_1m"]
    if p["anchor"] == "utc":
        starts = m.day_starts()
        length = 1440
    else:
        starts = m.ny_time_index(9, 30, weekdays_only=True)
        length = 390
    starts = starts[starts + length < m.n]
    first = m.c[starts + 29] / m.o[starts] - 1
    keep = (np.abs(first) >= float(p["min_move_pct"]) / 100) & (first != 0)
    s = starts[keep]
    if not s.size:
        return empty_candidates(), None, None
    e = s + length - 30
    d = np.sign(first[keep]).astype(np.int64)
    return candidates(sig=s + 30, fill=e, dir=d, sdist=ATR_MULT * a1[e], maxb=30), None, None
