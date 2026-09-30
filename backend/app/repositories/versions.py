from typing import Any, Optional

from google.api_core.exceptions import AlreadyExists

from app.repositories import trips as trips_repo
from app.repositories.base import get_owned, snap_to_dict
from app.schemas.common import utcnow


def _col(trip_id: str):
    return trips_repo.ref(trip_id).collection("course_versions")


def create(uid: str, trip_id: str, data: dict[str, Any], doc_id: Optional[str] = None) -> dict[str, Any]:
    """doc_id를 주면 그 ID로 한 번만 만든다(이미 있으면 기존 버전을 돌려준다: 재시도 중복 방지)."""
    doc = {**data, "owner_uid": uid, "trip_id": trip_id, "created_at": utcnow()}
    if doc_id is None:
        ref = _col(trip_id).document()
        ref.set(doc)
        return {**doc, "id": ref.id}
    ref = _col(trip_id).document(doc_id)
    try:
        ref.create(doc)
    except AlreadyExists:
        return get(uid, trip_id, doc_id)
    return {**doc, "id": doc_id}


def list_for_trip(uid: str, trip_id: str) -> list[dict[str, Any]]:
    docs = [snap_to_dict(s) for s in _col(trip_id).stream()]
    docs = [d for d in docs if d.get("owner_uid") == uid]
    docs.sort(key=lambda d: d["created_at"])
    return docs


def get(uid: str, trip_id: str, version_id: str) -> dict[str, Any]:
    return get_owned(_col(trip_id).document(version_id), uid, "코스 버전")


def collection(trip_id: str):
    return _col(trip_id)
