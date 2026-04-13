# -*- coding: utf-8 -*-
"""Seed removable teacher-rule test data into the school rule library.

Usage:
    python backend/scripts/seed_teacher_rule_test_rules.py
    python backend/scripts/seed_teacher_rule_test_rules.py --cleanup

Behavior:
- Upserts a stable set of higher-frequency and higher-complexity school rules
- Marks test records with a dedicated title prefix and content marker
- Rebuilds the rule RAG index for inserted/updated rules
- Cleanup deletes only this script's tagged rules and removes their indexes
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from database.connection import SessionLocal
from database.models.school_rule import SchoolRule
from database.models.user import User
from services.rag.rule_kb_service import delete_rule_index, rebuild_rule_index


TEST_RULE_PREFIX = "[TEST_RULE_SEED]"
TEST_RULE_MARKER = "test_rule_seed_v2"

TEST_RULES = [
    {
        "category": "考勤",
        "title": "迟到管理",
        "content": (
            "主题: 迟到与日常考勤\n"
            "行为类型: late attendance punctuality\n"
            "关键词: 迟到,考勤,到校,进班,晨读,时间管理\n"
            "家校联系: 重复迟到时建议联系家长\n"
            "关怀跟进: 若伴随情绪波动或明显回避可转入持续关怀\n"
            "学生应按学校规定时间到校、进班和参加早读、升旗、课堂学习。\n"
            "当日迟到由值日教师或班主任登记。\n"
            "一周内累计迟到 2 次的，由班主任开展提醒谈话并记录原因。\n"
            "两周内累计迟到 3 次及以上的，建议联系家长共同了解作息、交通或情绪因素。\n"
            "若迟到同时伴随早退、旷课或情绪异常，应结合实际情况决定是否转入持续关怀跟进。"
        ),
    },
    {
        "category": "考勤",
        "title": "重复迟到的分层处置",
        "content": (
            "主题: 重复迟到升级处理\n"
            "行为类型: late escalation attendance\n"
            "关键词: 重复迟到,累计迟到,升级处理,分层处置,班主任,年级组\n"
            "家校联系: 达到升级阈值后建议同步家长\n"
            "关怀跟进: 迟到伴随回避、睡眠问题或家庭因素时可纳入关怀\n"
            "首次迟到以提醒教育和原因登记为主。\n"
            "连续两周内累计迟到 3 至 4 次的，由班主任约谈学生并联系家长说明情况。\n"
            "连续一个月内累计迟到 5 次及以上，或迟到后伴随缺课、顶撞、逃避沟通等情形的，"
            "可由班主任联合年级组开展重点教育，并评估是否纳入持续关怀观察。\n"
            "若学生能够提供充分的健康、交通或家庭突发情况说明，应优先核实事实，不宜机械按违纪升级。"
        ),
    },
    {
        "category": "考勤",
        "title": "早退与旷课管理",
        "content": (
            "主题: 早退与旷课\n"
            "行为类型: early_leave absent truancy\n"
            "关键词: 早退,旷课,缺勤,离校,缺课,异常考勤\n"
            "家校联系: 无故早退或旷课建议及时联系家长\n"
            "关怀跟进: 如伴随安全风险或回避行为需同步关注\n"
            "学生未经批准不得擅自离校、早退或缺课。\n"
            "确需提前离校的，应由家长或监护人说明原因并完成请假登记。\n"
            "无故早退 1 次应由班主任核实情况并提醒。\n"
            "无故旷课或多次早退的，应及时通知家长，并按学校日常行为规范开展教育处理。\n"
            "如存在安全风险、同伴冲突或明显回避情形，应同步关注学生校园安全感和支持需求。"
        ),
    },
    {
        "category": "请假管理",
        "title": "请假遗漏与考勤例外判定",
        "content": (
            "主题: 请假例外与考勤纠偏\n"
            "行为类型: leave attendance exception\n"
            "关键词: 请假遗漏,考勤例外,病假,事假,补假,误判,例外处理\n"
            "家校联系: 由家长补充说明后可修正考勤判断\n"
            "关怀跟进: 健康与家庭突发情况需保留支持性判断\n"
            "教师发现学生出现迟到、缺勤、早退等异常考勤时，应先核实是否属于请假遗漏、临时陪诊、校内授权外出等例外情况。\n"
            "经家长、班主任或年级组补充说明属实的，可先完成补假或考勤纠偏，不宜直接按照违纪处理。\n"
            "若学生长期以模糊理由反复补假，仍应结合真实频次和沟通情况评估是否纳入重复性考勤异常管理。"
        ),
    },
    {
        "category": "课堂纪律",
        "title": "课堂迟到与课堂纪律",
        "content": (
            "主题: 课堂纪律与课堂迟到\n"
            "行为类型: classroom discipline late\n"
            "关键词: 课堂,课堂纪律,课堂迟到,喧哗,走动,扰乱秩序,顶撞\n"
            "家校联系: 重复发生且影响教学秩序时可联系家长\n"
            "关怀跟进: 若课堂问题与情绪或同伴冲突叠加应继续关注\n"
            "学生进入课堂后应遵守课堂纪律，不得迟到、随意走动、喧哗或影响教学秩序。\n"
            "课堂迟到的，由任课教师先核实原因并进行当场提醒。\n"
            "同一课程内重复出现课堂迟到、顶撞或扰乱秩序等行为的，可由班主任联合任课教师进行教育谈话。\n"
            "必要时应记录在班级纪律台账中，并视情况通知家长配合。"
        ),
    },
    {
        "category": "课堂纪律",
        "title": "课堂扰序与顶撞的升级处理",
        "content": (
            "主题: 课堂扰序升级处理\n"
            "行为类型: classroom disruption conflict escalation\n"
            "关键词: 扰乱秩序,顶撞老师,课堂冲突,升级处理,课堂纪律\n"
            "家校联系: 再次发生或影响课堂整体秩序时建议联系家长\n"
            "关怀跟进: 若伴随情绪激化或持续对抗行为建议继续关注\n"
            "课堂中出现扰乱秩序、故意打断教学、公开顶撞教师等行为时，任课教师应先稳定课堂并记录关键事实。\n"
            "首次且情节较轻的，可由任课教师课后教育提醒。\n"
            "再次发生、造成整节课教学中断，或伴随辱骂、摔物、拒绝离开冲突现场等行为的，应由班主任介入，并可视情况上报年级组。\n"
            "若学生在事后能够稳定沟通并说明有明显情绪诱因，可在纪律处理同时增加支持性沟通安排。"
        ),
    },
    {
        "category": "行为规范",
        "title": "手机与智能终端管理",
        "content": (
            "主题: 手机与电子终端管理\n"
            "行为类型: phone device smartwatch classroom\n"
            "关键词: 手机,电子设备,智能手表,终端,课堂使用手机\n"
            "家校联系: 再次违规或拒不配合时建议家长到校沟通\n"
            "关怀跟进: 若与安全求助或特殊健康需求有关应先核实背景\n"
            "学生原则上不得在教学时段擅自使用手机、智能手表或其他与学习无关的电子终端。\n"
            "课堂中发现使用手机的，应先制止并核实用途。\n"
            "首次违规以教育提醒为主，必要时由班主任登记并告知家长。\n"
            "再次违规或拒不配合管理的，可由家长到校沟通后领回相关物品，并纳入阶段性行为观察。\n"
            "若学生使用电子设备与安全求助、家校联络或特殊健康需求有关，应先核实具体背景后再作处理。"
        ),
    },
    {
        "category": "行为规范",
        "title": "手机使用的例外情形",
        "content": (
            "主题: 手机规则例外判断\n"
            "行为类型: phone exception safety health\n"
            "关键词: 手机例外,安全求助,健康需求,授权使用,紧急联系\n"
            "家校联系: 涉及临时授权或紧急联系时应同步核实家校口径\n"
            "关怀跟进: 若手机使用与安全焦虑、医疗提醒有关可继续关注\n"
            "学生在教学时段使用手机原则上应受限制，但遇到以下情形时应优先核实背景："
            "一是安全求助或家长紧急联系；二是医疗、心理支持或定位提醒等特殊健康需求；三是经教师临时授权用于学习任务。\n"
            "属于上述情形且证据充分的，不宜直接按普通违规手机使用处理。"
        ),
    },
    {
        "category": "行为规范",
        "title": "同伴冲突与欺凌苗头处置",
        "content": (
            "主题: 同伴冲突与欺凌苗头\n"
            "行为类型: conflict bullying threat safety\n"
            "关键词: 同伴冲突,欺凌,威胁,围堵,排斥,安全感\n"
            "家校联系: 涉及持续冲突或安全风险时应联系家长\n"
            "关怀跟进: 受影响学生宜进行持续支持性观察\n"
            "学生之间应文明交往，不得辱骂、威胁、排斥、起哄、围堵或实施肢体伤害。\n"
            "发现同伴冲突或疑似欺凌苗头时，教师应先保护学生安全，及时固定基本事实。\n"
            "涉及威胁、围堵、持续排斥或学生明显恐惧回避的，应尽快通知班主任、年级组或德育负责人。\n"
            "必要时应联系家长，并根据学校反欺凌要求启动后续跟进。\n"
            "对受影响学生的情绪状态和安全感，应同步给予支持性沟通与持续观察。"
        ),
    },
    {
        "category": "行为规范",
        "title": "安全风险与紧急上报规则",
        "content": (
            "主题: 安全事件紧急上报\n"
            "行为类型: safety emergency threat escalation\n"
            "关键词: 安全风险,紧急上报,威胁,围堵,伤害,应急处理\n"
            "家校联系: 涉及人身安全时应尽快通知家长\n"
            "关怀跟进: 事件后应对受影响学生开展持续支持\n"
            "若事件已涉及明确人身威胁、围堵、跟踪、肢体伤害风险或学生明确表达害怕独处、害怕放学离校，"
            "教师应优先按安全事件处置，不应只停留在一般纪律提醒层面。\n"
            "此类情形应及时通知班主任、年级组或德育负责人，并视情况联系家长到校协同。\n"
            "事件处理后仍需关注学生安全感和回避反应，必要时纳入持续关怀跟进。"
        ),
    },
    {
        "category": "家校协同",
        "title": "家校联系的一般原则",
        "content": (
            "主题: 家校联系原则\n"
            "行为类型: parent_contact communication\n"
            "关键词: 家校联系,联系家长,家校沟通,电话沟通,协同\n"
            "家校联系: 本条即为家校联系规则\n"
            "关怀跟进: 对情绪波动和安全问题建议同步支持性沟通\n"
            "教师在处理学生考勤异常、课堂纪律反复问题、明显情绪波动或安全相关事件时，可根据需要及时联系家长。\n"
            "家校联系应尽量说明客观事实、已采取的校内措施和期待的协同方式。\n"
            "对于首次、轻微且已现场纠正的问题，可先校内提醒。\n"
            "对于重复发生、影响学习秩序或涉及安全的情况，建议尽早与家长沟通。"
        ),
    },
    {
        "category": "家校协同",
        "title": "家校沟通的分层触发条件",
        "content": (
            "主题: 家校沟通触发阈值\n"
            "行为类型: parent_contact escalation threshold\n"
            "关键词: 家校沟通,触发条件,联系家长,重复发生,安全事件\n"
            "家校联系: 明确区分轻微提醒与必须沟通情形\n"
            "关怀跟进: 家校多次沟通仍反复时建议联动关怀\n"
            "以下情况通常应优先联系家长：一是两周内重复出现的考勤异常；二是课堂纪律反复且已影响教学秩序；"
            "三是涉及手机、冲突等问题并拒不配合管理；四是出现明显安全风险、欺凌苗头或持续情绪波动。\n"
            "以下情况可先校内教育后再观察：首次且轻微、已及时纠正、无重复趋势、无安全风险、学生沟通配合良好。"
        ),
    },
    {
        "category": "学生关怀",
        "title": "需要持续关怀跟进的情形",
        "content": (
            "主题: 持续关怀触发信号\n"
            "行为类型: care followup support risk\n"
            "关键词: 关怀跟进,情绪波动,回避,支持性沟通,持续观察\n"
            "家校联系: 必要时与家长保持同口径支持\n"
            "关怀跟进: 本条即为关怀判断规则\n"
            "当学生同时出现考勤波动、同伴冲突、情绪低落、明显回避、课堂状态下降等多项信号时，"
            "教师可在常规教育处理外，建议纳入持续关怀观察。\n"
            "关怀跟进以支持性沟通、问题识别和资源协调为主，不替代正式违纪认定。\n"
            "如事件已涉及校园安全、欺凌风险或家校多次沟通仍反复出现，应提升跟进优先级。"
        ),
    },
    {
        "category": "学生关怀",
        "title": "纪律处理与关怀跟进的边界",
        "content": (
            "主题: 纪律与关怀双轨处理\n"
            "行为类型: discipline care boundary\n"
            "关键词: 纪律处理,关怀跟进,双轨,边界,支持性判断\n"
            "家校联系: 家校沟通可同时服务于纪律说明和支持跟进\n"
            "关怀跟进: 不替代正式处分判断，但可并行开展\n"
            "当学生行为已构成明确纪律问题时，教师仍应依据校规完成记录、提醒或升级处理。\n"
            "若同时存在情绪波动、安全焦虑、同伴冲突、家庭压力或明显退缩等线索，"
            "可在纪律处理之外并行安排支持性沟通和关怀观察。\n"
            "纪律处理关注规则边界，关怀跟进关注原因理解与持续支持，两者不应相互替代。"
        ),
    },
    {
        "category": "请假管理",
        "title": "病假、事假与补假说明",
        "content": (
            "主题: 请假审批与补假\n"
            "行为类型: leave sick_leave personal_leave attendance\n"
            "关键词: 请假,病假,事假,补假,审批,返校,缺勤\n"
            "家校联系: 请假场景原则上由家长或监护人说明\n"
            "关怀跟进: 因健康或家庭突发情况造成的异常考勤需保留支持性判断\n"
            "学生请假应由家长或监护人提前向班主任说明。\n"
            "病假返校后应及时补充相关说明或证明材料。\n"
            "事假原则上应在离校前完成审批。\n"
            "未按流程说明而缺勤的，应先核实是否属于请假遗漏，再判断是否纳入考勤异常。\n"
            "对于因健康、家庭突发情况导致的异常考勤，教师应在制度执行外保留必要的支持性判断。"
        ),
    },
    {
        "category": "角色分工",
        "title": "任课教师、班主任与年级组职责分工",
        "content": (
            "主题: 处置角色分工\n"
            "行为类型: role responsibility workflow\n"
            "关键词: 任课教师,班主任,年级组,职责分工,升级上报,角色\n"
            "家校联系: 通常由班主任主导统一口径\n"
            "关怀跟进: 班主任可发起，必要时联动专门人员\n"
            "任课教师主要负责课堂现场管理、事实记录与首次提醒。\n"
            "班主任主要负责重复问题跟进、家校沟通、学生阶段性行为判断与班级台账记录。\n"
            "年级组或德育负责人主要负责跨班级、涉及安全风险、重复升级或需统一处置口径的事件。\n"
            "对于普通轻微问题，不宜一开始直接上升到年级组；对于安全事件、欺凌苗头、反复无效个案，应及时升级上报。"
        ),
    },
]


def build_seed_title(title: str) -> str:
    return f"{TEST_RULE_PREFIX} {title}"


def build_seed_content(content: str) -> str:
    return f"{TEST_RULE_MARKER}\n{content}"


def get_seed_operator_id(db) -> int | None:
    admin = db.query(User).filter(User.username == "admin").first()
    if admin:
        return admin.id
    teacher = db.query(User).filter(User.role == "teacher").order_by(User.id.asc()).first()
    if teacher:
        return teacher.id
    return None


def seed_rules() -> None:
    db = SessionLocal()
    try:
        updated_by = get_seed_operator_id(db)
        touched_rule_ids: list[int] = []

        for item in TEST_RULES:
            seed_title = build_seed_title(item["title"])
            seed_content = build_seed_content(item["content"])
            rule = db.query(SchoolRule).filter(SchoolRule.title == seed_title).first()
            if not rule:
                rule = SchoolRule(
                    category=item["category"],
                    title=seed_title,
                    content=seed_content,
                    updated_by=updated_by,
                )
                db.add(rule)
                db.commit()
                db.refresh(rule)
                print(f"[seed] created rule #{rule.id}: {seed_title}")
            else:
                rule.category = item["category"]
                rule.content = seed_content
                rule.updated_by = updated_by
                db.commit()
                db.refresh(rule)
                print(f"[seed] updated rule #{rule.id}: {seed_title}")

            touched_rule_ids.append(rule.id)
            rebuild_rule_index(db, rule.id)

        print(f"[seed] completed, touched {len(touched_rule_ids)} test rules")
    finally:
        db.close()


def cleanup_rules() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(SchoolRule)
            .filter(
                SchoolRule.title.like(f"{TEST_RULE_PREFIX}%"),
                SchoolRule.content.like(f"{TEST_RULE_MARKER}%"),
            )
            .all()
        )
        if not rows:
            print("[cleanup] no seeded test rules found")
            return

        rule_ids = [row.id for row in rows]
        for row in rows:
            print(f"[cleanup] deleting rule #{row.id}: {row.title}")
            db.delete(row)
        db.commit()

        for rule_id in rule_ids:
            delete_rule_index(db, rule_id)

        print(f"[cleanup] removed {len(rule_ids)} test rules")
    finally:
        db.close()


def main() -> None:
    if "--cleanup" in sys.argv:
        cleanup_rules()
        return
    seed_rules()


if __name__ == "__main__":
    main()
