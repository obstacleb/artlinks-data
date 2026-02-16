#!/usr/bin/env python3
"""
Scrape ARCH Art Supplies workshops page and output arch_events.csv

Source page:
  https://shop.archsupplies.com/pages/workshops

Output CSV columns (matches your client-side Event object fields):
  date, venue, title, category, start_time, end_time, price_text, event_url,
  is_museum, source, event_type, notes, museum_name
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ARCH_WORKSHOPS_URL = "https://shop.archsupplies.com/pages/workshops"
OUTPUT_CSV = "arch_events.csv"

# Fixed venue (you can adjust to your preferred label)
VENUE = "ARCH Art Supplies"
SOURCE = "arch"
CATEGORY = "Workshops"
EVENT_TYPE = "workshop"

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass
class ParsedTimeRange:
    start_hhmm: str  # "HH:MM" 24h
    end_hhmm: str    # "HH:MM" 24h


DATE_LINE_RE = re.compile(
    r"^(?P<weekday>[A-Za-z]+),\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<times>[^,]+),\s+(?P<price>.+?)\s*$"
)


def _get_soup(url: str) -> BeautifulSoup:
    headers = {
        "User-Agent": "artlinks-data/1.0 (+https://github.com/obstacleb/artlinks-data)"
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _infer_year(month: int, day: int, today: date) -> int:
    """
    Workshops page does not include a year. Use a simple rollover heuristic:
    - default current year
    - if the month is "far behind" current month (e.g. January while today is December), roll forward.
    """
    y = today.year
    # If month is more than 2 months behind current month, assume it's next year.
    # (Keeps Jan/Feb from being interpreted as past when we’re in late year.)
    if month < max(1, today.month - 2):
        y += 1
    return y


def _parse_time_token(token: str, meridiem_hint: Optional[str] = None) -> tuple[int, int, str]:
    """
    token examples: "6:30pm", "11am", "1", "1pm", "8:30"
    Returns (hour24, minute, meridiem_used)
    """
    t = _clean(token).lower()

    # detect explicit meridiem
    m = None
    if t.endswith("am"):
        m = "am"
        t = t[:-2]
    elif t.endswith("pm"):
        m = "pm"
        t = t[:-2]

    if m is None:
        m = meridiem_hint  # may still be None

    if ":" in t:
        hh_s, mm_s = t.split(":", 1)
        hh = int(hh_s)
        mm = int(mm_s)
    else:
        hh = int(t)
        mm = 0

    if m == "am":
        if hh == 12:
            hh = 0
    elif m == "pm":
        if hh != 12:
            hh += 12

    meridiem_used = m or ""  # empty if truly unknown
    return hh, mm, meridiem_used


def _parse_time_range(times_text: str) -> Optional[ParsedTimeRange]:
    """
    times_text examples:
      "6:30-8:30pm"
      "11am-1pm"
      "12pm-4pm"
      "11am-2pm"
    """
    t = _clean(times_text).lower()
    if "-" not in t:
        return None

    start_raw, end_raw = [x.strip() for x in t.split("-", 1)]

    # Determine end meridiem first (common pattern)
    end_mer = "pm" if end_raw.endswith("pm") else ("am" if end_raw.endswith("am") else None)

    # Parse end (may contain meridiem)
    end_h, end_m, end_mer_used = _parse_time_token(end_raw, meridiem_hint=None)
    if not end_mer_used:
        # if end has no meridiem, we can't reliably infer
        return None

    # Parse start, hint with end meridiem if missing
    start_h, start_m, _ = _parse_time_token(start_raw, meridiem_hint=end_mer_used)

    return ParsedTimeRange(
        start_hhmm=f"{start_h:02d}:{start_m:02d}",
        end_hhmm=f"{end_h:02d}:{end_m:02d}",
    )


def _find_rte_container(soup: BeautifulSoup):
    # Shopify "page" content is usually in an element with class 'rte' or within main content.
    rte = soup.select_one(".rte")
    if rte:
        return rte
    main = soup.select_one("main") or soup.body
    return main


def scrape() -> list[dict]:
    soup = _get_soup(ARCH_WORKSHOPS_URL)
    rte = _find_rte_container(soup)

    # Find signup links inside the workshops content.
    # (On this page, the visible CTA text is exactly "SIGN UP".) :contentReference[oaicite:1]{index=1}
    signup_links = []
    for a in rte.find_all("a"):
        if _clean(a.get_text()).lower() == "sign up" and a.get("href"):
            signup_links.append(a)

    today = date.today()
    events: list[dict] = []

    for a in signup_links:
        event_url = urljoin(ARCH_WORKSHOPS_URL, a["href"])

        # Walk backwards through text nodes to find:
        # - the first line that matches "Weekday, Month Day, time-time, $price"
        # - the title immediately before that
        prev_texts = []
        for node in a.find_all_previous(string=True, limit=60):
            txt = _clean(str(node))
            if not txt:
                continue
            # Skip obvious noise
            if txt.lower() in {"sign up"}:
                continue
            prev_texts.append(txt)

        # prev_texts is in reverse document order (closest first)
        date_line = None
        date_line_idx = None
        for idx, txt in enumerate(prev_texts):
            if DATE_LINE_RE.match(txt):
                date_line = txt
                date_line_idx = idx
                break
        if not date_line or date_line_idx is None:
            # If the structure changes, skip rather than emitting bad rows
            continue

        # Title should be the next “meaningful” text after the date_line when going backwards
        title = None
        for j in range(date_line_idx + 1, len(prev_texts)):
            candidate = prev_texts[j]
            # Heuristic: titles are not huge paragraphs and usually don't contain commas+price pattern
            if len(candidate) > 160:
                continue
            if DATE_LINE_RE.match(candidate):
                continue
            title = candidate
            break
        if not title:
            continue

        # Notes are any short-ish lines between date_line and the link (in reverse order that’s idx 0..date_line_idx-1)
        notes_bits = []
        for k in range(0, date_line_idx):
            n = prev_texts[k]
            # Avoid capturing navigation-ish junk
            if len(n) > 200:
                continue
            if n.lower() in {"image", "previous slide", "next slide"}:
                continue
            # If it looks like another title, ignore (shouldn't happen but safe)
            if DATE_LINE_RE.match(n):
                continue
            notes_bits.append(n)
        notes_bits = list(reversed(notes_bits))
        notes = _clean(" • ".join(notes_bits))

        m = DATE_LINE_RE.match(date_line)
        assert m is not None
        month_name = m.group("month").lower()
        month = MONTHS.get(month_name)
        if not month:
            continue
        day_num = int(m.group("day"))
        year = _infer_year(month, day_num, today)
        event_date = date(year, month, day_num).isoformat()

        times_text = m.group("times")
        tr = _parse_time_range(times_text)
        start_time = tr.start_hhmm if tr else ""
        end_time = tr.end_hhmm if tr else ""

        price_text = _clean(m.group("price"))

        events.append(
            {
                "date": event_date,
                "venue": VENUE,
                "title": title,
                "category": CATEGORY,
                "start_time": start_time,
                "end_time": end_time,
                "price_text": price_text,
                "event_url": event_url,
                "is_museum": "false",
                "source": SOURCE,
                "event_type": EVENT_TYPE,
                "notes": notes,
                "museum_name": "",
            }
        )

    # Deduplicate by URL (Shopify product URL is stable)
    dedup = {}
    for e in events:
        dedup[e["event_url"]] = e
    return list(dedup.values())


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
        for r in sorted(rows, key=lambda x: (x["date"], x["start_time"], x["title"])):
            w.writerow(r)


if __name__ == "__main__":
    rows = scrape()
    write_csv(rows, OUTPUT_CSV)
    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")
