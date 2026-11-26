from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as quiz  # noqa: E402

ANSWERS = Path(__file__).resolve().parent.parent / "answers.json"


def answers_with(tmp_path, speed_multipliers: list[float]) -> str:
    """Copia de answers.json con unos multiplicadores fijos, para no depender del fichero real."""
    cfg = json.loads(ANSWERS.read_text())
    cfg["speed_multipliers"] = speed_multipliers
    path = tmp_path / f"answers-{len(speed_multipliers)}.json"
    path.write_text(json.dumps(cfg))
    return str(path)


def make_client(tmp_path, speed_multipliers: list[float] | None = None, **overrides) -> TestClient:
    settings = quiz.Settings(
        auth_mode="dev",
        dev_password="pw",
        secret_key="test-secret",
        db_path=str(tmp_path / "quiz.db"),
        answers_file=answers_with(tmp_path, speed_multipliers or []),
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
    assert data["questions"][1]["goal"] is None
    assert data["questions"][1]["hint"] is None
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
    assert "4087" in q5["goal"]
    assert "49183" not in json.dumps(q5)
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
    cfg["speed_multipliers"] = []
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
            {"id": "q1", "type": "ip", "goal": "g", "hint": "usa {q2}", "answer": "1.1.1.1"},
            {"id": "q2", "type": "ip", "goal": "g", "hint": "x", "answer": "2.2.2.2"},
        ]
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        quiz.load_quiz(path)
    path.write_text(
        json.dumps({"questions": [{"id": "q1", "type": "ip", "goal": "g", "hint": "x", "answer": "no-ip"}]})
    )
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


def test_instructions_page_is_public_and_rendered(tmp_path):
    doc = tmp_path / "instrucciones.md"
    doc.write_text("# Seminario 1\n\n- **URL:** `https://demo.example`\n", encoding="utf-8")
    c = make_client(tmp_path, instructions_file=str(doc))
    res = c.get("/instrucciones")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "<h1>Seminario 1</h1>" in res.text
    assert "<strong>URL:</strong>" in res.text
    assert "<title>Seminario 1</title>" in res.text


def test_instructions_page_reflects_edits_without_restart(tmp_path):
    doc = tmp_path / "instrucciones.md"
    doc.write_text("# Antes\n", encoding="utf-8")
    c = make_client(tmp_path, instructions_file=str(doc))
    doc.write_text("# Después\n", encoding="utf-8")
    assert "<h1>Después</h1>" in c.get("/instrucciones").text


def test_instructions_page_absent_when_not_configured(tmp_path):
    c = make_client(tmp_path)
    assert c.get("/instrucciones").status_code == 404


def test_missing_instructions_file_fails_at_start(tmp_path):
    with pytest.raises(RuntimeError):
        make_client(tmp_path, instructions_file=str(tmp_path / "missing.md"))


SPEED = [2, 1.75, 1.5, 1.25]


def as_user(client: TestClient, name: str) -> TestClient:
    other = TestClient(client.app)
    login(other, name)
    return other


def test_first_correct_answers_get_decreasing_multipliers(tmp_path):
    first = make_client(tmp_path, SPEED)
    login(first, "u1")
    users = [first] + [as_user(first, f"u{i}") for i in range(2, 7)]
    results = [answer(c, "q1", "192.168.1.4").json() for c in users]
    assert [r["points"] for r in results] == [200, 175, 150, 125, 100, 100]
    assert [r["position"] for r in results] == [1, 2, 3, 4, 5, 6]
    assert [r["multiplier"] for r in results] == [2, 1.75, 1.5, 1.25, 1, 1]


def test_multiplier_applies_after_penalty_and_rounds_half_up(tmp_path):
    c = make_client(tmp_path, SPEED)
    login(c, "ana")
    answer(c, "q1", "10.0.0.1")
    r = answer(c, "q1", "192.168.1.4").json()
    assert r["points"] == 150  # (100 - 25) * 2
    luis = as_user(c, "luis")
    answer(luis, "q1", "10.0.0.1")
    assert answer(luis, "q1", "192.168.1.4").json()["points"] == 131  # 75 * 1.75 = 131.25


