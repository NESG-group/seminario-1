from __future__ import annotations

import re
from typing import Final

from demo.api.v1.chat_schema import ChatMessage, FilePart, ImagePart, TextPart
from demo.api.v1.pcap.utils import UUID_PATTERN, decode_data_uri, looks_like_pcap, read_open_webui_file, stage_bytes

# Open WebUI treats an attached file as a RAG document: it wraps the user query in its RAG
# template, inlines the file's "extracted text" (for a pcap, the raw binary decoded as text)
# in <source> blocks inside <context>, and lists the file in <attached_files>.
_SOURCE_BLOCK: Final[re.Pattern[str]] = re.compile(
    r"<source\b[^>]*\bresource-id=\"(?P<id>[^\"]+)\"[^>]*>.*?</source>\s*", re.DOTALL
)
_ATTACHED_FILE_TAG: Final[re.Pattern[str]] = re.compile(r"<file\b[^>]*\bid=\"(?P<id>[^\"]+)\"[^>]*/>\s*")
_EMPTY_ATTACHED_FILES: Final[re.Pattern[str]] = re.compile(r"<attached_files>\s*</attached_files>\s*")
_CONTEXT_BLOCK: Final[re.Pattern[str]] = re.compile(r"<context>(?P<body>.*?)</context>\s*", re.DOTALL)


def _strip_open_webui_file_context(text: str, pcap_ids: set[str]) -> str:
    """Remove what Open WebUI's RAG pipeline added for the given pcap files.

    Drops their <source> blocks (raw binary decoded as text) and their
    <attached_files> entries (whose id the model could mistake for a
    capture_id). If no other source is left in <context>, the RAG template
    that precedes it is dropped too, leaving only the user's question.
    Sources of non-pcap files are kept.
    """
    text = _SOURCE_BLOCK.sub(lambda m: "" if m["id"] in pcap_ids else m[0], text)
    text = _ATTACHED_FILE_TAG.sub(lambda m: "" if m["id"] in pcap_ids else m[0], text)
    text = _EMPTY_ATTACHED_FILES.sub("", text)
    context = _CONTEXT_BLOCK.search(text)
    if context is not None and not context["body"].strip():
        text = text[context.end() :]
    return text.strip()


def _stage_pcap_ids_in_text(text: str, owner: str | None = None) -> str:
    """Stage pcap files referenced by id in Open WebUI's text payload.

    Each pcap is replaced by a `[pcap attachment staged: ...]` marker, and the
    content Open WebUI inlined for it is removed so the model never sees it.
    """
    pcap_ids: set[str] = set()
    markers: list[str] = []
    for file_id in dict.fromkeys(UUID_PATTERN.findall(text)):
        resolved = read_open_webui_file(file_id)
        if resolved is None:
            continue
        filename, data = resolved
        if not looks_like_pcap(filename, None):
            continue
        ref = stage_bytes(data, owner)
        pcap_ids.add(file_id)
        markers.append(f"\n[pcap attachment staged: pcap_ref={ref}, filename={filename}]")
    if not pcap_ids:
        return text
    return _strip_open_webui_file_context(text, pcap_ids) + "".join(markers)


def stage_pcap_attachments(messages: list[ChatMessage], owner: str | None = None) -> list[dict[str, object]]:
    """
    Scan messages for pcap-like attachments, write their raw bytes to the
    staging directory, and replace those content parts with a short text
    note the LLM can read and act on directly (no transcription needed).

    ``owner`` (multi-user mode) is recorded with every staged attachment.

    Returns plain dicts ready to forward to Hermes (mirrors the previous
    `message.model_dump()` shape used by the router).
    """
    result: list[dict[str, object]] = []

    for message in messages:
        if isinstance(message.content, str):
            result.append({"role": message.role, "content": _stage_pcap_ids_in_text(message.content, owner)})
            continue

        new_parts: list[object] = []
        for part in message.content:
            if isinstance(part, FilePart):
                filename = part.file.filename
                data: bytes | None = None
                if part.file.file_data is not None:
                    data = decode_data_uri(part.file.file_data)
                elif part.file.file_id is not None:
                    resolved = read_open_webui_file(part.file.file_id)
                    if resolved is not None:
                        filename, data = resolved
                if data is not None and looks_like_pcap(filename, None):
                    ref = stage_bytes(data, owner)
                    new_parts.append(
                        {
                            "type": "text",
                            "text": f"[pcap attachment staged: pcap_ref={ref}, filename={filename or 'unknown'}]",
                        }
                    )
                    continue
                new_parts.append(part.model_dump())
            elif isinstance(part, ImagePart):
                data = decode_data_uri(part.image_url.url)
                mime_hint = part.image_url.url.split(";", 1)[0].removeprefix("data:") if data else None
                if data is not None and looks_like_pcap(None, mime_hint):
                    ref = stage_bytes(data, owner)
                    new_parts.append({"type": "text", "text": f"[pcap attachment staged: pcap_ref={ref}]"})
                    continue
                new_parts.append(part.model_dump())
            elif isinstance(part, TextPart):
                new_parts.append(part.model_dump())

        result.append({"role": message.role, "content": new_parts})

    return result
