# Paper trading plan: frozen 4h trend filter (pre-registered), version 2

- **Version 2, 23 Nov 2026:** committed before go-live; the git timestamp is the record. See the change log at the end.
- **Rules:** [`frozen_rules.md`](frozen_rules.md) stays frozen. Nothing in this plan changes or retunes a trading rule.
- **If anything here needs to change:** write a new plan version, commit it, and restart the paper period.

## 1. What is paper traded

| Item | Setting |
|---|---|
| Strategy | `strategies/trend_ma_4h.py`, `DEFAULT` parameters, exactly as in `frozen_rules.md` (4h close vs SMA200, long/short, 20-day hold, 2 × daily ATR(20) stop, 0.5% risk, 3x cap, Delta taker fee + 18% GST, 0.01% slippage per side, funding as Delta publishes it) |
| Budget | **$2,500**, the amount you said you would actually trade |
| Split (your choice) | One sub-account per coin, each risking 0.5% of itself per trade: **BTCUSD $1,400, ETHUSD $600, XRPUSD $167, BCHUSD $167, LTCUSD $166** (`paper_config.json`) |
| Data | Delta Exchange India **public** API only: 1h candles, funding history, live order book and ticker. No API keys, no orders |
| Schedule | Every 4 hours, 5 minutes after 00/04/08/12/16/20 UTC |
| Start | **The 12-month paper period begins with a fresh `init` on the first scheduled AWS run.** The 23 Nov 2026 local dry-run state was discarded. The manual pre-deployment `check` task creates no state |

### Two equity tracks: same trades, two fill prices

Both tracks contain exactly the same trades with the same quantities. Position size always comes from the model track's equity, as the frozen rules define it.

