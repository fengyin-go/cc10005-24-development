"""样本血缘种子数据。

数据刻意覆盖需求里点名的每一种情形，页面一打开就能验证：

* SMPL-0001：两条来源被去重合并，血缘保留全部来源与全部采集段，不只剩最后一次；
* SMPL-0002：被校验规则隔离，但隔离前后的完整轨迹都还在；
* SMPL-0003：跨批次续做中的任务，断点前的证据已落，续做要幂等、不能重复追加；
* SMPL-0004：历史迁移进来的旧样例，缺少采集来源，必须明确标出证据缺口；
* SMPL-0005：正常走完全链路并交付到正式分区的普通样本。
"""
from __future__ import annotations

from typing import Any

from app.lineage_engine import (
    ORIGINAL_RULE_IDS,
    STAGE_NAMES,
    canonical_json,
    segment_fingerprint,
)


def _segment(
    sample_code: str,
    stage: str,
    batch_id: str,
    input_value: Any,
    output_value: Any,
    transform: str,
    *,
    rule_id: str | None = None,
    source_ref: str | None = None,
    status: str = "ok",
    reasons: list[str] | None = None,
    evidence_gap: bool = False,
) -> dict[str, Any]:
    """构造一条处理段并自动算指纹；指纹即续做时的幂等键。"""
    rid, version = ORIGINAL_RULE_IDS[stage] if rule_id is None else (rule_id, ORIGINAL_RULE_IDS[stage][1])
    if rule_id is not None:
        version = ORIGINAL_RULE_IDS[stage][1]
    return {
        "fingerprint": segment_fingerprint(sample_code, stage, rid, version, batch_id, input_value),
        "stage": stage,
        "stage_name": STAGE_NAMES[stage],
        "rule_id": rid,
        "rule_version": version,
        "batch_id": batch_id,
        "source_ref": source_ref,
        "input_value": input_value,
        "output_value": output_value,
        "transform": transform,
        "status": status,
        "reasons": reasons or [],
        "evidence_gap": evidence_gap,
        "is_candidate": False,
    }


# ---------------------------------------------------------------------------
# SMPL-0001：同键去重合并，两个来源都要保留
# ---------------------------------------------------------------------------

_SMPL_0001_SNIPPET_A = (
    '<li class="goods"><h3>  降噪蓝牙耳机 Pro </h3>'
    '<span class="p">¥299.00</span><em data-sku="SKU-1001"></em></li>'
)
_SMPL_0001_SNIPPET_B = (
    '<div class="card"><h3>降噪蓝牙耳机 Pro</h3>'
    '<p class="price">299元</p><small>SKU-1001</small></div>'
)

_SMPL_0001_RECORD = {
    "raw_title": "  降噪蓝牙耳机 Pro ",
    "price_text": "¥299.00",
    "raw_sku": "SKU-1001",
}
_SMPL_0001_EXTRACTED = {"title": "降噪蓝牙耳机 Pro", "price": 299.0, "sku": "SKU-1001"}
_SMPL_0001_CLEANSED = {
    "title": "降噪蓝牙耳机 Pro",
    "price": 299.0,
    "sku": "SKU-1001",
    "dedup_key": "SKU-1001|降噪蓝牙耳机 Pro",
}
_SMPL_0001_FINAL = {
    **_SMPL_0001_CLEANSED,
    "validation_passed": True,
    "storage_ref": "s3://warehouse/products/dt=2026-11-08/SKU-1001.parquet",
    "storage_zone": "published",
}


