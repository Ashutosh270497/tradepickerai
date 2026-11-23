"""Backtest reference numbers for the paper-trading plan (frozen rules, chosen coins and capital split).

    python3 -m paper.plan_stats paper_config.json   -> logs/paper_plan_stats.json

Full history (Binance USD-M prices 2020 -> 2026, Delta specs/fees, funding as Phase 3/4), each coin in its own
sub-account with the planned capital and real whole-contract rounding. Returns the combined account's max
drawdown, return, trades per year, and monthly-block bootstrap ranges for 6- and 12-month windows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from core.engine import Scenario, run
from core.market import load_binance_market, load_phase4_market
from phase3_runner import daily_mtm, perf
from strategies import trend_ma_4h as S

SC = Scenario("taker", slip=0.0001)


def load(coin):
    if coin in ("BTCUSD", "ETHUSD"):
        return load_binance_market(coin)
    sp = json.loads(Path("logs/phase4_delta_specs.json").read_text())[coin]
    return load_phase4_market(coin, lot=sp["contract_value"], tick=sp["tick"], delta_interval_h=sp["funding_interval_h"])


def main(cfg_path):
    cfg = json.loads(Path(cfg_path).read_text())
    eqs, trades, rows = [], [], []
    starts = []
    for c in cfg["coins"]:
        m = load(c["coin"])
        cand, _, _ = S.build(m, S.DEFAULT)
        tr = run(m, cand, 0, m.n, SC, equity0=c["capital"], risk=0.005, max_lev=3.0)
        first = int(cand["fill"][0])
        d0 = pd.to_datetime(m.t[first], unit="s", utc=True).floor("D")
        d1 = pd.to_datetime(m.t[-1], unit="s", utc=True).floor("D")
        eq = daily_mtm(m, tr, c["capital"], d0, d1)
        eqs.append(eq.rename(c["coin"]))
        starts.append(d0)
        trades.append(tr.assign(coin=c["coin"]))
        p = perf(eq)
        rows.append({"coin": c["coin"], "capital": c["capital"], "trades": len(tr), "skipped_below_1_contract": tr.attrs["skipped_small"],
                     "net_usd": float(tr["net"].sum()), "max_dd_pct": p["max_dd_pct"], "cagr_pct": p["cagr_pct"]})
    common = max(starts)
    E = pd.concat([e.loc[common:] for e in eqs], axis=1, sort=True).ffill().dropna()
    total = E.sum(axis=1)
    cap = sum(c["capital"] for c in cfg["coins"])
    p = perf(total)
    pnl = total.diff().dropna()
    blocks = [g.to_numpy() for _, g in pnl.groupby(pnl.index.tz_localize(None).to_period("M"))]
    rng = np.random.default_rng(42)
    boot = {}
    for months in (6, 12):
        sums, dds = [], []
        for _ in range(10000):
            seq = np.concatenate([blocks[i] for i in rng.integers(0, len(blocks), months)])
            curve = cap + np.cumsum(seq)
            sums.append(seq.sum() / cap * 100)
            dds.append(float((1 - curve / np.maximum.accumulate(np.r_[cap, curve])[1:]).max() * 100))
        sums, dds = np.array(sums), np.array(dds)
        boot[f"{months}m"] = {"return_pct_p5": float(np.percentile(sums, 5)), "return_pct_p50": float(np.percentile(sums, 50)),
                              "return_pct_p95": float(np.percentile(sums, 95)), "prob_loss_pct": float((sums < 0).mean() * 100),
                              "max_dd_pct_p50": float(np.percentile(dds, 50)), "max_dd_pct_p95": float(np.percentile(dds, 95))}
    allt = pd.concat(trades)
    years = (total.index[-1] - total.index[0]).days / 365.25
    n_in = allt[pd.to_datetime(allt["entry_time"]) >= common]
    out = {"period": f"{common.date()} -> {total.index[-1].date()}", "capital": cap,
           "combined": {**p, "trades": len(n_in), "trades_per_year": len(n_in) / years}, "per_coin": rows, "bootstrap": boot,
           "months_to_100_trades": 100 / (len(n_in) / years) * 12}
    Path("logs").mkdir(exist_ok=True)
    Path("logs/paper_plan_stats.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "paper_config.json")
