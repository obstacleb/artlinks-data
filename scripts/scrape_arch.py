#!/usr/bin/env python3
"""
Scrape ARCH Art Supplies workshops page and output arch_events.csv
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

FIELDS = [
    "date","venue","title","category","start_time","end_time",
    "price_text","event_url","instagram_url","is_museum","museum_name","notes","source",
]

VENUE = "ARCH Art Supplies"

MONTHS = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}

@dataclass
class ParsedTimeRange:
    start_hhmm: str
    end_hhmm: str

DATE_LINE_RE = re.compile(
    r"^(?P<weekday>[A-Za-z]+),\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<times>[^,]+),\s+(?P<price>.+?)\s*$"
)

def _get_soup(url: str) -> BeautifulSoup:
    r = requests.get(url, headers={"User-Agent": "artlinks-data/1.0"}, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _infer_year(month: int, day: int, today: date) -> int:
    y = today.year
    if month < max(1, today.month - 2):
        y += 1
    return y

def _parse_time_token(token: str, meridiem_hint: Optional[str] = None) -> tuple[int, int, str]:
    t = _clean(token).lower()
    m = None
    if t.endswith("am"): m = "am"; t = t[:-2]
    elif t.endswith("pm"): m = "pm"; t = t[:-2]
    if m is None: m = meridiem_hint
    if ":" in t:
        hh_s, mm_s = t.split(":", 1)
        hh, mm = int(hh_s), int(mm_s)
    else:
        hh, mm = int(t), 0
    if m == "am" and hh == 12: hh = 0
    elif m == "pm" and hh != 12: hh += 12
    return hh, mm, m or ""

def _parse_time_range(times_text: str) -> Optional[ParsedTimeRange]:
    t = _clean(times_text).lower()
    if "-" not in t:
        return None
    start_raw, end_raw = [x.strip() for x in t.split("-", 1)]
    end_h, end_m, end_mer_used = _parse_time_token(end_raw)
    if not end_mer_used:
        return None
    start_h, start_m, _ = _parse_time_token(start_raw, meridiem_hint=end_mer_used)
    return ParsedTimeRange(
        start_hhmm=f"{start_h:02d}:{start_m:02d}",
        end_hhmm=f"{end_h:02d}:{end_m:02d}",
    )

def _find_rte_container(soup: BeautifulSoup):
    rte = soup.select_one(".rte")
    if rte:
        return rte
    return soup.select_one("main") or soup.body

def scrape() -> list[dict]:
    soup = _get_soup(ARCH_WORKSHOPS_URL)
    rte = _find_rte_container(soup)

    signup_links = [
        a for a in rte.find_all("a")
        if _clean(a.get_text()).lower() == "sign up" and a.get("href")
    ]

    today = date.today()
    events: list[dict] = []

    for a in signup_links:
        event_url = urljoin(ARCH_WORKSHOPS_URL, a["href"])

        prev_texts = []
        for node in a.find_all_previous(string=True, limit=60):
            txt = _clean(str(node))
            if not txt or txt.lower() in {"sign up"}:
                continue
            prev_texts.append(txt)

        date_line = None
        date_line_idx = None
        for idx, txt in enumerate(prev_texts):
            if DATE_LINE_RE.match(txt):
                date_line = txt
                date_line_idx = idx
                break
        if not date_line or date_line_idx is None:
            continue

        title = None
        for j in range(date_line_idx + 1, len(prev_texts)):
            candidate = prev_texts[j]
            if len(candidate) > 160 or DATE_LINE_RE.match(candidate):
                continue
            title = candidate
            break
        if not title:
            continue

        notes_bits = []
        for k in range(date_line_idx):
            n = prev_texts[k]
            if len(n) > 200 or n.lower() in {"image","previous slide","next slide"} or DATE_LINE_RE.match(n):
                continue
            notes_bits.append(n)
        notes = _clean(" • ".join(reversed(notes_bits)))

        m = DATE_LINE_RE.match(date_line)
        assert m is not None
        month = MONTHS.get(m.group("month").lower())
        if not month:
            continue
        day_num = int(m.group("day"))
        year = _infer_year(month, day_num, today)
        event_date = date(year, month, day_num).isoformat()

        tr = _parse_time_range(m.group("times"))
        start_time = tr.start_hhmm if tr else ""
        end_time = tr.end_hhmm if tr else ""

        events.append({
            "date": event_date,
            "venue": VENUE,
            "title": title,
            "category": "Workshop",
            "start_time": start_time,
            "end_time": end_time,
            "price_text": _clean(m.group("price")),
            "event_url": event_url,
            "instagram_url": "",
            "is_museum": "false",
            "museum_name": "",
            "notes": notes,
            "source": "ARCH",
        })

    dedup = {}
    for e in events:
        dedup[e["event_url"]] = e
    return list(dedup.values())

if __name__ == "__main__":
    rows = scrape()
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["date"], x["start_time"], x["title"])):
            w.writerow(r)
    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")
