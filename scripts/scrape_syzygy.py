#!/usr/bin/env python3
import csv
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://syzygysf.com/"
OUT = "syzygy_events.csv"

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

DATE_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")  # MM-DD-YYYY

def mmddyyyy_to_iso(mm: str, dd: str, yyyy: str) -> str:
    return f"{yyyy}-{mm}-{dd}"

def main():
    r = requests.get(BASE_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    rows = []

    for a in soup.select("a"):
        title = (a.get_text(" ", strip=True) or "").strip()
        if not title:
            continue

        parent_text = (a.parent.get_text(" ", strip=True) if a.parent else "")
        m = DATE_RE.search(parent_text)
        if not m:
            continue

        mm, dd, yyyy = m.group(1), m.group(2), m.group(3)
        date_iso = mmddyyyy_to_iso(mm, dd, yyyy)

        href = a.get("href") or ""
        event_url = urljoin(BASE_URL, href)

        t_low = title.lower()
        if "fair" in t_low or "market" in t_low:
            category = "Market"
        elif "workshop" in t_low or "class" in t_low:
            category = "Workshop"
        else:
            category = "Syzygy"

        rows.append({
            "date": date_iso,
            "venue": "Syzygy SF",
            "title": title,
            "category": category,
            "start_time": "",
            "end_time": "",
            "price_text": "",
            "event_url": event_url,
            "is_museum": "false",
            "source": "Syzygy",
        })

    # dedupe
    seen = set()
    deduped = []
    for e in rows:
        key = (e["date"], e["title"].lower(), e["event_url"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    deduped.sort(key=lambda x: (x["date"], x["title"].lower()))

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(deduped)

    # Print to log (NOT into the CSV)
    print(f"Wrote {len(deduped)} rows -> {OUT}")

if __name__ == "__main__":
    main()
