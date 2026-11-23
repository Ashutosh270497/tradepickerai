"""#2 Asia range -> London breakout (control strategy; holds for hours, not a scalp).

Rules (defaults from phase1_findings.md):
* Asia range = high/low of 00:00-07:00 UTC.
* Entry: first 15m candle that CLOSES outside the range between 07:00 and 16:00 UTC; market order at
  the next 1m open. One trade per day.
* Stop distance = `stop_mult` x range height; target distance = `target_mult` x range height
  (0 = no target). Exit at end of day (00:00 UTC) if neither is hit.
Tuned (in-sample only): stop_mult, target_mult.
Assumption I added: the 16:00 UTC cut-off for new entries.
"""
import numpy as np

from core.engine import candidates, empty_candidates

NAME = "asia_london"
TITLE = "Asia range to London breakout"
DAILY = True
GRID = {"stop_mult": [0.5, 0.75, 1.0], "target_mult": [1.0, 1.5, 2.0, 3.0, 0.0]}
DEFAULT = {"stop_mult": 1.0, "target_mult": 2.0}


def build(m, p):
    sm, tm = float(p["stop_mult"]), float(p["target_mult"])
    b = m.bars(15)
    act, close = b["act"].to_numpy(), b["c"].to_numpy()
    fills, dirs, sd, ex = [], [], [], []
    for d0 in m.day_starts():
        asia_end, london_end, eod = d0 + 420, d0 + 960, d0 + 1440
        if eod >= m.n:
            break
        hi, lo = m.h[d0:asia_end].max(), m.l[d0:asia_end].min()
        rng = hi - lo
        if rng < 2 * m.tick:
            continue
        i0 = np.searchsorted(act, asia_end + 15)
        i1 = np.searchsorted(act, london_end, side="right")
        seg = close[i0:i1]
        out = np.flatnonzero((seg > hi) | (seg < lo))
        if not out.size:
            continue
        k = i0 + out[0]
        fills.append(act[k]); dirs.append(1 if close[k] > hi else -1); sd.append(sm * rng); ex.append(eod)
    if not fills:
        return empty_candidates(), None, None
    f = np.asarray(fills)
    rr = tm / sm if tm > 0 else np.nan
    return candidates(sig=f, fill=f, dir=np.asarray(dirs), sdist=np.asarray(sd), rr=rr,
                      exit_at=np.asarray(ex)), None, None
