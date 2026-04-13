# -*- coding: utf-8 -*-
"""Standalone Bayesian-network-style plugin for social isolation alerts.

改进版本 v2.0:
- 与贝叶斯辅助层协同：使用动态先验
- 使用共享的边际递减函数处理证据相关性
- 网络输出可回传至辅助层形成闭环
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import prod

from sqlalchemy.orm import Session

from core.response import error_response, success_response
from database.models.student import Student
from database.models.student_care_agent_record import StudentCareAgentRecord
from database.models.student_care_profile import StudentCareProfile
from database.models.student_care_signal import StudentCareSignal
from database.models.user import User
from services import student_care_service
from services.student_care_bayes_service import apply_diminishing_returns
from services.student_care_schema_guard import ensure_student_care_schema


ISOLATION_SCENE = "social_isolation"

# 节点到维度的映射：用于从贝叶斯辅助层获取动态先验
NODE_TO_DIMENSION = {
    "peer_disconnect": "social",        # 同伴连接 → 社交维度
    "emotional_withdrawal": "emotion",  # 情绪退缩 → 情绪维度
    "family_support_gap": "family",     # 家庭支持 → 家庭维度
    "safety_threat": "safety",          # 安全威胁 → 安全维度
    "behavior_retreat": "behavior",     # 行为退避 → 行为维度
}

ROOT_CAUSE_CONFIG = {
    "peer_disconnect": {
        "label": "同伴连接缺失",
        "prior": 0.20,
        "impact": 0.92,
        "description": "缺少稳定同伴连接时，学生更容易处于班级互动边缘。",
    },
    "emotional_withdrawal": {
        "label": "情绪退缩",
        "prior": 0.16,
        "impact": 0.78,
        "description": "情绪低落或持续焦虑会降低学生主动建立社交连接的意愿。",
    },
    "family_support_gap": {
        "label": "家庭支持不足",
        "prior": 0.14,
        "impact": 0.58,
        "description": "家庭支持不足会削弱学生在校园中的安全感与连接意愿。",
    },
    "safety_threat": {
        "label": "安全威胁暴露",
        "prior": 0.12,
        "impact": 0.54,
        "description": "冲突、欺凌或威胁事件会让学生回避同伴场景。",
    },
    "behavior_retreat": {
        "label": "行为退避",
        "prior": 0.10,
        "impact": 0.48,
        "description": "缺勤、早退或违纪波动会破坏持续参与集体活动的节奏。",
    },
}

DIRECT_CAUSE_KEYS = (
    "peer_disconnect",
    "emotional_withdrawal",
    "family_support_gap",
    "safety_threat",
    "behavior_retreat",
)

EVIDENCE_RULES = {
    "peer_disconnect": (
        {"id": "graph_social_isolation", "label": "图谱孤立信号", "lr": 2.8, "signal_types": {"graph_social_isolation"}},
        {"id": "class_unassigned", "label": "未分班", "lr": 1.8, "signal_types": {"class_unassigned"}},
        {"id": "tag_social", "label": "社交标签预警", "lr": 1.6, "signal_types": {"tag_social"}},
        {"id": "social_observation", "label": "社交观察异常", "lr": 2.1, "dimension": "social", "source": "care_observation"},
        {
            "id": "manual_peer_concern",
            "label": "人工图谱重点关注",
            "lr": 1.7,
            "source": "graph",
            "signal_types": {"graph_manual_student_concern", "graph_manual_event_concern"},
        },
        {"id": "assistant_social_signal", "label": "AI 社交信号", "lr": 1.65, "source": "assistant_summary", "dimension": "social"},
        {"id": "agent_social_summary", "label": "智能研判社交摘要", "lr": 1.45, "agent_context": "social_summary"},
        {"id": "teacher_confirmed_social_evidence", "label": "教师确认社交线索", "lr": 1.7, "agent_context": "social_evidence"},
    ),
    "emotional_withdrawal": (
        {"id": "emotion_score_high", "label": "情绪分偏高", "lr": 1.9, "profile_score": ("emotion_score", 0.45)},
        {"id": "score_drop_emotion", "label": "成绩波动诱发情绪变化", "lr": 1.5, "signal_types": {"score_drop_emotion"}},
        {"id": "assistant_distress", "label": "对话出现低落表达", "lr": 2.1, "source": "assistant_summary", "dimension": "emotion"},
        {"id": "emotion_observation", "label": "情绪观察异常", "lr": 2.2, "source": "care_observation", "dimension": "emotion"},
    ),
    "family_support_gap": (
        {"id": "family_score_high", "label": "家庭支持分偏高", "lr": 1.8, "profile_score": ("family_score", 0.4)},
        {"id": "tag_family", "label": "家庭困难标签", "lr": 1.7, "signal_types": {"tag_family"}},
        {"id": "family_contact_negative", "label": "家校沟通显示支持不足", "lr": 2.2, "source": "family_contact", "dimension": "family"},
        {"id": "assistant_family", "label": "对话出现家庭困扰", "lr": 1.9, "source": "assistant_summary", "dimension": "family"},
    ),
    "safety_threat": (
        {"id": "safety_score_high", "label": "安全分偏高", "lr": 1.8, "profile_score": ("safety_score", 0.35)},
        {
            "id": "behavior_conflict",
            "label": "行为事件冲突或欺凌",
            "lr": 2.3,
            "source": "behavior_event",
            "signal_types": {"behavior_conflict", "behavior_bullying"},
        },
        {
            "id": "graph_conflict",
            "label": "图谱冲突共现",
            "lr": 1.9,
            "signal_types": {"graph_conflict_cooccurrence", "graph_manual_student_conflict", "graph_manual_student_bullying_link"},
            "source": "graph",
        },
        {"id": "assistant_safety", "label": "对话出现安全受威胁表达", "lr": 2.4, "source": "assistant_summary", "dimension": "safety"},
    ),
    "behavior_retreat": (
        {"id": "behavior_score_high", "label": "行为稳定分偏高", "lr": 1.8, "profile_score": ("behavior_score", 0.35)},
        {"id": "attendance_risk", "label": "出勤异常", "lr": 1.8, "source": "attendance", "signal_keywords": ("缺勤", "迟到", "早退", "请假")},
        {"id": "behavior_event", "label": "行为事件波动", "lr": 1.7, "source": "behavior_event", "dimension": "behavior"},
        {"id": "study_pressure", "label": "学业压力外溢", "lr": 1.35, "profile_score": ("study_score", 0.45)},
    ),
}

PROTECTIVE_RULES = (
    {
        "id": "peer_support",
        "label": "存在同伴支持关系",
        "weight": 0.12,
        "source": "graph",
        "signal_types": {"graph_manual_student_peer_support", "graph_manual_student_shared_activity"},
    },
    {
        "id": "positive_social_observation",
        "label": "观察记录显示社交状态改善",
        "weight": 0.08,
        "source": "care_observation",
        "dimension": "social",
        "signal_type_prefixes": ("care_observation_positive_",),
    },
    {
        "id": "family_support_positive",
        "label": "家校沟通显示存在支持资源",
        "weight": 0.08,
        "source": "family_contact",
        "signal_types": {"family_contact_positive"},
    },
    {
        "id": "assistant_positive_social",
        "label": "AI 摘要提示近期互动改善",
        "weight": 0.05,
        "source": "assistant_summary",
        "dimension": "social",
        "signal_type_prefixes": ("assistant_signal_positive",),
    },
    {"id": "low_social_score", "label": "当前社交风险分较低", "weight": 0.08, "profile_score_max": ("social_score", 0.25)},
    {"id": "teacher_review_resolved", "label": "教师确认问题已缓解", "weight": 0.10, "agent_resolution_status": {"resolved"}},
    {"id": "teacher_review_false_alarm", "label": "教师确认本次为误报", "weight": 0.18, "agent_resolution_status": {"false_alarm"}},
)

SOCIAL_DATA_REQUIREMENTS = (
    {
        "id": "graph_social_network",
        "label": "同伴关系图谱",
        "description": "是否存在稳定同伴连接、共享活动或图谱孤立线索。",
        "action_hint": "补充同伴支持、共享活动或冲突排斥关系，确认学生在班级网络中的位置。",
        "match": lambda signals, agent_context: any(item.get("source") == "graph" and item.get("dimension") == "social" for item in signals),
    },
    {
        "id": "social_observation",
        "label": "教师社交观察",
        "description": "是否有课间、班级或活动中的社交表现记录。",
        "action_hint": "补充近 30 天课间、班级活动或小组合作中的社交观察。",
        "match": lambda signals, agent_context: any(item.get("source") == "care_observation" and item.get("dimension") == "social" for item in signals),
    },
    {
        "id": "agent_social_summary",
        "label": "智能研判社交摘要",
        "description": "是否有最近一次智能研判的社交维度摘要。",
        "action_hint": "重新执行一次智能研判，确认社交维度摘要是否与近期事实一致。",
        "match": lambda signals, agent_context: bool(str(agent_context.get("social_summary") or "").strip()),
    },
    {
        "id": "teacher_confirmed_social_evidence",
        "label": "教师确认社交线索",
        "description": "是否有老师在研判后确认的社交证据。",
        "action_hint": "在复核弹窗里补充已确认的社交线索，例如独处、互动减少或获得同伴支持。",
        "match": lambda signals, agent_context: bool(agent_context.get("social_evidence")),
    },
    {
        "id": "assistant_social_signal",
        "label": "AI 摘要社交信号",
        "description": "是否从 AI 对话摘要中提取到社交相关线索。",
        "action_hint": "补充学生谈话摘要，或确认助手摘要中是否存在社交互动、回避或支持线索。",
        "match": lambda signals, agent_context: any(item.get("source") == "assistant_summary" and item.get("dimension") == "social" for item in signals),
    },
)

SOURCE_GROUP_META = {
    "fact": {"label": "事实证据", "description": "来自图谱、观察、家校或行为记录的直接事实。"},
    "teacher_feedback": {"label": "老师反馈", "description": "来自教师复核或教师确认后的社交线索。"},
    "ai_signal": {"label": "AI 信号", "description": "来自 AI 摘要或智能研判摘要的补充线索。"},
    "inference": {"label": "推断基础", "description": "来自画像分或规则推断的基础判断。"},
}


def get_student_isolation_analysis(db: Session, current_user: User, student_id: int) -> dict:
    ensure_student_care_schema()
    db.rollback()
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return error_response(msg="学生不存在")
    if current_user.role != "admin":
        permission_error = student_care_service._ensure_head_teacher_access(db, current_user, student)
        if permission_error:
            return permission_error
    return success_response(data=build_student_isolation_analysis_payload(db, student))


def build_student_isolation_analysis_payload(db: Session, student: Student) -> dict:
    profile, signals = _ensure_profile_and_signals(db, student)
    signal_dicts = [_signal_to_dict(item) for item in signals]
    agent_context = _get_recent_agent_context(db, student.id)
    social_data_coverage = _build_social_data_coverage(signal_dicts, agent_context)
    social_trend = _build_social_trend(signal_dicts, social_data_coverage)

    root_causes = _infer_root_causes(profile, signal_dicts, agent_context)
    node_probabilities = {item["node"]: item["probability"] for item in root_causes}
    social_withdrawal_probability = _derive_social_withdrawal_probability(node_probabilities)
    risk_probability = _derive_isolation_risk(node_probabilities, social_withdrawal_probability)

    protective_factors = _collect_protective_factors(profile, signal_dicts, agent_context)
    if protective_factors:
        total_weight = sum(item["weight"] for item in protective_factors[:3])
        risk_probability = _clamp_probability(risk_probability * max(0.62, 1 - total_weight))

    key_evidence = _select_key_evidence(root_causes)
    evidence_source_groups = _build_evidence_source_groups(root_causes, protective_factors)
    evidence_interpretation = _build_evidence_interpretation(social_data_coverage, social_trend, evidence_source_groups)

    return {
        "student_id": student.id,
        "scene": ISOLATION_SCENE,
        "risk_probability": risk_probability,
        "risk_level": _risk_level(risk_probability),
        "confidence": _estimate_confidence(signal_dicts, root_causes, protective_factors),
        "root_causes": root_causes,
        "propagation_paths": _build_propagation_paths(node_probabilities, social_withdrawal_probability),
        "evidence_summary": {
            "matched_signal_count": sum(len(item["evidence"]) for item in root_causes),
            "protective_factor_count": len(protective_factors),
            "key_evidence": key_evidence,
            "protective_factors": protective_factors[:3],
            "social_data_coverage": social_data_coverage,
            "social_trend": social_trend,
            "evidence_source_groups": evidence_source_groups,
            "evidence_interpretation": evidence_interpretation,
            "evidence_sufficient": social_data_coverage["evidence_sufficient"],
            "missing_items": social_data_coverage["missing_items"],
            "coverage_ratio": social_data_coverage["coverage_ratio"],
        },
        "network_snapshot": {
            "social_withdrawal_probability": social_withdrawal_probability,
            "source_count": len(signal_dicts),
            "agent_linked": bool(agent_context.get("has_agent_record")),
            "social_trend": social_trend,
            "inference_version": "isolation_bn_v1",
        },
    }


def _ensure_profile_and_signals(db: Session, student: Student) -> tuple[StudentCareProfile, list[StudentCareSignal]]:
    profile = db.query(StudentCareProfile).filter(StudentCareProfile.student_id == student.id).first()
    signals = (
        db.query(StudentCareSignal)
        .filter(StudentCareSignal.student_id == student.id)
        .order_by(StudentCareSignal.signal_weight.desc(), StudentCareSignal.id.desc())
        .all()
    )
    if profile and signals:
        return profile, signals
    profile, signals, _, _ = student_care_service.recalculate_student_care_profile(db, student)
    return profile, signals


def _signal_to_dict(item: StudentCareSignal) -> dict:
    return {
        "id": item.id,
        "signal_type": item.signal_type,
        "dimension": item.dimension,
        "signal_text": item.signal_text,
        "signal_weight": float(item.signal_weight or 0),
        "source": item.source,
        "created_at": getattr(item, "created_at", None),
    }


def _infer_root_causes(profile: StudentCareProfile, signals: list[dict], agent_context: dict | None = None) -> list[dict]:
    """
    推断根本原因节点概率。
    
    改进v2.0:
    - 使用动态先验（融合贝叶斯辅助层的输出）
    - 使用边际递减处理证据相关性
    
    Args:
        profile: 学生关怀画像（包含贝叶斯辅助层的维度分数）
        signals: 信号列表
        agent_context: 智能体上下文
    
    Returns:
        根本原因列表（按贡献度排序，最多4个）
    """
    result = []
    for node in DIRECT_CAUSE_KEYS:
        config = ROOT_CAUSE_CONFIG[node]
        matches = []
        for rule in EVIDENCE_RULES[node]:
            matched, evidence = _match_rule(rule, profile, signals, agent_context)
            if matched:
                matches.append({"rule": rule, "evidence": evidence})
        
        # 改进：使用动态先验
        base_prior = config["prior"]
        dynamic_prior = _calculate_dynamic_prior_for_node(base_prior, profile, node)
        
        # 收集似然比
        likelihood_ratios = [item["rule"]["lr"] for item in matches]
        
        # 改进：使用边际递减计算后验
        probability = _calculate_probability(dynamic_prior, likelihood_ratios, use_diminishing=True)
        
        contribution = _clamp_probability(probability * config["impact"])
        result.append(
            {
                "node": node,
                "label": config["label"],
                "base_prior": round(base_prior, 4),
                "dynamic_prior": round(dynamic_prior, 4),
                "probability": probability,
                "impact": round(config["impact"], 4),
                "contribution": contribution,
                "description": config["description"],
                "evidence": [
                    {
                        "rule_id": item["rule"]["id"],
                        "label": item["rule"]["label"],
                        "lr": round(float(item["rule"]["lr"]), 4),
                        "signal_text": item["evidence"].get("signal_text") or item["evidence"].get("summary") or "",
                        "source": item["evidence"].get("source") or "profile",
                    }
                    for item in matches
                ],
            }
        )
    result.sort(key=lambda item: (item["contribution"], item["probability"]), reverse=True)
    return result[:4]


def _match_rule(rule: dict, profile: StudentCareProfile, signals: list[dict], agent_context: dict | None = None) -> tuple[bool, dict]:
    agent_context = agent_context or {}

    score_rule = rule.get("profile_score")
    if score_rule:
        key, threshold = score_rule
        score = float(getattr(profile, key, 0) or 0)
        if score >= threshold:
            return True, {"summary": f"{key}={score:.2f}", "source": "profile"}

    score_max_rule = rule.get("profile_score_max")
    if score_max_rule:
        key, threshold = score_max_rule
        score = float(getattr(profile, key, 0) or 0)
        if score <= threshold:
            return True, {"summary": f"{key}={score:.2f}", "source": "profile"}

    if rule.get("agent_context") == "social_summary":
        summary = str(agent_context.get("social_summary") or "").strip()
        risk_level = str(agent_context.get("social_risk_level") or "").strip()
        if summary and risk_level in {"attention", "medium", "high"}:
            return True, {"summary": summary, "signal_text": summary, "source": "agent_social_summary"}

    if rule.get("agent_context") == "social_evidence":
        evidence_items = [str(item).strip() for item in (agent_context.get("social_evidence") or []) if str(item).strip()]
        if evidence_items:
            summary = "；".join(evidence_items[:2])
            return True, {"summary": summary, "signal_text": summary, "source": "teacher_confirmed_social_evidence"}

    resolution_statuses = set(rule.get("agent_resolution_status") or ())
    if resolution_statuses:
        resolution_status = str(agent_context.get("resolution_status") or "").strip()
        if resolution_status in resolution_statuses:
            teacher_notes = str(agent_context.get("teacher_notes") or "").strip()
            summary = teacher_notes or f"resolution_status={resolution_status}"
            return True, {"summary": summary, "signal_text": summary, "source": "agent_review"}

    signal_types = set(rule.get("signal_types") or [])
    signal_type_prefixes = tuple(rule.get("signal_type_prefixes") or ())
    keywords = tuple(rule.get("signal_keywords") or ())
    for signal in signals:
        if rule.get("source") and signal.get("source") != rule["source"]:
            continue
        if rule.get("dimension") and signal.get("dimension") != rule["dimension"]:
            continue
        if signal_types and signal.get("signal_type") not in signal_types:
            if not signal_type_prefixes or not any(str(signal.get("signal_type") or "").startswith(prefix) for prefix in signal_type_prefixes):
                continue
        elif signal_type_prefixes and not any(str(signal.get("signal_type") or "").startswith(prefix) for prefix in signal_type_prefixes):
            continue
        if keywords and not any(keyword in str(signal.get("signal_text") or "") for keyword in keywords):
            continue
        if signal_types or signal_type_prefixes or keywords or rule.get("source") or rule.get("dimension"):
            return True, signal
    return False, {}


def _calculate_probability(prior: float, likelihood_ratios: list[float], use_diminishing: bool = True) -> float:
    """
    计算贝叶斯后验概率。
    
    改进v2.0:
    - 使用共享的边际递减函数处理证据相关性
    
    Args:
        prior: 先验概率
        likelihood_ratios: 似然比列表
        use_diminishing: 是否使用边际递减（默认True）
    
    Returns:
        后验概率
    """
    if prior <= 0:
        return 0.0
    if prior >= 1:
        return 1.0
    
    # 应用边际递减
    if use_diminishing and likelihood_ratios:
        adjusted_lrs = apply_diminishing_returns(likelihood_ratios, method="sqrt")
    else:
        adjusted_lrs = likelihood_ratios
    
    odds = prior / (1 - prior)
    for lr in adjusted_lrs:
        odds *= max(float(lr), 0.05)
    posterior = odds / (1 + odds)
    return _clamp_probability(posterior)


def _calculate_dynamic_prior_for_node(base_prior: float, profile: StudentCareProfile, node: str) -> float:
    """
    为网络节点计算动态先验。
    
    改进v2.0:
    - 从贝叶斯辅助层的输出（画像分数）获取动态信息
    - 公式: dynamic_prior = base_prior + (1 - base_prior) * dimension_score * 0.3
    
    Args:
        base_prior: 基准先验概率
        profile: 学生关怀画像（包含贝叶斯辅助层的输出）
        node: 网络节点名称
    
    Returns:
        动态先验概率
    """
    dimension = NODE_TO_DIMENSION.get(node)
    if not dimension or not profile:
        return base_prior
    
    # 从画像获取维度分数
    score_attr = f"{dimension}_score"
    dimension_score = float(getattr(profile, score_attr, 0) or 0)
    
    # 计算动态先验
    dynamic_prior = base_prior + (1 - base_prior) * dimension_score * 0.3
    return _clamp_probability(dynamic_prior)


def _derive_social_withdrawal_probability(node_probabilities: dict[str, float]) -> float:
    contributions = [
        node_probabilities.get("emotional_withdrawal", 0) * 0.63,
        node_probabilities.get("peer_disconnect", 0) * 0.58,
        node_probabilities.get("behavior_retreat", 0) * 0.46,
    ]
    return _clamp_probability(1 - prod(max(0.01, 1 - value) for value in contributions))


def _derive_isolation_risk(node_probabilities: dict[str, float], social_withdrawal_probability: float) -> float:
    contributions = [
        social_withdrawal_probability * 0.78,
        node_probabilities.get("peer_disconnect", 0) * 0.72,
        node_probabilities.get("safety_threat", 0) * 0.28,
    ]
    return _clamp_probability(1 - prod(max(0.01, 1 - value) for value in contributions))


def _collect_protective_factors(profile: StudentCareProfile, signals: list[dict], agent_context: dict | None = None) -> list[dict]:
    items = []
    for rule in PROTECTIVE_RULES:
        matched, evidence = _match_rule(rule, profile, signals, agent_context)
        if not matched:
            continue
        items.append(
            {
                "id": rule["id"],
                "label": rule["label"],
                "weight": round(float(rule["weight"]), 4),
                "signal_text": evidence.get("signal_text") or evidence.get("summary") or "",
                "source": evidence.get("source") or "profile",
            }
        )
    items.sort(key=lambda item: item["weight"], reverse=True)
    return items


def _build_social_data_coverage(signals: list[dict], agent_context: dict | None = None) -> dict:
    agent_context = agent_context or {}
    covered_items = []
    missing_items = []
    for item in SOCIAL_DATA_REQUIREMENTS:
        matched = bool(item["match"](signals, agent_context))
        target = covered_items if matched else missing_items
        target.append(
            {
                "id": item["id"],
                "label": item["label"],
                "description": item["description"],
                "action_hint": item["action_hint"],
            }
        )
    total = len(SOCIAL_DATA_REQUIREMENTS)
    covered = len(covered_items)
    coverage_ratio = round(covered / total, 4) if total else 0
    return {
        "covered_count": covered,
        "required_count": total,
        "coverage_ratio": coverage_ratio,
        "evidence_sufficient": coverage_ratio >= 0.6,
        "covered_items": covered_items,
        "missing_items": missing_items,
    }


def _build_social_trend(signals: list[dict], social_data_coverage: dict) -> dict:
    social_signals = [item for item in signals if item.get("dimension") == "social"]
    recent = []
    historical = []
    now = datetime.now(timezone.utc)

    for item in social_signals:
        created_at = item.get("created_at")
        weight = float(item.get("signal_weight") or 0)
        if isinstance(created_at, datetime):
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            days_delta = (now - created_at).days
            if days_delta <= 14:
                recent.append(weight)
            else:
                historical.append(weight)
        else:
            recent.append(weight)

    recent_risk = sum(weight for weight in recent if weight > 0)
    recent_support = abs(sum(weight for weight in recent if weight < 0))
    historical_risk = sum(weight for weight in historical if weight > 0)
    net_recent = recent_risk - recent_support

    if recent_support > recent_risk and recent_support >= 0.08:
        direction = "improving"
        summary = "近期出现更多正向社交证据，孤立状态有改善迹象。"
    elif net_recent >= max(0.18, historical_risk + 0.05):
        direction = "worsening"
        summary = "近期负向社交信号上升，孤立风险有加重迹象。"
    else:
        direction = "stable"
        summary = "近期社交信号整体平稳，建议继续观察班级互动变化。"

    if not social_data_coverage.get("evidence_sufficient", False):
        summary = f"{summary} 当前社交证据仍不足，趋势判断可信度有限。"

    return {
        "direction": direction,
        "summary": summary,
        "recent_risk_weight": round(recent_risk, 4),
        "recent_support_weight": round(recent_support, 4),
        "historical_risk_weight": round(historical_risk, 4),
    }


def _build_propagation_paths(node_probabilities: dict[str, float], social_withdrawal_probability: float) -> list[dict]:
    path_templates = [
        (
            "family_support_gap",
            ["家庭支持不足", "情绪退缩", "社交退缩", "孤立风险"],
            node_probabilities.get("family_support_gap", 0) * 0.55 * max(node_probabilities.get("emotional_withdrawal", 0), 0.01) * 0.63 * max(social_withdrawal_probability, 0.01) * 0.78,
            "家庭支持不足会先推高情绪退缩，再经由社交退缩传导到孤立风险。",
        ),
        (
            "safety_threat",
            ["安全威胁暴露", "情绪退缩", "社交退缩", "孤立风险"],
            node_probabilities.get("safety_threat", 0) * 0.42 * max(node_probabilities.get("emotional_withdrawal", 0), 0.01) * 0.63 * max(social_withdrawal_probability, 0.01) * 0.78,
            "安全威胁会诱发回避和警觉，进一步削弱与同伴的稳定连接。",
        ),
        (
            "peer_disconnect",
            ["同伴连接缺失", "社交退缩", "孤立风险"],
            node_probabilities.get("peer_disconnect", 0) * 0.58 * max(social_withdrawal_probability, 0.01) * 0.78,
            "稳定同伴连接不足会直接推动社交退缩，并放大孤立风险。",
        ),
        (
            "behavior_retreat",
            ["行为退避", "社交退缩", "孤立风险"],
            node_probabilities.get("behavior_retreat", 0) * 0.46 * max(social_withdrawal_probability, 0.01) * 0.78,
            "出勤和行为退避会减少集体参与频率，间接推高孤立风险。",
        ),
    ]
    paths = [
        {"path_id": path_id, "nodes": nodes, "path_probability": _clamp_probability(score), "summary": summary}
        for path_id, nodes, score, summary in path_templates
        if score >= 0.08
    ]
    paths.sort(key=lambda item: item["path_probability"], reverse=True)
    return paths[:3]


def _estimate_confidence(signals: list[dict], root_causes: list[dict], protective_factors: list[dict]) -> float:
    positive_signals = [item for item in signals if float(item.get("signal_weight") or 0) > 0]
    graph_count = sum(1 for item in positive_signals if item.get("source") == "graph")
    dimension_count = len({item.get("dimension") for item in positive_signals if item.get("dimension")})
    root_evidence_count = sum(len(item["evidence"]) for item in root_causes)
    confidence = 0.42
    confidence += min(len(positive_signals), 6) * 0.05
    confidence += min(graph_count, 2) * 0.05
    confidence += min(dimension_count, 4) * 0.03
    confidence += min(root_evidence_count, 5) * 0.03
    if protective_factors:
        confidence += 0.03
    return _clamp_probability(min(confidence, 0.93))


def _select_key_evidence(root_causes: list[dict]) -> list[dict]:
    items = []
    for cause in root_causes:
        for evidence in cause["evidence"][:2]:
            items.append(
                {
                    "cause": cause["label"],
                    "label": evidence["label"],
                    "signal_text": evidence["signal_text"],
                    "source": evidence["source"],
                }
            )
    return items[:6]


def _build_evidence_source_groups(root_causes: list[dict], protective_factors: list[dict]) -> list[dict]:
    grouped_items = {key: [] for key in SOURCE_GROUP_META}

    for cause in root_causes:
        for item in cause.get("evidence") or []:
            group_key = _source_group_for_source(item.get("source"))
            grouped_items[group_key].append(
                {
                    "label": item.get("label") or "",
                    "signal_text": item.get("signal_text") or "",
                    "source": item.get("source") or "",
                    "cause": cause.get("label") or "",
                }
            )

    for item in protective_factors[:3]:
        group_key = _source_group_for_source(item.get("source"))
        grouped_items[group_key].append(
            {
                "label": item.get("label") or "",
                "signal_text": item.get("signal_text") or "",
                "source": item.get("source") or "",
                "cause": "保护因子",
            }
        )

    result = []
    for group_key, meta in SOURCE_GROUP_META.items():
        items = grouped_items[group_key]
        if not items:
            continue
        result.append(
            {
                "id": group_key,
                "label": meta["label"],
                "description": meta["description"],
                "count": len(items),
                "items": items[:3],
            }
        )
    return result


def _source_group_for_source(source: str | None) -> str:
    source = str(source or "").strip()
    if source in {"teacher_confirmed_social_evidence", "agent_review"}:
        return "teacher_feedback"
    if source in {"assistant_summary", "agent_social_summary"}:
        return "ai_signal"
    if source == "profile":
        return "inference"
    return "fact"


def _build_evidence_interpretation(social_data_coverage: dict, social_trend: dict, evidence_source_groups: list[dict]) -> list[dict]:
    notes = []
    if not social_data_coverage.get("evidence_sufficient"):
        notes.append(
            {
                "id": "coverage_gap",
                "label": "证据仍有缺口",
                "summary": "当前社交证据覆盖不足，结论更适合作为提醒而不是最终定性。",
            }
        )
    if social_trend.get("direction") == "worsening":
        notes.append(
            {
                "id": "trend_worsening",
                "label": "近期风险在抬升",
                "summary": "近期负向社交线索多于支持性线索，建议优先核查课间独处、互动回避或冲突排斥。",
            }
        )
    if social_trend.get("direction") == "improving":
        notes.append(
            {
                "id": "trend_improving",
                "label": "近期存在缓解迹象",
                "summary": "近期支持性线索更多，建议结合老师观察确认改善是否稳定。",
            }
        )
    if any(item["id"] == "teacher_feedback" for item in evidence_source_groups):
        notes.append(
            {
                "id": "teacher_feedback_linked",
                "label": "已联动老师复核",
                "summary": "本次判断已参考教师复核或教师确认的社交线索，连续性更好。",
            }
        )
    return notes[:3]


def _get_recent_agent_context(db: Session, student_id: int) -> dict:
    if db is None:
        return {
            "has_agent_record": False,
            "social_summary": "",
            "social_evidence": [],
            "social_risk_level": "",
            "resolution_status": "",
            "teacher_notes": "",
            "review_status": "pending",
        }

    record = (
        db.query(StudentCareAgentRecord)
        .filter(StudentCareAgentRecord.student_id == student_id)
        .order_by(StudentCareAgentRecord.id.desc())
        .first()
    )
    if not record:
        return {
            "has_agent_record": False,
            "social_summary": "",
            "social_evidence": [],
            "social_risk_level": "",
            "resolution_status": "",
            "teacher_notes": "",
            "review_status": "pending",
        }

    payload = record.reviewed_result_json if record.review_status == "confirmed" and record.reviewed_result_json else record.result_json
    payload = payload or {}
    social_dimension = next(
        (item for item in payload.get("dimensions", []) if isinstance(item, dict) and item.get("dimension") == "social"),
        {},
    )
    return {
        "has_agent_record": True,
        "social_summary": str(social_dimension.get("summary") or "").strip(),
        "social_evidence": [str(item).strip() for item in (social_dimension.get("evidence") or []) if str(item).strip()][:3],
        "social_risk_level": str(social_dimension.get("risk_level") or "").strip(),
        "resolution_status": str(record.resolution_status or "").strip(),
        "teacher_notes": str(record.teacher_notes or "").strip(),
        "review_status": str(record.review_status or "pending"),
    }


def _risk_level(value: float) -> str:
    if value >= 0.7:
        return "high"
    if value >= 0.5:
        return "medium"
    if value >= 0.3:
        return "attention"
    return "low"


def _clamp_probability(value: float) -> float:
    return round(min(max(float(value or 0), 0.0), 1.0), 4)
