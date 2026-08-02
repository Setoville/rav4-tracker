"""Discord and Healthchecks.io notification delivery."""

from typing import Any

import requests

import config


DISCORD_MESSAGE_LIMIT = 1900


def format_vehicle(vehicle: dict[str, Any]) -> str:
    vin = vehicle.get("vin", "unknown")
    model = vehicle.get("model", {}).get("marketingTitle", "RAV4")
    dealer = vehicle.get("dealerMarketingName", "unknown dealer")
    exterior = vehicle.get("extColor", {}).get("marketingName", "?")
    interior = vehicle.get("intColor", {}).get("marketingName", "?")
    distance = vehicle.get("distance")
    distance_text = f"{distance} mi away" if distance else ""
    price = vehicle.get("price", {}).get("totalMsrp")
    price_text = f"${price:,}" if price else "price TBD"
    status = vehicle.get("inventoryStatus") or "At dealer"
    zipcode = config.SEARCH_FILTERS.get("zipcode", "94085")
    link = vehicle.get("vdpUrl") or (
        f"https://www.toyota.com/search-inventory/model/rav4/?vin={vin}&zipcode={zipcode}"
    )
    return (
        f"  VIN:    {vin}\n  Model:  {model}\n  Ext:    {exterior}\n"
        f"  Int:    {interior}\n  Price:  {price_text}\n"
        f"  Dealer: {dealer} ({distance_text})\n  Status: {status}\n  Link:   {link}"
    )


def post_discord(content: str) -> None:
    if not config.DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL must be set to send notifications")
    response = requests.post(config.DISCORD_WEBHOOK_URL, json={"content": content}, timeout=15)
    response.raise_for_status()


def vehicle_notification_messages(new_vehicles: list[dict[str, Any]]) -> list[str]:
    """Build Discord-safe messages containing detailed new-vehicle alerts."""
    count = len(new_vehicles)
    header = f"**RAV4 Alert: {count} new vehicle{'s' if count != 1 else ''} found!**\n"
    chunks: list[str] = []
    current = header
    for vehicle in new_vehicles:
        entry = f"\n{format_vehicle(vehicle)}\n"
        if len(current) > len(header) and len(current) + len(entry) > DISCORD_MESSAGE_LIMIT:
            chunks.append(current.rstrip())
            current = header
        current += entry
    if current.strip():
        chunks.append(current.rstrip())
    return chunks


def notify_new_vehicles(new_vehicles: list[dict[str, Any]]) -> None:
    chunks = vehicle_notification_messages(new_vehicles)
    for chunk in chunks:
        post_discord(chunk)
    print(f"  Discord vehicle notification sent ({len(chunks)} message(s)).")


def notify_healthcheck(
    fetched_count: int, filtered_count: int, existing_vins: set[str], new_vins: set[str]
) -> None:
    """Report a fully validated Toyota scan to Healthchecks.io."""
    if not config.HEALTHCHECK_URL:
        print("  Healthcheck URL not configured; skipping detailed health ping.")
        return
    summary = (
        f"Toyota scan OK; fetched={fetched_count}; filtered={filtered_count}; "
        f"existing={len(existing_vins)}; new={len(new_vins)}"
    )
    response = requests.post(f"{config.HEALTHCHECK_URL}/0", data=summary, timeout=10)
    response.raise_for_status()
    print(f"  Healthcheck success sent: {summary}")
