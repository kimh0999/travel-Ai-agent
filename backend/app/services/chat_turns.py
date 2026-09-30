"""대화 턴 실행과 실시간 이벤트.

흐름: POST로 턴을 만들면(같은 client_turn_id면 기존 턴 반환) 서버 스레드에서 에이전트를 실행한다.
실행은 HTTP 연결과 무관하게 계속되고, 화면은 SSE로 이벤트를 받는다. 연결이 끊기면 마지막으로 받은
이벤트 번호(after)로 다시 붙어 이어 받는다. 실행이 실패하면 저장된 transcript에서 이어서 재시도한다.

이벤트 종류: start, text(delta), text_reset, tool_start, tool_end, card, active_trip, done, error
"""
import json
import logging
import threading
import time
from datetime import timedelta, timezone
from typing import Any, Iterator, Optional

from fastapi.encoders import jsonable_encoder

from app.clients.ai_base import AIError, reply_from_transcript
from app.clients.factory import get_ai_client
from app.core.errors import AppError
from app.repositories import conversations as conv_repo
from app.repositories import trips as trips_repo
from app.repositories import turns as turns_repo
from app.schemas.chat import TurnCreate
from app.schemas.common import utcnow
from app.services.agent_tools import TOOLS, TRANSPORT_LABELS, ToolContext, make_executor, trip_brief
from app.services.context_builder import load_prompt

logger = logging.getLogger("app.turns")

TURN_DEADLINE_SECONDS = 240
MAX_TOOL_CALLS = 12
HISTORY_LIMIT = 20
ORPHAN_SECONDS = 30  # 실행 중인 스레드가 없는데 이 시간 넘게 갱신이 없으면 중단된 턴으로 본다
KEEPALIVE_SECONDS = 15
KST = timezone(timedelta(hours=9))
WEEKDAYS = "월화수목금토일"


# ---------------- 이벤트 버스 (프로세스 메모리) ----------------

class TurnBus:
    def __init__(self, attempt: int):
        self.attempt = attempt
        self.events: list[dict[str, Any]] = []
        self.finished = False
        self._cond = threading.Condition()

    def publish(self, event: dict[str, Any]) -> None:
        with self._cond:
            self.events.append({**event, "seq": len(self.events) + 1})
            self._cond.notify_all()

    def finish(self) -> None:
        with self._cond:
            self.finished = True
            self._cond.notify_all()

    def wait(self, after: int, timeout: float) -> tuple[list[dict[str, Any]], bool]:
        with self._cond:
            if len(self.events) <= after and not self.finished:
                self._cond.wait(timeout)
            return self.events[after:], self.finished


_BUSES: dict[str, TurnBus] = {}
_LOCK = threading.Lock()


def _running(turn_id: str) -> bool:
    bus = _BUSES.get(turn_id)
    return bool(bus and not bus.finished)


def _forget_later(turn_id: str, bus: TurnBus) -> None:
    def forget():
        with _LOCK:
            if _BUSES.get(turn_id) is bus:
                del _BUSES[turn_id]
    timer = threading.Timer(300, forget)
    timer.daemon = True
    timer.start()


# ---------------- 프롬프트 ----------------

def _trip_line(t: dict[str, Any]) -> str:
    if t.get("start_date"):
        when = f"{t['start_date']}~{t.get('end_date') or ''}"
    elif t.get("period_hint"):
        when = f"날짜 미정({t['period_hint']})"
    else:
        when = "날짜 미정"
    nights = f"{t['days'] - 1}박 {t['days']}일" if t["days"] > 1 else "당일"
    transport = TRANSPORT_LABELS.get(t.get("transport") or "", "이동수단 모름")
    course = "코스 있음" if t.get("current_version_id") else "코스 없음"
    status = "다녀옴" if t.get("status") == "completed" else "계획 중"
    return f"{t['destination']} (trip_id={t['id']}) · {when} · {nights} · {transport} · {course} · {status}"


def build_system(uid: str, active_trip_id: Optional[str]) -> str:
    """턴 시작 시 한 번 만들어 저장한다(재시도 때 같은 프롬프트로 이어가기 위해)."""
    now = utcnow().astimezone(KST)
    trips = trips_repo.list_for_owner(uid)[:10]
    active = next((t for t in trips if t["id"] == active_trip_id), None)
    lines = [
        f"오늘: {now.date().isoformat()} ({WEEKDAYS[now.weekday()]}요일), 한국 시간 기준.",
        f"현재 작업 중인 여행: {_trip_line(active) if active else '없음'}",
        "사용자의 여행 목록:",
        *([f"- {_trip_line(t)}" for t in trips] or ["- (없음)"]),
    ]
    return load_prompt("chat_system.md") + "\n\n<session>\n" + "\n".join(lines) + "\n</session>"


