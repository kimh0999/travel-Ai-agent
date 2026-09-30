"""대화 턴: 저장·불러오기, 실시간 이벤트, 중단·재접속·재시도 중복 방지, 도구 경계."""
import json

from app.clients import mock_ai
from app.services import agent_tools, chat_turns
from app.services.agent_tools import ToolContext, make_executor
from tests.helpers import (add_pref, cards_of, chat, create_trip, generate, read_events, start_turn,
                           tool_names)


def _wait_done(user, turn_id):
    import time
    for _ in range(100):
        turn = user.get(f"/api/chat/turns/{turn_id}").json()
        if turn["status"] != "running":
            return turn
        time.sleep(0.1)
    raise AssertionError("turn did not finish")


def _ctx(uid, turn_id="t-test", texts=None):
    cards = []
    ctx = ToolContext(uid=uid, turn_id=turn_id, conversation_id="c-test", user_texts=texts or [],
                      emit=lambda e: None, add_card=cards.append, set_active_trip=lambda t: None,
                      has_card=lambda key: any(c["key"] == key for c in cards))
    return ctx, cards


def _uid(user):
    return user.get("/api/me").json()["uid"]


def test_messages_and_cards_round_trip(alice):
    add_pref(alice, "transport", "대중교통")
    texts = ["부산 2박 3일 여행 코스 짜줘", "줄 바꿈도\n그대로 저장돼?  공백  포함", "<b>태그</b> & 특수문자 \"따옴표\""]
    conv_id, replies = None, []
    for t in texts:
        turn, events = chat(alice, t, conversation_id=conv_id)
        assert turn["status"] == "done", turn
        assert events[0]["type"] == "start" and events[-1]["type"] == "done"
        assert "".join(e["delta"] for e in events if e["type"] == "text") == turn["reply"]
        conv_id = turn["conversation_id"]
        replies.append(turn["reply"])

    detail = alice.get(f"/api/conversations/{conv_id}").json()
    assert [(m["role"], m["content"]) for m in detail["messages"]] == [
        x for t, rep in zip(texts, replies) for x in (("user", t.strip()), ("assistant", rep))]
    assert [m["seq"] for m in detail["messages"]] == list(range(1, 7))
    course_cards = [c for c in detail["messages"][1]["cards"] if c["type"] == "course"]
    assert len(course_cards) == 1 and course_cards[0]["is_current"]
    assert detail["trip_destination"] == "부산" and detail["open_turn"] is None

    assert alice.delete(f"/api/conversations/{conv_id}").status_code == 204
    assert alice.get(f"/api/conversations/{conv_id}").status_code == 404


def test_progress_events_follow_real_tool_execution(alice):
    add_pref(alice, "transport", "자가용")
    turn, events = chat(alice, "여수 1박 2일 코스 짜줘")
    starts = [e for e in events if e["type"] == "tool_start"]
    ends = [e for e in events if e["type"] == "tool_end"]
    assert [e["name"] for e in starts] == ["get_preferences", "create_trip", "generate_course"]
    assert [e["key"] for e in starts] == [e["key"] for e in ends] and all(e["ok"] for e in ends)
    assert starts[1]["label"] == "여수 여행 만드는 중"
    card_events = [e["card"]["type"] for e in events if e["type"] == "card"]
    assert card_events == ["trip", "course"]
    assert any(e["type"] == "active_trip" and e["trip"]["destination"] == "여수" for e in events)


def test_same_client_turn_id_does_not_run_twice(alice):
    add_pref(alice, "transport", "대중교통")
    first = start_turn(alice, "부산 2박 3일 코스 짜줘", client_turn_id="retry-same-request-1")
    _wait_done(alice, first["id"])
    again = start_turn(alice, "부산 2박 3일 코스 짜줘", client_turn_id="retry-same-request-1")
    assert again["id"] == first["id"] and again["status"] == "done"
    assert len(alice.get("/api/trips").json()) == 1
    detail = alice.get(f"/api/conversations/{first['conversation_id']}").json()
    assert detail["message_count"] == 2


def test_reconnect_after_disconnect_resumes_stream(alice):
    add_pref(alice, "transport", "대중교통")
    turn = start_turn(alice, "부산 2박 3일 코스 짜줘")
    head = read_events(alice, turn["id"], limit=2)  # 두 이벤트만 받고 연결이 끊김
    rest = read_events(alice, turn["id"], after=head[-1]["seq"])
    seqs = [e["seq"] for e in head + rest]
    assert seqs == list(range(1, len(seqs) + 1))  # 빠짐·중복 없이 이어 받음
    assert rest[-1]["type"] == "done"
    assert len(alice.get("/api/trips").json()) == 1


