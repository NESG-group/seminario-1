from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from demo.mcp.tools.filter_pcaps import PcapFilterResult
from demo.mcp.tools.filter_pcaps import pcap_arp as _pcap_arp
from demo.mcp.tools.filter_pcaps import pcap_ip as _pcap_ip
from demo.mcp.tools.filter_pcaps import pcap_tcp as _pcap_tcp
from demo.mcp.tools.filter_pcaps import pcap_udp as _pcap_udp
from demo.mcp.tools.get_pcaps import CaptureNotFoundError, CaptureSummary
from demo.mcp.tools.get_pcaps import (
    list_captures as _list_captures,
)
from demo.mcp.tools.ingest_pcap import IngestError, IngestResult
from demo.mcp.tools.ingest_pcap import ingest_pcap as _ingest_pcap

mcp = FastMCP("pcap-views")


def _parse_capture_id(capture_id: str) -> uuid.UUID:
    """Parse a capture UUID, raising an error message the LLM can act on."""
    try:
        return uuid.UUID(capture_id)
    except ValueError as exc:
        raise ValueError(f"capture_id must be a valid UUID, got {capture_id!r}") from exc


def _compact(result: PcapFilterResult) -> CallToolResult:
    """Send a view as compact JSON.

    FastMCP's default text rendering is ``indent=2``, which puts every cell on its own
    line and roughly doubles the size. Hermes replaces any MCP result above its
    per-result budget (~39K chars with context_length 65536) with a 1.5K-char preview,
    so the model would only see the first rows. The structured content is unchanged.
    """
    return CallToolResult(
        content=[TextContent(type="text", text=result.model_dump_json())],
        structuredContent=result.model_dump(mode="json"),
    )


@mcp.tool()
async def ping() -> str:
    """Health-check tool used to verify MCP connectivity (Hermes <-> backend, FastAPI <-> backend)."""
    return "pong"


@mcp.tool()
async def ingest_pcap(pcap_ref: str) -> IngestResult | IngestError:
    """
    Resolve and validate a staged pcap/pcapng attachment and register it in
    the datalake. Returns the `capture_id` to pass to the pcap_* views.

    pcap_ref: the exact reference from the
    `[pcap attachment staged: pcap_ref=...]` marker. Do not pass raw bytes,
    base64 content, or a filesystem path.
    """
    return await _ingest_pcap(pcap_ref)


@mcp.tool()
async def list_captures(start: str | None = None, end: str | None = None) -> list[CaptureSummary]:
    """
    List captures registered in the datalake, optionally filtered to those
    whose time window overlaps a given range. Results are ordered newest first.

    start/end: ISO 8601 timestamps (e.g. "2024-11-11T19:00:00Z"). Omit
    both to list every capture. Use this to find a capture_id when the
    user describes a capture by time rather than giving its UUID.
    """
    parsed_start = datetime.fromisoformat(start) if start else None
    parsed_end = datetime.fromisoformat(end) if end else None
    return await _list_captures(start=parsed_start, end=parsed_end)


@mcp.tool()
async def pcap_ip(
    capture_id: str,
    offset: int = 0,
    limit: int = 100,
    frame_from: int | None = None,
    frame_to: int | None = None,
) -> Annotated[CallToolResult, PcapFilterResult]:
    """
    IPv4 view of a stored capture: frame number, src/dst IP, protocol name,
    TTL and IP header fields per packet. Use it for L3 questions (who talks to
    whom, TTL anomalies, protocol distribution). No ports, no flags, no
    application text.

    To pair IPs with TCP/UDP fields, look up the SAME frame number: call this
    view with frame_from=F and frame_to=F (or a small range around F), where F
    is a frame.number you already read in pcap_tcp or pcap_udp.

    capture_id: a UUID from list_captures or ingest_pcap.
    frame_from/frame_to: optional inclusive frame range. ONLY use them to fetch a
    frame you ALREADY read in another view (frame_from=F, frame_to=F). Never use
    them to scan the capture in blocks like 1-100: your first call must not set them.
    offset/limit: paging over the returned rows (limit at most 150). offset
    counts rows, NOT frame numbers.
    """
    parsed_id = _parse_capture_id(capture_id)
    try:
        return _compact(await _pcap_ip(parsed_id, offset, limit, frame_from, frame_to))
    except CaptureNotFoundError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
async def pcap_arp(capture_id: str, offset: int = 0, limit: int = 100) -> Annotated[CallToolResult, PcapFilterResult]:
    """
    ARP view of a stored capture: opcode (1 request, 2 reply) with sender and
    target MAC and IP for every ARP packet, requests included. Use it to
    confirm or refute ARP spoofing, gratuitous ARP or ARP scanning.

    capture_id: a UUID from list_captures or ingest_pcap. offset/limit: paging (limit at most 150).
    """
    parsed_id = _parse_capture_id(capture_id)
    try:
        return _compact(await _pcap_arp(parsed_id, offset, limit))
    except CaptureNotFoundError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
async def pcap_tcp(
    capture_id: str,
    offset: int = 0,
    limit: int = 100,
    frame_from: int | None = None,
    frame_to: int | None = None,
) -> Annotated[CallToolResult, PcapFilterResult]:
    """
    TCP view of a stored capture: frame number, ports, flags (e.g. "SYN,ACK"),
    seq/ack, window and payload length per packet. No IP addresses.

    START HERE for any question that involves a port, a service or a server role
    (file server, DNS server, web server): ports exist only in TCP/UDP views. Call
    it normally (no frame range), find the matching row and note its frame.number F;
    then call pcap_ip with frame_from=F and frame_to=F to get the IP addresses.
    Use it for handshakes, SYN scans, resets and connection behaviour. ICMP errors
    that merely quote a TCP header are excluded.

    capture_id: a UUID from list_captures or ingest_pcap.
    frame_from/frame_to: optional inclusive frame range. ONLY use them to fetch a
    frame you ALREADY read in another view. Never use them to scan the capture in
    blocks like 1-100: your first call must not set them.
    offset/limit: paging over the returned rows (limit at most 150). offset
    counts rows, NOT frame numbers.
    """
    parsed_id = _parse_capture_id(capture_id)
    try:
        return _compact(await _pcap_tcp(parsed_id, offset, limit, frame_from, frame_to))
    except CaptureNotFoundError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
async def pcap_udp(capture_id: str, offset: int = 0, limit: int = 100) -> Annotated[CallToolResult, PcapFilterResult]:
    """
    UDP view of a stored capture: frame number, ports and UDP length per
    packet. No IP addresses: to get them, call pcap_ip with frame_from=F and
    frame_to=F, where F is the frame.number you read here. Start here for
    questions about DNS/NTP/DHCP-style services, beaconing patterns and UDP scans.
    ICMP errors that merely quote a UDP header are excluded.

    capture_id: a UUID from list_captures or ingest_pcap. offset/limit: paging
    over the returned rows (limit at most 150). offset counts rows, NOT frame numbers.
    """
    parsed_id = _parse_capture_id(capture_id)
    try:
        return _compact(await _pcap_udp(parsed_id, offset, limit))
    except CaptureNotFoundError as exc:
        raise ValueError(str(exc)) from exc


def main() -> None:
    """Entrypoint for running the MCP server over stdio (local Hermes profile)."""
    mcp.run()


if __name__ == "__main__":
    main()
