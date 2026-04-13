# -*- coding: utf-8 -*-
"""Profile-aware grouping generation service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.response import error_response, success_response
from database.models.student import Student
from database.models.user import User
from services import grouping_service
from services.profile_balance_optimizer import build_student_records, generate_grouping


DEFAULT_BALANCE_FACTORS = ["gender", "academic", "risk", "support"]


def generate_with_profile(
    db: Session,
    current_user: User,
    class_id: int,
    group_count: int,
    constraints: dict | None,
) -> dict:
    access_error = grouping_service._ensure_class_access(db, current_user, class_id)
    if access_error:
        return access_error

    if group_count < 1:
        return error_response(msg="分组数量必须大于 0")

    students = (
        db.query(Student)
        .filter(Student.class_id == class_id)
        .order_by(Student.student_no.asc())
        .all()
    )
    if not students:
        return error_response(msg="当前班级暂无学生")
    if group_count > len(students):
        return error_response(msg="分组数量不能超过班级学生人数")

    records, missing_profiles = build_student_records(db, students)
    plan = generate_grouping(records, group_count)
    validation_error = grouping_service._validate_group_assignments(
        db,
        class_id,
        group_count,
        plan["assignments"],
    )
    if validation_error:
        return validation_error

    return success_response(
        data={
            "class_id": class_id,
            "group_count": group_count,
            "balance_factors": list(DEFAULT_BALANCE_FACTORS),
            "constraints": constraints or {},
            "assignments": plan["assignments"],
            "group_summaries": plan["summaries"],
            "balance_report": plan["balance_report"],
            "missing_profiles": missing_profiles,
        },
        msg="画像分组方案生成成功",
    )
