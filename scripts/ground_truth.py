"""Ground truth of the demo scenarios (Q1-Q5 in data/demo/scenarios.md), with PyShark."""

from __future__ import annotations

import argparse
import ipaddress
import json
from collections.abc import Callable
from pathlib import Path

import pyshark
from pyshark.capture.capture import TSharkCrashException

RAW_DIR = Path("data/demo/raw")
GT_DIR = Path("data/demo/ground_truth")
# (capture, ground-truth JSON) pairs generated when the script runs without arguments.
DEFAULT_TARGETS: list[tuple[Path, Path]] = [
    (RAW_DIR / "nmap22-23-53-80-443-threewayhandshake.pcapng", GT_DIR / "gt_basic_demo.json"),
    (RAW_DIR / "Monday-WorkingHours_qwen2.5-72b_run3_L100_495pkts.pcapng", GT_DIR / "gt_cicids_demo.json"),
]

Q1 = "List the unique IPv4 addresses that appear as source or destination of IPv4 packets in the trace"
Q2 = (
    "List the unique ARP flows found in the trace. For each one report: sender MAC address, target MAC address, "
    "sender IP address and target IP address"
)
Q3 = (
    "List the destination ports where a TCP connection attempt was explicitly refused with a RST packet. "
    "Report as a simple list of ports"
)
Q4 = (
    "List the source IP addresses belonging to private RFC 1918 ranges and their corresponding UDP destination "
    "ports. Present the results using the format: Source IP - Destination port"
)
Q5 = (
    "For each (source IP, destination IP) pair that exchanged TCP traffic, list every distinct TCP session "
    "(client_port -> server_port) initiated between them. For each session report: whether the three-way handshake "
    "completed, whether the session was closed with FIN, whether the session was reset with RST, and the number of "
    "packets exchanged in each direction"
)

RFC1918_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]

TCP_FIN, TCP_SYN, TCP_RST, TCP_ACK = 0x01, 0x02, 0x04, 0x10
TCP_OUTER = "tcp && !icmp && !icmpv6"
UDP_OUTER = "udp && !icmp && !icmpv6"

ClientKey = tuple[str, str, int, int]

# pyshark sometimes loses tshark's exit status ("Unknown child process pid") and reports
# a spurious crash (retcode 255). The question is rerun from scratch when that happens.
MAX_ATTEMPTS = 3


def _l3_endpoints(pkt: object) -> tuple[str, str]:
    """(src, dst) from IPv4 or IPv6."""
    if hasattr(pkt, "ip"):
        return pkt.ip.src, pkt.ip.dst
    if hasattr(pkt, "ipv6"):
        return pkt.ipv6.src, pkt.ipv6.dst
    raise AttributeError("no IP layer")


def _is_syn(flags: int) -> bool:  # SYN set, ACK clear
    return (flags & (TCP_SYN | TCP_ACK)) == TCP_SYN


def _is_synack(flags: int) -> bool:  # SYN and ACK set
    return (flags & (TCP_SYN | TCP_ACK)) == (TCP_SYN | TCP_ACK)


def _is_final_ack(flags: int) -> bool:  # ACK set, SYN and RST clear (may carry PSH/data)
    return (flags & (TCP_SYN | TCP_RST | TCP_ACK)) == TCP_ACK


def _is_rfc1918(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in net for net in RFC1918_NETWORKS)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _ip_sort_key(ip_str: str) -> tuple[int, int]:
    """Total order across IPv4 and IPv6.

    IPv4Address and IPv6Address cannot be compared directly (raises TypeError),
    so we sort by (version, integer value). IPv4 (32-bit) always sorts before
    IPv6 (128-bit), and within a version the integer ordering is the natural
    numeric ordering. Safe for mixed-version captures.
    """
    ip = ipaddress.ip_address(ip_str)
    return (ip.version, int(ip))


# Q1 = IP_QUESTIONS[0] of the paper.
def list_ipv4_addresses(pcap: str) -> str:
    cap = pyshark.FileCapture(pcap, display_filter="ip")
    ips = set()
    for p in cap:
        ips.add(p.ip.src)
        ips.add(p.ip.dst)
    cap.close()
    return "Unique IPv4 addresses:\n" + ("\n".join(sorted(ips, key=ipaddress.ip_address)) if ips else "None")


