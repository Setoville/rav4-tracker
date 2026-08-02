import unittest

from rav4_tracker.inventory import apply_filters, validate_captured_pages


def vehicle(**overrides):
    result = {
        "vin": "VIN-1",
        "distance": 10,
        "inventoryStatus": "Vehicle may be in transit.",
        "extColor": {"colorCd": "0218"},
        "intColor": {"colorCd": "EE40"},
        "model": {"modelCd": "4444"},
    }
    result.update(overrides)
    return result


class InventoryTests(unittest.TestCase):
    filters = {
        "zipcode": "94085",
        "distance": 250,
        "availability": ["inTransitTrue"],
        "extColor": ["0218"],
        "intColor": ["EE40"],
        "trim": ["4444-2026"],
    }

    def test_filters_include_build_phase_as_future_inventory(self):
        build_phase = vehicle(inventoryStatus="Vehicle is in build phase.")
        self.assertEqual(apply_filters([build_phase], self.filters), [build_phase])

    def test_filters_reject_wrong_color_or_availability(self):
        wrong_color = vehicle(extColor={"colorCd": "0040"})
        at_dealer = vehicle(inventoryStatus="")
        self.assertEqual(apply_filters([wrong_color, at_dealer], self.filters), [])

    def test_validation_rejects_missing_page(self):
        pages = {
            1: {"pagination": {"pageNo": 1, "totalPages": 2, "totalRecords": 1}, "vehicleSummary": []}
        }
        with self.assertRaisesRegex(RuntimeError, "missing page"):
            validate_captured_pages(pages)

    def test_validation_rejects_implausibly_small_complete_result(self):
        pages = {
            1: {"pagination": {"pageNo": 1, "totalPages": 1, "totalRecords": 1}, "vehicleSummary": [vehicle()]}
        }
        with self.assertRaisesRegex(RuntimeError, "implausibly small"):
            validate_captured_pages(pages, minimum_total_records=100)

    def test_validation_returns_sorted_complete_results(self):
        first = vehicle(vin="FIRST")
        second = vehicle(vin="SECOND")
        pages = {
            2: {"pagination": {"pageNo": 2, "totalPages": 2, "totalRecords": 2}, "vehicleSummary": [second]},
            1: {"pagination": {"pageNo": 1, "totalPages": 2, "totalRecords": 2}, "vehicleSummary": [first]},
        }
        vehicles, summary = validate_captured_pages(pages, minimum_total_records=1)
        self.assertEqual([item["vin"] for item in vehicles], ["FIRST", "SECOND"])
        self.assertEqual(summary["records_captured"], 2)
