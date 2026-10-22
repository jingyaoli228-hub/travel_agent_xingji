"""Single-owner WeChat login and short-lived API token helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from travel_agent.config.settings import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
TOKEN_TTL_SECONDS = 60 * 60 * 12


class WeChatLoginRequest(BaseModel):
    code: str


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def issue_token(openid: str, secret: str, now: int | None = None) -> str:
    payload = _encode(json.dumps({"sub": openid, "exp": (now or int(time.time())) + TOKEN_TTL_SECONDS}, separators=(",", ":")).encode())
    signature = _encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_token(token: str, secret: str, now: int | None = None) -> dict[str, Any] | None:
    try:
        payload, signature = token.split(".", 1)
        expected = _encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(raw)
        if int(claims.get("exp", 0)) <= (now or int(time.time())) or not claims.get("sub"):
            return None
        return claims
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


@router.post("/wechat")
async def wechat_login(request: WeChatLoginRequest) -> dict[str, Any]:
    settings = get_settings()
    if not all((settings.wechat_app_id, settings.wechat_app_secret, settings.owner_openid, settings.auth_token_secret)):
        raise HTTPException(503, detail="微信自用登录尚未配置")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get("https://api.weixin.qq.com/sns/jscode2session", params={
            "appid": settings.wechat_app_id, "secret": settings.wechat_app_secret,
            "js_code": request.code, "grant_type": "authorization_code",
        })
    if response.is_error:
        raise HTTPException(502, detail="微信登录服务暂不可用")
    result = response.json()
    openid = result.get("openid")
    if result.get("errcode") or not openid:
        raise HTTPException(401, detail="微信登录凭证已失效，请重试")
    if not hmac.compare_digest(str(openid), settings.owner_openid):
        raise HTTPException(403, detail="此体验版仅允许所有者微信使用")
    return {"access_token": issue_token(openid, settings.auth_token_secret), "expires_in": TOKEN_TTL_SECONDS, "user_id": openid}
