import unittest

from rav4_tracker.notifications import DISCORD_MESSAGE_LIMIT, vehicle_notification_messages


def vehicle(vin: str) -> dict:
    return {
        "vin": vin,
        "dealerMarketingName": "Example Toyota",
        "distance": 10,
        "inventoryStatus": "Vehicle may be in transit.",
        "model": {"marketingTitle": "RAV4 XLE Premium"},
        "extColor": {"marketingName": "Midnight Black"},
        "intColor": {"marketingName": "Black"},
        "price": {"totalMsrp": 40000},
    }


class NotificationTests(unittest.TestCase):
    def test_vehicle_alerts_are_split_before_discord_limit(self):
        messages = vehicle_notification_messages([vehicle(f"VIN-{number}") for number in range(30)])
        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= DISCORD_MESSAGE_LIMIT for message in messages))
        self.assertTrue(all("RAV4 Alert: 30 new vehicles found" in message for message in messages))
