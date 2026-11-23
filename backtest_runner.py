"""Reproduce every Phase 2 result with one command:

    python3 backtest_runner.py              # uses cached data in data/
    python3 backtest_runner.py --download   # refresh 2 years of Delta candles + funding first

Protocol
* Test window 2024-11-23 -> 2026-11-23 (UTC). In-sample (IS) = first 16 months (to 2026-03-23),
  out-of-sample (OOS) = last 8 months. Data before 2024-11-23 is indicator warm-up only.
* Each strategy: every combination of its <=2 tuned parameters (<=5 values each) is run on IS and OOS
  for BTCUSD and ETHUSD under 3 fee scenarios. The variant is chosen PER SCENARIO on IS only
  (highest combined BTC+ETH net R among variants with enough IS trades). OOS numbers of the other
  variants are logged for transparency but never used for selection.
* Selected variants: OOS at base slippage (0.01%/side) and stress slippage (0.03%/side), plus a
  200-run random-entry baseline (same trade count, direction mix, stop/target/time limits, costs).
* PASS (OOS, base slippage): profit factor >= 1.2, >= 100 trades (>= 50 for one-trade-a-day
  strategies, flagged low sample), net positive on BTC and on ETH, above the 95th percentile of the
  random baseline. Strategy verdict: PASS if the standard-fee scenario passes, CONDITIONAL if only an
  offer scenario passes, otherwise FAIL.

Outputs: results.csv, logs/variants_log.csv, logs/random_baseline.csv, logs/quarterly.csv,
logs/trades/*.csv.gz, charts/<strategy>.png, logs/summary.md
"""
from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
import time
import zlib
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from core.engine import SCENARIOS, STRESS_SLIP, random_baseline, run
from core.market import load_market
from core.metrics import quarterly, stats
from strategies import ALL, BY_NAME

ROOT = Path(__file__).resolve().parent
LOGS, CHARTS = ROOT / "logs", ROOT / "charts"
SYMBOLS = ["BTCUSD", "ETHUSD"]
TEST_START, SPLIT, TEST_END = "2024-11-23", "2026-03-23", "2026-11-23"
N_SIMS = 200
EQUITY0 = 1000.0


def ts(s: str) -> int:
    return pd.Timestamp(s, tz="UTC").value // 10**9


def bounds(m):
    a, b, c = (int(m.idx(ts(x))) for x in (TEST_START, SPLIT, TEST_END))
    return {"IS": (a, b), "OOS": (b, c)}


def window(per: str):
    return (pd.Timestamp(TEST_START, tz="UTC"), pd.Timestamp(SPLIT, tz="UTC")) if per == "IS" else \
        (pd.Timestamp(SPLIT, tz="UTC"), pd.Timestamp(TEST_END, tz="UTC"))


def combined(trs: dict) -> pd.DataFrame:
    df = pd.concat([t.assign(symbol=s) for s, t in trs.items() if len(t)], ignore_index=True)
    return df.sort_values("exit_time").reset_index(drop=True) if len(df) else df


def all_stats(trs: dict, per: str) -> dict:
    w0, w1 = window(per)
    out = {s: stats(t, w0, w1, EQUITY0) for s, t in trs.items()}
    out["combined"] = stats(combined(trs), w0, w1, EQUITY0 * len(trs))
    return out


