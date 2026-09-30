from typing import Any, Optional

from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore import FieldFilter

from app.core.errors import not_found
from app.core.firebase import get_db
from app.repositories.base import get_owned, snap_to_dict
from app.schemas.common import utcnow
from app.schemas.preferences import PreferenceCreate, PreferenceUpdate

COLLECTION = "preferences"


def _col():
    return get_db().collection(COLLECTION)


def ref(pref_id: str):
    return _col().document(pref_id)


def create(uid: str, body: PreferenceCreate, doc_id: Optional[str] = None, source_type: Optional[str] = None,
           evidence_text: Optional[str] = None) -> dict[str, Any]:
    """doc_id를 주면 그 ID로 한 번만 만든다(이미 있으면 기존 기억을 돌려준다: 재시도 중복 방지)."""
    now = utcnow()
    source = {"type": source_type or body.source_type, "trip_id": body.trip_id if body.scope == "trip" else None,
              "feedback_id": None, "proposal_id": None, "evidence_text": evidence_text, "trip_deleted": False,
              "trip_destination": None}
    data = {
        "owner_uid": uid,
        "scope": body.scope,
        "trip_id": body.trip_id if body.scope == "trip" else None,
        "strength": body.strength,
        "subject": body.subject,
        "category": body.category,
        "value": body.value,
        "status": "active",
        "sources": [source],
        "sensitive": body.sensitive,
        "share_with_ai": bool(body.share_with_ai),
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    if doc_id is None:
        ref = _col().document()
        ref.set(data)
        return {**data, "id": ref.id}
    try:
        _col().document(doc_id).create(data)
    except AlreadyExists:
        return get(uid, doc_id)
    return {**data, "id": doc_id}


def list_for_owner(uid: str, status: Optional[str] = None, scope: Optional[str] = None,
                   trip_id: Optional[str] = None, include_deleted: bool = False) -> list[dict[str, Any]]:
    # owner_uid 동등 조건만 쿼리하고 나머지는 메모리에서 거른다(사용자당 문서 수가 작아 복합 인덱스 불필요).
    docs = [snap_to_dict(s) for s in _col().where(filter=FieldFilter("owner_uid", "==", uid)).stream()]
    result = []
    for d in docs:
        if not include_deleted and d.get("status") == "deleted":
            continue
        if status and d.get("status") != status:
            continue
        if scope and d.get("scope") != scope:
            continue
        if trip_id and d.get("trip_id") != trip_id:
            continue
        result.append(d)
    result.sort(key=lambda d: d["updated_at"], reverse=True)
    return result


def get(uid: str, pref_id: str) -> dict[str, Any]:
    data = get_owned(_col().document(pref_id), uid, "기억")
    if data.get("status") == "deleted":
        raise not_found("기억")
    return data


def update(uid: str, pref_id: str, body: PreferenceUpdate) -> dict[str, Any]:
    current = get(uid, pref_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if changes.get("sensitive") is True and "share_with_ai" not in changes and not current["sensitive"]:
        # 새로 민감 항목으로 지정하면 외부 AI 전송은 명시적으로 다시 동의받는다.
        changes["share_with_ai"] = False
    if not changes:
        return current
    changes["updated_at"] = utcnow()
    _col().document(pref_id).update(changes)
    return {**current, **changes}


def soft_delete(uid: str, pref_id: str) -> None:
    get(uid, pref_id)
    now = utcnow()
    _col().document(pref_id).update({"status": "deleted", "deleted_at": now, "updated_at": now})
