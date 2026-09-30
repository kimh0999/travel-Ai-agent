"""대화 턴(chat_turns): 한 번의 사용자 요청과 그 실행 상태.

- 문서 ID는 (uid, 클라이언트 요청 ID)에서 결정적으로 만든다 → 같은 요청을 다시 보내도 새로 실행하지 않는다.
- transcript(모델 메시지·도구 결과)를 단계마다 저장해 중단 후 이어서 실행한다.
- tool_runs 하위 컬렉션: 부작용이 있는 도구의 실행 결과 기록(같은 호출이면 다시 실행하지 않음).
"""
import hashlib
from typing import Any, Optional

from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore import FieldFilter

from app.core.firebase import get_db
from app.repositories.base import delete_query_in_batches, get_owned, snap_to_dict
from app.schemas.common import utcnow

COLLECTION = "chat_turns"


def col():
    return get_db().collection(COLLECTION)


def turn_id_for(uid: str, client_turn_id: str) -> str:
    return "t" + hashlib.sha256(f"{uid}:{client_turn_id}".encode()).hexdigest()[:31]


def get(uid: str, turn_id: str) -> dict[str, Any]:
    return get_owned(col().document(turn_id), uid, "요청")


def create(turn_id: str, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """(턴, 새로 만들었는지). 이미 있으면 기존 턴을 돌려준다."""
    try:
        col().document(turn_id).create(data)
        return {**data, "id": turn_id}, True
    except AlreadyExists:
        return get(data["owner_uid"], turn_id), False


def update(turn_id: str, changes: dict[str, Any]) -> None:
    col().document(turn_id).update({**changes, "updated_at": utcnow()})


def list_for_conversation(uid: str, conversation_id: str) -> list[dict[str, Any]]:
    docs = [snap_to_dict(s) for s in col().where(filter=FieldFilter("owner_uid", "==", uid)).stream()]
    docs = [d for d in docs if d.get("conversation_id") == conversation_id]
    docs.sort(key=lambda d: d["created_at"])
    return docs


def get_tool_run(turn_id: str, key: str) -> Optional[dict[str, Any]]:
    snap = col().document(turn_id).collection("tool_runs").document(key).get()
    return snap.to_dict() if snap.exists else None


def save_tool_run(turn_id: str, key: str, data: dict[str, Any]) -> None:
    col().document(turn_id).collection("tool_runs").document(key).set({**data, "created_at": utcnow()})


def _delete(turn_id: str) -> None:
    ref = col().document(turn_id)
    delete_query_in_batches(get_db(), ref.collection("tool_runs"))
    ref.delete()


def delete_for_conversation(uid: str, conversation_id: str) -> int:
    turns = list_for_conversation(uid, conversation_id)
    for t in turns:
        _delete(t["id"])
    return len(turns)


def delete_mentioning(uid: str, trip_id: str) -> int:
    """삭제한 여행의 데이터가 담긴 턴 기록(실행 기록·도구 결과)을 지운다."""
    count = 0
    for snap in col().where(filter=FieldFilter("owner_uid", "==", uid)).stream():
        d = snap.to_dict() or {}
        if trip_id in (d.get("transcript") or "") or trip_id in str(d.get("cards") or "") or d.get("trip_id") == trip_id:
            _delete(snap.id)
            count += 1
    return count
