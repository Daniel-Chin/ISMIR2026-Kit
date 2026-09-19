import pandas as pd
import re
import os
from tqdm import tqdm

from utils import slack as slackUtils
from utils.shared import format_session_window, load_conference_timezone_name, load_site_config
from utils.zoom_redirect import (
    build_zoom_redirect_url,
    load_zoom_redirect_access_token,
)


def title2channelID(
    title: str,
    paper_id = None,
    session_number: int | None = None,
    paper_number: int | None = None,
) -> str:
    if session_number is not None and paper_number is not None:
        prefix = f"p{session_number}-{paper_number}"
    else:
        prefix = f"p{paper_id}"

    return slackUtils.build_channel_name(prefix, title)


# Defining the class that exposes the methods related to papaers.
class Papers:
    """
    This method takes the config data loaded and the papers csv file.
    """

    def __init__(self, data_path, papersCsvFile, useDummyValues, eventsCsvFile=None):
        self.data_path = data_path
        self.papersCsvFile = papersCsvFile
        self.useDummyValues = useDummyValues
        self.eventsCsvFile = eventsCsvFile
        data_dir = (
            os.path.dirname(self.papersCsvFile) if self.papersCsvFile else "sitedata"
        )
        self.conference_timezone = load_conference_timezone_name(data_dir)

    """
    This method inputs the zoomUtils and setup zoom calls for the all the sessions.
    """

    def setupSlackChannels(self, *_):
        if self.papersCsvFile is None:
            raise Exception("self.papersCsvFile passed in contructor is null")

        # Reading the papers data.
        csv_data = pd.read_csv(self.papersCsvFile)

        slack_channel_column = "slack_channel"

        csv_data = slackUtils.populate_channel_names(
            csv_data,
            slack_channel_column,
            lambda row, _: title2channelID(
                row["title"],
                session_number=row["session"],
                paper_number=row["position"],
            ),
        )

        print("Data output at: ", csv_data)
        # Updating the file with the details to be able to write the slack columns.
        csv_data.to_csv(self.papersCsvFile, index=False)
        print(
            f'Paper channel names generated. Please paste the updated "{slack_channel_column}" column back into the Google Sheet.'
        )

    def createSlackChannels(self, *_):
        if self.papersCsvFile is None:
            raise Exception("self.papersCsvFile passed in contructor is null")

        # Reading the papers data.
        csv_data = pd.read_csv(self.papersCsvFile)
        slack_channel_column = "slack_channel"
        channel_names = [
            str(name).strip() for name in csv_data[slack_channel_column].tolist() if str(name).strip()
        ]

        print("########### Now creating slack channels ##########")
        slackUtils.createPublicSlackChannels(channel_names)

        #  force reloading all channel data.
        slackUtils.loadAllChannelData()

        # Adding the channel link to the file.
        slackUtils.write_channel_links_to_csv(
            csv_data,
            self.papersCsvFile,
            slackUtils,
            slack_channel_column,
            remind_to_paste_to_sheet=True,
        )

    def inviteAuthorsToChannels(self):
        if self.papersCsvFile is None:
            raise Exception("self.papersCsvFile passed in contructor is null")
        # Reading the papers data.
        csv_data = pd.read_csv(self.papersCsvFile)
        slack_channel_column = "slack_channel"
        # Adding the authors to the papers channel.
        user_details = {}
        for index, data in csv_data.iterrows():
            # print("Row is: ", data)
            user_details[data[slack_channel_column]] = (
                str(data["author_emails"]).replace(" ", "").replace("*", "").split(";")
            )

        if self.useDummyValues:
            print("Have to use dummy values!!!")
            for key in user_details:
                user_details[key] = [
                    os.environ.get("DUMMY_EMAIL", "default_dummy_email@example.com")
                ]

        # Sending invites to users.
        print("The user details are: ", user_details)

        # Finally sending invites.
        for key, emails in user_details.items():
            for email in emails:
                print("Sending email for ", key, " to ", email)
                slackUtils.inviteUserToChannel(email, key)

    def setSlackChannelDescription(self):
        if self.papersCsvFile is None:
            raise Exception("self.papersCsvFile passed in contructor is null")
        if self.eventsCsvFile is None:
            raise Exception("eventsCsvFile passed in constructor is null")

        csv_data = pd.read_csv(self.papersCsvFile)
        events_data = pd.read_csv(self.eventsCsvFile)
        zoom_redirect_token = load_zoom_redirect_access_token()
        site_base_url = load_site_config(self.data_path)["miniconf_url"]

        poster_session_details = {}
        for _, row in csv_data.iterrows():
            day = row["day"]
            session = row["session"]
            if pd.notna(day) and float(day).is_integer():
                day = int(day)
            if pd.notna(session) and float(session).is_integer():
                session = int(session)

            matching_events = events_data[
                (events_data["day"] == day)
                & (events_data["title"] == f"Poster Session - {session}")
            ]
            if matching_events.empty:
                raise Exception(
                    f"No event found for paper {row['uid']} (day {day}, "
                    f"session {session})."
                )

            event_row = matching_events.iloc[0]
            if pd.isna(event_row["live_url"]) or not str(event_row["live_url"]).strip():
                raise Exception(
                    f"The live_url for Poster Session - {session} is empty. "
                    "Run the setup-zoom action first."
                )
            zoom_url = build_zoom_redirect_url(
                site_base_url,
                str(event_row["uid"]),
                zoom_redirect_token,
            )

            poster_channel_name = str(event_row["slack_channel"]).strip()
            if not poster_channel_name:
                raise Exception(
                    f"Poster Session - {session} is missing slack_channel. "
                    "Run setup-event-channels and create-event-channels first."
                )

            poster_channel_id = slackUtils.getChannelID(poster_channel_name)
            if poster_channel_id is None:
                raise Exception(
                    f"Poster session channel '{poster_channel_name}' does not exist in Slack. "
                    "Run create-event-channels first."
                )

            poster_session_details[(day, session)] = {
                "title": str(event_row["title"]).strip(),
                "channel_name": poster_channel_name,
                "channel_id": poster_channel_id,
                "zoom_url": zoom_url,
                "session_window": format_session_window(
                    event_row.get("start_date"),
                    event_row.get("start_time"),
                    event_row.get("end_time"),
                    self.conference_timezone,
                ),
            }

        for details in poster_session_details.values():
            poster_topic = details["title"]
            poster_purpose = slackUtils.truncateText(
                f"{details['title']} - {details['session_window']}. "
                "During that time, use this Zoom room for live interaction with authors and audiences: "
                f"<{details['zoom_url']}>"
            , 250)
            slackUtils.updateTopicandPurpose(
                details["channel_name"],
                poster_topic,
                poster_purpose,
            )

        with tqdm(csv_data.iterrows()) as pbar:
            pbar.set_description("Setting Slack channel descriptions")
            for index, row in pbar:
                channel_name = row["slack_channel"]
                title = row["title"]
                paper_id = row["uid"]
                authors = (
                    row["authors_and_affil"]
                    .replace("*", "")
                    .replace(";", ",")
                    .replace("  ", " ")
                )
                authors = (
                    re.sub(r"\s*\(.*?\)", "", authors).replace("(", "").replace(")", "")
                )

                day = row["day"]
                session = row["session"]
                if pd.notna(day) and float(day).is_integer():
                    day = int(day)
                if pd.notna(session) and float(session).is_integer():
                    session = int(session)

                poster_details = poster_session_details[(day, session)]
                poster_channel_link = (
                    f"<#{poster_details['channel_id']}|"
                    f"{poster_details['channel_name']}>"
                )
                topic = f"Paper {paper_id}: {title}"
                purpose = slackUtils.truncateText(
                    f"\nPaper, poster, & more: <{site_base_url}/poster_{paper_id}.html>\n"
                    f"{poster_details['title']}: {poster_details['session_window']}.\n"
                    f"Go to {poster_channel_link} for the live Zoom room.\n"
                    f"{title}. {authors}"
                , 250)

                slackUtils.updateTopicandPurpose(channel_name, topic, purpose)
                pbar.set_postfix(channel=channel_name)
