# Data

```
data/
├── CryLock_final.pcap   capture used in the seminar
└── fixtures/            captures used only by the test suite
```

## Seminar capture

`CryLock_final.pcap` is the capture analysed in the seminar: CryLock ransomware
traffic in which an infected machine encrypts files on an SMB file server. The
questions asked about it, and their answers, are in the [quiz](../quiz/README.md).

## Test fixtures

The captures in `fixtures/` (traces T1 and T2 of Table II in the companion
paper, *Do LLMs Understand Network Traces?*) are kept for the test suite.

| File | Trace | Traffic | Packets (default / ARP / IP / TCP / UDP) |
| --- | --- | --- | --- |
| `arp-icmp.pcapng` | T1 | Host initialisation: neighbour discovery, address resolution, connectivity checks | 23 / 7 / 6 / 0 / 0 |
| `ip-networktrace2.pcapng` | T2 | Connectivity tests, DNS, IP fragmentation, failed TCP connections | 29 / 0 / 29 / 7 / 6 |
