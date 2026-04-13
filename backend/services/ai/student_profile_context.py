# -*- coding: utf-8 -*-
"""Helpers for turning care profiles into gentle AI context."""

from __future__ import annotations

from sqlalchemy.orm import Session

from database.models.student import Student
from database.models.student_care_profile import StudentCareProfile


DIMENSION_LABELS = {
    "emotion_score": "情绪状态",
    "social_score": "同伴融入",
    "safety_score": "校园安全感",
    "family_score": "家庭支持",
    "study_score": "学习压力",
    "behavior_score": "行为稳定",
}


def build_student_profile_context(db: Session, student: Student) -> dict:
    profile = (
        db.query(StudentCareProfile)
        .filter(StudentCareProfile.student_id == student.id)
        .first()
    )
    if not profile:
        return {
            "has_profile": False,
            "summary": "暂无学生关怀画像，请仅基于成绩、标签和基础信息输出。",
            "state_lines": [],
            "care_suggestions": [],
            "prompt_block": "暂无学生关怀画像，请不要臆测学生心理或家庭情况。",
        }

    dimension_items = [
        ("emotion_score", float(profile.emotion_score or 0)),
        ("social_score", float(profile.social_score or 0)),
        ("safety_score", float(profile.safety_score or 0)),
        ("family_score", float(profile.family_score or 0)),
        ("study_score", float(profile.study_score or 0)),
        ("behavior_score", float(profile.behavior_score or 0)),
    ]
    sorted_dimensions = sorted(dimension_items, key=lambda item: item[1], reverse=True)
    focus_dimensions = sorted_dimensions[:2]

    state_lines = [_describe_dimension(name, value) for name, value in focus_dimensions if _describe_dimension(name, value)]
    care_suggestions = [_care_advice(name, value) for name, value in focus_dimensions if _care_advice(name, value)]

    trend_text = {
        "up": "近期状态波动上升，需要更细致关注",
        "down": "近期状态较前稳定一些，但仍需持续观察",
        "steady": "近期整体状态相对平稳",
    }.get((profile.trend or "steady").lower(), "近期整体状态相对平稳")

    risk_text = {
        "critical": "当前处于重点关怀状态",
        "high": "当前需要较多关怀关注",
        "medium": "当前存在一定需要关注的状态变化",
        "low": "当前整体状态较为平稳",
    }.get((profile.risk_level or "low").lower(), "当前整体状态较为平稳")

    prompt_lines = [
        f"学生关怀状态：{risk_text}；{trend_text}。",
        *[f"- {line}" for line in state_lines],
        *[f"- 建议表达方向：{item}" for item in care_suggestions],
        "注意：只允许使用温和、支持性的表达，不要直接输出“高风险”“心理问题”“家庭困难”等标签化措辞。",
    ]

    summary = "；".join([risk_text, trend_text] + state_lines) if state_lines else f"{risk_text}；{trend_text}"
    return {
        "has_profile": True,
        "summary": summary,
        "state_lines": state_lines,
        "care_suggestions": care_suggestions,
        "prompt_block": "\n".join(prompt_lines),
    }


def _describe_dimension(name: str, value: float) -> str:
    label = DIMENSION_LABELS.get(name, name)
    if value >= 0.75:
        mapping = {
            "emotion_score": f"{label}波动较明显，表达上宜更多强调理解、接纳与节奏调整",
            "social_score": f"{label}需要更多支持，适合鼓励其逐步建立合作与表达信心",
            "safety_score": f"{label}偏弱，表达上宜突出稳定感、信任感与日常支持",
            "family_score": f"{label}相对不足，表达上宜避免施压，强调学校与老师的陪伴",
            "study_score": f"{label}较大，建议在分析中强调拆解目标和循序渐进",
            "behavior_score": f"{label}有波动，表达上宜突出正向引导和过程提醒",
        }
        return mapping.get(name, f"{label}需要更多温和支持")
    if value >= 0.5:
        mapping = {
            "emotion_score": f"{label}存在一定起伏，可在表达中增加鼓励与稳定感",
            "social_score": f"{label}有一定压力，适合提醒其多参与合作和互动",
            "safety_score": f"{label}有一定敏感性，宜保持温和、稳妥的措辞",
            "family_score": f"{label}有一定压力，宜强调老师和学校的支持",
            "study_score": f"{label}偏大，可适当强调方法优化和节奏管理",
            "behavior_score": f"{label}有一定波动，适合结合具体行动建议",
        }
        return mapping.get(name, f"{label}有一定波动")
    return ""


def _care_advice(name: str, value: float) -> str:
    if value < 0.5:
        return ""
    mapping = {
        "emotion_score": "少一些直接施压，多一些对努力过程的肯定",
        "social_score": "鼓励其在合作、表达和同伴互动中慢慢建立信心",
        "safety_score": "强调老师可依靠、班级环境可支持，避免使用刺激性词语",
        "family_score": "语气以理解和支持为主，减少对家庭背景的直接提及",
        "study_score": "建议聚焦阶段目标、方法调整和学习节奏，而非单纯强调分数",
        "behavior_score": "建议强调自我管理、规律习惯和逐步改善",
    }
    return mapping.get(name, "")
