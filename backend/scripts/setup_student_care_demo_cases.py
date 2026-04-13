# -*- coding: utf-8 -*-
"""Set up reproducible student-care demo cases for teacher 王建国."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from database.connection import SessionLocal
from database.models.class_ import Class
from database.models.score import Score
from database.models.student import Student
from database.models.student_assistant_summary import StudentAssistantSummary
from database.models.student_attendance import StudentAttendance
from database.models.student_behavior_event import StudentBehaviorEvent
from database.models.student_care_agent_record import StudentCareAgentRecord
from database.models.student_care_graph_relation import StudentCareGraphRelation
from database.models.student_care_observation import StudentCareObservation
from database.models.student_care_profile import StudentCareProfile
from database.models.student_care_signal import StudentCareSignal
from database.models.student_family_contact import StudentFamilyContact
from database.models.user import User
from schemas.student_care_agent import StudentCareAgentReviewLabels, StudentCareAgentReviewUpdate
from services import student_care_agent_service, student_care_service
from services.student_care_graph_service import student_care_graph_service

DEMO_BATCHES = ("2025秋期中", "2026寒假后月考", "2026春季月考", "2026四月周测")
TODAY = date(2026, 4, 10)
NOW = datetime(2026, 4, 10, 15, 30, 0)


@dataclass
class DemoStudentSpec:
    student_no: str
    name: str
    gender: str
    age: int
    grade: str
    contact: str
    specialty: str
    tags: str | None
    story: str
    scores: list[dict[str, Any]]
    attendance: list[dict[str, Any]]
    behavior: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    family_contacts: list[dict[str, Any]]
    assistant_summaries: list[dict[str, Any]]
    graph_relations: list[dict[str, Any]]
    review: dict[str, Any]


def ensure_student(db, class_id: int, spec: DemoStudentSpec) -> Student:
    student = db.query(Student).filter(Student.student_no == spec.student_no).first()
    if not student:
        student = Student(
            student_no=spec.student_no,
            name=spec.name,
            gender=spec.gender,
            age=spec.age,
            grade=spec.grade,
            class_id=class_id,
            contact=spec.contact,
            specialty=spec.specialty,
            tags=spec.tags,
        )
        db.add(student)
    else:
        student.name = spec.name
        student.gender = spec.gender
        student.age = spec.age
        student.grade = spec.grade
        student.class_id = class_id
        student.contact = spec.contact
        student.specialty = spec.specialty
        student.tags = spec.tags
    db.flush()
    return student


def reset_student_related_data(db, student_id: int) -> None:
    db.query(StudentCareAgentRecord).filter(StudentCareAgentRecord.student_id == student_id).delete(synchronize_session=False)
    db.query(StudentCareSignal).filter(StudentCareSignal.student_id == student_id).delete(synchronize_session=False)
    db.query(StudentCareProfile).filter(StudentCareProfile.student_id == student_id).delete(synchronize_session=False)
    db.query(StudentCareGraphRelation).filter(StudentCareGraphRelation.student_id == student_id).delete(synchronize_session=False)
    db.query(StudentAssistantSummary).filter(StudentAssistantSummary.student_id == student_id).delete(synchronize_session=False)
    db.query(StudentFamilyContact).filter(StudentFamilyContact.student_id == student_id).delete(synchronize_session=False)
    db.query(StudentCareObservation).filter(StudentCareObservation.student_id == student_id).delete(synchronize_session=False)
    db.query(StudentBehaviorEvent).filter(StudentBehaviorEvent.student_id == student_id).delete(synchronize_session=False)
    db.query(StudentAttendance).filter(StudentAttendance.student_id == student_id).delete(synchronize_session=False)
    db.query(Score).filter(Score.student_id == student_id).delete(synchronize_session=False)
    db.flush()


def add_scores(db, student: Student, score_rows: list[dict[str, Any]]) -> None:
    for row in score_rows:
        for subject, value in row["subjects"].items():
            db.add(
                Score(
                    student_id=student.id,
                    class_id=student.class_id,
                    exam_batch=row["exam_batch"],
                    subject=subject,
                    score=Decimal(str(value)),
                    created_at=row["created_at"],
                    updated_at=row["created_at"],
                )
            )
    db.flush()


def add_attendance(db, student: Student, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.add(
            StudentAttendance(
                student_id=student.id,
                date=row["date"],
                status=row["status"],
                remark=row.get("remark"),
                created_at=row["created_at"],
                updated_at=row["created_at"],
            )
        )
    db.flush()


def add_behavior_events(db, student: Student, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.add(
            StudentBehaviorEvent(
                student_id=student.id,
                event_type=row["event_type"],
                event_level=row["event_level"],
                event_desc=row["event_desc"],
                occurred_at=row["occurred_at"],
                created_at=row["created_at"],
                updated_at=row["created_at"],
            )
        )
    db.flush()


def add_observations(db, student: Student, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.add(
            StudentCareObservation(
                student_id=student.id,
                dimension=row["dimension"],
                observation_type=row["observation_type"],
                observation_level=row["observation_level"],
                observed_at=row["observed_at"],
                summary=row["summary"],
                created_at=row["created_at"],
                updated_at=row["created_at"],
            )
        )
    db.flush()


def add_family_contacts(db, student: Student, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.add(
            StudentFamilyContact(
                student_id=student.id,
                contact_type=row["contact_type"],
                summary=row["summary"],
                created_at=row["created_at"],
                updated_at=row["created_at"],
            )
        )
    db.flush()


def add_assistant_summaries(db, student: Student, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.add(
            StudentAssistantSummary(
                student_id=student.id,
                summary_text=row["summary_text"],
                signals_json=row["signals_json"],
                created_at=row["created_at"],
                updated_at=row["created_at"],
            )
        )
    db.flush()


def add_graph_relations(db, student: Student, rows: list[dict[str, Any]], created_by: int) -> None:
    for row in rows:
        db.add(
            StudentCareGraphRelation(
                student_id=student.id,
                target_type=row["target_type"],
                target_student_id=row.get("target_student_id"),
                relation_type=row["relation_type"],
                dimension=row["dimension"],
                relation_level=row["relation_level"],
                summary=row["summary"],
                event_title=row.get("event_title"),
                occurred_at=row.get("occurred_at"),
                created_by=created_by,
                created_at=row["created_at"],
                updated_at=row["created_at"],
            )
        )
    db.flush()


def duplicate_agent_record(
    db,
    source: StudentCareAgentRecord,
    created_at: datetime,
    *,
    review_status: str,
    teacher_notes: str | None,
    resolution_status: str | None,
    confirmed_by: int | None,
    confirmed_at: datetime | None,
    review_labels_json: dict[str, Any] | None,
) -> None:
    db.add(
        StudentCareAgentRecord(
            student_id=source.student_id,
            model_name=source.model_name,
            timeout_seconds=source.timeout_seconds,
            fallback=source.fallback,
            error_msg=source.error_msg,
            input_snapshot=source.input_snapshot,
            result_json=source.result_json,
            raw_text=source.raw_text,
            review_status=review_status,
            reviewed_result_json=source.result_json if review_status == "confirmed" else None,
            review_labels_json=review_labels_json,
            teacher_notes=teacher_notes,
            resolution_status=resolution_status,
            confirmed_by=confirmed_by,
            confirmed_at=confirmed_at,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    db.flush()


def build_demo_specs(target_lookup: dict[str, int]) -> list[DemoStudentSpec]:
    return [
        DemoStudentSpec(
            student_no="202400101",
            name="李明",
            gender="male",
            age=15,
            grade="高一",
            contact="13800001001",
            specialty="足球",
            tags="家庭困难",
            story="突发恶性事件型",
            scores=[
                {"exam_batch": DEMO_BATCHES[0], "subjects": {"语文": 78, "数学": 76, "英语": 74}, "created_at": datetime(2025, 11, 18, 9, 0)},
                {"exam_batch": DEMO_BATCHES[1], "subjects": {"语文": 75, "数学": 72, "英语": 70}, "created_at": datetime(2026, 2, 28, 9, 0)},
                {"exam_batch": DEMO_BATCHES[2], "subjects": {"语文": 72, "数学": 69, "英语": 67}, "created_at": datetime(2026, 3, 26, 9, 0)},
                {"exam_batch": DEMO_BATCHES[3], "subjects": {"语文": 70, "数学": 66, "英语": 64}, "created_at": datetime(2026, 4, 8, 9, 0)},
            ],
            attendance=[
                {"date": date(2026, 4, 1), "status": "late", "remark": "进校后情绪低落，称昨晚不敢独自回家。", "created_at": datetime(2026, 4, 1, 8, 10)},
                {"date": date(2026, 4, 2), "status": "late", "remark": "班主任观察到神情紧张，反复确认放学安排。", "created_at": datetime(2026, 4, 2, 8, 8)},
                {"date": date(2026, 4, 4), "status": "early_leave", "remark": "午后因家长到校陪同提前离校。", "created_at": datetime(2026, 4, 4, 15, 10)},
            ],
            behavior=[
                {
                    "event_type": "bullying",
                    "event_level": "high",
                    "event_desc": "晚自习后在校门外被两名高年级学生围堵，学生自述被推搡并被索要零花钱。",
                    "occurred_at": datetime(2026, 4, 1, 20, 40),
                    "created_at": datetime(2026, 4, 1, 21, 10),
                },
                {
                    "event_type": "threat",
                    "event_level": "high",
                    "event_desc": "班主任谈话中确认学生担心再次被堵，提到对方扬言“放学别一个人走”。",
                    "occurred_at": datetime(2026, 4, 2, 11, 0),
                    "created_at": datetime(2026, 4, 2, 11, 30),
                },
            ],
            observations=[
                {
                    "dimension": "emotion",
                    "observation_type": "care_talk",
                    "observation_level": "high",
                    "observed_at": datetime(2026, 4, 2, 10, 20),
                    "summary": "谈话中多次提到害怕再次被堵，声音发抖，不愿独自去操场，明显紧张。",
                    "created_at": datetime(2026, 4, 2, 10, 25),
                },
                {
                    "dimension": "social",
                    "observation_type": "social_observation",
                    "observation_level": "medium",
                    "observed_at": datetime(2026, 4, 3, 12, 10),
                    "summary": "午休时独自坐在教室后排，不愿和同学一起去食堂，明显有回避。",
                    "created_at": datetime(2026, 4, 3, 12, 15),
                },
            ],
            family_contacts=[
                {
                    "contact_type": "phone",
                    "summary": "母亲表示孩子回家后一直说不敢独自走校门外的小路，希望学校近期多关注放学时段安全。",
                    "created_at": datetime(2026, 4, 2, 18, 30),
                }
            ],
            assistant_summaries=[
                {
                    "summary_text": "学生在 AI 助手中自述：放学路上又想起前两天被堵和被打的事，现在一到傍晚就紧张，担心对方继续威胁。",
                    "signals_json": {
                        "signals": [
                            {
                                "dimension": "safety",
                                "type": "assistant_safety_disclosure",
                                "text": "学生在 AI 助手中自述可能遭受他人攻击或受伤：放学路上被堵和被打。",
                                "weight": 0.78,
                            },
                            {
                                "dimension": "emotion",
                                "type": "assistant_emotion_disclosure",
                                "text": "AI 助手对话中出现需要关怀跟进的求助表达：一到傍晚就紧张，担心继续被威胁。",
                                "weight": 0.42,
                            },
                        ]
                    },
                    "created_at": datetime(2026, 4, 2, 22, 10),
                }
            ],
            graph_relations=[
                {
                    "target_type": "student",
                    "target_student_id": target_lookup["202400401"],
                    "relation_type": "conflict",
                    "dimension": "social",
                    "relation_level": "medium",
                    "summary": "班主任记录其与唐子墨因座位和玩笑冲突升级，事件后学生更不愿与同伴靠近。",
                    "occurred_at": datetime(2026, 4, 2, 9, 0),
                    "created_at": datetime(2026, 4, 2, 9, 5),
                },
                {
                    "target_type": "event",
                    "relation_type": "bullying_link",
                    "dimension": "safety",
                    "relation_level": "high",
                    "summary": "德育处记录：学生与校门外勒索线索存在明确关联，已通知家长共同核实。",
                    "event_title": "校门外围堵勒索线索",
                    "occurred_at": datetime(2026, 4, 2, 16, 0),
                    "created_at": datetime(2026, 4, 2, 16, 10),
                },
            ],
            review={
                "scene": "safety_risk",
                "is_true_risk": "yes",
                "severity": "high",
                "confidence_by_teacher": 5,
                "intervention_taken": "已完成谈话、联系家长并调整放学陪护安排",
                "follow_up_outcome": "学生情绪稍有稳定，但仍需继续核实事件是否持续",
                "teacher_notes": "已与家长和德育处同步，近期放学时段由老师重点关注。",
                "resolution_status": "in_progress",
            },
        ),
        DemoStudentSpec(
            student_no="202400409",
            name="林若溪",
            gender="female",
            age=15,
            grade="高一",
            contact="13800001009",
            specialty="手账设计",
            tags="住校生",
            story="渐进式被孤立型",
            scores=[
                {"exam_batch": DEMO_BATCHES[0], "subjects": {"语文": 82, "数学": 79, "英语": 84}, "created_at": datetime(2025, 11, 18, 9, 0)},
                {"exam_batch": DEMO_BATCHES[1], "subjects": {"语文": 80, "数学": 78, "英语": 82}, "created_at": datetime(2026, 2, 28, 9, 0)},
                {"exam_batch": DEMO_BATCHES[2], "subjects": {"语文": 78, "数学": 76, "英语": 80}, "created_at": datetime(2026, 3, 26, 9, 0)},
                {"exam_batch": DEMO_BATCHES[3], "subjects": {"语文": 77, "数学": 74, "英语": 79}, "created_at": datetime(2026, 4, 8, 9, 0)},
            ],
            attendance=[
                {"date": date(2026, 3, 20), "status": "late", "remark": "课前一直在走廊徘徊，不愿进教室。", "created_at": datetime(2026, 3, 20, 8, 5)},
                {"date": date(2026, 3, 27), "status": "late", "remark": "称昨晚失眠，担心分组活动又落单。", "created_at": datetime(2026, 3, 27, 8, 6)},
                {"date": date(2026, 4, 3), "status": "absent", "remark": "早晨说肚子痛请假，午后返校后仍明显回避同学。", "created_at": datetime(2026, 4, 3, 8, 20)},
            ],
            behavior=[],
            observations=[
                {
                    "dimension": "social",
                    "observation_type": "social_observation",
                    "observation_level": "medium",
                    "observed_at": datetime(2026, 3, 18, 12, 10),
                    "summary": "小组讨论时经常被动等待，发言变少，结束后独自回座位。",
                    "created_at": datetime(2026, 3, 18, 12, 15),
                },
                {
                    "dimension": "social",
                    "observation_type": "social_observation",
                    "observation_level": "high",
                    "observed_at": datetime(2026, 3, 31, 12, 20),
                    "summary": "午餐常独自留在教室，体育课自由组队时最后才被同伴叫到，明显有孤立感。",
                    "created_at": datetime(2026, 3, 31, 12, 25),
                },
                {
                    "dimension": "emotion",
                    "observation_type": "emotion_observation",
                    "observation_level": "medium",
                    "observed_at": datetime(2026, 4, 3, 15, 0),
                    "summary": "谈到同学分组时明显低落，反复说自己不想再主动开口，已有回避。",
                    "created_at": datetime(2026, 4, 3, 15, 5),
                },
            ],
            family_contacts=[
                {
                    "contact_type": "wechat",
                    "summary": "家长反映孩子近两周回家后不太愿意谈学校情况，常说“大家都已经分好了，我插不进去”。",
                    "created_at": datetime(2026, 4, 2, 20, 10),
                }
            ],
            assistant_summaries=[
                {
                    "summary_text": "学生在 AI 助手中表达：最近不太想和同学说话，感觉大家分组时总会先找别人，我也不想再主动开口。",
                    "signals_json": {
                        "signals": [
                            {
                                "dimension": "social",
                                "type": "assistant_social_withdrawal",
                                "text": "AI 助手对话中出现社交退缩表达：分组时总会先找别人，我不想再主动开口。",
                                "weight": 0.34,
                            },
                            {
                                "dimension": "emotion",
                                "type": "assistant_emotion_disclosure",
                                "text": "AI 助手对话中出现需要关怀跟进的低落表达：感觉自己插不进去。",
                                "weight": 0.26,
                            },
                        ]
                    },
                    "created_at": datetime(2026, 4, 3, 22, 0),
                }
            ],
            graph_relations=[
                {
                    "target_type": "event",
                    "relation_type": "concern",
                    "dimension": "social",
                    "relation_level": "high",
                    "summary": "近三次课堂分组均未被同伴主动邀请，班主任记录其已经接近被孤立的临界状态。",
                    "event_title": "连续分组边缘化",
                    "occurred_at": datetime(2026, 4, 1, 10, 0),
                    "created_at": datetime(2026, 4, 1, 10, 5),
                }
            ],
            review={
                "scene": "social_isolation",
                "is_true_risk": "yes",
                "severity": "medium",
                "confidence_by_teacher": 4,
                "intervention_taken": "已安排同桌轮换并让心理老师进行一次关怀谈话",
                "follow_up_outcome": "学生愿意接受老师帮助，但仍对同伴互动保持回避",
                "teacher_notes": "目前更像渐进式孤立，尚未出现公开冲突，适合做提前干预案例。",
                "resolution_status": "in_progress",
            },
        ),
        DemoStudentSpec(
            student_no="202400202",
            name="赵丽",
            gender="female",
            age=15,
            grade="高一",
            contact="13800001022",
            specialty="朗诵",
            tags="单亲家庭",
            story="家庭压力传导型",
            scores=[
                {"exam_batch": DEMO_BATCHES[0], "subjects": {"语文": 86, "数学": 80, "英语": 84}, "created_at": datetime(2025, 11, 18, 9, 0)},
                {"exam_batch": DEMO_BATCHES[1], "subjects": {"语文": 83, "数学": 78, "英语": 81}, "created_at": datetime(2026, 2, 28, 9, 0)},
                {"exam_batch": DEMO_BATCHES[2], "subjects": {"语文": 78, "数学": 73, "英语": 76}, "created_at": datetime(2026, 3, 26, 9, 0)},
                {"exam_batch": DEMO_BATCHES[3], "subjects": {"语文": 74, "数学": 69, "英语": 72}, "created_at": datetime(2026, 4, 8, 9, 0)},
            ],
            attendance=[
                {"date": date(2026, 3, 24), "status": "late", "remark": "早晨送弟弟到托管后才赶到学校。", "created_at": datetime(2026, 3, 24, 8, 12)},
                {"date": date(2026, 4, 7), "status": "late", "remark": "昨晚照顾家中老人到很晚，今早明显疲惫。", "created_at": datetime(2026, 4, 7, 8, 15)},
            ],
            behavior=[],
            observations=[
                {
                    "dimension": "family",
                    "observation_type": "follow_up",
                    "observation_level": "high",
                    "observed_at": datetime(2026, 3, 29, 16, 20),
                    "summary": "提到母亲连续夜班、自己要照顾弟弟时明显无助，家庭支持不足。",
                    "created_at": datetime(2026, 3, 29, 16, 25),
                },
                {
                    "dimension": "emotion",
                    "observation_type": "emotion_observation",
                    "observation_level": "medium",
                    "observed_at": datetime(2026, 4, 1, 10, 30),
                    "summary": "晨读时频繁走神，谈到家里安排时明显焦虑，反复说压力大。",
                    "created_at": datetime(2026, 4, 1, 10, 35),
                },
                {
                    "dimension": "study",
                    "observation_type": "study_observation",
                    "observation_level": "medium",
                    "observed_at": datetime(2026, 4, 8, 14, 10),
                    "summary": "作业完成质量下滑，课堂专注度下降，近期学习波动明显。",
                    "created_at": datetime(2026, 4, 8, 14, 15),
                },
            ],
            family_contacts=[
                {
                    "contact_type": "phone",
                    "summary": "母亲表示最近连续上夜班，孩子晚上要帮忙照顾弟弟，作业经常写到很晚，家庭支持一时跟不上。",
                    "created_at": datetime(2026, 4, 1, 20, 20),
                }
            ],
            assistant_summaries=[
                {
                    "summary_text": "学生在 AI 助手中表达：妈妈最近一直上夜班，我晚上要照顾弟弟，作业写到很晚，最近总觉得压力大，越学越慌。",
                    "signals_json": {
                        "signals": [
                            {
                                "dimension": "family",
                                "type": "assistant_family_pressure",
                                "text": "AI 助手对话中出现家庭支持不足表达：晚上要照顾弟弟，家里顾不过来。",
                                "weight": 0.32,
                            },
                            {
                                "dimension": "emotion",
                                "type": "assistant_emotion_disclosure",
                                "text": "AI 助手对话中出现压力和焦虑表达：最近总觉得压力大，越学越慌。",
                                "weight": 0.3,
                            },
                            {
                                "dimension": "study",
                                "type": "assistant_study_pressure",
                                "text": "AI 助手对话中出现学习承压表达：作业写到很晚，注意力越来越差。",
                                "weight": 0.28,
                            },
                        ]
                    },
                    "created_at": datetime(2026, 4, 7, 22, 40),
                }
            ],
            graph_relations=[],
            review={
                "scene": "family_pressure",
                "is_true_risk": "yes",
                "severity": "medium",
                "confidence_by_teacher": 4,
                "intervention_taken": "已与家长沟通作息安排，并协调任课老师减轻短期作业压力",
                "follow_up_outcome": "学生情绪略有缓和，但学业波动仍需跟踪",
                "teacher_notes": "该案例适合展示家庭支持下降如何传导到情绪和学习。",
                "resolution_status": "in_progress",
            },
        ),
        DemoStudentSpec(
            student_no="202400103",
            name="陈晨",
            gender="female",
            age=15,
            grade="高一",
            contact="13800001003",
            specialty="绘画",
            tags="心理关爱,班干部",
            story="学习压力伴随情绪耗竭型",
            scores=[
                {"exam_batch": DEMO_BATCHES[0], "subjects": {"语文": 90, "数学": 88, "英语": 89}, "created_at": datetime(2025, 11, 18, 9, 0)},
                {"exam_batch": DEMO_BATCHES[1], "subjects": {"语文": 88, "数学": 85, "英语": 87}, "created_at": datetime(2026, 2, 28, 9, 0)},
                {"exam_batch": DEMO_BATCHES[2], "subjects": {"语文": 82, "数学": 79, "英语": 81}, "created_at": datetime(2026, 3, 26, 9, 0)},
                {"exam_batch": DEMO_BATCHES[3], "subjects": {"语文": 78, "数学": 74, "英语": 77}, "created_at": datetime(2026, 4, 8, 9, 0)},
            ],
            attendance=[
                {"date": date(2026, 4, 2), "status": "late", "remark": "前一晚准备竞赛和班级事务到较晚，晨起状态差。", "created_at": datetime(2026, 4, 2, 8, 9)},
            ],
            behavior=[],
            observations=[
                {
                    "dimension": "study",
                    "observation_type": "study_observation",
                    "observation_level": "high",
                    "observed_at": datetime(2026, 4, 6, 14, 10),
                    "summary": "课堂答题反应变慢，作业订正拖延，近期学习压力明显上升。",
                    "created_at": datetime(2026, 4, 6, 14, 15),
                },
                {
                    "dimension": "emotion",
                    "observation_type": "emotion_observation",
                    "observation_level": "medium",
                    "observed_at": datetime(2026, 4, 7, 12, 20),
                    "summary": "谈及竞赛和班务时明显焦虑，表示最近总怕自己做不好，情绪有波动。",
                    "created_at": datetime(2026, 4, 7, 12, 25),
                },
            ],
            family_contacts=[
                {
                    "contact_type": "phone",
                    "summary": "家长表示愿意配合调整作息，近期会减少额外培训安排，家庭支持总体稳定。",
                    "created_at": datetime(2026, 4, 7, 20, 40),
                }
            ],
            assistant_summaries=[
                {
                    "summary_text": "学生在 AI 助手中表达：最近在准备竞赛又要处理班务，晚上总学到很晚，感觉越学越慌，怕自己把事情都做砸。",
                    "signals_json": {
                        "signals": [
                            {
                                "dimension": "study",
                                "type": "assistant_study_pressure",
                                "text": "AI 助手对话中出现学习承压表达：晚上总学到很晚，越学越慌。",
                                "weight": 0.34,
                            },
                            {
                                "dimension": "emotion",
                                "type": "assistant_emotion_disclosure",
                                "text": "AI 助手对话中出现焦虑表达：怕自己把事情都做砸。",
                                "weight": 0.28,
                            },
                        ]
                    },
                    "created_at": datetime(2026, 4, 7, 23, 10),
                }
            ],
            graph_relations=[
                {
                    "target_type": "student",
                    "target_student_id": target_lookup["202400105"],
                    "relation_type": "peer_support",
                    "dimension": "social",
                    "relation_level": "medium",
                    "summary": "何雨彤常主动帮其分担班务，提醒其按时休息，存在稳定同伴支持。",
                    "occurred_at": datetime(2026, 4, 7, 17, 0),
                    "created_at": datetime(2026, 4, 7, 17, 5),
                }
            ],
            review={
                "scene": "study_pressure",
                "is_true_risk": "yes",
                "severity": "medium",
                "confidence_by_teacher": 4,
                "intervention_taken": "已减少班务分配并建议暂缓额外竞赛任务",
                "follow_up_outcome": "学生愿意配合调整，但短期内学习压力仍偏高",
                "teacher_notes": "该案例用于展示常规规则链和保护性因素并存的情况。",
                "resolution_status": "in_progress",
            },
        ),
        DemoStudentSpec(
            student_no="202400410",
            name="沈知远",
            gender="male",
            age=15,
            grade="高一",
            contact="13800001010",
            specialty="篮球",
            tags="体育特长,班干部",
            story="干净稳定样本",
            scores=[
                {"exam_batch": DEMO_BATCHES[0], "subjects": {"语文": 91, "数学": 88, "英语": 90}, "created_at": datetime(2025, 11, 18, 9, 0)},
                {"exam_batch": DEMO_BATCHES[1], "subjects": {"语文": 92, "数学": 89, "英语": 91}, "created_at": datetime(2026, 2, 28, 9, 0)},
                {"exam_batch": DEMO_BATCHES[2], "subjects": {"语文": 90, "数学": 90, "英语": 92}, "created_at": datetime(2026, 3, 26, 9, 0)},
                {"exam_batch": DEMO_BATCHES[3], "subjects": {"语文": 91, "数学": 90, "英语": 93}, "created_at": datetime(2026, 4, 8, 9, 0)},
            ],
            attendance=[],
            behavior=[],
            observations=[
                {
                    "dimension": "social",
                    "observation_type": "social_observation",
                    "observation_level": "low",
                    "observed_at": datetime(2026, 4, 2, 12, 10),
                    "summary": "能主动融入小组合作，午休常与同学一起讨论作业，整体社交稳定。",
                    "created_at": datetime(2026, 4, 2, 12, 15),
                },
                {
                    "dimension": "study",
                    "observation_type": "study_observation",
                    "observation_level": "low",
                    "observed_at": datetime(2026, 4, 8, 15, 20),
                    "summary": "课堂参与积极，作业完成稳定，学习状态良好。",
                    "created_at": datetime(2026, 4, 8, 15, 25),
                },
            ],
            family_contacts=[
                {
                    "contact_type": "wechat",
                    "summary": "家长反馈孩子作息规律，愿意主动与老师沟通，家庭支持稳定。",
                    "created_at": datetime(2026, 4, 8, 20, 0),
                }
            ],
            assistant_summaries=[
                {
                    "summary_text": "学生在 AI 助手中提到：最近班级活动挺顺利，我和同学配合得不错，学习节奏也比较稳定。",
                    "signals_json": {
                        "signals": [
                            {
                                "dimension": "social",
                                "type": "assistant_social_positive",
                                "text": "AI 助手对话中出现积极社交表达：和同学配合得不错，愿意主动参加活动。",
                                "weight": 0.24,
                            },
                            {
                                "dimension": "study",
                                "type": "assistant_study_positive",
                                "text": "AI 助手对话中出现稳定学习表达：学习节奏比较稳定。",
                                "weight": 0.2,
                            },
                        ]
                    },
                    "created_at": datetime(2026, 4, 8, 21, 30),
                }
            ],
            graph_relations=[
                {
                    "target_type": "student",
                    "target_student_id": target_lookup["202400104"],
                    "relation_type": "peer_support",
                    "dimension": "social",
                    "relation_level": "medium",
                    "summary": "与孙浩常一起参加篮球训练和课后答疑，存在稳定互助。",
                    "occurred_at": datetime(2026, 4, 6, 17, 20),
                    "created_at": datetime(2026, 4, 6, 17, 25),
                },
                {
                    "target_type": "event",
                    "relation_type": "shared_activity",
                    "dimension": "social",
                    "relation_level": "medium",
                    "summary": "连续参加班级篮球联赛和志愿活动，班级参与度高，关系稳定。",
                    "event_title": "班级联赛与志愿活动",
                    "occurred_at": datetime(2026, 4, 5, 16, 0),
                    "created_at": datetime(2026, 4, 5, 16, 10),
                },
            ],
            review={
                "scene": "other",
                "is_true_risk": "no",
                "severity": "low",
                "confidence_by_teacher": 4,
                "intervention_taken": "保持常规观察",
                "follow_up_outcome": "目前状态稳定，无需额外干预",
                "teacher_notes": "用于现场演示系统不会对数据完整且状态稳定的学生误报。",
                "resolution_status": "resolved",
            },
        ),
    ]


def sync_class_count(db, class_id: int) -> None:
    class_row = db.query(Class).filter(Class.id == class_id).first()
    if class_row:
        class_row.current_count = db.query(Student).filter(Student.class_id == class_id).count()
        db.flush()


async def generate_agent_outputs(db, teacher_user: User, student: Student, spec: DemoStudentSpec) -> None:
    eval_resp = await student_care_agent_service.evaluate_student_care_agent(db, teacher_user, student.id)
    if eval_resp.get("code") != 200:
        raise RuntimeError(f"agent eval failed for {student.name}: {eval_resp}")

    payload = eval_resp.get("data") or {}
    record_id = payload.get("record_id")
    result = payload.get("result") or {}
    review = spec.review
    review_payload = StudentCareAgentReviewUpdate(
        reviewed_result=result,
        teacher_notes=review["teacher_notes"],
        resolution_status=review["resolution_status"],
        review_labels=StudentCareAgentReviewLabels(
            scene=review["scene"],
            is_true_risk=review["is_true_risk"],
            severity=review["severity"],
            confidence_by_teacher=review["confidence_by_teacher"],
            intervention_taken=review["intervention_taken"],
            follow_up_outcome=review["follow_up_outcome"],
        ),
    )
    confirm_resp = student_care_agent_service.confirm_agent_eval_review(db, teacher_user, record_id, review_payload)
    if confirm_resp.get("code") != 200:
        raise RuntimeError(f"agent confirm failed for {student.name}: {confirm_resp}")

    latest = db.query(StudentCareAgentRecord).filter(StudentCareAgentRecord.id == record_id).first()
    if not latest:
        raise RuntimeError(f"agent record missing for {student.name}")

    latest.created_at = NOW - timedelta(hours=3)
    latest.updated_at = NOW - timedelta(hours=3)
    latest.confirmed_at = NOW - timedelta(hours=2, minutes=30)
    db.flush()

    duplicate_agent_record(
        db,
        latest,
        created_at=NOW - timedelta(days=2, hours=5),
        review_status="pending",
        teacher_notes=None,
        resolution_status="pending",
        confirmed_by=None,
        confirmed_at=None,
        review_labels_json=None,
    )
    db.commit()


def summarize_profiles(db, teacher_user: User, students: list[Student]) -> None:
    print("\n=== Demo profile summary ===")
    for student in students:
        profile_resp = student_care_service.get_student_care_profile(db, teacher_user, student.id)
        data = profile_resp.get("data") or {}
        profile = data.get("profile") or {}
        print(
            {
                "student": student.name,
                "overall_risk": profile.get("overall_risk"),
                "risk_level": profile.get("risk_level"),
                "trend": profile.get("trend"),
                "major_incident": profile.get("major_incident_detected"),
                "emotion": profile.get("emotion_score"),
                "social": profile.get("social_score"),
                "safety": profile.get("safety_score"),
                "family": profile.get("family_score"),
                "study": profile.get("study_score"),
                "behavior": profile.get("behavior_score"),
            }
        )


def main() -> None:
    db = SessionLocal()
    try:
        teacher_user = db.query(User).filter(User.username == "wang_math").first()
        if not teacher_user:
            raise RuntimeError("teacher user wang_math not found")

        class_row = db.query(Class).filter(Class.id == 1).first()
        if not class_row:
            raise RuntimeError("class 高一1班 not found")

        target_lookup = {
            row.student_no: row.id
            for row in db.query(Student).filter(Student.class_id == class_row.id).all()
        }
        required = {"202400401", "202400104", "202400105"}
        missing = required - set(target_lookup)
        if missing:
            raise RuntimeError(f"required classmates missing: {sorted(missing)}")

        specs = build_demo_specs(target_lookup)

        for spec in specs:
            ensure_student(db, class_row.id, spec)
        db.commit()

        refreshed_students: list[Student] = []
        for spec in specs:
            student = db.query(Student).filter(Student.student_no == spec.student_no).first()
            refreshed_students.append(student)
            reset_student_related_data(db, student.id)
            add_scores(db, student, spec.scores)
            add_attendance(db, student, spec.attendance)
            add_behavior_events(db, student, spec.behavior)
            add_observations(db, student, spec.observations)
            add_family_contacts(db, student, spec.family_contacts)
            add_assistant_summaries(db, student, spec.assistant_summaries)
            add_graph_relations(db, student, spec.graph_relations, created_by=teacher_user.id)
        sync_class_count(db, class_row.id)
        db.commit()

        for student in refreshed_students:
            try:
                student_care_graph_service.sync_student_graph(db, student.id)
            except Exception as exc:
                print(f"[warn] graph sync skipped for {student.name}: {exc}")
            student_care_service.recalculate_student_care_profile(db, student)
            db.commit()

        for spec in specs:
            student = db.query(Student).filter(Student.student_no == spec.student_no).first()
            asyncio.run(generate_agent_outputs(db, teacher_user, student, spec))

        summarize_profiles(db, teacher_user, refreshed_students)
        print("\nDemo students ready:")
        for spec in specs:
            print(f"- {spec.name} ({spec.student_no}) | {spec.story}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
