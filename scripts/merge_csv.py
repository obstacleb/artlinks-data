#!/usr/bin/env python3
import csv
import sys
from pathlib import Path

HEADERS = [
    "date","venue","title","category","event_type","start_time","end_time",
    "price_text","is_museum","museum_name","event_url","notes"
]

def read_csv(p: Path):
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return [{h: (row.get(h,"") or "").strip() for h in HEADERS} for row in r]

def write_csv(p: Path, rows):
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        w.writeheader()
        for row in rows:
            w.writerow({h: row.get(h,"") for h in HEADERS})

def key(row):
    return (
        (row.get("date","") or ""),
        (row.get("venue","") or "").lower().strip(),
        (row.get("title","") or "").lower().strip(),
        (row.get("start_time","") or "").strip(),
    )

def main():
    base = Path("events.csv")
    auto = Path("sketchboard_drinkdraw.csv")

    base_rows = read_csv(base)
    auto_rows = read_csv(auto)

    # remove prior auto-imported rows from Sketchboard to avoid duplicates
    cleaned = [r for r in base_rows if "Auto-imported from sketchboard.co/schedule" not in (r.get("notes","") or "")]

    # merge in new auto rows
    merged = cleaned + auto_rows

    # de-dupe
    seen = set()
    uniq = []
    for r in merged:
        k = key(r)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    # sort
    uniq.sort(key=lambda r: (r.get("date",""), r.get("start_time",""), r.get("venue",""), r.get("title","")))

    write_csv(base, uniq)

if __name__ == "__main__":
    main()
