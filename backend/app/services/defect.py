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

SEVERITY_LEVELS = ["一般", "严重", "危急"]
DEFAULT_SEVERITY = "一般"
# 各严重等级对应的默认处理期限（天），定级时随等级一起落到缺陷上。
DEADLINE_DAYS = {"危急": 1, "严重": 7, "一般": 30}
# 严重等级建议规则：按“所属设备 + 缺陷类型”的关键词命中，靠前的规则优先；
# 设备关键词为空表示不限设备。建议值只作预填，值班人调整后必须留下定级依据。
SEVERITY_RULES: list[tuple[tuple[str, ...], tuple[str, ...], str]] = [
    (("逆变器", "箱变"), ("起火", "冒烟", "漏电", "过热"), "危急"),
    (("汇流箱",), ("起火", "烧损", "进水", "漏电"), "危急"),
    (("组件", "组串"), ("热斑", "碎裂", "击穿", "起火"), "危急"),
    (("逆变器", "箱变"), ("通讯", "停机", "故障", "告警"), "严重"),
    (("汇流箱",), ("通讯", "故障", "防雷"), "严重"),
    (("组件", "组串"), ("衰减", "偏移", "遮挡", "为零", "偏低"), "严重"),
    ((), ("起火", "冒烟", "漏电"), "危急"),
    ((), ("故障", "停机", "过热", "进水"), "严重"),
]


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
        entry["status"] = STATUS_ORDER[0]
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
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"设备缺陷已{action}"

    def stats(self) -> list[dict[str, Any]]:
        """缺陷统计：待定级、处理中与超期未闭环数量，随每次定级实时重算。"""
        rows = store.rows(MODULE)
        today = date.today()
        overdue = 0
        for row in rows:
            if row.get("status") in ("已闭环", "已挂起"):
                continue
            try:
                deadline = date.fromisoformat(str(row.get("处理期限") or ""))
            except ValueError:
                continue
            if deadline < today:
                overdue += 1
        return [
            {"label": "待定级缺陷", "value": sum(1 for row in rows if row.get("status") == "待定级")},
            {"label": "处理中缺陷", "value": sum(1 for row in rows if row.get("status") == "处理中")},
            {"label": "超期未闭环", "value": overdue},
        ]

    def grade_suggestions(self, codes: list[str]) -> list[dict[str, Any]]:
        """按缺陷编号逐条给出严重等级与处理期限的建议值，找不到的编号也如实回执。"""
        suggestions: list[dict[str, Any]] = []
        for code in codes:
            entry = self._find_by_code(code)
            if entry is None:
                suggestions.append({"缺陷编号": code, "found": False, "建议说明": "缺陷不存在或已归档"})
                continue
            level, reason = self.suggest_severity(entry)
            suggestions.append({
                "缺陷编号": code,
                "found": True,
                "所属设备": entry.get("所属设备"),
                "缺陷类型": entry.get("缺陷类型"),
                "当前状态": entry.get("status"),
                "建议严重等级": level,
                "建议处理期限": self.suggest_deadline(level),
                "建议说明": reason,
            })
        return suggestions

    def batch_grade(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量确认定级：逐条处理、逐条回执。

        每条缺陷独立校验、独立落库：成功的立即生效且不回退，失败的只在回执里
        说明原因；提交中断时已定级的保留，重试时已定级缺陷按幂等处理，不会
        被重复定级，同一批次里重复的缺陷编号也只处理一次。
        """
        receipts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            code = str(item.get("缺陷编号") or "").strip()
            if not code:
                receipts.append({"缺陷编号": "", "ok": False, "message": "缺少缺陷编号，无法定位缺陷", "entry": None})
                continue
            if code in seen:
                continue
            seen.add(code)
            receipts.append(self._grade_one(code, item))
        return receipts

    def suggest_severity(self, entry: dict[str, Any]) -> tuple[str, str]:
        """按所属设备与缺陷类型命中规则，返回（建议严重等级，建议说明）。"""
        device = str(entry.get("所属设备") or "")
        defect_type = str(entry.get("缺陷类型") or "")
        for device_keywords, type_keywords, level in SEVERITY_RULES:
            if device_keywords and not any(keyword in device for keyword in device_keywords):
                continue
            if not any(keyword in defect_type for keyword in type_keywords):
                continue
            device_desc = "、".join(device_keywords) if device_keywords else "不限设备"
            reason = f"所属设备命中「{device_desc}」、缺陷类型命中「{'、'.join(type_keywords)}」，建议定为{level}"
            return level, reason
        return DEFAULT_SEVERITY, f"未命中特定规则，按默认建议定为{DEFAULT_SEVERITY}"

    def suggest_deadline(self, severity: str) -> str:
        """按严重等级给出默认处理期限：危急 1 天、严重 7 天、一般 30 天。"""
        days = DEADLINE_DAYS.get(severity, DEADLINE_DAYS[DEFAULT_SEVERITY])
        return (date.today() + timedelta(days=days)).isoformat()

    def _grade_one(self, code: str, item: dict[str, Any]) -> dict[str, Any]:
        entry = self._find_by_code(code)
        if entry is None:
            return {"缺陷编号": code, "ok": False, "message": f"缺陷 {code} 不存在或已归档", "entry": None}
        status = str(entry.get("status") or "")
        if status == "已定级":
            # 幂等：中断重试时保留此前定级结果，不重复处理、不算失败。
            return {"缺陷编号": code, "ok": True, "message": f"缺陷 {code} 此前已确认定级，本次未重复处理", "entry": dict(entry)}
        if status != "待定级":
            return {"缺陷编号": code, "ok": False, "message": f"缺陷 {code} 当前状态为「{status}」，只有待定级缺陷可以确认定级", "entry": None}
        severity = str(item.get("严重等级") or "").strip()
        if severity not in SEVERITY_LEVELS:
            return {"缺陷编号": code, "ok": False, "message": f"缺陷 {code} 的严重等级「{severity or '空'}」不在允许范围（{'、'.join(SEVERITY_LEVELS)}）", "entry": None}
        suggested, _ = self.suggest_severity(entry)
        basis = str(item.get("定级依据") or "").strip()
        if severity != suggested and not basis:
            return {"缺陷编号": code, "ok": False, "message": f"缺陷 {code} 的严重等级由建议值「{suggested}」调整为「{severity}」，必须填写定级依据", "entry": None}
        deadline = str(item.get("处理期限") or "").strip()
        if deadline:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                return {"缺陷编号": code, "ok": False, "message": f"缺陷 {code} 的处理期限「{deadline}」格式不正确，应为 YYYY-MM-DD", "entry": None}
        else:
            deadline = self.suggest_deadline(severity)
        entry["严重等级"] = severity
        entry["处理期限"] = deadline
        entry["定级依据"] = basis or f"按建议等级定级（{suggested}）"
        entry["status"] = "已定级"
        entry["缺陷状态"] = "已定级"
        entry["pending"] = True
        entry["abnormal"] = False
        return {"缺陷编号": code, "ok": True, "message": f"缺陷 {code} 已确认定级为「{severity}」，处理期限 {deadline}", "entry": dict(entry)}

    def _find_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("缺陷编号") or "") == code:
                return row
        return None
