from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as quiz  # noqa: E402

ANSWERS = Path(__file__).resolve().parent.parent / "answers.json"


def make_client(tmp_path, **overrides) -> TestClient:
    settings = quiz.Settings(
        auth_mode="dev",
        dev_password="pw",
        secret_key="test-secret",
        db_path=str(tmp_path / "quiz.db"),
        answers_file=str(ANSWERS),
        admin_users=frozenset({"admin"}),
        **overrides,
    )
    return TestClient(quiz.create_app(settings))


def login(client: TestClient, user: str, password: str = "pw"):
    return client.post("/api/login", json={"username": user, "password": password})


def answer(client: TestClient, qid: str, value: str):
    return client.post("/api/answer", json={"question_id": qid, "answer": value})


def test_requires_login(tmp_path):
    c = make_client(tmp_path)
    assert c.get("/api/state").status_code == 401
    assert c.post("/api/answer", json={"question_id": "q1", "answer": "1.1.1.1"}).status_code == 401
    assert c.get("/api/ranking").status_code == 401


def test_bad_password_and_username(tmp_path):
    c = make_client(tmp_path)
    assert login(c, "ana", "wrong").status_code == 401
    assert login(c, "ana; drop").status_code == 401
    assert login(c, "ana").status_code == 200


def test_initial_state_hides_locked_questions_and_answers(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    data = c.get("/api/state").json()
    assert [q["status"] for q in data["questions"]] == ["open", "locked", "locked", "locked", "locked"]
    assert data["questions"][1]["text"] is None
    assert "192.168.1.4" not in json.dumps(data)
    assert "49183" not in json.dumps(data)


def test_correct_flow_unlocks_in_order_and_fills_context(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    assert answer(c, "q2", "192.168.1.5").status_code == 409  # bloqueada

    r = answer(c, "q1", " 192.168.1.4 ").json()
    assert r["correct"] and r["points"] == 100 and r["status"] == "solved"

    assert answer(c, "q2", "192.168.1.5").json()["correct"]
    assert answer(c, "q3", "445").json()["correct"]

    assert answer(c, "q4", "4087").json()["correct"]
    q5 = c.get("/api/state").json()["questions"][4]
    assert q5["status"] == "open"
    assert all(x in q5["text"] for x in ("4087", "192.168.1.4", "192.168.1.5", "445"))
    assert "49183" not in q5["text"]
    assert answer(c, "q5", "49183").json()["points"] == 100
    assert c.get("/api/state").json()["total_points"] == 500


def test_wrong_answers_reduce_points_and_close_question(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    r = answer(c, "q1", "192.168.1.3").json()
    assert not r["correct"] and r["attempts_left"] == 2
    r = answer(c, "q1", "192.168.1.9").json()
    assert r["attempts_left"] == 1
    r = answer(c, "q1", "192.168.1.4").json()
    assert r["correct"] and r["points"] == 50  # 100 - 2 * 25

    r = answer(c, "q2", "10.0.0.1").json()
    answer(c, "q2", "10.0.0.2")
    r = answer(c, "q2", "10.0.0.3").json()
    assert r["status"] == "failed" and r["attempts_left"] == 0
    assert answer(c, "q2", "192.168.1.5").status_code == 409  # cerrada
    # Agotar los intentos desbloquea la siguiente.
    assert c.get("/api/state").json()["questions"][2]["status"] == "open"


def test_min_points(tmp_path):
    cfg = json.loads(ANSWERS.read_text())
    cfg["max_attempts"] = 10
    cfg["penalty_per_wrong"] = 40
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(cfg))
    settings = quiz.Settings(
        auth_mode="dev", dev_password="pw", secret_key="s", db_path=str(tmp_path / "q.db"), answers_file=str(path)
    )
    c = TestClient(quiz.create_app(settings))
    login(c, "ana")
    for i in range(5):
        answer(c, "q1", f"10.0.0.{i + 1}")
    assert answer(c, "q1", "192.168.1.4").json()["points"] == 25  # min_points


def test_invalid_format_does_not_consume_attempt(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    assert answer(c, "q1", "no es una ip").status_code == 422
    assert answer(c, "q1", "999.1.1.1").status_code == 422
    assert c.get("/api/state").json()["questions"][0]["attempts_left"] == 3
    answer(c, "q1", "192.168.1.4")
    answer(c, "q2", "192.168.1.5")
    assert answer(c, "q3", "70000").status_code == 422
    assert answer(c, "q3", "44a").status_code == 422
    assert answer(c, "q3", "²").status_code == 422


def test_unknown_question(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    assert answer(c, "q99", "1").status_code == 404


def test_users_are_independent_and_ranking_orders(tmp_path):
    a = make_client(tmp_path)
    login(a, "ana")
    answer(a, "q1", "192.168.1.4")
    answer(a, "q2", "192.168.1.5")

    b = TestClient(a.app)
    login(b, "luis")
    answer(b, "q1", "10.0.0.1")  # fallo
    answer(b, "q1", "192.168.1.4")  # 75 pts

    rank = a.get("/api/ranking").json()
    names = [e["name"] for e in rank["entries"]]
    assert names == ["ana", "luis"]
    assert rank["entries"][0]["points"] == 200 and rank["entries"][1]["points"] == 75
    assert rank["entries"][0]["me"] and not rank["entries"][1]["me"]
    assert rank["total_questions"] == 5


def test_admin_csv(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    answer(c, "q1", "192.168.1.4")
    assert c.get("/api/admin/results.csv").status_code == 403

    admin = TestClient(c.app)
    login(admin, "admin")
    res = admin.get("/api/admin/results.csv")
    assert res.status_code == 200
    lines = res.text.strip().splitlines()
    assert lines[0].startswith("username,display_name,question_id")
    assert any(line.startswith("ana,ana,q1,1,1,100") for line in lines[1:])


def test_csv_injection_is_neutralised():
    assert quiz._csv_safe("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert quiz._csv_safe("ana") == "ana"


def test_login_throttle(tmp_path):
    c = make_client(tmp_path)
    for _ in range(quiz.LOGIN_MAX_FAILS):
        assert login(c, "ana", "bad").status_code == 401
    assert login(c, "ana", "bad").status_code == 429
    assert login(c, "ana", "pw").status_code == 429  # bloqueada aunque acierte


def test_session_tampering_and_expiry():
    token = quiz.sign_session("k", {"u": "ana", "exp": 9_999_999_999})
    assert quiz.verify_session("k", token)["u"] == "ana"
    assert quiz.verify_session("otra", token) is None
    body, mac = token.split(".")
    forged = quiz.sign_session("k", {"u": "admin", "exp": 9_999_999_999}).split(".")[0] + "." + mac
    assert quiz.verify_session("k", forged) is None
    assert quiz.verify_session("k", quiz.sign_session("k", {"u": "ana", "exp": 1})) is None


def test_ldap_empty_password_is_rejected_without_connecting():
    settings = quiz.Settings(ldap_url="ldaps://no-existe.invalid", ldap_user_dn_template="uid={username},dc=x")
    assert quiz.ldap_authenticate(settings, "ana", "") is None
    assert quiz.ldap_authenticate(settings, "", "pw") is None


def test_ldap_mode_requires_secret_and_config(tmp_path):
    with pytest.raises(RuntimeError):
        quiz.create_app(
            quiz.Settings(
                auth_mode="ldap",
                ldap_url="ldaps://x",
                ldap_user_dn_template="uid={username}",
                answers_file=str(ANSWERS),
                db_path=str(tmp_path / "a.db"),
            )
        )
    with pytest.raises(RuntimeError):
        quiz.create_app(
            quiz.Settings(auth_mode="ldap", secret_key="s", answers_file=str(ANSWERS), db_path=str(tmp_path / "b.db"))
        )


def test_answers_file_validation(tmp_path):
    bad = {
        "questions": [
            {"id": "q1", "type": "ip", "text": "usa {q2}", "answer": "1.1.1.1"},
            {"id": "q2", "type": "ip", "text": "x", "answer": "2.2.2.2"},
        ]
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        quiz.load_quiz(path)
    path.write_text(json.dumps({"questions": [{"id": "q1", "type": "ip", "text": "x", "answer": "no-ip"}]}))
    with pytest.raises(ValueError):
        quiz.load_quiz(path)


def test_static_page_served(tmp_path):
    c = make_client(tmp_path)
    res = c.get("/")
    assert res.status_code == 200 and "<title>" in res.text


def test_chat_url_setting_overrides_answers_file(tmp_path):
    c = make_client(tmp_path, chat_url="https://demo.example")
    login(c, "ana")
    assert c.get("/api/state").json()["chat_url"] == "https://demo.example"


def test_chat_url_defaults_to_answers_file(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    assert c.get("/api/state").json()["chat_url"] == json.loads(ANSWERS.read_text())["chat_url"]


def test_capture_download_requires_login(tmp_path):
    capture = tmp_path / "capture.pcap"
    capture.write_bytes(b"\x0a\x0d\x0d\x0a")
    c = make_client(tmp_path, capture_file=str(capture))
    assert c.get("/api/capture").status_code == 401


def test_capture_download_serves_configured_file(tmp_path):
    capture = tmp_path / "CryLock_final.pcap"
    capture.write_bytes(b"\x0a\x0d\x0d\x0a")
    c = make_client(tmp_path, capture_file=str(capture))
    login(c, "ana")
    assert c.get("/api/state").json()["capture_download"] is True
    res = c.get("/api/capture")
    assert res.status_code == 200
    assert res.content == b"\x0a\x0d\x0d\x0a"
    assert 'filename="CryLock_final.pcap"' in res.headers["content-disposition"]


def test_capture_download_absent_when_not_configured(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    assert c.get("/api/state").json()["capture_download"] is False
    assert c.get("/api/capture").status_code == 404


def test_missing_capture_file_fails_at_start(tmp_path):
    with pytest.raises(RuntimeError):
        make_client(tmp_path, capture_file=str(tmp_path / "missing.pcap"))
