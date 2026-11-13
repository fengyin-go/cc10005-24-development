"""样本血缘规则引擎。

这里集中放三件事，保证「采集 -> 字段映射 -> 数据清洗 -> 结果校验 -> 最终存储」
全链路的处理逻辑只有一份口径：

1. 规范化 JSON 与处理段指纹：跨批次续做时靠指纹判断某段是否已经追加过，
   重复执行不会产生重复处理段；
2. 原始规则函数：当前真正交付给存储的在效版本（EXTR-0001 v3 等）；
3. 候选规则函数：只服务于重演实验，函数全部是纯函数，不碰任何已交付证据。

引擎的输入输出都是普通 dict，便于在处理段里原样快照保存 input_value /
output_value，逆向排查时能逐段看到「进入时是什么、出来时变成什么」。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Callable

# 全链路固定阶段顺序，血缘时间线和续做断点都按这个顺序推导。
STAGES = ["collect", "extract", "cleanse", "validate", "storage"]
STAGE_NAMES = {
    "collect": "网页采集",
    "extract": "字段映射",
    "cleanse": "数据清洗",
    "validate": "结果校验",
    "storage": "最终存储",
}

# 当前在效、真正交付给存储的规则版本。重演时默认仍走这套规则，
# 只有用户选中的候选阶段才替换。
ORIGINAL_RULE_IDS = {
    "collect": ("COLLECT-RAW", "v1"),
    "extract": ("EXTR-0001", "v3"),
    "cleanse": ("CLEA-0001", "v2"),
    "validate": ("VALI-0001", "v4"),
    "storage": ("STOR-0001", "v2"),
}


def canonical_json(value: Any) -> str:
    """把任意快照值序列化为稳定字符串，排序键后同值必然同串。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def segment_fingerprint(
    sample_code: str,
    stage: str,
    rule_id: str,
    rule_version: str,
    batch_id: str,
    input_value: Any,
) -> str:
    """处理段幂等键。

    同一样本、同一阶段、同一规则版本、同一批次、同一份输入快照，算出来的指纹
    永远相同。续做时先查指纹，已存在就跳过追加，断点前的证据也不会被重写。
    """
    raw = canonical_json({
        "sample": sample_code,
        "stage": stage,
        "rule_id": rule_id,
        "rule_version": rule_version,
        "batch": batch_id,
        "input": input_value,
    })
    return "FP-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class RuleResult:
    """单条规则执行结果：输出快照 + 给人看的处理说明 + 校验/隔离状态。"""

    def __init__(
        self,
        record: dict[str, Any],
        note: str,
        *,
        status: str = "ok",
        reasons: list[str] | None = None,
    ) -> None:
        self.record = record
        self.note = note
        self.status = status
        self.reasons = reasons or []


# ---------------------------------------------------------------------------
# 原始规则：与已交付血缘里记录的 rule_id / rule_version 一一对应
# ---------------------------------------------------------------------------

def collect_original(record: dict[str, Any]) -> RuleResult:
    """采集段只做原始网页片段的结构化落地，不改写任何值。"""
    return RuleResult(copy.deepcopy(record), "保存原始网页片段与抓取上下文，不做改写")


def extract_original(record: dict[str, Any]) -> RuleResult:
    """EXTR-0001 v3：抽取标题并去首尾空白；价格只认连续数字与小数点。"""
    title = str(record.get("raw_title") or "").strip()
    price_text = str(record.get("price_text") or "")
    match = re.search(r"\d+(?:\.\d+)?", price_text.replace(",", ""))
    if match:
        price: float | None = round(float(match.group(0)), 2)
        note = f"正则提取价格 {price_text!r} -> {price}"
    else:
        price = None
        note = f"未在 {price_text!r} 中匹配到数字价格，price 置空"
    # 映射段只输出目标字段，raw_* 源字段留在采集/映射输入快照里可回溯。
    out = {"title": title, "price": price, "sku": str(record.get("raw_sku") or "").strip()}
    return RuleResult(out, note)


def cleanse_original(record: dict[str, Any]) -> RuleResult:
    """CLEA-0001 v2：全角数字转半角，折叠标题中的连续空白。"""
    out = copy.deepcopy(record)
    title = str(out.get("title") or "")
    fold = re.sub(r"\s+", " ", title).strip()
    out["title"] = fold
    table = str.maketrans("０１２３４５６７８９．", "0123456789.")
    out["title"] = out["title"].translate(table)
    out["dedup_key"] = f"{out.get('sku', '')}|{out.get('title', '')}"
    return RuleResult(out, f"空白折叠并全角转半角，生成去重键 {out['dedup_key']}")


