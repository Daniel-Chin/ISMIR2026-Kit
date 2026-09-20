import argparse
import os

# module imports live inside the setup functions below: several modules pull in
# utils.slack, which needs SLACK_TOKEN at import time — deferring keeps
# credential-free actions (e.g. setup-zoom in dummy mode) runnable

# Prepare for tutorials
# 1. Go to /static/tutorials
# 2. Update the tutorial content as seen in the tut_X.md files.
# 3. Add/Remove tut_X.md files as necessary. Make sure they are consecutive in number

useDummyValues = True
DEFAULT_REGISTRATION_CSV = (
    "__23rd_International_Society_for_Music_Information_Retrieval_Conference_"
    "(ISMIR_2022)__Registration_Data.csv"
)


def prompt_for_zoom_passcode():
    return input(
        "Enter shared passcode for webinar and all poster meetings: "
    ).strip()


def parse_arguments():
    parser = argparse.ArgumentParser(description="MiniConf Prep Script")

    parser.add_argument(
        "--path",
        help="Pass the path of directory containing the master data.",
        required=False,
    )

    parser.add_argument(
        "--prod",
        help="set this value as true if we want to run on prod data.",
        default=False,
    )

    parser.add_argument(
        "--registration-csv",
        help="registration CSV used by tutorial/sponsor attendee assignment",
    )

    #### Possible actions ####
    # setup-zoom
    # setup-tutorials-create-channels
    # setup-tutorials-invite-attendees
    # setup-tutorials (compatibility: runs both stages)
    # setup-papers-set-desc
    # setup-event-channels
    # create-event-channels
    # set-event-channel-desc
    # setup-lbd
    # setup-music
    # setup-sponsors
    # remove-author-email
    # prepare-calendar
    # process-new-users

    parser.add_argument(
        "--action",
        help="action to run (for example setup-zoom, setup-tutorials-create-channels, setup-tutorials-invite-attendees, setup-papers-create-channels, setup-papers-set-desc, setup-event-channels, create-event-channels, set-event-channel-desc)",
        required=True,
    )

    args = parser.parse_args()
    return args


# Step1: Create Slack channels and Zoom links 
def setupZoom(eventsCsvFile, papersCsvFile=None, passcode=None):
    from modules.zoom_creator import ZoomCreator

    if passcode is None:
        passcode = prompt_for_zoom_passcode()
    zoomCreator = ZoomCreator(eventsCsvFile, useDummyValues, papersCsvFile)
    zoomCreator.setupZoomCalls(zoomUtils, passcode=passcode)


def setupTutorials(eventsCsvFile, registrationDataCsvFile, followup_action):
    from modules.tutorials import Tutorials

    tutObj = Tutorials(eventsCsvFile, registrationDataCsvFile, useDummyValues)
    if followup_action == "create-channels":
        tutObj.createPublicSlackChannels(slackUtils)
    elif followup_action == "invite-attendees":
        tutObj.inviteAttendeesToChannels(slackUtils)
    elif followup_action == "all":
        tutObj.setupSlackChannels(slackUtils)
    else:
        raise ValueError(f"Unknown tutorial action: {followup_action}")


def setupPapers(data_path, papersCsvFile, eventsCsvFile, followup_action):
    from modules.papers import Papers

    paperObj = Papers(data_path, papersCsvFile, useDummyValues, eventsCsvFile)
    if followup_action == "setup-channels":
        paperObj.setupSlackChannels()
    elif followup_action == "create-channels":
        paperObj.createSlackChannels()
    elif followup_action == "invite-authors":
        paperObj.inviteAuthorsToChannels()
    elif followup_action == "set-desc":
        paperObj.setSlackChannelDescription()
    else:
        raise Exception(
            "Invalid followup action for papers: "
            + followup_action
            + ". Possible values are setup-channels, create-channels, invite-authors"
        )


def setupEventChannels(eventsCsvFile):
    from modules.events import Events

    eventsObj = Events(eventsCsvFile, useDummyValues)
    eventsObj.setupSlackChannels()


def createEventChannels(eventsCsvFile):
    from modules.events import Events

    eventsObj = Events(eventsCsvFile, useDummyValues)
    eventsObj.createSlackChannels()


