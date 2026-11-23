"""Event-loop backtester on 1-minute bars.

Strategies hand the engine a table of order CANDIDATES (see `candidates()`); the engine walks them in
time order, takes a candidate only when flat, simulates the trade bar by bar on 1m data and books
fees, slippage, the Scalper Offer waiver and funding.

Execution rules
* Market entry: fills at the open of bar `fill` (the bar after the signal bar closed) + slippage.
* Limit entry/target: fills only if price trades at least 1 tick through the limit; fills at the
  limit price, maker fee, no slippage. No take-profit on the bar a limit entry fills (unknown order).
* Stop: stop-market. Intrabar hit fills at the stop price - slippage; a gap through the stop at the
  bar open fills at the open - slippage. Taker fee.
* Same 1m bar touches stop and target: the stop is assumed to have hit first.
* Time stop / end-of-day exit: market order at the open of the exit bar, taker fee + slippage.
* Dynamic targets (e.g. VWAP, Bollinger mid band) are resting limits re-priced every minute to the
  value known at the bar open; if the open is already beyond it, the exit is a market order.
* Funding: charged at 00/08/16 UTC on positions open across the settlement instant;
  P&L = -direction * rate * qty * price. Positive rate: longs pay.
* Scalper Offer: closing fee discounted (50% or 100%) when the position is closed less than
  30 minutes after it was opened. Liquidations never happen here (leverage <= 10x, hard stops).
* Sizing: qty so that a stop-out loses `risk` (0.5%) of current equity, capped at `max_lev` x
  equity notional, rounded DOWN to whole contracts. Trades smaller than one contract are skipped.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from core.market import Market

TAKER = 0.0005
MAKER = 0.0002
GST = 0.18
WAIVER_WINDOW_MIN = 30.0
MARKET, LIMIT = 0, 1
CHUNK = 2880


@dataclass(frozen=True)
class Scenario:
    name: str
    close_discount: float = 0.0      # 0 = standard fees, 0.5 = 50% off the close, 1.0 = free close
    time_cap: int | None = None      # forced time stop in minutes (29 in the offer scenarios)
    slip: float = 0.0001             # per side on market entries, market exits and stop fills
    maker_fills: bool = False        # 'maker scenario': market entries and time/signal exits are
                                     # assumed to fill as limit orders (maker fee, no slippage);
                                     # stops stay stop-market (taker + slippage). Optimistic.

    def with_slip(self, slip: float) -> "Scenario":
        return replace(self, slip=slip)


SCENARIOS = [
    Scenario("standard", 0.0, None),
    Scenario("offer_50", 0.5, 29),
    Scenario("offer_100", 1.0, 29),
]
STRESS_SLIP = 0.0003


# ------------------------------------------------------------------ candidates
FIELDS = {"sig": -1, "fill": -1, "dir": 0, "etype": MARKET, "px": np.nan, "stop": np.nan,
          "sdist": np.nan, "tgt": np.nan, "rr": np.nan, "dyn": 0, "maxb": 0, "exit_at": -1}


def candidates(**cols) -> dict:
    """Build a candidate table. Required: sig, fill, dir. Optional (scalar or array):
    etype (MARKET/LIMIT), px (limit price), stop (absolute) or sdist (distance from fill),
    tgt (absolute) or rr (R multiple) or dyn=1 (use the strategy's dynamic target array),
    maxb (time stop in BARS of the market, i.e. minutes on 1m data; 0 = none), exit_at (1m index to exit at its open, -1 = none)."""
    n = len(np.atleast_1d(cols["sig"]))
    out = {}
    for k, default in FIELDS.items():
        v = cols.get(k, default)
        dtype = float if isinstance(default, float) else np.int64
        out[k] = np.broadcast_to(np.asarray(v, dtype=dtype), (n,)).copy()
    order = np.lexsort((out["sig"], out["fill"]))
    return {k: v[order] for k, v in out.items()}


def empty_candidates() -> dict:
    return candidates(sig=np.zeros(0, np.int64), fill=np.zeros(0, np.int64), dir=np.zeros(0, np.int64))


def limit_fill_index(low: np.ndarray, high: np.ndarray, start: int, end: int, direction: int,
                     price: float, tick: float, cancel_level: float = np.nan) -> int:
    """First bar in [start, end) where a resting limit at `price` fills (1 tick through), or -1.
    Buy (direction>0) fills when low <= price - tick. If `cancel_level` is given, the order is
    cancelled once price reaches it first (high >= level for a buy, low <= level for a sell)."""
    if end <= start:
        return -1
    lo, hi = low[start:end], high[start:end]
    fill = np.flatnonzero(lo <= price - tick) if direction > 0 else np.flatnonzero(hi >= price + tick)
    f = fill[0] if fill.size else -1
    if not np.isnan(cancel_level):
        c = np.flatnonzero(hi >= cancel_level) if direction > 0 else np.flatnonzero(lo <= cancel_level)
        if c.size and (f < 0 or c[0] < f):
            return -1
    return start + f if f >= 0 else -1


# ------------------------------------------------------------------ trade path
def _first(mask: np.ndarray) -> int:
    i = np.flatnonzero(mask)
    return int(i[0]) if i.size else -1


def path_exit(m: Market, fill: int, d: int, etype: int, stop: float, tgt: float,
              dyn: np.ndarray | None, j_end: int):
    """Walk a position from bar `fill` until stop / target / dynamic target / bar `j_end`.
    Returns (exit_pos, raw_exit_price, kind, maker_exit). exit_pos is in bar units: k for an exit at
    the open of bar k, k+0.5 for an intrabar exit in bar k."""
    o, h, l = m.o, m.h, m.l
    tick = m.tick
    tstart = fill + 1 if etype == LIMIT else fill
    a = fill
    j_end = min(j_end, m.n)
    while a < j_end:
        b = min(j_end, a + CHUNK)
        best = None  # (bar, priority, pos, price, kind, maker)
        # stop
        s = _first(l[a:b] <= stop) if d > 0 else _first(h[a:b] >= stop)
        if s >= 0:
            k = a + s
            gap = k > fill and ((o[k] <= stop) if d > 0 else (o[k] >= stop))
            best = (k, 0, k, o[k], "stop", False) if gap else (k, 2, k + 0.5, stop, "stop", False)
        # fixed target
        ta = max(a, tstart)
        if not np.isnan(tgt) and ta < b:
            g = _first(h[ta:b] >= tgt + tick) if d > 0 else _first(l[ta:b] <= tgt - tick)
            if g >= 0:
                k = ta + g
                cand = (k, 3, k + 0.5, tgt, "target", True)
                best = cand if best is None or cand[:2] < best[:2] else best
        # dynamic target
        if dyn is not None:
            da = max(a, fill + 1)
            if da < b:
                lvl = dyn[da:b]
                oc = _first(o[da:b] >= lvl) if d > 0 else _first(o[da:b] <= lvl)
                if oc >= 0:
                    k = da + oc
                    cand = (k, 1, k, o[k], "dyn_open", False)
                    best = cand if best is None or cand[:2] < best[:2] else best
            da2 = max(a, tstart)
            if da2 < b:
                lvl = dyn[da2:b]
                ib = _first(h[da2:b] >= lvl + tick) if d > 0 else _first(l[da2:b] <= lvl - tick)
                if ib >= 0:
                    k = da2 + ib
                    cand = (k, 3, k + 0.5, dyn[k], "dyn_target", True)
                    best = cand if best is None or cand[:2] < best[:2] else best
        if best is not None:
            return best[2], best[3], best[4], best[5]
        a = b
    if j_end < m.n:
        return float(j_end), o[j_end], "time", False
    return float(m.n), m.c[-1], "end", False


def funding_paid(m: Market, entry_pos: float, exit_pos: float, d: int, qty: float) -> float:
    """Funding P&L (negative = paid) for settlements strictly inside (entry_pos, exit_pos)."""
    lo = np.searchsorted(m.settle_idx, entry_pos, side="right")
    hi = np.searchsorted(m.settle_idx, exit_pos, side="left")
    if hi <= lo:
        return 0.0
    ks = m.settle_idx[lo:hi]
    return float(-d * np.sum(m.settle_rate[lo:hi] * m.o[ks]) * qty)


def trade_costs(entry: float, exit_: float, qty: float, etype: int, maker_exit: bool,
                hold_min: float, sc: Scenario) -> tuple[float, bool]:
    fee_in = (MAKER if etype == LIMIT else TAKER) * (1 + GST) * qty * entry
    fee_out = (MAKER if maker_exit else TAKER) * (1 + GST) * qty * exit_
    fee_free = sc.close_discount > 0 and hold_min < WAIVER_WINDOW_MIN
    if fee_free:
        fee_out *= 1 - sc.close_discount
    return fee_in + fee_out, fee_free


# ------------------------------------------------------------------ main loop
RUIN_FRACTION = 0.10  # stop trading once equity falls to 10% of the starting balance


def run(m: Market, cand: dict, start: int, end: int, sc: Scenario, dyn_long=None, dyn_short=None,
        equity0: float = 1000.0, risk: float = 0.005, max_lev: float = 10.0) -> pd.DataFrame:
    """Simulate candidates whose fill bar is in [start, end). Trades may finish after `end`.
    Trading halts ('ruined') if equity drops to RUIN_FRACTION of equity0."""
    sig, fill, dirs = cand["sig"], cand["fill"], cand["dir"]
    i = int(np.searchsorted(fill, start, side="left"))
    N = int(np.searchsorted(fill, end, side="left"))
    free = start
    equity = equity0
    rows = []
    skipped_small = invalid = 0
    ruined_at = None
    while i < N:
        if equity <= RUIN_FRACTION * equity0:
            ruined_at = int(fill[i - 1]) if i else start
            break
        if sig[i] < free or fill[i] < free:
            i += 1
            continue
        f, d, et = int(fill[i]), int(dirs[i]), int(cand["etype"][i])
        if et == LIMIT:
            entry, entry_pos = float(cand["px"][i]), f + 0.5
        else:
            entry, entry_pos = (m.o[f] if sc.maker_fills else m.o[f] * (1 + d * sc.slip)), float(f)
        stop = cand["stop"][i] if not np.isnan(cand["stop"][i]) else entry - d * cand["sdist"][i]
        dist = (entry - stop) * d
        if not dist > 0:
            invalid += 1
            i += 1
            continue
        if not np.isnan(cand["tgt"][i]):
            tgt = cand["tgt"][i]
        elif not np.isnan(cand["rr"][i]):
            tgt = entry + d * cand["rr"][i] * dist
        else:
            tgt = np.nan
        dyn = None
        if cand["dyn"][i]:
            dyn = dyn_long if d > 0 else dyn_short
        maxb = int(cand["maxb"][i])
        if sc.time_cap:
            cap = max(1, int(sc.time_cap * 60 // m.step))
            maxb = min(maxb, cap) if maxb else cap
        j_end = m.n
        if maxb:
            j_end = min(j_end, f + maxb)
        if cand["exit_at"][i] >= 0:
            j_end = min(j_end, int(cand["exit_at"][i]))
        if j_end <= f:
            invalid += 1
            i += 1
            continue
        # sizing
        qty = risk * equity / dist
        capped = qty * entry > max_lev * equity
        if capped:
            qty = max_lev * equity / entry
        qty = np.floor(qty / m.lot + 1e-9) * m.lot
        if qty <= 0:
            skipped_small += 1
            i += 1
            continue
        exit_pos, raw, kind, maker_exit = path_exit(m, f, d, et, stop, tgt, dyn, j_end)
        if sc.maker_fills and kind in ("time", "end", "dyn_open"):
            maker_exit = True
        exit_px = raw if maker_exit else raw * (1 - d * sc.slip)
        hold = (exit_pos - entry_pos) * m.step / 60.0   # minutes
        gross = d * (exit_px - entry) * qty
        fees, fee_free = trade_costs(entry, exit_px, qty, LIMIT if sc.maker_fills else et, maker_exit, hold, sc)
        fund = funding_paid(m, entry_pos, exit_pos, d, qty)
        net = gross - fees + fund
        risk_usd = qty * dist
        tgt_frac = abs(tgt - entry) / entry if not np.isnan(tgt) else (
            abs(dyn[min(f + 1, m.n - 1)] - entry) / entry if dyn is not None else np.nan)
        rows.append((f, int(np.floor(exit_pos)) if exit_pos < m.n else m.n - 1, d, et, entry, exit_px,
                     stop, tgt, qty, qty * entry / equity, capped, kind, hold, gross, fees, fund, net,
                     net / risk_usd, equity, fee_free, dist / entry, tgt_frac, j_end - f))
        equity += net
        free = int(np.ceil(exit_pos))  # exit at open of k -> flat from k; intrabar in k -> from k+1
        i += 1
    cols = ["fill", "exit_bar", "dir", "etype", "entry", "exit", "stop", "target", "qty", "leverage",
            "capped", "exit_kind", "hold_min", "gross", "fees", "funding", "net", "R", "equity_before",
            "fee_free", "stop_frac", "tgt_frac", "max_hold"]
    df = pd.DataFrame(rows, columns=cols)
    df.attrs.update(skipped_small=skipped_small, invalid=invalid, equity0=equity0, ruined_at=ruined_at,
                    start=start, end=end, symbol=m.symbol, scenario=sc.name, slip=sc.slip)
    if len(df):
        df["entry_time"] = pd.to_datetime(m.t[df["fill"].to_numpy()], unit="s", utc=True)
        df["exit_time"] = pd.to_datetime(m.t[df["exit_bar"].to_numpy()], unit="s", utc=True)
    return df


def net_r_fraction(entry: float, exit_px: float, d: int, etype: int, maker_exit: bool, hold: float,
                   stop_frac: float, sc: Scenario, fund_frac: float) -> float:
    """Net R of a trade in size-free terms (used by the random baseline)."""
    gross = d * (exit_px - entry) / entry
    fees, _ = trade_costs(1.0, exit_px / entry, 1.0, etype, maker_exit, hold, sc)
    return (gross - fees + fund_frac) / stop_frac


def random_baseline(m: Market, trades: pd.DataFrame, start: int, end: int, sc: Scenario,
                    n_sims: int = 200, seed: int = 7) -> np.ndarray:
    """Net-R totals of `n_sims` random-entry runs. Each run uses the same number of trades as the
    strategy, with the strategy's direction mix, stop and target distances, time limits and entry
    order type re-assigned at random entry bars inside [start, end). Returns array of net-R sums."""
    rng = np.random.default_rng(seed)
    K = len(trades)
    if K == 0:
        return np.zeros(n_sims)
    dirs = trades["dir"].to_numpy()
    etypes = trades["etype"].to_numpy()
    sf = trades["stop_frac"].to_numpy()
    tf = trades["tgt_frac"].to_numpy()
    mh = trades["max_hold"].to_numpy()
    pool = np.arange(start, end - 1)
    out = np.empty(n_sims)
    for s in range(n_sims):
        entries = np.sort(rng.choice(pool, K, replace=K > len(pool)))
        perm = rng.permutation(K)
        total = 0.0
        for e, p in zip(entries, perm):
            d, et = int(dirs[p]), int(etypes[p])
            mk = sc.maker_fills or et == LIMIT
            entry = m.o[e] if mk else m.o[e] * (1 + d * sc.slip)
            stop = entry * (1 - d * sf[p])
            tgt = entry * (1 + d * tf[p]) if not np.isnan(tf[p]) else np.nan
            j_end = min(m.n, e + int(mh[p]))
            if sc.time_cap:
                j_end = min(j_end, e + max(1, int(sc.time_cap * 60 // m.step)))
            pos, raw, kind, maker = path_exit(m, int(e), d, MARKET, stop, tgt, None, max(j_end, e + 1))
            if sc.maker_fills and kind in ("time", "end"):
                maker = True
            exit_px = raw if maker else raw * (1 - d * sc.slip)
            fund = funding_paid(m, float(e), pos, d, 1.0) / entry
            total += net_r_fraction(entry, exit_px, d, LIMIT if mk else MARKET, maker, (pos - e) * m.step / 60.0,
                                    sf[p], sc, fund)
        out[s] = total
    return out