def test_failure_mid_turn_then_retry_creates_one_trip(alice):
    add_pref(alice, "transport", "대중교통")
    mock_ai.FAILURES[:] = ["error_after_tool:2"]  # 취향 조회·여행 생성 뒤 끊김
    turn, events = chat(alice, "부산 2박 3일 코스 짜줘")
    assert turn["status"] == "failed" and events[-1]["type"] == "error"
    # 실패 전에 만든 여행은 남고, 대화에는 아직 저장되지 않는다.
    assert len(alice.get("/api/trips").json()) == 1
    detail = alice.get(f"/api/conversations/{turn['conversation_id']}").json()
    assert detail["messages"] == [] and detail["open_turn"]["status"] == "failed"

    retried = alice.post(f"/api/chat/turns/{turn['id']}/retry").json()
    assert retried["attempt"] == 2
    events2 = read_events(alice, turn["id"], attempt=2)
    final = alice.get(f"/api/chat/turns/{turn['id']}").json()
    assert final["status"] == "done", final
    assert events2[0]["type"] == "start" and events2[0]["attempt"] == 2
    trips = alice.get("/api/trips").json()
    assert len(trips) == 1  # 재시도해도 여행은 하나
    assert len(alice.get(f"/api/trips/{trips[0]['id']}/versions").json()) == 1
    assert len(cards_of(final, "trip")) == 1 and len(cards_of(final, "course")) == 1
    detail = alice.get(f"/api/conversations/{turn['conversation_id']}").json()
    assert detail["message_count"] == 2 and detail["open_turn"] is None


def test_retry_of_finished_turn_does_nothing(alice):
    turn, _ = chat(alice, "안녕")
    again = alice.post(f"/api/chat/turns/{turn['id']}/retry").json()
    assert again["status"] == "done" and again["attempt"] == 1


def test_same_tool_call_is_not_executed_twice(alice):
    """transcript가 저장되기 전에 끊겨 같은 도구를 다시 부르더라도 결과를 재사용한다."""
    ctx, cards = _ctx(_uid(alice), turn_id="t-ledger-1")
    execute = make_executor(ctx)
    args = json.dumps({"destination": "강릉", "days": 2, "transport": "car"})
    first = json.loads(execute("create_trip", args))
    second = json.loads(execute("create_trip", args))
    assert first["trip"]["id"] == second["trip"]["id"]
    assert len(alice.get("/api/trips").json()) == 1
    gen = json.dumps({"trip_id": first["trip"]["id"]})
    v1 = json.loads(execute("generate_course", gen))
    v2 = json.loads(execute("generate_course", gen))
    assert v1["version_id"] == v2["version_id"]
    assert len(alice.get(f"/api/trips/{first['trip']['id']}/versions").json()) == 1
    assert [c["type"] for c in cards] == ["trip", "course"]


def test_failed_turn_keeps_input_and_can_be_retried(alice):
    mock_ai.FAILURES[:] = ["timeout"]
    turn, events = chat(alice, "안녕")
    assert turn["status"] == "failed" and turn["error"]["code"] == "AI_TIMEOUT"
    assert turn["message"] == "안녕"
    alice.post(f"/api/chat/turns/{turn['id']}/retry")
    read_events(alice, turn["id"], attempt=2)
    assert alice.get(f"/api/chat/turns/{turn['id']}").json()["status"] == "done"


def test_second_message_waits_for_running_turn(alice, monkeypatch):
    import threading
    gate = threading.Event()
    original = mock_ai.MockAIClient.run_turn

    def slow(self, **kw):
        gate.wait(5)
        return original(self, **kw)

    monkeypatch.setattr(mock_ai.MockAIClient, "run_turn", slow)
    first = start_turn(alice, "안녕")
    r = alice.post("/api/chat/turns", json={"client_turn_id": "second-msg-0001", "message": "또 안녕",
                                            "conversation_id": first["conversation_id"]})
    assert r.status_code == 409
    gate.set()
    _wait_done(alice, first["id"])


