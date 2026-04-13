from __future__ import annotations

import asyncio
import json
import operator
from copy import deepcopy
from datetime import datetime, date, timedelta
from functools import lru_cache
from typing import Annotated, TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from core.config import settings
from core.response import error_response, success_response
from database.models.student_care_agent_record import StudentCareAgentRecord
from database.models.student import Student
from database.models.class_ import Class
from database.models.teacher import Teacher
from schemas.student_care_agent import (
    StudentCareAgentDimension,
    StudentCareAgentEvalOut,
    StudentCareAgentReviewUpdate,
    StudentCareAgentResult,
)
from services import student_care_service
from services.ai.base import ai_client
from services.student_care_graph_service import student_care_graph_service
from services.student_care_schema_guard import ensure_student_care_schema
from services.web_search_service import search_web
from database.models.student_tag_definition import StudentTagDefinition
from utils.logger import logger


DIMENSION_LABELS = {
    "emotion": "情绪状态",
    "social": "社交融入",
    "safety": "校园安全",
    "family": "家庭支持",
    "study": "学习压力",
    "behavior": "行为稳定",
}

RISK_LEVELS = {"low", "attention", "medium", "high"}

OVERALL_WEIGHTS = {
    "emotion": 0.18,
    "social": 0.18,
    "safety": 0.18,
    "family": 0.18,
    "study": 0.16,
    "behavior": 0.12,
}

SOURCE_LABELS = {
    "student_tag": "学生标签",
    "score": "成绩记录",
    "student_status": "学生状态",
    "attendance": "出勤记录",
    "behavior_event": "行为事件",
    "family_contact": "家校沟通",
    "assistant_summary": "AI对话摘要",
    "care_observation": "关怀观察",
    "graph": "关系图谱",
    "major_incident": "恶性事件传导",
}

EXPERT_PROMPTS = {
    "emotion": "你是情绪状态风险研判专家，只能基于校内事实与信号判断，不得编造。",
    "social": "你是社交融入风险研判专家，只能基于校内事实与信号判断，不得编造。",
    "safety": "你是校园安全风险研判专家，只能基于校内事实与信号判断，不得编造。",
    "family": "你是家庭支持风险研判专家，只能基于校内事实与信号判断，不得编造。",
    "study": "你是学习压力风险研判专家，只能基于校内事实与信号判断，不得编造。",
    "behavior": "你是行为稳定风险研判专家，只能基于校内事实与信号判断，不得编造。",
}


ALLOWED_EMOTION_SOURCES = {
    "score",
    "attendance",
    "behavior_event",
    "family_contact",
    "assistant_summary",
    "care_observation",
}

EMOTION_LOW_SCORE_MAX = 0.29
EMOTION_ATTENTION_SCORE = 0.3
EMOTION_MEDIUM_SCORE = 0.5
AGENT_EXPERT_TIMEOUT_SECONDS = 25
AGENT_INTEGRATION_TIMEOUT_SECONDS = 45

STUDENT_CARE_WEB_QUERY_RULES = {
    ("attendance", "behavior"): "学生迟到缺勤早退 班主任关怀干预建议",
    ("behavior_event", "behavior"): "学生违纪行为稳定 班主任关怀干预建议",
    ("behavior_event", "safety"): "校园冲突安全风险 学生关怀处置建议",
    ("care_observation", "emotion"): "学生情绪观察 班主任关怀谈话建议",
    ("care_observation", "social"): "学生社交融入观察 班级支持建议",
    ("care_observation", "safety"): "校园安全线索 学生保护处置建议",
    ("care_observation", "study"): "学生学习压力观察 学业支持建议",
    ("care_observation", "behavior"): "学生行为变化观察 班主任支持建议",
    ("care_observation", "family"): "学生家庭支持观察 家校协同建议",
    ("family_contact", "family"): "家校沟通 家庭支持不足 学生关怀建议",
}


class StudentCareGraphState(TypedDict, total=False):
    prompt_payload: dict
    profile: dict
    signals: list[dict]
    actions: list[str]
    light_model: str
    strong_model: str
    expert_outputs: Annotated[list[dict], operator.add]
    raw_text: str | None
    fallback: bool
    error_msg: str | None
    result: StudentCareAgentResult | None


def _risk_level(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.5:
        return "medium"
    if score >= 0.3:
        return "attention"
    return "low"


def _clamp_score(value: float) -> float:
    return round(min(max(value, 0.0), 1.0), 4)


def _truncate_text(value: str, limit: int = 80) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _is_technical_text(value: str) -> bool:
    text = str(value or "")
    markers = [
        "validation error",
        "pydantic",
        "input should be a valid string",
        "bayes_",
        "bayes后验概率",
        "linear_score",
        "profile.",
        "tag_definitions",
        "care_fact_context",
        "tag_web_context",
        "signal_type",
        "signals中无任何",
        "evidence.",
        "posterior",
        "final_score",
        "absence_of_evidence",
        "absence_of_risk",
        "tag_mismatch",
        "zero_linear_score",
        "linear_score_zero",
        "系统计算值",
        "student.tags",
        "behavior_score=",
    ]
    lowered = text.lower()
    return any(marker in lowered or marker in text for marker in markers)


def _risk_hint_text(dimension: str, score: float, evidence: list[str]) -> str:
    label = DIMENSION_LABELS.get(dimension, dimension)
    if evidence:
        if score >= 0.5:
            return f"{label}方面已有较明确风险线索，建议尽快跟进核实。"
        if score >= 0.3:
            return f"{label}方面出现需要关注的线索，建议持续观察并补充核实。"
        return f"{label}方面目前风险较低，但建议继续保持常规关注。"
    if score >= 0.3:
        return f"{label}方面暂缺充分证据，建议结合后续表现继续观察。"
    return "暂无明显风险线索。"


def _format_signed_score(value: float) -> str:
    rounded = round(float(value or 0), 4)
    if rounded > 0:
        return f"+{rounded:.4f}"
    if rounded < 0:
        return f"{rounded:.4f}"
    return "0.0000"


def _missing_signal_hint(dimension: str) -> str:
    return {
        "emotion": "当前缺少出勤备注、关怀谈话、家校沟通等情绪补充证据。",
        "social": "当前缺少同伴互动、班级融入、教师观察等社交补充证据。",
        "safety": "当前缺少冲突、受伤、欺凌、异常出勤等直接安全证据。",
        "family": "当前缺少家校沟通、家庭支持观察等补充证据。",
        "study": "当前缺少作业、课堂表现、教师评语等学习补充证据。",
        "behavior": "当前缺少违纪、冲突、异常出勤、教师观察等行为补充证据。",
    }.get(dimension, "当前缺少更多补充证据。")


def _build_dimension_score_details(dimension: str, profile: dict, signals: list[dict]) -> tuple[list[str], list[dict]]:
    final_score = float(profile.get(f"{dimension}_score") or 0.0)
    linear_score = profile.get(f"{dimension}_linear_score")
    base_score = float(linear_score if linear_score is not None else final_score)
    label = DIMENSION_LABELS.get(dimension, dimension)

    dimension_signals = sorted(
        [
            item for item in signals
            if item.get("dimension") == dimension and float(item.get("signal_weight") or 0) > 0
        ],
        key=lambda item: float(item.get("signal_weight") or 0),
        reverse=True,
    )[:3]

    breakdown = [
        {
            "label": "基础得分",
            "value": round(base_score, 4),
            "display": f"{base_score:.4f}",
            "note": "基于规则画像的初始得分。",
        }
    ]
    explanation = [f"基础得分：{base_score:.2f}。"]

    for item in dimension_signals:
        weight = round(float(item.get("signal_weight") or 0), 4)
        source_label = SOURCE_LABELS.get(item.get("source"), item.get("source") or "信号")
        note = _truncate_text(item.get("signal_text") or f"{source_label}线索", 48)
        breakdown.append(
            {
                "label": source_label,
                "value": weight,
                "display": _format_signed_score(weight),
                "note": note,
            }
        )
        explanation.append(f"{source_label}：{note}，对{label}贡献 {weight:.2f}。")

    if not dimension_signals:
        breakdown.append(
            {
                "label": "补充证据",
                "value": 0.0,
                "display": "0.0000",
                "note": _missing_signal_hint(dimension),
            }
        )
        explanation.append(_missing_signal_hint(dimension))

    bayes_posterior = profile.get(f"{dimension}_bayes_posterior")
    if bayes_posterior is not None:
        bayes_delta = round(final_score - base_score, 4)
        breakdown.append(
            {
                "label": "贝叶斯修正",
                "value": bayes_delta,
                "display": _format_signed_score(bayes_delta),
                "note": f"后验概率 {float(bayes_posterior):.2f} 参与修正。",
            }
        )
        explanation.append(
            f"贝叶斯辅助层后验概率约为 {float(bayes_posterior):.2f}，对最终得分修正 {_format_signed_score(bayes_delta)}。"
        )

    breakdown.append(
        {
            "label": "最终得分",
            "value": round(final_score, 4),
            "display": f"{final_score:.4f}",
            "note": f"{label}当前最终判定得分。",
        }
    )
    explanation.append(f"最终得分：{final_score:.2f}。")
    return explanation, breakdown


def _stringify_evidence_item(item) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        text = str(item.get("text") or "").strip()
        key = str(item.get("key") or item.get("type") or "").strip()
        source = str(item.get("source") or "").strip()
        if text:
            if source == "graph":
                return _truncate_text("".join(chr(i) for i in (20851, 31995, 22270, 35889, 65306)) + text)
            return _truncate_text(text)
        if _is_technical_text(key) or _is_technical_text(source):
            return ""
        if source == "graph" and key:
            return "".join(chr(i) for i in (20851, 31995, 22270, 35889, 65306)) + key
        if key and source:
            return f"{key}（来源：{source}）"
        if key:
            return key
    return _truncate_text(str(item))


def _contains_internal_marker(value: str) -> bool:
    text = str(value or "").strip()
    lowered = text.lower()
    markers = [
        "tag_social",
        "signal_irrelevance",
        "overall_risk",
        "teacher_reviews",
        "behavior_score",
        "student.tags",
        "tag_mismatch",
        "zero_linear_score",
        "linear_score_zero",
        "profile.",
        "care_fact_context",
        "tag_web_context",
        "signal_type",
        "posterior",
        "final_score",
        "bayes_",
    ]
    return any(marker in lowered for marker in markers)


def _normalize_evidence_list(raw_evidence) -> list[str]:
    if not isinstance(raw_evidence, list):
        return []
    results = []
    for item in raw_evidence:
        text = _stringify_evidence_item(item)
        if not text or _is_technical_text(text) or _contains_internal_marker(text):
            continue
        results.append(text)
    deduped = []
    seen = set()
    for item in results:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped[:4]


def _normalize_dimension_payload(dimension: str, payload: dict) -> dict:
    normalized = dict(payload or {})
    score = _clamp_score(float(normalized.get("score") or 0))
    evidence = _normalize_evidence_list(normalized.get("evidence"))
    summary = str(normalized.get("summary") or "").strip()
    if not summary or _is_technical_text(summary) or _contains_internal_marker(summary) or len(summary) > 120:
        summary = _risk_hint_text(dimension, score, evidence)

    normalized["dimension"] = normalized.get("dimension") or dimension
    normalized["score"] = score
    normalized["risk_level"] = normalized.get("risk_level") or _risk_level(score)
    normalized["summary"] = " ".join(summary.split()).strip()
    normalized["evidence"] = evidence
    return normalized


def _humanize_expert_error(error_msg: str | None, dimension: str) -> str | None:
    if not error_msg:
        return None
    label = DIMENSION_LABELS.get(dimension, dimension)
    text = str(error_msg)
    lowered = text.lower()
    if "证据不足" in text or "维度不匹配" in text:
        return text
    if "无法解析为 json" in text or "json" in lowered:
        return f"{label}专家输出格式不稳定，已自动切换为规则兜底结果。"
    if "validation error" in lowered or "input should be a valid" in lowered or "pydantic" in lowered:
        return f"{label}专家返回内容不规范，系统已自动整理并采用兜底结果。"
    if "timeout" in lowered or "超时" in text:
        return f"{label}专家响应超时，系统已自动切换为规则兜底结果。"
    if "维度不匹配" in text:
        return f"{label}专家返回维度异常，系统已自动切换为规则兜底结果。"
    return f"{label}专家本次输出不稳定，系统已自动采用更稳妥的兜底结果。"


def _render_chat_prompt(system_template: str, user_template: str, values: dict) -> tuple[str, str]:
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_template),
            ("human", user_template),
        ]
    )
    messages = prompt.invoke(values).to_messages()
    return messages[0].content, messages[1].content


