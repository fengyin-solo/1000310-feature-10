"""缺陷登记业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.store import store

MODULE = "defect"
REQUIRED_FIELDS = ["缺陷编号", "所属设备", "缺陷类型"]
STATUS_ORDER = ["待定级", "已定级", "处理中", "已闭环", "已挂起"]
ACTION_RULES = {"确认定级": "已定级", "提交闭环": "已闭环", "挂起缺陷": "已挂起"}
NEGATIVE_ACTIONS = []

# 严重等级允许值，以及按所属设备缺陷类型给出的建议值；未覆盖的类型回落到「一般」。
SEVERITY_LEVELS = ["一般", "严重", "危急"]
SEVERITY_BY_TYPE = {
    "热斑": "危急",
    "电弧": "危急",
    "接地故障": "危急",
    "隐裂": "严重",
    "组件破损": "严重",
    "渗油": "严重",
    "支架变形": "严重",
    "通讯中断": "一般",
    "污秽": "一般",
    "标识缺失": "一般",
}
DEFAULT_SEVERITY = "一般"
# 处理期限随定级一起落上：按严重等级给出建议天数。
DEADLINE_DAYS = {"危急": 1, "严重": 7, "一般": 30}

STATUS_PENDING, STATUS_GRADED = STATUS_ORDER[0], STATUS_ORDER[1]
CLOSED_STATUSES = ("已闭环", "已挂起")


class DefectService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("缺陷编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_PENDING
        entry["缺陷状态"] = STATUS_PENDING
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"设备缺陷 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于缺陷登记可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["缺陷状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"设备缺陷已{action}"

    def stats(self) -> list[dict[str, Any]]:
        """统计卡片口径：待定级、处理中，以及处理期限已过但尚未闭环的缺陷数。"""
        rows = store.rows(MODULE)
        today = date.today().isoformat()

        def overdue(row: dict[str, Any]) -> bool:
            deadline = str(row.get("处理期限") or "").strip()
            return bool(deadline) and deadline < today and row.get("status") not in CLOSED_STATUSES

        return [
            {"label": "待定级缺陷", "value": sum(1 for row in rows if row.get("status") == STATUS_PENDING)},
            {"label": "处理中缺陷", "value": sum(1 for row in rows if row.get("status") == "处理中")},
            {"label": "超期未闭环", "value": sum(1 for row in rows if overdue(row))},
        ]

    def suggest_grading(self, codes: list[str]) -> list[dict[str, Any]]:
        """按缺陷编号给出建议严重等级与建议处理期限，供批量定级面板预填。"""
        suggestions = []
        for raw_code in codes:
            code = str(raw_code or "").strip()
            entry = self._find_by_code(code)
            if entry is None:
                suggestions.append({"缺陷编号": code, "可定级": False, "提示": f"缺陷编号 {code or '空'} 不存在或已归档"})
                continue
            severity = self._suggest_severity(entry)
            deadline = (date.today() + timedelta(days=DEADLINE_DAYS[severity])).isoformat()
            gradable = entry.get("status") == STATUS_PENDING
            suggestions.append({
                "缺陷编号": code,
                "所属设备": entry.get("所属设备"),
                "缺陷类型": entry.get("缺陷类型"),
                "建议严重等级": severity,
                "建议处理期限": deadline,
                "可定级": gradable,
                "提示": "" if gradable else f"当前状态为「{entry.get('status')}」，不在待定级范围",
            })
        return suggestions

    def grade_batch(self, items: list[Any]) -> list[dict[str, Any]]:
        """批量确认定级：逐条校验逐条落库，失败不影响已成功条目，重复提交不重复定级。"""
        return [self._grade_one(item) for item in items]

    def _grade_one(self, item: Any) -> dict[str, Any]:
        code = str(getattr(item, "缺陷编号", "") or "").strip()
        if not code:
            return self._receipt(code, False, "缺陷编号不能为空")
        entry = self._find_by_code(code)
        if entry is None:
            return self._receipt(code, False, f"缺陷编号 {code} 不存在或已归档")
        if entry.get("status") == STATUS_GRADED:
            # 幂等：已定级的保留原结果，重复提交只回执不改动，避免打断重试后重复定级。
            return self._receipt(code, True, "该缺陷此前已定级，保留原结果，本次不重复处理", repeated=True, entry=entry)
        if entry.get("status") != STATUS_PENDING:
            return self._receipt(code, False, f"当前状态为「{entry.get('status')}」，不允许确认定级")

        severity = str(getattr(item, "严重等级", "") or "").strip()
        if severity not in SEVERITY_LEVELS:
            return self._receipt(code, False, f"严重等级「{severity or '空'}」不在允许范围：{'、'.join(SEVERITY_LEVELS)}")
        deadline = str(getattr(item, "处理期限", "") or "").strip()
        if not deadline:
            return self._receipt(code, False, "处理期限不能为空，需随定级一起落上")
        try:
            date.fromisoformat(deadline)
        except ValueError:
            return self._receipt(code, False, f"处理期限「{deadline}」格式应为 YYYY-MM-DD")

        suggested = self._suggest_severity(entry)
        basis = str(getattr(item, "定级依据", None) or "").strip()
        if severity != suggested and not basis:
            return self._receipt(code, False, f"严重等级与建议值「{suggested}」不一致，必须填写定级依据")

        entry["严重等级"] = severity
        entry["处理期限"] = deadline
        entry["定级依据"] = basis or f"按缺陷类型建议值定级（{suggested}）"
        entry["status"] = STATUS_GRADED
        entry["缺陷状态"] = STATUS_GRADED
        entry["pending"] = True
        entry["abnormal"] = False
        return self._receipt(code, True, f"已定级为「{severity}」，处理期限 {deadline}", entry=entry)

    def _find_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("缺陷编号", "")) == code:
                return row
        return None

    @staticmethod
    def _suggest_severity(entry: dict[str, Any]) -> str:
        defect_type = str(entry.get("缺陷类型") or "").strip()
        return SEVERITY_BY_TYPE.get(defect_type, DEFAULT_SEVERITY)

    @staticmethod
    def _receipt(
        code: str,
        ok: bool,
        message: str,
        *,
        repeated: bool = False,
        entry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"缺陷编号": code, "ok": ok, "repeated": repeated, "message": message, "entry": entry}
