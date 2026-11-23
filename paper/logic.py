"""One 4h-close step of the shadow paper trader for one coin.

Everything that decides or prices a trade is the backtest's own code:
  signal + stop distance  -> strategies.trend_ma_4h.build (DEFAULT params, frozen)
  stop / gap detection    -> core.engine.path_exit
  position size           -> core.engine.position_size
  fees                    -> core.engine.trade_costs
  funding                 -> core.engine.funding_events
The only difference from the backtest is the reference price for entries and time exits: the live last
traded price a few minutes after the 4h close instead of the 1h bar's open (in replay/test mode the bar
open is used, which makes the paper trader reproduce engine.run exactly).

Stops are treated as resting stop-market orders on the exchange (frozen rules): they are detected from
Delta's 1h candles, so a stop that triggers between runs - or while the trader is down - still fills at
the stop price minus slippage, exactly as in the backtest. Entries and time exits need the trader to be
running: missed 4h closes are logged and the next run acts at its own live price.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.engine import GST, MARKET, TAKER, Scenario, funding_events, path_exit, position_size, trade_costs
from core.market import Market, fill_hourly
from strategies import trend_ma_4h as S

SLIP = 0.0001          # frozen: 0.01% per side
RISK = 0.005           # frozen: 0.5% of equity per trade
MAX_LEV = 3.0          # frozen: 3x notional cap
SC = Scenario("taker", slip=SLIP)
BAR = 3600
FOUR_H = 4 * 3600
HOLD_SECONDS = int(S.DEFAULT["hold_4h"]) * FOUR_H     # 20 days


def market_until(store, coin: str, T: int, ref_price: float, lot: float, tick: float, interval_h: int) -> Market:
    """Market of stored 1h candles with open time < T, plus a placeholder bar at T (open = ref price).
    The placeholder is never part of a completed 4h/1D bar, so it cannot influence any signal; it only
    gives the 4h close at T an index (the engine's 'act' convention) and a price for funding at T."""
    anchor = store.get_meta("history_anchor")
    rows = store.db.execute("SELECT time, o, h, l, c, v FROM candles WHERE coin=? AND time>=? AND time<? ORDER BY time",
                            (coin, anchor, T)).fetchall()
    if not rows:
        raise RuntimeError(f"{coin}: no candles stored")
    raw = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df, _ = fill_hourly(raw)
    if int(df["time"].iloc[-1]) != T - BAR:
        raise RuntimeError(f"{coin}: latest stored candle {int(df['time'].iloc[-1])} is not the bar before {T}")
    ph = pd.DataFrame([{"time": T, "open": ref_price, "high": ref_price, "low": ref_price, "close": ref_price, "volume": 0.0}])
    df = pd.concat([df, ph], ignore_index=True)
    t = df["time"].to_numpy(np.int64)
    m = Market(coin, t, *(df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")),
               tick=tick, lot=lot, step=BAR)
    fr = store.db.execute("SELECT time, rate_pct FROM funding_raw WHERE coin=? AND time>=? AND time<? ORDER BY time",
                          (coin, anchor, T)).fetchall()
    if fr:
        f = pd.DataFrame(fr, columns=["time", "rate_pct"])
        st = f[(f["time"] + BAR) % (interval_h * 3600) == 0]
        times = st["time"].to_numpy(np.int64) + BAR
        keep = (times > t[0]) & (times <= T)
        m.settle_idx = m.idx(times[keep]).astype(np.int64)
        m.settle_rate = st["rate_pct"].to_numpy(float)[keep] / 100.0
    return m


def _fill_row(db, pos_id, coin, side, kind, T, now, ref, model, qty, quote, live):
    q = quote or {}
    db.execute("""INSERT INTO fills(position_id, coin, side, kind, bar_time, decided_at, ref_price, model_price, qty,
                  best_bid, best_ask, bid_size, ask_size, mark, ltp, quote_time, live_quote)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(position_id, kind) DO NOTHING""",
               (pos_id, coin, side, kind, T, now, ref, model, qty, q.get("best_bid"), q.get("best_ask"),
                q.get("bid_size"), q.get("ask_size"), q.get("mark"), q.get("ltp"), q.get("quote_time"), int(live)))


def process_coin(store, cfg: dict, T: int, quote: dict, live: bool, paused: bool, now: int) -> list[str]:
    """Run the frozen rules for one coin at the 4h close T. Idempotent: a (coin, T) pair is processed once."""
    coin = cfg["coin"]
    if store.coin_done(coin, T):
        return [f"{coin}: bar already processed"]
    ref = float(quote["ltp"] if live else quote["ref"])
    m = market_until(store, coin, T, ref, cfg["lot"], cfg["tick"], cfg["funding_interval_h"])
    iT = int(m.idx(T))
    msgs = []
    with store.tx() as db:
        pos = store.open_position(coin)
        if pos:
            d, qty = int(pos["dir"]), float(pos["qty"])
            f = int(m.idx(pos["entry_time"]))
            exit_pos, raw, kind, _ = path_exit(m, f, d, MARKET, float(pos["stop"]), np.nan, None, iT)
            closed = None
            if kind == "stop" and exit_pos < iT:
                closed = ("stop", exit_pos, raw, raw * (1 - d * SLIP), None, False)
            elif T >= int(pos["time_exit_time"]):
                closed = ("time", float(iT), ref, ref * (1 - d * SLIP), quote, live)
            upper = closed[1] if closed else iT + 0.5
            ks, rates, pnl = funding_events(m, float(f), upper, d, qty)
            for k, rate, p in zip(ks, rates, pnl):
                db.execute("""INSERT INTO funding_applied(position_id, coin, settle_time, rate, price, qty, pnl)
                              VALUES(?,?,?,?,?,?,?) ON CONFLICT(position_id, settle_time) DO NOTHING""",
                           (pos["id"], coin, int(m.t[k]), float(rate), float(m.o[k]), qty, float(p)))
            fund = db.execute("SELECT COALESCE(SUM(pnl),0) s FROM funding_applied WHERE position_id=?", (pos["id"],)).fetchone()["s"]
            db.execute("UPDATE positions SET funding=? WHERE id=?", (fund, pos["id"]))
            if closed:
                kind, xpos, xref, xpx, xq, xlive = closed
                entry = float(pos["entry_price"])
                hold_min = (xpos - f) * 60.0
                fees, _ = trade_costs(entry, xpx, qty, MARKET, False, hold_min, SC)
                gross = d * (xpx - entry) * qty
                net = gross - fees + fund
                R = net / (qty * float(pos["stop_dist"]))
                exit_time = int(m.t[int(np.floor(xpos))])
                db.execute("""UPDATE positions SET status='closed', exit_time=?, exit_pos_hours=?, exit_price=?, exit_ref=?,
                              exit_kind=?, exit_fee=?, gross=?, net=?, R=? WHERE id=?""",
                           (exit_time, xpos - f, xpx, xref, kind, fees - float(pos["entry_fee"]), gross, net, R, pos["id"]))
                _fill_row(db, pos["id"], coin, "sell" if d > 0 else "buy", "exit_" + kind, T, now, xref, xpx, qty, xq, xlive)
                msgs.append(f"EXIT {coin} {'long' if d > 0 else 'short'} ({kind}) qty {qty:g} @ {xpx:.6g} | "
                            f"net {net:+.2f} USD ({R:+.2f}R), funding {fund:+.2f}")
                store.log("info", msgs[-1], coin, db=db, now=now)
                pos = None
        if pos is None:
            c, _, _ = S.build(m, S.DEFAULT)
            hit = np.flatnonzero(c["fill"] == iT)
            ruined = _realized(db, coin) <= 0.10 * cfg["capital"]   # frozen ruin rule
            if len(hit) and not paused and not ruined:
                j = int(hit[0])
                d, sdist = int(c["dir"][j]), float(c["sdist"][j])
                entry = ref * (1 + d * SLIP)
                eq = _realized(db, coin)
                qty, capped = position_size(eq, entry, sdist, cfg["lot"], RISK, MAX_LEV)
                if qty > 0:
                    fee = TAKER * (1 + GST) * qty * entry
                    cur = db.execute("""INSERT INTO positions(coin, dir, qty, entry_time, entry_idx_time, entry_price, entry_ref,
                                        stop, stop_dist, time_exit_time, entry_fee, equity_before, capped, status)
                                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'open')""",
                                     (coin, d, qty, T, T, entry, ref, entry - d * sdist, sdist, T + HOLD_SECONDS, fee, eq, int(capped)))
                    _fill_row(db, cur.lastrowid, coin, "buy" if d > 0 else "sell", "entry", T, now, ref, entry, qty, quote, live)
                    msgs.append(f"ENTRY {coin} {'long' if d > 0 else 'short'} qty {qty:g} @ {entry:.6g} | stop {entry - d * sdist:.6g} "
                                f"({sdist / entry * 100:.2f}%), time exit {pd.to_datetime(T + HOLD_SECONDS, unit='s'):%Y-%m-%d %H:%M} UTC")
                else:
                    msgs.append(f"SKIP {coin}: size below 1 contract (equity {eq:.2f}, stop {sdist / entry * 100:.2f}%)")
                store.log("info", msgs[-1], coin, db=db, now=now)
            elif len(hit) and paused:
                msgs.append(f"PAUSED {coin}: signal {'long' if c['dir'][hit[0]] > 0 else 'short'} ignored")
                store.log("warn", msgs[-1], coin, db=db, now=now)
        realized = _realized(db, coin)
        op = db.execute("SELECT * FROM positions WHERE coin=? AND status='open'", (coin,)).fetchone()
        mark = float(quote.get("mark") or ref) if live else ref
        unreal = 0.0
        if op:
            unreal = int(op["dir"]) * (mark - op["entry_price"]) * op["qty"] - op["entry_fee"] + (op["funding"] or 0.0)
        db.execute("INSERT INTO equity(coin, bar_time, realized, unrealized, total) VALUES(?,?,?,?,?) "
                   "ON CONFLICT(coin, bar_time) DO NOTHING", (coin, T, realized, unreal, realized + unreal))
        db.execute("INSERT INTO coin_runs(coin, bar_time, done_at, action) VALUES(?,?,?,?)",
                   (coin, T, now, "; ".join(msgs) or "no action"))
    return msgs or [f"{coin}: no action"]


def _realized(db, coin) -> float:
    cap = db.execute("SELECT capital FROM coins WHERE coin=?", (coin,)).fetchone()["capital"]
    net = db.execute("SELECT COALESCE(SUM(net),0) s FROM positions WHERE coin=? AND status='closed'", (coin,)).fetchone()["s"]
    return cap + net
