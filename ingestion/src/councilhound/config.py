"""Central config, loaded from environment (.env in local dev)."""
import os
from dotenv import load_dotenv

load_dotenv()

# Empty string -> db/session.py falls back to an embedded dev Postgres
# (pgserver) under DATA_DIR, so local dev needs no Docker/managed DB.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GRANICUS_BASE_URL = os.environ.get("GRANICUS_BASE_URL", "https://fairfax.granicus.com")
GRANICUS_VIEW_IDS = [v.strip() for v in os.environ.get("GRANICUS_VIEW_IDS", "13").split(",") if v.strip()]
FAIRFAX_PROJECTS_URL = os.environ.get(
    "FAIRFAX_PROJECTS_URL",
    "https://www.fairfaxva.gov/Property-Business/Development/Projects",
)
FAIRFAX_PROJECTS_ARCGIS_URL = os.environ.get(
    "FAIRFAX_PROJECTS_ARCGIS_URL",
    "https://services2.arcgis.com/DANcyjLcCCpGk8Ri/arcgis/rest/services/"
    "Major_Developments_Project_Map_v2/FeatureServer/0/query",
)
# Anchor default data dir to the repo root (ingestion/src/councilhound/config.py
# -> three parents up), so CLI behavior doesn't depend on cwd. Overridden by
# env in Docker/cloud.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(_REPO_ROOT, "data"))
RAW_DATA_DIR = os.environ.get("RAW_DATA_DIR", os.path.join(DATA_DIR, "raw"))

# Granicus 403s requests without a browser-ish User-Agent (verified 2026-07-11
# against archive-video.granicus.com), so send one and be polite about rate.
USER_AGENT = os.environ.get(
    "SCRAPER_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 councilhound/0.1",
)
REQUEST_DELAY_SECONDS = float(os.environ.get("REQUEST_DELAY_SECONDS", "1.0"))

# Optional for the impact subsystem's ACS loader; anonymous access is fine at
# our volume, a key just raises the rate limit.
CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY", "")
