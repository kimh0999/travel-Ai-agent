"""필수 테스트 4·5 + 핵심 시나리오:
취향 저장 → 부산 코스 생성 → 여행 후 피드백 → 기억 변경 승인 → 여수 코스에 반영."""
from tests.helpers import add_pref, create_trip, generate, last_call, leave_feedback, place_items


def test_core_scenario_busan_feedback_approval_yeosu(alice, ai_calls):
    # 1) 취향 저장
    alice.put("/api/me", json={"home_base": "서울", "onboarded": True})
    transport = add_pref(alice, "transport", "선호 교통수단: 대중교통", source_type="onboarding")
    add_pref(alice, "mobility", "오래 걷는 것은 피하고 싶음 (하루 30분 이내)", source_type="onboarding")

    # 2) 부산 코스: 기본 하루 3곳
    busan = create_trip(alice, "부산")
    busan_v = generate(alice, busan["id"])
    busan_day1 = [i for i in busan_v["course"]["days"][0]["items"] if i["kind"] == "place"]
    assert len(busan_day1) == 3
    assert transport["id"] in {a["preference_id"] for a in busan_v["applied_memories"]}

    # 3) 여행 완료 + 피드백 (방문한 장소 표시)
    alice.put(f"/api/trips/{busan['id']}", json={"status": "completed"})
    visits = [{"item_id": i["item_id"], "place_name": i["name"], "visited": True, "rating": 4} for i in place_items(busan_v)[:2]]
    leave_feedback(alice, busan["id"], busan_v, visits=visits)

    # 4) 변경안 생성 → 항목별 승인·거절
    proposals = alice.post(f"/api/trips/{busan['id']}/memory-proposals").json()["proposals"]
    by_after = {p["after"]: p for p in proposals}
    pace = by_after["하루 주요 방문지 두세 곳 선호"]
    crowd = by_after["혼잡한 장소를 피하는 편"]
    cafe = by_after["바다 전망 카페 선호"]
    assert alice.post(f"/api/memory-proposals/{pace['id']}/approve", json={}).status_code == 200
    assert alice.post(f"/api/memory-proposals/{cafe['id']}/approve", json={}).status_code == 200
    assert alice.post(f"/api/memory-proposals/{crowd['id']}/reject").status_code == 200

    learned = [p for p in alice.get("/api/preferences").json() if p["scope"] == "learned"]
    assert {p["value"] for p in learned} == {"하루 주요 방문지 두세 곳 선호", "바다 전망 카페 선호"}

    # 5) 여수 코스: 승인한 기억이 컨텍스트와 결과에 반영
    yeosu = create_trip(alice, "여수")
    yeosu_v = generate(alice, yeosu["id"])
    prompt = last_call(ai_calls, "course")["user"]
    assert "하루 주요 방문지 두세 곳 선호" in prompt and "지난 부산 여행 피드백" in prompt
    assert "바다 전망 카페 선호" in prompt
    assert "혼잡한 장소를 피하는 편" not in prompt  # 거절한 제안은 반영되지 않음
    assert "부산 여행: 승인된 교훈" in prompt

    yeosu_day1 = [i for i in yeosu_v["course"]["days"][0]["items"] if i["kind"] == "place"]
    assert len(yeosu_day1) == 2  # 하루 두 곳
    applied = {a["value"]: a for a in yeosu_v["applied_memories"]}
    pace_applied = applied["하루 주요 방문지 두세 곳 선호"]
    assert pace_applied["scope"] == "learned" and pace_applied["source_destinations"] == ["부산"]
    assert "지난 부산 여행" in yeosu_v["course"]["summary_explanation"]
    assert busan["id"] in yeosu_v["generation_basis"]["past_trip_ids"]


