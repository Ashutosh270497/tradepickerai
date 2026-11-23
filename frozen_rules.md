# Phase 4 pre-registration: frozen rules for the 4h trend filter

Committed **before** any Phase 4 data was downloaded or any Phase 4 test was run. The git timestamp of this file is the proof.

- **Written:** 23 Nov 2026
- **Reference code:** `strategies/trend_ma_4h.py` (with `DEFAULT` parameters) and `core/engine.py` as of commit `816470c`. Phase 4 may add data-loading and reporting code only. The strategy logic and engine trade logic stay as they are, and to prove it, Phase 3's BTC/ETH default-parameter result will be reproduced exactly with the Phase 4 code.
- **No retuning of any kind.** No parameter, rule, cost, coin or period below will change after results are seen.

## 1. Trading rules (frozen)

| Item | Rule |
|---|---|
| Bars | 4h bars aligned to 00:00 UTC, built from 1h data (only complete 4h bars) |
| Signal | At each 4h close: **long** if close > SMA(200) of 4h closes; **short** if close < SMA(200); no signal if equal or SMA not yet available |
| Entry | When flat, at the first 4h close with a signal: **market order at the open of the next 1h bar** (the bar that starts at that 4h close), in the signal's direction |
| Hold | Time exit after **120 four-hour bars (20 days)**: market order at the open of the 1h bar 480 hours after entry |
| Hard stop | Stop distance = **2 × ATR(20) of daily bars** (Wilder-smoothed true range, daily bars aligned to 00:00 UTC, using the last completed daily bar at entry). Stop-market: an intrabar touch fills at the stop price minus slippage; a gap through the stop at a bar open fills at that open minus slippage. If the stop and a time exit fall on the same bar, the time exit at the open comes first |
| Re-entry | After any exit, a new trade opens at the next 4h close that has a signal (so a time exit on a 4h boundary rolls straight into a new trade in the current direction) |
| Sizing | Quantity = **0.5% of current equity / stop distance**; notional capped at **3 × equity**; rounded **down** to whole Delta contracts; trade skipped if below 1 contract |
| Fees | Delta taker fee **0.05% + 18% GST** per side on notional, entry and exit (all orders are market or stop-market). No Scalper Offer (holds exceed 30 minutes) |
| Slippage | **0.01% per side** on entries, time exits and stop fills |
| Funding | Charged at every settlement while a position is open: −direction × rate × quantity × price (positive rate: longs pay). Sources in section 3 |
| Starting equity | **$10,000 per coin**, separate account per coin, compounding within the coin |
| Ruin rule | Trading stops if equity falls to 10% of the starting balance (engine default; not expected to bind) |

## 2. Test sets (frozen)

### Part A: unseen coins

**Selection rule (applied before any data download):** every Delta India perpetual (`GET /v2/products`, `contract_type = perpetual_futures`, state live) whose Binance USD-M symbol (Delta symbol with `USD` replaced by `USDT`) has archive files at data.binance.vision for both **Dec 2021** (history from 2021 or earlier) and **Oct 2026** (still trading). BTC and ETH are excluded.

43 coins met that rule. **LITUSD is excluded before testing:** Delta's underlying is "Lighter", a different token from the Litentry token behind Binance's 2021 LITUSDT history (ticker reuse).

**Primary set: all remaining 42 coins.** This follows your instruction to use every coin that qualifies, rather than the 6–10 you guessed would qualify. The PASS decision uses the primary set only.

**Secondary breakdown (diagnostic only, not part of PASS):** the 10 most liquid coins on Delta by 24h USD turnover in this snapshot: SOLUSD, XRPUSD, ZECUSD, UNIUSD, BNBUSD, DOGEUSD, AAVEUSD, BCHUSD, LTCUSD, LINKUSD.

**Automatic data-quality exclusion (applied in code after download, before computing results):** a coin is dropped if its Binance 1h history has a gap longer than 7 days, or any single 1h close-to-close move above ±50% (a sign of a relisting or redenomination). Any exclusion will be reported with its reason.

**Period per coin:** its full Binance USD-M history, from the first archive month to the latest available bar. Trading starts once SMA(200) on 4h and the daily ATR(20) exist.

Delta specs snapshot (23 Nov 2026):

