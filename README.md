# tradepickerai
platform which helps you to pick the best suited trade for you to become profitable and it only suggests not promise anything to be profitable trader

## Research status

Phase 2 backtest of 7 scalping strategies on Delta Exchange India (BTCUSD and ETHUSD perpetuals, 2 years of 1-minute data). **Result: none passed, in any fee scenario.** Start with [research_report.md](research_report.md).

| Path | What it is |
|---|---|
| `research_report.md` | Platform facts, breakeven math, results, what didn't work and why |
| `phase1_findings.md` | Phase 0/1 platform facts, research summary and the 7-strategy shortlist |
| `sources.md` | Every URL used, tagged by evidence quality |
| `results.csv` | Selected variant of each strategy, by fee scenario, period and symbol |
| `charts/` | In-sample and out-of-sample equity curves per strategy |
| `logs/` | Every variant tried, random baselines, quarterly breakdowns, trade lists |
| `strategies/` | One Python file per strategy |
| `core/` | Data download, market container, backtest engine, indicators, metrics |
| `tests/` | Unit tests for fees, slippage, funding, limit and stop fills, no-lookahead |
| `data/` | Cached Delta candles and funding history (parquet) |
| `backtest/` | Earlier exploratory backtests (EMA crosses, multi-timeframe comparison) |

```bash
pip install -r requirements.txt
```

```bash
python3 -m pytest -q tests
```

```bash
python3 backtest_runner.py
```
