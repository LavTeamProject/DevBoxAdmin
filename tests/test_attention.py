import unittest
from unittest import mock

import attention


class Attention(unittest.TestCase):
    def test_cheap_has_no_brew_calls(self):
        with mock.patch.object(attention, "_cached", side_effect=AssertionError("deep only")):
            d = attention.attention({})
        self.assertFalse(d["deep"])
        self.assertIsInstance(d["items"], list)

    def test_pending_plans_item(self):
        with mock.patch("plans.list_plans", return_value={"pending": 2}):
            d = attention.attention({})
        self.assertIn("plans", [i["id"] for i in d["items"]])
        self.assertGreaterEqual(d["warn"], 1)

    def test_cached_swallows_errors(self):
        attention._cache.clear()
        self.assertIsNone(attention._cached("x", 60, lambda: 1 / 0))


if __name__ == "__main__":
    unittest.main()
