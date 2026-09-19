#!/bin/bash
# Mock-conference version of migrate.sh.
#
# The real setup is ONE master sheet with 5 tabs (pulled via $SITEDATA + per-tab
# $*_GID). The mock uses 5 separate Google Sheets (one per tab, created via the
# Drive API which can't add tabs), so this script pulls each by its own ID.
# Same mechanism: unauthenticated CSV-export URLs.
#
# REQUIREMENT: the Drive folder ISMIR2026-mock-drive must be shared as
# "Anyone with the link: Viewer", otherwise these downloads return an HTML
# login page instead of CSV.
#
# Sheets live in https://drive.google.com/drive/folders/1-0LdWqhrLIaJ9PsG7uhAN7As8LXAFPXk

set -e

PAPERS_ID="1hak92WcsA16PaXI3TY563NSuCHoe2_PkcWcly9hBTTI"
EVENTS_ID="1jJ9hRrVKQu1PozjSnoG60Qsj2RsOylpob4nWfdm_OsE"
LBDS_ID="1F6vdNHiDpQKpO5PZ9Yfhv7sB5s_3xtS9i8za-besVl4"
MUSIC_ID="1GsqtA27aaHBHqQj1JqNKR_hK9A9lQcy5fUTlq3vWGYM"
INDUSTRY_ID="1DmTd2bbcZDxUPWGzOwfADnwQ9bswYmDM5uxu62ui4Qw"

OUT_DIR="${1:-sitedata_mock}"

for pair in "papers:$PAPERS_ID" "events:$EVENTS_ID" "lbds:$LBDS_ID" "music:$MUSIC_ID" "industry:$INDUSTRY_ID"; do
    name="${pair%%:*}"
    id="${pair##*:}"
    echo "pulling $OUT_DIR/$name.csv"
    curl -sSL "https://docs.google.com/spreadsheets/d/$id/export?format=csv" -o "$OUT_DIR/$name.csv"
    echo "ok"
done

# Rebuild the calendar from the freshly pulled events
.venv/bin/python - <<EOF
from scripts.calendar_csv2ics import calendar_csv2ics
from scripts.calendar_ics2json import calendar_ics2json
calendar_csv2ics(in_csv="$OUT_DIR/events.csv", out_ics="static/calendar/ISMIR_2026.ics")
calendar_ics2json(in_ics="static/calendar/ISMIR_2026.ics", out_json="$OUT_DIR/main_calendar.json")
EOF
echo "calendar rebuilt"
