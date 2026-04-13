# -*- coding: utf-8 -*-
"""Profile-aware placement and grouping optimizer."""

from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models.score import Score
from database.models.student_care_profile import StudentCareProfile


RISK_WEIGHTS = {
    "emotion": 0.20,
    "social": 0.20,
    "safety": 0.20,
    "family": 0.15,
    "study": 0.15,
    "behavior": 0.10,
}


def load_avg_scores(db: Session, student_ids: list[int]) -> dict[int, float]:
    if not student_ids:
        return {}

    rows = (
        db.query(Score.student_id, func.avg(Score.score))
        .filter(Score.student_id.in_(student_ids))
        .group_by(Score.student_id)
        .all()
    )
    return {int(student_id): round(float(avg or 0), 2) for student_id, avg in rows}


def load_profiles(db: Session, student_ids: list[int]) -> dict[int, StudentCareProfile]:
    if not student_ids:
        return {}

    profiles = (
        db.query(StudentCareProfile)
        .filter(StudentCareProfile.student_id.in_(student_ids))
        .all()
    )
    return {int(item.student_id): item for item in profiles}


def calculate_risk_score(profile: StudentCareProfile | None) -> float | None:
    if profile is None:
        return None

    return round(
        RISK_WEIGHTS["emotion"] * _bounded_score(profile.emotion_score)
        + RISK_WEIGHTS["social"] * _bounded_score(profile.social_score)
        + RISK_WEIGHTS["safety"] * _bounded_score(profile.safety_score)
        + RISK_WEIGHTS["family"] * _bounded_score(profile.family_score)
        + RISK_WEIGHTS["study"] * _bounded_score(profile.study_score)
        + RISK_WEIGHTS["behavior"] * _bounded_score(profile.behavior_score),
        4,
    )


def calculate_support_score(avg_score: float, risk_score: float | None, score_max: float = 100.0) -> float:
    academic_support = _clamp(avg_score / score_max)
    low_risk_support = 0.5 if risk_score is None else _clamp(1 - risk_score)
    return round(0.6 * low_risk_support + 0.4 * academic_support, 4)


def build_student_records(db: Session, students: list) -> tuple[list[dict], list[dict]]:
    student_ids = [int(item.id) for item in students]
    avg_scores = load_avg_scores(db, student_ids)
    profiles = load_profiles(db, student_ids)
    missing_profiles = []
    records = []

    for student in students:
        avg_score = round(float(avg_scores.get(int(student.id), 0.0)), 2)
        profile = profiles.get(int(student.id))
        risk_score = calculate_risk_score(profile)
        support_score = calculate_support_score(avg_score, risk_score)
        risk_level = (profile.risk_level if profile and profile.risk_level else "").lower() or None

        record = {
            "id": int(student.id),
            "student_no": student.student_no,
            "name": student.name,
            "gender": student.gender,
            "grade": student.grade,
            "class_id": student.class_id,
            "tags": student.tags or "",
            "avg_score": avg_score,
            "risk_score": risk_score,
            "support_score": support_score,
            "risk_level": risk_level,
            "has_profile": profile is not None,
            "high_risk": risk_level in {"high", "critical"},
            "critical_risk": risk_level == "critical",
            "support_anchor": support_score >= 0.7,
            "profile_scores": {
                "emotion_score": _bounded_score(profile.emotion_score) if profile else None,
                "social_score": _bounded_score(profile.social_score) if profile else None,
                "safety_score": _bounded_score(profile.safety_score) if profile else None,
                "family_score": _bounded_score(profile.family_score) if profile else None,
                "study_score": _bounded_score(profile.study_score) if profile else None,
                "behavior_score": _bounded_score(profile.behavior_score) if profile else None,
            },
        }
        records.append(record)

        if profile is None:
            missing_profiles.append(
                {
                    "student_id": int(student.id),
                    "student_name": student.name,
                    "student_no": student.student_no,
                }
            )

    return records, missing_profiles


