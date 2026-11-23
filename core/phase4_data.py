"""Phase 4 data download (public data only; hosts already allowed in this environment).

    python3 -m core.phase4_data

* Binance USD-M 1h klines + funding for the 42 frozen Part A coins, from 2019-09 (full history).
* Delta FUNDING:<symbol> history for the same coins (same ~2-year window as Phase 3).
* Binance SPOT BTCUSDT/ETHUSDT 1h klines, 2017-08 -> 2019-12 (Part B).
Files: data/BINANCE_<DELTASYM>_1h.parquet, data/BINANCE_FUNDING_<DELTASYM>.parquet,
data/FUNDING_<DELTASYM>.parquet (Delta), data/BINANCESPOT_<SYM>_1h.parquet.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from core import binance_data as bd
from core import data

PART_A = ["SOLUSD", "XRPUSD", "ZECUSD", "UNIUSD", "BNBUSD", "DOGEUSD", "AAVEUSD", "BCHUSD", "LTCUSD", "LINKUSD",
          "AVAXUSD", "XMRUSD", "DOTUSD", "NEARUSD", "ADAUSD", "FILUSD", "DASHUSD", "ETCUSD", "TRXUSD", "ARUSD",
          "HBARUSD", "GTCUSD", "1000SHIBUSD", "RUNEUSD", "RLCUSD", "MANAUSD", "RSRUSD", "IOSTUSD", "XLMUSD",
          "ENJUSD", "DYDXUSD", "GALAUSD", "KSMUSD", "AXSUSD", "ZENUSD", "PEOPLEUSD", "TLMUSD", "MASKUSD", "TRBUSD",
          "SKLUSD", "IOTAUSD", "SUSHIUSD"]                      # frozen_rules.md, order = Delta turnover rank
TOP10 = PART_A[:10]
PERP_START = "2019-09"


def binance_sym(delta_sym: str) -> str:
    return delta_sym[:-3] + "USDT"


def spot_path(sym: str):
    return data.DATA_DIR / f"BINANCESPOT_{sym}_1h.parquet"


def main():
    data.DATA_DIR.mkdir(exist_ok=True)
    end = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    delta_end = int(time.time()) // 3600 * 3600
    for s in PART_A:
        b = binance_sym(s)
        k = bd.fetch_klines(b, end, start=PERP_START)
        k.to_parquet(bd.path(s), index=False)
        f = bd.fetch_funding(b, end, start=PERP_START)
        f.to_parquet(bd.funding_path(s), index=False)
        df = data.fetch(f"FUNDING:{s}", "1h", 745, delta_end)
        df.to_parquet(data.funding_path(s), index=False)
        d = np.diff(k["time"].to_numpy())
        print(f"{s}: klines {len(k)} {pd.to_datetime(k.time.iloc[0], unit='s'):%Y-%m-%d} -> "
              f"{pd.to_datetime(k.time.iloc[-1], unit='s'):%Y-%m-%d %H:%M}, max gap {d.max() / 3600:.0f}h | "
              f"Binance funding {len(f)} | Delta funding rows {len(df)} from "
              f"{pd.to_datetime(df.time.iloc[0], unit='s'):%Y-%m-%d}", flush=True)
    for ours, sym in (("BTCUSD", "BTCUSDT"), ("ETHUSD", "ETHUSDT")):
        k = bd.fetch_klines(sym, pd.Timestamp("2020-01-01"), start="2017-08", base=bd.SPOT, daily=False)
        k.to_parquet(spot_path(ours), index=False)
        d = np.diff(k["time"].to_numpy())
        print(f"{ours} spot: {len(k)} {pd.to_datetime(k.time.iloc[0], unit='s')} -> {pd.to_datetime(k.time.iloc[-1], unit='s')}; "
              f"gaps {(d > 3600).sum()}, missing hours {int(((d // 3600) - 1)[d > 3600].sum())}, max gap {d.max() / 3600:.0f}h", flush=True)


if __name__ == "__main__":
    main()
