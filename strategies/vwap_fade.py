"""#3 Session VWAP band fade (maker entries).

Rules (defaults from phase1_findings.md + Phase 2 brief):
* VWAP anchored at 00:00 UTC on 1m typical price (H+L+C)/3, volume-weighted; sigma = volume-weighted
  standard deviation of typical price around VWAP since the anchor.
* While flat (and at least 60 minutes after the anchor), resting limit orders at VWAP - k*sigma (buy)
  and VWAP + k*sigma (sell), re-priced every minute from the previous bar's values. Fills need a
  1-tick trade-through.
* Hard stop (fixed, not tuned): the 3-sigma band at the time of the fill.
* Exit: resting limit at VWAP (re-priced every minute) or at the 1-sigma band on the VWAP side;
  30-minute time stop.
Tuned (in-sample only): band_k, exit.
Assumption I added: the 60-minute warm-up after the 00:00 UTC anchor.
"""
import numpy as np
import pandas as pd

from core.engine import LIMIT, candidates, empty_candidates

NAME = "vwap_fade"
TITLE = "VWAP band fade"
DAILY = False
GRID = {"band_k": [1.5, 1.75, 2.0, 2.25, 2.5], "exit": ["vwap", "1sigma"]}
DEFAULT = {"band_k": 2.0, "exit": "vwap"}
WARMUP = 60
STOP_K = 3.0
TIME_STOP = 30


def session_vwap(m):
    if "vwap" not in m._cache:
        tp = (m.h + m.l + m.c) / 3
        day = m.t // 86400
        v = np.where(m.v > 0, m.v, 0.0)
        g = pd.DataFrame({"d": day, "v": v, "pv": v * tp, "pv2": v * tp * tp}).groupby("d")
        cv, cpv, cpv2 = (g[k].cumsum().to_numpy() for k in ("v", "pv", "pv2"))
        with np.errstate(invalid="ignore", divide="ignore"):
            vw = cpv / cv
            sd = np.sqrt(np.maximum(cpv2 / cv - vw * vw, 0.0))
        m._cache["vwap"] = (vw, sd)
    return m._cache["vwap"]


def build(m, p):
    k = float(p["band_k"])
    vw, sd = session_vwap(m)
    vw_prev = np.concatenate([[np.nan], vw[:-1]])   # known at the open of bar j
    sd_prev = np.concatenate([[np.nan], sd[:-1]])
    mins = (m.t % 86400) // 60
    ok = (mins >= WARMUP) & (sd_prev > 0) & np.isfinite(vw_prev)
    lo_band, hi_band = vw_prev - k * sd_prev, vw_prev + k * sd_prev
    long_ = ok & (m.l <= lo_band - m.tick)
    short = ok & (m.h >= hi_band + m.tick)
    both = long_ & short
    long_ &= ~both
    short &= ~both
    jl, js = np.flatnonzero(long_), np.flatnonzero(short)
    if not (jl.size or js.size):
        return empty_candidates(), None, None
    j = np.concatenate([jl, js])
    d = np.concatenate([np.ones(jl.size, np.int64), -np.ones(js.size, np.int64)])
    px = np.concatenate([lo_band[jl], hi_band[js]])
    stop = np.concatenate([vw_prev[jl] - STOP_K * sd_prev[jl], vw_prev[js] + STOP_K * sd_prev[js]])
    if p["exit"] == "vwap":
        dyn_l = dyn_s = vw_prev
    else:
        dyn_l, dyn_s = vw_prev - sd_prev, vw_prev + sd_prev
    c = candidates(sig=j, fill=j, dir=d, etype=LIMIT, px=px, stop=stop, dyn=1, maxb=TIME_STOP)
    return c, dyn_l, dyn_s