| # by Delta 24h turnover | Delta symbol | Binance symbol | Delta underlying | Contract size | Tick | Taker / maker | Delta funding interval | 24h turnover (USD) | Set |
|---|---|---|---|---|---|---|---|---|---|
| 1 | SOLUSD | SOLUSDT | Solana | 1 SOL | 0.0001 | 0.05% / 0.02% | 8h | 69,992,924 | primary, top-10 |
| 2 | XRPUSD | XRPUSDT | Ripple | 1 XRP | 0.0001 | 0.05% / 0.02% | 8h | 7,476,259 | primary, top-10 |
| 3 | ZECUSD | ZECUSDT | Zcash | 0.1 ZEC | 0.01 | 0.05% / 0.02% | 8h | 3,618,809 | primary, top-10 |
| 4 | UNIUSD | UNIUSDT | Uniswap | 1 UNI | 0.0001 | 0.05% / 0.02% | 8h | 2,962,386 | primary, top-10 |
| 5 | BNBUSD | BNBUSDT | BNB | 0.1 BNB | 0.001 | 0.05% / 0.02% | 8h | 2,197,217 | primary, top-10 |
| 6 | DOGEUSD | DOGEUSDT | Dogecoin | 100 DOGE | 1e-06 | 0.05% / 0.02% | 8h | 1,716,610 | primary, top-10 |
| 7 | AAVEUSD | AAVEUSDT | Aave | 1 AAVE | 0.001 | 0.05% / 0.02% | 8h | 1,213,572 | primary, top-10 |
| 8 | BCHUSD | BCHUSDT | Bitcoin Cash | 0.01 BCH | 0.01 | 0.05% / 0.02% | 8h | 952,589 | primary, top-10 |
| 9 | LTCUSD | LTCUSDT | Litecoin | 0.1 LTC | 0.01 | 0.05% / 0.02% | 8h | 748,691 | primary, top-10 |
| 10 | LINKUSD | LINKUSDT | Chainlink | 1 LINK | 0.001 | 0.05% / 0.02% | 8h | 636,406 | primary, top-10 |
| 11 | AVAXUSD | AVAXUSDT | Avalanche | 1 AVAX | 0.0001 | 0.05% / 0.02% | 8h | 565,912 | primary |
| 12 | XMRUSD | XMRUSDT | Monero | 0.01 XMR | 0.01 | 0.05% / 0.02% | 8h | 306,585 | primary |
| 13 | DOTUSD | DOTUSDT | Polkadot | 1 DOT | 0.001 | 0.05% / 0.02% | 8h | 302,321 | primary |
| 14 | NEARUSD | NEARUSDT | NEAR Protocol | 1 NEAR | 0.0001 | 0.05% / 0.02% | 8h | 278,697 | primary |
| 15 | ADAUSD | ADAUSDT | Cardano | 1 ADA | 1e-05 | 0.05% / 0.02% | 8h | 210,990 | primary |
| 16 | FILUSD | FILUSDT | Filecoin | 1 FIL | 0.0001 | 0.05% / 0.02% | 8h | 180,079 | primary |
| 17 | DASHUSD | DASHUSDT | Dash | 0.1 DASH | 0.01 | 0.05% / 0.02% | 8h | 99,616 | primary |
| 18 | ETCUSD | ETCUSDT | Ethereum Classic | 0.1 ETC | 0.001 | 0.05% / 0.02% | 8h | 54,712 | primary |
| 19 | TRXUSD | TRXUSDT | TRON | 1 TRX | 1e-05 | 0.05% / 0.02% | 8h | 48,130 | primary |
| 20 | ARUSD | ARUSDT | Arweave | 1 AR | 0.001 | 0.05% / 0.02% | 8h | 45,939 | primary |
| 21 | LITUSD | LITUSDT | Lighter | 10 LIT | 0.0001 | 0.05% / 0.02% | 4h | 45,758 | EXCLUDED (ticker reuse) |
| 22 | HBARUSD | HBARUSDT | Hedera | 1 HBAR | 1e-05 | 0.05% / 0.02% | 8h | 14,003 | primary |
| 23 | GTCUSD | GTCUSDT | Gitcoin | 100 GTC | 1e-05 | 0.05% / 0.02% | 4h | 8,196 | primary |
| 24 | 1000SHIBUSD | 1000SHIBUSDT | 1000SHIB | 1000 1000SHIB | 1e-06 | 0.05% / 0.02% | 8h | 7,079 | primary |
| 25 | RUNEUSD | RUNEUSDT | THORChain | 1 RUNE | 0.0001 | 0.05% / 0.02% | 8h | 4,873 | primary |
| 26 | RLCUSD | RLCUSDT | iExecRLC | 10 RLC | 0.0001 | 0.05% / 0.02% | 4h | 4,851 | primary |
| 27 | MANAUSD | MANAUSDT | Decentraland | 1 MANA | 0.0001 | 0.05% / 0.02% | 8h | 4,447 | primary |
| 28 | RSRUSD | RSRUSDT | Reserve Rights | 100 RSR | 1e-06 | 0.05% / 0.02% | 8h | 3,444 | primary |
| 29 | IOSTUSD | IOSTUSDT | IOST | 10000 IOST | 1e-07 | 0.05% / 0.02% | 4h | 3,319 | primary |
| 30 | XLMUSD | XLMUSDT | Stellar | 1 XLM | 1e-05 | 0.05% / 0.02% | 8h | 3,265 | primary |
| 31 | ENJUSD | ENJUSDT | Enjin Coin | 100 ENJ | 1e-05 | 0.05% / 0.02% | 4h | 2,811 | primary |
| 32 | DYDXUSD | DYDXUSDT | dYdX | 1 DYDX | 0.0001 | 0.05% / 0.02% | 8h | 2,726 | primary |
| 33 | GALAUSD | GALAUSDT | GALA | 100 GALA | 1e-06 | 0.05% / 0.02% | 8h | 2,504 | primary |
| 34 | KSMUSD | KSMUSDT | Kusama | 0.1 KSM | 0.001 | 0.05% / 0.02% | 8h | 2,183 | primary |
| 35 | AXSUSD | AXSUSDT | Axie Infinity | 10 AXS | 0.001 | 0.05% / 0.02% | 4h | 2,083 | primary |
| 36 | ZENUSD | ZENUSDT | Horizen | 1 ZEN | 0.001 | 0.05% / 0.02% | 8h | 1,989 | primary |
| 37 | PEOPLEUSD | PEOPLEUSDT | ConstitutionDAO | 100 PEOPLE | 1e-05 | 0.05% / 0.02% | 8h | 1,460 | primary |
| 38 | TLMUSD | TLMUSDT | Alien Worlds | 10000 TLM | 1e-06 | 0.05% / 0.02% | 4h | 1,110 | primary |
| 39 | MASKUSD | MASKUSDT | Mask Network | 1 MASK | 0.0001 | 0.05% / 0.02% | 4h | 1,090 | primary |
| 40 | TRBUSD | TRBUSDT | Tellor Tributes | 0.1 TRB | 0.001 | 0.05% / 0.02% | 4h | 994 | primary |
| 41 | SKLUSD | SKLUSDT | SKALE | 100 SKL | 1e-05 | 0.05% / 0.02% | 4h | 841 | primary |
| 42 | IOTAUSD | IOTAUSDT | IOTA | 1 IOTA | 1e-05 | 0.05% / 0.02% | 8h | 335 | primary |
| 43 | SUSHIUSD | SUSHIUSDT | Sushi | 1 SUSHI | 0.0001 | 0.05% / 0.02% | 8h | 294 | primary |

