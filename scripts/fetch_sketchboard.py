#!/usr/bin/env python3
import csv
import datetime as dt
import requests

COLLECTION_ID = "6949d6a566f9574d9d6216f2"
MONTHS_AHEAD = 6
OUT = "sketchboard_events.csv"

def month_key(d: dt.date) -> str:
    return f"{d.month:02d}-{d.year}"

def iso_date_from_ms(ms):
    if not ms:
        return ""
    return dt.datetime.utcfromtimestamp(ms/1000).date().isoformat()

def time_from_ms(ms):
    if not ms:
        return ""
    # keep local-ish display stable by formatting in UTC then letting your UI show times;
    # or change to local if you want.
    t = dt.datetime.utcfromtimestamp(ms/1000).time()
    return t.strftime("%H:%M")

def fetch_month(key: str):
    url = "https://www.sketchboard.co/api/open/GetItemsByMonth"
    r = requests.get(url, params={"month": key, "collectionId": COLLECTION_ID}, timeout=30)
    r.raise_for_status()
    return r.json()

def first_category(item):
    cats = item.get("categories")
    if isinstance(cats, list) and cats:
        return cats[0]
    return "Sketchboard"

def main():
    today = dt.date.today()
    items = []
    d = today

    for _ in range(MONTHS_AHEAD):
        key = month_key(d)
        month_items = fetch_month(key)
        if isinstance(month_items, list):
            items.extend(month_items)
        # advance one month
        year = d.year + (1 if d.month == 12 else 0)
        month = 1 if d.month == 12 else d.month + 1
        d = dt.date(year, month, 1)

    rows = []
    for it in items:
        start_ms = it.get("startDate") or (it.get("structuredContent") or {}).get("startDate")
        end_ms = it.get("endDate") or (it.get("structuredContent") or {}).get("endDate")
        date = iso_date_from_ms(start_ms)
        if not date:
            continue

        loc = it.get("location") or {}
        venue = loc.get("addressTitle") or loc.get("addressLine1") or "Sketchboard"
        full_url = it.get("fullUrl") or ""
        event_url = f"https://www.sketchboard.co{full_url}" if full_url else ""

        rows.append({
            "date": date,
            "venue": venue,
            "title": it.get("title") or "Untitled",
            "category": first_category(it),
            "event_type": "Sketchboard",
            "start_time": time_from_ms(start_ms),
            "end_time": time_from_ms(end_ms),
            "price_text": "",
            "is_museum": "false",
            "museum_name": "",
            "event_url": event_url,
            "notes": "",
        })

    # dedupe
    seen = set()
    deduped = []
    for r in sorted(rows, key=lambda x: (x["date"], x["start_time"], x["title"])):
        k = (r["date"], r["title"].lower(), r["venue"].lower(), r["start_time"], r["event_url"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(deduped[0].keys()) if deduped else [
            "date","venue","title","category","event_type","start_time","end_time",
            "price_text","is_museum","museum_name","event_url","notes"
        ])
        w.writeheader()
        w.writerows(deduped)

    print(f"Wrote {len(deduped)} rows -> {OUT}")

if __name__ == "__main__":
    main()
