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

DIGIKALA_URL = "https://api.digikala.com/v2/product/{id}/"
SELLERS_URL = "https://api.torob.com/v4/base-product/sellers/?prk={id}"
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


def fetch_sellers_stats(pid: str, n: int = 10) -> tuple[int, float, int] | None:
    """Return (min_price, avg_of_first_n, seller_count) from the Torob sellers endpoint.

    Torob returns sellers roughly price-sorted; we sort by price ourselves
    anyway and average the cheapest n available offers.
    """
    try:
        data = http_get_json(SELLERS_URL.format(id=pid))
        prices = [int(r["price"]) for r in data.get("results", [])
                  if r.get("price") and r.get("availability", True)]
        if not prices:
            return None
        prices.sort()
        cheapest_n = prices[:n]
        return prices[0], round(sum(cheapest_n) / len(cheapest_n)), len(prices)
    except Exception:
        return None


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


def fetch_price_digikala(product: dict) -> int | None:
    """Return the current price (toman) of a Digikala product via /v2/product/.

    Digikala prices are in RIALS; convert to toman (divide by 10) so all
    history stays in one unit. Unavailable products (no default_variant
    price) return None.
    """
    try:
        data = http_get_json(DIGIKALA_URL.format(id=product["id"]))
        prod = (data.get("data") or {}).get("product") or {}
        variant = prod.get("default_variant") or {}
        price = (variant.get("price") or {}).get("selling_price")
        if price is None:
            # try the variant's own fields (some payloads nest differently)
            price = variant.get("selling_price")
        return int(price) // 10 if price else None
    except Exception:
        return None


def append_sample(pid: str, price: int, avg: int | None = None) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / f"{pid}.json"
    samples = []
    if path.exists():
        try:
            samples = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            samples = []  # corrupt file -> start over rather than crash
    # Skip duplicate sample if price AND avg unchanged within the last 12 hours.
    now = int(time.time())
    last = samples[-1] if samples else None
    if last and now - last["ts"] < 12 * 3600:
        same_price = last["price"] == price
        last_avg = last.get("avg")
        same_avg = (last_avg == avg) or (avg is not None and last_avg is not None
                                         and abs(last_avg - avg) / last_avg < 0.005)
        if same_price and (same_avg or avg is None):
            return
    entry = {"ts": now, "price": price}
    if avg is not None:
        entry["avg"] = avg
    samples.append(entry)
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
            avg = None
            if product.get("source") == "digikala":
                price = fetch_price_digikala(product)
            else:
                price = fetch_price(product)
                stats = fetch_sellers_stats(pid)
                if stats:
                    min_p, avg, sellers = stats
                    price = min_p  # cheapest offer across sellers
        except Exception as e:
            print(f"  [error] {e}", file=sys.stderr)
            price = None
            avg = None
        if price is None:
            print("  -> no price (skipped)")
            fail += 1
        else:
            append_sample(pid, price, avg)
            extra = f" | avg10={avg:,}" if avg else ""
            print(f"  -> {price:,} toman{extra}")
            ok += 1
        time.sleep(3)  # be polite to the API

    print(f"[done] ok={ok} failed={fail}")
    # Non-zero only if EVERYTHING failed, so a partial outage still commits data.
    return 1 if (ok == 0 and fail > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
