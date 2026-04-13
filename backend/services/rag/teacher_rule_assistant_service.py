# -*- coding: utf-8 -*-
"""Teacher-side enhanced rule assistant service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.response import success_response
from database.models.class_ import Class
from database.models.student import Student
from database.models.user import User
from schemas.rule_rag import RuleRagAskRequest
from schemas.teacher_rule_assistant import TeacherRuleAssistantAskRequest
from services.rag import rule_rag_service
from services.rag import teacher_rule_audit
from services.rag import teacher_rule_tools
from services.rag.rule_intent import infer_query_intent


async def ask_teacher_rule_assistant(
    db: Session,
    current_user: User,
    request: TeacherRuleAssistantAskRequest,
) -> dict:
    gatekeeper = _run_gatekeeper(request)
    if not gatekeeper["question_clear"]:
        clarification_result = {
            "answer": gatekeeper["clarification_question"],
            "decision_summary": {
                "conclusion": "当前信息不足，暂不建议直接给出处置结论。",
                "primary_action": "请先补充学生、事件类型或发生时间。",
                "parent_contact": "暂不判断",
                "care_followup": "暂不判断",
            },
            "policy_basis": [],
            "student_context_summary": {
                "student_id": request.student_id,
                "student_name": None,
                "grade": None,
                "class_name": None,
                "behavior_summary": "门卫节点判断当前信息不足，暂不加载行为事实摘要。",
                "attendance_summary": "门卫节点判断当前信息不足，暂不加载考勤事实摘要。",
                "care_hint": "请补充学生、事件或时间范围后，再生成教师版建议。",
            },
            "recommended_actions": [
                "先补充学生对象、事件类型或发生时间。",
                "补充后再结合校规和学生上下文进行分析。",
            ],
            "parent_contact_advice": {"suggested": False, "reason": "当前信息不足，暂不生成家校联系建议。"},
            "care_followup_advice": {"suggested": False, "reason": "当前信息不足，暂不生成关怀跟进建议。"},
            "needs_manual_confirmation": [
                "请先明确具体学生、事件类型或时间范围。",
                "AI 结果仅作教师处置辅助，不替代学校正式认定和处分流程。",
            ],
            "sources": [],
            "history_experience": {
                "history_summary": "当前为澄清阶段，暂不检索历史经验。",
                "history_risk_hint": False,
                "history_feedback_count": 0,
            },
            "meta": {
                "mode": request.mode,
                "qa_record_id": None,
                "trace_id": None,
                "planner": ["门卫节点要求先澄清问题，再进入检索与分析。"],
                "gatekeeper": gatekeeper,
            },
        }
        audited_result = teacher_rule_audit.audit_teacher_rule_result(clarification_result)
        return success_response(data=audited_result)

    student_context_summary = _build_student_context_summary(db, current_user, request.student_id)
    if student_context_summary.get("access_error"):
        return student_context_summary["access_error"]

    planner = _build_plan_summary(request)
    history_experience = teacher_rule_tools.build_history_experience_summary(db, request.question)
    rag_result = await rule_rag_service.ask_rule_rag(
        db=db,
        current_user=current_user,
        request=RuleRagAskRequest(question=request.question, chat_history=request.chat_history),
    )
    rag_data = rag_result.get("data") or {}
    if request.event_type:
        student_context_summary["event_type"] = request.event_type

    policy_basis = _build_policy_basis(rag_data.get("sources") or [])
    parent_contact_advice = _build_parent_contact_advice(student_context_summary)
    care_followup_advice = _build_care_followup_advice(student_context_summary)
    recommended_actions = _build_recommended_actions(
        student_context_summary,
        rag_data.get("sources") or [],
        planner,
        history_experience,
    )

    result = {
        "answer": rag_data.get("answer") or "暂未生成教师版校规建议。",
        "decision_summary": _build_decision_summary(
            request=request,
            policy_basis=policy_basis,
            student_context_summary=student_context_summary,
            parent_contact_advice=parent_contact_advice,
            care_followup_advice=care_followup_advice,
            recommended_actions=recommended_actions,
        ),
        "policy_basis": policy_basis,
        "student_context_summary": student_context_summary,
        "recommended_actions": recommended_actions,
        "parent_contact_advice": parent_contact_advice,
        "care_followup_advice": care_followup_advice,
        "needs_manual_confirmation": _build_manual_confirmation_items(
            request,
            student_context_summary,
            history_experience,
        ),
        "sources": rag_data.get("sources") or [],
        "history_experience": history_experience,
        "meta": {
            "mode": request.mode,
            "qa_record_id": rag_data.get("qa_record_id"),
            "trace_id": rag_data.get("trace_id"),
            "planner": planner,
            "gatekeeper": gatekeeper,
        },
    }
    audited_result = teacher_rule_audit.audit_teacher_rule_result(result)
    return success_response(data=audited_result)


def _run_gatekeeper(request: TeacherRuleAssistantAskRequest) -> dict:
    question = (request.question or "").strip()
    event_type = (request.event_type or "").strip()
    lowered = question.lower()

    vague_markers = ["这个学生", "这名学生", "这次", "这种情况", "该怎么处理", "怎么办", "合适吗", "可以吗"]
    has_vague_marker = any(marker in question for marker in vague_markers)
    mentions_rule_topic = any(
        keyword in lowered
        for keyword in ["校规", "迟到", "违纪", "手机", "请假", "旷课", "纪律", "课堂", "宿舍", "打架", "家长"]
    )

    if has_vague_marker and not request.student_id and not event_type:
        return {
            "question_clear": False,
            "reason": "missing_student_or_event",
            "clarification_question": "当前问题更像个案处置，请补充学生对象或事件类型，例如学生 ID、迟到、手机、课堂纪律等信息。",
        }
    if len(question) < 8 and not mentions_rule_topic:
        return {
            "question_clear": False,
            "reason": "question_too_short",
            "clarification_question": "当前问题过短，请补充更具体的校规场景，例如“学生迟到两次后老师怎么按校规处理”。",
        }
    return {"question_clear": True, "reason": "sufficient", "clarification_question": ""}


def _build_student_context_summary(db: Session, current_user: User, student_id: int | None) -> dict:
    summary = {
        "student_id": student_id,
        "student_name": None,
        "grade": None,
        "class_name": None,
        "behavior_summary": "未指定学生，暂不加载行为事实摘要。",
        "attendance_summary": "未指定学生，暂不加载考勤事实摘要。",
        "care_hint": "未指定学生，暂不加载学生关怀摘要。",
    }
    if not student_id:
        return summary

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        summary["care_hint"] = "未查询到对应学生，请先确认学生身份信息。"
        return summary

    access_error = teacher_rule_tools.ensure_teacher_student_access(db, current_user, student)
    if access_error:
        return {"access_error": access_error}

    summary["student_name"] = student.name
    summary["grade"] = student.grade
    if student.class_id:
        class_row = db.query(Class).filter(Class.id == student.class_id).first()
        if class_row:
            summary["class_name"] = class_row.name

    fact_summary = teacher_rule_tools.build_student_fact_summary(db, student.id)
    care_summary = teacher_rule_tools.build_care_context_summary(db, student.id)
    family_summary = teacher_rule_tools.build_family_contact_summary(db, student.id)
    summary["behavior_summary"] = fact_summary["behavior_summary"]
    summary["attendance_summary"] = fact_summary["attendance_summary"]
    summary["care_hint"] = care_summary["care_hint"]
    summary["_care_followup_advice"] = care_summary["care_followup_advice"]
    summary["_parent_contact_advice"] = family_summary["parent_contact_advice"]
    return summary


def _build_policy_basis(sources: list[dict]) -> list[dict]:
    items = []
    seen_rule_ids: set[int] = set()
    for item in sources:
        rule_id = item.get("rule_id")
        if not rule_id or rule_id in seen_rule_ids:
            continue
        seen_rule_ids.add(rule_id)
        title = _extract_rule_title(item.get("chunk_text") or "", rule_id)
        excerpt = _extract_excerpt(item.get("chunk_text") or "")
        items.append({"rule_id": rule_id, "title": title, "excerpt": excerpt})
    return items


def _extract_rule_title(chunk_text: str, rule_id: int) -> str:
    for line in chunk_text.splitlines():
        raw = line.strip()
        if raw.startswith("标题:"):
            return raw.split(":", 1)[1].strip()
    first_non_empty = next((line.strip() for line in chunk_text.splitlines() if line.strip()), "")
    return first_non_empty or f"校规 #{rule_id}"


def _extract_excerpt(chunk_text: str) -> str:
    lines = []
    for line in chunk_text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        if raw.startswith(("分类:", "标题:", "主题:", "行为类型:", "关键词:", "家校联系:", "关怀跟进:")):
            continue
        lines.append(raw)
    return " ".join(lines)[:140]


def _build_recommended_actions(
    student_context_summary: dict,
    sources: list[dict],
    planner: list[str],
    history_experience: dict,
) -> list[str]:
    actions = ["先核对事实经过，再结合命中的校规条款做出处理。"]
    if sources:
        actions.append("向学生说明对应校规依据，并记录本次沟通结论。")
    else:
        actions.append("当前命中依据不足，建议补充更具体的制度关键词后再次检索。")
    if student_context_summary.get("student_id"):
        actions.append("已结合学生近期行为和考勤记录，请老师核对是否存在特殊说明或例外情况。")
    if any("关怀" in item or "家校" in item for item in planner):
        actions.append("除制度处理外，建议同步关注沟通方式、家校口径和后续支持安排。")
    if history_experience.get("history_risk_hint"):
        actions.append("历史相近问题出现过低满意反馈，关键结论建议再做一次人工复核。")
    return actions[:4]


def _build_parent_contact_advice(student_context_summary: dict) -> dict:
    if student_context_summary.get("_parent_contact_advice"):
        return student_context_summary["_parent_contact_advice"]
    if student_context_summary.get("student_id"):
        return {
            "suggested": False,
            "reason": "未查询到可用家校联系摘要，建议老师结合事件重复性和班级沟通情况人工判断。",
        }
    return {"suggested": False, "reason": "当前未指定学生对象，暂不生成家校联系建议。"}


def _build_care_followup_advice(student_context_summary: dict) -> dict:
    if student_context_summary.get("_care_followup_advice"):
        return student_context_summary["_care_followup_advice"]
    if student_context_summary.get("student_id"):
        return {"suggested": False, "reason": "未查询到可用关怀摘要，建议老师先按校规处置并持续观察。"}
    return {"suggested": False, "reason": "当前未指定学生对象，暂不生成关怀跟进建议。"}


def _build_manual_confirmation_items(
    request: TeacherRuleAssistantAskRequest,
    student_context_summary: dict,
    history_experience: dict,
) -> list[str]:
    items = ["AI 结果仅作教师处置辅助，不替代学校正式认定和处分流程。"]
    if not request.student_id:
        items.append("若问题涉及具体个案，请补充学生信息后再判断。")
    if request.event_type:
        items.append(f"请进一步确认事件类型“{request.event_type}”与实际记录是否一致。")
    if student_context_summary.get("student_id") and not student_context_summary.get("student_name"):
        items.append("未找到对应学生档案，请核对学生 ID。")
    if history_experience.get("history_risk_hint"):
        items.append("历史相近问题存在低满意反馈，关键结论建议老师再做一次人工确认。")
    return items


def _build_plan_summary(request: TeacherRuleAssistantAskRequest) -> list[str]:
    question = (request.question or "").lower()
    intent = infer_query_intent(request.question or "")
    plan = ["检索相关校规条款"]
    if request.student_id:
        plan.append("带入学生基础信息与事实摘要")
    if request.event_type:
        plan.append("结合事件类型校验规则适用场景")
    if any(keyword in question for keyword in ["沟通", "家长", "联系家长", "跟进", "关怀", "支持"]):
        plan.append("补充关怀摘要与家校协同建议")
    elif request.student_id:
        plan.append("优先输出规则加事实匹配型建议")
    else:
        plan.append("优先输出条文检索型建议")
    if "attendance" in intent.get("themes", []):
        plan.append("提高考勤与请假类规则权重")
    if "phone" in intent.get("themes", []):
        plan.append("提高手机与课堂纪律类规则权重")
    plan.append("综合生成教师侧结构化回答")
    return plan


def _build_decision_summary(
    *,
    request: TeacherRuleAssistantAskRequest,
    policy_basis: list[dict],
    student_context_summary: dict,
    parent_contact_advice: dict,
    care_followup_advice: dict,
    recommended_actions: list[str],
) -> dict:
    student_name = student_context_summary.get("student_name") or "该学生"
    if not policy_basis:
        conclusion = "当前未命中足够直接的制度依据，建议补充更明确的校规条款或完善规则库后再判断。"
    else:
        top_title = policy_basis[0]["title"]
        conclusion = f"{student_name} 当前问题建议优先按《{top_title}》相关要求处理。"
    primary_action = recommended_actions[0] if recommended_actions else "先核对事实，再决定后续处理。"
    parent_text = "建议联系家长" if parent_contact_advice.get("suggested") else "暂不优先联系家长"
    care_text = "建议继续关怀跟进" if care_followup_advice.get("suggested") else "暂不优先转入关怀跟进"
    if request.event_type:
        conclusion = f"{conclusion} 当前事件类型为 {request.event_type}。"
    return {
        "conclusion": conclusion,
        "primary_action": primary_action,
        "parent_contact": parent_text,
        "care_followup": care_text,
    }
