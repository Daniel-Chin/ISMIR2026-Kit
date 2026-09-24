## Adding a schedule to MiniConf

Edit `events.csv` in `sitedata/` (or `sitedata_mock/` when using `--mockup`).
The website builds its calendar directly from these rows, using the timezone
and calendar colors in that directory's `config.yml`.

To regenerate the downloadable ICS calendar, run from the repository root:

```bash
python miniconf_prep.py --action prepare-calendar
```

Use your selected site data directory in place of `sitedata`.
No intermediate `main_calendar.json` file is needed.
