"""Download historical OHLCV candles from Delta Exchange (India) public API.

Usage:
    python3 backtest/fetch_data.py BTCUSD ETHUSD --resolution 15m --days 380

Candles are cached as CSV in data/<SYMBOL>_<RESOLUTION>.csv (git-ignored).
No API key is needed: this only uses public market data.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

BASE_URL = "https://api.india.delta.exchange"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_CANDLES_PER_CALL = 2000
RESOLUTION_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400,
}


def _get(path: str, params: dict) -> dict:
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "backtest-client", "Accept": "application/json"})
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as err:  # network hiccup or rate limit: back off and retry
            last_err = err
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Request failed after retries: {url}") from last_err


def fetch_candles(symbol: str, resolution: str, days: int) -> pd.DataFrame:
    step = RESOLUTION_SECONDS[resolution]
    end = int(time.time())
    start = end - days * 86400
    chunk = step * MAX_CANDLES_PER_CALL
    rows: list[dict] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + chunk, end)
        payload = _get("/v2/history/candles", {
            "resolution": resolution, "symbol": symbol, "start": cursor, "end": chunk_end,
        })
        if not payload.get("success"):
            raise RuntimeError(f"Delta API error for {symbol}: {payload}")
        rows.extend(payload["result"])
        cursor = chunk_end
        time.sleep(0.15)

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"No candles returned for {symbol}")
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    # The newest candle is still forming; a backtest must only see closed candles.
    df = df[df["time"] + step <= end].reset_index(drop=True)
    return df[["time", "open", "high", "low", "close", "volume"]]


def csv_path(symbol: str, resolution: str) -> Path:
    return DATA_DIR / f"{symbol}_{resolution}.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--resolution", default="15m", choices=RESOLUTION_SECONDS)
    parser.add_argument("--days", type=int, default=380)
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    step = RESOLUTION_SECONDS[args.resolution]
    for symbol in args.symbols:
        df = fetch_candles(symbol, args.resolution, args.days)
        df.to_csv(csv_path(symbol, args.resolution), index=False)
        gaps = int((df["time"].diff().dropna() != step).sum())
        first = pd.to_datetime(df["time"].iloc[0], unit="s", utc=True)
        last = pd.to_datetime(df["time"].iloc[-1], unit="s", utc=True)
        print(f"{symbol}: {len(df)} candles, {first} -> {last}, gaps: {gaps}")


if __name__ == "__main__":
    main()
