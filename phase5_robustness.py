"""Phase 5, step 1: correlation-aware re-check of the Phase 4 Part A pooled test (report only).

    python3 phase5_robustness.py   -> logs/phase5_robustness.csv, logs/phase5_sync_baseline.csv

1. Synchronized random baseline: in each of 200 runs, every coin draws its random entries from the
   SAME random ordering of calendar hours, so random trades cluster in time across coins the way
   the strategy's trades do. Directions are synchronized too: a shared random number per hour
   decides which entries are longs (each coin keeps its own long/short count). Stop distance and
   holding limit are drawn from that coin's own trades of the same direction. Costs as Phase 4.
2. Block bootstrap: pooled daily mark-to-market P&L of the 33 coins, resampled in calendar-month
   blocks (10,000 draws) for a 95% confidence interval on pooled expectancy.
Uses the frozen Phase 4 trades exactly; nothing is re-tuned.
"""
from __future__ import annotations

import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from core.engine import LIMIT, MARKET, funding_paid, net_r_fraction, path_exit
from phase3_runner import daily_mtm
from phase4_runner import EQ0, TAKER, load, trades_for

ROOT = Path(__file__).resolve().parent
N_SIMS = int(sys.argv[1]) if len(sys.argv) > 1 else 200     # 200 = the pre-registered run count
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 20261123
N_BOOT = 10000
TAG = "" if N_SIMS == 200 and SEED == 20261123 else f"_{N_SIMS}sims_seed{SEED}"


def primary_coins() -> list[str]:
    r = pd.read_csv(ROOT / "phase4_results.csv")
    return r[(r.part == "A") & (~r.dq_excluded)]["coin"].tolist()


def coin_data(coin):
    m = load(coin, "A")
    tr, first = trades_for(m)
    return coin, m, tr, first


_MK = {}


def _init(coins):
    for c in coins:
        _MK[c] = coin_data(c)


def _sims(args):
    sim_ids, g0, n_hours = args
    out = np.zeros((len(sim_ids), len(_MK)))
    for row, s in enumerate(sim_ids):
        rng = np.random.default_rng(SEED + s)
        order = rng.permutation(n_hours)
        u = rng.random(n_hours)
        for col, (coin, m, tr, first) in enumerate(_MK.values()):
            K = len(tr)
            if K == 0:
                continue
            t_lo, t_hi = m.t[first], m.t[-1] - 3600
            hours = g0 + order * 3600
            pick = order[(hours >= t_lo) & (hours < t_hi)][:K]
            times = g0 + pick * 3600
            n_long = int((tr["dir"] > 0).sum())
            is_long = np.zeros(K, bool)
            is_long[np.argsort(u[pick])[:n_long]] = True
            longs, shorts = tr[tr.dir > 0], tr[tr.dir < 0]
            la = longs.sample(frac=1, random_state=int(rng.integers(1 << 31))) if len(longs) else longs
            sa = shorts.sample(frac=1, random_state=int(rng.integers(1 << 31))) if len(shorts) else shorts
            li = si = 0
            total = 0.0
            for tm, lg in zip(times, is_long):
                if lg:
                    a = la.iloc[li % len(la)]; li += 1; d = 1
                else:
                    a = sa.iloc[si % len(sa)]; si += 1; d = -1
                e = int(m.idx(tm))
                et = int(a["etype"])
                mk = TAKER.maker_fills or et == LIMIT
                entry = m.o[e] if mk else m.o[e] * (1 + d * TAKER.slip)
                stop = entry * (1 - d * a["stop_frac"])
                j_end = min(m.n, e + int(a["max_hold"]))
                pos, raw, kind, maker = path_exit(m, e, d, MARKET, stop, np.nan, None, max(j_end, e + 1))
                exit_px = raw if maker else raw * (1 - d * TAKER.slip)
                fund = funding_paid(m, float(e), pos, d, 1.0) / entry
                total += net_r_fraction(entry, exit_px, d, LIMIT if mk else MARKET, maker,
                                        (pos - e) * m.step / 60.0, a["stop_frac"], TAKER, fund)
            out[row, col] = total
    return out


