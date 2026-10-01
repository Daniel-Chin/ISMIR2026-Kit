from unittest.mock import Mock

import pytest
import requests

from catalogue.build_catalogue import read_csv, to_int, to_utc
from catalogue.schema import validate_catalogue
from utils import zoom
from utils.shared import format_session_window, load_site_config


@pytest.mark.parametrize('date,start,end', [
    (None, '09:00', '10:00'), ('2026-01-01', '', '10:00'),
    ('bad', '09:00', '10:00'), ('2026-01-01', 'bad', '10:00'),
    ('2026-02-30', '09:00', '10:00'), ('2026-01-01', '25:00', '10:00'),
])
def test_invalid_session_raises(date, start, end):
    with pytest.raises(ValueError):
        format_session_window(date, start, end, 'UTC')


def test_overnight_session_still_formats():
    assert format_session_window('2026-01-01', '23:30', '00:15', 'UTC') == (
        'Thu, Jan 01, 23:30 - Fri, Jan 02, 00:15 (GMT+0, UTC)'
    )


def test_missing_inputs_raise(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_site_config(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        read_csv(tmp_path / 'missing.csv')
    with pytest.raises(ValueError):
        to_int('invalid')
    with pytest.raises(ValueError):
        to_utc('', '09:00', None)
    with pytest.raises(ValueError, match='missing field'):
        validate_catalogue({})


@pytest.mark.parametrize('function,args', [
    ('deleteMeeting', ('123',)), ('deleteWebinar', ('123',)),
    ('deletePanelistFromWebinar', ('123', '456')),
])
def test_zoom_delete_http_failure_raises(monkeypatch, function, args):
    monkeypatch.setattr(zoom, 'checkToken', lambda: ('token', 0))
    response = requests.Response()
    response.status_code = 500
    monkeypatch.setattr(zoom.requests, 'delete', Mock(return_value=response))
    with pytest.raises(requests.HTTPError):
        getattr(zoom, function)(*args)


@pytest.mark.parametrize('row', [
    {}, {'start_time': 'bad', 'end_time': '10:00'},
    {'start_time': '10:00', 'end_time': '09:00'},
])
def test_invalid_zoom_duration_raises(row):
    with pytest.raises((KeyError, ValueError)):
        zoom._durationMinutes(row)


def test_slack_invitation_failure_raises(monkeypatch):
    from slack_sdk.errors import SlackApiError
    from utils import slack

    monkeypatch.setattr(slack, 'isUserAlreadyInChannel', lambda *args: False)
    monkeypatch.setattr(slack, 'getUserID', lambda *args: 'U1')
    monkeypatch.setattr(slack, 'getChannelID', lambda *args: 'C1')
    failure = SlackApiError('denied', {'error': 'not_in_channel'})
    monkeypatch.setattr(slack, 'addUserIDsToASlackChannelById', Mock(side_effect=failure))
    with pytest.raises(SlackApiError) as caught:
        slack.inviteUserToChannel('user@example.org', 'channel')
    assert caught.value is failure


@pytest.mark.parametrize('contents', ['', '[]', '{}'])
def test_invalid_site_config_raises(tmp_path, contents):
    (tmp_path / 'config.yml').write_text(contents)
    with pytest.raises(ValueError, match='nonempty mapping'):
        load_site_config(str(tmp_path))
