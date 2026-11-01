"""全局配置。

合规要点：所有数据源凭据只能来自环境变量 / .env（见仓库根 .env.example），
代码中不得出现任何硬编码的 API Key、账号密码或 JWT Secret。
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENV_FILES = (os.path.join(REPO_ROOT, ".env"), os.path.join(os.path.dirname(__file__), "..", ".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore")

    # 运行
    env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # 数据存储
    database_url: str = "sqlite:///./horizon.db"
    redis_url: str = ""

    # 数据源（全部可选，缺省时后端自动降级为 synthetic 并在 /meta/status 中标注）
    yahoo_enabled: bool = True
    akshare_enabled: bool = True
    tushare_token: str = ""
    finnhub_key: str = ""

    # 认证
    # 开源部署默认关闭账号体系；配置 SMTP_* 后由部署者显式设为 true
    auth_enabled: bool = False
    token_ttl_hours: int = 72
    # 生产必须通过环境变量注入；开发环境自动派生随机值，绝不写死在代码里
    jwt_secret: str = ""

    # 邮件验证码（默认关闭，仅在配置 SMTP 后启用）
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@horizon.local"

    @property
    def secret(self) -> str:
        """签名密钥：优先环境变量 JWT_SECRET；缺失时使用进程内缓存的随机值。

        必须在进程内只生成一次（原实现每次访问都重新随机，导致刚签发的令牌
        立刻验签失败）。多进程/多副本部署务必显式设置 JWT_SECRET。
        """
        return self.jwt_secret or _fallback_secret()

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def email_verification_required(self) -> bool:
        return bool(self.smtp_host)


_FALLBACK_SECRET: str | None = None


def _fallback_secret() -> str:
    global _FALLBACK_SECRET
    if _FALLBACK_SECRET is None:
        _FALLBACK_SECRET = secrets.token_urlsafe(32)
    return _FALLBACK_SECRET


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()