# -*- coding: utf-8 -*-
"""Seed richer user-facing demo data across student, tag, care, evaluation and rule modules.

Safe to re-run:
- student/class/user/rule/tag definitions are upserted
- demo auxiliary records use a stable prefix and are replaced
- demo evaluation records use a fixed model_name and are replaced
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from core.security import hash_password
from database.connection import SessionLocal
from database.models.class_ import Class
from database.models.school_rule import SchoolRule
from database.models.score import Score
from database.models.student import Student
from database.models.student_assistant_summary import StudentAssistantSummary
from database.models.student_attendance import StudentAttendance
from database.models.student_behavior_event import StudentBehaviorEvent
from database.models.student_care_agent_record import StudentCareAgentRecord
from database.models.student_care_profile import StudentCareProfile
from database.models.student_family_contact import StudentFamilyContact
from database.models.student_tag_definition import StudentTagDefinition
from database.models.student_tag_review import StudentTagReview
from database.models.user import User
from scripts.append_manual_test_data import main as append_manual_test_data_main
from services import student_care_service
from services.student_care_schema_guard import ensure_student_care_schema


DEMO_PREFIX = "demo_seed"
EVAL_MODEL_NAME = "demo-seed-eval"
NOW = datetime(2026, 4, 10, 16, 0, 0)


@dataclass
class DemoStudentSpec:
    student_no: str
    username: str
    name: str
    gender: str
    age: int
    grade: str
    class_name: str | None
    contact: str
    specialty: str
    tags: str
    scores: dict[str, dict[str, float]]
    attendance_rows: list[tuple[date, str, str]]
    behavior_rows: list[tuple[str, str, str, datetime]]
    family_rows: list[tuple[str, str]]
    assistant_rows: list[tuple[str, list[dict]]]


def ensure_user(db, username: str, password: str, role: str, name: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    if user:
        user.role = role
        user.name = name
        return user
    user = User(username=username, password_hash=hash_password(password), role=role, name=name)
    db.add(user)
    db.flush()
    return user


def ensure_student(db, spec: DemoStudentSpec, class_lookup: dict[str, int]) -> Student:
    class_id = class_lookup.get(spec.class_name) if spec.class_name else None
    student = db.query(Student).filter(Student.student_no == spec.student_no).first()
    if student:
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
    db.flush()
    return student


def ensure_score(db, student: Student, exam_batch: str, subject: str, value: float) -> None:
    row = (
        db.query(Score)
        .filter(
            Score.student_id == student.id,
            Score.class_id == student.class_id,
            Score.exam_batch == exam_batch,
            Score.subject == subject,
        )
        .first()
    )
    if row:
        row.score = Decimal(str(value))
        return
    db.add(
        Score(
            student_id=student.id,
            class_id=student.class_id,
            exam_batch=exam_batch,
            subject=subject,
            score=Decimal(str(value)),
            created_at=NOW,
            updated_at=NOW,
        )
    )


def replace_demo_auxiliary_rows(db, student: Student, spec: DemoStudentSpec) -> None:
    db.query(StudentAttendance).filter(
        StudentAttendance.student_id == student.id,
        StudentAttendance.remark.like(f"{DEMO_PREFIX}:%"),
    ).delete(synchronize_session=False)
    db.query(StudentBehaviorEvent).filter(
        StudentBehaviorEvent.student_id == student.id,
        StudentBehaviorEvent.event_desc.like(f"{DEMO_PREFIX}:%"),
    ).delete(synchronize_session=False)
    db.query(StudentFamilyContact).filter(
        StudentFamilyContact.student_id == student.id,
        StudentFamilyContact.summary.like(f"{DEMO_PREFIX}:%"),
    ).delete(synchronize_session=False)
    db.query(StudentAssistantSummary).filter(
        StudentAssistantSummary.student_id == student.id,
        StudentAssistantSummary.summary_text.like(f"{DEMO_PREFIX}:%"),
    ).delete(synchronize_session=False)
    db.flush()

    for exam_batch, subjects in spec.scores.items():
        for subject, value in subjects.items():
            ensure_score(db, student, exam_batch, subject, value)

    for day_value, status, remark in spec.attendance_rows:
        db.add(
            StudentAttendance(
                student_id=student.id,
                date=day_value,
                status=status,
                remark=f"{DEMO_PREFIX}:{remark}",
                created_at=NOW,
                updated_at=NOW,
            )
        )

    for event_type, event_level, event_desc, occurred_at in spec.behavior_rows:
        db.add(
            StudentBehaviorEvent(
                student_id=student.id,
                event_type=event_type,
                event_level=event_level,
                event_desc=f"{DEMO_PREFIX}:{event_desc}",
                occurred_at=occurred_at,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    for contact_type, summary in spec.family_rows:
        db.add(
            StudentFamilyContact(
                student_id=student.id,
                contact_type=contact_type,
                summary=f"{DEMO_PREFIX}:{summary}",
                created_at=NOW,
                updated_at=NOW,
            )
        )

    for summary_text, signals in spec.assistant_rows:
        db.add(
            StudentAssistantSummary(
                student_id=student.id,
                summary_text=f"{DEMO_PREFIX}:{summary_text}",
                signals_json={"signals": signals},
                created_at=NOW,
                updated_at=NOW,
            )
        )


def ensure_tag_definition(
    db,
    *,
    scope_type: str,
    scope_value: str | None,
    tag_text: str,
    polarity: str,
    dimension: str | None,
    weight: float | None,
    description: str,
    created_by: int,
) -> None:
    row = (
        db.query(StudentTagDefinition)
        .filter(
            StudentTagDefinition.scope_type == scope_type,
            StudentTagDefinition.scope_value == scope_value,
            StudentTagDefinition.tag_text == tag_text,
        )
        .first()
    )
    if not row:
        row = StudentTagDefinition(
            scope_type=scope_type,
            scope_value=scope_value,
            tag_text=tag_text,
            created_by=created_by,
        )
        db.add(row)
    row.polarity = polarity
    row.dimension = dimension
    row.weight = weight
    row.description = description


def ensure_tag_review(
    db,
    *,
    tag_text: str,
    student: Student,
    status: str,
    source: str,
    scope_type: str,
    scope_value: str | None,
    polarity: str,
    dimension: str | None,
    weight: float | None,
    description: str,
    suggestion_note: str,
    created_by: int,
    reviewed_by: int | None = None,
    review_note: str | None = None,
) -> None:
    row = (
        db.query(StudentTagReview)
        .filter(
            StudentTagReview.tag_text == tag_text,
            StudentTagReview.student_id == student.id,
            StudentTagReview.source == source,
        )
        .first()
    )
    if not row:
        row = StudentTagReview(
            tag_text=tag_text,
            student_id=student.id,
            class_id=student.class_id,
            grade=student.grade,
            source=source,
            created_by=created_by,
        )
        db.add(row)
    row.status = status
    row.class_id = student.class_id
    row.grade = student.grade
    row.suggested_scope_type = scope_type
    row.suggested_scope_value = scope_value
    row.suggested_polarity = polarity
    row.suggested_dimension = dimension
    row.suggested_weight = weight
    row.suggested_description = description
    row.suggestion_note = suggestion_note
    row.reviewed_by = reviewed_by
    row.reviewed_at = NOW if reviewed_by else None
    row.review_note = review_note


def ensure_school_rule(db, category: str, title: str, content: str, updated_by: int) -> None:
    row = db.query(SchoolRule).filter(SchoolRule.title == title).first()
    if not row:
        row = SchoolRule(category=category, title=title, content=content, updated_by=updated_by)
        db.add(row)
        return
    row.category = category
    row.content = content
    row.updated_by = updated_by


def replace_demo_evaluations(db, students_by_no: dict[str, Student], teacher_user: User) -> None:
    db.query(StudentCareAgentRecord).filter(
        StudentCareAgentRecord.model_name == EVAL_MODEL_NAME,
    ).delete(synchronize_session=False)
    db.flush()

    payloads = [
        ("202400501", "medium", "study", "yes", "medium", "in_progress", 4, False, ["最近成绩波动明显，需要持续跟进。"]),
        ("202400502", "high", "emotion", "yes", "high", "resolved", 5, False, ["情绪与学业双重压力较高，已安排谈心。"]),
        ("202400503", "attention", "family", "no", "low", "false_alarm", 3, False, ["家庭支持偏弱但近期状态稳定，先观察。"]),
        ("202400504", "high", "behavior", "yes", "high", "in_progress", 4, True, ["同伴冲突与迟到同时出现，需家校联动。"]),
        ("202400505", "low", "social", "no", "low", "resolved", 4, False, ["系统预警偏保守，老师判断目前稳定。"]),
        ("202400506", "attention", "social", "yes", "medium", "pending", 3, True, ["待分班阶段社交融入风险上升，建议持续观察。"]),
    ]

    for index, (student_no, level, scene, is_true_risk, severity, resolution_status, confidence, fallback, suggestions) in enumerate(payloads):
        student = students_by_no[student_no]
        created_at = NOW - timedelta(days=index)
        result_json = {
            "overall_score": {"low": 0.18, "attention": 0.42, "medium": 0.66, "high": 0.83}[level],
            "overall_level": level,
            "suggestions": suggestions,
            "dimensions": [
                {
                    "dimension": scene,
                    "score": {"low": 0.2, "attention": 0.45, "medium": 0.68, "high": 0.86}[level],
                    "risk_level": level,
                    "summary": f"{scene} 维度存在需要关注的信号",
                    "evidence": [f"{DEMO_PREFIX} evidence for {student.name}"],
                    "score_explanation": ["demo seeded explanation"],
                    "score_breakdown": [],
                }
            ],
            "review_suggestions": [],
            "explanation_highlights": [f"{student.name} 的最近动态触发了演示研判记录"],
            "overall_breakdown": {},
            "major_incident_mode": fallback,
            "major_incident_summary": None,
            "secondary_impacts": [],
        }
        input_snapshot = {
            "student_id": student.id,
            "signals": [
                {
                    "source": "tag_definition",
                    "signal_type": "demo_seed_signal",
                    "signal_weight": 0.32 if level in {"medium", "high"} else 0.12,
                    "dimension": scene,
                }
            ],
        }
        review_labels_json = {
            "scene": scene,
            "is_true_risk": is_true_risk,
            "severity": severity,
            "confidence_by_teacher": confidence,
            "intervention_taken": "已在班主任工作台登记跟进" if is_true_risk == "yes" else "暂不升级处理",
            "follow_up_outcome": "一周后复盘",
        }
        db.add(
            StudentCareAgentRecord(
                student_id=student.id,
                model_name=EVAL_MODEL_NAME,
                timeout_seconds=60,
                fallback=1 if fallback else 0,
                error_msg=None,
                input_snapshot=input_snapshot,
                result_json=result_json,
                raw_text=f"{DEMO_PREFIX}: {student.name} evaluation",
                review_status="confirmed",
                reviewed_result_json=result_json,
                review_labels_json=review_labels_json,
                teacher_notes=f"{student.name} 的演示复核备注",
                resolution_status=resolution_status,
                confirmed_by=teacher_user.id,
                confirmed_at=created_at + timedelta(hours=4),
                created_at=created_at,
                updated_at=created_at,
            )
        )


def sync_class_counts(db) -> None:
    for class_row in db.query(Class).all():
        class_row.current_count = db.query(Student).filter(Student.class_id == class_row.id).count()


def build_demo_students() -> list[DemoStudentSpec]:
    return [
        DemoStudentSpec(
            student_no="202400501",
            username="stu_202400501",
            name="韩雨辰",
            gender="female",
            age=15,
            grade="高一",
            class_name="高一2班",
            contact="13800000101",
            specialty="主持",
            tags="班级骨干,英语拔尖",
            scores={
                "2025秋期中": {"语文": 88, "数学": 84, "英语": 93},
                "2026春季月考": {"语文": 86, "数学": 82, "英语": 95},
            },
            attendance_rows=[],
            behavior_rows=[],
            family_rows=[("phone", "家长反馈学习状态稳定，愿意配合学校活动。")],
            assistant_rows=[("综合状态稳定，适合作为班级正向示范。", [{"dimension": "social", "weight": -0.08, "text": "班级参与度高", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202400502",
            username="stu_202400502",
            name="罗子轩",
            gender="male",
            age=15,
            grade="高一",
            class_name="高一2班",
            contact="13800000102",
            specialty="篮球",
            tags="学习吃力,情绪波动",
            scores={
                "2025秋期中": {"语文": 72, "数学": 68, "英语": 70},
                "2026春季月考": {"语文": 64, "数学": 59, "英语": 61},
            },
            attendance_rows=[(date(2026, 4, 7), "late", "连续两天早读迟到"), (date(2026, 4, 9), "absent", "上午请假未及时补登记")],
            behavior_rows=[("conflict", "medium", "课间与同学发生口角", NOW - timedelta(days=3))],
            family_rows=[("phone", "家长反馈最近作业拖延明显，晚上情绪波动。")],
            assistant_rows=[("近期学业压力较大，情绪易波动。", [{"dimension": "emotion", "weight": 0.28, "text": "作业反馈消极", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202400503",
            username="stu_202400503",
            name="程心怡",
            gender="female",
            age=15,
            grade="高一",
            class_name="高一3班",
            contact="13800000103",
            specialty="绘画",
            tags="留守儿童,心理关爱",
            scores={
                "2025秋期中": {"语文": 78, "数学": 76, "英语": 81},
                "2026春季月考": {"语文": 79, "数学": 74, "英语": 80},
            },
            attendance_rows=[],
            behavior_rows=[],
            family_rows=[("visit", "家访记录显示祖辈照护为主，情感支持相对有限。")],
            assistant_rows=[("家庭支持偏弱，但课堂状态尚可。", [{"dimension": "family", "weight": 0.22, "text": "监护支持不足", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202400504",
            username="stu_202400504",
            name="许嘉豪",
            gender="male",
            age=16,
            grade="高一",
            class_name="高一3班",
            contact="13800000104",
            specialty="足球",
            tags="同伴冲突,迟到",
            scores={
                "2025秋期中": {"语文": 75, "数学": 73, "英语": 69},
                "2026春季月考": {"语文": 71, "数学": 67, "英语": 66},
            },
            attendance_rows=[(date(2026, 4, 8), "late", "值日结束后迟到"), (date(2026, 4, 10), "late", "晨检后进班较晚")],
            behavior_rows=[("conflict", "high", "午休前在走廊与同伴发生推搡", NOW - timedelta(days=1))],
            family_rows=[("phone", "家长表示放学后与同伴矛盾较多，愿意来校沟通。")],
            assistant_rows=[("近期社交摩擦明显，需要班主任持续盯防。", [{"dimension": "social", "weight": 0.31, "text": "冲突复发", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202400505",
            username="stu_202400505",
            name="苏芷晴",
            gender="female",
            age=15,
            grade="高一",
            class_name="高一4班",
            contact="13800000105",
            specialty="钢琴",
            tags="艺术特长,班级骨干",
            scores={
                "2025秋期中": {"语文": 91, "数学": 87, "英语": 89},
                "2026春季月考": {"语文": 92, "数学": 88, "英语": 90},
            },
            attendance_rows=[],
            behavior_rows=[],
            family_rows=[("phone", "家长希望继续支持学生参加艺术节。")],
            assistant_rows=[("整体状态积极稳定，可承担班级展示任务。", [{"dimension": "social", "weight": -0.06, "text": "稳定参与班级事务", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202400506",
            username="stu_202400506",
            name="邵泽宇",
            gender="male",
            age=15,
            grade="高一",
            class_name=None,
            contact="13800000106",
            specialty="机器人",
            tags="待分班,行为失范",
            scores={},
            attendance_rows=[(date(2026, 4, 9), "absent", "分班报到材料提交不完整")],
            behavior_rows=[("discipline", "medium", "报到时与值班老师顶撞", NOW - timedelta(days=2))],
            family_rows=[("phone", "家长表示转学适应中，愿意配合行为习惯纠偏。")],
            assistant_rows=[("待分班阶段规则适应不足，建议入班后重点观察。", [{"dimension": "behavior", "weight": 0.26, "text": "规则边界感偏弱", "type": "assistant_signal"}])],
        ),
    ]


def build_school_like_students() -> list[DemoStudentSpec]:
    return [
        DemoStudentSpec(
            student_no="202400511",
            username="stu_202400511",
            name="周一诺",
            gender="female",
            age=15,
            grade="高一",
            class_name="高一1班",
            contact="13800000111",
            specialty="朗读",
            tags="班级骨干,语文拔尖",
            scores={
                "2025秋期中": {"语文": 92, "数学": 83, "英语": 88},
                "2025秋期末": {"语文": 94, "数学": 84, "英语": 89},
                "2026春季月考": {"语文": 93, "数学": 86, "英语": 90},
            },
            attendance_rows=[],
            behavior_rows=[],
            family_rows=[("phone", "家长反馈学生在班内担任学习委员，状态稳定。")],
            assistant_rows=[("课堂参与积极，兼具组织能力和学习稳定性。", [{"dimension": "social", "weight": -0.06, "text": "班务参与稳定", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202400512",
            username="stu_202400512",
            name="郭晨浩",
            gender="male",
            age=15,
            grade="高一",
            class_name="高一1班",
            contact="13800000112",
            specialty="篮球",
            tags="迟到,学习吃力",
            scores={
                "2025秋期中": {"语文": 74, "数学": 71, "英语": 69},
                "2025秋期末": {"语文": 70, "数学": 66, "英语": 64},
                "2026春季月考": {"语文": 68, "数学": 63, "英语": 61},
            },
            attendance_rows=[
                (date(2026, 4, 6), "late", "周一晨读迟到"),
                (date(2026, 4, 7), "late", "晨检后进班偏晚"),
                (date(2026, 4, 10), "late", "早操结束后返班缓慢"),
            ],
            behavior_rows=[("discipline", "medium", "晚自习期间与后排同学聊天影响秩序", NOW - timedelta(days=4))],
            family_rows=[("phone", "家长反映晚上打游戏时间偏长，作业完成拖延。")],
            assistant_rows=[("考勤和作业执行力偏弱，学习状态持续下滑。", [{"dimension": "study", "weight": 0.24, "text": "近期作业拖延", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202400513",
            username="stu_202400513",
            name="陆思瑶",
            gender="female",
            age=15,
            grade="高一",
            class_name="高一2班",
            contact="13800000113",
            specialty="舞蹈",
            tags="艺术特长,心理关爱",
            scores={
                "2025秋期中": {"语文": 84, "数学": 78, "英语": 87},
                "2025秋期末": {"语文": 82, "数学": 76, "英语": 85},
                "2026春季月考": {"语文": 81, "数学": 75, "英语": 84},
            },
            attendance_rows=[(date(2026, 4, 8), "leave", "参加区级文艺节目排练请假半天")],
            behavior_rows=[],
            family_rows=[("phone", "家长希望兼顾艺术活动与文化课，愿意配合学校做时间管理。")],
            assistant_rows=[("综合表现较稳，但阶段性疲劳感增加。", [{"dimension": "emotion", "weight": 0.16, "text": "近期训练和学习并行", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202400514",
            username="stu_202400514",
            name="何俊驰",
            gender="male",
            age=16,
            grade="高一",
            class_name="高一2班",
            contact="13800000114",
            specialty="编程",
            tags="信息技术特长,同伴冲突",
            scores={
                "2025秋期中": {"语文": 79, "数学": 92, "英语": 73},
                "2025秋期末": {"语文": 78, "数学": 90, "英语": 72},
                "2026春季月考": {"语文": 76, "数学": 88, "英语": 70},
            },
            attendance_rows=[],
            behavior_rows=[
                ("conflict", "medium", "机房值日分工时与同学争执", NOW - timedelta(days=5)),
                ("discipline", "low", "信息课上擅自切换设备权限设置", NOW - timedelta(days=12)),
            ],
            family_rows=[("phone", "家长表示孩子在家较少表达，但对同伴评价较敏感。")],
            assistant_rows=[("学科优势明显，但同伴合作耐心不足。", [{"dimension": "social", "weight": 0.21, "text": "合作沟通摩擦增加", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202400515",
            username="stu_202400515",
            name="唐可欣",
            gender="female",
            age=15,
            grade="高一",
            class_name="高一3班",
            contact="13800000115",
            specialty="书法",
            tags="留守儿童,班级骨干",
            scores={
                "2025秋期中": {"语文": 86, "数学": 79, "英语": 81},
                "2025秋期末": {"语文": 85, "数学": 78, "英语": 80},
                "2026春季月考": {"语文": 84, "数学": 77, "英语": 79},
            },
            attendance_rows=[],
            behavior_rows=[],
            family_rows=[
                ("visit", "家访显示与祖父母同住，日常生活稳定但缺少学业陪伴。"),
                ("phone", "家长表示视频沟通频率较低，希望老师适时提醒。"),
            ],
            assistant_rows=[("责任感较强，但家庭陪伴不足仍是长期变量。", [{"dimension": "family", "weight": 0.18, "text": "家庭支持偏弱但稳定", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202400516",
            username="stu_202400516",
            name="谢博文",
            gender="male",
            age=16,
            grade="高一",
            class_name="高一3班",
            contact="13800000116",
            specialty="足球",
            tags="违纪,迟到",
            scores={
                "2025秋期中": {"语文": 71, "数学": 69, "英语": 67},
                "2025秋期末": {"语文": 73, "数学": 68, "英语": 65},
                "2026春季月考": {"语文": 70, "数学": 64, "英语": 62},
            },
            attendance_rows=[
                (date(2026, 4, 7), "late", "晨练后未按时回班"),
                (date(2026, 4, 9), "late", "值日后迟到"),
            ],
            behavior_rows=[
                ("discipline", "medium", "午休铃响后仍在操场逗留", NOW - timedelta(days=6)),
                ("conflict", "low", "与宿舍同学因物品摆放发生争执", NOW - timedelta(days=9)),
            ],
            family_rows=[("phone", "家长认可学校严格管理，希望加强行为习惯约束。")],
            assistant_rows=[("行为规范和时间管理需要持续纠偏。", [{"dimension": "behavior", "weight": 0.27, "text": "纪律提醒频率升高", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202300111",
            username="stu_202300111",
            name="陈安琪",
            gender="female",
            age=16,
            grade="高二",
            class_name="高二1班",
            contact="13800000117",
            specialty="声乐",
            tags="英语拔尖,班级骨干",
            scores={
                "2025秋期中": {"语文": 87, "数学": 82, "英语": 95},
                "2025秋期末": {"语文": 88, "数学": 84, "英语": 96},
                "2026春季月考": {"语文": 89, "数学": 85, "英语": 95},
            },
            attendance_rows=[],
            behavior_rows=[],
            family_rows=[("phone", "家长关注升学规划，希望保持英语优势。")],
            assistant_rows=[("高二阶段学习节奏稳定，可承担经验分享。", [{"dimension": "study", "weight": -0.05, "text": "学习节奏稳定", "type": "assistant_signal"}])],
        ),
        DemoStudentSpec(
            student_no="202300112",
            username="stu_202300112",
            name="宋嘉树",
            gender="male",
            age=17,
            grade="高二",
            class_name="高二1班",
            contact="13800000118",
            specialty="物理竞赛",
            tags="数学拔尖,情绪波动",
            scores={
                "2025秋期中": {"语文": 76, "数学": 96, "英语": 78},
                "2025秋期末": {"语文": 74, "数学": 95, "英语": 76},
                "2026春季月考": {"语文": 72, "数学": 94, "英语": 73},
            },
            attendance_rows=[(date(2026, 4, 10), "leave", "竞赛集训返校后下午请假调整")],
            behavior_rows=[],
            family_rows=[("phone", "家长担心竞赛与高考课程冲突，学生近期睡眠不足。")],
            assistant_rows=[("竞赛投入高，情绪疲劳和作息压力需要同步关注。", [{"dimension": "emotion", "weight": 0.2, "text": "睡眠质量下降", "type": "assistant_signal"}])],
        ),
    ]


def main() -> None:
    append_manual_test_data_main()
    ensure_student_care_schema()

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        teacher_user = db.query(User).filter(User.username == "wang_math").first()
        if not admin or not teacher_user:
            raise RuntimeError("required admin/wang_math users are missing")

        class_lookup = {row.name: row.id for row in db.query(Class).all()}
        students_by_no: dict[str, Student] = {}

        all_specs = build_demo_students() + build_school_like_students()
        for spec in all_specs:
            ensure_user(db, spec.username, "student123", "student", spec.name)
            student = ensure_student(db, spec, class_lookup)
            replace_demo_auxiliary_rows(db, student, spec)
            students_by_no[spec.student_no] = student

        definition_rows = [
            ("school", None, "班级骨干", "positive", "social", 0.0, "具备较强的组织与班级服务能力。"),
            ("school", None, "英语拔尖", "positive", "study", 0.0, "英语学科表现突出。"),
            ("school", None, "艺术特长", "positive", "emotion", 0.0, "艺术活动参与积极，可作为保护性因素参考。"),
            ("school", None, "学习吃力", "negative", "study", 0.42, "近期学业压力较高，需要学习支持。"),
            ("school", None, "情绪波动", "negative", "emotion", 0.46, "近期情绪稳定性不足。"),
            ("school", None, "留守儿童", "negative", "family", 0.38, "家庭陪伴与支持可能不足。"),
            ("school", None, "心理关爱", "negative", "emotion", 0.34, "需要持续关注心理状态。"),
            ("school", None, "同伴冲突", "negative", "social", 0.44, "同伴关系存在冲突风险。"),
            ("school", None, "行为失范", "negative", "behavior", 0.4, "规则意识与行为稳定性需加强。"),
            ("grade", "高一", "待分班", "negative", "social", 0.18, "处于待分班阶段，需要关注融入状态。"),
        ]
        for scope_type, scope_value, tag_text, polarity, dimension, weight, description in definition_rows:
            ensure_tag_definition(
                db,
                scope_type=scope_type,
                scope_value=scope_value,
                tag_text=tag_text,
                polarity=polarity,
                dimension=dimension,
                weight=weight,
                description=description,
                created_by=admin.id,
            )

        review_rows = [
            ("202400502", "夜间情绪低落", "approved", "ai_detected", "school", None, "negative", "emotion", 0.41, "由AI摘要发现的情绪低落标签，建议纳入统一字典。", "近三次摘要都出现明显消极表达。", admin.id, "纳入统一标签"),
            ("202400503", "家庭照护不足", "approved", "teacher_input", "grade", "高一", "negative", "family", 0.36, "家访中多次出现，需要纳入高一年级通用标签。", "祖辈照护场景较典型。", admin.id, "适合年级通用"),
            ("202400504", "课间冲突频发", "pending", "teacher_input", "school", None, "negative", "social", 0.43, "建议作为同伴冲突的细分标签。", "近两周事件重复出现。", None, None),
            ("202400505", "艺术活动积极", "approved", "teacher_input", "school", None, "positive", "emotion", 0.0, "可作为保护性标签。", "多次承担艺术节展示任务。", teacher_user.id, "作为正向示范标签"),
            ("202400506", "入班适应风险", "pending", "ai_detected", "grade", "高一", "negative", "social", 0.24, "待分班学生在适应期的通用风险标签。", "转入与待分班场景都可复用。", None, None),
            ("202400501", "课堂带动能力强", "rejected", "teacher_input", "school", None, "positive", "social", 0.0, "与班级骨干标签重叠度较高。", "已有同义标签，无需重复。", admin.id, "与现有标签重复"),
        ]
        for student_no, tag_text, status, source, scope_type, scope_value, polarity, dimension, weight, description, suggestion_note, reviewer_id, review_note in review_rows:
            ensure_tag_review(
                db,
                tag_text=tag_text,
                student=students_by_no[student_no],
                status=status,
                source=source,
                scope_type=scope_type,
                scope_value=scope_value,
                polarity=polarity,
                dimension=dimension,
                weight=weight,
                description=description,
                suggestion_note=suggestion_note,
                created_by=teacher_user.id,
                reviewed_by=reviewer_id,
                review_note=review_note,
            )

        rule_rows = [
            ("安全管理", "校园欺凌零容忍处置", "发现言语羞辱、围堵、网络恶意传播等疑似欺凌情形时，班主任需在当日完成首轮核查并上报年级组。"),
            ("教学管理", "课堂秩序与手机收纳", "进入教室后学生手机统一放入班级收纳柜，课堂期间未经允许不得取回。"),
            ("德育管理", "心理关怀跟进记录", "涉及情绪波动、家庭重大变故等情况的学生，应在一周内形成不少于一次关怀跟进记录。"),
            ("考勤", "周末返校与销假", "周末离校学生返校后需在首节课前完成销假登记，特殊情况由家长与班主任同步说明。"),
        ]
        for category, title, content in rule_rows:
            ensure_school_rule(db, category, title, content, admin.id)

        db.flush()
        sync_class_counts(db)
        db.commit()

        for student_no in list(students_by_no):
            students_by_no[student_no] = db.query(Student).filter(Student.student_no == student_no).first()

        for student in students_by_no.values():
            student_care_service.recalculate_student_care_profile(db, student)
        replace_demo_evaluations(db, students_by_no, teacher_user)
        db.commit()

        print("Seeded demo content successfully.")
        print("students:", db.query(Student).count())
        print("tag_definitions:", db.query(StudentTagDefinition).count())
        print("tag_reviews:", db.query(StudentTagReview).count())
        print("care_profiles:", db.query(StudentCareProfile).count())
        print("agent_records:", db.query(StudentCareAgentRecord).count())
        print("school_rules:", db.query(SchoolRule).count())
    finally:
        db.close()


if __name__ == "__main__":
    main()
