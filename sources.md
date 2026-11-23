# Sources

## Evidence tags

| Tag | Meaning |
|---|---|
| **[official]** | Delta Exchange's own API, documentation or help centre |
| **[code+fee backtest]** | Reproducible code with a fee-inclusive backtest |
| **[paper]** | Peer-reviewed article or working paper |
| **[rules]** | Rules detailed enough to replicate, no trustworthy results |
| **[anecdote]** | Claims, screenshots, vendor or forum posts |

**How each source was accessed:**
- **(read):** I opened the page in this project.
- **(snippet):** only a search summary was seen, because the host was blocked in the research session. Treat those figures as leads, not facts.

No source in this research had a verifiable live track record.

## Platform facts (Phase 0 and Phase 2 verification)

| URL | Tag | Used for |
|---|---|---|
| https://api.india.delta.exchange/v2/products/BTCUSD and `/ETHUSD` | [official] (read) | Fees, contract size, tick, leverage, funding interval |
| https://api.india.delta.exchange/v2/history/candles | [official] (read) | All 1m/5m candles and `FUNDING:` history used in the backtest |
| https://docs.delta.exchange/ | [official] (read) | Candle limits, resolutions, rate limits, WebSocket channels and endpoints, data-centre location |
| https://www.delta.exchange/fees | [official] (read) | 18% GST; "up to 50% off" Scalper Offer wording |
| https://www.delta.exchange/support/solutions/articles/80001172745-scalper-offer | [official] (read) | Exact Scalper Offer terms, Diwali add-on and its 19 Nov 2026 end date, liquidation exclusion |
| https://www.delta.exchange/support/solutions/articles/80001149608-futures-scalper-offer | [official] (read) | Base Scalper Offer terms and worked fee examples |
| https://www.delta.exchange/blog/futures-scalper-carnival | [official] (read) | Earlier 2023 promotion (50% cashback, expired), showing promotions change |
| https://www.delta.exchange/blog/how-to-minimize-your-crypto-trading-fees-and-keep-more-profit | [official] (snippet) | Fee levels (consistent with the API) |

## Academic and quantitative research (Phase 1)

| URL | Tag | Finding relevant here |
|---|---|---|
| https://centaur.reading.ac.uk/100181 | [paper] (snippet) | Shen, Urquhart, Wang (2022), Bitcoin intraday time-series momentum. Basis of strategy #7, which failed on Delta 2024–2026 |
| https://www.sciencedirect.com/science/article/abs/pii/S1062940822000833 | [paper] (snippet) | Wen et al. (2022), intraday momentum and reversal in crypto; no costs stated |
| https://www.mdpi.com/1911-8074/19/9/692 | [paper] (snippet) | BTC session reversal edge vanishes at about 2 bp cost |
| https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/ | [paper] (snippet) | Turn-of-the-candle effect, about 0.6 bp per minute, far below taker cost |
| https://arxiv.org/pdf/2607.09426 | [paper] (snippet) | Quarter-hour effect in Binance perps, about 0.5 bp gross per trade |
| https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/ | [rules] (snippet) | 21:00–23:00 UTC seasonality; zero-cost result |
| https://ideas.repec.org/a/eee/finlet/v31y2019icp78-92.html | [paper] (snippet) | Baur et al. (2019): time-of-day effects not persistent |
| https://link.springer.com/article/10.1007/s10479-019-03357-1 | [paper] (snippet) | Hudson and Urquhart (2021): technical rules work mainly at daily frequency |
| https://ideas.repec.org/a/eee/reveco/v93y2024ipbp858-874.html | [paper] (snippet) | Daily trading is more robust to costs than high-frequency trading |
| https://arxiv.org/abs/2602.10785 | [code+fee backtest] (snippet) | Walk-forward BTC EMA rules: only bars above 30 minutes profitable at 0.1% cost |
| https://arxiv.org/pdf/2608.21888 | [code+fee backtest] (snippet) | Short-horizon reversal does not clear about 5 bp maker cost |
| https://arxiv.org/html/2602.00776v1 | [paper] (snippet) | Order-flow imbalance predicts seconds-ahead returns; maker test loses to adverse selection |
| https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7227998 | [paper] (snippet) | Order-flow imbalance signal unstable out-of-sample |
| https://github.com/gianleonardosalvemini-tech/hpc-lob-imbalance | [code+fee backtest] (snippet) | Imbalance edge 0.04–0.3 bp, far below taker fees |
| https://arxiv.org/pdf/2212.06888 | [paper] (snippet) | He et al.: perp-spot basis arbitrage survives retail costs (hedged, multi-day; not scalping) |
| https://www.bis.org/publ/work1087.pdf | [paper] (snippet) | Crypto carry; compressed since 2024 |
| https://simplemarkets.io/strategies/research-log/opening-range-breakout-costs | [code+fee backtest] (snippet) | Pre-registered ORB on BTC/ETH perps: gross edge about 2.5× smaller than costs. Consistent with strategy #1 here |
| https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7428398 | [paper] (snippet) | ORB on futures 2010–2026: positive gross, deeply negative net |
| https://arxiv.org/pdf/2502.18625 | [paper] (snippet) | Maker fills on Binance BTC perps suffer adverse selection. Consistent with strategy #3 here |

