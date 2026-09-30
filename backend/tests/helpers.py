def add_pref(user, category, value, **extra):
    r = user.post("/api/preferences", json={"category": category, "value": value, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def create_trip(user, destination, **extra):
    r = user.post("/api/trips", json={"destination": destination, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def generate(user, trip_id):
    r = user.post(f"/api/trips/{trip_id}/generate")
    assert r.status_code == 201, r.text
    return r.json()


def last_call(calls, kind):
    matches = [c for c in calls if c["kind"] == kind]
    assert matches, f"no AI call of kind {kind}"
    return matches[-1]


def place_items(version):
    return [i for d in version["course"]["days"] for i in d["items"] if i["kind"] == "place"]


BUSAN_FEEDBACK = "바다 보이는 카페는 좋았어. 시장은 너무 붐볐고, 하루 네 곳은 힘들었어."


def leave_feedback(user, trip_id, version, text=BUSAN_FEEDBACK, visits=None):
    body = {"version_id": version["id"], "overall_text": text, "overall_rating": 4, "visits": visits or []}
    r = user.post(f"/api/trips/{trip_id}/feedback", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def start_turn(user, message, trip_id=None, conversation_id=None, client_turn_id=None):
    import uuid
    body = {"client_turn_id": client_turn_id or uuid.uuid4().hex, "message": message,
            "trip_id": trip_id, "conversation_id": conversation_id}
    r = user.post("/api/chat/turns", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def read_events(user, turn_id, after=0, attempt=None, limit=None):
    """SSE 이벤트를 읽는다. limit개를 읽으면 연결을 끊는다(재접속 테스트용)."""
    import json
    url = f"/api/chat/turns/{turn_id}/events?after={after}" + (f"&attempt={attempt}" if attempt else "")
    events = []
    with user.client.stream("GET", url, headers=user.headers) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if limit and len(events) >= limit:
                    break
    return events


def chat(user, message, trip_id=None, conversation_id=None, client_turn_id=None):
    """턴을 시작하고 스트림이 끝날 때까지 읽은 뒤 (최종 턴, 이벤트)를 돌려준다."""
    turn = start_turn(user, message, trip_id, conversation_id, client_turn_id)
    events = read_events(user, turn["id"], attempt=turn["attempt"])
    final = user.get(f"/api/chat/turns/{turn['id']}").json()
    return final, events


def cards_of(turn, kind):
    return [c for c in turn["cards"] if c["type"] == kind]


def tool_names(events):
    return [e["name"] for e in events if e["type"] == "tool_start"]
