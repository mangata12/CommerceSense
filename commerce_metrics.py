"""Deterministic commerce metrics used by the UI and future LangChain tools."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd
from commerce_data import parse_commerce_rows


REQUIRED_METRIC_COLUMNS = ("order_id", "quantity", "unit_price", "order_time")


def prepare_metrics_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Parse canonical columns and add a line-level amount without dropping rows."""

    missing = [column for column in REQUIRED_METRIC_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError("Missing canonical commerce columns: " + ", ".join(missing))

    return parse_commerce_rows(df)


def filter_period(df: pd.DataFrame, start: date | str | pd.Timestamp, end: date | str | pd.Timestamp) -> pd.DataFrame:
    """Filter a date range with inclusive start and inclusive end semantics."""

    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize() + timedelta(days=1)
    if end_ts <= start_ts:
        raise ValueError("Period end must be on or after period start")

    prepared = prepare_metrics_frame(df)
    mask = prepared["_valid_metric_row"] & (prepared["_order_time"] >= start_ts) & (prepared["_order_time"] < end_ts)
    return prepared.loc[mask].copy()


def calculate_metrics(df: pd.DataFrame, start: date | str | pd.Timestamp, end: date | str | pd.Timestamp) -> dict[str, Any]:
    """Calculate sales metrics for one inclusive date range."""

    period = filter_period(df, start, end)
    amounts = period["_line_amount_minor"]
    positive = amounts[amounts > 0]
    negative = amounts[amounts < 0]
    order_ids = period["order_id"].dropna()
    customers = period["customer_id"].replace("", pd.NA).dropna() if "customer_id" in period.columns else None
    metrics = {
        "start": str(pd.Timestamp(start).date()),
        "end": str(pd.Timestamp(end).date()),
        "row_count": int(len(period)),
        "order_count": int(order_ids.nunique()),
        "currency": df.attrs.get("currency", "未指定"),
        "customer_count": int(customers.nunique()) if customers is not None else None,
        "gross_sales_minor": int(positive.sum()),
        "reversal_amount_minor": int(-negative.sum()),
        "net_sales_minor": int(amounts.sum()),
        "gross_sales": int(positive.sum()) / 100,
        "reversal_amount": int(-negative.sum()) / 100,
        "net_sales": int(amounts.sum()) / 100,
        "units_sold": round(float(period.loc[period["_quantity"] > 0, "_quantity"].sum()), 2),
        "reversed_units": round(max(0.0, float(-period.loc[period["_quantity"] < 0, "_quantity"].sum())), 2),
    }
    metrics["average_order_value"] = float(
        (Decimal(metrics["net_sales_minor"]) / metrics["order_count"] / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ) if metrics["order_count"] else None
    return metrics


def _change_percent(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def compare_periods(
    df: pd.DataFrame,
    current_start: date | str | pd.Timestamp,
    current_end: date | str | pd.Timestamp,
    previous_start: date | str | pd.Timestamp,
    previous_end: date | str | pd.Timestamp,
) -> pd.DataFrame:
    """Compare two periods and return a reviewer-friendly metric table."""

    current = calculate_metrics(df, current_start, current_end)
    previous = calculate_metrics(df, previous_start, previous_end)
    keys = ("gross_sales", "reversal_amount", "net_sales", "order_count", "customer_count", "average_order_value", "units_sold", "reversed_units")
    rows = []
    for key in keys:
        current_value = current[key]
        previous_value = previous[key]
        if current_value is None or previous_value is None:
            delta = None
            change_percent = None
        else:
            if key + "_minor" in current:
                current_minor, previous_minor = current[key + "_minor"], previous[key + "_minor"]
                delta = (current_minor - previous_minor) / 100
                change_percent = _change_percent(current_minor, previous_minor)
            else:
                delta = round(current_value - previous_value, 2)
                change_percent = _change_percent(current_value, previous_value)
        rows.append({"metric": key, "current": current_value, "previous": previous_value, "delta": delta, "change_percent": change_percent})
    return pd.DataFrame(rows)


def product_contribution(
    df: pd.DataFrame,
    current_start: date | str | pd.Timestamp,
    current_end: date | str | pd.Timestamp,
    previous_start: date | str | pd.Timestamp,
    previous_end: date | str | pd.Timestamp,
    top_n: int | None = 10,
) -> pd.DataFrame:
    """Rank products by their contribution to the net-sales period change."""

    if top_n is not None and top_n < 1:
        raise ValueError("top_n must be positive")
    current = filter_period(df, current_start, current_end)
    previous = filter_period(df, previous_start, previous_end)
    current = _with_product_keys(current)
    previous = _with_product_keys(previous)
    current_values = current.groupby("product_key")["_line_amount_minor"].sum().rename("current_minor")
    previous_values = previous.groupby("product_key")["_line_amount_minor"].sum().rename("previous_minor")
    # Reindex with integer zero before joining, so missing products never
    # promote integer cents to floats (including amounts beyond 2**53).
    products = current_values.index.union(previous_values.index)
    result = pd.concat([current_values.reindex(products, fill_value=0),
                        previous_values.reindex(products, fill_value=0)], axis=1)
    result["delta_minor"] = result["current_minor"] - result["previous_minor"]
    for source, target in (("current_minor", "current_net_sales"), ("previous_minor", "previous_net_sales"), ("delta_minor", "delta")):
        result[target] = result[source].map(lambda value: int(value) / 100)
    total_delta = int(result["delta_minor"].sum())
    result["contribution_percent"] = result["delta_minor"].apply(
        lambda value: round(int(value) / total_delta * 100, 2) if total_delta else None
    )
    label_columns = ["product_key", "product"]
    labels = pd.concat([previous[label_columns], current[label_columns]]).drop_duplicates("product_key", keep="last").set_index("product_key")["product"]
    result = result.reset_index()
    result["product"] = result["product_key"].map(labels)
    ranked = result.assign(_abs_delta=result["delta_minor"].abs()).sort_values("_abs_delta", ascending=False, kind="stable").drop(columns="_abs_delta")
    return ranked if top_n is None else ranked.head(top_n)


def _with_product_keys(frame: pd.DataFrame) -> pd.DataFrame:
    if not any(column in frame for column in ("product_id", "product_name")):
        raise ValueError("商品贡献分析需要商品编号或商品名称")
    result = frame.copy()
    ids = result.get("product_id", pd.Series("", index=result.index)).fillna("").astype(str)
    names = result.get("product_name", pd.Series("", index=result.index)).fillna("").astype(str)
    result["product_key"] = ["id:" + pid if pid else "name:" + name if name else "missing:" for pid, name in zip(ids, names)]
    result["product"] = [name or pid or "(未填写)" for pid, name in zip(ids, names)]
    return result


def order_drilldown(
    df: pd.DataFrame,
    start: date | str | pd.Timestamp,
    end: date | str | pd.Timestamp,
    product: str | None = None,
) -> pd.DataFrame:
    """Return order-level evidence for a period and optional product filter."""

    result = filter_period(df, start, end)
    if product:
        result = _with_product_keys(result)
        keys = result["product_key"]
        matches = keys.eq(product)
        if not matches.any():
            matches = result["product"].eq(product)
            if "product_id" in result:
                matches |= result["product_id"].eq(product)
            if result.loc[matches, "product_key"].nunique() > 1:
                raise ValueError("商品名称对应多个编号，请使用贡献表中的 product_key 精确筛选")
        result = result.loc[matches]

    result["line_amount"] = result["_line_amount"]
    result["record_type"] = result["_line_amount"].apply(lambda value: "销售" if value >= 0 else "冲销")
    output_columns = [
        column for column in (
            "order_id", "product_id", "product_name", "quantity", "unit_price", "order_time", "customer_id", "country", "line_amount", "record_type"
        ) if column in result.columns
    ]
    return result.sort_values("_order_time")[output_columns]
