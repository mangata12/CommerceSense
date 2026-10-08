"""Fixed PNG charts from the diagnostic snapshot; no model-generated code."""

import io
import textwrap

import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib import font_manager


def report_font():
    for family in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei"):
        try:
            return font_manager.FontProperties(fname=font_manager.findfont(family, fallback_to_default=False))
        except ValueError:
            pass
    return font_manager.FontProperties(family="DejaVu Sans")


def as_png(figure):
    buffer = io.BytesIO()
    FigureCanvasAgg(figure).print_png(buffer)
    return buffer.getvalue()


def generate_charts(result):
    font = report_font()
    trend = Figure(figsize=(10, 4.5), dpi=150, layout="constrained")
    axis = trend.subplots()
    for label, title, color in (("previous", "对比周期", "#8294ae"), ("current", "当前周期", "#2563eb")):
        rows = result.trend.loc[result.trend["period"].eq(label)]
        axis.plot(pd.to_datetime(rows["date"]), [int(value) / 100 for value in rows["net_sales_minor"]],
                  marker="o", markersize=3, color=color, label=title)
    axis.set_title("净销售额趋势", fontproperties=font)
    axis.set_ylabel(f"净销售额（{result.currency}）", fontproperties=font)
    axis.set_xlabel("订单日期（包含起止日）", fontproperties=font)
    axis.axhline(0, color="#999999", linewidth=0.6)
    axis.grid(axis="y", alpha=0.2)
    axis.legend(prop=font)
    axis.tick_params(axis="x", rotation=25)
    change = Figure(figsize=(10, 6), dpi=150, layout="constrained")
    axis = change.subplots()
    products = result.products.head(result.top_n)
    if result.product_available and not products.empty:
        labels = ["\n".join(textwrap.wrap(str(row["product"])[:35] + " (" + row["product_key"] + ")", width=30))
                  for row in products.to_dict("records")]
        values = [int(value) / 100 for value in products["delta_minor"]]
        axis.barh(range(len(products)), values, color=["#2563eb" if value >= 0 else "#e59d33" for value in values])
        axis.set_yticks(range(len(products)), labels, fontproperties=font)
        axis.invert_yaxis()
        axis.axvline(0, color="#555555", linewidth=0.8)
        axis.grid(axis="x", alpha=0.2)
    else:
        axis.text(0.5, 0.5, "未提供商品字段" if not result.product_available else "所选周期没有商品记录",
                  ha="center", va="center", transform=axis.transAxes, fontproperties=font)
    axis.set_title(f"商品净销售额变化（展示前 {min(result.top_n, len(result.products))} 名 / 共 {len(result.products)} 个商品）", fontproperties=font)
    axis.set_xlabel(f"当前周期减去对比周期（{result.currency}）", fontproperties=font)
    return {"charts/net_sales_trend.png": as_png(trend), "charts/product_change.png": as_png(change)}
