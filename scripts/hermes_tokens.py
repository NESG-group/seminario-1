"""Token usage and latency per question, read from Hermes's session store.

Runs INSIDE the hermes container (stdlib only), fed through stdin:

    docker exec -i demo-hermes python3 - [LIMIT] [--all] < scripts/hermes_tokens.py

One row per Hermes session (one chat turn). Open WebUI's auxiliary requests
(title, tags, follow-ups, search queries), which also go through the agent,
are hidden unless --all is given.

Columns:
    secs    seconds from the user's message to the last message of the turn
    llm     calls to the model in the turn (one more per round of tool calls)
    tools   tool calls in the turn
    input   prompt tokens processed from scratch
    cached  prompt tokens reused from Ollama's prompt cache
    output  generated tokens
"""

from __future__ import annotations

import re
import sqlite3
import sys

DB = "/opt/data/state.db"
MARKER = re.compile(r"\[pcap attachment staged:[^\]]*\]")

QUERY = """
SELECT s.id,
       datetime(s.started_at, 'unixepoch', 'localtime'),
       COALESCE(u.api_call_count, 0),
       COALESCE(s.tool_call_count, 0),
       COALESCE(u.input_tokens, 0),
       COALESCE(u.cache_read_tokens, 0),
       COALESCE(u.output_tokens, 0),
       (SELECT m.content FROM messages m
         WHERE m.session_id = s.id AND m.role = 'user' ORDER BY m.id LIMIT 1),
       {duration}
  FROM sessions s
  JOIN session_model_usage u ON u.session_id = s.id AND u.task = ''
 ORDER BY s.started_at DESC
"""


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Column names of a table."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def duration_sql(conn: sqlite3.Connection) -> str:
    """SQL expression for the turn's duration, given the available columns."""
    if "timestamp" in columns(conn, "messages"):
        return "(SELECT MAX(m.timestamp) - MIN(m.timestamp) FROM messages m WHERE m.session_id = s.id)"
    if "ended_at" in columns(conn, "sessions"):
        return "(s.ended_at - s.started_at)"
    return "NULL"


def is_open_webui_task(content: str) -> bool:
    """Open WebUI's auxiliary prompts embed the conversation in <chat_history>."""
    return "<chat_history>" in content


def question_of(content: str, width: int) -> str:
    """The user's question, without the pcap marker or Open WebUI's RAG wrapper
    (still present in turns recorded before the backend stripped it)."""
    for closing_tag in ("</attached_files>", "</context>"):
        if closing_tag in content:
            content = content.rsplit(closing_tag, 1)[1]
            break
    text = " ".join(MARKER.sub("", content).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def seconds(value: float | None) -> str:
    """Duration formatted for the table, or a dash when unknown."""
    return "-" if value is None else f"{value:.1f}"


def main(argv: list[str]) -> None:
    show_all = "--all" in argv
    numbers = [a for a in argv if a.isdigit()]
    limit = int(numbers[0]) if numbers else 10

    conn = sqlite3.connect(DB)
    rows = []
    for row in conn.execute(QUERY.format(duration=duration_sql(conn))):
        content = row[7] or ""
        task = is_open_webui_task(content)
        if task and not show_all:
            continue
        label = "[Open WebUI task]" if task else question_of(content, 70)
        rows.append((row[1], seconds(row[8]), *row[2:7], label))
        if len(rows) == limit:
            break

    line = "{:<19}  {:>6}  {:>3}  {:>5}  {:>7}  {:>7}  {:>6}  {}"
    print(line.format("started", "secs", "llm", "tools", "input", "cached", "output", "question"))
    for row in rows:
        print(line.format(*row))
    if not rows:
        print("(no sessions)")


if __name__ == "__main__":
    main(sys.argv[1:])
