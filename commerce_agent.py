"""LangChain tool-calling orchestration for commerce analysis."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from commerce_metrics import calculate_metrics, compare_periods, order_drilldown, product_contribution


def serialise_payload(value: Any) -> str:
    """Return stable JSON for tool results, including pandas scalar values."""

    if isinstance(value, pd.DataFrame):
        value = value.to_dict(orient="records")
    elif isinstance(value, pd.Series):
        value = value.to_dict()
    return json.dumps(value, ensure_ascii=False, default=str, indent=2)


def build_commerce_tools(df: pd.DataFrame):
    """Create deterministic LangChain tools bound to the current dataframe."""

    from langchain_core.tools import tool

    @tool
    def get_period_metrics(start: str, end: str) -> str:
        """计算指定日期范围内的销售额、冲销、净销售额、订单数和客单价。日期格式使用 YYYY-MM-DD。"""

        try:
            return serialise_payload(calculate_metrics(df, start, end))
        except Exception as exc:
            return serialise_payload({"error": str(exc)})

    @tool
    def compare_period_metrics(
        current_start: str,
        current_end: str,
        previous_start: str,
        previous_end: str,
    ) -> str:
        """对比两个日期范围的经营指标并返回变化量和变化百分比。日期格式使用 YYYY-MM-DD。"""

        try:
            result = compare_periods(df, current_start, current_end, previous_start, previous_end)
            return serialise_payload(result)
        except Exception as exc:
            return serialise_payload({"error": str(exc)})

    @tool
    def rank_product_contribution(
        current_start: str,
        current_end: str,
        previous_start: str,
        previous_end: str,
        top_n: int = 10,
    ) -> str:
        """找出商品对两个周期净销售额变化贡献最大的记录。日期格式使用 YYYY-MM-DD。"""

        try:
            result = product_contribution(df, current_start, current_end, previous_start, previous_end, top_n)
            return serialise_payload(result)
        except Exception as exc:
            return serialise_payload({"error": str(exc)})

    @tool
    def drilldown_orders(start: str, end: str, product: str = "") -> str:
        """查询指定日期范围的订单证据，可选按商品名称或编号筛选。日期格式使用 YYYY-MM-DD。"""

        try:
            result = order_drilldown(df, start, end, product or None).head(100)
            return serialise_payload({"row_count": len(result), "rows": result})
        except Exception as exc:
            return serialise_payload({"error": str(exc)})

    return [get_period_metrics, compare_period_metrics, rank_product_contribution, drilldown_orders]


def build_commerce_agent(model, df: pd.DataFrame):
    """Build a LangChain tool-calling executor with a compatibility fallback."""

    tools = build_commerce_tools(df)
    system_prompt = (
        "你是电商经营分析 Agent。只能使用提供的业务工具计算数据，不能编造数值。"
        "涉及周期对比时必须先确定当前周期和上一周期；回答中说明指标口径、日期范围和数据限制。"
        "销售额、冲销金额、净销售额必须分别展示；如果问题缺少日期范围，先向用户询问。"
    )
    try:
        from langchain.agents import AgentExecutor, create_tool_calling_agent
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )
        agent = create_tool_calling_agent(model, tools, prompt)
        return AgentExecutor(agent=agent, tools=tools, verbose=False, max_iterations=6, handle_parsing_errors=True)
    except ImportError:
        from langchain.agents import AgentType, initialize_agent

        return initialize_agent(
            tools,
            model,
            agent=AgentType.OPENAI_FUNCTIONS,
            verbose=False,
            max_iterations=6,
            handle_parsing_errors=True,
        )


def run_commerce_agent(model, df: pd.DataFrame, question: str) -> str:
    """Run one user question through the commerce tool-calling agent."""

    if not question or not question.strip():
        raise ValueError("Question cannot be empty")
    executor = build_commerce_agent(model, df)
    result = executor.invoke({"input": question.strip()})
    if isinstance(result, dict):
        return str(result.get("output", result))
    return str(result)

