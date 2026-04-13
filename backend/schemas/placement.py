# -*- coding: utf-8 -*-
"""校务分班相关 Schema。"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import PaginationParams


class PlacementAssignmentItem(BaseModel):
    class_id: int = Field(..., description="目标班级 ID")
    student_ids: List[int] = Field(default_factory=list, description="学生 ID 列表")


class PlacementValidateRequest(BaseModel):
    grade: str = Field(..., description="年级")
    assignments: List[PlacementAssignmentItem] = Field(default_factory=list, description="当前分班结果")


class PlacementGenerateRequest(BaseModel):
    grade: str = Field(..., description="年级")
    target_classes: List[int] = Field(default_factory=list, description="目标班级 ID 列表，为空时默认当前年级全部有效班级")
    constraints: Optional[dict] = Field(None, description="生成约束配置")


class PlacementConfirmRequest(BaseModel):
    grade: str = Field(..., description="年级")
    batch_name: str = Field(..., description="批次名称")
    balance_factors: List[str] = Field(default_factory=list, description="均衡因素")
    summary: Optional[dict] = Field(None, description="前端统计摘要")
    assignments: List[PlacementAssignmentItem] = Field(default_factory=list, description="最终分班结果")


class PlacementBatchQuery(PaginationParams):
    grade: Optional[str] = Field(None, description="年级")


class PlacementBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    grade: str
    batch_name: str
    created_by: int
    student_count: int
    class_count: int
    status: str
    balance_factors: List[str]
    assignment_result_json: List[dict]
    summary_json: dict
    confirmed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
