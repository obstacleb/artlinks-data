#!/usr/bin/env python3
import csv
import datetime as dt
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HOME = "https://www.mothbelly.org/"
OUT = "mothbelly_events.csv"

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

# Example: "exhibit ends Saturday, March 28, 2026."
ENDS_RE = re.compile(
    r"\bends\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?,?\s*"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),\s*(\d{4})\b",
    re.IGNORECASE
)

def fetch(url: str) -> BeautifulSoup:
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def main():
    soup = fetch(HOME)

    # Find the "Now Showing" section and the first "Shop ..." link under it.
    now_showing = None
    for h in soup.find_all(["h2", "h3"]):
        if "now showing" in (h.get_text(" ", strip=True) or "").lower():
            now_showing = h
            break

    link = None
    if now_showing:
        # search forward in the document for an anchor with "Shop"
        for a in now_showing.find_all_next("a", limit=50):
            txt = (a.get_text(" ", strip=True) or "").lower()
            if txt.startswith("shop"):
                link = a
                break

    if not link or not link.get("href"):
        # fallback: just find any /magiclatitudes style page link
        for a in soup.select('a[href^="/"]'):
            if "shop" in (a.get_text(" ", strip=True) or "").lower():
                link = a
                break

    rows = []
    if link and link.get("href"):
        exhibit_url = urljoin(HOME, link.get("href"))
        ex = fetch(exhibit_url)
        page_text = ex.get_text(" ", strip=True)

        m = ENDS_RE.search(page_text)
        if m:
            month, day, year = m.group(1), int(m.group(2)), int(m.group(3))
            date_iso = dt.date(year, dt.datetime.strptime(month, "%B").month, day).isoformat()

            # Title: use first H3 on the page if present
            h3 = ex.find("h3")
            title = h3.get_text(" ", strip=True) if h3 else (link.get_text(" ", strip=True) or "Moth Belly Exhibit")
            title = title.strip()

            rows.append({
                "date": date_iso,
                "venue": "Moth Belly Gallery",
                "title": title,
                "category": "Exhibition",
                "start_time": "",
                "end_time": "",
                "price_text": "",
                "event_url": exhibit_url,
                "is_museum": "false",
                "source": "Moth Belly",
            })

    # Write CSV
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows -> {OUT}")
    if rows:
        print("---- preview ----")
        for r in rows[:5]:
            print(r["date"], r["title"])

if __name__ == "__main__":
    main()
