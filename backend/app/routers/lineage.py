"""样本血缘接口。

只读接口负责把「原始片段 -> 字段映射 -> 清洗 -> 校验 -> 存储」的逐段证据
交给前端；两个写接口语义完全不同：

* ``POST /{id}/resume``  断点续做，幂等补齐正式血缘；
* ``POST /{id}/replay``  候选规则重演，只生成实验轨迹，永不覆盖交付证据。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.lineage import LineageService

router = APIRouter(prefix="/api/lineage", tags=["样本血缘"])

service = LineageService()


@router.get("/stats")
def get_stats() -> dict[str, int]:
    """血缘看板统计：总量、隔离量、待续做量与证据缺口量。"""
    return service.stats()


@router.get("/candidate-rules")
def get_candidate_rules() -> dict[str, list[dict[str, str]]]:
    """可用于重演的候选规则目录，按规则编号返回所属阶段与说明。"""
    return {"items": service.candidate_rules()}


@router.get("/experiments")
def list_experiments(sample_id: int | None = Query(default=None, description="只看某条样本的实验分支")) -> dict[str, list[dict[str, object]]]:
    """重演实验列表；带 sample_id 时只返回该样本的实验轨迹。"""
    return {"items": service.list_experiments(sample_id)}


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: int) -> dict:
    """实验详情：完整实验处理段、逐字段差异与正式血缘对照。"""
    experiment = service.get_experiment(experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail=f"重演实验 {experiment_id} 不存在")
    return experiment


@router.get("", response_model=PageResult[dict])
def list_samples(
    keyword: str | None = Query(default=None, description="按样本编号、业务键或标题检索"),
    status: str | None = Query(default=None, description="已交付、已隔离、待续做、证据缺口"),
    evidence_gap: bool | None = Query(default=None, description="只看存在证据缺口的样本"),
    merged_only: bool | None = Query(default=None, description="只看去重合并过的样本"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """样本血缘列表；支持按状态、证据缺口、合并标记过滤。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_samples(
        keyword=keyword,
        status=status,
        evidence_gap=evidence_gap,
        merged_only=merged_only,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{sample_id}")
def get_sample(sample_id: int) -> dict:
    """血缘详情：全部来源（含合并来源）、逐段输入/输出快照与证据缺口标记。"""
    sample = service.get_sample(sample_id)
    if sample is None:
        raise HTTPException(status_code=404, detail=f"样本 {sample_id} 不存在或已归档")
    return sample


@router.post("/{sample_id}/resume", response_model=ActionResult)
def resume_sample(sample_id: int, payload: EntryPayload | None = None) -> ActionResult:
    """跨批次续做：按处理段指纹幂等补齐，重复触发不会重复追加。"""
    batch_id = None
    if payload is not None:
        batch_id = str(payload.values.get("batch_id") or "").strip() or None
    result, message = service.resume(sample_id, batch_id)
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.post("/{sample_id}/replay", response_model=ActionResult)
def replay_sample(sample_id: int, payload: EntryPayload) -> ActionResult:
    """候选规则重演：另存实验轨迹，正式交付给存储的证据保持不变。"""
    candidate_rule_id = str(payload.values.get("candidate_rule_id") or "").strip()
    if not candidate_rule_id:
        return ActionResult(ok=False, message="缺少 candidate_rule_id，无法重演")
    note = payload.values.get("note")
    try:
        experiment, message = service.replay(
            sample_id,
            candidate_rule_id,
            note=str(note) if note is not None else None,
        )
    except ValueError as exc:
        # 例如证据缺口样本试图重演采集/映射阶段：明确拒绝而不是返回 500。
        return ActionResult(ok=False, message=str(exc))
    if experiment is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=experiment)
