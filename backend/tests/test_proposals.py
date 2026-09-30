"""필수 테스트 3: 피드백은 승인 전에 장기 기억을 바꾸지 않는다. + 변경안 추출 규칙."""
from tests.helpers import BUSAN_FEEDBACK, add_pref, create_trip, generate, leave_feedback, place_items


def _prefs(user):
    return sorted((p["id"], p["value"], p["status"]) for p in user.get("/api/preferences").json())


def test_feedback_and_proposals_do_not_change_memory_before_approval(alice):
    add_pref(alice, "transport", "선호 교통수단: 대중교통")
    pace = add_pref(alice, "pace", "하루 주요 방문지 3~4곳")
    trip = create_trip(alice, "부산")
    version = generate(alice, trip["id"])
    before = _prefs(alice)

    leave_feedback(alice, trip["id"], version)
    assert _prefs(alice) == before

    result = alice.post(f"/api/trips/{trip['id']}/memory-proposals").json()
    assert _prefs(alice) == before
    proposals = result["proposals"]
    afters = {p["after"] for p in proposals}
    assert {"바다 전망 카페 선호", "혼잡한 장소를 피하는 편", "하루 주요 방문지 두세 곳 선호"} <= afters
    for p in proposals:
        assert p["status"] == "pending"
        assert p["evidence_text"] in BUSAN_FEEDBACK
        assert p["is_mock"] is True
    # 기존 pace 기억과 충돌 → update 제안 + 변경 전후
    pace_prop = next(p for p in proposals if p["category"] == "pace")
    assert pace_prop["type"] == "update" and pace_prop["target_preference_id"] == pace["id"]
    assert pace_prop["before"] == pace["value"]

    # 거절한 제안은 기억을 바꾸지 않는다.
    r = alice.post(f"/api/memory-proposals/{pace_prop['id']}/reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert _prefs(alice) == before
    assert alice.post(f"/api/memory-proposals/{pace_prop['id']}/approve", json={}).status_code == 409


def test_unvisited_place_is_not_extracted_as_experience(alice):
    trip = create_trip(alice, "부산", days=1)
    version = generate(alice, trip["id"])
    places = place_items(version)
    visits = [
        {"item_id": places[0]["item_id"], "place_name": places[0]["name"], "visited": False, "comment": "바다 카페가 좋았다고 들었어"},
        {"item_id": places[1]["item_id"], "place_name": places[1]["name"], "visited": True, "rating": 5, "comment": "사람이 많아서 복잡했어"},
    ]
    leave_feedback(alice, trip["id"], version, text="", visits=visits)
    result = alice.post(f"/api/trips/{trip['id']}/memory-proposals").json()
    afters = [p["after"] for p in result["proposals"]]
    assert "혼잡한 장소를 피하는 편" in afters
    assert not any("카페" in a for a in afters)
    assert any("방문하지 않아" in n for n in result["excluded_notes"])


def test_unvisited_place_cannot_get_rating_and_unknown_items_rejected(alice):
    trip = create_trip(alice, "부산", days=1)
    version = generate(alice, trip["id"])
    item = place_items(version)[0]
    r = alice.post(f"/api/trips/{trip['id']}/feedback", json={"version_id": version["id"], "visits": [
        {"item_id": item["item_id"], "place_name": item["name"], "visited": False, "rating": 5}]})
    assert r.status_code == 422
    r = alice.post(f"/api/trips/{trip['id']}/feedback", json={"version_id": version["id"], "visits": [
        {"item_id": "d9-9", "place_name": "추천하지 않은 곳", "visited": True}]})
    assert r.status_code == 422


def test_situational_feedback_is_flagged(alice):
    trip = create_trip(alice, "부산", days=1)
    version = generate(alice, trip["id"])
    leave_feedback(alice, trip["id"], version, text="비가 와서 카페가 좋았어")
    proposals = alice.post(f"/api/trips/{trip['id']}/memory-proposals").json()["proposals"]
    assert proposals and proposals[0]["situational"]["is_situational"] is True
    assert proposals[0]["situational"]["factor"] == "weather"


def test_companion_feedback_is_marked_companion(alice):
    trip = create_trip(alice, "부산", days=1, companions=[{"relation": "아이"}])
    version = generate(alice, trip["id"])
    leave_feedback(alice, trip["id"], version, text="아이가 하루 세 곳 일정은 힘들어했어")
    proposals = alice.post(f"/api/trips/{trip['id']}/memory-proposals").json()["proposals"]
    assert proposals and proposals[0]["subject"] == "companion"


def test_edited_approval_saves_edited_value(alice):
    trip = create_trip(alice, "부산")
    version = generate(alice, trip["id"])
    leave_feedback(alice, trip["id"], version)
    proposals = alice.post(f"/api/trips/{trip['id']}/memory-proposals").json()["proposals"]
    cafe = next(p for p in proposals if "카페" in p["after"])
    r = alice.post(f"/api/memory-proposals/{cafe['id']}/approve", json={"edited_value": "조용한 바다 전망 카페 선호"})
    assert r.status_code == 200, r.text
    assert r.json()["proposal"]["status"] == "edited_approved"
    pref = alice.get(f"/api/preferences/{r.json()['preference_id']}").json()
    assert pref["value"] == "조용한 바다 전망 카페 선호" and pref["scope"] == "learned"
    src = pref["sources"][0]
    assert src["type"] == "feedback_proposal" and src["proposal_id"] == cafe["id"]
    assert src["trip_destination"] == "부산" and src["evidence_text"] == cafe["evidence_text"]


def test_regenerating_replaces_only_pending_proposals(alice):
    trip = create_trip(alice, "부산")
    version = generate(alice, trip["id"])
    leave_feedback(alice, trip["id"], version)
    first = alice.post(f"/api/trips/{trip['id']}/memory-proposals").json()["proposals"]
    alice.post(f"/api/memory-proposals/{first[0]['id']}/approve", json={})
    second = alice.post(f"/api/trips/{trip['id']}/memory-proposals").json()["proposals"]
    all_props = alice.get(f"/api/memory-proposals?trip_id={trip['id']}").json()
    assert any(p["id"] == first[0]["id"] and p["status"] == "approved" for p in all_props)
    assert len([p for p in all_props if p["status"] == "pending"]) == len(second)
    # 이미 저장된 기억과 같은 제안은 다시 만들지 않는다.
    assert first[0]["after"] not in [p["after"] for p in second]
