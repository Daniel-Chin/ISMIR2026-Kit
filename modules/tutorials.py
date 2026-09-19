import os

import pandas as pd

MORNING_TUTORIAL_COL = "Select the morning session tutorial you wish to attend"
AFTERNOON_TUTORIAL_COL = "Select the afternoon session tutorial you wish to attend"
ATTENDEE_EMAIL = "Attendee Email"
PERMANENT_DEFAULT_CHANNELS = ("announcements", "help")


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

    def createPublicSlackChannels(self, slackUtils):
        """Create onboarding channels and write tutorial links to events.csv."""

        events, tutorial_mask, tutorials = self._read_events()
        tutorial_channels = (
            tutorials["slack_channel"].astype(str).str.lstrip("#").tolist()
        )
        channel_names = list(PERMANENT_DEFAULT_CHANNELS) + tutorial_channels

        print("Creating public onboarding channels")
        slackUtils.createPublicSlackChannels(channel_names)
        slackUtils.loadAllChannelData()

        if "channel_url" not in events:
            events["channel_url"] = ""
        events["channel_url"] = events["channel_url"].fillna("").astype(str)

        for index, channel_name in zip(tutorials.index, tutorial_channels):
            channel_id = slackUtils.getChannelID(channel_name)
            if channel_id is None:
                print(f"Channel {channel_name} was not found; link not written.")
                continue
            events.loc[index, "channel_url"] = (
                f"https://slack.com/app_redirect?channel={channel_id}"
            )

        events.to_csv(self.eventsCsvFile, index=False)
        print(
            "Public onboarding channels ready: "
            f"{len(PERMANENT_DEFAULT_CHANNELS)} permanent defaults and "
            f"{tutorial_mask.sum()} tutorial channel(s)"
        )

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
        """Compatibility action: create public channels, then assign attendees."""

        self.createPublicSlackChannels(slackUtils)
        self.inviteAttendeesToChannels(slackUtils)
