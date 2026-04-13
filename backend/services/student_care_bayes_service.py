# -*- coding: utf-8 -*-
"""Bayesian helper service for student care.

改进版本 v2.0:
- 引入边际递减机制处理证据相关性
- 扩展social维度证据匹配
- 添加保护性证据(LR<1)支持
- 使用动态先验替代固定先验
"""

from __future__ import annotations

import math

from core.student_care_bayes_config import STUDENT_CARE_BAYES_CONFIG


# ============================================================================
# 关键词提示词
# ============================================================================

BRUISE_HINTS = ("淤青", "伤", "受伤", "流血", "打了", "被打")
WORRY_HINTS = ("担忧", "害怕", "恐惧", "不安", "紧张")
FAMILY_VIOLENCE_HINTS = ("家暴", "殴打", "打骂", "被打", "暴力")
DISTRESS_HINTS = ("难受", "害怕", "低落", "崩溃", "想哭", "不想上学", "焦虑", "压抑")
FAMILY_ISSUE_HINTS = ("家庭", "家里", "父母", "监护", "照顾", "支持不足", "困难", "不耐烦", "打牌")

# 社交维度关键词
SOCIAL_DISTRESS_HINTS = ("没朋友", "被孤立", "被排挤", "融入不了", "没有人理", "被欺负", "无法融入", "孤立", "没有朋友")
SOCIAL_POSITIVE_HINTS = ("好转", "改善", "融入", "有朋友", "朋友多了", "合群", "互动增加", "社交改善")


# ============================================================================
# 基础工具函数
# ============================================================================

def _clamp_probability(value: float) -> float:
    """将概率值限制在[0, 1]范围内"""
    return round(min(max(value, 0.0), 1.0), 4)


def _normalize_text(value: str | None) -> str:
    """标准化文本：去空格、转小写"""
    return (value or "").strip().lower()


def _has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """检查文本是否包含任一关键词"""
    normalized = _normalize_text(text)
    return any(keyword in normalized for keyword in keywords)


# ============================================================================
# 边际递减函数（处理证据相关性）
# ============================================================================

def apply_diminishing_returns(lrs: list[float], method: str = "sqrt") -> list[float]:
    """
    对似然比应用边际递减，处理证据相关性问题。
    
    数学原理：
    贝叶斯定理假设证据条件独立，但实际场景中多个证据往往相关性较高。
    边际递减通过降低后续证据的权重来缓解这个问题。
    
    Args:
        lrs: 似然比列表
        method: 递减方法
            - "sqrt": 第n个证据权重 = LR^(1/√n)，推荐
            - "log": 边际效应线性递减
            - "none": 不应用递减
    
    Returns:
        调整后的似然比列表
    
    Examples:
        >>> apply_diminishing_returns([4.5, 2.2])
        [4.5, 1.66]  # 第二个证据被衰减
    """
    if not lrs:
        return []
    
    adjusted = []
    for i, lr in enumerate(lrs, start=1):
        if method == "sqrt":
            # 第1个证据: LR^1, 第2个: LR^0.707, 第3个: LR^0.577...
            adj_lr = lr ** (1.0 / math.sqrt(i))
        elif method == "log":
            # 边际效应线性递减
            adj_lr = 1.0 + (lr - 1.0) / i
        else:
            adj_lr = lr
        # 确保LR不会过小（最小0.05，对应约5%的风险调整）
        adjusted.append(max(adj_lr, 0.05))
    
    return adjusted


def _match_safety_evidence(signals: list[dict], teacher_reviews: list[dict]) -> list[dict]:
    matched: dict[str, dict] = {}

    for item in signals:
        source = item.get("source")
        signal_type = item.get("signal_type")
        text = item.get("signal_text") or ""

        if source == "assistant_summary" and (
            signal_type == "assistant_safety_disclosure" or _has_any_keyword(text, BRUISE_HINTS)
        ):
            matched["assistant_self_report_assault"] = {"key": "assistant_self_report_assault", "text": text}

        if source == "attendance" and _has_any_keyword(text, BRUISE_HINTS):
            matched["attendance_bruise_remark"] = {"key": "attendance_bruise_remark", "text": text}

        if source == "attendance" and _has_any_keyword(text, WORRY_HINTS):
            matched["attendance_worried_remark"] = {"key": "attendance_worried_remark", "text": text}

        if source == "behavior_event" and signal_type == "behavior_conflict":
            matched["behavior_conflict"] = {"key": "behavior_conflict", "text": text}

        if source == "behavior_event" and signal_type == "behavior_bullying":
            matched["behavior_bullying"] = {"key": "behavior_bullying", "text": text}

        if source == "family_contact" and _has_any_keyword(text, FAMILY_VIOLENCE_HINTS):
            matched["family_violence_hint"] = {"key": "family_violence_hint", "text": text}

        if source == "graph" and signal_type == "graph_conflict_cooccurrence":
            matched["graph_conflict_cooccurrence"] = {"key": "graph_conflict_cooccurrence", "text": text}

    for review in teacher_reviews or []:
        resolution_status = review.get("resolution_status")
        if resolution_status == "resolved":
            matched["teacher_review_resolved"] = {
                "key": "teacher_review_resolved",
                "text": review.get("teacher_notes") or "老师确认已处理完成",
            }
        elif resolution_status == "false_alarm":
            matched["teacher_review_false_alarm"] = {
                "key": "teacher_review_false_alarm",
                "text": review.get("teacher_notes") or "老师确认本次为误报",
            }

    return list(matched.values())


