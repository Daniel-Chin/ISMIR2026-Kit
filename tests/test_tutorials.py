import pandas as pd

from modules.tutorials import (
    AFTERNOON_TUTORIAL_COL,
    ATTENDEE_EMAIL,
    MORNING_TUTORIAL_COL,
    Tutorials,
)


class FakeSlack:
    def __init__(self):
        self.channels = {}
        self.created_public = []
        self.invites = []
        self.reloads = 0

    def createPublicSlackChannels(self, channel_names):
        self.created_public.extend(channel_names)
        for index, name in enumerate(channel_names, start=1):
            self.channels[name] = f"C{index}"

    def loadAllChannelData(self):
        self.reloads += 1

    def getChannelID(self, channel_name):
        return self.channels.get(channel_name)

    def inviteUserToChannel(self, email, channel_name):
        self.invites.append((email, channel_name))


def write_events(path):
    pd.DataFrame(
        [
            {
                "uid": "1",
                "title": "Morning Tutorial",
                "category": "Tutorials",
                "slack_channel": "#tutorial-morning",
                "channel_url": "",
            },
            {
                "uid": "2",
                "title": "Afternoon Tutorial",
                "category": "Tutorials",
                "slack_channel": "tutorial-afternoon",
                "channel_url": "",
            },
            {
                "uid": "3",
                "title": "Opening",
                "category": "Opening",
                "slack_channel": "",
                "channel_url": "keep-me",
            },
        ]
    ).to_csv(path, index=False)


def write_registration(path):
    pd.DataFrame(
        [
            {
                ATTENDEE_EMAIL: "one@example.com",
                MORNING_TUTORIAL_COL: "Morning Tutorial",
                AFTERNOON_TUTORIAL_COL: "Afternoon Tutorial",
            },
            {
                ATTENDEE_EMAIL: "two@example.com",
                MORNING_TUTORIAL_COL: '"=Morning Tutorial"',
                AFTERNOON_TUTORIAL_COL: "",
            },
            {
                ATTENDEE_EMAIL: "one@example.com",
                MORNING_TUTORIAL_COL: "Morning Tutorial",
                AFTERNOON_TUTORIAL_COL: "Unknown Tutorial",
            },
        ]
    ).to_csv(path, index=False)


def test_create_tutorial_channels_public_and_write_links(tmp_path):
    events_path = tmp_path / "events.csv"
    write_events(events_path)
    slack = FakeSlack()

    Tutorials(events_path, None, useDummyValues=False).createPublicSlackChannels(slack)

    assert slack.created_public == [
        "announcements",
        "help",
        "tutorial-morning",
        "tutorial-afternoon",
    ]
    assert slack.reloads == 1
    events = pd.read_csv(events_path).fillna("")
    assert events.loc[0, "channel_url"] == ("https://slack.com/app_redirect?channel=C3")
    assert events.loc[1, "channel_url"] == ("https://slack.com/app_redirect?channel=C4")
    assert events.loc[2, "channel_url"] == "keep-me"


def test_invite_tutorial_attendees_is_separate_and_deduplicated(tmp_path):
    events_path = tmp_path / "events.csv"
    registration_path = tmp_path / "registration.csv"
    write_events(events_path)
    write_registration(registration_path)
    slack = FakeSlack()

    Tutorials(
        events_path, registration_path, useDummyValues=False
    ).inviteAttendeesToChannels(slack)

    assert slack.created_public == []
    assert slack.invites == [
        ("one@example.com", "tutorial-morning"),
        ("two@example.com", "tutorial-morning"),
        ("one@example.com", "tutorial-afternoon"),
    ]


def test_dummy_mode_uses_configured_dummy_email(tmp_path, monkeypatch):
    events_path = tmp_path / "events.csv"
    registration_path = tmp_path / "registration.csv"
    write_events(events_path)
    write_registration(registration_path)
    monkeypatch.setenv("DUMMY_EMAIL", "dummy@example.com")
    slack = FakeSlack()

    Tutorials(
        events_path, registration_path, useDummyValues=True
    ).inviteAttendeesToChannels(slack)

    assert slack.invites == [
        ("dummy@example.com", "tutorial-morning"),
        ("dummy@example.com", "tutorial-afternoon"),
    ]
