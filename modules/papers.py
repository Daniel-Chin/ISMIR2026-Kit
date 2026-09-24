import re
import os

import pandas as pd
from tqdm import tqdm

from utils import slack as slackUtils
from utils.shared import format_session_window, load_conference_timezone_name, load_site_config
from utils.session_assignment import parse_file


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

    def _paper_assignments(self, csv_data):
        _, papers = parse_file(self.data_path)
        assignments = {paper.uid: paper for paper in papers}
        missing = [uid for uid in csv_data["uid"] if uid not in assignments]
        if missing:
            raise ValueError(
                "Papers missing from session_assignment.csv: " + ", ".join(missing)
            )
        return assignments

    """
    This method inputs the zoomUtils and setup zoom calls for the all the sessions.
    """

    def setupSlackChannels(self, *_):
        if self.papersCsvFile is None:
            raise Exception("self.papersCsvFile passed in contructor is null")

        # Reading the papers data.
        csv_data = pd.read_csv(self.papersCsvFile, dtype={"uid": str})

        slack_channel_column = "slack_channel"
        assignments = self._paper_assignments(csv_data)

        csv_data = slackUtils.populate_channel_names(
            csv_data,
            slack_channel_column,
            lambda row, _: title2channelID(
                row["title"],
                session_number=assignments[row["uid"]].session_index,
                paper_number=assignments[row["uid"]].position,
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
        csv_data = pd.read_csv(self.papersCsvFile, dtype={"uid": str})
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
        csv_data = pd.read_csv(self.papersCsvFile, dtype={"uid": str})
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

        csv_data = pd.read_csv(self.papersCsvFile, dtype={"uid": str})
        events_data = pd.read_csv(self.eventsCsvFile)
        assignments = self._paper_assignments(csv_data)
        site_base_url = load_site_config(self.data_path)["miniconf_url"]

        poster_session_details = {}
        for _, row in csv_data.iterrows():
            assignment = assignments[row["uid"]]
            session = assignment.session_index
            if session in poster_session_details:
                continue

            # Session indices are global; assignment days are relative to the
            # first paper session, whereas event days may include tutorials.
            matching_events = events_data[
                events_data["title"] == f"Poster Session - {session}"
            ]
            if matching_events.empty:
                raise Exception(
                    f"No event found for paper {row['uid']} (session {session})."
                )

            event_row = matching_events.iloc[0]
            poster_channel_name = (
                "" if pd.isna(event_row["slack_channel"])
                else str(event_row["slack_channel"]).strip()
            )
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

            poster_session_details[session] = {
                "title": str(event_row["title"]).strip(),
                "channel_name": poster_channel_name,
                "channel_id": poster_channel_id,
                "session_window": format_session_window(
                    event_row.get("start_date"),
                    event_row.get("start_time"),
                    event_row.get("end_time"),
                    self.conference_timezone,
                ),
            }

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

                session = assignments[paper_id].session_index
                poster_details = poster_session_details[session]
                poster_channel_link = (
                    f"<#{poster_details['channel_id']}|"
                    f"{poster_details['channel_name']}>"
                )
                topic = f"Paper {paper_id}: {title}"
                purpose = slackUtils.truncateText(
                    f"_\nPaper, poster, & more: <{site_base_url}/poster_{paper_id}.html>\n"
                    f"{poster_details['title']}: {poster_details['session_window']}.\n"
                    f"Go to {poster_channel_link} for the live Zoom room.\n"
                    f"{title}. {authors}"
                , 250)

                slackUtils.updateTopicandPurpose(channel_name, topic, purpose)
                pbar.set_postfix(channel=channel_name)
