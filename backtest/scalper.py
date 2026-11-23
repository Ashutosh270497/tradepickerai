"""EMA 9/21 scalper on 15m candles: at most 4 trades a day, only on filtered setups.

Entry is always the 9/21 EMA cross (read at candle close, filled at next open).
"Best setup" filters and exits are tested as a grid so nothing is hand-picked:

  filters: none | trend (price on the right side of the 200 EMA)
           | trend + ADX>=25 | trend + ADX>=25 + above-average volume
  exits:   opposite cross | 1 ATR stop & 1.5 ATR target | 1.5 ATR stop & 3 ATR target
           (stop/target variants also exit on the opposite cross)

Costs: taker fee + GST + slippage per side, plus funding from Delta's history.
Returns are $ on a fixed position equal to the account (1x), no compounding.

Usage:  python3 backtest/scalper.py --capital 1000
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from fetch_data import csv_path
from strategies import (MAKER, TAKER, adx, atr, cross_dn, cross_up, ema, load_funding, sig, simulate)

STEP = 900
FILTERS = ["none", "trend", "trend+adx", "trend+adx+vol"]
EXITS = {"opposite cross": None, "1 ATR stop / 1.5 ATR target": (1.0, 1.5), "1.5 ATR stop / 3 ATR target": (1.5, 2.0)}


def build(df: pd.DataFrame, filt: str, exit_cfg) -> dict:
    c = df["close"]
    up, dn = cross_up(ema(c, 9), ema(c, 21)), cross_dn(ema(c, 9), ema(c, 21))
    ok_l = np.ones(len(c), bool)
    ok_s = np.ones(len(c), bool)
    if "trend" in filt:
        t = ema(c, 200)
        ok_l &= (c > t).to_numpy()
        ok_s &= (c < t).to_numpy()
    if "adx" in filt:
        strong = (adx(df) >= 25).to_numpy()
        ok_l &= strong
        ok_s &= strong
    if "vol" in filt:
        busy = (df["volume"] > df["volume"].rolling(20).mean()).to_numpy()
        ok_l &= busy
        ok_s &= busy
    if exit_cfg is None:
        return sig(up & ok_l, dn & ok_s, lx=dn, sx=up)
    stop_mult, rr = exit_cfg
    a = atr(df).to_numpy() * stop_mult
    return sig(up & ok_l, dn & ok_s, lx=dn, sx=up, stop_l=a, stop_s=a, rr=rr)


def report(df, s, start, funding, capital) -> dict:
    trades, eq = simulate(df, s, start, TAKER, funding)
    idx, side, gross, _ = (np.array(x) for x in zip(*trades))
    net = gross - 2 * TAKER
    half = start + (len(df) - start) // 2
    days = (len(df) - start) * STEP / 86400
    trade_days = len(np.unique((df["time"].to_numpy()[idx] + 19800) // 86400))
    k = capital
    return {
        "trades": len(net), "per_day": len(net) / days, "days_traded_%": trade_days / days * 100,
        "win_%": (net > 0).mean() * 100,
        "net_$": net.sum() * k, "net_maker_$": (gross - 2 * MAKER).sum() * k,
        "before_fees_$": gross.sum() * k, "fees_$": 2 * TAKER * len(net) * k,
        "profit_factor": net[net > 0].sum() / -net[net <= 0].sum(),
        "max_dd_$": (np.maximum.accumulate(eq) - eq).max() * k,
        "year1_$": net[idx < half].sum() * k, "year2_$": net[idx >= half].sum() * k,
        "avg_hold_h": None, "_net": net, "_idx": idx,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", nargs="+", default=["BTCUSD", "ETHUSD"])
    p.add_argument("--days", type=int, default=730)
    p.add_argument("--capital", type=float, default=1000.0)
    args = p.parse_args()
    pd.set_option("display.width", 250)

    for symbol in args.symbols:
        df = pd.read_csv(csv_path(symbol, "15m"))
        start = len(df) - args.days * 96
        funding = load_funding(symbol, df, STEP)
        rows, keep = [], {}
        for filt in FILTERS:
            for exit_name, exit_cfg in EXITS.items():
                r = report(df, build(df, filt, exit_cfg), start, funding, args.capital)
                keep[(filt, exit_name)] = r
                rows.append({"filter": filt, "exit": exit_name,
                             **{k: v for k, v in r.items() if not k.startswith("_") and v is not None}})
        t0, t1 = (pd.to_datetime(df["time"].iloc[i], unit="s", utc=True).date() for i in (start, -1))
        print(f"\n{'=' * 100}\n{symbol} 15m, {t0} to {t1}, ${args.capital:.0f} per trade at 1x, max 4 trades/day\n{'=' * 100}")
        table = pd.DataFrame(rows)
        print(table.round(2).to_string(index=False))
        # Pick the variant on year 1 only, then see how that same variant did in year 2.
        best = table.sort_values("year1_$", ascending=False).iloc[0]
        print(f"\nBest in year 1: [{best['filter']}] + [{best['exit']}]  year1 ${best['year1_$']:+.0f}  ->  year2 ${best['year2_$']:+.0f}")
        r = keep[(best["filter"], best["exit"])]
        month = pd.to_datetime(df["time"].to_numpy()[r["_idx"]], unit="s").strftime("%Y-%m")
        m = pd.Series(r["_net"] * args.capital).groupby(np.array(month)).agg(["size", "sum"])
        print(f"months profitable for that variant: {(m['sum'] > 0).sum()} of {len(m)}; "
              f"best month ${m['sum'].max():+.0f}, worst month ${m['sum'].min():+.0f}")


if __name__ == "__main__":
    main()
