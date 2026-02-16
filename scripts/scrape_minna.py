#!/usr/bin/env python3
import csv
import datetime as dt
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://111minnagallery.com"
LIST_URL = "https://111minnagallery.com/events/list/"
OUT = "minna_events.csv"

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

SKIP_TITLES = {
    "red door coffee",
    "happy hour",
    "private event",
}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Examples in the page:
# "Featured February 17 @ 4:00 pm - 10:00 pm"
# Sometimes it can omit "Featured", we just search the whole row text.
DT_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2})\s*@\s*"
    r"(\d{1,2}:\d{2}\s*(?:am|pm))\s*(?:-|–)\s*"
    r"(\d{1,2}:\d{2}\s*(?:am|pm))",
    re.IGNORECASE
)

def to_24h(s: str) -> str:
    s = s.strip().lower()
    t = dt.datetime.strptime(s, "%I:%M %p").time()
    return t.strftime("%H:%M")

def guess_category(title: str) -> str:
    t = (title or "").lower()
    if "sketch" in t or "draw" in t:
        return "Figure Drawing" if "figure" in t else "Drink & Draw" if "drink" in t else "Drawing"
    if "opening" in t or "reception" in t:
        return "Opening"
    if "exhibit" in t or "exhibition" in t:
        return "Exhibition"
    if "dj" in t or "music" in t:
        return "Music"
    return "111 Minna"

def main():
    r = requests.get(LIST_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    today = dt.date.today()
    year = today.year

    # The list view groups by month headers like "February 2026"
    # We'll update `year` as we encounter those headers.
    month_header_re = re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})$", re.I)

    rows = []

    # Each event block uses h4 with a link for the title
    # We'll walk through the page top to bottom and keep a running year based on month headers.
    for el in soup.select("body *"):
        # Update year when we see a month header
        txt = el.get_text(" ", strip=True)
        m = month_header_re.match(txt or "")
        if m:
            year = int(m.group(2))
            continue

        # Event titles appear as h4 links inside list blocks.
        if el.name not in ("h3", "h4"):
            continue

        a = el.find("a")
        if not a:
            continue

        title = a.get_text(" ", strip=True) or ""
        title_clean = title.strip()
        if not title_clean:
            continue

        if title_clean.strip().lower() in SKIP_TITLES:
            continue

        href = a.get("href") or ""
        event_url = urljoin(BASE, href)

        # The date/time line is usually near this title in the same event container.
        container = el.find_parent()
        block_text = container.get_text(" ", strip=True) if container else ""
        dm = DT_RE.search(block_text or "")
        if not dm:
            continue

        month_name = dm.group(1).lower()
        day = int(dm.group(2))
        start_str = dm.group(3)
        end_str = dm.group(4)

        mm = MONTHS.get(month_name)
        if not mm:
            continue

        date_iso = dt.date(year, mm, day).isoformat()
        start_time = to_24h(start_str)
        end_time = to_24h(end_str)

        rows.append({
            "date": date_iso,
            "venue": "111 Minna Gallery",
            "title": title_clean,
            "category": guess_category(title_clean),
            "start_time": start_time,
            "end_time": end_time,
            "price_text": "",
            "event_url": event_url,
            "is_museum": "false",
            "source": "111 Minna",
        })

    # dedupe
    seen = set()
    out = []
    for r in rows:
        k = (r["date"], r["title"].lower(), r["start_time"], r["event_url"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)

    out.sort(key=lambda x: (x["date"], x["start_time"], x["title"].lower()))

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)

    print(f"Wrote {len(out)} rows -> {OUT}")
    if out:
        print("---- preview ----")
        for r in out[:5]:
            print(r["date"], r["title"], r["start_time"], "-", r["end_time"])

if __name__ == "__main__":
    main()
