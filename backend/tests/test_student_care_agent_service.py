# -*- coding: utf-8 -*-
"""Tests for the student care multi-agent evaluation service."""

import json
import asyncio
from types import SimpleNamespace

from schemas.student_care_agent import StudentCareAgentReviewLabels, StudentCareAgentReviewUpdate
from services import student_care_agent_service as service


class FakeDb:
    def __init__(self):
        self.added = []
        self.committed = False

    def rollback(self):
        return None

    def add(self, record):
        self.added.append(record)

    def commit(self):
        self.committed = True

    def refresh(self, record):
        record.id = 1


def _profile_response():
    return {
        "code": 200,
        "data": {
            "student": {
                "id": 1,
                "name": "李明",
                "class_id": 1,
                "grade": "高一",
                "tags": "",
            },
            "profile": {
                "emotion_score": 0.1,
                "social_score": 0.2,
                "safety_score": 0.102,
                "safety_linear_score": 0.0,
                "safety_bayes_posterior": 0.34,
                "safety_final_score": 0.102,
                "family_score": 0.0,
                "study_score": 0.3,
                "behavior_score": 0.0,
                "overall_risk": 0.11,
                "risk_level": "low",
                "bayes_results": {
                    "safety": {
                        "enabled": True,
                        "dimension": "safety",
                        "prior": 0.12,
                        "linear_score": 0.0,
                        "posterior": 0.34,
                        "blend_alpha": 0.7,
                        "final_score": 0.102,
                        "evidence_keys": ["assistant_self_report_assault"],
                        "evidence_details": [
                            {
                                "key": "assistant_self_report_assault",
                                "matched": True,
                                "lr": 4.5,
                                "text": "AI 助手对话摘要：学生自述可能遭受他人攻击或受伤",
                            }
                        ],
                    }
                },
            },
            "signals": [
                {
                    "dimension": "behavior",
                    "signal_text": "4月7日迟到，备注包含学生个人情况",
                    "signal_weight": 0.2,
                    "source": "attendance",
                },
                {
                    "dimension": "safety",
                    "signal_text": "课间与同学发生冲突，备注包含具体学生姓名",
                    "signal_weight": 0.4,
                    "source": "behavior_event",
                },
                {
                    "dimension": "family",
                    "signal_text": "家校沟通摘要包含家庭具体情况",
                    "signal_weight": 0.25,
                    "source": "family_contact",
                },
                {
                    "dimension": "emotion",
                    "signal_type": "care_observation_care_talk",
                    "signal_text": "关怀观察中记录到情绪低落线索",
                    "signal_weight": 0.35,
                    "source": "care_observation",
                },
                {
                    "dimension": "study",
                    "signal_text": "最近一次考试平均分下降",
                    "signal_weight": 0.3,
                    "source": "score",
                },
                {
                    "dimension": "safety",
                    "signal_type": "assistant_safety_disclosure",
                    "signal_text": "AI 助手对话摘要：学生自述可能遭受他人攻击或受伤",
                    "signal_weight": 0.75,
                    "source": "assistant_summary",
                }
            ],
            "actions": ["建议继续观察学习压力变化"],
        },
    }


def _dimension_json(dimension, score=0.1, risk_level="low"):
    return json.dumps(
        {
            "dimension": dimension,
            "score": score,
            "risk_level": risk_level,
            "summary": f"{dimension} 维度暂无明显风险",
            "evidence": [],
        },
        ensure_ascii=False,
    )


def _overall_json():
    return json.dumps(
        {
            "overall_score": 0.11,
            "overall_level": "low",
            "suggestions": ["建议继续观察学习压力变化"],
            "dimensions": [
                {
                    "dimension": dimension,
                    "score": 0.1,
                    "risk_level": "low",
                    "summary": f"{dimension} 维度暂无明显风险",
                    "evidence": [],
                }
                for dimension in service.DIMENSION_LABELS.keys()
            ],
        },
        ensure_ascii=False,
    )


def _overall_json_without_behavior():
    payload = json.loads(_overall_json())
    payload["dimensions"] = [
        item for item in payload["dimensions"] if item["dimension"] != "behavior"
    ]
    return json.dumps(payload, ensure_ascii=False)


def _dimension_from_prompt(user_prompt):
    label_to_dimension = {label: key for key, label in service.DIMENSION_LABELS.items()}
    for label, dimension in label_to_dimension.items():
        if label in user_prompt:
            return dimension
    return "emotion"


