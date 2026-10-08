"""Offline teaching walkthrough: real business tools and LangChain, no model API."""

import io
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from langchain_core.messages import AIMessage
from commerce_agent import run_commerce_agent, serialise_payload
from commerce_session import load_dataset, apply_dataset_mapping
from commerce_metrics import calculate_metrics, compare_periods, product_contribution, order_drilldown
from commerce_diagnosis import run_diagnosis
from commerce_report import build_report_bundle
from rag_knowledge import default_knowledge_base
from fake_chat_model import ScriptedChatModel, tool_call


def show(title, value):
    print("\n" + title)
    print(serialise_payload(value))


def main():
    print("学习模式：不调用真实模型 API，不读取 API Key；只有模型响应被模拟。")
    print("字段映射、金额计算、规则检索、LangChain 执行器、工具和报告导出实际运行。")
    uploaded = io.BytesIO((
        "订单编号,商品编号,商品名称,数量,单价,日期\n"
        "001,01,杯子,3,0.10,2026-09-01\n"
        "002,02,杯子,1,0.20,2026-09-02\n"
        "003,01,杯子,-1,0.10,2026-09-02\n"
    ).encode("utf-8"))
    uploaded.name = "learning_orders.csv"
    state = {}
    load_dataset(state, uploaded)
    show("1. 自动字段映射：标准字段 -> 原始列", state["commerce_mapping"])
    data = apply_dataset_mapping(state, state["commerce_mapping"], "CNY")["data"]
    show("2. 有效标准数据（同名商品 01 / 02 保持独立）", data)
    show("3. 两天合计指标：净销售额应为 40 分", calculate_metrics(data, "2026-09-01", "2026-09-02"))
    current, previous = ("2026-09-02", "2026-09-02"), ("2026-09-01", "2026-09-01")
    show("4. 周期对比：本期 10 分，上期 30 分，变化 -20 分", compare_periods(data, *current, *previous))
    show("5. 全部商品贡献：id:01 变化 -40 分，id:02 变化 +20 分", product_contribution(data, *current, *previous, top_n=None))
    show("6. id:01 本期订单证据：003，数量 -1", order_drilldown(data, *current, product="id:01"))
    retrieval = default_knowledge_base().retrieve("净销售额 net_sales")
    show("7. 真实 TF-IDF 检索：查看命中的原文和规则来源", retrieval)

    model = ScriptedChatModel(responses=[
        tool_call("compare_period_metrics", {}, "learn-1"),
        AIMessage(content="本期净销售额 0.10 CNY，上期 0.30 CNY，变化 -0.20 CNY。"),
        tool_call("rank_product_contribution", {}, "learn-2"),
        AIMessage(content="id:01 变化 -0.40 CNY，id:02 变化 +0.20 CNY；变化绝对值第一名为 id:01。"),
        tool_call("drilldown_orders", {}, "learn-3"),
        AIMessage(content="id:01 本期证据为订单 003，数量 -1，冲销金额 0.10 CNY。"),
    ])
    history, context = [], None
    for question in ("比较本期与上期经营情况", "继续按商品分析", "查看该商品明细"):
        result = run_commerce_agent(model, data, question, history, current, context,
                                    comparison_period=previous, quality=state["commerce_quality"])
        if result["error"]:
            raise RuntimeError(result["error"])
        show("8. 真实 LangChain 执行的一轮（模型响应模拟）", {
            "question": question, "answer": result["answer"],
            "context": result["context"], "actual_tool_calls": result["tool_calls"],
        })
        history.extend([{"role": "user", "content": question},
                        {"role": "assistant", "content": result["answer"], "result": result}])
        context = result["context"]

    diagnosis = run_diagnosis(data, current, previous, state["commerce_quality"], dataset_name="三条教学订单")
    bundle = build_report_bundle(diagnosis)
    output = ROOT / "outputs" / "learning_demo"
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.zip").write_bytes(bundle.zip_bytes)
    (output / "report.md").write_text(bundle.markdown, encoding="utf-8")
    assert diagnosis.delta_minor == -20
    assert sum(diagnosis.products["delta_minor"]) == diagnosis.delta_minor
    with zipfile.ZipFile(io.BytesIO(bundle.zip_bytes)) as archive:
        show("9. 报告包实际包含的文件", archive.namelist())
    print("\n学习报告已保存：" + str(output))
    print("请对照 docs/project-walkthrough.md 阅读源码。模拟模型输出不代表真实 DeepSeek 验收。")


if __name__ == "__main__":
    main()
