"""LangChain tool-calling orchestration for commerce analysis."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from langchain_core.callbacks import BaseCallbackHandler

from commerce_metrics import calculate_metrics, compare_periods, order_drilldown, product_contribution
from rag_knowledge import default_knowledge_base
from model_identity import configured_identity_answer, model_identity_instruction


def serialise_payload(value: Any) -> str:
    """Return stable JSON for tool results, including pandas scalar values."""

    def convert(item):
        if isinstance(item, pd.DataFrame):
            return item.astype(object).where(pd.notna(item), None).to_dict(orient="records")
        if isinstance(item, pd.Series):
            return item.astype(object).where(pd.notna(item), None).to_dict()
        return str(item)

    return json.dumps(value, ensure_ascii=False, default=convert, indent=2)


def effective_tool_input(name, params, context):
    """Resolve omitted tool conditions to the explicit conversation context."""
    params = dict(params)
    if name in {"get_period_metrics", "drilldown_orders"}:
        for target, source in (("start", "current_start"), ("end", "current_end")):
            params[target] = context[source] if context.get("question_has_explicit_period") else params.get(target) or context.get(source, "")
    elif name in {"compare_period_metrics", "rank_product_contribution", "diagnose_business"}:
        for field in ("current_start", "current_end", "previous_start", "previous_end"):
            force = context.get("question_has_explicit_period") if field.startswith("current_") else context.get("question_has_explicit_comparison")
            params[field] = context[field] if force else params.get(field) or context.get(field, "")
    if name == "drilldown_orders":
        if context.get("question_clears_product"):
            params["product"] = ""
        elif context.get("question_has_explicit_product"):
            params["product"] = context.get("product_key", "")
        else:
            params["product"] = params.get("product") or context.get("product_key", "")
    if name == "rank_product_contribution":
        params.setdefault("top_n", 10)
    return params


def build_commerce_tools(df: pd.DataFrame, context=None, quality=None):
    """Create deterministic LangChain tools bound to the current dataframe."""

    from langchain_core.tools import tool

    knowledge_base = default_knowledge_base()
    context = context or {}

    @tool
    def get_period_metrics(start: str = "", end: str = "") -> str:
        """计算日期范围内的销售额、冲销、净销售额、订单数和客单价；省略日期时使用当前分析周期。日期格式 YYYY-MM-DD。"""

        try:
            params = effective_tool_input("get_period_metrics", {"start": start, "end": end}, context)
            return serialise_payload(calculate_metrics(df, **params))
        except Exception as exc:
            return serialise_payload({"error": str(exc)})

    @tool
    def compare_period_metrics(
        current_start: str = "",
        current_end: str = "",
        previous_start: str = "",
        previous_end: str = "",
    ) -> str:
        """对比两个日期范围的经营指标并返回变化量和变化百分比。日期格式使用 YYYY-MM-DD。"""

        try:
            params = effective_tool_input("compare_period_metrics", dict(current_start=current_start, current_end=current_end,
                                          previous_start=previous_start, previous_end=previous_end), context)
            result = compare_periods(df, **params)
            return serialise_payload(result)
        except Exception as exc:
            return serialise_payload({"error": str(exc)})

    @tool
    def rank_product_contribution(
        current_start: str = "",
        current_end: str = "",
        previous_start: str = "",
        previous_end: str = "",
        top_n: int = 10,
    ) -> str:
        """找出商品对两个周期净销售额变化贡献最大的记录。日期格式使用 YYYY-MM-DD。"""

        try:
            params = effective_tool_input("rank_product_contribution", dict(current_start=current_start, current_end=current_end,
                                          previous_start=previous_start, previous_end=previous_end, top_n=top_n), context)
            result = product_contribution(df, **params)
            return serialise_payload(result)
        except Exception as exc:
            return serialise_payload({"error": str(exc)})

    @tool
    def drilldown_orders(start: str = "", end: str = "", product: str = "") -> str:
        """查询订单证据；省略日期或 product 时沿用当前周期或商品。product 使用贡献表 product_key 精确筛选。日期格式 YYYY-MM-DD。"""

        try:
            params = effective_tool_input("drilldown_orders", dict(start=start, end=end, product=product), context)
            result = order_drilldown(df, **params)
            return serialise_payload({"row_count": len(result), "returned_rows": min(len(result), 100), "rows": result.head(100), "currency": df.attrs.get("currency", "未指定")})
        except Exception as exc:
            return serialise_payload({"error": str(exc)})

    @tool
    def retrieve_metric_rules(query: str) -> str:
        """检索销售额、冲销、净销售额、订单数和客单价的业务口径，并返回来源。"""

        return serialise_payload(knowledge_base.retrieve(query))

    @tool
    def diagnose_business(current_start: str = "", current_end: str = "", previous_start: str = "", previous_end: str = "") -> str:
        """一次完成经营诊断：指标对比、全部商品变化计算后的排名、重点商品订单证据、绑定规则原文与限制；省略日期沿用当前条件。"""
        from commerce_diagnosis import run_diagnosis
        try:
            params = effective_tool_input("diagnose_business", dict(current_start=current_start, current_end=current_end,
                                          previous_start=previous_start, previous_end=previous_end), context)
            result = run_diagnosis(df, (params["current_start"], params["current_end"]),
                                   (params["previous_start"], params["previous_end"]), quality, knowledge_base=knowledge_base)
            return serialise_payload(result.tool_payload())
        except Exception as exc:
            return serialise_payload({"error": str(exc)})

    return [get_period_metrics, compare_period_metrics, rank_product_contribution, drilldown_orders, retrieve_metric_rules, diagnose_business]


class ToolExecutionRecorder(BaseCallbackHandler):
    """Record public tool inputs/outputs only, never model reasoning or actions."""

    def __init__(self, secrets=(), context=None):
        self.records = []
        self._runs = {}
        self.secrets = secrets
        self.context = context or {}

    @staticmethod
    def payload(value):
        if hasattr(value, "content"):
            value = value.content
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                pass
        return value

    def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs):
        record = {"tool": (serialized or {}).get("name", "unknown"),
                  "input": inputs if inputs is not None else self.payload(input_str),
                  "result": None, "status": "running"}
        if isinstance(record["input"], dict):
            record["input"] = effective_tool_input(record["tool"], record["input"], self.context)
        self._runs[run_id] = record
        self.records.append(record)

    def on_tool_end(self, output, *, run_id, **kwargs):
        from model_config import safe_error
        record = self._runs.get(run_id)
        if record is not None:
            record["result"] = self.payload(output)
            failed = isinstance(record["result"], dict) and bool(record["result"].get("error"))
            if failed:
                record["result"]["error"] = safe_error(record["result"]["error"], self.secrets)
            record["status"] = "error" if failed else "success"

    def on_tool_error(self, error, *, run_id, **kwargs):
        from model_config import safe_error
        record = self._runs.get(run_id)
        if record is not None:
            record.update(status="error", result={"error": safe_error(error, self.secrets)})


def build_commerce_agent(model, df: pd.DataFrame, context=None, max_iterations=6, quality=None, model_identity=None):
    """One verified path for installed LangChain 0.3: tool-calling executor."""
    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.messages import SystemMessage
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    tools = build_commerce_tools(df, context, quality)
    system_prompt = (
        "你是 CommerceSense 电商经营分析助手，用中文回答。只能通过提供的工具计算，不能编造数值。"
        "下面的分析条件由当前问题、页面周期和上轮对话确定；当前问题明确指定日期或商品时优先使用新条件。"
        "没有明确日期时使用给定 current_start/current_end，不要再次询问日期。对比默认使用 previous_start/previous_end。"
        "连续追问要结合历史回答和实际工具结果：按商品分析调用贡献工具，查看该商品明细使用最近讨论的 product_key。"
        "贡献排名后的‘该商品’默认指排名第一的商品，回答中要说清；若历史里存在多个可能的商品，先澄清。"
        "不得把同名不同编号商品合并。用户明确取消筛选时展示全部商品。"
        "说明实际计算周期、币种和限制；销售额、冲销、净销售额分别展示，订单数包含冲销订单。"
        "当涉及口径、定义、退款/冲销时调用 retrieve_metric_rules，只引用实际返回的来源；未检索到则明确说明。"
        "用户需要完整经营诊断或周报依据时优先调用 diagnose_business；区分全部商品与排名之外的商品。"
        "工具返回 error 时不得用失败结果计算或声称成功，可以修正参数有限重试。"
        "只输出结论和数据依据，不输出内部推理、思考过程或 scratchpad。\n"
        + model_identity_instruction(model_identity) + "\n当前分析条件：\n" + serialise_payload(context or {}) + "\n币种：" + df.attrs.get("currency", "未指定")
    )
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=system_prompt),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    agent = create_tool_calling_agent(model, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=False, max_iterations=max_iterations,
                         max_execution_time=120, early_stopping_method="force",
                         return_intermediate_steps=False, handle_parsing_errors=True)


def run_commerce_agent(model, df: pd.DataFrame, question: str, history=None, period=None,
                       context=None, *, max_iterations=6, secrets=(), comparison_period=None, quality=None, model_identity=None) -> dict:
    """Run a turn, retaining completed tool evidence if any later operation fails."""
    from commerce_conversation import resolve_analysis_context, chat_history_messages, update_context_from_tools
    from model_config import safe_error

    recorder = ToolExecutionRecorder(secrets)
    resolved = {}
    error, answer = None, ""
    try:
        if not question or not question.strip():
            raise ValueError("问题不能为空")
        resolved = resolve_analysis_context(question, period, context, comparison_period)
        recorder.context = resolved
        identity_answer = configured_identity_answer(question, model_identity)
        if identity_answer:
            answer = identity_answer
        else:
            executor = build_commerce_agent(model, df, resolved, max_iterations, quality, model_identity)
            result = executor.invoke({"input": question.strip(), "chat_history": chat_history_messages(history)},
                                     config={"callbacks": [recorder]})
            answer = str(result.get("output", ""))
        if answer.startswith("Agent stopped due to"):
            error = "已达到工具调用轮次或运行时间限制，请缩小问题范围后重试。"
            answer = "本次分析未完成，已执行的工具结果见下方。"
        elif any(record["status"] == "error" for record in recorder.records):
            error = "部分工具执行失败，请查看执行详情；已完成的结果已保留。"
    except Exception as exc:
        error = safe_error(exc, secrets)
        answer = "本次分析未完成，已执行的工具结果见下方，可重试原问题。"
    sources = []
    for record in recorder.records:
        if record["tool"] in {"retrieve_metric_rules", "diagnose_business"} and record["status"] == "success" and isinstance(record["result"], dict):
            for source in record["result"].get("sources", record["result"].get("rule_sources", [])):
                if source not in sources:
                    sources.append(source)
    resolved = update_context_from_tools(resolved, recorder.records)
    return {"answer": answer, "tool_calls": recorder.records, "rule_sources": sources,
            "error": error, "context": resolved, "currency": df.attrs.get("currency", "未指定"), "model_identity": model_identity}
