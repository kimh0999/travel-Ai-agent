from typing import Any, Optional

from google.cloud.firestore import FieldFilter

from app.core.firebase import get_db
from app.repositories.base import get_owned, snap_to_dict

COLLECTION = "memory_proposals"


def col():
    return get_db().collection(COLLECTION)


def list_for_owner(uid: str, status: Optional[str] = None, trip_id: Optional[str] = None) -> list[dict[str, Any]]:
    docs = [snap_to_dict(s) for s in col().where(filter=FieldFilter("owner_uid", "==", uid)).stream()]
    docs = [d for d in docs if (not status or d.get("status") == status) and (not trip_id or d.get("trip_id") == trip_id)]
    docs.sort(key=lambda d: d["created_at"])
    return docs


def get(uid: str, proposal_id: str) -> dict[str, Any]:
    return get_owned(col().document(proposal_id), uid, "변경안")


def delete_pending(uid: str, trip_id: str, feedback_id: Optional[str] = None) -> int:
    """아직 결정하지 않은 변경안만 지운다. 승인·거절 기록은 남긴다."""
    batch = get_db().batch()
    count = 0
    for d in list_for_owner(uid, status="pending", trip_id=trip_id):
        if feedback_id and d.get("feedback_id") != feedback_id:
            continue
        batch.delete(col().document(d["id"]))
        count += 1
    if count:
        batch.commit()
    return count
