"""Compare many simple strategies across timeframes on Delta Exchange candles.

Every strategy is tested with the same engine and the same rules:
* signals are read at candle CLOSE and filled at the NEXT candle's open;
* stop-loss / take-profit are checked inside each candle (stop first if both hit);
* fixed notional per trade at 1x, no compounding -> returns are "% of account";
* costs charged per side; funding is not modelled.

Usage:
    for r in 15m 30m 1h 4h; do python3 backtest/fetch_data.py BTCUSD ETHUSD --resolution $r --days 520; done
    python3 backtest/strategies.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from fetch_data import RESOLUTION_SECONDS, csv_path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
GST = 0.18
TAKER = 0.0005 * (1 + GST) + 0.0001  # market orders: 0.05% + GST + 0.01% slippage, per side
MAKER = 0.0002 * (1 + GST)           # limit orders: 0.02% + GST, per side


# ---------------------------------------------------------------- indicators
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def supertrend_dir(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> np.ndarray:
    a = atr(df, n).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    c = df["close"].to_numpy()
    ub, lb = hl2 + mult * a, hl2 - mult * a
    d = np.ones(len(c), dtype=int)
    for i in range(1, len(c)):
        if not (ub[i] < ub[i - 1] or c[i - 1] > ub[i - 1]):
            ub[i] = ub[i - 1]
        if not (lb[i] > lb[i - 1] or c[i - 1] < lb[i - 1]):
            lb[i] = lb[i - 1]
        d[i] = 1 if c[i] > ub[i - 1] else -1 if c[i] < lb[i - 1] else d[i - 1]
    return d


def cross_up(a, b) -> np.ndarray:
    a, b = np.asarray(a, float), np.asarray(b, float)
    out = np.zeros(len(a), bool)
    out[1:] = (a[1:] > b[1:]) & (a[:-1] <= b[:-1])
    return out


def cross_dn(a, b) -> np.ndarray:
    return cross_up(b, a)


# ---------------------------------------------------------------- strategies
# Each returns: le/se (long/short entry), lx/sx (exit), optional stop distances and reward:risk.
def sig(le, se, lx=None, sx=None, stop_l=None, stop_s=None, rr=None) -> dict:
    z = np.zeros(len(le), bool)
    return {"le": np.asarray(le, bool), "se": np.asarray(se, bool),
            "lx": z if lx is None else np.asarray(lx, bool), "sx": z if sx is None else np.asarray(sx, bool),
            "stop_l": stop_l, "stop_s": stop_s, "rr": rr}


def ema_cross(fast, slow, trend=None):
    def f(df):
        c = df["close"]
        a, b = ema(c, fast), ema(c, slow)
        up, dn = cross_up(a, b), cross_dn(a, b)
        if trend is None:
            return sig(up, dn)  # stop-and-reverse
        t = ema(c, trend)
        return sig(up & (c > t).to_numpy(), dn & (c < t).to_numpy(), lx=dn, sx=up)
    return f


def supertrend(n=10, mult=3.0, trend=None):
    def f(df):
        d = supertrend_dir(df, n, mult)
        up, dn = cross_up(d, np.zeros(len(d))), cross_dn(d, np.zeros(len(d)))
        if trend is None:
            return sig(up, dn)
        c = df["close"]
        t = ema(c, trend)
        return sig(up & (c > t).to_numpy(), dn & (c < t).to_numpy(), lx=dn, sx=up)
    return f


def donchian(entry_n, exit_n):
    def f(df):
        c = df["close"]
        hi, lo = df["high"].rolling(entry_n).max().shift(1), df["low"].rolling(entry_n).min().shift(1)
        xhi, xlo = df["high"].rolling(exit_n).max().shift(1), df["low"].rolling(exit_n).min().shift(1)
        return sig(c > hi, c < lo, lx=c < xlo, sx=c > xhi)
    return f


def macd(trend=None):
    def f(df):
        c = df["close"]
        line = ema(c, 12) - ema(c, 26)
        signal = ema(line, 9)
        up, dn = cross_up(line, signal), cross_dn(line, signal)
        if trend is None:
            return sig(up, dn)
        t = ema(c, trend)
        return sig(up & (c > t).to_numpy(), dn & (c < t).to_numpy(), lx=dn, sx=up)
    return f


def rsi_reversion(df):
    r, a = rsi(df["close"]), atr(df).to_numpy()
    lo, hi = np.full(len(r), 30.0), np.full(len(r), 70.0)
    return sig(cross_dn(r, lo), cross_up(r, hi), lx=r > 50, sx=r < 50, stop_l=3 * a, stop_s=3 * a)


def bollinger_reversion(df):
    c, a = df["close"], atr(df).to_numpy()
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    return sig(cross_dn(c, mid - 2 * sd), cross_up(c, mid + 2 * sd), lx=c >= mid, sx=c <= mid,
               stop_l=3 * a, stop_s=3 * a)


def bollinger_breakout(df):
    c = df["close"]
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    return sig(c > mid + 2 * sd, c < mid - 2 * sd, lx=c < mid, sx=c > mid)


def rsi_trend_pullback(df):
    c, a = df["close"], atr(df).to_numpy()
    r, t = rsi(c), ema(c, 200)
    lo, hi = np.full(len(r), 40.0), np.full(len(r), 60.0)
    return sig(cross_dn(r, lo) & (c > t).to_numpy(), cross_up(r, hi) & (c < t).to_numpy(),
               lx=r > 60, sx=r < 40, stop_l=3 * a, stop_s=3 * a)


def smc_liquidity_sweep(df):
    """Price takes out the prior 20-candle low/high, then closes back inside. Stop beyond the wick, 2R target."""
    c, h, l, a = df["close"], df["high"], df["low"], atr(df)
    plo, phi = l.rolling(20).min().shift(1), h.rolling(20).max().shift(1)
    return sig((l < plo) & (c > plo), (h > phi) & (c < phi),
               stop_l=(c - l + 0.1 * a).to_numpy(), stop_s=(h - c + 0.1 * a).to_numpy(), rr=2.0)


def smc_fvg_retest(df):
    """Fair value gap in the direction of the 200 EMA trend; enter on the first retest within 10 candles.
    Stop beyond the gap, 2R target. (Simplified: entry at next open after the retest candle, not a resting limit.)"""
    c, h, l = df["close"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy()
    a, t = atr(df).to_numpy(), ema(df["close"], 200).to_numpy()
    n = len(c)
    le, se = np.zeros(n, bool), np.zeros(n, bool)
    stop_l, stop_s = np.full(n, np.nan), np.full(n, np.nan)
    for i in range(2, n):
        if l[i] - h[i - 2] > 0.2 * a[i] and c[i] > t[i]:  # bullish gap: [h[i-2], l[i]]
            top, bot = l[i], h[i - 2]
            for u in range(i + 1, min(i + 11, n)):
                if l[u] <= top:
                    if c[u] > bot:
                        le[u], stop_l[u] = True, c[u] - bot + 0.1 * a[u]
                    break
        if l[i - 2] - h[i] > 0.2 * a[i] and c[i] < t[i]:  # bearish gap: [h[i], l[i-2]]
            bot, top = h[i], l[i - 2]
            for u in range(i + 1, min(i + 11, n)):
                if h[u] >= bot:
                    if c[u] < top:
                        se[u], stop_s[u] = True, top - c[u] + 0.1 * a[u]
                    break
    return sig(le, se, stop_l=stop_l, stop_s=stop_s, rr=2.0)


STRATEGIES = {
    "EMA 9/21 cross": ema_cross(9, 21),
    "EMA 20/50 cross": ema_cross(20, 50),
    "EMA 50/200 cross": ema_cross(50, 200),
    "EMA 9/21 + 200 EMA filter": ema_cross(9, 21, trend=200),
    "Supertrend (10,3)": supertrend(),
    "Supertrend + 200 EMA filter": supertrend(trend=200),
    "Donchian breakout 20/10": donchian(20, 10),
    "Donchian breakout 55/20": donchian(55, 20),
    "MACD cross": macd(),
    "MACD + 200 EMA filter": macd(trend=200),
    "Bollinger breakout": bollinger_breakout,
    "RSI 30/70 reversion": rsi_reversion,
    "Bollinger reversion": bollinger_reversion,
    "RSI pullback in trend": rsi_trend_pullback,
    "SMC liquidity sweep": smc_liquidity_sweep,
    "SMC fair value gap retest": smc_fvg_retest,
}


# ---------------------------------------------------------------- engine
def simulate(df: pd.DataFrame, s: dict, start: int, cost: float):
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    le, se, lx, sx, stop_l, stop_s, rr = (s[k] for k in ("le", "se", "lx", "sx", "stop_l", "stop_s", "rr"))
    n = len(c)
    pos, entry, stop, tp = 0, 0.0, np.nan, np.nan
    realised = 0.0
    eq = np.zeros(n)
    trades = []  # (exit_idx, direction, gross)
    want_exit, want_entry, want_stop = False, 0, np.nan

    def close_at(price, t):
        nonlocal pos, realised
        gross = pos * (price / entry - 1)
        realised += gross - 2 * cost
        trades.append((t, pos, gross))
        pos = 0

    for t in range(start, n):
        if want_exit and pos:
            close_at(o[t], t)
        if want_entry and not pos:
            pos, entry = want_entry, o[t]
            stop = entry - pos * want_stop if want_stop == want_stop else np.nan
            tp = entry + pos * rr * want_stop if (rr and want_stop == want_stop) else np.nan
        if pos > 0:
            if l[t] <= stop:
                close_at(min(o[t], stop), t)
            elif h[t] >= tp:
                close_at(max(o[t], tp), t)
        elif pos < 0:
            if h[t] >= stop:
                close_at(max(o[t], stop), t)
            elif l[t] <= tp:
                close_at(min(o[t], tp), t)

        want_exit = bool(pos and ((pos > 0 and (lx[t] or se[t])) or (pos < 0 and (sx[t] or le[t]))))
        want_entry, want_stop = 0, np.nan
        if not pos or want_exit:
            if le[t] and not se[t]:
                want_entry, want_stop = 1, (stop_l[t] if stop_l is not None else np.nan)
            elif se[t] and not le[t]:
                want_entry, want_stop = -1, (stop_s[t] if stop_s is not None else np.nan)
        eq[t] = realised + (pos * (c[t] / entry - 1) - cost if pos else 0.0)
    if pos:
        close_at(c[-1], n - 1)
        eq[-1] = realised
    return trades, eq[start:]


def evaluate(df: pd.DataFrame, s: dict, start: int) -> dict:
    trades, eq = simulate(df, s, start, TAKER)
    if not trades:
        return {"trades": 0}
    idx, side, gross = (np.array(x) for x in zip(*trades))
    net = gross - 2 * TAKER
    wins, losses = net[net > 0].sum(), -net[net <= 0].sum()
    half = start + (len(df) - start) // 2
    return {
        "trades": len(net),
        "win_%": (net > 0).mean() * 100,
        "net_taker_%": net.sum() * 100,
        "net_maker_%": (gross - 2 * MAKER).sum() * 100,
        "gross_%": gross.sum() * 100,
        "profit_factor": wins / losses if losses > 0 else np.inf,
        "max_dd_%": (np.maximum.accumulate(eq) - eq).max() * 100,
        "h1_net_%": net[idx < half].sum() * 100,
        "h2_net_%": net[idx >= half].sum() * 100,
        "long_net_%": net[side > 0].sum() * 100,
        "short_net_%": net[side < 0].sum() * 100,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSD", "ETHUSD"])
    parser.add_argument("--resolutions", nargs="+", default=["15m", "30m", "1h", "4h"])
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()

    rows = []
    for res in args.resolutions:
        step = RESOLUTION_SECONDS[res]
        for symbol in args.symbols:
            df = pd.read_csv(csv_path(symbol, res))
            start = len(df) - args.days * 86400 // step
            if start < 250:
                raise SystemExit(f"{symbol} {res}: not enough warm-up history, fetch more days")
            for name, fn in STRATEGIES.items():
                rows.append({"strategy": name, "tf": res, "symbol": symbol, **evaluate(df, fn(df), start)})
    out = pd.DataFrame(rows)
    RESULTS_DIR.mkdir(exist_ok=True)
    out.to_csv(RESULTS_DIR / "strategy_comparison.csv", index=False)

    pd.set_option("display.width", 250, "display.max_rows", 500)
    g = out.groupby(["strategy", "tf"], sort=False)
    summary = g.agg(trades=("trades", "mean"), net_taker=("net_taker_%", "mean"), net_maker=("net_maker_%", "mean"),
                    worst_symbol=("net_taker_%", "min"), pf=("profit_factor", "mean"), max_dd=("max_dd_%", "max"),
                    worst_half=("h1_net_%", "min"), worst_half2=("h2_net_%", "min"),
                    long_net=("long_net_%", "mean"), short_net=("short_net_%", "mean"))
    summary["worst_half"] = summary[["worst_half", "worst_half2"]].min(axis=1)
    summary = summary.drop(columns="worst_half2")
    # Robust = profitable on BOTH coins in BOTH halves of the year, after market-order costs.
    summary["robust"] = (summary["worst_symbol"] > 0) & (summary["worst_half"] > 0)
    summary = summary.sort_values("net_taker", ascending=False)
    print("Average of BTC and ETH, last", args.days, "days. Returns in % of account at 1x, after costs.\n")
    print(summary.round(2).to_string())
    summary.round(2).to_csv(RESULTS_DIR / "strategy_summary.csv")


if __name__ == "__main__":
    main()
