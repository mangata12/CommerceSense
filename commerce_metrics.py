"""Deterministic commerce metrics used by the UI and future LangChain tools."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


REQUIRED_METRIC_COLUMNS = ("order_id", "quantity", "unit_price", "order_time")


def prepare_metrics_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Parse canonical columns and add a line-level amount without dropping rows."""

    missing = [column for column in REQUIRED_METRIC_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError("Missing canonical commerce columns: " + ", ".join(missing))

    result = df.copy()
    result["_order_time"] = pd.to_datetime(result["order_time"], errors="coerce")
    result["_quantity"] = pd.to_numeric(result["quantity"], errors="coerce")
    result["_unit_price"] = pd.to_numeric(result["unit_price"], errors="coerce")
    result["_line_amount"] = (result["_quantity"] * result["_unit_price"]).round(2)
    result["_valid_metric_row"] = result[list(("_order_time", "_quantity", "_unit_price"))].notna().all(axis=1)
    return result


def filter_period(df: pd.DataFrame, start: date | str | pd.Timestamp, end: date | str | pd.Timestamp) -> pd.DataFrame:
    """Filter a date range with inclusive start and inclusive end semantics."""

    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize() + pd.Timedelta(days=1)
    if end_ts <= start_ts:
        raise ValueError("Period end must be on or after period start")

    prepared = prepare_metrics_frame(df)
    mask = prepared["_valid_metric_row"] & (prepared["_order_time"] >= start_ts) & (prepared["_order_time"] < end_ts)
    return prepared.loc[mask].copy()


def calculate_metrics(df: pd.DataFrame, start: date | str | pd.Timestamp, end: date | str | pd.Timestamp) -> dict[str, Any]:
    """Calculate sales metrics for one inclusive date range."""

    period = filter_period(df, start, end)
    amounts = period["_line_amount"]
    positive = amounts[amounts > 0]
    negative = amounts[amounts < 0]
    order_ids = period["order_id"].dropna()
    customers = period["customer_id"].dropna() if "customer_id" in period.columns else pd.Series(dtype=object)
    metrics = {
        "start": str(pd.Timestamp(start).date()),
        "end": str(pd.Timestamp(end).date()),
        "row_count": int(len(period)),
        "order_count": int(order_ids.nunique()),
        "customer_count": int(customers.nunique()),
        "gross_sales": round(float(positive.sum()), 2),
        "reversal_amount": round(max(0.0, float(-negative.sum())), 2),
        "net_sales": round(float(amounts.sum()), 2),
        "units_sold": round(float(period.loc[period["_quantity"] > 0, "_quantity"].sum()), 2),
        "reversed_units": round(max(0.0, float(-period.loc[period["_quantity"] < 0, "_quantity"].sum())), 2),
    }
    metrics["average_order_value"] = round(
        metrics["net_sales"] / metrics["order_count"], 2
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
    top_n: int = 10,
) -> pd.DataFrame:
    """Rank products by their contribution to the net-sales period change."""

    if top_n < 1:
        raise ValueError("top_n must be positive")
    current = filter_period(df, current_start, current_end)
    previous = filter_period(df, previous_start, previous_end)
    product_column = "product_name" if "product_name" in df.columns else "product_id"
    if product_column not in df.columns:
        product_column = "order_id"

    current_values = current.groupby(product_column, dropna=False)["_line_amount"].sum().rename("current_net_sales")
    previous_values = previous.groupby(product_column, dropna=False)["_line_amount"].sum().rename("previous_net_sales")
    result = pd.concat([current_values, previous_values], axis=1).fillna(0)
    result["delta"] = (result["current_net_sales"] - result["previous_net_sales"]).round(2)
    total_delta = float(result["delta"].sum())
    result["contribution_percent"] = result["delta"].apply(
        lambda value: round(float(value) / total_delta * 100, 2) if total_delta else None
    )
    result = result.reset_index().rename(columns={product_column: "product"})
    result["product"] = result["product"].fillna("(未填写)").astype(str)
    return result.assign(_abs_delta=result["delta"].abs()).sort_values("_abs_delta", ascending=False).drop(columns="_abs_delta").head(top_n)


def order_drilldown(
    df: pd.DataFrame,
    start: date | str | pd.Timestamp,
    end: date | str | pd.Timestamp,
    product: str | None = None,
) -> pd.DataFrame:
    """Return order-level evidence for a period and optional product filter."""

    result = filter_period(df, start, end)
    if product:
        product_columns = [column for column in ("product_name", "product_id") if column in result.columns]
        if product_columns:
            mask = result[product_columns].astype(str).apply(lambda column: column.str.contains(product, case=False, na=False)).any(axis=1)
            result = result.loc[mask]

    result["line_amount"] = result["_line_amount"]
    result["record_type"] = result["_line_amount"].apply(lambda value: "销售" if value >= 0 else "冲销")
    output_columns = [
        column for column in (
            "order_id", "product_id", "product_name", "quantity", "unit_price", "order_time", "customer_id", "country", "line_amount", "record_type"
        ) if column in result.columns
    ]
    return result[output_columns].sort_values("order_time")
