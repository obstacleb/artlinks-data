#!/usr/bin/env python3
"""
Scrape Comix Experience Events (Squarespace) and output comix_events.csv
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

FIELDS = [
    "date","venue","title","category","start_time","end_time",
    "price_text","event_url","instagram_url","is_museum","museum_name","notes","source",
]

UA = "artlinks-data/1.0 (+https://github.com/obstacleb/artlinks-data)"

EVENT_PATH_RE = re.compile(r"^/events/\d{4}/\d{1,2}/\d{1,2}/")

DATETIME_LINE_RE = re.compile(
    r"(?P<weekday>[A-Za-z]+),\s+"
    r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\s+"
    r"(?P<time>\d{1,2}:\d{2}\s+[AP]M)"
)
TIME_RANGE_LINE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}\s+[AP]M)\s+(?P<end>\d{1,2}:\d{2}\s+[AP]M)"
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

def _extract_event_urls(index_html: str) -> list[str]:
    soup = BeautifulSoup(index_html, "html.parser")
    urls = set()
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if not href.startswith("/events/"):
            continue
        if not EVENT_PATH_RE.match(href):
            continue
        if "/category/" in href:
            continue
        urls.add(urljoin(BASE, href.split("?")[0]))
    return sorted(urls)

def _pick_main_text(soup: BeautifulSoup) -> str:
    main = soup.find("main")
    if main:
        return _clean(main.get_text(" ", strip=True))
    return _clean(soup.get_text(" ", strip=True))

def _extract_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1 and _clean(h1.get_text()):
        return _clean(h1.get_text())
    t = soup.find("title")
    return _clean(t.get_text()) if t else ""

def _extract_categories(soup: BeautifulSoup) -> list[str]:
    cats: list[str] = []
    for a in soup.select('a[href*="/events/category/"]'):
        c = _clean(a.get_text())
        if c:
            cats.append(c)
    seen = set()
    out = []
    for c in cats:
        if c.lower() in seen:
            continue
        seen.add(c.lower())
        out.append(c)
    return out

def _choose_category(cats: list[str]) -> str:
    priority = ["Signings", "Graphic Novel Club", "Party", "Free Comic Book Day", "Live Stream"]
    for p in priority:
        for c in cats:
            if c.lower() == p.lower():
                return p
    return cats[0] if cats else "Comics"

def _extract_venue(soup: BeautifulSoup) -> str:
    txt = _pick_main_text(soup)
    if "Comix Experience Outpost" in txt:
        return "Comix Experience Outpost"
    return "Comix Experience"

def _extract_notes_and_price(soup: BeautifulSoup) -> tuple[str, str]:
    txt = _pick_main_text(soup).lower()
    price_text = ""
    if "attendance is free" in txt or "free, and open to all" in txt or "free and open to all" in txt:
        price_text = "Free"
    notes = ""
    if "live stream" in txt or "livestream" in txt:
        notes = "Live Stream / Online"
    return notes, price_text

def _extract_datetime(soup: BeautifulSoup):
    raw = soup.get_text("\n")
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    dt_matches = []
    for l in lines:
        m = DATETIME_LINE_RE.search(l)
        if m:
            dt_str = f"{m.group('month')} {m.group('day')}, {m.group('year')} {m.group('time')}"
            try:
                dt = dateparser.parse(dt_str)
                dt_matches.append(dt)
            except Exception:
                pass

    if dt_matches:
        start_dt = dt_matches[0]
        end_dt = dt_matches[1] if len(dt_matches) > 1 else None
        return start_dt, end_dt, _to_24h_hhmm(start_dt), (_to_24h_hhmm(end_dt) if end_dt else "")

    date_only = None
    for l in lines:
        if re.search(r"\b\d{4}\b", l) and "," in l and any(
            m in l for m in ["January","February","March","April","May","June",
                              "July","August","September","October","November","December"]
        ):
            try:
                d = dateparser.parse(l)
                if d:
                    date_only = d.date()
                    break
            except Exception:
                pass

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
        if start_time:
            start_dt = datetime.combine(date_only, datetime.strptime(start_time, "%H:%M").time())
        else:
            start_dt = datetime.combine(date_only, datetime.min.time())
        return start_dt, None, start_time, end_time

    return None, None, "", ""

def _parse_event(url: str):
    soup = _soup(url)
    title = _extract_title(soup)
    if not title:
        return None, None

    start_dt, end_dt, start_time, end_time = _extract_datetime(soup)
    if not start_dt:
        return None, None

    cats = _extract_categories(soup)
    category = _choose_category(cats)
    venue = _extract_venue(soup)
    notes, price_text = _extract_notes_and_price(soup)

    if end_dt and end_dt.date() != start_dt.date():
        end_note = f"Runs through {end_dt.date().isoformat()}"
        notes = _clean(" • ".join([n for n in [notes, end_note] if n]))

    row = {
        "date": start_dt.date().isoformat(),
        "venue": venue,
        "title": title,
        "category": category,
        "start_time": start_time,
        "end_time": end_time,
        "price_text": price_text,
        "event_url": url,
        "instagram_url": "",
        "is_museum": "false",
        "museum_name": "",
        "notes": notes,
        "source": "Comix Experience",
    }
    return row, price_text

def scrape() -> list[dict]:
    index_html = _get(INDEX_URL)
    urls = _extract_event_urls(index_html)

    today = date.today()
    earliest = today - timedelta(days=365)
    latest = today + timedelta(days=370)

    out_rows = []
    for u in urls:
        try:
            row, _ = _parse_event(u)
            if not row:
                continue
            event_date = date.fromisoformat(row["date"])
            if not (earliest <= event_date <= latest):
                continue
            out_rows.append(row)
        except Exception:
            continue

    dedup = {}
    for r in out_rows:
        dedup[r["event_url"]] = r
    return sorted(dedup.values(), key=lambda r: (r["date"], r["start_time"], r["title"]))

if __name__ == "__main__":
    rows = scrape()
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")
