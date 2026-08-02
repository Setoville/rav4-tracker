import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rav4_tracker.audit import write_run_audit
from rav4_tracker.store import connect_db, init_db, load_tracked_vins, save_vehicles


def vehicle(vin: str, dealer: str) -> dict:
    return {
        "vin": vin,
        "dealerMarketingName": dealer,
        "model": {"modelCd": "4444", "marketingTitle": "RAV4 XLE Premium"},
        "extColor": {"colorCd": "0218", "marketingName": "Midnight Black"},
        "intColor": {"colorCd": "EE40", "marketingName": "Black"},
        "price": {"totalMsrp": 40000},
    }


class StoreTests(unittest.TestCase):
    def test_audit_log_uses_default_path_for_older_configs(self):
        with tempfile.TemporaryDirectory() as directory:
            original_path = os.getcwd()
            import rav4_tracker.audit as audit_module
            has_configured_path = hasattr(audit_module.config, "AUDIT_LOG_PATH")
            configured_path = getattr(audit_module.config, "AUDIT_LOG_PATH", None)
            try:
                if has_configured_path:
                    del audit_module.config.AUDIT_LOG_PATH
                os.chdir(directory)
                write_run_audit({"status": "success"})
            finally:
                os.chdir(original_path)
                if has_configured_path:
                    audit_module.config.AUDIT_LOG_PATH = configured_path
            audit_path = Path(directory) / "data" / "run_history.jsonl"
            self.assertEqual(audit_path.read_text(encoding="utf-8"), '{"status": "success"}\n')

    def test_saving_again_updates_vehicle_without_losing_first_seen(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "vehicles.sqlite3")
            with patch("rav4_tracker.store.config.VEHICLE_DB_PATH", database_path):
                with connect_db() as connection:
                    init_db(connection)
                    save_vehicles(connection, [vehicle("VIN-1", "First Toyota")])
                    first_seen = connection.execute(
                        "SELECT first_seen_at FROM vehicles WHERE vin = 'VIN-1'"
                    ).fetchone()[0]
                    save_vehicles(connection, [vehicle("VIN-1", "Second Toyota")])
                    row = connection.execute(
                        "SELECT first_seen_at, dealer_marketing_name FROM vehicles WHERE vin = 'VIN-1'"
                    ).fetchone()
                    self.assertEqual(load_tracked_vins(connection), {"VIN-1"})
                    self.assertEqual(row[0], first_seen)
                    self.assertEqual(row[1], "Second Toyota")