def evaluate(name: str) -> dict:
    t_start = time.time()
    s = BY_NAME[name]
    mk = {sym: load_market(sym) for sym in SYMBOLS}
    bd = {sym: bounds(m) for sym, m in mk.items()}
    keys = list(s.GRID)
    grid = [dict(zip(keys, v)) for v in itertools.product(*s.GRID.values())]
    min_trades = 50 if s.DAILY else 100
    var_rows, store = [], {}
    for vid, p in enumerate(grid):
        built = {sym: s.build(m, p) for sym, m in mk.items()}
        for sc in SCENARIOS:
            for per in ("IS", "OOS"):
                trs = {}
                for sym, m in mk.items():
                    c, dl, ds = built[sym]
                    a, b = bd[sym][per]
                    trs[sym] = run(m, c, a, b, sc, dl, ds, equity0=EQUITY0)
                store[(vid, sc.name, per)] = trs
                for sym, st in all_stats(trs, per).items():
                    var_rows.append({"strategy": name, "variant": vid, "params": json.dumps(p),
                                     "is_default": p == s.DEFAULT, "scenario": sc.name, "period": per,
                                     "symbol": sym, "used_for_selection": per == "IS", **st})
    var = pd.DataFrame(var_rows)

    res_rows, rb_rows, q_rows, curves = [], [], [], {}
    LOGS.joinpath("trades").mkdir(parents=True, exist_ok=True)
    for sc in SCENARIOS:
        isc = var[(var.scenario == sc.name) & (var.period == "IS") & (var.symbol == "combined")]
        elig = isc[isc.trades >= min_trades]
        pick = (elig if len(elig) else isc).sort_values(["net_R", "is_default"], ascending=False).iloc[0]
        vid, p = int(pick.variant), json.loads(pick.params)
        var.loc[(var.variant == vid) & (var.scenario == sc.name), "selected"] = True
        trs_is, trs_oos = store[(vid, sc.name, "IS")], store[(vid, sc.name, "OOS")]
        # stress slippage, OOS
        stress = sc.with_slip(STRESS_SLIP)
        trs_st = {}
        for sym, m in mk.items():
            c, dl, ds = s.build(m, p)
            a, b = bd[sym]["OOS"]
            trs_st[sym] = run(m, c, a, b, stress, dl, ds, equity0=EQUITY0)
        # random baseline, OOS base slippage
        sims, pct = {}, {}
        for sym, m in mk.items():
            a, b = bd[sym]["OOS"]
            sims[sym] = random_baseline(m, trs_oos[sym], a, b, sc, n_sims=N_SIMS, seed=zlib.crc32(f"{name}|{sc.name}|{sym}".encode()))
        sims["combined"] = sims["BTCUSD"] + sims["ETHUSD"]
        oos_stats = all_stats(trs_oos, "OOS")
        for sym in sims:
            strat_r = oos_stats[sym].get("net_R", 0.0)
            pct[sym] = float((sims[sym] < strat_r).mean() * 100)
            rb_rows.append({"strategy": name, "scenario": sc.name, "symbol": sym, "trades": oos_stats[sym]["trades"],
                            "strategy_net_R": strat_r, "percentile": pct[sym], "random_p5": np.percentile(sims[sym], 5),
                            "random_median": np.median(sims[sym]), "random_p95": np.percentile(sims[sym], 95),
                            "random_mean": sims[sym].mean()})
        co = oos_stats["combined"]
        checks = {
            "pf_ok": co.get("profit_factor", 0) >= 1.2,
            "trades_ok": co.get("trades", 0) >= min_trades,
            "btc_pos": oos_stats["BTCUSD"].get("net_usd", -1) > 0,
            "eth_pos": oos_stats["ETHUSD"].get("net_usd", -1) > 0,
            "beats_random_95": pct["combined"] > 95,
        }
        passed = all(checks.values())
        for per, trs in (("IS", trs_is), ("OOS", trs_oos), ("OOS_stress_0.03pct", trs_st)):
            st_all = all_stats(trs, "IS" if per == "IS" else "OOS")
            for sym, st in st_all.items():
                res_rows.append({"strategy": name, "title": s.TITLE, "scenario": sc.name, "period": per,
                                 "symbol": sym, "params": json.dumps(p), "variant": vid,
                                 "selected_with_enough_IS_trades": bool(len(elig)),
                                 "low_sample_flag": bool(s.DAILY),
                                 "random_percentile": pct.get(sym) if per == "OOS" else np.nan,
                                 **({**checks, "scenario_pass": passed} if per == "OOS" and sym == "combined" else {}),
                                 **st})
            for sym, t in trs.items():
                if per != "OOS_stress_0.03pct":
                    q = quarterly(t, EQUITY0)
                    if len(q):
                        q_rows.append(q.assign(strategy=name, scenario=sc.name, period=per, symbol=sym))
                    t.to_csv(LOGS / "trades" / f"{name}_{sc.name}_{per}_{sym}.csv.gz", index=False)
                    curves[(sc.name, per, sym)] = t[["exit_time", "net"]] if len(t) else None
    # hindsight check (NOT a valid selection method): best variant by OOS profit factor per scenario
    hind = var[(var.period == "OOS") & (var.symbol == "combined")].sort_values("profit_factor", ascending=False)
    hind = hind.groupby("scenario", sort=False).head(1).assign(note="best OOS variant in hindsight; not used")
    var["selected"] = var.get("selected", False)
    var["selected"] = var["selected"].fillna(False)
    res = pd.DataFrame(res_rows)
    std_pass = bool(res[(res.scenario == "standard") & (res.period == "OOS") & (res.symbol == "combined")]["scenario_pass"].iloc[0])
    off_pass = bool(res[(res.scenario != "standard") & (res.period == "OOS") & (res.symbol == "combined")]["scenario_pass"].any())
    verdict = "PASS" if std_pass else ("CONDITIONAL" if off_pass else "FAIL")
    res["verdict"] = verdict
    plot(name, s.TITLE, curves, verdict)
    return {"name": name, "variants": var, "results": res, "random": pd.DataFrame(rb_rows),
            "quarterly": pd.concat(q_rows, ignore_index=True) if q_rows else pd.DataFrame(),
            "hindsight": hind, "seconds": time.time() - t_start}


