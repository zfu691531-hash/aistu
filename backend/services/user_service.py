# -*- coding: utf-8 -*-
"""
用户服务模块（个人中心）
========================
- get_user_info: 查询当前用户个人信息
- update_user_info: 修改个人信息（排除角色、账号等不可修改字段）
- reset_password: 重置密码（需验证旧密码）
- get_student_by_user_id: 通过显式user_id或兼容规则获取学生记录
"""

from typing import Optional

from sqlalchemy.orm import Session

from database.models.user import User
from database.models.student import Student
from core.security import verify_password, hash_password
from core.response import success_response, error_response


def get_user_info(db: Session, user_id: int) -> dict:
    """
    查询当前用户个人信息
    
    Args:
        db: 数据库会话
        user_id: 用户ID
    
    Returns:
        dict: 用户信息
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return error_response(msg="用户不存在")
    
    return success_response(data={
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    })


def update_user_info(db: Session, user_id: int, name: Optional[str] = None) -> dict:
    """
    修改个人信息（排除角色、账号等不可修改字段）
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        name: 姓名
    
    Returns:
        dict: 操作结果
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return error_response(msg="用户不存在")
    
    if name is not None:
        user.name = name
    
    db.commit()
    db.refresh(user)
    
    return success_response(msg="修改成功", data={
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "role": user.role,
    })


def reset_password(db: Session, user_id: int, old_password: str, new_password: str) -> dict:
    """
    重置密码（需验证旧密码）
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        old_password: 旧密码
        new_password: 新密码
    
    Returns:
        dict: 操作结果
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return error_response(msg="用户不存在")
    
    # 验证旧密码
    if not verify_password(old_password, user.password_hash):
        return error_response(msg="旧密码错误")
    
    # 更新密码
    user.password_hash = hash_password(new_password)
    db.commit()
    
    return success_response(msg="密码修改成功")


def get_student_by_user_id(db: Session, user_id: int) -> Optional[Student]:
    """
    优先通过 student.user_id 获取学生记录，兼容旧数据时回退到学号或姓名匹配。
    
    Args:
        db: 数据库会话
        user_id: 用户ID
    
    Returns:
        Student: 学生对象，未找到返回None
    """
    direct_student = db.query(Student).filter(Student.user_id == user_id).first()
    if direct_student:
        return direct_student

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    student = _find_student_by_user_identity(db, user)
    if not student:
        return None

    if student.user_id in {None, user.id}:
        student.user_id = user.id
        db.commit()
        db.refresh(student)
    return student


def find_student_user_id(
    db: Session,
    student_no: str | None,
    name: str | None,
) -> int | None:
    user = _find_student_user(db, student_no=student_no, name=name)
    return user.id if user else None


def _find_student_by_user_identity(db: Session, user: User) -> Optional[Student]:
    candidates: list[Student] = []

    student_no_candidates: list[str] = []
    if user.username:
        student_no_candidates.append(user.username)
        if user.username.startswith("stu_"):
            student_no_candidates.append(user.username.removeprefix("stu_"))

    for candidate in student_no_candidates:
        student = db.query(Student).filter(Student.student_no == candidate).first()
        if student:
            candidates.append(student)

    if not candidates and user.name:
        name_matches = db.query(Student).filter(Student.name == user.name).all()
        if len(name_matches) == 1:
            candidates.extend(name_matches)

    for candidate in candidates:
        if candidate.user_id not in {None, user.id}:
            continue
        return candidate
    return None


def _find_student_user(
    db: Session,
    student_no: str | None,
    name: str | None,
) -> Optional[User]:
    usernames: list[str] = []
    if student_no:
        normalized_student_no = str(student_no).strip()
        if normalized_student_no:
            usernames.extend([normalized_student_no, f"stu_{normalized_student_no}"])

    if usernames:
        user = (
            db.query(User)
            .filter(User.role == "student", User.username.in_(usernames))
            .order_by(User.id.asc())
            .first()
        )
        if user:
            return user

    normalized_name = str(name or "").strip()
    if not normalized_name:
        return None

    name_matches = (
        db.query(User)
        .filter(User.role == "student", User.name == normalized_name)
        .order_by(User.id.asc())
        .all()
    )
    if len(name_matches) == 1:
        return name_matches[0]
    return None
