"""Exercise real Streamlit reruns without a server or a model API call."""

from pathlib import Path
import os
import io
import pandas as pd
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from commerce_session import load_dataset
from test_commerce_lifecycle import upload
from fake_chat_model import ScriptedChatModel, tool_call
from langchain_core.messages import AIMessage


class CommerceUITests(unittest.TestCase):
    def sample_app(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30)
        app.run()
        app.button(key="load_commerce_sample").click().run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_chinese_pages_sample_and_closed_advanced_tools_need_no_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            app = self.sample_app()
        self.assertEqual([tab.label for tab in app.tabs], ["数据导入", "经营概览", "分析助手", "经营报告"])
        self.assertEqual(len(app.error), 0)
        self.assertTrue(any(metric.label == "净销售额" for metric in app.metric))
        self.assertEqual(app.selectbox(key="commerce_currency_choice").value, "CNY")
        self.assertFalse(app.toggle(key="commerce_advanced_enabled").value)
        self.assertTrue(app.date_input(key="commerce_current_period").proto.is_range)
        self.assertTrue(app.date_input(key="commerce_previous_period").proto.is_range)
        self.assertFalse(any(area.key == "commerce_advanced_request" for area in app.text_area))
        self.assertTrue(any(button.key == "generate_commerce_report" for button in app.button))
        self.assertTrue(any(expander.label == "数据质量详情" for expander in app.expander))

    def test_chat_failure_retry_and_clear_preserve_page_period(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            app = self.sample_app()
            app.date_input(key="commerce_current_period").set_value(("2026-09-01", "2026-09-02")).run()
            app.chat_input(key="commerce_chat_input").set_value("分析本期经营情况").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state["commerce_retry_question"], "分析本期经营情况")
            self.assertTrue(any("调用模型前" in item.value for item in app.error))
            model = ScriptedChatModel(responses=[
                tool_call("get_period_metrics", {"start": "2026-09-01", "end": "2026-09-02"}),
                TimeoutError("模拟模型超时"),
                tool_call("get_period_metrics", {"start": "2026-09-01", "end": "2026-09-02"}),
                AIMessage(content="经营指标已计算。"),
            ])
            with patch("commerce_ui.create_chat_model", return_value=model) as factory:
                app.text_input(key="model_key_DeepSeek").set_value("session-only-key").run()
                self.assertEqual(factory.call_count, 0)
                app.button(key="retry_commerce_chat").click().run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(app.session_state["commerce_tool_results"][0]["status"], "success")
                self.assertTrue(any("模拟模型超时" in item.value for item in app.error))
                app.button(key="retry_commerce_chat").click().run()
                self.assertEqual(len(app.exception), 0)
                self.assertIsNone(app.session_state["commerce_retry_question"])
                self.assertEqual(app.session_state["commerce_messages"][-1]["content"], "经营指标已计算。")
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "")
            app.button(key="clear_commerce_chat").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertNotIn("commerce_messages", app.session_state)
            self.assertNotIn("commerce_chat_context", app.session_state)
            self.assertEqual(str(app.date_input(key="commerce_current_period").value[0]), "2026-09-01")

    def test_report_generation_downloads_ai_failure_and_changed_period_invalidation(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            app = self.sample_app()
            app.date_input(key="commerce_current_period").set_value(("2026-09-08", "2026-09-09")).run()
            app.date_input(key="commerce_previous_period").set_value(("2026-09-01", "2026-09-02")).run()
            app.button(key="generate_commerce_report").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.error), 0)
            saved = app.session_state["commerce_report"]
            self.assertEqual(saved["result"].delta_minor, -4380)
            report_table = [table.value for table in app.dataframe if list(table.value.columns) == ["指标", "当前周期", "对比周期", "变化量", "变化比例（%）"]][-1].set_index("指标")
            exported = pd.read_csv(io.BytesIO(saved["bundle"].metrics_csv), dtype=str).set_index("metric")
            self.assertEqual(report_table.loc["净销售额", "变化量"], exported.loc["net_sales", "delta"])
            self.assertEqual(report_table.loc["净销售额", "当前周期"], exported.loc["net_sales", "current"])
            labels = [element.proto.label for element in app.get("download_button")]
            self.assertIn("下载完整报告包（ZIP，含图表 PNG）", labels)
            self.assertEqual(len(labels), 5)
            original_zip = saved["bundle"].zip_bytes
            app.button(key="add_report_ai").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(app.session_state["commerce_report"]["result"].ai_error)
            self.assertEqual(app.session_state["commerce_report"]["bundle"].zip_bytes, original_zip)
            app.date_input(key="commerce_previous_period").set_value(("2026-09-03", "2026-09-04")).run()
            self.assertEqual(len(app.exception), 0)
            self.assertNotIn("commerce_report", app.session_state)
            self.assertEqual(len(app.get("download_button")), 0)

    def test_mapping_rerun_and_date_interaction_share_standard_data(self):
        state = {}
        load_dataset(state, upload(
            "订单编号,商品编号,商品名称,数量,单价,日期,备选单价\n"
            "001,01,杯子,3,0.10,2026-09-01,1.00\n"
            "002,02,杯子,1,0.20,2026-09-02,2.00\n"
            "003,01,杯子,-1,0.10,2026-09-02,1.00\n"
        ))
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30)
        for key, value in state.items():
            app.session_state[key] = value
        app.run()
        self.assertEqual(len(app.exception), 0)
        app.selectbox(key="commerce_currency_choice").select("CNY").run()
        next(button for button in app.button if button.label == "应用电商字段映射").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["commerce_standard_df"].iloc[0]["order_id"], "001")
        metrics = next(table.value for table in app.dataframe if list(table.value.columns) == ["指标", "结果"])
        self.assertEqual(metrics.set_index("指标").loc["净销售额", "结果"], "0.4")

        # The no-key page still exposes deterministic metrics. Date interaction
        # reruns the whole app without replacing the standard frame with raw CSV.
        app.date_input(key="commerce_current_period").set_value(("2026-09-02", "2026-09-02")).run()
        self.assertEqual(len(app.exception), 0)
        metrics = next(table.value for table in app.dataframe if list(table.value.columns) == ["指标", "结果"])
        self.assertEqual(metrics.set_index("指标").loc["净销售额", "结果"], "0.1")

        app.session_state["commerce_agent_last_answer"] = "旧答案"
        app.session_state["commerce_report"] = "旧报告"
        app.selectbox(key="commerce_mapping_unit_price").select("备选单价").run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("请先应用当前字段映射" in item.value for item in app.info))
        next(button for button in app.button if button.label == "应用电商字段映射").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(str(app.session_state["commerce_standard_df"].iloc[0]["unit_price"]), "1.00")
        self.assertNotIn("commerce_agent_last_answer", app.session_state)
        self.assertNotIn("commerce_report", app.session_state)


if __name__ == "__main__":
    unittest.main()
