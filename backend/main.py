#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FastAPI backend entry."""

import os
import sys
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api import (
    assistant,
    ai_history,
    ai_tools,
    auth,
    classes,
    grouping,
    placement,
    rule_feedback,
    rule_kb,
    rule_rag,
    school_rules,
    scores,
    student_care,
    student_care_data,
    tag_definitions,
    tag_reviews,
    teacher_rule_assistant,
    students,
    teachers,
    users,
)
from core.config import settings
from database import models  # noqa: F401
from database.base import Base
from database.connection import engine
from middleware.log_middleware import LogMiddleware
from services.student_schema_guard import ensure_student_schema

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine, checkfirst=True)
    ensure_student_grade_column()
    ensure_student_schema()
    normalize_legacy_grade_labels()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="AIStu - 校园AI教务助手平台",
    description="基于AI大模型的智能教务管理系统",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(LogMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(assistant.router)
app.include_router(users.router)
app.include_router(students.router)
app.include_router(teachers.router)
app.include_router(classes.router)
app.include_router(scores.router)
app.include_router(student_care.router)
app.include_router(student_care_data.router)
app.include_router(tag_definitions.router)
app.include_router(tag_reviews.router)
app.include_router(ai_tools.router)
app.include_router(ai_history.router)
app.include_router(grouping.router)
app.include_router(placement.router)
app.include_router(school_rules.router)
app.include_router(rule_rag.router)
app.include_router(teacher_rule_assistant.router)
app.include_router(rule_feedback.router)
app.include_router(rule_kb.router)


def ensure_student_grade_column() -> None:
    inspector = inspect(engine)
    column_names = {column["name"] for column in inspector.get_columns("student")}

    with engine.begin() as connection:
        if "grade" not in column_names:
            if engine.dialect.name == "mysql":
                connection.execute(text("ALTER TABLE student ADD COLUMN grade VARCHAR(20) NULL COMMENT '年级'"))
            else:
                connection.execute(text("ALTER TABLE student ADD COLUMN grade VARCHAR(20)"))

        if engine.dialect.name == "mysql":
            connection.execute(
                text(
                    """
                    UPDATE student s
                    LEFT JOIN class c ON s.class_id = c.id
                    SET s.grade = COALESCE(s.grade, c.grade)
                    WHERE s.grade IS NULL AND s.class_id IS NOT NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE student
                    SET grade = CONCAT(SUBSTRING(student_no, 1, 4), '级')
                    WHERE grade IS NULL
                      AND student_no IS NOT NULL
                      AND CHAR_LENGTH(student_no) >= 4
                    """
                )
            )


def normalize_legacy_grade_labels() -> None:
    grade_mapping = {
        "2024级": "高一",
        "2023级": "高二",
        "2022级": "高三",
    }

    with engine.begin() as connection:
        if engine.dialect.name == "mysql":
            for old_grade, new_grade in grade_mapping.items():
                connection.execute(
                    text("UPDATE class SET grade = :new_grade WHERE grade = :old_grade"),
                    {"old_grade": old_grade, "new_grade": new_grade},
                )
                connection.execute(
                    text("UPDATE student SET grade = :new_grade WHERE grade = :old_grade"),
                    {"old_grade": old_grade, "new_grade": new_grade},
                )
                connection.execute(
                    text("UPDATE placement_batch SET grade = :new_grade WHERE grade = :old_grade"),
                    {"old_grade": old_grade, "new_grade": new_grade},
                )

            class_rows = connection.execute(text("SELECT id, name FROM class")).fetchall()
            for class_id, class_name in class_rows:
                if not class_name:
                    continue
                normalized_name = class_name
                for old_grade, new_grade in grade_mapping.items():
                    normalized_name = normalized_name.replace(old_grade, new_grade)
                if normalized_name != class_name:
                    connection.execute(
                        text("UPDATE class SET name = :name WHERE id = :id"),
                        {"id": class_id, "name": normalized_name},
                    )

            batch_rows = connection.execute(text("SELECT id, batch_name FROM placement_batch")).fetchall()
            for batch_id, batch_name in batch_rows:
                if not batch_name:
                    continue
                normalized_batch_name = batch_name
                for old_grade, new_grade in grade_mapping.items():
                    normalized_batch_name = normalized_batch_name.replace(old_grade, new_grade)
                if normalized_batch_name != batch_name:
                    connection.execute(
                        text("UPDATE placement_batch SET batch_name = :batch_name WHERE id = :id"),
                        {"id": batch_id, "batch_name": normalized_batch_name},
                    )

            student_rows = connection.execute(text("SELECT id, student_no, grade FROM student")).fetchall()
            for student_id, student_no, grade in student_rows:
                if grade:
                    continue
                if not student_no or len(student_no) < 4:
                    continue
                inferred_grade = infer_grade_from_student_no(student_no)
                if inferred_grade:
                    connection.execute(
                        text("UPDATE student SET grade = :grade WHERE id = :id"),
                        {"id": student_id, "grade": inferred_grade},
                    )


def infer_grade_from_student_no(student_no: str) -> str | None:
    match = re.match(r"^(20\d{2})", student_no or "")
    if not match:
        return None
    admission_year = match.group(1)
    return {
        "2024": "高一",
        "2023": "高二",
        "2022": "高三",
    }.get(admission_year)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_detail = str(exc) if settings.DEBUG else "服务器内部错误"
    return JSONResponse(
        status_code=500,
        content={"code": 500, "msg": error_detail, "data": None},
    )


@app.get("/")
async def root():
    return {
        "name": "AIStu - 校园AI教务助手平台",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "running",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
        log_level="info",
    )
