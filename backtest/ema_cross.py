"""Backtest: EMA crossover (default 9/21) stop-and-reverse on Delta Exchange candles.

Rules
-----
* Fast EMA closes above slow EMA  -> go long.
* Fast EMA closes below slow EMA  -> go short (closing the long, and vice versa).
* A signal is only known once its candle has CLOSED, so the order is filled at
  the OPEN of the next candle. No look-ahead.
* Position size: a fixed notional equal to starting capital on every trade
  (1x leverage, no compounding), so returns are "% of account".
* Costs are charged on entry and on exit. Funding payments are NOT modelled.

Usage:
    python3 backtest/fetch_data.py BTCUSD ETHUSD
    python3 backtest/ema_cross.py BTCUSD ETHUSD
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from fetch_data import RESOLUTION_SECONDS, csv_path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

GST = 0.18  # India: GST is charged on top of trading fees
TAKER_FEE = 0.0005 * (1 + GST)  # 0.05% + GST per side (market orders)
MAKER_FEE = 0.0002 * (1 + GST)  # 0.02% + GST per side (limit orders)


@dataclass
class Result:
    trades: pd.DataFrame
    equity: pd.Series  # mark-to-market account return (fraction), per candle
    buy_hold: float


def run(df: pd.DataFrame, fast: int, slow: int, test_days: int, step: int,
        cost_per_side: float, side: str = "both") -> Result:
    close = df["close"].to_numpy(float)
    open_ = df["open"].to_numpy(float)
    times = df["time"].to_numpy()
    n = len(df)

    ema_fast = df["close"].ewm(span=fast, adjust=False).mean().to_numpy()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean().to_numpy()
    state = np.where(ema_fast > ema_slow, 1, -1)

    # Candles before test_start only warm up the EMAs.
    test_start = max(n - test_days * 86400 // step, slow * 5)
    cross = np.flatnonzero(state[1:] != state[:-1]) + 1  # candle whose close made the cross
    cross = cross[(cross >= test_start) & (cross < n - 1)]

    equity = np.zeros(n)
    realised = 0.0
    rows = []
    for k, i in enumerate(cross):
        direction = int(state[i])
        entry_idx = i + 1
        last = k == len(cross) - 1
        exit_idx = n - 1 if last else cross[k + 1] + 1
        if side == "long" and direction < 0 or side == "short" and direction > 0:
            equity[entry_idx:exit_idx + 1] = realised
            continue
        entry = open_[entry_idx]
        # Final still-open trade is marked at the last close.
        exit_ = close[exit_idx] if last else open_[exit_idx]
        gross = direction * (exit_ / entry - 1)
        net = gross - 2 * cost_per_side
        path = open_[entry_idx:exit_idx + 1].copy()
        path[-1] = exit_
        equity[entry_idx:exit_idx + 1] = realised - cost_per_side + direction * (path / entry - 1)
        realised += net
        equity[exit_idx] = realised
        rows.append({
            "entry_time": pd.to_datetime(times[entry_idx], unit="s", utc=True),
            "exit_time": pd.to_datetime(times[exit_idx], unit="s", utc=True),
            "side": "long" if direction > 0 else "short",
            "entry": entry, "exit": exit_,
            "bars": exit_idx - entry_idx,
            "gross_pct": gross * 100, "net_pct": net * 100,
        })
    if len(cross):
        equity[cross[-1] + 1:] = np.where(equity[cross[-1] + 1:] == 0, realised, equity[cross[-1] + 1:])

    idx = pd.to_datetime(times[test_start:], unit="s", utc=True)
    return Result(
        trades=pd.DataFrame(rows),
        equity=pd.Series(equity[test_start:], index=idx),
        buy_hold=close[-1] / open_[test_start] - 1,
    )


def stats(res: Result) -> dict:
    t = res.trades
    if t.empty:
        return {"trades": 0}
    net = t["net_pct"]
    wins, losses = net[net > 0], net[net <= 0]
    eq = res.equity * 100
    drawdown = (eq.cummax() - eq).max()
    return {
        "trades": len(t),
        "win_rate_%": len(wins) / len(t) * 100,
        "net_return_%": net.sum(),
        "gross_return_%": t["gross_pct"].sum(),
        "costs_%": t["gross_pct"].sum() - net.sum(),
        "profit_factor": wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf"),
        "avg_win_%": wins.mean() if len(wins) else 0.0,
        "avg_loss_%": losses.mean() if len(losses) else 0.0,
        "expectancy_%/trade": net.mean(),
        "max_drawdown_%": drawdown,
        "avg_bars_held": t["bars"].mean(),
        "buy_hold_%": res.buy_hold * 100,
    }


def fmt(d: dict) -> str:
    return "\n".join(f"  {k:<20} {v:>10.2f}" if isinstance(v, float) else f"  {k:<20} {v:>10}" for k, v in d.items())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--resolution", default="15m", choices=RESOLUTION_SECONDS)
    parser.add_argument("--fast", type=int, default=9)
    parser.add_argument("--slow", type=int, default=21)
    parser.add_argument("--days", type=int, default=365, help="length of the test window")
    parser.add_argument("--slippage", type=float, default=0.0001, help="per side, as a fraction (taker scenario)")
    args = parser.parse_args()

    step = RESOLUTION_SECONDS[args.resolution]
    RESULTS_DIR.mkdir(exist_ok=True)
    scenarios = {
        "no costs (theoretical)": 0.0,
        "maker fees (limit orders)": MAKER_FEE,
        "taker fees + slippage (market orders)": TAKER_FEE + args.slippage,
    }
    for symbol in args.symbols:
        df = pd.read_csv(csv_path(symbol, args.resolution))
        print(f"\n{'=' * 64}\n{symbol}  EMA {args.fast}/{args.slow}  {args.resolution}  last {args.days} days\n{'=' * 64}")
        for name, cost in scenarios.items():
            res = run(df, args.fast, args.slow, args.days, step, cost)
            print(f"\n-- {name}: {cost * 100:.4f}% per side")
            print(fmt(stats(res)))

        cost = scenarios["taker fees + slippage (market orders)"]
        res = run(df, args.fast, args.slow, args.days, step, cost)
        print("\n-- long vs short (taker scenario)")
        for side_name, g in res.trades.groupby("side"):
            print(f"  {side_name:<6} trades {len(g):>5}  win% {(g['net_pct'] > 0).mean() * 100:6.2f}  "
                  f"net {g['net_pct'].sum():9.2f}%  gross {g['gross_pct'].sum():9.2f}%")
        monthly = res.trades.assign(month=res.trades["exit_time"].dt.strftime("%Y-%m")).groupby("month").agg(
            trades=("net_pct", "size"), net_pct=("net_pct", "sum"), gross_pct=("gross_pct", "sum"))
        print("\n-- monthly (taker scenario)")
        print(monthly.round(2).to_string())
        out = RESULTS_DIR / f"{symbol}_ema{args.fast}_{args.slow}_{args.resolution}_trades.csv"
        res.trades.to_csv(out, index=False)
        print(f"\ntrade log: {out}")


if __name__ == "__main__":
    main()
