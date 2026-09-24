## Adding a schedule to MiniConf

Edit `events.csv` in the site data directory passed to `main.py --path`.
The website builds its calendar directly from these rows, using the timezone
and calendar colors in that directory's `config.yml`.

To regenerate the downloadable ICS calendar, run from the repository root:

```bash
python miniconf_prep.py --path sitedata --action prepare-calendar
```

Use your selected site data directory in place of `sitedata`.
No intermediate `main_calendar.json` file is needed.
