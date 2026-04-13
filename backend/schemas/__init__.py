# -*- coding: utf-8 -*-
"""
Schema 统一导出
===============
导出所有 Pydantic 模型，供其他模块导入
"""

from .common import PaginationParams, BatchDeleteRequest, IdRequest
from .user import LoginRequest, TokenResponse, PasswordChangeRequest, UserUpdate, UserInfo
from .student import StudentCreate, StudentUpdate, StudentQuery, StudentResponse
from .teacher import TeacherCreate, TeacherUpdate, TeacherQuery, TeacherResponse, TeacherBindClasses
from .class_ import ClassCreate, ClassUpdate, ClassQuery, ClassResponse, ClassStudentBind
from .grouping import GroupGenerateRequest, GroupSchemeCreate, GroupSchemeUpdate, GroupSchemeQuery, GroupSchemeResponse
from .placement import (
    PlacementGenerateRequest,
    PlacementAssignmentItem,
    PlacementBatchQuery,
    PlacementBatchResponse,
    PlacementConfirmRequest,
    PlacementValidateRequest,
)
from .score import ScoreCreate, ScoreUpdate, ScoreQuery, ScoreResponse, ScoreStatsResponse
from .ai_history import AiHistoryQuery, AiHistoryResponse
from .school_rule import SchoolRuleCreate, SchoolRuleUpdate, SchoolRuleQuery, SchoolRuleResponse

__all__ = [
    # Common
    "PaginationParams",
    "BatchDeleteRequest",
    "IdRequest",
    # User
    "LoginRequest",
    "TokenResponse",
    "PasswordChangeRequest",
    "UserUpdate",
    "UserInfo",
    # Student
    "StudentCreate",
    "StudentUpdate",
    "StudentQuery",
    "StudentResponse",
    # Teacher
    "TeacherCreate",
    "TeacherUpdate",
    "TeacherQuery",
    "TeacherResponse",
    "TeacherBindClasses",
    # Class
    "ClassCreate",
    "ClassUpdate",
    "ClassQuery",
    "ClassResponse",
    "ClassStudentBind",
    # Grouping
    "GroupGenerateRequest",
    "GroupSchemeCreate",
    "GroupSchemeUpdate",
    "GroupSchemeQuery",
    "GroupSchemeResponse",
    # Placement
    "PlacementGenerateRequest",
    "PlacementAssignmentItem",
    "PlacementBatchQuery",
    "PlacementBatchResponse",
    "PlacementConfirmRequest",
    "PlacementValidateRequest",
    # Score
    "ScoreCreate",
    "ScoreUpdate",
    "ScoreQuery",
    "ScoreResponse",
    "ScoreStatsResponse",
    # AI History
    "AiHistoryQuery",
    "AiHistoryResponse",
    # School Rule
    "SchoolRuleCreate",
    "SchoolRuleUpdate",
    "SchoolRuleQuery",
    "SchoolRuleResponse",
]
