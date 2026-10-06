"""
Sets the title. description, and other metadata for YouTube videos.  
uv run python -m scripts.decorate_youtube_videos --dry-run
"""

from __future__ import annotations

import argparse
import copy
import csv
import io
import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict, cast

from tqdm import tqdm

from utils.session_assignment import parse_file
from utils.shared import load_site_config

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource
    from googleapiclient.http import HttpRequest
from urllib.parse import parse_qs, urlparse

EXPECTED_CHANNEL_ID = 'UC_L9sCoMJqF3I42IAbO7Bfg'    # change this to your channel ID. https://www.youtube.com/account_advanced
ROOT = Path(__file__).resolve().parent.parent
SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']
SNIPPET_FIELDS = {'title', 'description', 'categoryId', 'defaultLanguage', 'tags',
                  'defaultAudioLanguage'}
STATUS_FIELDS = {'privacyStatus', 'license', 'embeddable', 'publicStatsViewable',
                 'publishAt', 'selfDeclaredMadeForKids', 'containsSyntheticMedia'}


# The API's discovery-generated payloads are dynamic.
APIObject = dict[str, Any]


class PaperRow(TypedDict):
    """CSV cells are strings; optional columns may be absent in smaller exports."""

    uid: str
    title: str
    authors_and_affil: str
    abstract: str
    raw_video: str
    video: NotRequired[str]


class Metadata(TypedDict):
    paper_id: str
    google_drive_id: str


class UpdatePlan(TypedDict):
    uid: str
    body: APIObject
    before: dict[str, APIObject]
    url: str | None
    classification: Literal['current', 'outdated']


def generate_title(paper: PaperRow) -> str:
    _, papers = parse_file('./sitedata/')
    matches = [p for p in papers if p.uid == paper['uid']]
    if len(matches) != 1:
        raise SafetyError(f'Paper {paper["uid"]} appears {len(matches)} times in session_assignment.csv')
    p, = matches
    proposal = f'P{p.session_index}-{p.position} {paper["title"]}'
    return proposal[:100]


def generate_description(paper: PaperRow) -> str:
    config = load_site_config('./sitedata/')
    conf_name = config['name']
    miniconf_url = config['miniconf_url']
    miniconf_page_url = f'{miniconf_url}/poster_{paper["uid"]}'  # site serves extensionless URLs
    short_url = miniconf_page_url.split('https://', 1)[-1]
    buf = []
    buf.append(f'Paper, Poster, and more: \n{short_url}\n\n')
    buf.append('Authors: ')
    buf.append(paper['authors_and_affil'])
    buf.append('\n\n')
    buf.append(f'Presented at {conf_name}.')
    buf.append('\n\n')
    buf.append('Abstract: \n')
    buf.append(paper['abstract'])
    buf.append('\n')
    return ''.join(buf)


class SafetyError(ValueError):
    """An unsafe or ambiguous input; no further operations are permitted."""


def identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise SafetyError(f'Malformed {label}: {value!r}')
    return value


def drive_id(value: object, allow_url: bool = False) -> str:
    if allow_url and isinstance(value, str) and value.startswith('https://'):
        url = urlparse(value)
        if url.netloc != 'drive.google.com' or url.fragment:
            raise SafetyError(f'Malformed Drive URL: {value!r}')
        match = re.fullmatch(r'/file/d/([A-Za-z0-9_-]+)(?:/view)?', url.path)
        query = parse_qs(url.query)
        if match and 'id' not in query:
            value = match[1]
        elif url.path in ('/open', '/uc') and len(query.get('id', [])) == 1:
            value = query['id'][0]
        else:
            raise SafetyError(f'Ambiguous Drive URL: {value!r}')
    return identifier(value, 'Google Drive ID')