def _match_emotion_evidence(signals: list[dict], teacher_reviews: list[dict]) -> list[dict]:
    """
    匹配情绪维度的贝叶斯证据。
    
    改进v2.0:
    - 新增保护性证据：情绪好转、正向表达等
    """
    matched: dict[str, dict] = {}

    # 正向情绪关键词（保护性证据）
    POSITIVE_EMOTION_HINTS = ("好转", "缓解", "稳定", "开心", "放松", "积极", "乐观", "情绪改善")

    for item in signals:
        source = item.get("source")
        signal_type = item.get("signal_type") or ""
        text = item.get("signal_text") or ""

        # 负向证据（LR > 1）
        if source == "score" and signal_type == "score_drop_emotion":
            matched["score_drop_emotion"] = {"key": "score_drop_emotion", "text": text}

        if source == "attendance" and _has_any_keyword(text, WORRY_HINTS):
            matched["attendance_worried_remark"] = {"key": "attendance_worried_remark", "text": text}

        if source == "assistant_summary" and (
            signal_type == "assistant_safety_disclosure" or _has_any_keyword(text, DISTRESS_HINTS)
        ):
            matched["assistant_self_report_distress"] = {"key": "assistant_self_report_distress", "text": text}

        if source == "care_observation" and item.get("dimension") == "emotion":
            # 检查是否是正向信号
            if _has_any_keyword(text, POSITIVE_EMOTION_HINTS) or signal_type.startswith("care_observation_positive"):
                matched["care_talk_positive"] = {"key": "care_talk_positive", "text": text}
            else:
                matched["care_observation_emotion"] = {"key": "care_observation_emotion", "text": text}
                if signal_type == "care_observation_care_talk":
                    matched["care_talk_low_mood"] = {"key": "care_talk_low_mood", "text": text}

        if source == "family_contact" and _has_any_keyword(text, ("不耐烦", "冲突", "压力", "打骂")):
            matched["family_negative_contact"] = {"key": "family_negative_contact", "text": text}

        # 保护性证据：AI对话中的正向情绪表达
        if source == "assistant_summary" and _has_any_keyword(text, POSITIVE_EMOTION_HINTS):
            matched["assistant_positive_mood"] = {"key": "assistant_positive_mood", "text": text}

    for review in teacher_reviews or []:
        resolution_status = review.get("resolution_status")
        if resolution_status == "resolved":
            matched["teacher_review_resolved"] = {
                "key": "teacher_review_resolved",
                "text": review.get("teacher_notes") or "老师确认情绪问题已缓解",
            }
        elif resolution_status == "false_alarm":
            matched["teacher_review_false_alarm"] = {
                "key": "teacher_review_false_alarm",
                "text": review.get("teacher_notes") or "老师确认当前并无持续情绪风险",
            }

    return list(matched.values())


