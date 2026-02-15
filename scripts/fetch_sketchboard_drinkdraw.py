#!/usr/bin/env python3
import re
import csv
import sys
from datetime import datetime
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

SCHEDULE_URL = "https://www.sketchboard.co/schedule"

HEADERS = [
    "date","venue","title","category","event_type","start_time","end_time",
    "price_text","is_museum","museum_name","event_url","notes"
]

UA = {"User-Agent": "artlinks-bot/1.0 (github actions)"}

def fetch_html(url: str) -> str:
    req = Request(url, headers=UA)
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def parse_long_date(s: str) -> str:
    # e.g. "Tuesday, February 17, 2026"
    dt = datetime.strptime(s.strip(), "%A, %B %d, %Y")
    return dt.strftime("%Y-%m-%d")

def parse_time_range(text: str):
    # e.g. "6:30 PM 8:30 PM"
    t = " ".join(text.split())
    m = re.search(r"(\d{1,2}:\d{2}\s*[AP]M)\s+(\d{1,2}:\d{2}\s*[AP]M)", t, re.I)
    if not m:
        return ("","")
    start = m.group(1).upper().replace(" ", "")
    end = m.group(2).upper().replace(" ", "")
    return (start, end)

def abs_url(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://www.sketchboard.co" + href
    return "https://www.sketchboard.co/" + href.lstrip("/")

def classify_event(title: str, block_text: str):
    """
    Returns (category, venue_override, price_override) or (None, None, None) if we ignore it.
    We keep this modular so you can add other venue rules later.
    """
    t = (title or "").lower()
    b = (block_text or "").lower()

    # --- FIGURE DRAWING ---
    figure_terms = ["figure", "life drawing", "model session", "open studio (figure)", "gesture"]
    if any(term in t or term in b for term in figure_terms):
        return ("Figure Drawing", "Sketchboard (Figure Session)", "")

    # --- DRINK & DRAW ---
    # Conservative rules: include “Madrone” and any literal "drink & draw"
    if "madrone" in t or "madrone" in b or ("drink" in t and "draw" in t) or ("drink" in b and "draw" in b):
        return ("Drink & Draw", "Sketchboard @ Madrone Art Bar", "$15 CASH ONLY @ the door (per Sketchboard schedule)")

    return (None, None, None)

def main():
    html = fetch_html(SCHEDULE_URL)
    soup = BeautifulSoup(html, "html.parser")

    events = []

    # Heuristic: find links that look like event titles, then inspect nearby text
    for a in soup.select("a[href]"):
        title = " ".join(a.get_text(" ").split()).strip()
        href = abs_url(a.get("href"))

        if not title or "View Event" in title:
            continue
        if "sketchboard.co" not in href:
            continue

        container = a.find_parent()
        if not container:
            continue

        block_text = container.get_text("\n", strip=True)

        # Need a full weekday-style date somewhere in the block
        dm = re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+[A-Za-z]+\s+\d{1,2},\s+\d{4}", block_text)
        if not dm:
            continue

        try:
            date_iso = parse_long_date(dm.group(0))
        except Exception:
            continue

        # Time range if present
        start_time, end_time = ("","")
        tm = re.search(r"\d{1,2}:\d{2}\s*[AP]M\s+\d{1,2}:\d{2}\s*[AP]M", block_text, re.I)
        if tm:
            start_time, end_time = parse_time_range(tm.group(0))

        category, venue_override, price_override = classify_event(title, block_text)
        if not category:
            continue  # ignore non-target events for now

        # Try to detect a price if it’s explicitly shown
        price = ""
        pm = re.search(r"\$\d+[^\\n]*", block_text)
        if pm:
            price = pm.group(0).strip()

        events.append({
            "date": date_iso,
            "venue": venue_override or "Sketchboard",
            "title": title,
            "category": category,
            "event_type": "",
            "start_time": start_time,
            "end_time": end_time,
            "price_text": price or price_override or "",
            "is_museum": "no",
            "museum_name": "",
            "event_url": href,
            "notes": "Auto-imported from sketchboard.co/schedule",
        })

    # De-dupe by date+title+start_time
    seen = set()
    uniq = []
    for ev in events:
        key = (ev["date"], ev["title"].lower().strip(), ev["start_time"].strip())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(ev)

    uniq.sort(key=lambda x: (x["date"], x["start_time"], x["title"]))

    w = csv.DictWriter(sys.stdout, fieldnames=HEADERS)
    w.writeheader()
    for ev in uniq:
        w.writerow(ev)

if __name__ == "__main__":
    main()