def _card_note(card: dict[str, Any]) -> str:
    kind = card.get("type")
    trip = card.get("trip") or {}
    dest = trip.get("destination", "")
    if kind == "course":
        v = card["version"]
        changes = f", 변경점: {'; '.join(v.get('changes') or [])}" if v.get("changes") else ""
        return f"[코스 카드: {dest} (trip_id={trip.get('id')}) 버전 {v['id']} '{v['course']['title']}'{changes}]"
    if kind == "trip":
        return f"[여행 카드: {dest} (trip_id={trip.get('id')})]"
    if kind == "proposal":
        p = card["proposal"]
        return f"[기억 변경안 카드: '{p.get('after') or p.get('before')}' ({p.get('applies_to')}), id={p['id']}]"
    if kind == "condition":
        return f"[이번 여행 조건 카드: {dest} - {card['preference']['value']}]"
    if kind == "pin":
        return f"[장소 {'고정' if card['pinned'] else '고정 해제'} 카드: {dest} - {card['name']}]"
    if kind == "question":
        return f"[질문 카드: {card['question']} / 선택지: {', '.join(card['options'])}]"
    return ""


def _history(uid: str, conversation_id: str) -> list[dict[str, Any]]:
    out = []
    for m in conv_repo.messages(uid, conversation_id)[-HISTORY_LIMIT:]:
        text = m["content"]
        notes = [n for n in (_card_note(c) for c in m.get("cards") or []) if n]
        if notes:
            text = (text + "\n" if text else "") + "\n".join(notes)
        out.append({"role": m["role"], "content": text or "(내용 없음)"})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


# ---------------- 턴 생성·조회 ----------------

def _public(turn: dict[str, Any]) -> dict[str, Any]:
    return {k: turn.get(k) for k in ("id", "conversation_id", "trip_id", "status", "attempt", "message", "reply",
                                     "cards", "error", "created_at", "updated_at")}


def _check_orphan(turn: dict[str, Any]) -> dict[str, Any]:
    """서버 재시작 등으로 실행 스레드가 사라진 턴은 실패로 바꿔 재시도할 수 있게 한다."""
    if turn["status"] != "running" or _running(turn["id"]):
        return turn
    if (utcnow() - turn["updated_at"]).total_seconds() < ORPHAN_SECONDS:
        return turn
    error = {"code": "INTERRUPTED", "message": "처리가 중단됐어요. 다시 시도하면 진행한 곳부터 이어서 해요."}
    turns_repo.update(turn["id"], {"status": "failed", "error": error})
    return {**turn, "status": "failed", "error": error}


def get_turn(uid: str, turn_id: str) -> dict[str, Any]:
    return _public(_check_orphan(turns_repo.get(uid, turn_id)))


def open_turn(uid: str, conversation_id: str) -> Optional[dict[str, Any]]:
    """대화의 마지막 턴이 아직 실행 중이거나 실패했으면 돌려준다."""
    turns = turns_repo.list_for_conversation(uid, conversation_id)
    if not turns:
        return None
    last = _check_orphan(turns[-1])
    return _public(last) if last["status"] != "done" else None


def start_turn(uid: str, body: TurnCreate) -> dict[str, Any]:
    turn_id = turns_repo.turn_id_for(uid, body.client_turn_id)
    try:
        existing = turns_repo.get(uid, turn_id)
        return _public(_check_orphan(existing))  # 같은 요청을 다시 보냄: 새로 실행하지 않는다
    except AppError:
        pass
    message = body.message.strip()
    if not message:
        raise AppError(422, "VALIDATION_ERROR", "메시지를 입력하세요.")
    if body.conversation_id:
        conversation = conv_repo.get(uid, body.conversation_id)
        last = open_turn(uid, conversation["id"])
        if last and last["status"] == "running":
            raise AppError(409, "TURN_RUNNING", "앞선 요청을 아직 처리하고 있어요. 끝난 뒤 다시 보내 주세요.")
    else:
        title = message[:40] + ("…" if len(message) > 40 else "")
        conversation = conv_repo.create(uid, title, body.trip_id, doc_id=f"c{turn_id[1:]}")
    active_trip_id = body.trip_id or conversation.get("trip_id")
    if active_trip_id:
        trips_repo.get(uid, active_trip_id)  # 소유자 검사
        if conversation.get("trip_id") != active_trip_id:
            conv_repo.set_trip(conversation["id"], active_trip_id)

    transcript = _history(uid, conversation["id"]) + [{"role": "user", "content": message}]
    now = utcnow()
    turn, created = turns_repo.create(turn_id, {
        "owner_uid": uid, "conversation_id": conversation["id"], "trip_id": active_trip_id, "status": "running",
        "attempt": 1, "message": message, "reply": "", "cards": [], "error": None,
        "system": build_system(uid, active_trip_id), "transcript": json.dumps(transcript, ensure_ascii=False),
        "created_at": now, "updated_at": now,
    })
    if created:
        _launch(turn_id, 1)
    return _public(_check_orphan(turn))


