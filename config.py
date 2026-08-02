import os
import platform
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
HEALTHCHECK_URL = os.environ.get("HEALTHCHECK_URL")

# ---------------------------------------------------------------------------
# Storage & browser
# ---------------------------------------------------------------------------

# Path to persistent vehicle database
VEHICLE_DB_PATH = "data/vehicles.sqlite3"
AUDIT_LOG_PATH = "data/run_history.jsonl"

# Toyota normally returns thousands of vehicles for the broad query before our
# client-side filters run. A much smaller response is likely a WAF/API issue,
# not a genuine empty market, so fail the run rather than silently accepting it.
MIN_TOTAL_RECORDS = 100
# Future adaptive guard: use max(MIN_TOTAL_RECORDS, 10% of a rolling median of
# recent successful result counts) once enough run history has accumulated.

# Run Chrome without opening a visible window. Toyota's inventory page currently
# does not emit inventory API responses in headless mode on this machine.
HEADLESS_BROWSER = os.environ.get("HEADLESS_BROWSER", "false").lower() in {
    "1",
    "true",
    "yes",
}

# Browser executable. macOS uses the installed Chrome channel by default;
# Linux deployments can point Playwright at the system Chromium package.
BROWSER_EXECUTABLE_PATH = os.environ.get("BROWSER_EXECUTABLE_PATH")

# Browser profile directory — reusing a persistent profile lets WAF/browser
# state survive between runs.
default_profile_dir = (
    Path.home() / "Library/Application Support/Google/Chrome/Default"
    if platform.system() == "Darwin"
    else Path.home() / ".local/share/rav4-tracker/chromium-profile"
)
CHROME_PROFILE_DIR = os.environ.get(
    "CHROME_PROFILE_DIR",
    str(default_profile_dir),
)