def _build_smpl_0001() -> dict[str, Any]:
    code = "SMPL-0001"
    segments = [
        _segment(code, "collect", "BATCH-20261108-01",
                 {"url": "https://mall.example.com/list/page-1", "http_status": 200},
                 {"snippet": _SMPL_0001_SNIPPET_A, "captured_at": "2026-11-08T09:12:03+08:00"},
                 "列表页抓取到商品卡片，保存原始 HTML 片段",
                 source_ref="https://mall.example.com/list/page-1#SKU-1001",
                 rule_id="COLLECT-RAW"),
        _segment(code, "collect", "BATCH-20261108-01",
                 {"url": "https://mall.example.com/channel/audio?from=push", "http_status": 200},
                 {"snippet": _SMPL_0001_SNIPPET_B, "captured_at": "2026-11-08T09:40:51+08:00"},
                 "推送渠道页再次抓到同一商品，作为第二个来源保留，不覆盖首个片段",
                 source_ref="https://mall.example.com/channel/audio?from=push#SKU-1001",
                 rule_id="COLLECT-RAW"),
        _segment(code, "extract", "BATCH-20261108-01",
                 _SMPL_0001_RECORD, _SMPL_0001_EXTRACTED,
                 "正则提取价格 '¥299.00' -> 299.0，标题去除首尾空白"),
        _segment(code, "cleanse", "BATCH-20261108-01",
                 _SMPL_0001_EXTRACTED, _SMPL_0001_CLEANSED,
                 "空白折叠并全角转半角，生成去重键 SKU-1001|降噪蓝牙耳机 Pro"),
        _segment(code, "validate", "BATCH-20261108-01",
                 _SMPL_0001_CLEANSED, {**_SMPL_0001_CLEANSED, "validation_passed": True},
                 "标题与价格均通过 VALI-0001 v4 校验"),
        _segment(code, "storage", "BATCH-20261108-01",
                 {**_SMPL_0001_CLEANSED, "validation_passed": True}, _SMPL_0001_FINAL,
                 "写入正式交付分区 s3://warehouse/products/dt=2026-11-08/SKU-1001.parquet"),
    ]
    return {
        "id": 1,
        "sample_code": code,
        "business_key": "SKU-1001",
        "title": "降噪蓝牙耳机 Pro",
        "final_value": _SMPL_0001_FINAL,
        "status": "已交付",
        "quarantined": False,
        "merged": True,
        "evidence_gap": False,
        "resume_stage": None,
        "source_count": 2,
        "sources": [
            {
                "source_ref": "https://mall.example.com/list/page-1#SKU-1001",
                "batch_id": "BATCH-20261108-01",
                "captured_at": "2026-11-08T09:12:03+08:00",
                "raw_snippet": _SMPL_0001_SNIPPET_A,
                "dedup_key": "SKU-1001|降噪蓝牙耳机 Pro",
            },
            {
                "source_ref": "https://mall.example.com/channel/audio?from=push#SKU-1001",
                "batch_id": "BATCH-20261108-01",
                "captured_at": "2026-11-08T09:40:51+08:00",
                "raw_snippet": _SMPL_0001_SNIPPET_B,
                "dedup_key": "SKU-1001|降噪蓝牙耳机 Pro",
            },
        ],
        "segments": segments,
    }


# ---------------------------------------------------------------------------
# SMPL-0002：校验隔离，完整轨迹保留（含隔离分区落点）
# ---------------------------------------------------------------------------

_SMPL_0002_SNIPPET = (
    '<article><h2>便携机械键盘</h2>'
    '<span class="price-tag">价格待公布</span><i>SKU-2007</i></article>'
)
_SMPL_0002_RECORD = {"raw_title": "便携机械键盘", "price_text": "价格待公布", "raw_sku": "SKU-2007"}
_SMPL_0002_EXTRACTED = {"title": "便携机械键盘", "price": None, "sku": "SKU-2007"}
_SMPL_0002_CLEANSED = {
    "title": "便携机械键盘",
    "price": None,
    "sku": "SKU-2007",
    "dedup_key": "SKU-2007|便携机械键盘",
}
_SMPL_0002_QUARANTINED = {
    **_SMPL_0002_CLEANSED,
    "validation_passed": False,
    "storage_ref": "s3://warehouse/quarantine/dt=2026-11-08/SKU-2007.json",
    "storage_zone": "quarantine",
}


