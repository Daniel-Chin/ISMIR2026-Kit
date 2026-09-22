## Cheatsheet
```fish
tmux new -s job
uv run python -m announcement_bot.announcement_bot --mockup --path sitedata_mock
# interact...
# ctrl-B D
# logout.
# ...
# login
tmux attach -t job
```

## Notes
For ISMIR2026, Daniel Chin is in charge of keeping the process running, by keeping his home desktop always on, and opening ssh for maintenance.  
