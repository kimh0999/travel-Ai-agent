"""취향 CRUD, 인증, 요청 검증."""


def test_health_needs_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ai_mode"] == "mock"


def test_api_requires_token(client):
    r = client.get("/api/preferences")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    r = client.get("/api/preferences", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_preference_crud_and_soft_delete(alice):
    r = alice.post("/api/preferences", json={"category": "transport", "value": "대중교통 선호"})
    assert r.status_code == 201, r.text
    pref = r.json()
    assert pref["scope"] == "base" and pref["status"] == "active" and pref["share_with_ai"] is True
    assert pref["sources"][0]["type"] == "manual"

    r = alice.put(f"/api/preferences/{pref['id']}", json={"status": "paused", "strength": "hard"})
    assert r.status_code == 200 and r.json()["status"] == "paused" and r.json()["strength"] == "hard"

    assert alice.delete(f"/api/preferences/{pref['id']}").status_code == 204
    assert alice.get(f"/api/preferences/{pref['id']}").status_code == 404
    assert alice.get("/api/preferences").json() == []


def test_sensitive_defaults_to_not_shared(alice):
    r = alice.post("/api/preferences", json={"category": "food", "value": "갑각류 알레르기",
                                             "strength": "hard", "sensitive": True})
    assert r.json()["share_with_ai"] is False
    plain = alice.post("/api/preferences", json={"category": "food", "value": "매운 음식 좋아함"}).json()
    r = alice.put(f"/api/preferences/{plain['id']}", json={"sensitive": True})
    assert r.json()["share_with_ai"] is False  # 민감 지정 시 전송 동의를 초기화


def test_preference_validation(alice):
    assert alice.post("/api/preferences", json={"category": "food", "value": ""}).status_code == 422
    assert alice.post("/api/preferences", json={"category": "food", "value": "x" * 201}).status_code == 422
    assert alice.post("/api/preferences", json={"category": "weird", "value": "x"}).status_code == 422
    assert alice.post("/api/preferences", json={"category": "food", "value": "x", "scope": "learned"}).status_code == 422
    r = alice.post("/api/preferences", json={"category": "food", "value": "x", "scope": "trip"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    pref = alice.post("/api/preferences", json={"category": "food", "value": "x"}).json()
    assert alice.put(f"/api/preferences/{pref['id']}", json={"status": "deleted"}).status_code == 422


def test_summary_marks_unknown_categories(alice):
    alice.put("/api/me", json={"home_base": "서울", "onboarded": True})
    alice.post("/api/preferences", json={"category": "transport", "value": "대중교통 선호"})
    paused = alice.post("/api/preferences", json={"category": "activity", "value": "카페"}).json()
    alice.put(f"/api/preferences/{paused['id']}", json={"status": "paused"})
    s = alice.get("/api/preferences/summary").json()
    assert s["home_base"] == "서울"
    assert list(s["by_category"]) == ["transport"]
    assert "activity" in s["unknown_categories"] and "transport" not in s["unknown_categories"]
    assert s["paused_count"] == 1
