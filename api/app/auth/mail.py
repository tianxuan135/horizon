"""邮件发送（仅标准库 ``smtplib``）。

仅当 ``settings.smtp_host`` 配置时才启用；``settings.email_verification_required``
即 ``bool(smtp_host)``。未配置时注册直接返回 ``requiresVerification:false``。
任何发送异常都被捕获并转成 ``(False, 原因)``，绝不把 SMTP 密码写进日志。
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from ..config import settings

SUBJECT = "Horizon 极目楚天 · 邮箱验证码"


def smtp_configured() -> bool:
    """SMTP 是否可用（决定注册是否需要邮箱验证）。"""
    return bool(settings.smtp_host)


def _body(code: str) -> tuple[str, str]:
    text = (
        "你好，\n\n"
        f"你在 Horizon 极目楚天 的验证码是：{code}\n"
        "验证码 10 分钟内有效，仅可使用一次。\n\n"
        "如果这不是你本人的操作，请忽略本邮件。\n"
        "Horizon 只提供研究与行情分析，不提供任何交易下单能力。\n"
    )
    html = (
        "<div style=\"font-family:system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.6\">"
        "<p>你好，</p>"
        "<p>你在 <b>Horizon 极目楚天</b> 的验证码是：</p>"
        f"<p style=\"font-size:24px;letter-spacing:6px;font-weight:700\">{code}</p>"
        "<p>验证码 10 分钟内有效，仅可使用一次。若这不是你本人的操作，请忽略本邮件。</p>"
        "<p style=\"color:#666;font-size:12px\">Horizon 只提供研究与行情分析，不提供任何交易下单能力。</p>"
        "</div>"
    )
    return text, html


def send_verification_code(email: str, code: str) -> tuple[bool, str]:
    """发送验证码邮件，返回 ``(是否成功, 说明)``。"""
    if not smtp_configured():
        return False, "未配置 SMTP（HORIZON_SMTP_HOST），邮件验证未启用"
    msg = EmailMessage()
    msg["Subject"] = SUBJECT
    from_addr = settings.smtp_from or settings.smtp_user or "no-reply@horizon.local"
    msg["From"] = formataddr(("Horizon 极目楚天", from_addr))
    msg["To"] = email
    text, html = _body(code)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    host = settings.smtp_host
    port = int(settings.smtp_port or 587)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=12, context=ssl.create_default_context()) as s:
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password or "")
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=12) as s:
                s.ehlo()
                try:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                except smtplib.SMTPException:
                    pass  # 服务端不支持 STARTTLS 时退回明文（仅内网自建场景）
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password or "")
                s.send_message(msg)
        return True, f"验证码已发送至 {email}"
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        return False, f"邮件发送失败：{type(exc).__name__}: {exc}"