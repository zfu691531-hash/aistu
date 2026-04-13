# -*- coding: utf-8 -*-
"""Tests for teacher rule assistant API."""

from services.rag import teacher_rule_assistant_service
from tests.conftest import auth_headers, create_client, login_as


async def fake_teacher_assistant(*args, **kwargs):
    return {
        "code": 200,
        "msg": "操作成功",
        "data": {
            "answer": "这是教师版校规助手的测试回答。",
            "decision_summary": {
                "conclusion": "建议先按课堂纪律相关规则处理。",
                "primary_action": "先核对事实经过。",
                "parent_contact": "暂不优先联系家长",
                "care_followup": "暂不优先转入关怀跟进",
            },
            "policy_basis": [],
            "student_context_summary": {},
            "recommended_actions": [],
            "parent_contact_advice": {"suggested": False, "reason": "test"},
            "care_followup_advice": {"suggested": False, "reason": "test"},
            "needs_manual_confirmation": [],
            "history_experience": {"history_summary": "test", "history_risk_hint": False, "history_feedback_count": 0},
            "sources": [],
            "meta": {"mode": "teacher_enhanced"},
        },
    }


def test_teacher_can_access_teacher_rule_assistant(monkeypatch):
    monkeypatch.setattr(teacher_rule_assistant_service, "ask_teacher_rule_assistant", fake_teacher_assistant)

    client = create_client()
    token = login_as(client, username="wang_math", password="teacher123")
    headers = auth_headers(token)

    response = client.post(
        "/api/teacher-rule-assistant/ask",
        headers=headers,
        json={"question": "这个学生迟到三次按校规怎么处理？", "student_id": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["meta"]["mode"] == "teacher_enhanced"
    assert "decision_summary" in body["data"]


def test_student_cannot_access_teacher_rule_assistant():
    client = create_client()
    token = login_as(client, username="stu_2024001", password="student123")
    headers = auth_headers(token)

    response = client.post(
        "/api/teacher-rule-assistant/ask",
        headers=headers,
        json={"question": "我想问老师版接口"},
    )
    assert response.status_code == 403


def test_teacher_rule_assistant_returns_fact_summaries():
    client = create_client()
    token = login_as(client, username="wang_math", password="teacher123")
    headers = auth_headers(token)

    attendance_resp = client.post(
        "/api/attendance",
        headers=headers,
        json={"student_id": 1, "date": "2026-04-11", "status": "late", "remark": "晨检后迟到"},
    )
    behavior_resp = client.post(
        "/api/behavior-events",
        headers=headers,
        json={
            "student_id": 1,
            "event_type": "discipline",
            "event_level": "medium",
            "event_desc": "课堂纪律提醒测试",
            "occurred_at": "2026-04-11 09:10:00",
        },
    )
    assert attendance_resp.status_code == 200
    assert behavior_resp.status_code == 200
    attendance_id = attendance_resp.json()["data"]["id"]
    behavior_id = behavior_resp.json()["data"]["id"]

    try:
        response = client.post(
            "/api/teacher-rule-assistant/ask",
            headers=headers,
            json={"question": "这个学生最近表现如何，按校规怎么理解？", "student_id": 1},
        )
        assert response.status_code == 200
        body = response.json()
        summary = body["data"]["student_context_summary"]
        assert "纪律" in summary["behavior_summary"] or "discipline" in summary["behavior_summary"]
        assert "late" in summary["attendance_summary"]
    finally:
        client.delete(f"/api/attendance/{attendance_id}", headers=headers)
        client.delete(f"/api/behavior-events/{behavior_id}", headers=headers)


def test_teacher_rule_assistant_returns_care_and_family_summaries():
    client = create_client()
    token = login_as(client, username="wang_math", password="teacher123")
    headers = auth_headers(token)

    observation_resp = client.post(
        "/api/care-observations",
        headers=headers,
        json={
            "student_id": 1,
            "dimension": "emotion",
            "observation_type": "care_talk",
            "observation_level": "medium",
            "observed_at": "2026-04-11 11:20:00",
            "summary": "近期情绪起伏较明显，需要更稳定的支持性沟通",
        },
    )
    family_resp = client.post(
        "/api/family-contacts",
        headers=headers,
        json={
            "student_id": 1,
            "contact_type": "phone",
            "summary": "已电话沟通近期课堂状态，家长表示愿意配合后续提醒",
        },
    )
    assert observation_resp.status_code == 200
    assert family_resp.status_code == 200
    observation_id = observation_resp.json()["data"]["id"]
    family_id = family_resp.json()["data"]["id"]

    try:
        response = client.post(
            "/api/teacher-rule-assistant/ask",
            headers=headers,
            json={"question": "这名学生这次课堂问题后，老师怎么沟通更合适？", "student_id": 1},
        )
        assert response.status_code == 200
        body = response.json()
        summary = body["data"]["student_context_summary"]
        assert "支持性沟通" in summary["care_hint"] or "关怀观察" in summary["care_hint"]
        assert "近期已有" in body["data"]["parent_contact_advice"]["reason"]
    finally:
        client.delete(f"/api/care-observations/{observation_id}", headers=headers)
        client.delete(f"/api/family-contacts/{family_id}", headers=headers)


def test_teacher_rule_assistant_includes_audit_block_and_decision_summary():
    client = create_client()
    token = login_as(client, username="wang_math", password="teacher123")
    headers = auth_headers(token)

    response = client.post(
        "/api/teacher-rule-assistant/ask",
        headers=headers,
        json={"question": "请结合校规给出老师处理建议", "student_id": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert "audit" in body["data"]
    assert "passed" in body["data"]["audit"]
    assert "decision_summary" in body["data"]


def test_teacher_rule_assistant_gatekeeper_requests_clarification():
    client = create_client()
    token = login_as(client, username="wang_math", password="teacher123")
    headers = auth_headers(token)

    response = client.post(
        "/api/teacher-rule-assistant/ask",
        headers=headers,
        json={"question": "这个学生该怎么处理？"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["meta"]["gatekeeper"]["question_clear"] is False
    assert "补充" in body["data"]["answer"]


def test_teacher_rule_assistant_planner_marks_care_flow():
    client = create_client()
    token = login_as(client, username="wang_math", password="teacher123")
    headers = auth_headers(token)

    response = client.post(
        "/api/teacher-rule-assistant/ask",
        headers=headers,
        json={"question": "这名学生课堂问题后，老师怎么沟通并决定是否联系家长？", "student_id": 1},
    )
    assert response.status_code == 200
    body = response.json()
    planner = body["data"]["meta"]["planner"]
    assert any("关怀" in item or "家校" in item for item in planner)


def test_teacher_rule_assistant_returns_history_experience_summary():
    client = create_client()
    token = login_as(client, username="wang_math", password="teacher123")
    headers = auth_headers(token)

    first_response = client.post(
        "/api/teacher-rule-assistant/ask",
        headers=headers,
        json={"question": "学生迟到后老师按校规怎么处理？", "student_id": 1},
    )
    assert first_response.status_code == 200
    record_id = first_response.json()["data"]["meta"]["qa_record_id"]

    feedback_response = client.post(
        "/api/rule-rag/feedback",
        headers=headers,
        json={
            "qa_record_id": record_id,
            "rating": "down",
            "improvement_reason": "回答还不够贴近教师处置场景",
        },
    )
    assert feedback_response.status_code == 200

    second_response = client.post(
        "/api/teacher-rule-assistant/ask",
        headers=headers,
        json={"question": "学生迟到后老师按校规怎么处理？", "student_id": 1},
    )
    assert second_response.status_code == 200
    body = second_response.json()
    assert "history_experience" in body["data"]
    assert body["data"]["history_experience"]["history_feedback_count"] >= 1