def _build_prompt_payload(data: dict) -> tuple[str, str]:
    system_template = (
        "你是校园学生关怀研判助手。"
        "请基于给定的校内事实与信号进行研判，不得编造事实。"
        "web_context 只能作为通用教育参考，不得作为学生个人风险证据。"
        "必须输出严格 JSON，不要输出多余文字。"
        "JSON 必须包含：overall_score(0-1), overall_level,"
        "dimensions(数组), suggestions(数组)。"
        "dimensions 每项包含：dimension, score(0-1), risk_level, summary, evidence(数组)。"
        "如果 tag_definitions 标注为正向或中性，不得作为风险依据。"
    )
    user_template = "以下是学生关怀画像的校内事实数据，请输出研判 JSON：\n{payload}"
    return _render_chat_prompt(system_template, user_template, {"payload": json.dumps(data, ensure_ascii=False)})


def _resolve_tag_definitions(
    db: Session,
    student: dict,
) -> tuple[list[dict], list[str]]:
    class_id = student.get("class_id")
    grade = student.get("grade")
    query = db.query(StudentTagDefinition)
    records = query.all()
    filtered = []
    for item in records:
        if item.scope_type == "school":
            filtered.append(item)
        elif item.scope_type == "grade" and grade and item.scope_value == grade:
            filtered.append(item)
        elif item.scope_type == "class" and class_id and item.scope_value == str(class_id):
            filtered.append(item)

    priority = {"class": 3, "grade": 2, "school": 1}
    resolved: dict[str, StudentTagDefinition] = {}
    for item in filtered:
        key = item.tag_text
        current = resolved.get(key)
        if not current or priority[item.scope_type] > priority[current.scope_type]:
            resolved[key] = item

    tags = [item.strip() for item in (student.get("tags") or "").split(",") if item.strip()]
    unknown = [tag for tag in tags if tag not in resolved]
    definitions = [
        {
            "tag_text": item.tag_text,
            "polarity": item.polarity,
            "dimension": item.dimension,
            "description": item.description,
            "scope_type": item.scope_type,
            "scope_value": item.scope_value,
        }
        for item in resolved.values()
    ]
    return definitions, unknown


async def _fetch_tag_web_context(tags: list[str]) -> list[dict]:
    if not tags:
        return []
    tasks = [search_web(tag) for tag in tags[:3]]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    context = []
    for tag, result in zip(tags[:3], results):
        if isinstance(result, Exception):
            continue
        context.append({"tag": tag, "summary": result.get("summary", ""), "sources": result.get("sources", [])})
    return context


