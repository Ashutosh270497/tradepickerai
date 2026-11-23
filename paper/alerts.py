"""Telegram alerts. Token and chat id come from environment variables only (never stored in git):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Without them (or if Telegram is unreachable) messages are printed and kept in the events table."""
from __future__ import annotations

import json
import os
import urllib.request


def send(text: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    print(f"[alert] {text}", flush=True)
    if not token or not chat:
        print("[alert] Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID unset): logged only", flush=True)
        return False
    body = json.dumps({"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception as e:  # never let an alert failure break the trading loop
        print(f"[alert] Telegram send failed: {type(e).__name__}", flush=True)
        return False
