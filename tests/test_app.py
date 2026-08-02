import unittest
from unittest.mock import patch

from rav4_tracker import app


class Connection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class AppTests(unittest.TestCase):
    def test_healthcheck_success_is_sent_after_audit_when_no_new_vehicle_exists(self):
        vehicle = {
            "vin": "VIN-1",
            "model": {}, "price": {}, "intColor": {}, "extColor": {},
        }
        events = []
        with (
            patch.object(app, "fetch_all_vehicles", return_value=([vehicle], {"records_captured": 1})),
            patch.object(app, "apply_filters", return_value=[vehicle]),
            patch.object(app, "connect_db", return_value=Connection()),
            patch.object(app, "init_db"),
            patch.object(app, "load_tracked_vins", return_value={"VIN-1"}),
            patch.object(app, "save_vehicles", side_effect=lambda *_: events.append("database")),
            patch.object(app, "notify_new_vehicles"),
            patch.object(app, "write_run_audit", side_effect=lambda *_: events.append("audit")),
            patch.object(app, "notify_healthcheck", side_effect=lambda *_: events.append("healthcheck")),
        ):
            app.main()
        self.assertEqual(events, ["database", "audit", "healthcheck"])

    def test_new_vehicle_alert_is_sent_before_audit_and_healthcheck(self):
        vehicle = {
            "vin": "VIN-1",
            "model": {}, "price": {}, "intColor": {}, "extColor": {},
        }
        events = []
        with (
            patch.object(app, "fetch_all_vehicles", return_value=([vehicle], {"records_captured": 1})),
            patch.object(app, "apply_filters", return_value=[vehicle]),
            patch.object(app, "connect_db", return_value=Connection()),
            patch.object(app, "init_db"),
            patch.object(app, "load_tracked_vins", return_value=set()),
            patch.object(app, "save_vehicles", side_effect=lambda *_: events.append("database")),
            patch.object(app, "notify_new_vehicles", side_effect=lambda *_: events.append("discord")),
            patch.object(app, "write_run_audit", side_effect=lambda *_: events.append("audit")),
            patch.object(app, "notify_healthcheck", side_effect=lambda *_: events.append("healthcheck")),
        ):
            app.main()
        self.assertEqual(events, ["database", "discord", "audit", "healthcheck"])

    def test_healthcheck_delivery_failure_makes_the_run_fail_and_is_audited(self):
        vehicle = {
            "vin": "VIN-1",
            "model": {}, "price": {}, "intColor": {}, "extColor": {},
        }
        audit_records = []
        with (
            patch.object(app, "fetch_all_vehicles", return_value=([vehicle], {"records_captured": 1})),
            patch.object(app, "apply_filters", return_value=[vehicle]),
            patch.object(app, "connect_db", return_value=Connection()),
            patch.object(app, "init_db"),
            patch.object(app, "load_tracked_vins", return_value={"VIN-1"}),
            patch.object(app, "save_vehicles"),
            patch.object(app, "notify_new_vehicles"),
            patch.object(app, "write_run_audit", side_effect=lambda record: audit_records.append(record.copy())),
            patch.object(app, "notify_healthcheck", side_effect=RuntimeError("Healthchecks unavailable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Healthchecks unavailable"):
                app.main()
        self.assertEqual([record["status"] for record in audit_records], ["success", "failure"])
        self.assertEqual(audit_records[-1]["phase"], "healthcheck")