# Q2 = ARP_QUESTIONS[1] of the paper.
def list_arp_flows(pcap: str) -> str:
    cap = pyshark.FileCapture(pcap, display_filter="arp")
    flows = set()
    for pkt in cap:
        if hasattr(pkt, "arp"):
            flows.add(
                f"Sender MAC: {pkt.arp.src_hw_mac}, Target MAC: {pkt.arp.dst_hw_mac}, "
                f"Sender IP: {pkt.arp.src_proto_ipv4}, Target IP: {pkt.arp.dst_proto_ipv4}"
            )
    cap.close()
    return "ARP flows:\n" + ("\n".join(sorted(flows)) if flows else "None")


# Q3 = TCP_QUESTIONS[4] of the paper.
def tcp_refused_with_rst(pcap: str) -> str:
    cap = pyshark.FileCapture(pcap, display_filter="tcp")
    syn_sent: set[ClientKey] = set()
    synack_seen: set[ClientKey] = set()
    refused: set[int] = set()
    for pkt in cap:
        try:
            src, dst = _l3_endpoints(pkt)
            sport, dport = int(pkt.tcp.srcport), int(pkt.tcp.dstport)
            flags = int(pkt.tcp.flags, 16)
        except (AttributeError, ValueError):
            continue
        if _is_syn(flags):
            syn_sent.add((src, dst, sport, dport))
        elif _is_synack(flags):
            synack_seen.add((dst, src, dport, sport))
        elif flags & TCP_RST:
            client = (dst, src, dport, sport)
            if client in syn_sent and client not in synack_seen:
                refused.add(sport)
    cap.close()
    if not refused:
        return "No explicitly refused TCP connection attempts found"
    return "Destination ports that refused TCP connections with RST:\n" + "\n".join(str(p) for p in sorted(refused))


# Q4
def rfc1918_sources_udp_ports(pcap: str) -> str:
    cap = pyshark.FileCapture(pcap, display_filter=UDP_OUTER)
    pairs: set[tuple[str, int]] = set()
    for pkt in cap:
        try:
            src, _ = _l3_endpoints(pkt)
            dport = int(pkt.udp.dstport)
        except (AttributeError, ValueError):
            continue
        if _is_rfc1918(src):
            pairs.add((src, dport))
    cap.close()
    if not pairs:
        return "No UDP packets from RFC 1918 source addresses found"
    ordered = sorted(pairs, key=lambda p: (_ip_sort_key(p[0]), p[1]))
    return "Source IP - Destination port:\n" + "\n".join(f"{ip} - {port}" for ip, port in ordered)


