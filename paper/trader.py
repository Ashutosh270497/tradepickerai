"""Shadow paper trader CLI (public Delta data only; no API keys, no orders).

    python3 -m paper.trader init   --config paper_config.json --db state/paper.db
    python3 -m paper.trader run    --db state/paper.db          # process the latest closed 4h bar
    python3 -m paper.trader status --db state/paper.db
    python3 -m paper.trader reconcile --db state/paper.db
    python3 -m paper.trader resume --db state/paper.db          # clear a pause after review

Schedule `run` every 4 hours, a few minutes after 00/04/08/12/16/20 UTC. It is safe to run it more than
once for the same bar: nothing is duplicated. Stop rules and the weekly report run inside `run`.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from core.engine import TAKER, MAKER
from paper import alerts, delta_public as dp
from paper.logic import FOUR_H, SLIP, process_coin
from paper.reconcile import reconcile
from paper.store import Store

HISTORY_DAYS = 400          # candle history kept from a FIXED anchor so indicators match the backtest
DATA_WAIT_S, DATA_RETRIES = 30, 10


def latest_closed_bar(now: int) -> int:
    return now // FOUR_H * FOUR_H


def sync_data(store: Store, coin: str, until: int):
    """Fetch new closed 1h candles and funding readings from the last stored one up to `until` (exclusive)."""
    anchor = store.get_meta("history_anchor")
    last = store.db.execute("SELECT MAX(time) t FROM candles WHERE coin=?", (coin,)).fetchone()["t"]
    start = anchor if last is None else last + 3600
    if start < until:
        rows = dp.candles(coin, start, until)
        with store.tx() as db:
            db.executemany("INSERT OR IGNORE INTO candles(coin, time, o, h, l, c, v) VALUES(?,?,?,?,?,?,?)",
                           [(coin, r["time"], r["open"], r["high"], r["low"], r["close"], r["volume"] or 0.0) for r in rows])
    lastf = store.db.execute("SELECT MAX(time) t FROM funding_raw WHERE coin=?", (coin,)).fetchone()["t"]
    startf = anchor if lastf is None else lastf + 3600
    if startf < until:
        rows = dp.candles(f"FUNDING:{coin}", startf, until)
        with store.tx() as db:
            db.executemany("INSERT OR IGNORE INTO funding_raw(coin, time, rate_pct) VALUES(?,?,?)",
                           [(coin, r["time"], r["close"]) for r in rows])


def cmd_init(a):
    cfg = json.loads(Path(a.config).read_text())
    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    store = Store(a.db)
    if store.get_meta("initialised"):
        print("already initialised; nothing changed")
        return
    now = int(time.time())
    with store.tx() as db:
        for i, c in enumerate(cfg["coins"]):
            p = dp.product(c["coin"])
            taker, maker = float(p["taker_commission_rate"]), float(p["maker_commission_rate"])
            if (taker, maker) != (TAKER, MAKER):
                raise SystemExit(f"{c['coin']}: Delta fees {taker}/{maker} differ from the frozen {TAKER}/{MAKER}")
            interval = int((p.get("product_specs") or {}).get("rate_exchange_interval", 28800)) // 3600
            db.execute("INSERT INTO coins(coin, capital, lot, tick, funding_interval_h, taker, maker, sort) VALUES(?,?,?,?,?,?,?,?)",
                       (c["coin"], float(c["capital"]), float(p["contract_value"]), float(p["tick_size"]), interval, taker, maker, i))
        store.set_meta("config", cfg, db)
        store.set_meta("history_anchor", (now - HISTORY_DAYS * 86400) // 86400 * 86400, db)
        store.set_meta("initialised", now, db)
        store.set_meta("paused", None, db)
    for c in store.coins():
        sync_data(store, c["coin"], latest_closed_bar(now))
        n = store.db.execute("SELECT COUNT(*) n FROM candles WHERE coin=?", (c["coin"],)).fetchone()["n"]
        print(f"{c['coin']}: capital {c['capital']:.2f} USD, contract {c['lot']:g}, funding every {c['funding_interval_h']}h, "
              f"{n} candles stored")


def track_drawdown(store: Store, column: str = "exec_total") -> float:
    """Max drawdown of the combined account (sum of sub-accounts) on the executable (default) or model track."""
    assert column in ("exec_total", "total")
    eq = pd.DataFrame([dict(r) for r in store.db.execute(
        f"SELECT bar_time, SUM({column}) v FROM equity GROUP BY bar_time ORDER BY bar_time")])
    caps = sum(c["capital"] for c in store.coins())
    if not len(eq):
        return 0.0
    curve = np.r_[caps, eq["v"].to_numpy()]
    return float((1 - curve / np.maximum.accumulate(curve)).max())


def check_stop_rules(store: Store, T: int) -> str | None:
    """Plan v2 pause rules: drawdown on the EXECUTABLE track; execution cost vs mid; reconciliation mismatches."""
    rules = store.get_meta("config")["stop_rules"]
    dd = track_drawdown(store, "exec_total")
    if dd > rules["max_drawdown"]:
        return (f"executable-track drawdown {dd * 100:.2f}% exceeds the limit {rules['max_drawdown'] * 100:.2f}% "
                f"(2x backtest max DD)")
    costs = [r["exec_cost"] for r in store.db.execute("SELECT exec_cost FROM fills WHERE exec_cost IS NOT NULL")]
    if len(costs) >= rules["min_fills_for_exec_cost"]:
        avg = float(np.mean(costs))
        if avg > rules["max_avg_exec_cost"]:
            return (f"execution cost (book price vs mid) averages {avg * 100:.4f}% per side over {len(costs)} fills, "
                    f"above {rules['max_avg_exec_cost'] * 100:.3f}%")
    last = store.db.execute("SELECT * FROM weekly ORDER BY week_start DESC LIMIT 1").fetchone()
    if last and last["recon_trades"] and last["recon_mismatches"] / last["recon_trades"] > rules["max_mismatch_rate"]:
        return f"reconciliation mismatches {last['recon_mismatches']}/{last['recon_trades']} exceed {rules['max_mismatch_rate'] * 100:.0f}% of trades"
    return None


def fill_metrics(store: Store) -> pd.DataFrame:
    """Plan v2 per-coin fill metrics: execution cost vs mid (the pause/go-live metric) and LTP staleness
    (diagnostic): signed and absolute averages."""
    f = pd.DataFrame([dict(r) for r in store.db.execute(
        "SELECT coin, exec_cost, staleness FROM fills WHERE exec_cost IS NOT NULL")])
    if not len(f):
        return pd.DataFrame(columns=["fills", "exec_cost_avg", "staleness_signed_avg", "staleness_abs_avg"])
    g = f.groupby("coin")
    out = pd.DataFrame({"fills": g.size(), "exec_cost_avg": g["exec_cost"].mean(),
                        "staleness_signed_avg": g["staleness"].mean(),
                        "staleness_abs_avg": g["staleness"].apply(lambda x: x.abs().mean())})
    out.loc["ALL"] = [len(f), f["exec_cost"].mean(), f["staleness"].mean(), f["staleness"].abs().mean()]
    return out


def weekly_report(store: Store, T: int, force: bool = False) -> str | None:
    week_start = T - ((T // 86400 + 3) % 7) * 86400 - T % 86400      # Monday 00:00 UTC
    if not force and (store.db.execute("SELECT 1 FROM weekly WHERE week_start=?", (week_start,)).fetchone()
                      or store.get_meta("start_time") is None or store.get_meta("start_time") >= week_start):
        return None
    rec = reconcile(store, T)
    coins = store.coins()
    lines = [f"Weekly paper report to {pd.to_datetime(T, unit='s'):%Y-%m-%d %H:%M} UTC",
             "Equity per coin: MODEL track (LTP +/- 0.01%; used for backtest parity) | EXECUTABLE track (book ask/bid; "
             "used for return, drawdown and the drawdown pause)"]
    tot = tot_x = cap = 0.0
    for c in coins:
        e = store.db.execute("SELECT total, exec_total FROM equity WHERE coin=? ORDER BY bar_time DESC LIMIT 1", (c["coin"],)).fetchone()
        val, val_x = (e["total"], e["exec_total"]) if e else (c["capital"], c["capital"])
        tot, tot_x, cap = tot + val, tot_x + val_x, cap + c["capital"]
        op = store.open_position(c["coin"])
        lines.append(f"{c['coin']}: {val:.2f} ({(val / c['capital'] - 1) * 100:+.2f}%) | {val_x:.2f} ({(val_x / c['capital'] - 1) * 100:+.2f}%)" +
                     (f", open {'long' if op['dir'] > 0 else 'short'} {op['qty']:g} since {pd.to_datetime(op['entry_time'], unit='s'):%m-%d %H:%M}" if op else ", flat"))
    fund = store.db.execute("SELECT COALESCE(SUM(pnl),0) s FROM funding_applied").fetchone()["s"]
    closed = store.db.execute("SELECT COUNT(*) n, COALESCE(SUM(net),0) s, COALESCE(SUM(net_exec),0) sx "
                              "FROM positions WHERE status='closed'").fetchone()
    fm = fill_metrics(store)
    lines += [f"Total: model {tot:.2f} ({(tot / cap - 1) * 100:+.2f}%), max DD {track_drawdown(store, 'total') * 100:.2f}% | "
              f"executable {tot_x:.2f} ({(tot_x / cap - 1) * 100:+.2f}%), max DD {track_drawdown(store, 'exec_total') * 100:.2f}% "
              f"on {cap:.2f}",
              f"Closed trades {closed['n']}: net {closed['s']:+.2f} model, {closed['sx']:+.2f} executable",
              f"Funding paid/received: {fund:+.2f} USD (same on both tracks)"]
    if len(fm):
        a = fm.loc["ALL"]
        lines.append(f"Execution cost (book price vs mid): avg {a['exec_cost_avg'] * 100:.4f}% per side over {int(a['fills'])} fills "
                     f"(model assumes 0.0100%; pause above 0.03%)")
        lines.append("LTP staleness (last price - mid), per coin: signed avg / absolute avg")
        lines += [f"  {coin}: {r['staleness_signed_avg'] * 100:+.4f}% / {r['staleness_abs_avg'] * 100:.4f}% "
                  f"(exec cost {r['exec_cost_avg'] * 100:.4f}%, {int(r['fills'])} fills)" for coin, r in fm.drop(index="ALL").iterrows()]
    else:
        lines.append("Execution cost / staleness: no fills with a live order book yet")
    lines += [f"Reconciliation (model track vs backtest): {rec['mismatches']} mismatches in {rec['trades']} trades ({rec['rate'] * 100:.1f}%)"]
    lines += [f"  - {r['coin']} {r['entry']:%Y-%m-%d %H:%M} {r['type']}: {r['cause']}" for r in rec["rows"]]
    text = "\n".join(lines)
    with store.tx() as db:
        db.execute("INSERT OR REPLACE INTO weekly(week_start, created_at, summary, recon_trades, recon_mismatches) VALUES(?,?,?,?,?)",
                   (week_start, int(time.time()), text, rec["trades"], rec["mismatches"]))
    return text


def cmd_run(a):
    store = Store(a.db)
    if not store.get_meta("initialised"):
        raise SystemExit("not initialised: run `init` first")
    now = int(a.now or time.time())
    T = latest_closed_bar(now)
    done = store.db.execute("SELECT status FROM runs WHERE bar_time=?", (T,)).fetchone()
    if done and done["status"] == "done":
        print(f"bar {pd.to_datetime(T, unit='s')} already processed; nothing to do")
        return
    last = store.db.execute("SELECT MAX(bar_time) t FROM runs WHERE status='done'").fetchone()["t"]
    with store.tx() as db:
        if last is not None:
            for missed in range(last + FOUR_H, T, FOUR_H):
                db.execute("INSERT OR IGNORE INTO runs(bar_time, status, mode, started_at, note) VALUES(?, 'missed', 'live', ?, ?)",
                           (missed, now, "trader was not running; exchange-side stops still applied from candles"))
        db.execute("INSERT INTO runs(bar_time, status, mode, started_at) VALUES(?, 'started', 'live', ?) "
                   "ON CONFLICT(bar_time) DO UPDATE SET status='started', started_at=excluded.started_at", (T, now))
    if store.get_meta("start_time") is None:
        with store.tx() as db:
            store.set_meta("start_time", T, db)
    paused = store.get_meta("paused")
    out = []
    for c in store.coins():
        for attempt in range(DATA_RETRIES):
            sync_data(store, c["coin"], T)
            have = store.db.execute("SELECT 1 FROM candles WHERE coin=? AND time=?", (c["coin"], T - 3600)).fetchone()
            if have:
                break
            time.sleep(DATA_WAIT_S)
        else:
            store.log("error", f"candle before {T} not published after retries; coin skipped this bar", c["coin"])
            out.append(f"{c['coin']}: DATA MISSING, skipped")
            continue
        q = dp.quote(c["coin"])
        msgs = process_coin(store, c, T, q, live=True, paused=bool(paused), now=int(time.time()))
        out += msgs
        for msg in msgs:
            if msg.startswith(("ENTRY", "EXIT", "SKIP")):
                alerts.send(f"[paper] {msg}")
    with store.tx() as db:
        db.execute("UPDATE runs SET status='done', finished_at=? WHERE bar_time=?", (int(time.time()), T))
    rep = weekly_report(store, T)
    if rep:
        alerts.send(rep)
    reason = check_stop_rules(store, T)
    if reason and not paused:
        with store.tx() as db:
            store.set_meta("paused", {"since": T, "reason": reason}, db)
        store.log("warn", f"PAUSED: {reason}")
        alerts.send(f"[paper] PAUSED - new entries stopped, open positions still managed. Reason: {reason}. "
                    f"Review, then run `resume`.")
    print(f"processed 4h close {pd.to_datetime(T, unit='s')} UTC")
    for line in out:
        print("  " + line)


def cmd_status(a):
    store = Store(a.db)
    for c in store.coins():
        op = store.open_position(c["coin"])
        e = store.db.execute("SELECT * FROM equity WHERE coin=? ORDER BY bar_time DESC LIMIT 1", (c["coin"],)).fetchone()
        print(f"{c['coin']}: capital {c['capital']:.2f}, equity model {e['total'] if e else c['capital']:.2f} / "
              f"executable {e['exec_total'] if e else c['capital']:.2f}, "
              + (f"open {'long' if op['dir'] > 0 else 'short'} {op['qty']:g} @ {op['entry_price']:.6g}, stop {op['stop']:.6g}, "
                 f"time exit {pd.to_datetime(op['time_exit_time'], unit='s')}" if op else "flat"))
    print("paused:", store.get_meta("paused"))
    for r in store.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 10"):
        print(f"  {pd.to_datetime(r['time'], unit='s')} {r['level']} {r['coin'] or ''} {r['message']}")


def cmd_reconcile(a):
    store = Store(a.db)
    T = store.db.execute("SELECT MAX(bar_time) t FROM runs WHERE status='done'").fetchone()["t"]
    print(weekly_report(store, T, force=True))


def cmd_resume(a):
    store = Store(a.db)
    with store.tx() as db:
        store.set_meta("paused", None, db)
    store.log("info", "resumed by user")
    print("resumed")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init", "run", "status", "reconcile", "resume"])
    ap.add_argument("--db", default=os.environ.get("PAPER_DB", "state/paper.db"))
    ap.add_argument("--config", default="paper_config.json")
    ap.add_argument("--now", type=int, default=None, help="override current time (UTC seconds), for testing")
    a = ap.parse_args()
    {"init": cmd_init, "run": cmd_run, "status": cmd_status, "reconcile": cmd_reconcile, "resume": cmd_resume}[a.cmd](a)


if __name__ == "__main__":
    main()
