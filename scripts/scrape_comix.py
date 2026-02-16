#!/usr/bin/env python3
"""
Scrape Comix Experience Events (Squarespace) and output comix_events.csv

Index:
  https://www.comixexperience.com/events  :contentReference[oaicite:1]{index=1}

We scrape the index for event URLs, then visit each event page and extract:
- title
- start date/time and optional end time/date (best-effort)
- venue/location (Comix Experience vs Outpost)
- categories (from "Posted in ...")
- online/live stream hint (if category includes "Live Stream")

CSV columns:
  date, venue, title, category, start_time, end_time, price_text, event_url,
  is_museum, source, event_type, notes, museum_name
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

BASE = "https://www.comixexperience.com"
INDEX_URL = "https://www.comixexperience.com/events"
OUTPUT_CSV = "comix_events.csv"

SOURCE = "comix"
EVENT_TYPE = "comix"
IS_MUSEUM = "false"
MUSEUM_NAME = ""

UA = "artlinks-data/1.0 (+https://github.com/obstacleb/artlinks-data)"


# Event permalinks typically look like:
# /events/2026/1/1/january-2026s-graphic-novel-club-events  :contentReference[oaicite:2]{index=2}
EVENT_PATH_RE = re.compile(r"^/events/\d{4}/\d{1,2}/\d{1,2}/")

# Matches lines like:
# "Thursday, January 1, 2026 10:00 AM 10:00"  :contentReference[oaicite:3]{index=3}
DATETIME_LINE_RE = re.compile(
    r"(?P<weekday>[A-Za-z]+),\s+"
    r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\s+"
    r"(?P<time>\d{1,2}:\d{2}\s+[AP]M)"
)

# Matches time range line like:
# "10:00 AM 6:00 PM 10:00 18:00"  :contentReference[oaicite:4]{index=4}
TIME_RANGE_LINE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}\s+[AP]M)\s+"
    r"(?P<end>\d{1,2}:\d{2}\s+[AP]M)"
)


def _get(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


def _soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(_get(url), "html.parser")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _to_24h_hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


@dataclass
class ParsedEvent:
    title: str
    start_date: date
    start_time: str
    end_time: str
    venue: str
    category: str
    notes: str
    url: str


def _extract_event_urls(index_html: str) -> list[str]:
    soup = BeautifulSoup(index_html, "html.parser")
    urls = set()

    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if not href.startswith("/events/"):
            continue
        if not EVENT_PATH_RE.match(href):
            continue
        # skip category pages like /events/category/...
        if "/category/" in href:
            continue
        # normalize
        urls.add(urljoin(BASE, href.split("?")[0]))

    return sorted(urls)


def _pick_main_text(soup: BeautifulSoup) -> str:
    # Try to focus on main content area; Squarespace often has <main>
    main = soup.find("main")
    if main:
        return _clean(main.get_text(" ", strip=True))
    return _clean(soup.get_text(" ", strip=True))


def _extract_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1 and _clean(h1.get_text()):
        return _clean(h1.get_text())
    # fallback to <title>
    t = soup.find("title")
    return _clean(t.get_text()) if t else ""


def _extract_categories(soup: BeautifulSoup) -> list[str]:
    """
    Event pages contain "Posted in ..." with category links. :contentReference[oaicite:5]{index=5}
    We'll grab those anchor texts near that phrase, best-effort.
    """
    text = soup.get_text("\n")
    # Find "Posted in" block
    # We'll locate the line containing "Posted in" and read nearby anchors.
    cats: list[str] = []

    # More reliable: search for any anchor href that includes "/events/category/"
    for a in soup.select('a[href*="/events/category/"]'):
        c = _clean(a.get_text())
        if c:
            cats.append(c)

    # de-dupe preserve order
    seen = set()
    out = []
    for c in cats:
        if c.lower() in seen:
            continue
        seen.add(c.lower())
        out.append(c)
    return out


def _choose_category(cats: list[str]) -> str:
    # Prefer something simple and useful for your filters
    # (You can remap later in client if you want.)
    priority = ["Signings", "Graphic Novel Club", "Party", "Free Comic Book Day", "Live Stream"]
    for p in priority:
        for c in cats:
            if c.lower() == p.lower():
                return p
    return cats[0] if cats else "Comics"


def _extract_venue(soup: BeautifulSoup) -> str:
    """
    Location lines commonly include:
      "Comix Experience 305 Divisadero Street San Francisco, CA, 94117" :contentReference[oaicite:6]{index=6}
    We'll look for "Comix Experience" or "Outpost" in visible text.
    """
    txt = _pick_main_text(soup)
    if "Comix Experience Outpost" in txt:
        return "Comix Experience Outpost"
    if "Comix Experience" in txt:
        return "Comix Experience"
    return "Comix Experience"


def _extract_notes_and_price(soup: BeautifulSoup) -> tuple[str, str]:
    """
    Price isn't consistently structured; many events are free.
    We'll set price_text="Free" if the text strongly indicates it, else "".
    """
    txt = _pick_main_text(soup).lower()
    price_text = ""
    if "attendance is free" in txt or "free, and open to all" in txt or "free and open to all" in txt:
        price_text = "Free"
    notes = ""
    # Light notes: mark online if Live Stream mentioned
    if "live stream" in txt or "livestream" in txt:
        notes = "Live Stream / Online"
    return notes, price_text


def _extract_datetime(soup: BeautifulSoup) -> tuple[Optional[datetime], Optional[datetime], str, str]:
    """
    Handle two common Squarespace event formats seen on Comix Experience pages:

    A) Start/end datetime lines:
       "Thursday, January 1, 2026 10:00 AM 10:00"
       "Saturday, January 31, 2026 6:00 PM 18:00"  :contentReference[oaicite:7]{index=7}

    B) Date line + time range line:
       "Saturday, May 3, 2025"
       "10:00 AM 6:00 PM 10:00 18:00"  :contentReference[oaicite:8]{index=8}
    """
    raw = soup.get_text("\n")
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    # A) find datetime lines
    dt_matches = []
    for l in lines:
        m = DATETIME_LINE_RE.search(l)
        if m:
            # parse "Month day, year time"
            dt_str = f"{m.group('month')} {m.group('day')}, {m.group('year')} {m.group('time')}"
            try:
                dt = dateparser.parse(dt_str)
                dt_matches.append(dt)
            except Exception:
                pass

    if dt_matches:
        start_dt = dt_matches[0]
        end_dt = dt_matches[1] if len(dt_matches) > 1 else None
        start_time = _to_24h_hhmm(start_dt)
        end_time = _to_24h_hhmm(end_dt) if end_dt else ""
        return start_dt, end_dt, start_time, end_time

    # B) find date-only line with year
    date_only = None
    for l in lines:
        # weekday optional; dateparser can handle both
        if re.search(r"\b\d{4}\b", l) and re.search(r"\b[A-Za-z]+\b", l) and re.search(r"\b\d{1,2}\b", l):
            # Heuristic: a date-only line often starts with weekday and contains a comma after weekday
            # Example: "Saturday, May 3, 2025" :contentReference[oaicite:9]{index=9}
            if "," in l and any(m in l for m in ["January", "February", "March", "April", "May", "June",
                                                 "July", "August", "September", "October", "November", "December"]):
                try:
                    d = dateparser.parse(l)
                    if d:
                        date_only = d.date()
                        break
                except Exception:
                    pass

    # find time range line
    start_time = ""
    end_time = ""
    if date_only:
        for l in lines:
            m = TIME_RANGE_LINE_RE.search(l)
            if m:
                try:
                    st = dateparser.parse(m.group("start"))
                    et = dateparser.parse(m.group("end"))
                    if st and et:
                        start_time = st.strftime("%H:%M")
                        end_time = et.strftime("%H:%M")
                        break
                except Exception:
                    pass
        # Construct start datetime (date + start_time if present)
        if start_time:
            start_dt = datetime.combine(date_only, datetime.strptime(start_time, "%H:%M").time())
        else:
            start_dt = datetime.combine(date_only, datetime.min.time())
        return start_dt, None, start_time, end_time

    return None, None, "", ""


def _parse_event(url: str) -> Optional[ParsedEvent]:
    soup = _soup(url)
    title = _extract_title(soup)
    if not title:
        return None

    start_dt, end_dt, start_time, end_time = _extract_datetime(soup)
    if not start_dt:
        return None

    cats = _extract_categories(soup)
    category = _choose_category(cats)
    venue = _extract_venue(soup)
    notes, price_text = _extract_notes_and_price(soup)

    # If end date exists and differs, add a note so your UI has context.
    if end_dt and end_dt.date() != start_dt.date():
        end_note = f"Runs through {end_dt.date().isoformat()}"
        notes = _clean(" • ".join([n for n in [notes, end_note] if n]))

    return ParsedEvent(
        title=title,
        start_date=start_dt.date(),
        start_time=start_time,
        end_time=end_time,
        venue=venue,
        category=category,
        notes=notes,
        url=url,
    ), price_text


def scrape() -> list[dict]:
    index_html = _get(INDEX_URL)
    urls = _extract_event_urls(index_html)

    today = date.today()
    earliest = today - timedelta(days=365)   # keep last year
    latest = today + timedelta(days=370)     # + ~1 year

    out_rows = []
    for u in urls:
        try:
            parsed, price_text = _parse_event(u)
            if not parsed:
                continue

            if not (earliest <= parsed.start_date <= latest):
                continue

            out_rows.append({
                "date": parsed.start_date.isoformat(),
                "venue": parsed.venue,
                "title": parsed.title,
                "category": parsed.category,
                "start_time": parsed.start_time,
                "end_time": parsed.end_time,
                "price_text": price_text,
                "event_url": parsed.url,
                "is_museum": IS_MUSEUM,
                "source": SOURCE,
                "event_type": EVENT_TYPE,
                "notes": parsed.notes,
                "museum_name": MUSEUM_NAME,
            })
        except Exception:
            # Never hard fail the whole pipeline on one weird event page
            continue

    # Dedup by URL
    dedup = {}
    for r in out_rows:
        dedup[r["event_url"]] = r
    return sorted(dedup.values(), key=lambda r: (r["date"], r["start_time"], r["title"]))


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
