#!/usr/bin/env python3
import csv
import datetime as dt
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://caseformaking.com"
PAGES = [
    ("In Person", "https://caseformaking.com/pages/cfm-art-room"),
    ("Online", "https://caseformaking.com/pages/workshops"),
]

OUT = "case_events.csv"

FIELDS = [
    "date",
    "venue",
    "title",
    "category",
    "start_time",
    "end_time",
    "price_text",
    "event_url",
    "is_museum",
    "source",
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

def to_iso_date(mon, day, today):
    m = MONTHS[mon.lower()[:3]]
    y = today.year
    d = dt.date(y, m, day)
    if d < today - dt.timedelta(days=7):
        d = dt.date(y + 1, m, day)
    return d.isoformat()

def to_time(h, m, ampm):
    if ampm.lower() == "pm" and h != 12:
        h += 12
    if ampm.lower() == "am" and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}"

def guess_category(title):
    t = title.lower()
    if "figure" in t:
        return "Figure Drawing"
    if "drink" in t and "draw" in t:
        return "Drink & Draw"
    if "zine" in t:
        return "Zine"
    return "Workshop"

def extract(html, label, today):
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    for a in soup.select('a[href*="/products/"]'):
        title = a.get_text(" ", strip=True)
        if not title:
            continue

        block = a.parent.get_text(" ", strip=True)
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
            "Case for Making — Art Room (SF)"
            if label == "In Person"
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
            "event_url": urljoin(BASE, a["href"]),
            "is_museum": "false",
            "source": "Case for Making",
        })

    return rows

def dedupe(rows):
    seen = set()
    out = []
    for r in rows:
        k = (r["date"], r["title"].lower(), r["venue"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return sorted(out, key=lambda r: (r["date"], r["start_time"], r["title"]))

def main():
    today = dt.date.today()
    rows = []

    headers = {"User-Agent": "Mozilla/5.0"}
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