def unique_object(pairs: list[tuple[str, Any]]) -> APIObject:
    result = dict[str, Any]()
    for key, value in pairs:
        if key in result:
            raise SafetyError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def validate_local(
    csv_path: Path, video_dir: Path,
) -> tuple[list[str], list[PaperRow], dict[str, PaperRow], bytes]:
    original = csv_path.read_bytes()
    reader = csv.DictReader(io.StringIO(original.decode('utf-8-sig'), newline=''))
    fields = list(reader.fieldnames or [])
    if len(fields) != len(set(fields)) or not {'uid', 'raw_video'} <= set(fields):
        raise SafetyError('CSV requires unique columns including uid and raw_video')
    rows = list[PaperRow]()
    papers = dict[str, PaperRow]()
    for raw_row in reader:
        if None in raw_row or any(value is None for value in raw_row.values()):
            raise SafetyError('Malformed CSV row')
        # Required columns and cell shapes have been checked at the CSV boundary.
        row = cast(PaperRow, raw_row)
        rows.append(row)
        uid = identifier(row['uid'], 'paper UID')
        if uid in papers:
            raise SafetyError(f'Duplicate CSV UID: {uid}')
        # Papers without videos may have an empty Drive cell.
        if row['raw_video']:
            drive_id(row['raw_video'], allow_url=True)
        papers[uid] = row
    recorded = json.loads((video_dir / 'download-state/video_urls.json').read_text(),
                          object_pairs_hook=unique_object)
    if not isinstance(recorded, dict):
        raise SafetyError('Download state must be a JSON object')
    mappings = dict[str, str]()
    for key, value in recorded.items():
        path = Path(key)
        if path.name != key:
            raise SafetyError(f'Invalid download-state filename: {key}')
        uid = identifier(path.stem if path.suffix else key, 'download UID')
        if uid in mappings:
            raise SafetyError(f'Duplicate download UID: {uid}')
        mappings[uid] = drive_id(value, allow_url=True)
    seen = set[str]()
    for path in sorted(video_dir.iterdir()):
        if path.name == 'download-state' and path.is_dir():
            continue
        if not path.is_file() or path.is_symlink() or not path.suffix:
            raise SafetyError(f'Unexpected local video entry: {path}')
        uid = identifier(path.stem, 'local video UID')
        if uid in seen:
            raise SafetyError(f'Duplicate local UID: {uid}')
        seen.add(uid)
        if uid not in papers or uid not in mappings:
            raise SafetyError(f'Missing provenance mapping for local UID: {uid}')
        if mappings[uid] != drive_id(papers[uid]['raw_video'], allow_url=True):
            raise SafetyError(f'Drive provenance mismatch for local UID: {uid}')
    return fields, rows, papers, original


def metadata(description: object) -> Metadata | None:
    if not isinstance(description, str):
        raise SafetyError('Video description is not a string')
    if 'ISMIR_METADATA' not in description:
        return None
    blocks = re.findall(r'(?:^|\n)---\nISMIR_METADATA\n(.*?)\s*\Z', description, re.S)
    if description.count('ISMIR_METADATA') != 1 or len(blocks) != 1:
        raise SafetyError('Malformed or ambiguous ISMIR_METADATA block')
    values = dict[str, str]()
    for line in blocks[0].splitlines():
        match = re.fullmatch(r'(paper_id|google_drive_id): ([A-Za-z0-9_-]+)', line)
        if not match or match[1] in values:
            raise SafetyError('Malformed or duplicate metadata field')
        values[match[1]] = match[2]
    if set(values) != {'paper_id', 'google_drive_id'}:
        raise SafetyError('Metadata requires paper_id and google_drive_id')
    return Metadata(paper_id=values['paper_id'], google_drive_id=values['google_drive_id'])


def execute(request: HttpRequest) -> APIObject:
    try:
        result = request.execute(num_retries=0)
    except Exception as exc:
        content = getattr(exc, 'content', b'')
        if any(reason in str(content) for reason in ('quotaExceeded', 'dailyLimitExceeded')):
            raise SafetyError('YouTube quota exhausted; aborted immediately') from exc
        raise SafetyError(f'YouTube request failed; aborted without retry: {exc}') from exc
    if not isinstance(result, dict):
        raise SafetyError('Unexpected API response')
    return result


