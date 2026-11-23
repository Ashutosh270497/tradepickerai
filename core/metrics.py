"""Performance statistics for a trade list produced by core.engine.run."""
from __future__ import annotations

import numpy as np
import pandas as pd


def longest_losing_streak(net: np.ndarray) -> int:
    best = cur = 0
    for x in net:
        cur = cur + 1 if x < 0 else 0
        best = max(best, cur)
    return best


def stats(tr: pd.DataFrame, period_start, period_end, equity0: float = 1000.0) -> dict:
    """period_start / period_end: UTC timestamps bounding the test window (for daily Sharpe)."""
    if tr is None or len(tr) == 0:
        return {"trades": 0}
    net = tr["net"].to_numpy()
    R = tr["R"].to_numpy()
    wins, losses = net[net > 0], net[net <= 0]
    eq = equity0 + np.cumsum(net)
    peak = np.maximum.accumulate(np.concatenate([[equity0], eq]))[1:]
    dd = ((peak - eq) / peak).max() * 100
    # daily realised P&L on every calendar day of the window -> Sharpe / Sortino (365-day year)
    days = pd.date_range(pd.Timestamp(period_start).floor("D"), pd.Timestamp(period_end).floor("D"),
                         freq="D", tz="UTC")
    daily = tr.groupby(tr["exit_time"].dt.floor("D"))["net"].sum().reindex(days, fill_value=0.0)
    eq_start = equity0 + daily.cumsum().shift(1, fill_value=0.0)
    rets = (daily / eq_start).to_numpy()
    sd = rets.std(ddof=1)
    down = rets[rets < 0]
    dsd = np.sqrt((down ** 2).sum() / max(len(rets) - 1, 1))
    gross_profit, gross_loss = wins.sum(), -losses.sum()
    return {
        "trades": len(tr),
        "trades_per_day": len(tr) / max(len(days), 1),
        "net_usd": net.sum(),
        "net_pct": net.sum() / equity0 * 100,
        "win_rate_pct": len(wins) / len(tr) * 100,
        "avg_win_usd": wins.mean() if len(wins) else 0.0,
        "avg_loss_usd": losses.mean() if len(losses) else 0.0,
        "avg_win_R": R[R > 0].mean() if (R > 0).any() else 0.0,
        "avg_loss_R": R[R <= 0].mean() if (R <= 0).any() else 0.0,
        "expectancy_R": R.mean(),
        "expectancy_pct_equity": (net / tr["equity_before"].to_numpy()).mean() * 100,
        "net_R": R.sum(),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else np.inf,
        "gross_before_costs_usd": tr["gross"].sum(),
        "fees_usd": tr["fees"].sum(),
        "funding_usd": tr["funding"].sum(),
        "gross_expectancy_R": (tr["gross"] / (tr["qty"] * tr["stop_frac"] * tr["entry"])).mean(),
        "fees_per_trade_R": (tr["fees"] / (tr["qty"] * tr["stop_frac"] * tr["entry"])).mean(),
        "gross_move_pct_per_trade": (tr["dir"] * (tr["exit"] - tr["entry"]) / tr["entry"]).mean() * 100,
        "cost_pct_per_trade": (tr["fees"] / (tr["qty"] * tr["entry"])).mean() * 100,
        "max_dd_pct": dd,
        "sharpe": rets.mean() / sd * np.sqrt(365) if sd > 0 else 0.0,
        "sortino": rets.mean() / dsd * np.sqrt(365) if dsd > 0 else 0.0,
        "avg_hold_min": tr["hold_min"].mean(),
        "longest_losing_streak": longest_losing_streak(net),
        "long_share_pct": (tr["dir"] > 0).mean() * 100,
        "cap_hit_pct": tr["capped"].mean() * 100,
        "avg_leverage": tr["leverage"].mean(),
        "fee_free_close_pct": tr["fee_free"].mean() * 100,
        "skipped_below_1_lot": tr.attrs.get("skipped_small", 0),
        "ruined": tr.attrs.get("ruined_at") is not None,
    }


def quarterly(tr: pd.DataFrame, equity0: float = 1000.0) -> pd.DataFrame:
    if tr is None or len(tr) == 0:
        return pd.DataFrame()
    q = tr["exit_time"].dt.tz_localize(None).dt.to_period("Q").astype(str)
    eq_before = tr.groupby(q)["equity_before"].first()
    g = tr.groupby(q).agg(trades=("net", "size"), net_usd=("net", "sum"), net_R=("R", "sum"),
                          win_rate_pct=("net", lambda x: (x > 0).mean() * 100))
    g["return_pct"] = g["net_usd"] / eq_before * 100
    return g.reset_index().rename(columns={"exit_time": "quarter", "index": "quarter"})
