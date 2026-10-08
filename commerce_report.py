"""Markdown/CSV/ZIP exports reuse one diagnostic result, without model calls."""

from dataclasses import dataclass
from decimal import Decimal
import io
import json
import math
import zipfile

import pandas as pd

from commerce_data import COMMERCE_FIELDS
from report_charts import generate_charts


METRIC_TITLES = {
    "gross_sales": "成交销售额", "reversal_amount": "冲销金额", "net_sales": "净销售额",
    "order_count": "周期去重订单数（含冲销）", "customer_count": "客户数",
    "average_order_value": "客单价（净销售额／周期去重订单数）",
    "units_sold": "销售数量", "reversed_units": "冲销数量",
}
REASON_TITLES = {"empty_order_id": "空订单号", "invalid_order_time": "无效日期或时区",
                 "invalid_quantity": "无效或非有限数量", "invalid_unit_price": "无效或非有限单价",
                 "negative_unit_price": "负单价", "price_precision": "单价超过两位小数", "amount_precision": "金额不足一分"}


def amount(minor):
    return format(Decimal(int(minor)) / 100, ".2f")


def number(value, *, two_decimals=False):
    if value is None or pd.isna(value):
        return ""
    if two_decimals:
        return f"{value:.2f}"
    return str(int(value)) if isinstance(value, (int, float)) and math.isfinite(value) and int(value) == value else str(value)


def comparison_table(result):
    rows = []
    for record in result.comparison.to_dict("records"):
        monetary = record["current_minor"] is not None
        rows.append({"metric": record["metric"], "metric_title": METRIC_TITLES[record["metric"]], "currency": result.currency,
                     **period_columns(result),
                     **{side: amount(record[side + "_minor"]) if monetary else number(record[side], two_decimals=record["metric"] == "average_order_value")
                        for side in ("current", "previous", "delta")},
                     "change_percent": number(record["change_percent"], two_decimals=True),
                     **{side + "_minor": str(record[side + "_minor"]) if monetary else "" for side in ("current", "previous", "delta")}})
    return pd.DataFrame(rows)


def product_table(result):
    frame = result.products.copy(deep=True)
    for source, target in (("current_minor", "current_net_sales"), ("previous_minor", "previous_net_sales"), ("delta_minor", "delta")):
        frame[target] = frame[source].map(amount)
    frame["contribution_percent"] = frame["contribution_percent"].map(lambda value: number(value, two_decimals=True))
    frame["currency"] = result.currency
    for key, value in period_columns(result).items():
        frame[key] = value
    return frame


def evidence_table(result):
    frame = result.evidence.copy(deep=True)
    frame["line_amount"] = frame["line_amount_minor"].map(amount)
    frame["unit_price"] = frame["unit_price"].map(lambda value: format(Decimal(str(value)), ".2f"))
    frame["currency"] = result.currency
    for edge in ("start", "end"):
        frame["period_" + edge] = frame["period"].map({"current": result.current[edge], "previous": result.previous[edge]})
    return frame


def trend_table(result):
    frame = result.trend.copy(deep=True)
    frame["net_sales"] = frame["net_sales_minor"].map(amount)
    frame["currency"] = result.currency
    return frame


def evidence_display_table(frame):
    display = frame.copy(deep=True)
    display["period"] = display["period"].map({"current": "当前周期", "previous": "对比周期"})
    labels = {field: label for field, label, _ in COMMERCE_FIELDS}
    labels.update(period="所属周期", product_key="商品标识", line_amount="明细金额", line_amount_minor="明细金额（分）",
                  currency="币种", period_start="周期开始", period_end="周期结束")
    return display.rename(columns=labels)


def csv_bytes(frame):
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")


def period_columns(result):
    return {side + "_" + edge: getattr(result, side)[edge] for side in ("current", "previous") for edge in ("start", "end")}


def markdown_table(frame):
    def cell(value):
        text = str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        return text.replace("`", "\\`").replace("<", "&lt;").replace(">", "&gt;") or "不适用"
    return "\n".join(["| " + " | ".join(map(cell, frame.columns)) + " |",
                       "| " + " | ".join(["---"] * len(frame.columns)) + " |",
                       *["| " + " | ".join(map(cell, row)) + " |" for row in frame.itertuples(index=False, name=None)]])