### Part B: unseen period

- **Data:** BTCUSDT and ETHUSDT **Binance spot** 1h candles (data.binance.vision spot archive), **Aug 2017 to Dec 2019** (data ends 2019-12-31 23:00 UTC; a position still open then is closed at the last close).
- **Fees and contracts:** Delta's BTCUSD/ETHUSD fees and contract sizes (0.001 BTC, 0.01 ETH).
- **Funding:** assumed **0.01% per 8h** at 00/08/16 UTC (no perpetual existed; flagged assumption).
- Missing hours in the spot data are filled as flat bars (no trading), and reported.

## 3. Funding for Part A (as in Phase 3)

- **Delta period:** Delta's actual settlement rates, from the cached `FUNDING:<symbol>` history (same download window as Phase 3, about 2 years). The rate realised at settlement T is the published value in the hour before T, at Delta's own interval for that coin (8h or 4h; see table). The published value is treated as the rate per settlement, as for BTC/ETH (flagged assumption).
- **Before the Delta period:** Binance's actual funding events (their own timestamps and intervals) **plus a per-coin gap**. The gap is the average of (Delta − Binance), with both rates converted to per-8h, over the overlap. It is applied scaled to each Binance event's interval.
- **If a coin has less than 90 days of Delta/Binance funding overlap:** the BTC/ETH average gap from Phase 3 (0.0034% per 8h) is used instead, and flagged.
- **If Binance funding is missing for a period** (e.g. the archive's current month): the last known rate is carried forward.

## 4. Pass criteria (fixed in advance)

- **Part A (unseen coins):** PASS only if **all three** hold for the primary set:
  1. net profit after all costs is positive on **at least 2/3 of the coins**;
  2. **pooled profit factor ≥ 1.2** (sum of all winning trades' net $ ÷ sum of all losing trades' net $, across every coin's account);
  3. the pooled result is **above the 95th percentile of a random-entry baseline**. The baseline is 200 runs per coin, with the same trade count, direction mix, stop distance, holding limit and costs, at random entry bars over the same history. Its pooled statistic is the sum of net R across coins, summed run by run.
- **Part B (pre-2020 BTC/ETH):** PASS only if net profit after all costs is **positive on both BTC and ETH**.
- **Overall:** **PASS only if Part A and Part B both pass.** Otherwise **FAIL**, stated plainly.

## 5. Diagnostics (reported, do not affect the verdict or the rules)

1. Long-only vs short-only split of net profit for every coin and period, from the same trades.
2. Risk scaling at **0.5%, 1% and 2%** risk per trade (all other rules unchanged):
   - CAGR and maximum drawdown (daily mark-to-market);
   - share of trades where the 3x leverage cap binds;
   - trades lost to Delta's minimum contract size, measured as trades with whole-contract rounding vs the same run with fractional contracts.
3. Minimum Delta account size per coin with no skipped trades, at each risk level:
   - for each trade, equity ≥ contract size × max(stop distance ÷ risk, entry price ÷ 3);
   - reported as the maximum over history and at the latest price and ATR.
