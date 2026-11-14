"""方法替换决策所需的比较口径。

只用 Python 标准库。参考方法被视为同样带有测量误差的观测，不默认真值：
斜率与截距采用 Deming 回归，误差方差比 lambda 由同一样品的复测方差估计。
低于检出限的记录只携带 limit 信息，绝不按零值参与定量计算；证据不足的
量程区间显式标记，不向外推断。
"""
from collections import defaultdict
from statistics import mean, median
import math

BIN_COUNT = 6
MIN_BIN_SAMPLES = 3
LOA_FACTOR = 1.96


def _number(value):
    """统一输出口径：有限数保留四位小数，避免 -0.0 与 NaN 进入 JSON。"""
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    rounded = round(float(value), 4)
    return rounded + 0.0


def normalize_policy(raw, data):
    """校验并补全业务容许误差约定。

    容许误差 TEa(x) = absolute + relative * |x|。raw 为页面提交内容，
    缺省时回退到数据自带的 limits，再缺省使用 0/0（即只做描述不做判定）。
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("容许误差约定必须是对象")
    limits = data.get("limits") if isinstance(data, dict) else None
    limits = limits if isinstance(limits, dict) else {}

    def pick(key, fallback):
        if key in raw and raw[key] is not None:
            return raw[key]
        return fallback

    absolute = pick("absolute", limits.get("absolute", 0))
    relative = pick("relative", limits.get("relative", 0))
    if isinstance(absolute, bool) or not isinstance(absolute, (int, float)) or not math.isfinite(absolute):
        raise ValueError("绝对容许误差应为有限数字")
    if isinstance(relative, bool) or not isinstance(relative, (int, float)) or not math.isfinite(relative):
        raise ValueError("相对容许误差应为有限数字")
    if absolute < 0 or relative < 0:
        raise ValueError("容许误差不能为负数")
    if relative > 1:
        raise ValueError("相对容许误差不应超过 1（即 100%）")
    if absolute == 0 and relative == 0:
        verdict_enabled = False
    else:
        verdict_enabled = True
    return {
        "absolute": _number(absolute),
        "relative": _number(relative),
        "verdict_enabled": verdict_enabled,
        "formula": "TEa(x) = absolute + relative × |x|，x 取参考方法可定量均值",
    }


def _build_samples(data, reference, candidate):
    """按样品汇总两个方法的复测，保留检出限与环境信息，不丢弃任何记录。"""
    methods = {reference, candidate}
    grouped = defaultdict(lambda: {method: {"values": [], "censored": [], "limits": [],
                                            "labs": set(), "lots": set()} for method in methods})
    for row in data["measurements"]:
        if row["method"] not in methods:
            continue
        sample = grouped[row["sample_id"]][row["method"]]
        sample["labs"].add(row.get("laboratory") or "未标注")
        sample["lots"].add(row.get("lot") or "未标注")
        if row["status"] == "below_limit":
            sample["censored"].append(row["replicate"])
            sample["limits"].append(row["limit"])
        else:
            sample["values"].append(row["value"])

    samples = []
    for sample_id in sorted(grouped):
        entry = {"sample_id": sample_id}
        observed_methods = set()
        for method, label in ((reference, "reference"), (candidate, "candidate")):
            record = grouped[sample_id][method]
            values = sorted(record["values"])
            entry[label + "_values"] = values
            entry[label + "_censored_replicates"] = sorted(record["censored"])
            entry[label + "_limit"] = _number(max(record["limits"])) if record["limits"] else None
            entry[label + "_n"] = len(values)
            entry[label + "_mean"] = _number(mean(values)) if values else None
            entry[label + "_sd"] = _number(_sample_sd(values)) if len(values) >= 2 else None
            entry[label + "_labs"] = sorted(record["labs"])
            entry[label + "_lots"] = sorted(record["lots"])
            if values or record["censored"]:
                observed_methods.add(method)
        ref_values = entry["reference_values"]
        cand_values = entry["candidate_values"]
        ref_censored = entry["reference_censored_replicates"]
        cand_censored = entry["candidate_censored_replicates"]
        if ref_values and cand_values:
            entry["pair_status"] = "partial_censored" if (ref_censored or cand_censored) else "quantitative"
            entry["difference"] = _number(mean(cand_values) - mean(ref_values))
        elif ref_values or cand_values:
            entry["pair_status"] = "one_sided_censored"
            entry["difference"] = None
        elif observed_methods:
            entry["pair_status"] = "fully_censored"
            entry["difference"] = None
        else:
            continue
        entry["observed_methods"] = sorted(observed_methods)
        entry["laboratories"] = sorted(set(entry["reference_labs"]) | set(entry["candidate_labs"]))
        entry["lots"] = sorted(set(entry["reference_lots"]) | set(entry["candidate_lots"]))
        samples.append(entry)
    return samples


def _sample_sd(values):
    if len(values) < 2:
        return None
    average = mean(values)
    return math.sqrt(sum((value - average) ** 2 for value in values) / (len(values) - 1))


def _repeatability(data, method):
    """合并样品内复测方差（pooled within-sample variance）。"""
    per_sample = defaultdict(list)
    for row in data["measurements"]:
        if row["method"] == method and row["status"] == "measured":
            per_sample[row["sample_id"]].append(row["value"])
    sum_squares = 0.0
    degrees = 0
    sample_count = 0
    for values in per_sample.values():
        if len(values) >= 2:
            average = mean(values)
            sum_squares += sum((value - average) ** 2 for value in values)
            degrees += len(values) - 1
            sample_count += 1
    if degrees == 0:
        return {"method": method, "variance": None, "sd": None, "degrees_of_freedom": 0,
                "replicated_samples": sample_count, "note": "该方法没有同样品复测，无法估计重复性方差"}
    variance = sum_squares / degrees
    return {"method": method, "variance": _number(variance), "sd": _number(math.sqrt(variance)),
            "degrees_of_freedom": degrees, "replicated_samples": sample_count, "note": None}


def _deming(points, repeatability):
    """Deming 回归：min 同时考虑 x、y 方向误差，lambda = 参考方差/候选方差。"""
    if len(points) < 2:
        return {"n": len(points), "slope": None, "intercept": None, "lambda": None,
                "bias_trend": [], "note": "可定量配对少于 2 个，无法拟合 Deming 回归"}
    ref_variance = repeatability["reference"]["variance"]
    cand_variance = repeatability["candidate"]["variance"]
    fallback_note = None
    if ref_variance and cand_variance and cand_variance > 0:
        lam = ref_variance / cand_variance
    else:
        lam = 1.0
        fallback_note = "缺少可用复测方差，lambda 暂取 1（等同等方差假设），结论仅作描述"
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_bar, y_bar = mean(xs), mean(ys)
    sxx = sum((x - x_bar) ** 2 for x in xs) / len(points)
    syy = sum((y - y_bar) ** 2 for y in ys) / len(points)
    sxy = sum((x - x_bar) * (y - y_bar) for x, y in points) / len(points)
    if abs(sxy) < 1e-12:
        return {"n": len(points), "slope": None, "intercept": None, "lambda": _number(lam),
                "bias_trend": [], "note": "配对协方差为零，Deming 回归不可识别，该区间不给出斜率结论"}
    discriminant = (syy - lam * sxx) ** 2 + 4 * lam * sxy ** 2
    slope = (syy - lam * sxx + math.sqrt(discriminant)) / (2 * sxy)
    intercept = y_bar - slope * x_bar
    ordered = sorted(points, key=lambda point: point[0])
    anchors = ordered[:1] + [ordered[len(ordered) // 2]] + ordered[-1:]
    trend = []
    for x, _ in anchors:
        predicted = intercept + slope * x
        trend.append({"x": _number(x), "predicted_candidate": _number(predicted),
                      "bias": _number(predicted - x),
                      "relative_bias": _number((predicted - x) / x) if x else None})
    return {"n": len(points), "slope": _number(slope), "intercept": _number(intercept),
            "lambda": _number(lam), "bias_trend": trend, "note": fallback_note}


def _bland_altman(points):
    """差值的描述性界限；它不是业务容许误差，也不假设参考方法无误差。"""
    diffs = [y - x for x, y in points]
    if not diffs:
        return {"n": 0, "mean_bias": None, "sd_bias": None, "loa_lower": None, "loa_upper": None,
                "note": "没有可定量配对，无法描述差值分布"}
    bias = mean(diffs)
    result = {"n": len(diffs), "mean_bias": _number(bias), "sd_bias": None,
              "loa_lower": None, "loa_upper": None, "note": None}
    if len(diffs) >= 2:
        sd = _sample_sd(diffs)
        result["sd_bias"] = _number(sd)
        result["loa_lower"] = _number(bias - LOA_FACTOR * sd)
        result["loa_upper"] = _number(bias + LOA_FACTOR * sd)
        result["note"] = "一致性界限为 mean ± 1.96 SD 的描述区间，不等于业务容许误差"
    else:
        result["note"] = "仅 1 个配对，无法估计差值标准差与一致性界限"
    return result


def _tolerance_at(policy, x):
    return policy["absolute"] + policy["relative"] * abs(x)


def _profile(samples, policy):
    """按参考方法量程等宽分箱，逐箱判定容许误差，证据不足保持空白结论。"""
    pairs = [sample for sample in samples if sample["pair_status"] in ("quantitative", "partial_censored")]
    if not pairs:
        return {"bins": [], "applicable_ranges": [], "restricted_bins": [], "insufficient_bins": [],
                "evidence_range": None, "note": "没有可定量配对，无法给定量程适用结论"}
    x_min = min(sample["reference_mean"] for sample in pairs)
    x_max = max(sample["reference_mean"] for sample in pairs)
    span = (x_max - x_min) / BIN_COUNT
    edges = [x_min + index * span for index in range(BIN_COUNT + 1)]
    bins = []
    for index in range(BIN_COUNT):
        low, high = edges[index], edges[index + 1]
        members = [sample for sample in pairs
                   if (sample["reference_mean"] >= low and sample["reference_mean"] < high)
                   or (index == BIN_COUNT - 1 and sample["reference_mean"] == high)]
        diffs = [sample["difference"] for sample in members]
        tea_center = _tolerance_at(policy, (low + high) / 2)
        exceeding, within = [], []
        for sample in members:
            if policy["verdict_enabled"] and abs(sample["difference"]) <= _tolerance_at(
                    policy, sample["reference_mean"]) + 1e-12:
                within.append(sample["sample_id"])
            else:
                exceeding.append(sample["sample_id"])
        if not members:
            status = "区间无证据"
        elif len(members) < MIN_BIN_SAMPLES:
            status = "证据不足"
        elif not policy["verdict_enabled"]:
            status = "仅描述（未设定容许误差）"
        elif exceeding:
            status = "超限"
        else:
            status = "合格"
        bins.append({
            "index": index, "range_low": _number(low), "range_high": _number(high),
            "n_pairs": len(members), "sample_ids": [sample["sample_id"] for sample in members],
            "mean_bias": _number(mean(diffs)) if diffs else None,
            "median_abs_bias": _number(median(abs(diff) for diff in diffs)) if diffs else None,
            "max_abs_bias": _number(max(abs(diff) for diff in diffs)) if diffs else None,
            "tolerance_at_center": _number(tea_center),
            "within_tolerance_samples": within, "exceeding_samples": exceeding,
            "evaluable": bool(members) and len(members) >= MIN_BIN_SAMPLES and policy["verdict_enabled"],
            "status": status,
        })
    applicable, restricted, insufficient = [], [], []
    run = []
    for bin_entry in bins:
        if bin_entry["status"] == "合格":
            run.append(bin_entry)
            continue
        if run:
            applicable.append(_merge_bins(run))
            run = []
        if bin_entry["status"] == "超限":
            restricted.append({"range_low": bin_entry["range_low"], "range_high": bin_entry["range_high"],
                               "sample_ids": bin_entry["sample_ids"],
                               "exceeding_samples": bin_entry["exceeding_samples"]})
        else:
            insufficient.append({"range_low": bin_entry["range_low"], "range_high": bin_entry["range_high"],
                                 "status": bin_entry["status"], "n_pairs": bin_entry["n_pairs"],
                                 "sample_ids": bin_entry["sample_ids"]})
    if run:
        applicable.append(_merge_bins(run))
    return {"bins": bins, "applicable_ranges": applicable, "restricted_bins": restricted,
            "insufficient_bins": insufficient,
            "evidence_range": {"low": _number(x_min), "high": _number(x_max)},
            "note": "结论仅覆盖观测量程；证据不足与超出观测范围的区间不给出互换结论"}


def _merge_bins(run):
    return {"range_low": run[0]["range_low"], "range_high": run[-1]["range_high"],
            "n_pairs": sum(bin_entry["n_pairs"] for bin_entry in run),
            "sample_ids": [identifier for bin_entry in run for identifier in bin_entry["sample_ids"]]}


def _groups(samples, dimension):
    """实验室或试剂批次层面的偏差分布与单方法覆盖提示。"""
    grouped = defaultdict(list)
    methods_seen = defaultdict(set)
    label = "laboratories" if dimension == "laboratory" else "lots"
    for sample in samples:
        for name in sample[label]:
            grouped[name].append(sample)
            methods_seen[name].update(sample["observed_methods"])
    result = []
    for name in sorted(grouped):
        members = grouped[name]
        pairs = [sample for sample in members
                 if sample["pair_status"] in ("quantitative", "partial_censored")]
        diffs = [sample["difference"] for sample in pairs]
        result.append({
            "name": name, "dimension": dimension,
            "methods_measured": sorted(methods_seen[name]),
            "only_one_method": len(methods_seen[name]) < 2,
            "n_samples": len(members), "n_pairs": len(pairs),
            "sample_ids": [sample["sample_id"] for sample in members],
            "mean_bias": _number(mean(diffs)) if diffs else None,
            "max_abs_bias": _number(max(abs(diff) for diff in diffs)) if diffs else None,
        })
    return result


def compare(data, selection, policy=None):
    reference = selection.get("reference", "old")
    candidate = selection.get("candidate", "new_a")
    if reference == candidate or reference not in data["methods"] or candidate not in data["methods"]:
        raise ValueError("请选择两个不同的有效方法")
    policy = normalize_policy(policy, data)
    samples = _build_samples(data, reference, candidate)
    pairs = [sample for sample in samples
             if sample["pair_status"] in ("quantitative", "partial_censored")]
    points = [(sample["reference_mean"], sample["candidate_mean"]) for sample in pairs]
    repeatability = {"reference": _repeatability(data, reference),
                     "candidate": _repeatability(data, candidate)}
    deming = _deming(points, repeatability)
    bland_altman = _bland_altman(points)
    profile = _profile(samples, policy)

    for sample in pairs:
        tea = _tolerance_at(policy, sample["reference_mean"])
        sample["tolerance"] = _number(tea)
        sample["within_tolerance"] = (bool(policy["verdict_enabled"])
                                      and abs(sample["difference"]) <= tea + 1e-12)

    fully_censored = [{"sample_id": sample["sample_id"],
                       "reference_limit": sample["reference_limit"],
                       "candidate_limit": sample["candidate_limit"]}
                      for sample in samples if sample["pair_status"] == "fully_censored"]
    one_sided = [{"sample_id": sample["sample_id"],
                  "censored_method": reference if not sample["reference_n"] else candidate,
                  "quantitative_method": candidate if not sample["reference_n"] else reference,
                  "quantitative_mean": (sample["candidate_mean"] if not sample["reference_n"]
                                        else sample["reference_mean"]),
                  "limit": sample["reference_limit"] if not sample["reference_n"]
                  else sample["candidate_limit"]}
                 for sample in samples if sample["pair_status"] == "one_sided_censored"]
    single_method = [{"sample_id": sample["sample_id"],
                      "methods": sample["observed_methods"]}
                     for sample in samples if len(sample["observed_methods"]) == 1
                     and sample["pair_status"] != "one_sided_censored"]

    notes = [
        "参考方法与候选方法都被视为带测量误差的观测，参考读数不默认真值；斜率与截距由 Deming 回归估计。",
        "低于检出限的记录只保留 limit 信息，未按零值参与均值、回归或容许误差判定。",
        profile["note"],
        bland_altman["note"],
    ]
    if deming["note"]:
        notes.append("Deming 回归：" + deming["note"])
    if any(sample["pair_status"] == "partial_censored" for sample in pairs):
        notes.append("部分配对含低于检出限的复测，其差值只基于可定量复测，已在样品明细中标注。")
    if fully_censored:
        notes.append("有 %d 个样品两方法均低于检出限，量程下端的互换性没有定量证据。" % len(fully_censored))
    if one_sided:
        notes.append("有 %d 个样品仅一侧可定量，不能形成配对差值。" % len(one_sided))
    if single_method:
        notes.append("有 %d 个样品只测过一种方法，只能从原始记录核对，不参与比较结论。" % len(single_method))
    if not policy["verdict_enabled"]:
        notes.append("当前绝对与相对容许误差均为 0，页面只展示描述统计，不输出合格/超限判定。")

    coverage = {
        "quantitative_pairs": len(pairs),
        "partial_censored_pairs": sum(1 for sample in pairs
                                      if sample["pair_status"] == "partial_censored"),
        "fully_censored_pairs": len(fully_censored),
        "one_sided_censored_pairs": len(one_sided),
        "single_method_samples": len(single_method),
        "observed_reference_range": profile["evidence_range"],
    }
    return {
        "policy": policy,
        "reference": reference,
        "candidate": candidate,
        "coverage": coverage,
        "samples": samples,
        "repeatability": repeatability,
        "deming": deming,
        "bland_altman": bland_altman,
        "profile": profile,
        "lab_groups": _groups(samples, "laboratory"),
        "lot_groups": _groups(samples, "lot"),
        "fully_censored_samples": fully_censored,
        "one_sided_censored_samples": one_sided,
        "single_method_samples": single_method,
        "notes": [note for note in notes if note],
    }
