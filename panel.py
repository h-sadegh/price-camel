#!/usr/bin/env python3
"""Build a self-contained HTML dashboard (docs/index.html) from data/*.json + watched.json.

The output has zero dependencies beyond the page itself: chart rendering is
plain SVG generated here, so it works offline and on GitHub Pages.
"""
import json
import datetime
import html
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
WATCHED = BASE / "watched.json"
OUT = BASE / "docs" / "index.html"

TZ = datetime.timezone(datetime.timedelta(hours=3, minutes=30))  # Iran


def fmt_price(p):
    return f"{p:,}".replace(",", "،")


def load():
    watched = json.loads(WATCHED.read_text(encoding="utf-8"))
    products = []
    for p in watched.get("products", []):
        f = DATA / f"{p['id']}.json"
        samples = []
        if f.exists():
            try:
                samples = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                samples = []
        products.append({**p, "samples": samples})
    return products


def sparkline_svg(samples, w=560, h=120):
    if len(samples) < 2:
        return f'<div class="empty">داده کافی نیست (حداقل ۲ نمونه لازم است)</div>'
    ts = [s["ts"] for s in samples]
    ps = [s["price"] for s in samples]
    t0, t1 = min(ts), max(ts)
    p0, p1 = min(ps), max(ps)
    if p1 == p0:
        p1 = p0 + 1
    if t1 == t0:
        t1 = t0 + 1
    pad = 8
    pts = []
    for t, pr in zip(ts, ps):
        x = pad + (t - t0) / (t1 - t0) * (w - 2 * pad)
        y = h - pad - (pr - p0) / (p1 - p0) * (h - 2 * pad)
        pts.append((x, y))
    # downsample if too many points
    if len(pts) > 300:
        step = len(pts) / 300
        pts = [pts[int(i * step)] for i in range(300)]
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = path + f" L{pts[-1][0]:.1f},{h - pad} L{pts[0][0]:.1f},{h - pad} Z"
    first, last = ps[0], ps[-1]
    change = (last - first) / first * 100 if first else 0
    color = "#e05252" if change > 0 else "#3aa66a"
    labels = ""
    for t, pr, (x, y) in zip(ts, ps, pts):
        if t in (ts[0], ts[-1]) or pr in (min(ps), max(ps)):
            dt = datetime.datetime.fromtimestamp(t, TZ).strftime("%m/%d %H:%M")
            labels += (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>'
                       f'<text x="{x:.1f}" y="{y - 6:.1f}" font-size="9" text-anchor="middle" fill="{color}">'
                       f'{fmt_price(pr)} — {dt}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" preserveAspectRatio="none">'
            f'<path d="{area}" fill="{color}" opacity="0.08"/>'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>{labels}</svg>')


def build():
    products = load()
    now = datetime.datetime.now(TZ).strftime("%Y/%m/%d — %H:%M")
    cards = []
    for p in products:
        samples = p["samples"]
        if samples:
            last = samples[-1]
            last_dt = datetime.datetime.fromtimestamp(last["ts"], TZ).strftime("%m/%d %H:%M")
            price = fmt_price(last["price"])
            avg = last.get("avg")
            avg_html = (f'<div class="avg">میانگین ۱۰ فروشنده ارزان: {fmt_price(avg)} تومان</div>'
                        if avg else "")
            dk = last.get("dk")
            dk_html = (f'<div class="dk">دیجیکالا: {fmt_price(dk)} تومان</div>'
                       if dk else "")
            first = samples[0]["price"]
            change = (last["price"] - first) / first * 100 if first else 0
            sign = "▲" if change > 0 else ("▼" if change < 0 else "—")
            cclass = "up" if change > 0 else ("down" if change < 0 else "flat")
            change_html = f'<span class="{cclass}">{sign} {abs(change):.1f}٪ از شروع رصد</span>'
            target = p.get("target_price")
            target_html = ""
            if target:
                tstate = "رسیده ✅" if last["price"] <= target else "نرسیده"
                target_html = f'<div class="target">هدف: {fmt_price(target)} — {tstate}</div>'
        else:
            price = "—"
            last_dt = "—"
            change_html = ""
            target_html = ""
            avg_html = ""
            dk_html = ""
        src = p.get("source", "torob")
        src_badge = {"torob": "ترب", "digikala": "دیجیکالا"}.get(src, src)
        url = p.get("url", "#")
        cards.append(f'''
        <div class="card">
          <div class="card-head">
            <h3><a href="{html.escape(url)}">{html.escape(p["name"])}</a></h3>
            <span class="badge">{src_badge}</span>
          </div>
          <div class="price-row">
            <div class="price">{price} <small>تومان</small></div>
            <div class="meta">آخرین برداشت: {last_dt} • {len(samples)} نمونه</div>
          </div>
          {avg_html}
          {dk_html}
          {change_html}
          {target_html}
          {sparkline_svg(samples)}
        </div>''')
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(f'''<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🐫</text></svg>">
<title>چک قیمت — پایش قیمت محصولات</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Vazirmatn, Tahoma, sans-serif; background: #0f1117; color: #e6e8ee; padding: 24px; }}
  header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 20px; flex-wrap: wrap; gap: 8px; }}
  h1 {{ font-size: 1.5rem; }}
  .updated {{ color: #8b93a7; font-size: 0.85rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }}
  .card {{ background: #171a23; border: 1px solid #262b38; border-radius: 12px; padding: 16px; }}
  .card-head {{ display: flex; justify-content: space-between; align-items: start; gap: 8px; margin-bottom: 8px; }}
  .card h3 {{ font-size: 0.95rem; font-weight: 600; line-height: 1.5; }}
  .card h3 a {{ color: #e6e8ee; text-decoration: none; }}
  .card h3 a:hover {{ color: #7ab8ff; }}
  .badge {{ background: #262b38; color: #9fb0cc; border-radius: 6px; padding: 2px 8px; font-size: 0.72rem; white-space: nowrap; }}
  .price-row {{ display: flex; justify-content: space-between; align-items: baseline; margin: 6px 0 4px; }}
  .price {{ font-size: 1.35rem; font-weight: 700; }}
  .price small {{ font-size: 0.7rem; color: #8b93a7; }}
  .meta {{ color: #8b93a7; font-size: 0.75rem; }}
  .up {{ color: #e05252; font-size: 0.8rem; }}
  .down {{ color: #3aa66a; font-size: 0.8rem; }}
  .flat {{ color: #8b93a7; font-size: 0.8rem; }}
  .dk {{ margin-top: 4px; font-size: 0.8rem; color: #e08a4a; }}
  .avg {{ margin-top: 4px; font-size: 0.8rem; color: #7ab8ff; }}
  .target {{ margin-top: 4px; font-size: 0.8rem; color: #d8b04a; }}
  .chart {{ width: 100%; height: 120px; margin-top: 10px; display: block; }}
  .empty {{ color: #8b93a7; font-size: 0.8rem; padding: 24px 0; text-align: center; }}
  footer {{ margin-top: 24px; color: #667; font-size: 0.75rem; text-align: center; }}
</style>
</head>
<body>
<header>
  <h1>🐫 چک قیمت</h1>
  <div class="updated">آخرین به‌روزرسانی: {now}</div>
</header>
<div class="grid">
{''.join(cards)}
</div>
<footer>ساخته‌شده خودکار از داده‌های ریپازیتوری — هر ۳۰ دقیقه به‌روز می‌شود</footer>
</body>
</html>''', encoding="utf-8")
    print(f"dashboard written: {OUT} ({len(products)} products)")


if __name__ == "__main__":
    build()
