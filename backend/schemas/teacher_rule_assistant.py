# -*- coding: utf-8 -*-
"""Schemas for teacher rule assistant feature."""

from pydantic import BaseModel, Field


class TeacherRuleAssistantAskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    student_id: int | None = Field(default=None, description="关联学生ID")
    event_type: str | None = Field(default=None, description="事件类型")
    mode: str = Field(default="teacher_enhanced", description="问答模式")
    chat_history: list[dict] | None = Field(default=None, description="对话历史")

