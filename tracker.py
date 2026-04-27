#!/usr/bin/env python3
"""
RAV4 Tracker — polls Toyota's inventory API and notifies on new vehicles.
Run on a cron schedule, e.g. every 3 hours.
"""

import json
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

import config


# ---------------------------------------------------------------------------
# Toyota GraphQL API (via Playwright to pass AWS WAF bot challenge)
# ---------------------------------------------------------------------------

INVENTORY_URL = (
    "https://www.toyota.com/search-inventory/model/rav4/"
    "?availability[]=salePendingTrue,inTransitTrue"
    "&extColor[]={ext_colors}"
    "&intColor[]={int_colors}"
    "&trim[]={trims}"
    "&zipcode={zipcode}"
    "&distance={distance}"
)

GRAPHQL_URL = "https://api.search-inventory.toyota.com/graphql"

SEARCH_QUERY = """
query {
  locateVehiclesByZip(
    zipCode: "%s"
    brand: "TOYOTA"
    pageNo: %d
    pageSize: 250
    seriesCodes: "rav4"
    distance: %d
    interiorMedia: true
  ) {
    pagination {
      pageNo
      pageSize
      totalPages
      totalRecords
    }
    vehicleSummary {
      vin
      stockNum
      brand
      marketingSeries
      year
      dealerCd
      inventoryStatus
      isPreSold
      dealerMarketingName
      dealerWebsite
      vdpUrl
      distance
      price {
        advertizedPrice
        totalMsrp
        baseMsrp
        dph
      }
      model {
        modelCd
        marketingName
        marketingTitle
      }
      intColor {
        colorCd
        marketingName
      }
      extColor {
        colorCd
        marketingName
      }
    }
  }
}
"""


def fetch_all_vehicles() -> list[dict]:
    """
    Launch a headless browser, navigate to Toyota's inventory page, and
    intercept the GraphQL responses the page makes naturally. This bypasses
    the AWS WAF bot challenge since the real browser solves it.
    """
    filters = config.SEARCH_FILTERS

    page_url = INVENTORY_URL.format(
        ext_colors=",".join(filters.get("extColor", [])),
        int_colors=",".join(filters.get("intColor", [])),
        trims=",".join(filters.get("trim", [])),
        zipcode=filters["zipcode"],
        distance=filters.get("distance", 250),
    )

    captured_pages: dict[int, dict] = {}

    def handle_response(response):
        if GRAPHQL_URL not in response.url:
            return
        try:
            body = response.json()
        except Exception:
            return
        data = body.get("data", {}).get("locateVehiclesByZip")
        if not data:
            return
        page_no = data["pagination"]["pageNo"]
        captured_pages[page_no] = data
        print(f"  Captured page {page_no}/{data['pagination']['totalPages']} "
              f"— {len(data['vehicleSummary'])} vehicles")

    with sync_playwright() as p:
        # Use a persistent Chrome profile so the WAF token is pre-solved.
        # On first run this seeds the profile; subsequent runs reuse it.
        # On a server with a display (xvfb), point CHROME_PROFILE_DIR to a
        # profile directory that was pre-seeded on a real machine.
        profile_dir = config.CHROME_PROFILE_DIR
        context = p.chromium.launch_persistent_context(
            profile_dir,
            channel="chrome",
            headless=False,
            args=["--window-position=9999,9999", "--window-size=1,1"],
        )
        page = context.new_page()
        page.on("response", handle_response)

        print("  Opening Toyota inventory page...")
        page.goto(page_url, wait_until="domcontentloaded", timeout=60000)

        # Accept cookie consent if present
        try:
            btn = page.locator("button.cookie-banner__accept")
            btn.wait_for(state="attached", timeout=10000)
            btn.evaluate("el => el.click()")
            print("  Cookie consent accepted.")
        except Exception:
            pass  # already accepted from a previous run

        # Wait for GraphQL responses to be captured (or up to 30s)
        page.wait_for_timeout(30000)

        # Save a screenshot for debugging
        Path("data").mkdir(exist_ok=True)
        page.screenshot(path="data/debug_screenshot.png", full_page=True)
        print(f"  Screenshot saved: {page.title()} — {page.url}")

        context.close()

    if not captured_pages:
        raise RuntimeError("No GraphQL responses captured — page may not have loaded correctly")

    vehicles = []
    total_records = 0
    for page_data in sorted(captured_pages.values(), key=lambda d: d["pagination"]["pageNo"]):
        vehicles.extend(page_data["vehicleSummary"])
        total_records = page_data["pagination"]["totalRecords"]

    print(f"  Fetched {len(vehicles)} of {total_records} total vehicles")
    return vehicles


