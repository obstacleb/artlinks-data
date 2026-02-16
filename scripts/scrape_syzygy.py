#!/usr/bin/env python3
import csv
import datetime as dt
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://syzygysf.com/"
OUT = "syzygy_events.csv"
MONTHS_AHEAD = 6  # generate recurring events this far ahead

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

# Python weekday: Mon=0 ... Sun=6
WD = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

def mmddyyyy_to_iso(mm: str, dd: str, yyyy: str) -> str:
    return f"{yyyy}-{mm}-{dd}"

def month_iter(start: dt.date, months_ahead: int):
    y, m = start.year, start.month
    for i in range(months_ahead + 1):
        yy = y + ((m - 1 + i) // 12)
        mm = ((m - 1 + i) % 12) + 1
        yield yy, mm

def nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> dt.date:
    # Find the n-th weekday (e.g., 2nd Wednesday) in a given month.
    d = dt.date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    d = d + dt.timedelta(days=offset)
    d = d + dt.timedelta(days=7 * (n - 1))
    return d

def weekly_dates(start: dt.date, end: dt.date, weekday: int):
    # All dates between [start, end] on a given weekday
    d = start
    offset = (weekday - d.weekday()) % 7
    d = d + dt.timedelta(days=offset)
    while d <= end:
        yield d
        d += dt.timedelta(days=7)

def add_row(rows, date_iso, title, category, start_time="", end_time="", event_url=BASE_URL + "#events"):
    rows.append({
        "date": date_iso,
        "venue": "Syzygy SF",
        "title": title,
        "category": category,
        "start_time": start_time,
        "end_time": end_time,
        "price_text": "",
        "event_url": event_url,
        "is_museum": "false",
        "source": "Syzygy",
    })

def scrape_special_events(soup: BeautifulSoup):
    """
    Finds linked items where the parent text contains a MM-DD-YYYY date,
    like: [Title link] 04-25-2026
    """
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

        add_row(rows, date_iso, title, category, event_url=event_url)

    return rows

def generate_recurring_events(today: dt.date, months_ahead: int):
    """
    Hardcode recurring rules based on the current Syzygy #events text.
    (This is more robust than trying to NLP their prose every time.)
    """
    rows = []

    # range for weekly generation
    end = today + dt.timedelta(days=30 * months_ahead)

    # Weekly
    for d in weekly_dates(today, end, WD["monday"]):
        add_row(rows, d.isoformat(), "Jam Night", "Music", start_time="20:00", end_time="22:00", event_url=BASE_URL + "#events")

    for d in weekly_dates(today, end, WD["tuesday"]):
        # NOTE: first Tuesday also has Game Night; we’ll add a separate monthly entry below
        add_row(rows, d.isoformat(), "Hobby Hangs", "Syzygy", start_time="19:00", end_time="22:00", event_url=BASE_URL + "#events")

    # Monthly rules
    for (yy, mm) in month_iter(today, months_ahead):
        # Zine Club — 2nd Wednesday
        z = nth_weekday_of_month(yy, mm, WD["wednesday"], 2)
        if z >= today:
            add_row(rows, z.isoformat(), "Zine Club", "Zine", start_time="18:00", end_time="21:00", event_url=BASE_URL + "#events")

        # Flipside Record Club — 3rd Thursday
        f = nth_weekday_of_month(yy, mm, WD["thursday"], 3)
        if f >= today:
            add_row(rows, f.isoformat(), "Flipside Record Club", "Music", start_time="19:00", end_time="21:00", event_url=BASE_URL + "#events")

        # Game Night — 1st Tuesday
        g = nth_weekday_of_month(yy, mm, WD["tuesday"], 1)
        if g >= today:
            add_row(rows, g.isoformat(), "Hobby Hangs: Game Night", "Games", start_time="19:00", end_time="21:00", event_url=BASE_URL + "#events")

    # We do NOT generate “Drink and Draw Every other Wednesday…”
    # because it requires an anchor date (they say to use Meetup).
    return rows

def dedupe(rows):
    seen = set()
    out = []
    for r in rows:
        key = (
            r["date"],
            r["title"].strip().lower(),
            r["venue"].strip().lower(),
            r.get("start_time",""),
            r.get("event_url",""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    out.sort(key=lambda x: (x["date"], x["start_time"], x["title"].lower()))
    return out

def main():
    r = requests.get(BASE_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    today = dt.date.today()

    special = scrape_special_events(soup)
    recurring = generate_recurring_events(today, MONTHS_AHEAD)

    rows = dedupe(special + recurring)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows -> {OUT}")

if __name__ == "__main__":
    main()
