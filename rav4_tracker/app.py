"""Application orchestration for one complete inventory scan."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from rav4_tracker.audit import audit_match, write_run_audit
from rav4_tracker.inventory import apply_filters, fetch_all_vehicles
from rav4_tracker.notifications import notify_healthcheck, notify_new_vehicles
from rav4_tracker.store import connect_db, init_db, load_tracked_vins, save_vehicles


def main() -> None:
    started_at = datetime.now().isoformat(timespec="seconds")
    audit: dict[str, Any] = {
        "run_id": str(uuid4()),
        "started_at": started_at,
        "status": "failure",
    }
    run_completed = False
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Checking Toyota RAV4 inventory...")
    try:
        audit["phase"] = "fetch"
        all_vehicles, fetch_summary = fetch_all_vehicles()
        audit.update(fetch_summary)

        audit["phase"] = "filter"
        filtered = apply_filters(all_vehicles)
        print(f"  {len(filtered)} vehicle(s) match your filters")

        audit["phase"] = "database"
        with connect_db() as connection:
            init_db(connection)
            current_vins = {vehicle["vin"] for vehicle in filtered if vehicle.get("vin")}
            tracked_vins = load_tracked_vins(connection)
            new_vins = current_vins - tracked_vins
            existing_vins = current_vins - new_vins
            new_vehicles = [vehicle for vehicle in filtered if vehicle.get("vin") in new_vins]
            audit.update({
                "filtered_count": len(filtered),
                "existing_vins": sorted(existing_vins),
                "new_vins": sorted(new_vins),
                "matches": [audit_match(vehicle) for vehicle in filtered],
            })
            print(f"  Existing: {sorted(existing_vins)}")
            print(f"  NEW: {sorted(new_vins)}" if new_vehicles else "  No new vehicles.")
            save_vehicles(connection, filtered)

        audit["phase"] = "notify"
        if new_vehicles:
            notify_new_vehicles(new_vehicles)
        audit["notifications"] = {
            "new_vehicle_alert": "sent" if new_vehicles else "not_needed",
            "healthcheck": "pending",
        }

        # A healthy Healthchecks ping is deliberately last: a completed scan
        # means the results were saved, alerted, and durably audited.
        audit["status"] = "success"
        audit["phase"] = "audit"
        audit["finished_at"] = datetime.now().isoformat(timespec="seconds")
        write_run_audit(audit)

        audit["phase"] = "healthcheck"
        notify_healthcheck(len(all_vehicles), len(filtered), existing_vins, new_vins)
        run_completed = True
        print("  Done.")
    except Exception as exc:
        audit["error"] = f"{type(exc).__name__}: {exc}"
        audit["status"] = "failure"
        print(f"  FAILED during {audit.get('phase', 'startup')}: {exc}")
        raise
    finally:
        if not run_completed:
            audit["finished_at"] = datetime.now().isoformat(timespec="seconds")
            try:
                write_run_audit(audit)
            except Exception as audit_error:
                # The nonzero service exit remains the authoritative failure
                # signal when the disk is also unable to accept an audit record.
                print(f"  WARNING: could not write failure audit log: {audit_error}")