def test_wrong_answers_do_not_take_a_position(tmp_path):
    c = make_client(tmp_path, SPEED)
    login(c, "ana")
    answer(c, "q1", "10.0.0.1")
    luis = as_user(c, "luis")
    assert answer(luis, "q1", "192.168.1.4").json()["position"] == 1


def test_positions_are_counted_per_question(tmp_path):
    c = make_client(tmp_path, SPEED)
    login(c, "ana")
    answer(c, "q1", "192.168.1.4")
    luis = as_user(c, "luis")
    answer(luis, "q1", "192.168.1.4")
    assert answer(luis, "q2", "192.168.1.5").json()["position"] == 1
    assert answer(c, "q2", "192.168.1.5").json()["position"] == 2


def test_state_shows_how_many_solved_and_next_multiplier(tmp_path):
    c = make_client(tmp_path, SPEED)
    login(c, "ana")
    q1 = c.get("/api/state").json()["questions"][0]
    assert q1["solved_by"] == 0 and q1["next_multiplier"] == 2
    answer(as_user(c, "luis"), "q1", "192.168.1.4")
    q1 = c.get("/api/state").json()["questions"][0]
    assert q1["solved_by"] == 1 and q1["next_multiplier"] == 1.75


def test_state_reports_own_position_and_multiplier(tmp_path):
    c = make_client(tmp_path, SPEED)
    login(as_user(c, "luis"), "luis")
    answer(as_user(c, "luis"), "q1", "192.168.1.4")
    login(c, "ana")
    answer(c, "q1", "192.168.1.4")
    q1 = c.get("/api/state").json()["questions"][0]
    assert q1["position"] == 2 and q1["multiplier"] == 1.75 and q1["points"] == 175


def test_max_points_include_the_top_multiplier(tmp_path):
    c = make_client(tmp_path, SPEED)
    login(c, "ana")
    assert c.get("/api/state").json()["questions"][0]["max_points"] == 200