def apply_filters(vehicles: list[dict]) -> list[dict]:
    """Apply color/trim/availability filters client-side (Toyota does this in-browser too)."""
    filters = config.SEARCH_FILTERS
    ext_colors = set(filters.get("extColor", []))
    int_colors = set(filters.get("intColor", []))
    # trim codes come as "4527-2026" — we only want the modelCd part before the dash
    trim_codes = {t.split("-")[0] for t in filters.get("trim", [])}
    availability = set(filters.get("availability", []))

    def matches_availability(v: dict) -> bool:
        if not availability:
            return True
        status = v.get("inventoryStatus") or ""
        s = status.lower()
        in_transit = "in transit" in s
        sale_pending = "sale pending" in s
        in_build = "build phase" in s
        at_dealer = not status  # empty status = at dealer / available now
        if "inTransitTrue" in availability and in_transit:
            return True
        if "salePendingTrue" in availability and sale_pending:
            return True
        if "inTransitTrue" in availability and in_build:
            return True  # treat build phase as a future in-transit
        if "atDealerTrue" in availability and at_dealer:
            return True
        return False

    max_distance = filters.get("distance")

    result = []
    for v in vehicles:
        if ext_colors and v.get("extColor", {}).get("colorCd") not in ext_colors:
            continue
        if int_colors and v.get("intColor", {}).get("colorCd") not in int_colors:
            continue
        if trim_codes and v.get("model", {}).get("modelCd") not in trim_codes:
            continue
        if availability and not matches_availability(v):
            continue
        if max_distance and (v.get("distance") or 0) > max_distance:
            continue
        result.append(v)

    return result


# ---------------------------------------------------------------------------
# VIN store
# ---------------------------------------------------------------------------

def load_seen_vins() -> set[str]:
    path = Path(config.VIN_STORE_PATH)
    if not path.exists():
        return set()
    with path.open() as f:
        return set(json.load(f))


def save_seen_vins(vins: set[str]) -> None:
    path = Path(config.VIN_STORE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(sorted(vins), f, indent=2)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def format_vehicle(v: dict) -> str:
    vin = v.get("vin", "unknown")
    model = v.get("model", {}).get("marketingTitle", "RAV4")
    dealer = v.get("dealerMarketingName", "unknown dealer")
    ext = v.get("extColor", {}).get("marketingName", "?")
    interior = v.get("intColor", {}).get("marketingName", "?")
    distance = v.get("distance")
    dist_str = f"{distance} mi away" if distance else ""
    price = v.get("price", {}).get("totalMsrp")
    price_str = f"${price:,}" if price else "price TBD"
    status = v.get("inventoryStatus") or "At dealer"
    zipcode = config.SEARCH_FILTERS.get("zipcode", "94085")
    vdp = v.get("vdpUrl") or f"https://www.toyota.com/search-inventory/model/rav4/?vin={vin}&zipcode={zipcode}"
    return (
        f"  VIN:    {vin}\n"
        f"  Model:  {model}\n"
        f"  Ext:    {ext}\n"
        f"  Int:    {interior}\n"
        f"  Price:  {price_str}\n"
        f"  Dealer: {dealer} ({dist_str})\n"
        f"  Status: {status}\n"
        f"  Link:   {vdp}"
    )


def notify(new_vehicles: list[dict]) -> None:
    import requests

    count = len(new_vehicles)
    lines = [f"**RAV4 Alert: {count} new vehicle{'s' if count > 1 else ''} found!**\n"]
    for v in new_vehicles:
        lines.append(format_vehicle(v))
        lines.append("")
    content = "\n".join(lines)[:2000]

    resp = requests.post(config.DISCORD_WEBHOOK_URL, json={"content": content})
    resp.raise_for_status()
    print("  Discord notification sent.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Checking Toyota RAV4 inventory...")

    all_vehicles = fetch_all_vehicles()
    filtered = apply_filters(all_vehicles)
    print(f"  {len(filtered)} vehicle(s) match your filters")

    current_vins = {v["vin"] for v in filtered if v.get("vin")}
    seen_vins = load_seen_vins()
    new_vins = current_vins - seen_vins
    new_vehicles = [v for v in filtered if v.get("vin") in new_vins]

    if new_vehicles:
        print(f"  NEW: {sorted(new_vins)}")
        notify(new_vehicles)
    else:
        print("  No new vehicles.")

    save_seen_vins(seen_vins | current_vins)
    print("  Done.")


if __name__ == "__main__":
    main()