def make_markdown(result, metrics, products, evidence):
    current, previous, quality = result.current, result.previous, result.quality
    lines = ["# CommerceSense 经营周报", "", f"数据集：{str(result.dataset_name).replace(chr(10), ' ')}", "",
             f"当前周期：{current['start']} 至 {current['end']}（起止日全天）",
             f"对比周期：{previous['start']} 至 {previous['end']}（起止日全天）", f"币种：{result.currency}；不进行汇率转换。",
             f"生成时间（UTC）：{result.generated_at}", "", "## 数据质量与口径", "",
             f"全数据集原始记录 {quality['rows']} 条，有效 {quality['valid_rows']} 条，排除 {quality['excluded_rows']} 条，重复明细 {quality.get('duplicate_rows', 0)} 条（保留）。",
             "排除原因计数（同一记录可有多个原因）：" + ("、".join(f"{REASON_TITLES.get(key, key)}={count}" for key, count in quality.get("exclusion_counts", {}).items() if count) or "无已记录的排除原因"),
             f"当前周期有效 {current['row_count']} 条；对比周期有效 {previous['row_count']} 条。质量摘要不是各周期排除记录数。",
             "金额逐行转换为整数分后汇总；负数量作为冲销，负单价排除。订单数包含冲销订单。客单价=净销售额／周期去重订单数。", "",
             "## 指标对比", "",
             markdown_table(metrics[["metric_title", "current", "previous", "delta", "change_percent"]].rename(
                 columns={"metric_title": "指标", "current": "当前周期", "previous": "对比周期", "delta": "变化量", "change_percent": "变化比例（%）"})),
             "", f"净销售额变化：{amount(result.delta_minor)} {result.currency}。基期为零或缺少客户字段时，不填变化比例。", "",
             "## 商品变化贡献", ""]
    if result.product_available:
        shown = min(result.top_n, len(products))
        outside = max(0, len(products) - result.top_n)
        lines += [f"先计算全部 {len(products)} 个商品，再展示前 {shown} 名（按变化绝对值）。排名之外还有 {outside} 个商品，其变化合计 {amount(result.outside_top_minor)} {result.currency}。",
                  f"完整商品变化合计 {amount(sum(result.products['delta_minor']))} {result.currency}，与总净销售额变化一致。完整商品贡献 CSV 包含全部商品。",
                  "贡献比例以全部商品总变化为分母；正负抵消时可以超过 100% 或为负数，总变化为零时不适用。", "",
                  markdown_table(products.head(result.top_n)[["product_key", "product", "current_net_sales", "previous_net_sales", "delta", "contribution_percent"]].rename(
                      columns={"product_key": "商品标识", "product": "商品名称", "current_net_sales": "当前净销售额", "previous_net_sales": "对比净销售额", "delta": "变化量", "contribution_percent": "贡献比例（%）"}))]
    else:
        lines.append("未提供商品编号或名称，无法生成商品贡献。")
    lines += ["", "## 重点商品订单证据", "",
              f"选取变化绝对值最大的前 {min(result.evidence_top_n, len(products))} 个商品，导出两个周期完整有效明细，共 {len(evidence)} 条。Markdown 仅预览前 20 条，完整内容见 order_evidence.csv。", "",
              markdown_table(evidence_display_table(evidence.head(20)[[column for column in ("period", "product_key", "order_id", "order_time", "quantity", "unit_price", "line_amount") if column in evidence]])),
              "", "## 固定经营图表", "", "![净销售额趋势](charts/net_sales_trend.png)", "",
              "![商品变化](charts/product_change.png)", "", "单独下载 Markdown 时图表为相对路径；ZIP 包内包含两张 PNG，可解压后查看。", "",
              "## 规则来源与计算绑定", "", "规则原文用于解释，计算由固定代码函数执行；修改规则文档不会自行改变公式。", ""]
    for rule in result.rule_sources:
        lines += [f"### {rule['rule_id']} · {rule['title']} · v{rule['version']}", "",
                  f"来源：{rule['source']}:{rule['line']}；指标：{', '.join(rule['metric_ids'])}；计算函数：{rule['calculator'] or '解读限制，无计算函数'}。", "",
                  *["> " + line for line in rule["text"].splitlines()], ""]
    lines += ["## 数据限制", "", *["- " + text for text in result.limitations]]
    if result.ai_interpretation:
        lines += ["", "## AI 解读（模型生成，需人工核对）", "", result.ai_interpretation]
    else:
        lines += ["", "未添加 AI 解读；本报告由固定计算函数生成，不依赖模型 API。"]
    return "\n\n".join(lines) + "\n"


@dataclass(frozen=True)
class ReportBundle:
    markdown: str
    metrics_csv: bytes
    products_csv: bytes
    evidence_csv: bytes
    trend_csv: bytes
    charts: dict
    zip_bytes: bytes


def build_report_bundle(result):
    metrics, products, evidence = comparison_table(result), product_table(result), evidence_table(result)
    markdown = make_markdown(result, metrics, products, evidence)
    charts = generate_charts(result)
    files = {"report.md": markdown.encode("utf-8"), "metrics_comparison.csv": csv_bytes(metrics),
             "product_contribution.csv": csv_bytes(products), "order_evidence.csv": csv_bytes(evidence),
             "daily_net_sales.csv": csv_bytes(trend_table(result)), **charts}
    manifest = {"schema_version": "1.0", "generated_at": result.generated_at, "currency": result.currency,
                "dataset_name": result.dataset_name, "current": result.current, "previous": result.previous,
                "quality": result.quality, "total_products": len(result.products),
                "total_delta_minor": result.delta_minor, "outside_top_delta_minor": result.outside_top_minor,
                "evidence_rows": len(result.evidence), "product_available": result.product_available,
                "rule_sources": [{key: value for key, value in rule.items() if key != "text"} for rule in result.rule_sources],
                "limitations": result.limitations, "ai_interpretation_included": bool(result.ai_interpretation)}
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return ReportBundle(markdown, files["metrics_comparison.csv"], files["product_contribution.csv"],
                        files["order_evidence.csv"], files["daily_net_sales.csv"], charts, output.getvalue())
