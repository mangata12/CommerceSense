"""Regression cases for real upload / mapping / metric failure modes."""

import io
import json
import unittest
from decimal import Decimal

import pandas as pd

from commerce_data import load_commerce_file, prepare_commerce_data
from commerce_metrics import calculate_metrics, order_drilldown, product_contribution
from commerce_session import load_dataset, apply_dataset_mapping
from commerce_agent import build_commerce_tools


def upload(text, name="orders.csv", encoding="utf-8"):
    file = io.BytesIO(text.encode(encoding))
    file.name = name
    return file


class CommerceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.csv = "订单编号,商品编号,商品名称,数量,单价,日期,备选单价\n001,01,杯子,3,0.10,2026-09-01 23:59:59,1.00\n002,02,杯子,1,0.20,2026-09-02,2.00\n003,01,杯子,-1,0.10,2026-09-02,1.00\n"

    def test_rerun_preserves_mapping_and_applied_data(self):
        state = {}
        load_dataset(state, upload(self.csv))
        mapping = state["commerce_mapping"].copy()
        apply_dataset_mapping(state, mapping, "CNY")
        self.assertFalse(load_dataset(state, upload(self.csv)))
        self.assertEqual(state["commerce_standard_df"].iloc[0]["order_id"], "001")
        mapping["unit_price"] = "备选单价"
        state["commerce_agent_last_answer"] = "old answer"
        state["commerce_report"] = "old report"
        apply_dataset_mapping(state, mapping, "CNY")
        self.assertEqual(state["commerce_standard_df"].iloc[0]["unit_price"], Decimal("1.00"))
        self.assertNotIn("commerce_agent_last_answer", state)
        self.assertNotIn("commerce_report", state)
        mapping["unit_price"] = "单价"
        apply_dataset_mapping(state, mapping, "CNY")
        self.assertEqual(state["commerce_standard_df"].iloc[0]["unit_price"], Decimal("0.10"))
        self.assertEqual(state["commerce_raw_df"].iloc[0]["备选单价"], "1.00")

    def test_new_content_same_name_resets_results_and_currency(self):
        state = {}
        load_dataset(state, upload(self.csv))
        apply_dataset_mapping(state, state["commerce_mapping"], "CNY")
        state["commerce_agent_last_answer"] = "stale"
        state["commerce_messages"] = ["old"]
        state["commerce_chat_context"] = {"product_key": "id:01"}
        state["commerce_retry_question"] = "old question"
        state["commerce_mapping_order_id"] = "订单编号"
        self.assertTrue(load_dataset(state, upload(self.csv.replace("001", "009"))))
        self.assertIsNone(state["commerce_standard_df"])
        self.assertIsNone(state["commerce_currency"])
        self.assertNotIn("commerce_messages", state)
        self.assertNotIn("commerce_chat_context", state)
        self.assertNotIn("commerce_retry_question", state)
        self.assertNotIn("commerce_mapping_order_id", state)

    def test_gb_csv_and_xlsx_string_ids(self):
        loaded = load_commerce_file(upload(self.csv, encoding="gb18030"))
        self.assertEqual(loaded.iloc[0]["商品编号"], "01")
        file = io.BytesIO()
        loaded.to_excel(file, index=False)
        file.name = "orders.xlsx"
        self.assertEqual(load_commerce_file(file).iloc[0]["订单编号"], "001")

    def test_integer_amounts_same_name_distinct_ids_and_exact_drilldown(self):
        state = {}
        load_dataset(state, upload(self.csv))
        data = apply_dataset_mapping(state, state["commerce_mapping"], "CNY")["data"]
        metrics = calculate_metrics(data, "2026-09-01", "2026-09-02")
        self.assertEqual(metrics["net_sales_minor"], 40)
        self.assertEqual(metrics["order_count"], 3)  # includes reversal order
        self.assertIsNone(metrics["customer_count"])
        self.assertEqual(metrics["currency"], "CNY")
        self.assertEqual(calculate_metrics(data, "2026-09-01", "2026-09-01")["net_sales_minor"], 30)
        contribution = product_contribution(data, "2026-09-02", "2026-09-02", "2026-09-01", "2026-09-01", top_n=None)
        self.assertEqual(set(contribution["product_key"]), {"id:01", "id:02"})
        self.assertEqual(sum(contribution["delta_minor"]), -20)
        self.assertEqual(len(order_drilldown(data, "2026-09-01", "2026-09-02", "id:01")), 2)
        self.assertEqual(len(order_drilldown(data, "2026-09-01", "2026-09-02", "杯")), 0)
        with self.assertRaisesRegex(ValueError, "多个编号"):
            order_drilldown(data, "2026-09-01", "2026-09-02", "杯子")

    def test_invalid_rows_and_duplicates_are_auditable(self):
        raw = pd.DataFrame({
            "order_id": ["01", "01", "02", "03", "04", "05", "", "07", "08"],
            "product_id": ["sku"] * 9,
            "quantity": [1, 1, -1, "inf", 1, 1, 1, 1, "0.5"],
            "unit_price": ["0.10", "0.10", "0.10", 1, -1, "0.001", 1, 1, "0.01"],
            "order_time": ["2026-09-01"] * 7 + ["bad", "2026-09-01"],
        })
        mapping = {column: column for column in raw.columns}
        result = prepare_commerce_data(raw, mapping, "GBP")
        self.assertEqual(result["quality"]["duplicate_rows"], 1)
        self.assertEqual(result["quality"]["valid_rows"], 3)
        self.assertEqual(result["quality"]["excluded_rows"], 6)
        self.assertEqual(len(result["excluded"]), 6)
        self.assertEqual(calculate_metrics(result["data"], "2026-09-01", "2026-09-01")["net_sales_minor"], 10)

    def test_missing_product_and_empty_period(self):
        raw = pd.DataFrame({"order_id": ["01"], "quantity": [1], "unit_price": [1], "order_time": ["2026-09-01"]})
        result = prepare_commerce_data(raw, {column: column for column in raw}, "CNY")
        self.assertTrue(result["quality"]["missing_product"])
        with self.assertRaises(ValueError):
            product_contribution(result["data"], "2026-09-01", "2026-09-01", "2026-08-01", "2026-08-01")
        empty = calculate_metrics(result["data"], "2026-08-01", "2026-08-02")
        self.assertEqual(empty["net_sales_minor"], 0)
        self.assertIsNone(empty["average_order_value"])

    def test_unmapped_canonical_column_is_not_silently_reused(self):
        raw = pd.DataFrame({"order_id": ["old"], "真实订单": ["new"], "quantity": [1], "unit_price": [1], "order_time": ["2026-09-01"]})
        mapping = {column: column for column in ("quantity", "unit_price", "order_time")}
        self.assertIn("order_id", prepare_commerce_data(raw, mapping, "CNY")["quality"]["missing_required"])
        mapping["order_id"] = "真实订单"
        self.assertEqual(prepare_commerce_data(raw, mapping, "CNY")["data"].iloc[0]["order_id"], "new")

    def test_empty_input_and_out_of_range_dates(self):
        raw = pd.DataFrame(columns=["order_id", "quantity", "unit_price", "order_time"])
        result = prepare_commerce_data(raw, {column: column for column in raw}, "CNY")
        self.assertEqual(result["quality"]["valid_rows"], 0)
        self.assertEqual(calculate_metrics(result["data"], "2026-09-01", "2026-09-01")["net_sales_minor"], 0)
        raw = pd.DataFrame({"order_id": ["1", "2"], "quantity": [1, 1], "unit_price": [1, 1],
                            "order_time": ["2500-01-01", "2026-09-01T00:00:00+08:00"]})
        result = prepare_commerce_data(raw, {column: column for column in raw}, "CNY")
        self.assertEqual(result["quality"]["invalid_order_time"], 2)

    def test_langchain_tools_receive_mapped_data_and_exact_product_evidence(self):
        state = {}
        load_dataset(state, upload(self.csv))
        data = apply_dataset_mapping(state, state["commerce_mapping"], "CNY")["data"]
        tools = {tool.name: tool for tool in build_commerce_tools(data)}
        metrics = json.loads(tools["get_period_metrics"].invoke({"start": "2026-09-01", "end": "2026-09-02"}))
        self.assertEqual(metrics["net_sales_minor"], 40)
        evidence = json.loads(tools["drilldown_orders"].invoke({"start": "2026-09-01", "end": "2026-09-02", "product": "id:01"}))
        self.assertEqual(evidence["currency"], "CNY")
        self.assertEqual(evidence["row_count"], 2)
        self.assertEqual({row["order_id"] for row in evidence["rows"]}, {"001", "003"})

    def test_name_fallback_and_integer_cents_survive_absent_period_product(self):
        raw = pd.DataFrame({"order_id": ["1", "2", "3"], "quantity": [1, 1, 1],
                            "unit_price": ["90071992547409.93", "0.01", "0.02"],
                            "order_time": ["2026-09-01", "2026-09-02", "2026-09-02"],
                            "product_name": ["杯子", "碗", ""]})
        data = prepare_commerce_data(raw, {column: column for column in raw}, "GBP")["data"]
        products = product_contribution(data, "2026-09-02", "2026-09-02", "2026-09-01", "2026-09-01", top_n=None).set_index("product_key")
        self.assertEqual(products.loc["name:杯子", "previous_minor"], 9007199254740993)
        self.assertEqual(products.loc["name:碗", "delta_minor"], 1)
        self.assertEqual(products.loc["missing:", "delta_minor"], 2)
        self.assertEqual(sum(products["delta_minor"]), 3 - 9007199254740993)


if __name__ == "__main__":
    unittest.main()
