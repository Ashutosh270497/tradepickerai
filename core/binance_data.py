"""Long BTC/ETH perpetual history from Binance's public data archive (data.binance.vision).

    python3 -m core.binance_data            # 1h klines + funding, BTCUSDT and ETHUSDT, 2020-01 -> yesterday

SOURCE: Binance USD-M perpetual futures (BTCUSDT, ETHUSDT), monthly and daily archive files:
  https://data.binance.vision/data/futures/um/monthly/klines/{SYM}/1h/{SYM}-1h-YYYY-MM.zip
  https://data.binance.vision/data/futures/um/daily/klines/{SYM}/1h/{SYM}-1h-YYYY-MM-DD.zip
  https://data.binance.vision/data/futures/um/monthly/fundingRate/{SYM}/{SYM}-fundingRate-YYYY-MM.zip
Used for SIGNAL RESEARCH ONLY (4h and 1D). Costs and contract specs stay Delta's.
Saved as data/BINANCE_{SYM}_1h.parquet (time = candle open, UTC seconds) and
data/BINANCE_FUNDING_{SYM}.parquet (time = funding time, rate = FRACTION per interval).
"""
from __future__ import annotations

import io
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from core.data import DATA_DIR

BASE = "https://data.binance.vision/data/futures/um"
SYMBOLS = {"BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT"}
START = "2020-01"
KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count",
         "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def _get(url: str) -> bytes | None:
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "backtest-client"}),
                                        timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed: {url}")


def _csv(blob: bytes, cols: list[str] | None) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    first = raw.split(b"\n", 1)[0]
    has_header = not first[:1].isdigit()
    df = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None)
    if cols is not None and not has_header:
        df.columns = cols[:df.shape[1]]
    return df


def _to_seconds(x: pd.Series) -> np.ndarray:
    v = x.astype("int64").to_numpy()
    return np.where(v > 10**15, v // 10**6, np.where(v > 10**12, v // 1000, v))  # us / ms / s


SPOT = "https://data.binance.vision/data/spot"


def months(end: pd.Timestamp, start: str = START) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end.to_period("M") - 1, freq="M")]


def fetch_klines(sym: str, end: pd.Timestamp, start: str = START, base: str = BASE,
                 daily: bool = True) -> pd.DataFrame:
    """1h klines from the archive. `end` is exclusive (monthly files up to the month before `end`,
    then daily files for `end`'s month if daily=True)."""
    urls = [f"{base}/monthly/klines/{sym}/1h/{sym}-1h-{m}.zip" for m in months(end, start)]
    day0 = end.to_period("M").start_time
    if daily:
        urls += [f"{base}/daily/klines/{sym}/1h/{sym}-1h-{d:%Y-%m-%d}.zip"
                 for d in pd.date_range(day0, end - pd.Timedelta(days=1), freq="D")]
    with ThreadPoolExecutor(8) as ex:
        blobs = list(ex.map(_get, urls))
    missing = [u for u, b in zip(urls, blobs) if b is None]
    frames = [_csv(b, KCOLS) for b in blobs if b is not None]
    df = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({"time": _to_seconds(df["open_time"])})
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = df[c].astype(float).to_numpy()
    out = out.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    out.attrs["missing_files"] = missing
    return out


def fetch_funding(sym: str, end: pd.Timestamp, start: str = START) -> pd.DataFrame:
    urls = [f"{BASE}/monthly/fundingRate/{sym}/{sym}-fundingRate-{m}.zip" for m in months(end, start)]
    with ThreadPoolExecutor(8) as ex:
        blobs = list(ex.map(_get, urls))
    df = pd.concat([_csv(b, None) for b in blobs if b is not None], ignore_index=True)
    t = _to_seconds(df["calc_time"])
    ih = df["funding_interval_hours"].to_numpy() if "funding_interval_hours" in df else np.full(len(df), np.nan)
    out = pd.DataFrame({"time": (t // 60) * 60, "rate": df["last_funding_rate"].astype(float).to_numpy(), "interval_h": ih})
    out = out.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    out.attrs["missing_files"] = [u for u, b in zip(urls, blobs) if b is None]
    return out


def path(symbol: str) -> str:
    return DATA_DIR / f"BINANCE_{symbol}_1h.parquet"


def funding_path(symbol: str) -> str:
    return DATA_DIR / f"BINANCE_FUNDING_{symbol}.parquet"


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    end = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    for ours, sym in SYMBOLS.items():
        k = fetch_klines(sym, end)
        k.to_parquet(path(ours), index=False)
        d = np.diff(k["time"].to_numpy())
        print(f"{sym} 1h: {len(k)} candles {pd.to_datetime(k.time.iloc[0], unit='s')} -> "
              f"{pd.to_datetime(k.time.iloc[-1], unit='s')}; gaps {(d > 3600).sum()} "
              f"(missing hours {int(((d // 3600) - 1)[d > 3600].sum())}); missing files {len(k.attrs['missing_files'])}")
        f = fetch_funding(sym, end)
        f.to_parquet(funding_path(ours), index=False)
        print(f"{sym} funding: {len(f)} readings {pd.to_datetime(f.time.iloc[0], unit='s')} -> "
              f"{pd.to_datetime(f.time.iloc[-1], unit='s')}; intervals(h) {f['interval_h'].value_counts().to_dict()}; "
              f"missing files {len(f.attrs['missing_files'])}")


if __name__ == "__main__":
    main()
