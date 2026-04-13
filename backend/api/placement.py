# -*- coding: utf-8 -*-
"""校务正式分班专项业务路由。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_db, require_role
from database.models.user import User
from schemas.placement import PlacementConfirmRequest, PlacementGenerateRequest, PlacementValidateRequest
from services import placement_service, profile_placement_service

router = APIRouter(prefix="/api/placement", tags=["校务分班管理"])


@router.get("/overview")
def get_placement_overview(
    grade: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return placement_service.get_overview(db=db, current_user=current_user, grade=grade)


@router.post("/generate-with-profile")
def generate_placement_with_profile(
    data: PlacementGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return profile_placement_service.generate_with_profile(
        db=db,
        current_user=current_user,
        grade=data.grade,
        target_classes=data.target_classes,
        constraints=data.constraints,
    )


@router.post("/validate")
def validate_placement(
    data: PlacementValidateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return placement_service.validate_assignments(
        db=db,
        current_user=current_user,
        grade=data.grade,
        assignments=[item.model_dump() for item in data.assignments],
    )


@router.post("/confirm")
def confirm_placement(
    data: PlacementConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return placement_service.confirm_assignments(
        db=db,
        current_user=current_user,
        grade=data.grade,
        batch_name=data.batch_name,
        balance_factors=data.balance_factors,
        summary=data.summary,
        assignments=[item.model_dump() for item in data.assignments],
    )


@router.get("/batches")
def get_placement_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    grade: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return placement_service.list_batches(
        db=db,
        current_user=current_user,
        page=page,
        page_size=page_size,
        grade=grade,
    )


@router.get("/batches/{batch_id}")
def get_placement_batch_detail(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return placement_service.get_batch(db=db, current_user=current_user, batch_id=batch_id)
