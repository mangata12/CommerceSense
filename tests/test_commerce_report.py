import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import pandas as pd
from langchain_core.messages import AIMessage

from commerce_data import prepare_commerce_data
from commerce_diagnosis import run_diagnosis, add_ai_interpretation
from commerce_metrics import calculate_metrics
from commerce_report import build_report_bundle, comparison_table
from rag_knowledge import MetricKnowledgeBase
from fake_chat_model import ScriptedChatModel


def prepared_rows(rows, currency="CNY"):
    raw = pd.DataFrame(rows)
    return prepare_commerce_data(raw, {column: column for column in raw}, currency)


class CommerceReportTests(unittest.TestCase):
    def setUp(self):
        rows = []
        for index in range(12):
            for day, quantity in (("2026-09-01", 1), ("2026-09-08", index + 1)):
                rows.append({"order_id": f"{index:03d}-{day}", "product_id": f"{index:03d}",
                             "product_name": "同名商品", "quantity": quantity, "unit_price": "0.10", "order_time": day})
        self.prepared = prepared_rows(rows)
        self.current, self.previous = ("2026-09-08", "2026-09-09"), ("2026-09-01", "2026-09-02")
        self.result = run_diagnosis(self.prepared["data"], self.current, self.previous, self.prepared["quality"])

    def test_full_product_changes_and_daily_trend_reconcile(self):
        self.assertEqual(len(self.result.products), 12)
        self.assertEqual(sum(self.result.products["delta_minor"]), self.result.delta_minor)
        self.assertEqual(self.result.delta_minor, 660)
        self.assertEqual(self.result.outside_top_minor, 10)
        for period, metrics in (("current", self.result.current), ("previous", self.result.previous)):
            rows = self.result.trend.loc[self.result.trend["period"].eq(period)]
            self.assertEqual(sum(rows["net_sales_minor"]), metrics["net_sales_minor"])
            self.assertEqual(len(rows), 2)
        self.assertEqual(len(self.result.evidence), 6)
        self.assertEqual(set(self.result.evidence["product_key"]), {"id:009", "id:010", "id:011"})

    def test_zip_csv_and_markdown_share_amounts_periods_and_sources(self):
        bundle = build_report_bundle(self.result)
        with zipfile.ZipFile(io.BytesIO(bundle.zip_bytes)) as archive:
            self.assertEqual(len(archive.namelist()), 8)
            self.assertEqual(archive.read("metrics_comparison.csv"), bundle.metrics_csv)
            self.assertEqual(archive.read("product_contribution.csv"), bundle.products_csv)
            self.assertEqual(archive.read("order_evidence.csv"), bundle.evidence_csv)
            self.assertEqual(archive.read("report.md").decode("utf-8"), bundle.markdown)
            for path in bundle.charts:
                self.assertTrue(archive.read(path).startswith(b"\x89PNG\r\n\x1a\n"))
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["total_delta_minor"], 660)
            self.assertEqual(manifest["currency"], "CNY")
        metrics = pd.read_csv(io.BytesIO(bundle.metrics_csv), dtype=str, keep_default_na=False).set_index("metric")
        self.assertEqual(metrics.loc["net_sales", "current"], "7.80")
        self.assertEqual(metrics.loc["net_sales", "previous"], "1.20")
        self.assertEqual(metrics.loc["net_sales", "delta_minor"], "660")
        self.assertEqual(metrics.loc["net_sales", "current_start"], self.current[0])
        products = pd.read_csv(io.BytesIO(bundle.products_csv), dtype=str)
        self.assertEqual(len(products), 12)
        self.assertEqual(sum(map(int, products["delta_minor"])), 660)
        self.assertIn("排名之外还有 2 个商品", bundle.markdown)
        self.assertIn("6.60 CNY", bundle.markdown)
        for source in self.result.rule_sources:
            original = (Path(__file__).parents[1] / source["source"]).read_text(encoding="utf-8")
            self.assertIn(source["text"], original)
            self.assertIn(source["rule_id"], bundle.markdown)

    def test_order_evidence_export_is_not_capped_at_agent_limit(self):
        rows = [{"order_id": f"{index:04d}", "product_id": "001", "quantity": 1,
                 "unit_price": "0.01", "order_time": "2026-09-08"} for index in range(151)]
        prepared = prepared_rows(rows, "GBP")
        result = run_diagnosis(prepared["data"], self.current, self.previous, prepared["quality"])
        bundle = build_report_bundle(result)
        evidence = pd.read_csv(io.BytesIO(bundle.evidence_csv), dtype=str)
        self.assertEqual(len(evidence), 151)
        self.assertEqual(evidence.iloc[0]["order_id"], "0000")
        self.assertEqual(evidence.iloc[0]["product_id"], "001")
        self.assertEqual(set(evidence["currency"]), {"GBP"})
        self.assertEqual(set(evidence["period_start"]), {self.current[0]})
        self.assertEqual(result.tool_payload()["total_evidence_rows"], 151)
        self.assertEqual(len(result.tool_payload()["evidence"]), 100)

    def test_empty_period_zero_base_missing_customer_and_product_are_explicit(self):
        prepared = prepared_rows([{"order_id": "01", "quantity": 1, "unit_price": "1.00", "order_time": "2026-08-01"}])
        result = run_diagnosis(prepared["data"], self.current, self.previous, prepared["quality"])
        bundle = build_report_bundle(result)
        self.assertFalse(result.product_available)
        self.assertIn("当前周期没有有效记录", bundle.markdown)
        self.assertIn("基期净销售额为零", bundle.markdown)
        self.assertIn("客户数无法统计", bundle.markdown)
        self.assertIn("缺少商品编号与商品名称", bundle.markdown)
        metrics = comparison_table(result).set_index("metric")
        self.assertEqual(metrics.loc["net_sales", "change_percent"], "")
        self.assertEqual(metrics.loc["customer_count", "current"], "")
        self.assertEqual(len(bundle.charts), 2)  # placeholder explicitly shows unavailable products

    def test_zero_total_change_keeps_offsetting_products_without_percentages(self):
        prepared = prepared_rows([
            {"order_id": "1", "product_id": "A", "quantity": 1, "unit_price": 1, "order_time": "2026-09-01"},
            {"order_id": "2", "product_id": "B", "quantity": 1, "unit_price": 1, "order_time": "2026-09-01"},
            {"order_id": "3", "product_id": "A", "quantity": 2, "unit_price": 1, "order_time": "2026-09-08"},
        ])
        result = run_diagnosis(prepared["data"], self.current, self.previous, prepared["quality"])
        self.assertEqual(result.delta_minor, 0)
        self.assertEqual(set(result.products["delta_minor"]), {-100, 100})
        self.assertTrue(result.products["contribution_percent"].isna().all())
        self.assertIn("商品贡献比例不适用", build_report_bundle(result).markdown)

    def test_optional_ai_does_not_change_computed_files(self):
        base = build_report_bundle(self.result)
        model = ScriptedChatModel(responses=[AIMessage(content="经营变化已列明；因果关系需要额外业务数据验证。")])
        enriched = add_ai_interpretation(self.result, model)
        bundle = build_report_bundle(enriched)
        self.assertEqual(base.metrics_csv, bundle.metrics_csv)
        self.assertEqual(base.products_csv, bundle.products_csv)
        self.assertEqual(base.evidence_csv, bundle.evidence_csv)
        self.assertEqual(base.charts, bundle.charts)
        self.assertIn("AI 解读（模型生成", bundle.markdown)
        self.assertEqual(self.result.ai_interpretation, "")

    def test_rule_document_cannot_change_calculation_functions(self):
        original = (Path(__file__).parents[1] / "knowledge/commerce_metrics.md").read_text(encoding="utf-8")
        edited = original.replace("净销售额 net_sales = 成交销售额 gross_sales - 冲销金额 reversal_amount", "净销售额 net_sales = 999999")
        edited += "\n## CS-099 | 新增公式\n指标：forecast\n版本：1.0\n预测净销售额为999999。\n"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "commerce_metrics.md").write_text(edited, encoding="utf-8")
            result = run_diagnosis(self.prepared["data"], self.current, self.previous, self.prepared["quality"], knowledge_base=MetricKnowledgeBase(directory))
        self.assertEqual(result.current["net_sales_minor"], self.result.current["net_sales_minor"])
        self.assertEqual(len(result.rule_sources), 13)
        self.assertFalse(any(rule["rule_id"] == "CS-099" for rule in result.rule_sources))

    def test_snapshot_does_not_re_read_mutated_input(self):
        before = build_report_bundle(self.result)
        self.prepared["data"].loc[0, "unit_price"] = 999
        after = build_report_bundle(self.result)
        self.assertEqual(before.metrics_csv, after.metrics_csv)
        self.assertEqual(before.evidence_csv, after.evidence_csv)

    def test_fractional_quantity_and_integer_money_preserve_valid_precision(self):
        prepared = prepared_rows([{"order_id": "01", "product_id": "01", "quantity": "0.125", "unit_price": "8.00", "order_time": "2026-09-08"}])
        metrics = calculate_metrics(prepared["data"], *self.current)
        self.assertEqual(metrics["units_sold"], 0.125)
        self.assertEqual(metrics["net_sales_minor"], 100)
        result = run_diagnosis(prepared["data"], self.current, self.previous, prepared["quality"])
        table = comparison_table(result).set_index("metric")
        self.assertEqual(table.loc["units_sold", "delta"], "0.125")


if __name__ == "__main__":
    unittest.main()
