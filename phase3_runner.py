"""Phase 3, step 3: full backtest of edge-screen survivors.

    python3 edge_screen.py && python3 phase3_runner.py

* Market: Binance USD-M 1h history 2020-01 -> 2026-11 (prices); Delta fees, tick, lot; funding = Delta
  actual from Nov 2024, Binance + measured gap before (see core.market.load_binance_market).
* Costs: taker (market orders, 0.01% slippage per side) = primary; maker (limit fills assumed,
  optimistic) and 0.03% slippage stress reported. 0.5% risk per trade, leverage cap 3x.
* Walk-forward: train 24 months, test 6 months, step 6 months. Parameters picked on each train
  window by combined BTC+ETH daily Sharpe (taker costs), then traded on the next 6 months.
  Only the stitched test windows (2022-01-01 onward) are reported.
* Benchmarks: buy-and-hold BTC, ETH and 50/50 over the same dates (price only, no funding); random
  entries (200 runs, same trade count / direction mix / stops / holding limit / costs).
* PASS (taker, base slippage): PF >= 1.3; net positive on BTC and ETH; above 95th pct of random;
  Sharpe AND CAGR/MaxDD better than 50/50 buy-and-hold; >= 30 trades and bootstrap 95% CI of
  expectancy (R) above zero. Criteria met but < 30 trades or CI touching zero -> LOW-CONFIDENCE.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from core.engine import STRESS_SLIP, Scenario, random_baseline, run
from core.market import load_binance_market
from strategies import trend_ma_4h

ROOT = Path(__file__).resolve().parent
LOGS, CHARTS = ROOT / "logs", ROOT / "charts"
ASSETS = ["BTCUSD", "ETHUSD"]
EQ0 = 10000.0  # per asset; at $1,000 Delta's 0.001 BTC lot forces skipping ~1/3 of BTC trades at 0.5% risk
RISK, MAX_LEV = 0.005, 3.0
WF_START, TRAIN_MONTHS, TEST_MONTHS = "2022-01-01", 24, 6
SCREEN_SPLIT = "2024-08-05"  # edge-screen IS/OOS boundary for the Binance data (2/3 point)
TAKER = Scenario("taker", slip=0.0001)
SCENARIOS = {"taker_0.01pct": TAKER, "taker_0.03pct": TAKER.with_slip(STRESS_SLIP),
             "maker_0.01pct": Scenario("maker", slip=0.0001, maker_fills=True),
             "maker_0.03pct": Scenario("maker", slip=STRESS_SLIP, maker_fills=True)}
SURVIVORS = [trend_ma_4h]


def ts(x) -> int:
    return pd.Timestamp(x, tz="UTC").value // 10**9


def unix_seconds(idx: pd.DatetimeIndex) -> np.ndarray:
    """UTC seconds, independent of the index's internal time unit (ns/us/s)."""
    return ((idx - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy(np.int64)


def daily_mtm(m, tr: pd.DataFrame, eq0: float, d0: pd.Timestamp, d1: pd.Timestamp) -> pd.Series:
    """Mark-to-market equity at each UTC day close (open positions valued at the 1h close before 00:00)."""
    days = pd.date_range(d0, d1, freq="D", tz="UTC")
    day_ts = unix_seconds(days)
    close_at = np.interp(day_ts, m.t + m.step, m.c)  # close of the bar ending at each day boundary
    eq = np.full(len(days), eq0, dtype=float)
    if tr is None or not len(tr):
        return pd.Series(eq, index=days)
    for r in tr.itertuples():
        t_in = m.t[r.fill]
        t_out = m.t[r.exit_bar] + (m.step if r.exit_kind != "time" else 0)
        held = (day_ts > t_in) & (day_ts < t_out)
        unreal = r.dir * (close_at[held] - r.entry) * r.qty - (r.fees / 2)
        eq[held] += unreal
        eq[day_ts >= t_out] += r.net
    return pd.Series(eq, index=days)


def perf(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 and eq.iloc[-1] > 0 else -1.0
    dd = (1 - eq / eq.cummax()).max()
    sd = r.std(ddof=1)
    down = np.sqrt((np.minimum(r, 0) ** 2).mean())
    return {"total_return_pct": total * 100, "cagr_pct": cagr * 100, "max_dd_pct": dd * 100,
            "cagr_over_maxdd": cagr / dd if dd > 0 else np.nan,
            "sharpe": r.mean() / sd * np.sqrt(365) if sd > 0 else 0.0,
            "sortino": r.mean() / down * np.sqrt(365) if down > 0 else 0.0}


def buy_hold(m, d0, d1) -> pd.Series:
    days = pd.date_range(d0, d1, freq="D", tz="UTC")
    px = np.interp(unix_seconds(days), m.t + m.step, m.c)
    return pd.Series(EQ0 * px / px[0], index=days)


def boot_ci(x: np.ndarray, n=10000, seed=11) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    if len(x) < 2:
        return (np.nan, np.nan)
    means = rng.choice(x, (n, len(x)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def folds(m_end_ts: int):
    out = []
    t = pd.Timestamp(WF_START, tz="UTC")
    end = pd.to_datetime(m_end_ts, unit="s", utc=True)
    while t < end:
        out.append((t - pd.DateOffset(months=TRAIN_MONTHS), t, min(t + pd.DateOffset(months=TEST_MONTHS), end)))
        t = t + pd.DateOffset(months=TEST_MONTHS)
    return out


def combined_sharpe(trs: dict, mk: dict, d0, d1) -> float:
    eq = sum(daily_mtm(mk[s], trs[s], EQ0, d0, d1) for s in ASSETS)
    return perf(eq)["sharpe"]


def evaluate(strat, mk) -> dict:
    keys = list(strat.GRID)
    grid = [dict(zip(keys, v)) for v in itertools.product(*strat.GRID.values())]
    built = {(json.dumps(p), s): strat.build(mk[s], p) for p in grid for s in ASSETS}
    end_ts = int(min(mk[s].t[-1] for s in ASSETS)) + 3600
    fl = folds(end_ts)
    wf_log, picks = [], []
    for tr0, te0, te1 in fl:
        best, best_sh = None, -np.inf
        for p in grid:
            k = json.dumps(p)
            trs = {s: run(mk[s], built[(k, s)][0], int(mk[s].idx(tr0.value // 10**9)), int(mk[s].idx(te0.value // 10**9)),
                          TAKER, equity0=EQ0, risk=RISK, max_lev=MAX_LEV) for s in ASSETS}
            sh = combined_sharpe(trs, mk, max(tr0, pd.Timestamp("2020-03-01", tz="UTC")), te0)
            n = sum(len(t) for t in trs.values())
            wf_log.append({"strategy": strat.NAME, "train_start": tr0.date(), "test_start": te0.date(), "params": k,
                           "train_sharpe": sh, "train_trades": n,
                           "train_net_usd": sum(t["net"].sum() for t in trs.values() if len(t))})
            if n >= 10 and (sh > best_sh or (sh == best_sh and p == strat.DEFAULT)):
                best, best_sh = p, sh
        picks.append((te0, te1, best or strat.DEFAULT))
    out = {"wf_log": pd.DataFrame(wf_log), "picks": picks, "scen": {}}
    d0, d1 = pd.Timestamp(WF_START, tz="UTC"), pd.to_datetime(end_ts, unit="s", utc=True).floor("D")
    for sname, sc in SCENARIOS.items():
        trades = {}
        for s in ASSETS:
            eq, free_from, parts = EQ0, 0, []
            for te0, te1, p in picks:
                a = max(int(mk[s].idx(te0.value // 10**9)), free_from)
                b = int(mk[s].idx(te1.value // 10**9))
                t = run(mk[s], built[(json.dumps(p), s)][0], a, b, sc, equity0=eq, risk=RISK, max_lev=MAX_LEV)
                if len(t):
                    t = t.assign(params=json.dumps(p), fold=str(te0.date()))
                    parts.append(t)
                    eq += t["net"].sum()
                    free_from = int(t["exit_bar"].iloc[-1]) + 1
            trades[s] = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        out["scen"][sname] = trades
    out["d0"], out["d1"] = d0, d1
    return out


def report(strat, mk, res) -> tuple[list[dict], dict]:
    d0, d1 = res["d0"], res["d1"]
    rows, extras = [], {}
    bh = {s: buy_hold(mk[s], d0, d1) for s in ASSETS}
    bh["50/50"] = (bh["BTCUSD"] + bh["ETHUSD"]) / 2
    bh_perf = {k: perf(v) for k, v in bh.items()}
    for sname, trades in res["scen"].items():
        eqs = {s: daily_mtm(mk[s], trades[s], EQ0, d0, d1) for s in ASSETS}
        eqs["combined"] = (eqs["BTCUSD"] + eqs["ETHUSD"]) / 2   # 50/50 of two $1,000 accounts, scaled to $1,000
        allt = pd.concat([t.assign(asset=s) for s, t in trades.items() if len(t)], ignore_index=True)
        segs = {"stitched OOS 2022-01 -> end": (d0, d1),
                "part A: 2022-01 -> 2024-08 (before screen OOS)": (d0, pd.Timestamp(SCREEN_SPLIT, tz="UTC")),
                "part B: 2024-08 -> end (overlaps screen OOS)": (pd.Timestamp(SCREEN_SPLIT, tz="UTC"), d1)}
        for seg, (a, b) in segs.items():
            for who in ASSETS + ["combined"]:
                t = allt if who == "combined" else allt[allt.asset == who]
                t = t[(t.entry_time >= a) & (t.entry_time < b)]
                eq = eqs[who].loc[a:b]
                pf = t.loc[t.net > 0, "net"].sum() / -t.loc[t.net <= 0, "net"].sum() if (t.net <= 0).any() else np.inf
                lo, hi = boot_ci(t["R"].to_numpy())
                bench = bh_perf["50/50" if who == "combined" else who] if seg.startswith("stitched") else perf(
                    (bh["50/50"] if who == "combined" else bh[who]).loc[a:b])
                sp = perf(eq)
                rows.append({"strategy": strat.NAME, "scenario": sname, "segment": seg, "asset": who,
                             "trades": len(t), "net_usd": t["net"].sum(), "gross_usd": t["gross"].sum(),
                             "fees_usd": t["fees"].sum(), "funding_usd": t["funding"].sum(),
                             "profit_factor": pf, "win_rate_pct": (t.net > 0).mean() * 100 if len(t) else np.nan,
                             "expectancy_R": t["R"].mean() if len(t) else np.nan, "R_ci95_lo": lo, "R_ci95_hi": hi,
                             "avg_hold_days": t["hold_min"].mean() / 1440 if len(t) else np.nan,
                             "avg_leverage": t["leverage"].mean() if len(t) else np.nan,
                             "stop_exits_pct": (t.exit_kind == "stop").mean() * 100 if len(t) else np.nan,
                             "long_share_pct": (t.dir > 0).mean() * 100 if len(t) else np.nan,
                             **{f"strat_{k}": v for k, v in sp.items()}, **{f"bh_{k}": v for k, v in bench.items()}})
        extras[sname] = {"eqs": eqs, "trades": trades}
    extras["bh"] = bh
    return rows, extras


def main():
    LOGS.mkdir(exist_ok=True)
    CHARTS.mkdir(exist_ok=True)
    mk = {s: load_binance_market(s) for s in ASSETS}
    all_rows, verdicts, rb_rows = [], [], []
    for strat in SURVIVORS:
        res = evaluate(strat, mk)
        res["wf_log"].to_csv(LOGS / f"phase3_walkforward_{strat.NAME}.csv", index=False)
        rows, ex = report(strat, mk, res)
        all_rows += rows
        # random baseline on the stitched OOS, primary scenario
        tr = ex["taker_0.01pct"]["trades"]
        sims, pct = {}, {}
        for s in ASSETS:
            a, b = int(mk[s].idx(res["d0"].value // 10**9)), int(mk[s].idx(res["d1"].value // 10**9))
            sims[s] = random_baseline(mk[s], tr[s], a, b, TAKER, n_sims=200, seed=17 + ASSETS.index(s))
        sims["combined"] = sims["BTCUSD"] + sims["ETHUSD"]
        strat_R = {s: tr[s]["R"].sum() for s in ASSETS}
        strat_R["combined"] = sum(strat_R.values())
        for k in sims:
            pct[k] = float((sims[k] < strat_R[k]).mean() * 100)
            rb_rows.append({"strategy": strat.NAME, "asset": k, "strategy_net_R": strat_R[k], "percentile": pct[k],
                            "random_p5": np.percentile(sims[k], 5), "random_median": np.median(sims[k]),
                            "random_p95": np.percentile(sims[k], 95)})
        df = pd.DataFrame(rows)
        main_ = df[(df.scenario == "taker_0.01pct") & (df.segment.str.startswith("stitched"))].set_index("asset")
        c = main_.loc["combined"]
        checks = {"pf_ge_1.3": c.profit_factor >= 1.3,
                  "btc_positive": main_.loc["BTCUSD"].net_usd > 0, "eth_positive": main_.loc["ETHUSD"].net_usd > 0,
                  "beats_random_95": pct["combined"] > 95,
                  "sharpe_gt_buyhold": c.strat_sharpe > c.bh_sharpe,
                  "ret_dd_gt_buyhold": c.strat_cagr_over_maxdd > c.bh_cagr_over_maxdd}
        enough = c.trades >= 30 and c.R_ci95_lo > 0
        verdict = ("PASS" if enough else "LOW-CONFIDENCE") if all(checks.values()) else "FAIL"
        verdicts.append({"strategy": strat.NAME, "title": strat.TITLE, **checks, "trades": int(c.trades),
                         "trades_ge_30": c.trades >= 30, "R_ci95": f"[{c.R_ci95_lo:.3f}, {c.R_ci95_hi:.3f}]",
                         "verdict": verdict,
                         "params_by_fold": "; ".join(f"{a.date()}: {json.dumps(p)}" for a, _, p in res["picks"])})
        plot(strat, ex, res, verdict)
    pd.DataFrame(all_rows).to_csv(ROOT / "phase3_results.csv", index=False)
    pd.DataFrame(rb_rows).to_csv(LOGS / "phase3_random_baseline.csv", index=False)
    v = pd.DataFrame(verdicts)
    v.to_csv(ROOT / "phase3_verdicts.csv", index=False)
    print(v.T.to_string())


def plot(strat, ex, res, verdict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(17, 5))
    for ax, who in zip(axes, ["BTCUSD", "ETHUSD", "combined"]):
        for sname, col in (("taker_0.01pct", "#1f4e79"), ("taker_0.03pct", "#c55a11"), ("maker_0.01pct", "#548235")):
            e = ex[sname]["eqs"][who]
            ax.plot(e.index.tz_localize(None), 100 * (e / e.iloc[0] - 1), color=col, lw=1.3, label=f"strategy {sname}")
        b = ex["bh"]["50/50" if who == "combined" else who]
        ax2 = ax.twinx()
        ax2.plot(b.index.tz_localize(None), 100 * (b / b.iloc[0] - 1), color="#888", lw=1, ls="--", label="buy & hold (right axis)")
        ax2.set_ylabel("Buy & hold return (%)", color="#666")
        ax.axvline(pd.Timestamp(SCREEN_SPLIT), color="#b00", lw=0.8, ls=":")
        ax.set_title(f"{who}: stitched walk-forward OOS")
        ax.set_ylabel("Strategy return (%)")
        ax.grid(alpha=0.3)
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, fontsize=7, loc="upper left")
    fig.suptitle(f"{strat.TITLE}: 0.5% risk/trade, 3x cap, after fees, slippage and funding - verdict {verdict}"
                 f"  (red dotted line = start of edge-screen OOS)")
    fig.tight_layout()
    fig.savefig(CHARTS / f"phase3_{strat.NAME}.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    main()
