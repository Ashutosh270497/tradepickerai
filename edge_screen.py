"""Phase 3, step 2: zero-cost edge screen (no fees, no slippage).

    python3 edge_screen.py        -> edge_screen.csv, logs/edge_screen_summary.md

Data
* 15m and 1h: Delta Exchange BTCUSD/ETHUSD perpetual LTP candles (resampled from 1m),
  2024-11-23 -> 2026-11-23. Funding: Delta's FUNDING:<symbol> history.
* 4h and 1D: Binance USD-M BTCUSDT/ETHUSDT perpetual candles (resampled from 1h archive files),
  2020-01-01 -> 2026-11-21. Funding: Binance archive (to 2026-10-31). Signal research only.
* Split by time: first 2/3 in-sample (IS), last 1/3 out-of-sample (OOS).

Method (one row per signal config x asset x period, plus BTC+ETH pooled)
* A signal is read at the CLOSE of bar t: +1 long, -1 short, 0 nothing. Its trade is the forward
  close-to-close return over the next M bars. Events are NON-OVERLAPPING: after an event at t, the
  next event can start at t+M at the earliest (one position at a time, like a strategy).
* gross_edge = mean(direction x forward return) = gross return per trade before costs.
* excess = mean(direction x (forward return - unconditional mean M-bar return of that period)):
  what the signal adds over simply holding. t-stat and two-sided p-value are on `excess`.
* Calendar signals are tested over 1 bar (that hour / 4h block / day). Calendar and funding
  signals have no natural direction; their direction is chosen from the
  pooled IS data and then applied unchanged OOS (their IS numbers are therefore biased upward).
* Multiple testing: Benjamini-Hochberg on the pooled OOS p-values over all configs (q <= 0.05).
* A signal SURVIVES if: pooled OOS gross edge >= 0.36% per trade (3 x ~0.12% taker round trip),
  OOS gross edge > 0 on BTC and on ETH, and BH-significant.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

from core import binance_data as bd
from core.indicators import atr, ema, rsi, sma
from core.market import load_market

ROOT = Path(__file__).resolve().parent
COST_RT = 0.0012          # ~taker round trip used for the threshold (Phase 2 model: 0.138%)
EDGE_MIN = 3 * COST_RT    # 0.36% gross per trade
Q = 0.05
DELTA_START, DELTA_END = "2024-11-23", "2026-11-23"
TF = {  # bars: lookbacks L and horizons H
    "15m": {"src": "delta", "min": 15, "L": [4, 16, 96], "H": [4, 16, 96]},
    "1h": {"src": "delta", "min": 60, "L": [4, 24, 120], "H": [4, 24, 120]},
    "4h": {"src": "binance", "min": 240, "L": [6, 30, 120], "H": [6, 30, 120]},
    "1D": {"src": "binance", "min": 1440, "L": [5, 20, 60], "H": [1, 5, 20]},
}
ASSETS = ["BTCUSD", "ETHUSD"]


# ---------------------------------------------------------------- data
def resample(df: pd.DataFrame, minutes: int, base_min: int) -> pd.DataFrame:
    step = minutes * 60
    key = df["time"] // step * step
    g = df.assign(key=key).groupby("key").agg(o=("open", "first"), h=("high", "max"), l=("low", "min"),
                                               c=("close", "last"), v=("volume", "sum"), n=("open", "size"))
    g = g[g["n"] == minutes // base_min].drop(columns="n").reset_index().rename(columns={"key": "time"})
    return g


def load_tf(tf: str, sym: str):
    """Return (bars, funding_events) where funding_events = DataFrame(time=settlement UTC s, rate=fraction)."""
    cfg = TF[tf]
    if cfg["src"] == "delta":
        m = load_market(sym)
        b = m.bars(cfg["min"])[["time", "o", "h", "l", "c", "v"]].copy()
        fund = pd.DataFrame({"time": m.t[m.settle_idx], "rate": m.settle_rate})
        start, end = pd.Timestamp(DELTA_START, tz="UTC"), pd.Timestamp(DELTA_END, tz="UTC")
    else:
        raw = pd.read_parquet(bd.path(sym))
        b = resample(raw, cfg["min"], 60)
        f = pd.read_parquet(bd.funding_path(sym))
        fund = f[["time", "rate"]].copy()
        start = pd.to_datetime(raw["time"].iloc[0], unit="s", utc=True)
        end = pd.to_datetime(raw["time"].iloc[-1] + 3600, unit="s", utc=True)
    b = b[b["time"] < end.value // 10**9].reset_index(drop=True)
    return b, fund, start, end


# ---------------------------------------------------------------- signals
def trailing_extremes(vals: np.ndarray, window: int, lo_q=0.1, hi_q=0.9):
    s = pd.Series(vals)
    lo = s.shift(1).rolling(window, min_periods=window).quantile(lo_q).to_numpy()
    hi = s.shift(1).rolling(window, min_periods=window).quantile(hi_q).to_numpy()
    return vals > hi, vals < lo


def directional_signals(b: pd.DataFrame, tf: str) -> dict:
    """Pre-specified-direction signals: name -> (family, params, s array)."""
    c, h, l = b["c"], b["h"], b["l"]
    out = {}
    for L in TF[tf]["L"]:
        r = c / c.shift(L) - 1
        out[f"tsmom_L{L}"] = ("1 time-series momentum", f"lookback={L}", np.sign(r).fillna(0).to_numpy())
    for n in (50, 100, 200):
        ma = sma(c, n)
        out[f"price_vs_ma{n}"] = ("2 trend filter", f"price vs SMA{n}", np.sign(c - ma).fillna(0).to_numpy())
        out[f"ma{n}_slope"] = ("2 trend filter", f"SMA{n} slope over 10 bars",
                               np.sign(ma - ma.shift(10)).fillna(0).to_numpy())
    for n in (20, 55):
        hi, lo = h.rolling(n).max().shift(1), l.rolling(n).min().shift(1)
        out[f"donchian{n}"] = ("3 Donchian breakout", f"{n}-bar close breakout",
                               np.where(c > hi, 1, np.where(c < lo, -1, 0)).astype(float))
    r2, r14 = rsi(c, 2), rsi(c, 14)
    out["rsi2_10_90"] = ("4 mean reversion", "RSI(2) <10 long, >90 short",
                         np.where(r2 < 10, 1, np.where(r2 > 90, -1, 0)).astype(float))
    out["rsi14_30_70"] = ("4 mean reversion", "RSI(14) <30 long, >70 short",
                          np.where(r14 < 30, 1, np.where(r14 > 70, -1, 0)).astype(float))
    d = (c - sma(c, 20)) / atr(h, l, c, 14)
    for k in (2, 3):
        out[f"ma20_dist_{k}atr"] = ("4 mean reversion", f"close {k}+ ATR from SMA20, fade",
                                    np.where(d < -k, 1, np.where(d > k, -1, 0)).astype(float))
    if tf == "15m":
        a, bb = ema(c, 9), ema(c, 21)
        st = np.sign(a - bb).to_numpy()
        cross = np.r_[0, np.where(st[1:] != st[:-1], st[1:], 0)]
        out["ema9_21_cross"] = ("7 reference", "EMA 9/21 cross (Phase 1 strategy)", cross.astype(float))
    if tf == "4h":
        a, bb = ema(c, 50), ema(c, 200)
        st = np.sign(a - bb).to_numpy()
        cross = np.r_[0, np.where(st[1:] != st[:-1], st[1:], 0)]
        out["ema50_200_cross"] = ("7 reference", "EMA 50/200 cross (best earlier 4h result)", cross.astype(float))
    return out


def bucket_signals(b: pd.DataFrame, fund: pd.DataFrame, tf: str) -> dict:
    """Signals without a natural direction: name -> (family, params, boolean mask). Direction set in IS."""
    out = {}
    nxt = pd.to_datetime(b["time"] + TF[tf]["min"] * 60, unit="s", utc=True)  # open time of the NEXT bar
    if tf == "1h":
        for hr in range(24):
            out[f"hour_{hr:02d}"] = ("5 calendar", f"next 1h bar starts {hr:02d}:00 UTC", (nxt.dt.hour == hr).to_numpy())
    if tf == "4h":
        for hr in range(0, 24, 4):
            out[f"block_{hr:02d}"] = ("5 calendar", f"next 4h bar starts {hr:02d}:00 UTC", (nxt.dt.hour == hr).to_numpy())
    if tf == "1D":
        for d, name in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"]):
            out[f"dow_{name}"] = ("5 calendar", f"next day is {name}", (nxt.dt.dayofweek == d).to_numpy())
        out["weekend"] = ("5 calendar", "next day is Sat or Sun", (nxt.dt.dayofweek >= 5).to_numpy())
    # funding extremes, trailing 90-day percentiles (no lookahead)
    if tf in ("1h", "4h", "1D"):
        f = fund.sort_values("time").reset_index(drop=True)
        if tf == "1D":
            f = f.assign(day=f["time"] // 86400 * 86400).groupby("day")["rate"].mean().reset_index()
            f.columns = ["time", "rate"]
            bar_time = f["time"].to_numpy()              # daily bar opening at that day
            window = 90
        else:
            bar_time = f["time"].to_numpy() - TF[tf]["min"] * 60   # bar that CLOSES at the settlement
            window = 270                                  # 90 days of 8h readings
        top, bot = trailing_extremes(f["rate"].to_numpy(), window)
        pos = pd.Index(b["time"]).get_indexer(bar_time)
        for name, mask in (("funding_top10", top), ("funding_bottom10", bot)):
            arr = np.zeros(len(b), bool)
            ok = (pos >= 0) & mask
            arr[pos[ok]] = True
            out[name] = ("6 funding extremes", f"{name.split('_')[1]} 10% of trailing-90d funding", arr)
    return out


# ---------------------------------------------------------------- statistics
def events(s: np.ndarray, M: int, n: int) -> np.ndarray:
    out, nxt = [], -1
    for t in np.flatnonzero(s != 0):
        if t >= nxt and t + M < n:
            out.append(t)
            nxt = t + M
    return np.asarray(out, dtype=np.int64)


def summarize(dirs, fwd, mu) -> dict:
    n = len(fwd)
    if n == 0:
        return {"n": 0}
    g = dirs * fwd
    x = dirs * (fwd - mu)
    sd = x.std(ddof=1) if n > 1 else np.nan
    t = x.mean() / (sd / np.sqrt(n)) if n > 1 and sd > 0 else np.nan
    p = 2 * sps.t.sf(abs(t), n - 1) if np.isfinite(t) else np.nan
    lo, sh = dirs > 0, dirs < 0
    return {"n": n, "n_long": int(lo.sum()), "n_short": int(sh.sum()),
            "mean_fwd_long_pct": fwd[lo].mean() * 100 if lo.any() else np.nan,
            "mean_fwd_short_pct": fwd[sh].mean() * 100 if sh.any() else np.nan,
            "uncond_mean_pct": mu * 100 if np.isscalar(mu) else np.mean(mu) * 100,
            "gross_edge_pct": g.mean() * 100, "excess_pct": x.mean() * 100,
            "hit_rate_pct": (g > 0).mean() * 100, "t_stat": t, "p_value": p}


def bh(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, float)
    q = np.full_like(p, np.nan)
    ok = np.isfinite(p)
    pv = p[ok]
    order = np.argsort(pv)
    ranked = pv[order] * len(pv) / (np.arange(len(pv)) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty_like(pv)
    out[order] = np.minimum(ranked, 1.0)
    q[ok] = out
    return q


def main():
    rows = []
    for tf, cfg in TF.items():
        data = {s: load_tf(tf, s) for s in ASSETS}
        # common split by time for both assets
        start, end = data["BTCUSD"][2], data["BTCUSD"][3]
        split = start + (end - start) * 2 / 3
        s_ts, e_ts, sp_ts = (x.value // 10**9 for x in (start, end, split))
        sigs = {s: directional_signals(data[s][0], tf) for s in ASSETS}
        bucks = {s: bucket_signals(data[s][0], data[s][1], tf) for s in ASSETS}
        for M in sorted(set(cfg["H"]) | ({1} if tf in ("1h", "4h", "1D") else set())):
            fw, mu, per = {}, {}, {}
            for s in ASSETS:
                b = data[s][0]
                c = b["c"].to_numpy()
                f = np.full(len(c), np.nan)
                f[:-M] = c[M:] / c[:-M] - 1
                tt = b["time"].to_numpy()
                bar_s = cfg["min"] * 60
                is_mask = (tt >= s_ts) & (tt + (M + 1) * bar_s <= sp_ts)
                oos_mask = (tt >= sp_ts) & (tt + (M + 1) * bar_s <= e_ts)
                fw[s] = f
                per[s] = {"IS": is_mask, "OOS": oos_mask}
                mu[s] = {k: np.nanmean(f[v]) for k, v in per[s].items()}

            def run_cfg(name, family, params, sarr: dict, chosen_dir: str):
                ev = {}
                for s in ASSETS:
                    e = events(sarr[s], M, len(fw[s]))
                    ev[s] = e
                for period in ("IS", "OOS"):
                    pooled_d, pooled_f, pooled_mu = [], [], []
                    for s in ASSETS:
                        e = ev[s][per[s][period][ev[s]]]
                        d, f = sarr[s][e], fw[s][e]
                        rows.append({"config": f"{tf}|{name}|H{M}", "family": family, "signal": name, "params": params,
                                     "timeframe": tf, "horizon_bars": M, "horizon_hours": M * cfg["min"] / 60,
                                     "asset": s, "period": period, "direction": chosen_dir,
                                     "source": "Delta" if cfg["src"] == "delta" else "Binance",
                                     **summarize(d, f, mu[s][period])})
                        pooled_d.append(d); pooled_f.append(f); pooled_mu.append(np.full(len(f), mu[s][period]))
                    d, f, m_ = (np.concatenate(x) for x in (pooled_d, pooled_f, pooled_mu))
                    rows.append({"config": f"{tf}|{name}|H{M}", "family": family, "signal": name, "params": params,
                                 "timeframe": tf, "horizon_bars": M, "horizon_hours": M * cfg["min"] / 60,
                                 "asset": "pooled", "period": period, "direction": chosen_dir,
                                 "source": "Delta" if cfg["src"] == "delta" else "Binance", **summarize(d, f, m_)})

            for name in sigs["BTCUSD"]:
                if M not in cfg["H"]:
                    continue
                fam, params, _ = sigs["BTCUSD"][name]
                run_cfg(name, fam, params, {s: sigs[s][name][2] for s in ASSETS}, "pre-specified")
            for name in bucks["BTCUSD"]:
                fam, params, _ = bucks["BTCUSD"][name]
                if fam.startswith("5") and M != 1:
                    continue  # calendar effects are tested over their natural unit only (1 bar)
                if fam.startswith("6") and M not in cfg["H"]:
                    continue
                # direction from pooled IS excess
                xs = []
                for s in ASSETS:
                    mask = bucks[s][name][2]
                    e = events(mask.astype(float), M, len(fw[s]))
                    e = e[per[s]["IS"][e]]
                    xs.append(fw[s][e] - mu[s]["IS"])
                xs = np.concatenate(xs)
                d0 = 1.0 if (len(xs) and xs.mean() >= 0) else -1.0
                run_cfg(name, fam, params, {s: bucks[s][name][2].astype(float) * d0 for s in ASSETS},
                        f"chosen in IS: {'long' if d0 > 0 else 'short'}")
        print(f"{tf}: done", flush=True)

    df = pd.DataFrame(rows)
    pooled_oos = df[(df.asset == "pooled") & (df.period == "OOS")].copy()
    pooled_is = df[(df.asset == "pooled") & (df.period == "IS")].copy()
    pooled_oos["q_value_oos"] = bh(pooled_oos["p_value"].to_numpy())
    pooled_is["q_value_is"] = bh(pooled_is["p_value"].to_numpy())
    df = df.merge(pooled_oos[["config", "q_value_oos"]], on="config", how="left") \
           .merge(pooled_is[["config", "q_value_is"]], on="config", how="left")
    # survivor rule
    piv = df[df.period == "OOS"].pivot_table(index="config", columns="asset", values="gross_edge_pct")
    q = df[(df.asset == "pooled") & (df.period == "OOS")].set_index("config")["q_value_oos"]
    surv = (piv["pooled"] >= EDGE_MIN * 100) & (piv["BTCUSD"] > 0) & (piv["ETHUSD"] > 0) & (q.reindex(piv.index) <= Q)
    df["edge_ok"] = df["config"].map(piv["pooled"] >= EDGE_MIN * 100)
    df["same_sign_ok"] = df["config"].map((piv["BTCUSD"] > 0) & (piv["ETHUSD"] > 0))
    df["bh_ok"] = df["config"].map(q <= Q)
    df["survivor"] = df["config"].map(surv)
    df.to_csv(ROOT / "edge_screen.csv", index=False)

    n_cfg = df["config"].nunique()
    n_rows = len(df)
    po = df[(df.asset == "pooled") & (df.period == "OOS")]
    pi = df[(df.asset == "pooled") & (df.period == "IS")]
    lines = [f"configs: {n_cfg}; rows (config x asset/pooled x IS/OOS): {n_rows}",
             f"individual asset-level tests: {len(df[df.asset != 'pooled'])}",
             f"pooled OOS raw p<0.05: {(po.p_value < 0.05).sum()} (expected by chance {0.05 * n_cfg:.1f})",
             f"pooled IS raw p<0.05: {(pi.p_value < 0.05).sum()} (expected by chance {0.05 * n_cfg:.1f})",
             f"pooled OOS BH q<=0.05: {(po.q_value_oos <= Q).sum()}; pooled IS BH q<=0.05: {(pi.q_value_is <= Q).sum()}",
             f"edge_ok: {po.edge_ok.sum()}  same_sign_ok: {po.same_sign_ok.sum()}  bh_ok: {po.bh_ok.sum()}  SURVIVORS: {po.survivor.sum()}"]
    print("\n".join(lines))
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "edge_screen_summary.md").write_text("\n".join(f"- {x}" for x in lines) + "\n")


if __name__ == "__main__":
    main()