def validate_original(record: dict[str, Any]) -> RuleResult:
    """VALI-0001 v4：标题必填、价格必须落在 (0, 100000)，否则隔离。"""
    out = copy.deepcopy(record)
    reasons: list[str] = []
    if not str(out.get("title") or "").strip():
        reasons.append("标题为空，未通过必填校验")
    price = out.get("price")
    if price is None:
        reasons.append("价格缺失，未通过数值校验")
    elif not (0 < float(price) < 100000):
        reasons.append(f"价格 {price} 超出允许区间 (0, 100000)")
    if reasons:
        out["validation_passed"] = False
        return RuleResult(out, "；".join(reasons), status="quarantined", reasons=reasons)
    out["validation_passed"] = True
    return RuleResult(out, "标题与价格均通过 VALI-0001 v4 校验")


def storage_original(record: dict[str, Any]) -> RuleResult:
    """STOR-0001 v2：通过的样本写正式分区，隔离样本写隔离分区。"""
    out = copy.deepcopy(record)
    sku = str(out.get("sku") or "UNKNOWN")
    if record.get("validation_passed") is False:
        out["storage_ref"] = f"s3://warehouse/quarantine/dt=2026-11-08/{sku}.json"
        out["storage_zone"] = "quarantine"
        return RuleResult(out, f"隔离样本转存至 {out['storage_ref']}", status="quarantined")
    out["storage_ref"] = f"s3://warehouse/products/dt=2026-11-08/{sku}.parquet"
    out["storage_zone"] = "published"
    return RuleResult(out, f"写入正式交付分区 {out['storage_ref']}")


# ---------------------------------------------------------------------------
# 候选规则：仅用于重演实验，绝不参与正式交付链路
# ---------------------------------------------------------------------------

def extract_cand_thousands(record: dict[str, Any]) -> RuleResult:
    """EXTR-CAND-01：价格容错增强，识别千分位并强制保留两位小数。"""
    title = str(record.get("raw_title") or "").strip()
    price_text = str(record.get("price_text") or "")
    normalized = price_text.replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", normalized)
    if match:
        price = round(float(match.group(0)), 2)
        note = f"候选规则兼容千分位：{price_text!r} -> {price:.2f}"
    else:
        price = None
        note = "候选规则仍未匹配到价格，price 置空"
    out = {"title": title, "price": price, "sku": str(record.get("raw_sku") or "").strip()}
    return RuleResult(out, note)


def cleanse_cand_truncate(record: dict[str, Any]) -> RuleResult:
    """CLEA-CAND-01：在原清洗基础上把标题截断到 20 个字符，超长加省略标记。"""
    base = cleanse_original(record)
    out = base.record
    if len(out["title"]) > 20:
        out["title"] = out["title"][:20] + "…"
        return RuleResult(out, "空白规范化后标题超过 20 字，已截断并打省略标记")
    return RuleResult(out, base.note + "；标题未超长，无需截断")


def validate_cand_optional_price(record: dict[str, Any]) -> RuleResult:
    """VALI-CAND-01：价格允许为空，空值样本转人工复核而不是直接隔离。"""
    out = copy.deepcopy(record)
    reasons: list[str] = []
    if not str(out.get("title") or "").strip():
        reasons.append("标题为空，未通过必填校验")
    price = out.get("price")
    if price is not None and not (0 < float(price) < 100000):
        reasons.append(f"价格 {price} 超出允许区间 (0, 100000)")
    if reasons:
        out["validation_passed"] = False
        return RuleResult(out, "；".join(reasons), status="quarantined", reasons=reasons)
    out["validation_passed"] = True
    out["manual_review"] = price is None
    note = "价格为空时放行并标记人工复核" if price is None else "标题与价格通过候选校验"
    return RuleResult(out, note)


def validate_cand_strict(record: dict[str, Any]) -> RuleResult:
    """VALI-CAND-02：收紧到 [500, 50000]，低于 500 元的样本会被隔离。"""
    out = copy.deepcopy(record)
    reasons: list[str] = []
    if not str(out.get("title") or "").strip():
        reasons.append("标题为空，未通过必填校验")
    price = out.get("price")
    if price is None:
        reasons.append("价格缺失，未通过数值校验")
    elif not (500 <= float(price) <= 50000):
        reasons.append(f"价格 {price} 不在候选严格区间 [500, 50000] 内")
    if reasons:
        out["validation_passed"] = False
        return RuleResult(out, "；".join(reasons), status="quarantined", reasons=reasons)
    out["validation_passed"] = True
    return RuleResult(out, "标题与价格通过 VALI-CAND-02 严格区间校验")


