"""Route explicit chart requests without loading model or plotting libraries."""

import re


def resolve_advanced_mode(selected, request):
    if selected != "自然语言查询":
        return selected
    text = request.strip().lower()
    if re.search(r"(?:不要|不用|无需|不需要|别)\s*(?:画|绘|生成.*图)|\b(?:do not|don't)\s+(?:plot|draw)", text):
        return selected
    chart = r"柱状图|条形图|折线图|饼图|散点图|直方图|箱线图|热力图|走势图|bar\s*chart|line\s*chart|scatter\s*plot|histogram|pie\s*chart|heatmap|box\s*plot"
    intent = r"画|绘制|绘图|生成|做[一张个幅]*|展示|可视化|\b(?:plot|draw|create|show|visualize)\b"
    if re.search(intent, text) and (re.search(chart, text) or re.search(r"画.*图|绘图|可视化|\bplot\b", text)):
        return "自由绘图"
    if re.fullmatch(r"(?:" + chart + r")[。.!！?？]*", text):
        return "自由绘图"
    return selected