def test_rejected_deleted_paused_and_other_trip_memories_are_excluded(alice, ai_calls):
    """필수 테스트 5: 거절·삭제·비활성화한 기억, 다른 여행의 scope=trip 기억은 컨텍스트에서 제외."""
    keep = add_pref(alice, "activity", "미술관 좋아함")
    paused = add_pref(alice, "activity", "쇼핑 좋아함")
    alice.put(f"/api/preferences/{paused['id']}", json={"status": "paused"})
    deleted = add_pref(alice, "activity", "야시장 좋아함")
    alice.delete(f"/api/preferences/{deleted['id']}")

    busan = create_trip(alice, "부산")
    busan_only = add_pref(alice, "pace", "부산에서는 늦잠", scope="trip", trip_id=busan["id"])
    busan_v = generate(alice, busan["id"])
    assert busan_only["value"] in last_call(ai_calls, "course")["user"]

    leave_feedback(alice, busan["id"], busan_v, text="시장은 너무 붐볐어")
    crowd = alice.post(f"/api/trips/{busan['id']}/memory-proposals").json()["proposals"][0]
    alice.post(f"/api/memory-proposals/{crowd['id']}/reject")

    # 승인 후 비활성화한 learned 기억도 제외
    leave_feedback(alice, busan["id"], busan_v, text="바다 보이는 카페는 좋았어")
    cafe = next(p for p in alice.post(f"/api/trips/{busan['id']}/memory-proposals").json()["proposals"] if "카페" in p["after"])
    pref_id = alice.post(f"/api/memory-proposals/{cafe['id']}/approve", json={}).json()["preference_id"]
    alice.put(f"/api/preferences/{pref_id}", json={"status": "paused"})

    yeosu = create_trip(alice, "여수")
    yeosu_v = generate(alice, yeosu["id"])
    prompt = last_call(ai_calls, "course")["user"]
    assert keep["value"] in prompt
    for excluded in ("쇼핑 좋아함", "야시장 좋아함", "부산에서는 늦잠", "혼잡한 장소를 피하는 편", "바다 전망 카페 선호"):
        assert excluded not in prompt, excluded
    ids = set(yeosu_v["generation_basis"]["memory_ids"])
    assert ids == {keep["id"]}


def test_soft_preferences_are_capped_at_15_but_hard_always_included(alice, ai_calls):
    hard = add_pref(alice, "food", "견과류 알레르기 있음", strength="hard")
    for i in range(20):
        add_pref(alice, "activity", f"활동 선호 {i:02d}")
    trip = create_trip(alice, "부산")
    version = generate(alice, trip["id"])
    ids = version["generation_basis"]["memory_ids"]
    assert hard["id"] in ids and len(ids) == 16


def test_companion_preferences_only_with_companions(alice, ai_calls):
    comp = add_pref(alice, "pace", "아이는 낮잠 시간이 필요", subject="companion")
    solo = create_trip(alice, "부산")
    generate(alice, solo["id"])
    assert comp["value"] not in last_call(ai_calls, "course")["user"]
    family = create_trip(alice, "여수", companions=[{"relation": "아이", "note": "5세"}])
    generate(alice, family["id"])
    assert comp["value"] in last_call(ai_calls, "course")["user"]


def test_updated_base_preference_shows_feedback_origin(alice, ai_calls):
    """기존(직접 입력) 기억을 피드백 승인으로 바꾸면, 다음 코스에서 출처가 '지난 부산 여행 피드백'으로 표시된다."""
    pace = add_pref(alice, "pace", "하루 주요 방문지 3~4곳")
    busan = create_trip(alice, "부산")
    version = generate(alice, busan["id"])
    leave_feedback(alice, busan["id"], version, text="하루 네 곳은 힘들었어")
    prop = alice.post(f"/api/trips/{busan['id']}/memory-proposals").json()["proposals"][0]
    assert prop["type"] == "update" and prop["target_preference_id"] == pace["id"]
    alice.post(f"/api/memory-proposals/{prop['id']}/approve", json={})
    assert alice.get(f"/api/preferences/{pace['id']}").json()["value"] == "하루 주요 방문지 두세 곳 선호"

    yeosu = create_trip(alice, "여수")
    v = generate(alice, yeosu["id"])
    prompt = last_call(ai_calls, "course")["user"]
    assert f"{pace['id']} | soft | self" in prompt and "출처: 지난 부산 여행 피드백" in prompt
    applied = next(a for a in v["applied_memories"] if a["preference_id"] == pace["id"])
    assert applied["source_destinations"] == ["부산"]
    assert "지난 부산 여행에서" in v["course"]["summary_explanation"]
    assert len([i for i in v["course"]["days"][0]["items"] if i["kind"] == "place"]) == 2
