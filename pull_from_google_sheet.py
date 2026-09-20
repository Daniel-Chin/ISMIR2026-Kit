import argparse
import os
from pathlib import Path
from urllib import request

from scripts.calendar_csv2ics import calendar_csv2ics
from scripts.calendar_ics2json import calendar_ics2json


REAL_SHEETS = {
    "industry": "INDUSTRY_GID",
    "papers": "PAPERS_GID",
    "events": "EVENTS_GID",
    "music": "MUSIC_GID",
    "lbds": "LBDS_GID",
}

MOCK_SHEETS = {
    "papers": "1hak92WcsA16PaXI3TY563NSuCHoe2_PkcWcly9hBTTI",
    "events": "1jJ9hRrVKQu1PozjSnoG60Qsj2RsOylpob4nWfdm_OsE",
    "lbds": "1F6vdNHiDpQKpO5PZ9Yfhv7sB5s_3xtS9i8za-besVl4",
    "music": "1GsqtA27aaHBHqQj1JqNKR_hK9A9lQcy5fUTlq3vWGYM",
    "industry": "1DmTd2bbcZDxUPWGzOwfADnwQ9bswYmDM5uxu62ui4Qw",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Download site-data CSVs, rebuild the calendar, and prepare the sitedata "
            "for either the production conference or the mock conference."
        )
    )
    parser.add_argument(
        "--mockup",
        action="store_true",
        help=(
            "Use the mock-conference spreadsheet IDs in sitedata_mock/. "
            "The mock setup stores each tab in a separate Google Sheet and "
            "requires the Drive folder to be shared as 'Anyone with the link: Viewer'."
        ),
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Optional directory to write CSVs into; defaults to sitedata or sitedata_mock.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help=(
            "Skip downloading CSVs from Google Sheets."
        ),
    )
    return parser.parse_args()


def download_csv_from_google_sheet(sheet_id: str, output_path: Path) -> None:
    """Download a published CSV export from a Google Sheet.

    The real conference has one master sheet with five tabs. The mock conference uses
    five separate Drive sheets instead, because the Drive API cannot add tabs. In both
    cases the workflow is identical: request the CSV export and save it to a local data dir.
    """
    if not sheet_id:
        raise ValueError(f"Missing Google Sheet ID for {output_path.name}")

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with request.urlopen(url) as response, open(output_path, "wb") as file_handle:
        file_handle.write(response.read())

    print(f"downloaded {output_path}")


def get_sheet_mapping(mockup: bool) -> dict[str, str]:
    if mockup:
        return MOCK_SHEETS

    missing = [name for name, env_name in REAL_SHEETS.items() if not os.getenv(env_name)]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            "Missing env vars for production sheet download: "
            f"{names}. Set SITEDATA plus the corresponding *_GID values."
        )

    return {name: os.environ[env_name] for name, env_name in REAL_SHEETS.items()}


def pull_data_dir(target_dir: Path, mockup: bool) -> Path:
    sheet_map = get_sheet_mapping(mockup)

    for name, sheet_id in sheet_map.items():
        output_path = target_dir / f"{name}.csv"
        download_csv_from_google_sheet(sheet_id, output_path)

    return target_dir


def rebuild_calendar_for_data_dir(data_dir: Path) -> None:
    """Rebuild the calendar assets from the freshest events CSV.

    This replaces the shell commands that ran:
      .venv/bin/python scripts/calendar_csv2ics.py
      .venv/bin/python scripts/calendar_ics2json.py
    """
    events_csv = data_dir / "events.csv"
    calendar_ics = Path("static") / "calendar" / "ISMIR_2026.ics"
    calendar_json = data_dir / "main_calendar.json"

    if not events_csv.exists():
        raise FileNotFoundError(f"Missing events CSV at {events_csv}")

    calendar_csv2ics(in_csv=str(events_csv), out_ics=str(calendar_ics))
    calendar_ics2json(in_ics=str(calendar_ics), out_json=str(calendar_json))
    print("calendar rebuilt")


def main():
    args = parse_args()

    target_dir = Path(args.data_dir) if args.data_dir else (
        Path("sitedata_mock") if args.mockup else Path("sitedata")
    )
    if not args.skip_download:
        pull_data_dir(target_dir, args.mockup)
    rebuild_calendar_for_data_dir(target_dir)


if __name__ == "__main__":
    main()