def _match_family_evidence(signals: list[dict], teacher_reviews: list[dict]) -> list[dict]:
    matched: dict[str, dict] = {}

    for item in signals:
        source = item.get("source")
        signal_type = item.get("signal_type")
        text = item.get("signal_text") or ""

        if signal_type == "tag_family":
            matched["tag_family_hardship"] = {"key": "tag_family_hardship", "text": text}

        if source == "family_contact" and _has_any_keyword(text, FAMILY_ISSUE_HINTS):
            matched["family_contact_negative"] = {"key": "family_contact_negative", "text": text}

        if source == "family_contact" and _has_any_keyword(text, FAMILY_VIOLENCE_HINTS):
            matched["family_violence_hint"] = {"key": "family_violence_hint", "text": text}

        if source == "attendance" and _has_any_keyword(text, ("家庭", "家里", "家长", "父母")):
            matched["attendance_family_issue"] = {"key": "attendance_family_issue", "text": text}

        if source == "assistant_summary" and _has_any_keyword(text, ("家里", "父母", "家庭", "没人管", "不想回家")):
            matched["assistant_family_distress"] = {"key": "assistant_family_distress", "text": text}

    for review in teacher_reviews or []:
        resolution_status = review.get("resolution_status")
        if resolution_status == "resolved":
            matched["teacher_review_resolved"] = {
                "key": "teacher_review_resolved",
                "text": review.get("teacher_notes") or "老师确认家庭支持问题已缓解",
            }
        elif resolution_status == "false_alarm":
            matched["teacher_review_false_alarm"] = {
                "key": "teacher_review_false_alarm",
                "text": review.get("teacher_notes") or "老师确认当前并无持续家庭支持风险",
            }

    return list(matched.values())


def _match_social_evidence(signals: list[dict], teacher_reviews: list[dict]) -> list[dict]:
    """
    匹配社交维度的贝叶斯证据。
    
    改进v2.0:
    - 新增手工图谱社交冲突证据
    - 新增关怀观察中的社交问题证据
    - 新增AI对话中的社交困扰证据
    - 新增保护性证据（正向社交信号）
    """
    matched: dict[str, dict] = {}

    for item in signals:
        source = item.get("source")
        signal_type = item.get("signal_type") or ""
        text = item.get("signal_text") or ""

        # 1. 图谱社交孤立（原有）
        if source == "graph" and signal_type == "graph_social_isolation":
            matched["graph_social_isolation"] = {"key": "graph_social_isolation", "text": text}

        # 2. 手工添加的社交冲突（新增）
        if source == "graph" and signal_type.startswith("graph_manual_student_conflict"):
            matched["graph_manual_conflict"] = {"key": "graph_manual_conflict", "text": text}

        # 3. 关怀观察中的社交问题（新增）
        if source == "care_observation" and item.get("dimension") == "social":
            # 负向：社交困难
            if _has_any_keyword(text, SOCIAL_DISTRESS_HINTS) or "无法融入" in text:
                matched["social_difficulty_report"] = {"key": "social_difficulty_report", "text": text}
            else:
                # 一般社交观察
                matched["care_observation_social"] = {"key": "care_observation_social", "text": text}

        # 4. AI对话中的社交困扰（新增）
        if source == "assistant_summary" and item.get("dimension") == "social":
            if _has_any_keyword(text, SOCIAL_DISTRESS_HINTS):
                matched["assistant_social_distress"] = {"key": "assistant_social_distress", "text": text}

        # 5. 保护性证据：正向社交信号（新增）
        if source == "care_observation" and signal_type.startswith("care_observation_positive"):
            matched["care_observation_positive_social"] = {"key": "care_observation_positive_social", "text": text}

        if source == "graph" and signal_type in ("graph_manual_student_peer_support", "graph_manual_student_shared_activity"):
            matched["graph_peer_support"] = {"key": "graph_peer_support", "text": text}

        if source == "assistant_summary" and _has_any_keyword(text, SOCIAL_POSITIVE_HINTS):
            matched["assistant_positive_social"] = {"key": "assistant_positive_social", "text": text}

    # 教师确认
    for review in teacher_reviews or []:
        resolution_status = review.get("resolution_status")
        if resolution_status == "resolved":
            matched["teacher_review_resolved"] = {
                "key": "teacher_review_resolved",
                "text": review.get("teacher_notes") or "教师确认当前社交融入问题已缓解",
            }
        elif resolution_status == "false_alarm":
            matched["teacher_review_false_alarm"] = {
                "key": "teacher_review_false_alarm",
                "text": review.get("teacher_notes") or "教师确认当前并无持续社交风险",
            }

    return list(matched.values())


def _calculate_posterior(prior: float, likelihood_ratios: list[float], use_diminishing: bool = True) -> float:
    """
    计算贝叶斯后验概率。
    
    改进v2.0:
    - 支持边际递减处理证据相关性
    
    Args:
        prior: 先验概率
        likelihood_ratios: 似然比列表
        use_diminishing: 是否使用边际递减（默认True）
    
    Returns:
        后验概率
    """
    prior = _clamp_probability(prior)
    if prior <= 0:
        return 0.0
    if prior >= 1:
        return 1.0
    
    # 应用边际递减（默认启用）
    if use_diminishing:
        adjusted_lrs = apply_diminishing_returns(likelihood_ratios, method="sqrt")
    else:
        adjusted_lrs = likelihood_ratios
    
    # 计算后验几率
    odds = prior / (1 - prior)
    for lr in adjusted_lrs:
        odds *= max(lr, 0.05)
    posterior = odds / (1 + odds)
    return _clamp_probability(posterior)