def pages(resource: Resource, **kwargs: Any) -> Iterator[APIObject]:
    token = None
    seen = set[str]()
    while True:
        response = execute(resource.list(**kwargs, **({'pageToken': token} if token else {})))
        items = response.get('items')
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise SafetyError('API response missing valid items')
        yield from items
        token = response.get('nextPageToken')
        if token is None:
            break
        if not isinstance(token, str) or not token or token in seen:
            raise SafetyError('Invalid/repeated pagination token')
        seen.add(token)


def enumerate_videos(youtube: Resource) -> list[APIObject]:
    if not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', EXPECTED_CHANNEL_ID):
        raise SafetyError('Configure EXPECTED_CHANNEL_ID before calling YouTube')
    channels = list(pages(youtube.channels(), part='contentDetails', mine=True, maxResults=50))
    if len(channels) != 1 or channels[0].get('id') != EXPECTED_CHANNEL_ID:
        raise SafetyError('Authenticated channel does not exactly match EXPECTED_CHANNEL_ID')
    playlist = channels[0]['contentDetails']['relatedPlaylists']['uploads']
    if not isinstance(playlist, str) or not playlist:
        raise SafetyError('Missing uploads playlist')
    ids = list[str]()
    for item in pages(youtube.playlistItems(), part='contentDetails', playlistId=playlist, maxResults=50):
        video_id = item['contentDetails']['videoId']
        if not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id) or video_id in ids:
            raise SafetyError('Invalid or duplicate upload playlist video ID')
        ids.append(video_id)
    videos = list[APIObject]()
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        fetched = list(pages(youtube.videos(), part='snippet,status', id=','.join(batch), maxResults=50))
        if len(fetched) != len(batch) or {v.get('id') for v in fetched} != set(batch):
            raise SafetyError('Uploads playlist and videos response disagree')
        for video in fetched:
            if video['snippet']['channelId'] != EXPECTED_CHANNEL_ID:
                raise SafetyError('Video belongs to an unexpected channel')
            for key in ('title', 'description', 'categoryId'):
                if not isinstance(video['snippet'].get(key), str):
                    raise SafetyError(f'Missing video snippet.{key}')
            if video['status'].get('privacyStatus') not in ('private', 'unlisted', 'public'):
                raise SafetyError('Invalid video status')
        videos.extend(fetched)
    return videos


def mutable(video: APIObject) -> dict[str, APIObject]:
    return {part: {key: copy.deepcopy(value) for key, value in video[part].items() if key in keys}
            for part, keys in [('snippet', SNIPPET_FIELDS), ('status', STATUS_FIELDS)]}


def legalize(text: str, multiline: bool) -> str:
    """Make text acceptable to YouTube: no angle brackets or control characters."""
    text = text.replace('<', '‹').replace('>', '›')
    text = re.sub(r'\r\n?', '\n', text).replace('\t', ' ')
    text = ''.join(c for c in text if c == '\n' or unicodedata.category(c) != 'Cc')
    if not multiline:
        text = ' '.join(text.split())
    return text.strip()


def legalize_title(title: str) -> str:
    return legalize(title, multiline=False)[:100].rstrip()


def render(row: PaperRow) -> tuple[str, str]:
    title = legalize_title(generate_title(row))
    human = legalize(generate_description(row), multiline=True)
    if 'ISMIR_METADATA' in human:
        raise SafetyError('Human description template must not contain machine metadata')
    footer = ('\n\n---\nISMIR_METADATA\n'
              f"paper_id: {row['uid']}\ngoogle_drive_id: {drive_id(row['raw_video'], allow_url=True)}")
    budget = 4999 - len(footer.encode('utf-8'))
    if len(human.encode('utf-8')) > budget:
        ellipsis = '…'
        cut = budget - len(ellipsis.encode('utf-8'))
        human = human.encode('utf-8')[:cut].decode('utf-8', 'ignore').rstrip() + ellipsis
    description = human + footer
    return title, description


def fresh_paper_id(video: APIObject, papers: Mapping[str, PaperRow]) -> str | None:
    """A fresh upload has an integer title naming its paper and an empty description."""
    title = video['snippet']['title'].strip()
    if video['snippet']['description'].strip() or not re.fullmatch(r'\d+', title):
        return None
    matches = [uid for uid in papers if uid == title or (uid.isdigit() and int(uid) == int(title))]
    if len(matches) != 1:
        raise SafetyError(f'Fresh upload {video["id"]} titled {title!r} matches '
                          f'{len(matches)} CSV papers; expected exactly 1')
    return matches[0]