def storage_cand_experiment_partition(record: dict[str, Any]) -> RuleResult:
    """STOR-CAND-01：重演结果只能写实验分区，路径与正式交付物理隔离。"""
    out = copy.deepcopy(record)
    sku = str(out.get("sku") or "UNKNOWN")
    if record.get("validation_passed") is False:
        out["storage_ref"] = f"s3://warehouse-experiments/quarantine/{sku}.json"
        out["storage_zone"] = "experiment-quarantine"
        return RuleResult(out, f"实验隔离路径 {out['storage_ref']}", status="quarantined")
    out["storage_ref"] = f"s3://warehouse-experiments/replay/{sku}.parquet"
    out["storage_zone"] = "experiment"
    return RuleResult(out, f"实验分区路径，不覆盖正式交付：{out['storage_ref']}")


# 规则注册表：rule_id -> (所属阶段, 版本, 执行函数)。续做与重演都从这里取函数。
RULE_REGISTRY: dict[str, tuple[str, str, Callable[[dict[str, Any]], RuleResult]]] = {
    "COLLECT-RAW": ("collect", "v1", collect_original),
    "EXTR-0001": ("extract", "v3", extract_original),
    "CLEA-0001": ("cleanse", "v2", cleanse_original),
    "VALI-0001": ("validate", "v4", validate_original),
    "STOR-0001": ("storage", "v2", storage_original),
    "EXTR-CAND-01": ("extract", "v1-draft", extract_cand_thousands),
    "CLEA-CAND-01": ("cleanse", "v1-draft", cleanse_cand_truncate),
    "VALI-CAND-01": ("validate", "v1-draft", validate_cand_optional_price),
    "VALI-CAND-02": ("validate", "v1-draft", validate_cand_strict),
    "STOR-CAND-01": ("storage", "v1-draft", storage_cand_experiment_partition),
}

CANDIDATE_RULE_IDS = ["EXTR-CAND-01", "CLEA-CAND-01", "VALI-CAND-01", "VALI-CAND-02", "STOR-CAND-01"]


def diff_records(expected: Any, actual: Any) -> list[dict[str, Any]]:
    """对比两个阶段快照，逐字段列出差异，给重演结果标注分叉点。"""
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return [] if expected == actual else [{"field": "(整体)", "delivered": expected, "experiment": actual}]
    changes: list[dict[str, Any]] = []
    for key in sorted(set(expected) | set(actual)):
        if expected.get(key) != actual.get(key):
            changes.append({"field": key, "delivered": expected.get(key), "experiment": actual.get(key)})
    return changes


def run_pipeline(
    start_record: dict[str, Any],
    *,
    start_stage_index: int,
    override_rule_id: str | None = None,
) -> list[dict[str, Any]]:
    """从指定阶段开始执行规则链，返回每个阶段的输入/输出快照。

    override_rule_id 为空时全部走原始在效规则（断点续做用）；传入候选规则时，
    仅该规则所属阶段被替换，其余阶段仍是原始规则，保证重演可与交付轨迹逐段对比。
    """
    override_stage = RULE_REGISTRY[override_rule_id][0] if override_rule_id else None
    record = copy.deepcopy(start_record)
    produced: list[dict[str, Any]] = []
    for stage in STAGES[start_stage_index:]:
        if override_stage == stage:
            rule_id = override_rule_id  # type: ignore[assignment]
        else:
            rule_id, _version = ORIGINAL_RULE_IDS[stage]
        _stage, version, func = RULE_REGISTRY[rule_id]
        input_snapshot = copy.deepcopy(record)
        result = func(record)
        record = result.record
        produced.append({
            "stage": stage,
            "stage_name": STAGE_NAMES[stage],
            "rule_id": rule_id,
            "rule_version": version,
            "input_value": input_snapshot,
            "output_value": copy.deepcopy(record),
            "transform": result.note,
            "status": result.status,
            "reasons": result.reasons,
            "is_candidate": rule_id in CANDIDATE_RULE_IDS,
        })
    return produced
