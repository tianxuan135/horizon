"""账号路由（API_CONTRACT §7）。

* ``POST /register``  ``{email,password}`` → ``{ok,requiresVerification}``
* ``POST /login``     ``{email,password}`` → ``{token,user:{id,email}}``
* ``POST /verify``    ``{email,code}``     → ``{ok}``
* ``GET  /me``        ``Authorization: Bearer`` → ``{id,email,market}``

安全要点（实现见 ``app/auth/security.py``）：
密码用标准库 ``hashlib.pbkdf2_hmac("sha256", …, 200_000)`` + 每用户随机盐，
不引入 passlib/bcrypt；令牌是 HMAC-SHA256 签名的紧凑令牌（密钥 ``settings.secret``，
有效期 ``settings.token_ttl_hours``）。邮箱验证仅在配置了 SMTP
（``settings.email_verification_required``）时启用；未配置时注册直接可用。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..analytics.common import utc_now_iso
from ..auth.mail import send_verification_code, smtp_configured
from ..auth.security import (
    bearer_token,
    create_token,
    decode_token,
    email_problem,
    hash_password,
    normalize_email,
    password_problem,
    verification_code,
    verify_password,
)
from ..config import settings
from ..db import get_db
from ..models import User, VerificationCode

log = logging.getLogger("horizon.auth")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

CODE_TTL_MINUTES = 10
MARKETS = ("us", "cn")


class RegisterIn(BaseModel):
    """注册请求体。"""

    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)
    market: str = Field("us", max_length=8)


class LoginIn(BaseModel):
    """登录请求体。"""

    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)


class VerifyIn(BaseModel):
    """验证码校验请求体。"""

    email: str = Field(..., max_length=254)
    code: str = Field(..., max_length=12)


def _user_public(user: User) -> dict:
    return {"id": user.id, "email": user.email, "market": user.market, "verified": bool(user.verified)}


def _issue_code(db: Session, email: str) -> str:
    """作废旧码、写入新验证码（10 分钟有效），返回明文码。"""
    olds = db.scalars(
        select(VerificationCode).where(VerificationCode.email == email, VerificationCode.consumed == 0)
    ).all()
    for row in olds:
        row.consumed = 1
    code = verification_code()
    db.add(
        VerificationCode(
            email=email,
            code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MINUTES),
        )
    )
    db.commit()
    return code


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite 读回来的 DateTime 通常是 naive，统一按 UTC 处理。"""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _require_auth_enabled() -> None:
    """开源部署默认关闭账号体系。

    规格：邮箱注册/登录为可选功能，自托管默认关闭；部署者配置 SMTP_* 并将
    AUTH_ENABLED 设为 true 后才启用。关闭状态下分析功能不受任何影响。
    """
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=403,
            detail=(
                "本部署未开启认证（AUTH_ENABLED=false）。如需邮箱注册登录，"
                "请配置 SMTP_HOST / SMTP_USER / SMTP_PASSWORD 并将 AUTH_ENABLED 设为 true；"
                "全部分析功能无需登录即可使用。"
            ),
        )


@router.get("/config")
def config() -> dict:
    """前端用来决定是否显示"验证邮箱"步骤（不泄漏任何服务器细节）。"""
    return {
        "asOf": utc_now_iso(),
        "authEnabled": bool(settings.auth_enabled),
        "requiresVerification": smtp_configured(),
        "tokenTtlHours": int(settings.token_ttl_hours),
    }


@router.post("/register")
def register(
    body: RegisterIn,
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_auth_enabled),
) -> dict:
    """注册账号。配置了 SMTP 时发送验证码并返回 ``requiresVerification:true``。"""
    email = normalize_email(body.email)
    problem = email_problem(email) or password_problem(body.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    market = (body.market or "us").strip().lower()
    if market not in MARKETS:
        raise HTTPException(status_code=400, detail=f"market 必须是 {MARKETS}，收到 {body.market!r}")

    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="该邮箱已注册，请直接登录")

    requires = smtp_configured()
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        market=market,
        verified=0 if requires else 1,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该邮箱已注册，请直接登录") from None
    db.refresh(user)

    if not requires:
        token = create_token(user.id, user.email)
        return {
            "asOf": utc_now_iso(),
            "ok": True,
            "requiresVerification": False,
            "token": token,
            "user": _user_public(user),
        }

    code = _issue_code(db, email)
    sent, detail = send_verification_code(email, code)
    if not sent:
        # 邮件发不出时不留半成品账号，让用户重试
        log.error("register: verification mail failed for %s: %s", email, detail)
        for row in db.scalars(select(VerificationCode).where(VerificationCode.email == email)).all():
            db.delete(row)
        db.delete(user)
        db.commit()
        raise HTTPException(status_code=503, detail=f"验证邮件发送失败，请稍后重试（{detail}）")

    return {
        "asOf": utc_now_iso(),
        "ok": True,
        "requiresVerification": True,
        "emailSent": True,
        "message": f"验证码已发送至 {email}，{CODE_TTL_MINUTES} 分钟内有效",
    }


@router.post("/login")
def login(
    body: LoginIn,
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_auth_enabled),
) -> dict:
    """邮箱 + 密码登录，返回 Bearer 令牌。"""
    email = normalize_email(body.email)
    if not email or not body.password:
        raise HTTPException(status_code=400, detail="邮箱和密码都不能为空")
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    if smtp_configured() and not user.verified:
        raise HTTPException(status_code=403, detail="邮箱尚未验证，请先完成验证码校验")
    token = create_token(user.id, user.email)
    return {
        "asOf": utc_now_iso(),
        "token": token,
        "tokenType": "Bearer",
        "expiresInHours": int(settings.token_ttl_hours),
        "user": {"id": user.id, "email": user.email, "market": user.market},
    }


@router.post("/verify")
def verify(
    body: VerifyIn,
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_auth_enabled),
) -> dict:
    """校验邮箱验证码，成功后账号可用。"""
    email = normalize_email(body.email)
    code = (body.code or "").strip()
    if not email or not code:
        raise HTTPException(status_code=400, detail="邮箱和验证码都不能为空")
    rows = db.scalars(
        select(VerificationCode)
        .where(VerificationCode.email == email, VerificationCode.consumed == 0)
        .order_by(VerificationCode.expires_at.desc())
    ).all()
    if not rows:
        raise HTTPException(status_code=400, detail="验证码不存在或已使用，请重新获取")
    now = datetime.now(timezone.utc)
    row = rows[0]
    exp = _aware(row.expires_at)
    if exp is not None and exp <= now:
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")
    if row.code != code:
        raise HTTPException(status_code=400, detail="验证码不正确")
    row.consumed = 1
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        user.verified = 1
    db.commit()
    return {"asOf": utc_now_iso(), "ok": True, "email": email}


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """依赖：从 Bearer 令牌解析当前用户；任何异常一律 401。"""
    try:
        token = bearer_token(authorization)
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = db.get(User, str(payload.get("sub")))
    if user is None:
        raise HTTPException(status_code=401, detail="令牌对应的账号不存在")
    return user


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    """当前登录用户信息（契约：``{id,email,market}``）。"""
    return {"asOf": utc_now_iso(), "id": user.id, "email": user.email, "market": user.market,
            "verified": bool(user.verified)}