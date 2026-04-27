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
# Discord webhook — no account/bot required
# 1. Right-click a Discord channel → Edit Channel → Integrations → Webhooks
# 2. New Webhook → Copy Webhook URL
# 3. Set DISCORD_WEBHOOK_URL as a GitHub Actions secret (or paste it below)
# ---------------------------------------------------------------------------
DISCORD_WEBHOOK_URL = os.environ.get(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1497648115182731416/WClwYlUsHTeR0jX_g3SiRfK4MXHkpiwtS9PCxHA_oOQeMlMoRpNjpM0tPF2avqHAuBsV",
)

# ---------------------------------------------------------------------------
# Storage & browser
# ---------------------------------------------------------------------------

# Path to persistent VIN store
VIN_STORE_PATH = "data/seen_vins.json"

# Chrome profile directory — reusing your real Chrome profile passes the WAF
# challenge without needing to solve it fresh each run.
# Find yours at chrome://version → "Profile Path"
CHROME_PROFILE_DIR = os.environ.get(
    "CHROME_PROFILE_DIR",
    str(Path.home() / "Library/Application Support/Google/Chrome/Default"),
)
