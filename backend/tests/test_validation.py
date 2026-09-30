"""필수 테스트 9: 잘못된 날짜·예산·AI 응답을 처리한다."""
from app.clients import mock_ai
from tests.helpers import create_trip, generate


def _err(r, status=422, code="VALIDATION_ERROR"):
    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] == code
    return r.json()["error"]["message"]


def test_invalid_dates_are_rejected(alice):
    _err(alice.post("/api/trips", json={"destination": "부산", "start_date": "2026-10-05", "end_date": "2026-10-01"}))
    _err(alice.post("/api/trips", json={"destination": "부산", "end_date": "2026-10-01"}))
    _err(alice.post("/api/trips", json={"destination": "부산", "start_date": "2026-10-01", "end_date": "2026-10-20"}))
    _err(alice.post("/api/trips", json={"destination": "부산", "days": 15}))
    _err(alice.post("/api/trips", json={"destination": "부산", "start_date": "2026-10-01", "end_date": "2026-10-03", "days": 5}))
    _err(alice.post("/api/trips", json={"destination": "부산", "start_date": "not-a-date"}))
    _err(alice.post("/api/trips", json={"destination": "   "}))
    ok = create_trip(alice, "부산", start_date="2026-10-01", end_date="2026-10-03")
    assert ok["days"] == 3 and ok["days_is_default"] is False
    ok2 = create_trip(alice, "부산", start_date="2026-10-01", days=2)
    assert ok2["end_date"] == "2026-10-02"
    _err(alice.put(f"/api/trips/{ok['id']}", json={"end_date": "2026-09-01"}))


def test_invalid_budget_is_rejected(alice):
    _err(alice.post("/api/trips", json={"destination": "부산", "budget": {"amount": -1, "per": "person", "unit": "day"}}))
    _err(alice.post("/api/trips", json={"destination": "부산", "budget": {"amount": 1000}}))
    _err(alice.post("/api/trips", json={"destination": "부산", "budget": {"amount": 1000, "per": "x", "unit": "day"}}))
    trip = create_trip(alice, "부산", budget={"amount": 300000, "per": "person", "unit": "trip"})
    assert trip["budget"]["amount"] == 300000


def test_invalid_ai_response_is_retried_once(alice, ai_calls):
    trip = create_trip(alice, "부산")
    mock_ai.FAILURES[:] = ["invalid"]
    version = generate(alice, trip["id"])
    assert len([c for c in ai_calls if c["kind"] == "course"]) == 2
    assert version["course"]["days"]


def test_invalid_ai_response_twice_returns_error(alice, ai_calls):
    trip = create_trip(alice, "부산")
    mock_ai.FAILURES[:] = ["invalid", "invalid"]
    _err(alice.post(f"/api/trips/{trip['id']}/generate"), 502, "AI_FAILED")
    assert len([c for c in ai_calls if c["kind"] == "course"]) == 2
    assert alice.get(f"/api/trips/{trip['id']}/versions").json() == []
    mock_ai.FAILURES.clear()


def test_unrealistic_schedule_is_flagged(alice):
    trip = create_trip(alice, "부산", days=1)
    version = generate(alice, trip["id"])
    course = {k: version["course"][k] for k in ("title", "summary_explanation", "assumptions", "questions_for_user",
                                                "applied_memories")}
    day = version["course"]["days"][0]
    items = [{k: v for k, v in i.items() if k not in ("place", "travel_is_estimate", "cost_is_estimate")} for i in day["items"]]
    items[0]["stay_minutes"] = 700
    items[1]["travel_from_prev"] = {"mode": "car", "minutes_estimate": 400, "note": None}
    course["days"] = [{"day_index": 1, "date": None, "theme": day["theme"], "items": items}]
    r = alice.post(f"/api/trips/{trip['id']}/versions", json={"parent_version_id": version["id"], "course": course})
    assert r.status_code == 201, r.text
    warnings = r.json()["warnings"]
    assert any("비현실적" in w for w in warnings)
    assert any("너무 길어요" in w for w in warnings)


def test_invalid_revision_structure_is_rejected(alice):
    trip = create_trip(alice, "부산", days=1)
    version = generate(alice, trip["id"])
    bad = {"title": "x", "summary_explanation": "x", "assumptions": [], "questions_for_user": [], "applied_memories": [],
           "days": [{"day_index": 1, "date": None, "theme": "t", "items": [
               {"item_id": "a", "kind": "place", "name": "p", "search_keyword": None, "reason": "r",
                "applied_preference_ids": [], "stay_minutes": -5, "travel_from_prev": None,
                "cost_estimate_krw": None, "cost_basis": None}]}]}
    _err(alice.post(f"/api/trips/{trip['id']}/versions", json={"parent_version_id": version["id"], "course": bad}))
