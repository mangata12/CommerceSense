"""Opt-in real DeepSeek tool-calling check using public simulated data only."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from commerce_agent import run_commerce_agent
from commerce_session import load_dataset, apply_dataset_mapping
from model_config import resolve_model_settings, create_chat_model, safe_error


def main():
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        print(json.dumps({"status": "skipped", "reason": "未配置 DEEPSEEK_API_KEY；真实 API 未验收。"}, ensure_ascii=False))
        return 0
    settings = resolve_model_settings("DeepSeek", "deepseek-chat")
    try:
        state = {}
        with (ROOT / "data/examples/commerce_orders_demo.csv").open("rb") as uploaded:
            load_dataset(state, uploaded)
        data = apply_dataset_mapping(state, state["commerce_mapping"], "CNY")["data"]
        result = run_commerce_agent(
            create_chat_model(settings), data,
            "请调用 get_period_metrics 计算当前周期净销售额，再调用 retrieve_metric_rules 检索净销售额定义，给出实际规则来源。",
            period=("2026-09-08", "2026-09-09"), comparison_period=("2026-09-01", "2026-09-02"),
            quality=state["commerce_quality"], max_iterations=4, secrets=(settings.api_key,))
        valid_metrics = any(record["tool"] == "get_period_metrics" and record["status"] == "success"
                            and record["result"].get("net_sales_minor") == 4490
                            for record in result["tool_calls"])
        valid_sources = any(source.get("rule_id") == "CS-005" for source in result["rule_sources"])
        passed = not result["error"] and valid_metrics and valid_sources and bool(result["answer"].strip())
        print(json.dumps({"status": "passed" if passed else "failed", "model": settings.model_name,
                          "actual_tool_names": [record["tool"] for record in result["tool_calls"]],
                          "metrics_match_4490_minor": valid_metrics, "net_sales_rule_cited": valid_sources,
                          "error": result["error"], "scope": "单次公开模拟数据工具问答；不代表多轮对话质量。"}, ensure_ascii=False, indent=2))
        return 0 if passed else 1
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": safe_error(exc, (settings.api_key,))}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
