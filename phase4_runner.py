"""Phase 4: frozen 4h trend filter on unseen coins (Part A) and pre-2020 BTC/ETH (Part B).

    python3 -m core.phase4_data && python3 phase4_runner.py

Every rule, coin, cost and pass criterion comes from frozen_rules.md (commit 796f128). Nothing here
is tuned: the strategy is strategies/trend_ma_4h.py with its DEFAULT parameters.
Outputs: phase4_results.csv, logs/phase4_*.csv, logs/phase4_trades/*.csv.gz, charts/phase4/*.png
"""
from __future__ import annotations

import json
import zlib
from dataclasses import replace
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from core.engine import Scenario, random_baseline, run
from core.indicators import atr
from core.market import SPECS, load_phase4_market, load_spot_market
from core.phase4_data import PART_A, TOP10
from phase3_runner import boot_ci, buy_hold, daily_mtm, perf
from strategies import trend_ma_4h as S

ROOT = Path(__file__).resolve().parent
LOGS, CHARTS = ROOT / "logs", ROOT / "charts" / "phase4"
SPECS_FILE = ROOT / "logs" / "phase4_delta_specs.json"
EQ0, RISK, MAX_LEV = 10000.0, 0.005, 3.0
TAKER = Scenario("taker", slip=0.0001)
RISKS = [0.005, 0.01, 0.02]
N_SIMS = 200
PART_B = ["BTCUSD", "ETHUSD"]


def frozen_specs() -> dict:
    """Delta contract size, tick and funding interval per coin, as frozen on 23 Nov 2026."""
    return json.loads(SPECS_FILE.read_text())


def load(coin: str, part: str):
    if part == "B":
        return load_spot_market(coin)
    sp = frozen_specs()[coin]
    return load_phase4_market(coin, lot=sp["contract_value"], tick=sp["tick"], delta_interval_h=sp["funding_interval_h"])


def trades_for(m, risk=RISK, fractional=False):
    c, _, _ = S.build(m, S.DEFAULT)
    mm = replace(m, lot=1e-12) if fractional else m
    t = run(mm, c, 0, m.n, TAKER, equity0=EQ0, risk=risk, max_lev=MAX_LEV)
    first = int(c["fill"][0]) if len(c["fill"]) else 0
    return t, first


