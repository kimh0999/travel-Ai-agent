from datetime import date, timedelta
from typing import Any, Optional

from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore import FieldFilter

from app.core.errors import AppError
from app.core.firebase import get_db
from app.repositories.base import get_owned, snap_to_dict
from app.schemas.common import utcnow
from app.schemas.trips import TripCreate, TripUpdate, _resolve_dates

COLLECTION = "trips"


def _col():
    return get_db().collection(COLLECTION)


def ref(trip_id: str):
    return _col().document(trip_id)


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def create(uid: str, body: TripCreate, default_days: int, doc_id: Optional[str] = None) -> dict[str, Any]:
    """doc_id를 주면 그 ID로 한 번만 만든다(이미 있으면 기존 여행을 돌려준다: 재시도 중복 방지)."""
    now = utcnow()
    data = {
        "owner_uid": uid,
        "destination": body.destination,
        "start_date": _iso(body.start_date),
        "end_date": _iso(body.end_date),
        "days": body.days or default_days,
        "days_is_default": body.days is None,
        "period_hint": body.period_hint,
        "transport": body.transport,
        "pinned_places": [],
        "companions": [c.model_dump() for c in body.companions],
        "budget": body.budget.model_dump() if body.budget else None,
        "conditions": body.conditions,
        "status": "planned",
        "current_version_id": None,
        "created_at": now,
        "updated_at": now,
    }
    if doc_id is None:
        doc = _col().document()
        doc.set(data)
        return {**data, "id": doc.id}
    doc = _col().document(doc_id)
    try:
        doc.create(data)
    except AlreadyExists:
        return get(uid, doc_id)
    return {**data, "id": doc_id}


def list_for_owner(uid: str) -> list[dict[str, Any]]:
    docs = [snap_to_dict(s) for s in _col().where(filter=FieldFilter("owner_uid", "==", uid)).stream()]
    docs.sort(key=lambda d: d["created_at"], reverse=True)
    return docs


def get(uid: str, trip_id: str) -> dict[str, Any]:
    return get_owned(ref(trip_id), uid, "여행")


def update(uid: str, trip_id: str, body: TripUpdate) -> dict[str, Any]:
    current = get(uid, trip_id)
    changes = body.model_dump(exclude_unset=True)
    for key in ("destination", "status", "days"):
        if key in changes and changes[key] is None:
            changes.pop(key)
    if "destination" in changes:
        changes["destination"] = changes["destination"].strip()
        if not changes["destination"]:
            raise AppError(422, "VALIDATION_ERROR", "목적지를 입력하세요.")

    if {"start_date", "end_date", "days"} & changes.keys():
        start = changes["start_date"] if "start_date" in changes else _parse(current.get("start_date"))
        end = changes["end_date"] if "end_date" in changes else _parse(current.get("end_date"))
        days = changes.get("days")
        if days is not None and "end_date" not in changes and start:
            end = start + timedelta(days=days - 1)
        try:
            start, end, days = _resolve_dates(start, end, days)
        except ValueError as e:
            raise AppError(422, "VALIDATION_ERROR", str(e))
        changes["start_date"], changes["end_date"] = _iso(start), _iso(end)
        if days is not None:
            changes["days"] = days
            changes["days_is_default"] = False
    if "companions" in changes and changes["companions"] is None:
        changes["companions"] = []
    if not changes:
        return current
    changes["updated_at"] = utcnow()
    ref(trip_id).update(changes)
    return {**current, **changes}


def set_current_version(trip_id: str, version_id: str) -> None:
    ref(trip_id).update({"current_version_id": version_id, "updated_at": utcnow()})


def set_pinned(trip_id: str, pinned: list[dict[str, str]]) -> None:
    ref(trip_id).update({"pinned_places": pinned, "updated_at": utcnow()})


def _parse(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None
