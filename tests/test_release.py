"""Release integration: real file readers through mapping and report exports."""

import io
import unittest

import pandas as pd

from commerce_data import load_commerce_file
from commerce_session import load_dataset, apply_dataset_mapping
from commerce_diagnosis import run_diagnosis
from commerce_report import build_report_bundle


class ReleaseIntegrationTests(unittest.TestCase):
    def test_csv_and_xlsx_reconcile_quality_ids_and_reports(self):
        raw = pd.DataFrame({
            "订单编号": ["0001", "0002", "0003", "0004", "0004", "0005"],
            "商品编号": ["01", "02", "01", "02", "02", "02"],
            "商品名称": ["同名商品"] * 6, "数量": ["2", "1", "-1", "0.125", "0.125", "1"],
            "单价": ["0.10", "0.30", "0.10", "8.00", "8.00", "1.00"],
            "日期": ["2026-09-01", "2026-09-01 23:59:59", "2026-09-02", "2026-09-02", "2026-09-02", "bad"],
        })
        csv = io.BytesIO(raw.to_csv(index=False).encode("utf-8-sig"))
        csv.name = "中文订单.csv"
        xlsx = io.BytesIO()
        raw.to_excel(xlsx, index=False)
        xlsx.name = "中文订单.xlsx"
        for uploaded in (csv, xlsx):
            with self.subTest(format=uploaded.name):
                state = {}
                load_dataset(state, uploaded)
                data = apply_dataset_mapping(state, state["commerce_mapping"], "CNY")["data"]
                result = run_diagnosis(data, ("2026-09-02", "2026-09-02"), ("2026-09-01", "2026-09-01"), state["commerce_quality"])
                self.assertEqual((result.quality["valid_rows"], result.quality["excluded_rows"], result.quality["duplicate_rows"]), (5, 1, 1))
                self.assertEqual(result.current["net_sales_minor"], 190)
                self.assertEqual(result.previous["net_sales_minor"], 50)
                self.assertEqual(result.delta_minor, 140)
                self.assertEqual(set(result.products["product_key"]), {"id:01", "id:02"})
                self.assertEqual(sum(result.products["delta_minor"]), result.delta_minor)
                bundle = build_report_bundle(result)
                metrics = pd.read_csv(io.BytesIO(bundle.metrics_csv), dtype=str).set_index("metric")
                self.assertEqual(metrics.loc["net_sales", "delta"], "1.40")
                evidence = pd.read_csv(io.BytesIO(bundle.evidence_csv), dtype=str)
                self.assertIn("0003", set(evidence["order_id"]))
                self.assertIn("0.125", set(evidence["quantity"]))
                self.assertEqual(len(evidence), 5)

    def test_legacy_xls_has_actionable_format_error(self):
        uploaded = io.BytesIO(b"not-an-xlsx")
        uploaded.name = "legacy.xls"
        with self.assertRaisesRegex(ValueError, "XLS.*XLSX"):
            load_commerce_file(uploaded)


if __name__ == "__main__":
    unittest.main()