async def _fetch_student_care_web_context(signals: list[dict]) -> list[dict]:
    """Fetch generic public context for care signals without sending student PII."""
    if not settings.STUDENT_CARE_FACT_WEB_SEARCH:
        return []

    query_map: dict[str, dict] = {}
    for item in signals:
        source = item.get("source")
        dimension = item.get("dimension")
        query = STUDENT_CARE_WEB_QUERY_RULES.get((source, dimension))
        if query:
            query_map[query] = {
                "source": source,
                "dimension": dimension,
                "query": query,
            }

    if not query_map:
        return []

    contexts = list(query_map.values())[:4]
    tasks = [search_web(item["query"]) for item in contexts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    web_context = []
    for item, result in zip(contexts, results):
        if isinstance(result, Exception):
            continue
        web_context.append(
            {
                **item,
                "summary": result.get("summary", ""),
                "sources": result.get("sources", []),
            }
        )
    return web_context


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def _build_care_fact_context(signals: list[dict]) -> dict:
    context = {
        "attendance": [],
        "behavior_events": [],
        "care_observations": [],
        "family_contacts": [],
        "assistant_summaries": [],
    }
    for item in signals:
        source = item.get("source")
        text = item.get("signal_text")
        if not text:
            continue
        row = {
            "dimension": item.get("dimension"),
            "signal_type": item.get("signal_type"),
            "text": text,
        }
        if source == "attendance":
            context["attendance"].append(row)
        elif source == "behavior_event":
            context["behavior_events"].append(row)
        elif source == "care_observation":
            context["care_observations"].append(row)
        elif source == "family_contact":
            context["family_contacts"].append(row)
        elif source == "assistant_summary":
            context["assistant_summaries"].append(row)
    return {key: value[:5] for key, value in context.items()}


def _build_graph_context(signals: list[dict], profile: dict) -> dict:
    graph_signals = [
        {
            "dimension": item.get("dimension"),
            "signal_type": item.get("signal_type"),
            "text": item.get("signal_text"),
            "weight": item.get("signal_weight"),
        }
        for item in signals
        if item.get("source") == "graph"
    ][:5]
    safety_bayes = (profile or {}).get("bayes_results", {}).get("safety", {})
    return {
        "enabled": bool(getattr(student_care_graph_service, "enabled", False)),
        "graph_signals": graph_signals,
        "relationship_summary": [
            item.get("text")
            for item in graph_signals
            if item.get("text")
        ][:3],
        "safety_graph_evidence": [
            item.get("key")
            for item in safety_bayes.get("evidence_details", [])
            if str(item.get("key", "")).startswith("graph_")
        ],
    }


def _list_recent_teacher_reviews(db: Session, student_id: int, limit: int = 3) -> list[dict]:
    if not hasattr(db, "query"):
        return []
    records = (
        db.query(StudentCareAgentRecord)
        .filter(
            StudentCareAgentRecord.student_id == student_id,
            StudentCareAgentRecord.review_status == "confirmed",
        )
        .order_by(StudentCareAgentRecord.confirmed_at.desc(), StudentCareAgentRecord.id.desc())
        .limit(limit)
        .all()
    )
    reviews = []
    for item in records:
        reviewed_result = item.reviewed_result_json or item.result_json or {}
        reviews.append(
            {
                "record_id": item.id,
                "confirmed_at": str(item.confirmed_at) if item.confirmed_at else None,
                "confirmed_by": item.confirmed_by,
                "resolution_status": item.resolution_status,
                "review_labels": item.review_labels_json or {},
                "teacher_notes": item.teacher_notes,
                "reviewed_result": reviewed_result,
            }
        )
    return reviews


def _get_latest_confirmed_teacher_feedback(db: Session, student_id: int) -> dict:
    if not hasattr(db, "query"):
        return {}
    record = (
        db.query(StudentCareAgentRecord)
        .filter(
            StudentCareAgentRecord.student_id == student_id,
            StudentCareAgentRecord.review_status == "confirmed",
        )
        .order_by(StudentCareAgentRecord.confirmed_at.desc(), StudentCareAgentRecord.id.desc())
        .first()
    )
    if not record:
        return {}

    reviewed_result = record.reviewed_result_json or record.result_json or {}
    social_dimension = next(
        (
            item
            for item in reviewed_result.get("dimensions", [])
            if isinstance(item, dict) and item.get("dimension") == "social"
        ),
        {},
    )
    suggestions = reviewed_result.get("suggestions") or []
    return {
        "record_id": record.id,
        "confirmed_at": str(record.confirmed_at) if record.confirmed_at else None,
        "resolution_status": record.resolution_status,
        "teacher_notes": record.teacher_notes,
        "review_labels": record.review_labels_json or {},
        "social_summary": social_dimension.get("summary") or "",
        "social_evidence": [str(item) for item in (social_dimension.get("evidence") or []) if str(item).strip()][:3],
        "suggestions": [str(item) for item in suggestions if str(item).strip()][:3],
    }


def _build_major_incident_context(profile: dict, signals: list[dict]) -> dict:
    detected = bool(profile.get("major_incident_detected"))
    propagation_details = profile.get("major_incident_propagation_details") or []
    evidence = [str(item) for item in (profile.get("major_incident_evidence") or []) if str(item).strip()][:4]
    impacted_dimensions = []

    dimension_breakdown = profile.get("dimension_breakdown") or {}
    for dimension in profile.get("major_incident_impacted_dimensions") or []:
        detail = dimension_breakdown.get(dimension) or {}
        impacted_dimensions.append(
            {
                "dimension": dimension,
                "label": DIMENSION_LABELS.get(dimension, dimension),
                "base_score": round(float(detail.get("base_score") or 0), 4),
                "spillover_score": round(float(detail.get("spillover_score") or 0), 4),
                "total_score": round(float(detail.get("total_score") or profile.get(f"{dimension}_score") or 0), 4),
            }
        )

    propagation_signals = [
        {
            "dimension": item.get("dimension"),
            "signal_type": item.get("signal_type"),
            "signal_text": item.get("signal_text"),
            "signal_weight": round(float(item.get("signal_weight") or 0), 4),
        }
        for item in signals
        if item.get("source") == "major_incident"
    ][:6]

    return {
        "detected": detected,
        "types": profile.get("major_incident_types") or [],
        "confidence": round(float(profile.get("major_incident_confidence") or 0), 4),
        "evidence": evidence,
        "impacted_dimensions": impacted_dimensions,
        "propagation_details": propagation_details,
        "propagation_signals": propagation_signals,
        "bn_analysis": profile.get("major_incident_bn") or {},
    }


def _sanitize_reviewed_result(original: dict, reviewed: dict) -> dict:
    sanitized = deepcopy(original or {})
    reviewed = reviewed or {}
    if isinstance(reviewed.get("suggestions"), list):
        sanitized["suggestions"] = [str(item) for item in reviewed.get("suggestions", []) if str(item).strip()]

    reviewed_dimensions = {
        item.get("dimension"): item
        for item in reviewed.get("dimensions", [])
        if isinstance(item, dict) and item.get("dimension")
    }
    sanitized_dimensions = []
    for item in sanitized.get("dimensions", []) or []:
        if not isinstance(item, dict):
            continue
        merged = deepcopy(item)
        reviewed_item = reviewed_dimensions.get(item.get("dimension")) or {}
        if isinstance(reviewed_item.get("summary"), str):
            merged["summary"] = reviewed_item["summary"]
        if isinstance(reviewed_item.get("evidence"), list):
            merged["evidence"] = [str(row) for row in reviewed_item["evidence"] if str(row).strip()]
        sanitized_dimensions.append(merged)
    sanitized["dimensions"] = sanitized_dimensions
    sanitized["overall_score"] = original.get("overall_score", sanitized.get("overall_score", 0))
    sanitized["overall_level"] = original.get("overall_level", sanitized.get("overall_level", "low"))
    sanitized["overall_breakdown"] = original.get("overall_breakdown")
    return sanitized


def _serialize_agent_record(row: StudentCareAgentRecord) -> dict:
    return {
        "id": row.id,
        "student_id": row.student_id,
        "model_name": row.model_name,
        "timeout_seconds": row.timeout_seconds,
        "fallback": bool(row.fallback),
        "error_msg": row.error_msg,
        "input_snapshot": row.input_snapshot,
        "result": row.result_json,
        "review_status": row.review_status or "pending",
        "reviewed_result": row.reviewed_result_json,
        "review_labels": row.review_labels_json or {},
        "teacher_notes": row.teacher_notes,
        "resolution_status": row.resolution_status,
        "confirmed_by": row.confirmed_by,
        "confirmed_at": str(row.confirmed_at) if row.confirmed_at else None,
        "raw_text": row.raw_text,
        "created_at": str(row.created_at) if row.created_at else None,
    }


def _build_fallback_result(profile: dict, signals: list[dict], actions: list[str]) -> StudentCareAgentResult:
    signal_map: dict[str, list[str]] = {key: [] for key in DIMENSION_LABELS.keys()}
    for item in signals:
        dimension = item.get("dimension")
        if dimension in signal_map:
            signal_map[dimension].append(item.get("signal_text") or "")

    dimensions: list[StudentCareAgentDimension] = []
    for key in DIMENSION_LABELS.keys():
        score = float(profile.get(f"{key}_score") or 0)
        evidence = [text for text in signal_map.get(key, []) if text][:2]
        summary = "暂无明显风险线索" if not evidence else "结合近期信号需要持续关注"
        dimensions.append(
            _attach_dimension_details(
                StudentCareAgentDimension(
                    dimension=key,
                    score=score,
                    risk_level=_risk_level(score),
                    summary=summary,
                    evidence=evidence,
                ),
                profile,
                signals,
            )
        )

    overall_score = float(profile.get("overall_risk") or 0)
    overall_level = profile.get("risk_level") or _risk_level(overall_score)
    suggestions = actions[:3] if actions else ["建议持续观察并保持常规关怀。"]
    return StudentCareAgentResult(
        overall_score=overall_score,
        overall_level=overall_level,
        suggestions=suggestions,
        dimensions=dimensions,
    )


def _build_integrated_result_from_experts(
    profile: dict,
    signals: list[dict],
    actions: list[str],
    expert_outputs: list[dict],
) -> StudentCareAgentResult:
    expert_map = {item.get("dimension"): item for item in expert_outputs}
    dimensions: list[StudentCareAgentDimension] = []
    for dimension in DIMENSION_LABELS.keys():
        expert_output = expert_map.get(dimension) or {}
        result_payload = expert_output.get("result")
        try:
            dimension_result = StudentCareAgentDimension.model_validate(result_payload)
            _validate_dimension_result(dimension_result, expected_dimension=dimension)
        except Exception:
            dimension_result = _build_expert_fallback(dimension, profile, signals)
        dimension_result = _attach_dimension_details(dimension_result, profile, signals)
        dimensions.append(dimension_result)

    overall_score = _clamp_score(
        sum(float(item.score or 0) * OVERALL_WEIGHTS.get(item.dimension, 0.0) for item in dimensions)
    )
    suggestions = actions[:3] if actions else _build_integrated_suggestions(dimensions)
    return StudentCareAgentResult(
        overall_score=overall_score,
        overall_level=_risk_level(overall_score),
        suggestions=suggestions,
        dimensions=dimensions,
    )


def _build_integrated_suggestions(dimensions: list[StudentCareAgentDimension]) -> list[str]:
    sorted_dimensions = sorted(dimensions, key=lambda item: float(item.score or 0), reverse=True)
    suggestions = []
    for item in sorted_dimensions:
        if float(item.score or 0) < 0.3:
            continue
        label = DIMENSION_LABELS.get(item.dimension, item.dimension)
        evidence = "；".join((item.evidence or [])[:1])
        if evidence:
            suggestions.append(f"优先跟进{label}线索：{evidence}")
        else:
            suggestions.append(f"优先跟进{label}风险，并补充核实事实依据。")
        if len(suggestions) >= 3:
            break
    return suggestions or ["建议持续观察并保持常规关怀。"]


def _build_overall_breakdown(result: StudentCareAgentResult) -> dict:
    dimensions = result.dimensions or []
    items = []
    total = 0.0
    for item in dimensions:
        key = item.dimension
        weight = OVERALL_WEIGHTS.get(key, 0.0)
        score = float(item.score or 0)
        contribution = round(score * weight, 4)
        total += contribution
        items.append(
            {
                "dimension": key,
                "label": DIMENSION_LABELS.get(key, key),
                "score": round(score, 4),
                "weight": weight,
                "contribution": contribution,
            }
        )
    total = round(total, 4)
    overall_score = round(float(result.overall_score or 0), 4)
    return {
        "formula": "情绪*0.18 + 社交*0.18 + 安全*0.18 + 家庭*0.18 + 学习*0.16 + 行为*0.12",
        "items": sorted(items, key=lambda x: x["contribution"], reverse=True),
        "sum": total,
        "overall_score": overall_score,
        "delta": round(overall_score - total, 4),
    }


def _build_review_suggestions(
    dimensions: list[StudentCareAgentDimension],
    major_incident_context: dict | None = None,
) -> list[dict]:
    major_incident_context = major_incident_context or {}
    if major_incident_context.get("detected"):
        secondary_checks = []
        for item in major_incident_context.get("impacted_dimensions") or []:
            label = item.get("label") or DIMENSION_LABELS.get(item.get("dimension"), item.get("dimension"))
            spillover = float(item.get("spillover_score") or 0)
            if spillover <= 0:
                continue
            secondary_checks.append(f"核查{label}是否已出现事件后的次生波动（传导贡献 {spillover:.2f}）")
        checks = [
            "先核实安全事实是否仍在持续，包括是否仍存在冲突、欺凌、威胁或围堵。",
            "再核实学生是否已出现明显情绪受损，如紧张警觉、害怕、低落或回避表达。",
        ]
        checks.extend(secondary_checks)
        if not secondary_checks:
            checks.append("继续前瞻核查社交退缩、学习下滑和行为波动等次生影响是否开始显现。")

        suggestions = [
            {
                "dimension": "safety",
                "label": DIMENSION_LABELS.get("safety", "safety"),
                "priority": "high",
                "title": "优先核查恶性事件是否仍持续",
                "checks": checks[:3],
            }
        ]
        for item in major_incident_context.get("impacted_dimensions") or []:
            dimension = item.get("dimension")
            if dimension not in DIMENSION_LABELS or dimension == "safety":
                continue
            label = item.get("label") or DIMENSION_LABELS.get(dimension, dimension)
            suggestions.append(
                {
                    "dimension": dimension,
                    "label": label,
                    "priority": "medium",
                    "title": f"跟进{label}次生影响",
                    "checks": _dimension_review_checks(dimension)[:2],
                }
            )
            if len(suggestions) >= 3:
                break
        return suggestions

    sorted_dimensions = sorted(dimensions, key=lambda item: float(item.score or 0), reverse=True)
    suggestions = []
    for item in sorted_dimensions:
        score = float(item.score or 0)
        if score < 0.3:
            continue
        label = DIMENSION_LABELS.get(item.dimension, item.dimension)
        evidence = [str(row).strip() for row in (item.evidence or []) if str(row).strip()][:2]
        checks = []
        if evidence:
            checks.append(f"先核对这些线索是否仍在持续：{'；'.join(evidence)}")
        checks.extend(_dimension_review_checks(item.dimension))
        deduped_checks = []
        seen = set()
        for check in checks:
            if check in seen:
                continue
            seen.add(check)
            deduped_checks.append(check)
        suggestions.append(
            {
                "dimension": item.dimension,
                "label": label,
                "priority": "high" if score >= 0.5 else "medium",
                "title": f"优先核查{label}",
                "checks": deduped_checks[:3],
            }
        )
        if len(suggestions) >= 3:
            break
    return suggestions


def _dimension_review_checks(dimension: str) -> list[str]:
    mapping = {
        "social": [
            "观察近一周课间、班级活动和小组合作中的同伴互动情况。",
            "向班主任或任课老师核实是否存在独处、被动回避或同伴排斥。",
            "确认是否已经安排同伴支持、活动参与或班级融入干预。",
        ],
        "emotion": [
            "核对近一周情绪波动是否持续，必要时补充一次关怀谈话记录。",
            "向班主任确认是否出现明显低落、易怒、回避交流等状态变化。",
            "结合家校沟通判断情绪风险是否与近期事件相关。",
        ],
        "safety": [
            "核查是否存在冲突、欺凌、受威胁或受伤等直接安全事实。",
            "向相关老师确认近期是否出现需要立即处置的校园安全线索。",
            "如线索明确，优先确认保护措施和后续跟进安排。",
        ],
        "family": [
            "补充最近一次家校沟通，确认当前家庭支持是否稳定。",
            "核实是否存在监护缺位、沟通冲突或照护资源不足。",
            "确认家庭端是否愿意配合后续跟进。",
        ],
        "study": [
            "核对近期作业、课堂表现和成绩变化是否一致指向学习压力。",
            "向任课老师确认是否存在明显的任务拖延、畏难或状态下滑。",
            "区分学业困难本身与情绪、家庭因素外溢带来的影响。",
        ],
        "behavior": [
            "核查近两周出勤、违纪或课堂行为波动是否仍在持续。",
            "向班主任确认是否存在回避参与、冲动或明显失稳表现。",
            "区分偶发事件与持续性行为风险，避免把单次事件看成长期问题。",
        ],
    }
    return mapping.get(dimension, ["建议结合最近校内事实补充一次人工核查。"])


def _build_explanation_highlights(
    result: StudentCareAgentResult,
    major_incident_context: dict | None = None,
) -> list[str]:
    major_incident_context = major_incident_context or {}
    dimensions = sorted(result.dimensions or [], key=lambda item: float(item.score or 0), reverse=True)
    highlights = []
    if major_incident_context.get("detected"):
        impacted = [item.get("label") for item in major_incident_context.get("impacted_dimensions") if item.get("label")]
        if impacted:
            highlights.append(
                "当前属于恶性事件后阶段，除安全事实外，还要前瞻核查"
                + "、".join(impacted[:3])
                + "等次生影响。"
            )
        else:
            highlights.append("当前属于恶性事件后阶段，核查重点应从安全事实延伸到后续情绪、社交和学习影响。")
    if dimensions:
        top = dimensions[0]
        top_label = DIMENSION_LABELS.get(top.dimension, top.dimension)
        highlights.append(f"当前主要风险重心在{top_label}，建议优先核查这一维度。")
    elevated = [DIMENSION_LABELS.get(item.dimension, item.dimension) for item in dimensions if float(item.score or 0) >= 0.3]
    if len(elevated) >= 2:
        highlights.append(f"目前同时受{elevated[0]}、{elevated[1]}影响，核查时要注意维度间是否存在传导。")
    review_suggestions = result.review_suggestions or []
    if review_suggestions:
        checks = review_suggestions[0].get("checks") or []
        if checks:
            highlights.append(f"第一优先核查动作：{checks[0]}")
    return highlights[:3]


def _validate_dimension_result(result: StudentCareAgentDimension, expected_dimension: str | None = None) -> None:
    if result.dimension not in DIMENSION_LABELS:
        raise ValueError(f"未知研判维度: {result.dimension}")
    if expected_dimension and result.dimension != expected_dimension:
        raise ValueError(f"专家维度不匹配: 期望 {expected_dimension}, 实际 {result.dimension}")
    if result.risk_level not in RISK_LEVELS:
        raise ValueError(f"未知风险等级: {result.risk_level}")


def _validate_agent_result(result: StudentCareAgentResult) -> None:
    if result.overall_level not in RISK_LEVELS:
        raise ValueError(f"未知综合风险等级: {result.overall_level}")

    dimensions = result.dimensions or []
    dimension_keys = [item.dimension for item in dimensions]
    expected_keys = set(DIMENSION_LABELS.keys())
    if set(dimension_keys) != expected_keys or len(dimension_keys) != len(expected_keys):
        raise ValueError("综合研判结果必须包含完整且不重复的六个维度")

    for item in dimensions:
        _validate_dimension_result(item)


def _attach_dimension_details(
    result: StudentCareAgentDimension,
    profile: dict,
    signals: list[dict],
) -> StudentCareAgentDimension:
    explanation, breakdown = _build_dimension_score_details(result.dimension, profile, signals)
    payload = result.model_dump()
    payload["score_explanation"] = explanation
    payload["score_breakdown"] = breakdown
    return StudentCareAgentDimension.model_validate(payload)


def _build_expert_fallback(
    dimension: str,
    profile: dict,
    signals: list[dict],
) -> StudentCareAgentDimension:
    evidence = [
        item.get("signal_text")
        for item in signals
        if item.get("dimension") == dimension and item.get("signal_text")
    ][:2]
    score = float(profile.get(f"{dimension}_score") or 0)
    summary = "暂无明显风险线索" if not evidence else "结合近期信号需要持续关注"
    return StudentCareAgentDimension(
        dimension=dimension,
        score=score,
        risk_level=_risk_level(score),
        summary=summary,
        evidence=evidence,
    )


async def _run_expert(
    dimension: str,
    prompt_payload: dict,
    profile: dict,
    signals: list[dict],
    light_model: str,
) -> dict:
    system_prompt, user_prompt = _build_expert_prompts_v2(dimension, prompt_payload)
    raw_text = None
    fallback = False
    error_msg = None
    result: StudentCareAgentDimension

    try:
        raw_text = await ai_client.call(
            system_prompt,
            user_prompt,
            temperature=0.2,
            max_tokens=800,
            model_name=light_model,
            timeout=min(settings.AI_TIMEOUT, AGENT_EXPERT_TIMEOUT_SECONDS),
            max_retries=1,
        )
        parsed = _extract_json(raw_text)
        if parsed is None:
            raise ValueError("模型返回无法解析为 JSON")
        parsed = _normalize_dimension_payload(dimension, parsed)
        result = StudentCareAgentDimension.model_validate(parsed)
        _validate_dimension_result(result, expected_dimension=dimension)
        if dimension == "emotion":
            ok, reason = _validate_emotion_result(result, signals, prompt_payload.get("tag_definitions") or [])
            if not ok:
                raise ValueError(reason)
    except Exception as exc:
        fallback = True
        error_msg = _humanize_expert_error(str(exc), dimension)
        result = _build_expert_fallback(dimension, profile, signals)
        if dimension == "emotion" and error_msg:
            result.summary = "证据不足，建议继续观察"
            result.score = min(float(result.score or 0), EMOTION_LOW_SCORE_MAX)
            result.risk_level = _risk_level(result.score)

    return {
        "dimension": dimension,
        "fallback": fallback,
        "error_msg": error_msg,
        "raw_text": raw_text,
        "result": result.model_dump(),
    }


def _build_dimension_expert_node(dimension: str):
    async def _dimension_expert_node(state: StudentCareGraphState) -> StudentCareGraphState:
        output = await _run_expert(
            dimension,
            state["prompt_payload"],
            state["profile"],
            state["signals"],
            state["light_model"],
        )
        return {"expert_outputs": [output]}

    _dimension_expert_node.__name__ = f"{dimension}_agent_node"
    return _dimension_expert_node


async def _integration_agent_node(state: StudentCareGraphState) -> StudentCareGraphState:
    expert_order = {key: index for index, key in enumerate(DIMENSION_LABELS.keys())}
    expert_outputs = sorted(
        state["expert_outputs"],
        key=lambda item: expert_order.get(item.get("dimension"), 999),
    )
    result = _build_integrated_result_from_experts(
        state["profile"],
        state["signals"],
        state["actions"],
        expert_outputs,
    )
    _validate_agent_result(result)
    return {
        "raw_text": None,
        "fallback": False,
        "error_msg": None,
        "result": result,
    }


@lru_cache(maxsize=1)
def _build_student_care_agent_graph():
    workflow = StateGraph(StudentCareGraphState)
    expert_node_names = []
    for dimension in DIMENSION_LABELS.keys():
        node_name = f"{dimension}_agent"
        expert_node_names.append(node_name)
        workflow.add_node(node_name, _build_dimension_expert_node(dimension))
        workflow.add_edge(START, node_name)

    workflow.add_node("integration_agent", _integration_agent_node)
    workflow.add_edge(expert_node_names, "integration_agent")
    workflow.add_edge("integration_agent", END)
    return workflow.compile(name="student_care_multi_agent")


async def _run_student_care_agent_graph(
    prompt_payload: dict,
    profile: dict,
    signals: list[dict],
    actions: list[str],
    light_model: str,
    strong_model: str,
) -> dict:
    graph = _build_student_care_agent_graph()
    return await graph.ainvoke(
        {
            "prompt_payload": prompt_payload,
            "profile": profile,
            "signals": signals,
            "actions": actions,
            "light_model": light_model,
            "strong_model": strong_model,
            "expert_outputs": [],
            "raw_text": None,
            "fallback": False,
            "error_msg": None,
            "result": None,
        }
    )


async def evaluate_student_care_agent(db: Session, current_user, student_id: int) -> dict:
    ensure_student_care_schema()
    db.rollback()
    profile_resp = student_care_service.get_student_care_profile(db, current_user, student_id)
    if profile_resp.get("code") != 200:
        return profile_resp

    data = profile_resp.get("data") or {}
    student = data.get("student") or {}
    profile = data.get("profile") or {}
    signals = data.get("signals") or []
    actions = data.get("actions") or []
    major_incident_context = _build_major_incident_context(profile, signals)

    prompt_payload = {
        "student": student,
        "profile": profile,
        "signals": signals[:12],
        "care_fact_context": _build_care_fact_context(signals),
        "graph_context": _build_graph_context(signals, profile),
        "actions": actions[:5],
        "bayes_results": profile.get("bayes_results", {}),
        "dimension_labels": DIMENSION_LABELS,
        "major_incident_context": major_incident_context,
    }
    teacher_reviews = _list_recent_teacher_reviews(db, student_id)
    teacher_feedback_context = _get_latest_confirmed_teacher_feedback(db, student_id)
    prompt_payload["teacher_reviews"] = teacher_reviews
    prompt_payload["teacher_feedback_context"] = teacher_feedback_context
    prompt_payload["care_fact_context"]["teacher_reviews"] = teacher_reviews
    prompt_payload["care_fact_context"]["teacher_feedback_context"] = teacher_feedback_context
    prompt_payload["care_fact_context"]["major_incident_context"] = major_incident_context

    tag_definitions, unknown_tags = _resolve_tag_definitions(db, student)
    tag_web_context, student_care_web_context = await asyncio.gather(
        _fetch_tag_web_context(unknown_tags),
        _fetch_student_care_web_context(signals),
    )
    prompt_payload["tag_definitions"] = tag_definitions
    prompt_payload["tag_web_context"] = tag_web_context
    prompt_payload["web_context"] = student_care_web_context

    light_model = settings.AI_MODEL_NAME_LIGHT or settings.AI_MODEL_NAME or getattr(ai_client, "model", "")
    strong_model = settings.AI_MODEL_NAME_STRONG or settings.AI_MODEL_NAME or getattr(ai_client, "model", "")

    graph_state = await _run_student_care_agent_graph(
        prompt_payload=prompt_payload,
        profile=profile,
        signals=signals,
        actions=actions,
        light_model=light_model,
        strong_model=strong_model,
    )
    expert_order = {key: index for index, key in enumerate(DIMENSION_LABELS.keys())}
    expert_outputs = sorted(
        graph_state["expert_outputs"],
        key=lambda item: expert_order.get(item.get("dimension"), 999),
    )
    raw_text = graph_state["raw_text"]
    fallback = graph_state["fallback"]
    error_msg = graph_state["error_msg"]
    result = graph_state["result"]

    response = StudentCareAgentEvalOut(
        student_id=student_id,
        generated_at=datetime.now(),
        model_name=strong_model,
        timeout_seconds=settings.AI_TIMEOUT,
        fallback=fallback,
        error_msg=error_msg,
        expert_outputs=expert_outputs,
        result=result,
        raw_text=raw_text if fallback else None,
    )
    response.result.review_suggestions = _build_review_suggestions(response.result.dimensions, major_incident_context)
    response.result.explanation_highlights = _build_explanation_highlights(response.result, major_incident_context)
    response.result.overall_breakdown = _build_overall_breakdown(response.result)
    response.result.major_incident_mode = bool(major_incident_context.get("detected"))
    if major_incident_context.get("detected"):
        secondary_labels = [item.get("label") for item in major_incident_context.get("impacted_dimensions") if item.get("label")]
        response.result.major_incident_summary = (
            "当前属于恶性事件后阶段，应先核实安全事实是否仍持续，再前瞻核查"
            + ("、".join(secondary_labels[:3]) if secondary_labels else "情绪、社交与学习等次生影响")
            + "。"
        )
        response.result.suggestions = [response.result.major_incident_summary] + list(response.result.suggestions or [])
        response.result.suggestions = response.result.suggestions[:4]
    response.result.secondary_impacts = major_incident_context.get("impacted_dimensions") or []
    record = StudentCareAgentRecord(
        student_id=student_id,
        model_name=response.model_name,
        timeout_seconds=response.timeout_seconds,
        fallback=1 if fallback else 0,
        error_msg=error_msg,
        input_snapshot={
            **prompt_payload,
            "expert_outputs": expert_outputs,
            "models": {"light": light_model, "strong": strong_model},
        },
        result_json=response.result.model_dump(),
        raw_text=raw_text,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    response.record_id = record.id

    return success_response(data=response.model_dump(mode="json"))


def _build_expert_prompts_v2(dimension: str, payload: dict) -> tuple[str, str]:
    if dimension == "emotion":
        base_prompt = (
            "??????????????????????????????????"
            "??????????????????????????????AI ??????????????"
            "?????????????? summary ???????????????????"
        )
    else:
        base_prompt = EXPERT_PROMPTS.get(dimension, "?????????????")

    system_template = (
        base_prompt
        + "?????? JSON??????????"
        + "JSON ?????dimension, score(0-1), risk_level, summary, evidence(??)?"
        + "tag_definitions ??????????????????????"
        + "????? care_fact_context ????????????????????????????AI ???????"
        + "????? graph_context ??????????????????????????????????????????"
        + "???? bayes_results ?????? posterior/final_score?????????????? evidence ??????????"
        + "?? care_fact_context.teacher_reviews ??????????????????????????????????"
        + "?? major_incident_context.detected=true??????????????????????????????????????????????"
        + "???????????????? impacted_dimensions ? propagation_signals ??????????????????"
        + "??????????????????????????????????????????"
        + "web_context ?????????????? evidence ?????? facts/signals?"
    )
    user_template = (
        "以下是学生关怀画像的校内事实数据，请只评估该维度：{dimension_label}。"
        "\n请输出 JSON：\n{payload}"
    )
    return _render_chat_prompt(
        system_template,
        user_template,
        {
            "dimension_label": DIMENSION_LABELS.get(dimension, dimension),
            "payload": json.dumps(payload, ensure_ascii=False),
        },
    )


def _collect_allowed_emotion_evidence(signals: list[dict]) -> list[str]:
    allowed = []
    for item in signals:
        source = item.get("source")
        text = item.get("signal_text") or ""
        if source in ALLOWED_EMOTION_SOURCES and text:
            allowed.append(text)
    return allowed


def _evidence_hits_allowed(evidence: list[str], allowed_texts: list[str]) -> int:
    if not evidence or not allowed_texts:
        return 0
    hits = 0
    for item in evidence:
        if not item:
            continue
        for text in allowed_texts:
            if not text:
                continue
            if item in text or text in item:
                hits += 1
                break
    return hits


def _contains_positive_or_neutral_tag(evidence: list[str], tag_definitions: list[dict]) -> bool:
    if not evidence:
        return False
    positive_tags = [
        item.get("tag_text")
        for item in tag_definitions
        if item.get("polarity") in {"positive", "neutral"} and item.get("tag_text")
    ]
    if not positive_tags:
        return False
    for text in evidence:
        for tag in positive_tags:
            if tag and tag in text:
                return True
    return False


def _validate_emotion_result(
    result: StudentCareAgentDimension,
    signals: list[dict],
    tag_definitions: list[dict],
) -> tuple[bool, str]:
    evidence = result.evidence or []
    score = float(result.score or 0)
    allowed_texts = _collect_allowed_emotion_evidence(signals)
    hits = _evidence_hits_allowed(evidence, allowed_texts)

    if _contains_positive_or_neutral_tag(evidence, tag_definitions):
        return False, "心理维度证据包含正向/中性标签"

    if score >= EMOTION_MEDIUM_SCORE and hits < 2:
        return False, "心理维度高分但证据不足"
    if score >= EMOTION_ATTENTION_SCORE and hits < 1:
        return False, "心理维度评分超过关注阈值但无有效证据"
    if not evidence and score > EMOTION_LOW_SCORE_MAX:
        return False, "心理维度无证据但评分偏高"

    return True, ""


def list_agent_eval_history(
    db: Session,
    current_user,
    student_id: int,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    ensure_student_care_schema()
    db.rollback()
    profile_resp = student_care_service.get_student_care_profile(db, current_user, student_id)
    if profile_resp.get("code") != 200:
        return profile_resp

    query = (
        db.query(StudentCareAgentRecord)
        .filter(StudentCareAgentRecord.student_id == student_id)
        .order_by(StudentCareAgentRecord.id.desc())
    )
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    return success_response(data={"list": [_serialize_agent_record(item) for item in rows], "total": total})


def confirm_agent_eval_review(
    db: Session,
    current_user,
    record_id: int,
    payload: StudentCareAgentReviewUpdate,
) -> dict:
    ensure_student_care_schema()
    db.rollback()
    record = db.query(StudentCareAgentRecord).filter(StudentCareAgentRecord.id == record_id).first()
    if not record:
        return error_response(code=404, msg="研判记录不存在")

    student = db.query(Student).filter(Student.id == record.student_id).first()
    if not student:
        return error_response(code=404, msg="学生不存在")
    permission_error = student_care_service._ensure_head_teacher_access(db, current_user, student)
    if permission_error:
        return permission_error

    reviewed_result = _sanitize_reviewed_result(record.result_json or {}, payload.reviewed_result or {})
    record.review_status = "confirmed"
    record.reviewed_result_json = reviewed_result
    record.review_labels_json = payload.review_labels.model_dump()
    record.teacher_notes = payload.teacher_notes
    record.resolution_status = payload.resolution_status
    record.confirmed_by = current_user.id
    record.confirmed_at = datetime.now()
    db.add(record)
    db.commit()
    db.refresh(record)
    return success_response(data=_serialize_agent_record(record))


def get_agent_stats(
    db: Session,
    current_user,
    start_date: str | None = None,
    end_date: str | None = None,
    class_id: int | None = None,
) -> dict:
    ensure_student_care_schema()
    db.rollback()

    query = db.query(StudentCareAgentRecord).join(Student, Student.id == StudentCareAgentRecord.student_id)

    if current_user.role == "admin":
        if class_id:
            query = query.filter(Student.class_id == class_id)
    elif current_user.role == "teacher":
        teacher = db.query(Teacher).filter(Teacher.name == current_user.name).first()
        if not teacher:
            return error_response(code=403, msg="未找到教师档案")
        class_ids = [
            item.id
            for item in db.query(Class).filter(Class.head_teacher_id == teacher.id).all()
        ]
        if not class_ids:
            return success_response(
                data={
                    "total": 0,
                    "fallback_rate": 0,
                    "risk_distribution": {"low": 0, "attention": 0, "medium": 0, "high": 0},
                    "model_distribution": {},
                    "daily_trend": [],
                }
            )
        query = query.filter(Student.class_id.in_(class_ids))
    else:
        return error_response(code=403, msg="无权限访问")

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(StudentCareAgentRecord.created_at >= start_dt)
        except ValueError:
            return error_response(code=400, msg="开始日期格式错误")
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(StudentCareAgentRecord.created_at < end_dt)
        except ValueError:
            return error_response(code=400, msg="结束日期格式错误")

    rows = query.with_entities(
        StudentCareAgentRecord.fallback,
        StudentCareAgentRecord.model_name,
        StudentCareAgentRecord.result_json,
        StudentCareAgentRecord.created_at,
    ).all()

    total = len(rows)
    if total == 0:
        return success_response(
            data={
                "total": 0,
                "fallback_rate": 0,
                "risk_distribution": {"low": 0, "attention": 0, "medium": 0, "high": 0},
                "model_distribution": {},
                "daily_trend": [],
            }
        )

    fallback_count = sum(1 for row in rows if row.fallback)
    risk_distribution = {"low": 0, "attention": 0, "medium": 0, "high": 0}
    model_distribution: dict[str, int] = {}
    daily_map: dict[str, int] = {}

    for row in rows:
        model_distribution[row.model_name] = model_distribution.get(row.model_name, 0) + 1
        level = (row.result_json or {}).get("overall_level")
        if level in risk_distribution:
            risk_distribution[level] += 1
        if row.created_at:
            day = row.created_at.strftime("%Y-%m-%d")
            daily_map[day] = daily_map.get(day, 0) + 1

    daily_trend = [
        {"date": date, "count": count}
        for date, count in sorted(daily_map.items())
    ]

    return success_response(
        data={
            "total": total,
            "fallback_rate": round(fallback_count / total, 4),
            "risk_distribution": risk_distribution,
            "model_distribution": model_distribution,
            "daily_trend": daily_trend,
        }
    )


def _empty_agent_evaluation_summary() -> dict:
    return {
        "total_records": 0,
        "confirmed_reviews": 0,
        "reviewed_ratio": 0,
        "true_risk_count": 0,
        "false_alarm_count": 0,
        "unresolved_count": 0,
        "agreement_rate": 0,
        "avg_teacher_confidence": 0,
        "scene_distribution": {},
        "severity_distribution": {"low": 0, "medium": 0, "high": 0, "unknown": 0},
        "resolution_distribution": {"pending": 0, "in_progress": 0, "resolved": 0, "false_alarm": 0},
        "system_vs_teacher": {
            "aligned": 0,
            "misaligned": 0,
            "system_positive_teacher_yes": 0,
            "system_positive_teacher_no": 0,
            "system_low_teacher_yes": 0,
            "system_low_teacher_no": 0,
        },
        "rule_impact": {
            "data_gap_record_count": 0,
            "protective_record_count": 0,
            "attenuated_record_count": 0,
            "false_alarm_with_data_gap": 0,
            "false_alarm_with_protective": 0,
            "teacher_confirmed_with_data_gap": 0,
            "teacher_confirmed_with_attenuated": 0,
        },
        "trend": [],
    }


def _extract_rule_impact_flags(row) -> dict:
    input_snapshot = getattr(row, "input_snapshot", None) or {}
    signals = input_snapshot.get("signals") or []
    missing_sources = []
    has_protective = False
    has_attenuated = False

    for item in signals:
        source = str(item.get("source") or "").strip()
        signal_type = str(item.get("signal_type") or "").strip()
        try:
            weight = float(item.get("signal_weight") or 0)
        except (TypeError, ValueError):
            weight = 0.0

        if source == "data_gap":
            missing_sources.append(signal_type or "unknown_gap")
        if weight < 0:
            has_protective = True
        if 0 < weight <= 0.2 and source in {"attendance", "behavior_event", "score"}:
            has_attenuated = True

    return {
        "has_data_gap": bool(missing_sources),
        "has_protective": has_protective,
        "has_attenuated": has_attenuated,
        "missing_sources": sorted(set(missing_sources)),
    }


def _build_agent_evaluation_summary_from_rows(rows: list) -> dict:
    summary = _empty_agent_evaluation_summary()
    total_records = len(rows)
    summary["total_records"] = total_records
    if total_records == 0:
        return summary

    confirmed_rows = [row for row in rows if getattr(row, "review_status", None) == "confirmed"]
    summary["confirmed_reviews"] = len(confirmed_rows)
    summary["reviewed_ratio"] = round(len(confirmed_rows) / total_records, 4)
    if not confirmed_rows:
        return summary

    trend_map: dict[str, dict[str, int]] = {}
    alignment_total = 0
    alignment_hits = 0
    confidence_total = 0
    confidence_count = 0

    for row in confirmed_rows:
        labels = getattr(row, "review_labels_json", None) or {}
        rule_impact = _extract_rule_impact_flags(row)
        scene = str(labels.get("scene") or "other").strip() or "other"
        severity = str(labels.get("severity") or "unknown").strip() or "unknown"
        is_true_risk = str(labels.get("is_true_risk") or "unknown").strip() or "unknown"
        resolution_status = str(getattr(row, "resolution_status", None) or "pending").strip() or "pending"
        result_json = getattr(row, "result_json", None) or {}
        system_level = str(result_json.get("overall_level") or "low").strip() or "low"
        system_positive = system_level != "low"

        summary["scene_distribution"][scene] = summary["scene_distribution"].get(scene, 0) + 1
        summary["severity_distribution"][severity] = summary["severity_distribution"].get(severity, 0) + 1
        summary["resolution_distribution"][resolution_status] = (
            summary["resolution_distribution"].get(resolution_status, 0) + 1
        )
        if rule_impact["has_data_gap"]:
            summary["rule_impact"]["data_gap_record_count"] += 1
        if rule_impact["has_protective"]:
            summary["rule_impact"]["protective_record_count"] += 1
        if rule_impact["has_attenuated"]:
            summary["rule_impact"]["attenuated_record_count"] += 1

        if is_true_risk == "yes":
            summary["true_risk_count"] += 1
            if rule_impact["has_data_gap"]:
                summary["rule_impact"]["teacher_confirmed_with_data_gap"] += 1
            if rule_impact["has_attenuated"]:
                summary["rule_impact"]["teacher_confirmed_with_attenuated"] += 1
        elif is_true_risk == "no":
            summary["false_alarm_count"] += 1
            if rule_impact["has_data_gap"]:
                summary["rule_impact"]["false_alarm_with_data_gap"] += 1
            if rule_impact["has_protective"]:
                summary["rule_impact"]["false_alarm_with_protective"] += 1

        if resolution_status in {"pending", "in_progress"}:
            summary["unresolved_count"] += 1

        confidence = labels.get("confidence_by_teacher")
        if isinstance(confidence, int):
            confidence_total += confidence
            confidence_count += 1

        if is_true_risk in {"yes", "no"}:
            alignment_total += 1
            if system_positive and is_true_risk == "yes":
                summary["system_vs_teacher"]["system_positive_teacher_yes"] += 1
                summary["system_vs_teacher"]["aligned"] += 1
                alignment_hits += 1
            elif system_positive and is_true_risk == "no":
                summary["system_vs_teacher"]["system_positive_teacher_no"] += 1
                summary["system_vs_teacher"]["misaligned"] += 1
            elif (not system_positive) and is_true_risk == "yes":
                summary["system_vs_teacher"]["system_low_teacher_yes"] += 1
                summary["system_vs_teacher"]["misaligned"] += 1
            else:
                summary["system_vs_teacher"]["system_low_teacher_no"] += 1
                summary["system_vs_teacher"]["aligned"] += 1
                alignment_hits += 1

        created_at = getattr(row, "created_at", None)
        if created_at:
            day = created_at.strftime("%Y-%m-%d")
            if day not in trend_map:
                trend_map[day] = {"date": day, "confirmed_count": 0, "true_risk_count": 0}
            trend_map[day]["confirmed_count"] += 1
            if is_true_risk == "yes":
                trend_map[day]["true_risk_count"] += 1

    summary["agreement_rate"] = round(alignment_hits / alignment_total, 4) if alignment_total else 0
    summary["avg_teacher_confidence"] = round(confidence_total / confidence_count, 2) if confidence_count else 0
    summary["trend"] = [trend_map[key] for key in sorted(trend_map.keys())]
    return summary


def _build_scene_breakdown_from_rows(rows: list) -> list[dict]:
    scene_map: dict[str, dict] = {}

    for row in rows:
        if getattr(row, "review_status", None) != "confirmed":
            continue

        labels = getattr(row, "review_labels_json", None) or {}
        rule_impact = _extract_rule_impact_flags(row)
        scene = str(labels.get("scene") or "other").strip() or "other"
        severity = str(labels.get("severity") or "unknown").strip() or "unknown"
        is_true_risk = str(labels.get("is_true_risk") or "unknown").strip() or "unknown"
        resolution_status = str(getattr(row, "resolution_status", None) or "pending").strip() or "pending"
        result_json = getattr(row, "result_json", None) or {}
        system_level = str(result_json.get("overall_level") or "low").strip() or "low"
        system_positive = system_level != "low"
        confidence = labels.get("confidence_by_teacher")

        if scene not in scene_map:
            scene_map[scene] = {
                "scene": scene,
                "review_count": 0,
                "true_risk_count": 0,
                "false_alarm_count": 0,
                "unresolved_count": 0,
                "agreement_rate": 0,
                "avg_teacher_confidence": 0,
                "severity_distribution": {"low": 0, "medium": 0, "high": 0, "unknown": 0},
                "resolution_distribution": {"pending": 0, "in_progress": 0, "resolved": 0, "false_alarm": 0},
                "rule_impact": {
                    "data_gap_record_count": 0,
                    "protective_record_count": 0,
                    "attenuated_record_count": 0,
                },
                "_alignment_total": 0,
                "_alignment_hits": 0,
                "_confidence_total": 0,
                "_confidence_count": 0,
            }

        item = scene_map[scene]
        item["review_count"] += 1
        item["severity_distribution"][severity] = item["severity_distribution"].get(severity, 0) + 1
        item["resolution_distribution"][resolution_status] = item["resolution_distribution"].get(resolution_status, 0) + 1
        if rule_impact["has_data_gap"]:
            item["rule_impact"]["data_gap_record_count"] += 1
        if rule_impact["has_protective"]:
            item["rule_impact"]["protective_record_count"] += 1
        if rule_impact["has_attenuated"]:
            item["rule_impact"]["attenuated_record_count"] += 1

        if is_true_risk == "yes":
            item["true_risk_count"] += 1
        elif is_true_risk == "no":
            item["false_alarm_count"] += 1

        if resolution_status in {"pending", "in_progress"}:
            item["unresolved_count"] += 1

        if isinstance(confidence, int):
            item["_confidence_total"] += confidence
            item["_confidence_count"] += 1

        if is_true_risk in {"yes", "no"}:
            item["_alignment_total"] += 1
            teacher_positive = is_true_risk == "yes"
            if system_positive == teacher_positive:
                item["_alignment_hits"] += 1

    result = []
    for scene, item in scene_map.items():
        alignment_total = item.pop("_alignment_total", 0)
        alignment_hits = item.pop("_alignment_hits", 0)
        confidence_total = item.pop("_confidence_total", 0)
        confidence_count = item.pop("_confidence_count", 0)
        item["agreement_rate"] = round(alignment_hits / alignment_total, 4) if alignment_total else 0
        item["avg_teacher_confidence"] = round(confidence_total / confidence_count, 2) if confidence_count else 0
        result.append(item)

    return sorted(result, key=lambda item: (-item["review_count"], item["scene"]))


def _build_recent_review_rows(rows: list) -> list[dict]:
    recent = []
    for row in rows:
        if getattr(row, "review_status", None) != "confirmed":
            continue
        labels = getattr(row, "review_labels_json", None) or {}
        rule_impact = _extract_rule_impact_flags(row)
        recent.append(
            {
                "record_id": getattr(row, "id", None),
                "student_id": getattr(row, "student_id", None),
                "student_name": getattr(row, "student_name", "") or "",
                "class_name": getattr(row, "class_name", "") or "",
                "scene": str(labels.get("scene") or "other").strip() or "other",
                "is_true_risk": str(labels.get("is_true_risk") or "unknown").strip() or "unknown",
                "severity": str(labels.get("severity") or "unknown").strip() or "unknown",
                "confidence_by_teacher": labels.get("confidence_by_teacher") or 0,
                "resolution_status": getattr(row, "resolution_status", None) or "pending",
                "system_level": str((getattr(row, "result_json", None) or {}).get("overall_level") or "low"),
                "teacher_notes": getattr(row, "teacher_notes", None) or "",
                "confirmed_at": str(getattr(row, "confirmed_at", None) or ""),
                "created_at": str(getattr(row, "created_at", None) or ""),
                "has_data_gap": rule_impact["has_data_gap"],
                "has_protective": rule_impact["has_protective"],
                "has_attenuated": rule_impact["has_attenuated"],
                "missing_sources": rule_impact["missing_sources"],
            }
        )
    return recent[:12]


def get_agent_evaluation_summary(
    db: Session,
    current_user,
    start_date: str | None = None,
    end_date: str | None = None,
    class_id: int | None = None,
) -> dict:
    ensure_student_care_schema()
    db.rollback()

    query = db.query(StudentCareAgentRecord).join(Student, Student.id == StudentCareAgentRecord.student_id)

    if current_user.role == "admin":
        if class_id:
            query = query.filter(Student.class_id == class_id)
    elif current_user.role == "teacher":
        teacher = db.query(Teacher).filter(Teacher.name == current_user.name).first()
        if not teacher:
            return error_response(code=403, msg="teacher profile not found")
        class_ids = [item.id for item in db.query(Class).filter(Class.head_teacher_id == teacher.id).all()]
        if not class_ids:
            return success_response(data=_empty_agent_evaluation_summary())
        query = query.filter(Student.class_id.in_(class_ids))
    else:
        return error_response(code=403, msg="permission denied")

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(StudentCareAgentRecord.created_at >= start_dt)
        except ValueError:
            return error_response(code=400, msg="invalid start_date")
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(StudentCareAgentRecord.created_at < end_dt)
        except ValueError:
            return error_response(code=400, msg="invalid end_date")

    rows = query.with_entities(
        StudentCareAgentRecord.review_status,
        StudentCareAgentRecord.review_labels_json,
        StudentCareAgentRecord.resolution_status,
        StudentCareAgentRecord.result_json,
        StudentCareAgentRecord.input_snapshot,
        StudentCareAgentRecord.created_at,
    ).all()

    return success_response(data=_build_agent_evaluation_summary_from_rows(rows))


def get_agent_evaluation_detail(
    db: Session,
    current_user,
    start_date: str | None = None,
    end_date: str | None = None,
    class_id: int | None = None,
) -> dict:
    ensure_student_care_schema()
    db.rollback()

    query = (
        db.query(
            StudentCareAgentRecord.id,
            StudentCareAgentRecord.student_id,
            StudentCareAgentRecord.review_status,
            StudentCareAgentRecord.review_labels_json,
            StudentCareAgentRecord.resolution_status,
            StudentCareAgentRecord.result_json,
            StudentCareAgentRecord.input_snapshot,
            StudentCareAgentRecord.teacher_notes,
            StudentCareAgentRecord.confirmed_at,
            StudentCareAgentRecord.created_at,
            Student.name.label("student_name"),
            Class.name.label("class_name"),
        )
        .join(Student, Student.id == StudentCareAgentRecord.student_id)
        .outerjoin(Class, Class.id == Student.class_id)
    )

    if current_user.role == "admin":
        if class_id:
            query = query.filter(Student.class_id == class_id)
    elif current_user.role == "teacher":
        teacher = db.query(Teacher).filter(Teacher.name == current_user.name).first()
        if not teacher:
            return error_response(code=403, msg="teacher profile not found")
        class_ids = [item.id for item in db.query(Class).filter(Class.head_teacher_id == teacher.id).all()]
        if not class_ids:
            return success_response(data={"scene_breakdown": [], "recent_reviews": []})
        query = query.filter(Student.class_id.in_(class_ids))
    else:
        return error_response(code=403, msg="permission denied")

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(StudentCareAgentRecord.created_at >= start_dt)
        except ValueError:
            return error_response(code=400, msg="invalid start_date")
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(StudentCareAgentRecord.created_at < end_dt)
        except ValueError:
            return error_response(code=400, msg="invalid end_date")

    rows = (
        query.order_by(StudentCareAgentRecord.confirmed_at.desc(), StudentCareAgentRecord.id.desc())
        .all()
    )

    return success_response(
        data={
            "scene_breakdown": _build_scene_breakdown_from_rows(rows),
            "recent_reviews": _build_recent_review_rows(rows),
        }
    )


def export_agent_stats_csv(
    db: Session,
    current_user,
    start_date: str | None = None,
    end_date: str | None = None,
    class_id: int | None = None,
) -> tuple[str, str]:
    stats_resp = get_agent_stats(
        db=db,
        current_user=current_user,
        start_date=start_date,
        end_date=end_date,
        class_id=class_id,
    )
    if stats_resp.get("code") != 200:
        return "", stats_resp.get("msg", "导出失败")

    data = stats_resp.get("data") or {}
    lines = ["指标,数值"]
    lines.append(f"研判总量,{data.get('total', 0)}")
    lines.append(f"兜底率,{round((data.get('fallback_rate', 0) * 100), 2)}%")
    risk = data.get("risk_distribution") or {}
    lines.append(f"低风险,{risk.get('low', 0)}")
    lines.append(f"关注,{risk.get('attention', 0)}")
    lines.append(f"中风险,{risk.get('medium', 0)}")
    lines.append(f"高风险,{risk.get('high', 0)}")

    lines.append("")
    lines.append("模型分布,次数")
    for name, count in (data.get("model_distribution") or {}).items():
        lines.append(f"{name},{count}")

    lines.append("")
    lines.append("日期,研判次数")
    for row in data.get("daily_trend") or []:
        lines.append(f"{row.get('date')},{row.get('count')}")

    csv_text = "\n".join(lines)
    filename = "student_care_agent_stats.csv"
    return csv_text, filename


def export_agent_evaluation_summary_csv(
    db: Session,
    current_user,
    start_date: str | None = None,
    end_date: str | None = None,
    class_id: int | None = None,
) -> tuple[str, str]:
    summary_resp = get_agent_evaluation_summary(
        db=db,
        current_user=current_user,
        start_date=start_date,
        end_date=end_date,
        class_id=class_id,
    )
    if summary_resp.get("code") != 200:
        return "", summary_resp.get("msg", "瀵煎嚭澶辫触")

    data = summary_resp.get("data") or {}
    lines = ["metric,value"]
    lines.append(f"total_records,{data.get('total_records', 0)}")
    lines.append(f"confirmed_reviews,{data.get('confirmed_reviews', 0)}")
    lines.append(f"reviewed_ratio,{data.get('reviewed_ratio', 0)}")
    lines.append(f"true_risk_count,{data.get('true_risk_count', 0)}")
    lines.append(f"false_alarm_count,{data.get('false_alarm_count', 0)}")
    lines.append(f"unresolved_count,{data.get('unresolved_count', 0)}")
    lines.append(f"agreement_rate,{data.get('agreement_rate', 0)}")
    lines.append(f"avg_teacher_confidence,{data.get('avg_teacher_confidence', 0)}")

    lines.append("")
    lines.append("scene,count")
    for name, count in (data.get("scene_distribution") or {}).items():
        lines.append(f"{name},{count}")

    lines.append("")
    lines.append("severity,count")
    for name, count in (data.get("severity_distribution") or {}).items():
        lines.append(f"{name},{count}")

    lines.append("")
    lines.append("resolution_status,count")
    for name, count in (data.get("resolution_distribution") or {}).items():
        lines.append(f"{name},{count}")

    lines.append("")
    lines.append("trend_date,confirmed_count,true_risk_count")
    for row in data.get("trend") or []:
        lines.append(
            f"{row.get('date')},{row.get('confirmed_count', 0)},{row.get('true_risk_count', 0)}"
        )

    csv_text = "\n".join(lines)
    filename = "student_care_evaluation_summary.csv"
    return csv_text, filename
