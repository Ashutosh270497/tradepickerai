"""Market container: 1-minute bars plus funding settlements, and helpers for higher timeframes.

All execution happens on 1m bars. Strategies may compute signals on 5m/15m/1h bars built from
the same 1m data; a higher-timeframe bar that closes at time T can only be acted on from the
1m bar that OPENS at T (its `act` index). That is the no-lookahead contract used everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from core import data

SPECS = {  # from Delta API GET /v2/products/{symbol} (verified 23 Nov 2026)
    "BTCUSD": {"tick": 0.5, "lot": 0.001},
    "ETHUSD": {"tick": 0.05, "lot": 0.01},
}
SETTLE_HOURS = (0, 8, 16)  # funding exchange times, UTC (rate_exchange_interval = 28800 s)
NY = ZoneInfo("America/New_York")


@dataclass
class Market:
    symbol: str
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    tick: float
    lot: float
    step: int = 60  # bar size in seconds (60 = Delta 1m; 3600 = Binance 1h history)
    settle_idx: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    settle_rate: np.ndarray = field(default_factory=lambda: np.zeros(0))  # fraction per settlement
    _cache: dict = field(default_factory=dict, repr=False)

    @property
    def n(self) -> int:
        return len(self.t)

    def idx(self, ts) -> np.ndarray:
        """Bar index whose open time is ts (ts must be on the bar grid)."""
        return (np.asarray(ts, dtype=np.int64) - int(self.t[0])) // self.step

    def bars(self, minutes: int) -> pd.DataFrame:
        """Complete higher-timeframe bars aligned to UTC. `act` = 1m index where the bar's
        close is first usable (the 1m bar opening at the HTF bar's close time)."""
        if minutes in self._cache:
            return self._cache[minutes]
        step = minutes * 60
        key = self.t // step * step
        df = pd.DataFrame({"key": key, "o": self.o, "h": self.h, "l": self.l, "c": self.c, "v": self.v})
        g = df.groupby("key", sort=True).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"),
                                             c=("c", "last"), v=("v", "sum"), n=("o", "size"))
        g = g[g["n"] == minutes * 60 // self.step].drop(columns="n").reset_index().rename(columns={"key": "time"})
        g["act"] = self.idx(g["time"].to_numpy() + step)
        g = g[g["act"] < self.n].reset_index(drop=True)
        self._cache[minutes] = g
        return g

    def to_1m(self, bars: pd.DataFrame, values) -> np.ndarray:
        """Spread a higher-timeframe series onto 1m bars: value at 1m bar j is the latest HTF
        value whose bar closed at or before the open of j."""
        out = np.full(self.n, np.nan)
        out[bars["act"].to_numpy()] = np.asarray(values, dtype=float)
        return pd.Series(out).ffill().to_numpy()

    def day_starts(self) -> np.ndarray:
        """1m indices of every 00:00 UTC in the data."""
        return np.flatnonzero(self.t % 86400 == 0)

    def ny_time_index(self, hour: int, minute: int, weekdays_only: bool = True) -> np.ndarray:
        """1m indices of hh:mm America/New_York for each calendar day (DST-aware)."""
        days = pd.date_range(pd.to_datetime(self.t[0], unit="s").date(),
                             pd.to_datetime(self.t[-1], unit="s").date(), freq="D")
        out = []
        for d in days:
            if weekdays_only and d.weekday() >= 5:
                continue
            ts = pd.Timestamp(d.year, d.month, d.day, hour, minute, tz=NY).tz_convert("UTC").value // 10**9
            if (ts - int(self.t[0])) % self.step:
                continue
            j = (ts - int(self.t[0])) // self.step
            if 0 <= j < self.n:
                out.append(j)
        return np.asarray(out, dtype=np.int64)

    def ny_minute_of_day(self) -> np.ndarray:
        """Minutes since midnight America/New_York for every 1m bar (DST-aware)."""
        if "nymin" not in self._cache:
            ts = pd.to_datetime(self.t, unit="s", utc=True).tz_convert(NY)
            self._cache["nymin"] = (ts.hour * 60 + ts.minute).to_numpy()
        return self._cache["nymin"]


def load_market(symbol: str) -> Market:
    df = data.load(symbol, "1m", fill=True)
    t = df["time"].to_numpy(np.int64)
    m = Market(symbol, t, *(df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")),
               **SPECS[symbol])
    m.settle_idx, m.settle_rate = funding_schedule(t, data.load_funding(symbol))
    return m


def funding_schedule(t: np.ndarray, funding: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Settlement bar indices and the rate realised at each.

    ASSUMPTION: the rate realised at settlement T is the published rate in the hour before T
    (the 1h FUNDING candle opening at T-1h). Delta's published rate only changes at 00/08/16 UTC,
    i.e. it is fixed in advance for the coming settlement. Values are % per 8h -> divide by 100."""
    hours = (t % 86400) // 3600
    is_settle = (t % 3600 == 0) & np.isin(hours, SETTLE_HOURS)
    idx = np.flatnonzero(is_settle)
    f = funding.sort_values("time")
    rate_at = pd.merge_asof(pd.DataFrame({"time": t[idx] - 3600}), f[["time", "close"]], on="time")["close"]
    return idx.astype(np.int64), (rate_at.fillna(0.01).to_numpy() / 100.0)


def delta_settlements(symbol: str) -> pd.DataFrame:
    """Delta's realised funding per settlement (fraction), from the cached FUNDING:<symbol> history."""
    f = data.load_funding(symbol).sort_values("time")
    t = f["time"].to_numpy()
    hrs = (t % 86400) // 3600
    st = f[np.isin(hrs, [h - 1 if h else 23 for h in SETTLE_HOURS]) & (t % 3600 == 0)]
    return pd.DataFrame({"time": st["time"].to_numpy() + 3600, "rate": st["close"].to_numpy() / 100.0})


def load_binance_market(symbol: str) -> Market:
    """Binance USD-M perpetual 1h history (2020 onward) as a Market with step=3600.

    Prices: Binance BTCUSDT/ETHUSDT (proxy for Delta; 1h return correlation 0.999 over the overlap).
    Contract specs (tick, lot) and costs: Delta's.
    Funding at each 00/08/16 UTC settlement: Delta's actual rate where Delta history exists; before
    that, Binance's rate PLUS the average Delta-minus-Binance gap measured over the overlap
    (Delta's funding averaged ~0.003%/8h higher). ASSUMPTION, flagged in the report."""
    from core import binance_data as bd
    raw = pd.read_parquet(bd.path(symbol))
    t = raw["time"].to_numpy(np.int64)
    m = Market(symbol, t, *(raw[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")),
               step=3600, **SPECS[symbol])
    b = pd.read_parquet(bd.funding_path(symbol))[["time", "rate"]]
    d = delta_settlements(symbol)
    ov = d.merge(b, on="time", suffixes=("_d", "_b"))
    gap = float((ov["rate_d"] - ov["rate_b"]).mean())
    first_delta = int(d["time"].min())
    combo = pd.concat([b[b["time"] < first_delta].assign(rate=lambda x: x["rate"] + gap), d[d["time"] >= first_delta]])
    combo = combo.sort_values("time").drop_duplicates("time")
    hours = (t % 86400) // 3600
    idx = np.flatnonzero((t % 3600 == 0) & np.isin(hours, SETTLE_HOURS))
    rate = pd.merge_asof(pd.DataFrame({"time": t[idx]}), combo, on="time")["rate"].fillna(0.0001).to_numpy()
    m.settle_idx, m.settle_rate = idx.astype(np.int64), rate
    m._cache["funding_gap"] = gap
    m._cache["first_delta_funding"] = first_delta
    return m


# ---------------------------------------------------------------- Phase 4 loaders (data only; no rule changes)
DEFAULT_GAP_8H = 0.000034   # BTC/ETH average Delta-minus-Binance funding gap per 8h, measured in Phase 3


def fill_hourly(raw: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Reindex 1h candles to a complete hourly grid; missing hours become flat bars (no trading)."""
    t0, t1 = int(raw["time"].iloc[0]), int(raw["time"].iloc[-1])
    full = np.arange(t0, t1 + 3600, 3600, dtype=np.int64)
    df = raw.set_index("time").reindex(full)
    filled = int(df["close"].isna().sum())
    df["volume"] = df["volume"].fillna(0.0)
    df["close"] = df["close"].ffill()
    for c in ("open", "high", "low"):
        df[c] = df[c].fillna(df["close"])
    df.index.name = "time"
    return df.reset_index(), filled


def data_quality(raw: pd.DataFrame) -> dict:
    """Frozen Phase 4 exclusion rule: gap > 7 days or any 1h close-to-close move beyond +/-50%."""
    t = raw["time"].to_numpy()
    c = raw["close"].to_numpy()
    max_gap_h = float(np.diff(t).max() / 3600) if len(t) > 1 else 0.0
    max_move = float(np.abs(c[1:] / c[:-1] - 1).max()) if len(c) > 1 else 0.0
    return {"max_gap_hours": max_gap_h, "max_1h_move_pct": max_move * 100,
            "excluded": max_gap_h > 7 * 24 or max_move > 0.5}


def _binance_events(symbol: str) -> pd.DataFrame:
    from core import binance_data as bd
    f = pd.read_parquet(bd.funding_path(symbol)).sort_values("time").reset_index(drop=True)
    f["time"] = f["time"] // 3600 * 3600
    ih = f["interval_h"].to_numpy(dtype=float)
    gaps = np.diff(f["time"].to_numpy()) / 3600
    inferred = np.r_[gaps[:1], gaps] if len(gaps) else np.array([8.0])
    ih = np.where(np.isfinite(ih) & (ih > 0), ih, inferred)
    f["interval_h"] = np.clip(np.round(ih), 1, 8)
    return f[["time", "rate", "interval_h"]]


def _delta_events(symbol: str, interval_h: int) -> pd.DataFrame:
    """Delta settlements every `interval_h` hours; realised rate = published value in the hour before."""
    f = data.load_funding(symbol).sort_values("time")
    t = f["time"].to_numpy()
    st = f[((t + 3600) % (interval_h * 3600) == 0)]
    return pd.DataFrame({"time": st["time"].to_numpy() + 3600, "rate": st["close"].to_numpy() / 100.0,
                         "interval_h": float(interval_h)})


def load_phase4_market(symbol: str, lot: float, tick: float, delta_interval_h: int) -> Market:
    """Binance USD-M 1h history for a Part A coin, Delta contract specs, funding per frozen_rules.md s.3."""
    from core import binance_data as bd
    raw = pd.read_parquet(bd.path(symbol))
    dq = data_quality(raw)
    df, filled = fill_hourly(raw)
    t = df["time"].to_numpy(np.int64)
    m = Market(symbol, t, *(df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")),
               tick=tick, lot=lot, step=3600)
    be = _binance_events(symbol)
    be["per8"] = be["rate"] * 8 / be["interval_h"]
    try:
        de = _delta_events(symbol, delta_interval_h)
    except FileNotFoundError:
        de = pd.DataFrame(columns=["time", "rate", "interval_h"])
    gap_src, gap = "default BTC/ETH gap", DEFAULT_GAP_8H
    if len(de):
        de["per8"] = de["rate"] * 8 / de["interval_h"]
        a, b = max(de["time"].min(), be["time"].min()), min(de["time"].max(), be["time"].max())
        if (b - a) / 86400 >= 90:
            gap = float(de[(de.time >= a) & (de.time <= b)]["per8"].mean() - be[(be.time >= a) & (be.time <= b)]["per8"].mean())
            gap_src = f"measured over {(b - a) / 86400:.0f} days"
        first_delta = int(de["time"].min())
    else:
        first_delta = int(t[-1]) + 3600
    pre = be[be["time"] < first_delta].copy()
    pre["rate"] = pre["rate"] + gap * pre["interval_h"] / 8
    ev = pd.concat([pre[["time", "rate"]], de[["time", "rate"]] if len(de) else None]).sort_values("time")
    ev = ev.drop_duplicates("time")
    last_t = int(ev["time"].max())
    if last_t + 8 * 3600 <= t[-1]:   # carry the last known rate forward if a source runs out
        extra = np.arange(last_t + 8 * 3600, t[-1] + 1, 8 * 3600)
        ev = pd.concat([ev, pd.DataFrame({"time": extra, "rate": ev["rate"].iloc[-1]})])
    ev = ev[(ev["time"] > t[0]) & (ev["time"] <= t[-1])]
    m.settle_idx = m.idx(ev["time"].to_numpy(np.int64)).astype(np.int64)
    m.settle_rate = ev["rate"].to_numpy(float)
    m._cache.update(funding_gap_8h=gap, funding_gap_source=gap_src, filled_hours=filled, dq=dq,
                    first_delta_funding=first_delta)
    return m


def load_spot_market(symbol: str) -> Market:
    """Part B: Binance spot 1h BTC/ETH 2017-08 -> 2019-12, Delta specs, assumed funding 0.01% per 8h."""
    from core.phase4_data import spot_path
    raw = pd.read_parquet(spot_path(symbol))
    raw = raw[raw["time"] < pd.Timestamp("2020-01-01", tz="UTC").value // 10**9]
    dq = data_quality(raw)
    df, filled = fill_hourly(raw)
    t = df["time"].to_numpy(np.int64)
    m = Market(symbol, t, *(df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")),
               step=3600, **SPECS[symbol])
    hours = (t % 86400) // 3600
    idx = np.flatnonzero((t % 3600 == 0) & np.isin(hours, SETTLE_HOURS))
    m.settle_idx, m.settle_rate = idx.astype(np.int64), np.full(len(idx), 0.0001)
    m._cache.update(filled_hours=filled, dq=dq, funding_gap_source="assumed 0.01%/8h")
    return m
