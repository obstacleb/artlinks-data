#!/usr/bin/env python3
"""
Scrape https://syzygysf.com/ and generate a CSV of dated events
suitable for client-side merging on a static site.

- Special Events: cards with explicit dates like 04-25-2026
- Recurring Events: rules like "Every Monday, 8-10pm", "2nd Wednesday", etc.
  Expanded into dated instances for the next N days.

Output: syzygy_events.csv
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional, Tuple, List, Dict

import requests
from bs4 import BeautifulSoup

SYZYGY_URL = "https://syzygysf.com/"
VENUE_NAME = "Syzygy SF"

# --- config you may tweak ---
ROLLING_DAYS = 90
OUTPUT_CSV = "syzygy_events.csv"

# If you already ingest Drink & Draw elsewhere, skipping avoids duplicates.
SKIP_TITLES_CONTAINING = ["Drink and Draw"]


@dataclass(frozen=True)
class EventRow:
    date: str          # YYYY-MM-DD
    venue: str
    title: str
    category: str
    start_time: str    # "19:00" 24h, or ""
    end_time: str      # "21:00" 24h, or ""
    price_text: str
    event_url: str
    is_museum: str     # "false"/"true" for CSV friendliness
    source: str        # optional but handy


WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

ORDINAL_MAP = {"1st": 1, "first": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3, "4th": 4, "fourth": 4}


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def parse_mm_dd_yyyy(s: str) -> Optional[date]:
    # accepts "04-25-2026"
    m = re.search(r"\b(\d{2})-(\d{2})-(\d{4})\b", s)
    if not m:
        return None
    mm, dd, yyyy = map(int, m.groups())
    return date(yyyy, mm, dd)


def parse_time_range(text: str) -> Tuple[str, str]:
    """
    Parse times like "7-10pm", "7-9PM", "8-10pm"
    Return ("HH:MM","HH:MM") or ("","") if unknown.
    """
    t = text.lower().replace(" ", "")
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?-(\d{1,2})(?::(\d{2}))?(am|pm)\b", t)
    if not m:
        return "", ""
    sh, sm, eh, em, ap = m.groups()
    sh = int(sh); eh = int(eh)
    sm = int(sm) if sm else 0
    em = int(em) if em else 0

    # assume both times share the same am/pm marker (common in listings)
    if ap == "pm":
        if sh != 12:
            sh += 12
        if eh != 12:
            eh += 12
    else:  # am
        if sh == 12:
            sh = 0
        if eh == 12:
            eh = 0

    return f"{sh:02d}:{sm:02d}", f"{eh:02d}:{em:02d}"


def infer_category(title: str) -> str:
    t = title.lower()
    if "zine" in t:
        return "Zines"
    if "record" in t or "flipside" in t or "jam" in t:
        return "Music"
    if "game" in t:
        return "Games"
    if "hobby" in t:
        return "Hobby Hang"
    if "market" in t or "fair" in t:
        return "Art Market"
    return "Syzygy"


def daterange(start: date, end_exclusive: date) -> Iterable[date]:
    d = start
    while d < end_exclusive:
        yield d
        d += timedelta(days=1)


def next_weekday_on_or_after(d: date, weekday: int) -> date:
    delta = (weekday - d.weekday()) % 7
    return d + timedelta(days=delta)


def nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> Optional[date]:
    # n: 1..5-ish
    first = date(year, month, 1)
    first_w = next_weekday_on_or_after(first, weekday)
    candidate = first_w + timedelta(days=7 * (n - 1))
    if candidate.month != month:
        return None
    return candidate


def expand_rule_to_dates(rule_text: str, window_start: date, window_end: date) -> List[date]:
    """
    Supports common Syzygy patterns seen on the homepage:
      - "Every Monday, 8-10pm"
      - "Every Tuesday, 7-10pm"
      - "Every 2nd Wednesday, 6-9pm"
      - "Third Thursday of every month, 7-9PM"
      - "First Tuesday of every month, 7-9PM"
      - "Every other Wednesday..." (too ambiguous; not expanded)
    """
    txt = rule_text.strip().lower()

    # Every other Wednesday... (ambiguous without an anchor)
    if "every other" in txt:
        return []

    # Every <weekday>
    m = re.search(r"\bevery\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", txt)
    if m and "month" not in txt and not re.search(r"\b(1st|2nd|3rd|4th|first|second|third|fourth)\b", txt):
        wd = WEEKDAY_MAP[m.group(1)]
        first = next_weekday_on_or_after(window_start, wd)
        out = []
        d = first
        while d < window_end:
            out.append(d)
            d += timedelta(days=7)
        return out

    # <ordinal> <weekday> (monthly) e.g. "every 2nd wednesday" or "third thursday of every month"
    ord_m = re.search(r"\b(1st|2nd|3rd|4th|first|second|third|fourth)\b", txt)
    wd_m = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", txt)
    if ord_m and wd_m:
        n = ORDINAL_MAP[ord_m.group(1)]
        wd = WEEKDAY_MAP[wd_m.group(1)]
        out = []
        # iterate months in the window
        cur = date(window_start.year, window_start.month, 1)
        while cur < window_end:
            cand = nth_weekday_of_month(cur.year, cur.month, wd, n)
            if cand and window_start <= cand < window_end:
                out.append(cand)
            # next month
            if cur.month == 12:
                cur = date(cur.year + 1, 1, 1)
            else:
                cur = date(cur.year, cur.month + 1, 1)
        return out

    return []


def scrape_syzygy() -> List[EventRow]:
    r = requests.get(SYZYGY_URL, timeout=30, headers={"User-Agent": "TheArtListBot/1.0 (+https://drawstuff.neocities.org/)"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    today = date.today()
    window_start = today
    window_end = today + timedelta(days=ROLLING_DAYS)

    events: List[EventRow] = []

    # Heuristic: find all headings and grab the blocks after "Special Events" and "Recurring Events"
    # We’ll collect linked cards and use their visible text.
    headings = soup.find_all(["h1", "h2", "h3"])
    special_anchor = None
    recurring_anchor = None
    for h in headings:
        ht = norm_space(h.get_text())
        if ht.lower() == "special events":
            special_anchor = h
        if ht.lower() == "recurring events":
            recurring_anchor = h

    def collect_cards_until_next_heading(anchor_tag) -> List[BeautifulSoup]:
        if not anchor_tag:
            return []
        cards = []
        for sib in anchor_tag.next_siblings:
            if getattr(sib, "name", None) in ["h1", "h2", "h3"]:
                break
            if getattr(sib, "find_all", None):
                # grab linked blocks
                for a in sib.find_all("a", href=True):
                    # ignore nav/footer style links
                    txt = norm_space(a.get_text(" ", strip=True))
                    if len(txt) < 5:
                        continue
                    cards.append(a)
        return cards

    special_cards = collect_cards_until_next_heading(special_anchor)
    recurring_cards = collect_cards_until_next_heading(recurring_anchor)

    # --- Special Events (dated) ---
    for a in special_cards:
        text = norm_space(a.get_text(" ", strip=True))
        # typically "... 04-25-2026"
        d = parse_mm_dd_yyyy(text)
        if not d:
            continue
        if not (window_start <= d < window_end):
            continue

        title = norm_space(re.sub(r"\b\d{2}-\d{2}-\d{4}\b", "", text)).strip(" -")
        if any(k.lower() in title.lower() for k in SKIP_TITLES_CONTAINING):
            continue

        href = a["href"]
        url = href if href.startswith("http") else (SYZYGY_URL.rstrip("/") + "/" + href.lstrip("/"))

        events.append(
            EventRow(
                date=d.isoformat(),
                venue=VENUE_NAME,
                title=title,
                category=infer_category(title),
                start_time="",
                end_time="",
                price_text="",
                event_url=url,
                is_museum="false",
                source="syzygy_special",
            )
        )

    # --- Recurring Events (expand rules) ---
    # Recurring cards often include a title line and a rule line like "Every Tuesday, 7-10pm"
    # We'll treat the *full text* as "Title <rule>" and parse the rule from it.
    for a in recurring_cards:
        raw = norm_space(a.get_text(" ", strip=True))
        if not raw:
            continue

        # Split into title + rule by finding an "Every ..." or "First/Second/Third..." phrase
        rule_match = re.search(
            r"\b(every\s+(?:other\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
            r"(?:1st|2nd|3rd|4th|first|second|third|fourth)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b.*",
            raw,
            flags=re.IGNORECASE,
        )
        if not rule_match:
            continue

        rule = norm_space(rule_match.group(0))
        title = norm_space(raw[: rule_match.start()]).strip(" -,")

        if any(k.lower() in title.lower() for k in SKIP_TITLES_CONTAINING):
            continue

        href = a.get("href", "")
        url = href if href.startswith("http") else (SYZYGY_URL.rstrip("/") + "/" + href.lstrip("/")) if href else SYZYGY_URL

        dates = expand_rule_to_dates(rule, window_start, window_end)
        if not dates:
            # keep a single undated “info” event? skip for simplicity
            continue

        st, et = parse_time_range(rule)

        for d in dates:
            events.append(
                EventRow(
                    date=d.isoformat(),
                    venue=VENUE_NAME,
                    title=title,
                    category=infer_category(title),
                    start_time=st,
                    end_time=et,
                    price_text="",  # often not specified on the homepage
                    event_url=url,
                    is_museum="false",
                    source="syzygy_recurring",
                )
            )

    # Dedup by (date,title,url)
    seen = set()
    deduped = []
    for e in sorted(events, key=lambda x: (x.date, x.title, x.event_url)):
        key = (e.date, e.title.lower(), e.event_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    return deduped


def write_csv(rows: List[EventRow], path: str) -> None:
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
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r.__dict__)


def main() -> None:
    rows = scrape_syzygy()
    write_csv(rows, OUTPUT_CSV)
    print(f"Wrote {len(rows)} rows -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
