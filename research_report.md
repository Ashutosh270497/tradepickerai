# Phase 3: is there a real edge at longer holding periods?

Run on 23 Nov 2026. Signals were screened for an edge at zero cost first, and only the survivor was built into a strategy.

## Verdict

| Strategy | Your PASS rule (stitched walk-forward out-of-sample, 2022-01 → 2026-11) | Same rule on the clean half only (2022-01 → 2024-08) | My assessment |
|---|---|---|---|
| **4h price vs SMA trend filter, 10–30-day hold** (the only screen survivor) | **PASS**, but only just | Would **not** pass: 87.5th percentile vs random (needs 95th); expectancy confidence interval includes zero | **LOW-CONFIDENCE.** Paper-trade it; don't fund it yet |
| The other 241 signal configurations | Did not survive the screen | – | FAIL |

**In plain language**
- **Short horizons have nothing.** At 15 minutes, no signal had a gross edge big enough to cover costs, including your 9/21 EMA cross (about 0.00%–0.10% gross per trade).
- **One trend signal holds up, weakly.** Following the 4-hour trend for 2–4 weeks is the only thing that showed an edge clearly bigger than costs and that survived the multiple-testing correction.
- **It passes your bar, but only just.** As a full strategy with Delta fees, slippage and actual funding, it clears every PASS test, with little room on most of them.
- **Three things make me rate it LOW-CONFIDENCE:**
  - **Selection overlap.** The signal was chosen partly on 2024–2026 data, and that period supplies most of the strength. In 2022–2024, a period that played no role in choosing it, it is no better than random at the 95% level.
  - **The bar is close to the line.** The expectancy confidence interval lower bound is 0.02R, and the random percentile is 97 against a bar of 95. Small changes (account size, slippage) moved the profit factor between 1.42 and 1.57 just by shifting the trade sequence.
  - **The benchmark was easy.** Buy-and-hold BTC/ETH (50/50) lost 12% over this window (ETH −54%), so "better than buy-and-hold" was a low bar.
- **The returns are small at your risk setting.** At 0.5% risk per trade with an 8% stop, the strategy holds positions worth only about 6% of equity. Result: +12.4% in 4.9 years (2.4% a year) with a 2.8% maximum drawdown. Risking more per trade would scale return and drawdown up roughly in proportion; I have not tested that.
- **Funding costs more than fees on multi-day holds:** $236 in funding versus $191 in fees, on $2,913 of gross profit.
- **A $1,000 account can't run this on BTC.** With 0.5% risk and an 8% stop, the position is smaller than Delta's minimum of 0.001 BTC (about $100 at 2025 prices), so about a third of BTC trades get skipped. Results below use $10,000 per coin.

## Step 1: data and sources

