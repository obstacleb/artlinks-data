#!/usr/bin/env python3
"""
Scrape Mission Comics & Art upcoming events from Mission Local venue feed
and output missioncomics_events.csv.

Venue page (lists upcoming events with month headers/times):
  https://missionlocal.org/venue/mission-comics-and-art/  :contentReference[oaicite:1]{index=1}

CSV columns:
  date, venue, title, category, start_time, end_time, price_text, event_url,
  is_museum, source, event_type, notes, museum_name
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

START_URL = "https://missionlocal.org/venue/mission-comics-and-art/"
BASE = "https://missionlocal.org"
OUTPUT_CSV = "missioncomics_events.csv"

SOURCE = "missioncomics"
VENUE_DEFAULT = "Mission Comics & Art"
CATEGORY_DEFAULT = "Comics"
EVENT_TYPE = "comic_event"


UA = "artlinks-data/1.0 (+https://github.com/obstacleb/artlinks-data)"

MONTH_YEAR_RE = re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})$", re.I)

# Example line:
# "Featured March 12 @ 4:00 pm - 6:00 pm"  :contentReference[oaicite:2]{index=2}
FEATURED_TIME_RE = re.compile(
    r"\bFeatured\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})\s+@\s+"
    r"(?P<start>\d{1,2}:\d{2}\s*(?:am|pm))\s*-\s*(?P<end>\d{1,2}:\d{2}\s*(?:am|pm))",
    re.I
)

def _get(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _to_hhmm(t: str) -> str:
    dt = dateparser.parse(t)
    return dt.strftime("%H:%M") if dt else ""

def _infer_category(title: str, notes: str) -> str:
    t = (title or "").lower()
    n = (notes or "").lower()
    if "signing" in t or "signing" in n:
        return "Signing"
    if "party" in t or "party" in n:
        return "Party"
    if "workshop" in t or "workshop" in n:
        return "Workshop"
    if "zine" in t or "zine" in n:
        return "Zine"
    return CATEGORY_DEFAULT

def _infer_price(notes: str) -> str:
    n = (notes or "").lower()
    if "tickets are free" in n or "ticket is free" in n or "free" in n:
        # keep it conservative: only mark Free if strongly suggested
        if "tickets are free" in n or "ticket is free" in n or "free, but" in n or "free but" in n:
            return "Free"
    return ""

def _find_next_link(soup: BeautifulSoup) -> Optional[str]:
    # Try common Tribe Events nav classes, then fallback to anchor text match.
    a = soup.select_one("a.tribe-events-c-nav__next, a.tribe-events-nav-next a, a[rel='next']")
    if a and a.get("href"):
        return urljoin(BASE, a["href"])

    for cand in soup.find_all("a", href=True):
        if _clean(cand.get_text()).lower() == "next events":
            return urljoin(BASE, cand["href"])
    return None

def _extract_events_from_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    # Track the current "Month YYYY" header as we walk the DOM.
    current_month = None
    current_year = None

    events: list[dict] = []

    # We walk through headings in order: month header is typically h3, event title is h4 with an <a>.
    # If structure shifts, we still have the "Featured Month Day @ time - time" line to anchor date/time.
    for el in soup.find_all(["h3", "h4"]):
        if el.name == "h3":
            txt = _clean(el.get_text())
            m = MONTH_YEAR_RE.match(txt)
            if m:
                current_month = m.group(1)
                current_year = int(m.group(2))
            continue

        # h4: event title + link
        if el.name == "h4":
            a = el.find("a", href=True)
            title = _clean(a.get_text()) if a else _clean(el.get_text())
            if not title:
                continue
            event_url = urljoin(BASE, a["href"]) if a else ""

            # Find the nearby "Featured ..." time line after the title.
            featured_line = None
            cursor = el
            for _ in range(0, 25):
                cursor = cursor.find_next(string=True)
                if not cursor:
                    break
                line = _clean(str(cursor))
                if not line:
                    continue
                if FEATURED_TIME_RE.search(line):
                    featured_line = line
                    break

            if not featured_line:
                # If no time line, skip (avoid emitting bad dates)
                continue

            fm = FEATURED_TIME_RE.search(featured_line)
            assert fm is not None

            month = fm.group("month")
            day = int(fm.group("day"))
            start_raw = fm.group("start")
            end_raw = fm.group("end")

            # Prefer the year from the nearest Month-Year header; fallback to parsing year from page context.
            year = current_year
            if year is None:
                # last resort: assume current year
                year = datetime.now().year

            # Build a date
            dt_start = dateparser.parse(f"{month} {day} {year} {start_raw}")
            if not dt_start:
                continue
            dt_end = dateparser.parse(f"{month} {day} {year} {end_raw}")

            start_time = dt_start.strftime("%H:%M")
            end_time = dt_end.strftime("%H:%M") if dt_end else ""

            # Notes: grab the first paragraph-ish text after venue line.
            # We'll walk forward a bit and pick the first "long-ish" sentence.
            notes = ""
            venue = VENUE_DEFAULT
            found_venue_line = False
            cursor2 = el
            for _ in range(0, 60):
                cursor2 = cursor2.find_next(string=True)
                if not cursor2:
                    break
                line = _clean(str(cursor2))
                if not line:
                    continue
                if line.startswith(VENUE_DEFAULT):
                    found_venue_line = True
                    continue
                if found_venue_line and len(line) > 40:
                    notes = line
                    break

            category = _infer_category(title, notes)
            price_text = _infer_price(notes)

            events.append({
                "date": dt_start.date().isoformat(),
                "venue": venue,
                "title": title,
                "category": category,
                "start_time": start_time,
                "end_time": end_time,
                "price_text": price_text,
                "event_url": event_url,
                "is_museum": "false",
                "source": SOURCE,
                "event_type": EVENT_TYPE,
                "notes": notes,
                "museum_name": "",
            })

    # Dedup by URL+date+title
    dedup = {}
    for e in events:
        key = (e["event_url"], e["date"], e["title"])
        dedup[key] = e
    return list(dedup.values())

def scrape() -> list[dict]:
    url = START_URL
    seen = set()
    all_events: list[dict] = []

    # Follow "Next Events" pages if the site provides them
    for _ in range(0, 10):
        if url in seen:
            break
        seen.add(url)

        html = _get(url)
        all_events.extend(_extract_events_from_page(html))

        soup = BeautifulSoup(html, "html.parser")
        nxt = _find_next_link(soup)
        if not nxt:
            break
        url = nxt

    # Sort
    all_events.sort(key=lambda r: (r["date"], r["start_time"], r["title"]))
    return all_events

def write_csv(rows: list[dict], path: str) -> None:
    fieldnames = [
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
        "event_type",
        "notes",
        "museum_name",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

if __name__ == "__main__":
    rows = scrape()
    write_csv(rows, OUTPUT_CSV)
    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")