def generate_placement(records: list[dict], classes: list) -> dict:
    total_students = len(records)
    class_count = len(classes)
    base_size = total_students // class_count if class_count else 0
    remainder = total_students % class_count if class_count else 0
    specs = []
    for index, class_obj in enumerate(classes):
        target_size = base_size + (1 if index < remainder else 0)
        specs.append(
            {
                "id": int(class_obj.id),
                "label": class_obj.name,
                "capacity": max(int(class_obj.max_count or 0), 1),
                "target_size": max(target_size, 1),
            }
        )
    plan = _allocate(records, specs, mode="placement")
    return _build_result(plan, mode="placement")


def generate_grouping(records: list[dict], group_count: int) -> dict:
    total_students = len(records)
    base_size = total_students // group_count
    remainder = total_students % group_count
    specs = []
    for index in range(group_count):
        target_size = base_size + (1 if index < remainder else 0)
        specs.append(
            {
                "id": index + 1,
                "label": f"第{index + 1}组",
                "capacity": target_size,
                "target_size": target_size,
            }
        )
    plan = _allocate(records, specs, mode="grouping")
    return _build_result(plan, mode="grouping")


def _allocate(records: list[dict], specs: list[dict], mode: str) -> list[dict]:
    containers = [_create_container(spec) for spec in specs]
    overall = _build_overall_context(records, len(containers))
    ordered_records = _build_ordered_records(records, mode=mode)

    for record in ordered_records:
        chosen = min(
            (idx for idx, item in enumerate(containers) if item["count"] < item["capacity"]),
            key=lambda idx: _project_penalty(containers[idx], record, overall),
        )
        _append_record(containers[chosen], record)

    _refine_by_swaps(containers, overall)
    return containers


def _build_result(containers: list[dict], mode: str) -> dict:
    summaries = []
    assignment_items = []
    metric_rows = []

    for item in containers:
        summary = {
            "id": item["id"],
            "label": item["label"],
            "student_count": item["count"],
            "male_count": item["male_count"],
            "female_count": item["female_count"],
            "avg_score": round(_average(item["score_values"]), 2),
            "avg_risk_score": round(_average(item["risk_values"]), 4),
            "high_risk_count": item["high_risk_count"],
            "critical_risk_count": item["critical_risk_count"],
            "support_anchor_count": item["support_anchor_count"],
            "students": item["students"],
        }
        summaries.append(summary)
        metric_rows.append(summary)

        if mode == "placement":
            assignment_items.append(
                {
                    "class_id": item["id"],
                    "student_ids": [student["id"] for student in item["students"]],
                }
            )
        else:
            assignment_items.append(
                {
                    "group_no": item["id"],
                    "student_ids": [student["id"] for student in item["students"]],
                }
            )

    return {
        "assignments": assignment_items,
        "summaries": summaries,
        "balance_report": _build_balance_report(metric_rows),
    }


def _create_container(spec: dict) -> dict:
    return {
        "id": spec["id"],
        "label": spec["label"],
        "capacity": int(spec["capacity"]),
        "target_size": int(spec["target_size"]),
        "students": [],
        "count": 0,
        "male_count": 0,
        "female_count": 0,
        "high_risk_count": 0,
        "critical_risk_count": 0,
        "support_anchor_count": 0,
        "score_values": [],
        "risk_values": [],
    }


def _append_record(container: dict, record: dict) -> None:
    container["students"].append(record)
    container["count"] += 1
    if record["gender"] == "male":
        container["male_count"] += 1
    else:
        container["female_count"] += 1
    if record["high_risk"]:
        container["high_risk_count"] += 1
    if record["critical_risk"]:
        container["critical_risk_count"] += 1
    if record["support_anchor"]:
        container["support_anchor_count"] += 1
    container["score_values"].append(record["avg_score"])
    if record["risk_score"] is not None:
        container["risk_values"].append(record["risk_score"])


