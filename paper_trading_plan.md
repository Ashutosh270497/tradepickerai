# Paper trading plan: frozen 4h trend filter (pre-registered)

Committed **before** the paper trader goes live; the git timestamp is the record.

- **Rules:** [`frozen_rules.md`](frozen_rules.md) stays frozen. Nothing in this plan changes or retunes a trading rule.
- **If anything here needs to change:** write a new plan, commit it, and restart the paper period.

## 1. What is paper traded

| Item | Setting |
|---|---|
| Strategy | `strategies/trend_ma_4h.py`, `DEFAULT` parameters, exactly as in `frozen_rules.md` (4h close vs SMA200, long/short, 20-day hold, 2 × daily ATR(20) stop, 0.5% risk, 3x cap, Delta taker fee + 18% GST, 0.01% slippage per side, funding as Delta publishes it) |
| Budget | **$2,500**, the amount you said you would actually trade |
| Split (your choice) | One sub-account per coin, each risking 0.5% of itself per trade: **BTCUSD $1,400, ETHUSD $600, XRPUSD $167, BCHUSD $167, LTCUSD $166** (`paper_config.json`) |
| Data | Delta Exchange India **public** API only: 1h candles, funding history, live order book and ticker. No API keys, no orders |
| Schedule | Every 4 hours, 5 minutes after 00/04/08/12/16/20 UTC |

**How fills are simulated**
- **Entries and time exits:** at the live last traded price a few minutes after the 4h close, plus or minus 0.01% slippage (frozen).
- **Stops:** treated as resting stop-market orders on the exchange (frozen rules), so they are detected from Delta's 1h candles and fill at the stop minus 0.01%, or at the bar open if price gapped through the stop.
- **Funding:** each Delta settlement is applied once (rate = the published value in the hour before the settlement).
- **Live quotes:** every live fill records the L1 best bid and ask with sizes, the mark price and the last price.

**Measured slippage** for a live fill is the cost of crossing the book versus the model's reference price:
- buy: (best ask ÷ last price − 1);
- sell: (1 − best bid ÷ last price).

The half-spread vs mid is reported alongside. Stop fills are excluded, because no live quote exists at the moment a stop triggers.

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

When any of these triggers, the trader **pauses**: no new entries; open positions are still managed by the frozen stops and time exits. It sends a Telegram alert and stays paused until you review and run `python3 -m paper.trader resume`.

| Rule | Threshold | When checked |
|---|---|---|
| Drawdown | Paper combined equity drawdown (mark-to-market at each 4h run) **> 4.83%** (= 2 × backtest max DD of 2.42%) | Every run |
| Reconciliation | Mismatches **> 5% of trades** in the weekly trade-by-trade comparison with the backtest on the same Delta candles. A mismatch is a trade present in only one log, or the same trade with a different exit type or exit bar. With few trades, a single mismatch triggers this, deliberately | Weekly (first run after Monday 00:00 UTC) |
| Slippage | Average measured slippage **> 0.03% per side**, over at least 10 live fills | Every run |

Each pause is investigated and its cause written down (in the events table and this repository) before resuming.

## 5. Weekly report (Telegram + stored in the database)

Each weekly report contains:
- equity per coin and in total;
- open positions;
- funding paid or received;
- measured slippage vs the 0.01% assumption (and the half-spread);
- the reconciliation result, listing every mismatch with its cause.

Entries and exits are also alerted as they happen.

## 6. "Good enough to go live with small money": all must hold at the review point

| # | Criterion | Threshold (fixed now) |
|---|---|---|
| 1 | Performance | Paper net return over the review window **≥ the 5th percentile** of the backtest's monthly-block bootstrap for a window of the same length, i.e. inside or above its 90% range. For reference: −0.86% at 6 months, −0.33% at 12 months; the exact length at review is recomputed with `paper.plan_stats` |
| 2 | Fidelity | Paper net P&L within **±0.5% of the budget ($12.50) or ±20% of the same-period backtest's P&L, whichever is larger**, of the backtest rerun on the same Delta candles over the same period |
| 3 | Reconciliation | Over the whole period, mismatches **≤ 5% of trades**, each with an identified cause (e.g. a missed run) |
| 4 | Slippage | Average measured slippage **≤ 0.03% per side** over at least 30 live fills |
| 5 | Risk | Paper max drawdown **≤ 2.6%** (95th percentile of the backtest bootstrap for 12 months) and the drawdown pause never triggered |
| 6 | Operations | **≥ 98%** of scheduled 4h runs completed; no unresolved pause |

**Outcomes**
- **All six pass:** go live with **real money of at most $2,500** in the same coins, same split, same frozen rules and the same pause rules, then review again after 6 months live before adding any money.
- **Only criterion 1 or 5 fails:** extend paper trading by 6 months, no rule changes, and review again.
- **Criterion 2, 3, 4 or 6 fails:** the problem is execution or data, not the edge. Fix it, document it, and start a new paper period.
- **The drawdown pause triggers twice:** stop the project's live plans for this strategy and write up why.

## 7. Known limitations of the shadow trader

1. **Stops:** they are inferred from 1h candles. A real stop order could fill worse in a fast market than the stop-minus-0.01% (gap fills are modelled at the bar open).
2. **Fills:** paper fills ignore queue position and partial fills. Order sizes here are a few contracts, far below the L1 sizes Delta shows for these coins.
3. **Downtime:** missed 4h closes are logged. Entries and time exits are then taken late at the next live price, which the reconciliation reports as a mismatch; stops are unaffected.
4. **Small sub-accounts:** XRP, BCH and LTC (about $167 each) round to whole contracts. Actual risk per trade can be well below 0.5%, and some trades are skipped. The backtest reference above includes the same rounding.
5. **Alerts:** Telegram can fail. Failures never stop the trader, and every alert is also in the database and CloudWatch logs.
