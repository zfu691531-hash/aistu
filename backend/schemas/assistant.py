# -*- coding: utf-8 -*-
"""Schemas for personal AI assistant."""

from pydantic import BaseModel, Field


class AssistantMessageRequest(BaseModel):
    session_id: int | None = Field(default=None, description="会话ID")
    content: str = Field(..., min_length=1, max_length=2000, description="用户消息")


class AssistantSessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=100, description="会话标题")


class AssistantSessionClearRequest(BaseModel):
    session_id: int | None = Field(default=None, description="会话ID")
