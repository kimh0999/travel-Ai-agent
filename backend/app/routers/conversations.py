from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse

from app.core.auth import AuthUser, current_user
from app.repositories import conversations as repo
from app.repositories import proposals as proposals_repo
from app.repositories import trips as trips_repo
from app.repositories import turns as turns_repo
from app.schemas.chat import ConversationCreate, ConversationDetail, ConversationSummary, Turn, TurnCreate
from app.services import chat_turns

router = APIRouter(prefix="/api", tags=["chat"])


def _summary(conv: dict, destinations: dict[str, str]) -> dict:
    return {**conv, "trip_destination": destinations.get(conv.get("trip_id") or "")}


def _destinations(uid: str) -> dict[str, str]:
    return {t["id"]: t["destination"] for t in trips_repo.list_for_owner(uid)}


def _enrich(uid: str, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """카드는 만들 때의 스냅샷이다. 변경안 상태·현재 코스 여부·고정 장소는 지금 값으로 덮어 보여준다."""
    if not cards:
        return cards
    trips = {t["id"]: t for t in trips_repo.list_for_owner(uid)}
    proposals = {p["id"]: p for p in proposals_repo.list_for_owner(uid)}
    out = []
    for card in cards:
        card = dict(card)
        trip = trips.get((card.get("trip") or {}).get("id") or "")
        if trip:
            card["trip"] = {**card["trip"], "pinned_places": trip.get("pinned_places") or [],
                            "current_version_id": trip.get("current_version_id")}
        if card.get("type") == "course":
            card["is_current"] = bool(trip) and trip.get("current_version_id") == card["version"]["id"]
        if card.get("type") == "proposal":
            live = proposals.get(card["proposal"]["id"])
            if live:
                card["proposal"] = {**card["proposal"], "status": live["status"], "edited_value": live.get("edited_value"),
                                    "result_preference_id": live.get("result_preference_id")}
        out.append(card)
    return out


def _turn_out(uid: str, turn: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    return {**turn, "cards": _enrich(uid, turn["cards"])} if turn else None


@router.post("/chat/turns", response_model=Turn, status_code=201)
def start_turn(body: TurnCreate, user: AuthUser = Depends(current_user)):
    return chat_turns.start_turn(user.uid, body)


@router.get("/chat/turns/{turn_id}", response_model=Turn)
def get_turn(turn_id: str, user: AuthUser = Depends(current_user)):
    return _turn_out(user.uid, chat_turns.get_turn(user.uid, turn_id))


@router.post("/chat/turns/{turn_id}/retry", response_model=Turn)
def retry_turn(turn_id: str, user: AuthUser = Depends(current_user)):
    return chat_turns.retry_turn(user.uid, turn_id)


@router.get("/chat/turns/{turn_id}/events")
def turn_events(turn_id: str, after: int = Query(default=0, ge=0), attempt: Optional[int] = Query(default=None, ge=1),
                user: AuthUser = Depends(current_user)):
    events = chat_turns.stream(user.uid, turn_id, after, attempt)
    return StreamingResponse(events, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/conversations", response_model=ConversationSummary, status_code=201)
def create_conversation(body: ConversationCreate, user: AuthUser = Depends(current_user)):
    destination = None
    if body.trip_id:
        destination = trips_repo.get(user.uid, body.trip_id)["destination"]
    title = (body.title or "").strip() or (f"{destination} 여행 대화" if destination else "새 대화")
    conv = repo.create(user.uid, title, body.trip_id)
    return {**conv, "trip_destination": destination}


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(user: AuthUser = Depends(current_user)):
    dests = _destinations(user.uid)
    return [_summary(c, dests) for c in repo.list_for_owner(user.uid)]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, user: AuthUser = Depends(current_user)):
    conv = repo.get(user.uid, conversation_id)
    messages = [{**m, "cards": _enrich(user.uid, m.get("cards") or [])} for m in repo.messages(user.uid, conversation_id)]
    return {**_summary(conv, _destinations(user.uid)), "messages": messages,
            "open_turn": _turn_out(user.uid, chat_turns.open_turn(user.uid, conversation_id))}


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, user: AuthUser = Depends(current_user)):
    repo.get(user.uid, conversation_id)
    turns_repo.delete_for_conversation(user.uid, conversation_id)
    repo.delete(conversation_id)
    return Response(status_code=204)
