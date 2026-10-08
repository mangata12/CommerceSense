"""Export only the public simulated example; no credentials or model required."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from commerce_session import load_dataset, apply_dataset_mapping
from commerce_diagnosis import run_diagnosis
from commerce_report import build_report_bundle


def demo_diagnosis():
    state = {}
    with (ROOT / "data/examples/commerce_orders_demo.csv").open("rb") as uploaded:
        load_dataset(state, uploaded)
    data = apply_dataset_mapping(state, state["commerce_mapping"], "CNY")["data"]
    return run_diagnosis(data, ("2026-09-08", "2026-09-09"), ("2026-09-01", "2026-09-02"),
                         state["commerce_quality"], dataset_name="公开模拟订单（CNY）")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/demo_report")
    args = parser.parse_args()
    result = demo_diagnosis()
    bundle = build_report_bundle(result)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = {"report.md": bundle.markdown.encode("utf-8"),
             "metrics_comparison.csv": bundle.metrics_csv, "product_contribution.csv": bundle.products_csv,
             "order_evidence.csv": bundle.evidence_csv, "daily_net_sales.csv": bundle.trend_csv,
             "report.zip": bundle.zip_bytes, **bundle.charts}
    for filename, content in files.items():
        target = args.output_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    print(json.dumps({"output": str(args.output_dir.resolve()), "currency": result.currency,
                      "current_net_sales_minor": result.current["net_sales_minor"],
                      "previous_net_sales_minor": result.previous["net_sales_minor"],
                      "delta_minor": result.delta_minor, "products": len(result.products),
                      "evidence_rows": len(result.evidence), "rule_sources": len(result.rule_sources)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
