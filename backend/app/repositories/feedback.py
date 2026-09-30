from typing import Any

from google.cloud.firestore import FieldFilter

from app.core.errors import AppError
from app.core.firebase import get_db
from app.repositories import trips as trips_repo
from app.repositories import versions as versions_repo
from app.repositories.base import get_owned, snap_to_dict
from app.schemas.common import utcnow
from app.schemas.feedback import FeedbackCreate, FeedbackUpdate, VisitFeedback

COLLECTION = "feedback"


def _col():
    return get_db().collection(COLLECTION)


def _check_visits(uid: str, trip_id: str, version_id: str | None, visits: list[VisitFeedback]) -> None:
    """장소별 피드백은 해당 여행의 코스 항목에만 남길 수 있다(추천하지 않은 장소를 방문 기록으로 만들지 않기 위해)."""
    if not visits:
        return
    if not version_id:
        raise AppError(422, "VALIDATION_ERROR", "장소별 피드백에는 코스 버전(version_id)이 필요합니다.")
    version = versions_repo.get(uid, trip_id, version_id)
    item_ids = {i["item_id"] for d in version["course"]["days"] for i in d["items"]}
    unknown = [v.item_id for v in visits if v.item_id not in item_ids]
    if unknown:
        raise AppError(422, "VALIDATION_ERROR", f"코스에 없는 항목입니다: {', '.join(unknown[:5])}")


def create(uid: str, trip_id: str, body: FeedbackCreate) -> dict[str, Any]:
    trips_repo.get(uid, trip_id)
    if body.version_id:
        versions_repo.get(uid, trip_id, body.version_id)
    _check_visits(uid, trip_id, body.version_id, body.visits)
    now = utcnow()
    data = {"owner_uid": uid, "trip_id": trip_id, "version_id": body.version_id,
            "visits": [v.model_dump() for v in body.visits], "overall_text": body.overall_text,
            "overall_rating": body.overall_rating, "created_at": now, "updated_at": now}
    ref = _col().document()
    ref.set(data)
    return {**data, "id": ref.id}


def list_for_trip(uid: str, trip_id: str) -> list[dict[str, Any]]:
    trips_repo.get(uid, trip_id)
    docs = [snap_to_dict(s) for s in _col().where(filter=FieldFilter("owner_uid", "==", uid)).stream()]
    docs = [d for d in docs if d.get("trip_id") == trip_id]
    docs.sort(key=lambda d: d["created_at"])
    return docs


def get(uid: str, feedback_id: str) -> dict[str, Any]:
    return get_owned(_col().document(feedback_id), uid, "피드백")


def update(uid: str, feedback_id: str, body: FeedbackUpdate) -> dict[str, Any]:
    current = get(uid, feedback_id)
    changes = body.model_dump(exclude_unset=True)
    if "visits" in changes:
        visits = body.visits or []
        _check_visits(uid, current["trip_id"], current.get("version_id"), visits)
        changes["visits"] = [v.model_dump() for v in visits]
    if "overall_text" in changes and changes["overall_text"] is not None:
        changes["overall_text"] = changes["overall_text"].strip() or None
    merged = {**current, **changes}
    if not merged.get("overall_text") and not merged.get("visits") and merged.get("overall_rating") is None:
        raise AppError(422, "VALIDATION_ERROR", "피드백 내용을 하나 이상 입력하세요.")
    if not changes:
        return current
    changes["updated_at"] = utcnow()
    _col().document(feedback_id).update(changes)
    return {**current, **changes}


def delete(uid: str, feedback_id: str) -> None:
    get(uid, feedback_id)
    _col().document(feedback_id).delete()