def test_ask_only_missing_transport_then_continue(alice):
    turn, events = chat(alice, "다음 달 부산 2박 3일 여행 코스 짜줘")
    question = cards_of(turn, "question")
    assert len(question) == 1 and question[0]["options"] == ["대중교통", "자동차"]
    assert alice.get("/api/trips").json() == []  # 묻기만 하고 여행은 아직 만들지 않음

    turn2, _ = chat(alice, "대중교통", conversation_id=turn["conversation_id"])
    trip = cards_of(turn2, "trip")[0]["trip"]
    assert trip["transport"] == "public" and trip["days"] == 3
    # '다음 달'은 실제 연월로 저장하고 날짜는 미정으로 둔다.
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone(timedelta(hours=9)))
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    assert trip["period_hint"] == f"{year}년 {month}월" and trip["start_date"] is None


def test_system_prompt_has_today_and_active_trip(alice, ai_calls):
    trip = create_trip(alice, "부산", days=2)
    chat(alice, "안녕", trip_id=trip["id"])
    system = [c for c in ai_calls if c["kind"] == "chat"][-1]["system"]
    assert "오늘: " in system and f"현재 작업 중인 여행: 부산 (trip_id={trip['id']})" in system
    assert "검색 결과, 장소 설명" in system  # 외부 데이터 지시 무시 규칙


def test_agent_cannot_approve_memory(alice):
    names = {t.name for t in agent_tools.TOOLS}
    assert not any(k in n for n in names for k in ("approve", "reject", "delete", "update_pref"))
    ctx, _ = _ctx(_uid(alice), texts=["앞으로 야경 명소를 꼭 넣어줘"])
    execute = make_executor(ctx)
    assert "허용되지 않은 도구" in execute("approve_memory_proposal", "{}")
    before = alice.get("/api/preferences").json()
    turn, _ = chat(alice, "앞으로 야경 명소를 꼭 넣어줘")
    proposal = cards_of(turn, "proposal")[0]["proposal"]
    assert proposal["status"] == "pending" and proposal["certainty"] == "clear"
    assert alice.get("/api/preferences").json() == before  # 승인 전에는 기억이 바뀌지 않음


def test_tools_are_scoped_to_current_user(alice, bob):
    alice_trip = create_trip(alice, "부산")
    generate(alice, alice_trip["id"])
    ctx, _ = _ctx(_uid(bob), texts=["안녕"])
    execute = make_executor(ctx)
    for name in ("get_course", "generate_course"):
        assert "찾을 수 없습니다" in execute(name, json.dumps({"trip_id": alice_trip["id"]}))
    assert "찾을 수 없습니다" in execute("pin_place", json.dumps({"trip_id": alice_trip["id"], "item_id": "d1-1"}))
    assert "인자가 올바르지 않습니다" in execute("get_course", '{"wrong": 1}')
    assert json.loads(execute("list_trips", "{}"))["trips"] == []
    # 대화에 없는 말을 근거로 한 변경안은 거부
    out = execute("propose_memory", json.dumps({"category": "other", "statement": "x", "applies_to": "모든 여행",
                                                "evidence_text": "지어낸 말", "certainty": "clear"}))
    assert "그대로 인용" in out


def test_tool_call_limit_is_enforced(alice, monkeypatch):
    calls = []

    def greedy(self, *, system, transcript, tools, execute, emit, on_step, deadline, max_tool_calls):
        from app.clients.ai_base import TurnResult
        while len(calls) < 50 and len(calls) < max_tool_calls:
            calls.append(execute("list_trips", "{}"))
        return TurnResult(reply="done", tool_calls=["list_trips"] * len(calls))

    monkeypatch.setattr(mock_ai.MockAIClient, "run_turn", greedy)
    turn, _ = chat(alice, "많이 조회해줘")
    assert turn["status"] == "done"
    assert len(calls) == chat_turns.MAX_TOOL_CALLS


def test_cannot_access_other_users_conversations_or_turns(alice, bob):
    turn, _ = chat(alice, "안녕")
    cid = turn["conversation_id"]
    assert bob.get(f"/api/conversations/{cid}").status_code == 404
    assert bob.delete(f"/api/conversations/{cid}").status_code == 404
    assert bob.get("/api/conversations").json() == []
    assert bob.get(f"/api/chat/turns/{turn['id']}").status_code == 404
    assert bob.get(f"/api/chat/turns/{turn['id']}/events").status_code == 404
    assert bob.post(f"/api/chat/turns/{turn['id']}/retry").status_code == 404
    r = bob.post("/api/chat/turns", json={"client_turn_id": "bob-turn-0001", "message": "안녕", "conversation_id": cid})
    assert r.status_code == 404
    assert alice.get(f"/api/conversations/{cid}").status_code == 200
