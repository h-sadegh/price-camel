#!/usr/bin/env python3
"""price-camel alerts: compare latest price vs target and notify via Telegram.

check_alerts() reads watched.json + data/<id>.json. For each product whose
latest recorded price is <= target_price, it builds a Persian message and
calls send_telegram(). An alert only fires once per price level: the last
notified price is stored in data/<id>.alerted so re-runs stay quiet until
the price drops further (or rises above target again, which re-arms it).

send_telegram() reads BOT_TOKEN and CHAT_ID from environment variables.
No token is needed to run or test the rest of the project.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
WATCHED = BASE_DIR / "watched.json"


def send_telegram(chat_id: str, text: str) -> bool:
    """Send a message via the Telegram Bot API.

    Requires BOT_TOKEN in the environment (chat_id comes from CHAT_ID).
    Returns True on success. Thin stub on purpose; phase 2 adds retries.
    """
    token = os.environ.get("BOT_TOKEN")
    if not token or not chat_id:
        print("[alert] BOT_TOKEN/CHAT_ID not set - would have sent:")
        print(f"        to={chat_id!r} text={text!r}")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=payload)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[alert] telegram send failed: {e}", file=sys.stderr)
        return False


def load_latest_price(pid: str) -> int | None:
    path = DATA_DIR / f"{pid}.json"
    if not path.exists():
        return None
    try:
        samples = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return samples[-1]["price"] if samples else None


def load_alerted(pid: str) -> int | None:
    path = DATA_DIR / f"{pid}.alerted"
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def save_alerted(pid: str, price: int) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / f"{pid}.alerted").write_text(str(price))


def check_alerts() -> list:
    """Return list of alert messages that fired (and attempt to send them)."""
    watched = json.loads(WATCHED.read_text(encoding="utf-8"))
    chat_id = os.environ.get("CHAT_ID", "")
    fired = []
    for product in watched.get("products", []):
        pid = product["id"]
        target = product.get("target_price")
        if not target:
            continue
        price = load_latest_price(pid)
        if price is None:
            continue
        if price <= target:
            last_alert = load_alerted(pid)
            if last_alert is not None and last_alert <= price:
                continue  # already alerted at this or a lower price
            msg = (
                f"\U0001F42B قیمت پایین آمد!\n"
                f"{product.get('name', pid)}\n"
                f"قیمت فعلی: {price:,} تومان\n"
                f"قیمت هدف: {target:,} تومان\n"
                f"{product.get('url', '')}"
            )
            fired.append(msg)
            send_telegram(chat_id, msg)
            save_alerted(pid, price)
        else:
            # price rose above target again -> re-arm the alert
            if load_alerted(pid) is not None:
                (DATA_DIR / f"{pid}.alerted").unlink(missing_ok=True)
    return fired


if __name__ == "__main__":
    msgs = check_alerts()
    print(f"[alerts] {len(msgs)} alert(s) fired")