def plan_updates(
    videos: Sequence[APIObject], papers: Mapping[str, PaperRow],
) -> list[UpdatePlan]:
    # (video, is_current) per paper; fresh uploads are current by definition.
    by_paper = dict[str, list[tuple[APIObject, bool]]]()
    for video in videos:
        claim = metadata(video['snippet']['description'])
        if claim is None:
            uid = fresh_paper_id(video, papers)
            if uid is None:
                continue
            current = True
        else:
            uid = claim['paper_id']
            if uid not in papers:
                raise SafetyError(f'Managed paper absent from CSV: {uid}')
            current = claim['google_drive_id'] == drive_id(papers[uid]['raw_video'], allow_url=True)
        by_paper.setdefault(uid, []).append((video, current))

    plans = list[UpdatePlan]()
    for uid, paper in papers.items():
        candidates = by_paper.get(uid, [])
        currents = [video['id'] for video, current in candidates if current]
        if len(currents) > 1:
            raise SafetyError(f'!!! Multiple non-outdated YouTube videos for paper {uid}: '
                              f'{", ".join(currents)}. Archive or delete extras by hand. Aborting.')
        for video, current in candidates:
            # Archived, private outdated uploads need no further changes.
            if not current and (video['status']['privacyStatus'] == 'private'
                                and video['snippet']['title'].startswith('[outdated]')):
                continue
            before = mutable(video)
            after = copy.deepcopy(before)
            if current:
                title, description = render(paper)
                after['snippet'].update(title=title, description=description,
                                        categoryId='28', defaultLanguage='en')
                after['status'].update(privacyStatus='unlisted', license='creativeCommon',
                                       selfDeclaredMadeForKids=False)
            else:
                if not after['snippet']['title'].startswith('[outdated]'):
                    after['snippet']['title'] = legalize_title('[outdated] ' + after['snippet']['title'])
                after['snippet'].setdefault('defaultLanguage', 'en')
                after['status']['privacyStatus'] = 'private'
            # A scheduled publication would defeat private/unlisted visibility.
            after['status'].pop('publishAt', None)
            if not after['snippet']['title'] or len(after['snippet']['title']) > 100:
                raise SafetyError(f'Invalid generated title length for {uid}')
            if len(after['snippet']['description'].encode('utf-8')) > 5000:
                raise SafetyError(f'Generated description exceeds 5000 bytes for {uid}')
            body = {'id': video['id'], **{p: after[p] for p in after if before[p] != after[p]}}
            url = f"https://www.youtube.com/watch?v={video['id']}" if current else None
            plans.append({'uid': uid, 'body': body, 'before': before, 'url': url,
                          'classification': 'current' if current else 'outdated'})
    return plans


def summarize_coverage(rows: Sequence[PaperRow]) -> None:
    def count(raw: bool, vid: bool) -> int:
        return sum(bool(row['raw_video']) == raw and bool(row.get('video')) == vid for row in rows)
    print(f'papers.csv coverage ({len(rows)} papers):')
    print('                   video set  video empty')
    print(f'  raw_video set    {count(True, True):>9}  {count(True, False):>11}')
    print(f'  raw_video empty  {count(False, True):>9}  {count(False, False):>11}')


def atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            if mode is not None:
                os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def apply_updates(
    youtube: Resource, plans: Sequence[UpdatePlan], csv_path: Path,
    fields: list[str], rows: list[PaperRow], original: bytes, dry_run: bool = False,
) -> None:
    papers = {row['uid']: row for row in rows}
    for plan in tqdm(plans, desc='Videos', unit='video'):
        body = plan['body']
        parts = [part for part in ('snippet', 'status') if part in body]
        url = plan['url']
        csv_change = url is not None and papers[plan['uid']].get('video', '') != url
        if not parts and not csv_change:
            continue
        if csv_path.read_bytes() != original:
            raise SafetyError('CSV changed during execution; aborting')
        log = {**plan, 'csv_video_before': papers[plan['uid']].get('video', ''),
               'csv_video_after': plan['url'] if csv_change else None}
        tqdm.write(('DRY RUN ' if dry_run else 'PLANNED ') + json.dumps(log, ensure_ascii=False, sort_keys=True))
        if dry_run:
            continue
        if parts:
            response = execute(youtube.videos().update(part=','.join(parts), body=body))
            if response.get('id') != body['id'] or any(
                {k: response.get(p, {}).get(k) for k in body[p]} != body[p] for p in parts
            ) or any('publishAt' in response.get(p, {}) and 'publishAt' not in body[p] for p in parts):
                raise SafetyError('Update response differs from request; remote state may have changed')
            tqdm.write(f"COMPLETED YouTube {plan['classification']} update: {body['id']}")
        if csv_change and url is not None:
            if csv_path.read_bytes() != original:
                raise SafetyError('CSV changed during YouTube update; aborting')
            papers[plan['uid']]['video'] = url
            if 'video' not in fields:
                fields = [*fields, 'video']
            stream = io.StringIO(newline='')
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            updated = stream.getvalue().encode('utf-8-sig' if original.startswith(b'\xef\xbb\xbf') else 'utf-8')
            atomic_write(csv_path, updated, csv_path.stat().st_mode & 0o777)
            original = updated
            tqdm.write(f"COMPLETED CSV video update: {plan['uid']} -> {plan['url']}")


def authenticate() -> Resource:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    client_id = os.environ.get('google_client_id')
    client_secret = os.environ.get('google_client_secret')
    if not client_id or not client_secret:
        raise SafetyError('Set env vars google_client_id and google_client_secret')
    flow = InstalledAppFlow.from_client_config({'installed': {
        'client_id': client_id,
        'client_secret': client_secret,
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
    }}, SCOPES)
    credentials = flow.run_local_server(port=0)
    return build('youtube', 'v3', credentials=credentials, cache_discovery=False)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--input', type=Path, default=ROOT / 'sitedata/papers.csv')
        parser.add_argument('--videos', type=Path, default=ROOT / 'tmp/videos')
        parser.add_argument('--dry-run', action='store_true', help='Read and plan only; no CSV or YouTube writes')
        parser.add_argument('--drier-run', action='store_true',
                            help='No auth or API calls; pretend YouTube is empty and print the plan')
        parser.add_argument('--first-video', action='store_true',
                            help='Apply only the first planned update, for testing')
        args = parser.parse_args(argv)
        dry_run = args.dry_run or args.drier_run
        fields, rows, papers, original = validate_local(args.input, args.videos)
        if args.drier_run:
            print('DRIER RUN: no auth or API calls; pretending YouTube has no uploads.')
            youtube = cast('Resource', None)
            videos = list[APIObject]()
        else:
            if not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', EXPECTED_CHANNEL_ID):
                raise SafetyError('Set EXPECTED_CHANNEL_ID to the verified channel ID')
            youtube = authenticate()
            videos = enumerate_videos(youtube)
        managed = sum(metadata(v['snippet']['description']) is not None for v in videos)
        fresh = sum(metadata(v['snippet']['description']) is None
                    and fresh_paper_id(v, papers) is not None for v in videos)
        print(f'Found {len(videos)} uploads: {managed} with ISMIR_METADATA, {fresh} fresh, '
              f'{len(videos) - managed - fresh} unrelated and ignored.')
        plans = plan_updates(videos, papers)
        print(f'Planned {len(plans)} videos; ones needing no change are skipped silently.')
        if args.first_video:
            plans = plans[:1]
            print(f'FIRST VIDEO: limiting to {len(plans)} update.')
        apply_updates(youtube, plans, args.input, fields, rows, original, dry_run)
        if dry_run:
            print('DRY RUN: coverage below is the unchanged CSV.')
        summarize_coverage(rows)
        return 0
    finally:
        print('Reminder: paste the video column back into Google Sheets.')


if __name__ == '__main__':
    raise SystemExit(main())
