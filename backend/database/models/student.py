# -*- coding: utf-8 -*-
"""Student model."""

from sqlalchemy import BigInteger, Enum, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin


class Student(Base, TimestampMixin):
    __tablename__ = "student"
    __table_args__ = (
        Index("idx_class_id", "class_id"),
        Index("idx_grade", "grade"),
        Index("idx_user_id", "user_id", unique=True),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="主键"
    )
    student_no: Mapped[str] = mapped_column(
        String(20), unique=True, comment="学号"
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="关联学生用户ID"
    )
    name: Mapped[str] = mapped_column(
        String(50), comment="姓名"
    )
    gender: Mapped[str] = mapped_column(
        Enum("male", "female"), comment="性别"
    )
    age: Mapped[int | None] = mapped_column(
        Integer, comment="年龄"
    )
    grade: Mapped[str | None] = mapped_column(
        String(20), comment="年级"
    )
    class_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="所属班级ID"
    )
    contact: Mapped[str | None] = mapped_column(
        String(20), comment="联系方式"
    )
    specialty: Mapped[str | None] = mapped_column(
        String(200), comment="特长"
    )
    tags: Mapped[str | None] = mapped_column(
        String(500), comment="标签，逗号分隔"
    )