def _build_overall_context(records: list[dict], container_count: int) -> dict:
    total_students = len(records)
    male_total = sum(1 for item in records if item["gender"] == "male")
    score_values = [item["avg_score"] for item in records]
    risk_values = [item["risk_score"] for item in records if item["risk_score"] is not None]
    high_risk_total = sum(1 for item in records if item["high_risk"])
    critical_total = sum(1 for item in records if item["critical_risk"])
    support_anchor_total = sum(1 for item in records if item["support_anchor"])

    return {
        "total_students": total_students,
        "male_ratio": male_total / total_students if total_students else 0.5,
        "avg_score": _average(score_values),
        "avg_risk_score": _average(risk_values),
        "ideal_high_risk": math.ceil(high_risk_total / container_count) if container_count else 0,
        "ideal_critical_risk": math.ceil(critical_total / container_count) if container_count else 0,
        "ideal_support_anchor": math.ceil(support_anchor_total / container_count) if container_count else 0,
    }


def _build_ordered_records(records: list[dict], mode: str) -> list[dict]:
    critical = sorted(
        [item for item in records if item["critical_risk"]],
        key=lambda item: (item["risk_score"] or 0, item["avg_score"]),
        reverse=True,
    )
    high = sorted(
        [item for item in records if item["high_risk"] and not item["critical_risk"]],
        key=lambda item: (item["risk_score"] or 0, item["avg_score"]),
        reverse=True,
    )

    remaining = [item for item in records if not item["high_risk"]]
    if mode == "grouping":
        anchors = sorted(
            [item for item in remaining if item["support_anchor"]],
            key=lambda item: (item["support_score"], item["avg_score"]),
            reverse=True,
        )
        anchor_ids = {item["id"] for item in anchors}
        others = sorted(
            [item for item in remaining if item["id"] not in anchor_ids],
            key=lambda item: (item["avg_score"], -(item["risk_score"] or 0), item["support_score"]),
            reverse=True,
        )
        return critical + high + anchors + others

    others = sorted(
        remaining,
        key=lambda item: (item["avg_score"], -(item["risk_score"] or 0), item["support_score"]),
        reverse=True,
    )
    return critical + high + others


def _project_penalty(container: dict, record: dict, overall: dict) -> float:
    projected_count = container["count"] + 1
    projected_male = container["male_count"] + (1 if record["gender"] == "male" else 0)
    projected_high = container["high_risk_count"] + (1 if record["high_risk"] else 0)
    projected_critical = container["critical_risk_count"] + (1 if record["critical_risk"] else 0)
    projected_support = container["support_anchor_count"] + (1 if record["support_anchor"] else 0)

    projected_scores = container["score_values"] + [record["avg_score"]]
    projected_avg_score = _average(projected_scores)
    projected_risk_values = list(container["risk_values"])
    if record["risk_score"] is not None:
        projected_risk_values.append(record["risk_score"])
    projected_avg_risk = _average(projected_risk_values)

    target_size = max(container["target_size"], 1)
    count_penalty = abs(projected_count - target_size) * 2.5
    gender_penalty = abs((projected_male / projected_count) - overall["male_ratio"]) * 6
    score_penalty = abs(projected_avg_score - overall["avg_score"]) / 8 if projected_count else 0
    risk_penalty = abs(projected_avg_risk - overall["avg_risk_score"]) * 8 if projected_risk_values else 0
    high_risk_penalty = max(0, projected_high - overall["ideal_high_risk"]) * 15
    critical_penalty = max(0, projected_critical - overall["ideal_critical_risk"]) * 30
    support_penalty = max(0, projected_support - overall["ideal_support_anchor"]) * 6

    return round(
        count_penalty
        + gender_penalty
        + score_penalty
        + risk_penalty
        + high_risk_penalty
        + critical_penalty
        + support_penalty,
        6,
    )


