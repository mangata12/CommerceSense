import unittest
import json
from pathlib import Path

from rag_knowledge import MetricKnowledgeBase


class MetricKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.knowledge_base = MetricKnowledgeBase(Path(__file__).parents[1] / "knowledge")

    def test_retrieves_net_sales_rule_with_source(self):
        result = self.knowledge_base.retrieve("净销售额怎么算，冲销金额怎么处理")
        self.assertTrue(result["sources"])
        self.assertIn("净销售额", result["context"])
        self.assertTrue(result["sources"][0]["source"].endswith("commerce_metrics.md"))

    def test_empty_query_does_not_return_unrelated_rules(self):
        result = self.knowledge_base.retrieve("")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["context"], "")

    def test_fixed_calibration_and_independent_validation_samples(self):
        samples = json.loads((Path(__file__).parents[1] / "tests/fixtures/rule_queries.json").read_text(encoding="utf-8"))
        for group, cases in samples.items():
            for case in cases:
                with self.subTest(group=group, query=case["query"]):
                    result = self.knowledge_base.retrieve(case["query"])
                    if case["rule_id"]:
                        self.assertIn(case["rule_id"], [hit["rule_id"] for hit in result["hits"]])
                    else:
                        self.assertEqual(result["status"], "not_found")
                        self.assertEqual(result["message"], "未找到规则")
                        self.assertEqual(result["sources"], [])

    def test_hits_include_original_versioned_rule_text_and_real_line(self):
        result = self.knowledge_base.retrieve("客单价的分母包含冲销订单吗")
        self.assertTrue(result["hits"])
        for hit in result["hits"]:
            source = (Path(__file__).parents[1] / hit["source"]).read_text(encoding="utf-8")
            self.assertIn(hit["text"], source)
            self.assertTrue(source.splitlines()[hit["line"] - 1].startswith("## " + hit["rule_id"]))
            self.assertEqual(hit["version"], "1.0")
            self.assertGreaterEqual(hit["score"], result["threshold"])


if __name__ == "__main__":
    unittest.main()
