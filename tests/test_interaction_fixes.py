"""Regressions for rerun work, session invalidation and configured model identity."""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import commerce_data
import commerce_metrics
from commerce_session import load_dataset, apply_dataset_mapping, prepared_preview
from commerce_view_cache import cached_view
from commerce_metrics import calculate_metrics, compare_periods, metrics_snapshot
from commerce_diagnosis import run_diagnosis
from commerce_agent import run_commerce_agent
from model_identity import configured_identity_answer, public_model_identity, identity_question
from advanced_tools import answer_nlq_text
from streamlit.testing.v1 import AppTest
from langchain_core.messages import AIMessage, ToolMessage
from fake_chat_model import ScriptedChatModel, tool_call
from test_commerce_lifecycle import upload


class InteractionFixTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        load_dataset(self.state, upload(
            "订单编号,商品编号,商品名称,数量,单价,日期,备选单价\n"
            "001,01,杯子,3,0.10,2026-09-01,1.00\n"
            "002,02,杯子,1,0.20,2026-09-02,2.00\n"
            "003,01,杯子,-1,0.10,2026-09-02,1.00\n"))
        self.data = apply_dataset_mapping(self.state, self.state["commerce_mapping"], "CNY")["data"]
        self.state["commerce_currency_choice"] = "CNY"
        self.identity = public_model_identity("DeepSeek", "deepseek-chat")
        self.period = ("2026-09-01", "2026-09-02")

    def test_preview_reuses_validation_and_remapping_recalculates(self):
        with patch("commerce_data.parse_commerce_rows", wraps=commerce_data.parse_commerce_rows) as parse:
            preview = prepared_preview(self.state, self.state["commerce_mapping"], "CNY")
            self.assertIs(preview["data"], self.data)
            self.assertEqual(parse.call_count, 0)
            mapping = {**self.state["commerce_mapping"], "unit_price": "备选单价"}
            changed = prepared_preview(self.state, mapping, "GBP")
            apply_dataset_mapping(self.state, mapping, "GBP")
            self.assertEqual(parse.call_count, 1)
            self.assertIs(changed["data"], self.state["commerce_standard_df"])
            self.assertEqual(calculate_metrics(changed["data"], *self.period)["net_sales_minor"], 400)

    def test_view_cache_is_bounded_and_invalidates_all_dependencies(self):
        factory = Mock(side_effect=lambda: object())
        first = cached_view(self.state, "overview", self.period, factory)
        self.assertIs(cached_view(self.state, "overview", self.period, factory), first)
        cached_view(self.state, "overview", ("2026-09-02", "2026-09-02"), factory)
        self.state["commerce_currency"] = "GBP"
        cached_view(self.state, "overview", self.period, factory)
        self.state["commerce_applied_mapping"]["unit_price"] = "备选单价"
        cached_view(self.state, "overview", self.period, factory)
        self.state["commerce_file_fingerprint"] = "replacement-file"
        cached_view(self.state, "overview", self.period, factory)
        self.assertEqual(factory.call_count, 5)
        self.assertEqual(len(self.state["commerce_view_cache"]), 1)
        load_dataset(self.state, upload("订单编号,数量,单价,日期\n004,1,9.00,2026-09-03\n"))
        self.assertNotIn("commerce_view_cache", self.state)
        self.assertNotIn("commerce_preview", self.state)

    def test_comparison_and_diagnosis_parse_once_without_stale_future_calls(self):
        with patch("commerce_metrics.parse_commerce_rows", wraps=commerce_metrics.parse_commerce_rows) as parse:
            compare_periods(self.data, *self.period, *self.period)
            self.assertEqual(parse.call_count, 1)
            run_diagnosis(self.data, self.period, self.period, self.state["commerce_quality"])
            self.assertEqual(parse.call_count, 2)
            self.data.loc[self.data.index[0], "unit_price"] = "1.00"
            self.assertEqual(calculate_metrics(self.data, *self.period)["net_sales_minor"], 310)
            self.assertEqual(parse.call_count, 3)

    def test_nested_snapshot_restores_other_dataset_and_resets_after_error(self):
        other = self.data.copy(deep=True)
        other["unit_price"] = "1.00"
        with metrics_snapshot(self.data):
            self.assertEqual(calculate_metrics(other, *self.period)["net_sales_minor"], 300)
            self.assertEqual(calculate_metrics(self.data, *self.period)["net_sales_minor"], 40)
        with self.assertRaises(RuntimeError):
            with metrics_snapshot(self.data):
                raise RuntimeError("test cleanup")
        self.data["unit_price"] = "2.00"
        self.assertEqual(calculate_metrics(self.data, *self.period)["net_sales_minor"], 600)

    def test_identity_uses_configuration_without_llm_and_does_not_hijack_business(self):
        for question in ["你是什么模型？", "请问你是Claude吗？", "What model are you?"]:
            self.assertTrue(identity_question(question))
            self.assertIn("deepseek-chat", configured_identity_answer(question, self.identity))
            self.assertIn("DeepSeek", answer_nlq_text(None, self.data, question, model_identity=self.identity))
        for question in ["用什么模型预测销售额", "你是什么模型，分析销售额", "Claude商品销量是多少"]:
            self.assertFalse(identity_question(question))
        result = run_commerce_agent(None, self.data, "你是什么模型", period=self.period, model_identity=self.identity)
        self.assertIsNone(result["error"])
        self.assertEqual(result["tool_calls"], [])
        self.assertIn("deepseek-chat", result["answer"])

    def test_advanced_real_pandas_agent_executes_and_receives_identity(self):
        model = ScriptedChatModel(responses=[
            tool_call("python_repl_ast", {"query": "df['quantity'].sum()"}),
            AIMessage(content="净数量为3。"),
        ])
        answer = answer_nlq_text(model, self.data, "计算净数量", model_identity=self.identity)
        self.assertEqual(answer, "净数量为3。")
        self.assertIn("deepseek-chat", str(model.calls[0][0].content))
        self.assertTrue(any(isinstance(message, ToolMessage) and "3" in str(message.content)
                            for message in model.calls[1]))
        self.assertEqual(len(model.calls), 2)

    def test_form_input_and_submission_reuse_data_and_switch_clears_old_result(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30)
        for key, value in self.state.items():
            app.session_state[key] = value
        app.run()
        self.assertEqual(len(app.exception), 0)
        with patch("commerce_data.parse_commerce_rows", side_effect=AssertionError("unexpected validation")), \
             patch("commerce_metrics.parse_commerce_rows", side_effect=AssertionError("unexpected calculation")), \
             patch("commerce_ui.create_chat_model") as factory:
            app.toggle(key="commerce_advanced_enabled").set_value(True).run()
            self.assertFalse(app.button(key="execute_advanced").disabled)
            self.assertEqual(app.text_area(key="commerce_advanced_request").proto.form_id, "commerce_advanced_form")
            app.button(key="execute_advanced").click().run()
            self.assertTrue(any("请先输入需求" in item.value for item in app.warning))
            app.text_area(key="commerce_advanced_request").set_value("你是什么模型").run()
            app.button(key="execute_advanced").click().run()
            self.assertIn("deepseek-chat", app.session_state["commerce_advanced_result"]["answer"])
            app.selectbox(key="model_provider").select("Anthropic Claude").run()
            self.assertNotIn("commerce_advanced_result", app.session_state)
            app.button(key="execute_advanced").click().run()
            self.assertIn("claude-3-5-sonnet-latest", app.session_state["commerce_advanced_result"]["answer"])
            app.selectbox(key="model_provider").select("DeepSeek").run()
            app.chat_input(key="commerce_chat_input").set_value("你是什么模型").run()
            self.assertIn("deepseek-chat", app.session_state["commerce_messages"][-1]["content"])
            self.assertEqual(factory.call_count, 0)
            self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()
