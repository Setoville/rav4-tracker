#!/usr/bin/env python3
"""
RAV4 Tracker — polls Toyota's inventory API and notifies on new vehicles.
Run on a cron schedule, e.g. every 3 hours.
"""

import sqlite3
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

    def accept_cookie_consent(page) -> None:
        selectors = [
            "button.cookie-banner__accept",
            "button:has-text('Accept')",
            "[aria-label='Accept Cookies']",
        ]
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                btn.wait_for(state="visible", timeout=5000)
                btn.click(timeout=5000)
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

    with sync_playwright() as p:
        # Use a persistent Chrome profile so the WAF token is pre-solved.
        # On first run this seeds the profile; subsequent runs reuse it.
        # On a server with a display (xvfb), point CHROME_PROFILE_DIR to a
        # profile directory that was pre-seeded on a real machine.
        profile_dir = config.CHROME_PROFILE_DIR
        context = p.chromium.launch_persistent_context(
            profile_dir,
            channel="chrome",
            headless=config.HEADLESS_BROWSER,
            args=[] if config.HEADLESS_BROWSER else [
                "--window-position=9999,9999",
                "--window-size=1,1",
            ],
        )
        page = context.new_page()
        page.on("response", handle_response)

        print("  Opening Toyota inventory page...")
        page.goto(page_url, wait_until="domcontentloaded", timeout=60000)

        accept_cookie_consent(page)

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
# Vehicle store
# ---------------------------------------------------------------------------

def connect_db() -> sqlite3.Connection:
    path = Path(config.VEHICLE_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    columns = table_columns(conn, "vehicles")
    if "last_payload" in columns:
        migrate_vehicles_table_without_payload(conn)

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS vehicles (
            vin TEXT PRIMARY KEY,
            stock_num TEXT,
            brand TEXT,
            marketing_series TEXT,
            year INTEGER,
            dealer_cd TEXT,
            dealer_marketing_name TEXT,
            dealer_website TEXT,
            vdp_url TEXT,
            distance REAL,
            inventory_status TEXT,
            is_pre_sold INTEGER,
            total_msrp INTEGER,
            advertized_price INTEGER,
            base_msrp INTEGER,
            dph INTEGER,
            model_cd TEXT,
            model_marketing_name TEXT,
            model_marketing_title TEXT,
            int_color_cd TEXT,
            int_color_name TEXT,
            ext_color_cd TEXT,
            ext_color_name TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );

        DROP TABLE IF EXISTS vehicle_payloads;
        DROP VIEW IF EXISTS vehicle_summary;

        CREATE VIEW vehicle_summary AS
        SELECT
            vin,
            model_marketing_title AS model,
            ext_color_name AS exterior,
            int_color_name AS interior,
            total_msrp,
            dealer_marketing_name AS dealer,
            distance,
            inventory_status AS status,
            first_seen_at,
            last_seen_at
        FROM vehicles
        ORDER BY last_seen_at DESC, vin;
        """
    )
    conn.commit()


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def migrate_vehicles_table_without_payload(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS vehicle_summary;
        ALTER TABLE vehicles RENAME TO vehicles_old;

        CREATE TABLE vehicles (
            vin TEXT PRIMARY KEY,
            stock_num TEXT,
            brand TEXT,
            marketing_series TEXT,
            year INTEGER,
            dealer_cd TEXT,
            dealer_marketing_name TEXT,
            dealer_website TEXT,
            vdp_url TEXT,
            distance REAL,
            inventory_status TEXT,
            is_pre_sold INTEGER,
            total_msrp INTEGER,
            advertized_price INTEGER,
            base_msrp INTEGER,
            dph INTEGER,
            model_cd TEXT,
            model_marketing_name TEXT,
            model_marketing_title TEXT,
            int_color_cd TEXT,
            int_color_name TEXT,
            ext_color_cd TEXT,
            ext_color_name TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );

        INSERT INTO vehicles (
            vin,
            stock_num,
            brand,
            marketing_series,
            year,
            dealer_cd,
            dealer_marketing_name,
            dealer_website,
            vdp_url,
            distance,
            inventory_status,
            is_pre_sold,
            total_msrp,
            advertized_price,
            base_msrp,
            dph,
            model_cd,
            model_marketing_name,
            model_marketing_title,
            int_color_cd,
            int_color_name,
            ext_color_cd,
            ext_color_name,
            first_seen_at,
            last_seen_at
        )
        SELECT
            vin,
            stock_num,
            brand,
            marketing_series,
            year,
            dealer_cd,
            dealer_marketing_name,
            dealer_website,
            vdp_url,
            distance,
            inventory_status,
            is_pre_sold,
            total_msrp,
            advertized_price,
            base_msrp,
            dph,
            model_cd,
            model_marketing_name,
            model_marketing_title,
            int_color_cd,
            int_color_name,
            ext_color_cd,
            ext_color_name,
            first_seen_at,
            last_seen_at
        FROM vehicles_old
        WHERE last_payload IS NOT NULL
          AND last_payload != '{}';

        DROP TABLE vehicles_old;
        DROP TABLE IF EXISTS vehicle_payloads;
        """
    )
    conn.commit()


