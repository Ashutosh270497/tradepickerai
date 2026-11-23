"""Standard indicators (Wilder smoothing where conventional). Inputs are pandas Series; every
value at row i uses only rows <= i."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False).mean()


def atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return wilder(tr, n)


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up, dn = wilder(d.clip(lower=0), n), wilder(-d.clip(upper=0), n)
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def adx(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    up, dn = h.diff(), -l.diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    a = atr(h, l, c, n)
    pdi, mdi = 100 * wilder(plus, n) / a, 100 * wilder(minus, n) / a
    return wilder(100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan), n)


def bollinger(c: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(c, n)
    sd = c.rolling(n).std(ddof=0)
    return mid - k * sd, mid, mid + k * sd


def confirmed_swings(h: np.ndarray, l: np.ndarray, n: int):
    """Fractal swings with n bars each side. Returns arrays (last_swing_high, last_swing_low) where
    element j is the most recent swing whose CONFIRMATION (n bars to its right) completed at or
    before bar j's close. This is causal: a swing at bar i is only visible from bar i+n."""
    size = len(h)
    sh = np.full(size, np.nan)
    sl = np.full(size, np.nan)
    hs = pd.Series(h)
    ls = pd.Series(l)
    left_max = hs.shift(1).rolling(n).max().to_numpy()
    right_max = hs[::-1].shift(1).rolling(n).max()[::-1].to_numpy()
    left_min = ls.shift(1).rolling(n).min().to_numpy()
    right_min = ls[::-1].shift(1).rolling(n).min()[::-1].to_numpy()
    is_h = (h > left_max) & (h >= right_max)
    is_l = (l < left_min) & (l <= right_min)
    for i in np.flatnonzero(is_h):
        if i + n < size:
            sh[i + n] = h[i]
    for i in np.flatnonzero(is_l):
        if i + n < size:
            sl[i + n] = l[i]
    return pd.Series(sh).ffill().to_numpy(), pd.Series(sl).ffill().to_numpy()
