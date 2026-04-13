# -*- coding: utf-8 -*-
"""Student service."""

from typing import Optional

from fastapi import UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.response import error_response, success_response
from database.models.class_ import Class
from database.models.score import Score
from database.models.student import Student
from database.models.teacher import Teacher
from database.models.user import User
from services.export_service import (
    download_template,
    generate_student_excel,
    parse_import_excel,
)
from services import tag_review_service
from services.student_care_graph_service import student_care_graph_service
from services.student_care_service import recalculate_student_care_profile
from services.user_service import get_student_by_user_id
from services.user_service import find_student_user_id
from utils.logger import logger


_UNSET = object()


def get_list(
    db: Session,
    current_user: User,
    page: int = 1,
    page_size: int = 10,
    keyword: Optional[str] = None,
    grade: Optional[str] = None,
    class_id: Optional[int] = None,
    tag: Optional[str] = None,
    gender: Optional[str] = None,
) -> dict:
    query = db.query(Student)

    teacher_class_ids = None
    if current_user.role == "student":
        student = get_student_by_user_id(db, current_user.id)
        if not student:
            return success_response(data={"list": [], "total": 0})
        query = query.filter(Student.id == student.id)
    elif current_user.role == "teacher":
        teacher_class_ids = _get_teacher_class_ids(db, current_user)
        if not teacher_class_ids:
            return success_response(data={"list": [], "total": 0})
        query = query.filter(Student.class_id.in_(teacher_class_ids))

    if keyword:
        query = query.filter(
            or_(
                Student.student_no.contains(keyword),
                Student.name.contains(keyword),
            )
        )
    if grade:
        query = query.filter(Student.grade == grade)
    if class_id:
        query = query.filter(Student.class_id == class_id)
    if tag:
        query = query.filter(Student.tags.contains(tag))
    if gender:
        query = query.filter(Student.gender == gender)

    total = query.count()
    students = (
        query.order_by(Student.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    class_ids = [student.class_id for student in students if student.class_id]
    class_map = {}
    if class_ids:
        classes = db.query(Class).filter(Class.id.in_(class_ids)).all()
        class_map = {item.id: item for item in classes}

    return success_response(
        data={
            "list": [
                {
                    "id": student.id,
                    "student_no": student.student_no,
                    "user_id": student.user_id,
                    "name": student.name,
                    "gender": student.gender,
                    "age": student.age,
                    "grade": student.grade,
                    "class_id": student.class_id,
                    "class_name": class_map.get(student.class_id).name if class_map.get(student.class_id) else "",
                    "contact": student.contact,
                    "specialty": student.specialty,
                    "tags": student.tags,
                    "created_at": student.created_at,
                    "updated_at": student.updated_at,
                }
                for student in students
            ],
            "total": total,
        }
    )


def create(
    db: Session,
    current_user: User,
    student_no: str,
    name: str,
    gender: str,
    age: int,
    grade: str,
    class_id: Optional[int] = None,
    contact: Optional[str] = None,
    specialty: Optional[str] = None,
    tags: Optional[str] = None,
) -> dict:
    if db.query(Student).filter(Student.student_no == student_no).first():
        return error_response(msg=f"学号 {student_no} 已存在")
    if gender not in {"male", "female"}:
        return error_response(msg="性别只能是 male 或 female")

    class_obj = None
    if class_id is not None:
        class_obj = db.query(Class).filter(Class.id == class_id).first()
        if not class_obj:
            return error_response(msg=f"班级ID {class_id} 不存在")
        if class_obj.current_count >= class_obj.max_count:
            return error_response(msg=f"班级 {class_obj.name} 已满员")
        grade = class_obj.grade

    access_error = _ensure_teacher_class_access(
        db=db,
        current_user=current_user,
        class_id=class_id,
        allow_unassigned=False,
    )
    if access_error:
        return access_error

    student = Student(
        student_no=student_no,
        user_id=find_student_user_id(db, student_no=student_no, name=name),
        name=name,
        gender=gender,
        age=age,
        grade=grade,
        class_id=class_id,
        contact=contact,
        specialty=specialty,
        tags=tags,
    )
    db.add(student)

    if class_obj:
        class_obj.current_count += 1

    db.commit()
    db.refresh(student)
    if tags:
        tag_review_service.create_pending_reviews(
            db=db,
            current_user=current_user,
            student=student,
            tags=_parse_tags(tags),
            source="teacher_input",
        )
    logger.info("create student success: %s - %s", student_no, name)
    return success_response(msg="创建成功", data={"id": student.id})


def update(
    db: Session,
    current_user: User,
    student_id: int,
    student_no: Optional[str] | object = _UNSET,
    name: Optional[str] | object = _UNSET,
    gender: Optional[str] | object = _UNSET,
    age: Optional[int] | object = _UNSET,
    grade: Optional[str] | object = _UNSET,
    class_id: Optional[int] | object = _UNSET,
    contact: Optional[str] | object = _UNSET,
    specialty: Optional[str] | object = _UNSET,
    tags: Optional[str] | object = _UNSET,
) -> dict:
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return error_response(msg="学生不存在")

    if current_user.role == "teacher":
        teacher_class_ids = _get_teacher_class_ids(db, current_user)
        if not teacher_class_ids or student.class_id not in teacher_class_ids:
            return error_response(code=403, msg="当前教师无权操作该学生")

    old_class_id = student.class_id
    old_tags = student.tags
    next_class_id = class_id if class_id is not _UNSET else student.class_id

    access_error = _ensure_teacher_class_access(
        db=db,
        current_user=current_user,
        class_id=next_class_id,
        allow_unassigned=False,
    )
    if access_error:
        return access_error

    if student_no is not _UNSET and student_no and student_no != student.student_no:
        if db.query(Student).filter(Student.student_no == student_no).first():
            return error_response(msg=f"学号 {student_no} 已存在")
        student.student_no = student_no

    if gender is not _UNSET:
        if gender not in {"male", "female"}:
            return error_response(msg="性别只能是 male 或 female")
        student.gender = gender

    if class_id is not _UNSET and class_id is not None and class_id != old_class_id:
        new_class = db.query(Class).filter(Class.id == class_id).first()
        if not new_class:
            return error_response(msg=f"班级ID {class_id} 不存在")
        if new_class.current_count >= new_class.max_count:
            return error_response(msg=f"班级 {new_class.name} 已满员")

        if old_class_id:
            old_class = db.query(Class).filter(Class.id == old_class_id).first()
            if old_class:
                old_class.current_count -= 1
        new_class.current_count += 1
        student.class_id = class_id
        student.grade = new_class.grade
    elif class_id is not _UNSET and class_id is None and current_user.role == "admin":
        if old_class_id:
            old_class = db.query(Class).filter(Class.id == old_class_id).first()
            if old_class:
                old_class.current_count -= 1
        student.class_id = None
        if grade is not _UNSET:
            student.grade = grade

    if name is not _UNSET:
        student.name = name
    if age is not _UNSET:
        student.age = age
    if contact is not _UNSET:
        student.contact = contact
    if specialty is not _UNSET:
        student.specialty = specialty
    if tags is not _UNSET:
        student.tags = tags
    if grade is not _UNSET and student.class_id is None:
        student.grade = grade

    if student.user_id is None:
        next_student_no = student.student_no
        next_name = student.name
        student.user_id = find_student_user_id(db, student_no=next_student_no, name=next_name)

    db.commit()
    db.refresh(student)
    if old_tags != student.tags or old_class_id != student.class_id:
        recalculate_student_care_profile(db, student)
        try:
            student_care_graph_service.sync_student_graph(db, student.id)
        except Exception:
            pass
    logger.info("update student success: %s", student.student_no)
    return success_response(msg="更新成功")


def delete(db: Session, student_id: int) -> dict:
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return error_response(msg="学生不存在")
    score_count = db.query(Score).filter(Score.student_id == student_id).count()
    if score_count > 0:
        return error_response(msg=f"该学生有 {score_count} 条成绩记录，无法删除")

    if student.class_id:
        class_obj = db.query(Class).filter(Class.id == student.class_id).first()
        if class_obj:
            class_obj.current_count -= 1

    db.delete(student)
    db.commit()
    logger.info("delete student success: %s", student.student_no)
    return success_response(msg="删除成功")


def batch_delete(db: Session, student_ids: list[int]) -> dict:
    success_count = 0
    failed_list = []

    for student_id in student_ids:
        score_count = db.query(Score).filter(Score.student_id == student_id).count()
        if score_count > 0:
            failed_list.append({"id": student_id, "reason": f"有 {score_count} 条成绩记录"})
            continue

        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            failed_list.append({"id": student_id, "reason": "学生不存在"})
            continue

        if student.class_id:
            class_obj = db.query(Class).filter(Class.id == student.class_id).first()
            if class_obj:
                class_obj.current_count -= 1

        db.delete(student)
        success_count += 1

    db.commit()
    logger.info("batch delete students success=%s failed=%s", success_count, len(failed_list))
    return success_response(
        msg=f"成功删除 {success_count} 条",
        data={"success_count": success_count, "failed_list": failed_list},
    )


def import_excel(db: Session, current_user: User, file: UploadFile) -> dict:
    valid_data, parse_errors = parse_import_excel(file, "student")
    if parse_errors and not valid_data:
        return error_response(msg="文件解析失败", data={"error_list": parse_errors})

    class_names = [row.get("班级名称", "") for row in valid_data if row.get("班级名称")]
    class_map = {}
    if class_names:
        classes = db.query(Class).filter(Class.name.in_(class_names)).all()
        class_map = {item.name: item for item in classes}

    teacher_class_ids = set(_get_teacher_class_ids(db, current_user) or [])

    student_nos = [row.get("学号", "") for row in valid_data if row.get("学号")]
    existing_nos = set()
    if student_nos:
        students = db.query(Student.student_no).filter(Student.student_no.in_(student_nos)).all()
        existing_nos = {item.student_no for item in students}

    success_count = 0
    error_list = list(parse_errors)
    gender_map = {"男": "male", "女": "female", "male": "male", "female": "female"}

    for row_num, row in enumerate(valid_data, start=2):
        student_no = row.get("学号", "").strip()
        name = row.get("姓名", "").strip()
        gender = gender_map.get(row.get("性别", "").strip())
        age_text = row.get("年龄", "").strip()
        class_name = row.get("班级名称", "").strip()
        contact = row.get("联系方式", "").strip() or None
        specialty = row.get("特长", "").strip() or None
        tags = row.get("标签", "").strip() or None

        class_obj = class_map.get(class_name)
        if not class_obj:
            error_list.append({"row": row_num, "message": f"班级 {class_name} 不存在"})
            continue
        if current_user.role == "teacher" and class_obj.id not in teacher_class_ids:
            error_list.append({"row": row_num, "message": f"教师无权导入到班级 {class_name}"})
            continue
        if class_obj.current_count >= class_obj.max_count:
            error_list.append({"row": row_num, "message": f"班级 {class_name} 已满员"})
            continue
        if student_no in existing_nos:
            error_list.append({"row": row_num, "message": f"学号 {student_no} 已存在"})
            continue
        if not gender:
            error_list.append({"row": row_num, "message": "性别无效，只能是男/女"})
            continue

        age = None
        if age_text:
            try:
                age = int(age_text)
            except ValueError:
                error_list.append({"row": row_num, "message": f"年龄 {age_text} 不是有效整数"})
                continue

        db.add(
            Student(
                student_no=student_no,
                user_id=find_student_user_id(db, student_no=student_no, name=name),
                name=name,
                gender=gender,
                age=age,
                grade=class_obj.grade,
                class_id=class_obj.id,
                contact=contact,
                specialty=specialty,
                tags=tags,
            )
        )
        class_obj.current_count += 1
        existing_nos.add(student_no)
        success_count += 1

    db.commit()
    logger.info("import students success=%s failed=%s", success_count, len(error_list))
    return success_response(
        msg=f"成功导入 {success_count} 条",
        data={"success_count": success_count, "error_list": error_list},
    )


def export_excel(
    db: Session,
    current_user: User,
    keyword: Optional[str] = None,
    grade: Optional[str] = None,
    class_id: Optional[int] = None,
    tag: Optional[str] = None,
    gender: Optional[str] = None,
) -> StreamingResponse:
    result = get_list(
        db=db,
        current_user=current_user,
        page=1,
        page_size=5000,
        keyword=keyword,
        grade=grade,
        class_id=class_id,
        tag=tag,
        gender=gender,
    )
    students = result["data"]["list"]
    gender_map = {"male": "男", "female": "女"}
    rows = [
        {
            "学号": item["student_no"],
            "姓名": item["name"],
            "性别": gender_map.get(item["gender"], item["gender"]),
            "年龄": item["age"] or "",
            "年级": item["grade"] or "",
            "班级名称": item["class_name"] or "",
            "联系方式": item["contact"] or "",
            "特长": item["specialty"] or "",
            "标签": item["tags"] or "",
        }
        for item in students
    ]
    logger.info("export students count=%s", len(rows))
    return generate_student_excel(rows)


def get_template() -> StreamingResponse:
    return download_template("student")


def _get_teacher_class_ids(db: Session, current_user: User) -> list[int]:
    teacher = db.query(Teacher).filter(Teacher.name == current_user.name).first()
    if not teacher or not teacher.class_ids:
        return []
    return [int(item.strip()) for item in teacher.class_ids.split(",") if item.strip()]


def _ensure_teacher_class_access(
    db: Session,
    current_user: User,
    class_id: Optional[int],
    allow_unassigned: bool,
) -> dict | None:
    if current_user.role != "teacher":
        return None
    if class_id is None:
        if allow_unassigned:
            return None
        return error_response(code=403, msg="教师新增或编辑学生时必须选择本班班级")
    teacher_class_ids = _get_teacher_class_ids(db, current_user)
    if class_id not in teacher_class_ids:
        return error_response(code=403, msg="当前教师只能操作自己绑定班级的学生")
    return None


def _parse_tags(tags: Optional[str]) -> list[str]:
    if not tags:
        return []
    return [item.strip() for item in tags.split(",") if item.strip()]
