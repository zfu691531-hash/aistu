# -*- coding: utf-8 -*-
"""Personal AI assistant service."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.response import error_response, success_response
from database.models.assistant_message import AssistantMessage
from database.models.assistant_session import AssistantSession
from database.models.class_ import Class
from database.models.score import Score
from database.models.student import Student
from database.models.student_assistant_summary import StudentAssistantSummary
from database.models.teacher import Teacher
from database.models.user import User
from schemas.rule_rag import RuleRagAskRequest
from services.ai.base import ai_client
from services.assistant_schema_guard import ensure_assistant_schema
from services.rag import rule_rag_service
from services.student_care_schema_guard import ensure_student_care_schema
from services.user_service import get_student_by_user_id
from services.web_search_service import search_web


STUDENT_SAFETY_DISCLOSURE_KEYWORDS = (
    "被打",
    "打我",
    "打了我",
    "挨打",
    "受伤",
    "流血",
    "欺负",
    "霸凌",
    "威胁",
    "踢我",
    "推我",
    "校园暴力",
    "bully",
    "injured",
    "hurt",
)

NON_SAFETY_PHRASES = ("打游戏", "打卡", "打电话", "打开", "打字", "打扫")


def get_or_create_active_session(db: Session, current_user: User, title: str | None = None) -> dict:
    ensure_assistant_schema()
    db.close()

    session = (
        db.query(AssistantSession)
        .filter(AssistantSession.user_id == current_user.id, AssistantSession.status == "active")
        .order_by(AssistantSession.id.desc())
        .first()
    )
    if not session:
        session = AssistantSession(
            user_id=current_user.id,
            role_snapshot=current_user.role,
            title=title or f"{current_user.name} 的 AI 助手会话",
            status="active",
        )
        db.add(session)
        db.commit()
        db.refresh(session)

    messages = (
        db.query(AssistantMessage)
        .filter(AssistantMessage.session_id == session.id)
        .order_by(AssistantMessage.id.asc())
        .all()
    )
    return success_response(
        data={
            "session_id": session.id,
            "title": session.title,
            "messages": [
                {
                    "id": item.id,
                    "role": item.message_role,
                    "content": item.content,
                    "meta": item.meta_json or {},
                    "created_at": item.created_at,
                }
                for item in messages
            ],
            "greeting": _build_greeting(current_user),
        }
    )


def clear_session_messages(db: Session, current_user: User, session_id: int | None = None) -> dict:
    ensure_assistant_schema()

    session = _ensure_session(db, current_user, session_id)
    if not session:
        return error_response(msg="助手会话不存在")

    db.query(AssistantMessage).filter(AssistantMessage.session_id == session.id).delete(synchronize_session=False)
    db.commit()

    return success_response(
        msg="已清空当前会话记录",
        data={
            "session_id": session.id,
            "title": session.title,
            "messages": [],
            "greeting": _build_greeting(current_user),
        },
    )


async def send_message(db: Session, current_user: User, session_id: int | None, content: str) -> dict:
    ensure_assistant_schema()
    db.close()

    session = _ensure_session(db, current_user, session_id)
    if not session:
        return error_response(msg="助手会话不存在")

    _save_user_message(db, current_user, session.id, content)
    reply_text, meta = await _build_reply(db, current_user, session.id, content)
    assistant_message = _save_assistant_message(db, current_user, session.id, reply_text, meta)

    return success_response(
        data={
            "session_id": session.id,
            "message": {
                "id": assistant_message.id,
                "role": "assistant",
                "content": assistant_message.content,
                "meta": assistant_message.meta_json or {},
                "created_at": assistant_message.created_at,
            },
        }
    )


async def stream_message_events(
    db: Session,
    current_user: User,
    session_id: int | None,
    content: str,
) -> AsyncIterator[str]:
    ensure_assistant_schema()
    db.close()

    session = _ensure_session(db, current_user, session_id)
    if not session:
        yield _format_sse({"type": "error", "message": "助手会话不存在"})
        return

    _save_user_message(db, current_user, session.id, content)
    yield _format_sse({"type": "status", "stage": "analyzing", "message": "正在分析你的问题..."})

    reply_text, meta = await _build_reply(db, current_user, session.id, content)
    assistant_message = _save_assistant_message(db, current_user, session.id, reply_text, meta)

    yield _format_sse(
        {
            "type": "start",
            "session_id": session.id,
            "message_id": assistant_message.id,
            "meta": assistant_message.meta_json or {},
        }
    )
    yield _format_sse(
        {
            "type": "status",
            "stage": "answering",
            "message": _build_status_message(meta),
        }
    )

    for chunk in _chunk_text(reply_text):
        yield _format_sse({"type": "chunk", "content": chunk})

    yield _format_sse({"type": "status", "stage": "complete", "message": "已完成回答"})
    yield _format_sse(
        {
            "type": "done",
            "session_id": session.id,
            "message": {
                "id": assistant_message.id,
                "role": "assistant",
                "content": assistant_message.content,
                "meta": assistant_message.meta_json or {},
                "created_at": str(assistant_message.created_at),
            },
        }
    )


def _save_user_message(db: Session, current_user: User, session_id: int, content: str) -> AssistantMessage:
    user_message = AssistantMessage(
        session_id=session_id,
        user_id=current_user.id,
        message_role="user",
        content=content,
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)
    return user_message


async def _build_reply(db: Session, current_user: User, session_id: int, content: str) -> tuple[str, dict]:
    student_care_reply = _answer_student_safety_disclosure(db, current_user, content)
    if student_care_reply:
        return student_care_reply["reply"], {
            "tool": student_care_reply["tool"],
            "source": student_care_reply.get("source", "builtin"),
            "student_id": student_care_reply.get("student_id"),
            "care_signal": student_care_reply.get("care_signal"),
        }

    tool_result = await _route_tool(db, current_user, content)
    if tool_result:
        reply_text = tool_result["reply"]
        meta = {
            "tool": tool_result["tool"],
            "source": tool_result.get("source", "builtin"),
        }
        if tool_result.get("sources"):
            meta["sources"] = tool_result["sources"]
        return reply_text, meta

    history_rows = (
        db.query(AssistantMessage)
        .filter(AssistantMessage.session_id == session_id)
        .order_by(AssistantMessage.id.desc())
        .limit(8)
        .all()
    )
    history_text = "\n".join(
        f"{'用户' if item.message_role == 'user' else '助手'}：{item.content}"
        for item in reversed(history_rows)
    )
    system_prompt = _build_system_prompt(current_user)
    user_prompt = (
        f"{history_text}\n"
        f"用户当前问题：{content}\n"
        "请结合角色权限、已知业务数据和校园场景，用自然、可靠、简洁的方式回答。"
    )
    reply_text = await ai_client.call(system_prompt, user_prompt, temperature=0.4, max_tokens=1200)
    return reply_text, {"tool": "llm_fallback", "source": "model"}


def _answer_student_safety_disclosure(db: Session, current_user: User, content: str) -> dict | None:
    if current_user.role != "student" or not _is_student_safety_disclosure(content):
        return None

    student = _resolve_current_student(db, current_user)
    if not student:
        return {
            "tool": "student_safety_disclosure",
            "source": "builtin",
            "reply": (
                "我先认真接住这件事：如果你现在还在危险中，或者已经受伤，请立刻离开现场，"
                "马上找身边老师、校医、保安或家长；情况紧急时请直接拨打 110 或 120。"
                "我暂时没有匹配到你的学生档案，所以请同时告诉一位可信任的老师或家长你的姓名、位置和受伤情况。"
            ),
            "care_signal": False,
        }

    _record_student_safety_disclosure(db, student, content)
    return {
        "tool": "student_safety_disclosure",
        "source": "builtin",
        "student_id": student.id,
        "reply": (
            "我先认真接住这件事：如果你现在还在危险中，或者已经受伤，请立刻离开现场，"
            "马上找身边老师、校医、保安或家长；情况紧急时请直接拨打 110 或 120。"
            "我已经把这条求助线索记录到学生关怀研判中，方便老师后续核实和跟进。"
            "你可以继续告诉我：你现在是否安全、在哪里、哪里受伤、对方是谁或大概发生在什么时间。"
        ),
        "care_signal": True,
    }


def _is_student_safety_disclosure(content: str | None) -> bool:
    """Check if content contains student safety disclosure keywords.
    
    Improved logic:
    1. Check for safety keywords first
    2. If non-safety phrases exist, check remaining text for safety keywords
    3. For "打"+"我" pattern, only trigger if clear violence context exists
    """
    if not content:
        return False
    normalized = content.strip().lower()
    
    # Step 1: Check for explicit safety keywords
    has_safety_keyword = any(keyword in normalized for keyword in STUDENT_SAFETY_DISCLOSURE_KEYWORDS)
    
    # Step 2: Check if non-safety phrases mask the safety keywords
    # e.g., "打游戏被打" should still trigger because of "被打"
    if has_safety_keyword:
        # Check if the safety keyword is part of a non-safety phrase
        for phrase in NON_SAFETY_PHRASES:
            if phrase in normalized:
                # Remove the non-safety phrase and check again
                remaining = normalized.replace(phrase, "")
                if any(keyword in remaining for keyword in STUDENT_SAFETY_DISCLOSURE_KEYWORDS):
                    return True
                # If no safety keyword remains after removal, it's a false positive
                return False
        # Safety keyword exists and is not masked
        return True
    
    # Step 3: For "打"+"我" pattern, require clear violence context
    # This is very conservative - only trigger if there's clear violence indicator
    if "打" in normalized and "我" in normalized:
        # Non-violence contexts that should be excluded
        non_violence_patterns = (
            "打球", "打篮球", "打羽毛球", "打乒乓球", "打网球", "打排球",
            "打酱油", "打工", "打的", "打扮", "打扰",
            "打卡", "打电话", "打开", "打字", "打扫", "打游戏",
            "打造", "打算", "打听",
        )
        # If any non-violence pattern exists, don't trigger
        for pattern in non_violence_patterns:
            if pattern in normalized:
                return False
        # Additional check: "打" should have a violence indicator nearby
        # e.g., "打我", "打了我", "被打"
        violence_indicators = ("打我", "打了我", "被打", "挨打")
        for indicator in violence_indicators:
            if indicator in normalized:
                return True
        # "我打" alone is ambiguous, don't trigger (avoid false positive)
        # Only trigger if clear context like "我打他" + violence keywords exists
        # But those cases are already handled by STUDENT_SAFETY_DISCLOSURE_KEYWORDS
    
    return False


def _resolve_current_student(db: Session, current_user: User) -> Student | None:
    return get_student_by_user_id(db, current_user.id)


def _record_student_safety_disclosure(db: Session, student: Student, content: str) -> None:
    ensure_student_care_schema()
    summary_text = f"学生在 AI 助手中自述可能遭受他人攻击或受伤：{content}"
    signals_json = {
        "signals": [
            {
                "dimension": "safety",
                "weight": 0.75,
                "type": "assistant_safety_disclosure",
                "text": summary_text,
            },
            {
                "dimension": "emotion",
                "weight": 0.4,
                "type": "assistant_emotion_disclosure",
                "text": f"AI 助手对话中出现需要关怀跟进的求助表达：{content}",
            },
        ]
    }
    record = StudentAssistantSummary(
        student_id=student.id,
        summary_text=summary_text,
        signals_json=signals_json,
    )
    db.add(record)
    db.commit()


def _save_assistant_message(
    db: Session,
    current_user: User,
    session_id: int,
    reply_text: str,
    meta: dict,
) -> AssistantMessage:
    assistant_message = AssistantMessage(
        session_id=session_id,
        user_id=current_user.id,
        message_role="assistant",
        content=reply_text,
        meta_json=meta,
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    return assistant_message


def _ensure_session(db: Session, current_user: User, session_id: int | None) -> AssistantSession | None:
    if session_id:
        return (
            db.query(AssistantSession)
            .filter(AssistantSession.id == session_id, AssistantSession.user_id == current_user.id)
            .first()
        )

    session = (
        db.query(AssistantSession)
        .filter(AssistantSession.user_id == current_user.id, AssistantSession.status == "active")
        .order_by(AssistantSession.id.desc())
        .first()
    )
    if session:
        return session

    session = AssistantSession(
        user_id=current_user.id,
        role_snapshot=current_user.role,
        title=f"{current_user.name} 的 AI 助手会话",
        status="active",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


async def _route_tool(db: Session, current_user: User, content: str) -> dict | None:
    lower_text = content.lower()
    student_target = _find_matching_student(db, content)
    teacher_target = _find_matching_teacher(db, content)
    class_target = _find_matching_class(db, content)
    grade_target = _find_matching_grade(db, content)
    subject_target = _find_matching_subject(db, content)
    exam_batch_target = _find_matching_exam_batch(db, content)

    if any(keyword in content for keyword in ["我是谁", "我的身份", "我的权限", "我的账号", "我能做什么"]):
        return _answer_profile_question(current_user)
    if _is_datetime_question(content):
        return _answer_datetime_question()
    if any(keyword in content for keyword in ["校规", "规则", "手机", "宿舍", "请假", "迟到", "旷课", "违纪"]):
        return await _answer_rule_question(db, current_user, content)
    if any(keyword in content for keyword in ["成绩", "分数", "考试"]) or (
        (subject_target or exam_batch_target) and any([student_target, class_target, grade_target])
    ):
        return _answer_score_question(db, current_user, content)
    if any(keyword in content for keyword in ["老师", "教师", "教职工"]) or teacher_target:
        return _answer_teacher_question(db, current_user, content)
    if any(keyword in content for keyword in ["学生", "班级", "人数", "未分班", "待分班", "班主任", "构成"]) or student_target:
        return _answer_class_question(db, current_user, content)
    if any(keyword in lower_text for keyword in ["hello", "hi"]) or any(
        keyword in content for keyword in ["你好", "您好", "嗨", "早上好", "下午好", "晚上好"]
    ):
        return {"tool": "greeting", "reply": _build_greeting(current_user)}
    if _should_use_web_search(content):
        return await _answer_web_search_question(content)
    return None


def _answer_score_question(db: Session, current_user: User, content: str | None = None) -> dict:
    class_target = _find_matching_class(db, content)
    grade_target = _find_matching_grade(db, content)
    student_target = _find_matching_student(db, content)
    subject_target = _find_matching_subject(db, content)
    exam_batch_target = _find_matching_exam_batch(db, content)
    return _answer_score_question_with_scope(
        db,
        current_user,
        class_target,
        grade_target,
        student_target,
        subject_target,
        exam_batch_target,
    )


def _answer_score_question_with_scope(
    db: Session,
    current_user: User,
    class_target: Class | None,
    grade_target: str | None,
    student_target: Student | None,
    subject_target: str | None,
    exam_batch_target: str | None,
) -> dict:
    if current_user.role == "student":
        student = db.query(Student).filter(Student.name == current_user.name).first()
        if not student:
            return {
                "tool": "score_lookup",
                "reply": "暂时没有找到你的学生档案，建议联系管理员核对账号信息。",
            }
        reply = _describe_student_score(db, student, subject_target, exam_batch_target)
        return {"tool": "score_lookup", "reply": reply}

    if current_user.role == "teacher":
        teacher = db.query(Teacher).filter(Teacher.name == current_user.name).first()
        class_ids = _parse_class_ids(getattr(teacher, "class_ids", None))
        visible_classes = db.query(Class).filter(Class.id.in_(class_ids)).all() if class_ids else []
        visible_grade_names = {item.grade for item in visible_classes}

        if student_target:
            if student_target.class_id not in class_ids:
                return {
                    "tool": "score_lookup",
                    "reply": f"你当前没有查看学生 {student_target.name} 成绩的权限。",
                }
            reply = _describe_student_score(db, student_target, subject_target, exam_batch_target)
            return {"tool": "score_lookup", "reply": reply}

        if class_target and class_target.id not in class_ids:
            return {
                "tool": "score_scope",
                "reply": f"你当前没有 {class_target.name} 的成绩查看权限，可以继续问我你负责班级内的成绩情况。",
            }

        if class_target and class_target.id in class_ids:
            reply = _describe_score_scope(db, class_name=class_target.name, class_ids=[class_target.id], subject=subject_target, exam_batch=exam_batch_target)
            return {"tool": "score_scope", "reply": reply}

        if grade_target and grade_target in visible_grade_names:
            grade_class_ids = [item.id for item in visible_classes if item.grade == grade_target]
            reply = _describe_score_scope(db, grade_name=grade_target, class_ids=grade_class_ids, subject=subject_target, exam_batch=exam_batch_target, prefix="你权限范围内的")
            return {"tool": "score_scope", "reply": reply}

        score_query = db.query(Score)
        if class_ids:
            score_query = score_query.filter(Score.class_id.in_(class_ids))
        if subject_target:
            score_query = score_query.filter(Score.subject == subject_target)
        if exam_batch_target:
            score_query = score_query.filter(Score.exam_batch == exam_batch_target)
        score_count = score_query.count()
        reply = _format_score_scope_reply("你当前权限范围内", score_count, score_query.with_entities(func.avg(Score.score)).scalar(), subject_target, exam_batch_target)
        return {"tool": "score_scope", "reply": reply}

    if student_target:
        reply = _describe_student_score(db, student_target, subject_target, exam_batch_target)
        return {"tool": "score_lookup", "reply": reply}

    if class_target:
        reply = _describe_score_scope(db, class_name=class_target.name, class_ids=[class_target.id], subject=subject_target, exam_batch=exam_batch_target)
        return {"tool": "score_scope", "reply": reply}

    if grade_target:
        grade_class_ids = [item.id for item in db.query(Class).filter(Class.grade == grade_target).all()]
        reply = _describe_score_scope(db, grade_name=grade_target, class_ids=grade_class_ids, subject=subject_target, exam_batch=exam_batch_target)
        return {"tool": "score_scope", "reply": reply}

    total = db.query(Score).count()
    reply = f"系统当前共有 {total} 条成绩记录。你也可以继续问我某个年级、班级或考试批次的情况。"
    return {"tool": "score_scope", "reply": reply}


def _answer_class_question(db: Session, current_user: User, content: str | None = None) -> dict:
    class_target = _find_matching_class(db, content)
    grade_target = _find_matching_grade(db, content)
    student_target = _find_matching_student(db, content)

    if current_user.role == "student":
        student = db.query(Student).filter(Student.name == current_user.name).first()
        if not student or not student.class_id:
            return {"tool": "class_lookup", "reply": "我暂时没有查到你的班级信息。"}
        class_row = db.query(Class).filter(Class.id == student.class_id).first()
        if not class_row:
            return {"tool": "class_lookup", "reply": "我暂时没有查到你的班级信息。"}
        reply = f"你当前所在班级是 {class_row.name}，年级为 {class_row.grade}。"
        return {"tool": "class_lookup", "reply": reply}

    if current_user.role == "teacher":
        teacher = db.query(Teacher).filter(Teacher.name == current_user.name).first()
        class_ids = _parse_class_ids(getattr(teacher, "class_ids", None))
        classes = db.query(Class).filter(Class.id.in_(class_ids)).all() if class_ids else []
        visible_grade_names = {item.grade for item in classes}
        if not classes:
            return {"tool": "class_scope", "reply": "你当前还没有绑定班级。"}

        if student_target:
            if student_target.class_id not in class_ids:
                return {
                    "tool": "student_detail",
                    "reply": f"你当前没有查看学生 {student_target.name} 的权限。",
                }
            class_row = db.query(Class).filter(Class.id == student_target.class_id).first()
            reply = (
                f"学生 {student_target.name}，学号为 {student_target.student_no}，"
                f"当前在 {class_row.name if class_row else '未分配班级'}，"
                f"年级为 {student_target.grade or '未设置'}。"
            )
            if student_target.tags:
                reply += f" 他的标签有：{student_target.tags}。"
            return {"tool": "student_detail", "reply": reply}

        if class_target and class_target.id not in class_ids:
            return {
                "tool": "class_scope",
                "reply": f"你当前没有 {class_target.name} 的班级查看权限，可以继续问我你负责班级的学生情况。",
            }

        if class_target and class_target.id in class_ids:
            reply = _describe_class_detail(db, class_target, content)
            return {"tool": "class_scope", "reply": reply}

        if grade_target and grade_target in visible_grade_names:
            grade_classes = [item for item in classes if item.grade == grade_target]
            grade_class_ids = [item.id for item in grade_classes]
            student_count = db.query(Student).filter(Student.class_id.in_(grade_class_ids)).count()
            reply = (
                f"你权限范围内的 {grade_target} 共有 {len(grade_classes)} 个班级，"
                f"合计 {student_count} 名学生。"
            )
            return {"tool": "class_scope", "reply": reply}

        student_count = db.query(Student).filter(Student.class_id.in_(class_ids)).count() if class_ids else 0
        reply = "你当前负责的班级有：" + "、".join(item.name for item in classes) + f"。这些班级当前共有 {student_count} 名学生。"
        return {"tool": "class_scope", "reply": reply}

    if student_target:
        class_row = db.query(Class).filter(Class.id == student_target.class_id).first() if student_target.class_id else None
        reply = (
            f"学生 {student_target.name}，学号为 {student_target.student_no}，"
            f"当前在 {class_row.name if class_row else '未分配班级'}，"
            f"年级为 {student_target.grade or '未设置'}。"
        )
        if student_target.tags:
            reply += f" 他的标签有：{student_target.tags}。"
        return {"tool": "student_detail", "reply": reply}

    if class_target:
        reply = _describe_class_detail(db, class_target, content)
        return {"tool": "class_scope", "reply": reply}

    if grade_target:
        grade_classes = db.query(Class).filter(Class.grade == grade_target).all()
        grade_class_ids = [item.id for item in grade_classes]
        student_count = db.query(Student).filter(Student.class_id.in_(grade_class_ids)).count() if grade_class_ids else 0
        unassigned_count = db.query(Student).filter(Student.class_id.is_(None), Student.grade == grade_target).count()
        reply = (
            f"{grade_target} 当前共有 {len(grade_classes)} 个班级、{student_count} 名已分班学生，"
            f"另有 {unassigned_count} 名学生待分班。"
        )
        return {"tool": "class_scope", "reply": reply}

    class_count = db.query(Class).count()
    student_count = db.query(Student).count()
    unassigned_count = db.query(Student).filter(Student.class_id.is_(None)).count()
    reply = f"系统当前共有 {class_count} 个班级、{student_count} 名学生，其中 {unassigned_count} 名学生未分班。"
    return {"tool": "class_scope", "reply": reply}


def _answer_teacher_question(db: Session, current_user: User, content: str | None = None) -> dict:
    teacher_target = _find_matching_teacher(db, content)

    if current_user.role == "teacher":
        teacher = db.query(Teacher).filter(Teacher.name == current_user.name).first()
        if not teacher:
            return {"tool": "teacher_scope", "reply": "我暂时没有查到你的教师档案信息。"}

        if teacher_target and teacher_target.id != teacher.id:
            return {"tool": "teacher_scope", "reply": "我先按你的权限范围回答教师信息，如需查看其他教师信息请联系管理员。"}

        class_ids = _parse_class_ids(getattr(teacher, "class_ids", None))
        class_names = _query_class_names(db, class_ids)
        reply = f"你当前任教学科是 {teacher.subject or '未设置'}，负责 {len(class_ids)} 个班级。"
        if class_names:
            reply += f" 具体包括：{'、'.join(class_names)}。"
        return {"tool": "teacher_scope", "reply": reply}

    if teacher_target:
        class_ids = _parse_class_ids(getattr(teacher_target, "class_ids", None))
        class_names = _query_class_names(db, class_ids)
        reply = (
            f"{teacher_target.name} 当前任教学科是 {teacher_target.subject or '未设置'}，"
            f"负责 {len(class_ids)} 个班级。"
        )
        if class_names:
            reply += f" 具体包括：{'、'.join(class_names)}。"
        return {"tool": "teacher_scope", "reply": reply}

    teacher_count = db.query(Teacher).count()
    reply = f"系统当前共有 {teacher_count} 名教师档案。"
    return {"tool": "teacher_scope", "reply": reply}


def _answer_profile_question(current_user: User) -> dict:
    role_name = {
        "student": "学生",
        "teacher": "教师",
        "admin": "管理员",
    }.get(current_user.role, "用户")
    reply = (
        f"你当前登录身份是 {role_name}，姓名为 {current_user.name}，账号为 {current_user.username}。"
        "如果你愿意，我可以继续帮你查询成绩、班级、教师信息，或者直接回答校规问题。"
    )
    return {"tool": "profile", "reply": reply}


async def _answer_rule_question(db: Session, current_user: User, content: str) -> dict:
    result = await rule_rag_service.ask_rule_rag(
        db,
        current_user,
        RuleRagAskRequest(question=content, chat_history=[]),
    )
    data = result.get("data") or {}
    return {
        "tool": "rule_rag",
        "source": "rag",
        "reply": data.get("answer") or "我暂时没有检索到足够相关的校规内容。",
        "sources": data.get("sources") or [],
    }


async def _answer_web_search_question(content: str) -> dict:
    result = await search_web(content)
    return {
        "tool": "web_search",
        "source": "web",
        "reply": result.get("summary") or "我已经尝试联网查询，但暂时没有拿到足够可靠的结果。",
        "sources": result.get("sources") or [],
    }


def _answer_datetime_question() -> dict:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    weekday_map = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    reply = (
        f"现在是北京时间 {now.year}年{now.month}月{now.day}日，"
        f"{weekday_map[now.weekday()]}，{now:%H:%M}。"
    )
    return {"tool": "datetime", "source": "system", "reply": reply}


def _build_system_prompt(current_user: User) -> str:
    role_name = {
        "student": "学生",
        "teacher": "教师",
        "admin": "管理员",
    }.get(current_user.role, "用户")
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return (
        f"你是校园 AI 教务助手，当前服务对象是{role_name}。"
        f"当前北京时间是 {now.year}年{now.month}月{now.day}日 {now:%H:%M}。\n\n"
        "【系统数据边界】\n"
        "你目前接入的数据：学生档案、成绩信息、班级信息、校规知识库、教师信息。\n"
        "你没有接入的数据：食堂菜单、图书馆藏、宿舍管理、班车时刻、校园活动、设备设施、校园地图、心理咨询、医务室、快递点等。\n\n"
        "【回答规则】\n"
        "1. 先判断：用户问的数据是否在你接入的范围内？\n"
        "2. 如果不在范围内 → 必须拒绝，说明'我目前没有相关数据'，不要编造任何具体信息。\n"
        "3. 如果在范围内 → 基于真实数据回答。\n\n"
        "【正确示例】\n"
        "用户：今天食堂吃什么？\n"
        "回答：我目前没有食堂菜单数据，无法告诉你今天的菜品。建议你查看学校食堂公告或咨询后勤部门。\n\n"
        "【禁止示例】\n"
        "用户：今天食堂吃什么？\n"
        "错误回答：今天食堂有红烧鸡腿、清炒虾仁... ← 这是幻觉！你根本没有这些数据，禁止编造！\n\n"
        "记住：对于你没有的数据，宁可说'我不知道'，也不要编造任何具体内容。"
    )


def _build_greeting(current_user: User) -> str:
    suffix = {
        "student": "同学",
        "teacher": "老师",
        "admin": "",
    }.get(current_user.role, "")
    return f"你好，{current_user.name}{suffix}。我是你的个人 AI 助手，可以帮你处理日常问答和教务问题。"


def _build_status_message(meta: dict) -> str:
    tool = meta.get("tool")
    if tool == "datetime":
        return "正在核对当前日期与时间..."
    if tool == "rule_rag":
        return "正在检索校规知识库并整理答案..."
    if tool == "web_search":
        return "正在联网查询最新公开信息..."
    if tool == "score_lookup" or tool == "score_scope":
        return "正在查询成绩数据并整理结果..."
    if tool == "class_lookup" or tool == "class_scope":
        return "正在查询班级与学生信息..."
    if tool == "teacher_scope":
        return "正在查询教师档案信息..."
    if tool == "profile":
        return "正在整理你的账号与权限信息..."
    if tool == "greeting":
        return "正在准备问候语..."
    if tool == "llm_fallback":
        return "正在结合校园场景整理日常回答..."
    return "正在组织回答内容..."


def _is_datetime_question(content: str) -> bool:
    return any(
        keyword in content
        for keyword in ["今天几号", "今天几日", "今天星期", "今天周几", "现在几点", "现在时间", "当前日期", "今天日期", "今天多少号"]
    )


def _should_use_web_search(content: str) -> bool:
    live_keywords = ["最新", "新闻", "天气", "热搜", "汇率", "股价", "油价", "实时", "联网", "上网", "搜索", "查新闻"]
    return any(keyword in content for keyword in live_keywords)


def _find_matching_class(db: Session, content: str | None) -> Class | None:
    if not content:
        return None
    classes = db.query(Class).all()
    for item in classes:
        if item.name and item.name in content:
            return item
    return None


def _find_matching_grade(db: Session, content: str | None) -> str | None:
    if not content:
        return None
    grades = {item[0] for item in db.query(Class.grade).distinct().all() if item[0]}
    for grade in grades:
        if grade in content:
            return grade
    return None


def _find_matching_teacher(db: Session, content: str | None) -> Teacher | None:
    if not content:
        return None
    teachers = db.query(Teacher).all()
    for item in teachers:
        if item.name and item.name in content:
            return item
    return None


def _find_matching_student(db: Session, content: str | None) -> Student | None:
    if not content:
        return None
    students = db.query(Student).all()
    for item in students:
        if item.name and item.name in content:
            return item
        if item.student_no and item.student_no in content:
            return item
    return None


def _find_matching_subject(db: Session, content: str | None) -> str | None:
    if not content:
        return None
    subjects = {item[0] for item in db.query(Score.subject).distinct().all() if item[0]}
    for subject in subjects:
        if subject in content:
            return subject
    return None


def _find_matching_exam_batch(db: Session, content: str | None) -> str | None:
    if not content:
        return None
    exam_batches = {item[0] for item in db.query(Score.exam_batch).distinct().all() if item[0]}
    for exam_batch in exam_batches:
        if exam_batch in content or content in exam_batch:
            return exam_batch
        short_name = exam_batch.replace("考试", "").replace("年", "").replace("月", "")
        if short_name and short_name in content:
            return exam_batch
    return None


def _describe_student_score(
    db: Session,
    student: Student,
    subject: str | None = None,
    exam_batch: str | None = None,
) -> str:
    score_query = db.query(Score).filter(Score.student_id == student.id)
    if subject:
        score_query = score_query.filter(Score.subject == subject)
    if exam_batch:
        score_query = score_query.filter(Score.exam_batch == exam_batch)
    scores = score_query.all()
    score_count = len(scores)
    avg_score = score_query.with_entities(func.avg(Score.score)).scalar()
    if not scores:
        scope = _format_score_scope_label(subject, exam_batch)
        return f"学生 {student.name} 当前还没有{scope}成绩记录。"

    subject_map: dict[str, list[float]] = {}
    for item in scores:
        subject_map.setdefault(item.subject, []).append(float(item.score))

    subject_summary = []
    for subject, values in list(subject_map.items())[:3]:
        subject_summary.append(f"{subject}均分约为 {round(sum(values) / len(values), 2)}")

    latest_query = db.query(Score).filter(Score.student_id == student.id)
    if subject:
        latest_query = latest_query.filter(Score.subject == subject)
    if exam_batch:
        latest_query = latest_query.filter(Score.exam_batch == exam_batch)
    latest = latest_query.order_by(Score.id.desc()).first()
    scope = _format_score_scope_label(subject, exam_batch)
    reply = (
        f"学生 {student.name} 当前共有 {score_count} 条{scope}成绩记录，"
        f"平均分约为 {round(float(avg_score or 0), 2)}。"
    )
    if subject_summary:
        reply += " 主要科目里，" + "，".join(subject_summary) + "。"
    if latest:
        reply += f" 最近一条成绩是 {latest.exam_batch} 的 {latest.subject}，分数为 {float(latest.score):.2f}。"
    return reply


def _describe_score_scope(
    db: Session,
    class_ids: list[int],
    class_name: str | None = None,
    grade_name: str | None = None,
    subject: str | None = None,
    exam_batch: str | None = None,
    prefix: str | None = None,
) -> str:
    score_query = db.query(Score)
    if class_ids:
        score_query = score_query.filter(Score.class_id.in_(class_ids))
    else:
        score_query = score_query.filter(False)
    if subject:
        score_query = score_query.filter(Score.subject == subject)
    if exam_batch:
        score_query = score_query.filter(Score.exam_batch == exam_batch)

    score_count = score_query.count()
    avg_score = score_query.with_entities(func.avg(Score.score)).scalar()
    scope_name = class_name or grade_name or "当前范围"
    if prefix:
        scope_name = f"{prefix}{scope_name}"
    return _format_score_scope_reply(scope_name, score_count, avg_score, subject, exam_batch)


def _format_score_scope_reply(
    scope_name: str,
    score_count: int,
    avg_score: float | None,
    subject: str | None = None,
    exam_batch: str | None = None,
) -> str:
    scope = _format_score_scope_label(subject, exam_batch)
    return (
        f"{scope_name}共有 {score_count} 条{scope}成绩记录，"
        f"平均分约为 {round(float(avg_score or 0), 2)}。"
    )


def _format_score_scope_label(subject: str | None, exam_batch: str | None) -> str:
    if subject and exam_batch:
        return f"{exam_batch}{subject}的"
    if exam_batch:
        return f"{exam_batch}的"
    if subject:
        return f"{subject}的"
    return ""


def _describe_class_detail(db: Session, class_row: Class, content: str | None) -> str:
    student_query = db.query(Student).filter(Student.class_id == class_row.id)
    students = student_query.all()
    student_count = len(students)
    male_count = sum(1 for item in students if item.gender == "male")
    female_count = sum(1 for item in students if item.gender == "female")
    head_teacher = db.query(Teacher).filter(Teacher.id == class_row.head_teacher_id).first() if class_row.head_teacher_id else None

    reply = (
        f"{class_row.name} 当前有 {student_count} 名学生，"
        f"年级为 {class_row.grade}，班级人数上限为 {class_row.max_count}。"
    )

    if any(keyword in (content or "") for keyword in ["班主任", "老师", "构成", "男女"]):
        reply += (
            f" 班主任为 {head_teacher.name if head_teacher else '暂未设置'}，"
            f"男生 {male_count} 人，女生 {female_count} 人。"
        )

    if any(keyword in (content or "") for keyword in ["学生名单", "学生构成", "有哪些学生"]):
        names = "、".join(item.name for item in students[:8])
        if names:
            suffix = "等学生" if student_count > 8 else ""
            reply += f" 目前班内有：{names}{suffix}。"
    return reply


def _query_class_names(db: Session, class_ids: list[int]) -> list[str]:
    if not class_ids:
        return []
    return [item.name for item in db.query(Class).filter(Class.id.in_(class_ids)).all()]


def _parse_class_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    result: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            result.append(int(item))
    return result


def _chunk_text(text: str, chunk_size: int = 24) -> list[str]:
    if not text:
        return [""]
    return [text[index:index + chunk_size] for index in range(0, len(text), chunk_size)]


def _format_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# Re-declare the high-frequency routing helpers below with clean UTF-8 text.
# The file had historical mojibake in several keyword lists, which caused
# weather/date queries to miss the intended tool branch and fall through to
# the model fallback.
async def _route_tool(db: Session, current_user: User, content: str) -> dict | None:
    lower_text = content.lower()
    student_target = _find_matching_student(db, content)
    teacher_target = _find_matching_teacher(db, content)
    class_target = _find_matching_class(db, content)
    grade_target = _find_matching_grade(db, content)
    subject_target = _find_matching_subject(db, content)
    exam_batch_target = _find_matching_exam_batch(db, content)

    if any(keyword in content for keyword in ["我是谁", "我的身份", "我的权限", "我的账号", "我能做什么"]):
        return _answer_profile_question(current_user)
    if _is_datetime_question(content):
        return _answer_datetime_question()
    if any(keyword in content for keyword in ["校规", "规则", "手机", "宿舍", "请假", "迟到", "违纪"]):
        return await _answer_rule_question(db, current_user, content)

    unavailable_reply = _answer_unavailable_capability(content)
    if unavailable_reply:
        return unavailable_reply

    if any(keyword in content for keyword in ["成绩", "分数", "考试"]) or (
        (subject_target or exam_batch_target) and any([student_target, class_target, grade_target])
    ):
        return _answer_score_question(db, current_user, content)
    if any(keyword in content for keyword in ["老师", "教师", "教职工"]) or teacher_target:
        return _answer_teacher_question(db, current_user, content)
    if any(keyword in content for keyword in ["学生", "班级", "人数", "未分班", "待分班", "班主任", "构成"]) or student_target:
        return _answer_class_question(db, current_user, content)
    if any(keyword in lower_text for keyword in ["hello", "hi"]) or any(
        keyword in content for keyword in ["你好", "您好", "嗨", "早上好", "下午好", "晚上好"]
    ):
        return {"tool": "greeting", "reply": _build_greeting(current_user)}
    if _should_use_web_search(content):
        return await _answer_web_search_question(content)
    return None


async def _answer_web_search_question(content: str) -> dict:
    result = await search_web(content)
    return {
        "tool": "web_search",
        "source": "web",
        "reply": result.get("summary") or "我已经尝试联网查询，但暂时没有拿到足够可靠的公开结果。",
        "sources": result.get("sources") or [],
    }


def _answer_datetime_question() -> dict:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    weekday_map = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    reply = (
        f"现在是北京时间 {now.year}年{now.month}月{now.day}日，"
        f"{weekday_map[now.weekday()]}，{now:%H:%M}。"
    )
    return {"tool": "datetime", "source": "system", "reply": reply}


def _build_system_prompt(current_user: User) -> str:
    role_name = {
        "student": "学生",
        "teacher": "教师",
        "admin": "管理员",
    }.get(current_user.role, "用户")
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return (
        f"你是校园 AI 教务助手，当前服务对象是{role_name}。"
        f"当前北京时间是 {now.year}年{now.month}月{now.day}日 {now:%H:%M}。\n\n"
        "【系统数据边界】\n"
        "你目前接入的数据：学生档案、成绩信息、班级信息、校规知识库、教师信息。\n"
        "你没有接入的数据：食堂菜单、图书馆藏、宿舍管理、班车时刻、校园活动、设备设施、校园地图、心理咨询、医务室、快递点等。\n\n"
        "【回答规则】\n"
        "1. 先判断：用户问的数据是否在你接入的范围内？\n"
        "2. 如果不在范围内 → 必须拒绝，说明'我目前没有相关数据'，不要编造任何具体信息。\n"
        "3. 如果在范围内 → 基于真实数据回答。\n\n"
        "【正确示例】\n"
        "用户：今天食堂吃什么？\n"
        "回答：我目前没有食堂菜单数据，无法告诉你今天的菜品。建议你查看学校食堂公告或咨询后勤部门。\n\n"
        "【禁止示例】\n"
        "用户：今天食堂吃什么？\n"
        "错误回答：今天食堂有红烧鸡腿、清炒虾仁... ← 这是幻觉！你根本没有这些数据，禁止编造！\n\n"
        "记住：对于你没有的数据，宁可说'我不知道'，也不要编造任何具体内容。"
    )


def _build_greeting(current_user: User) -> str:
    suffix = {
        "student": "同学",
        "teacher": "老师",
        "admin": "",
    }.get(current_user.role, "")
    return f"你好，{current_user.name}{suffix}。我是你的个人 AI 助手，可以帮你处理日常问答和教务问题。"


def _build_status_message(meta: dict) -> str:
    tool = meta.get("tool")
    if tool == "datetime":
        return "正在核对当前日期与时间..."
    if tool == "rule_rag":
        return "正在检索校规知识库并整理答案..."
    if tool == "web_search":
        return "正在联网查询最新公开信息..."
    if tool in {"score_lookup", "score_scope"}:
        return "正在查询成绩数据并整理结果..."
    if tool in {"class_lookup", "class_scope"}:
        return "正在查询班级与学生信息..."
    if tool == "teacher_scope":
        return "正在查询教师档案信息..."
    if tool == "profile":
        return "正在整理你的账号与权限信息..."
    if tool == "greeting":
        return "正在准备问候语..."
    if tool == "capability_guard":
        return "正在核对当前已接入的系统能力..."
    if tool == "llm_fallback":
        return "正在结合校园场景整理日常回答..."
    return "正在组织回答内容..."


def _is_datetime_question(content: str) -> bool:
    return any(
        keyword in content
        for keyword in ["今天几号", "今天几日", "今天星期几", "今天周几", "现在几点", "现在时间", "当前日期", "今天日期", "今天多少号"]
    )


def _should_use_web_search(content: str) -> bool:
    live_keywords = ["最新", "新闻", "天气", "热搜", "汇率", "股价", "油价", "实时", "联网", "上网", "搜索", "查新闻"]
    return any(keyword in content for keyword in live_keywords)


def _answer_unavailable_capability(content: str) -> dict | None:
    unsupported_keywords = [
        "课表",
        "课程表",
        "上课安排",
        "教室安排",
        "空教室",
        "一卡通",
        "饭卡",
        "图书馆座位",
        "借书记录",
    ]
    if not any(keyword in content for keyword in unsupported_keywords):
        return None

    return {
        "tool": "capability_guard",
        "source": "builtin",
        "reply": (
            "我目前还没有接入课表、一卡通、图书馆座位这类校园业务系统，"
            "所以不能可靠地帮你查询这部分实时信息。"
            "如果你愿意，我可以先帮你处理已接入的教务、校规、成绩和班级相关问题。"
        ),
    }
