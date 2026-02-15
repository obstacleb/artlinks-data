#!/usr/bin/env python3
import re
import csv
import sys
from datetime import datetime, date
from urllib.request import Request, urlopen
from urllib.parse import urljoin

from bs4 import BeautifulSoup

URLS = [
    "https://www.sketchboard.co/schedule",
    "https://www.sketchboard.co/calendar",
]

HEADERS = [
    "date","venue","title","category","event_type","start_time","end_time",
    "price_text","is_museum","museum_name","event_url","notes"
]

UA = {"User-Agent": "artlinks-bot/1.1 (github actions)"}

# ---------- HTTP ----------
def fetch_html(url: str) -> str:
    req = Request(url, headers=UA)
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def abs_url(base: str, href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    return urljoin(base, href)

# ---------- DATE/TIME PARSING ----------
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"], start=1
)}
MONTHS_ABBR = {m[:3].lower(): i for m, i in MONTHS.items()}

def today_iso() -> str:
    d = date.today()
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"

def normalize_iso(y: int, m: int, d: int) -> str:
    return f"{y:04d}-{m:02d}-{d:02d}"

def parse_date_any(text: str) -> str:
    """
    Attempts to parse a date from messy block text.
    Supports:
      - YYYY-MM-DD
      - Monday, February 17, 2026
      - Feb 17, 2026 / February 17, 2026
      - Feb 17 (assume year; roll forward if needed)
    """
    t = " ".join((text or "").split())

    # ISO
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", t)
    if m:
        return normalize_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # Weekday, Month DD, YYYY
    m = re.search(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,\s+([A-Za-z]+)\s+(\d{1,2}),\s+(20\d{2})\b", t)
    if m:
        mon = m.group(1).lower()
        day = int(m.group(2))
        yr = int(m.group(3))
        mm = MONTHS.get(mon) or MONTHS_ABBR.get(mon[:3])
        if mm:
            return normalize_iso(yr, mm, day)

    # Month DD, YYYY
    m = re.search(r"\b([A-Za-z]+)\s+(\d{1,2}),\s+(20\d{2})\b", t)
    if m:
        mon = m.group(1).lower()
        day = int(m.group(2))
        yr = int(m.group(3))
        mm = MONTHS.get(mon) or MONTHS_ABBR.get(mon[:3])
        if mm:
            return normalize_iso(yr, mm, day)

    # Month DD (no year)
    m = re.search(r"\b([A-Za-z]+)\s+(\d{1,2})\b", t)
    if m:
        mon = m.group(1).lower()
        day = int(m.group(2))
        mm = MONTHS.get(mon) or MONTHS_ABBR.get(mon[:3])
        if mm:
            # assume current year, but roll into next year if it looks like a "future schedule"
            today = date.today()
            yr = today.year
            guess = date(yr, mm, day)
            # If guess is > ~9 months in the past, assume it's next year
            if (today - guess).days > 270:
                yr += 1
            return normalize_iso(yr, mm, day)

    return ""

def parse_time_range_any(text: str):
    """
    Returns ("HH:MM","HH:MM") in 24h if possible.
    Accepts:
      - 6:30 PM – 8:30 PM
      - 6:30pm 8:30pm
      - 18:00–21:00
    """
    t = " ".join((text or "").split())

    # 24h ranges: 18:00–21:00 or 18:00-21:00
    m = re.search(r"\b(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})\b", t)
    if m:
        return (m.group(1), m.group(2))

    # 12h ranges: 6:30 PM – 8:30 PM
    m = re.search(r"\b(\d{1,2}:\d{2})\s*([AP]M)\s*[–-]?\s*(\d{1,2}:\d{2})\s*([AP]M)\b", t, re.I)
    if m:
        s = to_24h(m.group(1), m.group(2))
        e = to_24h(m.group(3), m.group(4))
        return (s, e)

    return ("","")

def to_24h(hhmm: str, ampm: str) -> str:
    h, m = hhmm.split(":")
    h = int(h)
    m = int(m)
    ap = (ampm or "").strip().lower()
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}"

