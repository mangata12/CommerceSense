import unittest
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


if __name__ == "__main__":
    unittest.main()
