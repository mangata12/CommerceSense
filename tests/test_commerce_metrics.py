import unittest

import pandas as pd

from commerce_metrics import calculate_metrics, compare_periods, order_drilldown, product_contribution


class CommerceMetricsTests(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame(
            {
                "order_id": ["O1", "O2", "O3", "O3", "O4"],
                "product_id": ["S1", "S1", "S2", "S2", "S3"],
                "product_name": ["Bag", "Bag", "Mug", "Mug", "Lamp"],
                "quantity": [2, 1, 2, -1, 1],
                "unit_price": [10, 10, 20, 20, 80],
                "order_time": ["2026-09-01 10:00", "2026-09-02 10:00", "2026-09-03 10:00", "2026-09-03 11:00", "2026-09-10 10:00"],
                "customer_id": ["C1", "C2", "C3", "C3", "C4"],
            }
        )

    def test_metrics_separate_sales_reversals_and_net(self):
        result = calculate_metrics(self.data, "2026-09-01", "2026-09-03")
        self.assertEqual(result["order_count"], 3)
        self.assertEqual(result["gross_sales"], 70.0)
        self.assertEqual(result["reversal_amount"], 20.0)
        self.assertEqual(result["net_sales"], 50.0)
        self.assertEqual(result["average_order_value"], 16.67)

    def test_compare_periods_returns_deltas(self):
        result = compare_periods(self.data, "2026-09-01", "2026-09-03", "2026-09-10", "2026-09-10")
        net_sales = result.loc[result["metric"] == "net_sales"].iloc[0]
        self.assertEqual(net_sales["current"], 50.0)
        self.assertEqual(net_sales["previous"], 80.0)
        self.assertEqual(net_sales["delta"], -30.0)

    def test_product_contribution_ranks_by_absolute_delta(self):
        result = product_contribution(self.data, "2026-09-01", "2026-09-03", "2026-09-10", "2026-09-10")
        self.assertEqual(result.iloc[0]["product"], "Lamp")
        self.assertEqual(result.iloc[0]["delta"], -80.0)

    def test_order_drilldown_can_filter_product(self):
        result = order_drilldown(self.data, "2026-09-01", "2026-09-03", "Mug")
        self.assertEqual(len(result), 2)
        self.assertEqual(set(result["record_type"]), {"销售", "冲销"})


if __name__ == "__main__":
    unittest.main()