## Strategy rules: open source and TradingView (Phase 1)

| URL | Tag | Notes |
|---|---|---|
| https://github.com/joshyattridge/smart-money-concepts | [rules] (read) | SMC definitions. Its swings, BOS/CHoCH and order blocks use future bars when used at their stamped index; strategy #6 re-implements them causally |
| https://raw.githubusercontent.com/hummingbot/hummingbot/master/controllers/directional_trading/bollinger_v1.py | [rules] (read) | Bollinger %B controller with triple-barrier exits; no results |
| https://raw.githubusercontent.com/freqtrade/freqtrade-strategies/main/user_data/strategies/berlinguyinca/Scalp.py | [rules] (read) | 1m scalp: 1% target against 4% stop; no results |
| https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/backtesting.md | [official for Freqtrade] (read) | Freqtrade backtests assume no slippage |
| https://github.com/iterativv/NostalgiaForInfinity | [rules] (read) | Averaging-down system for alt baskets; excluded |
| https://github.com/enarjord/passivbot | [rules] (read) | Grid bot; excluded |
| https://github.com/jesse-ai/example-strategies | [rules] (read) | Examples only, no results |
| https://raw.githubusercontent.com/yeboster/liquidity-sweep-freqtrade/main/README.md | [rules] (read) | Liquidity sweep on crypto; 1 trade in 30 days |
| https://github.com/MHZardary/london-strategy-backtest | [rules] (read) | Asia→London breakout on FX; costs excluded. Basis of strategy #2 |
| https://www.tradingview.com/script/oGUYuz4N-Hulk-Strategy-x35-Leverage-5m-chart-w-Alerts | [rules] (snippet) | Basis of strategy #5's 1.1% / 1.35% defaults; possible repaint from lower-timeframe MACD |
| https://www.tradingview.com/script/cxhQ5d5x-EMA-Pullback-Speed-Strategy | [anecdote] (snippet) | PF 1.97 claim at 0.02% commission in a bull window |
| https://www.tradingview.com/script/oZcWZsvU-RVWAP-Mean-Reversion-Strategy/ | [rules] (snippet) | Author admits parameter sensitivity |
| https://www.tradingview.com/script/A3xy7WD4-Maiko-Range-Scalper-Sideways-BB-RSI-v4-clean | [rules] (snippet) | BB+RSI range scalp. Basis of strategy #4 |
| https://www.coinquant.ai/blog/vwap-strategy-backtest-on-bitcoin-intraday-mean-reversion-results | [code+fee backtest] (snippet) | BTC VWAP reversion loses at 0.1% taker. Consistent with strategy #3 |

## SMC / ICT evidence (Phase 1)

| URL | Tag | Notes |
|---|---|---|
| https://dev.to/moonthetrain/ict-trading-strategy-backtest-79-setups-on-es-and-nq-d4o | [code+fee backtest] (snippet) | ICT 2022 and Silver Bullet on ES/NQ: PF 0.72–0.96 |
| https://br.tradingview.com/script/teL2dDvS-Silver-Bullet-GBB/ | [code+fee backtest] (snippet) | Silver Bullet hours "not special" |
| https://dev.to/apurv_kaushal_b6764a01ddb/we-backtested-16-popular-gold-trading-setups-with-costs-most-lost-money-4p4p | [code+fee backtest] (snippet) | Order blocks −0.27R and sweeps −0.44R net on gold |
| https://backtrex.com/en/blog/liquidity-sweep-strategy-backtest-results | [anecdote] (snippet) | Vendor claims; contradicts its own backtests |
| https://www.luxalgo.com/library/concept/model-2022.md | [rules] (snippet) | ICT 2022 model description |
| https://www.luxalgo.com/library/concept/judas-swing.md | [rules] (snippet) | Judas swing description |
| https://gist.ly/youtube-summarizer/i-backtested-25000-ict-silver-bullet-trades | [anecdote] (snippet) | Heavy data mining; win rates near 52% |

## Indian and retail scalping content (Phase 1)

| URL | Tag | Notes |
|---|---|---|
| https://mudrex.com/learn/crypto-futures-scalping-strategies/ | [rules] (snippet) | 9/21 EMA pullback and VWAP bounce, partial rules, no results |
| https://algotest.in/blog/scalping-strategy/ | [rules] (snippet) | 1m VWAP + EMA cross, no results |
| https://www.delta.exchange/blog/how-use-vwap-indicator-trade-crypto | [rules] (snippet) | Generic VWAP usage |
| https://www.tapbit.com/en/learn/article/crypto-scalping-guide-fees-liquidity-execution-risks-2026-20260811 | [anecdote] (snippet) | Fee arithmetic for 0.2% scalps |
| https://medium.com/@bart_46269/the-impact-of-trading-fees-on-low-to-medium-frequency-systematic-bitcoin-trading-strategies-bb90f6990c | [anecdote] (snippet) | BTC mean reversion flips to a loss once fees are included |
| https://www.youtube.com/watch?v=l31KpfqXkxQ | [anecdote] (snippet) | Scalper Offer explainer video, no tested rules |
