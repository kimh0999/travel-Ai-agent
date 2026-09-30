"""필수 테스트 8: AI 실패·타임아웃 시 입력과 기존 코스가 보존된다."""
from app.clients import mock_ai
from tests.helpers import create_trip, generate


def test_timeout_keeps_trip_input_and_existing_course(alice):
    trip = create_trip(alice, "부산", conditions="바다 위주", budget={"amount": 500000, "per": "group", "unit": "trip"})
    first = generate(alice, trip["id"])

    mock_ai.FAILURES[:] = ["timeout"]
    r = alice.post(f"/api/trips/{trip['id']}/generate")
    assert r.status_code == 504 and r.json()["error"]["code"] == "AI_TIMEOUT"

    mock_ai.FAILURES[:] = ["error"]
    r = alice.post(f"/api/trips/{trip['id']}/generate")
    assert r.status_code == 502 and r.json()["error"]["code"] == "AI_FAILED"

    after = alice.get(f"/api/trips/{trip['id']}").json()
    assert after["current_version_id"] == first["id"]
    for key in ("destination", "conditions", "budget", "days"):
        assert after[key] == trip[key]
    versions = alice.get(f"/api/trips/{trip['id']}/versions").json()
    assert [v["id"] for v in versions] == [first["id"]]
    assert alice.get(f"/api/trips/{trip['id']}/versions/{first['id']}").json()["course"] == first["course"]


def test_proposal_generation_failure_changes_nothing(alice):
    trip = create_trip(alice, "부산")
    version = generate(alice, trip["id"])
    alice.post(f"/api/trips/{trip['id']}/feedback", json={"version_id": version["id"], "overall_text": "하루 네 곳은 힘들었어."})
    mock_ai.FAILURES[:] = ["timeout"]
    r = alice.post(f"/api/trips/{trip['id']}/memory-proposals")
    assert r.status_code == 504
    assert alice.get("/api/memory-proposals").json() == []
    assert len(alice.get(f"/api/trips/{trip['id']}/feedback").json()) == 1
