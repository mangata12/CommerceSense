"""Utilities for loading and validating commerce order data."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import BinaryIO, Mapping

import pandas as pd


COMMERCE_FIELDS = (
    ("order_id", "订单号", True),
    ("product_id", "商品编号", False),
    ("product_name", "商品名称", False),
    ("quantity", "数量", True),
    ("unit_price", "单价", True),
    ("order_time", "订单时间", True),
    ("customer_id", "客户编号", False),
    ("country", "地区", False),
)

FIELD_ALIASES = {
    "order_id": ("order_id", "orderid", "订单号", "订单编号", "交易号", "发票号", "invoiceno", "invoice_no", "transaction_id"),
    "product_id": ("product_id", "productid", "商品编号", "商品id", "货号", "stockcode", "stock_code", "sku"),
    "product_name": ("product_name", "productname", "商品名称", "商品名", "品名", "description", "product"),
    "quantity": ("quantity", "qty", "数量", "购买数量", "件数"),
    "unit_price": ("unit_price", "unitprice", "单价", "商品单价", "价格", "price"),
    "order_time": ("order_time", "ordertime", "订单时间", "下单时间", "交易时间", "日期", "invoicedate", "invoice_date", "date"),
    "customer_id": ("customer_id", "customerid", "客户编号", "客户id", "会员号", "customer"),
    "country": ("country", "地区", "国家", "区域", "region"),
}


def _normalise_column_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def infer_field_mapping(columns: list[object] | tuple[object, ...]) -> dict[str, str]:
    """Infer canonical commerce fields from common Chinese/English headers."""

    columns = [str(column) for column in columns]
    normalised_columns = {_normalise_column_name(column): column for column in columns}
    mapping: dict[str, str] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in (_normalise_column_name(item) for item in aliases):
            if alias in normalised_columns:
                mapping[canonical] = normalised_columns[alias]
                break
    return mapping


def load_commerce_file(uploaded_file: BinaryIO) -> pd.DataFrame:
    """Load CSV/XLSX input with a small encoding fallback for Chinese CSVs."""

    filename = str(getattr(uploaded_file, "name", "")).lower()
    if filename.endswith(".csv"):
        try:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding="gb18030", dtype=str, keep_default_na=False)
    if filename.endswith(".xlsx"):
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file, dtype=str, keep_default_na=False)
    raise ValueError("仅支持 CSV 或 XLSX；旧版 XLS 请先另存为 XLSX。")


def normalise_commerce_data(df: pd.DataFrame, mapping: Mapping[str, str]) -> pd.DataFrame:
    """Rebuild canonical columns from raw sources; keep noncanonical columns."""

    # Read sources from the original snapshot, including when names collide.
    result = df.drop(columns=[field for field, _, _ in COMMERCE_FIELDS], errors="ignore").copy()
    for canonical, source in mapping.items():
        if source in df.columns:
            result[canonical] = df[source].copy()
    return result


def _identifier(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _decimal(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value).strip())
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def parse_order_time(value: object) -> pd.Timestamp:
    """Accept local wall-clock dates; never silently guess a timezone or epoch."""
    if pd.isna(value) or isinstance(value, (int, float)):
        return pd.NaT
    try:
        timestamp = pd.Timestamp(value)
        return timestamp.as_unit("ns") if timestamp.tzinfo is None else pd.NaT
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def parse_commerce_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Annotate every row; invalid rows remain available for quality inspection."""
    result = df.copy().reset_index(drop=True)
    for field in ("order_id", "product_id", "product_name", "customer_id"):
        if field in result:
            result[field] = result[field].map(_identifier)
    times = result.get("order_time", pd.Series([None] * len(result))).map(parse_order_time)
    quantities = result.get("quantity", pd.Series([None] * len(result))).map(_decimal)
    prices = result.get("unit_price", pd.Series([None] * len(result))).map(_decimal)
    order_ids = result.get("order_id", pd.Series("", index=result.index))
    reasons, amounts = [], []
    for index, (quantity, price, timestamp) in enumerate(zip(quantities, prices, times)):
        errors = []
        if not order_ids.iloc[index]:
            errors.append("empty_order_id")
        if pd.isna(timestamp):
            errors.append("invalid_order_time")
        if quantity is None:
            errors.append("invalid_quantity")
        if price is None:
            errors.append("invalid_unit_price")
        elif price < 0:
            errors.append("negative_unit_price")
        elif price * 100 != (price * 100).to_integral_value():
            errors.append("price_precision")
        minor = quantity * price * 100 if quantity is not None and price is not None else None
        if minor is not None and minor != minor.to_integral_value():
            errors.append("amount_precision")
        reasons.append(";".join(errors))
        amounts.append(int(minor) if minor is not None and not errors else 0)
    result["_order_time"] = pd.to_datetime(times, errors="coerce")
    result["_quantity"] = quantities
    result["_unit_price"] = prices
    # Python integers avoid fixed-width overflow when large datasets are summed.
    result["_line_amount_minor"] = pd.Series(amounts, dtype=object)
    result["_line_amount"] = [amount / 100 for amount in amounts]
    result["_exclusion_reason"] = pd.Series(reasons, dtype=str)
    result["_valid_metric_row"] = pd.Series([not reason for reason in reasons], dtype=bool)
    result["_source_row"] = range(2, len(result) + 2)
    return result


