# -*- coding: utf-8 -*-
"""Tool helpers for teacher rule assistant."""

from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

from core.response import error_response
from database.models.class_ import Class
from database.models.rule_qa_feedback import RuleQaFeedback
from database.models.rule_qa_record import RuleQaRecord
from database.models.student import Student
from database.models.student_attendance import StudentAttendance
from database.models.student_behavior_event import StudentBehaviorEvent
from database.models.student_care_observation import StudentCareObservation
from database.models.student_care_profile import StudentCareProfile
from database.models.student_care_signal import StudentCareSignal
from database.models.student_family_contact import StudentFamilyContact
from database.models.teacher import Teacher
from database.models.user import User


def ensure_teacher_student_access(db: Session, current_user: User, student: Student) -> dict | None:
    if current_user.role == "admin":
        return None
    if current_user.role != "teacher":
        return error_response(code=403, msg="当前仅教师或管理员可查看教师版校规助手上下文")
    if not student.class_id:
        return error_response(code=403, msg="该学生当前未分班，暂不支持教师增强上下文")

    teacher = db.query(Teacher).filter(Teacher.name == current_user.name).first()
    if not teacher:
        return error_response(code=403, msg="未找到当前教师档案")

    class_row = db.query(Class).filter(Class.id == student.class_id).first()
    if not class_row or class_row.head_teacher_id != teacher.id:
        return error_response(code=403, msg="当前仅该学生所属班级班主任可查看增强上下文")
    return None


def build_student_fact_summary(db: Session, student_id: int) -> dict:
    attendance_rows = (
        db.query(StudentAttendance)
        .filter(StudentAttendance.student_id == student_id)
        .order_by(StudentAttendance.date.desc(), StudentAttendance.id.desc())
        .limit(10)
        .all()
    )
    behavior_rows = (
        db.query(StudentBehaviorEvent)
        .filter(StudentBehaviorEvent.student_id == student_id)
        .order_by(StudentBehaviorEvent.occurred_at.desc(), StudentBehaviorEvent.id.desc())
        .limit(10)
        .all()
    )
    return {
        "behavior_summary": _summarize_behavior(behavior_rows),
        "attendance_summary": _summarize_attendance(attendance_rows),
    }


def build_care_context_summary(db: Session, student_id: int) -> dict:
    profile = (
        db.query(StudentCareProfile)
        .filter(StudentCareProfile.student_id == student_id)
        .first()
    )
    signal_rows = (
        db.query(StudentCareSignal)
        .filter(StudentCareSignal.student_id == student_id)
        .order_by(StudentCareSignal.signal_weight.desc(), StudentCareSignal.id.desc())
        .limit(5)
        .all()
    )
    observation_rows = (
        db.query(StudentCareObservation)
        .filter(StudentCareObservation.student_id == student_id)
        .order_by(StudentCareObservation.observed_at.desc(), StudentCareObservation.id.desc())
        .limit(3)
        .all()
    )
    return {
        "care_hint": _summarize_care_hint(profile, signal_rows, observation_rows),
        "care_followup_advice": _build_care_followup_advice(profile, signal_rows, observation_rows),
    }


def build_family_contact_summary(db: Session, student_id: int) -> dict:
    rows = (
        db.query(StudentFamilyContact)
        .filter(StudentFamilyContact.student_id == student_id)
        .order_by(StudentFamilyContact.id.desc())
        .limit(3)
        .all()
    )
    if not rows:
        return {
            "parent_contact_advice": {
                "suggested": False,
                "reason": "近期未查询到家校联系记录，是否联系家长请结合事件重复性和班级沟通情况人工判断。",
            }
        }

    latest = rows[0]
    latest_summary = _clip_text(latest.summary, 36)
    return {
        "parent_contact_advice": {
            "suggested": True,
            "reason": f"近期已有{len(rows)}条家校联系记录，最近一次为“{latest.contact_type}: {latest_summary}”，建议延续沟通口径。",
        }
    }


def build_history_experience_summary(db: Session, question: str) -> dict:
    query_text = (question or "").strip()
    if not query_text:
        return {
            "history_summary": "当前未提供可匹配的历史问题文本。",
            "history_risk_hint": False,
            "history_feedback_count": 0,
        }

    records = db.query(RuleQaRecord).order_by(RuleQaRecord.id.desc()).limit(20).all()
    matched_record_ids = [
        item.id
        for item in records
        if item.question and (query_text[:6] in item.question or item.question[:6] in query_text)
    ]
    feedback_rows = (
        db.query(RuleQaFeedback)
        .filter(RuleQaFeedback.qa_record_id.in_(matched_record_ids or [-1]))
        .order_by(RuleQaFeedback.id.desc())
        .limit(10)
        .all()
    )

    down_rows = [item for item in feedback_rows if item.rating == "down"]
    adopted_rows = [item for item in feedback_rows if item.status in {"adopted", "revised"}]
    latest_reason = next((item.improvement_reason for item in down_rows if item.improvement_reason), "")

    lines = []
    if matched_record_ids:
        lines.append(f"历史上找到 {len(matched_record_ids)} 条相近问答记录。")
    else:
        lines.append("暂未找到足够相近的历史问答记录。")
    if down_rows:
        lines.append(f"其中有 {len(down_rows)} 条低满意反馈，建议老师对结论保持人工复核。")
    if adopted_rows:
        lines.append(f"有 {len(adopted_rows)} 条反馈已被管理员处理或修订。")
    if latest_reason:
        lines.append(f"最近一次低满意原因：{_clip_text(latest_reason, 32)}。")

    return {
        "history_summary": " ".join(lines),
        "history_risk_hint": len(down_rows) > 0,
        "history_feedback_count": len(feedback_rows),
    }


