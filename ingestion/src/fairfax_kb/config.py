"""Central config, loaded from environment (.env in local dev)."""
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://fairfax:changeme@localhost:5432/fairfax_kb")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GRANICUS_BASE_URL = os.environ.get("GRANICUS_BASE_URL", "https://fairfax.granicus.com")
GRANICUS_VIEW_IDS = [v.strip() for v in os.environ.get("GRANICUS_VIEW_IDS", "13").split(",") if v.strip()]
RAW_DATA_DIR = os.environ.get("RAW_DATA_DIR", "./data/raw")