def prepare_commerce_data(df: pd.DataFrame, mapping: Mapping[str, str], currency: str) -> dict:
    """Single input contract for metrics, Agent, charts and future reports."""
    if currency not in {"CNY", "GBP", "USD", "EUR"}:
        raise ValueError("请明确选择币种：CNY、GBP、USD 或 EUR")
    normalised = normalise_commerce_data(df, mapping)
    missing = [field for field, _, required in COMMERCE_FIELDS if required and field not in normalised]
    parsed = parse_commerce_rows(normalised)
    quality = {
        "rows": len(df), "columns": len(normalised.columns),
        "mapped_fields": {field: source for field, source in mapping.items() if source in df},
        "missing_required": missing,
        "missing_product": not any(field in normalised for field in ("product_id", "product_name")),
        "duplicate_rows": int(df.duplicated().sum()),
        "valid_rows": int(parsed["_valid_metric_row"].sum()) if not missing else 0,
        "excluded_rows": int((~parsed["_valid_metric_row"]).sum()) if not missing else len(df),
        "exclusion_counts": {},
        "currency": currency,
    }
    for reason in ("empty_order_id", "invalid_order_time", "invalid_quantity", "invalid_unit_price",
                   "negative_unit_price", "price_precision", "amount_precision"):
        quality[reason] = int(parsed["_exclusion_reason"].str.split(";").map(lambda items: reason in items).sum())
        quality["exclusion_counts"][reason] = quality[reason]
    quality["negative_quantity"] = int(parsed["_quantity"].map(lambda value: value is not None and value < 0).sum())
    valid = parsed.loc[parsed["_valid_metric_row"]].copy() if not missing else parsed.iloc[:0].copy()
    data = valid[list(normalised.columns)].copy()
    if "order_time" in data:
        data["order_time"] = valid["_order_time"]
    for field in ("quantity", "unit_price"):
        if field in data:
            data[field] = valid["_" + field]
    data.attrs["currency"] = currency
    return {"data": data.reset_index(drop=True), "mapping": dict(mapping), "quality": quality,
            "excluded": parsed.loc[~parsed["_valid_metric_row"]].copy()}


def validate_commerce_data(df: pd.DataFrame, mapping: Mapping[str, str]) -> dict:
    """Compatibility wrapper; validation itself does not convert currencies."""
    return prepare_commerce_data(df, mapping, "CNY")["quality"]
