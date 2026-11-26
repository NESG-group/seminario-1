---
name: pcap-filter
description: Use for any question about packets, IPs, ports, MACs, or protocols in a stored capture. Triggers — message contains `[pcap attachment staged: pcap_ref=...]` (ingest first, always, even if the question is only about IPs/ports), references a capture_id (UUID), asks for latest or by time range, or asks which captures exist. Applies pcap_ip, pcap_tcp, pcap_udp, or pcap_arp.
---

# pcap-filter

## Hard rules (correctness)

1. Marker `[pcap attachment staged: pcap_ref=X]` → first call is `ingest_pcap(pcap_ref=X)`. Always. Before reading, answering, or planning. The question is answered about THAT capture.
2. Every IP, port, MAC, protocol, or count in the answer comes from a view row read this turn. No view call → no answer. Answering a packet-data question without a view call is always wrong.
3. Counting questions ("how many TCP packets"): the answer is `matched_count` of one view call. Do not page to count.
4. If after 2 pages you have not found the target row, say so. Do not invent values, do not extrapolate from rows seen.

## Hard rules (style)

5. After a tool result: next message is a tool call OR the final answer. Do not narrate intent ("I will…", "Let's…"). A message with text and no tool call ends the turn.
6. Be decisive: pick the minimal set of views, call them, answer. Do not re-pick views on user pushback unless the columns used truly lack a needed field.

## Tools

- `list_captures(start?, end?)` — captures in the datalake, newest first.
- `ingest_pcap(pcap_ref)` — registers an attachment staged by the API; returns `capture_id`.
- `pcap_ip`, `pcap_arp`, `pcap_tcp`, `pcap_udp` — params: `capture_id`, `offset=0`, `limit=100` (max 150), optional `frame_from`, `frame_to`. Each applies one fixed display filter; you cannot change the filter.

## Views

| Tool | Filter | Columns (exclusions first) |
| --- | --- | --- |
| `pcap_ip` | `ip` | **NO ports, NO flags.** frame.number, time, ip.version, hdr_len, dsfield, len, id, flags, frag_offset, ttl, proto (as name), checksum, src, dst |
| `pcap_tcp` | `tcp && !icmp && !icmpv6` | **NO IP addresses.** frame.number, time, srcport, dstport, seq, ack, flags (as list), len, checksum, window |
| `pcap_udp` | `udp && !icmp && !icmpv6` | **NO IP addresses.** frame.number, time, srcport, dstport, length, checksum |
| `pcap_arp` | `arp` | frame.number, time, hw.type, proto.type, hw.size, proto.size, opcode, sender MAC+IP, target MAC+IP |

`frame.number` is the only column shared by all views. It is the packet number in the capture.

## Step 0 — Resolve `capture_id`

| Situation | Action |
| --- | --- |
| Marker `[pcap attachment staged: pcap_ref=X]` | `ingest_pcap(pcap_ref=X)`, use returned `capture_id` |
| UUID in message | use it directly; never invent one |
| "latest" or time range | `list_captures(start, end)`, take first |
| "which captures exist" | `list_captures`, report list, **STOP** |
| nothing specified | `list_captures()`, use newest; if empty, say so and **STOP** |

## Step 1 — Pick the views

List the fields the question needs. Match them to the Columns row above.

- **Default: one view.** Call a second only if you can name the field that forces it. If you cannot name that field, do not call it.
- `matched_count: 0` is a valid result: report it, do not try other views.

### Joining two views by packet

Two views describe the same packet only when their `frame.number` is equal. Never pair rows by position or by order.

Recipe:
1. Call the view whose columns let you **identify** the target packet (port, flag, ARP opcode). Find the row with `frame.number = F`.
2. Call the other view with `frame_from=F, frame_to=F`.
3. Verify the returned row has `frame.number = F`. If it does not, the match is not confirmed: say so, do not answer.

Example — "Which host is the database server receiving connections on port 3306?":
- IP + port needed; no single view has both → two views.
- `pcap_tcp` (normal call): read rows until one has `tcp.dstport = 3306` (or `srcport`). Note its `frame.number = F`.
- `pcap_ip` with `frame_from=F, frame_to=F`. The server is the side that owns the port: if `dstport = 3306` take `ip.dst`; if `srcport = 3306` take `ip.src`.
- Never answer an IP from `pcap_ip` alone for a question about a port.

### `offset` semantics

- `offset` counts **rows of the view you are calling**, never frame numbers.
- Row N of a filtered view is almost never frame N. Never use `frame.number - 1` as an offset.
- Never call the same view twice with the same arguments.

## Step 2 — Call and read

- Read `columns` and `rows` from every result.
- `frame_from` / `frame_to` are ONLY for looking up a frame you already read in another view. Never use them to scan the capture in blocks (1-100, 101-200, …): that never reaches late frames and wastes calls. 
- If the user gives you a frame number N, call the tool with frame_from=N and frame_to=N. Never read it from a page of rows.
- **Pagination budget**: max 2 pages per view per turn (`limit=150 × 2 = 300` rows). If `matched_count > 300`, do not page further: answer from what you read and say it is partial.
- Page with `offset` only when the target row was not in the page just read. Never page "to see what's next" without a specific field value to find.
- `truncated=True` means more rows exist beyond those returned. Page only if the evidence you need is missing.
- `warning` present (e.g. capture truncated at last packet): include it briefly in the answer.
- If a tool returns an error, state it once and stop.

## Step 3 — Post-process and answer

- Deduplicate when the question asks for unique values or tuples.
- Aggregation (top N, grouped counts): only from rows already read. State the result is partial if `matched_count > rows seen`.
- Time-filtered queries are not supported by the views; answer from rows read and mark as partial if needed.
- Give only the requested result (list or table), in the user's language.
- Do not narrate intermediate steps; do not mention `offset`, `limit`, or `truncated` unless data is actually missing.

For answers that combine two views, the `frame.number` of the row used in each view must be the same. If it is not, you have not confirmed the match: say so instead of answering.