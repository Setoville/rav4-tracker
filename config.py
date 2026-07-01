import os
from pathlib import Path

# Toyota GraphQL API
TOYOTA_API_URL = "https://api.search-inventory.toyota.com/graphql"

# Search filters (from your URL params)
SEARCH_FILTERS = {
    "zipcode": "94085",
    "distance": 250,
    "availability": ["salePendingTrue", "inTransitTrue"],
    "extColor": ["0218"],
    "intColor": ["EE40", "EA40"],
    "trim": ["4444-2026"],
}

# ---------------------------------------------------------------------------
# Discord webhook — no account/bot required.
# Set DISCORD_WEBHOOK_URL in your environment before running the tracker.
# ---------------------------------------------------------------------------
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# ---------------------------------------------------------------------------
# Storage & browser
# ---------------------------------------------------------------------------

# Path to persistent vehicle database
VEHICLE_DB_PATH = "data/vehicles.sqlite3"

# Run Chrome without opening a visible window. Toyota's inventory page currently
# does not emit inventory API responses in headless mode on this machine.
HEADLESS_BROWSER = os.environ.get("HEADLESS_BROWSER", "false").lower() in {
    "1",
    "true",
    "yes",
}

# Chrome profile directory — reusing your real Chrome profile passes the WAF
# challenge without needing to solve it fresh each run.
# Find yours at chrome://version → "Profile Path"
CHROME_PROFILE_DIR = os.environ.get(
    "CHROME_PROFILE_DIR",
    str(Path.home() / "Library/Application Support/Google/Chrome/Default"),
)
