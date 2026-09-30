"""필수 테스트 10: share_with_ai=false인 민감 항목은 AI 요청에 포함되지 않는다."""
import json

from tests.helpers import add_pref, chat, create_trip, generate, last_call, leave_feedback, tool_names


def test_sensitive_not_shared_is_excluded_from_all_ai_requests(alice, ai_calls):
    secret = add_pref(alice, "food", "갑각류 알레르기", strength="hard", sensitive=True)
    shared = add_pref(alice, "mobility", "무릎이 약해 계단 어려움", strength="hard", sensitive=True, share_with_ai=True)
    assert secret["share_with_ai"] is False

    trip = create_trip(alice, "부산")
    version = generate(alice, trip["id"])
    prompt = last_call(ai_calls, "course")["user"]
    assert "갑각류" not in prompt and secret["id"] not in prompt
    assert shared["value"] in prompt
    assert version["generation_basis"]["withheld_sensitive_ids"] == [secret["id"]]
    # 전송하지 않았으므로 '모름'으로 알리지도 않는다(음식 분류를 추측 대상으로 표시하지 않음).
    assert "음식" not in prompt.split("<unknown>")[1].split("</unknown>")[0]

    # 기억 변경안 추출 요청에도 포함되지 않는다.
    leave_feedback(alice, trip["id"], version)
    alice.post(f"/api/trips/{trip['id']}/memory-proposals")
    assert "갑각류" not in last_call(ai_calls, "proposals")["user"]

    # 대화 에이전트의 도구(get_preferences) 결과에도 포함되지 않는다.
    turn, events = chat(alice, "내 취향 알려줘", trip_id=trip["id"])
    assert turn["status"] == "done" and "get_preferences" in tool_names(events)
    from app.services.agent_tools import ToolContext, make_executor
    ctx = ToolContext(uid=alice_uid(alice), turn_id="t-sens", conversation_id="c", user_texts=[],
                      emit=lambda e: None, add_card=lambda c: None, set_active_trip=lambda t: None)
    out = json.loads(make_executor(ctx)("get_preferences", json.dumps({"trip_id": trip["id"]})))
    values = [p["value"] for p in out["preferences"]]
    assert "갑각류 알레르기" not in values and shared["value"] in values
    transcript = json.dumps([c for c in ai_calls if c["kind"] == "chat"], ensure_ascii=False)
    assert "갑각류" not in transcript

    # 동의로 바꾸면 그때부터 포함된다.
    alice.put(f"/api/preferences/{secret['id']}", json={"share_with_ai": True})
    generate(alice, trip["id"])
    assert "갑각류 알레르기" in last_call(ai_calls, "course")["user"]


def alice_uid(user):
    return user.get("/api/me").json()["uid"]
