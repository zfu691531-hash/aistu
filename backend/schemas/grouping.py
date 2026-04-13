# -*- coding: utf-8 -*-
"""教师分组相关 Schema。"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import PaginationParams


class GroupStudentAssign(BaseModel):
    group_no: int = Field(..., description="组号，从 1 开始")
    student_ids: List[int] = Field(default_factory=list, description="学生 ID 列表")


class GroupSchemeCreate(BaseModel):
    class_id: int = Field(..., description="班级 ID")
    scheme_name: str = Field(..., description="方案名称")
    group_count: int = Field(..., ge=1, description="分组数量")
    balance_factors: List[str] = Field(default_factory=list, description="均衡因素")
    source_type: str = Field("manual", description="manual 或 ai")
    remark: Optional[str] = Field(None, description="备注")
    assignments: List[GroupStudentAssign] = Field(default_factory=list, description="分组结果")


class GroupGenerateRequest(BaseModel):
    class_id: int = Field(..., description="班级 ID")
    group_count: int = Field(..., ge=1, description="分组数量")
    constraints: Optional[dict] = Field(None, description="生成约束配置")


class GroupSchemeUpdate(BaseModel):
    scheme_name: Optional[str] = Field(None, description="方案名称")
    group_count: Optional[int] = Field(None, ge=1, description="分组数量")
    balance_factors: Optional[List[str]] = Field(None, description="均衡因素")
    source_type: Optional[str] = Field(None, description="manual 或 ai")
    remark: Optional[str] = Field(None, description="备注")
    assignments: Optional[List[GroupStudentAssign]] = Field(None, description="分组结果")


class GroupSchemeQuery(PaginationParams):
    class_id: Optional[int] = Field(None, description="班级 ID")


class GroupSchemeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    created_by: int
    scheme_name: str
    group_count: int
    balance_factors: List[str]
    group_result_json: List[dict]
    source_type: str
    remark: Optional[str] = None
    created_at: datetime
    updated_at: datetime
