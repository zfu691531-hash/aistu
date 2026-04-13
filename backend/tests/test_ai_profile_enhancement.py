# -*- coding: utf-8 -*-
"""Tests for AI tools enhanced with student care profile context."""

from __future__ import annotations

from types import SimpleNamespace

from database.connection import SessionLocal
from database.models.student import Student
from database.models.student_care_profile import StudentCareProfile
from database.models.user import User
from services.ai import comment_generator, score_diagnosis


def test_score_diagnosis_prompt_contains_profile_context(monkeypatch):
    captured = {}

    async def fake_call(system_prompt, user_prompt, *args, **kwargs):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "诊断完成"

    monkeypatch.setattr(score_diagnosis.ai_client, "call", fake_call)

    db = SessionLocal()
    try:
        student = db.query(Student).filter(Student.id == 1).first()
        user = db.query(User).filter(User.username == "admin").first()
        assert student is not None
        assert user is not None

        profile = db.query(StudentCareProfile).filter(StudentCareProfile.student_id == student.id).first()
        if not profile:
            profile = StudentCareProfile(student_id=student.id, class_id=student.class_id)
            db.add(profile)
        profile.study_score = 0.82
        profile.emotion_score = 0.66
        profile.social_score = 0.31
        profile.safety_score = 0.24
        profile.family_score = 0.38
        profile.behavior_score = 0.22
        profile.risk_level = "medium"
        profile.trend = "up"
        db.commit()

        result = _run_async(
            score_diagnosis.diagnose_score(
                db,
                user,
                score_diagnosis.ScoreDiagnosisRequest(student_id=student.id),
            )
        )

        assert result["code"] == 200
        assert result["data"]["diagnosis"] == "诊断完成"
        assert "学生关怀状态摘要" in captured["user_prompt"]
        assert "学习压力" in captured["user_prompt"]
        assert "不要直接使用“高风险”" in captured["system_prompt"]
    finally:
        db.close()


def test_comment_generator_prompt_contains_gentle_profile_guidance(monkeypatch):
    captured = {}

    async def fake_call(system_prompt, user_prompt, *args, **kwargs):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "评语完成"

    monkeypatch.setattr(comment_generator.ai_client, "call", fake_call)

    db = SessionLocal()
    try:
        student = db.query(Student).filter(Student.id == 1).first()
        assert student is not None

        profile = db.query(StudentCareProfile).filter(StudentCareProfile.student_id == student.id).first()
        if not profile:
            profile = StudentCareProfile(student_id=student.id, class_id=student.class_id)
            db.add(profile)
        profile.emotion_score = 0.78
        profile.study_score = 0.71
        profile.social_score = 0.35
        profile.safety_score = 0.20
        profile.family_score = 0.32
        profile.behavior_score = 0.28
        profile.risk_level = "high"
        profile.trend = "steady"
        db.commit()

        result = _run_async(
            comment_generator._generate_single(
                db,
                student,
                comment_generator.CommentRequest(style="鼓励型", semester="2025-2026学年第二学期"),
            )
        )

        assert result == "评语完成"
        assert "学生关怀状态摘要" in captured["user_prompt"]
        assert "温和、支持性的表达" in captured["user_prompt"]
        assert "不要直接提及画像分数" in captured["system_prompt"]
    finally:
        db.close()


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)
