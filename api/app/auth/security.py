"""密码散列与 Bearer 令牌（API_CONTRACT §7）——**只用标准库**。

密码
====
``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``，其中
``hashlib.pbkdf2_hmac("sha256", password, salt, 200_000)``，每个用户独立随机
16 字节盐。故意不引入 passlib/bcrypt（项目硬性要求：不新增依赖）。

令牌
====
紧凑的自签名令牌，形如 ``h1.<b64url(payload)>.<b64url(hmac_sha256)>``：

* ``payload = {"sub": user_id, "email": ..., "iat": ts, "exp": ts}``（JSON，无填充 base64url）
* 签名密钥见 ``signing_secret()``：优先环境变量 ``JWT_SECRET``（``settings.jwt_secret``，无前缀）；未配置时使用
  持久化的 ``api/.horizon_secret``（首次自动生成），保证 uvicorn 重启 / 多 worker
  后已签发令牌仍然有效
* 校验：签名用 ``hmac.compare_digest`` 常数时间比较；``exp`` 以 ``time.time()`` 判断过期
* 有效期 ``settings.token_ttl_hours``（默认 72 小时）

这不是 JWT 库的替代品：没有 ``alg`` 协商、只有 HMAC-SHA256 一种算法，
因此不存在 ``alg=none`` 类降级攻击面。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from pathlib import Path

from ..config import settings

log = logging.getLogger("horizon.auth.security")




PBKDF2_ALGO = "sha256"
PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16
PW_SCHEME = "pbkdf2_sha256"
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 256
TOKEN_VERSION = "h1"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

_SECRET_CACHE: bytes | None = None
_SECRET_FILE = Path(__file__).resolve().parents[2] / ".horizon_secret"


def signing_secret() -> bytes:
    """签名密钥。

    优先环境变量 ``JWT_SECRET``；未配置时使用 ``api/.horizon_secret`` 里**持久化**的
    随机密钥（首次自动生成），这样 uvicorn 重启 / 多 worker 下已签发令牌仍然有效。
    ``Settings.secret`` 属性每次访问都会重新随机（不持久），单独用它会导致
    "刚签发的令牌立刻验签失败"，因此这里必须自己做一层稳定化。
    """
    global _SECRET_CACHE
    if _SECRET_CACHE is not None:
        return _SECRET_CACHE
    configured = (getattr(settings, "jwt_secret", "") or "").strip()
    if configured:
        _SECRET_CACHE = configured.encode("utf-8")
        return _SECRET_CACHE
    try:
        if _SECRET_FILE.exists():
            raw = _SECRET_FILE.read_text(encoding="utf-8").strip()
        else:
            raw = secrets.token_hex(32)
            _SECRET_FILE.write_text(raw + "\n", encoding="utf-8")
        if raw:
            _SECRET_CACHE = raw.encode("utf-8")
            return _SECRET_CACHE
    except OSError:
        log.warning("signing_secret: cannot persist %s, tokens will not survive restart", _SECRET_FILE)
    _SECRET_CACHE = str(settings.secret).encode("utf-8")
    return _SECRET_CACHE


# --------------------------------------------------------------------------- #
# 密码
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """生成 ``pbkdf2_sha256$200000$salt$hash`` 形式的密码散列（含随机盐）。"""
    if not isinstance(password, str) or not password:
        raise ValueError("密码不能为空")
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(PBKDF2_ALGO, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{PW_SCHEME}${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码；任何格式异常一律返回 False（不泄漏内部状态）。"""
    try:
        scheme, iter_s, salt_hex, hash_hex = (stored or "").split("$")
        if scheme != PW_SCHEME:
            return False
        iterations = int(iter_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac(PBKDF2_ALGO, (password or "").encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


def password_problem(password: str) -> str | None:
    """返回不合规原因，合规返回 None（路由层转 400）。"""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LEN:
        return f"密码长度至少 {MIN_PASSWORD_LEN} 位"
    if len(password) > MAX_PASSWORD_LEN:
        return f"密码长度不能超过 {MAX_PASSWORD_LEN} 位"
    if password.strip() != password:
        return "密码首尾不能有空白字符"
    return None


def normalize_email(email: str) -> str:
    """邮箱规范化：去空白 + 转小写（存储与查重都用规范形式）。"""
    return (email or "").strip().lower()


def email_problem(email: str) -> str | None:
    """邮箱格式检查。"""
    e = normalize_email(email)
    if not e:
        return "邮箱不能为空"
    if len(e) > 254 or not _EMAIL_RE.match(e):
        return "邮箱格式不正确"
    return None


# --------------------------------------------------------------------------- #
# 令牌
# --------------------------------------------------------------------------- #
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(payload_b64: str) -> str:
    mac = hmac.new(signing_secret(), payload_b64.encode("ascii"), hashlib.sha256)
    return _b64e(mac.digest())


def create_token(user_id: str, email: str, ttl_hours: int | None = None) -> str:
    """签发 Bearer 令牌，过期时间 = now + ``token_ttl_hours``。"""
    ttl = settings.token_ttl_hours if ttl_hours is None else int(ttl_hours)
    now = int(time.time())
    payload = {"sub": user_id, "email": email, "iat": now, "exp": now + max(1, ttl) * 3600}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_b64 = _b64e(raw)
    return f"{TOKEN_VERSION}.{payload_b64}.{_sign(payload_b64)}"


def decode_token(token: str) -> dict:
    """校验令牌并返回 payload；无效/过期/签名不符抛 ``ValueError``（路由层转 401）。"""
    parts = (token or "").split(".")
    if len(parts) != 3 or parts[0] != TOKEN_VERSION:
        raise ValueError("令牌格式不正确")
    _, payload_b64, sig = parts
    if not hmac.compare_digest(sig, _sign(payload_b64)):
        raise ValueError("令牌签名校验失败")
    try:
        payload = json.loads(_b64d(payload_b64))
    except (ValueError, json.JSONDecodeError):
        raise ValueError("令牌内容已损坏") from None
    if not isinstance(payload, dict) or "sub" not in payload:
        raise ValueError("令牌缺少 sub 声明")
    if int(payload.get("exp", 0)) <= int(time.time()):
        raise ValueError("令牌已过期，请重新登录")
    return payload


def bearer_token(authorization: str | None) -> str:
    """从 ``Authorization: Bearer xxx`` 头取出令牌，缺失抛 ``ValueError``。"""
    raw = (authorization or "").strip()
    if not raw:
        raise ValueError("缺少 Authorization 头（Bearer 令牌）")
    scheme, _, rest = raw.partition(" ")
    if scheme.lower() != "bearer" or not rest.strip():
        raise ValueError("Authorization 头必须是 Bearer <token> 形式")
    return rest.strip()


def verification_code(length: int = 6) -> str:
    """生成数字验证码（密码学随机）。"""
    return "".join(secrets.choice("0123456789") for _ in range(length))
