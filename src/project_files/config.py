import os
from dotenv import load_dotenv
from src.project_files.models import ATSConfig

# I imported environment variables from a .env file because I don't want to hardcode secrets like API keys.
# You should create a .env file with SERPER_API_KEY=your_key_here.
load_dotenv()

# I defined all the ATS platforms I want to search. Each one has a name for internal use,
# a site_operator for Google site: queries, and a label for display. I chose these because
# they are common ATS systems. You can add more if you find others.
ATS_PLATFORMS = [
    ATSConfig(name="greenhouse", site_operator="greenhouse.io", label="Greenhouse"),
    ATSConfig(
        name="greenhouse_boards",
        site_operator="boards.greenhouse.io",
        label="Greenhouse Boards",
    ),
    ATSConfig(name="lever", site_operator="jobs.lever.co", label="Lever"),
    ATSConfig(name="ashby", site_operator="jobs.ashby.com", label="Ashby"),
    ATSConfig(name="workable", site_operator="apply.workable.com", label="Workable"),
    ATSConfig(name="bamboohr", site_operator="bamboohr.com/careers", label="BambooHR"),
    ATSConfig(name="jobvite", site_operator="jobs.jobvite.com", label="Jobvite"),
    ATSConfig(name="notion", site_operator="notion.site", label="Notion"),
    ATSConfig(
        name="smartrecruiters",
        site_operator="jobs.smartrecruiters.com",
        label="SmartRecruiters",
    ),
    ATSConfig(name="icims", site_operator="icims.com", label="iCIMS"),
    ATSConfig(name="personio", site_operator="jobs.personio.com", label="Personio"),
    ATSConfig(name="teamtailor", site_operator="teamtailor.com", label="Teamtailor"),
    ATSConfig(name="recruitee", site_operator="recruitee.com", label="Recruitee"),
    ATSConfig(name="breezy", site_operator="breezy.hr", label="Breezy HR"),
    ATSConfig(name="workday", site_operator="myworkdayjobs.com", label="Workday"),
    ATSConfig(name="taleo", site_operator="taleo.net/careersection", label="Taleo"),
    ATSConfig(name="jobadder", site_operator="jobadder.com", label="JobAdder"),
    ATSConfig(name="jazzhr", site_operator="applytojob.com", label="JazzHR"),
    ATSConfig(name="avature", site_operator="avature.net", label="Avature"),
    ATSConfig(
        name="successfactors", site_operator="jobs.sap.com", label="SAP SuccessFactors"
    ),
]

# I got the API key from environment variables. If it's not set, the SerperSearcher will raise an error.
# You need to sign up for Serper.dev and get a key.
SERPER_API_KEY: str | None = os.environ.get("SERPER_API_KEY")
# This is the endpoint I use for Serper API calls. It's fixed.
SERPER_ENDPOINT: str = "https://google.serper.dev/search"
# I limited the number of pages per platform to 3 to control costs. Each page costs 1 credit.
SERPER_MAX_PAGES: int = 3
