"""#6 SMC: liquidity sweep -> market structure shift -> fair value gap limit entry (5m, 1h bias).

Mechanical definitions (all causal):
* Swings: 5-bar fractals on 5m (a swing high is the highest high of the 5 bars either side). A swing is
  only usable once its 5 right-hand bars have CLOSED (no lookahead).
* 1h bias: last closed 1h close above EMA(50) -> longs only; below -> shorts only.
* Sweep (long case): a 5m bar trades below the most recent confirmed swing low. The sweep extreme
  is tracked while the setup is live.
* Structure shift: within 12 bars (1 hour) of the sweep, a 5m bar CLOSES above the most recent
  confirmed swing high, and the move left a bullish fair value gap (high[i-2] < low[i], middle candle
  bullish) at the break bar or the bar before. Bias must agree at that bar.
* Entry: buy limit at the gap midpoint, valid 60 minutes, 1-tick trade-through; cancelled if price
  reaches the target before filling.
* Stop: 1 tick beyond the sweep extreme. Target: `rr` x risk. No time stop (standard scenario).
* "silver_bullet" window: the gap must form between 03:00-04:00, 10:00-11:00 or 14:00-15:00
  America/New_York (DST-aware).
Tuned (in-sample only): rr, window.
Fixed choices I made: swing length 5, 12-bar sweep-to-shift limit, 60-minute order validity, 1-tick buffer.
"""
import numpy as np

from core.engine import LIMIT, candidates, empty_candidates, limit_fill_index
from core.indicators import confirmed_swings, ema

NAME = "smc_sweep_fvg"
TITLE = "SMC sweep + structure shift + FVG"
DAILY = False
GRID = {"rr": [1.0, 1.5, 2.0, 2.5, 3.0], "window": ["any", "silver_bullet"]}
DEFAULT = {"rr": 2.0, "window": "any"}
SWING_N = 5
MSS_BARS = 12
ORDER_MIN = 60
SB_WINDOWS = [(180, 240), (600, 660), (840, 900)]  # NY minutes of day


def _setups(m):
    """Detect setups once per market (independent of rr); returns list of
    (sig_1m, dir, mid, stop, in_sb_window)."""
    if "smc" in m._cache:
        return m._cache["smc"]
    b, h1 = m.bars(5), m.bars(60)
    o, h, l, c = (b[k].to_numpy() for k in ("o", "h", "l", "c"))
    act = b["act"].to_numpy()
    sh, sl = confirmed_swings(h, l, SWING_N)
    bias = m.to_1m(h1, np.sign(h1["c"] - ema(h1["c"], 50)).to_numpy())[act]
    nymin = m.ny_minute_of_day()[act - 5]           # NY time at the OPEN of the 5m break bar
    in_sb = np.zeros(len(b), bool)
    for s, e in SB_WINDOWS:
        in_sb |= (nymin >= s) & (nymin < e)
    tick = m.tick
    out = []
    st_l = st_s = 0
    sw_lo = sw_hi = 0.0
    bar_l = bar_s = 0
    for j in range(3, len(b)):
        # ---- long side
        if st_l == 0:
            if not np.isnan(sl[j - 1]) and l[j] < sl[j - 1]:
                st_l, sw_lo, bar_l = 1, l[j], j
        else:
            sw_lo = min(sw_lo, l[j])
            if j - bar_l > MSS_BARS:
                st_l = 0
            elif j > bar_l and not np.isnan(sh[j - 1]) and c[j] > sh[j - 1]:
                st_l = 0
                if bias[j] > 0:
                    if h[j - 2] < l[j] and c[j - 1] > o[j - 1]:
                        top, bot = l[j], h[j - 2]
                    elif h[j - 3] < l[j - 1] and c[j - 2] > o[j - 2]:
                        top, bot = l[j - 1], h[j - 3]
                    else:
                        top = None
                    if top is not None:
                        out.append((act[j], 1, (top + bot) / 2, sw_lo - tick, in_sb[j]))
        # ---- short side
        if st_s == 0:
            if not np.isnan(sh[j - 1]) and h[j] > sh[j - 1]:
                st_s, sw_hi, bar_s = 1, h[j], j
        else:
            sw_hi = max(sw_hi, h[j])
            if j - bar_s > MSS_BARS:
                st_s = 0
            elif j > bar_s and not np.isnan(sl[j - 1]) and c[j] < sl[j - 1]:
                st_s = 0
                if bias[j] < 0:
                    if l[j - 2] > h[j] and c[j - 1] < o[j - 1]:
                        top, bot = l[j - 2], h[j]
                    elif l[j - 3] > h[j - 1] and c[j - 2] < o[j - 2]:
                        top, bot = l[j - 3], h[j - 1]
                    else:
                        top = None
                    if top is not None:
                        out.append((act[j], -1, (top + bot) / 2, sw_hi + tick, in_sb[j]))
    m._cache["smc"] = out
    return out


def build(m, p):
    rr = float(p["rr"])
    sigs, fills, dirs, pxs, stops = [], [], [], [], []
    for s, d, mid, stop, sb in _setups(m):
        if p["window"] == "silver_bullet" and not sb:
            continue
        risk = (mid - stop) * d
        if risk <= 0:
            continue
        tgt = mid + d * rr * risk
        f = limit_fill_index(m.l, m.h, int(s), min(int(s) + ORDER_MIN, m.n), d, mid, m.tick, cancel_level=tgt)
        if f < 0:
            continue
        sigs.append(s); fills.append(f); dirs.append(d); pxs.append(mid); stops.append(stop)
    if not fills:
        return empty_candidates(), None, None
    return candidates(sig=np.asarray(sigs), fill=np.asarray(fills), dir=np.asarray(dirs), etype=LIMIT,
                      px=np.asarray(pxs), stop=np.asarray(stops), rr=rr), None, None
