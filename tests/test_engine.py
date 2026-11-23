"""Unit tests for the cost, fill and timing logic. Run: python3 -m pytest -q tests"""
import numpy as np
import pandas as pd
import pytest

from core.engine import (GST, LIMIT, MAKER, MARKET, TAKER, Scenario, candidates, limit_fill_index,
                         random_baseline, run)
from core.indicators import confirmed_swings
from core.market import Market

T0 = 1_767_225_600  # 2026-01-01 00:00 UTC
STD = Scenario("standard", 0.0, None, slip=0.0001)
NOSLIP = Scenario("noslip", 0.0, None, slip=0.0)


def mk(o, h=None, l=None, c=None, settle_idx=(), settle_rate=()):
    o = np.asarray(o, float)
    h = o + 0.25 if h is None else np.asarray(h, float)
    l = o - 0.25 if l is None else np.asarray(l, float)
    c = o if c is None else np.asarray(c, float)
    t = T0 + 60 * np.arange(len(o), dtype=np.int64)
    return Market("TEST", t, o, h, l, c, np.ones(len(o)), tick=0.5, lot=0.001,
                  settle_idx=np.asarray(settle_idx, np.int64), settle_rate=np.asarray(settle_rate, float))


def one(m, sc=STD, **kw):
    base = dict(sig=0, fill=1, dir=1)
    base.update(kw)
    return run(m, candidates(**base), 0, m.n, sc, kw.pop("dyn_long", None), kw.pop("dyn_short", None))


def test_market_entry_time_exit_fees_and_slippage():
    m = mk([100, 100, 100, 101, 101])
    tr = one(m, sdist=1.0, maxb=2)
    r = tr.iloc[0]
    entry, exit_ = 100 * 1.0001, 101 * (1 - 0.0001)
    qty = 5.0  # 0.5% of 1000 / stop distance 1.0
    assert r.exit_kind == "time" and r.hold_min == 2
    assert r.entry == pytest.approx(entry) and r.exit == pytest.approx(exit_)
    assert r.qty == pytest.approx(qty)
    fees = TAKER * (1 + GST) * qty * (entry + exit_)
    assert r.fees == pytest.approx(fees)
    assert r.net == pytest.approx((exit_ - entry) * qty - fees)


def test_short_slippage_is_adverse():
    m = mk([100, 100, 100, 99, 99])
    r = one(m, dir=-1, sdist=1.0, maxb=2).iloc[0]
    assert r.entry == pytest.approx(100 * (1 - 0.0001))  # sell lower
    assert r.exit == pytest.approx(99 * (1 + 0.0001))    # buy back higher


def test_limit_fill_needs_one_tick_through():
    low = np.array([100.0, 100.0, 99.5, 99.0])
    high = low + 1
    assert limit_fill_index(low, high, 0, 2, +1, 100.0, 0.5) == -1      # touching is not enough
    assert limit_fill_index(low, high, 0, 4, +1, 100.0, 0.5) == 2       # one tick through fills
    assert limit_fill_index(low, high, 0, 4, -1, 100.5, 0.5) == 0       # sell: high >= px + tick
    # cancelled when the target level trades before the fill
    assert limit_fill_index(low, high, 0, 4, +1, 100.0, 0.5, cancel_level=101.0) == -1


def test_limit_entry_maker_fee_and_no_target_on_fill_bar():
    #           0      1      2      3
    o = np.array([101.0, 101.0, 101.0, 101.0])
    h = np.array([101.2, 103.0, 101.2, 103.0])   # bar 1 also touches the target, must be ignored
    l = np.array([100.8, 99.4, 100.8, 100.8])
    m = mk(o, h, l)
    r = one(m, NOSLIP, etype=LIMIT, px=100.0, stop=98.0, tgt=102.0, fill=1).iloc[0]
    assert r.entry == 100.0 and r.exit_kind == "target" and r.exit_bar == 3
    qty = r.qty
    assert r.fees == pytest.approx(MAKER * (1 + GST) * qty * (100.0 + 102.0))


