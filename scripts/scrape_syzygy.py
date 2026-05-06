#!/usr/bin/env python3
import csv, datetime, zoneinfo, requests
from icalendar import Calendar
import recurring_ical_events

ICAL_URL = (
    "https://calendar.google.com/calendar/ical/"
    "ab5594c927f49b0fdbac6df5105baab13fa8c85a557455199d4ffe8a1e3d2727"
    "%40group.calendar.google.com/public/basic.ics"
)
OUT = "syzygy_events.csv"
PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")
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
    if not hasattr(dt_val, "hour"):
        return ""
    if hasattr(dt_val, "tzinfo") and dt_val.tzinfo:
        dt_val = dt_val.astimezone(PACIFIC)
    return dt_val.strftime("%-I:%M %p")

def to_pacific_date(dt_val):
    if hasattr(dt_val, "hour"):
        if hasattr(dt_val, "tzinfo") and dt_val.tzinfo:
            dt_val = dt_val.astimezone(PACIFIC)
        return dt_val.strftime("%Y-%m-%d")
    return dt_val.isoformat()

def main():
    response = requests.get(ICAL_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    cal = Calendar.from_ical(response.content)

    today = datetime.date.today()
    end = today + datetime.timedelta(days=180)

    events = recurring_ical_events.of(cal).between(today, end)

    rows = []
    for component in events:
        dtstart = component.get("DTSTART")
        if not dtstart:
            continue
        dt = dtstart.dt
        date_str = to_pacific_date(dt)
        start_time = fmt_time(dt)

        dtend = component.get("DTEND")
        end_time = fmt_time(dtend.dt) if dtend else ""

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

    print(f"Found {len(rows)} events")
    rows.sort(key=lambda r: r["date"])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {OUT}")

if __name__ == "__main__":
    main()
