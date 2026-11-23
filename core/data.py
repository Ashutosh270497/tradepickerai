"""Download and load Delta Exchange India candles and funding history (public API, no key).

    python3 -m core.data download --days 740            # 1m + 5m candles and funding, BTCUSD + ETHUSD
    python3 -m core.data report                         # gaps and coverage of the cache

Files are cached as parquet in data/:  {SYMBOL}_{RES}.parquet, FUNDING_{SYMBOL}.parquet
Candle "time" is the candle OPEN time in UTC seconds; prices are last-traded-price (LTP) candles.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

BASE_URL = "https://api.india.delta.exchange"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SYMBOLS = ["BTCUSD", "ETHUSD"]
RES_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
MAX_CANDLES = 2000  # per request, per Delta API docs


def _get(path: str, params: dict) -> dict:
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "backtest-client"})
    err: Exception | None = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as e:  # 429 / network: back off
            err = e
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"failed: {url}") from err


def fetch(symbol: str, res: str, days: int, end: int | None = None) -> pd.DataFrame:
    step = RES_SECONDS[res]
    end = end or int(time.time()) // step * step
    start = end - days * 86400
    rows, cur = [], start
    while cur < end:
        stop = min(cur + step * MAX_CANDLES, end)
        p = _get("/v2/history/candles", {"resolution": res, "symbol": symbol, "start": cur, "end": stop})
        if not p.get("success"):
            raise RuntimeError(f"{symbol} {res}: {p}")
        rows.extend(p["result"])
        cur = stop
        time.sleep(0.05)
    df = pd.DataFrame(rows)
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    df = df[df["time"] + step <= end]  # drop the still-forming candle
    return df[["time", "open", "high", "low", "close", "volume"]].astype(
        {"time": "int64", "open": float, "high": float, "low": float, "close": float, "volume": float})


def path(symbol: str, res: str) -> Path:
    return DATA_DIR / f"{symbol}_{res}.parquet"


def funding_path(symbol: str) -> Path:
    return DATA_DIR / f"FUNDING_{symbol}.parquet"


def gap_report(df: pd.DataFrame, step: int) -> dict:
    d = np.diff(df["time"].to_numpy())
    missing = int(((d // step) - 1)[d > step].sum())
    return {"candles": len(df), "first": pd.to_datetime(df["time"].iloc[0], unit="s", utc=True),
            "last": pd.to_datetime(df["time"].iloc[-1], unit="s", utc=True),
            "gaps": int((d > step).sum()), "missing_candles": missing,
            "largest_gap_min": float(d.max() / 60)}


def load(symbol: str, res: str = "1m", fill: bool = True) -> pd.DataFrame:
    """Load cached candles. With fill=True, missing candles are inserted as flat bars
    (open=high=low=close=previous close, volume 0) so bar counts equal elapsed minutes."""
    df = pd.read_parquet(path(symbol, res))
    if fill:
        step = RES_SECONDS[res]
        full = np.arange(df["time"].iloc[0], df["time"].iloc[-1] + step, step, dtype="int64")
        df = df.set_index("time").reindex(full)
        df.index.name = "time"
        df["volume"] = df["volume"].fillna(0.0)
        df["close"] = df["close"].ffill()
        for c in ("open", "high", "low"):
            df[c] = df[c].fillna(df["close"])
        df = df.reset_index()
    return df


def load_funding(symbol: str) -> pd.DataFrame:
    """Funding rate history. Delta publishes it as 1h 'candles' of symbol FUNDING:<symbol>;
    the value is the funding rate in PERCENT per 8 hours."""
    return pd.read_parquet(funding_path(symbol))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["download", "report"])
    ap.add_argument("--days", type=int, default=740)
    ap.add_argument("--symbols", nargs="+", default=SYMBOLS)
    ap.add_argument("--res", nargs="+", default=["1m", "5m"])
    ap.add_argument("--no-funding", action="store_true")
    a = ap.parse_args()
    DATA_DIR.mkdir(exist_ok=True)
    if a.cmd == "download":
        end = int(time.time()) // 3600 * 3600  # common end time for every series
        for s in a.symbols:
            for r in a.res:
                t0 = time.time()
                df = fetch(s, r, a.days, end)
                df.to_parquet(path(s, r), index=False)
                print(s, r, gap_report(df, RES_SECONDS[r]), f"{time.time() - t0:.0f}s", flush=True)
            if not a.no_funding:
                f = fetch(f"FUNDING:{s}", "1h", a.days + 5, end)
                f.to_parquet(funding_path(s), index=False)
                print(s, "funding", gap_report(f, 3600), flush=True)
    else:
        for s in a.symbols:
            for r in a.res:
                if path(s, r).exists():
                    print(s, r, gap_report(pd.read_parquet(path(s, r)), RES_SECONDS[r]))
            if funding_path(s).exists():
                print(s, "funding", gap_report(load_funding(s), 3600))


if __name__ == "__main__":
    main()