def test_stop_intrabar_and_gap_fills():
    m = mk([100, 100, 100, 100], l=[99.75, 99.75, 98.9, 99.75])
    r = one(m, sdist=0.5, maxb=3).iloc[0]
    stop = 100 * 1.0001 - 0.5
    assert r.exit_kind == "stop" and r.exit == pytest.approx(stop * (1 - 0.0001))
    g = mk([100, 100, 97, 97], l=[99.75, 99.75, 96.8, 96.8])
    r = one(g, sdist=0.5, maxb=3).iloc[0]
    assert r.exit_kind == "stop" and r.exit == pytest.approx(97 * (1 - 0.0001))  # gap: fills at open


def test_stop_assumed_before_target_in_same_bar():
    m = mk([100, 100, 100, 100], h=[100.2, 100.2, 103, 100.2], l=[99.8, 99.8, 98, 99.8])
    r = one(m, NOSLIP, sdist=1.0, rr=2.0, maxb=3).iloc[0]
    assert r.exit_kind == "stop"


def test_target_needs_one_tick_through():
    m = mk([100] * 5, h=[100.2, 100.2, 102.0, 102.5, 100.2], l=[99.8] * 5)
    r = one(m, NOSLIP, sdist=1.0, rr=2.0, maxb=4).iloc[0]   # target 102.0
    assert r.exit_kind == "target" and r.exit_bar == 3 and r.exit == 102.0


def test_offer_waiver_29_minutes_qualifies_30_does_not():
    m = mk([100.0] * 40)
    free = run(m, candidates(sig=0, fill=1, dir=1, sdist=1.0), 0, m.n, Scenario("o", 1.0, 29, 0.0)).iloc[0]
    assert free.hold_min == 29 and free.fee_free
    assert free.fees == pytest.approx(TAKER * (1 + GST) * free.qty * 100.0)   # opening fee only
    half = run(m, candidates(sig=0, fill=1, dir=1, sdist=1.0), 0, m.n, Scenario("h", 0.5, 29, 0.0)).iloc[0]
    assert half.fees == pytest.approx(TAKER * (1 + GST) * half.qty * 100.0 * 1.5)
    late = run(m, candidates(sig=0, fill=1, dir=1, sdist=1.0, maxb=30), 0, m.n, Scenario("x", 1.0, None, 0.0)).iloc[0]
    assert late.hold_min == 30 and not late.fee_free


def test_funding_charged_only_when_held_across_settlement():
    m = mk([100.0] * 8, settle_idx=[3], settle_rate=[0.0001])
    long_ = run(m, candidates(sig=0, fill=1, dir=1, sdist=1.0, maxb=4), 0, m.n, NOSLIP).iloc[0]
    assert long_.funding == pytest.approx(-0.0001 * long_.qty * 100.0)       # long pays positive rate
    short = run(m, candidates(sig=0, fill=1, dir=-1, sdist=1.0, maxb=4), 0, m.n, NOSLIP).iloc[0]
    assert short.funding == pytest.approx(+0.0001 * short.qty * 100.0)       # short receives
    at = run(m, candidates(sig=3, fill=3, dir=1, sdist=1.0, maxb=2), 0, m.n, NOSLIP).iloc[0]
    assert at.funding == 0.0                                                 # opened at settlement
    before = run(m, candidates(sig=0, fill=1, dir=1, sdist=1.0, maxb=2), 0, m.n, NOSLIP).iloc[0]
    assert before.funding == 0.0                                             # closed at settlement


def test_sizing_risk_leverage_cap_and_lot_rounding():
    m = mk([100.0] * 5)
    r = one(m, NOSLIP, sdist=0.02, maxb=2).iloc[0]      # 5 USD / 0.02 = 250 units -> 25,000 notional
    assert r.capped and r.qty == pytest.approx(100.0)   # capped at 10x of 1,000 equity
    r = one(m, NOSLIP, sdist=1.2345, maxb=2).iloc[0]
    assert r.qty == pytest.approx(np.floor(5 / 1.2345 / 0.001) * 0.001)


def test_dynamic_target_open_cross_is_market_exit():
    m = mk([100, 100, 100, 101, 101])
    dyn = np.array([np.nan, 100.5, 100.5, 100.5, 100.5])
    tr = run(m, candidates(sig=0, fill=1, dir=1, sdist=1.0, dyn=1, maxb=4), 0, m.n, STD, dyn, dyn)
    r = tr.iloc[0]
    assert r.exit_kind == "dyn_open" and r.exit == pytest.approx(101 * (1 - 0.0001))


