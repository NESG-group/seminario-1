# Quiz de la demo NOMS 2027

Formulario web con login LDAP + backend que valida las respuestas y mantiene un ranking.

## Cómo funciona
- El usuario entra con su usuario/contraseña LDAP.
- Ve las 5 preguntas de forma progresiva: la siguiente se desbloquea al acertar la anterior
- Puntuación: 100 puntos por pregunta, −25 por cada fallo (mínimo 25), máximo 3 intentos.
- Cada pregunta muestra solo el objetivo (`goal`, "Averigua..."): el participante formula
  su propia pregunta al asistente. La pista (`hint`) es la pregunta exacta para copiar al
  chat; pedirla resta `hint_penalty` puntos (50 por defecto) antes del multiplicador, una
  sola vez, y respetando el mínimo. Al cerrar la pregunta, la pista se muestra sin coste.
- Bonus por rapidez (`speed_multipliers` en `answers.json`): en cada pregunta, la 1ª persona
  en acertar multiplica ×2, la 2ª ×1,75, la 3ª ×1,5, la 4ª ×1,25 y el resto ×1 (sin la
  clave, no hay bonus). El orden lo decide la llegada al servidor. Empate a puntos: gana
  quien terminó antes.
- Ranking en directo con podio y feed de últimos aciertos; animaciones al acertar/fallar
  (se desactivan con *reducir movimiento* del sistema).
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

La captura del seminario está en el datalake como compartida (`make share-capture` en la
raíz), visible para todos los usuarios del chat. Su ID va en `capture_id` de `answers.json`:
el quiz lo muestra y lo añade a la pista que se copia al chat. Si se vuelve a subir la captura,
cambia el ID: actualízalo en `answers.json` y en las instrucciones, y reconstruye el quiz.

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
En `goal` y `hint`, `{qN}` se sustituye por la respuesta correcta de una pregunta anterior.

## Antes del evento
- `AUTH_MODE=ldap` (el modo `dev` deja entrar a cualquiera).
- Servir por HTTPS y `COOKIE_SECURE=true`.
- `SECRET_KEY` larga y aleatoria; la base SQLite vive en el volumen `/data`.

## Tests
```bash
pip install -r requirements-dev.txt && python -m pytest -q tests
```
