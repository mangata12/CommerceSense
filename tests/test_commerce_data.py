import unittest

import pandas as pd

from commerce_data import infer_field_mapping, normalise_commerce_data, validate_commerce_data


class CommerceDataTests(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame(
            {
                "订单编号": ["O1", "O2", "O2"],
                "商品编号": ["S1", "S2", "S2"],
                "购买数量": [1, 2, -1],
                "商品单价": [10, 20, 20],
                "下单时间": ["2026-09-01", "bad-date", "2026-09-03"],
            }
        )

    def test_infers_chinese_headers(self):
        mapping = infer_field_mapping(list(self.data.columns))
        self.assertEqual(mapping["order_id"], "订单编号")
        self.assertEqual(mapping["quantity"], "购买数量")
        self.assertEqual(mapping["order_time"], "下单时间")

    def test_normalises_without_dropping_original_columns(self):
        mapping = infer_field_mapping(list(self.data.columns))
        result = normalise_commerce_data(self.data, mapping)
        self.assertIn("order_id", result.columns)
        self.assertIn("订单编号", result.columns)
        self.assertEqual(len(result), 3)

    def test_validation_reports_invalid_and_negative_values(self):
        mapping = infer_field_mapping(list(self.data.columns))
        report = validate_commerce_data(self.data, mapping)
        self.assertEqual(report["rows"], 3)
        self.assertEqual(report["invalid_order_time"], 1)
        self.assertEqual(report["negative_quantity"], 1)
        self.assertEqual(report["duplicate_rows"], 0)


if __name__ == "__main__":
    unittest.main()
