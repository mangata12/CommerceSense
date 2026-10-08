"""Chinese business UI; deterministic pages never require a model credential."""

from datetime import timedelta
from decimal import Decimal
import io
from pathlib import Path

import pandas as pd
import streamlit as st

from commerce_agent import run_commerce_agent
from commerce_data import COMMERCE_FIELDS
from commerce_metrics import calculate_metrics, compare_periods, product_contribution, order_drilldown, metrics_snapshot, product_catalog
from commerce_session import load_dataset, apply_dataset_mapping, clear_conversation, prepared_preview
from commerce_view_cache import cached_view
from model_identity import public_model_identity, configured_identity_answer
from model_config import PROVIDERS, resolve_model_settings, create_chat_model, safe_error
from report_ui import render_report


METRIC_LABELS = {
    "gross_sales": "成交销售额", "reversal_amount": "冲销金额", "net_sales": "净销售额",
    "order_count": "周期去重订单数（含冲销）", "customer_count": "客户数",
    "average_order_value": "客单价（净销售额／周期去重订单数）",
    "units_sold": "销售数量", "reversed_units": "冲销数量", "row_count": "周期有效记录数",
}
REASON_LABELS = {
    "empty_order_id": "空订单号", "invalid_order_time": "无效日期或不支持的时区",
    "invalid_quantity": "无效或非有限数量", "invalid_unit_price": "无效或非有限单价",
    "negative_unit_price": "负单价", "price_precision": "单价超过两位小数",
    "amount_precision": "明细金额不足最小货币单位",
}


def model_sidebar():
    with st.sidebar:
        st.header("CommerceSense")
        st.caption("电商经营数据分析助手")
        with st.expander("模型设置", expanded=False):
            provider = st.selectbox("模型服务", list(PROVIDERS), key="model_provider")
            variable, default = PROVIDERS[provider]
            model_name = st.text_input("模型名称", value=default, key=f"model_name_{provider}")
            key = st.text_input("API Key", type="password", key=f"model_key_{provider}",
                                help=f"仅当前会话使用；留空时读取启动环境中的 {variable}。")
            st.caption("请求超时 45 秒，失败最多重试 1 次；助手最多执行 6 轮工具调用。")
        st.caption("数据导入、经营概览无需密钥。需要问答时再配置模型。")
        st.caption(f"当前模型配置：{provider} / {model_name}")
    return provider, model_name, key


def handle_upload():
    file = st.session_state.get("commerce_upload")
    if file is None:
        return
    try:
        load_dataset(st.session_state, file)
        st.session_state["commerce_dataset_name"] = file.name
        st.session_state.pop("commerce_import_error", None)
    except Exception as exc:
        st.session_state["commerce_import_error"] = str(exc)


def render_quality(raw, preview):
    quality = preview["quality"]
    columns = st.columns(4)
    for column, label, key in zip(columns, ["原始记录", "有效记录", "排除记录", "重复明细"],
                                   ["rows", "valid_rows", "excluded_rows", "duplicate_rows"]):
        column.metric(label, f"{quality[key]:,}")
    st.caption("重复明细保留；负数量作为冲销保留。每行可有多个排除原因，原因计数之和可能大于排除记录数。")
    with st.expander("数据质量详情", expanded=False):
        st.dataframe(pd.DataFrame([{"排除原因": REASON_LABELS[key], "记录数": count}
                                  for key, count in quality["exclusion_counts"].items()]),
                     hide_index=True, width="stretch")
        if not preview["excluded"].empty:
            st.caption("以下展示前 100 条排除记录；_source_row 为源表行号（含表头）。")
            st.dataframe(preview["excluded"].head(100), hide_index=True, width="stretch")
        st.markdown("**原始列概况**")
        summary = cached_view(st.session_state, "raw_columns", (), lambda: pd.DataFrame([{"列名": str(column), "数据类型": str(raw[column].dtype),
                                   "空值数": int((raw[column].isna() | raw[column].eq("")).sum()),
                                   "不同值数": int(raw[column].nunique())} for column in raw]))
        st.dataframe(summary, hide_index=True, width="stretch")
        st.markdown("**原始数据预览**")
        st.dataframe(raw.head(20), hide_index=True, width="stretch")