def main():
    coins = primary_coins()
    data = [coin_data(c) for c in coins]
    strat_R = sum(tr["R"].sum() for _, _, tr, _ in data)
    g0 = int(min(m.t[first] for _, m, _, first in data))
    g1 = int(max(m.t[-1] for _, m, _, _ in data))
    n_hours = (g1 - g0) // 3600
    chunks = [list(range(i, N_SIMS, 4)) for i in range(4)]
    with Pool(4, initializer=_init, initargs=(coins,)) as pool:
        parts = pool.map(_sims, [(c, g0, n_hours) for c in chunks])
    sims = np.zeros((N_SIMS, len(coins)))
    for c, p in zip(chunks, parts):
        sims[c] = p
    pooled = sims.sum(axis=1)
    sync_pct = float((pooled < strat_R).mean() * 100)
    indep = pd.read_csv(ROOT / "phase4_summary.csv").iloc[0]
    # block bootstrap of pooled daily P&L
    daily = []
    for coin, m, tr, first in data:
        d0 = pd.to_datetime(m.t[first], unit="s", utc=True).floor("D")
        d1 = pd.to_datetime(m.t[-1], unit="s", utc=True).floor("D")
        daily.append(daily_mtm(m, tr, EQ0, d0, d1).diff().fillna(0.0).rename(coin))
    pnl = pd.concat(daily, axis=1, sort=True).fillna(0.0).sum(axis=1)
    months = pnl.groupby(pnl.index.tz_localize(None).to_period("M"))
    blocks = [g.to_numpy() for _, g in months]
    rng = np.random.default_rng(SEED)
    n_days, n_trades = len(pnl), sum(len(tr) for _, _, tr, _ in data)
    means = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pick = rng.integers(0, len(blocks), len(blocks))
        means[b] = np.concatenate([blocks[i] for i in pick]).mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    per_trade = lambda x: x * n_days / n_trades
    res = {
        "coins": len(coins), "pooled_trades": n_trades, "strategy_pooled_net_R": strat_R,
        "independent_baseline_p95_R": indep["random_p95_R"], "independent_baseline_pct": indep["random_pct"],
        "sync_baseline_median_R": float(np.median(pooled)), "sync_baseline_p95_R": float(np.percentile(pooled, 95)),
        "sync_baseline_p99_R": float(np.percentile(pooled, 99)), "sync_baseline_sd_R": float(pooled.std()),
        "independent_baseline_sd_R": np.nan, "sync_baseline_pct": sync_pct, "sync_beats_95": strat_R > np.percentile(pooled, 95),
        "days": n_days, "months": len(blocks), "pooled_mean_daily_pnl_usd": float(pnl.mean()),
        "boot_ci95_daily_lo": float(lo), "boot_ci95_daily_hi": float(hi),
        "pooled_expectancy_per_trade_usd": per_trade(pnl.mean()),
        "boot_ci95_per_trade_lo_usd": per_trade(lo), "boot_ci95_per_trade_hi_usd": per_trade(hi),
        "boot_ci_excludes_zero": lo > 0,
        "share_of_boot_draws_below_zero_pct": float((means <= 0).mean() * 100),
    }
    res["n_sims"], res["seed"] = N_SIMS, SEED
    res["sync_pct_std_error"] = float(np.sqrt(sync_pct / 100 * (1 - sync_pct / 100) / N_SIMS) * 100)
    pd.DataFrame([res]).to_csv(ROOT / "logs" / f"phase5_robustness{TAG}.csv", index=False)
    pd.DataFrame({"sim": range(N_SIMS), "pooled_net_R": pooled}).to_csv(ROOT / "logs" / f"phase5_sync_baseline{TAG}.csv", index=False)
    for k, v in res.items():
        print(f"{k:<40} {v}")


if __name__ == "__main__":
    main()
