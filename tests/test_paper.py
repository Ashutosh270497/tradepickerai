"""Paper-trader tests: signal/cost parity with the backtest engine, restart safety, funding accounting.
Run: python3 -m pytest -q tests/test_paper.py"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.engine import run
from paper import logic
from paper.logic import FOUR_H, MAX_LEV, RISK, SC, market_until, process_coin
from paper.store import Store
from strategies import trend_ma_4h as S

T0 = 1_735_689_600  # 2025-01-01 00:00 UTC


def synthetic(days=260, seed=3):
    rng = np.random.default_rng(seed)
    n = days * 24
    drift = np.repeat(rng.normal(0, 0.0012, n // 240 + 1), 240)[:n]      # regime-switching trend
    lr = drift + rng.normal(0, 0.006, n)
    c = 100 * np.exp(np.cumsum(lr))
    o = np.r_[100, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, n)))
    t = T0 + 3600 * np.arange(n)
    return pd.DataFrame({"time": t, "o": o, "h": h, "l": l, "c": c, "v": 1.0})


def make_store(tmp_path, bars, funding_pct=None, capital=10_000.0, lot=0.001, tick=0.01, interval=8):
    st = Store(str(tmp_path / "p.db"))
    with st.tx() as db:
        db.execute("INSERT INTO coins VALUES('TESTUSD', ?, ?, ?, ?, 0.0005, 0.0002, 0)", (capital, lot, tick, interval))
        db.executemany("INSERT INTO candles VALUES('TESTUSD',?,?,?,?,?,?)",
                       bars[["time", "o", "h", "l", "c", "v"]].itertuples(index=False, name=None))
        f = funding_pct if funding_pct is not None else np.full(len(bars), 0.01)
        db.executemany("INSERT INTO funding_raw VALUES('TESTUSD',?,?)", zip(bars["time"].tolist(), np.asarray(f).tolist()))
        st.set_meta("history_anchor", int(bars["time"].iloc[0]), db)
    return st


def cfg(st):
    return st.coins()[0]


def replay(st, bars, start, end):
    opens = dict(zip(bars["time"], bars["o"]))
    with st.tx() as db:
        st.set_meta("start_time", start, db)
    for T in range(start, end, FOUR_H):
        process_coin(st, cfg(st), T, {"ref": opens[T]}, live=False, paused=False, now=T)


def engine_trades(st, bars, start, end):
    opens = dict(zip(bars["time"], bars["o"]))
    c0 = cfg(st)
    m = market_until(st, "TESTUSD", end, opens[end], c0["lot"], c0["tick"], c0["funding_interval_h"])
    c, _, _ = S.build(m, S.DEFAULT)
    tr = run(m, c, int(m.idx(start)), int(m.idx(end)), SC, equity0=c0["capital"], risk=RISK, max_lev=MAX_LEV)
    tr["entry_t"] = m.t[tr["fill"].to_numpy()]
    tr["exit_t"] = m.t[tr["exit_bar"].to_numpy()]
    return tr[tr["exit_t"] < end].reset_index(drop=True)


def paper_closed(st, end):
    return pd.DataFrame([dict(r) for r in st.db.execute(
        "SELECT * FROM positions WHERE status='closed' AND exit_time < ? ORDER BY entry_time", (end,))])


def assert_parity(bt, pp):
    assert len(bt) == len(pp) and len(bt) > 5
    assert (bt["entry_t"].to_numpy() == pp["entry_time"].to_numpy()).all()
    assert (bt["dir"].to_numpy() == pp["dir"].to_numpy()).all()
    assert (bt["exit_t"].to_numpy() == pp["exit_time"].to_numpy()).all()
    assert (bt["exit_kind"].to_numpy() == pp["exit_kind"].to_numpy()).all()
    for a, b in (("entry", "entry_price"), ("exit", "exit_price"), ("qty", "qty"), ("funding", "funding"),
                 ("net", "net"), ("R", "R")):
        np.testing.assert_allclose(bt[a].to_numpy(), pp[b].to_numpy(), rtol=1e-9, atol=1e-9)


def test_signal_and_cost_parity_with_backtest_engine(tmp_path):
    bars = synthetic()
    fund = 0.01 + 0.02 * np.sin(np.arange(len(bars)) / 50)          # varying, sometimes negative funding
    st = make_store(tmp_path, bars, funding_pct=fund)
    start, end = T0 + 60 * 86400, T0 + 255 * 86400
    replay(st, bars, start, end)
    assert_parity(engine_trades(st, bars, start, end), paper_closed(st, end))
    kinds = set(paper_closed(st, end)["exit_kind"])
    assert kinds == {"stop", "time"}   # both exit paths exercised


@pytest.mark.skipif(not Path("data/BTCUSD_1m.parquet").exists(), reason="cached Delta data not present")
def test_parity_on_real_delta_candles(tmp_path):
    raw = pd.read_parquet("data/BTCUSD_1m.parquet")
    raw = raw[raw.time < 1_767_225_600]                                # up to 2026-01-01
    key = raw["time"] // 3600 * 3600
    h = raw.groupby(key).agg(o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"),
                             v=("volume", "sum"), n=("open", "size"))
    h = h[h.n == 60].drop(columns="n").reset_index().rename(columns={"index": "time"})
    h.columns = ["time", "o", "h", "l", "c", "v"]
    full = pd.DataFrame({"time": np.arange(h.time.iloc[0], h.time.iloc[-1] + 3600, 3600)}).merge(h, how="left")
    full["c"] = full["c"].ffill()
    for k in ("o", "h", "l"):
        full[k] = full[k].fillna(full["c"])
    full["v"] = full["v"].fillna(0)
    fr = pd.read_parquet("data/FUNDING_BTCUSD.parquet")
    fund = full[["time"]].merge(fr[["time", "close"]], how="left")["close"].ffill().fillna(0.01).to_numpy()
    st = make_store(tmp_path, full, funding_pct=fund, lot=0.001, tick=0.5)
    start = int(full.time.iloc[0]) // FOUR_H * FOUR_H + 60 * 86400
    end = start + 300 * 86400
    replay(st, full, start, end)
    assert_parity(engine_trades(st, full, start, end), paper_closed(st, end))


def test_restart_safety_no_double_entry(tmp_path):
    bars = synthetic()
    st = make_store(tmp_path, bars)
    start = T0 + 60 * 86400
    opens = dict(zip(bars["time"], bars["o"]))
    # find the first bar with an entry
    T = start
    while True:
        process_coin(st, cfg(st), T, {"ref": opens[T]}, live=False, paused=False, now=T)
        if st.db.execute("SELECT COUNT(*) n FROM positions").fetchone()["n"]:
            break
        T += FOUR_H
    # re-running the same bar (e.g. scheduler retry) changes nothing
    msg = process_coin(st, cfg(st), T, {"ref": opens[T] * 1.05}, live=False, paused=False, now=T + 60)
    assert "already processed" in msg[0]
    assert st.db.execute("SELECT COUNT(*) n FROM positions").fetchone()["n"] == 1
    assert st.db.execute("SELECT COUNT(*) n FROM fills").fetchone()["n"] == 1
    assert st.db.execute("SELECT COUNT(*) n FROM equity WHERE bar_time=?", (T,)).fetchone()["n"] == 1


def test_crash_mid_bar_rolls_back_and_rerun_enters_once(tmp_path, monkeypatch):
    bars = synthetic()
    st = make_store(tmp_path, bars)
    start = T0 + 60 * 86400
    opens = dict(zip(bars["time"], bars["o"]))
    T = start
    while True:  # advance until a bar that will produce an entry, using a scratch copy to look ahead
        probe = make_store(tmp_path / f"probe{T}", bars) if (tmp_path / f"probe{T}").mkdir() is None else None
        process_coin(probe, cfg(probe), T, {"ref": opens[T]}, live=False, paused=False, now=T)
        if probe.db.execute("SELECT COUNT(*) n FROM positions").fetchone()["n"]:
            break
        process_coin(st, cfg(st), T, {"ref": opens[T]}, live=False, paused=False, now=T)
        T += FOUR_H
    real = logic._fill_row

    def boom(*a, **k):
        real(*a, **k)
        raise RuntimeError("simulated crash after writing the entry")
    monkeypatch.setattr(logic, "_fill_row", boom)
    with pytest.raises(RuntimeError):
        process_coin(st, cfg(st), T, {"ref": opens[T]}, live=False, paused=False, now=T)
    assert st.db.execute("SELECT COUNT(*) n FROM positions").fetchone()["n"] == 0   # rolled back
    assert not st.coin_done("TESTUSD", T)
    monkeypatch.setattr(logic, "_fill_row", real)
    process_coin(st, cfg(st), T, {"ref": opens[T]}, live=False, paused=False, now=T + 300)
    process_coin(st, cfg(st), T, {"ref": opens[T]}, live=False, paused=False, now=T + 600)
    assert st.db.execute("SELECT COUNT(*) n FROM positions").fetchone()["n"] == 1
    assert st.db.execute("SELECT COUNT(*) n FROM fills").fetchone()["n"] == 1


def test_funding_charged_once_per_settlement_with_correct_sign(tmp_path):
    bars = synthetic()
    fund = np.where(np.arange(len(bars)) % 2, 0.03, -0.01)            # alternate, so sign errors would show
    st = make_store(tmp_path, bars, funding_pct=fund)
    start, end = T0 + 60 * 86400, T0 + 200 * 86400
    replay(st, bars, start, end)
    # re-processing every bar again must not add funding rows
    n_before = st.db.execute("SELECT COUNT(*) n FROM funding_applied").fetchone()["n"]
    replay(st, bars, start, end)
    assert st.db.execute("SELECT COUNT(*) n FROM funding_applied").fetchone()["n"] == n_before > 0
    rows = pd.DataFrame([dict(r) for r in st.db.execute(
        "SELECT f.*, p.dir, p.entry_time, p.exit_time, p.status FROM funding_applied f JOIN positions p ON p.id=f.position_id")])
    # amount = -direction x rate x qty x price; rate = published value in the hour before settlement
    np.testing.assert_allclose(rows["pnl"], -rows["dir"] * rows["rate"] * rows["qty"] * rows["price"], rtol=1e-12)
    raw = dict(zip(bars["time"], fund))
    np.testing.assert_allclose(rows["rate"], [raw[t - 3600] / 100 for t in rows["settle_time"]], rtol=1e-12)
    assert (rows["settle_time"] % (8 * 3600) == 0).all()
    assert (rows["settle_time"] > rows["entry_time"]).all()
    closed = rows[rows.status == "closed"]
    assert (closed["settle_time"] <= closed["exit_time"]).all()
    # position funding equals the sum of its settlements and matches the engine
    agg = rows.groupby("position_id")["pnl"].sum()
    pos = pd.DataFrame([dict(r) for r in st.db.execute("SELECT id, funding FROM positions")]).set_index("id")
    np.testing.assert_allclose(pos.loc[agg.index, "funding"], agg, rtol=1e-12)
    bt = engine_trades(st, bars, start, end)
    pp = paper_closed(st, end)
    np.testing.assert_allclose(bt["funding"].to_numpy(), pp["funding"].to_numpy(), rtol=1e-9, atol=1e-12)


def test_paused_trader_takes_no_new_entries_but_still_exits(tmp_path):
    bars = synthetic()
    st = make_store(tmp_path, bars)
    start = T0 + 60 * 86400
    opens = dict(zip(bars["time"], bars["o"]))
    for T in range(start, start + 120 * 86400, FOUR_H):
        process_coin(st, cfg(st), T, {"ref": opens[T]}, live=False, paused=True, now=T)
    assert st.db.execute("SELECT COUNT(*) n FROM positions").fetchone()["n"] == 0


def test_weekly_reconciliation_matches_backtest_and_flags_differences(tmp_path):
    from paper.reconcile import reconcile
    bars = synthetic()
    st = make_store(tmp_path, bars)
    start, end = T0 + 60 * 86400, T0 + 200 * 86400
    replay(st, bars, start, end)
    rec = reconcile(st, end)
    assert rec["trades"] > 5 and rec["mismatches"] == 0
    # a paper trade the backtest never took must be reported as a mismatch
    with st.tx() as db:
        db.execute("INSERT INTO positions(coin, dir, qty, entry_time, entry_price, stop, stop_dist, time_exit_time, entry_fee, "
                   "equity_before, capped, status) VALUES('TESTUSD', 1, 0.001, ?, 100, 90, 10, ?, 0, 10000, 0, 'open')",
                   (end - 3 * FOUR_H + 3600, end + 86400))
    rec2 = reconcile(st, end)
    assert rec2["mismatches"] == 1 and rec2["rows"][0]["type"] == "only in paper"


class FakeS3:
    """Minimal S3 stand-in with ETag-conditional writes (IfMatch / IfNoneMatch) like the real API."""
    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self):
        self.obj, self.etag, self.n = None, None, 0

    def get_object(self, Bucket, Key):
        if self.obj is None:
            raise FakeS3.exceptions.NoSuchKey()
        import io
        return {"Body": io.BytesIO(self.obj), "ETag": self.etag}

    def put_object(self, Bucket, Key, Body, IfMatch=None, IfNoneMatch=None):
        if IfNoneMatch == "*" and self.obj is not None:
            raise RuntimeError("PreconditionFailed: object exists")
        if IfMatch is not None and IfMatch != self.etag:
            raise RuntimeError("PreconditionFailed: stale ETag")
        self.n += 1
        self.obj, self.etag = Body, f'"v{self.n}"'


def test_container_state_roundtrip_and_conditional_write(tmp_path, monkeypatch):
    from paper import run_task
    fake = FakeS3()
    monkeypatch.setenv("PAPER_STATE_S3", "s3://bucket/paper.db")
    monkeypatch.setattr(run_task, "LOCAL", str(tmp_path / "paper.db"))
    monkeypatch.setattr(run_task, "_s3", lambda: (fake, "bucket", "paper.db"))
    calls = []
    monkeypatch.setattr(run_task, "cmd_init", lambda a: (Store(a.db).set_meta("initialised", 1), calls.append("init")))
    monkeypatch.setattr(run_task, "cmd_run", lambda a: (Store(a.db).log("info", "ran"), calls.append("run")))
    monkeypatch.setattr("sys.argv", ["run_task"])
    run_task.main()                                  # first run: no state -> init + run + create object
    assert calls == ["init", "run"] and fake.etag == '"v1"'
    (tmp_path / "paper.db").unlink()                 # a fresh container has no local file
    run_task.main()                                  # second run: download, run (no init), conditional upload
    assert calls == ["init", "run", "run"] and fake.etag == '"v2"'
    # an overlapping run that downloaded v2 cannot overwrite a newer v3
    etag = run_task.download()
    fake.put_object(Bucket="bucket", Key="paper.db", Body=fake.obj, IfMatch=fake.etag)   # someone else wrote v3
    with pytest.raises(RuntimeError, match="stale ETag"):
        run_task.upload(etag)