| Use | Source | Coverage | Gaps |
|---|---|---|---|
| 15m and 1h signals | Delta Exchange India API, BTCUSD/ETHUSD perpetual 1m candles, resampled | 2024-11-13 → 2026-11-23 | One 31-minute exchange halt (Phase 2) |
| 4h and 1D signals; Step 3 backtest prices | **Binance USD-M perpetual BTCUSDT/ETHUSDT**, public archive [data.binance.vision](https://data.binance.vision/) (monthly and daily 1h kline files) | 2020-01-01 → 2026-11-21, 60,408 hourly bars per coin | None |
| Funding for screen signals | Delta for 15m/1h; Binance archive (`fundingRate`, 8-hourly, 7,488 readings per coin, to 2026-10-31) for 4h/1D | – | Binance publishes funding monthly only, so November 2026 is missing there |
| Funding charged in Step 3 | Delta's actual rate from 2024-11-08; before that Binance's rate **plus** the measured Delta−Binance gap (+0.0033% per 8h for BTC, +0.0036% for ETH) | 2020 → 2026 | – |
| Fees, tick, lot | Delta API (`/v2/products`), unchanged from Phase 2 | – | – |

- **Fallbacks are blocked.** Bybit's public API (HTTP 403) and Binance's live futures API (HTTP 451) refuse requests from this server, so the Binance archive is the only long-history source.
- **Binance vs Delta prices agree.** Over the overlapping period, 1h returns correlate at 0.9993 and the median close difference is 0.01% (BTC) / 0.015% (ETH). Binance prices are a fair proxy for Delta's.
- **Funding does not agree.** Delta's averaged 0.0078% per 8h versus Binance's 0.0045% (correlation 0.45), hence the gap adjustment above.

## Step 2: zero-cost edge screen

- **Script and output:** `edge_screen.py` writes `edge_screen.csv`.
- **Events:** each signal is read at a bar close and held for a fixed horizon, close to close, with no overlap between events.
- **Measures:** gross edge = average direction-adjusted return per event. The t-test is on excess return over the unconditional average for the same horizon and period.
- **Split:** first 2/3 of each dataset in-sample, last 1/3 out-of-sample (Delta split at 2026-03-24, Binance split at 2024-08-05).
- **Correction:** Benjamini-Hochberg on the BTC+ETH pooled out-of-sample p-values.

### How many tests, and how many pass by chance

| Item | Count |
|---|---|
| Signal configurations (signal × parameters × timeframe × horizon) | **242** |
| Individual tests (configuration × asset × in-sample/out-of-sample) | 968 (1,452 rows including BTC+ETH pooled) |
| Expected false positives at raw p < 0.05, from chance alone | about 12 |
| Out-of-sample configurations with raw p < 0.05 | 23 (in-sample: 29) |
| Significant after Benjamini-Hochberg (q ≤ 0.05), out-of-sample | 2 |
| Of those 2 | 1 survivor; 1 calendar effect (hour 11 UTC) that **reversed** its in-sample direction and has a tiny edge (−0.06%) |
| Pass all three survival tests | **1** |

The survival tests are: pooled out-of-sample gross edge ≥ 0.36%, positive on both BTC and ETH, and BH-significant.

### By family (out-of-sample, pooled BTC+ETH)

| Family | Configs | Gross edge ≥ 0.36% | Positive on both coins | Raw p < 0.05 | BH-significant | Survivors | Best gross edge (config) |
|---|---|---|---|---|---|---|---|
| 1 Time-series momentum | 36 | 7 | 17 | 3 | 0 | 0 | +2.25% (1D, 60-day lookback, 20-day hold), p = 0.13 |
| 2 Trend filters (price vs MA, MA slope) | 72 | 16 | 45 | 8 | 1 | **1** | **+5.60% (4h, price vs SMA200, 20-day hold), q = 0.031** |
| 3 Donchian breakouts | 24 | 8 | 12 | 2 | 0 | 0 | +5.34% (1D, 55-day, 20-day hold), p = 0.029, q = 0.45 |
| 4 Mean reversion (RSI 2/14, MA distance) | 48 | 4 | 6 | 1 | 0 | 0 | +1.97% (1D RSI(2), 20-day hold), p = 0.23 |
| 5 Calendar (hour, 4h block, weekday, weekend) | 38 | 2 | 15 | 7 | 1 | 0 | +0.55% (Thursday short), p = 0.012, q = 0.45 |
| 6 Funding extremes (top/bottom 10%) | 18 | 6 | 7 | 1 | 0 | 0 | +2.29% (4h, top-10% funding then long, 20 days), p = 0.60 |
| 7 Reference: your EMA 9/21 on 15m; earlier EMA 50/200 on 4h | 6 | 2 | 3 | 1 | 0 | 0 | EMA 50/200: +1.72%, p = 0.55. EMA 9/21: −0.04% to +0.10%, p ≥ 0.09 |

By timeframe, the number of configs with a gross edge ≥ 0.36% was: **15m 0 of 48**, 1h 10 of 75, 4h 18 of 60, 1D 17 of 59. Only multi-day horizons produce moves big enough to pay for costs.

**The survivor, unvarnished**
- **Signal:** 4h price vs SMA200 (about 33 days), long above, short below, held 20 days.
- **Out-of-sample:** +5.6% gross per trade over 82 non-overlapping trades (BTC +4.2%, ETH +7.0%), 62% hit rate, t = 3.87.
- **In-sample (2020–2024):** only +1.9% per trade, t = 0.58, **not significant**.
- **Neighbours point the same way, without significance.** Nearby trend configs (SMA100, SMA200 slope, 1D SMA50, Donchian 20/55 on 1D) were also positive at multi-week horizons, which makes trend-following plausible, but none of them is significant on its own.

## Step 3: full backtest of the survivor

- **Code:** `strategies/trend_ma_4h.py`, run by `phase3_runner.py`.
- **Rules:**
  - At each 4h close, long if price is above its SMA(n), short if below.
  - Market entry at the next bar open.
  - Exit after the holding period or at a hard stop of 2 × the 20-day ATR (daily bars), then re-enter at the next 4h close in the current direction.
- **Costs:** Delta fees; slippage 0.01% (base) and 0.03% (stress) per side; actual funding every 8h.
- **Sizing:** 0.5% risk per trade, leverage capped at 3x, $10,000 per coin.
- **Walk-forward:**
  - Train 24 months, test 6 months, roll 6 months.
  - Tune SMA length n ∈ {100, 150, 200, 250, 300} (4h bars) and hold ∈ {10, 20, 30} days, picked by combined daily Sharpe on each training window.
  - Ten test windows from 2022-01-01, stitched together.

### PASS checklist (taker fees, 0.01% slippage, stitched out-of-sample)

| Test | Bar | Result | Pass |
|---|---|---|---|
| Net profit factor | ≥ 1.3 | 1.43 | ✓ |
| Net positive on BTC | > 0 | +$1,146 (+11.5%) | ✓ |
| Net positive on ETH | > 0 | +$1,340 (+13.4%) | ✓ |
| Random-entry baseline (200 runs) | > 95th percentile | 97th (BTC alone 93rd, ETH alone 94.5th) | ✓ (combined) |
| Sharpe vs 50/50 buy-and-hold | higher | 0.83 vs 0.23 | ✓ |
| CAGR / max drawdown vs buy-and-hold | higher | 0.86 vs −0.04 | ✓ |
| Trades | ≥ 30 | 267 | ✓ |
| Bootstrap 95% CI of expectancy | above 0 | +0.02R to +0.36R (mean +0.19R) | ✓ (barely) |

### Cost scenarios (stitched out-of-sample, BTC+ETH, $20,000 total)

| Scenario | Trades | Net $ | Fees $ | Funding $ | PF | Expectancy R | CI low (R) | Sharpe | CAGR/MaxDD |
|---|---|---|---|---|---|---|---|---|---|
| Taker, 0.01% slippage | 267 | +2,485 | 191 | −236 | 1.43 | 0.186 | 0.019 | 0.83 | 0.86 |
| Taker, 0.03% slippage | 265 | +2,603 | 191 | −224 | 1.46 | 0.194 | 0.027 | 0.86 | 0.90 |
| Maker (limit fills assumed), 0.01% | 267 | +2,466 | 99 | −239 | 1.42 | 0.185 | 0.016 | 0.82 | 0.85 |
| Maker (limit fills assumed), 0.03% | 267 | +2,449 | 99 | −239 | 1.41 | 0.184 | 0.015 | 0.82 | 0.84 |

The 0.03% stress run ending slightly *better* than 0.01% is not a real effect. One different exit shifts every later entry (path dependence), and that noise (about ±5%) is as large as the cost difference.

### Strategy vs buy-and-hold (same dates; buy-and-hold is price only, no funding)

| | Total return | CAGR | Max drawdown | CAGR/MaxDD | Sharpe |
|---|---|---|---|---|---|
| Strategy, BTC | +11.5% | +2.2% | 5.9% | 0.38 | 0.69 |
| Strategy, ETH | +13.4% | +2.6% | 3.8% | 0.69 | 0.80 |
| Strategy, BTC+ETH | +12.4% | +2.4% | 2.8% | 0.86 | 0.83 |
| Buy & hold BTC | +30.3% | +5.6% | 66.9% | 0.08 | 0.36 |
| Buy & hold ETH | −54.2% | −14.7% | 74.0% | −0.20 | 0.11 |
| Buy & hold 50/50 | −12.0% | −2.6% | 68.9% | −0.04 | 0.23 |

### Robustness

| Check | Result |
|---|---|
| Clean half, 2022-01 → 2024-08 (not used to pick the signal) | 137 trades, PF 1.33, BTC +$756, ETH +$286, expectancy +0.15R, CI −0.08R to +0.41R, **87.5th percentile vs random → would not pass** |
| Overlap half, 2024-08 → 2026-11 (used to pick the signal) | 130 trades, PF 1.54, BTC +$390, ETH +$1,053, expectancy +0.22R, CI −0.02R to +0.48R, 96.5th percentile |
| Net $ by entry year | 2022 +37, 2023 +713, 2024 +496, 2025 +50, 2026 +1,190 (48% of the total from 2026 alone) |
| Long vs short | Longs +$1,434, shorts +$1,052 (both positive) |
| Parameters picked per window | SMA 100–300 and hold 10–30 days both changed across windows; no stable optimum |
| Exposure | Average position 5.8% of equity (max about 11%); average hold 13 days; 37% of trades exit at the stop |
| $1,000 per coin instead of $10,000 | About a third of BTC trades skipped (below 1 contract); PF 1.57, random percentile 99.5. Better, but only because the trade sequence changed |

Equity curves against buy-and-hold are in `charts/phase3_trend_ma_4h.png`.

### Phase 3 assumptions

| # | Assumption |
|---|---|
| 1 | Binance BTCUSDT/ETHUSDT prices stand in for Delta BTCUSD/ETHUSD (correlation 0.999 over the overlap); Delta fees, tick and lot are used for costs |
| 2 | Funding before Nov 2024 = Binance rate + measured Delta gap; Delta actual after |
| 3 | Screen: close-to-close forward returns, non-overlapping events, no costs. Calendar and funding signal directions were chosen in-sample, so their in-sample numbers are biased upward |
| 4 | Survival rule: pooled BTC+ETH out-of-sample gross edge ≥ 0.36% (3 × your ~0.12%); both coins positive; BH q ≤ 0.05 on pooled out-of-sample p-values. At Phase 2's cost model (0.138%, so 3× = 0.41%) the result is the same |
| 5 | Strategy additions to the screened signal: a 2 × daily-ATR(20) hard stop (needed for 0.5% risk sizing) and immediate re-entry after each exit |
| 6 | Walk-forward picks by combined daily mark-to-market Sharpe under taker costs (at least 10 trades); the same picks are used for every cost scenario |
| 7 | Benchmark tests compare BTC+ETH combined with 50/50 buy-and-hold (per-coin comparisons also shown; both coins beat their own buy-and-hold) |
| 8 | PASS needs the bootstrap CI lower bound above 0 (10,000 resamples of trade R); otherwise LOW-CONFIDENCE |
| 9 | The maker scenario assumes limit orders fill at the bar open; stops stay stop-market |
| 10 | Mark-to-market equity is valued at daily closes, with half of the trade's fees charged while open |

### Phase 3 files

- `edge_screen.py` → `edge_screen.csv` (every test) and `logs/edge_screen_summary.md`
- `phase3_runner.py` → `phase3_verdicts.csv`, `phase3_results.csv` (all scenarios, segments and assets), `logs/phase3_walkforward_trend_ma_4h.csv` (every parameter on every training window), `logs/phase3_random_baseline.csv`, `logs/phase3_subperiod_checks.csv`, `charts/phase3_trend_ma_4h.png`
- `core/binance_data.py` (Binance archive downloader), `core/market.py` (`load_binance_market`, any bar size), `strategies/trend_ma_4h.py`
- `data/` is no longer committed. Rebuild it with:

```bash
python3 -m core.data download --days 740
```

```bash
python3 -m core.binance_data
```

Then rerun everything:

```bash
python3 edge_screen.py
```

```bash
python3 phase3_runner.py
```

### What I'd do next (not done; you asked me to stop here)

1. Paper-trade the trend filter forward on Delta's testnet for at least 6 months: the only clean test left.
2. Test the identical rules on other liquid perpetuals (SOL, XRP, BNB) from Binance's archive. That is an out-of-sample check that doesn't need new time to pass.
3. If both hold up, decide the risk per trade deliberately: at 0.5% the strategy earns about 2.4% a year.

---

# Phase 2: do crypto scalping strategies make money on Delta Exchange India?

Backtest of 7 shortlisted strategies on 2 years of Delta Exchange 1-minute data for BTCUSD and ETHUSD perpetuals, run on 23 Nov 2026.

## Verdict

**None of the 7 strategies passes, and none is CONDITIONAL. My recommendation is not to trade any of them with real money (suggested risk per trade: zero).**

- **Out-of-sample:** every strategy lost money in every fee scenario (standard fees, 50% off the closing fee, and the free close that Delta's Scalper Offer actually gives).
- **In-sample:** not one of the 108 parameter variants (324 variant-scenario combinations) reached a profit factor of 1.0. Tuning had nothing to find.
- **Fees are not the only problem.** Before any costs, average gross results range from −0.71R to +0.05R per trade (in-sample and out-of-sample). Fees then take another 0.04R to 0.60R per trade.
- **The Scalper Offer narrows losses but turns nothing positive.** Its free close cuts round-trip costs by about 25% to 65%, depending on the strategy's order types. But qualifying requires closing within 30 minutes, and the 29-minute time stop that guarantees this cuts off the longer-holding strategies' winners.
- **Random baselines:** no strategy beat its random-entry baseline at the 95th percentile. The best reached the 71st percentile. VWAP fade did worse than all 200 random runs.
- **This matches Phase 1.** The research found no published, fee-inclusive evidence of a profitable 1–5 minute BTC/ETH scalp, and this test reproduces that on Delta's own data.

## 1. Platform facts (re-verified 23 Nov 2026)

| Item | Value | Source | Matches `phase1_findings.md`? |
|---|---|---|---|
| Taker / maker fee | 0.05% / 0.02% of notional (BTCUSD and ETHUSD) | API `GET /v2/products/{symbol}`: `taker_commission_rate` 0.0005, `maker_commission_rate` 0.0002 | Yes |
| GST | 18% on trading fees, so 0.059% taker / 0.0236% maker per side | https://www.delta.exchange/fees ("18% GST is applicable on trading fees") | Yes |
| Contract size | BTCUSD 0.001 BTC; ETHUSD 0.01 ETH | API `contract_value` | Yes |
| Tick size | BTCUSD $0.5; ETHUSD $0.05 | API `tick_size` | Yes |
| Max leverage | 200x (`initial_margin` 0.5%) up to $100,000 notional | API `default_leverage`, `max_leverage_notional` | Yes |
| Funding | Every 8 hours (`rate_exchange_interval` 28,800 s), mark-price method, clamp 0.05% | API `product_specs`; history from `FUNDING:{symbol}` candles | Yes |
| Candles | `GET /v2/history/candles`, max 2,000 per call, 1m–1w | https://docs.delta.exchange/ | Yes |
| Rate limit | 20,000 weight per 5 min; candles weight 3 | https://docs.delta.exchange/ | Yes |

### Scalper Offer: exact current terms

Source: Delta help centre, [Scalper Offer](https://www.delta.exchange/support/solutions/articles/80001172745-scalper-offer) and [Futures Scalper Offer](https://www.delta.exchange/support/solutions/articles/80001149608-futures-scalper-offer).

| Question | Answer | Confidence |
|---|---|---|
| 100% or 50% off the close? | **100%.** "Zero closing fee on Futures trades that you open and close within the scalping window" | Confirmed |
| Why does the fee page say "up to 50% off"? | The closing fee is half the round-trip fee when both legs pay the same rate, so a free close is "up to 50% off" total fees | My reading of the fee page |
| Window | BTCUSD and ETHUSD: 30 minutes; other futures: 15 minutes | Confirmed |
| Products | All futures except PAXGUSD, XAUTUSD, SLVONUSD; not options | Confirmed |
| Order types | Any. Delta's worked examples cover maker/maker, taker/taker and maker/taker | Confirmed |
| Partial closes | Eligible | Confirmed |
| Stop-loss closes | Not mentioned. **Assumed eligible**, since a stop is an ordinary closing order | Assumption |
| Liquidations | Not eligible (stated in the current terms). Irrelevant here: leverage ≤ 10x with hard stops never liquidates | Confirmed |
| GST on the waived fee | Examples are "excluding GST". **Assumed no GST** when the fee is zero (GST is charged on the fee) | Assumption |
| Opt-in | KYC users must click "Join Now"; trades before joining don't count; cannot be deactivated once joined | Confirmed |
| End date | **None stated** for the base offer; "Delta Exchange reserves the right to modify or discontinue this offer without prior notice" | Confirmed |
| Diwali add-on | BTCUSD only: the opening fee came back as a fee voucher (capped at $100/month). **Ended 19 Nov 2026, 17:30 IST**, so it is not modelled | Confirmed |

The "50% off the close" scenario is therefore hypothetical: it shows what happens if Delta halves the offer.

### Breakeven per round trip (Phase 2 cost model)

Market legs carry 0.01% slippage; limit legs carry none. Values are % of notional.

| Execution | Standard | 50% off close | Free close (≤ 29 min) |
|---|---|---|---|
| Market in, market out | 0.138% | 0.109% | 0.079% |
| Limit in, market out | 0.093% | 0.063% | 0.034% |
| Market in, limit out | 0.093% | 0.081% | 0.069% |
| Limit in, limit out | 0.047% | 0.035% | 0.024% |
| Market/market at stress slippage (0.03%) | 0.178% | 0.149% | 0.119% |

The base slippage of 0.01% per side is about 12 ticks on BTC at $61,000 and 3.5 ticks on ETH at $1,730, so it is stricter than the "at least 1 tick" minimum.

## 2. Data

| Item | BTCUSD | ETHUSD |
|---|---|---|
| 1m last-traded-price candles | 1,065,569 (2024-11-13 05:00 to 2026-11-23 04:59 UTC) | 1,065,569 (same span) |
| 1m gaps | 1 gap of 31 candles, 2025-06-01 05:00–05:31 UTC | Same gap |
| 5m candles | 213,120, no gaps | 213,120, no gaps |
| 1m resampled vs Delta 5m | Closes identical on all 213,119 bars; 38 opens, 16 highs, 13 lows differ slightly | Closes identical; 160 opens, 41 highs, 49 lows differ slightly |
| Funding history | 17,861 hourly values, 8 gaps (16 h) forward-filled; mean 0.0077% per 8h, range −0.080% to +0.079% | Mean 0.0075% per 8h, range −0.025% to +0.049% |

- **The 1m gap is an exchange halt.** Delta's own 5m candles show flat, zero-volume bars for those minutes, so I filled them as flat bars.
- **All execution uses 1m data.** Higher timeframes are resampled from 1m, so signals and fills come from the same series.
- **Storage:** everything is cached as parquet in `data/`, and `python3 -m core.data download` refreshes it.

### Market context: quarterly price change in the test window

| Quarter | 24Q4* | 25Q1 | 25Q2 | 25Q3 | 25Q4 | 26Q1 | 26Q2 | 26Q3 | 26Q4* |
|---|---|---|---|---|---|---|---|---|---|
| BTC return % | −5.4 | −11.8 | +29.8 | +6.4 | −23.1 | −22.1 | −14.1 | +42.6 | −26.8 |
| ETH return % | +0.3 | −45.4 | +36.4 | +66.8 | −28.3 | −29.2 | −25.3 | +70.8 | −35.7 |

\*Partial quarters. The window covers strong rallies, crashes and choppy stretches, so the result is not one regime.

## 3. Engine and tests

The engine is a custom event loop on 1m bars (`core/engine.py`).

**Fills**
- Signals use closed candles only; orders fill on the next bar.
- A higher-timeframe bar is usable only from the 1m bar that opens at its close.
- Limit orders fill only when price trades at least 1 tick through, at the limit price, as maker.
- No take-profit is allowed on the bar a limit entry fills.
- Stops fill at the stop price minus slippage, or at the bar open if price gapped through.
- If the stop and target fall in the same 1m bar, the stop is assumed to hit first.
- Time stops and end-of-day exits are market orders at the bar open.
- Moving targets (VWAP, middle Bollinger band) are limit orders re-priced each minute; if the bar opens beyond the target, the exit is a market order.

**Costs**
- Funding is charged at 00/08/16 UTC on positions open across the settlement, at Delta's actual historical rate.
- The Scalper Offer discount applies only when a position is held less than 30 minutes. The offer scenarios force a 29-minute time stop on every strategy.

**Sizing**
- Each trade risks 0.5% of current equity at the stop.
- Notional is capped at 10x equity and rounded down to whole contracts.
- Trading halts if equity falls to 10% of the start (only VWAP fade hit this).
- **Leverage cap usage:** hit on at most 3.5% of trades (VWAP fade) and 1.4% (Bollinger + RSI); never for the other strategies.

**Tests:** `python3 -m pytest -q tests` gives 16 passed. They cover:
- fees with GST, and adverse slippage on longs and shorts;
- maker fee on limit fills, and the 1-tick trade-through rule for entries and targets;
- intrabar and gap stop fills, and stop-before-target in the same bar;
- the waiver at 29 minutes (qualifies) versus 30 minutes (does not), including the 50% case;
- funding sign and timing (charged only across a settlement, not when opening or closing exactly at it);
- the 0.5% risk sizing, the 10x cap and lot rounding;
- market exit when the open crosses a moving target;
- one position at a time, and causal swing detection;
- higher-timeframe bars usable only after they close;
- a reproducible random baseline, and the ruin halt.

I also hand-checked one live trade (entry slippage, exit slippage, fees) and re-counted VWAP-fade stop-outs independently (49% versus the engine's 48%).

## 4. Testing protocol

- **Window:** 2024-11-23 to 2026-11-23. In-sample (IS) is 2024-11-23 to 2026-03-23 (16 months); out-of-sample (OOS) is 2026-03-23 to 2026-11-23 (8 months). Earlier data is indicator warm-up only.
- **Defaults:** each strategy starts from the `phase1_findings.md` rules, with at most 2 tuned parameters of at most 5 values each (108 variants in total).
- **Selection:** separately for each fee scenario, the variant with the highest combined BTC+ETH net R on IS only, among variants with at least 100 IS trades (50 for one-trade-a-day strategies).
- **Logging:** every variant's IS and OOS results are in `logs/variants_log.csv` (1,944 rows). OOS rows are marked as not used for selection.
- **Side effect of the selection rule:** because every variant lost, "highest total net R" favoured the variants that traded least. Ranking by profit factor would have picked some different variants (for example the US-session anchor for intraday momentum), but none had an in-sample profit factor above 1, so no verdict would change.
- **Random baseline:** 200 runs per strategy, scenario and symbol. Each run uses the same trade count, the strategy's own direction mix, stop and target distances, time limits and entry order type, at random OOS entry bars, with the same costs.
- **PASS bar (OOS, base slippage):**
  - profit factor ≥ 1.2;
  - at least 100 trades, or 50 for one-trade-a-day strategies, flagged low sample (I counted BTC and ETH trades together; per-symbol counts are in `results.csv`);
  - net positive on BTC and on ETH;
  - above the 95th percentile of the random baseline.

## 5. Results

### 5.1 Out-of-sample comparison (BTC+ETH combined, $1,000 per symbol, base slippage)

| Strategy | Fee scenario | Selected params (IS) | OOS trades | Net % | PF | Win % | Exp. R | Max DD % | Sharpe | Random pct | Pass |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 ORB | Standard | range_min=60, target_rr=1.0 | 743 | -35.5 | 0.31 | 29.5 | -0.24 | 35.5 | -12.1 | 9 | no |
| 1 ORB | 50% off close | range_min=60, target_rr=3.0 | 743 | -30.5 | 0.36 | 30.8 | -0.20 | 30.6 | -9.4 | 11 | no |
| 1 ORB | Free close | range_min=60, target_rr=3.0 | 744 | -24.1 | 0.46 | 33.7 | -0.15 | 24.5 | -7.3 | 6 | no |
| 2 Asia→London | Standard | stop_mult=1.0, target_mult=1.0 | 431 | -8.1 | 0.81 | 46.4 | -0.08 | 9.4 | -2.0 | 71 | no |
| 2 Asia→London | 50% off close | stop_mult=1.0, target_mult=1.5 | 431 | -9.4 | 0.42 | 28.1 | -0.09 | 9.9 | -7.1 | 62 | no |
| 2 Asia→London | Free close | stop_mult=1.0, target_mult=1.5 | 431 | -6.9 | 0.52 | 31.8 | -0.07 | 7.3 | -5.2 | 58 | no |
| 3 VWAP fade | Standard | band_k=2.5, exit=1sigma | 939 | -90.0 | 0.19 | 12.1 | -1.08 | 90.1 | -3.3 | 0 | no |
| 3 VWAP fade | 50% off close | band_k=2.5, exit=1sigma | 1073 | -90.0 | 0.22 | 12.1 | -0.94 | 90.1 | -3.5 | 0 | no |
| 3 VWAP fade | Free close | band_k=2.5, exit=vwap | 1212 | -90.0 | 0.26 | 10.2 | -0.83 | 90.1 | -3.4 | 0 | no |
| 4 BB+RSI | Standard | adx_max=15, rsi_lo=30 | 59 | -9.8 | 0.33 | 32.2 | -0.70 | 10.4 | -4.3 | 52 | no |
| 4 BB+RSI | 50% off close | adx_max=15, rsi_lo=30 | 59 | -7.7 | 0.38 | 35.6 | -0.54 | 8.4 | -3.8 | 61 | no |
| 4 BB+RSI | Free close | adx_max=15, rsi_lo=30 | 59 | -5.6 | 0.48 | 39.0 | -0.40 | 6.6 | -3.0 | 57 | no |
| 5 EMA pullback | Standard | stop_pct=1.5, ratio=2.0 | 476 | -7.7 | 0.90 | 33.8 | -0.07 | 14.2 | -1.1 | 68 | no |
| 5 EMA pullback | 50% off close | stop_pct=1.5, ratio=1.0 | 9571 | -78.0 | 0.36 | 28.0 | -0.07 | 78.1 | -33.7 | 35 | no |
| 5 EMA pullback | Free close | stop_pct=1.5, ratio=0.8 | 9575 | -66.7 | 0.47 | 32.3 | -0.05 | 66.8 | -25.5 | 28 | no |
| 6 SMC sweep+FVG | Standard | rr=1.0, window=any | 123 | -6.2 | 0.67 | 52.0 | -0.21 | 7.6 | -2.3 | 68 | no |
| 6 SMC sweep+FVG | 50% off close | rr=1.0, window=any | 125 | -7.4 | 0.41 | 35.2 | -0.25 | 7.7 | -4.4 | 23 | no |
| 6 SMC sweep+FVG | Free close | rr=1.0, window=any | 125 | -4.7 | 0.57 | 43.2 | -0.15 | 5.0 | -2.9 | 25 | no |
| 7 Intraday momentum | Standard | anchor=utc, min_move_pct=0.3 | 111 | -16.3 | 0.18 | 27.0 | -0.65 | 16.7 | -6.3 | 47 | no |
| 7 Intraday momentum | 50% off close | anchor=utc, min_move_pct=0.3 | 111 | -13.5 | 0.24 | 28.8 | -0.53 | 13.9 | -5.4 | 34 | no |
| 7 Intraday momentum | Free close | anchor=utc, min_move_pct=0.3 | 111 | -10.2 | 0.34 | 34.2 | -0.39 | 10.8 | -4.3 | 38 | no |

VWAP fade hit the 10% ruin halt on both symbols in every scenario, so its −90% is where trading stopped.

### 5.2 PASS checklist (OOS)

Every strategy fails the profit-factor, BTC-positive, ETH-positive and random-baseline tests in all three fee scenarios. Trade count is the only test most of them meet; Bollinger + RSI fails that too (59 OOS trades).

| Strategy | Scenarios | PF ≥ 1.2 | Enough trades | BTC net > 0 | ETH net > 0 | > 95th pct random |
|---|---|---|---|---|---|---|
| 1 ORB | all 3 | ✗ | ✓ | ✗ | ✗ | ✗ |
| 2 Asia→London | all 3 | ✗ | ✓ | ✗ | ✗ | ✗ |
| 3 VWAP fade | all 3 | ✗ | ✓ | ✗ | ✗ | ✗ |
| 4 BB+RSI | all 3 | ✗ | ✗ (59) | ✗ | ✗ | ✗ |
| 5 EMA pullback | all 3 | ✗ | ✓ | ✗ | ✗ | ✗ |
| 6 SMC sweep+FVG | all 3 | ✗ | ✓ | ✗ | ✗ | ✗ |
| 7 Intraday momentum | all 3 | ✗ | ✓ (low sample) | ✗ | ✗ | ✗ |

### 5.3 OOS net % by symbol

| Strategy | BTC standard | ETH standard | BTC free close | ETH free close |
|---|---|---|---|---|
| 1 ORB | -38.5 | -32.5 | -27.0 | -21.2 |
| 2 Asia→London | -12.8 | -3.3 | -7.0 | -6.8 |
| 3 VWAP fade | -90.0 | -90.0 | -90.0 | -90.0 |
| 4 BB+RSI | -11.6 | -8.0 | -7.4 | -3.9 |
| 5 EMA pullback | -4.0 | -11.3 | -62.4 | -71.1 |
| 6 SMC sweep+FVG | -5.7 | -6.7 | -4.2 | -5.2 |
| 7 Intraday momentum | -16.2 | -16.5 | -9.7 | -10.7 |

### 5.4 Where the money goes: edge before and after costs (OOS, combined)

"Gross move" is measured after slippage and before fees.

| Strategy | Scenario | Avg gross move % / trade | Fees % of notional / trade | Gross R / trade | Fees R / trade | Net R / trade | Avg hold (min) |
|---|---|---|---|---|---|---|---|
| 1 ORB | Standard | -0.024 | 0.115 | -0.054 | 0.191 | -0.245 | 28 |
| 1 ORB | Free close | -0.029 | 0.059 | -0.057 | 0.097 | -0.154 | 28 |
| 2 Asia→London | Standard | +0.042 | 0.105 | +0.013 | 0.094 | -0.082 | 448 |
| 2 Asia→London | Free close | +0.002 | 0.059 | -0.014 | 0.054 | -0.068 | 29 |
| 3 VWAP fade | Standard | -0.260 | 0.080 | -0.657 | 0.423 | -1.080 | 4 |
| 3 VWAP fade | Free close | -0.307 | 0.024 | -0.711 | 0.117 | -0.828 | 4 |
| 4 BB+RSI | Standard | -0.023 | 0.109 | -0.097 | 0.604 | -0.702 | 21 |
| 4 BB+RSI | Free close | -0.015 | 0.059 | -0.067 | 0.328 | -0.396 | 17 |
| 5 EMA pullback | Standard | +0.006 | 0.106 | +0.004 | 0.071 | -0.066 | 1,376 |
| 5 EMA pullback | Free close | -0.022 | 0.059 | -0.014 | 0.039 | -0.054 | 29 |
| 6 SMC sweep+FVG | Standard | +0.022 | 0.064 | +0.023 | 0.231 | -0.208 | 107 |
| 6 SMC sweep+FVG | Free close | -0.010 | 0.024 | -0.069 | 0.084 | -0.153 | 24 |
| 7 Intraday momentum | Standard | -0.042 | 0.118 | -0.110 | 0.538 | -0.648 | 25 |
| 7 Intraday momentum | Free close | -0.045 | 0.059 | -0.122 | 0.269 | -0.391 | 24 |

How to read this:
- **No strategy has a real gross edge.** Four of seven are negative before fees even in the standard scenario.
- **The positive ones are too small.** The best gross results (Asia→London +0.042%, SMC +0.022%) are a fraction of even the free-close cost.
- **The free close trades cost for edge.** It roughly halves fees, but the forced 29-minute exit removes the few trades that ran in the strategy's favour, so the gross figure goes from slightly positive to slightly negative.

### 5.5 Stress test: 0.03% slippage per side (OOS combined)

| Strategy | Standard PF | Standard net % | 50% off PF | 50% off net % | Free close PF | Free close net % |
|---|---|---|---|---|---|---|
| 1 ORB | 0.24 | -41.0 | 0.28 | -36.4 | 0.34 | -31.1 |
| 2 Asia→London | 0.77 | -9.8 | 0.33 | -12.5 | 0.39 | -10.2 |
| 3 VWAP fade | 0.18 | -90.0 | 0.21 | -90.0 | 0.23 | -90.0 |
| 4 BB+RSI | 0.27 | -11.4 | 0.28 | -9.7 | 0.36 | -7.7 |
| 5 EMA pullback | 0.88 | -9.6 | 0.26 | -83.9 | 0.33 | -80.4 |
| 6 SMC sweep+FVG | 0.64 | -7.2 | 0.35 | -9.0 | 0.47 | -6.3 |
| 7 Intraday momentum | 0.11 | -20.5 | 0.15 | -17.8 | 0.21 | -14.7 |

### 5.6 Random-entry baseline (OOS, combined net R, 200 runs)

| Strategy | Scenario | Strategy net R | Random 5th pct | Random median | Random 95th pct | Percentile |
|---|---|---|---|---|---|---|
| 1 ORB | Standard | -181.9 | -187.3 | -161.8 | -138.3 | 9 |
| 1 ORB | Free close | -114.8 | -115.3 | -94.7 | -70.5 | 6 |
| 2 Asia→London | Standard | -35.3 | -75.5 | -46.2 | -11.4 | 71 |
| 2 Asia→London | Free close | -29.1 | -42.6 | -30.9 | -21.4 | 58 |
| 3 VWAP fade | Standard | -1,014.3 | -481.9 | -425.1 | -368.2 | 0 |
| 3 VWAP fade | Free close | -1,004.1 | -237.7 | -183.5 | -122.4 | 0 |
| 4 BB+RSI | Standard | -41.4 | -56.7 | -42.2 | -29.3 | 52 |
| 4 BB+RSI | Free close | -23.4 | -36.7 | -24.4 | -12.0 | 57 |
| 5 EMA pullback | Standard | -31.4 | -90.9 | -42.1 | 3.7 | 68 |
| 5 EMA pullback | Free close | -515.3 | -538.8 | -504.4 | -467.8 | 28 |
| 6 SMC sweep+FVG | Standard | -25.6 | -50.9 | -31.1 | -15.2 | 68 |
| 6 SMC sweep+FVG | Free close | -19.1 | -26.7 | -13.8 | -2.8 | 25 |
| 7 Intraday momentum | Standard | -71.9 | -89.1 | -71.0 | -47.8 | 47 |
| 7 Intraday momentum | Free close | -43.4 | -59.7 | -38.7 | -15.9 | 38 |

The 50%-off rows are in `logs/random_baseline.csv` and tell the same story.

- **Most strategies are indistinguishable from random.** They sit between the 6th and 71st percentiles: no better than random entries with the same stops and costs.
- **VWAP fade is far worse than random.** Its limit orders fill exactly when price is running through the band, which a random entry at the bar open does not suffer. This is adverse selection, and it is the main finding for that strategy.

### 5.7 Quarterly net R (standard fees, BTC+ETH, selected variant)

| Strategy | 24Q4 | 25Q1 | 25Q2 | 25Q3 | 25Q4 | 26Q1 | 26Q2 | 26Q3 | 26Q4 |
|---|---|---|---|---|---|---|---|---|---|
| 1 ORB | -13.6 | -31.1 | -50.1 | -58.0 | -26.6 | -59.1 | -52.1 | -79.7 | -47.4 |
| 2 Asia→London | +2.2 | +12.9 | -22.3 | -10.5 | -15.4 | +7.6 | -27.1 | +1.5 | -8.9 |
| 3 VWAP fade | -1,011.6 | halted | halted | halted | halted | -184.9 | -829.5 | halted | halted |
| 4 BB+RSI | -6.8 | -20.7 | -20.9 | -11.5 | -5.7 | -17.0 | -2.4 | -24.1 | -12.4 |
| 5 EMA pullback | -15.8 | -99.0 | -40.1 | -15.8 | -11.3 | +12.8 | -16.5 | -26.0 | +9.7 |
| 6 SMC sweep+FVG | -2.3 | -15.7 | -15.3 | -13.4 | -7.6 | +4.1 | -3.4 | -14.5 | -9.6 |
| 7 Intraday momentum | -17.0 | -22.7 | -38.7 | -27.3 | -19.0 | -27.1 | -18.7 | -30.1 | -23.2 |

- **No regime helps.** ORB, BB+RSI and intraday momentum lost in every quarter, rallies (25Q2, 26Q3) and crashes (25Q1, 26Q1) alike.
- **The few positive quarters don't line up.** Asia→London, EMA pullback and SMC had 2 to 4 positive quarters each, with no clear link to rising or falling markets.
- **VWAP fade:** "halted" means the ruin halt stopped trading in that run (the IS run in Dec 2024, the OOS run in 2026Q2).

Per-symbol quarters for every scenario are in `logs/quarterly.csv`.

### 5.8 Variant log and a hindsight check

Profit factor across every variant (combined BTC+ETH; no variant reached 1.0 in-sample):

| Strategy | Variants | Best IS PF (standard) | Best IS PF (free close) | Variants with OOS PF > 1 (any scenario) |
|---|---|---|---|---|
| 1 ORB | 25 | 0.43 | 0.61 | 0 |
| 2 Asia→London | 15 | 0.93 | 0.62 | 0 |
| 3 VWAP fade | 10 | 0.22 | 0.29 | 0 |
| 4 BB+RSI | 15 | 0.52 | 0.68 | 0 |
| 5 EMA pullback | 25 | 0.84 | 0.60 | 0 |
| 6 SMC sweep+FVG | 10 | 0.99 | 0.87 | 2 |
| 7 Intraday momentum | 8 | 0.38 | 0.58 | 0 |

- **Even cherry-picking wouldn't produce a pass.** Choosing variants by their OOS results (`logs/hindsight_best_oos.csv`) still gives none that passes.
- **The only OOS profit factors above 1 are noise.** Both are SMC "Silver Bullet" variants: PF 1.18 on 31 trades (+1.2%) and PF 1.08 on 18 trades (+0.1%). Both had in-sample PF below 1, and both samples are far too small to mean anything.

### 5.9 Sensitivity checks on fixed choices

These are outside the protocol and not used for selection; full numbers are in `logs/sensitivity_checks.csv`.

| Check | Settings tried | Result |
|---|---|---|
| VWAP fade warm-up after the 00:00 UTC anchor | 60 (used), 240, 480 minutes | Gross R stays between −0.53 and −0.82 per trade; PF 0.10–0.32. Not caused by narrow early-session bands |
| SMC swing length | 3, 5 (used), 10 bars | Gross R −0.05 to −0.17 per trade; PF 0.42–0.75. No setting has an edge |

## 6. Top strategies: none qualifies

No strategy earned a recommendation, so there are no executable rules to hand over for live trading, and my suggested risk per trade is zero.

If you want to keep researching, these two came closest. Both had a slightly positive gross edge in the standard-fee scenario and lost the least:

**Asia range to London breakout** (`strategies/asia_london.py`): OOS PF 0.81, −8.1%; IS PF 0.93, −5.1%.
- Range: high and low of 00:00–07:00 UTC.
- Entry: first 15-minute candle closing outside the range between 07:00 and 16:00 UTC; market entry at the next minute.
- Stop: 1.0 × range height from entry. Target: 1.0 × range height. Otherwise exit at 00:00 UTC.
- Why it failed: gross edge of +0.013R to +0.045R per trade against about 0.08R to 0.09R in fees.

**EMA pullback continuation** (`strategies/ema_pullback.py`): OOS PF 0.90, −7.7%; IS PF 0.84, −32.6%.
- Trend: 1h EMA21 above EMA50 means longs only; below means shorts only.
- Entry: a 5m bar touches the 5m EMA21 and closes back on the trend side; market entry at the next minute.
- Stop: 1.5%. Target: 3.0%. No time stop.
- Why it failed: gross edge of about zero.

Neither is a scalp: they hold for about 7.5 and 23 hours on average. Neither should be traded without a new edge being found and confirmed out-of-sample.

## 7. What didn't work and why

- **1 ORB:** breakouts of the 00:00 UTC and US-open ranges did not follow through on 1m data. Gross was slightly negative (−0.02R in-sample, −0.05R out-of-sample); 86% to 88% of trades ended on the 30-minute time stop with small moves that fees then turned into losses. It lost in every quarter.
- **2 Asia→London:** the closest to break-even. The tiny gross edge (+0.04% per trade) was about 40% of the fees. Forcing a 29-minute exit for the free close removed it entirely.
- **3 VWAP fade:** the worst result, and an important one. Limit orders at the bands fill when price is moving through them, and price then kept going. In a sample of 1.5σ band touches, the median 30-minute move was 0.82σ further away versus 0.18σ back toward VWAP. The selected variant (2.5σ entry, so the 3σ stop is only 0.5σ away) was stopped out on 85% to 86% of trades. Cheaper fees cannot fix a gross loss of −0.66R per trade. "Fading the band" on 1m BTC/ETH is trading against short-term momentum.
- **4 BB+RSI:** with the ADX < 15 filter it fired only about 60 times in 8 months. Its stop (1.5 × 5m ATR, about 0.2%) is so tight that fees cost about 0.6R per trade. Without the filter, more trades simply meant more losses (best IS PF across all filters: 0.52).
- **5 EMA pullback:** about zero gross edge with wide stops. The tight-stop and offer versions traded about 10,000 times in 8 months and lost 67% to 78%.
- **6 SMC sweep + FVG:** coded without lookahead (swings only usable once confirmed), it had no edge: gross −0.04R in-sample, +0.02R OOS. The 1-tick stop beyond the sweep makes fees about 0.2R per trade. The Silver Bullet window and different swing lengths did not help.
- **7 Intraday momentum:** the first-half-hour signal from the academic paper did not predict the last half-hour on Delta in 2024–2026. Gross results were negative in all 8 variants, in-sample and out-of-sample, at both anchors (00:00 UTC and the US session): −0.04R to −0.23R per trade.

The common thread across all seven: at 1–30 minute horizons the strategies' entries are no better than random, and the costs (0.08%–0.14% per round trip at market, 0.02%–0.05% with limit orders) are bigger than the typical move being captured.

## 8. What to try next

1. **Find a gross edge before thinking about fees.** Every test above fails before costs. A useful next step is screening signals for gross R and win rate with zero costs, and only engineering execution for candidates that clear about +0.15R gross per trade.
2. **Hold for days, not minutes.** The earlier 4-hour test in this project (50/200 EMA cross) was the only thing that made money after costs, on about 10 trades a year per coin. That is thin evidence, but fees there are a small fraction of the move. Re-test it with this engine and a proper IS/OOS split.
3. **Use maker-only execution, with realistic fill modelling.** The VWAP result shows that resting limits suffer adverse selection; a candle backtest cannot see queue position. A fair test needs Delta's tick/order-book data (Delta sells historical tick data; the public WebSocket `ob_l2`/`trades` feeds can be recorded going forward).
4. **Paper-trade before any live capital.** Delta has a testnet: `wss://socket-ind-pub.testnet.deltaex.org` for public data and `wss://socket-ind.testnet.deltaex.org` for private.
5. **Don't build a strategy around the Scalper Offer.** It can be withdrawn without notice, and in this test it never turned a loser into a winner.

## 9. Assumptions

| # | Assumption | Effect if wrong |
|---|---|---|
| 1 | Stop-loss closes qualify for the Scalper Offer; no GST on a waived fee | Offer results slightly too optimistic |
| 2 | Funding realised at settlement T equals the published rate in the hour before T (rates only change at 00/08/16 UTC, which supports this) | Negligible: funding averaged under 0.001R per trade for every strategy (largest single trade 0.14R) |
| 3 | Slippage 0.01% per side on market orders and stops (0.03% stress); none on limit fills | Real slippage on small BTC/ETH orders is probably lower; even zero slippage would not lift any PF to 1.2 (gross edges are ≤ +0.05R) |
| 4 | Limit fills need 1 tick of trade-through; queue position not modelled | Fills could be fewer (worse for maker strategies) or slightly more |
| 5 | Take-profit orders are resting limits (maker fee) | Taker take-profits would make results worse |
| 6 | Trade counts for the PASS bar are BTC+ETH combined | Per-symbol counts are lower; no strategy was near passing either way |
| 7 | ORB: 120-minute breakout window; US anchor on weekdays only | Fixed, not tuned |
| 8 | Asia→London: no new entries after 16:00 UTC | Fixed, not tuned |
| 9 | VWAP fade: 60-minute warm-up after 00:00 UTC; stop fixed at the 3σ level at entry | Warm-up checked in §5.9 |
| 10 | EMA pullback: trend = 1h EMA21 vs EMA50; the source script's MACD/RSI/ADX filters dropped (exact values unknown) | Could matter; the source's claims used 0.02% commission |
| 11 | SMC: 5-bar swings, sweep-to-shift within 12 bars, 60-minute limit validity, 1-tick stop buffer | Swing length checked in §5.9 |
| 12 | Intraday momentum: 1.5 × 5m ATR hard stop added (the paper has none) | Stops hit on 26% to 30% of trades; gross results were negative in every variant |
| 13 | $1,000 starting equity per symbol, positions rounded down to whole contracts | Small accounts round more; no effect on R metrics |
| 14 | Trading halts at 10% of starting equity | Only VWAP fade affected |

## 10. Limitations

- **Candle data only.** Intrabar order is unknown, which is why the stop-first rule is used. No order book, queue position or partial fills.
- **The random baseline enters at the bar open.** For limit-entry strategies (VWAP fade, SMC) it doesn't reproduce their fill selection, which makes random look somewhat better than a true random limit strategy would.
- **Two years, two coins, one exchange.** Strategies that failed here could behave differently in other periods, but the failure was consistent across all nine quarters and both coins.
- **The offer scenarios change the strategies.** The 29-minute cap makes the Asia→London and EMA-pullback offer versions different strategies from their standard versions.

## 11. Reproduce

```bash
pip install -r requirements.txt
```

```bash
python3 -m pytest -q tests
```

```bash
python3 backtest_runner.py
```

The full run takes about 90 seconds on 4 cores. Add `--download` to refresh the data from Delta first.

**Outputs:**
- `results.csv`: every selected variant, by scenario, period (IS, OOS, OOS stress) and symbol, with all metrics.
- `logs/variants_log.csv`: all 108 variants.
- `logs/random_baseline.csv`, `logs/quarterly.csv`, `logs/hindsight_best_oos.csv`, `logs/sensitivity_checks.csv`.
- `logs/trades/`: every trade of every selected variant.
- `charts/<strategy>.png`: IS and OOS equity curves.

## Appendix: in-sample vs out-of-sample detail (combined BTC+ETH, $1,000 per symbol)

### Standard fees

| Strategy | Period | Trades | Net $ (on $2,000) | Net % | Win % | Avg win $ | Avg loss $ | Avg win R | Avg loss R | Expectancy R | Expectancy % equity | Profit factor | Max DD % | Sharpe | Sortino | Avg hold (min) | Longest losing streak | Gross R/trade | Fees R/trade |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 ORB | IS | 1,458 | -850 | -42.5 | 32.9 | 1.36 | -1.54 | 0.37 | -0.42 | -0.162 | -0.077 | 0.43 | 42.9 | -9.21 | -9.22 | 28 | 14 | -0.017 | 0.144 |
| 1 ORB | OOS | 743 | -711 | -35.5 | 29.5 | 1.46 | -1.97 | 0.37 | -0.50 | -0.245 | -0.118 | 0.31 | 35.5 | -12.08 | -10.96 | 28 | 21 | -0.054 | 0.191 |
| 2 Asia→London | IS | 833 | -101 | -5.1 | 49.1 | 3.52 | -3.63 | 0.79 | -0.82 | -0.030 | -0.012 | 0.93 | 13.4 | -0.65 | -0.88 | 461 | 10 | 0.045 | 0.075 |
| 2 Asia→London | OOS | 431 | -161 | -8.1 | 46.4 | 3.41 | -3.65 | 0.77 | -0.82 | -0.082 | -0.039 | 0.81 | 9.4 | -1.98 | -2.51 | 448 | 11 | 0.013 | 0.094 |
| 3 VWAP fade | IS | 1,052 | -1,801 | -90.0 | 13.3 | 3.60 | -2.53 | 1.47 | -1.33 | -0.962 | -0.436 | 0.22 | 90.0 | -2.75 | -2.72 | 5 | 149 | -0.649 | 0.312 |
| 3 VWAP fade | OOS | 939 | -1,800 | -90.0 | 12.1 | 3.82 | -2.71 | 1.56 | -1.45 | -1.080 | -0.488 | 0.19 | 90.1 | -3.32 | -3.27 | 4 | 276 | -0.657 | 0.423 |
| 4 BB+RSI | IS | 122 | -354 | -17.7 | 36.1 | 3.95 | -6.76 | 0.90 | -1.53 | -0.657 | -0.321 | 0.33 | 18.2 | -3.64 | -3.81 | 23 | 12 | -0.051 | 0.605 |
| 4 BB+RSI | OOS | 59 | -196 | -9.8 | 32.2 | 5.08 | -7.31 | 1.06 | -1.54 | -0.702 | -0.348 | 0.33 | 10.4 | -4.25 | -4.52 | 21 | 8 | -0.097 | 0.604 |
| 5 EMA pullback | IS | 1,603 | -651 | -32.6 | 32.4 | 6.39 | -3.66 | 1.94 | -1.09 | -0.106 | -0.048 | 0.84 | 35.0 | -2.14 | -2.93 | 780 | 18 | -0.035 | 0.071 |
| 5 EMA pullback | OOS | 476 | -153 | -7.7 | 33.8 | 8.45 | -4.81 | 1.94 | -1.09 | -0.066 | -0.032 | 0.90 | 14.2 | -1.06 | -1.57 | 1,376 | 12 | 0.004 | 0.071 |
| 6 SMC sweep+FVG | IS | 232 | -236 | -11.8 | 48.7 | 3.91 | -5.69 | 0.87 | -1.26 | -0.224 | -0.109 | 0.65 | 13.2 | -2.63 | -3.09 | 93 | 9 | -0.040 | 0.183 |
| 6 SMC sweep+FVG | OOS | 123 | -124 | -6.2 | 52.0 | 4.03 | -6.48 | 0.84 | -1.34 | -0.208 | -0.103 | 0.67 | 7.6 | -2.35 | -2.75 | 107 | 9 | 0.023 | 0.231 |
| 7 Intraday momentum | IS | 310 | -619 | -31.0 | 28.1 | 1.98 | -3.55 | 0.49 | -0.87 | -0.490 | -0.241 | 0.22 | 31.0 | -6.98 | -6.86 | 26 | 15 | -0.121 | 0.369 |
| 7 Intraday momentum | OOS | 111 | -327 | -16.3 | 27.0 | 2.40 | -4.92 | 0.51 | -1.08 | -0.648 | -0.320 | 0.18 | 16.7 | -6.26 | -6.21 | 25 | 17 | -0.110 | 0.538 |

### Free close (Scalper Offer, 29-minute time stop)

| Strategy | Period | Trades | Net $ (on $2,000) | Net % | Win % | Avg win $ | Avg loss $ | Avg win R | Avg loss R | Expectancy R | Expectancy % equity | Profit factor | Max DD % | Sharpe | Sortino | Avg hold (min) | Longest losing streak | Gross R/trade | Fees R/trade |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 ORB | IS | 1,464 | -542 | -27.1 | 36.6 | 1.58 | -1.50 | 0.39 | -0.37 | -0.089 | -0.043 | 0.61 | 27.4 | -4.84 | -6.22 | 28 | 14 | -0.015 | 0.074 |
| 1 ORB | OOS | 744 | -482 | -24.1 | 33.7 | 1.61 | -1.80 | 0.37 | -0.42 | -0.154 | -0.074 | 0.46 | 24.5 | -7.27 | -8.39 | 28 | 20 | -0.057 | 0.097 |
| 2 Asia→London | IS | 833 | -182 | -9.1 | 33.6 | 1.02 | -0.85 | 0.24 | -0.20 | -0.050 | -0.023 | 0.61 | 9.1 | -3.79 | -5.24 | 29 | 18 | -0.008 | 0.043 |
| 2 Asia→London | OOS | 431 | -137 | -6.9 | 31.8 | 1.10 | -0.98 | 0.25 | -0.21 | -0.068 | -0.033 | 0.52 | 7.3 | -5.24 | -6.62 | 29 | 20 | -0.014 | 0.054 |
| 3 VWAP fade | IS | 1,344 | -1,801 | -90.0 | 12.7 | 4.21 | -2.15 | 1.87 | -1.13 | -0.752 | -0.341 | 0.29 | 90.1 | -3.00 | -2.97 | 5 | 149 | -0.645 | 0.107 |
| 3 VWAP fade | OOS | 1,212 | -1,800 | -90.0 | 10.2 | 5.00 | -2.22 | 1.97 | -1.15 | -0.828 | -0.378 | 0.26 | 90.1 | -3.43 | -3.37 | 4 | 278 | -0.711 | 0.117 |
| 4 BB+RSI | IS | 122 | -190 | -9.5 | 41.8 | 3.59 | -5.26 | 0.78 | -1.13 | -0.333 | -0.164 | 0.49 | 10.2 | -2.50 | -2.81 | 18 | 12 | -0.002 | 0.331 |
| 4 BB+RSI | OOS | 59 | -113 | -5.6 | 39.0 | 4.56 | -6.05 | 0.94 | -1.25 | -0.396 | -0.196 | 0.48 | 6.6 | -3.00 | -3.47 | 17 | 8 | -0.067 | 0.328 |
| 5 EMA pullback | IS | 16,053 | -1,659 | -83.0 | 37.4 | 0.38 | -0.40 | 0.20 | -0.20 | -0.053 | -0.022 | 0.58 | 83.0 | -15.65 | -12.58 | 28 | 20 | -0.014 | 0.039 |
| 5 EMA pullback | OOS | 9,575 | -1,334 | -66.7 | 32.3 | 0.38 | -0.39 | 0.15 | -0.15 | -0.054 | -0.023 | 0.47 | 66.8 | -25.45 | -15.40 | 29 | 28 | -0.014 | 0.039 |
| 6 SMC sweep+FVG | IS | 234 | -168 | -8.4 | 41.5 | 2.32 | -2.88 | 0.50 | -0.62 | -0.156 | -0.075 | 0.57 | 8.8 | -3.12 | -3.60 | 24 | 12 | -0.090 | 0.066 |
| 6 SMC sweep+FVG | OOS | 125 | -93 | -4.7 | 43.2 | 2.25 | -3.02 | 0.47 | -0.62 | -0.153 | -0.076 | 0.57 | 5.0 | -2.95 | -3.50 | 24 | 7 | -0.069 | 0.084 |
| 7 Intraday momentum | IS | 310 | -411 | -20.5 | 34.2 | 2.45 | -3.29 | 0.57 | -0.75 | -0.302 | -0.149 | 0.39 | 20.6 | -4.95 | -5.37 | 25 | 11 | -0.118 | 0.184 |
| 7 Intraday momentum | OOS | 111 | -205 | -10.2 | 34.2 | 2.76 | -4.24 | 0.57 | -0.89 | -0.391 | -0.193 | 0.34 | 10.8 | -4.34 | -4.74 | 24 | 14 | -0.122 | 0.269 |

### 50% off the close (hypothetical, 29-minute time stop)

| Strategy | Period | Trades | Net $ (on $2,000) | Net % | Win % | Avg win $ | Avg loss $ | Avg win R | Avg loss R | Expectancy R | Expectancy % equity | Profit factor | Max DD % | Sharpe | Sortino | Avg hold (min) | Longest losing streak | Gross R/trade | Fees R/trade |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 ORB | IS | 1,460 | -708 | -35.4 | 33.7 | 1.49 | -1.49 | 0.39 | -0.39 | -0.127 | -0.060 | 0.51 | 35.6 | -6.66 | -7.87 | 28 | 14 | -0.016 | 0.111 |
| 1 ORB | OOS | 743 | -610 | -30.5 | 30.8 | 1.53 | -1.87 | 0.37 | -0.46 | -0.203 | -0.098 | 0.36 | 30.6 | -9.43 | -9.89 | 28 | 21 | -0.057 | 0.146 |
| 2 Asia→London | IS | 833 | -254 | -12.7 | 30.5 | 1.02 | -0.88 | 0.24 | -0.21 | -0.072 | -0.033 | 0.50 | 12.7 | -5.29 | -6.77 | 29 | 18 | -0.008 | 0.064 |
| 2 Asia→London | OOS | 431 | -188 | -9.4 | 28.1 | 1.13 | -1.05 | 0.26 | -0.23 | -0.094 | -0.046 | 0.42 | 9.9 | -7.10 | -8.20 | 29 | 27 | -0.014 | 0.080 |
| 3 VWAP fade | IS | 1,176 | -1,800 | -90.0 | 13.6 | 3.75 | -2.36 | 1.53 | -1.24 | -0.863 | -0.390 | 0.25 | 90.0 | -2.92 | -2.89 | 5 | 149 | -0.644 | 0.219 |
| 3 VWAP fade | OOS | 1,073 | -1,801 | -90.0 | 12.1 | 3.96 | -2.45 | 1.59 | -1.29 | -0.943 | -0.428 | 0.22 | 90.1 | -3.48 | -3.42 | 4 | 278 | -0.675 | 0.268 |
| 4 BB+RSI | IS | 122 | -267 | -13.4 | 39.3 | 3.26 | -5.73 | 0.73 | -1.26 | -0.481 | -0.236 | 0.37 | 13.8 | -3.21 | -3.43 | 18 | 12 | -0.002 | 0.479 |
| 4 BB+RSI | OOS | 59 | -154 | -7.7 | 35.6 | 4.41 | -6.48 | 0.92 | -1.35 | -0.544 | -0.270 | 0.38 | 8.4 | -3.82 | -4.16 | 17 | 8 | -0.067 | 0.476 |
| 5 EMA pullback | IS | 12,710 | -1,701 | -85.0 | 34.5 | 0.37 | -0.40 | 0.20 | -0.22 | -0.073 | -0.031 | 0.49 | 85.0 | -17.30 | -13.00 | 29 | 26 | -0.014 | 0.059 |
| 5 EMA pullback | OOS | 9,571 | -1,561 | -78.0 | 28.0 | 0.32 | -0.35 | 0.15 | -0.16 | -0.073 | -0.032 | 0.36 | 78.1 | -33.66 | -16.64 | 29 | 44 | -0.014 | 0.059 |
| 6 SMC sweep+FVG | IS | 234 | -243 | -12.1 | 38.5 | 2.18 | -3.05 | 0.48 | -0.67 | -0.229 | -0.111 | 0.45 | 12.5 | -4.30 | -4.68 | 24 | 12 | -0.090 | 0.139 |
| 6 SMC sweep+FVG | OOS | 125 | -148 | -7.4 | 35.2 | 2.36 | -3.10 | 0.50 | -0.65 | -0.246 | -0.122 | 0.41 | 7.7 | -4.39 | -4.83 | 24 | 12 | -0.069 | 0.177 |
| 7 Intraday momentum | IS | 310 | -517 | -25.9 | 32.6 | 2.11 | -3.50 | 0.50 | -0.83 | -0.394 | -0.194 | 0.29 | 25.9 | -6.17 | -6.34 | 25 | 15 | -0.118 | 0.277 |
| 7 Intraday momentum | OOS | 111 | -269 | -13.5 | 28.8 | 2.64 | -4.48 | 0.56 | -0.96 | -0.525 | -0.259 | 0.24 | 13.9 | -5.43 | -5.59 | 24 | 17 | -0.122 | 0.404 |

Per-symbol versions of every table are in `results.csv`.
