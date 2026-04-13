# -*- coding: utf-8 -*-
"""Student schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import PaginationParams


class StudentCreate(BaseModel):
    student_no: str = Field(..., description="学号")
    name: str = Field(..., description="姓名")
    gender: str = Field(..., description="性别")
    age: int = Field(..., description="年龄")
    grade: str = Field(..., description="年级")
    class_id: Optional[int] = Field(None, description="班级ID")
    contact: Optional[str] = Field(None, description="联系方式")
    specialty: Optional[str] = Field(None, description="特长")
    tags: Optional[str] = Field(None, description="标签")


class StudentUpdate(BaseModel):
    student_no: Optional[str] = Field(None, description="学号")
    name: Optional[str] = Field(None, description="姓名")
    gender: Optional[str] = Field(None, description="性别")
    age: Optional[int] = Field(None, description="年龄")
    grade: Optional[str] = Field(None, description="年级")
    class_id: Optional[int] = Field(None, description="班级ID")
    contact: Optional[str] = Field(None, description="联系方式")
    specialty: Optional[str] = Field(None, description="特长")
    tags: Optional[str] = Field(None, description="标签")


class StudentQuery(PaginationParams):
    keyword: Optional[str] = Field(None, description="关键词")
    grade: Optional[str] = Field(None, description="年级")
    class_id: Optional[int] = Field(None, description="班级ID")
    tag: Optional[str] = Field(None, description="标签")
    gender: Optional[str] = Field(None, description="性别")


class StudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_no: str
    user_id: Optional[int]
    name: str
    gender: str
    age: int
    grade: Optional[str]
    class_id: Optional[int]
    class_name: str
    contact: Optional[str]
    specialty: Optional[str]
    tags: Optional[str]
    created_at: datetime
    updated_at: datetime
