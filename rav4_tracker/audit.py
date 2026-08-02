"""Durable, append-only records of completed and failed scan attempts."""

import json
import os
from pathlib import Path
from typing import Any

import config


def audit_match(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Return the stable, useful portion of a Toyota vehicle response."""
    price = vehicle.get("price") or {}
    model = vehicle.get("model") or {}
    int_color = vehicle.get("intColor") or {}
    ext_color = vehicle.get("extColor") or {}
    return {
        "vin": vehicle.get("vin"),
        "model": model.get("marketingTitle"),
        "exterior": ext_color.get("marketingName"),
        "interior": int_color.get("marketingName"),
        "total_msrp": price.get("totalMsrp"),
        "dealer": vehicle.get("dealerMarketingName"),
        "distance": vehicle.get("distance"),
        "status": vehicle.get("inventoryStatus"),
    }


def write_run_audit(record: dict[str, Any]) -> None:
    """Append and sync one audit record before reporting a healthy scan."""
    # Keep deployments compatible with configs created before audit logging was
    # introduced. Newer configs may still choose another location.
    path = Path(getattr(config, "AUDIT_LOG_PATH", "data/run_history.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, sort_keys=True) + "\n")
        file.flush()
        os.fsync(file.fileno())
