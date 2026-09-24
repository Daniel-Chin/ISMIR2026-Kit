## Cheatsheet
```fish
tmux new -s anno_bot
systemd-inhibit --what=sleep --why='announcement bot' \
    uv run python -m long_running_bots.announcement_bot --mockup --path sitedata_mock
# interact...
# ctrl-B D
tmux new -s self_s_bot
systemd-inhibit --what=sleep --why='self service bot' \
    uv run python -m long_running_bots.self_service_pusher --mockup --path sitedata_mock
# interact...
# ctrl-B D
systemd-inhibit --list  # to check locks
# logout.
# ...
# login
tmux attach -t anno_bot
tmux attach -t self_s_bot
```

## Notes
For ISMIR2026, Daniel Chin is in charge of keeping the process running, by keeping his home desktop always on, and opening ssh for maintenance.  