def _calculate_dynamic_prior(base_prior: float, linear_score: float, alpha: float = 0.3) -> float:
    """
    计算动态先验概率。
    
    改进v2.0:
    - 将线性分数映射为先验概率的动态调整
    - 线性分数反映"基于历史数据的基线风险"
    
    公式: dynamic_prior = base_prior + (1 - base_prior) * linear_score * alpha
    
    Args:
        base_prior: 基准先验概率（来自配置）
        linear_score: 线性累加分数
        alpha: 动态调整系数（默认0.3）
    
    Returns:
        动态先验概率
    """
    linear_score = _clamp_probability(linear_score)
    dynamic_prior = base_prior + (1 - base_prior) * linear_score * alpha
    return _clamp_probability(dynamic_prior)


def build_bayes_result(
    dimension: str,
    linear_score: float,
    signals: list[dict],
    teacher_reviews: list[dict] | None = None,
    bayes_config: dict | None = None,
) -> dict:
    """
    构建单维度的贝叶斯推断结果。
    
    改进v2.0:
    1. 使用动态先验替代固定先验
    2. 应用边际递减处理证据相关性
    3. 最终分数直接使用后验概率（取消混合公式）
    
    Args:
        dimension: 维度名称
        linear_score: 线性累加分数
        signals: 信号列表
        teacher_reviews: 教师审核列表
        bayes_config: 贝叶斯配置
    
    Returns:
        贝叶斯推断结果字典
    """
    config_source = bayes_config or STUDENT_CARE_BAYES_CONFIG
    config = config_source.get(dimension, {})
    if not config.get("enabled"):
        return {"enabled": False, "dimension": dimension}

    teacher_reviews = teacher_reviews or []
    evidence_rules = config.get("evidence_rules", {})
    
    # 匹配证据
    if dimension == "safety":
        matches = _match_safety_evidence(signals, teacher_reviews)
    elif dimension == "emotion":
        matches = _match_emotion_evidence(signals, teacher_reviews)
    elif dimension == "family":
        matches = _match_family_evidence(signals, teacher_reviews)
    elif dimension == "social":
        matches = _match_social_evidence(signals, teacher_reviews)
    else:
        matches = []

    # 收集似然比
    evidence_details = []
    likelihood_ratios = []
    for item in matches:
        lr = float(evidence_rules.get(item["key"], 1.0))
        likelihood_ratios.append(lr)
        evidence_details.append(
            {
                "key": item["key"],
                "matched": True,
                "lr": round(lr, 4),
                "text": item.get("text") or "",
            }
        )

    # 计算动态先验
    base_prior = float(config.get("prior", 0.0))
    dynamic_prior = _calculate_dynamic_prior(base_prior, linear_score, alpha=0.3)
    
    # 计算后验（使用边际递减）
    posterior = _calculate_posterior(dynamic_prior, likelihood_ratios, use_diminishing=True)
    
    # 改进：直接使用后验概率作为最终分数
    # 取消旧的混合公式: blend_alpha * linear_score + (1-blend_alpha) * posterior
    # 因为动态先验已经融合了线性分数的信息
    final_score = posterior

    return {
        "enabled": True,
        "dimension": dimension,
        "base_prior": _clamp_probability(base_prior),
        "dynamic_prior": dynamic_prior,
        "linear_score": _clamp_probability(linear_score),
        "posterior": posterior,
        "final_score": final_score,
        "evidence_keys": [item["key"] for item in evidence_details],
        "evidence_details": evidence_details,
        "inference_version": "bayes_v2",
    }


def build_bayes_results(
    dimension_scores: dict[str, float],
    signals: list[dict],
    teacher_reviews: list[dict] | None = None,
    bayes_config: dict | None = None,
) -> dict:
    results = {}
    config_source = bayes_config or STUDENT_CARE_BAYES_CONFIG
    for dimension, linear_score in dimension_scores.items():
        config = config_source.get(dimension)
        if not config or not config.get("enabled"):
            continue
        results[dimension] = build_bayes_result(
            dimension=dimension,
            linear_score=float(linear_score or 0.0),
            signals=signals,
            teacher_reviews=teacher_reviews,
            bayes_config=config_source,
        )
    return results
