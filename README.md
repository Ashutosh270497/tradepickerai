# tradepickerai
platform which helps you to pick the best suited trade for you to become profitable and it only suggests not promise anything to be profitable trader

## Research status

Start with [research_report.md](research_report.md).

- **Phase 5 (paper trading):** the correlation-aware re-check still passes, but narrowly (96.5th percentile of a synchronized random baseline). A public-data shadow paper trader (`paper/`) reuses the backtest's own code, and its dry run is complete. The plan is in `paper_trading_plan.md` (committed before go-live); AWS deployment steps are in `docs/deploy_aws.md`.
- **Phase 4 (frozen rules, unseen data):** the 4h trend filter, pre-registered in `frozen_rules.md`, **passed** on 33 unseen coins (31 positive, pooled PF 1.38, beats 100% of random runs) and on pre-2020 BTC/ETH. The edge is modest and mostly long-side. Recommended next step: paper trading.
- **Phase 3 (longer holding periods):** a zero-cost screen of 242 signal configurations found one survivor, a 4h price-vs-SMA trend filter held 10–30 days. It **passes** the walk-forward PASS bar only marginally and is rated **LOW-CONFIDENCE**: it fails on the half of the data not used to pick it.
- **Phase 2 (1–5 minute scalping):** 7 strategies on Delta Exchange India, 2 years of 1-minute data. **None passed**, in any fee scenario.

| Path | What it is |
|---|---|
| `research_report.md` | Platform facts, breakeven math, results, what didn't work and why |
| `phase1_findings.md` | Phase 0/1 platform facts, research summary and the 7-strategy shortlist |
| `sources.md` | Every URL used, tagged by evidence quality |
| `edge_screen.py`, `edge_screen.csv` | Phase 3 zero-cost edge screen and every test it ran |
| `paper/`, `paper_config.json`, `paper_trading_plan.md`, `docs/deploy_aws.md`, `Dockerfile` | Phase 5 shadow paper trader, its pre-registered plan and AWS deployment |
| `phase5_robustness.py` | Phase 5 correlation-aware re-check of Phase 4 Part A |
| `frozen_rules.md` | Phase 4 pre-registration (rules, coins, pass criteria), committed before testing |
| `phase4_runner.py`, `phase4_results.csv`, `phase4_summary.csv` | Phase 4 frozen-rule test on unseen coins and pre-2020 BTC/ETH |
| `phase3_runner.py`, `phase3_verdicts.csv`, `phase3_results.csv` | Phase 3 walk-forward backtest of the screen survivor |
| `results.csv` | Phase 2: selected variant of each strategy, by fee scenario, period and symbol |
| `charts/` | In-sample and out-of-sample equity curves per strategy |
| `logs/` | Every variant tried, random baselines, quarterly breakdowns, trade lists |
| `strategies/` | One Python file per strategy |
| `core/` | Data download, market container, backtest engine, indicators, metrics |
| `tests/` | Unit tests for fees, slippage, funding, limit and stop fills, no-lookahead |
| `data/` | Not committed; rebuild with `python3 -m core.data download`, `python3 -m core.binance_data` and `python3 -m core.phase4_data` |
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

```bash
python3 edge_screen.py
```

```bash
python3 phase3_runner.py
```

```bash
python3 phase4_runner.py
```
