"""缺陷登记接口：维护设备缺陷，覆盖确认定级、提交闭环、挂起缺陷与批量确认定级。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BatchGradePayload,
    BatchGradeResult,
    EntryPayload,
    GradeSuggestPayload,
    PageResult,
)
from app.services.defect import DefectService

router = APIRouter(prefix="/api/defect", tags=["缺陷登记"])

service = DefectService()

LIST_FIELDS = ["缺陷编号", "所属设备", "缺陷类型", "严重等级", "发现时间", "发现人", "处理期限", "缺陷状态"]
STATUSES = ["待定级", "已定级", "处理中", "已闭环", "已挂起"]


@router.get("/stats")
def defect_stats() -> dict[str, Any]:
    """缺陷统计：待定级、处理中与超期未闭环数量，随定级动作实时变化。"""
    return {"items": service.stats()}


@router.post("/grade-suggestions")
def grade_suggestions(payload: GradeSuggestPayload) -> dict[str, Any]:
    """按所属设备与缺陷类型，为一批缺陷编号给出严重等级与处理期限的建议值。"""
    return {"items": service.grade_suggestions(payload.缺陷编号列表)}


@router.post("/batch-grade", response_model=BatchGradeResult)
def batch_grade(payload: BatchGradePayload) -> BatchGradeResult:
    """批量确认定级：逐条处理、逐条按缺陷编号回执；成功的立即生效不回退，失败的给出原因。"""
    if not payload.items:
        return BatchGradeResult(ok=False, message="未选择需要定级的缺陷", receipts=[])
    receipts = service.batch_grade([item.model_dump() for item in payload.items])
    failed = sum(1 for receipt in receipts if not receipt["ok"])
    message = f"批量定级完成：成功 {len(receipts) - failed} 条，失败 {failed} 条"
    return BatchGradeResult(ok=failed == 0, message=message, receipts=receipts)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出缺陷登记清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "defect", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按缺陷编号检索"),
    status: str | None = Query(default=None, description="待定级、已定级、处理中、已闭环、已挂起"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按缺陷编号与状态过滤缺陷登记列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条设备缺陷明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"设备缺陷 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条设备缺陷，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="设备缺陷已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条设备缺陷执行确认定级、提交闭环、挂起缺陷；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
