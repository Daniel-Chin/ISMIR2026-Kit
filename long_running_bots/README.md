## Cheatsheet
```fish
tmux new -s anno_bot
systemd-inhibit --what=sleep --why='announcement bot' \
    uv run python -m long_running_bots.announcement_bot --mockup
# interact...
# ctrl-B D
tmux new -s self_s_bot
systemd-inhibit --what=sleep --why='self service bot' \
    uv run python -m long_running_bots.self_service_pusher
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

The announcement bot uses `SLACK_TOKEN_ANNOUNCEMENT_BOT` by default and
`MOCKUP_SLACK_TOKEN_ANNOUNCEMENT_BOT` with `--mockup`. Set both in `.env`.
The self-service bot uses its separate `SLACK_BOT_TOKEN_SELF_SERVICE` and
`SLACK_APP_TOKEN_SELF_SERVICE` credentials; it has no mockup or path flags.
