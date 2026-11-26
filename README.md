# NOMS 2027 demo

Code of the NOMS 2027 demo paper *From Natural-Language Questions to Auditable
Packet Evidence with an Agentic LLM*: an analyst question in Open WebUI becomes a **fixed, audited
tshark filter** over a stored capture, and the LLM answers from that evidence.
This repository contains only what that flow needs.

```
Open WebUI -> demo-backend (FastAPI) -> Hermes Agent -> Ollama
                    |  sanitise, stage attachments,  |
                    |  prepend scope prompt          |
                    +--------- MCP (/mcp) -----------+
                       pcap_tcp / pcap_arp / ... -> tshark -> audit line
```

## The flow

1. The analyst asks in Open WebUI (`docker-compose.dev-ui.yml`).
2. The API ([chat.py](src/demo/api/v1/chat.py)) stages attachments
   outside the conversation ([staging.py](src/demo/api/v1/pcap/staging.py):
   the model only sees a `pcap_ref`) and prepends the scope prompt
   ([scope.py](src/demo/services/scope.py)).
3. Hermes offers the model its skills and the MCP tools of
   [server.py](src/demo/mcp/server.py).
4. The model loads the `pcap-filter` skill
   ([SKILL.md](hermes/skills/security/pcap-filter/SKILL.md)) and picks a view
   (`pcap_tcp`, `pcap_arp`, ...).
5. The view ([filter_pcaps.py](src/demo/mcp/tools/filter_pcaps.py)) runs a
   hard-coded display filter and logs one audit line, independent of what the
   model later says:
   ```
   PCAP_VIEW_APPLIED {"capture_id": "...", "tool": "pcap_tcp", "display_filter": "tcp && !icmp && !icmpv6", ...}
   ```
6. The model answers using that evidence.

| View | Fixed display filter |
| --- | --- |
| `pcap_tcp` | `tcp && !icmp && !icmpv6` |
| `pcap_udp` | `udp && !icmp && !icmpv6` |
| `pcap_arp` | `arp` |
| `pcap_ip` | `ip` |

## Run it

### Requirements

- Linux with an NVIDIA GPU, Docker with Compose v2, the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/),
  `make` and `openssl`.
- Enough GPU memory for Qwen 2.5 72B with a 64K context (the model alone is
  47 GB), and about 60 GB of free disk for the images and the model.
- Free ports 3000, 5432, 8000, 8642, 9119 and 11435.

All images are pinned in `docker-compose.yml` and `docker-compose.dev-ui.yml`
to the versions used for the paper results.

### Start the system

```bash
git clone https://github.com/NESG-group/demo-noms-2027.git && cd demo-noms-2027
make env            # creates .env: random Hermes API key and your UID/GID
make up             # postgres, ollama, hermes, backend
make ollama-model   # pulls qwen2.5:72b (about 47 GB, only the first time)
make up-ui          # Open WebUI
```

The backend applies the datalake schema on start. Check that the chain works
end to end; it should list the `hermes-agent` model:

```bash
curl -s http://localhost:8000/v1/models
```

If it fails, look at `docker logs demo-hermes` and
`docker logs demo-backend`.

### Ask the questions

1. Open http://localhost:3000. The first time, Open WebUI asks you to create
   an admin account; it is local to your machine.
2. Pick the `hermes-agent` model.
3. Attach [`data/CryLock_final.pcap`](data/README.md), the seminar capture,
   to the chat and ask the questions of the [quiz](quiz/README.md).

To see which views the model applied (one line per view call, written by the
backend whatever the model says):

```bash
docker logs demo-backend 2>&1 | grep PCAP_VIEW_APPLIED
```

