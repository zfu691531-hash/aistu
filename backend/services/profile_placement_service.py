# -*- coding: utf-8 -*-
"""Profile-aware placement generation service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.response import error_response, success_response
from database.models.class_ import Class
from database.models.student import Student
from database.models.user import User
from services import placement_service
from services.profile_balance_optimizer import build_student_records, generate_placement


DEFAULT_BALANCE_FACTORS = ["gender", "academic", "risk"]


def generate_with_profile(
    db: Session,
    current_user: User,
    grade: str,
    target_classes: list[int] | None,
    constraints: dict | None,
) -> dict:
    auth_error = placement_service._ensure_admin(current_user)
    if auth_error:
        return auth_error

    all_classes = placement_service._get_target_classes(db, grade)
    if target_classes:
        target_class_set = {int(item) for item in target_classes}
        all_class_ids = {int(item.id) for item in all_classes}
        if target_class_set != all_class_ids:
            return error_response(msg="V1 仅支持当前年级全部有效班级参与画像分班")
    classes = all_classes
    if not classes:
        return error_response(msg="该年级没有可用班级")

    students, source_type = placement_service._get_eligible_students(
        db,
        grade,
        [int(item.id) for item in classes],
    )
    if not students:
        return error_response(msg="当前没有可用于正式分班的学生")
    if sum(int(item.max_count or 0) for item in classes) < len(students):
        return error_response(msg="目标班级总容量不足，无法生成画像分班方案")

    records, missing_profiles = build_student_records(db, students)
    plan = generate_placement(records, classes)
    validation = placement_service._build_validation_summary(db, grade, plan["assignments"])
    if isinstance(validation, dict) and "code" in validation and validation.get("code") != 200:
        return validation

    return success_response(
        data={
            "grade": grade,
            "source_type": source_type,
            "balance_factors": list(DEFAULT_BALANCE_FACTORS),
            "constraints": constraints or {},
            "assignments": plan["assignments"],
            "class_summaries": plan["summaries"],
            "balance_report": plan["balance_report"],
            "missing_profiles": missing_profiles,
            "validation_summary": validation["summary"],
        },
        msg="画像分班方案生成成功",
    )
