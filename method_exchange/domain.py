from collections import Counter, defaultdict
from statistics import mean, median
import math

from .validation import require_tables, unique, finite, references


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


def explore(data, selection):
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
    return {"summary": {"可定量样品": len(rows), "有定量配对": len(differences), "检出限记录": censored},
            "rows": rows, "series": [{"label": row["sample_id"], "x": row["reference_mean"], "y": row["candidate_mean"]}
                                      for row in rows if row["raw_difference"] is not None],
            "notes": ["配对均值是原始读数描述，不代表方法互换性或一致性界限。", "没有精确读数的样品仍可从原始记录中核对。"]}
