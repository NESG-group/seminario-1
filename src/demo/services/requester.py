"""Who is asking: the Open WebUI user behind the chat that is running.

Multi-user mode is on when ``settings.user_jwt_secret`` is set. Open WebUI then
signs each request with that secret (``X-OpenWebUI-User-Jwt``) and the backend
verifies it.

The MCP tools are called by Hermes, not by the user, so they cannot see that
header. Instead the backend runs one chat at a time and records whose it is
while it runs (``acting_as``); the tools read it with ``current_requester``.
Serialising costs no throughput: Ollama serves one request at a time anyway.

Known limit: if a client disconnects, the next chat starts as soon as the
backend stops relaying, even if Hermes has not finished the abandoned run.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final

import jwt

from demo.config import settings

USER_JWT_HEADER: Final[str] = "X-OpenWebUI-User-Jwt"
_ISSUER: Final[str] = "open-webui"


@dataclass(frozen=True, slots=True)
class Requester:
    """An Open WebUI user, as asserted by a verified JWT."""

    user_id: str
    email: str


class RequesterError(ValueError):
    """The request carries no valid user identity."""


_chat_lock = asyncio.Lock()
_current: Requester | None = None


def multi_user_enabled() -> bool:
    return bool(settings.user_jwt_secret)


def verify_user_jwt(token: str | None) -> Requester:
    """Return the user a forwarded Open WebUI JWT asserts, or raise RequesterError."""
    secret = settings.user_jwt_secret
    if not secret:
        raise RequesterError("multi-user mode is off (no user_jwt_secret)")
    if not token:
        raise RequesterError(f"missing {USER_JWT_HEADER} header")
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=_ISSUER,
            options={"require": ["sub", "exp", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise RequesterError(f"invalid {USER_JWT_HEADER}: {exc}") from exc
    return Requester(user_id=str(claims["sub"]), email=str(claims.get("email", "")))


@asynccontextmanager
async def acting_as(requester: Requester | None) -> AsyncIterator[None]:
    """Run a chat on behalf of ``requester``; chats of different users never overlap.

    With ``None`` (single-user mode) nothing is serialised or recorded.
    """
    global _current
    if requester is None:
        yield
        return
    async with _chat_lock:
        _current = requester
        try:
            yield
        finally:
            _current = None


def current_requester() -> Requester | None:
    """The user whose chat is running, or None if no chat is running."""
    return _current
