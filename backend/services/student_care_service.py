# -*- coding: utf-8 -*-
"""Student care profile service."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from math import prod

from sqlalchemy import case
from sqlalchemy.orm import Session

from core.response import error_response, success_response
from database.models.class_ import Class
from database.models.score import Score
from database.models.student import Student
from database.models.student_assistant_summary import StudentAssistantSummary
from database.models.student_attendance import StudentAttendance
from database.models.student_behavior_event import StudentBehaviorEvent
from database.models.student_care_observation import StudentCareObservation
from database.models.student_care_profile import StudentCareProfile
from database.models.student_care_signal import StudentCareSignal
from database.models.student_care_agent_record import StudentCareAgentRecord
from database.models.student_care_graph_relation import StudentCareGraphRelation
from database.models.student_family_contact import StudentFamilyContact
from database.models.student_tag_definition import StudentTagDefinition
from database.models.teacher import Teacher
from database.models.user import User
from services.student_care_bayes_config_service import get_effective_bayes_config
from services.student_care_bayes_service import apply_diminishing_returns
from services.student_care_bayes_service import build_bayes_results
from services.student_care_graph_service import student_care_graph_service
from services.student_care_schema_guard import ensure_student_care_schema


DIMENSIONS = ("emotion", "social", "safety", "family", "study", "behavior")

OVERALL_WEIGHTS = {
    "emotion": 0.18,
    "social": 0.18,
    "safety": 0.18,
    "family": 0.18,
    "study": 0.16,
    "behavior": 0.12,
}

MANUAL_GRAPH_RELATION_POLARITY = {
    "peer_support": -1,
    "shared_activity": -1,
    "conflict": 1,
    "bullying_link": 1,
    "concern": 1,
}

ATTENDANCE_BEHAVIOR_WEIGHTS = {
    "late": 0.2,
    "absent": 0.35,
    "early_leave": 0.15,
}

BEHAVIOR_EVENT_WEIGHTS = {
    "low": 0.25,
    "medium": 0.4,
    "high": 0.6,
}

SAFETY_EVENT_TYPES = {"conflict", "bullying", "threat", "dorm_conflict", "cyber_conflict"}

CARE_OBSERVATION_WEIGHTS = {
    "low": 0.18,
    "medium": 0.35,
    "high": 0.55,
}

TIME_DECAY_WINDOWS = (
    (7, 1.0),
    (30, 0.75),
    (90, 0.45),
)

TEXT_NEGATIVE_HINTS = (
    "低落",
    "焦虑",
    "孤立",
    "冲突",
    "打骂",
    "欺凌",
    "受伤",
    "害怕",
    "不耐烦",
    "紧张",
    "回避",
    "独处",
    "迟到",
    "缺勤",
    "早退",
    "请假",
    "困难",
    "压力",
    "异常",
    "波动",
    "无助",
    "失控",
    "退缩",
)

TEXT_POSITIVE_HINTS = (
    "好转",
    "缓解",
    "稳定",
    "支持",
    "陪伴",
    "参与",
    "积极",
    "主动",
    "融入",
    "适应",
    "愿意",
    "恢复",
    "配合",
    "改善",
    "鼓励",
    "同伴支持",
    "共同活动",
    "家长支持",
    "情绪稳定",
)

TAG_SIGNAL_RULES = [
    {"keyword": "心理关爱", "dimension": "emotion", "weight": 0.38, "signal_type": "tag_emotion", "text": "学生标签包含“心理关爱”"},
    {"keyword": "学困生", "dimension": "study", "weight": 0.45, "signal_type": "tag_study", "text": "学生标签包含“学困生”"},
    {"keyword": "家庭困难", "dimension": "family", "weight": 0.52, "signal_type": "tag_family", "text": "学生标签包含“家庭困难”"},
    {"keyword": "待分班", "dimension": "social", "weight": 0.24, "signal_type": "tag_social", "text": "学生当前处于待分班状态"},
    {"keyword": "迟到", "dimension": "behavior", "weight": 0.42, "signal_type": "tag_behavior", "text": "学生标签包含“迟到”"},
    {"keyword": "违纪", "dimension": "behavior", "weight": 0.55, "signal_type": "tag_behavior", "text": "学生标签包含“违纪”"},
    {"keyword": "打架", "dimension": "safety", "weight": 0.62, "signal_type": "tag_safety", "text": "学生标签包含“打架”"},
]

TAG_NEGATIVE_DEFAULT_WEIGHT = 0.35

DIMENSION_LABELS = {
    "emotion": "情绪状态风险",
    "social": "社交融入风险",
    "safety": "校园安全风险",
    "family": "家庭支持风险",
    "study": "学习压力风险",
    "behavior": "行为稳定风险",
}

MAJOR_INCIDENT_HINTS = (
    "被打",
    "挨打",
    "受伤",
    "勒索",
    "威胁",
    "恐吓",
    "欺凌",
    "霸凌",
    "殴打",
    "围堵",
    "索要钱财",
)

MAJOR_INCIDENT_PROPAGATION_RULES = (
    {
        "from_dimension": "safety",
        "to_dimension": "emotion",
        "signal_type": "major_incident_emotion_spillover",
        "signal_text": "恶性安全事件后，学生短期内更容易出现情绪受损与紧张警觉。",
        "max_weight": 0.22,
        "factor": 0.34,
        "threshold": 0.2,
        "min_weight": 0.08,
    },
    {
        "from_dimension": "safety",
        "to_dimension": "social",
        "signal_type": "major_incident_social_withdrawal",
        "signal_text": "恶性安全事件后，学生可能出现回避同伴、减少互动的社交退缩。",
        "max_weight": 0.2,
        "factor": 0.28,
        "threshold": 0.2,
        "min_weight": 0.06,
    },
    {
        "from_dimension": "emotion",
        "to_dimension": "study",
        "signal_type": "major_incident_study_impact",
        "signal_text": "事件引发的情绪受损可能进一步影响课堂专注和学习承压。",
        "max_weight": 0.16,
        "factor": 0.24,
        "threshold": 0.14,
        "min_weight": 0.05,
    },
    {
        "from_dimension": "safety",
        "to_dimension": "behavior",
        "signal_type": "major_incident_behavior_instability",
        "signal_text": "恶性安全事件后，学生近期更可能出现迟到、回避参与或行为波动。",
        "max_weight": 0.18,
        "factor": 0.22,
        "threshold": 0.2,
        "min_weight": 0.05,
    },
)

MAJOR_INCIDENT_BN_NODE_CONFIG = {
    "safety_threat": {
        "label": "安全威胁持续",
        "dimension": "safety",
        "base_prior": 0.42,
        "profile_weight": 0.45,
        "impact": 0.92,
        "parents": [],
    },
    "emotion_impact": {
        "label": "情绪受损",
        "dimension": "emotion",
        "base_prior": 0.18,
        "profile_weight": 0.32,
        "impact": 0.78,
        "parents": [("safety_threat", 0.64)],
    },
    "social_withdrawal": {
        "label": "社交退缩",
        "dimension": "social",
        "base_prior": 0.14,
        "profile_weight": 0.28,
        "impact": 0.74,
        "parents": [("safety_threat", 0.42), ("emotion_impact", 0.38)],
    },
    "study_decline": {
        "label": "学习下滑",
        "dimension": "study",
        "base_prior": 0.1,
        "profile_weight": 0.24,
        "impact": 0.68,
        "parents": [("emotion_impact", 0.46), ("social_withdrawal", 0.32)],
    },
    "behavior_instability": {
        "label": "行为波动",
        "dimension": "behavior",
        "base_prior": 0.12,
        "profile_weight": 0.3,
        "impact": 0.76,
        "parents": [("safety_threat", 0.5), ("emotion_impact", 0.34)],
    },
}

MAJOR_INCIDENT_BN_EVIDENCE_RULES = {
    "safety_threat": [
        {"source": "behavior_event", "signal_type_prefixes": ("behavior_conflict", "behavior_bullying", "behavior_threat"), "lr": 2.4, "label": "行为安全事件"},
        {"source": "assistant_summary", "signal_type_prefixes": ("assistant_safety_disclosure",), "lr": 2.8, "label": "AI 求助披露"},
        {"source": "graph", "signal_type_prefixes": ("graph_manual_student_conflict", "graph_manual_student_bullying_link"), "lr": 1.8, "label": "图谱冲突/欺凌"},
    ],
    "emotion_impact": [
        {"source": "major_incident", "signal_type_prefixes": ("major_incident_emotion_spillover",), "lr": 2.2, "label": "事件后情绪传导"},
        {"source": "assistant_summary", "dimension": "emotion", "signal_type_prefixes": ("assistant_emotion_disclosure",), "lr": 1.8, "label": "AI 情绪表达"},
        {"source": "attendance", "keywords": ("沮丧", "忧郁", "害怕", "紧张"), "lr": 1.5, "label": "出勤异常伴随情绪备注"},
    ],
    "social_withdrawal": [
        {"source": "major_incident", "signal_type_prefixes": ("major_incident_social_withdrawal",), "lr": 2.0, "label": "事件后社交传导"},
        {"source": "graph", "dimension": "social", "signal_type_prefixes": ("graph_manual_student_conflict",), "lr": 1.6, "label": "图谱冲突关系"},
        {"source": "care_observation", "dimension": "emotion", "keywords": ("无法融入", "不想和同学说话", "被孤立"), "lr": 1.7, "label": "关怀观察中的社交退缩"},
    ],
    "study_decline": [
        {"source": "score", "signal_type_prefixes": ("score_low_average", "score_medium_pressure", "score_drop"), "lr": 2.2, "label": "成绩/学习直接信号"},
        {"source": "major_incident", "signal_type_prefixes": ("major_incident_study_impact",), "lr": 1.9, "label": "事件后学习传导"},
        {"source": "attendance", "signal_type_prefixes": ("attendance_absent", "attendance_late"), "lr": 1.3, "label": "出勤扰动"},
    ],
    "behavior_instability": [
        {"source": "major_incident", "signal_type_prefixes": ("major_incident_behavior_instability",), "lr": 2.0, "label": "事件后行为传导"},
        {"source": "attendance", "signal_type_prefixes": ("attendance_late", "attendance_absent", "attendance_early_leave"), "lr": 1.5, "label": "出勤异常"},
        {"source": "behavior_event", "dimension": "behavior", "signal_type_prefixes": ("behavior_",), "lr": 1.4, "label": "行为波动信号"},
    ],
}


def get_student_care_profile(db: Session, current_user: User, student_id: int) -> dict:
    ensure_student_care_schema()
    db.rollback()
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return error_response(msg="学生不存在")

    permission_error = _ensure_head_teacher_access(db, current_user, student)
    if permission_error:
        return permission_error

    profile, signals, bayes_results, incident_context = recalculate_student_care_profile(db, student)
    return success_response(
        data={
            "student": _serialize_student(student, db),
            "profile": _serialize_profile(profile, bayes_results, incident_context),
            "signals": [_serialize_signal(item) for item in signals],
            "data_quality": _build_data_quality_summary(signals),
            "actions": _build_actions(profile),
        }
    )


def get_student_care_signals(db: Session, current_user: User, student_id: int) -> dict:
    ensure_student_care_schema()
    db.rollback()
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return error_response(msg="学生不存在")

    permission_error = _ensure_head_teacher_access(db, current_user, student)
    if permission_error:
        return permission_error

    _, signals, _, _ = recalculate_student_care_profile(db, student)
    return success_response(data={"list": [_serialize_signal(item) for item in signals]})


def recalculate_student_care_profile(
    db: Session,
    student: Student,
) -> tuple[StudentCareProfile, list[StudentCareSignal], dict, dict]:
    ensure_student_care_schema()
    db.rollback()
    previous_profile = db.query(StudentCareProfile).filter(StudentCareProfile.student_id == student.id).first()
    db.query(StudentCareSignal).filter(StudentCareSignal.student_id == student.id).delete(synchronize_session=False)

    signals_to_create: list[StudentCareSignal] = []
    base_dimension_scores: dict[str, float] = {key: 0.0 for key in DIMENSIONS}
    spillover_scores: dict[str, float] = {key: 0.0 for key in DIMENSIONS}
    trend = "steady"

    tags = _parse_tags(student.tags)
    tag_def_map = _get_tag_definitions(db, student)
    handled_tags: set[str] = set()

    for tag in tags:
        definition = tag_def_map.get(tag)
        if not definition:
            continue
        handled_tags.add(tag)
        if definition.dimension not in DIMENSIONS:
            continue
        polarity = definition.polarity
        weight = definition.weight
        if polarity == "negative":
            weight = weight if weight is not None else TAG_NEGATIVE_DEFAULT_WEIGHT
        else:
            weight = 0.0

        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type=f"tag_{polarity}",
                dimension=definition.dimension,
                signal_text=f"标签“{tag}”被标注为{_polarity_label(polarity)}",
                signal_weight=weight,
                source="tag_definition",
            )
        )
        if weight:
            base_dimension_scores[definition.dimension] += weight

    for tag in tags:
        if tag in handled_tags:
            continue
        for rule in TAG_SIGNAL_RULES:
            if rule["keyword"] in tag:
                signal = StudentCareSignal(
                    student_id=student.id,
                    class_id=student.class_id,
                    signal_type=rule["signal_type"],
                    dimension=rule["dimension"],
                    signal_text=rule["text"],
                    signal_weight=rule["weight"],
                    source="student_tag",
                )
                signals_to_create.append(signal)
                base_dimension_scores[rule["dimension"]] += rule["weight"]

    score_rows = (
        db.query(Score)
        .filter(Score.student_id == student.id)
        .order_by(Score.id.asc())
        .all()
    )
    avg_score = 0.0
    if score_rows:
        numeric_scores = [float(item.score) for item in score_rows]
        avg_score = round(sum(numeric_scores) / len(numeric_scores), 2)
        if avg_score < 70:
            signals_to_create.append(
                StudentCareSignal(
                    student_id=student.id,
                    class_id=student.class_id,
                    signal_type="score_low_average",
                    dimension="study",
                    signal_text=f"学生当前平均分约为 {avg_score}，低于关注阈值",
                    signal_weight=0.4,
                    source="score",
                )
            )
            base_dimension_scores["study"] += 0.4
        elif avg_score < 80:
            signals_to_create.append(
                StudentCareSignal(
                    student_id=student.id,
                    class_id=student.class_id,
                    signal_type="score_medium_pressure",
                    dimension="study",
                    signal_text=f"学生当前平均分约为 {avg_score}，存在一定学习压力",
                    signal_weight=0.22,
                    source="score",
                )
            )
            base_dimension_scores["study"] += 0.22

        batch_map = defaultdict(list)
        for item in score_rows:
            batch_map[item.exam_batch].append(float(item.score))
        batch_avgs = [(batch, round(sum(values) / len(values), 2)) for batch, values in batch_map.items()]
        if len(batch_avgs) >= 2:
            prev_avg = batch_avgs[-2][1]
            latest_batch, latest_avg = batch_avgs[-1]
            if latest_avg <= prev_avg - 8:
                signals_to_create.append(
                    StudentCareSignal(
                        student_id=student.id,
                        class_id=student.class_id,
                        signal_type="score_drop",
                        dimension="study",
                        signal_text=f"{latest_batch}较上一阶段平均分下降明显（{prev_avg} -> {latest_avg}）",
                        signal_weight=0.18,
                        source="score",
                    )
                )
                signals_to_create.append(
                    StudentCareSignal(
                        student_id=student.id,
                        class_id=student.class_id,
                        signal_type="score_drop_emotion",
                        dimension="emotion",
                        signal_text=f"{latest_batch}成绩阶段性下滑，需关注情绪波动",
                        signal_weight=0.12,
                        source="score",
                    )
                )
                base_dimension_scores["study"] += 0.18
                base_dimension_scores["emotion"] += 0.12
                trend = "up"
    else:
        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type="score_missing",
                dimension="study",
                signal_text="当前缺少成绩记录，建议结合学习状态进一步观察",
                signal_weight=0.0,
                source="data_gap",
            )
        )
        base_dimension_scores["study"] += 0.0

    if student.class_id is None:
        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type="class_unassigned",
                dimension="social",
                signal_text="学生当前未分配班级，需关注融入状态",
                signal_weight=0.16,
                source="student_status",
            )
        )
        base_dimension_scores["social"] += 0.16

    _append_attendance_signals(db, student, signals_to_create, base_dimension_scores)
    _append_behavior_event_signals(db, student, signals_to_create, base_dimension_scores)
    _append_care_observation_signals(db, student, signals_to_create, base_dimension_scores)
    _append_family_contact_signals(db, student, signals_to_create, base_dimension_scores)
    _append_assistant_summary_signals(db, student, signals_to_create, base_dimension_scores)
    _append_manual_graph_relation_signals(db, student, signals_to_create, base_dimension_scores)
    _append_graph_signals(db, student, signals_to_create, base_dimension_scores)

    major_incident_context = _detect_major_incident(db, student)
    _append_major_incident_signals(
        student=student,
        signals_to_create=signals_to_create,
        base_dimension_scores=base_dimension_scores,
        spillover_scores=spillover_scores,
        incident_context=major_incident_context,
    )

    base_dimension_scores = {key: _clamp_score(value) for key, value in base_dimension_scores.items()}
    spillover_scores = {key: _clamp_score(value) for key, value in spillover_scores.items()}
    dimension_scores = {
        key: _clamp_score(base_dimension_scores[key] + spillover_scores[key])
        for key in DIMENSIONS
    }

    pre_bn_signal_dicts = [_signal_to_dict(item) for item in signals_to_create]
    major_incident_bn = _build_major_incident_bn_analysis(
        dimension_scores=dimension_scores,
        signals=pre_bn_signal_dicts,
        incident_context=major_incident_context,
    )
    _apply_major_incident_bn_spillover(
        student=student,
        signals_to_create=signals_to_create,
        spillover_scores=spillover_scores,
        dimension_scores=dimension_scores,
        bn_analysis=major_incident_bn,
    )
    major_incident_context["bn_analysis"] = major_incident_bn

    spillover_scores = {key: _clamp_score(value) for key, value in spillover_scores.items()}
    dimension_scores = {
        key: _clamp_score(base_dimension_scores[key] + spillover_scores[key])
        for key in DIMENSIONS
    }

    linear_scores = {key: value for key, value in dimension_scores.items()}
    signal_dicts = [_signal_to_dict(item) for item in signals_to_create]
    teacher_reviews = _list_recent_teacher_reviews(db, student.id)
    bayes_config = get_effective_bayes_config(db)
    bayes_results = build_bayes_results(
        dimension_scores=linear_scores,
        signals=signal_dicts,
        teacher_reviews=teacher_reviews,
        bayes_config=bayes_config,
    )
    incident_context = _finalize_major_incident_context(
        incident_context=major_incident_context,
        base_dimension_scores=base_dimension_scores,
        spillover_scores=spillover_scores,
        total_dimension_scores=dimension_scores,
    )
    emotion_bayes = bayes_results.get("emotion")
    if emotion_bayes and emotion_bayes.get("enabled"):
        dimension_scores["emotion"] = _clamp_score(emotion_bayes.get("final_score", dimension_scores["emotion"]))
    family_bayes = bayes_results.get("family")
    if family_bayes and family_bayes.get("enabled"):
        dimension_scores["family"] = _clamp_score(family_bayes.get("final_score", dimension_scores["family"]))
    safety_bayes = bayes_results.get("safety")
    if safety_bayes and safety_bayes.get("enabled"):
        dimension_scores["safety"] = _clamp_score(safety_bayes.get("final_score", dimension_scores["safety"]))
    social_bayes = bayes_results.get("social")
    if social_bayes and social_bayes.get("enabled"):
        dimension_scores["social"] = _clamp_score(social_bayes.get("final_score", dimension_scores["social"]))

    overall_risk = _clamp_score(
        dimension_scores["emotion"] * OVERALL_WEIGHTS["emotion"]
        + dimension_scores["social"] * OVERALL_WEIGHTS["social"]
        + dimension_scores["safety"] * OVERALL_WEIGHTS["safety"]
        + dimension_scores["family"] * OVERALL_WEIGHTS["family"]
        + dimension_scores["study"] * OVERALL_WEIGHTS["study"]
        + dimension_scores["behavior"] * OVERALL_WEIGHTS["behavior"]
    )
    risk_level = _risk_level(overall_risk)
    major_incident_bn = _build_major_incident_bn_analysis(
        dimension_scores=dimension_scores,
        signals=signal_dicts,
        incident_context=incident_context,
    )
    incident_context["bn_analysis"] = major_incident_bn
    trend = _determine_profile_trend(
        previous_profile=previous_profile,
        overall_risk=overall_risk,
        dimension_scores=dimension_scores,
        incident_context=incident_context,
    )

    profile = previous_profile
    if not profile:
        profile = StudentCareProfile(student_id=student.id, class_id=student.class_id)
        db.add(profile)

    profile.class_id = student.class_id
    profile.emotion_score = dimension_scores["emotion"]
    profile.social_score = dimension_scores["social"]
    profile.safety_score = dimension_scores["safety"]
    profile.family_score = dimension_scores["family"]
    profile.study_score = dimension_scores["study"]
    profile.behavior_score = dimension_scores["behavior"]
    profile.overall_risk = overall_risk
    profile.risk_level = risk_level
    profile.trend = trend

    for signal in signals_to_create:
        db.add(signal)

    db.commit()
    db.refresh(profile)
    signals = (
        db.query(StudentCareSignal)
        .filter(StudentCareSignal.student_id == student.id)
        .order_by(StudentCareSignal.signal_weight.desc(), StudentCareSignal.id.desc())
        .all()
    )
    return profile, signals, bayes_results, incident_context


def _ensure_head_teacher_access(db: Session, current_user: User, student: Student) -> dict | None:
    if current_user.role != "teacher":
        return error_response(code=403, msg="当前仅班主任可查看学生关怀画像")
    if not student.class_id:
        return error_response(code=403, msg="该学生当前未分班，无法查看关怀画像")

    teacher = db.query(Teacher).filter(Teacher.name == current_user.name).first()
    if not teacher:
        return error_response(code=403, msg="未找到当前教师档案")

    class_row = db.query(Class).filter(Class.id == student.class_id).first()
    if not class_row or class_row.head_teacher_id != teacher.id:
        return error_response(code=403, msg="当前仅该学生所属班级班主任可查看关怀画像")
    return None


def _serialize_student(student: Student, db: Session) -> dict:
    class_name = None
    if student.class_id:
        class_row = db.query(Class).filter(Class.id == student.class_id).first()
        class_name = class_row.name if class_row else None
    return {
        "id": student.id,
        "student_no": student.student_no,
        "name": student.name,
        "gender": student.gender,
        "age": student.age,
        "grade": student.grade,
        "class_id": student.class_id,
        "class_name": class_name,
        "tags": student.tags,
    }


def _serialize_profile(
    profile: StudentCareProfile,
    bayes_results: dict | None = None,
    incident_context: dict | None = None,
) -> dict:
    bayes_results = bayes_results or {}
    incident_context = incident_context or {}
    safety_bayes = bayes_results.get("safety", {})
    social_bayes = bayes_results.get("social", {})
    payload = {
        "student_id": profile.student_id,
        "class_id": profile.class_id,
        "emotion_score": round(profile.emotion_score or 0, 4),
        "emotion_linear_score": round(float(bayes_results.get("emotion", {}).get("linear_score", profile.emotion_score or 0)), 4),
        "emotion_bayes_posterior": round(float(bayes_results.get("emotion", {}).get("posterior", 0)), 4),
        "emotion_final_score": round(float(bayes_results.get("emotion", {}).get("final_score", profile.emotion_score or 0)), 4),
        "social_score": round(profile.social_score or 0, 4),
        "social_linear_score": round(float(social_bayes.get("linear_score", profile.social_score or 0)), 4),
        "social_bayes_posterior": round(float(social_bayes.get("posterior", 0)), 4),
        "social_final_score": round(float(social_bayes.get("final_score", profile.social_score or 0)), 4),
        "safety_score": round(profile.safety_score or 0, 4),
        "safety_linear_score": round(float(safety_bayes.get("linear_score", profile.safety_score or 0)), 4),
        "safety_bayes_posterior": round(float(safety_bayes.get("posterior", 0)), 4),
        "safety_final_score": round(float(safety_bayes.get("final_score", profile.safety_score or 0)), 4),
        "family_score": round(profile.family_score or 0, 4),
        "family_linear_score": round(float(bayes_results.get("family", {}).get("linear_score", profile.family_score or 0)), 4),
        "family_bayes_posterior": round(float(bayes_results.get("family", {}).get("posterior", 0)), 4),
        "family_final_score": round(float(bayes_results.get("family", {}).get("final_score", profile.family_score or 0)), 4),
        "study_score": round(profile.study_score or 0, 4),
        "behavior_score": round(profile.behavior_score or 0, 4),
        "overall_risk": round(profile.overall_risk or 0, 4),
        "risk_level": profile.risk_level,
        "trend": profile.trend,
        "bayes_results": bayes_results,
        "updated_at": str(profile.updated_at) if profile.updated_at else None,
    }
    dimension_breakdown = incident_context.get("dimension_breakdown") or {}
    for dimension in DIMENSIONS:
        detail = dimension_breakdown.get(dimension, {})
        payload[f"{dimension}_base_score"] = round(float(detail.get("base_score", 0)), 4)
        payload[f"{dimension}_spillover_score"] = round(float(detail.get("spillover_score", 0)), 4)
    payload["dimension_breakdown"] = dimension_breakdown
    payload["major_incident_detected"] = bool(incident_context.get("major_incident_detected"))
    payload["major_incident_types"] = incident_context.get("major_incident_types") or []
    payload["major_incident_confidence"] = round(float(incident_context.get("major_incident_confidence", 0)), 4)
    payload["major_incident_evidence"] = incident_context.get("major_incident_evidence") or []
    payload["major_incident_impacted_dimensions"] = incident_context.get("impacted_dimensions") or []
    payload["major_incident_propagation_details"] = incident_context.get("propagation_details") or []
    payload["major_incident_bn"] = incident_context.get("bn_analysis") or {}
    return payload


def _serialize_signal(signal: StudentCareSignal) -> dict:
    return {
        "id": signal.id,
        "signal_type": signal.signal_type,
        "dimension": signal.dimension,
        "dimension_label": DIMENSION_LABELS.get(signal.dimension, signal.dimension),
        "signal_text": signal.signal_text,
        "signal_weight": round(signal.signal_weight or 0, 4),
        "source": signal.source,
        "created_at": str(signal.created_at) if signal.created_at else None,
    }


def _signal_to_dict(signal: StudentCareSignal) -> dict:
    return {
        "signal_type": signal.signal_type,
        "dimension": signal.dimension,
        "signal_text": signal.signal_text,
        "signal_weight": round(signal.signal_weight or 0, 4),
        "source": signal.source,
    }


def _build_data_quality_summary(signals: list[StudentCareSignal]) -> dict:
    signal_rows = [_signal_to_dict(item) for item in signals]
    missing_sources = [
        item["signal_type"]
        for item in signal_rows
        if item["source"] == "data_gap"
    ]
    positive_sources = len([item for item in signal_rows if float(item.get("signal_weight") or 0) > 0])
    protective_sources = len([item for item in signal_rows if float(item.get("signal_weight") or 0) < 0])
    return {
        "missing_sources": missing_sources,
        "missing_count": len(missing_sources),
        "positive_signal_count": positive_sources,
        "protective_signal_count": protective_sources,
        "evidence_sufficient": len(missing_sources) <= 1 and positive_sources >= 2,
    }


def _list_recent_teacher_reviews(db: Session, student_id: int, limit: int = 3) -> list[dict]:
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
        reviews.append(
            {
                "record_id": item.id,
                "resolution_status": item.resolution_status,
                "teacher_notes": item.teacher_notes,
            }
        )
    return reviews


def _build_actions(profile: StudentCareProfile) -> list[str]:
    actions: list[str] = []
    dimension_pairs = [
        ("social", profile.social_score, "建议班主任近期安排一次非正式谈话，关注该生在班级中的同伴关系。"),
        ("safety", profile.safety_score, "建议尽快核实是否存在宿舍、课间或放学时段的安全风险。"),
        ("family", profile.family_score, "建议在合适时机了解学生家庭支持情况，必要时联系家长沟通。"),
        ("emotion", profile.emotion_score, "建议关注学生近期情绪变化，先以低压力方式建立信任沟通。"),
        ("study", profile.study_score, "建议结合最近成绩波动，帮助学生拆解当前学习压力来源。"),
        ("behavior", profile.behavior_score, "建议结合近期行为标签，观察是否存在明显节律或状态波动。"),
    ]
    for _, score, action in sorted(dimension_pairs, key=lambda item: item[1], reverse=True):
        if score >= 0.5:
            actions.append(action)
    if not actions:
        actions.append("当前整体风险较低，建议继续保持常规关注。")
    return actions[:3]


def _parse_tags(tags: str | None) -> list[str]:
    if not tags:
        return []
    return [item.strip() for item in tags.split(",") if item.strip()]


def _get_tag_definitions(db: Session, student: Student) -> dict[str, StudentTagDefinition]:
    query = db.query(StudentTagDefinition)
    records = query.all()
    filtered = []
    for item in records:
        if item.scope_type == "school":
            filtered.append(item)
        elif item.scope_type == "grade" and student.grade and item.scope_value == student.grade:
            filtered.append(item)
        elif item.scope_type == "class" and student.class_id and item.scope_value == str(student.class_id):
            filtered.append(item)

    priority = {"class": 3, "grade": 2, "school": 1}
    resolved: dict[str, StudentTagDefinition] = {}
    for item in filtered:
        key = item.tag_text
        current = resolved.get(key)
        if not current or priority[item.scope_type] > priority[current.scope_type]:
            resolved[key] = item
    return resolved


def _polarity_label(polarity: str) -> str:
    return {"positive": "正向", "neutral": "中性", "negative": "负向"}.get(polarity, "中性")


def _clamp_score(value: float) -> float:
    return round(min(max(value, 0.0), 1.0), 4)


def _days_since(value: date | datetime | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        target = value.date()
    else:
        target = value
    return max((date.today() - target).days, 0)


def _time_decay_multiplier(value: date | datetime | None) -> float:
    days = _days_since(value)
    if days is None:
        return 1.0
    for window, factor in TIME_DECAY_WINDOWS:
        if days <= window:
            return factor
    return 0.2


def _apply_time_decay(weight: float, value: date | datetime | None) -> float:
    return round(float(weight or 0) * _time_decay_multiplier(value), 4)


def _classify_text_polarity(text: str | None) -> str:
    content = str(text or "").strip()
    if not content:
        return "neutral"

    negative_hits = sum(1 for item in TEXT_NEGATIVE_HINTS if item in content)
    positive_hits = sum(1 for item in TEXT_POSITIVE_HINTS if item in content)
    if negative_hits > positive_hits and negative_hits > 0:
        return "negative"
    if positive_hits > negative_hits and positive_hits > 0:
        return "positive"
    return "neutral"


def _polarity_weight(base_weight: float, polarity: str, positive_factor: float = 0.6, neutral_factor: float = 0.0) -> float:
    if polarity == "negative":
        return round(float(base_weight or 0), 4)
    if polarity == "positive":
        return round(-abs(float(base_weight or 0)) * positive_factor, 4)
    return round(float(base_weight or 0) * neutral_factor, 4)


def _append_data_gap_signal(
    student: Student,
    signals_to_create: list[StudentCareSignal],
    dimension: str,
    signal_type: str,
    signal_text: str,
) -> None:
    signals_to_create.append(
        StudentCareSignal(
            student_id=student.id,
            class_id=student.class_id,
            signal_type=signal_type,
            dimension=dimension,
            signal_text=signal_text,
            signal_weight=0.0,
            source="data_gap",
        )
    )


def _detect_major_incident(db: Session, student: Student) -> dict:
    incident_types: list[str] = []
    evidence: list[str] = []
    confidence_scores: list[float] = []

    def register(incident_type: str, evidence_text: str, confidence: float) -> None:
        if incident_type not in incident_types:
            incident_types.append(incident_type)
        if evidence_text and evidence_text not in evidence:
            evidence.append(evidence_text)
        confidence_scores.append(confidence)

    behavior_records = (
        db.query(StudentBehaviorEvent)
        .filter(StudentBehaviorEvent.student_id == student.id)
        .order_by(StudentBehaviorEvent.occurred_at.desc(), StudentBehaviorEvent.id.desc())
        .all()
    )
    for item in behavior_records[:8]:
        desc = str(item.event_desc or "")
        if item.event_type == "bullying":
            register(
                "behavior_bullying",
                f"行为事件记录疑似欺凌：{desc or item.event_type}",
                0.92 if item.event_level == "high" else 0.82,
            )
        if item.event_type == "conflict" and item.event_level == "high":
            register(
                "behavior_conflict_high",
                f"行为事件记录高等级冲突：{desc or item.event_type}",
                0.84,
            )
        if item.event_type == "threat":
            register(
                "behavior_threat",
                f"行为事件记录疑似威胁或恐吓：{desc or item.event_type}",
                0.88 if item.event_level == "high" else 0.78,
            )
        if any(keyword in desc for keyword in MAJOR_INCIDENT_HINTS):
            register(
                "behavior_severe_text",
                f"行为事件描述出现恶性事件关键词：{desc}",
                0.78,
            )

    latest_summary = (
        db.query(StudentAssistantSummary)
        .filter(StudentAssistantSummary.student_id == student.id)
        .order_by(StudentAssistantSummary.id.desc())
        .first()
    )
    if latest_summary:
        summary_text = str(latest_summary.summary_text or "")
        if any(keyword in summary_text for keyword in MAJOR_INCIDENT_HINTS):
            register(
                "assistant_summary_severe_hint",
                f"AI 摘要提示恶性事件：{summary_text[:80]}",
                0.76,
            )
        signal_items = ((latest_summary.signals_json or {}).get("signals") or [])[:8]
        for item in signal_items:
            text = str(item.get("text") or "")
            if any(keyword in text for keyword in MAJOR_INCIDENT_HINTS):
                register(
                    "assistant_signal_severe_hint",
                    f"AI 结构化信号提示恶性事件：{text[:80]}",
                    0.8,
                )

    graph_records = (
        db.query(StudentCareGraphRelation)
        .filter(StudentCareGraphRelation.student_id == student.id)
        .order_by(
            case((StudentCareGraphRelation.occurred_at.is_(None), 1), else_=0).asc(),
            StudentCareGraphRelation.occurred_at.desc(),
            StudentCareGraphRelation.id.desc(),
        )
        .all()
    )
    for item in graph_records[:8]:
        if item.relation_type not in {"conflict", "bullying_link"}:
            continue
        if item.relation_level not in {"medium", "high"}:
            continue
        label = "冲突" if item.relation_type == "conflict" else "欺凌"
        register(
            f"graph_{item.relation_type}",
            f"图谱关系存在{label}线索：{item.summary}",
            0.74 if item.relation_level == "medium" else 0.84,
        )

    attendance_records = (
        db.query(StudentAttendance)
        .filter(StudentAttendance.student_id == student.id)
        .order_by(StudentAttendance.date.desc(), StudentAttendance.id.desc())
        .all()
    )
    attendance_anomaly_count = sum(
        1 for item in attendance_records[:10]
        if item.status in {"late", "absent", "early_leave"}
    )
    safety_behavior_hits = [
        item for item in behavior_records[:8]
        if item.event_type in SAFETY_EVENT_TYPES or any(keyword in str(item.event_desc or "") for keyword in MAJOR_INCIDENT_HINTS)
    ]
    if safety_behavior_hits and attendance_anomaly_count >= 2:
        register(
            "safety_attendance_cluster",
            f"安全事件叠加近期异常出勤 {attendance_anomaly_count} 次",
            0.72,
        )

    base_confidence = max(confidence_scores) if confidence_scores else 0.0
    boosted_confidence = min(0.98, base_confidence + max(len(incident_types) - 1, 0) * 0.04)
    return {
        "major_incident_detected": bool(incident_types),
        "major_incident_types": incident_types,
        "major_incident_confidence": round(boosted_confidence, 4),
        "major_incident_evidence": evidence[:6],
    }


def _append_major_incident_signals(
    student: Student,
    signals_to_create: list[StudentCareSignal],
    base_dimension_scores: dict[str, float],
    spillover_scores: dict[str, float],
    incident_context: dict,
) -> None:
    if not incident_context.get("major_incident_detected"):
        return

    confidence = float(incident_context.get("major_incident_confidence") or 0)
    safety_anchor = max(float(base_dimension_scores.get("safety") or 0), 0.35 + confidence * 0.15)
    propagation_details = []

    for rule in MAJOR_INCIDENT_PROPAGATION_RULES:
        from_dimension = rule["from_dimension"]
        to_dimension = rule["to_dimension"]
        source_score = float(base_dimension_scores.get(from_dimension) or 0) + float(spillover_scores.get(from_dimension) or 0)
        if from_dimension == "safety":
            source_score = max(source_score, safety_anchor)
        if source_score < rule["threshold"]:
            continue

        weight = round(source_score * rule["factor"] * (0.75 + confidence * 0.25), 4)
        weight = min(rule["max_weight"], weight)
        if weight <= 0:
            continue
        if weight < rule["min_weight"]:
            weight = rule["min_weight"]

        spillover_scores[to_dimension] += weight
        propagation_details.append(
            {
                "from_dimension": from_dimension,
                "to_dimension": to_dimension,
                "signal_type": rule["signal_type"],
                "signal_weight": round(weight, 4),
            }
        )
        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type=rule["signal_type"],
                dimension=to_dimension,
                signal_text=rule["signal_text"],
                signal_weight=round(weight, 4),
                source="major_incident",
            )
        )

    incident_context["propagation_details"] = propagation_details


def _finalize_major_incident_context(
    incident_context: dict,
    base_dimension_scores: dict[str, float],
    spillover_scores: dict[str, float],
    total_dimension_scores: dict[str, float],
) -> dict:
    if not incident_context.get("major_incident_detected"):
        return {
            "major_incident_detected": False,
            "major_incident_types": [],
            "major_incident_confidence": 0.0,
            "major_incident_evidence": [],
            "propagation_details": [],
            "bn_analysis": incident_context.get("bn_analysis") or {},
            "impacted_dimensions": [],
            "dimension_breakdown": {
                key: {
                    "base_score": round(float(base_dimension_scores.get(key) or 0), 4),
                    "spillover_score": 0.0,
                    "total_score": round(float(total_dimension_scores.get(key) or 0), 4),
                }
                for key in DIMENSIONS
            },
        }

    impacted_dimensions = [
        key for key in DIMENSIONS
        if float(spillover_scores.get(key) or 0) > 0
    ]
    return {
        "major_incident_detected": True,
        "major_incident_types": incident_context.get("major_incident_types") or [],
        "major_incident_confidence": round(float(incident_context.get("major_incident_confidence") or 0), 4),
        "major_incident_evidence": incident_context.get("major_incident_evidence") or [],
        "propagation_details": incident_context.get("propagation_details") or [],
        "bn_analysis": incident_context.get("bn_analysis") or {},
        "impacted_dimensions": impacted_dimensions,
        "dimension_breakdown": {
            key: {
                "base_score": round(float(base_dimension_scores.get(key) or 0), 4),
                "spillover_score": round(float(spillover_scores.get(key) or 0), 4),
                "total_score": round(float(total_dimension_scores.get(key) or 0), 4),
            }
            for key in DIMENSIONS
        },
    }


def _determine_profile_trend(
    previous_profile: StudentCareProfile | None,
    overall_risk: float,
    dimension_scores: dict[str, float],
    incident_context: dict,
) -> str:
    if incident_context.get("major_incident_detected"):
        spillover_total = sum(
            float(item.get("spillover_score") or 0)
            for item in (incident_context.get("dimension_breakdown") or {}).values()
        )
        if spillover_total >= 0.15:
            return "up"

    if not previous_profile:
        if overall_risk >= 0.3:
            return "up"
        return "steady"

    risk_delta = round(float(overall_risk or 0) - float(previous_profile.overall_risk or 0), 4)
    if risk_delta >= 0.08:
        return "up"
    if risk_delta <= -0.08:
        return "down"

    significant_dimensions = [
        "emotion",
        "social",
        "safety",
        "study",
        "behavior",
    ]
    for dimension in significant_dimensions:
        previous_score = float(getattr(previous_profile, f"{dimension}_score", 0) or 0)
        current_score = float(dimension_scores.get(dimension) or 0)
        if current_score - previous_score >= 0.18:
            return "up"
        if previous_score - current_score >= 0.18:
            return "down"
    return "steady"


def _build_major_incident_bn_analysis(
    dimension_scores: dict[str, float],
    signals: list[dict],
    incident_context: dict,
) -> dict:
    if not incident_context.get("major_incident_detected"):
        return {
            "enabled": False,
            "detected": False,
            "nodes": [],
            "paths": [],
            "suggested_spillover_scores": {},
        }

    node_results = {}
    for node in MAJOR_INCIDENT_BN_NODE_CONFIG:
        node_results[node] = _infer_major_incident_bn_node(
            node=node,
            dimension_scores=dimension_scores,
            signals=signals,
            incident_context=incident_context,
            node_results=node_results,
        )

    suggested_spillover_scores = {}
    for node, result in node_results.items():
        dimension = result.get("dimension")
        if dimension not in DIMENSIONS or dimension == "safety":
            continue
        impact = float(result.get("impact") or 0)
        probability = float(result.get("probability") or 0)
        suggestion = round(probability * impact * 0.24, 4)
        if suggestion <= 0:
            continue
        suggested_spillover_scores[dimension] = min(0.24, suggestion)

    path_items = [
        {
            "path_id": "safety-emotion-study",
            "nodes": ["安全威胁持续", "情绪受损", "学习下滑"],
            "path_probability": round(
                float(node_results["safety_threat"]["probability"])
                * 0.64
                * float(node_results["emotion_impact"]["probability"])
                * 0.46
                * float(node_results["study_decline"]["probability"]),
                4,
            ),
            "summary": "安全事件先冲击情绪，再通过注意力下降和学习承压影响学习表现。",
        },
        {
            "path_id": "safety-social-study",
            "nodes": ["安全威胁持续", "社交退缩", "学习下滑"],
            "path_probability": round(
                float(node_results["safety_threat"]["probability"])
                * 0.42
                * float(node_results["social_withdrawal"]["probability"])
                * 0.32
                * float(node_results["study_decline"]["probability"]),
                4,
            ),
            "summary": "安全事件引发的回避同伴与班级脱离，可能进一步拖累学习投入。",
        },
        {
            "path_id": "safety-behavior",
            "nodes": ["安全威胁持续", "行为波动"],
            "path_probability": round(
                float(node_results["safety_threat"]["probability"])
                * 0.5
                * float(node_results["behavior_instability"]["probability"]),
                4,
            ),
            "summary": "安全威胁若未解除，往往会先表现在迟到、回避参与或行为失稳上。",
        },
    ]
    path_items.sort(key=lambda item: item["path_probability"], reverse=True)

    return {
        "enabled": True,
        "detected": True,
        "confidence": round(float(incident_context.get("major_incident_confidence") or 0), 4),
        "nodes": [
            {
                "node": key,
                "label": value["label"],
                "dimension": value["dimension"],
                "probability": value["probability"],
                "base_prior": value["base_prior"],
                "dynamic_prior": value["dynamic_prior"],
                "impact": value["impact"],
                "evidence": value["evidence"],
            }
            for key, value in node_results.items()
        ],
        "paths": path_items,
        "suggested_spillover_scores": suggested_spillover_scores,
    }


def _apply_major_incident_bn_spillover(
    student: Student,
    signals_to_create: list[StudentCareSignal],
    spillover_scores: dict[str, float],
    dimension_scores: dict[str, float],
    bn_analysis: dict,
) -> None:
    if not bn_analysis.get("enabled"):
        return

    suggested_scores = bn_analysis.get("suggested_spillover_scores") or {}
    study_suggestion = round(float(suggested_scores.get("study") or 0), 4)
    current_study_spillover = round(float(spillover_scores.get("study") or 0), 4)
    additional_weight = round(study_suggestion - current_study_spillover, 4)
    if additional_weight <= 0.02:
        return

    study_node = next(
        (item for item in (bn_analysis.get("nodes") or []) if item.get("dimension") == "study"),
        None,
    )
    if not study_node or float(study_node.get("probability") or 0) < 0.3:
        return

    spillover_scores["study"] += additional_weight
    dimension_scores["study"] = _clamp_score(float(dimension_scores.get("study") or 0) + additional_weight)
    signals_to_create.append(
        StudentCareSignal(
            student_id=student.id,
            class_id=student.class_id,
            signal_type="major_incident_bn_study_impact",
            dimension="study",
            signal_text="恶性事件传播贝叶斯子图判断：学习维度已出现次生受影响概率，建议作为前瞻风险纳入观察。",
            signal_weight=additional_weight,
            source="major_incident_bn",
        )
    )


def _infer_major_incident_bn_node(
    node: str,
    dimension_scores: dict[str, float],
    signals: list[dict],
    incident_context: dict,
    node_results: dict[str, dict],
) -> dict:
    config = MAJOR_INCIDENT_BN_NODE_CONFIG[node]
    dimension = config["dimension"]
    dimension_score = float(dimension_scores.get(dimension) or 0)
    parent_signal = 0.0
    if config["parents"]:
        parent_values = []
        for parent_node, edge_weight in config["parents"]:
            parent_probability = float((node_results.get(parent_node) or {}).get("probability") or 0)
            parent_values.append(parent_probability * edge_weight)
        if parent_values:
            parent_signal = 1 - prod(max(0.01, 1 - value) for value in parent_values)

    base_prior = float(config["base_prior"])
    dynamic_prior = base_prior + (1 - base_prior) * max(
        dimension_score * float(config["profile_weight"]),
        parent_signal * 0.5,
    )
    dynamic_prior = _clamp_score(dynamic_prior)

    matches = []
    for rule in MAJOR_INCIDENT_BN_EVIDENCE_RULES.get(node, []):
        matched_signal = _match_major_incident_bn_signal(rule, signals)
        if not matched_signal:
            continue
        matches.append(
            {
                "label": rule["label"],
                "lr": float(rule["lr"]),
                "signal_text": matched_signal.get("signal_text") or "",
                "source": matched_signal.get("source") or "",
            }
        )

    likelihood_ratios = [item["lr"] for item in matches]
    adjusted_lrs = apply_diminishing_returns(likelihood_ratios, method="sqrt") if likelihood_ratios else []
    odds = dynamic_prior / max(1 - dynamic_prior, 0.001)
    for lr in adjusted_lrs:
        odds *= max(float(lr), 0.05)
    probability = _clamp_score(odds / (1 + odds))
    return {
        "label": config["label"],
        "dimension": dimension,
        "base_prior": round(base_prior, 4),
        "dynamic_prior": round(dynamic_prior, 4),
        "probability": round(probability, 4),
        "impact": round(float(config["impact"]), 4),
        "evidence": [
            {
                "label": item["label"],
                "lr": round(item["lr"], 4),
                "signal_text": item["signal_text"],
                "source": item["source"],
            }
            for item in matches[:4]
        ],
    }


def _match_major_incident_bn_signal(rule: dict, signals: list[dict]) -> dict | None:
    prefixes = tuple(rule.get("signal_type_prefixes") or ())
    keywords = tuple(rule.get("keywords") or ())
    for item in signals:
        if rule.get("source") and item.get("source") != rule["source"]:
            continue
        if rule.get("dimension") and item.get("dimension") != rule["dimension"]:
            continue
        signal_type = str(item.get("signal_type") or "")
        signal_text = str(item.get("signal_text") or "")
        if prefixes and not any(signal_type.startswith(prefix) for prefix in prefixes):
            continue
        if keywords and not any(keyword in signal_text for keyword in keywords):
            continue
        return item
    return None


def _risk_level(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.5:
        return "medium"
    if score >= 0.3:
        return "attention"
    return "low"


def _append_attendance_signals(
    db: Session,
    student: Student,
    signals_to_create: list[StudentCareSignal],
    dimension_scores: dict[str, float],
) -> None:
    records = (
        db.query(StudentAttendance)
        .filter(StudentAttendance.student_id == student.id)
        .order_by(StudentAttendance.date.desc(), StudentAttendance.id.desc())
        .all()
    )
    if not records:
        _append_data_gap_signal(
            student,
            signals_to_create,
            "behavior",
            "attendance_missing",
            "当前缺少出勤记录，暂不额外提升行为风险，建议补充近期出勤数据。",
        )
        return
    late_count = sum(1 for item in records if item.status == "late")
    absent_count = sum(1 for item in records if item.status == "absent")
    early_count = sum(1 for item in records if item.status == "early_leave")
    if late_count:
        relevant_records = [item for item in records if item.status == "late"]
        weight = min(
            0.4,
            sum(_apply_time_decay(ATTENDANCE_BEHAVIOR_WEIGHTS["late"], item.date) for item in relevant_records),
        )
        remark_summary = _attendance_remark_summary(records, "late")
        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type="attendance_late",
                dimension="behavior",
                signal_text=f"近阶段出现 {late_count} 次迟到记录{remark_summary}",
                signal_weight=weight,
                source="attendance",
            )
        )
        dimension_scores["behavior"] += weight
    if absent_count:
        relevant_records = [item for item in records if item.status == "absent"]
        weight = min(
            0.6,
            sum(_apply_time_decay(ATTENDANCE_BEHAVIOR_WEIGHTS["absent"], item.date) for item in relevant_records),
        )
        remark_summary = _attendance_remark_summary(records, "absent")
        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type="attendance_absent",
                dimension="behavior",
                signal_text=f"近阶段出现 {absent_count} 次缺勤记录{remark_summary}",
                signal_weight=weight,
                source="attendance",
            )
        )
        dimension_scores["behavior"] += weight
    if early_count:
        relevant_records = [item for item in records if item.status == "early_leave"]
        weight = min(
            0.3,
            sum(_apply_time_decay(ATTENDANCE_BEHAVIOR_WEIGHTS["early_leave"], item.date) for item in relevant_records),
        )
        remark_summary = _attendance_remark_summary(records, "early_leave")
        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type="attendance_early_leave",
                dimension="behavior",
                signal_text=f"近阶段出现 {early_count} 次早退记录{remark_summary}",
                signal_weight=weight,
                source="attendance",
            )
        )
        dimension_scores["behavior"] += weight


def _attendance_remark_summary(records: list[StudentAttendance], status: str) -> str:
    remarks = []
    for item in records:
        if item.status != status or not item.remark:
            continue
        remark = item.remark.strip()
        if not remark:
            continue
        remarks.append(f"{item.date}：{remark}")
        if len(remarks) >= 3:
            break
    if not remarks:
        return ""
    return "；备注：" + "；".join(remarks)


def _append_behavior_event_signals(
    db: Session,
    student: Student,
    signals_to_create: list[StudentCareSignal],
    dimension_scores: dict[str, float],
) -> None:
    records = (
        db.query(StudentBehaviorEvent)
        .filter(StudentBehaviorEvent.student_id == student.id)
        .order_by(StudentBehaviorEvent.occurred_at.desc(), StudentBehaviorEvent.id.desc())
        .all()
    )
    if not records:
        _append_data_gap_signal(
            student,
            signals_to_create,
            "behavior",
            "behavior_event_missing",
            "当前缺少行为事件记录，行为风险判断主要依赖其他来源。",
        )
        return

    for item in records[:5]:
        weight = _apply_time_decay(BEHAVIOR_EVENT_WEIGHTS.get(item.event_level, 0.2), item.occurred_at)
        dimension = "behavior"
        if item.event_type in SAFETY_EVENT_TYPES:
            dimension = "safety"
        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type=f"behavior_{item.event_type}",
                dimension=dimension,
                signal_text=f"行为事件：{item.event_desc}",
                signal_weight=weight,
                source="behavior_event",
            )
        )
        dimension_scores[dimension] += weight


def _append_care_observation_signals(
    db: Session,
    student: Student,
    signals_to_create: list[StudentCareSignal],
    dimension_scores: dict[str, float],
) -> None:
    records = (
        db.query(StudentCareObservation)
        .filter(StudentCareObservation.student_id == student.id)
        .order_by(StudentCareObservation.observed_at.desc(), StudentCareObservation.id.desc())
        .all()
    )
    if not records:
        _append_data_gap_signal(
            student,
            signals_to_create,
            "emotion",
            "care_observation_missing",
            "当前缺少关怀观察记录，情绪与社交判断的证据充分度有限。",
        )
        return

    for item in records[:6]:
        if item.dimension not in DIMENSIONS:
            continue
        base_weight = _apply_time_decay(CARE_OBSERVATION_WEIGHTS.get(item.observation_level, 0.25), item.observed_at)
        polarity = _classify_text_polarity(item.summary)
        weight = _polarity_weight(base_weight, polarity, positive_factor=0.65, neutral_factor=0.1)
        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type=(
                    f"care_observation_positive_{item.observation_type}"
                    if polarity == "positive"
                    else (
                        f"care_observation_neutral_{item.observation_type}"
                        if polarity == "neutral"
                        else f"care_observation_{item.observation_type}"
                    )
                ),
                dimension=item.dimension,
                signal_text=(
                    f"关怀观察（{_observation_type_label(item.observation_type)}，"
                    f"{_observation_level_label(item.observation_level)}）：{item.summary}"
                ),
                signal_weight=weight,
                source="care_observation",
            )
        )
        dimension_scores[item.dimension] += weight


def _observation_type_label(value: str) -> str:
    return {
        "care_talk": "关怀谈话",
        "emotion_observation": "情绪观察",
        "social_observation": "社交观察",
        "safety_observation": "安全线索",
        "study_observation": "学习状态",
        "behavior_observation": "行为观察",
        "follow_up": "后续跟进",
    }.get(value, value)


def _observation_level_label(value: str) -> str:
    return {
        "low": "轻度关注",
        "medium": "中度关注",
        "high": "高度关注",
    }.get(value, value)


def _append_family_contact_signals(
    db: Session,
    student: Student,
    signals_to_create: list[StudentCareSignal],
    dimension_scores: dict[str, float],
) -> None:
    records = (
        db.query(StudentFamilyContact)
        .filter(StudentFamilyContact.student_id == student.id)
        .order_by(StudentFamilyContact.id.desc())
        .all()
    )
    if not records:
        _append_data_gap_signal(
            student,
            signals_to_create,
            "family",
            "family_contact_missing",
            "当前缺少家校沟通记录，家庭支持判断的证据充分度有限。",
        )
        return

    latest = records[0]
    if latest.summary:
        base_weight = _apply_time_decay(0.25, latest.created_at)
        polarity = _classify_text_polarity(latest.summary)
        weight = _polarity_weight(base_weight, polarity, positive_factor=0.75, neutral_factor=0.05)
        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type=(
                    "family_contact_positive"
                    if polarity == "positive"
                    else ("family_contact_neutral" if polarity == "neutral" else "family_contact_summary")
                ),
                dimension="family",
                signal_text=f"家校沟通摘要：{latest.summary}",
                signal_weight=weight,
                source="family_contact",
            )
        )
        dimension_scores["family"] += weight


def _append_assistant_summary_signals(
    db: Session,
    student: Student,
    signals_to_create: list[StudentCareSignal],
    dimension_scores: dict[str, float],
) -> None:
    records = (
        db.query(StudentAssistantSummary)
        .filter(StudentAssistantSummary.student_id == student.id)
        .order_by(StudentAssistantSummary.id.desc())
        .all()
    )
    if not records:
        _append_data_gap_signal(
            student,
            signals_to_create,
            "emotion",
            "assistant_summary_missing",
            "当前缺少 AI 助手摘要，文本线索型证据暂不充分。",
        )
        return
    latest = records[0]
    if not latest.signals_json:
        _append_data_gap_signal(
            student,
            signals_to_create,
            "emotion",
            "assistant_signal_missing",
            "当前 AI 助手摘要未提取到结构化信号，文本线索型证据暂不充分。",
        )
        return
    signals = latest.signals_json.get("signals", [])
    for item in signals[:6]:
        dimension = item.get("dimension")
        base_weight = _apply_time_decay(float(item.get("weight", 0.2)), latest.created_at)
        if dimension not in DIMENSIONS:
            continue
        text = item.get("text", "鍔╂墜瀵硅瘽绾跨储")
        polarity = _classify_text_polarity(text)
        weight = _polarity_weight(base_weight, polarity, positive_factor=0.55, neutral_factor=0.15)
        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type=(
                    f"{item.get('type', 'assistant_signal')}_positive"
                    if polarity == "positive"
                    else (
                        f"{item.get('type', 'assistant_signal')}_neutral"
                        if polarity == "neutral"
                        else item.get("type", "assistant_signal")
                    )
                ),
                dimension=dimension,
                signal_text=item.get("text", "助手对话线索"),
                signal_weight=round(weight, 4),
                source="assistant_summary",
            )
        )
        dimension_scores[dimension] += weight


def _append_graph_signals(
    db: Session,
    student: Student,
    signals_to_create: list[StudentCareSignal],
    dimension_scores: dict[str, float],
) -> None:
    graph_signals = student_care_graph_service.build_graph_signals(db, student)
    for item in graph_signals:
        dimension = item.get("dimension")
        if dimension not in DIMENSIONS:
            continue
        weight = _clamp_score(float(item.get("signal_weight", 0)))
        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type=item.get("signal_type", "graph_signal"),
                dimension=dimension,
                signal_text=item.get("signal_text", "关系图谱发现新的辅助线索"),
                signal_weight=weight,
                source=item.get("source", "graph"),
            )
        )
        dimension_scores[dimension] += weight


def _append_manual_graph_relation_signals(
    db: Session,
    student: Student,
    signals_to_create: list[StudentCareSignal],
    dimension_scores: dict[str, float],
) -> None:
    records = (
        db.query(StudentCareGraphRelation)
        .filter(StudentCareGraphRelation.student_id == student.id)
        .order_by(
            case((StudentCareGraphRelation.occurred_at.is_(None), 1), else_=0).asc(),
            StudentCareGraphRelation.occurred_at.desc(),
            StudentCareGraphRelation.id.desc(),
        )
        .all()
    )
    if not records:
        return

    level_weights = {
        "low": 0.12,
        "medium": 0.2,
        "high": 0.3,
    }
    relation_labels = {
        "peer_support": "同伴支持",
        "conflict": "冲突关系",
        "bullying_link": "欺凌关联",
        "shared_activity": "共同活动",
        "concern": "重点关注",
    }

    for item in records[:8]:
        if item.dimension not in DIMENSIONS:
            continue
        weight = round(
            level_weights.get(item.relation_level, 0.16)
            * MANUAL_GRAPH_RELATION_POLARITY.get(item.relation_type, 1),
            4,
        )
        if item.target_type == "student" and item.target_student_id:
            target_student = db.query(Student).filter(Student.id == item.target_student_id).first()
            target_name = target_student.name if target_student else f"学生{item.target_student_id}"
            signal_text = (
                f"手工图谱关系：与 {target_name} 存在"
                f"{relation_labels.get(item.relation_type, item.relation_type)}线索，备注：{item.summary}"
            )
            signal_type = f"graph_manual_student_{item.relation_type}"
        else:
            title = item.event_title or relation_labels.get(item.relation_type, "手工事件")
            signal_text = f"手工图谱事件：{title}，备注：{item.summary}"
            signal_type = f"graph_manual_event_{item.relation_type}"

        signals_to_create.append(
            StudentCareSignal(
                student_id=student.id,
                class_id=student.class_id,
                signal_type=signal_type,
                dimension=item.dimension,
                signal_text=signal_text,
                signal_weight=weight,
                source="graph",
            )
        )
        dimension_scores[item.dimension] += weight
