# -*- coding: utf-8 -*-
"""
公共依赖注入模块
================
定义 FastAPI 的 Depends 公共依赖：
- get_db: 获取数据库会话
- get_current_user: 从JWT token解析当前登录用户，校验token有效性
- require_role: 角色权限校验装饰器/依赖，支持指定允许的角色列表
  所有需要鉴权的路由都应依赖 get_current_user，需要特定角色的路由额外依赖 require_role。
"""

from fastapi import Depends, HTTPException, status, Header
from jose import JWTError
from sqlalchemy.orm import Session

from core.security import decode_access_token
from database.connection import get_db as raw_get_db
from database.models.user import User
from services.student_schema_guard import ensure_student_schema


def get_db():
    ensure_student_schema()
    yield from raw_get_db()


def get_current_user(
    db: Session = Depends(get_db),
    authorization: str = Header(None, description="Bearer token"),
) -> User:
    """
    从 JWT token 解析并返回当前登录用户
    
    Args:
        db: 数据库会话
        authorization: Authorization header (Bearer token)
    
    Returns:
        User: 当前登录用户对象
    
    Raises:
        HTTPException: 401 未授权错误
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not authorization or not authorization.startswith("Bearer "):
        raise credentials_exception
    
    token = authorization[7:]  # Remove "Bearer " prefix
    
    try:
        payload = decode_access_token(token)
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        # JWT中的sub是字符串，需要转换为整数
        user_id: int = int(user_id_str)
    except (JWTError, ValueError, TypeError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user


def require_role(*roles: str):
    """角色权限校验依赖工厂函数，返回一个依赖函数。"""

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        """校验当前用户是否具有指定角色之一。"""
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )
        return current_user

    return role_checker