def setEventChannelDesc(data_path):
    from utils.slack import batch_set_channel_description_interactive

    batch_set_channel_description_interactive(data_path)

def setupLbds(lbdCsvFile):
    from modules.lbds import Lbds

    lbdObj = Lbds(lbdCsvFile, useDummyValues)
    lbdObj.setupSlackChannels(slackUtils)


def setupMusic(musicCsvFile):
    from modules.music import Music

    musicObj = Music(musicCsvFile, useDummyValues)
    musicObj.setupSlackChannels(slackUtils)


def setupSponsors(industryCsvFile, registrtionDataCsvFile):
    from modules.industry import Industry

    industryObj = Industry(industryCsvFile, registrtionDataCsvFile, useDummyValues)
    industryObj.setupSlackChannels(slackUtils)


def removeAuthorEmails():
    from scripts.remove_private_details import remove_author_contacts

    remove_author_contacts()


if __name__ == "__main__":
    args = parse_arguments()
    data_path = args.path
    useDummyValues = not args.prod
    action = args.action
    registration_csv = args.registration_csv or (
        os.path.join(data_path, DEFAULT_REGISTRATION_CSV) if data_path else None
    )

    if action is None:
        raise Exception(
            "--action is missing. See --help for available actions, including "
            "setup-tutorials-create-channels and "
            "setup-tutorials-invite-attendees."
        )

    if "setup" in action or "process" in action:
        if data_path is None:
            raise Exception("--path for the root directory for data is missing")
        if action == "setup-zoom":
            # zoom creds are only checked on first API call, so this import is
            # safe without .env and setup-zoom never needs SLACK_TOKEN
            from utils import zoom as zoomUtils
        else:
            from utils import slack as slackUtils

    if action == "setup-zoom":
        setupZoom(
            os.path.join(data_path, "events.csv"),
            os.path.join(data_path, "papers.csv"),
            passcode=None,
        )

    elif action == "setup-tutorials-create-channels":
        setupTutorials(
            os.path.join(data_path, "events.csv"),
            None,
            "create-channels",
        )

    elif action == "setup-tutorials-invite-attendees":
        setupTutorials(
            os.path.join(data_path, "events.csv"),
            registration_csv,
            "invite-attendees",
        )

    elif action == "setup-tutorials":
        setupTutorials(
            os.path.join(data_path, "events.csv"),
            registration_csv,
            "all",
        )

    elif action.startswith("setup-papers-"):
        folowup_action = action.replace("setup-papers-", "")
        setupPapers(
            data_path,
            os.path.join(data_path, "papers.csv"),
            os.path.join(data_path, "events.csv"),
            folowup_action,
        )

    elif action == "setup-event-channels":
        setupEventChannels(os.path.join(data_path, "events.csv"))

    elif action == "create-event-channels":
        createEventChannels(os.path.join(data_path, "events.csv"))
    
    elif action == "set-event-channel-desc":
        setEventChannelDesc(data_path)

    elif action == "setup-lbd":
        setupLbds(os.path.join(data_path, "lbds.csv"))

    elif action == "setup-music":
        setupMusic(os.path.join(data_path, "music.csv"))

    elif action == "setup-sponsors":
        setupSponsors(
            os.path.join(data_path, "industry.csv"),
            registration_csv,
        )

    elif action == "process-new-users":
        # First setup tutorials.
        setupTutorials(
            os.path.join(data_path, "events.csv"),
            registration_csv,
            "invite-attendees",
        )
        # Next setup sponsors.
        setupSponsors(
            os.path.join(data_path, "industry.csv"),
            registration_csv,
        )

    elif action == "remove-author-email":
        removeAuthorEmails()

    elif action == "prepare-calendar":
        # Step3: Prepare for calendar
        # If links from schedule are not redirecting to the right page, check this code
        from scripts.calendar_csv2ics import calendar_csv2ics
        from scripts.calendar_ics2json import calendar_ics2json

        if data_path is None:
            raise Exception("--path for the root directory for data is missing")
        calendar_path = os.path.join("static", "calendar", "ISMIR_2026.ics")
        calendar_csv2ics(
            in_csv=os.path.join(data_path, "events.csv"),
            out_ics=calendar_path,
        )
        calendar_ics2json(
            in_ics=calendar_path,
            out_json=os.path.join(data_path, "main_calendar.json"),
        )
