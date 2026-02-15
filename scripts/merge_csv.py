#!/usr/bin/env python3
import csv
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

def is_sketchboard_auto(row):
  notes = (row.get("notes","") or "").lower()
  return "auto-imported: sketchboard" in notes

def key(row):
  return (
    (row.get("date","") or ""),
    (row.get("venue","") or "").lower().strip(),
    (row.get("title","") or "").lower().strip(),
    (row.get("start_time","") or "").strip(),
    (row.get("category","") or "").lower().strip(),
  )

def main():
  base = Path("events.csv")
  auto = Path("sketchboard_auto.csv")

  base_rows = read_csv(base)
  auto_rows = read_csv(auto)

  # Remove prior Sketchboard auto rows so updates replace cleanly
  cleaned = [r for r in base_rows if not is_sketchboard_auto(r)]

  merged = cleaned + auto_rows

  seen = set()
  uniq = []
  for r in merged:
    k = key(r)
    if k in seen:
      continue
    seen.add(k)
    uniq.append(r)

  uniq.sort(key=lambda r: (r.get("date",""), r.get("start_time",""), r.get("venue",""), r.get("title","")))
  write_csv(base, uniq)

if __name__ == "__main__":
  main()
