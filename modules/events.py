import os

import pandas as pd

from utils import slack as slackUtils


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
            lambda row, index: slackUtils.build_channel_name(
                "",
                row.get("title", ""),
            ),
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
        channel_names = [str(name).strip() for name in csv_data[slack_channel_column].tolist() if str(name).strip()]

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
