# -*- coding: utf-8 -*-
"""Bayesian helper config for student care.

改进版本 v2.0:
- 扩展social维度证据规则
- 添加保护性证据(LR<1)
- 优化似然比取值

似然比含义:
- LR > 1: 证据支持风险存在（数值越大，支持力度越强）
- LR = 1: 证据与风险无关
- LR < 1: 证据反对风险存在（保护性证据）
"""

STUDENT_CARE_BAYES_CONFIG = {
    "emotion": {
        "enabled": True,
        "prior": 0.15,
        "description": "情绪风险维度：基于情绪低落、焦虑、压力等信号",
        "evidence_rules": {
            # 负向证据 (LR > 1): 支持风险存在
            "score_drop_emotion": 1.8,              # 成绩下滑诱发情绪变化
            "attendance_worried_remark": 1.9,       # 出勤记录中有担忧表达
            "assistant_self_report_distress": 2.8, # AI对话中出现低落表达
            "care_observation_emotion": 2.4,        # 教师观察记录情绪异常
            "care_talk_low_mood": 2.1,              # 关怀谈话中情绪低落
            "family_negative_contact": 1.6,         # 家校沟通显示压力
            # 保护性证据 (LR < 1): 降低风险
            "care_talk_positive": 0.5,              # 关怀谈话显示情绪好转
            "assistant_positive_mood": 0.55,        # AI对话中正向情绪表达
            # 教师确认
            "teacher_review_resolved": 0.5,         # 教师确认已解决
            "teacher_review_false_alarm": 0.4,      # 教师确认为误报
        },
    },
    "family": {
        "enabled": True,
        "prior": 0.14,
        "description": "家庭支持维度：基于家庭困难、支持不足等信号",
        "evidence_rules": {
            # 负向证据
            "tag_family_hardship": 1.8,              # 学生标签：家庭困难
            "family_contact_negative": 2.3,          # 家校沟通显示支持不足
            "family_violence_hint": 2.8,             # 家庭暴力线索
            "attendance_family_issue": 1.7,          # 出勤记录涉及家庭问题
            "assistant_family_distress": 2.0,        # AI对话中的家庭困扰
            # 教师确认
            "teacher_review_resolved": 0.45,
            "teacher_review_false_alarm": 0.35,
        },
    },
    "social": {
        "enabled": True,
        "prior": 0.10,
        "description": "社交融入维度：基于同伴关系、社交孤立等信号",
        "evidence_rules": {
            # 负向证据 (LR > 1)
            "graph_social_isolation": 2.0,              # 图谱显示社交孤立
            "graph_manual_conflict": 1.7,               # 手工添加的社交冲突
            "social_difficulty_report": 2.3,            # 明确的社交困难报告
            "care_observation_social": 1.8,             # 教师社交观察异常
            "assistant_social_distress": 2.2,           # AI对话中社交困扰
            # 保护性证据 (LR < 1)
            "care_observation_positive_social": 0.55,   # 社交状态改善观察
            "graph_peer_support": 0.5,                  # 图谱显示同伴支持
            "assistant_positive_social": 0.6,           # AI对话显示社交改善
            # 教师确认
            "teacher_review_resolved": 0.55,
            "teacher_review_false_alarm": 0.45,
        },
    },
    "safety": {
        "enabled": True,
        "prior": 0.12,
        "description": "安全风险维度：基于冲突、欺凌、威胁等信号",
        "evidence_rules": {
            # 负向证据 (LR > 1)
            "assistant_self_report_assault": 4.5,   # AI对话自述受攻击（最强证据）
            "behavior_bullying": 3.8,               # 行为事件：欺凌
            "attendance_bruise_remark": 3.0,        # 出勤记录有淤青描述
            "behavior_conflict": 2.2,               # 行为事件：冲突
            "family_violence_hint": 2.4,            # 家庭暴力线索
            "graph_conflict_cooccurrence": 1.9,     # 图谱冲突共现
            "attendance_worried_remark": 1.6,       # 出勤记录有担忧表达
            # 教师确认
            "teacher_review_resolved": 0.35,
            "teacher_review_false_alarm": 0.15,
        },
    }
}
