"""Explicit period/product context shared by the chat UI and LangChain prompt."""

from datetime import timedelta
import re

import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage


DATE_PATTERN = r"(?<!\d)(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?(?!\d)"


def resolve_analysis_context(question, period, previous=None, comparison_period=None):
    if not period or len(period) != 2:
        raise ValueError("请先在经营概览选择完整的起止日期")
    selected = [str(pd.Timestamp(value).date()) for value in period]
    if selected[0] > selected[1]:
        raise ValueError("结束日期不能早于开始日期")
    previous = previous or {}
    dates = [str(pd.Timestamp(year=int(y), month=int(m), day=int(d)).date())
             for y, m, d in re.findall(DATE_PATTERN, question)]
    context = dict(previous)
    selected_comparison = [str(pd.Timestamp(value).date()) for value in comparison_period] if comparison_period and len(comparison_period) == 2 else None
    if previous.get("selected_period") != selected:
        for key in ("current_start", "current_end", "previous_start", "previous_end"):
            context.pop(key, None)
    if selected_comparison != previous.get("selected_comparison"):
        context.pop("previous_start", None)
        context.pop("previous_end", None)
    if dates:
        context.update(current_start=dates[0], current_end=dates[1] if len(dates) >= 2 else dates[0])
        context["period_source"] = "当前问题指定"
    elif context.get("current_start"):
        context["period_source"] = "沿用上轮分析周期"
    else:
        context.update(current_start=selected[0], current_end=selected[1], period_source="经营概览所选周期")
    start, end = pd.Timestamp(context["current_start"]), pd.Timestamp(context["current_end"])
    if end < start:
        raise ValueError("问题中的结束日期不能早于开始日期")
    if len(dates) >= 4:
        context.update(previous_start=dates[2], previous_end=dates[3])
    elif dates or "previous_start" not in context:
        if selected_comparison and not dates:
            context.update(previous_start=selected_comparison[0], previous_end=selected_comparison[1])
        else:
            previous_end = start - timedelta(days=1)
            context.update(previous_start=str((previous_end - (end - start)).date()), previous_end=str(previous_end.date()))
    if pd.Timestamp(context["previous_start"]) > pd.Timestamp(context["previous_end"]):
        raise ValueError("对比周期结束日期不能早于开始日期")
    context["selected_period"] = selected
    context["selected_comparison"] = selected_comparison
    context["question_has_explicit_period"] = bool(dates)
    context["question_has_explicit_comparison"] = len(dates) >= 4
    product = re.search(r"(?:id|name):[^\s，。；？！,;!?]+", question)
    context["question_has_explicit_product"] = bool(product)
    if product:
        context["product_key"] = product.group(0)
    context["question_clears_product"] = any(word in question for word in ("全部商品", "所有商品", "取消商品筛选"))
    if context["question_clears_product"]:
        context.pop("product_key", None)
    return context


def chat_history_messages(history):
    """Pass answers plus real tool evidence; never pass agent scratchpad/logs."""
    messages = []
    from commerce_agent import serialise_payload
    for entry in history or []:
        if entry.get("role") == "user":
            messages.append(HumanMessage(content=str(entry["content"])))
        elif entry.get("role") == "assistant":
            content = str(entry["content"])
            result = entry.get("result", {})
            if result.get("tool_calls"):
                content += "\n实际工具执行记录：\n" + serialise_payload(result["tool_calls"])
            messages.append(AIMessage(content=content))
    return messages


def update_context_from_tools(context, records):
    result = dict(context)
    for record in records:
        if record.get("status") != "success":
            continue
        params = record["input"]
        if not isinstance(params, dict):
            continue
        if record["tool"] in {"get_period_metrics", "drilldown_orders"}:
            current = {"current_start": params["start"], "current_end": params["end"]}
        elif record["tool"] in {"compare_period_metrics", "rank_product_contribution", "diagnose_business"}:
            current = {key: params[key] for key in ("current_start", "current_end", "previous_start", "previous_end")}
        else:
            current = {}
        if any(result.get(key) != value for key, value in current.items()):
            result.update(current, period_source="工具实际执行周期（见执行详情）")
        if record["tool"] == "drilldown_orders" and params.get("product"):
            result["product_key"] = params["product"]
        elif record["tool"] == "rank_product_contribution":
            rows = record["result"]
            if isinstance(rows, list) and rows:
                result["product_key"] = rows[0].get("product_key", "")
    return result