def _build_smpl_0002() -> dict[str, Any]:
    code = "SMPL-0002"
    segments = [
        _segment(code, "collect", "BATCH-20261108-01",
                 {"url": "https://mall.example.com/item/2007", "http_status": 200},
                 {"snippet": _SMPL_0002_SNIPPET, "captured_at": "2026-11-08T10:02:44+08:00"},
                 "详情页抓取成功，原始片段里没有价格数字",
                 source_ref="https://mall.example.com/item/2007",
                 rule_id="COLLECT-RAW"),
        _segment(code, "extract", "BATCH-20261108-01",
                 _SMPL_0002_RECORD, _SMPL_0002_EXTRACTED,
                 "未在 '价格待公布' 中匹配到数字价格，price 置空"),
        _segment(code, "cleanse", "BATCH-20261108-01",
                 _SMPL_0002_EXTRACTED, _SMPL_0002_CLEANSED,
                 "空白折叠并全角转半角，生成去重键 SKU-2007|便携机械键盘"),
        _segment(code, "validate", "BATCH-20261108-01",
                 _SMPL_0002_CLEANSED,
                 {**_SMPL_0002_CLEANSED, "validation_passed": False},
                 "价格缺失，未通过数值校验",
                 status="quarantined",
                 reasons=["价格缺失，未通过数值校验"]),
        _segment(code, "storage", "BATCH-20261108-01",
                 {**_SMPL_0002_CLEANSED, "validation_passed": False},
                 _SMPL_0002_QUARANTINED,
                 "隔离样本转存至 s3://warehouse/quarantine/dt=2026-11-08/SKU-2007.json",
                 status="quarantined",
                 reasons=["价格缺失，未通过数值校验"]),
    ]
    return {
        "id": 2,
        "sample_code": code,
        "business_key": "SKU-2007",
        "title": "便携机械键盘",
        "final_value": _SMPL_0002_QUARANTINED,
        "status": "已隔离",
        "quarantined": True,
        "merged": False,
        "evidence_gap": False,
        "resume_stage": None,
        "source_count": 1,
        "sources": [
            {
                "source_ref": "https://mall.example.com/item/2007",
                "batch_id": "BATCH-20261108-01",
                "captured_at": "2026-11-08T10:02:44+08:00",
                "raw_snippet": _SMPL_0002_SNIPPET,
                "dedup_key": "SKU-2007|便携机械键盘",
            },
        ],
        "segments": segments,
    }


# ---------------------------------------------------------------------------
# SMPL-0003：跨批次续做中断，断点前证据已落，等待幂等续做
# ---------------------------------------------------------------------------

_SMPL_0003_SNIPPET = (
    '<li><h3>  ４Ｋ高刷显示器　27寸 </h3>'
    '<span>￥1,899.00</span><b>SKU-3105</b></li>'
)
_SMPL_0003_RECORD = {"raw_title": "  ４Ｋ高刷显示器　27寸 ", "price_text": "￥1,899.00", "raw_sku": "SKU-3105"}
_SMPL_0003_EXTRACTED = {"title": "４Ｋ高刷显示器　27寸", "price": 1899.0, "sku": "SKU-3105"}


def _build_smpl_0003() -> dict[str, Any]:
    code = "SMPL-0003"
    segments = [
        _segment(code, "collect", "BATCH-20261108-02",
                 {"url": "https://mall.example.com/list/page-9", "http_status": 200},
                 {"snippet": _SMPL_0003_SNIPPET, "captured_at": "2026-11-08T11:20:17+08:00"},
                 "采集批次在清洗阶段前中断，原始片段与映射结果已先行落证",
                 source_ref="https://mall.example.com/list/page-9#SKU-3105",
                 rule_id="COLLECT-RAW"),
        _segment(code, "extract", "BATCH-20261108-02",
                 _SMPL_0003_RECORD, _SMPL_0003_EXTRACTED,
                 "正则提取价格 '￥1,899.00' -> 1899.0"),
    ]
    return {
        "id": 3,
        "sample_code": code,
        "business_key": "SKU-3105",
        "title": "４Ｋ高刷显示器　27寸",
        "final_value": None,
        "status": "待续做",
        "quarantined": False,
        "merged": False,
        "evidence_gap": False,
        # 断点：cleanse 及其之后尚未产生处理段。
        "resume_stage": "cleanse",
        "source_count": 1,
        "sources": [
            {
                "source_ref": "https://mall.example.com/list/page-9#SKU-3105",
                "batch_id": "BATCH-20261108-02",
                "captured_at": "2026-11-08T11:20:17+08:00",
                "raw_snippet": _SMPL_0003_SNIPPET,
                "dedup_key": None,
            },
        ],
        "segments": segments,
    }


