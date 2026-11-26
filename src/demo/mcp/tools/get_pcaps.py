from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select

from demo.db.models import Capture
from demo.db.session import get_session
from demo.services.requester import current_requester, multi_user_enabled


class CaptureSummary(BaseModel):
    """Minimal identifying info for a stored capture."""

    capture_id: uuid.UUID
    event_start: datetime
    event_end: datetime


class CaptureNotFoundError(ValueError):
    """Raised when `capture_id` has no matching row in the datalake."""


_NO_OWNER: object = object()


def _visible_owner() -> str | None | object:
    """Owner the caller may see: ``None`` = everything (single-user mode),
    ``_NO_OWNER`` = nothing (multi-user mode with no chat running), else a user id."""
    if not multi_user_enabled():
        return None
    requester = current_requester()
    return _NO_OWNER if requester is None else requester.user_id


async def get_capture_file_path(capture_id: uuid.UUID) -> str:
    """Resolve the on-disk path of a registered capture.

    In multi-user mode only captures of the user whose chat is running resolve.

    Raises:
        CaptureNotFoundError: if `capture_id` has no catalog row, or it belongs
            to another user (reported the same way, so ids do not leak).
    """
    owner = _visible_owner()
    async with get_session() as session:
        capture = await session.get(Capture, capture_id)
    if capture is None or (owner is not None and capture.owner != owner):
        raise CaptureNotFoundError(f"No capture found with id {capture_id}.")
    return str(capture.file_path)


async def list_captures(
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[CaptureSummary]:
    """Return captures registered in the datalake, optionally filtered to
    those whose time window overlaps [start, end].

    Omitting both returns every capture. Omitting one bound leaves that
    side open (e.g. start=None means "any capture ending before `end`").
    In multi-user mode only the captures of the user whose chat is running.
    """
    owner = _visible_owner()
    if owner is _NO_OWNER:
        return []
    async with get_session() as session:
        stmt = select(Capture).order_by(Capture.event_start.desc())
        if owner is not None:
            stmt = stmt.where(Capture.owner == owner)
        if start is not None:
            stmt = stmt.where(Capture.event_end >= start)
        if end is not None:
            stmt = stmt.where(Capture.event_start <= end)

        result = await session.scalars(stmt)
        return [CaptureSummary(capture_id=c.id, event_start=c.event_start, event_end=c.event_end) for c in result.all()]
