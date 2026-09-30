"""소유자 검사 헬퍼. 모든 문서 접근은 이 함수들을 거쳐 owner_uid를 확인한다."""
from typing import Any

from google.cloud.firestore import DocumentReference, DocumentSnapshot

from app.core.errors import not_found


def snap_to_dict(snap: DocumentSnapshot) -> dict[str, Any]:
    data = snap.to_dict() or {}
    data["id"] = snap.id
    return data


def get_owned_snapshot(ref: DocumentReference, uid: str, what: str = "리소스", transaction=None) -> DocumentSnapshot:
    snap = ref.get(transaction=transaction) if transaction is not None else ref.get()
    if not snap.exists or (snap.to_dict() or {}).get("owner_uid") != uid:
        raise not_found(what)
    return snap


def get_owned(ref: DocumentReference, uid: str, what: str = "리소스") -> dict[str, Any]:
    return snap_to_dict(get_owned_snapshot(ref, uid, what))


def delete_query_in_batches(db, query, batch_size: int = 300) -> int:
    """쿼리 결과 문서를 배치로 삭제하고 삭제 개수를 반환한다."""
    deleted = 0
    while True:
        docs = list(query.limit(batch_size).stream())
        if not docs:
            return deleted
        batch = db.batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
        deleted += len(docs)
