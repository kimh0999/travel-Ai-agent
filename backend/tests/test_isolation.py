"""필수 테스트 1: 다른 사용자의 여행·기억·대화에 접근할 수 없다."""


def test_cannot_access_other_users_preferences(alice, bob):
    pref = alice.post("/api/preferences", json={"category": "pace", "value": "여유로운 일정"}).json()
    pid = pref["id"]
    assert bob.get(f"/api/preferences/{pid}").status_code == 404
    assert bob.put(f"/api/preferences/{pid}", json={"value": "빡빡한 일정"}).status_code == 404
    assert bob.delete(f"/api/preferences/{pid}").status_code == 404
    assert bob.get("/api/preferences").json() == []
    assert alice.get(f"/api/preferences/{pid}").json()["value"] == "여유로운 일정"


def test_cannot_create_trip_scoped_preference_on_other_users_trip(alice, bob):
    trip = alice.post("/api/trips", json={"destination": "부산"}).json()
    r = bob.post("/api/preferences", json={"category": "pace", "value": "x", "scope": "trip", "trip_id": trip["id"]})
    assert r.status_code == 404


def test_cannot_access_other_users_trips(alice, bob):
    trip = alice.post("/api/trips", json={"destination": "부산"}).json()
    tid = trip["id"]
    assert bob.get(f"/api/trips/{tid}").status_code == 404
    assert bob.put(f"/api/trips/{tid}", json={"destination": "제주"}).status_code == 404
    assert bob.post(f"/api/trips/{tid}/generate").status_code == 404
    assert bob.get(f"/api/trips/{tid}/versions").status_code == 404
    assert bob.post(f"/api/trips/{tid}/feedback", json={"overall_text": "좋았어"}).status_code == 404
    assert bob.get(f"/api/trips/{tid}/feedback").status_code == 404
    assert bob.post(f"/api/trips/{tid}/memory-proposals").status_code == 404
    assert bob.get(f"/api/trips/{tid}/delete-preview").status_code == 404
    assert bob.delete(f"/api/trips/{tid}", json={"delete_preference_ids": []}).status_code == 404
    assert bob.get("/api/trips").json() == []
    assert alice.get(f"/api/trips/{tid}").status_code == 200


def test_cannot_access_other_users_versions_feedback_and_proposals(alice, bob):
    trip = alice.post("/api/trips", json={"destination": "부산"}).json()
    tid = trip["id"]
    version = alice.post(f"/api/trips/{tid}/generate").json()
    assert bob.get(f"/api/trips/{tid}/versions/{version['id']}").status_code == 404
    fb = alice.post(f"/api/trips/{tid}/feedback", json={"version_id": version["id"], "overall_text": "하루 네 곳은 힘들었어."}).json()
    assert bob.put(f"/api/feedback/{fb['id']}", json={"overall_text": "변경"}).status_code == 404
    assert bob.delete(f"/api/feedback/{fb['id']}").status_code == 404
    proposals = alice.post(f"/api/trips/{tid}/memory-proposals").json()["proposals"]
    assert proposals, "mock 추출기가 제안을 만들어야 한다"
    prop_id = proposals[0]["id"]
    assert bob.post(f"/api/memory-proposals/{prop_id}/approve", json={}).status_code == 404
    assert bob.post(f"/api/memory-proposals/{prop_id}/reject").status_code == 404
    assert bob.get("/api/memory-proposals?status=pending").json() == []


def test_cannot_access_other_users_conversations(alice, bob):
    conv = alice.post("/api/conversations", json={"title": "부산 계획"}).json()
    cid = conv["id"]
    assert bob.get(f"/api/conversations/{cid}").status_code == 404
    assert bob.delete(f"/api/conversations/{cid}").status_code == 404
    assert bob.get("/api/conversations").json() == []
    r = bob.post("/api/chat/turns", json={"client_turn_id": "bob-isolation-1", "conversation_id": cid, "message": "안녕"})
    assert r.status_code == 404
    assert alice.get(f"/api/conversations/{cid}").status_code == 200
