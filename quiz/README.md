# Quiz de la demo NOMS 2027

Formulario web con login LDAP + backend que valida las respuestas y mantiene un ranking.

## Cómo funciona
- El usuario entra con su usuario/contraseña LDAP.
- Ve las 5 preguntas de forma progresiva: la siguiente se desbloquea al acertar la anterior
- Puntuación: 100 puntos por pregunta, −25 por cada fallo (mínimo 25), máximo 3 intentos.
- El backend compara con `answers.json` (las respuestas nunca llegan al navegador).
- Ranking en `/api/ranking` (se muestra en la web). CSV para admins en `/api/admin/results.csv`.

## Arrancar en local (sin LDAP)
```bash
pip install -r requirements.txt
AUTH_MODE=dev DEV_PASSWORD=pw SECRET_KEY=algo ADMIN_USERS=irene \
  uvicorn app:app_factory --factory --port 8080
```
Abrir http://127.0.0.1:8080 (cualquier usuario, contraseña `pw`).

## Con el chat (modo multiusuario)
Es la forma de usarlo en el seminario. `make up-multiuser` (en la raíz del repo) levanta
el quiz en `https://<DEMO_HOST>:9443` con el mismo LDAP, cuenta de servicio y búsqueda que
Open WebUI: los participantes entran con el mismo usuario y contraseña que en el chat.
Toda la configuración sale del `.env` raíz (`QUIZ_SECRET_KEY` lo crea `make multiuser-env`)
y de `docker-compose.multiuser.yml`; el `.env` de esta carpeta no se usa.

Cada usuario solo ve en el chat las capturas que ha subido él, así que `capture_id` va
vacío en `answers.json`: el quiz ofrece la captura para descargar (`CAPTURE_FILE`) y cada
participante la adjunta en su chat.

## Con LDAP y Docker (independiente)
```bash
cp .env.example .env      # editar LDAP_*, SECRET_KEY, ADMIN_USERS
docker compose up -d --build
```
Dos modos LDAP: bind directo (`LDAP_USER_DN_TEMPLATE`) o cuenta de servicio + búsqueda
(`LDAP_BIND_DN`, `LDAP_BIND_PASSWORD`, `LDAP_BASE_DN`, `LDAP_SEARCH_FILTER`).

## Respuestas
`answers.json` contiene las respuestas correctas y NO se sube a git (ver `.gitignore`).
`answers.example.json` es la plantilla. Si el repo es público, no commitees las reales.
Tipos de respuesta normalizados: ip, port (número) y texto.

## Antes del evento
- `AUTH_MODE=ldap` (el modo `dev` deja entrar a cualquiera).
- Servir por HTTPS y `COOKIE_SECURE=true`.
- `SECRET_KEY` larga y aleatoria; la base SQLite vive en el volumen `/data`.

## Tests
```bash
pip install -r requirements-dev.txt && python -m pytest -q tests
```