def test_evaluate_student_care_agent_runs_six_experts_and_records(monkeypatch):
    fake_db = FakeDb()
    calls = []

    monkeypatch.setattr(service.student_care_service, "get_student_care_profile", lambda *args: _profile_response())
    monkeypatch.setattr(
        service,
        "_list_recent_teacher_reviews",
        lambda *args, **kwargs: [
            {
                "record_id": 9,
                "resolution_status": "resolved",
                "teacher_notes": "老师已跟进，学生反馈情况已缓解",
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "_get_latest_confirmed_teacher_feedback",
        lambda *args, **kwargs: {
            "record_id": 11,
            "confirmed_at": "2026-04-09 10:00:00",
            "resolution_status": "in_progress",
            "teacher_notes": "已安排家校沟通并持续观察社交互动。",
            "review_labels": {
                "scene": "social_isolation",
                "is_true_risk": "yes",
                "severity": "medium",
                "confidence_by_teacher": 4,
            },
            "social_summary": "老师确认该生近期在班级互动中较被动，建议继续关注。",
            "social_evidence": ["课间多独处", "同伴互动偏少"],
            "suggestions": ["继续安排同伴支持"],
        },
    )
    monkeypatch.setattr(service, "_resolve_tag_definitions", lambda *args: ([], []))
    monkeypatch.setattr(service, "_fetch_tag_web_context", lambda tags: service.asyncio.sleep(0, result=[]))
    monkeypatch.setattr(
        service,
        "_fetch_student_care_web_context",
        lambda signals: service.asyncio.sleep(
            0,
            result=[
                {
                    "source": "attendance",
                    "dimension": "behavior",
                    "query": "学生迟到缺勤早退 班主任关怀干预建议",
                    "summary": "通用关怀建议",
                    "sources": [],
                }
            ],
        ),
    )
    monkeypatch.setattr(service.settings, "AI_MODEL_NAME_LIGHT", "light-model")
    monkeypatch.setattr(service.settings, "AI_MODEL_NAME_STRONG", "strong-model")
    monkeypatch.setattr(service.student_care_graph_service, "enabled", False)

    async def fake_call(system_prompt, user_prompt, temperature, max_tokens, model_name=None, **kwargs):
        calls.append(model_name)
        if model_name == "light-model":
            return _dimension_json(_dimension_from_prompt(user_prompt))
        return _overall_json()

    monkeypatch.setattr(service.ai_client, "call", fake_call)

    response = asyncio.run(service.evaluate_student_care_agent(fake_db, current_user=object(), student_id=1))

    assert response["code"] == 200
    data = response["data"]
    assert data["fallback"] is False
    assert len(data["expert_outputs"]) == 6
    assert data["model_name"] == "strong-model"
    assert data["result"]["overall_breakdown"]["overall_score"] == 0.1204
    assert data["result"]["dimensions"][0]["score_breakdown"]
    assert data["result"]["dimensions"][0]["score_explanation"]
    assert data["result"]["review_suggestions"]
    assert data["result"]["review_suggestions"][0]["checks"]
    assert data["result"]["explanation_highlights"]
    assert calls.count("light-model") == 6
    assert calls.count("strong-model") == 0
    assert fake_db.committed is True
    assert len(fake_db.added) == 1
    assert fake_db.added[0].model_name == "strong-model"
    assert len(fake_db.added[0].input_snapshot["expert_outputs"]) == 6
    assert fake_db.added[0].input_snapshot["care_fact_context"]["attendance"][0]["text"] == "4月7日迟到，备注包含学生个人情况"
    assert fake_db.added[0].input_snapshot["care_fact_context"]["behavior_events"][0]["text"] == "课间与同学发生冲突，备注包含具体学生姓名"
    assert fake_db.added[0].input_snapshot["care_fact_context"]["care_observations"][0]["text"] == "关怀观察中记录到情绪低落线索"
    assert fake_db.added[0].input_snapshot["care_fact_context"]["family_contacts"][0]["text"] == "家校沟通摘要包含家庭具体情况"
    assert fake_db.added[0].input_snapshot["care_fact_context"]["assistant_summaries"][0]["text"] == "AI 助手对话摘要：学生自述可能遭受他人攻击或受伤"
    assert fake_db.added[0].input_snapshot["care_fact_context"]["teacher_reviews"][0]["resolution_status"] == "resolved"
    assert fake_db.added[0].input_snapshot["teacher_feedback_context"]["record_id"] == 11
    assert fake_db.added[0].input_snapshot["teacher_feedback_context"]["social_summary"] == "老师确认该生近期在班级互动中较被动，建议继续关注。"
    assert fake_db.added[0].input_snapshot["care_fact_context"]["teacher_feedback_context"]["review_labels"]["scene"] == "social_isolation"
    assert fake_db.added[0].input_snapshot["bayes_results"]["safety"]["posterior"] == 0.34
    assert fake_db.added[0].input_snapshot["graph_context"]["enabled"] is False
    assert fake_db.added[0].result_json["review_suggestions"]
    assert fake_db.added[0].result_json["explanation_highlights"]
    assert fake_db.added[0].input_snapshot["web_context"][0]["query"] == "学生迟到缺勤早退 班主任关怀干预建议"


def test_agent_payload_contains_graph_context(monkeypatch):
    fake_db = FakeDb()

    profile_resp = _profile_response()
    profile_resp["data"]["signals"].append(
        {
            "dimension": "safety",
            "signal_type": "graph_conflict_cooccurrence",
            "signal_text": "关系图谱显示该生所在班级近期存在多名学生卷入冲突/欺凌事件",
            "signal_weight": 0.22,
            "source": "graph",
        }
    )
    profile_resp["data"]["profile"]["bayes_results"]["safety"]["evidence_details"].append(
        {
            "key": "graph_conflict_cooccurrence",
            "matched": True,
            "lr": 1.9,
            "text": "关系图谱显示该生所在班级近期存在多名学生卷入冲突/欺凌事件",
        }
    )

    monkeypatch.setattr(service.student_care_service, "get_student_care_profile", lambda *args: profile_resp)
    monkeypatch.setattr(service, "_list_recent_teacher_reviews", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "_resolve_tag_definitions", lambda *args: ([], []))
    monkeypatch.setattr(service, "_fetch_tag_web_context", lambda tags: service.asyncio.sleep(0, result=[]))
    monkeypatch.setattr(service, "_fetch_student_care_web_context", lambda signals: service.asyncio.sleep(0, result=[]))
    monkeypatch.setattr(service.settings, "AI_MODEL_NAME_LIGHT", "light-model")
    monkeypatch.setattr(service.settings, "AI_MODEL_NAME_STRONG", "strong-model")

    async def fake_call(system_prompt, user_prompt, temperature, max_tokens, model_name=None, **kwargs):
        return _dimension_json(_dimension_from_prompt(user_prompt))

    monkeypatch.setattr(service.ai_client, "call", fake_call)

    response = asyncio.run(service.evaluate_student_care_agent(fake_db, current_user=object(), student_id=1))

    assert response["code"] == 200
    graph_context = fake_db.added[0].input_snapshot["graph_context"]
    assert graph_context["graph_signals"][0]["signal_type"] == "graph_conflict_cooccurrence"
    assert graph_context["relationship_summary"]
    assert "graph_conflict_cooccurrence" in graph_context["safety_graph_evidence"]


def test_expert_output_with_structured_evidence_is_normalized(monkeypatch):
    async def fake_call(system_prompt, user_prompt, temperature, max_tokens, model_name=None, **kwargs):
        return json.dumps(
            {
                "dimension": "safety",
                "score": 0.15,
                "risk_level": "low",
                "summary": "safety_final_score=0.1485，care_fact_context.behavior_events=[]，tag_web_context 不构成证据",
                "evidence": [
                    {
                        "type": "bayes_result",
                        "key": "assistant_self_report_assault",
                        "text": "AI 助手对话摘要：学生自述可能遭受他人攻击或受伤",
                    }
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(service.ai_client, "call", fake_call)

    output = asyncio.run(
        service._run_expert(
            dimension="safety",
            prompt_payload={"tag_definitions": []},
            profile={"safety_score": 0.1},
            signals=[],
            light_model="light-model",
        )
    )

    assert output["fallback"] is False
    assert output["result"]["evidence"] == ["AI 助手对话摘要：学生自述可能遭受他人攻击或受伤"]
    assert "care_fact_context" not in output["result"]["summary"]
    assert "Bayes" not in output["result"]["summary"]


def test_expert_output_marks_graph_evidence_as_relation_graph(monkeypatch):
    async def fake_call(system_prompt, user_prompt, temperature, max_tokens, model_name=None, **kwargs):
        return json.dumps(
            {
                "dimension": "social",
                "score": 0.22,
                "risk_level": "low",
                "summary": "结合关系图谱发现需要继续关注班级融入情况",
                "evidence": [
                    {
                        "type": "graph_signal",
                        "source": "graph",
                        "text": "关系图谱中暂未形成稳定同伴连接，建议继续关注学生融入情况",
                    }
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(service.ai_client, "call", fake_call)

    output = asyncio.run(
        service._run_expert(
            dimension="social",
            prompt_payload={"tag_definitions": []},
            profile={"social_score": 0.22},
            signals=[],
            light_model="light-model",
        )
    )

    assert output["fallback"] is False
    assert output["result"]["evidence"] == ["关系图谱：关系图谱中暂未形成稳定同伴连接，建议继续关注学生融入情况"]


def test_expert_output_hides_internal_reasoning_markers(monkeypatch):
    async def fake_call(system_prompt, user_prompt, temperature, max_tokens, model_name=None, **kwargs):
        return json.dumps(
            {
                "dimension": "behavior",
                "score": 0.0,
                "risk_level": "low",
                "summary": "behavior_score字段明确为0，teacher_reviews为空数组，整体风险（overall_risk=0.099）与各维度分项未提示行为相关风险",
                "evidence": [
                    {"key": "tag_mismatch", "source": "tag_definitions"},
                    {"key": "zero_linear_score", "source": "profile.safety_linear_score"},
                    {"key": "tag_social", "source": "student_tag"},
                    {"key": "signal_irrelevance", "source": "signals"},
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(service.ai_client, "call", fake_call)

    output = asyncio.run(
        service._run_expert(
            dimension="behavior",
            prompt_payload={"tag_definitions": []},
            profile={"behavior_score": 0.0},
            signals=[],
            light_model="light-model",
        )
    )

    assert output["fallback"] is False
    assert output["result"]["evidence"] == []
    assert "overall_risk" not in output["result"]["summary"]
    assert "teacher_reviews" not in output["result"]["summary"]
    assert "behavior_score=" not in output["result"]["summary"]
    assert "behavior_score字段" not in output["result"]["summary"]
    assert "student.tags" not in output["result"]["summary"]
    assert "tag_social" not in output["result"]["summary"]
    assert "signal_irrelevance" not in output["result"]["summary"]


def test_expert_validation_error_is_humanized(monkeypatch):
    async def fake_call(system_prompt, user_prompt, temperature, max_tokens, model_name=None, **kwargs):
        return json.dumps(
            {
                "dimension": "family",
                "score": 0.2,
                "risk_level": "low",
                "summary": "暂无明显风险线索",
                "evidence": [{"type": "absence_of_evidence"}],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(service.ai_client, "call", fake_call)
    output = asyncio.run(
        service._run_expert(
            dimension="family",
            prompt_payload={"tag_definitions": []},
            profile={"family_score": 0.2},
            signals=[],
            light_model="light-model",
        )
    )

    assert output["fallback"] is False
    assert output["error_msg"] is None
    assert output["result"]["evidence"] == []


def test_evaluate_student_care_agent_does_not_call_strong_model_for_integration(monkeypatch):
    fake_db = FakeDb()

    monkeypatch.setattr(service.student_care_service, "get_student_care_profile", lambda *args: _profile_response())
    monkeypatch.setattr(service, "_resolve_tag_definitions", lambda *args: ([], []))
    monkeypatch.setattr(service, "_fetch_tag_web_context", lambda tags: service.asyncio.sleep(0, result=[]))
    monkeypatch.setattr(service, "_fetch_student_care_web_context", lambda signals: service.asyncio.sleep(0, result=[]))
    monkeypatch.setattr(service.settings, "AI_MODEL_NAME_LIGHT", "light-model")
    monkeypatch.setattr(service.settings, "AI_MODEL_NAME_STRONG", "strong-model")

    async def fake_call(system_prompt, user_prompt, temperature, max_tokens, model_name=None, **kwargs):
        if model_name == "light-model":
            return _dimension_json(_dimension_from_prompt(user_prompt))
        raise AssertionError("strong model should not be called by deterministic integration")

    monkeypatch.setattr(service.ai_client, "call", fake_call)

    response = asyncio.run(service.evaluate_student_care_agent(fake_db, current_user=object(), student_id=1))

    assert response["code"] == 200
    data = response["data"]
    assert data["fallback"] is False
    assert data["error_msg"] is None
    assert data["raw_text"] is None
    assert len(data["result"]["dimensions"]) == 6
    assert fake_db.added[0].fallback == 0


def test_evaluate_student_care_agent_integrates_complete_dimensions_from_experts(monkeypatch):
    fake_db = FakeDb()

    monkeypatch.setattr(service.student_care_service, "get_student_care_profile", lambda *args: _profile_response())
    monkeypatch.setattr(service, "_resolve_tag_definitions", lambda *args: ([], []))
    monkeypatch.setattr(service, "_fetch_tag_web_context", lambda tags: service.asyncio.sleep(0, result=[]))
    monkeypatch.setattr(service, "_fetch_student_care_web_context", lambda signals: service.asyncio.sleep(0, result=[]))
    monkeypatch.setattr(service.settings, "AI_MODEL_NAME_LIGHT", "light-model")
    monkeypatch.setattr(service.settings, "AI_MODEL_NAME_STRONG", "strong-model")

    async def fake_call(system_prompt, user_prompt, temperature, max_tokens, model_name=None, **kwargs):
        if model_name == "light-model":
            return _dimension_json(_dimension_from_prompt(user_prompt))
        raise AssertionError("strong model should not be called by deterministic integration")

    monkeypatch.setattr(service.ai_client, "call", fake_call)

    response = asyncio.run(service.evaluate_student_care_agent(fake_db, current_user=object(), student_id=1))

    assert response["code"] == 200
    data = response["data"]
    assert data["fallback"] is False
    assert data["error_msg"] is None
    assert len(data["result"]["dimensions"]) == 6


def test_emotion_expert_high_score_without_evidence_uses_conservative_fallback(monkeypatch):
    async def fake_call(system_prompt, user_prompt, temperature, max_tokens, model_name=None, **kwargs):
        return _dimension_json("emotion", score=0.75, risk_level="high")

    monkeypatch.setattr(service.ai_client, "call", fake_call)

    output = asyncio.run(
        service._run_expert(
            dimension="emotion",
            prompt_payload={"tag_definitions": []},
            profile={"emotion_score": 0.45},
            signals=[],
            light_model="light-model",
        )
    )

    assert output["fallback"] is True
    assert output["error_msg"] == "心理维度高分但证据不足"
    assert output["result"]["score"] <= service.EMOTION_LOW_SCORE_MAX
    assert output["result"]["risk_level"] == "low"
    assert "证据不足" in output["result"]["summary"]


def test_expert_dimension_mismatch_uses_fallback(monkeypatch):
    async def fake_call(system_prompt, user_prompt, temperature, max_tokens, model_name=None, **kwargs):
        return _dimension_json("emotion", score=0.1, risk_level="low")

    monkeypatch.setattr(service.ai_client, "call", fake_call)

    output = asyncio.run(
        service._run_expert(
            dimension="social",
            prompt_payload={"tag_definitions": []},
            profile={"social_score": 0.2},
            signals=[
                {
                    "dimension": "social",
                    "signal_text": "同伴互动减少",
                    "source": "assistant_summary",
                }
            ],
            light_model="light-model",
        )
    )

    assert output["fallback"] is True
    assert output["error_msg"] == "专家维度不匹配: 期望 social, 实际 emotion"
    assert output["result"]["dimension"] == "social"


def test_fetch_student_care_web_context_disabled_by_default(monkeypatch):
    queries = []

    async def fake_search_web(query):
        queries.append(query)
        return {"summary": "通用公开资料摘要", "sources": []}

    monkeypatch.setattr(service.settings, "STUDENT_CARE_FACT_WEB_SEARCH", False)
    monkeypatch.setattr(service, "search_web", fake_search_web)

    context = asyncio.run(
        service._fetch_student_care_web_context(
            [
                {
                    "source": "attendance",
                    "dimension": "behavior",
                    "signal_text": "李明 4月7日因家庭情况迟到",
                }
            ]
        )
    )

    assert context == []
    assert queries == []


def test_fetch_student_care_web_context_uses_desensitized_queries_when_enabled(monkeypatch):
    queries = []

    async def fake_search_web(query):
        queries.append(query)
        return {"summary": "通用公开资料摘要", "sources": [{"title": "source", "url": "https://example.com"}]}

    monkeypatch.setattr(service.settings, "STUDENT_CARE_FACT_WEB_SEARCH", True)
    monkeypatch.setattr(service, "search_web", fake_search_web)

    context = asyncio.run(
        service._fetch_student_care_web_context(
            [
                {
                    "source": "attendance",
                    "dimension": "behavior",
                    "signal_text": "李明 4月7日因家庭情况迟到",
                },
                {
                    "source": "family_contact",
                    "dimension": "family",
                    "signal_text": "家长沟通记录包含隐私细节",
                },
            ]
        )
    )

    assert len(context) == 2
    assert "李明" not in " ".join(queries)
    assert "隐私细节" not in " ".join(queries)
    assert "学生迟到缺勤早退" in queries[0]
    assert "家校沟通" in queries[1]


def test_sanitize_reviewed_result_keeps_scores_and_allows_teacher_text_updates():
    original = {
        "overall_score": 0.62,
        "overall_level": "high",
        "suggestions": ["建议先联系家长"],
        "dimensions": [
            {
                "dimension": "emotion",
                "score": 0.7,
                "risk_level": "high",
                "summary": "原始总结",
                "evidence": ["原始证据"],
            }
        ],
        "overall_breakdown": {"overall_score": 0.62, "delta": 0.0},
    }
    reviewed = {
        "overall_score": 0.1,
        "overall_level": "low",
        "suggestions": ["老师建议先观察三天"],
        "dimensions": [
            {
                "dimension": "emotion",
                "score": 0.1,
                "risk_level": "low",
                "summary": "老师确认已完成初步安抚",
                "evidence": ["班主任已谈话", "学生反馈情绪稳定一些"],
            }
        ],
        "overall_breakdown": {"overall_score": 0.1, "delta": 1.0},
    }

    sanitized = service._sanitize_reviewed_result(original, reviewed)

    assert sanitized["overall_score"] == 0.62
    assert sanitized["overall_level"] == "high"
    assert sanitized["overall_breakdown"]["overall_score"] == 0.62
    assert sanitized["dimensions"][0]["score"] == 0.7
    assert sanitized["dimensions"][0]["risk_level"] == "high"
    assert sanitized["dimensions"][0]["summary"] == "老师确认已完成初步安抚"
    assert sanitized["dimensions"][0]["evidence"] == ["班主任已谈话", "学生反馈情绪稳定一些"]
    assert sanitized["suggestions"] == ["老师建议先观察三天"]


def test_serialize_agent_record_includes_review_labels():
    row = SimpleNamespace(
        id=9,
        student_id=1,
        model_name="gpt-test",
        timeout_seconds=25,
        fallback=0,
        error_msg=None,
        input_snapshot={},
        result_json={"overall_level": "attention"},
        review_status="confirmed",
        reviewed_result_json={"dimensions": []},
        review_labels_json={
            "scene": "social_isolation",
            "is_true_risk": "yes",
            "severity": "medium",
            "confidence_by_teacher": 4,
        },
        teacher_notes="已核实并安排跟进",
        resolution_status="in_progress",
        confirmed_by=2,
        confirmed_at=None,
        raw_text=None,
        created_at=None,
    )

    data = service._serialize_agent_record(row)

    assert data["review_labels"]["scene"] == "social_isolation"
    assert data["review_labels"]["is_true_risk"] == "yes"


def test_get_latest_confirmed_teacher_feedback_extracts_social_dimension():
    row = SimpleNamespace(
        id=12,
        student_id=1,
        review_status="confirmed",
        reviewed_result_json={
            "suggestions": ["继续观察"],
            "dimensions": [
                {
                    "dimension": "social",
                    "summary": "老师确认学生近一周同伴互动偏弱。",
                    "evidence": ["课间独处", "互动减少"],
                }
            ],
        },
        result_json={},
        resolution_status="resolved",
        teacher_notes="已做一次谈话",
        review_labels_json={"scene": "social_isolation"},
        confirmed_at=None,
    )

    class QueryStub:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return row

    db = SimpleNamespace(query=lambda model: QueryStub())

    payload = service._get_latest_confirmed_teacher_feedback(db, 1)

    assert payload["record_id"] == 12
    assert payload["social_summary"] == "老师确认学生近一周同伴互动偏弱。"
    assert payload["social_evidence"] == ["课间独处", "互动减少"]
    assert payload["review_labels"]["scene"] == "social_isolation"


def test_confirmed_teacher_feedback_flows_into_next_agent_eval(monkeypatch):
    class AgentRecordQueryStub:
        def __init__(self, db):
            self.db = db

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            if self.db.lookup_record_id is not None:
                for item in self.db.records:
                    if item.id == self.db.lookup_record_id:
                        return item
                return None

            confirmed = [item for item in self.db.records if getattr(item, "review_status", None) == "confirmed"]
            if not confirmed:
                return None
            return sorted(
                confirmed,
                key=lambda item: (
                    getattr(item, "confirmed_at", None) is not None,
                    getattr(item, "confirmed_at", None),
                    getattr(item, "id", 0),
                ),
                reverse=True,
            )[0]

    class StudentQueryStub:
        def __init__(self, student):
            self.student = student

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return self.student

    class FlowDb:
        def __init__(self):
            self.records = []
            self.lookup_record_id = None
            self.student = SimpleNamespace(id=1, class_id=1)
            self.commits = 0

        def rollback(self):
            return None

        def add(self, record):
            if record not in self.records:
                self.records.append(record)

        def commit(self):
            self.commits += 1

        def refresh(self, record):
            if getattr(record, "id", None) is None:
                record.id = len(self.records)

        def query(self, model):
            if model is service.StudentCareAgentRecord:
                return AgentRecordQueryStub(self)
            if model is service.Student:
                return StudentQueryStub(self.student)
            raise AssertionError(f"unexpected query model: {model}")

    flow_db = FlowDb()
    current_user = SimpleNamespace(id=7, role="teacher", name="张老师")

    monkeypatch.setattr(service.student_care_service, "get_student_care_profile", lambda *args: _profile_response())
    monkeypatch.setattr(service.student_care_service, "_ensure_head_teacher_access", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_list_recent_teacher_reviews", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "_resolve_tag_definitions", lambda *args: ([], []))
    monkeypatch.setattr(service, "_fetch_tag_web_context", lambda tags: service.asyncio.sleep(0, result=[]))
    monkeypatch.setattr(service, "_fetch_student_care_web_context", lambda signals: service.asyncio.sleep(0, result=[]))
    monkeypatch.setattr(service.settings, "AI_MODEL_NAME_LIGHT", "light-model")
    monkeypatch.setattr(service.settings, "AI_MODEL_NAME_STRONG", "strong-model")

    async def fake_call(system_prompt, user_prompt, temperature, max_tokens, model_name=None, **kwargs):
        return _dimension_json(_dimension_from_prompt(user_prompt))

    monkeypatch.setattr(service.ai_client, "call", fake_call)

    first_response = asyncio.run(
        service.evaluate_student_care_agent(flow_db, current_user=current_user, student_id=1)
    )

    assert first_response["code"] == 200
    assert len(flow_db.records) == 1
    assert flow_db.records[0].input_snapshot["teacher_feedback_context"] == {}

    review_payload = StudentCareAgentReviewUpdate(
        reviewed_result={
            "suggestions": ["继续安排同伴支持"],
            "dimensions": [
                {
                    "dimension": "social",
                    "summary": "老师确认该生近期在班级互动中较被动，建议继续关注。",
                    "evidence": ["课间多独处", "同伴互动偏少"],
                }
            ],
        },
        teacher_notes="已安排家校沟通并持续观察社交互动。",
        resolution_status="in_progress",
        review_labels=StudentCareAgentReviewLabels(
            scene="social_isolation",
            is_true_risk="yes",
            severity="medium",
            confidence_by_teacher=4,
        ),
    )

    flow_db.lookup_record_id = 1
    review_response = service.confirm_agent_eval_review(
        flow_db,
        current_user=current_user,
        record_id=1,
        payload=review_payload,
    )

    assert review_response["code"] == 200
    assert flow_db.records[0].review_status == "confirmed"

    flow_db.lookup_record_id = None
    second_response = asyncio.run(
        service.evaluate_student_care_agent(flow_db, current_user=current_user, student_id=1)
    )

    assert second_response["code"] == 200
    assert len(flow_db.records) == 2
    teacher_feedback_context = flow_db.records[1].input_snapshot["teacher_feedback_context"]
    assert teacher_feedback_context["record_id"] == 1
    assert teacher_feedback_context["resolution_status"] == "in_progress"
    assert teacher_feedback_context["teacher_notes"] == "已安排家校沟通并持续观察社交互动。"
    assert teacher_feedback_context["review_labels"]["scene"] == "social_isolation"
    assert teacher_feedback_context["social_summary"] == "老师确认该生近期在班级互动中较被动，建议继续关注。"
    assert teacher_feedback_context["social_evidence"] == ["课间多独处", "同伴互动偏少"]
    assert teacher_feedback_context["suggestions"] == ["继续安排同伴支持"]
    assert (
        flow_db.records[1].input_snapshot["care_fact_context"]["teacher_feedback_context"]["social_summary"]
        == "老师确认该生近期在班级互动中较被动，建议继续关注。"
    )


def test_build_agent_evaluation_summary_from_rows_counts_alignment_and_distribution():
    rows = [
        SimpleNamespace(
            review_status="confirmed",
            review_labels_json={
                "scene": "social_isolation",
                "is_true_risk": "yes",
                "severity": "medium",
                "confidence_by_teacher": 4,
            },
            resolution_status="in_progress",
            result_json={"overall_level": "attention"},
            input_snapshot={
                "signals": [
                    {"source": "data_gap", "signal_type": "family_contact_missing", "signal_weight": 0},
                    {"source": "attendance", "signal_weight": 0.15},
                ]
            },
            created_at=service.datetime(2026, 4, 8, 10, 0, 0),
        ),
        SimpleNamespace(
            review_status="confirmed",
            review_labels_json={
                "scene": "social_isolation",
                "is_true_risk": "no",
                "severity": "low",
                "confidence_by_teacher": 2,
            },
            resolution_status="false_alarm",
            result_json={"overall_level": "medium"},
            input_snapshot={
                "signals": [
                    {"source": "care_observation", "signal_weight": -0.2},
                    {"source": "data_gap", "signal_type": "assistant_summary_missing", "signal_weight": 0},
                ]
            },
            created_at=service.datetime(2026, 4, 8, 11, 0, 0),
        ),
        SimpleNamespace(
            review_status="confirmed",
            review_labels_json={
                "scene": "emotion",
                "is_true_risk": "yes",
                "severity": "high",
                "confidence_by_teacher": 5,
            },
            resolution_status="resolved",
            result_json={"overall_level": "low"},
            input_snapshot={"signals": [{"source": "score", "signal_weight": 0.18}]},
            created_at=service.datetime(2026, 4, 9, 9, 0, 0),
        ),
        SimpleNamespace(
            review_status="pending",
            review_labels_json={},
            resolution_status="pending",
            result_json={"overall_level": "low"},
            input_snapshot={"signals": []},
            created_at=service.datetime(2026, 4, 9, 12, 0, 0),
        ),
    ]

    summary = service._build_agent_evaluation_summary_from_rows(rows)

    assert summary["total_records"] == 4
    assert summary["confirmed_reviews"] == 3
    assert summary["reviewed_ratio"] == 0.75
    assert summary["true_risk_count"] == 2
    assert summary["false_alarm_count"] == 1
    assert summary["unresolved_count"] == 1
    assert summary["agreement_rate"] == 0.3333
    assert summary["avg_teacher_confidence"] == 3.67
    assert summary["scene_distribution"]["social_isolation"] == 2
    assert summary["scene_distribution"]["emotion"] == 1
    assert summary["severity_distribution"]["medium"] == 1
    assert summary["severity_distribution"]["high"] == 1
    assert summary["resolution_distribution"]["false_alarm"] == 1
    assert summary["system_vs_teacher"]["system_positive_teacher_yes"] == 1
    assert summary["system_vs_teacher"]["system_positive_teacher_no"] == 1
    assert summary["system_vs_teacher"]["system_low_teacher_yes"] == 1
    assert summary["system_vs_teacher"]["aligned"] == 1
    assert summary["system_vs_teacher"]["misaligned"] == 2
    assert summary["rule_impact"]["data_gap_record_count"] == 2
    assert summary["rule_impact"]["protective_record_count"] == 1
    assert summary["rule_impact"]["attenuated_record_count"] == 2
    assert summary["rule_impact"]["false_alarm_with_data_gap"] == 1
    assert summary["rule_impact"]["false_alarm_with_protective"] == 1
    assert summary["rule_impact"]["teacher_confirmed_with_data_gap"] == 1
    assert summary["rule_impact"]["teacher_confirmed_with_attenuated"] == 2
    assert summary["trend"][0]["date"] == "2026-04-08"
    assert summary["trend"][0]["confirmed_count"] == 2
    assert summary["trend"][0]["true_risk_count"] == 1


def test_build_scene_breakdown_and_recent_review_rows():
    rows = [
        SimpleNamespace(
            id=21,
            student_id=1,
            student_name="李明",
            class_name="高一(1)班",
            review_status="confirmed",
            review_labels_json={
                "scene": "social_isolation",
                "is_true_risk": "yes",
                "severity": "medium",
                "confidence_by_teacher": 4,
            },
            resolution_status="in_progress",
            result_json={"overall_level": "attention"},
            input_snapshot={
                "signals": [
                    {"source": "data_gap", "signal_type": "care_observation_missing", "signal_weight": 0},
                    {"source": "attendance", "signal_weight": 0.12},
                ]
            },
            teacher_notes="已安排同伴支持",
            confirmed_at=service.datetime(2026, 4, 9, 10, 0, 0),
            created_at=service.datetime(2026, 4, 9, 9, 30, 0),
        ),
        SimpleNamespace(
            id=22,
            student_id=2,
            student_name="王芳",
            class_name="高一(1)班",
            review_status="confirmed",
            review_labels_json={
                "scene": "social_isolation",
                "is_true_risk": "no",
                "severity": "low",
                "confidence_by_teacher": 3,
            },
            resolution_status="false_alarm",
            result_json={"overall_level": "medium"},
            input_snapshot={"signals": [{"source": "family_contact", "signal_weight": -0.22}]},
            teacher_notes="更多是临时独处",
            confirmed_at=service.datetime(2026, 4, 8, 12, 0, 0),
            created_at=service.datetime(2026, 4, 8, 11, 30, 0),
        ),
        SimpleNamespace(
            id=23,
            student_id=3,
            student_name="赵强",
            class_name="高一(2)班",
            review_status="confirmed",
            review_labels_json={
                "scene": "emotion",
                "is_true_risk": "yes",
                "severity": "high",
                "confidence_by_teacher": 5,
            },
            resolution_status="resolved",
            result_json={"overall_level": "low"},
            input_snapshot={"signals": [{"source": "score", "signal_weight": 0.18}]},
            teacher_notes="已转介并回访",
            confirmed_at=service.datetime(2026, 4, 7, 8, 0, 0),
            created_at=service.datetime(2026, 4, 7, 7, 30, 0),
        ),
    ]

    scene_breakdown = service._build_scene_breakdown_from_rows(rows)
    recent_reviews = service._build_recent_review_rows(rows)

    assert scene_breakdown[0]["scene"] == "social_isolation"
    assert scene_breakdown[0]["review_count"] == 2
    assert scene_breakdown[0]["true_risk_count"] == 1
    assert scene_breakdown[0]["false_alarm_count"] == 1
    assert scene_breakdown[0]["agreement_rate"] == 0.5
    assert scene_breakdown[0]["avg_teacher_confidence"] == 3.5
    assert scene_breakdown[0]["rule_impact"]["data_gap_record_count"] == 1
    assert scene_breakdown[0]["rule_impact"]["protective_record_count"] == 1
    assert scene_breakdown[0]["rule_impact"]["attenuated_record_count"] == 1
    assert recent_reviews[0]["record_id"] == 21
    assert recent_reviews[0]["student_name"] == "李明"
    assert recent_reviews[0]["scene"] == "social_isolation"
    assert recent_reviews[0]["teacher_notes"] == "已安排同伴支持"
    assert recent_reviews[0]["has_data_gap"] is True
    assert recent_reviews[0]["has_attenuated"] is True
    assert recent_reviews[1]["has_protective"] is True