def test_one_position_at_a_time():
    m = mk([100.0] * 10)
    c = candidates(sig=[0, 2, 6], fill=[1, 3, 7], dir=[1, 1, -1], sdist=1.0, maxb=4)
    tr = run(m, c, 0, m.n, NOSLIP)
    assert list(tr["fill"]) == [1, 7]                    # the bar-3 signal arrived while in a trade


def test_swings_are_causal():
    h = np.array([1, 2, 3, 9, 3, 2, 1, 1, 1, 1], float)
    l = h - 0.5
    sh, _ = confirmed_swings(h, l, 2)
    assert np.isnan(sh[4])          # swing at bar 3 is not visible before bar 3 + 2
    assert sh[5] == 9


def test_htf_bar_only_usable_after_it_closes():
    o = np.arange(20, dtype=float)
    m = mk(o, h=o + 0.1, l=o - 0.1, c=o + 0.05)
    b = m.bars(5)
    assert list(b["act"]) == [5, 10, 15]                 # 1m bar opening at each 5m close
    arr = m.to_1m(b, b["c"])
    assert np.isnan(arr[4]) and arr[5] == pytest.approx(4.05)


def test_random_baseline_runs_and_is_reproducible():
    rng = np.random.default_rng(0)
    o = 100 + np.cumsum(rng.normal(0, 0.05, 3000))
    m = mk(o, h=o + 0.3, l=o - 0.3)
    c = candidates(sig=np.arange(0, 2900, 50), fill=np.arange(1, 2901, 50), dir=1, sdist=0.6, rr=1.5, maxb=30)
    tr = run(m, c, 0, m.n, STD)
    a = random_baseline(m, tr, 0, m.n, STD, n_sims=20, seed=1)
    b = random_baseline(m, tr, 0, m.n, STD, n_sims=20, seed=1)
    assert len(a) == 20 and np.allclose(a, b)


def test_trading_halts_at_ruin():
    # every trade is a full stop-out with heavy costs; equity can never trade below 10% of start
    o = np.full(4000, 100.0)
    l = o.copy(); l[2::4] = 90.0          # a deep low every 4th bar hits any stop
    m = mk(o, h=o + 0.1, l=l)
    c = candidates(sig=np.arange(1, 3990, 4), fill=np.arange(1, 3990, 4), dir=1, sdist=0.02, maxb=3)
    tr = run(m, c, 0, m.n, STD)
    assert tr.attrs["ruined_at"] is not None
    assert (tr["equity_before"] > 100).all()


def mk_hourly(o, h=None, l=None, settle_idx=(), settle_rate=()):
    m = mk(o, h, l, settle_idx=settle_idx, settle_rate=settle_rate)
    m.t = T0 + 3600 * np.arange(len(m.o), dtype=np.int64)
    m.step = 3600
    return m


def test_hourly_bars_hold_time_in_minutes_and_idx():
    m = mk_hourly([100.0] * 10)
    r = run(m, candidates(sig=0, fill=1, dir=1, sdist=1.0, maxb=3), 0, m.n, NOSLIP).iloc[0]
    assert r.hold_min == 180 and r.exit_kind == "time"
    assert m.idx(T0 + 7200) == 2
    b = m.bars(240)
    assert list(b["act"]) == [4, 8]


def test_maker_scenario_entry_and_time_exit_are_maker_without_slippage():
    m = mk([100, 100, 100, 101, 101])
    sc = Scenario("maker", slip=0.0001, maker_fills=True)
    r = one(m, sc, sdist=1.0, maxb=2).iloc[0]
    assert r.entry == 100.0 and r.exit == 101.0
    assert r.fees == pytest.approx(MAKER * (1 + GST) * r.qty * (100.0 + 101.0))
    s = mk([100, 100, 100, 100], l=[99.75, 99.75, 98.9, 99.75])
    r = one(s, sc, sdist=0.5, maxb=3).iloc[0]          # stop stays stop-market: taker + slippage
    assert r.exit_kind == "stop" and r.exit == pytest.approx(99.5 * (1 - 0.0001))
    assert r.fees == pytest.approx(MAKER * (1 + GST) * r.qty * 100.0 + TAKER * (1 + GST) * r.qty * r.exit)