# ---------------------------------------------------------------------------
# SMPL-0004：历史迁移旧样例，缺少采集来源，明确显示证据缺口
# ---------------------------------------------------------------------------

_SMPL_0004_EXTRACTED = {"title": "旧版数据迁移样例", "price": 128.0, "sku": "LEGACY-042"}
_SMPL_0004_CLEANSED = {
    "title": "旧版数据迁移样例",
    "price": 128.0,
    "sku": "LEGACY-042",
    "dedup_key": "LEGACY-042|旧版数据迁移样例",
}
_SMPL_0004_FINAL = {
    **_SMPL_0004_CLEANSED,
    "validation_passed": True,
    "storage_ref": "s3://warehouse/legacy/dt=2026-08-01/LEGACY-042.parquet",
    "storage_zone": "published",
}


def _build_smpl_0004() -> dict[str, Any]:
    code = "SMPL-0004"
    segments = [
        {
            # 缺口段不参与续做幂等：没有输入快照，指纹留空并显式打证据缺口标记。
            "fingerprint": "",
            "stage": "collect",
            "stage_name": STAGE_NAMES["collect"],
            "rule_id": "UNKNOWN",
            "rule_version": "unknown",
            "batch_id": "LEGACY-MIGRATION",
            "source_ref": None,
            "input_value": None,
            "output_value": None,
            "transform": "历史系统迁移样例，原始网页片段与抓取上下文未随迁移带出，证据无法补齐",
            "status": "gap",
            "reasons": ["缺少原始网页片段", "缺少来源 URL 与抓取批次上下文"],
            "evidence_gap": True,
            "is_candidate": False,
        },
        _segment(code, "extract", "LEGACY-MIGRATION",
                 {"note": "迁移时仅保留了映射后字段，源字段已丢失"},
                 _SMPL_0004_EXTRACTED,
                 "沿用迁移时的字段映射结果，无法回溯映射前的原始值",
                 rule_id="EXTR-0001"),
        _segment(code, "cleanse", "LEGACY-MIGRATION",
                 _SMPL_0004_EXTRACTED, _SMPL_0004_CLEANSED,
                 "按迁移批次补跑 CLEA-0001 v2，生成去重键"),
        _segment(code, "validate", "LEGACY-MIGRATION",
                 _SMPL_0004_CLEANSED, {**_SMPL_0004_CLEANSED, "validation_passed": True},
                 "迁移补录校验通过，但因来源缺失整体仍标记证据缺口"),
        _segment(code, "storage", "LEGACY-MIGRATION",
                 {**_SMPL_0004_CLEANSED, "validation_passed": True}, _SMPL_0004_FINAL,
                 "写入历史遗留分区 s3://warehouse/legacy/dt=2026-08-01/LEGACY-042.parquet"),
    ]
    return {
        "id": 4,
        "sample_code": code,
        "business_key": "LEGACY-042",
        "title": "旧版数据迁移样例",
        "final_value": _SMPL_0004_FINAL,
        "status": "证据缺口",
        "quarantined": False,
        "merged": False,
        "evidence_gap": True,
        "resume_stage": None,
        "source_count": 0,
        "sources": [],
        "segments": segments,
    }