def load_tracked_vins(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT vin FROM vehicles").fetchall()
    return {row["vin"] for row in rows}


def vehicle_db_row(v: dict, now: str) -> dict:
    price = v.get("price") or {}
    model = v.get("model") or {}
    int_color = v.get("intColor") or {}
    ext_color = v.get("extColor") or {}
    return {
        "vin": v.get("vin"),
        "stock_num": v.get("stockNum"),
        "brand": v.get("brand"),
        "marketing_series": v.get("marketingSeries"),
        "year": v.get("year"),
        "dealer_cd": v.get("dealerCd"),
        "dealer_marketing_name": v.get("dealerMarketingName"),
        "dealer_website": v.get("dealerWebsite"),
        "vdp_url": v.get("vdpUrl"),
        "distance": v.get("distance"),
        "inventory_status": v.get("inventoryStatus"),
        "is_pre_sold": int(bool(v.get("isPreSold"))),
        "total_msrp": price.get("totalMsrp"),
        "advertized_price": price.get("advertizedPrice"),
        "base_msrp": price.get("baseMsrp"),
        "dph": price.get("dph"),
        "model_cd": model.get("modelCd"),
        "model_marketing_name": model.get("marketingName"),
        "model_marketing_title": model.get("marketingTitle"),
        "int_color_cd": int_color.get("colorCd"),
        "int_color_name": int_color.get("marketingName"),
        "ext_color_cd": ext_color.get("colorCd"),
        "ext_color_name": ext_color.get("marketingName"),
        "first_seen_at": now,
        "last_seen_at": now,
    }


def save_vehicles(conn: sqlite3.Connection, vehicles: list[dict]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    rows = [vehicle_db_row(v, now) for v in vehicles if v.get("vin")]
    conn.executemany(
        """
        INSERT INTO vehicles (
            vin,
            stock_num,
            brand,
            marketing_series,
            year,
            dealer_cd,
            dealer_marketing_name,
            dealer_website,
            vdp_url,
            distance,
            inventory_status,
            is_pre_sold,
            total_msrp,
            advertized_price,
            base_msrp,
            dph,
            model_cd,
            model_marketing_name,
            model_marketing_title,
            int_color_cd,
            int_color_name,
            ext_color_cd,
            ext_color_name,
            first_seen_at,
            last_seen_at
        ) VALUES (
            :vin,
            :stock_num,
            :brand,
            :marketing_series,
            :year,
            :dealer_cd,
            :dealer_marketing_name,
            :dealer_website,
            :vdp_url,
            :distance,
            :inventory_status,
            :is_pre_sold,
            :total_msrp,
            :advertized_price,
            :base_msrp,
            :dph,
            :model_cd,
            :model_marketing_name,
            :model_marketing_title,
            :int_color_cd,
            :int_color_name,
            :ext_color_cd,
            :ext_color_name,
            :first_seen_at,
            :last_seen_at
        )
        ON CONFLICT(vin) DO UPDATE SET
            stock_num = excluded.stock_num,
            brand = excluded.brand,
            marketing_series = excluded.marketing_series,
            year = excluded.year,
            dealer_cd = excluded.dealer_cd,
            dealer_marketing_name = excluded.dealer_marketing_name,
            dealer_website = excluded.dealer_website,
            vdp_url = excluded.vdp_url,
            distance = excluded.distance,
            inventory_status = excluded.inventory_status,
            is_pre_sold = excluded.is_pre_sold,
            total_msrp = excluded.total_msrp,
            advertized_price = excluded.advertized_price,
            base_msrp = excluded.base_msrp,
            dph = excluded.dph,
            model_cd = excluded.model_cd,
            model_marketing_name = excluded.model_marketing_name,
            model_marketing_title = excluded.model_marketing_title,
            int_color_cd = excluded.int_color_cd,
            int_color_name = excluded.int_color_name,
            ext_color_cd = excluded.ext_color_cd,
            ext_color_name = excluded.ext_color_name,
            last_seen_at = excluded.last_seen_at
        """,
        rows,
    )
    conn.commit()


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

    if not config.DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL must be set to send notifications")

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

    with connect_db() as conn:
        init_db(conn)

        current_vins = {v["vin"] for v in filtered if v.get("vin")}
        tracked_vins = load_tracked_vins(conn)
        new_vins = current_vins - tracked_vins
        new_vehicles = [v for v in filtered if v.get("vin") in new_vins]

        if new_vehicles:
            print(f"  NEW: {sorted(new_vins)}")
            notify(new_vehicles)
        else:
            print("  No new vehicles.")

        save_vehicles(conn, filtered)
    print("  Done.")


if __name__ == "__main__":
    main()