def test_without_multipliers_scoring_is_unchanged(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    r = answer(c, "q1", "192.168.1.4").json()
    assert r["points"] == 100 and r["multiplier"] == 1 and r["position"] == 1


def test_ranking_breaks_ties_by_who_finished_first(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    luis = as_user(c, "luis")
    answer(luis, "q1", "192.168.1.4")
    answer(c, "q1", "192.168.1.4")
    names = [e["name"] for e in c.get("/api/ranking").json()["entries"]]
    assert names == ["luis", "ana"]


def test_ranking_includes_recent_correct_answers(tmp_path):
    c = make_client(tmp_path, SPEED)
    login(c, "ana")
    answer(c, "q1", "192.168.1.4")
    luis = as_user(c, "luis")
    answer(luis, "q1", "10.0.0.1")
    answer(luis, "q1", "192.168.1.4")
    recent = c.get("/api/ranking").json()["recent"]
    assert recent == [
        {"name": "luis", "question": 1, "position": 2, "points": 131},
        {"name": "ana", "question": 1, "position": 1, "points": 200},
    ]


@pytest.mark.parametrize("bad", [[0.5], ["x"], 2, [2, -1]])
def test_invalid_speed_multipliers_are_rejected(tmp_path, bad):
    cfg = json.loads(ANSWERS.read_text())
    cfg["speed_multipliers"] = bad
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError):
        quiz.load_quiz(path)


def test_state_exposes_the_multiplier_scale(tmp_path):
    c = make_client(tmp_path, SPEED)
    login(c, "ana")
    assert c.get("/api/state").json()["speed_multipliers"] == SPEED


# --------------------------------------------------------------------------- #
# Objetivo visible y pista (pregunta exacta para el chat) con penalización
# --------------------------------------------------------------------------- #

Q1_HINT = "What is the IP address of the infected machine?"


def hint(client: TestClient, qid: str):
    return client.post("/api/hint", json={"question_id": qid})


def test_state_shows_the_goal_and_hides_the_exact_prompt(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    data = c.get("/api/state").json()
    q1 = data["questions"][0]
    assert q1["goal"].startswith("Averigua")
    assert q1["hint"] is None and q1["hint_used"] is False
    assert data["hint_penalty"] == 50
    assert Q1_HINT not in json.dumps(data)


def test_hint_returns_the_exact_prompt_and_shows_it_in_state(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    res = hint(c, "q1")
    assert res.status_code == 200
    assert res.json() == {"hint": Q1_HINT, "hint_penalty": 50}
    q1 = c.get("/api/state").json()["questions"][0]
    assert q1["hint"] == Q1_HINT and q1["hint_used"] is True


def test_hint_subtracts_its_penalty_once(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    hint(c, "q1")
    hint(c, "q1")
    assert answer(c, "q1", "192.168.1.4").json()["points"] == 50


def test_hint_penalty_is_applied_before_the_speed_multiplier(tmp_path):
    c = make_client(tmp_path, SPEED)
    login(c, "ana")
    hint(c, "q1")
    assert answer(c, "q1", "192.168.1.4").json()["points"] == 100  # (100 - 50) * 2


def test_hint_and_wrong_answers_never_go_below_min_points(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    hint(c, "q1")
    answer(c, "q1", "10.0.0.1")
    answer(c, "q1", "10.0.0.2")
    assert answer(c, "q1", "192.168.1.4").json()["points"] == 25


def test_hint_only_for_open_questions(tmp_path):
    c = make_client(tmp_path)
    assert hint(c, "q1").status_code == 401
    login(c, "ana")
    assert hint(c, "q2").status_code == 409  # bloqueada
    assert hint(c, "q99").status_code == 404
    answer(c, "q1", "192.168.1.4")
    assert hint(c, "q1").status_code == 409  # cerrada


def test_hint_of_later_question_fills_previous_answers_but_not_its_own(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    for qid, value in (("q1", "192.168.1.4"), ("q2", "192.168.1.5"), ("q3", "445"), ("q4", "4087")):
        answer(c, qid, value)
    text = hint(c, "q5").json()["hint"]
    assert all(x in text for x in ("4087", "192.168.1.4", "192.168.1.5", "445"))
    assert "49183" not in text


def test_closed_question_shows_the_hint_without_penalty(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    answer(c, "q1", "192.168.1.4")
    q1 = c.get("/api/state").json()["questions"][0]
    assert q1["hint"] == Q1_HINT and q1["hint_used"] is False and q1["points"] == 100


def test_hints_are_per_user(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    hint(c, "q1")
    luis = as_user(c, "luis")
    assert luis.get("/api/state").json()["questions"][0]["hint"] is None
    assert answer(luis, "q1", "192.168.1.4").json()["points"] == 100


def test_admin_csv_reports_hint_use(tmp_path):
    c = make_client(tmp_path)
    login(c, "ana")
    hint(c, "q1")
    answer(c, "q1", "192.168.1.4")
    admin = as_user(c, "admin")
    lines = admin.get("/api/admin/results.csv").text.strip().splitlines()
    assert lines[0].endswith(",hint_used")
    assert lines[1].startswith("ana,ana,q1,1,1,50,") and lines[1].endswith(",1")


@pytest.mark.parametrize(
    "question",
    [
        {"id": "q1", "type": "ip", "hint": "x", "answer": "1.1.1.1"},
        {"id": "q1", "type": "ip", "goal": "g", "answer": "1.1.1.1"},
        {"id": "q1", "type": "ip", "goal": "usa {q2}", "hint": "x", "answer": "1.1.1.1"},
    ],
)
def test_questions_need_goal_and_hint_with_valid_references(tmp_path, question):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"questions": [question]}))
    with pytest.raises(ValueError):
        quiz.load_quiz(path)


def test_negative_hint_penalty_is_rejected(tmp_path):
    cfg = json.loads(ANSWERS.read_text())
    cfg["hint_penalty"] = -10
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError):
        quiz.load_quiz(path)


def test_max_points_drop_after_using_the_hint(tmp_path):
    c = make_client(tmp_path, SPEED)
    login(c, "ana")
    hint(c, "q1")
    assert c.get("/api/state").json()["questions"][0]["max_points"] == 100  # (100 - 50) * 2
