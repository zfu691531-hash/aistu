# -*- coding: utf-8 -*-
"""Schema guard for core student table compatibility."""

from __future__ import annotations

from threading import Lock

from sqlalchemy import inspect, text

from database.connection import engine


_schema_ready = False
_schema_lock = Lock()


def ensure_student_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return

    with _schema_lock:
        if _schema_ready:
            return

        inspector = inspect(engine)
        column_names = {column["name"] for column in inspector.get_columns("student")}
        index_names = {index["name"] for index in inspector.get_indexes("student")}

        with engine.begin() as connection:
            if "user_id" not in column_names:
                if engine.dialect.name == "mysql":
                    connection.execute(text("ALTER TABLE student ADD COLUMN user_id BIGINT NULL COMMENT '关联学生用户ID'"))
                else:
                    connection.execute(text("ALTER TABLE student ADD COLUMN user_id BIGINT"))

            if "idx_user_id" not in index_names:
                connection.execute(text("CREATE UNIQUE INDEX idx_user_id ON student(user_id)"))

        _schema_ready = True
