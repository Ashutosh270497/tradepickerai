"""#1 Opening-range breakout (ORB).

Rules (defaults from phase1_findings.md):
* Two sessions a day: 00:00 UTC (every day) and the US equity open, 09:30 America/New_York
  (DST-aware, weekdays only).
* Opening range = high/low of the first `range_min` minutes after the anchor.
* Entry: first 1m CLOSE above the range high (long) or below the range low (short) within 120 minutes
  after the range completes; market order at the next 1m open. One trade per session.
* Stop: opposite side of the range. Target: `target_rr` x risk. Time stop: 30 minutes.
Tuned (in-sample only): range_min, target_rr.
Assumptions I added: the 120-minute breakout window; US anchor on weekdays only.
"""
import numpy as np

from core.engine import candidates, empty_candidates

NAME = "orb"
TITLE = "Opening-range breakout"
DAILY = False
GRID = {"range_min": [5, 10, 15, 30, 60], "target_rr": [1.0, 1.5, 2.0, 2.5, 3.0]}
DEFAULT = {"range_min": 15, "target_rr": 2.0}
BREAK_WINDOW = 120
TIME_STOP = 30


def build(m, p):
    R, rr = int(p["range_min"]), float(p["target_rr"])
    anchors = np.sort(np.concatenate([m.day_starts(), m.ny_time_index(9, 30, weekdays_only=True)]))
    fills, dirs, stops = [], [], []
    for a in anchors:
        r_end, w_end = a + R, a + R + BREAK_WINDOW
        if w_end + 1 >= m.n:
            continue
        hi, lo = m.h[a:r_end].max(), m.l[a:r_end].min()
        if hi - lo < 2 * m.tick:
            continue
        seg = m.c[r_end:w_end]
        up, dn = np.flatnonzero(seg > hi), np.flatnonzero(seg < lo)
        iu = up[0] if up.size else 1 << 30
        idn = dn[0] if dn.size else 1 << 30
        if iu == idn:
            continue
        if iu < idn:
            fills.append(r_end + iu + 1); dirs.append(1); stops.append(lo)
        else:
            fills.append(r_end + idn + 1); dirs.append(-1); stops.append(hi)
    if not fills:
        return empty_candidates(), None, None
    f = np.asarray(fills)
    return candidates(sig=f, fill=f, dir=np.asarray(dirs), stop=np.asarray(stops), rr=rr, maxb=TIME_STOP), None, None
