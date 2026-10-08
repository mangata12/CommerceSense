"""Report preview and downloads; generate the base report without an API key."""

from dataclasses import replace

import streamlit as st

from commerce_diagnosis import run_diagnosis, add_ai_interpretation
from commerce_report import build_report_bundle, comparison_table, product_table, evidence_table, evidence_display_table
from model_config import resolve_model_settings, create_chat_model, safe_error


def render_report(data, current_period, previous_period, config):
    st.subheader("经营报告")
    st.write("一次生成周期对比、完整商品贡献、重点商品订单证据、规则依据和周报下载，无需 API Key。")
    if data is None or not current_period or not previous_period or len(previous_period) != 2:
        st.info("请先导入数据，并在经营概览选择完整的当前周期和对比周期。")
        return
    st.caption(f"当前周期：{current_period[0]} 至 {current_period[1]}；对比周期：{previous_period[0]} 至 {previous_period[1]}。在经营概览中修改日期。")
    state = st.session_state
    signature = (tuple(map(str, current_period)), tuple(map(str, previous_period)),
                 state.get("commerce_file_fingerprint"), str(state.get("commerce_applied_mapping")), data.attrs["currency"])
    saved = state.get("commerce_report")
    if saved and saved["signature"] != signature:
        state.pop("commerce_report", None)
        saved = None
    if st.button("生成基础经营周报", type="primary", key="generate_commerce_report"):
        try:
            with st.spinner("正在生成经营诊断、图表和报告包…"):
                result = run_diagnosis(data, current_period, previous_period, state["commerce_quality"],
                                       dataset_name=state.get("commerce_dataset_name", "订单数据"))
                bundle = build_report_bundle(result)
                saved = {"signature": signature, "result": result, "bundle": bundle}
                state["commerce_report"] = saved
        except Exception as exc:
            st.error("报告生成失败：" + safe_error(exc, (config[2],)))
    if not saved:
        st.info("点击生成基础经营周报。计算和图表由固定函数完成，模型配置不影响基础报告。")
        return
    result, bundle = saved["result"], saved["bundle"]
    st.success("报告已生成。页面、表格、图表和下载文件使用同一份诊断结果。")
    if st.button("添加 AI 解读（可选）", key="add_report_ai"):
        try:
            settings = resolve_model_settings(*config)
            with st.spinner("正在生成附加文字解读，基础数据保持不变…"):
                result = add_ai_interpretation(result, create_chat_model(settings))
                bundle = build_report_bundle(result)
        except Exception as exc:
            result = replace(result, ai_error=safe_error(exc, (config[2],)))
        saved.update(result=result, bundle=bundle)
    if result.ai_error:
        st.error("AI 解读未生成，基础报告仍可下载：" + result.ai_error)
    if result.ai_interpretation:
        st.markdown("#### AI 解读（模型生成，需人工核对）")
        st.markdown(result.ai_interpretation)
    st.markdown("#### 指标对比")
    metrics = comparison_table(result)
    st.dataframe(metrics[["metric_title", "current", "previous", "delta", "change_percent"]].rename(
        columns={"metric_title": "指标", "current": "当前周期", "previous": "对比周期", "delta": "变化量", "change_percent": "变化比例（%）"}),
        hide_index=True, width="stretch")
    st.markdown("#### 商品变化贡献")
    st.caption(f"完整计算 {len(result.products)} 个商品，预览前 {result.top_n} 名；排名外 {max(0, len(result.products) - result.top_n)} 个商品也在 CSV 中。")
    products = product_table(result)
    st.dataframe(products.head(result.top_n)[["product_key", "product", "current_net_sales", "previous_net_sales", "delta", "contribution_percent"]].rename(
        columns={"product_key": "商品标识", "product": "商品名称", "current_net_sales": "当前净销售额",
                 "previous_net_sales": "对比净销售额", "delta": "变化量", "contribution_percent": "贡献比例（%）"}),
                 hide_index=True, width="stretch")
    st.markdown("#### 重点商品订单证据")
    st.caption(f"共 {len(result.evidence)} 条，页面预览前 200 条；CSV 包含所选重点商品两个周期的完整有效明细。")
    st.dataframe(evidence_display_table(evidence_table(result).head(200)), hide_index=True, width="stretch")
    for path, content in bundle.charts.items():
        st.image(content, caption="净销售额趋势" if "trend" in path else "商品净销售额变化", width="stretch")
    with st.expander("规则原文与计算函数", expanded=False):
        for rule in result.rule_sources:
            st.markdown(f"**{rule['rule_id']} · {rule['title']} · v{rule['version']}**")
            st.caption(f"{rule['source']}:{rule['line']} · {rule['calculator'] or '解读限制'}")
            st.text(rule["text"])
    with st.expander("周报全文预览", expanded=False):
        preview = bundle.markdown.replace("![净销售额趋势](charts/net_sales_trend.png)", "图表见上方预览或 ZIP 报告包。")
        preview = preview.replace("![商品变化](charts/product_change.png)", "")
        st.markdown(preview)
    st.markdown("#### 下载")
    filename = f"CommerceSense_{result.current['start']}_{result.current['end']}"
    st.download_button("下载完整报告包（ZIP，含图表 PNG）", bundle.zip_bytes, filename + ".zip", "application/zip", key="download_report_zip")
    st.download_button("下载 Markdown 周报", bundle.markdown.encode("utf-8"), filename + ".md", "text/markdown", key="download_report_md")
    st.download_button("下载指标对比 CSV", bundle.metrics_csv, "metrics_comparison.csv", "text/csv", key="download_report_metrics")
    st.download_button("下载全部商品贡献 CSV", bundle.products_csv, "product_contribution.csv", "text/csv", key="download_report_products")
    st.download_button("下载完整订单证据 CSV", bundle.evidence_csv, "order_evidence.csv", "text/csv", key="download_report_evidence")
    st.caption("CSV 为 UTF-8 BOM；用 Excel 打开时请将订单号、商品号按文本导入，防止软件再次丢失前导零。")
