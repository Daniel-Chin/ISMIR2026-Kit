import re

import pandas as pd

from utils import slack as slackUtils


def event_channel_name(row, index):
    BLACKLIST = [
        "lunch", 'registration', 'tutorials (t1/t2/t3)', 'tutorials (t4/t5/t6)', 
        'welcome reception', 'late-breaking/demo',
    ]
    title = str(row.get("title", "") or "").strip()
    if title.lower() in BLACKLIST:
        return ""
    award_session = re.fullmatch(
        r"★?\s*Award\s+Nominees\s+Oral\s+Session\s*-\s*(\d+)",
        title,
        flags=re.IGNORECASE,
    )
    if award_session:
        return f"award-nominees-{award_session.group(1)}"
    if str(row.get("category", "")).strip().lower() == "special":
        title = re.sub(r"^lunch\s+", "", title, flags=re.IGNORECASE)
        return slackUtils.build_channel_name("", title, max_words=None)
    return slackUtils.build_channel_name("", title)


class Events:
    def __init__(self, eventsCsvFile, useDummyValues):
        self.eventsCsvFile = eventsCsvFile
        self.useDummyValues = useDummyValues

    def setupSlackChannels(self, *_):
        if self.eventsCsvFile is None:
            raise Exception("self.eventsCsvFile passed in constructor is null")

        csv_data = pd.read_csv(self.eventsCsvFile)
        slack_channel_column = "slack_channel"
        csv_data = slackUtils.populate_channel_names(
            csv_data,
            slack_channel_column,
            event_channel_name,
        )

        csv_data.to_csv(self.eventsCsvFile, index=False)
        print("Data output at: ", csv_data)
        print(
            'Event channel names generated. Please paste the updated "{slack_channel_column}" column back into the Google Sheet.'
        )

    def createSlackChannels(self, slack_client=None, *_):
        if self.eventsCsvFile is None:
            raise Exception("self.eventsCsvFile passed in constructor is null")

        csv_data = pd.read_csv(self.eventsCsvFile)
        slack_channel_column = "slack_channel"
        channel_names = [str(name).strip() for name in csv_data[
            slack_channel_column
        ].fillna("").tolist() if str(name).strip()]

        print("########### Now creating event slack channels ##########")
        target_client = slack_client or slackUtils
        target_client.createPublicSlackChannels(channel_names)
        target_client.loadAllChannelData()

        slackUtils.write_channel_links_to_csv(
            csv_data,
            self.eventsCsvFile,
            target_client,
            slack_channel_column,
            remind_to_paste_to_sheet=True,
        )
