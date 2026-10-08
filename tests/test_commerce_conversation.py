import unittest
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from commerce_agent import run_commerce_agent
from commerce_conversation import resolve_analysis_context
from commerce_session import load_dataset, apply_dataset_mapping
from test_commerce_lifecycle import upload
from fake_chat_model import ScriptedChatModel, tool_call


class CommerceConversationTests(unittest.TestCase):
    def setUp(self):
        state = {}
        load_dataset(state, upload("订单编号,商品编号,商品名称,数量,单价,日期\n"
                                   "001,01,杯子,3,0.10,2026-09-01\n"
                                   "002,02,杯子,1,0.20,2026-09-02\n"
                                   "003,01,杯子,-1,0.10,2026-09-02\n"))
        self.data = apply_dataset_mapping(state, state["commerce_mapping"], "CNY")["data"]
        self.period = ("2026-09-01", "2026-09-02")

    def test_three_turns_preserve_history_product_and_update_explicit_date(self):
        model = ScriptedChatModel(responses=[
            tool_call("get_period_metrics", {}),
            AIMessage(content="净销售额 0.40 CNY。"),
            tool_call("rank_product_contribution", {}),
            AIMessage(content="排名第一为商品 id:01，净销售额 0.20 CNY。"),
            tool_call("drilldown_orders", {}),
            AIMessage(content="商品 id:01 在 9 月 2 日有一条冲销明细。"),
        ])
        model.responses[0].content = "INTERNAL_REASONING_MUST_NOT_BE_EXPORTED"
        history, context = [], None
        questions = ["分析本期经营情况", "继续按商品分析", "改为2026-09-02，查看该商品明细"]
        results = []
        for question in questions:
            result = run_commerce_agent(model, self.data, question, history, self.period, context)
            self.assertIsNone(result["error"])
            history.extend([{"role": "user", "content": question},
                            {"role": "assistant", "content": result["answer"], "result": result}])
            context = result["context"]
            results.append(result)
        self.assertEqual(results[0]["tool_calls"][0]["result"]["net_sales_minor"], 40)
        self.assertEqual(results[1]["context"]["product_key"], "id:01")
        self.assertEqual(results[2]["context"]["current_start"], "2026-09-02")
        self.assertEqual(results[2]["tool_calls"][0]["result"]["rows"][0]["order_id"], "003")
        self.assertEqual(results[2]["tool_calls"][0]["result"]["row_count"], 1)
        self.assertEqual(results[2]["tool_calls"][0]["input"], {"start": "2026-09-02", "end": "2026-09-02", "product": "id:01"})
        followup_messages = model.calls[4]
        self.assertTrue(any(isinstance(message, HumanMessage) and message.content == questions[0] for message in followup_messages))
        self.assertTrue(any(isinstance(message, AIMessage) and "实际工具执行记录" in message.content and "id:01" in message.content for message in followup_messages))
        self.assertTrue(any(isinstance(message, ToolMessage) for message in model.calls[5]))
        self.assertNotIn("intermediate_steps", results[2])
        self.assertNotIn("INTERNAL_REASONING_MUST_NOT_BE_EXPORTED", json.dumps(results, ensure_ascii=False))

    def test_context_precedence_and_ui_period_changes(self):
        first = resolve_analysis_context("比较2026年9月2日到2026年9月3日与2026年8月2日到2026年8月3日，商品id:01", self.period)
        self.assertEqual(first["current_start"], "2026-09-02")
        self.assertEqual(first["previous_start"], "2026-08-02")
        followup = resolve_analysis_context("查看该商品明细", self.period, first)
        self.assertEqual(followup["current_end"], "2026-09-03")
        self.assertEqual(followup["product_key"], "id:01")
        changed = resolve_analysis_context("再看该商品", ("2026-09-04", "2026-09-05"), followup)
        self.assertEqual(changed["current_start"], "2026-09-04")
        self.assertEqual(changed["product_key"], "id:01")
        all_products = resolve_analysis_context("查看全部商品", self.period, first)
        self.assertNotIn("product_key", all_products)

    def test_explicit_question_date_precedes_conflicting_model_arguments(self):
        model = ScriptedChatModel(responses=[
            tool_call("get_period_metrics", {"start": "2026-09-01", "end": "2026-09-01"}),
            AIMessage(content="已计算指定日期。"),
        ])
        result = run_commerce_agent(model, self.data, "分析2026-09-02", period=self.period)
        self.assertIsNone(result["error"])
        self.assertEqual(result["tool_calls"][0]["input"], {"start": "2026-09-02", "end": "2026-09-02"})
        self.assertEqual(result["tool_calls"][0]["result"]["net_sales_minor"], 10)

    def test_explicit_clear_product_precedes_stale_model_filter(self):
        previous = resolve_analysis_context("商品 id:01", self.period)
        model = ScriptedChatModel(responses=[tool_call("drilldown_orders", {"product": "id:01"}),
                                             AIMessage(content="已展示全部商品明细。")])
        result = run_commerce_agent(model, self.data, "查看全部商品明细", period=self.period, context=previous)
        self.assertIsNone(result["error"])
        self.assertEqual(result["tool_calls"][0]["input"]["product"], "")
        self.assertEqual(result["tool_calls"][0]["result"]["row_count"], 3)
        self.assertNotIn("product_key", result["context"])

    def test_model_timeout_preserves_completed_tool_results_and_redacts_key(self):
        model = ScriptedChatModel(responses=[
            tool_call("get_period_metrics", {"start": "2026-09-01", "end": "2026-09-02"}),
            TimeoutError("timeout; Bearer test-secret-key"),
        ])
        result = run_commerce_agent(model, self.data, "分析经营情况", period=self.period, secrets=("test-secret-key",))
        self.assertIn("timeout", result["error"])
        self.assertNotIn("test-secret-key", result["error"])
        self.assertEqual(result["tool_calls"][0]["status"], "success")
        self.assertEqual(result["tool_calls"][0]["result"]["net_sales_minor"], 40)

    def test_tool_error_is_explicit_and_results_are_retained(self):
        model = ScriptedChatModel(responses=[
            tool_call("get_period_metrics", {"start": "bad-date", "end": "2026-09-02"}),
            AIMessage(content="日期无效，请检查。"),
        ])
        result = run_commerce_agent(model, self.data, "分析经营情况", period=self.period)
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["tool_calls"][0]["status"], "error")
        self.assertIn("error", result["tool_calls"][0]["result"])

    def test_iteration_limit_and_real_rule_sources(self):
        model = ScriptedChatModel(responses=[tool_call("retrieve_metric_rules", {"query": "净销售额 冲销"})])
        result = run_commerce_agent(model, self.data, "净销售额怎么算", period=self.period, max_iterations=1)
        self.assertIn("限制", result["error"])
        self.assertTrue(result["rule_sources"])
        self.assertTrue(all(source["source"] == "knowledge/commerce_metrics.md" for source in result["rule_sources"]))
        self.assertIn("净销售额", result["tool_calls"][0]["result"]["context"])
        self.assertEqual(len(model.calls), 1)


if __name__ == "__main__":
    unittest.main()
