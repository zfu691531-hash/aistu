# -*- coding: utf-8 -*-
"""
期末评语生成工具
================
根据学生信息生成个性化期末评语，支持单个和批量班级生成。
"""

from typing import Optional, List
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.models.student import Student
from database.models.class_ import Class
from database.models.score import Score
from database.models.user import User
from services.ai.base import ai_client, save_history
from services.ai.student_profile_context import build_student_profile_context
from core.response import success_response, error_response
from utils.logger import logger


class CommentRequest(BaseModel):
    """评语生成请求"""
    student_id: Optional[int] = Field(None, description="学生ID（单个生成）")
    class_id: Optional[int] = Field(None, description="班级ID（批量生成）")
    style: str = Field("鼓励型", description="评语风格：鼓励型/客观型/建议型")
    semester: str = Field(..., description="学期，如：2024-2025学年第一学期")


async def generate_comment(
    db: Session,
    current_user: User,
    request: CommentRequest,
) -> dict:
    """
    生成期末评语
    
    Args:
        db: 数据库会话
        current_user: 当前用户
        request: 请求参数
    
    Returns:
        dict: 生成结果
    """
    results = []
    
    # 单个学生生成
    if request.student_id:
        student = db.query(Student).filter(Student.id == request.student_id).first()
        if not student:
            return error_response(msg="学生不存在")
        
        result = await _generate_single(db, student, request)
        results.append(result)
        
        # 保存历史
        save_history(
            db=db,
            user_id=current_user.id,
            tool_type="comment",
            input_params=request.model_dump(),
            content=result,
            student_id=student.id,
            class_id=student.class_id,
        )
    
    # 批量班级生成
    elif request.class_id:
        students = db.query(Student).filter(Student.class_id == request.class_id).all()
        if not students:
            return error_response(msg="班级内无学生")
        
        for student in students:
            result = await _generate_single(db, student, request)
            results.append({
                "student_id": student.id,
                "student_name": student.name,
                "comment": result,
            })
        
        # 保存历史（批量）
        save_history(
            db=db,
            user_id=current_user.id,
            tool_type="comment",
            input_params=request.model_dump(),
            content=f"批量生成 {len(results)} 条评语",
            class_id=request.class_id,
        )
    
    else:
        return error_response(msg="请指定学生ID或班级ID")
    
    return success_response(data=results if len(results) > 1 else results[0])


async def _generate_single(
    db: Session,
    student: Student,
    request: CommentRequest,
) -> str:
    """生成单个学生评语"""
    # 查询班级名称
    class_name = ""
    if student.class_id:
        class_obj = db.query(Class).filter(Class.id == student.class_id).first()
        class_name = class_obj.name if class_obj else ""
    
    # 查询成绩
    scores = db.query(Score).filter(Score.student_id == student.id).all()
    score_info = ""
    if scores:
        score_list = [f"{s.subject}:{float(s.score)}分" for s in scores[-5:]]  # 最近5条
        score_info = "近期成绩：" + "、".join(score_list)

    profile_context = build_student_profile_context(db, student)
    
    # 构建提示词
    system_prompt = f"""你是一位经验丰富、善于发现学生闪光点的班主任。
请根据学生信息、近期成绩和学生状态摘要撰写一份{request.style}期末评语。
要求：
1. 语言亲切自然，避免套话
2. 突出学生个性特点
3. 肯定优点，委婉指出不足，并给出简短、温和的成长建议
4. 如果学生近期状态有波动，请转化成支持性表达，不要直接提及画像分数、风险等级或敏感标签
5. 可适度加入老师视角的关怀感和陪伴感
6. 字数150-220字"""

    user_prompt = f"""学生信息：
- 姓名：{student.name}
- 班级：{class_name}
- 性别：{"男" if student.gender == "male" else "女"}
- 特长：{student.specialty or "无"}
- 标签：{student.tags or "无"}
- {score_info}
- 学期：{request.semester}

学生关怀状态摘要：
{profile_context["prompt_block"]}

请为该学生撰写期末评语。"""

    result = await ai_client.call(system_prompt, user_prompt)
    return result