def render_import():
    st.subheader("数据导入")
    st.write("上传订单明细，确认币种和字段映射后即可查看经营概览。")
    st.file_uploader("上传 CSV 或 XLSX", type=["csv", "xlsx"], key="commerce_upload", on_change=handle_upload)
    if st.button("加载模拟样例（CNY）", key="load_commerce_sample"):
        file = io.BytesIO((Path(__file__).parent / "data/examples/commerce_orders_demo.csv").read_bytes())
        file.name = "commerce_orders_demo.csv"
        load_dataset(st.session_state, file)
        st.session_state["commerce_currency_choice"] = "CNY"
        st.session_state["commerce_dataset_name"] = "模拟电商订单（CNY）"
        st.session_state.pop("commerce_import_error", None)
        apply_dataset_mapping(st.session_state, st.session_state["commerce_mapping"], "CNY")
        st.rerun()
    if st.session_state.get("commerce_import_error"):
        st.error("文件读取失败：" + st.session_state["commerce_import_error"])
        return None
    raw = st.session_state.get("commerce_raw_df")
    if raw is None:
        st.info("还没有数据。可以先加载模拟样例体验，无需 API Key。")
        return None
    st.caption("当前数据：" + st.session_state.get("commerce_dataset_name", "已导入订单"))
    currency = st.selectbox("数据币种", ["请选择币种", "CNY", "GBP", "USD", "EUR"], key="commerce_currency_choice")
    st.caption("样例为模拟 CNY；UCI Online Retail 请选 GBP。币种选项不进行汇率转换。")
    st.caption("Excel 只读取第一张工作表，原文件中已丢失的编号前导零无法恢复。带时区日期请先转换为统一的本地时间。")
    choices = ["(未映射)", *map(str, raw.columns)]
    mapping, selected = st.session_state.get("commerce_mapping", {}), {}
    columns = st.columns(2)
    for index, (field, label, required) in enumerate(COMMERCE_FIELDS):
        with columns[index % 2]:
            source = st.selectbox(label + (" *" if required else ""), choices,
                                  index=choices.index(mapping[field]) if mapping.get(field) in choices else 0,
                                  key=f"commerce_mapping_{field}")
        if source != "(未映射)":
            selected[field] = source
    preview = prepared_preview(st.session_state, selected, currency if currency != "请选择币种" else "CNY")
    quality = preview["quality"]
    render_quality(raw, preview)
    if quality["missing_required"]:
        labels = dict((field, label) for field, label, _ in COMMERCE_FIELDS)
        st.warning("请映射必填字段：" + "、".join(labels[key] for key in quality["missing_required"]))
    if quality["missing_product"]:
        st.warning("商品编号或商品名称至少提供一个；未提供时可查看总指标，无法进行商品贡献分析。")
    if st.button("应用电商字段映射", type="primary", disabled=bool(quality["missing_required"]) or currency == "请选择币种"):
        apply_dataset_mapping(st.session_state, selected, currency)
        st.rerun()
    if selected != st.session_state.get("commerce_applied_mapping") or currency != st.session_state.get("commerce_currency"):
        st.info("请先应用当前字段映射及币种，再查看指标或运行分析。")
        return None
    data = st.session_state.get("commerce_standard_df")
    if data is None or data.empty:
        st.warning("没有可分析的有效记录，请检查数据或映射。")
        return None
    st.success("字段映射已应用，经营概览与分析助手使用同一份有效数据。")
    return data


def money(minor):
    return f"{Decimal(minor) / 100:,.2f}"


def overview_results(data, period, previous_period, has_products):
    with metrics_snapshot(data):
        return {"metrics": calculate_metrics(data, *period),
                "comparison": compare_periods(data, *period, *previous_period),
                "contribution": product_contribution(data, *period, *previous_period, top_n=None) if has_products else None}


