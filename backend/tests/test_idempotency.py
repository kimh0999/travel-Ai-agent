"""필수 테스트 6: 같은 변경안을 두 번(동시에) 승인해도 기억이 중복되지 않는다."""
from concurrent.futures import ThreadPoolExecutor

from tests.helpers import create_trip, generate, leave_feedback


def _setup(alice):
    trip = create_trip(alice, "부산")
    version = generate(alice, trip["id"])
    leave_feedback(alice, trip["id"], version)
    proposals = alice.post(f"/api/trips/{trip['id']}/memory-proposals").json()["proposals"]
    return next(p for p in proposals if p["type"] == "add")


def test_double_approval_creates_single_memory(alice):
    prop = _setup(alice)
    r1 = alice.post(f"/api/memory-proposals/{prop['id']}/approve", json={})
    r2 = alice.post(f"/api/memory-proposals/{prop['id']}/approve", json={})
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["already_decided"] is False and r2.json()["already_decided"] is True
    assert r1.json()["preference_id"] == r2.json()["preference_id"] == f"prop_{prop['id']}"
    matching = [p for p in alice.get("/api/preferences").json() if p["value"] == prop["after"]]
    assert len(matching) == 1


def test_concurrent_approvals_create_single_memory(alice):
    prop = _setup(alice)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: alice.post(f"/api/memory-proposals/{prop['id']}/approve", json={}), range(5)))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert sum(1 for r in results if not r.json()["already_decided"]) == 1
    matching = [p for p in alice.get("/api/preferences").json() if p["value"] == prop["after"]]
    assert len(matching) == 1
    assert len(matching[0]["sources"]) == 1
