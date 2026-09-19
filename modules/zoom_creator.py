import re

import pandas as pd


class ZoomCreator:
    """
    Creates Zoom meetings for the live sessions in the events CSV and writes the
    join URLs back into its live_url column (via utils/zoom.py). Poster sessions
    get one pre-created breakout room per poster, named after the paper's Slack
    channel, so the poster craze can split into per-paper rooms.
    """

    # Tutorials are created manually; Lunch and Social need no call.
    SKIP_CATEGORIES = ("Tutorials", "Lunch", "Social")

    POSTER_SESSION_RE = re.compile(r"Poster Session - (\d+)")

    def __init__(self, eventsCsvFile, useDummyValues=True, papersCsvFile=None):
        self.eventsCsvFile = eventsCsvFile
        self.useDummyValues = useDummyValues
        self.papers = pd.read_csv(papersCsvFile) if papersCsvFile else None

    def _wantsZoom(self, row):
        return row["category"] not in self.SKIP_CATEGORIES

    def _breakoutRooms(self, row):
        """Room names (paper Slack channels) for a 'Poster Session - N' row, else None."""
        if self.papers is None:
            return None
        match = self.POSTER_SESSION_RE.match(str(row["title"]))
        if not match:
            return None
        sessionPapers = self.papers[
            (self.papers.day == row["day"])
            & (self.papers.session == int(match.group(1)))
        ].sort_values("position")
        rooms = [str(ch) for ch in sessionPapers.slack_channel.dropna()]
        return rooms or None

    def setupZoomCalls(self, zoomUtils, passcode=None):
        if self.eventsCsvFile is None:
            raise Exception("eventsCsvFile passed in constructor is null")

        csv_data = pd.read_csv(self.eventsCsvFile)
        wanted = csv_data[csv_data.apply(self._wantsZoom, axis=1)]

        print("## Number of items to create zoom link for: ", len(wanted.index))
        print("### Final data: ", wanted[["uid", "title", "category"]])
        for _, row in wanted.iterrows():
            rooms = self._breakoutRooms(row)
            if rooms:
                print(f"### Breakout rooms for '{row['title']}': {rooms}")

        if self.useDummyValues:
            print("## Dummy mode (no --prod true): no Zoom API calls made.")
            return

        zoomUtils.createZoomLinksIfNeeded(
            self.eventsCsvFile,
            "title",
            "live_url",
            "uid",
            rowFilter=self._wantsZoom,
            breakoutRoomsForRow=self._breakoutRooms,
            passcode=passcode,
        )
