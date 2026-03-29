#!/usr/bin/env python3
"""
Scrape Mission Comics & Art upcoming events from Mission Local venue feed.
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

FIELDS = [
    "date","venue","title","category","start_time","end_time",
    "price_text","event_url","instagram_url","is_museum","museum_name","notes","source",
]

UA = "artlinks-data/1.0 (+https://github.com/obstacleb/artlinks-data)"
VENUE_DEFAULT = "Mission Comics & Art"

MONTH_YEAR_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})$",
    re.I
)
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

def _infer_category(title: str, notes: str) -> str:
    t = (title or "").lower()
    n = (notes or "").lower()
    if "signing" in t or "signing" in n: return "Signing"
    if "party" in t or "party" in n: return "Party"
    if "workshop" in t or "workshop" in n: return "Workshop"
    if "zine" in t or "zine" in n: return "Zine"
    return "Comics"

def _infer_price(notes: str) -> str:
    n = (notes or "").lower()
    if "tickets are free" in n or "ticket is free" in n or "free, but" in n or "free but" in n:
        return "Free"
    return ""

def _find_next_link(soup: BeautifulSoup) -> Optional[str]:
    a = soup.select_one("a.tribe-events-c-nav__next, a.tribe-events-nav-next a, a[rel='next']")
    if a and a.get("href"):
        return urljoin(BASE, a["href"])
    for cand in soup.find_all("a", href=True):
        if _clean(cand.get_text()).lower() == "next events":
            return urljoin(BASE, cand["href"])
    return None

def _extract_events_from_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    current_year = None
    events: list[dict] = []

    for el in soup.find_all(["h3", "h4"]):
        if el.name == "h3":
            txt = _clean(el.get_text())
            m = MONTH_YEAR_RE.match(txt)
            if m:
                current_year = int(m.group(2))
            continue

        if el.name == "h4":
            a = el.find("a", href=True)
            title = _clean(a.get_text()) if a else _clean(el.get_text())
            if not title:
                continue
            event_url = urljoin(BASE, a["href"]) if a else ""

            featured_line = None
            cursor = el
            for _ in range(25):
                cursor = cursor.find_next(string=True)
                if not cursor:
                    break
                line = _clean(str(cursor))
                if line and FEATURED_TIME_RE.search(line):
                    featured_line = line
                    break

            if not featured_line:
                continue

            fm = FEATURED_TIME_RE.search(featured_line)
            assert fm is not None

            month = fm.group("month")
            day = int(fm.group("day"))
            start_raw = fm.group("start")
            end_raw = fm.group("end")
            year = current_year or datetime.now().year

            dt_start = dateparser.parse(f"{month} {day} {year} {start_raw}")
            if not dt_start:
                continue
            dt_end = dateparser.parse(f"{month} {day} {year} {end_raw}")

            start_time = dt_start.strftime("%H:%M")
            end_time = dt_end.strftime("%H:%M") if dt_end else ""

            notes = ""
            found_venue_line = False
            cursor2 = el
            for _ in range(60):
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

            events.append({
                "date": dt_start.date().isoformat(),
                "venue": VENUE_DEFAULT,
                "title": title,
                "category": _infer_category(title, notes),
                "start_time": start_time,
                "end_time": end_time,
                "price_text": _infer_price(notes),
                "event_url": event_url,
                "instagram_url": "",
                "is_museum": "false",
                "museum_name": "",
                "notes": notes,
                "source": "Mission Comics & Art",
            })

    dedup = {}
    for e in events:
        key = (e["event_url"], e["date"], e["title"])
        dedup[key] = e
    return list(dedup.values())

def scrape() -> list[dict]:
    url = START_URL
    seen = set()
    all_events: list[dict] = []

    for _ in range(10):
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

    all_events.sort(key=lambda r: (r["date"], r["start_time"], r["title"]))
    return all_events

if __name__ == "__main__":
    rows = scrape()
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")