def render_overview(data):
    st.subheader("经营概览")
    if data is None:
        st.info("先在数据导入中加载数据并应用字段映射。")
        return None
    currency = data.attrs["currency"]
    bounds = cached_view(st.session_state, "date_bounds", (), lambda: (
        pd.Timestamp(data["order_time"].min()).date(), pd.Timestamp(data["order_time"].max()).date()))
    period = st.date_input("当前分析周期", value=bounds, key="commerce_current_period")
    if not isinstance(period, tuple) or len(period) != 2:
        st.info("请选择完整的起止日期。")
        return None
    start, end = period
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - (end - start)
    if st.session_state.get("commerce_comparison_anchor") != period:
        st.session_state["commerce_previous_period"] = (previous_start, previous_end)
        st.session_state["commerce_comparison_anchor"] = period
    previous_period = st.date_input("对比分析周期", key="commerce_previous_period")
    if not isinstance(previous_period, tuple) or len(previous_period) != 2:
        st.info("请选择完整的对比分析周期。")
        return period
    previous_start, previous_end = previous_period
    has_products = not st.session_state["commerce_quality"]["missing_product"]
    results = cached_view(st.session_state, "overview", (period, previous_period),
                          lambda: overview_results(data, period, previous_period, has_products))
    metrics = results["metrics"]
    columns = st.columns(4)
    for column, label, value in zip(columns, ["净销售额", "成交销售额", "冲销金额", "周期去重订单数"],
                                     [money(metrics["net_sales_minor"]) + " " + currency,
                                      money(metrics["gross_sales_minor"]) + " " + currency,
                                      money(metrics["reversal_amount_minor"]) + " " + currency, str(metrics["order_count"])]):
        column.metric(label, value)
    st.caption(f"周期：{start} 至 {end}（包含结束日全天）。币种：{currency}。订单数包含冲销订单；客单价=净销售额／周期去重订单数。")
    st.dataframe(pd.DataFrame([{"指标": label, "结果": str(metrics[key]) if metrics[key] is not None
                               else "无法统计（未提供客户字段）" if key == "customer_count" else "不适用"}
                              for key, label in METRIC_LABELS.items()]), hide_index=True, width="stretch")
    if metrics["row_count"] == 0:
        st.info("当前周期没有有效记录，销售额为 0，客单价不适用。")
    st.markdown("#### 周期对比")
    st.caption(f"对比周期：{previous_start} 至 {previous_end}。默认使用同等天数的相邻周期，可手动修改。基期为 0 时变化比例不适用。")
    comparison = results["comparison"].copy()
    comparison["metric"] = comparison["metric"].map(METRIC_LABELS)
    st.dataframe(comparison.rename(columns={"metric": "指标", "current": "当前周期", "previous": "对比周期",
                                             "delta": "变化量", "change_percent": "变化比例（%）"}), hide_index=True, width="stretch")
    st.markdown("#### 商品贡献")
    products = {}
    if st.session_state["commerce_quality"]["missing_product"]:
        st.info("未提供商品字段，无法进行商品贡献分析。")
    else:
        contribution = results["contribution"]
        st.caption(f"共 {len(contribution)} 个商品，按变化绝对值展示前 10 个。")
        st.dataframe(contribution.head(10).drop(columns=["current_minor", "previous_minor", "delta_minor"]).rename(
            columns={"product_key": "商品标识", "product": "商品名称", "current_net_sales": "当前净销售额",
                     "previous_net_sales": "对比净销售额", "delta": "变化量", "contribution_percent": "贡献比例（%）"}),
            hide_index=True, width="stretch")
        products = cached_view(st.session_state, "products", (), lambda: product_catalog(data))
    st.markdown("#### 订单明细")
    selected = st.selectbox("订单下钻商品筛选（精确标识）", ["", *products], key="commerce_product_filter",
                            format_func=lambda key: f"{products[key]}（{key}）" if key else "全部商品")
    def detail_preview():
        rows = order_drilldown(data, start, end, selected or None)
        return len(rows), rows.head(200)
    detail_count, details = cached_view(st.session_state, "details", (period, selected), detail_preview)
    labels = {field: label for field, label, _ in COMMERCE_FIELDS}
    labels.update(line_amount="明细金额", line_amount_minor="明细金额（分）", record_type="记录类型")
    st.caption(f"共 {detail_count} 条，预览前 200 条；下钻条件不会自动修改助手对话中讨论的商品。")
    st.dataframe(details.head(200).rename(columns=labels), hide_index=True, width="stretch")
    return period


