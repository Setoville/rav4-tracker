"""Toyota inventory collection and client-side filtering."""

from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

import config


Vehicle = dict[str, Any]

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


def build_inventory_url(filters: dict[str, Any]) -> str:
    """Build the Toyota inventory URL that triggers GraphQL requests."""
    return INVENTORY_URL.format(
        ext_colors=",".join(filters.get("extColor", [])),
        int_colors=",".join(filters.get("intColor", [])),
        trims=",".join(filters.get("trim", [])),
        zipcode=filters["zipcode"],
        distance=filters.get("distance", 250),
    )


def accept_cookie_consent(page: Any) -> None:
    """Dismiss Toyota's consent banner when it is present."""
    selectors = [
        "button.cookie-banner__accept",
        "button:has-text('Accept')",
        "[aria-label='Accept Cookies']",
    ]
    for selector in selectors:
        try:
            button = page.locator(selector).first
            button.wait_for(state="visible", timeout=5000)
            button.click(timeout=5000)
            print("  Cookie consent accepted.")
            return
        except Exception:
            pass
    try:
        clicked = page.evaluate(
            """
            () => {
              for (const button of document.querySelectorAll("button")) {
                if (button.textContent.trim().toLowerCase() === "accept") {
                  button.click();
                  return true;
                }
              }
              return false;
            }
            """
        )
        if clicked:
            print("  Cookie consent accepted.")
    except Exception:
        pass


def validate_captured_pages(captured_pages: dict[int, dict[str, Any]]) -> tuple[list[Vehicle], dict[str, int]]:
    """Validate paginated GraphQL results before they affect state or alerts."""
    if not captured_pages:
        raise RuntimeError("No GraphQL responses captured — page may not have loaded correctly")

    pages = sorted(captured_pages.values(), key=lambda data: data["pagination"]["pageNo"])
    page_numbers = {data["pagination"]["pageNo"] for data in pages}
    total_pages = max(data["pagination"]["totalPages"] for data in pages)
    missing_pages = set(range(1, total_pages + 1)) - page_numbers
    if missing_pages:
        raise RuntimeError(f"Incomplete GraphQL capture — missing page(s): {sorted(missing_pages)}")

    total_records_values = {data["pagination"]["totalRecords"] for data in pages}
    if len(total_records_values) != 1:
        raise RuntimeError(f"Inconsistent GraphQL totals across pages: {sorted(total_records_values)}")
    total_records = total_records_values.pop()
    vehicles = [vehicle for page_data in pages for vehicle in page_data["vehicleSummary"]]
    if len(vehicles) != total_records:
        raise RuntimeError(
            f"Incomplete vehicle data — captured {len(vehicles)} of {total_records} records"
        )
    missing_vins = sum(1 for vehicle in vehicles if not vehicle.get("vin"))
    if missing_vins:
        raise RuntimeError(f"Vehicle data missing VINs: {missing_vins}")

    return vehicles, {
        "pages_captured": len(pages),
        "pages_expected": total_pages,
        "records_reported": total_records,
        "records_captured": len(vehicles),
    }


def fetch_all_vehicles() -> tuple[list[Vehicle], dict[str, int]]:
    """Capture Toyota's browser-issued GraphQL responses using persistent Chrome."""
    page_url = build_inventory_url(config.SEARCH_FILTERS)
    captured_pages: dict[int, dict[str, Any]] = {}

    def handle_response(response: Any) -> None:
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
        print(
            f"  Captured page {page_no}/{data['pagination']['totalPages']} "
            f"— {len(data['vehicleSummary'])} vehicles"
        )

    with sync_playwright() as playwright:
        browser_options: dict[str, Any] = {
            "headless": config.HEADLESS_BROWSER,
            "args": [] if config.HEADLESS_BROWSER else [
                "--window-position=0,0",
                "--window-size=1280,900",
            ],
        }
        if config.BROWSER_EXECUTABLE_PATH:
            browser_options["executable_path"] = config.BROWSER_EXECUTABLE_PATH
        else:
            browser_options["channel"] = "chrome"

        context = playwright.chromium.launch_persistent_context(
            config.CHROME_PROFILE_DIR,
            **browser_options,
        )
        page = context.new_page()
        page.on("response", handle_response)
        print("  Opening Toyota inventory page...")
        page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        accept_cookie_consent(page)
        page.wait_for_timeout(30000)

        Path("data").mkdir(exist_ok=True)
        page.screenshot(path="data/debug_screenshot.png", full_page=True)
        print(f"  Screenshot saved: {page.title()} — {page.url}")
        context.close()

    vehicles, summary = validate_captured_pages(captured_pages)
    print(f"  Fetched {len(vehicles)} of {summary['records_reported']} total vehicles")
    return vehicles, summary


def matches_availability(vehicle: Vehicle, availability: set[str]) -> bool:
    """Return whether Toyota's free-form status matches requested availability."""
    if not availability:
        return True
    status = vehicle.get("inventoryStatus") or ""
    normalized = status.lower()
    if "inTransitTrue" in availability and (
        "in transit" in normalized or "build phase" in normalized
    ):
        return True
    if "salePendingTrue" in availability and "sale pending" in normalized:
        return True
    return "atDealerTrue" in availability and not status


def apply_filters(
    vehicles: list[Vehicle], filters: dict[str, Any] | None = None
) -> list[Vehicle]:
    """Apply the requested color, trim, availability, and distance filters."""
    filters = config.SEARCH_FILTERS if filters is None else filters
    ext_colors = set(filters.get("extColor", []))
    int_colors = set(filters.get("intColor", []))
    trim_codes = {trim.split("-")[0] for trim in filters.get("trim", [])}
    availability = set(filters.get("availability", []))
    max_distance = filters.get("distance")

    result = []
    for vehicle in vehicles:
        if ext_colors and vehicle.get("extColor", {}).get("colorCd") not in ext_colors:
            continue
        if int_colors and vehicle.get("intColor", {}).get("colorCd") not in int_colors:
            continue
        if trim_codes and vehicle.get("model", {}).get("modelCd") not in trim_codes:
            continue
        if not matches_availability(vehicle, availability):
            continue
        if max_distance and (vehicle.get("distance") or 0) > max_distance:
            continue
        result.append(vehicle)
    return result
