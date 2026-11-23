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

Plan v2 adds a second, EXECUTABLE track with the same trades and quantities, but entry and time-exit fills at
the recorded order-book price (ask for buys, bid for sells) instead of LTP +/- 0.01%. Stop exits trigger between
runs with no live quote, so both tracks use the frozen stop fill for them. The model track is what the backtest
parity checks use; the executable track drives the return/drawdown criteria and the drawdown pause.

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


def book_metrics(quote: dict | None, side: str) -> dict:
    """Plan v2 metrics from one order-book snapshot. side = 'buy' or 'sell'.
    exec_price: ask for buys, bid for sells.  exec_cost: gap to mid as a fraction (always >= 0 for a sane book).
    staleness: (last traded price - mid) / mid, signed. All None if the snapshot has no two-sided book."""
    q = quote or {}
    bid, ask = q.get("best_bid"), q.get("best_ask")
    if bid is None or ask is None or not (ask >= bid > 0):
        return {"mid": None, "exec_price": None, "exec_cost": None, "staleness": None}
    mid = (bid + ask) / 2
    px = ask if side == "buy" else bid
    cost = (ask - mid) / mid if side == "buy" else (mid - bid) / mid
    ltp = q.get("ltp")
    return {"mid": mid, "exec_price": px, "exec_cost": cost, "staleness": (ltp - mid) / mid if ltp is not None else None}


def _fill_row(db, pos_id, coin, side, kind, T, now, ref, model, qty, quote, live):
    q = quote or {}
    bm = book_metrics(quote, side)
    db.execute("""INSERT INTO fills(position_id, coin, side, kind, bar_time, decided_at, ref_price, model_price, qty,
                  best_bid, best_ask, bid_size, ask_size, mark, ltp, quote_time, live_quote, mid, exec_price, exec_cost, staleness)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(position_id, kind) DO NOTHING""",
               (pos_id, coin, side, kind, T, now, ref, model, qty, q.get("best_bid"), q.get("best_ask"),
                q.get("bid_size"), q.get("ask_size"), q.get("mark"), q.get("ltp"), q.get("quote_time"), int(live),
                bm["mid"], bm["exec_price"], bm["exec_cost"], bm["staleness"]))


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
                # executable track: same trade and qty; book price where a live quote exists, else the model fill
                bm = book_metrics(xq, "sell" if d > 0 else "buy")
                x_exec = bm["exec_price"] if bm["exec_price"] is not None else xpx
                e_exec = float(pos["entry_exec"])
                fees_exec, _ = trade_costs(e_exec, x_exec, qty, MARKET, False, hold_min, SC)
                gross_exec = d * (x_exec - e_exec) * qty
                net_exec = gross_exec - fees_exec + fund
                db.execute("""UPDATE positions SET status='closed', exit_time=?, exit_pos_hours=?, exit_price=?, exit_ref=?,
                              exit_kind=?, exit_fee=?, gross=?, net=?, R=?, exit_exec=?, exit_fee_exec=?, gross_exec=?,
                              net_exec=? WHERE id=?""",
                           (exit_time, xpos - f, xpx, xref, kind, fees - float(pos["entry_fee"]), gross, net, R,
                            x_exec, fees_exec - float(pos["entry_fee_exec"]), gross_exec, net_exec, pos["id"]))
                _fill_row(db, pos["id"], coin, "sell" if d > 0 else "buy", "exit_" + kind, T, now, xref, xpx, qty, xq, xlive)
                msgs.append(f"EXIT {coin} {'long' if d > 0 else 'short'} ({kind}) qty {qty:g} @ {xpx:.6g} model / "
                            f"{x_exec:.6g} executable | net {net:+.2f} model, {net_exec:+.2f} executable USD ({R:+.2f}R), "
                            f"funding {fund:+.2f}")
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
                    bm = book_metrics(quote, "buy" if d > 0 else "sell")
                    e_exec = bm["exec_price"] if bm["exec_price"] is not None else entry
                    fee_exec = TAKER * (1 + GST) * qty * e_exec
                    cur = db.execute("""INSERT INTO positions(coin, dir, qty, entry_time, entry_idx_time, entry_price, entry_ref,
                                        stop, stop_dist, time_exit_time, entry_fee, equity_before, capped, status,
                                        entry_exec, entry_fee_exec)
                                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?)""",
                                     (coin, d, qty, T, T, entry, ref, entry - d * sdist, sdist, T + HOLD_SECONDS, fee, eq,
                                      int(capped), e_exec, fee_exec))
                    _fill_row(db, cur.lastrowid, coin, "buy" if d > 0 else "sell", "entry", T, now, ref, entry, qty, quote, live)
                    msgs.append(f"ENTRY {coin} {'long' if d > 0 else 'short'} qty {qty:g} @ {entry:.6g} model / {e_exec:.6g} "
                                f"executable | stop {entry - d * sdist:.6g} "
                                f"({sdist / entry * 100:.2f}%), time exit {pd.to_datetime(T + HOLD_SECONDS, unit='s'):%Y-%m-%d %H:%M} UTC")
                else:
                    msgs.append(f"SKIP {coin}: size below 1 contract (equity {eq:.2f}, stop {sdist / entry * 100:.2f}%)")
                store.log("info", msgs[-1], coin, db=db, now=now)
            elif len(hit) and paused:
                msgs.append(f"PAUSED {coin}: signal {'long' if c['dir'][hit[0]] > 0 else 'short'} ignored")
                store.log("warn", msgs[-1], coin, db=db, now=now)
        realized, realized_x = _realized(db, coin), _realized(db, coin, "net_exec")
        op = db.execute("SELECT * FROM positions WHERE coin=? AND status='open'", (coin,)).fetchone()
        mark = float(quote.get("mark") or ref) if live else ref
        unreal = unreal_x = 0.0
        if op:
            od = int(op["dir"])
            unreal = od * (mark - op["entry_price"]) * op["qty"] - op["entry_fee"] + (op["funding"] or 0.0)
            # executable: value the position at the price it could be closed at now (bid for longs, ask for shorts)
            close_px = book_metrics(quote, "sell" if od > 0 else "buy")["exec_price"] or mark
            unreal_x = od * (close_px - op["entry_exec"]) * op["qty"] - op["entry_fee_exec"] + (op["funding"] or 0.0)
        db.execute("INSERT INTO equity(coin, bar_time, realized, unrealized, total, exec_realized, exec_unrealized, exec_total) "
                   "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(coin, bar_time) DO NOTHING",
                   (coin, T, realized, unreal, realized + unreal, realized_x, unreal_x, realized_x + unreal_x))
        db.execute("INSERT INTO coin_runs(coin, bar_time, done_at, action) VALUES(?,?,?,?)",
                   (coin, T, now, "; ".join(msgs) or "no action"))
    return msgs or [f"{coin}: no action"]


def _realized(db, coin, col: str = "net") -> float:
    """Capital plus closed-trade net P&L on the model track (net) or the executable track (net_exec)."""
    assert col in ("net", "net_exec")
    cap = db.execute("SELECT capital FROM coins WHERE coin=?", (coin,)).fetchone()["capital"]
    net = db.execute(f"SELECT COALESCE(SUM({col}),0) s FROM positions WHERE coin=? AND status='closed'", (coin,)).fetchone()["s"]
    return cap + net