def render_assistant_result(result):
    context = result.get("context", {})
    identity = result.get("model_identity")
    if identity:
        st.caption(f"本次模型配置：{identity['provider']} / {identity['model_name']}")
    if context.get("current_start"):
        st.caption(f"分析周期：{context['current_start']} 至 {context['current_end']}（{context['period_source']}）；币种：{result['currency']}。")
    st.markdown(result["answer"])
    if result.get("error"):
        st.error(result["error"])
    if result.get("tool_calls"):
        with st.expander("工具执行详情", expanded=bool(result.get("error"))):
            for record in result["tool_calls"]:
                status = {"success": "已完成", "error": "失败", "running": "未完成"}[record["status"]]
                st.markdown(f"**{record['tool']} · {status}**")
                st.caption("输入参数")
                st.json(record["input"])
                st.caption("结构化结果")
                st.json(record["result"])
    if result.get("rule_sources"):
        with st.expander("规则来源", expanded=False):
            st.json(result["rule_sources"])
            st.caption("仅展示本轮实际检索或诊断所引用的规则；原文、版本和相关性分数见工具结构化结果。未命中时明确返回“未找到规则”。")


def submit_question(question, data, period, config):
    state = st.session_state
    history = list(state.get("commerce_messages", []))
    messages = state.setdefault("commerce_messages", [])
    messages.append({"role": "user", "content": question})
    provider, model_name, key = config
    identity = public_model_identity(provider, model_name)
    try:
        identity_answer = configured_identity_answer(question, identity)
        settings = None if identity_answer else resolve_model_settings(provider, model_name, key)
        model = None if identity_answer else create_chat_model(settings)
        result = run_commerce_agent(model, data, question, history, period, state.get("commerce_chat_context"),
                                    secrets=(settings.api_key,) if settings else (), comparison_period=state.get("commerce_previous_period"),
                                    quality=state.get("commerce_quality"), model_identity=identity)
    except Exception as exc:
        result = {"answer": "问题已保留，配置模型后可以重试。", "error": safe_error(exc, (key,)),
                  "tool_calls": [], "rule_sources": [], "context": {}, "currency": data.attrs["currency"], "model_identity": identity}
    messages.append({"role": "assistant", "content": result["answer"], "result": result})
    if result.get("context"):
        state["commerce_chat_context"] = result["context"]
    state["commerce_retry_question"] = question if result.get("error") else None
    state["commerce_tool_results"] = result["tool_calls"]


def render_assistant(data, period, config):
    st.subheader("分析助手")
    st.caption("例如：分析本期经营情况 → 继续按商品分析 → 查看该商品明细。支持在新问题中明确修改日期或商品。")
    if data is None or period is None:
        st.info("请先应用数据映射，并在经营概览选择完整的分析周期。")
        return
    st.caption(f"页面周期：{period[0]} 至 {period[1]}。首次提问默认使用该周期；追问沿用上轮条件，修改页面周期或在问题中指定日期可更新。")
    if st.button("清空对话", key="clear_commerce_chat"):
        clear_conversation(st.session_state)
        st.rerun()
    for entry in st.session_state.get("commerce_messages", []):
        with st.chat_message(entry["role"]):
            if entry.get("result"):
                render_assistant_result(entry["result"])
            else:
                st.markdown(entry["content"])
    retry = st.session_state.get("commerce_retry_question")
    retry_clicked = bool(retry) and st.button("重试上个问题", key="retry_commerce_chat")
    question = st.chat_input("输入经营分析问题或继续追问", key="commerce_chat_input")
    if question or retry_clicked:
        with st.spinner("正在调用经营分析工具…"):
            submit_question(question or retry, data, period, config)
        st.rerun()
    render_advanced_tools(data, config)


