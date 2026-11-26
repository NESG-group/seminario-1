"""Quiz de la demo: login LDAP, comprobación de respuestas y ranking.

Servicio independiente del backend de la demo: no importa nada del repositorio.
Las respuestas correctas solo viven en el servidor (``answers.json``) y nunca se
envían al navegador salvo, en el texto de las preguntas posteriores, los datos
que esa pregunta da por supuestos.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

log = logging.getLogger("quiz")

BASE_DIR = Path(__file__).resolve().parent
USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
COOKIE_NAME = "quiz_session"
LOGIN_MAX_FAILS = 5
LOGIN_WINDOW_S = 300.0
QUESTION_TYPES = ("ip", "port", "frame", "text")


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    auth_mode: str = "ldap"  # "ldap" | "dev" (dev: cualquier usuario con DEV_PASSWORD)
    dev_password: str = "dev"
    ldap_url: str = ""
    ldap_user_dn_template: str = ""  # p. ej. "uid={username},ou=people,dc=ejemplo,dc=org"
    ldap_bind_dn: str = ""  # alternativa: cuenta de servicio + búsqueda
    ldap_bind_password: str = ""
    ldap_base_dn: str = ""
    ldap_search_filter: str = "(uid={username})"
    ldap_display_attr: str = "cn"
    ldap_starttls: bool = False
    secret_key: str = ""
    db_path: str = "data/quiz.db"
    answers_file: str = str(BASE_DIR / "answers.json")
    admin_users: frozenset[str] = frozenset()
    session_hours: float = 12.0
    cookie_secure: bool = False
    chat_url: str = ""  # si se define, sustituye al chat_url de answers.json
    capture_file: str = ""  # captura que los participantes descargan para adjuntarla al chat

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ.get
        admins = frozenset(u.strip() for u in env("ADMIN_USERS", "").split(",") if u.strip())
        return cls(
            auth_mode=env("AUTH_MODE", "ldap").strip().lower(),
            dev_password=env("DEV_PASSWORD", "dev"),
            ldap_url=env("LDAP_URL", ""),
            ldap_user_dn_template=env("LDAP_USER_DN_TEMPLATE", ""),
            ldap_bind_dn=env("LDAP_BIND_DN", ""),
            ldap_bind_password=env("LDAP_BIND_PASSWORD", ""),
            ldap_base_dn=env("LDAP_BASE_DN", ""),
            ldap_search_filter=env("LDAP_SEARCH_FILTER", "(uid={username})"),
            ldap_display_attr=env("LDAP_DISPLAY_ATTR", "cn"),
            ldap_starttls=_env_bool("LDAP_STARTTLS"),
            secret_key=env("SECRET_KEY", ""),
            db_path=env("DB_PATH", "data/quiz.db"),
            answers_file=env("ANSWERS_FILE", str(BASE_DIR / "answers.json")),
            admin_users=admins,
            session_hours=float(env("SESSION_HOURS", "12")),
            cookie_secure=_env_bool("COOKIE_SECURE"),
            chat_url=env("CHAT_URL", ""),
            capture_file=env("CAPTURE_FILE", ""),
        )


@dataclass(frozen=True)
class Question:
    id: str
    type: str
    text: str
    answer: str
    points: int


@dataclass(frozen=True)
class QuizConfig:
    title: str
    chat_url: str
    capture_id: str
    max_attempts: int
    penalty: int
    min_points: int
    questions: tuple[Question, ...]


def normalize(kind: str, raw: str) -> str:
    """Normaliza una respuesta para compararla. Lanza ValueError si el formato no vale."""
    value = raw.strip()
    if kind == "ip":
        try:
            return str(ipaddress.ip_address(value))
        except ValueError as exc:
            raise ValueError("Formato de IP no válido (por ejemplo 192.168.1.10)") from exc
    if kind == "port":
        if not (value.isascii() and value.isdigit()) or not 0 <= int(value) <= 65535:
            raise ValueError("El puerto debe ser un número entre 0 y 65535")
        return str(int(value))
    if kind == "frame":
        if not (value.isascii() and value.isdigit()) or int(value) < 1:
            raise ValueError("El número de frame debe ser un entero positivo")
        return str(int(value))
    return " ".join(value.casefold().split())


def load_quiz(path: str | Path) -> QuizConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    questions: list[Question] = []
    seen: set[str] = set()
    for raw in data["questions"]:
        qid = str(raw["id"])
        kind = raw.get("type", "text")
        if qid in seen:
            raise ValueError(f"Pregunta duplicada: {qid}")
        if kind not in QUESTION_TYPES:
            raise ValueError(f"Tipo no válido en {qid}: {kind}")
        # Valida que la respuesta tenga el formato de su tipo.
        answer = normalize(kind, str(raw["answer"]))
        # Los marcadores {qN} solo pueden apuntar a preguntas anteriores.
        for ref in re.findall(r"\{(\w+)\}", raw["text"]):
            if ref not in seen:
                raise ValueError(f"{qid}: el texto usa {{{ref}}}, que no es una pregunta anterior")
        questions.append(
            Question(
                id=qid,
                type=kind,
                text=raw["text"],
                answer=answer,
                points=int(raw.get("points", data.get("base_points", 100))),
            )
        )
        seen.add(qid)
    if not questions:
        raise ValueError("answers.json no tiene preguntas")
    return QuizConfig(
        title=data.get("title", "Quiz"),
        chat_url=data.get("chat_url", ""),
        capture_id=data.get("capture_id", ""),
        max_attempts=int(data.get("max_attempts", 3)),
        penalty=int(data.get("penalty_per_wrong", 25)),
        min_points=int(data.get("min_points", 25)),
        questions=tuple(questions),
    )


def render_question_text(config: QuizConfig, index: int) -> str:
    """Rellena los {qN} del texto con las respuestas correctas de las preguntas anteriores."""
    known = {q.id: q.answer for q in config.questions[:index]}
    return config.questions[index].text.format_map(known)


# --------------------------------------------------------------------------- #
# Sesión firmada (sin dependencias extra)
# --------------------------------------------------------------------------- #


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_session(secret: str, payload: dict[str, Any]) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def verify_session(secret: str, token: str) -> dict[str, Any] | None:
    try:
        body, mac = token.split(".", 1)
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(mac), expected):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or float(payload.get("exp", 0)) < time.time():
        return None
    return payload


# --------------------------------------------------------------------------- #
# Autenticación
# --------------------------------------------------------------------------- #


def ldap_authenticate(settings: Settings, username: str, password: str) -> str | None:
    """Devuelve el nombre a mostrar si las credenciales son válidas, o None si no lo son.

    Dos modos: ``LDAP_USER_DN_TEMPLATE`` (bind directo con el DN del usuario) o
    ``LDAP_BIND_DN`` + ``LDAP_BASE_DN`` (cuenta de servicio que busca al usuario).
    """
    # Un bind LDAP con contraseña vacía es un bind anónimo y "funciona": se rechaza antes.
    if not username or not password:
        return None

    from ldap3 import Connection, Server
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_filter_chars
    from ldap3.utils.dn import escape_rdn

    server = Server(settings.ldap_url, connect_timeout=5)

    def _bind(dn: str, pwd: str) -> Connection | None:
        conn = Connection(server, user=dn, password=pwd, receive_timeout=10, raise_exceptions=False)
        try:
            conn.open()
            if settings.ldap_starttls:
                conn.start_tls()
            return conn if conn.bind() else None
        except LDAPException:
            log.exception("Error LDAP al conectar")
            return None

    try:
        if settings.ldap_bind_dn:
            service = _bind(settings.ldap_bind_dn, settings.ldap_bind_password)
            if service is None:
                log.error("No se pudo hacer bind con la cuenta de servicio LDAP")
                return None
            flt = settings.ldap_search_filter.format(username=escape_filter_chars(username))
            service.search(settings.ldap_base_dn, flt, attributes=[settings.ldap_display_attr], size_limit=2)
            entries = list(service.entries)
            service.unbind()
            if len(entries) != 1:
                return None
            entry = entries[0]
            user_conn = _bind(entry.entry_dn, password)
            if user_conn is None:
                return None
            user_conn.unbind()
            attr = entry[settings.ldap_display_attr] if settings.ldap_display_attr in entry else None
            return str(attr.value) if attr is not None and attr.value else username

        dn = settings.ldap_user_dn_template.format(username=escape_rdn(username))
        conn = _bind(dn, password)
        if conn is None:
            return None
        conn.unbind()
        return username
    except LDAPException:
        log.exception("Error LDAP")
        return None


def authenticate(settings: Settings, username: str, password: str) -> str | None:
    if settings.auth_mode == "dev":
        return username if password == settings.dev_password else None
    return ldap_authenticate(settings, username, password)


# --------------------------------------------------------------------------- #
# Almacenamiento
# --------------------------------------------------------------------------- #

_SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    question_id TEXT NOT NULL,
    answer TEXT NOT NULL,
    correct INTEGER NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts (username, question_id);
"""


