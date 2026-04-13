# -*- coding: utf-8 -*-
"""Placement service."""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.response import error_response, success_response
from database.models.class_ import Class
from database.models.placement_batch import PlacementBatch
from database.models.score import Score
from database.models.student import Student
from database.models.user import User


def get_overview(db: Session, current_user: User, grade: str) -> dict:
    auth_error = _ensure_admin(current_user)
    if auth_error:
        return auth_error

    classes = _get_target_classes(db, grade)
    if not classes:
        return error_response(msg="该年级没有可用班级")

    students, source_type = _get_eligible_students(db, grade, [item.id for item in classes])
    return success_response(
        data={
            "grade": grade,
            "source_type": source_type,
            "classes": [_serialize_class(item) for item in classes],
            "students": [_serialize_student(db, item) for item in students],
        }
    )


def validate_assignments(
    db: Session,
    current_user: User,
    grade: str,
    assignments: list[dict],
) -> dict:
    auth_error = _ensure_admin(current_user)
    if auth_error:
        return auth_error

    summary_or_error = _build_validation_summary(db, grade, assignments)
    if isinstance(summary_or_error, dict) and "code" in summary_or_error and summary_or_error.get("code") != 200:
        return summary_or_error
    return success_response(msg="分班结果校验通过", data=summary_or_error)