@st.fragment
def render_advanced_tools(data, config):
    with st.expander("高级工具（默认关闭）", expanded=False):
        enabled = st.toggle("启用高级工具", value=False, key="commerce_advanced_enabled")
        if not enabled:
            st.caption("包含自然语言查询、自由绘图和数据处理。")
            return
        st.warning("这些工具会执行模型生成的 Python 代码，不能视为安全沙箱。请仅在可信的本地环境使用可信数据；处理结果不会覆盖经营数据。")
        identity = public_model_identity(*config[:2])
        st.caption(f"当前模型配置：{identity['provider']} / {identity['model_name']}")
        with st.form("commerce_advanced_form"):
            mode = st.selectbox("工具类型", ["自然语言查询", "自由绘图", "数据处理"], key="commerce_advanced_mode")
            request = st.text_area("描述需求", key="commerce_advanced_request")
            submitted = st.form_submit_button("执行高级工具", key="execute_advanced")
        if submitted and not request.strip():
            st.warning("请先输入需求。")
        elif submitted:
            try:
                identity_answer = configured_identity_answer(request, identity)
                if identity_answer:
                    result = {"mode": mode, "answer": identity_answer}
                else:
                    settings = resolve_model_settings(*config)
                    model = create_chat_model(settings)
                    from advanced_tools import answer_nlq_text, generate_and_render_chart, manipulate_dataframe_with_llm
                    with st.spinner("正在执行高级工具…"):
                        if mode == "自然语言查询":
                            result = {"mode": mode, "answer": answer_nlq_text(model, data, request, model_identity=identity)}
                        elif mode == "自由绘图":
                            figure, code, error = generate_and_render_chart(model, data, request)
                            result = {"mode": mode, "figure": figure, "code": code, "error": error}
                        else:
                            frame, code, error = manipulate_dataframe_with_llm(model, data, request)
                            result = {"mode": mode, "frame": frame, "code": code, "error": error}
                st.session_state["commerce_advanced_result"] = {**result, "model_identity": identity}
            except Exception as exc:
                st.session_state["commerce_advanced_result"] = {"mode": mode, "error": safe_error(exc, (config[2],)), "model_identity": identity}
        result = st.session_state.get("commerce_advanced_result")
        if result and result.get("model_identity") != identity:
            st.session_state.pop("commerce_advanced_result", None)
            result = None
        if result:
            if result.get("error"):
                st.error(safe_error(result["error"], (config[2],)))
            if result.get("answer"):
                st.markdown(result["answer"])
            if result.get("code"):
                st.code(result["code"], language="python")
            if result.get("figure") is not None:
                st.pyplot(result["figure"])
            if result.get("frame") is not None and not result.get("error"):
                st.dataframe(result["frame"].head(200), width="stretch")
                st.download_button("下载处理结果", result["frame"].to_csv(index=False).encode("utf-8-sig"),
                                   file_name="manipulated.csv", mime="text/csv")


def run_app():
    st.set_page_config(page_title="CommerceSense · 经营分析", page_icon="📊", layout="wide")
    st.title("CommerceSense · 电商经营分析")
    st.caption("导入订单 → 查看经营指标 → 连续追问 → 经营报告")
    config = model_sidebar()
    imported, overview, assistant, report = st.tabs(["数据导入", "经营概览", "分析助手", "经营报告"])
    with imported:
        data = render_import()
    with overview:
        period = render_overview(data)
    with assistant:
        render_assistant(data, period, config)
    with report:
        render_report(data, period, st.session_state.get("commerce_previous_period"), config)
