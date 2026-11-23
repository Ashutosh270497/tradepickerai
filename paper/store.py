"""SQLite state for the paper trader. Every write that matters is keyed so a re-run cannot duplicate it."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS coins(coin TEXT PRIMARY KEY, capital REAL, lot REAL, tick REAL, funding_interval_h INTEGER,
    taker REAL, maker REAL, sort INTEGER);
CREATE TABLE IF NOT EXISTS candles(coin TEXT, time INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL, PRIMARY KEY(coin, time));
CREATE TABLE IF NOT EXISTS funding_raw(coin TEXT, time INTEGER, rate_pct REAL, PRIMARY KEY(coin, time));
CREATE TABLE IF NOT EXISTS runs(bar_time INTEGER PRIMARY KEY, status TEXT, mode TEXT, started_at INTEGER,
    finished_at INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS coin_runs(coin TEXT, bar_time INTEGER, done_at INTEGER, action TEXT, PRIMARY KEY(coin, bar_time));
CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT, dir INTEGER, qty REAL,
    entry_time INTEGER, entry_idx_time INTEGER, entry_price REAL, entry_ref REAL, stop REAL, stop_dist REAL,
    time_exit_time INTEGER, entry_fee REAL, equity_before REAL, capped INTEGER, status TEXT,
    exit_time INTEGER, exit_pos_hours REAL, exit_price REAL, exit_ref REAL, exit_kind TEXT, exit_fee REAL,
    funding REAL DEFAULT 0, gross REAL, net REAL, R REAL, UNIQUE(coin, entry_time));
CREATE TABLE IF NOT EXISTS fills(id INTEGER PRIMARY KEY AUTOINCREMENT, position_id INTEGER, coin TEXT, side TEXT,
    kind TEXT, bar_time INTEGER, decided_at INTEGER, ref_price REAL, model_price REAL, qty REAL,
    best_bid REAL, best_ask REAL, bid_size REAL, ask_size REAL, mark REAL, ltp REAL, quote_time INTEGER,
    live_quote INTEGER, UNIQUE(position_id, kind));
CREATE TABLE IF NOT EXISTS funding_applied(position_id INTEGER, coin TEXT, settle_time INTEGER, rate REAL, price REAL,
    qty REAL, pnl REAL, PRIMARY KEY(position_id, settle_time));
CREATE TABLE IF NOT EXISTS equity(coin TEXT, bar_time INTEGER, realized REAL, unrealized REAL, total REAL,
    PRIMARY KEY(coin, bar_time));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER, level TEXT, coin TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS weekly(week_start INTEGER PRIMARY KEY, created_at INTEGER, summary TEXT,
    recon_trades INTEGER, recon_mismatches INTEGER);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect(path, isolation_level=None)  # explicit transactions below
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    # meta
    def get_meta(self, key, default=None):
        r = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def set_meta(self, key, value, db=None):
        (db or self.db).execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                (key, json.dumps(value)))

    def coins(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM coins ORDER BY sort")]

    def open_position(self, coin):
        r = self.db.execute("SELECT * FROM positions WHERE coin=? AND status='open'", (coin,)).fetchone()
        return dict(r) if r else None

    def realized_equity(self, coin):
        cap = self.db.execute("SELECT capital FROM coins WHERE coin=?", (coin,)).fetchone()["capital"]
        net = self.db.execute("SELECT COALESCE(SUM(net), 0) s FROM positions WHERE coin=? AND status='closed'", (coin,)).fetchone()["s"]
        return cap + net

    def coin_done(self, coin, bar_time):
        return self.db.execute("SELECT 1 FROM coin_runs WHERE coin=? AND bar_time=?", (coin, bar_time)).fetchone() is not None

    def log(self, level, message, coin=None, db=None, now=None):
        import time
        (db or self.db).execute("INSERT INTO events(time, level, coin, message) VALUES(?, ?, ?, ?)",
                                (int(now or time.time()), level, coin, message))