def retry_turn(uid: str, turn_id: str) -> dict[str, Any]:
    turn = _check_orphan(turns_repo.get(uid, turn_id))
    if turn["status"] != "failed":
        return _public(turn)  # 실행 중이거나 끝난 턴은 다시 실행하지 않는다
    attempt = int(turn.get("attempt", 1)) + 1
    turns_repo.update(turn_id, {"status": "running", "attempt": attempt, "error": None})
    _launch(turn_id, attempt)
    return get_turn(uid, turn_id)


def _launch(turn_id: str, attempt: int) -> None:
    bus = TurnBus(attempt)
    with _LOCK:
        _BUSES[turn_id] = bus
    threading.Thread(target=_run, args=(turn_id, bus), name=f"turn-{turn_id[:8]}", daemon=True).start()


# ---------------- 실행 ----------------

def _run(turn_id: str, bus: TurnBus) -> None:
    started = time.monotonic()
    try:
        turn = turns_repo.col().document(turn_id).get().to_dict()
        uid = turn["owner_uid"]
        transcript = json.loads(turn["transcript"])
        cards: list[dict[str, Any]] = list(turn.get("cards") or [])
        bus.publish({"type": "start", "attempt": bus.attempt, "cards": cards,
                     "text": reply_from_transcript(transcript)})
        active = {"trip_id": turn.get("trip_id")}

        def add_card(card: dict[str, Any]) -> None:
            if any(c.get("key") == card.get("key") for c in cards):
                return
            cards.append(card)
            turns_repo.update(turn_id, {"cards": cards})
            bus.publish({"type": "card", "card": card})

        def set_active_trip(trip: dict[str, Any]) -> None:
            if active["trip_id"] == trip["id"]:
                return
            active["trip_id"] = trip["id"]
            conv_repo.set_trip(turn["conversation_id"], trip["id"])
            turns_repo.update(turn_id, {"trip_id": trip["id"]})
            bus.publish({"type": "active_trip", "trip": trip_brief(trip)})

        def on_step(messages: list[dict[str, Any]]) -> None:
            turns_repo.update(turn_id, {"transcript": json.dumps(messages, ensure_ascii=False)})

        user_texts = [m["content"] for m in transcript if m["role"] == "user" and isinstance(m["content"], str)]
        ctx = ToolContext(uid=uid, turn_id=turn_id, conversation_id=turn["conversation_id"], user_texts=user_texts,
                          emit=bus.publish, add_card=add_card, set_active_trip=set_active_trip,
                          has_card=lambda key: any(c.get("key") == key for c in cards))
        result = get_ai_client().run_turn(
            system=turn["system"], transcript=transcript, tools=TOOLS, execute=make_executor(ctx), emit=bus.publish,
            on_step=on_step, deadline=started + TURN_DEADLINE_SECONDS, max_tool_calls=MAX_TOOL_CALLS)
        reply = result.reply or ("요청을 처리했어요. 위 카드를 확인해 주세요." if cards else "")
        if not reply:
            raise AIError("AI 답변이 비어 있습니다. 다시 시도해 주세요.")
        conv_repo.append_turn(uid, turn["conversation_id"], turn_id, turn["message"], reply, cards)
        turns_repo.update(turn_id, {"status": "done", "reply": reply})
        bus.publish({"type": "done", "reply": reply, "cards": cards})
    except (AIError, AppError) as e:
        _fail(turn_id, bus, e.code, e.message)
    except Exception:
        logger.exception("turn %s failed", turn_id)
        _fail(turn_id, bus, "INTERNAL", "서버 오류로 처리하지 못했어요. 다시 시도하면 진행한 곳부터 이어서 해요.")
    finally:
        bus.finish()
        _forget_later(turn_id, bus)


def _fail(turn_id: str, bus: TurnBus, code: str, message: str) -> None:
    error = {"code": code, "message": message}
    try:
        turns_repo.update(turn_id, {"status": "failed", "error": error})
    except Exception:
        logger.exception("could not mark turn %s failed", turn_id)
    bus.publish({"type": "error", "error": error})


# ---------------- SSE ----------------

def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(jsonable_encoder(event), ensure_ascii=False)}\n\n"


def stream(uid: str, turn_id: str, after: int, attempt: Optional[int]) -> Iterator[str]:
    """after 이후의 이벤트를 보낸다. 이 서버에 실행 기록이 없으면 저장된 상태(snapshot)를 한 번 보낸다.

    소유자 검사는 스트림을 열기 전에 한다(실패하면 일반 JSON 오류 응답)."""
    turn = get_turn(uid, turn_id)
    bus = _BUSES.get(turn_id)
    if bus is None or (attempt is not None and bus.attempt != attempt):
        return iter([_sse({"type": "snapshot", "seq": 0, "turn": turn})])
    return _follow(bus, after)


def _follow(bus: TurnBus, after: int) -> Iterator[str]:
    while True:
        events, finished = bus.wait(after, KEEPALIVE_SECONDS)
        for e in events:
            yield _sse(e)
        after += len(events)
        if finished and after >= len(bus.events):
            return
        if not events:
            yield ": keepalive\n\n"
