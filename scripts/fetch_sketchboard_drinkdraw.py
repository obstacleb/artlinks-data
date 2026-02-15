#!/usr/bin/env python3
import re
import csv
import sys
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import urljoin

from bs4 import BeautifulSoup

PAGES = [
  "https://www.sketchboard.co/schedule",
  "https://www.sketchboard.co/calendar",
]

OUT_CSV = "sketchboard_auto.csv"  # workflow will redirect stdout to this filename

HEADERS = [
  "date","venue","title","category","event_type","start_time","end_time",
  "price_text","is_museum","museum_name","event_url","notes"
]

UA = {"User-Agent": "artlinks-bot/1.2 (github actions)"}

def fetch_html(url: str) -> str:
  req = Request(url, headers=UA)
  with urlopen(req, timeout=30) as r:
    return r.read().decode("utf-8", errors="replace")

def abs_url(base: str, href: str) -> str:
  href = (href or "").strip()
  if not href:
    return ""
  return urljoin(base, href)

def parse_long_date(block: str) -> str:
  """
  Looks for: Tuesday, February 17, 2026
  Returns ISO: 2026-02-17
  """
  m = re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Za-z]+)\s+(\d{1,2}),\s+(20\d{2})", block)
  if not m:
    return ""
  dt = datetime.strptime(m.group(0), "%A, %B %d, %Y")
  return dt.strftime("%Y-%m-%d")

def parse_time_range(block: str):
  """
  Accepts: 6:30 PM 8:30 PM
  Returns: ("18:30","20:30")
  """
  t = " ".join(block.split())
  m = re.search(r"(\d{1,2}:\d{2})\s*([AP]M)\s+(\d{1,2}:\d{2})\s*([AP]M)", t, re.I)
  if not m:
    return ("","")
  return (to_24(m.group(1), m.group(2)), to_24(m.group(3), m.group(4)))

def to_24(hhmm: str, ampm: str) -> str:
  h, m = hhmm.split(":")
  h = int(h); m = int(m)
  ap = ampm.lower()
  if ap == "pm" and h != 12: h += 12
  if ap == "am" and h == 12: h = 0
  return f"{h:02d}:{m:02d}"

def extract_price(block: str) -> str:
  t = " ".join(block.split())
  m = re.search(r"\$\s*\d+(?:\.\d{2})?(?:\s*(?:suggested|sliding|donation))?", t, re.I)
  if m:
    return re.sub(r"\s+", " ", m.group(0)).strip()
  if re.search(r"\bfree\b", t, re.I):
    return "Free"
  return ""

def classify(title: str, block: str):
  tl = (title or "").lower()
  bl = (block or "").lower()

  # Figure Drawing (broad but safe)
  figure_terms = [
    "figure drawing","life drawing","figure session","model session",
    "gesture drawing","open studio (figure)","open studio figure"
  ]
  if any(term in tl or term in bl for term in figure_terms) or ("figure" in tl and "drawing" in tl):
    return {
      "category": "Figure Drawing",
      "venue": "Sketchboard (Figure)",
      "price_default": ""
    }

  # Drink & Draw
  if ("drink" in tl and "draw" in tl) or ("drink" in bl and "draw" in bl) or ("madrone" in tl) or ("madrone" in bl):
    return {
      "category": "Drink & Draw",
      "venue": "Sketchboard @ Madrone Art Bar",
      "price_default": "$15 cash only (per Sketchboard)"
    }

  return None

def scrape_page(url: str):
  html = fetch_html(url)
  soup = BeautifulSoup(html, "html.parser")

  events = []

  # Grab link-ish blocks; tolerate markup changes by using nearby text
  for a in soup.select("a[href]"):
    title = " ".join(a.get_text(" ").split()).strip()
    if not title or "View Event" in title:
      continue

    href = abs_url(url, a.get("href", ""))
    if "sketchboard.co" not in href:
      continue

    container = a.find_parent()
    if not container:
      continue

    block = container.get_text("\n", strip=True)

    info = classify(title, block)
    if not info:
      continue

    date_iso = parse_long_date(block)
    if not date_iso:
      # sometimes date is a bit higher up
      p2 = container.find_parent()
      if p2:
        date_iso = parse_long_date(p2.get_text("\n", strip=True))
    if not date_iso:
      continue

    start, end = parse_time_range(block)

    price = extract_price(block) or info["price_default"]

    events.append({
      "date": date_iso,
      "venue": info["venue"],
      "title": title,
      "category": info["category"],
      "event_type": "",
      "start_time": start,
      "end_time": end,
      "price_text": price,
      "is_museum": "no",
      "museum_name": "",
      "event_url": href,
      "notes": "Auto-imported: Sketchboard",
    })

  return events

def dedupe(rows):
  seen = set()
  out = []
  for r in rows:
    key = (r["date"], r["title"].lower().strip(), r["start_time"].strip(), r["category"])
    if key in seen:
      continue
    seen.add(key)
    out.append(r)
  out.sort(key=lambda r: (r["date"], r["start_time"], r["title"]))
  return out

def main():
  all_rows = []
  for url in PAGES:
    try:
      all_rows.extend(scrape_page(url))
    except Exception as e:
      sys.stderr.write(f"[warn] failed to scrape {url}: {e}\n")

  rows = dedupe(all_rows)

  w = csv.DictWriter(sys.stdout, fieldnames=HEADERS)
  w.writeheader()
  for r in rows:
    w.writerow(r)

if __name__ == "__main__":
  main()