class Store:
    """SQLite mínimo. Un solo candado serializa las escrituras (escala de demo)."""

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._memory: sqlite3.Connection | None = None
        if path == ":memory:":
            self._memory = sqlite3.connect(":memory:", check_same_thread=False)
            self._memory.row_factory = sqlite3.Row
        with self.tx() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._memory or sqlite3.connect(self.path, timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if self._memory is None:
                    conn.close()


@dataclass
class Progress:
    wrong: int = 0
    solved: bool = False
    points: int = 0


def user_progress(conn: sqlite3.Connection, username: str) -> dict[str, Progress]:
    out: dict[str, Progress] = defaultdict(Progress)
    rows = conn.execute("SELECT question_id, correct, points FROM attempts WHERE username = ? ORDER BY id", (username,))
    for row in rows:
        prog = out[row["question_id"]]
        if row["correct"]:
            prog.solved = True
            prog.points = row["points"]
        else:
            prog.wrong += 1
    return out


def question_status(config: QuizConfig, progress: dict[str, Progress], index: int) -> str:
    """locked | open | solved | failed"""
    q = config.questions[index]
    prog = progress.get(q.id, Progress())
    if prog.solved:
        return "solved"
    if prog.wrong >= config.max_attempts:
        return "failed"
    if index == 0:
        return "open"
    prev = config.questions[index - 1]
    prev_prog = progress.get(prev.id, Progress())
    prev_done = prev_prog.solved or prev_prog.wrong >= config.max_attempts
    return "open" if prev_done else "locked"


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


class LoginBody(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class AnswerBody(BaseModel):
    question_id: str = Field(max_length=32)
    answer: str = Field(max_length=100)


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    is_admin: bool


def current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE_NAME, "")
    payload = verify_session(request.app.state.session_secret, token) if token else None
    if payload is None:
        raise HTTPException(status_code=401, detail="Sesión no iniciada")
    username = str(payload["u"])
    return User(username, str(payload.get("n", username)), username in request.app.state.admin_users)


CurrentUser = Annotated[User, Depends(current_user)]


def _csv_safe(value: str) -> str:
    """Evita inyección de fórmulas al abrir el CSV en una hoja de cálculo."""
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.auth_mode not in ("ldap", "dev"):
        raise RuntimeError("AUTH_MODE debe ser 'ldap' o 'dev'")
    secret = settings.secret_key
    if not secret:
        if settings.auth_mode == "ldap":
            raise RuntimeError("Falta SECRET_KEY (cadena aleatoria larga) para firmar las sesiones")
        secret = secrets.token_hex(32)
        log.warning("Modo dev sin SECRET_KEY: las sesiones se pierden al reiniciar")
    if settings.auth_mode == "dev":
        log.warning("AUTH_MODE=dev: cualquier usuario entra con DEV_PASSWORD. No usar en el evento.")
    elif not (settings.ldap_url and (settings.ldap_user_dn_template or settings.ldap_bind_dn)):
        raise RuntimeError("Configura LDAP_URL y LDAP_USER_DN_TEMPLATE (o LDAP_BIND_DN + LDAP_BASE_DN)")

    config = load_quiz(settings.answers_file)
    capture_path = Path(settings.capture_file) if settings.capture_file else None
    if capture_path is not None and not capture_path.is_file():
        raise RuntimeError(f"CAPTURE_FILE no existe: {capture_path}")
    chat_url = settings.chat_url or config.chat_url
    store = Store(settings.db_path)
    failures: dict[str, deque[float]] = defaultdict(deque)

    app = FastAPI(title="Demo quiz", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.session_secret = secret
    app.state.admin_users = settings.admin_users

    @app.post("/api/login")
    def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
        username = body.username.strip()
        key = f"{request.client.host if request.client else '?'}|{username.lower()}"
        now = time.time()
        window = failures[key]
        while window and now - window[0] > LOGIN_WINDOW_S:
            window.popleft()
        if len(window) >= LOGIN_MAX_FAILS:
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera unos minutos.")
        display = authenticate(settings, username, body.password) if USERNAME_RE.match(username) else None
        if display is None:
            window.append(now)
            raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
        failures.pop(key, None)
        token = sign_session(secret, {"u": username, "n": display, "exp": now + settings.session_hours * 3600})
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=int(settings.session_hours * 3600),
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
        )
        return {"username": username, "display_name": display, "is_admin": username in settings.admin_users}

    @app.post("/api/logout")
    def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(COOKIE_NAME)
        return {"ok": True}

    @app.get("/api/me")
    def me(user: CurrentUser) -> dict[str, Any]:
        return {"username": user.username, "display_name": user.display_name, "is_admin": user.is_admin}

    @app.get("/api/state")
    def state(user: CurrentUser) -> dict[str, Any]:
        with store.tx() as conn:
            progress = user_progress(conn, user.username)
        items = []
        total = 0
        for index, q in enumerate(config.questions):
            status = question_status(config, progress, index)
            prog = progress.get(q.id, Progress())
            total += prog.points
            items.append(
                {
                    "id": q.id,
                    "number": index + 1,
                    "type": q.type,
                    "status": status,
                    "text": None if status == "locked" else render_question_text(config, index),
                    "attempts_used": prog.wrong + (1 if prog.solved else 0),
                    "attempts_left": 0 if status in ("solved", "failed") else config.max_attempts - prog.wrong,
                    "points": prog.points,
                    "max_points": q.points,
                }
            )
        return {
            "title": config.title,
            "chat_url": chat_url,
            "capture_download": capture_path is not None,
            "capture_id": config.capture_id,
            "max_attempts": config.max_attempts,
            "total_points": total,
            "questions": items,
        }

    @app.post("/api/answer")
    def answer(body: AnswerBody, user: CurrentUser) -> dict[str, Any]:
        index = next((i for i, q in enumerate(config.questions) if q.id == body.question_id), None)
        if index is None:
            raise HTTPException(status_code=404, detail="Pregunta no encontrada")
        q = config.questions[index]
        try:
            given = normalize(q.type, body.answer)
        except ValueError as exc:
            # Un formato inválido no consume intento.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with store.tx() as conn:
            progress = user_progress(conn, user.username)
            status = question_status(config, progress, index)
            if status == "locked":
                raise HTTPException(status_code=409, detail="Responde antes la pregunta anterior")
            if status in ("solved", "failed"):
                raise HTTPException(status_code=409, detail="Esta pregunta ya está cerrada")
            wrong = progress.get(q.id, Progress()).wrong
            correct = hmac.compare_digest(given, q.answer)
            points = max(config.min_points, q.points - config.penalty * wrong) if correct else 0
            conn.execute(
                "INSERT INTO attempts (username, display_name, question_id, answer, correct, points, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user.username, user.display_name, q.id, given, int(correct), points, time.time()),
            )
        left = 0 if correct else max(0, config.max_attempts - (wrong + 1))
        return {
            "correct": correct,
            "points": points,
            "attempts_left": left,
            "status": "solved" if correct else ("failed" if left == 0 else "open"),
        }

    @app.get("/api/capture")
    def capture(user: CurrentUser) -> FileResponse:
        if capture_path is None:
            raise HTTPException(status_code=404, detail="No hay captura para descargar")
        return FileResponse(capture_path, media_type="application/vnd.tcpdump.pcap", filename=capture_path.name)

    @app.get("/api/ranking")
    def ranking(user: CurrentUser) -> dict[str, Any]:
        with store.tx() as conn:
            rows = conn.execute(
                """
                SELECT username, MAX(display_name) AS display_name, SUM(points) AS points,
                       SUM(correct) AS solved,
                       MAX(CASE WHEN correct = 1 THEN created_at END) AS last_solved
                FROM attempts GROUP BY username
                ORDER BY points DESC, (last_solved IS NULL), last_solved ASC, username ASC
                LIMIT 100
                """
            ).fetchall()
        entries = [
            {
                "rank": i + 1,
                "name": r["display_name"] or r["username"],
                "points": r["points"],
                "solved": r["solved"],
                "me": r["username"] == user.username,
            }
            for i, r in enumerate(rows)
        ]
        return {"total_questions": len(config.questions), "entries": entries}

    @app.get("/api/admin/results.csv")
    def results_csv(user: CurrentUser) -> PlainTextResponse:
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Solo administradores")
        with store.tx() as conn:
            rows = conn.execute(
                """
                SELECT username, MAX(display_name) AS display_name, question_id,
                       COUNT(*) AS attempts, MAX(correct) AS solved, SUM(points) AS points,
                       MAX(created_at) AS last_attempt
                FROM attempts GROUP BY username, question_id ORDER BY username, question_id
                """
            ).fetchall()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["username", "display_name", "question_id", "attempts", "solved", "points", "last_attempt_utc"])
        for r in rows:
            stamp = datetime.fromtimestamp(r["last_attempt"], UTC).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow(
                [
                    _csv_safe(r["username"]),
                    _csv_safe(r["display_name"]),
                    r["question_id"],
                    r["attempts"],
                    r["solved"],
                    r["points"],
                    stamp,
                ]
            )
        return PlainTextResponse(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="quiz_results.csv"'},
        )

    app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")
    return app


def app_factory() -> FastAPI:
    """Entrada para ``uvicorn app:app_factory --factory``."""
    return create_app()
