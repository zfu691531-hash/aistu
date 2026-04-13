# -*- coding: utf-8 -*-
"""Teacher rule assistant APIs."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_db, require_role
from database.models.user import User
from schemas.teacher_rule_assistant import TeacherRuleAssistantAskRequest
from services.rag import teacher_rule_assistant_service

router = APIRouter(prefix="/api/teacher-rule-assistant", tags=["teacher-rule-assistant"])


@router.post("/ask")
async def ask_teacher_rule_assistant(
    request: TeacherRuleAssistantAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("teacher", "admin")),
):
    return await teacher_rule_assistant_service.ask_teacher_rule_assistant(db, current_user, request)

