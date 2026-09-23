import unittest

import pandas as pd

from commerce_agent import serialise_payload


class CommerceAgentUtilityTests(unittest.TestCase):
    def test_serialises_dataframe_with_chinese_content(self):
        result = serialise_payload(pd.DataFrame({"商品": ["水杯"], "金额": [29.0]}))
        self.assertIn("水杯", result)
        self.assertIn("29.0", result)

    def test_serialises_dates(self):
        result = serialise_payload({"date": pd.Timestamp("2026-09-01")})
        self.assertIn("2026-09-01", result)


if __name__ == "__main__":
    unittest.main()
