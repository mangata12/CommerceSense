"""Utilities for loading and validating commerce order data."""

from __future__ import annotations

import re
import unicodedata
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
            return pd.read_csv(uploaded_file, encoding="utf-8-sig")
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding="gb18030")
    if filename.endswith((".xlsx", ".xls")):
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file)
    raise ValueError("Unsupported file format. Please upload CSV or Excel.")


def normalise_commerce_data(df: pd.DataFrame, mapping: Mapping[str, str]) -> pd.DataFrame:
    """Add canonical columns while retaining every original user column."""

    result = df.copy()
    for canonical, source in mapping.items():
        if source in result.columns and canonical not in result.columns:
            result[canonical] = result[source]
    return result


def validate_commerce_data(df: pd.DataFrame, mapping: Mapping[str, str]) -> dict:
    """Return deterministic data-quality facts for the commerce setup panel."""

    normalised = normalise_commerce_data(df, mapping)
    required = [field for field, _, is_required in COMMERCE_FIELDS if is_required]
    missing_required = [field for field in required if field not in normalised.columns]
    report = {
        "rows": int(len(normalised)),
        "columns": int(len(normalised.columns)),
        "mapped_fields": {field: source for field, source in mapping.items() if source in df.columns},
        "missing_required": missing_required,
        "unmapped_columns": [column for column in df.columns if column not in mapping.values()],
        "duplicate_rows": int(normalised.duplicated().sum()),
        "null_counts": {},
        "invalid_order_time": 0,
        "invalid_quantity": 0,
        "invalid_unit_price": 0,
        "negative_quantity": 0,
        "negative_unit_price": 0,
    }
    for field in mapping:
        if field in normalised.columns:
            report["null_counts"][field] = int(normalised[field].isna().sum())
    if "order_time" in normalised.columns:
        report["invalid_order_time"] = int(pd.to_datetime(normalised["order_time"], errors="coerce").isna().sum())
    if "quantity" in normalised.columns:
        quantity = pd.to_numeric(normalised["quantity"], errors="coerce")
        report["invalid_quantity"] = int(quantity.isna().sum())
        report["negative_quantity"] = int((quantity < 0).sum())
    if "unit_price" in normalised.columns:
        unit_price = pd.to_numeric(normalised["unit_price"], errors="coerce")
        report["invalid_unit_price"] = int(unit_price.isna().sum())
        report["negative_unit_price"] = int((unit_price < 0).sum())
    return report