To see the tokens used by each question (`N=20` for more rows, `ALL=1` to
include Open WebUI's own background requests):

```bash
make tokens
```

To stop everything: `make down`. Data and the model stay in Docker volumes.

## Multi-user access (optional)

[docker-compose.multiuser.yml](docker-compose.multiuser.yml) adds an HTTPS
proxy (Caddy) and LDAP login (a bundled [LLDAP](https://github.com/lldap/lldap)
server) on top of the setup above, plus the [seminar quiz](#seminar-quiz).
Only the proxy listens on the network (ports 80/443 for the chat, 9443 for the
quiz (`QUIZ_PORT`)); everything else stays on `127.0.0.1`. Each user sees only the
captures they uploaded plus the shared ones, and every audit record names the user.

```bash
make multiuser-env      # adds secrets and DEMO_HOST (this machine's IP) to .env
make up-multiuser       # starts everything plus proxy and LLDAP
make multiuser-config   # copies the LDAP settings into Open WebUI's database, restarts it
```

`make multiuser-config` is needed because Open WebUI only reads its LDAP and
sign-up variables on its first start; on an existing install it uses the
values saved in its database.

**Users.** Open the LLDAP admin page at http://127.0.0.1:17170 (from this
machine, or through an SSH/VS Code port forward), log in as `admin` with
`LLDAP_ADMIN_PASSWORD` from `.env`, and create each user with an email
address. They log in at `https://<DEMO_HOST>` with the LDAP form. The local
Open WebUI admin account keeps working.

**Certificate.** Caddy signs the certificate with its own CA, so browsers warn
until that CA is trusted. Export it and install it as a trusted root on the
users' machines (or accept the warning):

```bash
docker exec demo-proxy cat /data/caddy/pki/authorities/local/root.crt > caddy-root.crt
```

**Another LDAP server.** Set the `LDAP_*` variables in `.env` (see
[env.example](env.example)), run `make up-multiuser` and `make multiuser-config`
again. LLDAP then simply goes unused.

**How identity reaches the tools.** Open WebUI signs each request with the
user's identity (JWT, `USER_JWT_SECRET`) and the backend verifies it. The MCP
tools are called by Hermes, not by the user, so the backend runs one chat at a
time and the tools filter by the user of the running chat
([requester.py](src/demo/services/requester.py)). Ollama answers one request
at a time anyway, so this costs no throughput. Nothing the model sees changes.
Captures uploaded with `shared=true` (`make share-capture`) are visible to every
user. Captures stored before multi-user mode have no owner and, unless shared,
are not shown to anyone in this mode.

## Development

```bash
uv sync --all-groups
make test lint
```

The sensor, the ingest-time actor analysis and the evaluation scripts of the
full project are intentionally not part of this repository.

## Seminar quiz

[quiz/](quiz/README.md) is a web form (FastAPI) with the questions asked during
the seminar about `data/CryLock_final.pcap`. It checks each answer on the
server and keeps a ranking. The real answers live in `quiz/answers.json`, which
is not committed; copy `quiz/answers.example.json` and fill it in before
starting.

In multi-user mode `make up-multiuser` also starts the quiz at
`https://<DEMO_HOST>:9443`. It logs users in against the same LDAP server, with
the same service account and search as Open WebUI, so every participant uses
the same username and password for the chat and for the quiz. LDAP users listed
in `QUIZ_ADMIN_USERS` (default `admin`) can download the results as CSV.
Each question shows what to find out; its hint, the exact question for the chat,
costs `hint_penalty` points (default 50).
`make quiz-reset` empties the quiz (attempts, hints, points and ranking) after you type
`reset`; sessions stay open, so participants only need to reload the page.

The seminar capture lives in the datalake as a **shared** capture, which every
user can query in multi-user mode, so participants never get the file:

```bash
make share-capture      # uploads data/CryLock_final.pcap with shared=true, prints its capture_id
```

Put that `capture_id` in `quiz/answers.json` and in the instructions, then
rebuild the quiz (`make up-multiuser`). The quiz shows it and adds it to the
text copied into the chat. `SHARED_CAPTURE=<file>` shares another capture.

The instructions handed to participants are in
[docs/instrucciones-seminario-1.md](docs/instrucciones-seminario-1.md). The quiz
publishes them, without login, at `https://<DEMO_HOST>:9443/instrucciones` and
links them from its login page; edits to the file show on the next reload.
