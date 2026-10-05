import os

import pandas as pd

MORNING_TUTORIAL_COL = "Select the morning session tutorial you wish to attend"
AFTERNOON_TUTORIAL_COL = "Select the afternoon session tutorial you wish to attend"
ATTENDEE_EMAIL = "Attendee Email"


def getCleanTitle(incoming):
    return str(incoming).replace('"', "").replace("=", "").strip().lower()


class Tutorials:
    """Provision tutorial Slack channels and assign registered attendees."""

    def __init__(self, eventsCsvFile, townscriptCsvFile, useDummyValues):
        self.eventsCsvFile = eventsCsvFile
        self.townscriptCsvFile = townscriptCsvFile
        self.useDummyValues = useDummyValues

    def _read_events(self):
        if self.eventsCsvFile is None:
            raise ValueError("eventsCsvFile is required")

        events = pd.read_csv(self.eventsCsvFile)
        required = {"category", "title", "slack_channel"}
        missing = required.difference(events.columns)
        if missing:
            raise ValueError(
                "events CSV is missing required columns: " + ", ".join(sorted(missing))
            )

        tutorial_mask = events["category"] == "Tutorials"
        tutorials = events.loc[tutorial_mask].copy()
        if tutorials.empty:
            raise ValueError("events CSV contains no Tutorials rows")
        if tutorials["slack_channel"].isna().any():
            raise ValueError("every tutorial needs a slack_channel value")

        return events, tutorial_mask, tutorials

    def setupChannelNames(self):
        from modules.events import Events

        Events(self.eventsCsvFile, self.useDummyValues, tutorials_only=True).setupSlackChannels()

    def createSlackChannels(self, slackUtils):
        """Create named private tutorial channels and write their links."""
        from modules.events import Events

        Events(self.eventsCsvFile, self.useDummyValues, tutorials_only=True).createSlackChannels(slackUtils)

    def addAdminsToChannels(self, slackUtils):
        """Add each entered Slack member to every tutorial channel."""
        _, _, tutorials = self._read_events()
        channels = list(dict.fromkeys(
            str(name).strip().lstrip("#") for name in tutorials["slack_channel"]
        ))
        if any(not channel for channel in channels):
            raise ValueError("every tutorial needs a slack_channel value")

        while True:
            email = input("Admin email (empty to finish): ").strip()
            if not email:
                return
            for channel in channels:
                print(f"Adding admin {email} to channel {channel}")
                slackUtils.inviteUserToChannel(email, channel)

    def _attendees_by_channel(self, tutorials):
        if self.townscriptCsvFile is None:
            raise ValueError("registration CSV is required for attendee assignment")

        registration = pd.read_csv(self.townscriptCsvFile)
        required = {
            MORNING_TUTORIAL_COL,
            AFTERNOON_TUTORIAL_COL,
            ATTENDEE_EMAIL,
        }
        missing = required.difference(registration.columns)
        if missing:
            raise ValueError(
                "registration CSV is missing required columns: "
                + ", ".join(sorted(missing))
            )

        title_to_channel = {
            getCleanTitle(row["title"]): str(row["slack_channel"]).lstrip("#")
            for _, row in tutorials.iterrows()
        }
        attendees = {channel: set() for channel in title_to_channel.values()}
        titles_not_found = set()

        for _, row in registration.iterrows():
            email = str(row[ATTENDEE_EMAIL]).strip()
            if not email or email.lower() == "nan":
                continue
            for column in (MORNING_TUTORIAL_COL, AFTERNOON_TUTORIAL_COL):
                title = getCleanTitle(row[column])
                if not title or title == "nan":
                    continue
                channel = title_to_channel.get(title)
                if channel is None:
                    titles_not_found.add(title)
                else:
                    attendees[channel].add(email)

        if titles_not_found:
            print("Registration tutorial titles not found:", sorted(titles_not_found))
        return attendees

    def inviteAttendeesToChannels(self, slackUtils):
        """Assign active or pending invited attendees to tutorial channels."""

        _, _, tutorials = self._read_events()
        attendees = self._attendees_by_channel(tutorials)

        if self.useDummyValues:
            dummy_email = os.environ.get(
                "DUMMY_EMAIL", "default_dummy_email@example.com"
            )
            attendees = {channel: {dummy_email} for channel in attendees}

        for channel, emails in attendees.items():
            for email in sorted(emails):
                print(f"Adding user {email} to channel {channel}")
                slackUtils.inviteUserToChannel(email, channel)

    def setupSlackChannels(self, slackUtils):
        """Compatibility action: create private channels, then assign attendees."""

        self.createSlackChannels(slackUtils)
        self.inviteAttendeesToChannels(slackUtils)
