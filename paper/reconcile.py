"""Weekly reconciliation: rerun the frozen backtest (core.engine.run) on the SAME stored Delta candles over
the paper period and compare it trade by trade with the paper log."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.engine import run
from paper.logic import MAX_LEV, RISK, SC, market_until
from strategies import trend_ma_4h as S

PRICE_TOL = 0.002   # 0.2%: entry/exit price differences above this are listed (timing of live vs bar-open fills)


def backtest_trades(store, cfg: dict, start: int, T: int) -> pd.DataFrame:
    last = store.db.execute("SELECT c FROM candles WHERE coin=? AND time=?", (cfg["coin"], T - 3600)).fetchone()
    m = market_until(store, cfg["coin"], T, float(last["c"]), cfg["lot"], cfg["tick"], cfg["funding_interval_h"])
    c, _, _ = S.build(m, S.DEFAULT)
    tr = run(m, c, int(m.idx(start)), int(m.idx(T)) + 1, SC, equity0=cfg["capital"], risk=RISK, max_lev=MAX_LEV)
    if len(tr):
        tr["entry_t"] = m.t[tr["fill"].to_numpy()]
        tr["exit_t"] = m.t[tr["exit_bar"].to_numpy()]
        tr["open_at_end"] = tr["exit_kind"].eq("end")
    return tr


def reconcile(store, T: int) -> dict:
    start = store.get_meta("start_time")
    if start is None or T <= start:
        return {"trades": 0, "mismatches": 0, "rate": 0.0, "rows": []}
    missed = {r["bar_time"] for r in store.db.execute("SELECT bar_time FROM runs WHERE status='missed'")}
    rows, n_trades, n_mis = [], 0, 0
    for cfg in store.coins():
        coin = cfg["coin"]
        bt = backtest_trades(store, cfg, start, T)
        pp = pd.DataFrame([dict(r) for r in store.db.execute(
            "SELECT * FROM positions WHERE coin=? AND entry_time<=? ORDER BY entry_time", (coin, T))])
        bkeys = {(int(r.entry_t), int(r.dir)): r for r in bt.itertuples()} if len(bt) else {}
        pkeys = {(int(r.entry_time), int(r.dir)): r for r in pp.itertuples()} if len(pp) else {}
        for key in sorted(set(bkeys) | set(pkeys)):
            b, p = bkeys.get(key), pkeys.get(key)
            n_trades += 1
            when = pd.to_datetime(key[0], unit="s")
            if b is None or p is None:
                n_mis += 1
                cause = "paper missed the 4h close (trader down)" if key[0] in missed else (
                    "re-entry timing differs after an earlier mismatch" if n_mis > 1 else "unexplained")
                rows.append({"coin": coin, "entry": when, "dir": key[1], "type": "only in " + ("backtest" if p is None else "paper"),
                             "cause": cause})
                continue
            p_open = p.status == "open"
            b_open = bool(b.open_at_end)
            issue = None
            if p_open != b_open:
                issue = "one is still open, the other closed"
            elif not p_open and (int(p.exit_time) != int(b.exit_t) or p.exit_kind != b.exit_kind):
                issue = f"exit differs: paper {p.exit_kind} {pd.to_datetime(p.exit_time, unit='s')}, backtest {b.exit_kind} {pd.to_datetime(b.exit_t, unit='s')}"
            if issue:
                n_mis += 1
                stop_gap = abs(p.stop - b.stop) / b.stop
                cause = (f"stop level differs by {stop_gap * 100:.3f}% because the live entry price differed from the bar open"
                         if stop_gap > 1e-6 else "unexplained")
                rows.append({"coin": coin, "entry": when, "dir": key[1], "type": issue, "cause": cause})
            else:
                d_in = abs(p.entry_price / b.entry - 1)
                d_out = abs(p.exit_price / b.exit - 1) if not p_open else 0.0
                if max(d_in, d_out) > PRICE_TOL:
                    rows.append({"coin": coin, "entry": when, "dir": key[1], "type": "price difference (not a mismatch)",
                                 "cause": f"entry {d_in * 100:.3f}%, exit {d_out * 100:.3f}% vs bar open"})
    return {"trades": n_trades, "mismatches": n_mis, "rate": n_mis / n_trades if n_trades else 0.0, "rows": rows}
