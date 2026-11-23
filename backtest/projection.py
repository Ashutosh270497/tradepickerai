"""Historical outcome ranges for one strategy on a small account.

Runs the strategy over the test window, splits the account equally across the
symbols, then looks at EVERY 30/90/180/360-day stretch inside that history and
reports how the account would have ended. This is a description of the past,
not a forecast.

Usage:
    python3 backtest/projection.py --strategy "EMA 50/200 cross" --resolution 4h --capital 120
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from fetch_data import RESOLUTION_SECONDS, csv_path
from strategies import STRATEGIES, TAKER, simulate


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--strategy", default="EMA 50/200 cross", choices=STRATEGIES)
    p.add_argument("--resolution", default="4h", choices=RESOLUTION_SECONDS)
    p.add_argument("--symbols", nargs="+", default=["BTCUSD", "ETHUSD"])
    p.add_argument("--days", type=int, default=730)
    p.add_argument("--capital", type=float, default=120.0)
    p.add_argument("--windows", type=int, nargs="+", default=[30, 90, 180, 360])
    args = p.parse_args()

    step = RESOLUTION_SECONDS[args.resolution]
    per_day = 86400 // step
    curves, n_trades = [], 0
    for symbol in args.symbols:
        df = pd.read_csv(csv_path(symbol, args.resolution))
        start = len(df) - args.days * per_day
        trades, eq = simulate(df, STRATEGIES[args.strategy](df), start, TAKER)
        n_trades += len(trades)
        curves.append(eq)
        print(f"{symbol}: {len(trades)} trades, {eq[-1] * 100:+.1f}% over {args.days} days")
    # Equal split of the account across symbols, fixed size per trade (no compounding).
    eq = np.mean(curves, axis=0) * args.capital
    total = eq[-1]
    dd = (np.maximum.accumulate(eq) - eq).max()
    print(f"\n{args.strategy} {args.resolution}, ${args.capital:.0f} account, {n_trades} trades in {args.days} days")
    print(f"total profit ${total:+.2f}  (average ${total / args.days * 30:+.2f} per 30 days)  worst drawdown ${dd:.2f}\n")
    print(f"{'window':>8} {'worst':>9} {'low(10%)':>9} {'median':>9} {'high(90%)':>10} {'best':>9} {'profitable':>11}")
    for w in args.windows:
        k = w * per_day
        pnl = eq[k:] - eq[:-k]
        q = np.percentile(pnl, [0, 10, 50, 90, 100]) + args.capital
        print(f"{w:>6}d  " + " ".join(f"${v:8.2f}" for v in q[:3]) + f"  ${q[3]:8.2f} ${q[4]:8.2f} {np.mean(pnl > 0) * 100:9.0f}%")


if __name__ == "__main__":
    main()