def _summarize_behavior(rows: list[StudentBehaviorEvent]) -> str:
    if not rows:
        return "近期未查询到行为事件记录。"

    type_counter = Counter(item.event_type for item in rows if item.event_type)
    level_counter = Counter(item.event_level for item in rows if item.event_level)
    latest = rows[0]
    top_types = "、".join(f"{name}{count}次" for name, count in type_counter.most_common(3))
    top_levels = "、".join(f"{name}{count}次" for name, count in level_counter.most_common(2))
    latest_desc = _clip_text(latest.event_desc, 30)
    return (
        f"近{len(rows)}条行为事件中，主要类型为{top_types}；"
        f"事件等级以{top_levels or '未标注'}为主；"
        f"最新记录为“{latest_desc}”。"
    )


def _summarize_attendance(rows: list[StudentAttendance]) -> str:
    if not rows:
        return "近期未查询到考勤记录。"

    status_counter = Counter(item.status for item in rows if item.status)
    latest = rows[0]
    top_status = "、".join(f"{name}{count}次" for name, count in status_counter.most_common(3))
    latest_remark = _clip_text(latest.remark, 24) if latest.remark else ""
    latest_remark_text = f"；最近一次备注：{latest_remark}" if latest_remark else ""
    return f"近{len(rows)}条考勤记录中，状态分布为{top_status}；最近一次状态为{latest.status}{latest_remark_text}。"


def _summarize_care_hint(
    profile: StudentCareProfile | None,
    signals: list[StudentCareSignal],
    observations: list[StudentCareObservation],
) -> str:
    if not profile and not signals and not observations:
        return "近期暂无学生关怀摘要，建议老师结合日常观察和校规情境综合判断。"

    parts: list[str] = []
    trend_text = {
        "up": "近期状态波动有所上升，沟通时宜更稳妥",
        "down": "近期状态较前期略有缓和，可继续稳定支持",
        "steady": "近期整体状态相对平稳，可保持日常关注",
    }
    if profile:
        parts.append(trend_text.get((profile.trend or "steady").lower(), "近期整体状态相对平稳"))

    top_dimensions = _top_profile_dimensions(profile)
    if top_dimensions:
        parts.append(f"当前更需要留意{'、'.join(top_dimensions)}方面的支持性沟通")

    if observations:
        parts.append(f"最近一次关怀观察提到“{_clip_text(observations[0].summary, 28)}”")
    elif signals:
        parts.append(f"近期关怀线索提示“{_clip_text(signals[0].signal_text, 28)}”")

    return "；".join(parts) + "。"


def _build_care_followup_advice(
    profile: StudentCareProfile | None,
    signals: list[StudentCareSignal],
    observations: list[StudentCareObservation],
) -> dict:
    high_attention = False
    reason_parts: list[str] = []

    if profile and float(profile.overall_risk or 0) >= 0.45:
        high_attention = True
        reason_parts.append("近期状态波动需要持续关注")

    if observations and observations[0].observation_level in {"medium", "high"}:
        high_attention = True
        reason_parts.append("已有中高等级关怀观察记录")

    weighted = [item for item in signals if float(item.signal_weight or 0) >= 0.3]
    if len(weighted) >= 2:
        high_attention = True
        reason_parts.append("近期关怀线索相对集中")

    if high_attention:
        return {
            "suggested": True,
            "reason": "；".join(reason_parts) or "建议老师继续保持跟进，并结合班级观察安排后续支持。",
        }
    return {
        "suggested": False,
        "reason": "当前未见需要立即升级处理的关怀摘要，可先按校规处置并持续观察。",
    }


def _top_profile_dimensions(profile: StudentCareProfile | None) -> list[str]:
    if not profile:
        return []
    mapping = [
        ("情绪", float(profile.emotion_score or 0)),
        ("同伴融入", float(profile.social_score or 0)),
        ("校园安全感", float(profile.safety_score or 0)),
        ("家庭支持", float(profile.family_score or 0)),
        ("学习压力", float(profile.study_score or 0)),
        ("行为稳定", float(profile.behavior_score or 0)),
    ]
    return [name for name, score in sorted(mapping, key=lambda item: item[1], reverse=True)[:2] if score >= 0.3]


def _clip_text(text: str | None, limit: int) -> str:
    value = (text or "").strip().replace("\n", " ")
    if len(value) <= limit:
        return value or "未填写"
    return f"{value[:limit]}..."
