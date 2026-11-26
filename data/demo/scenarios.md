# Demo scenarios (NOMS 2027)

All questions use the upload flow (the PCAP is attached to the chat), Qwen 2.5 72B, and a capture of an Nmap scan of ports 22, 23, 53, 80, and 443 (`nmap22-23-53-80-443`).

## Scenario 1: one view per question

| ID | Type | View | Question |
| --- | --- | --- | --- |
| Q1 | Single-field extraction | `pcap_ip` | List the unique IPv4 addresses that appear as source or destination of IPv4 packets in the trace |
| Q2 | Single-layer aggregation | `pcap_arp` | List the unique ARP flows found in the trace. For each one report: sender MAC address, target MAC address, sender IP address and target IP address |
| Q3 | Intra-layer state reconstruction | `pcap_tcp` | List the destination ports where a TCP connection attempt was explicitly refused with a RST packet. Report as a simple list of ports |

## Scenario 2: questions needing two views

| ID | Type | Views | Question |
| --- | --- | --- | --- |
| Q4 | Cross-layer correlation | `pcap_ip`, `pcap_tcp` | List the source IP addresses belonging to private RFC1918 ranges and their corresponding TCP destination ports. Present the results using the format: `Source IP - Destination port` |
| Q5 | Multi-flow session reconstruction | `pcap_ip`, `pcap_tcp` | For each (source IP, destination IP) pair that exchanged TCP traffic, list every distinct TCP session (client_port -> server_port) initiated between them. For each session report: whether the three-way handshake completed, whether the session was closed with FIN, whether the session was reset with RST, and the number of packets exchanged in each direction. Present the results using the format: `Source IP - Destination IP | Source port - Destination port | Handshake: yes/no | FIN: yes/no | RST: yes/no | Packets src->dst: N | Packets dst->src: M` |

## Results

### Scenario 1

#### Q1: single-field extraction

Model answer:

```
The unique IPv4 addresses that appear as source or destination in the trace are:
- 192.168.1.15
- 192.168.1.1
```

Audit record:

```
PCAP_VIEW_APPLIED {"capture_id": "4e3e744b-3f14-4b4b-a9f0-e17f79424e75", "tool": "pcap_ip", "display_filter": "ip", "offset": 0, "returned": 30, "matched": 30}
```

View: correct. Answer: correct.

#### Q2: single-layer aggregation

Model answer:

```
The unique ARP flows found in the trace are:
1. Sender MAC: 08:00:27:12:c4:2f, Target MAC: 00:00:00:00:00:00, Sender IP: 192.168.1.15, Target IP: 192.168.1.1
2. Sender MAC: 08:00:27:d1:7b:b1, Target MAC: 08:00:27:12:c4:2f, Sender IP: 192.168.1.1, Target IP: 192.168.1.15
3. Sender MAC: 08:00:27:d1:7b:b1, Target MAC: 00:00:00:00:00:00, Sender IP: 192.168.1.1, Target IP: 192.168.1.15
4. Sender MAC: 08:00:27:12:c4:2f, Target MAC: 08:00:27:d1:7b:b1, Sender IP: 192.168.1.15, Target IP: 192.168.1.1
These flows show the ARP requests and replies between the two IP addresses 192.168.1.15 and 192.168.1.1.
```

Audit record:

```
PCAP_VIEW_APPLIED {"capture_id": "73b42d24-fcc6-423d-abba-a955b035b03f", "tool": "pcap_arp", "display_filter": "arp", "offset": 0, "returned": 4, "matched": 4}
```

View: correct. Answer: correct.

#### Q3: intra-layer state reconstruction

Model answer:

```
The destination ports where a TCP connection attempt was explicitly refused with a RST packet are:
443, 23, 80, 22, 53
```

Audit record:

```
PCAP_VIEW_APPLIED {"capture_id": "df48ff1e-2675-4fd4-867d-06ccfdf086a4", "tool": "pcap_tcp", "display_filter": "tcp && !icmp && !icmpv6", "offset": 0, "returned": 16, "matched": 16}
```

Ground truth: 23 and 443. Only these ports show a SYN answered directly by RST/ACK, without a prior SYN/ACK or ACK. On ports 22, 53, and 80 the RST follows earlier ACKs.

View: correct. Answer: incorrect (the model listed every scanned port).

### Scenario 2

#### Q4: cross-layer correlation

Model answer:

```
192.168.1.15 - 23
192.168.1.15 - 80
192.168.1.15 - 22
192.168.1.15 - 53
192.168.1.15 - 443
192.168.1.1 - 62053
```

Audit records:

```
PCAP_VIEW_APPLIED {"capture_id": "d00487dc-2b62-484c-82b7-c04da9f82cb2", "tool": "pcap_ip", "display_filter": "ip", "offset": 0, "returned": 30, "matched": 30}
PCAP_VIEW_APPLIED {"capture_id": "d00487dc-2b62-484c-82b7-c04da9f82cb2", "tool": "pcap_udp", "display_filter": "udp && !icmp && !icmpv6", "offset": 0, "returned": 8, "matched": 8}
```

Ground truth: the same six pairs (192.168.1.1 - 62053; 192.168.1.15 - 22, 23, 53, 80, 443).

Views: correct (both). Answer: correct.

#### Q5: multi-flow session reconstruction

Model answer (summarized as a table; the model returned a nested list):

| Source IP | Destination IP | Session | Handshake completed | Closed with FIN | Reset with RST | Client to server | Server to client |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 192.168.1.15 | 192.168.1.1 | 55020 -> 443 | No | No | Yes | 1 | 1 |
| 192.168.1.15 | 192.168.1.1 | 53322 -> 80 | Yes | No | Yes | 2 | 2 |
| 192.168.1.15 | 192.168.1.1 | 41558 -> 22 | Yes | No | Yes | 2 | 2 |
| 192.168.1.15 | 192.168.1.1 | 60812 -> 23 | No | No | Yes | 1 | 1 |
| 192.168.1.15 | 192.168.1.1 | 37912 -> 53 | Yes | No | Yes | 2 | 2 |

The model closed with: "Each session's details are based on the TCP packets exchanged between the source and destination IP addresses."

Audit records:

```
PCAP_VIEW_APPLIED {"capture_id": "3dd576c4-d3c9-4094-8f9c-a953cb4069d2", "tool": "pcap_ip", "display_filter": "ip", "offset": 0, "returned": 30, "matched": 30}
PCAP_VIEW_APPLIED {"capture_id": "3dd576c4-d3c9-4094-8f9c-a953cb4069d2", "tool": "pcap_tcp", "display_filter": "tcp && !icmp && !icmpv6", "offset": 0, "returned": 16, "matched": 16}
```

Ground truth (PyShark):

| Session | Handshake completed | FIN | RST | Client to server | Server to client |
| --- | --- | --- | --- | --- | --- |
| 37912 -> 53 | Yes | No | Yes | 3 | 1 |
| 41558 -> 22 | Yes | No | Yes | 3 | 1 |
| 53322 -> 80 | Yes | No | Yes | 3 | 1 |
| 55020 -> 443 | No | No | Yes | 1 | 1 |
| 60812 -> 23 | No | No | Yes | 1 | 1 |


Views: correct (both). Answer: partly correct. Handshake, FIN, and RST fields match for all five sessions, and the packet counts match for 443 and 23. For 53, 22, and 80 the first run reports 2 packets in each direction instead of 3 client packets and 1 server packet.