# ---------------------------------------------------------------------------
# SMPL-0005：单来源、全链路正常交付的普通样本
# ---------------------------------------------------------------------------

_SMPL_0005_SNIPPET = (
    '<div class="item"><h3>USB-C 扩展坞 七合一</h3>'
    '<span class="p">159.00 元</span><em>SKU-5012</em></div>'
)
_SMPL_0005_RECORD = {"raw_title": "USB-C 扩展坞 七合一", "price_text": "159.00 元", "raw_sku": "SKU-5012"}
_SMPL_0005_EXTRACTED = {"title": "USB-C 扩展坞 七合一", "price": 159.0, "sku": "SKU-5012"}
_SMPL_0005_CLEANSED = {
    "title": "USB-C 扩展坞 七合一",
    "price": 159.0,
    "sku": "SKU-5012",
    "dedup_key": "SKU-5012|USB-C 扩展坞 七合一",
}
_SMPL_0005_FINAL = {
    **_SMPL_0005_CLEANSED,
    "validation_passed": True,
    "storage_ref": "s3://warehouse/products/dt=2026-11-08/SKU-5012.parquet",
    "storage_zone": "published",
}


def _build_smpl_0005() -> dict[str, Any]:
    code = "SMPL-0005"
    segments = [
        _segment(code, "collect", "BATCH-20261108-03",
                 {"url": "https://mall.example.com/list/page-2", "http_status": 200},
                 {"snippet": _SMPL_0005_SNIPPET, "captured_at": "2026-11-08T12:05:39+08:00"},
                 "列表页抓取商品卡片，保存原始 HTML 片段",
                 source_ref="https://mall.example.com/list/page-2#SKU-5012",
                 rule_id="COLLECT-RAW"),
        _segment(code, "extract", "BATCH-20261108-03",
                 _SMPL_0005_RECORD, _SMPL_0005_EXTRACTED,
                 "正则提取价格 '159.00 元' -> 159.0"),
        _segment(code, "cleanse", "BATCH-20261108-03",
                 _SMPL_0005_EXTRACTED, _SMPL_0005_CLEANSED,
                 "空白折叠并全角转半角，生成去重键 SKU-5012|USB-C 扩展坞 七合一"),
        _segment(code, "validate", "BATCH-20261108-03",
                 _SMPL_0005_CLEANSED, {**_SMPL_0005_CLEANSED, "validation_passed": True},
                 "标题与价格均通过 VALI-0001 v4 校验"),
        _segment(code, "storage", "BATCH-20261108-03",
                 {**_SMPL_0005_CLEANSED, "validation_passed": True}, _SMPL_0005_FINAL,
                 "写入正式交付分区 s3://warehouse/products/dt=2026-11-08/SKU-5012.parquet"),
    ]
    return {
        "id": 5,
        "sample_code": code,
        "business_key": "SKU-5012",
        "title": "USB-C 扩展坞 七合一",
        "final_value": _SMPL_0005_FINAL,
        "status": "已交付",
        "quarantined": False,
        "merged": False,
        "evidence_gap": False,
        "resume_stage": None,
        "source_count": 1,
        "sources": [
            {
                "source_ref": "https://mall.example.com/list/page-2#SKU-5012",
                "batch_id": "BATCH-20261108-03",
                "captured_at": "2026-11-08T12:05:39+08:00",
                "raw_snippet": _SMPL_0005_SNIPPET,
                "dedup_key": "SKU-5012|USB-C 扩展坞 七合一",
            },
        ],
        "segments": segments,
    }


def build_lineage_seed() -> dict[str, list[dict[str, Any]]]:
    """组装血缘模块的两张表：样本表与重演实验表（启动时为空）。"""
    return {
        "lineage_sample": [
            _build_smpl_0001(),
            _build_smpl_0002(),
            _build_smpl_0003(),
            _build_smpl_0004(),
            _build_smpl_0005(),
        ],
        "lineage_experiment": [],
    }


__all__ = ["build_lineage_seed", "canonical_json"]