# Q5
def tcp_sessions_per_ip_pair(pcap: str) -> str:
    cap = pyshark.FileCapture(pcap, display_filter=TCP_OUTER)

    # Pass 1: group packets by tshark's tcp.stream index. No manual 4-tuple bookkeeping.
    streams: dict[str, list[tuple[str, str, int, int, int]]] = {}
    for pkt in cap:
        try:
            src, dst = _l3_endpoints(pkt)
            streams.setdefault(str(pkt.tcp.stream), []).append(
                (src, dst, int(pkt.tcp.srcport), int(pkt.tcp.dstport), int(pkt.tcp.flags, 16))
            )
        except (AttributeError, ValueError):
            continue
    cap.close()

    sessions: list[tuple[str, str, int, int, bool, bool, bool, int, int]] = []

    for pkts in streams.values():
        client_ip = server_ip = None
        client_port = server_port = None
        state = "INIT"
        handshake = fin = rst = False
        to_server = to_client = 0

        for src, dst, sport, dport, flags in pkts:
            # The first SYN observed in the stream identifies client and server.
            if state == "INIT" and _is_syn(flags):
                client_ip, server_ip = src, dst
                client_port, server_port = sport, dport
                state = "SYN_SENT"

            # Mid-stream packets we never saw a SYN for: skip silently.
            if client_ip is None:
                continue

            from_client = src == client_ip and dst == server_ip and sport == client_port and dport == server_port
            if from_client:
                to_server += 1
            else:
                to_client += 1

            if flags & TCP_FIN:
                fin = True
            if flags & TCP_RST:
                rst = True

            # State machine with direction checks.
            if state == "SYN_SENT" and _is_synack(flags) and not from_client:
                state = "SYN_ACK_RECEIVED"
            elif state == "SYN_ACK_RECEIVED" and _is_final_ack(flags) and from_client:
                state = "ESTABLISHED"
                handshake = True

        if client_ip is None:
            continue  # stream with no SYN seen — skip, like the original

        sessions.append((client_ip, server_ip, client_port, server_port, handshake, fin, rst, to_server, to_client))

    if not sessions:
        return "No TCP sessions initiated with a SYN found"

    # Group by (client IP, server IP) and format.
    # Sort key uses _ip_sort_key so IPv4 and IPv6 can coexist without TypeError.
    pairs = {(s[0], s[1]) for s in sessions}
    lines: list[str] = []
    for client_ip, server_ip in sorted(
        pairs,
        key=lambda p: (_ip_sort_key(p[0]), _ip_sort_key(p[1])),
    ):
        lines.append(f"{client_ip} -> {server_ip}:")
        for sess in sorted(
            (x for x in sessions if x[:2] == (client_ip, server_ip)),
            key=lambda x: (x[2], x[3]),
        ):
            _, _, cport, sport_, hs, fin_, rst_, ts, tc = sess
            lines.append(
                f"  {cport} -> {sport_}: handshake completed: {_yes_no(hs)}, "
                f"closed with FIN: {_yes_no(fin_)}, reset with RST: {_yes_no(rst_)}, "
                f"packets client->server: {ts}, server->client: {tc}"
            )
    return "TCP sessions per (client IP, server IP) pair:\n" + "\n".join(lines)


QUESTIONS: dict[str, Callable[[str], str]] = {
    Q1: list_ipv4_addresses,
    Q2: list_arp_flows,
    Q3: tcp_refused_with_rst,
    Q4: rfc1918_sources_udp_ports,
    Q5: tcp_sessions_per_ip_pair,
}


def _answer(func: Callable[[str], str], pcap: Path) -> str:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return func(str(pcap))
        except TSharkCrashException:
            if attempt == MAX_ATTEMPTS:
                raise
            print(f"(tshark crash reported, retrying {attempt}/{MAX_ATTEMPTS - 1})")
    raise AssertionError("unreachable")


def build_ground_truth(pcap: Path, output: Path) -> None:
    print(f"##### {pcap}\n")
    answers = {}
    for number, (question, func) in enumerate(QUESTIONS.items(), start=1):
        try:
            answers[question] = _answer(func, pcap)
        except Exception as exc:  # noqa: BLE001 - recorded like the paper does, then reported.
            answers[question] = f"ERROR: {exc}"
        print(f"=== Q{number}: {question}\n{answers[question]}\n")

    result = {"Filename": pcap.name, "Answer_Method": "Pyshark", "Questions": answers}
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Saved: {output}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog=f"Without arguments, answers the captures in {RAW_DIR}/ and writes gt_basic_demo.json "
        f"and gt_cicids_demo.json in {GT_DIR}/.",
    )
    parser.add_argument(
        "pcap", nargs="?", type=Path, help="single capture to answer about (default: both demo captures)"
    )
    parser.add_argument(
        "--output", type=Path, help=f"JSON file to write for PCAP (default: {GT_DIR}/gt_<pcap stem>.json)"
    )
    args = parser.parse_args()

    if args.pcap is None:
        if args.output is not None:
            parser.error("--output requires a PCAP argument")
        targets = DEFAULT_TARGETS
    else:
        targets = [(args.pcap, args.output or GT_DIR / f"gt_{args.pcap.stem}.json")]

    for pcap, output in targets:
        output.parent.mkdir(parents=True, exist_ok=True)
        build_ground_truth(pcap, output)


if __name__ == "__main__":
    main()