def evaluate(job):
    coin, part = job
    m = load(coin, part)
    dq = m._cache["dq"]
    tr, first = trades_for(m)
    d0 = pd.to_datetime(m.t[first], unit="s", utc=True).floor("D")
    d1 = pd.to_datetime(m.t[-1], unit="s", utc=True).floor("D")
    eq = daily_mtm(m, tr, EQ0, d0, d1)
    bh = buy_hold(m, d0, d1)
    sp, bp = perf(eq), perf(bh)
    sims = random_baseline(m, tr, first, m.n, TAKER, n_sims=N_SIMS, seed=zlib.crc32(f"phase4|{part}|{coin}".encode()))
    net = tr["net"] if len(tr) else pd.Series(dtype=float)
    pf = net[net > 0].sum() / -net[net <= 0].sum() if (net <= 0).any() else np.inf
    lo, hi = boot_ci(tr["R"].to_numpy()) if len(tr) else (np.nan, np.nan)
    longs, shorts = (tr[tr.dir > 0], tr[tr.dir < 0]) if len(tr) else (tr, tr)
    row = {"part": part, "coin": coin, "set": ("top-10, primary" if coin in TOP10 else "primary") if part == "A" else "pre-2020",
           "start": d0.date(), "end": d1.date(), "years": (d1 - d0).days / 365.25,
           "trades": len(tr), "net_usd": net.sum(), "net_pct": net.sum() / EQ0 * 100, "profit_factor": pf,
           "win_rate_pct": (net > 0).mean() * 100 if len(tr) else np.nan,
           "expectancy_R": tr["R"].mean() if len(tr) else np.nan, "R_ci95_lo": lo, "R_ci95_hi": hi,
           "net_R": tr["R"].sum() if len(tr) else 0.0,
           "random_pct": float((sims < (tr["R"].sum() if len(tr) else 0)).mean() * 100),
           "random_p95_R": float(np.percentile(sims, 95)), "random_median_R": float(np.median(sims)),
           "gross_usd": tr["gross"].sum() if len(tr) else 0, "fees_usd": tr["fees"].sum() if len(tr) else 0,
           "funding_usd": tr["funding"].sum() if len(tr) else 0,
           "long_trades": len(longs), "long_net_usd": longs["net"].sum() if len(tr) else 0,
           "short_trades": len(shorts), "short_net_usd": shorts["net"].sum() if len(tr) else 0,
           "avg_hold_days": tr["hold_min"].mean() / 1440 if len(tr) else np.nan,
           "stop_exits_pct": (tr.exit_kind == "stop").mean() * 100 if len(tr) else np.nan,
           "cap_hit_pct": tr["capped"].mean() * 100 if len(tr) else np.nan,
           **{f"strat_{k}": v for k, v in sp.items()}, **{f"bh_{k}": v for k, v in bp.items()},
           "funding_gap_source": m._cache.get("funding_gap_source"),
           "funding_gap_8h_pct": m._cache.get("funding_gap_8h", np.nan) * 100 if part == "A" else np.nan,
           "filled_hours": m._cache.get("filled_hours"), "dq_max_gap_hours": dq["max_gap_hours"],
           "dq_max_1h_move_pct": dq["max_1h_move_pct"], "dq_excluded": dq["excluded"]}
    # diagnostics: risk scaling and minimum account size
    risk_rows, acct_rows = [], []
    b1d = m.bars(1440)
    atr_last = float(atr(b1d["h"], b1d["l"], b1d["c"], 20).iloc[-1])
    px_last = float(m.c[-1])
    for r in RISKS:
        t_lot, _ = trades_for(m, r)
        t_frac, _ = trades_for(m, r, fractional=True)
        e = daily_mtm(m, t_lot, EQ0, d0, d1)
        p_ = perf(e)
        risk_rows.append({"part": part, "coin": coin, "risk_pct": r * 100, "trades_whole_contracts": len(t_lot),
                          "trades_fractional": len(t_frac), "trades_lost_to_min_lot": len(t_frac) - len(t_lot),
                          "cap_hit_pct": t_lot["capped"].mean() * 100 if len(t_lot) else np.nan,
                          "net_pct": t_lot["net"].sum() / EQ0 * 100 if len(t_lot) else 0, **p_})
        if len(t_frac):
            dist = t_frac["stop_frac"] * t_frac["entry"]
            need = m.lot * np.maximum(dist / r, t_frac["entry"] / MAX_LEV)
            hist = float(need.max())
        else:
            hist = np.nan
        acct_rows.append({"part": part, "coin": coin, "risk_pct": r * 100, "contract_size": m.lot,
                          "min_account_usd_history_max": hist,
                          "min_account_usd_at_latest_price": m.lot * max(2 * atr_last / r, px_last / MAX_LEV),
                          "latest_price": px_last, "latest_2atr_pct": 2 * atr_last / px_last * 100})
    (LOGS / "phase4_trades").mkdir(parents=True, exist_ok=True)
    tr.to_csv(LOGS / "phase4_trades" / f"{part}_{coin}.csv.gz", index=False)
    plot(coin, part, eq, bh, row)
    return {"row": row, "sims": sims, "risk": risk_rows, "acct": acct_rows,
            "eq": eq / EQ0 - 1, "bh": bh / bh.iloc[0] - 1}


def plot(coin, part, eq, bh, row):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(eq.index.tz_localize(None), 100 * (eq / EQ0 - 1), color="#1f4e79", lw=1.4, label="strategy (left axis)")
    ax.axhline(0, color="#999", lw=0.8)
    ax.set_ylabel("Strategy net return (%)")
    ax2 = ax.twinx()
    ax2.plot(bh.index.tz_localize(None), 100 * (bh / bh.iloc[0] - 1), color="#999", lw=1, ls="--", label="buy & hold (right axis)")
    ax2.set_ylabel("Buy & hold return (%)", color="#777")
    label = "Part A unseen coin" if part == "A" else "Part B pre-2020 (spot)"
    ax.set_title(f"{coin} - {label}: net {row['net_pct']:+.1f}%, PF {row['profit_factor']:.2f}, "
                 f"{row['trades']} trades, random pct {row['random_pct']:.0f}", fontsize=10)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(CHARTS / f"{part}_{coin}.png", dpi=100)
    plt.close(fig)


def overview(results):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n = len(results)
    cols = 7
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.0, rows * 2.2))
    for ax, r in zip(axes.ravel(), results):
        e = r["eq"] * 100
        col = "#2e7d32" if r["row"]["net_usd"] > 0 else "#c62828"
        ax.plot(e.index.tz_localize(None), e, color=col, lw=1)
        ax.axhline(0, color="#999", lw=0.6)
        ax.set_title(f"{r['row']['coin']} ({r['row']['part']}) {r['row']['net_pct']:+.0f}%", fontsize=8)
        ax.tick_params(labelsize=6)
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    fig.suptitle("Phase 4: frozen 4h trend filter, net return per coin after all costs ($10,000 each, 0.5% risk)", fontsize=11)
    fig.tight_layout()
    fig.savefig(ROOT / "charts" / "phase4_overview.png", dpi=100)
    plt.close(fig)


