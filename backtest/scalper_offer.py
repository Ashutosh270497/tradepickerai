"""Effect of Delta's "Scalper Offer" on the EMA 9/21 15m scalper.

Offer: no closing fee on BTC/ETH futures trades that are opened AND closed
within 30 minutes. On 15m candles that is two candles, so this tests:

  * the normal exits, with the closing fee waived only on trades that happen to finish in time;
  * a forced exit just before the 30-minute mark so every trade qualifies
    (with and without a 1 ATR stop / 1.5 ATR target).

A trade that exits exactly at the 30-minute candle boundary is treated as NOT qualifying.
Slippage (0.01% per side) and funding still apply. Max 4 trades/day.

Usage:  python3 backtest/scalper_offer.py --capital 1000
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from fetch_data import csv_path
from scalper import STEP, build
from strategies import GST, load_funding, simulate

TAKER_FEE, MAKER_FEE, SLIP = 0.0005 * (1 + GST), 0.0002 * (1 + GST), 0.0001
OFFER_BARS = 2  # 30 minutes on 15m candles

VARIANTS = {
    "opposite cross (no offer)": (None, None, False),
    "opposite cross + offer": (None, None, True),
    "30-min time exit + offer": (None, OFFER_BARS, True),
    "30-min exit, 1 ATR stop/1.5 ATR target + offer": ((1.0, 1.5), OFFER_BARS, True),
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
        move = (df["close"].shift(-1) / df["open"] - 1).abs().iloc[start:]
        rows = []
        for filt in ["none", "trend", "trend+adx"]:
            for name, (exit_cfg, max_bars, offer) in VARIANTS.items():
                trades, _ = simulate(df, build(df, filt, exit_cfg), start, 0.0, funding, max_bars)
                idx, _, gross, dur = (np.array(x) for x in zip(*trades))
                free = (dur < OFFER_BARS) if offer else np.zeros(len(dur), bool)
                close_fee = np.where(free, 0.0, TAKER_FEE)
                net_taker = gross - TAKER_FEE - close_fee - 2 * SLIP   # market order in, market order out
                net_maker = gross - MAKER_FEE - close_fee - SLIP       # limit order in (assumes it fills), market out
                half = start + (len(df) - start) // 2
                k = args.capital
                rows.append({
                    "filter": filt, "exit": name, "trades": len(gross), "free_close_%": free.mean() * 100,
                    "win_%": (net_taker > 0).mean() * 100, "before_fees_$": gross.sum() * k,
                    "costs_$": (gross - net_taker).sum() * k, "net_$": net_taker.sum() * k,
                    "year1_$": net_taker[idx < half].sum() * k, "year2_$": net_taker[idx >= half].sum() * k,
                    "net_limit_entry_$": net_maker.sum() * k,
                })
        print(f"\n{'=' * 110}\n{symbol} 15m, last {args.days} days, ${args.capital:.0f} per trade at 1x, max 4 trades/day")
        print(f"typical 30-minute price move: median {move.median() * 100:.2f}%, average {move.mean() * 100:.2f}%  "
              f"| cost per trade with offer: {(TAKER_FEE + 2 * SLIP) * 100:.3f}%  without: {(2 * TAKER_FEE + 2 * SLIP) * 100:.3f}%")
        print("=" * 110)
        print(pd.DataFrame(rows).round(1).to_string(index=False))


if __name__ == "__main__":
    main()
