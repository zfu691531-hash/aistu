# -*- coding: utf-8 -*-
"""Audit helpers for teacher rule assistant output."""

from __future__ import annotations


def audit_teacher_rule_result(result: dict) -> dict:
    policy_basis = result.get("policy_basis") or []
    sources = result.get("sources") or []
    student_context_summary = result.get("student_context_summary") or {}
    needs_manual_confirmation = result.get("needs_manual_confirmation") or []

    issues: list[str] = []
    if not policy_basis and not sources:
        issues.append("当前回答缺少明确校规依据，建议补充更具体的制度关键词后再判断。")

    care_hint = str(student_context_summary.get("care_hint") or "")
    if any(word in care_hint for word in ("高风险", "critical", "risk_level", "overall_risk")):
        issues.append("关怀摘要疑似包含敏感标签，需要进一步脱敏。")

    if not any("人工" in item or "正式" in item for item in needs_manual_confirmation):
        issues.append("回答缺少人工确认边界提示。")

    safe_result = dict(result)
    safe_result["student_context_summary"] = {
        key: value
        for key, value in student_context_summary.items()
        if not str(key).startswith("_")
    }
    safe_result["audit"] = {
        "passed": len(issues) == 0,
        "issues": issues,
    }
    return safe_result
