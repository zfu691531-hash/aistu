# -*- coding: utf-8 -*-
"""教师分组专项业务路由。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db, require_role
from database.models.user import User
from schemas.grouping import GroupGenerateRequest, GroupSchemeCreate, GroupSchemeUpdate
from services import grouping_service, profile_grouping_service

router = APIRouter(prefix="/api/grouping", tags=["教师分组管理"])


@router.get("/schemes")
def get_group_schemes(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    class_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("teacher", "admin")),
):
    return grouping_service.list_schemes(
        db=db,
        current_user=current_user,
        page=page,
        page_size=page_size,
        class_id=class_id,
    )


@router.get("/schemes/{scheme_id}")
def get_group_scheme_detail(
    scheme_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("teacher", "admin")),
):
    return grouping_service.get_scheme(db=db, current_user=current_user, scheme_id=scheme_id)


@router.post("/generate-with-profile")
def generate_group_scheme_with_profile(
    data: GroupGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("teacher", "admin")),
):
    return profile_grouping_service.generate_with_profile(
        db=db,
        current_user=current_user,
        class_id=data.class_id,
        group_count=data.group_count,
        constraints=data.constraints,
    )


@router.post("/schemes")
def create_group_scheme(
    data: GroupSchemeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("teacher", "admin")),
):
    return grouping_service.create_scheme(
        db=db,
        current_user=current_user,
        class_id=data.class_id,
        scheme_name=data.scheme_name,
        group_count=data.group_count,
        balance_factors=data.balance_factors,
        source_type=data.source_type,
        remark=data.remark,
        assignments=[item.model_dump() for item in data.assignments],
    )


@router.put("/schemes/{scheme_id}")
def update_group_scheme(
    scheme_id: int,
    data: GroupSchemeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("teacher", "admin")),
):
    payload = data.model_dump(exclude_unset=True)
    if "assignments" in payload:
        payload["assignments"] = [item.model_dump() for item in data.assignments or []]
    return grouping_service.update_scheme(
        db=db,
        current_user=current_user,
        scheme_id=scheme_id,
        payload=payload,
    )


@router.delete("/schemes/{scheme_id}")
def delete_group_scheme(
    scheme_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("teacher", "admin")),
):
    return grouping_service.delete_scheme(db=db, current_user=current_user, scheme_id=scheme_id)
