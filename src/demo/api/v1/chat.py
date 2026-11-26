import json
import time
from collections.abc import AsyncGenerator
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from demo.api.v1.chat_schema import ChatMessage
from demo.api.v1.pcap.staging import stage_pcap_attachments
from demo.config import settings
from demo.services.hermes_client import HermesClient
from demo.services.requester import (
    USER_JWT_HEADER,
    Requester,
    RequesterError,
    acting_as,
    multi_user_enabled,
    verify_user_jwt,
)
from demo.services.scope import with_scope_prompt

router = APIRouter()
hermes_client = HermesClient()


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request payload."""

    model: str
    messages: list[ChatMessage]
    stream: bool = False

    model_config = {"extra": "allow"}


class ModelInfo(BaseModel):
    """OpenAI-compatible model descriptor."""

    id: str
    object: Literal["model"] = "model"
    created: int
    owned_by: str


class ModelList(BaseModel):
    """OpenAI-compatible list of available models."""

    object: Literal["list"] = "list"
    data: list[ModelInfo]


@router.get("/models")
async def list_models() -> ModelList:
    """Fetch available models dynamically from Hermes."""
    try:
        hermes_models = await hermes_client.list_models()
        return ModelList(
            data=[
                ModelInfo(
                    id=model["id"],
                    created=model.get("created", int(time.time())),
                    owned_by="hermes",
                )
                for model in hermes_models
            ]
        )
    except Exception:  # noqa: BLE001 - any Hermes failure (network, protocol, or otherwise) falls back to a single default entry.
        return ModelList(
            data=[
                ModelInfo(
                    id=settings.default_llm_model,
                    created=int(time.time()),
                    owned_by="demo-fallback",
                )
            ]
        )


async def hermes_stream_to_openai_sse(
    messages: list[dict[str, object]], model_name: str, requester: Requester | None = None
) -> AsyncGenerator[str, None]:
    """Relay Hermes's streamed chat completion chunks to the client as SSE.

    Args:
        messages: OpenAI-format message list, already staged (attachments
            replaced with text references), forwarded to Hermes.
        model_name: The model requested by the client, forwarded to Hermes.
        requester: The user the chat runs for (multi-user mode), or None.
    """
    async with acting_as(requester):
        async for chunk in hermes_client.chat_completion_stream(messages, model=model_name):
            yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"


def _requester_from_header(token: str | None) -> Requester | None:
    """The verified user in multi-user mode (401 if missing or invalid), else None."""
    if not multi_user_enabled():
        return None
    try:
        return verify_user_jwt(token)
    except RequesterError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    request: ChatCompletionRequest,
    user_jwt: str | None = Header(default=None, alias=USER_JWT_HEADER),
) -> StreamingResponse | dict[str, object]:
    """Handle chat completion requests by proxying them to Hermes.

    Any pcap/pcapng attachments in the incoming messages are extracted and
    written to the backend's staging directory here, in code, before the
    request reaches Hermes — the LLM only ever sees a short `pcap_ref`
    text reference, never the raw binary content.

    In multi-user mode the request must carry Open WebUI's signed user JWT;
    attachments are staged as that user's, and the chat runs on their behalf
    (see ``demo.services.requester``).
    """
    requester = _requester_from_header(user_jwt)
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided.")

    owner = requester.user_id if requester is not None else None
    messages = with_scope_prompt(stage_pcap_attachments(request.messages, owner))

    if request.stream:
        return StreamingResponse(
            hermes_stream_to_openai_sse(messages, request.model, requester),
            media_type="text/event-stream",
        )

    try:
        async with acting_as(requester):
            result = await hermes_client.chat_completion(messages, model=request.model)
        return result
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean 502 to the client.
        raise HTTPException(status_code=502, detail="Failed to reach Hermes.") from exc
