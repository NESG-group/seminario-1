"""Lógica de login LDAP probada contra el servidor simulado de ldap3 (sin red)."""

from __future__ import annotations

import sys
from pathlib import Path

import ldap3
import pytest
from ldap3 import MOCK_SYNC, Connection, Server

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as quiz  # noqa: E402


@pytest.fixture
def fake_ldap(monkeypatch):
    fake = Server("fake-ldap")
    seed = Connection(fake, user="cn=admin,dc=ej,dc=org", password="adminpw", client_strategy=MOCK_SYNC)
    seed.strategy.add_entry("cn=admin,dc=ej,dc=org", {"userPassword": "adminpw", "objectClass": "inetOrgPerson"})
    seed.strategy.add_entry(
        "uid=ana,ou=people,dc=ej,dc=org",
        {"userPassword": "secreta", "cn": "Ana Pérez", "uid": "ana", "objectClass": "inetOrgPerson"},
    )
    real = ldap3.Connection

    def mock_connection(server, **kwargs):
        kwargs["client_strategy"] = MOCK_SYNC
        return real(fake, **kwargs)

    monkeypatch.setattr(ldap3, "Connection", mock_connection)


def test_direct_bind_with_dn_template(fake_ldap):
    s = quiz.Settings(ldap_url="ldap://fake", ldap_user_dn_template="uid={username},ou=people,dc=ej,dc=org")
    assert quiz.ldap_authenticate(s, "ana", "secreta") == "ana"
    assert quiz.ldap_authenticate(s, "ana", "incorrecta") is None
    assert quiz.ldap_authenticate(s, "ana", "") is None
    assert quiz.ldap_authenticate(s, "ana,ou=x", "secreta") is None  # el DN se escapa


def test_service_account_search(fake_ldap):
    s = quiz.Settings(
        ldap_url="ldap://fake",
        ldap_bind_dn="cn=admin,dc=ej,dc=org",
        ldap_bind_password="adminpw",
        ldap_base_dn="ou=people,dc=ej,dc=org",
    )
    assert quiz.ldap_authenticate(s, "ana", "secreta") == "Ana Pérez"
    assert quiz.ldap_authenticate(s, "ana", "incorrecta") is None
    assert quiz.ldap_authenticate(s, "nadie", "x") is None
    assert quiz.ldap_authenticate(s, "*", "secreta") is None  # comodín escapado
    assert quiz.ldap_authenticate(s, "ana)(uid=*", "secreta") is None  # inyección de filtro


def test_login_endpoint_uses_ldap(fake_ldap, tmp_path):
    from fastapi.testclient import TestClient

    settings = quiz.Settings(
        auth_mode="ldap",
        ldap_url="ldap://fake",
        ldap_bind_dn="cn=admin,dc=ej,dc=org",
        ldap_bind_password="adminpw",
        ldap_base_dn="ou=people,dc=ej,dc=org",
        secret_key="s",
        db_path=str(tmp_path / "q.db"),
    )
    client = TestClient(quiz.create_app(settings))
    ok = client.post("/api/login", json={"username": "ana", "password": "secreta"})
    assert ok.status_code == 200 and ok.json()["display_name"] == "Ana Pérez"
    assert client.get("/api/me").json()["username"] == "ana"
    bad = TestClient(client.app).post("/api/login", json={"username": "ana", "password": "mal"})
    assert bad.status_code == 401


def test_service_account_search_with_compose_filter(fake_ldap):
    s = quiz.Settings(
        ldap_url="ldap://fake",
        ldap_bind_dn="cn=admin,dc=ej,dc=org",
        ldap_bind_password="adminpw",
        ldap_base_dn="ou=people,dc=ej,dc=org",
        ldap_search_filter="(&(uid={username}))",
    )
    assert quiz.ldap_authenticate(s, "ana", "secreta") == "Ana Pérez"
    assert quiz.ldap_authenticate(s, "ana", "incorrecta") is None
    assert quiz.ldap_authenticate(s, "ana)(uid=*", "secreta") is None
