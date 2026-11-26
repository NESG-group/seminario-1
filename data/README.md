# Demo data

```
data/
├── demo/
│   ├── raw/                  captures used in the demo
│   ├── ground_truth/         reference answers, one JSON per capture (make ground-truth)
│   └── scenarios.md          paper scenarios: questions, answers, audit, ground truth
└── fixtures/                 other captures, used only by the test suite
```

## Demo capture

The demo uses a single capture:

| File | Traffic | Packets (default / ARP / IP / TCP / UDP) |
| --- | --- | --- |
| [`demo/raw/nmap22-23-53-80-443-threewayhandshake.pcapng`](demo/raw/nmap22-23-53-80-443-threewayhandshake.pcapng) | Nmap host discovery and scan of ports 22, 23, 53, 80 and 443 (ARP, UDP, TCP, ICMP), including TCP three-way handshake completion | 34 / 4 / 30 / 16 / 8 |

It corresponds to trace T4 of Table II in the companion paper, *Do LLMs
Understand Network Traces?*. It contains no ARP spoofing: every IP resolves to a
single MAC.

## Scenarios

[demo/scenarios.md](demo/scenarios.md) lists the scenarios used in the NOMS
2027 demo paper: the exact questions asked, the view each one should use, the
model answers, the audit records (`PCAP_VIEW_APPLIED`) and the ground truth.

[demo/ground_truth/](demo/ground_truth/) holds the reference answer of every
scenario for each capture in `demo/raw/` (`gt_basic_demo.json` for the nmap
capture, `gt_cicids_demo.json` for the CIC-IDS2017 Monday sample), computed with PyShark by
[scripts/ground_truth.py](../scripts/ground_truth.py), following the method of
the companion paper's repository. Q1-Q3 are questions of the paper and match its
ground truth for this trace; the convention used for each question is written
next to its function. To regenerate it (needs `tshark` on the host):

```bash
make ground-truth
```

## Test fixtures

The captures in `fixtures/` (traces T1-T3 of the same table) are not used in
the demo. They are kept as fixtures for the test suite.

| File | Trace | Traffic | Packets (default / ARP / IP / TCP / UDP) |
| --- | --- | --- | --- |
| `arp-icmp.pcapng` | T1 | Host initialisation: neighbour discovery, address resolution, connectivity checks | 23 / 7 / 6 / 0 / 0 |
| `ip-networktrace2.pcapng` | T2 | Connectivity tests, DNS, IP fragmentation, failed TCP connections | 29 / 0 / 29 / 7 / 6 |
| `nmap22-23-53-80-443.pcapng` | T3 | Nmap TCP SYN and UDP scan, ICMP from closed ports | 32 / 4 / 27 / 13 / 8 |
