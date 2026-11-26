"""Copy the LDAP/sign-up settings from Open WebUI's environment into its database.

Open WebUI reads these variables only on its first start; afterwards it uses
the values saved in its database (``config`` table), so changing them in
docker-compose.multiuser.yml or .env has no effect on an existing install.
This script writes the current environment values into that table.

Run inside the Open WebUI container, then restart it (``make multiuser-config``
does both):

    docker exec -i demo-ui-dev python3 - < scripts/openwebui_auth_config.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time

DB_PATH = "/app/backend/data/webui.db"


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).lower() == "true"


# Same defaults as Open WebUI's config.py.
SETTINGS: dict[str, object] = {
    "ui.enable_signup": _flag("ENABLE_SIGNUP", "true"),
    "ui.default_user_role": os.environ.get("DEFAULT_USER_ROLE", "pending"),
    "ldap.enable": _flag("ENABLE_LDAP", "false"),
    "ldap.server.label": os.environ.get("LDAP_SERVER_LABEL", "LDAP Server"),
    "ldap.server.host": os.environ.get("LDAP_SERVER_HOST", "localhost"),
    "ldap.server.port": int(os.environ.get("LDAP_SERVER_PORT", "389")),
    "ldap.server.attribute_for_mail": os.environ.get("LDAP_ATTRIBUTE_FOR_MAIL", "mail"),
    "ldap.server.attribute_for_username": os.environ.get("LDAP_ATTRIBUTE_FOR_USERNAME", "uid"),
    "ldap.server.app_dn": os.environ.get("LDAP_APP_DN", ""),
    "ldap.server.app_password": os.environ.get("LDAP_APP_PASSWORD", ""),
    "ldap.server.users_dn": os.environ.get("LDAP_SEARCH_BASE", ""),
    "ldap.server.search_filter": os.environ.get("LDAP_SEARCH_FILTER", os.environ.get("LDAP_SEARCH_FILTERS", "")),
    "ldap.server.use_tls": _flag("LDAP_USE_TLS", "true"),
    "ldap.server.validate_cert": _flag("LDAP_VALIDATE_CERT", "true"),
}

SECRET_KEYS = {"ldap.server.app_password"}


def main() -> int:
    if not _flag("ENABLE_LDAP", "false"):
        print("ENABLE_LDAP is not true in this container: start it with docker-compose.multiuser.yml", file=sys.stderr)
        return 1
    db = sqlite3.connect(DB_PATH)
    now = int(time.time())
    with db:
        for key, value in SETTINGS.items():
            encoded = json.dumps(value)
            updated = db.execute("UPDATE config SET value = ?, updated_at = ? WHERE key = ?", (encoded, now, key))
            if updated.rowcount == 0:
                db.execute("INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)", (key, encoded, now))
            shown = "***" if key in SECRET_KEYS and value else encoded
            print(f"{key} = {shown}")
    db.close()
    print("Saved. Restart Open WebUI to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
