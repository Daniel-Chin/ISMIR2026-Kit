# !/bin/bash
# Download the latest industry data from Google Sheets and save it as a CSV file
curl -sSL "https://docs.google.com/spreadsheets/d/$SITEDATA/export?format=csv&gid=$INDUSTRY_GID" -o sitedata/industry.csv
curl -sSL "https://docs.google.com/spreadsheets/d/$SITEDATA/export?format=csv&gid=$PAPERS_GID"   -o sitedata/papers.csv 
curl -sSL "https://docs.google.com/spreadsheets/d/$SITEDATA/export?format=csv&gid=$EVENTS_GID"   -o sitedata/events.csv
curl -sSL "https://docs.google.com/spreadsheets/d/$SITEDATA/export?format=csv&gid=$MUSIC_GID"    -o sitedata/music.csv
curl -sSL "https://docs.google.com/spreadsheets/d/$SITEDATA/export?format=csv&gid=$LBDS_GID"     -o sitedata/lbds.csv

# Get thumbnail images from google drive urls
# python scripts/get_thumbnails.py

# Set up calendar info
.venv/bin/python scripts/calendar_csv2ics.py
.venv/bin/python scripts/calendar_ics2json.py 