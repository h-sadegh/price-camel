#!/usr/bin/env python3
"""price-camel tracker: fetch current prices from Torob's public search API.

How it works:
  Torob's product-details endpoint is bot-walled, but the public search API
  (https://api.torob.com/v4/base-product/search/?q=...) returns each result's
  random_key (the product id used in torob.com/p/<random_key>/ URLs) together
  with its current cheapest price. So for every watched product we run the
  stored search query and pick the result whose random_key matches.

  Each sample is appended to data/<product_id>.json as {"ts": ..., "price": ...}.
  Failures (network, 404, bot-wall 490, product not in results) are logged and
  skipped gracefully - one bad product never aborts the whole run.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
WATCHED = BASE_DIR / "watched.json"

SEARCH_URL = "https://api.torob.com/v4/base-product/search/?q={q}&size=32"
DETAILS_URL = "https://api.torob.com/v4/base-product/details/?prk={id}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
    ),
    "Accept": "application/json",
}

RETRIES = 3
RETRY_DELAY = 5  # seconds


def http_get_json(url: str, timeout: int = 20) -> dict:
    last_err = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 490 = Torob bot-wall / rate limit; 404 = gone. Both are fatal
            # for this request, but we still retry a couple of times on 490.
            last_err = f"HTTP {e.code}"
            if e.code == 404:
                raise
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last_err = str(e)
        time.sleep(RETRY_DELAY)
    raise RuntimeError(f"GET failed after {RETRIES} tries: {url} ({last_err})")


def fetch_price(product: dict) -> int | None:
    """Return the current cheapest price (toman) for a watched product, or None."""
    pid = product["id"]
    # Primary path: search by query, match on random_key.
    try:
        data = http_get_json(SEARCH_URL.format(q=urllib.parse.quote(product["query"])))
        for r in data.get("results", []):
            if r.get("random_key") == pid:
                price = r.get("price")
                return int(price) if price else None
        # Not matched in search results -> fall through to details endpoint.
        print(f"  [warn] id {pid} not found in search results for "
              f"{product['query']!r}", file=sys.stderr)
    except Exception as e:
        print(f"  [warn] search failed ({e}); trying details endpoint", file=sys.stderr)

    # Fallback: details endpoint (often bot-walled with 490, hence optional).
    try:
        data = http_get_json(DETAILS_URL.format(id=pid))
        price = data.get("price")
        return int(price) if price else None
    except Exception as e:
        print(f"  [warn] details failed: {e}", file=sys.stderr)
        return None


def append_sample(pid: str, price: int) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / f"{pid}.json"
    samples = []
    if path.exists():
        try:
            samples = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            samples = []  # corrupt file -> start over rather than crash
    # Skip duplicate sample if price unchanged within the last 12 hours.
    now = int(time.time())
    if samples and samples[-1]["price"] == price and now - samples[-1]["ts"] < 12 * 3600:
        return
    samples.append({"ts": now, "price": price})
    path.write_text(json.dumps(samples, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    try:
        watched = json.loads(WATCHED.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] cannot read watched.json: {e}", file=sys.stderr)
        return 1

    ok = fail = 0
    for product in watched.get("products", []):
        pid = product["id"]
        print(f"[track] {product.get('name', pid)} ({pid})")
        try:
            price = fetch_price(product)
        except Exception as e:
            print(f"  [error] {e}", file=sys.stderr)
            price = None
        if price is None:
            print("  -> no price (skipped)")
            fail += 1
        else:
            append_sample(pid, price)
            print(f"  -> {price:,} toman")
            ok += 1
        time.sleep(3)  # be polite to the API

    print(f"[done] ok={ok} failed={fail}")
    # Non-zero only if EVERYTHING failed, so a partial outage still commits data.
    return 1 if (ok == 0 and fail > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
