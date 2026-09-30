"""필수 테스트 11: 여행 삭제 시 6-3 정책대로 처리된다."""
from tests.helpers import add_pref, chat, create_trip, generate, leave_feedback


def _approved_learned(alice, trip, version):
    leave_feedback(alice, trip["id"], version)
    proposals = alice.post(f"/api/trips/{trip['id']}/memory-proposals").json()["proposals"]
    by_after = {p["after"]: p for p in proposals}
    keep = alice.post(f"/api/memory-proposals/{by_after['바다 전망 카페 선호']['id']}/approve", json={}).json()["preference_id"]
    drop = alice.post(f"/api/memory-proposals/{by_after['하루 주요 방문지 두세 곳 선호']['id']}/approve", json={}).json()["preference_id"]
    alice.post(f"/api/memory-proposals/{by_after['혼잡한 장소를 피하는 편']['id']}/reject")
    return keep, drop


def test_trip_delete_policy(alice):
    base = add_pref(alice, "transport", "대중교통")
    trip = create_trip(alice, "부산")
    trip_pref = add_pref(alice, "pace", "부산은 늦게 시작", scope="trip", trip_id=trip["id"])
    version = generate(alice, trip["id"])
    keep, drop = _approved_learned(alice, trip, version)
    turn, _ = chat(alice, "일정 줄여줘", trip_id=trip["id"])
    assert turn["status"] == "done"
    chat_conv = turn["conversation_id"]
    leave_feedback(alice, trip["id"], version, text="하루 네 곳은 힘들었어")
    alice.post(f"/api/trips/{trip['id']}/memory-proposals")  # 대기 중 변경안 생성
    other = create_trip(alice, "여수")
    other_conv = alice.post("/api/conversations", json={"trip_id": other["id"]}).json()

    preview = alice.get(f"/api/trips/{trip['id']}/delete-preview").json()
    assert {p["id"] for p in preview["learned_preferences"]} == {keep, drop}
    assert preview["counts"]["conversations"] == 1 and preview["counts"]["feedback"] == 2
    assert preview["counts"]["trip_preferences"] == 1 and preview["counts"]["course_versions"] >= 2

    # 이 여행에서 비롯되지 않은 기억은 함께 삭제할 수 없다.
    bad = alice.delete(f"/api/trips/{trip['id']}", json={"delete_preference_ids": [base["id"]]})
    assert bad.status_code == 422

    r = alice.delete(f"/api/trips/{trip['id']}", json={"delete_preference_ids": [drop]})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["kept_learned_preference_ids"] == [keep] and result["deleted_preference_ids"] == [drop]

    assert alice.get(f"/api/trips/{trip['id']}").status_code == 404
    assert alice.get(f"/api/trips/{trip['id']}/versions").status_code == 404
    # 대화는 여러 여행을 다룰 수 있어 남기고, 삭제한 여행의 카드와 여행 연결만 지운다.
    convs = {c["id"]: c for c in alice.get("/api/conversations").json()}
    assert set(convs) == {chat_conv, other_conv["id"]} and convs[chat_conv]["trip_id"] is None
    detail = alice.get(f"/api/conversations/{chat_conv}").json()
    assert all(not m["cards"] for m in detail["messages"])
    assert trip["id"] not in str(detail)
    remaining = alice.get(f"/api/memory-proposals?trip_id={trip['id']}").json()
    assert remaining and all(p["status"] == "approved" for p in remaining)  # 대기·거절 제안은 삭제

    prefs = {p["id"]: p for p in alice.get("/api/preferences").json()}
    assert base["id"] in prefs and keep in prefs
    assert drop not in prefs and trip_pref["id"] not in prefs
    kept_source = prefs[keep]["sources"][0]
    assert kept_source["trip_deleted"] is True and kept_source["trip_destination"] == "부산"

    # 삭제된 여행에서 온 learned 기억은 다음 코스에 계속 반영된다.
    new_v = generate(alice, other["id"])
    assert keep in new_v["generation_basis"]["memory_ids"]
    assert trip["id"] not in new_v["generation_basis"]["past_trip_ids"]


def test_trip_delete_without_selection_keeps_all_learned(alice):
    trip = create_trip(alice, "부산")
    version = generate(alice, trip["id"])
    keep, drop = _approved_learned(alice, trip, version)
    r = alice.delete(f"/api/trips/{trip['id']}")
    assert r.status_code == 200, r.text
    prefs = {p["id"] for p in alice.get("/api/preferences").json()}
    assert {keep, drop} <= prefs