def plot(name, title, curves, verdict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    CHARTS.mkdir(exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=False)
    colors = {"standard": "#1f4e79", "offer_50": "#c55a11", "offer_100": "#548235"}
    styles = {"BTCUSD": "-", "ETHUSD": "--"}
    for ax, per in zip(axes, ("IS", "OOS")):
        for (sc, p, sym), cur in curves.items():
            if p != per or cur is None or not len(cur):
                continue
            eq = 100 * cur["net"].cumsum() / EQUITY0
            ax.step(cur["exit_time"].dt.tz_localize(None), eq, where="post", color=colors[sc], ls=styles[sym],
                    lw=1.3, label=f"{sym} {sc}")
        ax.axhline(0, color="#888", lw=0.8)
        w0, w1 = window(per)
        ax.set_title(f"{'In-sample' if per == 'IS' else 'Out-of-sample'} {w0.date()} to {w1.date()}")
        ax.set_ylabel("Net return on $1,000 (%)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="lower left")
    fig.suptitle(f"{title}: equity after all costs (selected variant per scenario) - verdict {verdict}")
    fig.tight_layout()
    fig.savefig(CHARTS / f"{name}.png", dpi=110)
    plt.close(fig)


def summary_md(res: pd.DataFrame, rb: pd.DataFrame) -> str:
    keep = ["strategy", "scenario", "period", "symbol", "params", "trades", "net_pct", "win_rate_pct", "profit_factor",
            "expectancy_R", "max_dd_pct", "sharpe", "avg_hold_min", "random_percentile", "scenario_pass", "verdict"]
    r = res[res.symbol == "combined"][[k for k in keep if k in res.columns]].copy()
    return "# Phase 2 summary (combined BTC+ETH, $1,000 per symbol)\n\n" + r.round(2).to_markdown(index=False) + \
        "\n\n## Random baseline (OOS)\n\n" + rb.round(2).to_markdown(index=False) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--strategies", nargs="+", default=[s.NAME for s in ALL])
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if a.download:
        subprocess.run([sys.executable, "-m", "core.data", "download", "--days", "740"], check=True, cwd=ROOT)
    LOGS.mkdir(exist_ok=True)
    order = sorted(a.strategies, key=lambda n: -len(list(itertools.product(*BY_NAME[n].GRID.values()))))
    with Pool(min(a.workers, len(order))) as pool:
        outs = pool.map(evaluate, order)
    outs.sort(key=lambda o: [s.NAME for s in ALL].index(o["name"]))
    res = pd.concat([o["results"] for o in outs], ignore_index=True)
    var = pd.concat([o["variants"] for o in outs], ignore_index=True)
    rb = pd.concat([o["random"] for o in outs], ignore_index=True)
    qt = pd.concat([o["quarterly"] for o in outs], ignore_index=True)
    res.to_csv(ROOT / "results.csv", index=False)
    var.to_csv(LOGS / "variants_log.csv", index=False)
    rb.to_csv(LOGS / "random_baseline.csv", index=False)
    qt.to_csv(LOGS / "quarterly.csv", index=False)
    pd.concat([o["hindsight"] for o in outs], ignore_index=True).to_csv(LOGS / "hindsight_best_oos.csv", index=False)
    (LOGS / "summary.md").write_text(summary_md(res, rb))
    for o in outs:
        v = o["results"]["verdict"].iloc[0]
        print(f"{o['name']:<20} verdict {v:<12} ({o['seconds']:.0f}s)")


if __name__ == "__main__":
    main()
