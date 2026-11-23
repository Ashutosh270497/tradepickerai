# Phase 0 and Phase 1 findings

Output of the earlier research session (same project, 23 Nov 2026), saved here so Phase 2 can build on it.
Phase 2 re-verified the platform facts; see `research_report.md` for the current, cited values.

## Phase 0: platform facts (Delta Exchange India, BTCUSD and ETHUSD perpetuals)

| Item | Value | Source |
|---|---|---|
| Taker / maker fee | 0.05% / 0.02% of notional, same for BTCUSD and ETHUSD | Delta API `GET /v2/products/{symbol}` (`taker_commission_rate`, `maker_commission_rate`) |
| GST | 18% on trading fees, so effectively 0.059% / 0.0236% per side | https://www.delta.exchange/fees |
| Scalper Offer | No closing fee if a BTC/ETH futures trade is opened and closed within 30 minutes (fee page says "up to 50% off") | User screenshot of the offer pop-up; fee page |
| Funding | Exchanged every 8 hours (00:00, 08:00, 16:00 UTC), mark-price method; typically 0.01% per 8h; observed range about −0.09% to +0.08% | API product specs (`rate_exchange_interval` = 28800), funding history `FUNDING:{symbol}` |
| Contract size | BTCUSD 0.001 BTC per lot; ETHUSD 0.01 ETH per lot; USD-settled | API `contract_value` |
| Tick size | BTCUSD $0.5; ETHUSD $0.05 | API `tick_size` |
| Max leverage | 200x (0.5% initial margin) up to $100,000 notional | API `default_leverage`, `initial_margin`, `max_leverage_notional` |
| Candle history | `GET /v2/history/candles`, max 2,000 candles per call, resolutions 1m to 1w; 1m data confirmed 800 days back | https://docs.delta.exchange/ |
| WebSocket | `wss://public-socket.india.delta.exchange`; `ob_l1`, `ob_l2`, `ob_updates`, `trades`, `candlesticks`, `funding_rate`; 150 connections per 5 min per IP | https://docs.delta.exchange/ |
| Rate limit | 20,000 weight per 5 minutes; candles weight 3; place order weight 5 | https://docs.delta.exchange/ |

Assumption: minimum order is 1 lot (not stated explicitly by the API).

### Breakeven per round trip (1 tick slippage per market-order side)

| Execution | BTC | ETH |
|---|---|---|
| (a) Taker in, taker out | 0.120% | 0.124% |
| (b) Maker in, taker out | 0.083% | 0.086% |
| (c) Maker in, maker out | 0.047% | 0.047% |
| Taker in, free close (Scalper Offer, ≤30 min) | 0.061% | 0.065% |
| Maker in, free close (Scalper Offer, ≤30 min) | 0.024% | 0.027% |

## Phase 1: research summary

- No source had a verifiable live record; the only fee-inclusive "profitable" claims used fees well below Delta's or a bull-market window.
- Every mechanical, fee-inclusive SMC/ICT test found (index futures, gold, forex; none on crypto) lost or broke even, mainly because small stops make costs a large share of each trade.
- VWAP-band and Bollinger targets on 1–5m bars are about the size of taker costs; one paper (arXiv 2608.21888) reports short-horizon reversal does not clear even maker costs.
- Order-book and quarter-hour effects are real but about 0.05–0.6 bp per trade, 20–100× below costs.
- One pre-registered crypto test (Simple Markets) found opening-range breakouts positive before costs but about 2.5× smaller than costs.

Most figures came from search summaries because many source sites were blocked in that session; treat them as leads.

## Shortlist (7 strategies, default rules)

| # | Strategy | Default rules | Why shortlisted |
|---|---|---|---|
| 1 | Opening-range breakout | 15-minute range after 00:00 UTC and after the US open; enter on a break; stop at the opposite side; exit at 2R or a 30-minute time stop | Real gross edge reported; Scalper Offer roughly halves the cost that killed it |
| 2 | Asia range to London breakout | Range 00:00–07:00 UTC; enter on a 15m close outside; stop = range, target = 2× range; exit at end of day | Wide stops keep costs under about 0.15R; holds for hours (a control, not a scalp) |
| 3 | VWAP ±2σ band fade | Session VWAP from 00:00 UTC; limit entry at the band; exit at VWAP; 30-minute time stop | Only plausible with maker entry plus free close |
| 4 | Bollinger + RSI reversion with range filter | 5m: close below lower band (20, 2) and RSI(14) under 30, ADX under 20; exit at mid band or after 45 minutes; short is the mirror | Most common published scalp |
| 5 | EMA pullback continuation | 5m entries in the 1h trend direction after a pullback to the 21 EMA; stop 1.1%, target 1.35% | Costs are about 10% of the target; holds run to hours |
| 6 | SMC: sweep, structure shift, FVG entry | 5m with 1h bias: sweep of a prior swing or session extreme, displacement breaking the opposing swing and leaving a gap, limit entry at the gap midpoint, stop beyond the sweep, 2R target; plus the "Silver Bullet" time-window variant | User's stated interest; swings coded without look-ahead |
| 7 | Intraday momentum | Sign of the first 30 minutes of the day decides a 30-minute trade at the end of the day; one trade a day | Peer-reviewed (Shen, Urquhart, Wang 2022); low trade count; fits the 30-minute fee waiver |

Left out: order-flow/CVD scalps (need tick and book history; edges far below fees), grid and averaging-down bots (hidden tail risk), Freqtrade scalps with 1% targets against 4–5% stops, funding-rate signals (24-hour holds).
