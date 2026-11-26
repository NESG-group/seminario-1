"""Multi-user mode: verified identity, per-user captures, serialised chats."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient

from demo.api.v1 import chat as chat_module
from demo.api.v1.chat_schema import ChatMessage
from demo.api.v1.pcap import staging as pcap_staging
from demo.api.v1.pcap import utils as pcap_utils
from demo.config import settings
from demo.db.models import Capture
from demo.mcp.tools import get_pcaps, ingest_pcap
from demo.mcp.tools.get_pcaps import CaptureNotFoundError
from demo.services import requester as requester_module
from demo.services.requester import (
    USER_JWT_HEADER,
    Requester,
    RequesterError,
    acting_as,
    current_requester,
    verify_user_jwt,
)

SECRET = "test-secret-at-least-32-bytes-long!!"
ALICE = Requester(user_id="alice-id", email="alice@example.org")
BOB = Requester(user_id="bob-id", email="bob@example.org")


@pytest.fixture
def multi_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "user_jwt_secret", SECRET)


def _token(sub: str = "alice-id", *, secret: str = SECRET, exp_in: int = 300, iss: str = "open-webui") -> str:
    now = int(time.time())
    payload = {"sub": sub, "email": f"{sub}@example.org", "iss": iss, "iat": now, "exp": now + exp_in}
    return jwt.encode(payload, secret, algorithm="HS256")


# --- identity --------------------------------------------------------------


@pytest.mark.usefixtures("multi_user")
def test_verify_user_jwt_accepts_open_webui_token() -> None:
    assert verify_user_jwt(_token("alice-id")) == Requester(user_id="alice-id", email="alice-id@example.org")


@pytest.mark.usefixtures("multi_user")
@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "not-a-jwt",
        _token(secret="another-secret-at-least-32-bytes!!"),
        _token(exp_in=-10),
        _token(iss="someone-else"),
    ],
)
def test_verify_user_jwt_rejects_bad_tokens(token: str | None) -> None:
    with pytest.raises(RequesterError):
        verify_user_jwt(token)


def test_verify_user_jwt_refuses_without_secret() -> None:
    with pytest.raises(RequesterError):
        verify_user_jwt(_token())


@pytest.mark.usefixtures("multi_user")
def test_chat_requires_user_jwt(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 401


@pytest.mark.usefixtures("multi_user")
def test_chat_runs_on_behalf_of_the_verified_user(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Requester | None] = []

    async def fake_chat_completion(messages: list[dict[str, object]], model: str) -> dict[str, object]:
        seen.append(current_requester())
        return {"choices": []}

    monkeypatch.setattr(chat_module.hermes_client, "chat_completion", fake_chat_completion)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        headers={USER_JWT_HEADER: _token("alice-id")},
    )

    assert response.status_code == 200
    assert seen == [Requester(user_id="alice-id", email="alice-id@example.org")]
    assert current_requester() is None


def test_single_user_mode_ignores_the_header(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat_completion(messages: list[dict[str, object]], model: str) -> dict[str, object]:
        assert current_requester() is None
        return {"choices": []}

    monkeypatch.setattr(chat_module.hermes_client, "chat_completion", fake_chat_completion)

    response = client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 200


async def test_chats_of_different_users_do_not_overlap() -> None:
    order: list[str] = []

    async def chat(who: Requester) -> None:
        async with acting_as(who):
            order.append(f"start {who.user_id}")
            assert current_requester() == who
            await asyncio.sleep(0.01)
            assert current_requester() == who
            order.append(f"end {who.user_id}")

    await asyncio.gather(chat(ALICE), chat(BOB))

    assert order in (
        ["start alice-id", "end alice-id", "start bob-id", "end bob-id"],
        ["start bob-id", "end bob-id", "start alice-id", "end alice-id"],
    )
    assert current_requester() is None
    assert not requester_module._chat_lock.locked()


# --- staging and ingest ----------------------------------------------------


@pytest.fixture
def staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "staging"
    monkeypatch.setattr(pcap_utils, "STAGING_ROOT", root)
    monkeypatch.setattr(ingest_pcap, "STAGING_ROOT", root)
    monkeypatch.setattr(ingest_pcap, "QUARANTINE_ROOT", tmp_path / "quarantine")
    return root


def test_staging_records_the_uploader(staging: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pcap_staging, "read_open_webui_file", lambda _id: ("c.pcapng", b"\x0a\x0d\x0d\x0a"))
    file_id = str(uuid.uuid4())

    staged = pcap_staging.stage_pcap_attachments(
        [ChatMessage(role="user", content=f'question <file type="file" id="{file_id}"/>')], owner="alice-id"
    )

    ref = str(staged[0]["content"]).split("pcap_ref=")[1].split(",")[0]
    assert (staging / ref / pcap_utils.STAGING_OWNER_FILE).read_text() == "alice-id"


@pytest.fixture
def persisted(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    owners: list[str | None] = []

    async def fake_persist(_data: bytes, owner: str | None = None) -> uuid.UUID:
        owners.append(owner)
        return uuid.uuid4()

    monkeypatch.setattr(ingest_pcap, "_persist_to_datalake", fake_persist)
    return owners


_FIXTURE = Path(__file__).parents[2] / "data/fixtures/arp-icmp.pcapng"


@pytest.mark.usefixtures("multi_user", "staging")
async def test_ingest_registers_the_capture_for_its_uploader(persisted: list[str | None]) -> None:
    ref = pcap_utils.stage_bytes(_FIXTURE.read_bytes(), owner="alice-id")

    async with acting_as(ALICE):
        result = await ingest_pcap.ingest_pcap(ref)

    assert result["ok"] is True
    assert persisted == ["alice-id"]


@pytest.mark.usefixtures("multi_user", "staging")
async def test_ingest_refuses_another_users_attachment(persisted: list[str | None]) -> None:
    ref = pcap_utils.stage_bytes(_FIXTURE.read_bytes(), owner="alice-id")

    async with acting_as(BOB):
        result = await ingest_pcap.ingest_pcap(ref)

    assert result == {"ok": False, "reason": "ref_not_found"}
    assert persisted == []


# --- catalog ---------------------------------------------------------------


class _FakeScalars:
    def __init__(self, rows: list[Capture]) -> None:
        self._rows = rows

    def all(self) -> list[Capture]:
        return self._rows


class _FakeSession:
    def __init__(self, captures: list[Capture]) -> None:
        self.captures = {c.id: c for c in captures}
        self.statements: list[Any] = []

    async def get(self, _model: type, capture_id: uuid.UUID) -> Capture | None:
        return self.captures.get(capture_id)

    async def scalars(self, stmt: Any) -> _FakeScalars:
        self.statements.append(stmt)
        return _FakeScalars(list(self.captures.values()))


def _capture(owner: str | None) -> Capture:
    t = datetime(2026, 1, 1, tzinfo=UTC)
    return Capture(id=uuid.uuid4(), file_path=f"/data/{owner}.pcap", event_start=t, event_end=t, owner=owner)


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> tuple[_FakeSession, Capture, Capture]:
    alice_capture, bob_capture = _capture("alice-id"), _capture("bob-id")
    session = _FakeSession([alice_capture, bob_capture])

    @asynccontextmanager
    async def fake_get_session() -> AsyncIterator[_FakeSession]:
        yield session

    monkeypatch.setattr(get_pcaps, "get_session", fake_get_session)
    return session, alice_capture, bob_capture


@pytest.mark.usefixtures("multi_user")
async def test_views_only_resolve_the_requesters_captures(catalog: tuple[_FakeSession, Capture, Capture]) -> None:
    _, alice_capture, bob_capture = catalog

    async with acting_as(ALICE):
        assert await get_pcaps.get_capture_file_path(alice_capture.id) == alice_capture.file_path
        with pytest.raises(CaptureNotFoundError):
            await get_pcaps.get_capture_file_path(bob_capture.id)


@pytest.mark.usefixtures("multi_user")
async def test_views_resolve_nothing_outside_a_chat(catalog: tuple[_FakeSession, Capture, Capture]) -> None:
    _, alice_capture, _ = catalog
    with pytest.raises(CaptureNotFoundError):
        await get_pcaps.get_capture_file_path(alice_capture.id)


@pytest.mark.usefixtures("multi_user")
async def test_list_captures_filters_by_requester(catalog: tuple[_FakeSession, Capture, Capture]) -> None:
    session, _, _ = catalog

    assert await get_pcaps.list_captures() == []  # no chat running
    async with acting_as(ALICE):
        await get_pcaps.list_captures()

    compiled = session.statements[-1].compile(compile_kwargs={"literal_binds": True})
    assert "captures.owner = 'alice-id'" in str(compiled)


async def test_single_user_mode_sees_every_capture(catalog: tuple[_FakeSession, Capture, Capture]) -> None:
    session, _, bob_capture = catalog

    assert await get_pcaps.get_capture_file_path(bob_capture.id) == bob_capture.file_path
    await get_pcaps.list_captures()
    assert session.statements[-1].whereclause is None
