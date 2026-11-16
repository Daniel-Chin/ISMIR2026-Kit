"""Back up the workspace's chat history (text only, no file contents) to one JSON file per channel.

Covers every public channel (read with the user token, so no joining is needed) and the private
channels the bot is in, with thread replies nested under their parent. Attached files are reduced
to name, title, type, size and permalink. Also writes users.json to resolve user ids.

uv run --env-file real.env python -m scripts.backup_slack_history ~/ismir2026/slack-backup
"""

import argparse
import json
import time
from pathlib import Path

import slack_sdk.errors

from utils import slack

FILE_FIELDS = ('name', 'title', 'mimetype', 'size', 'permalink')


def paged(method, key: str, **kwargs) -> list[dict]:
    out = []
    for page in method(limit=slack.PAGE_LIMIT, **kwargs):
        out += page.get(key) or []
    return out


def slim(message: dict) -> dict:
    m = {k: v for k, v in message.items() if k not in ('blocks', 'files', 'attachments')}
    if message.get('files'):
        m['files'] = [{k: f.get(k) for k in FILE_FIELDS} for f in message['files']]
    return m


def history(client, channel_id: str) -> list[dict]:
    messages = [slim(m) for m in paged(client.conversations_history, 'messages', channel=channel_id)]
    for m in messages:
        if m.get('reply_count'):
            replies = paged(client.conversations_replies, 'messages', channel=channel_id, ts=m['ts'])
            m['replies'] = [slim(r) for r in replies if r['ts'] != m['ts']]
    return sorted(messages, key=lambda m: float(m['ts']))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('out_dir')
    args = parser.parse_args()
    out = Path(args.out_dir).expanduser()
    (out / 'channels').mkdir(parents=True, exist_ok=True)

    slack.configure_clients(is_mockup=False)
    users = paged(slack.client_bot.users_list, 'members')
    (out / 'users.json').write_text(json.dumps(
        [{k: u.get(k) for k in ('id', 'name', 'real_name', 'deleted', 'is_bot')} for u in users],
        ensure_ascii=False, indent=1))

    public = paged(slack.client_user.conversations_list, 'channels', types='public_channel')
    private = paged(slack.client_bot.conversations_list, 'channels', types='private_channel')
    jobs = [(c, slack.client_user) for c in public] + [(c, slack.client_bot) for c in private]
    index, failed = [], []
    for i, (c, client) in enumerate(jobs, 1):
        try:
            messages = history(client, c['id'])
        except slack_sdk.errors.SlackApiError as e:
            failed.append((c['name'], e.response.get('error')))
            print(f'{i}/{len(jobs)} #{c["name"]}: FAILED {e.response.get("error")}', flush=True)
            continue
        (out / 'channels' / f'{c["name"]}.json').write_text(json.dumps(messages, ensure_ascii=False, indent=1))
        index.append({'id': c['id'], 'name': c['name'], 'is_private': c.get('is_private'),
                      'is_archived': c.get('is_archived'), 'topic': c.get('topic', {}).get('value'),
                      'purpose': c.get('purpose', {}).get('value'), 'messages': len(messages)})
        print(f'{i}/{len(jobs)} #{c["name"]}: {len(messages)} messages', flush=True)
    (out / 'channels.json').write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(f'done {time.strftime("%H:%M")}: {len(index)} channels backed up, {len(failed)} failed: {failed}')


if __name__ == '__main__':
    main()