def pooled_tests(res: list, label: str) -> dict:
    rows = [r["row"] for r in res]
    tr_net = np.concatenate([pd.read_csv(LOGS / "phase4_trades" / f"{r['part']}_{r['coin']}.csv.gz")["net"].to_numpy()
                             for r in rows if r["trades"] > 0])
    pf = tr_net[tr_net > 0].sum() / -tr_net[tr_net <= 0].sum()
    sims = np.sum([r["sims"] for r in res], axis=0)
    strat_R = sum(r["net_R"] for r in rows)
    pos = sum(r["net_usd"] > 0 for r in rows)
    return {"set": label, "coins": len(rows), "coins_positive": pos, "share_positive": pos / len(rows),
            "pooled_trades": int(sum(r["trades"] for r in rows)), "pooled_net_usd": sum(r["net_usd"] for r in rows),
            "pooled_profit_factor": pf, "pooled_net_R": strat_R, "random_p95_R": float(np.percentile(sims, 95)),
            "random_median_R": float(np.median(sims)), "random_pct": float((sims < strat_R).mean() * 100),
            "test_2_3_positive": pos / len(rows) >= 2 / 3, "test_pf_1_2": pf >= 1.2,
            "test_random_95": strat_R > np.percentile(sims, 95)}


def main():
    LOGS.mkdir(exist_ok=True)
    jobs = [(c, "A") for c in PART_A] + [(c, "B") for c in PART_B]
    with Pool(4) as pool:
        out = pool.map(evaluate, jobs)
    res_a = [o for o in out if o["row"]["part"] == "A"]
    excluded = [o["row"]["coin"] for o in res_a if o["row"]["dq_excluded"]]
    res_a_ok = [o for o in res_a if not o["row"]["dq_excluded"]]
    res_b = [o for o in out if o["row"]["part"] == "B"]
    A = pooled_tests(res_a_ok, "Part A primary (all qualifying coins)")
    A10 = pooled_tests([o for o in res_a_ok if o["row"]["coin"] in TOP10], "Part A top-10 liquid (diagnostic)")
    A42 = pooled_tests([o for o in res_a if o["row"]["dq_max_gap_hours"] <= 7 * 24],
                       "Part A incl. coins excluded only for extreme 1h moves (41; TLM's 29-day data hole stays out) (diagnostic)")
    a_pass = A["test_2_3_positive"] and A["test_pf_1_2"] and A["test_random_95"]
    b_pass = all(o["row"]["net_usd"] > 0 for o in res_b)
    verdict = "PASS" if (a_pass and b_pass) else "FAIL"
    summary = pd.DataFrame([A, A10, A42, {"set": "Part B pre-2020 BTC+ETH", "coins": 2,
                                     "coins_positive": sum(o["row"]["net_usd"] > 0 for o in res_b),
                                     "pooled_trades": sum(o["row"]["trades"] for o in res_b),
                                     "pooled_net_usd": sum(o["row"]["net_usd"] for o in res_b)}])
    summary["part_pass"] = [a_pass, np.nan, np.nan, b_pass]
    summary["overall_verdict"] = verdict
    summary["excluded_by_data_quality"] = ", ".join(excluded) or "none"
    pd.DataFrame([o["row"] for o in out]).to_csv(ROOT / "phase4_results.csv", index=False)
    summary.to_csv(ROOT / "phase4_summary.csv", index=False)
    pd.DataFrame([x for o in out for x in o["risk"]]).to_csv(LOGS / "phase4_risk_scaling.csv", index=False)
    pd.DataFrame([x for o in out for x in o["acct"]]).to_csv(LOGS / "phase4_min_account.csv", index=False)
    overview(out)
    # diagnostic: equal-weight portfolio of the primary coins vs an equal-weight buy-and-hold basket
    common0 = max(o["eq"].index[0] for o in res_a_ok)
    port_rows = []
    for label, key in (("strategy, equal-weight primary coins", "eq"), ("buy & hold, equal-weight primary coins", "bh")):
        rets = pd.concat([(1 + o[key]).loc[common0:].pct_change() for o in res_a_ok], axis=1).dropna(how="all").fillna(0)
        curve = (1 + rets.mean(axis=1)).cumprod()
        port_rows.append({"portfolio": label, "start": common0.date(), "end": curve.index[-1].date(),
                          **perf(pd.concat([pd.Series([1.0], index=[common0]), curve]))})
    pd.DataFrame(port_rows).to_csv(LOGS / "phase4_portfolio.csv", index=False)
    print(pd.DataFrame(port_rows).round(3).to_string(index=False))
    print(summary.T.to_string())
    print("excluded:", excluded or "none")


if __name__ == "__main__":
    main()