| | **Model track** | **Executable track** |
|---|---|---|
| Entry and time-exit fills | Live last traded price (LTP) a few minutes after the 4h close, ± 0.01% (frozen slippage) | The recorded order-book price at the same moment: **best ask for buys, best bid for sells** |
| Stop exits | Stop price ∓ 0.01%, or the bar open ∓ 0.01% on a gap (frozen) | **Same as the model track**: stops trigger between runs as resting exchange orders, so no live quote exists for them |
| Fees and funding | Delta taker fee + GST on the model prices; funding as published | Fee on the executable prices; identical funding |
| Open positions valued at | Mark price | The price they could be closed at now (bid for longs, ask for shorts) |
| **Used for** | **Backtest parity:** weekly reconciliation and the fidelity criterion (§6 #2, #3) | **Real-world results:** the return and drawdown criteria (§6 #1, #5) and the **drawdown pause** (§4) |

### Fill measurements (every fill with a live order book)

- **Execution cost** (the slippage metric for the pause rule and go-live criterion): the gap between the executable price and the mid price in the **same** order-book snapshot.
  - buys: (ask − mid) ÷ mid;
  - sells: (mid − bid) ÷ mid.
- **LTP staleness** (diagnostic only, no pause rule): (last traded price − mid) ÷ mid, **signed**. Reported per coin as a signed average and an absolute average.

Every live fill also stores the best bid, best ask, their sizes, the mark price and the last price.

## 2. What to expect (backtest reference for these exact coins and this split)

Frozen rules, Binance USD-M prices 2020-02 → 2026-11, Delta fees and contract sizes, real whole-contract rounding at these sub-account sizes (`python3 -m paper.plan_stats`, saved in `logs/paper_plan_stats.json`):

| Measure | Value |
|---|---|
| Combined return 2020-02 → 2026-11 | +22.9% (3.1% a year) on $2,500 |
| Maximum drawdown (daily mark-to-market) | **2.42%** |
| Sharpe | 1.28 |
| Trades per year | about 99. LTC and ETH skip many trades at these sizes because positions fall below one contract |
| 6-month return, monthly-block bootstrap | 5th pct **−0.86%**, median +1.6%, 95th pct +4.7%; 16% chance of a loss |
| 12-month return, monthly-block bootstrap | 5th pct **−0.33%**, median +3.3%, 95th pct +7.4%; 7% chance of a loss |
| 12-month max drawdown, bootstrap | median 1.5%, 95th pct **2.6%** |

**The expected money is small:** about $40 in 6 months and $80 in 12 months at the median. The point of paper trading is to check that live execution matches the backtest, not to make money.

**Caution from Phase 5, Step 1:** once the correlation between coins is accounted for, the evidence for the edge is weaker than Phase 4 suggested. The strategy sat at the 96.5th percentile of a synchronized random baseline, a narrow pass.

## 3. Review point

- **Formal review:** after **6 months or 100 closed trades, whichever comes later**. At about 99 trades a year that is expected around **month 12**.
- **No go-live decision before the review point**, however good or bad the early results look.

## 4. Automatic pause rules

When any of these triggers, the trader **pauses**: no new entries; open positions are still managed by the frozen stops and time exits. It sends a Telegram alert and stays paused until you review and run `resume`.

| Rule | Threshold | Track / metric | When checked |
|---|---|---|---|
| Drawdown | Combined equity drawdown **> 4.83%** (= 2 × backtest max DD of 2.42%) | **Executable track**, mark-to-market at each 4h run | Every run |
| Reconciliation | Mismatches **> 5% of trades** in the weekly trade-by-trade comparison with the backtest on the same Delta candles. A mismatch is a trade present in only one log, or the same trade with a different exit type or exit bar. With few trades, a single mismatch triggers this, deliberately | **Model track** | Weekly (first run after Monday 00:00 UTC) |
| Execution cost | Average **execution cost vs mid > 0.03% per side**, over at least 10 fills with a live order book | Execution cost (§1) | Every run |

Each pause is investigated and its cause written down (in the events table and this repository) before resuming.

## 5. Weekly report (Telegram + stored in the database)

Each weekly report contains:
- equity per coin and in total, **model and executable tracks side by side**, with each track's maximum drawdown;
- open positions;
- funding paid or received;
- **execution cost vs mid** against the 0.01% model assumption and the 0.03% pause line;
- **LTP staleness per coin, signed average and absolute average**;
- the reconciliation result (model track), listing every mismatch with its cause.

Entries and exits are also alerted as they happen, with both the model and executable fill prices.

## 6. "Good enough to go live with small money": all must hold at the review point

| # | Criterion | Track / metric | Threshold (fixed now) |
|---|---|---|---|
| 1 | Performance | **Executable track** | Net return over the review window **≥ the 5th percentile** of the backtest's monthly-block bootstrap for a window of the same length, i.e. inside or above its 90% range. For reference: −0.86% at 6 months, −0.33% at 12 months; the exact length at review is recomputed with `paper.plan_stats` |
| 2 | Fidelity | **Model track** | Net P&L within **±0.5% of the budget ($12.50) or ±20% of the same-period backtest's P&L, whichever is larger**, of the backtest rerun on the same Delta candles over the same period |
| 3 | Reconciliation | **Model track** | Over the whole period, mismatches **≤ 5% of trades**, each with an identified cause (e.g. a missed run) |
| 4 | Execution cost | Execution cost vs mid (§1) | Average **≤ 0.03% per side** over at least 30 fills with a live order book |
| 5 | Risk | **Executable track** | Max drawdown **≤ 2.6%** (95th percentile of the backtest bootstrap for 12 months) and the drawdown pause never triggered |
| 6 | Operations | Run log | **≥ 98%** of scheduled 4h runs completed; no unresolved pause |

**Outcomes**
- **All six pass:** go live with **real money of at most $2,500** in the same coins, same split, same frozen rules and the same pause rules, then review again after 6 months live before adding any money.
- **Only criterion 1 or 5 fails:** extend paper trading by 6 months, no rule changes, and review again.
- **Criterion 2, 3, 4 or 6 fails:** the problem is execution or data, not the edge. Fix it, document it, and start a new paper period.
- **The drawdown pause triggers twice:** stop the project's live plans for this strategy and write up why.

## 7. Known limitations of the shadow trader

1. **Stops:** they are inferred from 1h candles. A real stop order could fill worse in a fast market than the stop-minus-0.01%, and both tracks use that model fill for stops (gap fills are modelled at the bar open).
2. **Fills:** paper fills ignore queue position and partial fills. Order sizes here are a few contracts, far below the L1 sizes Delta shows for these coins.
3. **Downtime:** missed 4h closes are logged. Entries and time exits are then taken late at the next live price, which the reconciliation reports as a mismatch; stops are unaffected.
4. **Small sub-accounts:** XRP, BCH and LTC (about $167 each) round to whole contracts. Actual risk per trade can be well below 0.5%, and some trades are skipped. The backtest reference above includes the same rounding.
5. **Alerts:** Telegram can fail. Failures never stop the trader, and every alert is also in the database and CloudWatch logs.

## Change log

### v2, 23 Nov 2026 (before go-live)

**Reason.** In v1, slippage was measured against the last traded price (LTP). The 23 Nov 2026 local dry run (12:00 UTC close, live Delta data, 5 sell fills) showed that this mostly measures how **stale the last trade** is in thinly traded coins, not what a market order actually costs. v1 measured 0.028% per side, close to the 0.03% pause line. The real cost of crossing the book against mid was 0.009% per side, inside the 0.01% assumption.

| Coin | Best bid / ask | Last price | v1 metric: cost vs LTP | **v2 metric: execution cost vs mid** | LTP staleness (signed) |
|---|---|---|---|---|---|
| BTCUSD | 61,273.5 / 61,274.0 | 61,274.00 | 0.0008% | 0.0004% | +0.0004% |
| ETHUSD | 1,719.50 / 1,719.55 | 1,719.55 | 0.0029% | 0.0015% | +0.0015% |
| XRPUSD | 0.9399 / 0.9401 | 0.9400 | 0.0106% | 0.0106% | 0.0000% |
| BCHUSD | 199.44 / 199.47 | 199.50 | 0.0301% | 0.0075% | +0.0226% |
| LTCUSD | 40.96 / 40.98 | 41.00 | 0.0976% | 0.0244% | +0.0732% |
| **Average** | | | **0.0284%** | **0.0089%** | abs 0.0195% |

**Changes**
1. The pause rule and go-live criterion now use **execution cost vs mid** in the same order-book snapshot (§1, §4, §6 #4).
2. **LTP staleness** (signed, per coin) is recorded and reported weekly as a diagnostic, with no rule attached.
3. An **executable equity track** was added (book ask/bid fills, same trades). The model track stays the basis for backtest parity (reconciliation, ±0.5% fidelity). The executable track drives the return and drawdown criteria and the drawdown pause.
4. **Fresh start:** the dry-run state was discarded. The 12-month period begins with a fresh init on the first scheduled AWS run.

`frozen_rules.md` is unchanged.

### v1, 23 Nov 2026

Initial plan (commit `4a802b3`).