def confirm_assignments(
    db: Session,
    current_user: User,
    grade: str,
    batch_name: str,
    balance_factors: list[str],
    summary: dict | None,
    assignments: list[dict],
) -> dict:
    auth_error = _ensure_admin(current_user)
    if auth_error:
        return auth_error

    validation = _build_validation_summary(db, grade, assignments)
    if isinstance(validation, dict) and "code" in validation and validation.get("code") != 200:
        return validation

    target_class_map = {
        item.id: item for item in db.query(Class).filter(Class.grade == grade, Class.status == 1).all()
    }
    eligible_student_ids = set(validation["eligible_student_ids"])
    student_map = {
        student.id: student
        for student in db.query(Student).filter(Student.id.in_(eligible_student_ids)).all()
    }

    for item in assignments:
        target_class = target_class_map[item["class_id"]]
        for student_id in item.get("student_ids", []):
            student = student_map[student_id]
            student.class_id = item["class_id"]
            student.grade = target_class.grade

    for class_obj in target_class_map.values():
        class_obj.current_count = db.query(Student).filter(Student.class_id == class_obj.id).count()

    persisted_summary = summary or validation["summary"]
    batch = PlacementBatch(
        grade=grade,
        batch_name=batch_name,
        created_by=current_user.id,
        student_count=validation["student_count"],
        class_count=validation["class_count"],
        status="confirmed",
        balance_factors=balance_factors,
        assignment_result_json=validation["assignments"],
        summary_json=persisted_summary,
        confirmed_at=datetime.now(),
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    return success_response(
        msg="正式分班已生效",
        data={"id": batch.id, "summary": persisted_summary},
    )


def list_batches(
    db: Session,
    current_user: User,
    page: int = 1,
    page_size: int = 10,
    grade: str | None = None,
) -> dict:
    auth_error = _ensure_admin(current_user)
    if auth_error:
        return auth_error

    query = db.query(PlacementBatch)
    if grade:
        query = query.filter(PlacementBatch.grade == grade)

    total = query.count()
    items = (
        query.order_by(PlacementBatch.confirmed_at.desc(), PlacementBatch.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return success_response(data={"list": [_serialize_batch(item) for item in items], "total": total})


def get_batch(db: Session, current_user: User, batch_id: int) -> dict:
    auth_error = _ensure_admin(current_user)
    if auth_error:
        return auth_error
    item = db.query(PlacementBatch).filter(PlacementBatch.id == batch_id).first()
    if not item:
        return error_response(msg="分班批次不存在")
    return success_response(data=_serialize_batch(item))


def _build_validation_summary(db: Session, grade: str, assignments: list[dict]) -> dict:
    classes = _get_target_classes(db, grade)
    if not classes:
        return error_response(msg="该年级没有可用班级")

    target_class_map = {item.id: item for item in classes}
    target_class_ids = set(target_class_map.keys())

    if len(assignments) != len(target_class_ids):
        return error_response(msg="分班结果与目标班级数量不一致")

    assignment_class_ids = {item.get("class_id") for item in assignments}
    if assignment_class_ids != target_class_ids:
        return error_response(msg="分班结果中的班级与目标年级班级不一致")

    eligible_students, _ = _get_eligible_students(db, grade, list(target_class_ids))
    eligible_student_ids = {item.id for item in eligible_students}
    if not eligible_student_ids:
        return error_response(msg="当前没有可用于正式分班的学生")

    student_map = {item.id: item for item in eligible_students}
    assigned_ids: list[int] = []
    class_summaries = []

    for item in assignments:
        class_id = item.get("class_id")
        student_ids = item.get("student_ids", [])
        assigned_ids.extend(student_ids)

        if len(student_ids) > target_class_map[class_id].max_count:
            return error_response(msg=f"班级 {target_class_map[class_id].name} 超出人数上限")

        students = []
        for student_id in student_ids:
            student = student_map.get(student_id)
            if not student:
                return error_response(msg=f"学生 {student_id} 不在本次可分班范围内")
            students.append(student)

        male_count = sum(1 for student in students if student.gender == "male")
        female_count = len(students) - male_count
        class_summaries.append(
            {
                "class_id": class_id,
                "class_name": target_class_map[class_id].name,
                "assigned_count": len(student_ids),
                "male_count": male_count,
                "female_count": female_count,
                "avg_score": _calc_avg_score(db, student_ids),
            }
        )

    if len(assigned_ids) != len(set(assigned_ids)):
        return error_response(msg="分班结果中存在重复分配的学生")
    if set(assigned_ids) != eligible_student_ids:
        return error_response(msg="分班结果必须完整覆盖本次待分班学生")

    return {
        "grade": grade,
        "class_count": len(classes),
        "student_count": len(eligible_student_ids),
        "eligible_student_ids": list(eligible_student_ids),
        "assignments": assignments,
        "summary": {
            "grade": grade,
            "class_summaries": class_summaries,
            "unassigned_count": 0,
            "total_students": len(eligible_student_ids),
        },
    }


def _get_target_classes(db: Session, grade: str) -> list[Class]:
    return (
        db.query(Class)
        .filter(Class.grade == grade, Class.status == 1)
        .order_by(Class.name.asc())
        .all()
    )


def _get_eligible_students(
    db: Session,
    grade: str,
    target_class_ids: list[int],
) -> tuple[list[Student], str]:
    students = (
        db.query(Student)
        .filter(Student.grade == grade, Student.class_id.is_(None))
        .order_by(Student.student_no.asc())
        .all()
    )
    if students:
        return students, "unassigned"

    students = (
        db.query(Student)
        .filter(Student.grade == grade, Student.class_id.in_(target_class_ids))
        .order_by(Student.student_no.asc())
        .all()
    )
    return students, "current_grade"


def _serialize_class(item: Class) -> dict:
    return {
        "id": item.id,
        "grade": item.grade,
        "name": item.name,
        "max_count": item.max_count,
        "current_count": item.current_count,
        "status": item.status,
    }


def _serialize_student(db: Session, student: Student) -> dict:
    class_name = ""
    if student.class_id:
        class_obj = db.query(Class).filter(Class.id == student.class_id).first()
        class_name = class_obj.name if class_obj else ""
    return {
        "id": student.id,
        "student_no": student.student_no,
        "name": student.name,
        "gender": student.gender,
        "grade": student.grade,
        "class_id": student.class_id,
        "class_name": class_name,
        "tags": student.tags or "",
        "avg_score": _calc_avg_score(db, [student.id]),
    }


def _serialize_batch(item: PlacementBatch) -> dict:
    return {
        "id": item.id,
        "grade": item.grade,
        "batch_name": item.batch_name,
        "created_by": item.created_by,
        "student_count": item.student_count,
        "class_count": item.class_count,
        "status": item.status,
        "balance_factors": item.balance_factors or [],
        "assignment_result_json": item.assignment_result_json or [],
        "summary_json": item.summary_json or {},
        "confirmed_at": item.confirmed_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _calc_avg_score(db: Session, student_ids: list[int]) -> float:
    if not student_ids:
        return 0
    avg = db.query(func.avg(Score.score)).filter(Score.student_id.in_(student_ids)).scalar()
    return round(float(avg), 1) if avg is not None else 0


def _ensure_admin(current_user: User) -> dict | None:
    if current_user.role != "admin":
        return error_response(code=403, msg="只有管理员可以执行校务分班")
    return None