def _refine_by_swaps(containers: list[dict], overall: dict, max_rounds: int = 1) -> None:
    for _ in range(max_rounds):
        current_score = _evaluate_containers(containers)
        improved = False
        for left_index in range(len(containers)):
            for right_index in range(left_index + 1, len(containers)):
                left = containers[left_index]
                right = containers[right_index]
                for left_student in list(left["students"]):
                    for right_student in list(right["students"]):
                        if left_student["id"] == right_student["id"]:
                            continue
                        candidate = _clone_containers(containers)
                        _swap_students(candidate[left_index], candidate[right_index], left_student["id"], right_student["id"])
                        candidate_score = _evaluate_containers(candidate)
                        if candidate_score > current_score + 1e-6:
                            containers[:] = candidate
                            current_score = candidate_score
                            improved = True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
        if not improved:
            break


def _clone_containers(containers: list[dict]) -> list[dict]:
    clones = []
    for item in containers:
        clones.append(
            {
                "id": item["id"],
                "label": item["label"],
                "capacity": item["capacity"],
                "target_size": item["target_size"],
                "students": list(item["students"]),
                "count": item["count"],
                "male_count": item["male_count"],
                "female_count": item["female_count"],
                "high_risk_count": item["high_risk_count"],
                "critical_risk_count": item["critical_risk_count"],
                "support_anchor_count": item["support_anchor_count"],
                "score_values": list(item["score_values"]),
                "risk_values": list(item["risk_values"]),
            }
        )
    return clones


def _swap_students(left: dict, right: dict, left_student_id: int, right_student_id: int) -> None:
    left_students = [item for item in left["students"] if item["id"] != left_student_id]
    right_students = [item for item in right["students"] if item["id"] != right_student_id]
    left_student = next(item for item in left["students"] if item["id"] == left_student_id)
    right_student = next(item for item in right["students"] if item["id"] == right_student_id)
    left_students.append(right_student)
    right_students.append(left_student)
    _rebuild_container(left, left_students)
    _rebuild_container(right, right_students)


def _rebuild_container(container: dict, students: list[dict]) -> None:
    container["students"] = []
    container["count"] = 0
    container["male_count"] = 0
    container["female_count"] = 0
    container["high_risk_count"] = 0
    container["critical_risk_count"] = 0
    container["support_anchor_count"] = 0
    container["score_values"] = []
    container["risk_values"] = []
    for record in students:
        _append_record(container, record)


def _evaluate_containers(containers: list[dict]) -> float:
    metrics = defaultdict(list)
    for item in containers:
        metrics["student_count"].append(item["count"])
        metrics["male_ratio"].append(item["male_count"] / item["count"] if item["count"] else 0)
        metrics["avg_score"].append(_average(item["score_values"]))
        metrics["high_risk_count"].append(item["high_risk_count"])
        metrics["avg_risk_score"].append(_average(item["risk_values"]))

    return (
        -1.0 * _variance(metrics["student_count"])
        -1.0 * _variance(metrics["male_ratio"])
        -1.2 * _variance(metrics["avg_score"])
        -1.5 * _variance(metrics["high_risk_count"])
        -1.5 * _variance(metrics["avg_risk_score"])
    )


def _build_balance_report(rows: list[dict]) -> dict:
    return {
        "student_count_gap": _gap([item["student_count"] for item in rows]),
        "male_ratio_gap": round(_gap([
            (item["male_count"] / item["student_count"]) if item["student_count"] else 0 for item in rows
        ]), 4),
        "avg_score_gap": round(_gap([item["avg_score"] for item in rows]), 2),
        "high_risk_count_gap": _gap([item["high_risk_count"] for item in rows]),
        "avg_risk_score_gap": round(_gap([item["avg_risk_score"] for item in rows]), 4),
    }


def _variance(values: list[float]) -> float:
    if not values:
        return 0.0
    mean_value = sum(values) / len(values)
    return sum((value - mean_value) ** 2 for value in values) / len(values)


def _gap(values: list[float]) -> float:
    if not values:
        return 0.0
    return max(values) - min(values)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _bounded_score(value: float | None) -> float:
    return _clamp(float(value or 0))


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))
