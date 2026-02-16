name: Build Case for Making Events CSV

on:
  workflow_dispatch:
  schedule:
    - cron: "15 15 * * *" # daily ~7:15am PT (adjust any time)

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests beautifulsoup4

      - name: Fetch Case for Making events
        run: |
          python scripts/scrape_case.py
          echo "---- preview ----"
          head -n 10 case_events.csv

      - name: Commit case_events.csv
        run: |
          git config user.name "artlinks-bot"
          git config user.email "artlinks-bot@users.noreply.github.com"
          git add case_events.csv
          git diff --staged --quiet || git commit -m "Update Case for Making events CSV"
          git push
