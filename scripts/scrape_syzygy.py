#!/usr/bin/env python3
from icalendar import Calendar
import csv, datetime
from urllib.request import urlopen

ICAL_URL = (
    "https://calendar.google.com/calendar/ical/"
    "ab5594c927f49b0fdbac6df5105baab13fa8c85a557455199d4ffe8a1e3d2727"
    "%40group.calendar.google.com/public/basic.ics"
)
OUT = "syzygy_events.csv"
FIELDS = ["date","venue","title","category","start_time","end_time",
          "price_text","event_url","instagram_url","is_museum","museum_name","notes","source"]

def guess_category(title, desc):
    t = (title + " " + desc).lower()
    if "drink" in t and "draw" in t: return "Drink & Draw"
    if "figure" in t or "life draw" in t: return "Figure Drawing"
    if "workshop" in t: return "Workshop"
    if "zine" in t: return "Zine"
    if "jam" in t or "hobby hang" in t or "flipside" in t: return "Community"
    if "movie" in t or "film" in t: return "Other"
    if "reading" in t or "open mic" in t: return "Talk"
    return "Other"

def fmt_time(dt_val):
    if hasattr(dt_val, "hour"):
        return dt_val.strftime("%-I:%M %p")
    return ""

def main():
    with urlopen(ICAL_URL) as f:
        cal = Calendar.from_ical(f.read())

    rows = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        dtstart = component.get("DTSTART")
        if not dtstart:
            continue
        dt = dtstart.dt
        if hasattr(dt, "date"):
            date_str = dt.strftime("%Y-%m-%d")
            start_time = fmt_time(dt)
        else:
            date_str = dt.isoformat()
            start_time = ""

        dtend = component.get("DTEND")
        end_time = fmt_time(dtend.dt) if dtend and hasattr(dtend.dt, "hour") else ""

        title = str(component.get("SUMMARY", "")).strip()
        desc  = str(component.get("DESCRIPTION", "")).strip()
        url   = str(component.get("URL", "")).strip()

        if title.upper().startswith("[HOLD]") or title.lower().startswith("hold;"):
            continue

        rows.append({
            "date": date_str, "venue": "Syzygy Artists Co-Op",
            "title": title, "category": guess_category(title, desc),
            "start_time": start_time, "end_time": end_time,
            "price_text": "", "event_url": url or "https://syzygysf.com/#events",
            "instagram_url": "https://www.instagram.com/syzygycoop",
            "is_museum": "false", "museum_name": "",
            "notes": desc[:200], "source": "Syzygy",
        })

    rows.sort(key=lambda r: r["date"])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {OUT}")

if __name__ == "__main__":
    main()
