"""Delta Exchange India PUBLIC REST endpoints (no API key). Docs: https://docs.delta.exchange/"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

BASE = "https://api.india.delta.exchange"
MAX_CANDLES = 2000


def get(path: str, params: dict | None = None, retries: int = 5) -> dict:
    url = f"{BASE}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "paper-trader"})
    err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read())
            if body.get("success") is False:
                raise RuntimeError(f"Delta API error {body}")
            return body
        except Exception as e:  # network / 429: back off
            err = e
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"Delta request failed: {url}") from err


def candles(symbol: str, start: int, end: int, resolution: str = "1h", step: int = 3600) -> list[dict]:
    """Closed candles with open time in [start, end) (UTC seconds). The still-forming candle is dropped."""
    out, cur = [], start
    while cur < end:
        stop = min(cur + step * MAX_CANDLES, end)
        out += get("/v2/history/candles", {"resolution": resolution, "symbol": symbol, "start": cur, "end": stop})["result"]
        cur = stop
    seen, rows = set(), []
    for c in sorted(out, key=lambda x: x["time"]):
        if c["time"] in seen or c["time"] < start or c["time"] + step > end:
            continue
        seen.add(c["time"])
        rows.append(c)
    return rows


def product(symbol: str) -> dict:
    return get(f"/v2/products/{symbol}")["result"]


def quote(symbol: str) -> dict:
    """Live L1 snapshot: order-book top (bid/ask/sizes) plus ticker last price and mark price."""
    book = get(f"/v2/l2orderbook/{symbol}", {"depth": 1})["result"]
    tick = get(f"/v2/tickers/{symbol}")["result"]
    bid = book["buy"][0] if book.get("buy") else {}
    ask = book["sell"][0] if book.get("sell") else {}
    return {"best_bid": float(bid["price"]) if bid else None, "bid_size": float(bid.get("size", 0)) if bid else None,
            "best_ask": float(ask["price"]) if ask else None, "ask_size": float(ask.get("size", 0)) if ask else None,
            "ltp": float(tick["close"]), "mark": float(tick["mark_price"]),
            "quote_time": int(book.get("last_updated_at", 0)) // 1_000_000, "fetched_at": int(time.time())}
