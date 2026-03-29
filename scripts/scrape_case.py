#!/usr/bin/env python3
import csv
import datetime as dt
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://caseformaking.com"

PAGES = [
    ("In Person", "https://caseformaking.com/collections/art-room-workshops"),
    ("Online",    "https://caseformaking.com/collections/online-workshop"),
]

OUT = "case_events.csv"

FIELDS = [
    "date","venue","title","category","start_time","end_time",
    "price_text","event_url","instagram_url","is_museum","museum_name","notes","source",
]

WHEN_RE = re.compile(
    r"—\s*(?:[A-Za-z]{3},?\s*)?([A-Za-z]{3})\s+(\d{1,2})\s*/\s*(\d{1,2}):(\d{2})\s*([ap]m)",
    re.IGNORECASE,
)
PRICE_RE = re.compile(r"\$(\d+(?:\.\d{2})?)")
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

def to_iso_date(mon: str, day: int, today: dt.date) -> str:
    m = MONTHS[mon.lower()[:3]]
    y = today.year
    d = dt.date(y, m, day)
    if d < today - dt.timedelta(days=7):
        d = dt.date(y + 1, m, day)
    return d.isoformat()

def to_time(h: int, minute: int, ampm: str) -> str:
    ampm = ampm.lower()
    if ampm == "pm" and h != 12: h += 12
    if ampm == "am" and h == 12: h = 0
    return f"{h:02d}:{minute:02d}"

def guess_category(title: str) -> str:
    t = (title or "").lower()
    if "figure" in t: return "Figure Drawing"
    if "drink" in t and "draw" in t: return "Drink & Draw"
    if "zine" in t: return "Zine"
    return "Workshop"

def find_card_text(a):
    node = a
    for _ in range(12):
        if node is None:
            break
        txt = node.get_text(" ", strip=True)
        if WHEN_RE.search(txt):
            return txt
        node = node.parent
    return a.get_text(" ", strip=True)

def extract(html: str, label: str, today: dt.date):
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    for a in soup.select('a[href*="/products/"]'):
        href = a.get("href") or ""
        if "/products/" not in href:
            continue

        title = (a.get_text(" ", strip=True) or "").strip()
        if not title:
            title = (a.get("aria-label") or a.get("title") or "").strip()
        if not title:
            continue

        block = find_card_text(a)
        m = WHEN_RE.search(block)
        if not m:
            continue

        mon, day, h, minute, ampm = m.groups()
        date_iso = to_iso_date(mon, int(day), today)
        start_time = to_time(int(h), int(minute), ampm)

        price = ""
        pm = PRICE_RE.search(block)
        if pm:
            price = f"${pm.group(1)}"

        venue = (
            "Case for Making — Art Room (SF)" if label == "In Person"
            else "Case for Making — Online"
        )

        rows.append({
            "date": date_iso,
            "venue": venue,
            "title": title,
            "category": guess_category(title),
            "start_time": start_time,
            "end_time": "",
            "price_text": price,
            "event_url": urljoin(BASE, href),
            "instagram_url": "",
            "is_museum": "false",
            "museum_name": "",
            "notes": "",
            "source": "Case for Making",
        })

    return rows

def dedupe(rows):
    seen = set()
    out = []
    for r in rows:
        k = (r["date"], r["title"].strip().lower(), r["venue"].strip().lower(), r.get("start_time", ""))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    out.sort(key=lambda r: (r["date"], r.get("start_time", ""), r["title"].lower()))
    return out

def main():
    today = dt.date.today()
    rows = []
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}

    for label, url in PAGES:
        res = requests.get(url, headers=headers, timeout=30)
        res.raise_for_status()
        rows.extend(extract(res.text, label, today))

    rows = dedupe(rows)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows -> {OUT}")

if __name__ == "__main__":
    main()
