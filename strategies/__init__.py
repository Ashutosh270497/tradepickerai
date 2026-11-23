"""Registry of the seven shortlisted strategies (one module each)."""
from strategies import asia_london, bb_rsi, ema_pullback, intraday_momentum, orb, smc_sweep_fvg, vwap_fade

ALL = [orb, asia_london, vwap_fade, bb_rsi, ema_pullback, smc_sweep_fvg, intraday_momentum]
BY_NAME = {s.NAME: s for s in ALL}
