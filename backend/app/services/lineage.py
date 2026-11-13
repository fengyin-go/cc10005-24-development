"""样本血缘业务规则。

两类写操作在这里严格区分：

* ``resume`` 断点续做：只往正式血缘上「补齐」缺失阶段，靠处理段指纹去重，
  同批次重复触发不会重复追加，断点前的处理段一律不删不改；
* ``replay`` 候选规则重演：另开实验分支，实验段与正式血缘平行存放，
  正式交付给存储的证据在任何路径下都不会被覆盖。
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from app.lineage_engine import (
    CANDIDATE_RULE_IDS,
    RULE_REGISTRY,
    STAGES,
    STAGE_NAMES,
    diff_records,
    run_pipeline,
    segment_fingerprint,
)
from app.store import store

SAMPLE_MODULE = "lineage_sample"
EXPERIMENT_MODULE = "lineage_experiment"

# 列表页支持的状态筛选口径。
STATUS_FILTERS = ["已交付", "已隔离", "待续做", "证据缺口"]


class LineageService:
    # ------------------------------------------------------------------ 查询
    def list_samples(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        evidence_gap: bool | None = None,
        merged_only: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(SAMPLE_MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("sample_code", ""))
                or keyword in str(row.get("business_key", ""))
                or keyword in str(row.get("title", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if evidence_gap is not None:
            rows = [row for row in rows if bool(row.get("evidence_gap")) == evidence_gap]
        if merged_only:
            rows = [row for row in rows if row.get("merged")]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._list_view(row) for row in rows[start:start + size]], total

    def get_sample(self, sample_id: int) -> dict[str, Any] | None:
        row = store.find(SAMPLE_MODULE, sample_id)
        return copy.deepcopy(row) if row else None

    def stats(self) -> dict[str, int]:
        rows = store.rows(SAMPLE_MODULE)
        return {
            "sample_total": len(rows),
            "delivered": sum(1 for row in rows if row.get("status") == "已交付"),
            "quarantined": sum(1 for row in rows if row.get("quarantined")),
            "resume_pending": sum(1 for row in rows if row.get("resume_stage")),
            "evidence_gap": sum(1 for row in rows if row.get("evidence_gap")),
            "merged": sum(1 for row in rows if row.get("merged")),
        }

    def candidate_rules(self) -> list[dict[str, str]]:
        """候选规则目录：前端重演面板按阶段分组展示。"""
        return [
            {
                "rule_id": rule_id,
                "stage": RULE_REGISTRY[rule_id][0],
                "stage_name": STAGE_NAMES[RULE_REGISTRY[rule_id][0]],
                "rule_version": RULE_REGISTRY[rule_id][1],
                "summary": RULE_REGISTRY[rule_id][2].__doc__.strip().split("：", 1)[-1],
            }
            for rule_id in CANDIDATE_RULE_IDS
        ]

    def list_experiments(self, sample_id: int | None = None) -> list[dict[str, Any]]:
        rows = store.rows(EXPERIMENT_MODULE)
        if sample_id is not None:
            sample = store.find(SAMPLE_MODULE, sample_id)
            if sample is None:
                return []
            rows = [row for row in rows if row.get("sample_code") == sample["sample_code"]]
        # 实验只回摘要，完整处理段走详情接口，避免列表过大。
        return [self._experiment_summary(row) for row in rows]

    def get_experiment(self, experiment_id: int) -> dict[str, Any] | None:
        row = store.find(EXPERIMENT_MODULE, experiment_id)
        return copy.deepcopy(row) if row else None

    # ----------------------------------------------------------- 断点续做
    def resume(self, sample_id: int, batch_id: str | None = None) -> tuple[dict[str, Any] | None, str]:
        """对中断样本补齐后续处理段；按指纹幂等，可安全重复触发。"""
        sample = store.find(SAMPLE_MODULE, sample_id)
        if sample is None:
            return None, f"样本 {sample_id} 不存在，无法续做"
        if not sample.get("resume_stage"):
            return None, f"样本 {sample['sample_code']} 没有待续做的断点，所有处理段均已交付"

        resume_stage = sample["resume_stage"]
        if resume_stage not in STAGES:
            return None, f"断点阶段「{resume_stage}」无法识别"
        start_index = STAGES.index(resume_stage)
        batch = batch_id or f"RESUME-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 续做的输入快照固定取「断点阶段的前一段」输出：即使断点被重置，
        # 也不会拿末段（如存储段）输出当起点，保证指纹与首次续做完全一致。
        start_record = self._record_before_stage(sample, resume_stage)
        produced = run_pipeline(start_record, start_stage_index=start_index)

        existing_fingerprints = {seg.get("fingerprint") for seg in sample["segments"]}
        appended: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for item in produced:
            fingerprint = segment_fingerprint(
                sample["sample_code"],
                item["stage"],
                item["rule_id"],
                item["rule_version"],
                batch,
                item["input_value"],
            )
            if fingerprint in existing_fingerprints:
                # 跨批次续做重跑：同段已存在则跳过，绝不重复追加。
                skipped.append({"stage": item["stage"], "stage_name": item["stage_name"], "fingerprint": fingerprint})
                continue
            segment = {
                "fingerprint": fingerprint,
                "batch_id": batch,
                "source_ref": None,
                "evidence_gap": False,
                **item,
            }
            sample["segments"].append(segment)
            existing_fingerprints.add(fingerprint)
            appended.append(segment)

        remaining = [stage for stage in STAGES if not self._has_stage(sample, stage)]
        if remaining:
            # 理论上 run_pipeline 会一次跑完全部剩余阶段；仍保留防御性判断。
            sample["resume_stage"] = remaining[0]
        else:
            sample["resume_stage"] = None
            last_output = sample["segments"][-1]["output_value"]
            sample["final_value"] = last_output
            quarantined = any(seg.get("status") == "quarantined" for seg in sample["segments"])
            sample["quarantined"] = quarantined
            sample["status"] = "已隔离" if quarantined else "已交付"

        message = (
            f"续做完成：新增 {len(appended)} 个处理段，幂等跳过 {len(skipped)} 个已存在处理段"
        )
        return {
            "sample": self._list_view(sample),
            "batch_id": batch,
            "appended": [{"stage": seg["stage"], "stage_name": seg["stage_name"], "fingerprint": seg["fingerprint"]} for seg in appended],
            "skipped": skipped,
            "message": message,
        }, message

    # ----------------------------------------------------------- 候选规则重演
    def replay(
        self,
        sample_id: int,
        candidate_rule_id: str,
        *,
        note: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """用候选规则重演整条链路，结果只进实验分支，不动正式血缘。"""
        sample = store.find(SAMPLE_MODULE, sample_id)
        if sample is None:
            return None, f"样本 {sample_id} 不存在，无法重演"
        if candidate_rule_id not in RULE_REGISTRY:
            return None, f"候选规则「{candidate_rule_id}」不存在"
        if candidate_rule_id not in CANDIDATE_RULE_IDS:
            return None, f"规则「{candidate_rule_id}」是正式在效规则，重演只接受候选规则"

        start_record, start_index, carried_gap = self._replay_start(sample, candidate_rule_id)
        experiment_segments = run_pipeline(
            start_record,
            start_stage_index=start_index,
            override_rule_id=candidate_rule_id,
        )

        delivered_by_stage = {seg["stage"]: seg for seg in sample["segments"]}
        divergence_stages: list[str] = []
        for segment in experiment_segments:
            delivered = delivered_by_stage.get(segment["stage"])
            if segment["stage"] == "collect":
                # 重演的采集段只是同一份原始输入的结构化回放，原始 HTML 片段仍以正式
                # 血缘为准；这里不参与逐字段分叉对比，避免包装结构差异造成误报。
                segment["diffs"] = []
                segment["diverged"] = False
                segment["compare_note"] = "同来源重放，原始网页片段以正式交付证据为准"
                continue
            delivered_output = delivered["output_value"] if delivered else None
            segment["diffs"] = diff_records(delivered_output, segment["output_value"])
            segment["diverged"] = bool(segment["diffs"])
            if segment["diverged"]:
                divergence_stages.append(segment["stage"])

        final_output = experiment_segments[-1]["output_value"]
        experiment_quarantined = any(seg["status"] == "quarantined" for seg in experiment_segments)
        delivered_final = sample.get("final_value")
        final_diffs = diff_records(delivered_final, final_output)

        experiments = store.rows(EXPERIMENT_MODULE)
        next_id = max((int(row.get("id", 0)) for row in experiments), default=0) + 1
        experiment = {
            "id": next_id,
            "experiment_code": f"EXP-{next_id:04d}",
            "sample_id": sample_id,
            "sample_code": sample["sample_code"],
            "branch": "experiment",
            "immutable": True,
            "candidate_rule_id": candidate_rule_id,
            "candidate_stage": RULE_REGISTRY[candidate_rule_id][0],
            "candidate_rule_version": RULE_REGISTRY[candidate_rule_id][1],
            "note": note or "",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "carried_evidence_gap": carried_gap,
            "segments": experiment_segments,
            "summary": {
                "divergence_stages": divergence_stages,
                "first_divergence_stage": divergence_stages[0] if divergence_stages else None,
                "final_diverged": bool(final_diffs),
                "final_field_diffs": final_diffs,
                "experiment_quarantined": experiment_quarantined,
                "delivered_quarantined": bool(sample.get("quarantined")),
                "delivered_final_untouched": True,
            },
        }
        experiments.append(experiment)
        return copy.deepcopy(experiment), f"重演完成：实验 {experiment['experiment_code']} 已生成，正式交付证据未改动"

    # ------------------------------------------------------------------ 辅助
    def _replay_start(self, sample: dict[str, Any], candidate_rule_id: str) -> tuple[dict[str, Any], int, bool]:
        """确定重演起点：有采集段就从原始片段走；来源缺失则从映射输出起步并带缺口标记。"""
        segments = sample["segments"]
        collect = next((seg for seg in segments if seg["stage"] == "collect"), None)
        if collect and not collect.get("evidence_gap"):
            # 从采集输出重建引擎输入记录，保证重演包含完整五段。
            record = self._record_from_collect(collect, segments)
            return record, 0, False
        candidate_stage = RULE_REGISTRY[candidate_rule_id][0]
        extract = next((seg for seg in segments if seg["stage"] == "extract"), None)
        if extract is None:
            raise ValueError("样本既无采集段也无映射段，无法重演")
        if candidate_stage in ("collect", "extract"):
            raise ValueError("该样本缺失采集来源，无法重演采集或字段映射阶段，请选择清洗及之后的候选规则")
        # 缺口样本只能从映射输出起步，缺的那段在实验里继续以 carried_evidence_gap 明示。
        return copy.deepcopy(extract["output_value"]), STAGES.index("cleanse"), True

    @staticmethod
    def _record_before_stage(sample: dict[str, Any], stage: str) -> dict[str, Any]:
        """取断点阶段前一段的输出快照；collect 之前没有前置段时回退到首段输出。"""
        previous_index = STAGES.index(stage) - 1
        if previous_index < 0:
            return copy.deepcopy(sample["segments"][0]["output_value"])
        previous_stage = STAGES[previous_index]
        previous = next(
            (seg for seg in sample["segments"] if seg["stage"] == previous_stage),
            None,
        )
        if previous is not None:
            return copy.deepcopy(previous["output_value"])
        return copy.deepcopy(sample["segments"][0]["output_value"])

    @staticmethod
    def _record_from_collect(collect: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
        """从正式血缘的采集/映射段还原引擎所需的初始 record。"""
        extract = next((seg for seg in segments if seg["stage"] == "extract"), None)
        if extract and isinstance(extract.get("input_value"), dict):
            return copy.deepcopy(extract["input_value"])
        # 兜底：直接用采集输出，引擎规则会容忍缺字段。
        return copy.deepcopy(collect.get("output_value") or {})

    @staticmethod
    def _has_stage(sample: dict[str, Any], stage: str) -> bool:
        return any(seg.get("stage") == stage and not seg.get("evidence_gap") for seg in sample["segments"])

    @staticmethod
    def _list_view(row: dict[str, Any]) -> dict[str, Any]:
        """列表摘要：保留状态标识与证据计数，明细仍走详情接口。"""
        segments = row.get("segments", [])
        return {
            "id": row["id"],
            "sample_code": row.get("sample_code"),
            "business_key": row.get("business_key"),
            "title": row.get("title"),
            "status": row.get("status"),
            "quarantined": row.get("quarantined", False),
            "merged": row.get("merged", False),
            "evidence_gap": row.get("evidence_gap", False),
            "resume_stage": row.get("resume_stage"),
            "source_count": row.get("source_count", 0),
            "segment_count": len(segments),
            "gap_segment_count": sum(1 for seg in segments if seg.get("evidence_gap")),
            "stages": [seg["stage"] for seg in segments],
            "final_value": row.get("final_value"),
        }

    @staticmethod
    def _experiment_summary(row: dict[str, Any]) -> dict[str, Any]:
        summary = row.get("summary", {})
        return {
            "id": row["id"],
            "experiment_code": row.get("experiment_code"),
            "sample_code": row.get("sample_code"),
            "candidate_rule_id": row.get("candidate_rule_id"),
            "candidate_stage": row.get("candidate_stage"),
            "candidate_rule_version": row.get("candidate_rule_version"),
            "created_at": row.get("created_at"),
            "note": row.get("note"),
            "first_divergence_stage": summary.get("first_divergence_stage"),
            "final_diverged": summary.get("final_diverged"),
            "experiment_quarantined": summary.get("experiment_quarantined"),
            "carried_evidence_gap": row.get("carried_evidence_gap"),
        }
