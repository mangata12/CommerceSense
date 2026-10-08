"""Measure the fixed calibration/validation queries against the current corpus."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rag_knowledge import default_knowledge_base


def measure():
    kb = default_knowledge_base()
    samples = json.loads((ROOT / "tests/fixtures/rule_queries.json").read_text(encoding="utf-8"))
    groups = {}
    for group, cases in samples.items():
        results = []
        for case in cases:
            scored = kb.scored_rules(case["query"])
            hits = kb.retrieve(case["query"])["hits"]
            expected_score = next((score for doc, score in scored if doc.metadata["rule_id"] == case["rule_id"]), None)
            passed = any(hit["rule_id"] == case["rule_id"] for hit in hits) if case["rule_id"] else not hits
            results.append({**case, "expected_rule_score": expected_score, "top_score": scored[0][1],
                            "matched_rule_ids": [hit["rule_id"] for hit in hits], "passed": passed})
        groups[group] = results
    calibration = groups["calibration"]
    max_negative = max(case["top_score"] for case in calibration if not case["rule_id"])
    min_positive = min(case["expected_rule_score"] for case in calibration if case["rule_id"])
    return {"threshold": kb.min_relevance, "rule_count": len(kb.documents),
            "corpus_sha256": hashlib.sha256("\n".join(doc.page_content for doc in kb.documents).encode()).hexdigest(),
            "calibration_max_negative": max_negative, "calibration_min_expected_positive": min_positive,
            "rounded_threshold_above_negative": math.ceil(max_negative * 100) / 100,
            "counts": {group: {"total": len(cases), "passed": sum(case["passed"] for case in cases)} for group, cases in groups.items()},
            "samples": groups}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = measure()
    if arguments.output:
        arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2))
    sys.exit(0 if all(count["total"] == count["passed"] for count in result["counts"].values()) else 1)
