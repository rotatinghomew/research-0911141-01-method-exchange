from collections import defaultdict
from statistics import mean
import math

from .validation import require_tables, unique, finite
from .comparison import compare


def validate(data):
    require_tables(data, ["measurements", "methods"])
    unique(data["measurements"], ["sample_id", "method", "replicate"])
    for row in data["measurements"]:
        if row["method"] not in data["methods"] or row["status"] not in {"measured", "below_limit"}:
            raise ValueError("测量方法或状态无效")
        finite(row["limit"], minimum=0)
        if row["status"] == "measured":
            finite(row["value"])
        elif row["value"] is not None:
            raise ValueError("低于检出限的记录不能包含精确读数")
    limits = data.get("limits")
    if limits is not None:
        if not isinstance(limits, dict):
            raise ValueError("容许误差 limits 必须是对象")
        for key in ("absolute", "relative"):
            if key in limits:
                finite(limits[key], minimum=0)
        if "relative" in limits and limits["relative"] > 1:
            raise ValueError("相对容许误差不应超过 1（即 100%）")


def explore(data, selection, policy=None):
    reference = selection.get("reference", "old")
    candidate = selection.get("candidate", "new_a")
    if reference == candidate or reference not in data["methods"] or candidate not in data["methods"]:
        raise ValueError("请选择两个不同的有效方法")
    grouped = defaultdict(list)
    censored = 0
    for measurement in data["measurements"]:
        if measurement["method"] not in {reference, candidate}:
            continue
        if measurement["status"] == "measured":
            grouped[(measurement["sample_id"], measurement["method"])].append(measurement["value"])
        else:
            censored += 1
    samples = sorted({key[0] for key in grouped})
    rows = []
    for sample in samples:
        left = grouped.get((sample, reference), [])
        right = grouped.get((sample, candidate), [])
        rows.append({"sample_id": sample, "reference_mean": mean(left) if left else None,
                     "candidate_mean": mean(right) if right else None,
                     "reference_n": len(left), "candidate_n": len(right),
                     "raw_difference": mean(right) - mean(left) if left and right else None})
    differences = [row["raw_difference"] for row in rows if row["raw_difference"] is not None]
    comparison = compare(data, selection, policy)
    return {"summary": {"可定量样品": len(rows), "有定量配对": len(differences), "检出限记录": censored},
            "rows": rows,
            "series": [{"label": row["sample_id"], "x": row["reference_mean"], "y": row["candidate_mean"]}
                       for row in rows if row["raw_difference"] is not None],
            "comparison": comparison,
            "notes": comparison["notes"]}