# ---------- CLASSIFICATION ----------
def classify_event(title: str, block_text: str):
    """
    Returns dict with category/venue/price defaults, or None to ignore.
    """
    t = (title or "").strip()
    b = (block_text or "").strip()
    tl = t.lower()
    bl = b.lower()

    # Figure Drawing bucket (broad match)
    figure_terms = [
        "figure drawing", "life drawing", "figure session", "model session",
        "open studio (figure)", "open studio figure", "gesture drawing"
    ]
    if any(term in tl or term in bl for term in figure_terms) or ("figure" in tl and "drawing" in tl):
        return {
            "category": "Figure Drawing",
            "venue": "Sketchboard (Figure)",
            "price_text": "",
        }

    # Drink & Draw bucket
    if ("drink" in tl and "draw" in tl) or ("drink" in bl and "draw" in bl) or ("madrone" in tl) or ("madrone" in bl):
        return {
            "category": "Drink & Draw",
            "venue": "Sketchboard @ Madrone Art Bar",
            "price_text": "$15 cash only (per Sketchboard schedule)",
        }

    return None

def extract_price(block_text: str) -> str:
    # grab something like "$15" or "$15 suggested"
    t = " ".join((block_text or "").split())
    m = re.search(r"\$\s*\d+(?:\.\d{2})?(?:\s*(?:suggested|sliding|donation|donate))?", t, re.I)
    if m:
        return m.group(0).replace("  ", " ").strip()
    # common words
    if re.search(r"\bfree\b", t, re.I):
        return "Free"
    return ""

# ---------- SCRAPE ----------
def candidate_blocks(soup: BeautifulSoup):
    """
    We collect a bunch of link-containing blocks and let parsing/classification filter them down.
    This is intentionally tolerant because Sketchboard markup can change.
    """
    blocks = []
    for a in soup.select("a[href]"):
        title = " ".join(a.get_text(" ").split()).strip()
        href = a.get("href", "")
        if not title:
            continue
        # keep links that likely point to Sketchboard pages
        if "sketchboard.co" not in href and not href.startswith("/"):
            continue
        container = a.find_parent()
        if not container:
            continue
        blocks.append((a, container))
    return blocks

def scrape_url(url: str):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    out = []

    for a, container in candidate_blocks(soup):
        title = " ".join(a.get_text(" ").split()).strip()
        href = abs_url(url, a.get("href"))

        block_text = container.get_text("\n", strip=True)

        info = classify_event(title, block_text)
        if not info:
            continue

        date_iso = parse_date_any(block_text)
        if not date_iso:
            # sometimes date is slightly higher up than the immediate parent
            parent2 = container.find_parent()
            if parent2:
                date_iso = parse_date_any(parent2.get_text("\n", strip=True))
        if not date_iso:
            continue

        start_time, end_time = parse_time_range_any(block_text)

        # prefer explicit price if present
        price = extract_price(block_text) or info["price_text"]

        out.append({
            "date": date_iso,
            "venue": info["venue"],
            "title": title,
            "category": info["category"],
            "event_type": "",
            "start_time": start_time,
            "end_time": end_time,
            "price_text": price,
            "is_museum": "no",
            "museum_name": "",
            "event_url": href,
            "notes": f"Auto-imported from {url}",
        })

    return out

def dedupe(events):
    seen = set()
    uniq = []
    for ev in events:
        key = (ev["date"], ev["title"].lower().strip(), ev["start_time"].strip(), ev["category"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(ev)
    uniq.sort(key=lambda x: (x["date"], x["start_time"], x["title"]))
    return uniq

def main():
    all_events = []
    for url in URLS:
        try:
            all_events.extend(scrape_url(url))
        except Exception as e:
            # don't fail the whole run if one page changes; still commit what we have
            sys.stderr.write(f"[warn] scrape failed for {url}: {e}\n")

    events = dedupe(all_events)

    w = csv.DictWriter(sys.stdout, fieldnames=HEADERS)
    w.writeheader()
    for ev in events:
        w.writerow(ev)

if __name__ == "__main__":
    main()
